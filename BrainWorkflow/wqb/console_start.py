"""Durable local Start preparation, separate from live workflow execution."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from wqb.lockfile import json_lock_transition_guard
from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
from wqb.runtime_control import read_runtime_control, request_runtime_state
from wqb.start_preflight import prepare_start
from wqb.workflow_state import discover_active_workflow


START_LOCK_TIMEOUT_SECONDS = 5.0
START_LOCK_SLEEP_SECONDS = 0.02
PREPARING_STATUSES = {"preparing", "validating"}
START_CONFIG_FIELDS = (
    'instrument_type', 'region', 'universe', 'delay', 'language', 'neutralization', 'decay',
    'truncation', 'pasteurization', 'unit_handling', 'nan_handling', 'ai_executor',
    'request_timeout_seconds', 'max_retries', 'base_backoff_seconds', 'max_alphas_per_round',
    'max_rounds', 'runtime_max_steps', 'runtime_no_progress_limit', 'max_runtime_seconds',
    'max_recoveries', 'live_api_enabled', 'parallel_workflows', 'plan_depth', 'initial_hypotheses',
)
START_POLICY_FIELDS = ('preplanned_tree_version', 'paired_scout', 'exploration_scout',
    'exploration_policy_version', 'parallel_workflows', 'plan_depth', 'initial_hypotheses')


def load_start_config(paths) -> dict:
    """Input: ConsolePaths. Output: detached non-secret existing config; never persist credentials or executable argv."""
    from wqb.config import DEFAULT_CONFIG, load_config
    from wqb.console_api import _read, _safe
    config = deepcopy(DEFAULT_CONFIG)
    yaml_path = _safe(paths.workflow_root, paths.workflow_root / 'configs/stage1_usa_d1.yaml')
    if yaml_path.exists():
        config.update(load_config(yaml_path))
    for relative in ('configs/workflow_defaults.example.json', 'configs/workflow_local.json'):
        config.update(_read(paths.workflow_root, relative, optional=True) or {})
    clean = {key: config[key] for key in START_CONFIG_FIELDS if key in config}
    if any(type(value) not in (str, int, float, bool) for value in clean.values()):
        raise ValueError('Console Start settings must be scalar values')
    policy = config.get('research_policy', {})
    if not isinstance(policy, dict):
        raise ValueError('research_policy must be an object')
    version = policy.get('preplanned_tree_version', 0)
    if type(version) is not int or version not in (0, 1):
        raise ValueError('preplanned_tree_version must be integer 0 or 1')
    clean['research_policy'] = {key: policy[key] for key in START_POLICY_FIELDS if key in policy}
    if any(type(value) not in (bool, int) for value in clean['research_policy'].values()):
        raise ValueError('Console Start policy settings must be boolean or integer values')
    if 'repair_search_policy' in config:
        from wqb.repair_search import _policy
        clean['repair_search_policy'] = _policy(config['repair_search_policy'])
    for key, fields in (('selected_scope', ('instrument_type', 'region', 'delay', 'universe', 'as_of')),
                        ('measurement_period', ('start', 'end'))):
        if key in config:
            if not isinstance(config[key], dict):
                raise ValueError(key + ' must be an object')
            clean[key] = {field: config[key][field] for field in fields if field in config[key]}
            if any(type(value) not in (str, int) for value in clean[key].values()):
                raise ValueError(key + ' fields must be strings or integers')
    if 'live_api_enabled' in clean and type(clean['live_api_enabled']) is not bool:
        raise ValueError('live_api_enabled must be bool')
    return deepcopy(clean)


def application_start_form(paths, selected_option_id: str) -> dict:
    """Input: ConsolePaths/persisted option ID str. Output: ordinary Start form using saved scope and permission only."""
    config = load_start_config(paths)
    from wqb.console_server import _selected_option
    option = _selected_option(paths, selected_option_id)
    scope_match = re.fullmatch(r'([A-Z][A-Z0-9_]*)\s+D(\d+)\s*([A-Z][A-Z0-9_]*)',
                              str(option.get('candidate_scope', '')).strip().upper())
    if scope_match is None:
        raise ValueError('option scope must specify one exact region, delay and universe')
    scope = dict(region=scope_match[1], delay=int(scope_match[2]), universe=scope_match[3])
    return dict(selected_option_id=selected_option_id,
        selected_region=scope.get('region', ''), selected_delay=scope.get('delay', ''),
        selected_universe=scope.get('universe', ''), enable_live_api=config.get('live_api_enabled', False))


def start_request_guard(runs_root: Path):
    """Input: runs Path. Output: lock context. Serialize Start commit and durable Stop acknowledgement."""
    return json_lock_transition_guard(Path(runs_root) / "console_start" / "intent",
                                      START_LOCK_TIMEOUT_SECONDS, START_LOCK_SLEEP_SECONDS,
                                      "Console Start intent is busy")


def read_start_request(runs_root: Path) -> dict:
    """Input: runs Path. Output: request dict. Read preparation intent without creating a mission."""
    path = Path(runs_root) / "console_start" / "request.json"
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {"status": "blocked", "passed": False, "error": "invalid Console Start intent"}
    return row if isinstance(row, dict) else {"status": "blocked", "passed": False, "error": "invalid Console Start intent"}


def _write_request(runs_root: Path, row: dict) -> dict:
    """Input: runs Path and request dict. Output: written dict. Atomically persist preparation recovery state."""
    path = Path(runs_root) / "console_start" / "request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {**row, "updated_at": datetime.now(timezone.utc).isoformat()}
    temporary = path.with_name(uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return row


def _selection(form: dict) -> dict:
    """Input: action form dict. Output: canonical selection dict. Bind option, scope and explicit permission."""
    from wqb.console_server import _selected_scope, _truthy
    return {"selected_option_id": str(form.get("selected_option_id", "")),
            "scope": _selected_scope(form), "enable_live_api": _truthy(form.get("enable_live_api"))}


def _source_intent(runs_root: Path) -> dict:
    """Input: runs Path. Output: source identity dict. Bind preparation to the existing run and user intent."""
    active = discover_active_workflow(runs_root)
    return {"run_dir": str(active.run_dir) if active.run_dir else "",
            "request_revision": read_runtime_control(active.run_dir).get("request_revision", "") if active.run_dir else ""}


def register_start(paths, form: dict, job_id: str) -> dict:
    """Input: ConsolePaths, form dict, job ID str. Output: request dict. Reserve local prep without mission creation."""
    selection = _selection(form)
    from wqb.config import read_research_policy
    policy = read_research_policy(paths.workflow_root / 'configs/workflow_defaults.example.json',
                                  paths.workflow_root / 'configs/workflow_local.json')
    config = load_start_config(paths)
    preplanned = config['research_policy'].get('preplanned_tree_version') == 1
    with start_request_guard(paths.runs_root):
        previous = read_start_request(paths.runs_root)
        if previous.get("error") == "invalid Console Start intent":
            raise ValueError(previous["error"])
        if previous.get("status") in PREPARING_STATUSES:
            from wqb.console_jobs import load_job_history
            running = any(row.get("job_id") == previous.get("job_id") and row.get("status") in {"created", "running"}
                          for row in load_job_history(paths.job_root, paths.knowledge_root))
            if running:
                if previous.get("selection") != selection:
                    raise ValueError("another Console Start preparation is active; Stop it before changing options")
                return previous
        extra = {}
        if preplanned:
            from wqb.console_server import _selected_option
            if _source_intent(paths.runs_root)['run_dir'] or (paths.runs_root / 'active_research_group.json').exists():
                raise ValueError('preplanned Start cannot adopt or replace an active mission')
            config['selected_scope'] = {**config.get('selected_scope', {}), **selection['scope']}
            config.update(selection['scope'])
            extra = dict(preplanned_config=config, preplanned_option=_selected_option(paths, selection['selected_option_id']))
        return _write_request(paths.runs_root, {
            "request_id": uuid4().hex, "job_id": job_id, "status": "preparing", "passed": False,
            "selection": selection, "source_intent": _source_intent(paths.runs_root),
            **({'research_policy': policy} if policy is not None else {}),
            **extra,
        })


def cancel_start(runs_root: Path) -> dict:
    """Input: runs Path. Output: cancellation dict. Cancel prep or pause its committed mission before returning."""
    with start_request_guard(runs_root):
        row = read_start_request(runs_root)
        if not row:
            return {}
        if row.get("run_dir"):
            request_runtime_state(row["run_dir"], "paused")
        if row.get('group_dir'):
            from wqb.console_api import _safe
            from wqb.research_group import read_group, stop_group
            group = _safe(Path(runs_root), Path(row['group_dir']))
            stop_group(group, read_group(group)['request_revision'])
        return _write_request(runs_root, {**row, "status": "cancelled", "passed": False,
                                         "error": "Stop requested; local Start preparation cancelled"})


def _blocked_request(paths, row: dict, receipt: dict, error: str) -> dict:
    """Input: paths, request/receipt dicts, error str. Output: blocked dict. Persist local failure while caller holds intent lock."""
    receipt = {**receipt, "request_id": row["request_id"], "job_id": row["job_id"],
               "passed": False, "blocked": True, "scope": row["selection"]["scope"],
               "knowledge_root": str(paths.knowledge_root.resolve()), "online_refresh_authorized": False,
               "checked_at": datetime.now(timezone.utc).isoformat()}
    if not receipt.get("issues"):
        receipt["issues"] = [{"code": "local_start_blocked", "message": error,
                              "level": "block", "path": str(paths.knowledge_root)}]
    receipt_path = paths.runs_root / "start_preflight" / f"{row['request_id']}-blocked.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt["receipt_path"] = str(receipt_path)
    temporary = receipt_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, receipt_path)
    return _write_request(paths.runs_root, {**row, "status": "blocked", "passed": False,
        "issues": receipt["issues"], "error": error, "preflight_receipt_path": str(receipt_path)})


def _notify_blocked_request(paths, row: dict) -> dict:
    """Input: ConsolePaths and blocked dict. Output: current dict. Notify unlocked, then CAS without undoing Stop."""
    from wqb.preflight_notifications import notify_preflight_blocker
    try:
        receipt = json.loads(Path(row["preflight_receipt_path"]).read_text(encoding="utf-8"))
        notification = notify_preflight_blocker(paths.runs_root, receipt)
    except Exception as failure:
        notification = {"status": "failed", "error": str(failure)}
    with start_request_guard(paths.runs_root):
        current = read_start_request(paths.runs_root)
        if current.get("request_id") != row["request_id"] or current.get("status") != "blocked":
            return current
        return _write_request(paths.runs_root, {**current, "notification": notification})


def execute_start(paths, form: dict, request_id: str) -> dict:
    """Input: ConsolePaths, form dict, request ID str. Output: result dict. Prepare locally then commit a paused mission."""
    from wqb.console_server import _selected_option, _option_objective, _validate_option_data_coverage
    selection = _selection(form)
    with start_request_guard(paths.runs_root):
        row = read_start_request(paths.runs_root)
        if row.get("request_id") != request_id or row.get("selection") != selection:
            return {"status": "cancelled", "passed": False, "error": "superseded Console Start request"}
        if row.get("status") not in PREPARING_STATUSES:
            return row
    if 'preplanned_config' in row:
        return _execute_preplanned_start(paths, row)
    scope = selection["scope"]
    policy = row.get('research_policy')
    policy_args = {'research_policy': policy} if policy is not None else {}
    try:
        receipt = prepare_start(paths.knowledge_root, paths.runs_root, scope, selection["enable_live_api"],
                                **(dict(policy_args, selected_option_id=selection['selected_option_id']) if policy_args else {}))
    except Exception as error:
        receipt = {"passed": False, "scope": scope, "issues": [{"code": "local_preflight_failed",
            "level": "block", "path": str(paths.knowledge_root), "message": str(error)}]}
    validation_error = ""
    if receipt.get("passed") is True:
        try:
            option = _selected_option(paths, selection["selected_option_id"])
            _validate_option_data_coverage(paths, option, scope, **policy_args)
        except Exception as error:
            from wqb.data_ledger import data_ledger_path_for_knowledge
            validation_error = str(error)
            receipt = {**receipt, "passed": False, "blocked": True, "issues": [{
                "code": "start_validation_failed", "level": "block", "message": validation_error,
                "path": str(data_ledger_path_for_knowledge(paths.knowledge_root)),
            }]}
    with start_request_guard(paths.runs_root):
        row = read_start_request(paths.runs_root)
        if row.get("request_id") != request_id or row.get("status") not in PREPARING_STATUSES:
            return {**row, "status": "cancelled", "passed": False}
        row = _write_request(paths.runs_root, {**row, "preflight_receipt_path": receipt.get("receipt_path", "")})
        if receipt.get("passed") is not True:
            row = _blocked_request(paths, row, receipt, validation_error or "Local Start preflight blocked; inspect issues before retrying")
        elif row.get("source_intent") != _source_intent(paths.runs_root):
            return _write_request(paths.runs_root, {**row, "status": "cancelled", "passed": False,
                                                  "error": "source runtime intent changed during preparation"})
        else:
            try:
                objective = f"{_option_objective(option)} | scope: {scope['region']} D{scope['delay']} {scope['universe']}"
                orchestrator = WorkflowOrchestrator(OrchestratorPaths(paths.project_root, paths.workflow_root,
                                                                       paths.knowledge_root, paths.runs_root))
                result = orchestrator.start(objective, selection["selected_option_id"],
                                            datetime.now(timezone.utc).isoformat(), selected_scope=scope, **policy_args)
                if not result.get("run_dir"):
                    raise ValueError("Start returned no mission directory")
                # Persist the mission before publishing paused runtime intent.
                row = _write_request(paths.runs_root, {**row, **result, "status": "committing"})
                control = request_runtime_state(result["run_dir"], "paused", enable_live_api=selection["enable_live_api"])
                from wqb.daily_simulation_budget import activate_daily_policy
                if not (Path(result['run_dir']) / 'runtime_status.json').exists():
                    from wqb.runtime_control import update_runtime_status
                    update_runtime_status(result['run_dir'], simulation_attempts=0)
                control = activate_daily_policy(Path(result['run_dir']), control['request_revision'],
                                                'Console Start ' + request_id)
                return _write_request(paths.runs_root, {**row, "status": "completed", "passed": True,
                                                      "runtime_request_revision": control["request_revision"]})
            except Exception as error:
                row = _blocked_request(paths, row, {**receipt, "passed": False,
                    "issues": [{"code": "start_validation_failed", "level": "block",
                                "path": str(paths.knowledge_root), "message": str(error)}]}, str(error))
    return _notify_blocked_request(paths, row)


def _execute_preplanned_start(paths, original: dict) -> dict:
    """Input: ConsolePaths/frozen Start dict. Output: durable prepared group or blocker; model work runs outside Stop lock."""
    from wqb.console_api import _read, _safe
    from wqb.initial_model_worker import create_initial_model_runner
    from wqb.initial_research_planning import TASK_PATH
    from wqb.preplanned_start import prepare_preplanned_start
    from wqb.research_group import read_group
    from wqb.research_group_driver import initialize_group_runtime
    from wqb.runtime_control import DEFAULT_MAX_RUNTIME_SECONDS, DEFAULT_MAX_RECOVERIES
    runtime_paths = OrchestratorPaths(paths.project_root, paths.workflow_root, paths.knowledge_root, paths.runs_root)
    config = original['preplanned_config']
    runners = {}

    def model_runner(supplied: dict) -> dict:
        """Input: source-bound brief with context dict. Output: exact persisted-brief model answer for one owned lane."""
        brief = deepcopy(supplied)
        context = brief.pop('worker_context', {})
        run = _safe(paths.runs_root, Path(context.get('run_dir', '')))
        if (run.parent != paths.runs_root.absolute() or context.get('task_path') != TASK_PATH
                or context.get('manifest_path') != 'run_manifest.json'
                or context.get('checkpoint_type') != 'initial_research_planning'
                or Path(context.get('knowledge_root', '')).absolute() != paths.knowledge_root.absolute()
                or context.get('certificate_path') != 'runtime/exploration/resources/'
                    + brief['resource_certificate_sha256'] + '.json'):
            raise ValueError('initial model worker context mismatch')
        if _read(run, TASK_PATH).get('brief') != brief:
            raise ValueError('initial model brief differs from persisted task')
        binding = _read(run, 'research_group_binding.json')
        group = read_group(_safe(paths.runs_root, paths.runs_root / 'research_groups' / binding['group_id']))
        if group['authority'] != authority:
            raise ValueError('initial model group authority mismatch')
        with start_request_guard(paths.runs_root):
            row = read_start_request(paths.runs_root)
            if row.get('request_id') != original['request_id'] or row.get('status') not in PREPARING_STATUSES:
                raise ValueError('Console Start cancelled or superseded before model')
            if row.get('group_dir') and (row['group_dir'] != group['group_dir']
                    or row['group_request_revision'] != group['request_revision']):
                raise ValueError('original group Start revision changed')
            if not row.get('group_dir'):
                _write_request(paths.runs_root, {**row, 'group_dir': group['group_dir'],
                    'group_request_revision': group['request_revision']})
        if run not in runners:
            runners[run] = create_initial_model_runner(run, config)
        return runners[run](brief)

    try:
        if original.get('source_intent', {}).get('run_dir') or original['source_intent'] != _source_intent(paths.runs_root):
            raise ValueError('preplanned Start requires idle unchanged runtime intent')
        scope = config.get('selected_scope', {})
        if any(scope.get(k) != v for k, v in original['selection']['scope'].items()):
            raise ValueError('configured selected_scope differs from original Start')
        authority = dict(enable_live_api=original['selection']['enable_live_api'],
            max_runtime_seconds=config.get('max_runtime_seconds', DEFAULT_MAX_RUNTIME_SECONDS),
            max_recoveries=config.get('max_recoveries', DEFAULT_MAX_RECOVERIES))
        result = prepare_preplanned_start(runtime_paths, original['preplanned_option'], authority, config,
                                           model_runner=model_runner)
        with start_request_guard(paths.runs_root):
            row = read_start_request(paths.runs_root)
            if row.get('request_id') != original['request_id'] or row.get('status') not in PREPARING_STATUSES:
                return row
            if result.get('status') != 'completed':
                raise ValueError(result.get('reason') or 'preplanned Start preparation blocked')
            group = result['group']
            if (row.get('group_dir') != group['group_dir']
                    or row.get('group_request_revision') != group['request_revision']
                    or read_group(Path(group['group_dir']))['request_revision'] != row['group_request_revision']):
                raise ValueError('preplanned Start group revision changed before commit')
            current_intent = _source_intent(paths.runs_root)
            own_runs = {str((paths.runs_root / lane['run_id']).resolve()) for lane in group['lanes']}
            if current_intent['run_dir'] and str(Path(current_intent['run_dir']).resolve()) not in own_runs:
                raise ValueError('source runtime intent changed before group commit')
            initialize_group_runtime(runtime_paths, group)
            return _write_request(paths.runs_root, {**row, 'status': 'completed', 'passed': True,
                'warnings': result.get('warnings', []), 'prepared_lanes': result.get('prepared_lanes')})
    except Exception as error:
        with start_request_guard(paths.runs_root):
            row = read_start_request(paths.runs_root)
            if row.get('request_id') != original['request_id'] or row.get('status') not in PREPARING_STATUSES:
                return row
            row = _blocked_request(paths, row, {}, str(error))
        return _notify_blocked_request(paths, row)


def main(argv: list[str] | None = None) -> int:
    """Input: optional CLI tokens list[str]. Output: exit code int. Run background prep with existing workflow-start flags."""
    from wqb.console_state import default_console_paths
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["workflow-start"])
    parser.add_argument("--knowledge-root", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--selected-option-id", required=True)
    parser.add_argument("--selected-region", required=True)
    parser.add_argument("--selected-delay", required=True, type=int)
    parser.add_argument("--selected-universe", required=True)
    parser.add_argument("--enable-live-api", action="store_true")
    parser.add_argument("--start-request-id", required=True)
    args = parser.parse_args(argv)
    paths = default_console_paths(args.knowledge_root, args.run_dir)
    result = execute_start(paths, vars(args), args.start_request_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "completed" and result.get("passed") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
