from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import requests

from wqb.recorder import RunRecorder
from wqb.rate_limit_state import cooldown_is_active, read_rate_limit_state, record_rate_limit, reset_rate_limit, check_source_retry_authorization, RateLimitRecoveryRequired


SUPPORTED_ACTIONS = ("reduce_turnover", "increase_decay", "decrease_decay",
                     "change_neutralization", "adjust_truncation", "flip_direction")
NEUTRALIZATIONS = ("SUBINDUSTRY", "INDUSTRY", "SECTOR", "MARKET")
REPAIR_PROGRESS_RETRY_SECONDS = 60
REPAIR_PROGRESS_WAIT_FILE = 'progress_wait.json'
REPAIR_CHECK_MAX_ATTEMPTS = 3


def _checks_need_recovery(row: dict) -> bool:
    """Input: checked row dict. Output: bool. Keep baseline-pending or otherwise unqualified checks resumable."""
    from wqb.checker import SUBMISSION_ONLY_CHECKS
    pending = row.get('pending', [])
    names = [item.get('name') if isinstance(item, dict) else item for item in pending]
    return bool(names) and (not row.get('failed') or any(name not in SUBMISSION_ONLY_CHECKS for name in names))


class RepairRecoveryPending(RuntimeError):
    """Input: recovery explanation. Output: exception. Mark a known progress URL as safe to resume."""


class RepairResultUnknown(RepairRecoveryPending):
    def __init__(self, source_run_dir: str) -> None:
        """Input: bound source str. Output: typed exception. Isolate a submitted poll404, never replay POST."""
        super().__init__('Submitted repair result unavailable; no automatic resubmission')
        self.source_run_dir = source_run_dir


class RepairRateLimited(RepairRecoveryPending):
    def __init__(self, retry_at: str, source_run_dir: str) -> None:
        """Input: retry timestamp and source path. Output: exception. Carry bounded cooldown evidence."""
        super().__init__(f"repair rate limited until {retry_at}")
        self.retry_at = retry_at
        self.source_run_dir = source_run_dir


class RepairProgressPending(RepairRecoveryPending):
    def __init__(self, next_poll_at: str, source_run_dir: str, phase: str = 'poll') -> None:
        """Input: ISO wake str, source directory str, phase str. Output: exception. Preserve scheduled GET recovery, not a429."""
        super().__init__(f"existing repair {phase} recovery waits until {next_poll_at}; no simulation resubmission")
        self.next_poll_at = next_poll_at
        self.source_run_dir = source_run_dir


def _record_progress_wait(subrun: Path, variant: dict, exc: Exception, phase: str) -> RepairProgressPending:
    """Input: source Path, identity dict, exception, phase str. Output: wait exception. Persist sanitized bounded GET recovery evidence."""
    from wqb.runtime_control import _write
    response = getattr(exc, 'response', None)
    retry_after = response.headers.get('Retry-After') if response is not None else None
    try:
        delay = max(REPAIR_PROGRESS_RETRY_SECONDS, float(retry_after or 0))
    except (ValueError, TypeError):
        delay = REPAIR_PROGRESS_RETRY_SECONDS
    wake = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    evidence = {'expression_hash': variant['expression_hash'], 'next_poll_at': wake,
                'phase': phase, 'error_type': type(exc).__name__,
                'http_status': response.status_code if response is not None else None}
    _write(subrun / REPAIR_PROGRESS_WAIT_FILE, evidence)
    RunRecorder(subrun).append_jsonl('simulation_events.jsonl', {'event': 'PROGRESS_WAIT', **evidence})
    return RepairProgressPending(wake, str(subrun), phase)


