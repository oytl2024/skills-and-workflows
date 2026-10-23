from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from wqb.lockfile import json_lock_transition_guard


CONTROL_ENV = "BRAIN_WORKFLOW_CONTROL_PATH"
DEADLINE_ENV = 'BRAIN_WORKFLOW_RUNTIME_DEADLINE'
DAILY_RECONCILE_ENV = 'BRAIN_WORKFLOW_DAILY_RECONCILE_ONLY'
DEFAULT_MAX_SIMULATIONS = 150
DEFAULT_MAX_RUNTIME_SECONDS = 21600
DEFAULT_MAX_RECOVERIES = 3
SUBMISSION_GATE_TIMEOUT_SECONDS = 180.0
SUBMISSION_GATE_SLEEP_SECONDS = 0.02
HEARTBEAT_INTERVAL_SECONDS = 5.0
RUNTIME_RENEWAL_SECONDS = (21600, 43200)


class RuntimePaused(RuntimeError):
    """A cooperative stop before a new request; submitted identities remain recoverable."""


class RuntimeBudgetExhausted(RuntimePaused):
    """Input: runtime expiry. Output: exception. Stop model/request work without renewing authority."""


class DailyBudgetExhausted(RuntimePaused):
    """A recoverable calendar-day wait, not renewal authority or a code fault."""

    def __init__(self, budget: dict):
        """Input: validated daily budget dict. Output: exception. Carry the shared balance and reset time."""
        super().__init__('daily simulation allowance exhausted')
        self.budget = budget


def utc_now() -> str:
    """Input: none. Output: UTC str. Timestamp durable runtime records."""
    return datetime.now(timezone.utc).isoformat()


def runtime_control_path(run_dir: str | Path) -> Path:
    """Input: run directory str/Path. Output: Path. Locate user-owned run intent."""
    return Path(run_dir) / "runtime_control.json"


def _read(path: Path) -> dict[str, Any]:
    """Input: JSON Path. Output: dict. Preserve invalid-state evidence and fail closed."""
    if not path.exists():
        return {}
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(row, dict):
            return row
    except (OSError, ValueError):
        pass
    return {"invalid": True, "desired_state": "paused", "reason": "invalid runtime state"}