def _classify_get_failure(subrun: Path, variant: dict, exc: Exception, phase: str) -> RepairRecoveryPending:
    """Input: source Path, identity dict, GET/auth exception and phase str. Output: recoverable exception, or raise terminal error."""
    if isinstance(exc, requests.exceptions.JSONDecodeError):
        raise RuntimeError(f'repair {phase} invalid JSON payload; preserve submitted identity') from exc
    response = getattr(exc, 'response', None)
    status = response.status_code if response is not None else None
    if status == 429:
        state = record_rate_limit(subrun, 'repair_' + phase, exc, variant, datetime.now(timezone.utc).isoformat())
        return RepairRateLimited(str(state['retry_at']), str(subrun))
    if status == 404 and phase == 'poll':
        from wqb.repair_unknown import record_unknown
        record_unknown(subrun, variant['parent_alpha_id'], variant['parent_expression_hash'])
        return RepairResultUnknown(str(subrun))
    if status is not None and 400 <= status < 500:
        raise RuntimeError(f'repair {phase} terminal HTTP {status}; preserve submitted identity') from exc
    if not isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)) and status not in {500, 502, 503, 504}:
        raise RuntimeError(f'repair {phase} non-transient {type(exc).__name__}; preserve submitted identity') from exc
    return _record_progress_wait(subrun, variant, exc, phase)