def _write(path: Path, row: dict[str, Any]) -> None:
    """Input: Path and dict. Output: none. Atomically publish JSON without partial reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_runtime_control(run_dir: str | Path) -> dict[str, Any]:
    """Input: run path. Output: dict. Merge worker status with authoritative user intent."""
    request = _read(runtime_control_path(run_dir))
    status = _read(Path(run_dir) / "runtime_status.json")
    heartbeat = _read(Path(run_dir) / 'runtime_heartbeat.json')
    merged = {**status, **({'heartbeat_at': heartbeat['heartbeat_at']} if heartbeat.get('heartbeat_at') else {}), **request}
    if request.get('simulation_budget_mode') == 'daily':
        try:
            from wqb.daily_simulation_budget import read_daily_budget
            budget = read_daily_budget(Path(run_dir))
            merged.update(daily_simulation_budget=budget, simulation_attempts=budget['lifetime_attempts'])
            obsolete = merged.get('reason') == 'research_simulation_budget_exhausted' or (
                merged.get('reason') == 'research_round_budget_exhausted' and 'max_rounds' not in request)
            if merged.get('status') == 'blocked' and obsolete:
                merged.update(status='paused', reason='daily_budget_ready' if budget['remaining'] else 'daily_budget_exhausted')
        except (ValueError, OSError, TypeError) as error:
            merged.update(invalid=True, status='blocked', reason='daily_budget_accounting_invalid',
                          daily_budget_error=str(error))
    renewals = request.get('runtime_renewals') or []
    if (isinstance(renewals, list) and renewals and isinstance(renewals[-1], dict)
            and merged.get('status') == 'blocked' and merged.get('reason') == 'runtime_budget_exhausted'):
        receipt = renewals[-1]
        if (type(receipt.get('previous_limit_seconds')) is int
                and type(request.get('max_runtime_seconds')) is int
                and receipt.get('new_limit_seconds') == request.get('max_runtime_seconds')
                and receipt.get('previous_limit_seconds', float('inf')) <= float(status.get('elapsed_seconds', 0))
                < request.get('max_runtime_seconds', 0)):
            merged.update(status='paused', reason='runtime_renewed')
    return merged


def renew_runtime_budget(run_dir: str | Path, additional_seconds: int, expected_revision: str) -> dict[str, Any]:
    """Input: run path, added seconds int, revision str. Output: control dict. Atomically audit explicit renewal without resetting usage or intent."""
    if type(additional_seconds) is not int or additional_seconds not in RUNTIME_RENEWAL_SECONDS:
        raise ValueError('select a supported runtime extension: 6 or 12 hours')
    if not expected_revision:
        raise ValueError('runtime revision required')
    run = Path(run_dir)
    from wqb.recovery_cases import read_current_recovery_case, MAINTENANCE_BLOCKING_STATUSES
    with json_lock_transition_guard(run / 'runtime' / 'control_intent',
                                   SUBMISSION_GATE_TIMEOUT_SECONDS, SUBMISSION_GATE_SLEEP_SECONDS,
                                   'runtime control intent busy'):
        previous = _read(runtime_control_path(run))
        if read_current_recovery_case(run).get('status') in MAINTENANCE_BLOCKING_STATUSES:
            raise ValueError('maintenance confirmation and verification required before renewal')
        receipts = previous.get('runtime_renewals') or []
        if not isinstance(receipts, list) or any(not isinstance(item, dict) for item in receipts):
            raise ValueError('invalid renewal history; maintenance required')
        for receipt in receipts:
            if receipt.get('expected_revision') == expected_revision:
                if (receipt.get('additional_seconds') != additional_seconds
                        or previous.get('request_revision') != receipt.get('request_revision')):
                    raise ValueError('stale renewal; a newer action exists')
                return read_runtime_control(run)
        if (not runtime_authority_is_complete(previous) or previous.get('original_batch_scope_id')
                or previous.get('request_revision') != expected_revision):
            raise ValueError('stale or restricted runtime authority; renewal refused')
        status = _read(run / 'runtime_status.json')
        elapsed = float(status.get('elapsed_seconds', 0))
        old_limit = previous['max_runtime_seconds']
        if (status.get('status') != 'blocked' or status.get('reason') != 'runtime_budget_exhausted'
                or not old_limit <= elapsed < old_limit + additional_seconds):
            raise ValueError('runtime is not eligible for this extension')
        revision = uuid4().hex
        receipt = {'expected_revision': expected_revision, 'request_revision': revision,
                   'additional_seconds': additional_seconds, 'previous_limit_seconds': old_limit,
                   'new_limit_seconds': old_limit + additional_seconds, 'authorized_at': utc_now(),
                   'authority': 'explicit_human_runtime_renewal'}
        _write(runtime_control_path(run), {**previous, 'max_runtime_seconds': old_limit + additional_seconds,
                                         'request_revision': revision, 'requested_at': receipt['authorized_at'],
                                         'runtime_renewals': [*receipts, receipt]})
        return read_runtime_control(run)


def start_runtime_heartbeat(run_dir: Path, interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS):
    """Input: run Path, interval float. Output: (Event, Thread). Keep local liveness separate from intent/status."""
    from threading import Event, Thread
    stop = Event()
    path = Path(run_dir) / 'runtime_heartbeat.json'
    def pulse():
        """Input: closed-over run/Event. Output: None. Publish liveness without API/model calls."""
        while not stop.is_set():
            try:
                _write(path, {'heartbeat_at': utc_now()})
            except OSError:
                pass
            stop.wait(max(.01, interval_seconds))
    worker = Thread(target=pulse, name='workflow-local-heartbeat', daemon=True)
    worker.start()
    return stop, worker


def runtime_authority_is_complete(control: dict[str, Any]) -> bool:
    """Input: persisted intent dict. Output: bool. Reject partial or legacy intent as live authority."""
    mode = control.get('simulation_budget_mode')
    if mode not in (None, 'daily') or mode == 'daily' and not all(
            isinstance(control.get(key), str) and control[key] for key in ('daily_budget_policy_id', 'daily_budget_activation_id')):
        return False
    return (not control.get('invalid') and not control.get('legacy_authority_required')
            and control.get('desired_state') in {'running', 'paused'}
            and isinstance(control.get('enable_live_api'), bool)
            and isinstance(control.get('request_revision'), str) and bool(control['request_revision'])
            and all(type(control.get(key)) is int and control[key] > 0 for key in
                    ('max_simulations', 'max_runtime_seconds', 'max_recoveries')))


def has_runtime_authority(run_dir: str | Path) -> bool:
    """Input: run directory. Output: bool. Validate intent separately from worker-owned status."""
    intent = _read(runtime_control_path(run_dir))
    if not runtime_authority_is_complete(intent):
        return False
    if intent.get('simulation_budget_mode') == 'daily':
        from wqb.daily_simulation_budget import read_daily_budget
        try:
            read_daily_budget(Path(run_dir))
        except (ValueError, OSError, TypeError):
            return False
    if intent.get('original_batch_scope_id'):
        from wqb.original_batch_recovery import read_original_batch
        try:
            scope = read_original_batch(Path(run_dir))
            return (bool(scope) and scope['scope_id'] == intent['original_batch_scope_id']
                    and intent['max_simulations'] <= len(scope['allowed_expressions']) * (scope['max_recoveries'] + 1)
                    and intent['max_recoveries'] <= scope['max_recoveries']
                    and intent['max_runtime_seconds'] <= scope['max_runtime_seconds'])
        except RuntimePaused:
            return False
    return True


@contextmanager
def submission_request_gate(run_dir: str | Path, *, fair: bool = False):
    """Input: run directory/actual POST bool. Output: OS fence; control writes bypass fair admission."""
    from wqb.research_group import group_submission_gate
    with group_submission_gate(Path(run_dir), fair=fair):
        with json_lock_transition_guard(
            Path(run_dir) / "runtime" / "submission_post",
            SUBMISSION_GATE_TIMEOUT_SECONDS, SUBMISSION_GATE_SLEEP_SECONDS,
            "simulation submission gate busy",
        ):
            yield


def request_runtime_state(
    run_dir: str | Path, desired_state: str, *, expected_revision: str | None = None, **options: Any,
) -> dict[str, Any]:
    """Input: run, state str, optional revision/limits. Output: written intent dict. Persist and return this request's receipt."""
    if desired_state not in {"running", "paused"}:
        raise ValueError("desired_state must be running or paused")
    path = runtime_control_path(run_dir)
    with json_lock_transition_guard(
        Path(run_dir) / "runtime" / "control_intent",
        SUBMISSION_GATE_TIMEOUT_SECONDS, SUBMISSION_GATE_SLEEP_SECONDS,
        "runtime control intent busy",
    ):
        previous = _read(path)
        if previous.get("invalid"):
            raise ValueError("invalid runtime control requires recovery")
        if previous.get('original_batch_scope_id'):
            if (desired_state == 'running' and not has_runtime_authority(run_dir)) or any(
                    key in options and options[key] != previous.get(key)
                    for key in ('max_simulations', 'max_recoveries', 'max_runtime_seconds')):
                raise ValueError('original batch scope cannot be expanded by Resume')
        legacy_authority_required = (bool(previous) and not runtime_authority_is_complete(previous)) or (
            not previous and (Path(run_dir) / "stages" / "schedule" / "research_schedule.json").exists()
        )
        if desired_state == "running" and legacy_authority_required:
            raise ValueError("legacy run requires reconciled runtime authority; defaults cannot authorize resume")
        if expected_revision is not None and str(previous.get("request_revision", "")) != expected_revision:
            raise ValueError("stale runtime intent; resume refused because a newer user action exists")
        row = {
            "created_at": utc_now(), "enable_live_api": False,
            "max_simulations": DEFAULT_MAX_SIMULATIONS,
            "max_runtime_seconds": DEFAULT_MAX_RUNTIME_SECONDS,
            "max_recoveries": DEFAULT_MAX_RECOVERIES,
            **previous, "desired_state": desired_state, "requested_at": utc_now(),
            "request_revision": uuid4().hex,
        }
        if legacy_authority_required:
            row["legacy_authority_required"] = True
        for key in ("enable_live_api", "max_simulations", "max_runtime_seconds", "max_recoveries"):
            if key in options:
                value = options[key]
                if key == "enable_live_api":
                    if not isinstance(value, bool):
                        raise ValueError("enable_live_api must be bool")
                elif isinstance(value, bool) or int(value) <= 0:
                    raise ValueError(f"{key} must be positive")
                row[key] = value if key == "enable_live_api" else int(value)
        _write(path, row)
        if desired_state == "paused":
            with submission_request_gate(run_dir):
                pass
        return {**_read(Path(run_dir) / "runtime_status.json"), **row}


def update_runtime_status(run_dir: str | Path, **fields: Any) -> dict[str, Any]:
    """Input: run and worker fields. Output: merged dict. Never overwrite user pause/permission."""
    path = Path(run_dir) / "runtime_status.json"
    row = {**_read(path), **fields, "updated_at": utc_now()}
    _write(path, row)
    return read_runtime_control(run_dir)


def check_submission_allowed(payload_count: int = 0) -> None:
    """Input: new simulation count int. Output: None. Serialize accounting with explicit migration, never with GETs."""
    run = os.environ.get(CONTROL_ENV, '')
    if run and payload_count:
        from wqb.daily_simulation_budget import policy_transition_gate
        with json_lock_transition_guard(Path(run) / 'runtime/submission_accounting',
                SUBMISSION_GATE_TIMEOUT_SECONDS, SUBMISSION_GATE_SLEEP_SECONDS, 'submission accounting busy'):
            with policy_transition_gate(Path(run).parent):
                return _check_submission_allowed(payload_count)
    return _check_submission_allowed(payload_count)


def _check_submission_allowed(payload_count: int = 0) -> None:
    """Input: new simulation count int. Output: none or RuntimePaused. Enforce persisted pause and budget."""
    run_dir = os.environ.get(CONTROL_ENV, "")
    if not run_dir:
        return
    from wqb.research_group import require_group_running
    require_group_running(Path(run_dir))
    if type(payload_count) is not int or payload_count < 0:
        raise ValueError('simulation payload count must be a nonnegative integer')
    control = read_runtime_control(run_dir)
    if not has_runtime_authority(run_dir):
        raise RuntimePaused("runtime authority required; partial or legacy intent cannot authorize submission")
    if control.get("invalid") or control.get("desired_state") != "running":
        raise RuntimePaused("workflow paused; planned work is preserved")
    if os.environ.get(DEADLINE_ENV) and time.monotonic() >= float(os.environ[DEADLINE_ENV]):
        raise RuntimeBudgetExhausted('runtime_budget_exhausted')
    if not control.get("enable_live_api"):
        raise RuntimePaused("live API permission required")
    if payload_count and os.environ.get(DAILY_RECONCILE_ENV) == '1':
        from wqb.daily_simulation_budget import read_daily_budget
        raise DailyBudgetExhausted({**read_daily_budget(Path(run_dir)), 'required_count': payload_count})
    used = int(control.get("simulation_attempts", 0))
    limit = int(control.get("max_simulations", DEFAULT_MAX_SIMULATIONS))
    if control.get('simulation_budget_mode') != 'daily' and used + payload_count > limit:
        raise RuntimePaused("simulation attempt budget exhausted")
    if payload_count:
        from wqb.daily_simulation_budget import (has_shared_policy, charge_daily_budget,
            read_daily_budget, reconcile_lifetime_attempts, DailyBudgetUnavailable)
        if has_shared_policy(Path(run_dir)):
            budget = read_daily_budget(Path(run_dir))
            try:
                charge_daily_budget(Path(run_dir), payload_count)
            except DailyBudgetUnavailable as error:
                raise DailyBudgetExhausted(error.budget) from error
            reconcile_lifetime_attempts(Path(run_dir))
        else:
            update_runtime_status(run_dir, simulation_attempts=used + payload_count)


def cooperative_sleep(seconds: float) -> None:
    """Input: seconds float. Output: none or RuntimePaused. Wake promptly when a managed run pauses."""
    import time
    if not os.environ.get(CONTROL_ENV):
        time.sleep(seconds)
        return
    remaining = max(0.0, seconds)
    while remaining:
        check_submission_allowed()
        part = min(1.0, remaining)
        time.sleep(part)
        remaining -= part