def _digest(value: Any) -> str:
    """Input: JSON-serializable value. Output: SHA256 hex string. Identify an immutable repair plan."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def recover_parent_settings(root: Path, parent: dict[str, Any], client) -> dict[str, Any]:
    """Input: run Path, checked parent dict, authenticated bounded client. Output: copy with verified platform settings."""
    identity = {key: parent.get(key) for key in ("alpha_id", "expression", "expression_hash")}
    if not all(isinstance(value, str) and value for value in identity.values()):
        raise ValueError("parent settings recovery requires checked identity and expression")
    if not identity["alpha_id"].isalnum():
        raise ValueError("invalid platform alpha identity")
    path = root / "runtime" / "parent_settings" / (_digest(identity) + ".json")
    if path.exists():
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if evidence.get("identity") != identity:
            raise ValueError("parent settings evidence identity changed")
    else:
        if client is None:
            raise FileNotFoundError("verified parent settings cache unavailable")
        remote = client.get_json("/alphas/" + identity["alpha_id"])
        if remote.get("id") != identity["alpha_id"] or (remote.get("regular") or {}).get("code") != identity["expression"]:
            raise ValueError("platform parent identity or expression mismatch")
        evidence = {"identity": identity, "settings": remote.get("settings"),
                    "endpoint": "/alphas/" + identity["alpha_id"],
                    "captured_at": datetime.now(timezone.utc).isoformat()}
        if not isinstance(evidence["settings"], dict) or not evidence["settings"]:
            raise ValueError("platform parent settings missing")
        from wqb.runtime_control import _write
        _write(path, evidence)
    if not isinstance(evidence.get("settings"), dict) or not evidence["settings"]:
        raise ValueError("invalid cached parent settings")
    return {**parent, "settings": evidence["settings"], "settings_source": str(path)}


def _planned_variants(parent: dict[str, Any], actions: list[dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
    """Input: checked parent, optimizer actions and cap. Output: local bounded simulation variants."""
    expression = parent.get("expression")
    settings = parent.get("settings")
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("repair parent expression is required")
    if not isinstance(settings, dict) or not settings:
        raise ValueError("repair parent settings are required")
    if type(maximum) is not int or maximum < 1 or maximum > 8:
        raise ValueError("repair budget must be 1..8")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in actions:
        kind = action.get("action_type", "")
        if kind not in SUPPORTED_ACTIONS:
            continue
        next_settings = dict(settings)
        next_expression = expression
        if kind in {"reduce_turnover", "increase_decay"}:
            next_settings["decay"] = min(32, max(2, int(settings.get("decay", 0)) * 2))
        elif kind == "decrease_decay":
            next_settings["decay"] = max(0, int(settings.get("decay", 0)) // 2)
        elif kind == "change_neutralization":
            old = str(settings.get("neutralization", "SUBINDUSTRY"))
            next_settings["neutralization"] = NEUTRALIZATIONS[(NEUTRALIZATIONS.index(old) + 1) % len(NEUTRALIZATIONS)] if old in NEUTRALIZATIONS else "INDUSTRY"
        elif kind == "adjust_truncation":
            next_settings["truncation"] = min(0.15, round(float(settings.get("truncation", 0.08)) + 0.02, 3))
        elif kind == "flip_direction":
            next_expression = f"-({expression})"
        identity = _digest([next_expression, next_settings])
        if identity == _digest([expression, settings]) or identity in seen:
            continue
        seen.add(identity)
        rows.append({"expression": next_expression, "settings": next_settings, "expression_hash": identity,
                     "parent_alpha_id": parent["alpha_id"], "parent_expression_hash": parent["expression_hash"],
                     "repair_action": kind})
        if len(rows) >= maximum:
            break
    if not rows:
        raise ValueError("no supported, non-duplicate repair action for parent")
    return rows


class RepairRuntimeExecutor:
    supports_durable_recovery = True
    supports_ai_planning = True

    def __init__(self, config: dict[str, Any], *, enable_live_api: bool = False) -> None:
        """Input: config and live authorization. Output: executor. Hold scoped repair settings."""
        self.config = dict(config)
        self.enable_live_api = enable_live_api

    def prepare(self, root: Path, parent: dict, history: list[dict], allowance: int) -> dict:
        """Input: run/parent/history/allowance. Output: AI plan. Recover exact local settings before judgment."""
        from wqb.repair_planning import prepare_repair_decision
        if not parent.get('settings'):
            try:
                parent = recover_parent_settings(root, parent, None)
            except FileNotFoundError:
                if not self.enable_live_api or not self.config.get('allow_parent_settings_recovery'):
                    raise
                from wqb import cli
                from wqb.runtime_control import check_submission_allowed
                check_submission_allowed()
                subrun = root / 'stages/repair/parents' / (parent['alpha_id'] + '-' + parent['expression_hash'][:12])
                try:
                    check_source_retry_authorization(subrun)
                except RateLimitRecoveryRequired as exc:
                    raise RepairRateLimited(exc.retry_at, exc.source_run_dir) from exc
                cli.require_readiness_gate(
                    knowledge_root=self.config.get('knowledge_root', cli.default_knowledge_root()),
                    output_dir=subrun, mode='research', batch_size=30, live_api_enabled=True,
                    region=self.config.get('region', 'USA'), universe=self.config.get('universe', 'TOP3000'),
                    delay=int(self.config.get('delay', 1)))
                try:
                    client = cli.build_client({**self.config, 'max_retries': 0, 'request_timeout_seconds': 20})
                    client.authenticate()
                    parent = recover_parent_settings(root, parent, client)
                except requests.exceptions.RequestException as exc:
                    raise _classify_get_failure(subrun, {'expression_hash': parent['expression_hash']}, exc, 'parent_settings') from exc
        return prepare_repair_decision(root, parent, history, allowance, self.config,
                                       datetime.now(timezone.utc).isoformat())

    def __call__(self, root: Path, parent: dict[str, Any], actions: list[dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
        """Input: run, checked parent, actions, cap. Output: checked child rows. Recover by durable submit identity."""
        if not self.enable_live_api:
            raise ValueError("live repair API permission is required")
        subrun = Path(root) / "stages" / "repair" / "parents" / (str(parent["alpha_id"]) + "-" + str(parent["expression_hash"])[:12])
        original_ai_plan = actions[0].get('ai_plan') if len(actions) == 1 else None
        unknown_source = subrun if original_ai_plan is None else subrun / 'iterations' / str(original_ai_plan.get('evidence_digest', ''))
        if (unknown_source / 'result_unknown.json').exists():
            from wqb.runtime_control import check_submission_allowed
            from wqb.repair_unknown import quarantine_source
            check_submission_allowed()
            if original_ai_plan is not None:
                from wqb.repair_planning import verify_consumed_plan
                verify_consumed_plan(Path(root), original_ai_plan)
            bound = {'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash'],
                'phase': 'result_unknown', 'source_run_dir': str(unknown_source), 'max_simulations': maximum,
                'legacy': original_ai_plan is None, 'plan': original_ai_plan}
            if quarantine_source(Path(root), bound) is None:
                raise ValueError('Repair result-unknown source changed')
            raise RepairResultUnknown(str(unknown_source))
        now = datetime.now(timezone.utc).isoformat()
        rate_state = read_rate_limit_state(subrun / "rate_limit_state.json")
        if cooldown_is_active(rate_state, now):
            raise RepairRateLimited(str(rate_state["retry_at"]), str(subrun))
        if not parent.get("settings") and self.config.get("allow_parent_settings_recovery") is True:
            from wqb import cli
            from wqb.runtime_control import check_submission_allowed
            check_submission_allowed()
            cli.require_readiness_gate(
                knowledge_root=self.config.get("knowledge_root", cli.default_knowledge_root()),
                output_dir=root, mode="research", batch_size=30, live_api_enabled=True,
                region=self.config.get("region", "USA"), universe=self.config.get("universe", "TOP3000"),
                delay=int(self.config.get("delay", 1)))
            try:
                parent = recover_parent_settings(Path(root), parent, None)
            except FileNotFoundError:
                try:
                    check_source_retry_authorization(subrun)
                except RateLimitRecoveryRequired as exc:
                    raise RepairRateLimited(exc.retry_at, exc.source_run_dir) from exc
                try:
                    recovery_client = cli.build_client({**self.config, "max_retries": 0, "request_timeout_seconds": 20})
                    recovery_client.authenticate()
                    parent = recover_parent_settings(Path(root), parent, recovery_client)
                except requests.exceptions.RequestException as exc:
                    response = getattr(exc, "response", None)
                    if getattr(response, "status_code", 0) == 429:
                        state = record_rate_limit(subrun, "repair_parent_settings", exc, {}, now)
                        raise RepairRateLimited(str(state["retry_at"]), str(subrun)) from exc
                    raise RepairRecoveryPending("parent settings recovery can safely retry; no simulation submitted") from exc
        ai_plan = actions[0].get('ai_plan') if len(actions) == 1 else None
        if ai_plan is not None:
            from wqb.repair_planning import verify_consumed_plan
            verify_consumed_plan(Path(root), ai_plan)
            if ai_plan.get('status') not in {'validated', 'consumed'} or len(ai_plan.get('variants', [])) != 1:
                raise ValueError('Repair AI plan is not validated')
            variants = ai_plan['variants']
            if any(row.get('parent_alpha_id') != parent['alpha_id'] or
                   row.get('parent_expression_hash') != parent['expression_hash'] for row in variants):
                raise ValueError('Repair AI plan parent mismatch')
            subrun = subrun / 'iterations' / str(ai_plan['evidence_digest'])
        else:
            variants = _planned_variants(parent, actions, maximum)
        from wqb import cli

        recorder = RunRecorder(subrun)
        plan_file = subrun / "repair_plan.json"
        plan = {"parent_alpha_id": parent["alpha_id"], "parent_expression_hash": parent["expression_hash"],
                "maximum": maximum, "variants": variants}
        if plan_file.exists():
            if json.loads(plan_file.read_text(encoding="utf-8")) != plan:
                raise ValueError("persistent repair plan differs from current parent, actions or budget")
        else:
            plan_file.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
            for variant in variants:
                recorder.append_jsonl("planned_candidates.jsonl", variant)
        if ai_plan is not None:
            from wqb.runtime_control import _write
            receipt_path = Path(ai_plan['receipt_path'])
            if not receipt_path.resolve().is_relative_to((Path(root) / 'runtime/repair_decisions').resolve()):
                raise ValueError('Repair AI receipt outside bound run')
            saved = json.loads(receipt_path.read_text(encoding='utf-8'))
            if {k: v for k, v in saved.items() if k != 'status'} != {k: v for k, v in ai_plan.items() if k != 'status'}:
                raise ValueError('Repair AI receipt changed before consumption')
            if saved['status'] != 'consumed':
                saved['status'] = 'consumed'
                _write(receipt_path, saved)
                ai_plan['status'] = 'consumed'
        now = datetime.now(timezone.utc).isoformat()
        rate_state = read_rate_limit_state(subrun / "rate_limit_state.json")
        if cooldown_is_active(rate_state, now):
            raise RepairRateLimited(str(rate_state["retry_at"]), str(subrun))
        cli.require_readiness_gate(
            knowledge_root=self.config.get("knowledge_root", cli.default_knowledge_root()),
            output_dir=subrun, mode="research", batch_size=30, live_api_enabled=True,
            region=str(parent["settings"].get("region", self.config.get("region", "USA"))),
            universe=str(parent["settings"].get("universe", self.config.get("universe", "TOP3000"))),
            delay=int(parent["settings"].get("delay", self.config.get("delay", 1))),
        )
        wait_path = subrun / REPAIR_PROGRESS_WAIT_FILE
        if wait_path.exists():
            wait = json.loads(wait_path.read_text(encoding='utf-8'))
            if wait.get('expression_hash') not in {row['expression_hash'] for row in variants}:
                raise ValueError('repair progress wait identity differs from persistent plan')
            if datetime.now(timezone.utc) < datetime.fromisoformat(wait['next_poll_at']):
                raise RepairProgressPending(wait['next_poll_at'], str(subrun), wait.get('phase', 'poll'))
        if (subrun / 'result_unknown.json').exists():
            from wqb.repair_unknown import record_unknown
            record_unknown(subrun, parent['alpha_id'], parent['expression_hash'])
            raise RepairResultUnknown(str(subrun))
        client = cli.build_client({**self.config, 'max_retries': 0, 'request_timeout_seconds': 20})
        checked = {row.get("expression_hash"): row for row in recorder.read_jsonl("all_alphas.jsonl")
                   if not _checks_need_recovery(row)}
        pending_variant = next((row for row in variants if row['expression_hash'] not in checked), None)
        if pending_variant is None:
            return [checked[row['expression_hash']] for row in variants]
        try:
            check_source_retry_authorization(subrun)
            client.authenticate()
        except RateLimitRecoveryRequired as exc:
            raise RepairRateLimited(exc.retry_at, exc.source_run_dir) from exc
        except requests.exceptions.RequestException as exc:
            raise _classify_get_failure(subrun, pending_variant, exc, 'authentication') from exc
        events = recorder.read_jsonl("simulation_events.jsonl")
        for variant in variants:
            identity = variant["expression_hash"]
            if identity in checked:
                continue
            prior = [event for event in events if event.get("expression_hash") == identity]
            submitted = next((event for event in reversed(prior) if event.get("event") == "SUBMITTED"), None)
            if submitted is None:
                submission_events = [event for event in prior if event.get('event') in {
                    'SUBMIT_INTENT', 'SUBMITTED', 'RATE_LIMITED', 'LOCAL_SUBMISSION_REJECTED'}]
                if submission_events and submission_events[-1].get("event") not in {"RATE_LIMITED", "LOCAL_SUBMISSION_REJECTED"}:
                    raise RuntimeError("repair recovery requires reconciliation of uncertain submission")
                try:
                    check_source_retry_authorization(subrun)
                except RateLimitRecoveryRequired as exc:
                    raise RepairRateLimited(exc.retry_at, exc.source_run_dir) from exc
                recorder.append_jsonl("simulation_events.jsonl", {"event": "SUBMIT_INTENT", **variant})
                from wqb.runtime_control import check_submission_allowed, RuntimePaused
                try:
                    check_submission_allowed()
                    url = cli.submit_simulation(client, cli.simulation_payload(variant["settings"], variant["expression"]))
                except RateLimitRecoveryRequired as exc:
                    recorder.append_jsonl("simulation_events.jsonl", {"event": "LOCAL_SUBMISSION_REJECTED", **variant})
                    raise RepairRateLimited(exc.retry_at, exc.source_run_dir) from exc
                except RuntimePaused:
                    recorder.append_jsonl('simulation_events.jsonl', {'event': 'LOCAL_SUBMISSION_REJECTED', **variant})
                    raise
                except Exception as exc:
                    response = getattr(exc, "response", None)
                    if isinstance(exc, requests.exceptions.HTTPError) and getattr(response, "status_code", 0) == 429:
                        rate_state = record_rate_limit(subrun, "repair_submit", exc, variant, datetime.now(timezone.utc).isoformat())
                        recorder.append_jsonl("simulation_events.jsonl", {"event": "RATE_LIMITED", **variant})
                        raise RepairRateLimited(str(rate_state["retry_at"]), str(subrun)) from exc
                    raise RuntimeError("repair recovery requires reconciliation of uncertain submission") from exc
                reset_rate_limit(subrun, "repair_submission_accepted", datetime.now(timezone.utc).isoformat())
                submitted = {"event": "SUBMITTED", "progress_url": url, **variant}
                recorder.append_jsonl("simulation_events.jsonl", submitted)
                events.append(submitted)
            completed = next((event for event in reversed(prior) if event.get('event') == 'SIMULATION_COMPLETED'), None)
            phase = 'poll'
            try:
                check_source_retry_authorization(subrun)
                if completed is not None:
                    alpha_id = completed['alpha_id']
                else:
                    progress = cli.poll_simulation(client, str(submitted["progress_url"]), max_retry_after_polls=0)
                    alpha_id = cli.extract_alpha_id(progress)
                    recorder.append_jsonl('simulation_events.jsonl', {'event': 'SIMULATION_COMPLETED', 'alpha_id': alpha_id, **variant})
                phase = 'check'
                summary = cli.fetch_check_summary(client, alpha_id)
            except RateLimitRecoveryRequired as exc:
                raise RepairRateLimited(exc.retry_at, exc.source_run_dir) from exc
            except requests.exceptions.RequestException as exc:
                raise _classify_get_failure(subrun, variant, exc, phase) from exc
            reset_rate_limit(subrun, 'repair_checked', datetime.now(timezone.utc).isoformat())
            if wait_path.exists():
                from wqb.runtime_control import _write
                _write(wait_path, {'expression_hash': identity, 'next_poll_at': '1970-01-01T00:00:00+00:00', 'phase': 'completed'})
            row = {**variant, "alpha_id": alpha_id, "status": "CHECKED", "hard_pass": summary.hard_pass,
                   "metrics": summary.metrics, "failed": [item.name for item in summary.failed],
                   "pending": [item.name for item in summary.pending],
                   "warnings": [item.name for item in summary.warnings]}
            if _checks_need_recovery(row):
                from wqb.runtime_control import _read, _write
                check_path = subrun / 'pending_checks' / (_digest([identity, alpha_id]) + '.json')
                prior_check = _read(check_path)
                if not prior_check:
                    legacy_check = _read(subrun / 'pending_checks.json')
                    if legacy_check.get('expression_hash') == identity and legacy_check.get('alpha_id') == alpha_id:
                        prior_check = legacy_check
                if prior_check and prior_check.get('expression_hash') != identity:
                    raise ValueError('pending check identity changed')
                attempts = int(prior_check.get('attempts', 0)) + 1
                _write(check_path, {'expression_hash': identity, 'alpha_id': alpha_id,
                                    'attempts': attempts, 'pending': row['pending']})
                recorder.append_jsonl('simulation_events.jsonl', {'event': 'CHECK_PENDING', 'alpha_id': alpha_id,
                                                                 'expression_hash': identity, 'attempts': attempts})
                if attempts >= REPAIR_CHECK_MAX_ATTEMPTS:
                    raise RepairRecoveryPending('Existing Alpha checks remain pending after bounded recovery; no resubmission')
                raise _record_progress_wait(subrun, variant, RuntimeError('checks_pending'), 'check')
            row.update(cli.benchmark_fields_for_record(row, knowledge_root=self.config.get("knowledge_root", cli.default_knowledge_root()),
                                                       run_dir=subrun, consumer="triage"))
            recorder.append_jsonl("all_alphas.jsonl", row)
            recorder.append_jsonl("simulation_events.jsonl", {"event": "CHECKED", "alpha_id": alpha_id, **variant})
            checked[identity] = row
        return [checked[variant["expression_hash"]] for variant in variants]
