"""Durable local Start preparation, separate from live workflow execution."""

import argparse
import hashlib
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4

from wqb.lockfile import json_lock_transition_guard
from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
from wqb.runtime_control import read_runtime_control, request_runtime_state
from wqb.start_preflight import prepare_start
from wqb.workflow_state import discover_active_workflow


START_LOCK_TIMEOUT_SECONDS = 5.0
START_LOCK_SLEEP_SECONDS = 0.02
PREPARATION_CHECK_INTERVAL_SECONDS = 0.25
MAX_PREPARATION_STATE_BYTES = 256 * 1024
EXACT_SCOPE_PATTERN = r'([A-Z][A-Z0-9_]*)\s+D(\d+)\s*([A-Z][A-Z0-9_]*)'
CONFIGURED_SCOPE_INCENTIVES = {'genius_osmosis'}
MAINTENANCE_INCENTIVES = {'knowledge_refresh', 'theme', 'competition'}
PREPARING_STATUSES = {"preparing", "validating"}
START_CONFIG_FIELDS = (
    'instrument_type', 'region', 'universe', 'delay', 'language', 'neutralization', 'decay',
    'truncation', 'pasteurization', 'unit_handling', 'nan_handling', 'ai_executor',
    'request_timeout_seconds', 'max_retries', 'base_backoff_seconds', 'max_alphas_per_round',
    'max_rounds', 'runtime_max_steps', 'runtime_no_progress_limit', 'max_runtime_seconds',
    'max_recoveries', 'live_api_enabled', 'parallel_workflows', 'plan_depth', 'initial_hypotheses',
    'retrieval_max_queries', 'retrieval_max_validations', 'retrieval_max_returned_bytes', 'expression_tool_version',
)
START_POLICY_FIELDS = ('preplanned_tree_version', 'paired_scout', 'exploration_scout',
    'exploration_policy_version', 'parallel_workflows', 'plan_depth', 'initial_hypotheses',
    'execution_package_version', 'multiplier_scope_version', 'retrieval_design_version', 'direct_knowledge_version', 'expression_tool_version')


def load_start_config(paths) -> dict:
    """Input: ConsolePaths. Output: detached non-secret existing config; never persist credentials or executable argv."""
    from wqb.config import DEFAULT_CONFIG, load_config
    from wqb.console_api import _read, _safe
    config = deepcopy(DEFAULT_CONFIG)
    configuration = paths.configuration_root
    yaml_path = _safe(configuration, configuration / 'configs/stage1_usa_d1.yaml')
    if yaml_path.exists():
        config.update(load_config(yaml_path))
    for relative in ('configs/workflow_defaults.example.json', 'configs/workflow_local.json'):
        config.update(_read(configuration, relative, optional=True) or {})
    clean = {key: config[key] for key in START_CONFIG_FIELDS if key in config}
    if any(type(value) not in (str, int, float, bool) for value in clean.values()):
        raise ValueError('Console Start settings must be scalar values')
    for key in ('retrieval_max_queries', 'retrieval_max_validations', 'retrieval_max_returned_bytes'):
        if key in clean and (type(clean[key]) is not int or clean[key] <= 0):
            raise ValueError(key + ' must be a positive integer')
    policy = config.get('research_policy', {})
    if not isinstance(policy, dict):
        raise ValueError('research_policy must be an object')
    version = policy.get('preplanned_tree_version', 0)
    if type(version) is not int or version not in (0, 1):
        raise ValueError('preplanned_tree_version must be integer 0 or 1')
    clean['research_policy'] = {key: policy[key] for key in START_POLICY_FIELDS if key in policy}
    from wqb.expression_planning import expression_mode
    if expression_mode(dict(config,research_policy=policy)):
        clean['expression_tool_version']=1
        clean['research_policy']['expression_tool_version']=1
    if 'direct_knowledge_version' in policy:
        from wqb.direct_knowledge import direct_knowledge_enabled, DIRECT_POLICY
        direct_knowledge_enabled(dict(direct_knowledge_version=policy['direct_knowledge_version']))
        if version != 1:
            raise ValueError('direct knowledge requires preplanned trees')
        clean['direct_knowledge_version'] = 1
        clean['resource_admission_policy'] = DIRECT_POLICY
    if version == 1 and 'direct_knowledge_version' not in clean:
        from wqb.resource_evidence import KNOWLEDGE_CATALOG_POLICY
        clean['resource_admission_policy'] = KNOWLEDGE_CATALOG_POLICY
    if any(type(value) not in (bool, int) for value in clean['research_policy'].values()):
        raise ValueError('Console Start policy settings must be boolean or integer values')
    from wqb.execution_package import package_enabled
    package_enabled(clean)
    retrieval = clean['research_policy'].get('retrieval_design_version', 0)
    if type(retrieval) is not int or retrieval not in (0, 1):
        raise ValueError('retrieval_design_version must be integer 0 or 1')
    from wqb.multiplier_scope import multiplier_enabled
    multiplier_enabled(clean)
    if 'multiplier_preparation_policy' in config:
        from wqb.multiplier_preparation import validated_preparation_policy
        clean['multiplier_preparation_policy'] = validated_preparation_policy(config['multiplier_preparation_policy'])
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


def _application_scope(option: dict, config: dict) -> tuple[dict, str]:
    """Input: saved option/config dicts. Output: exact scope dict/source str; never infer scope from prose."""
    incentive = option.get('primary_incentive')
    if incentive in MAINTENANCE_INCENTIVES:
        raise ValueError('This option requires independent maintenance or activity feasibility before research')
    text = str(option.get('candidate_scope', '')).strip().upper()
    match = re.fullmatch(EXACT_SCOPE_PATTERN, text)
    explicit = option.get('execution_scope')
    if 'execution_scope' in option:
        scope = _exact_application_scope(explicit)
        if match and scope != dict(region=match[1], delay=int(match[2]), universe=match[3]):
            raise ValueError('option structured scope conflicts with displayed scope')
        if not match and re.search(r'\bD\d+\b', text):
            raise ValueError('option scope is ambiguous; maintenance must bind one exact scope')
        return scope, 'option'
    if match:
        return dict(region=match[1], delay=int(match[2]), universe=match[3]), 'option'
    if re.search(r'\bD\d+\b', text):
        raise ValueError('option scope must specify one exact region, delay and universe')
    if incentive not in CONFIGURED_SCOPE_INCENTIVES:
        raise ValueError('This option requires maintenance to bind its activity and one exact research scope')
    configured = config.get('selected_scope') if 'selected_scope' in config else {
        key: config.get(key) for key in ('region', 'delay', 'universe')}
    return _exact_application_scope(configured), 'configuration'


def _exact_application_scope(value) -> dict:
    """Input: scope object. Output: normalized scope dict; reject partial values, booleans and arbitrary tokens."""
    if (not isinstance(value, dict) or type(value.get('delay')) is not int or value['delay'] < 0
            or any(not isinstance(value.get(key), str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*', value[key])
                   for key in ('region', 'universe'))):
        raise ValueError('configured or structured scope must specify one exact region, delay and universe')
    return {key: value[key] for key in ('region', 'delay', 'universe')}


def application_option(paths, option: dict, *, config: dict | None = None) -> dict:
    """Input: paths/saved option/config dict. Output: display contract; no readiness, platform or authority effects."""
    result = dict(option_id=option['option_id'], title=option.get('title', option.get('name', '')),
                  startable=False, scope=None, scope_source='', reason='')
    try:
        if option.get('primary_incentive') == 'theme':
            from wqb.multiplier_scope import multiplier_enabled, scope_selection_contract
            supplied = config if config is not None else load_start_config(paths)
            if multiplier_enabled(supplied):
                result.update(startable=True, title='Multiplier · 自选范围', selection_mode='manual_multiplier',
                    scope_source='user', scope_selection=scope_selection_contract(paths.knowledge_root, supplied),
                    configuration_digest=_start_config_digest(supplied))
                return result
        needs_config = (option.get('primary_incentive') in CONFIGURED_SCOPE_INCENTIVES
                        and 'execution_scope' not in option
                        and not re.fullmatch(EXACT_SCOPE_PATTERN, str(option.get('candidate_scope', '')).strip().upper()))
        resolved = config if config is not None else (load_start_config(paths) if needs_config else {})
        scope, source = _application_scope(option, resolved)
        result.update(startable=True, scope=scope, scope_source=source)
    except ValueError as error:
        result['reason'] = str(error)
        from wqb.preflight_notifications import start_contract_path
        from wqb.runtime_control import _read
        receipt = _read(start_contract_path(paths, option['option_id'], str(error)))
        notification = receipt.get('notification', {})
        result['maintenance_status'] = (notification.get('status', 'not_requested')
                                        if isinstance(notification, dict) else 'delivery_uncertain')
    return result


def _start_config_digest(config: dict) -> str:
    """Input: sanitized non-secret config dict. Output: digest binding displayed scope/defaults/limits."""
    return hashlib.sha256(json.dumps(config, sort_keys=True, allow_nan=False).encode()).hexdigest()


def application_start_form(paths, selected_option_id: str, *, selected_scope: dict | None = None) -> dict:
    """Input: ConsolePaths/persisted option ID str. Output: ordinary Start form using saved scope and permission only."""
    config = load_start_config(paths)
    from wqb.console_server import _selected_option
    option = _selected_option(paths, selected_option_id)
    from wqb.multiplier_scope import multiplier_enabled, read_scope_catalog, select_multiplier_scope
    if option.get('primary_incentive') == 'theme' and multiplier_enabled(config):
        scope = select_multiplier_scope(read_scope_catalog(paths.knowledge_root), config, selected_scope)
        return dict(selected_option_id=selected_option_id, selected_region=scope['region'],
            selected_delay=scope['delay'], selected_universe=scope['universe'], enable_live_api=True,
            expected_start_config_digest=_start_config_digest(config))
    if selected_scope is not None:
        raise ValueError('scope selection is allowed only for manual Multiplier Start')
    scope, _ = _application_scope(option, config)
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
    if active.run_dir is not None:
        from wqb.research_retirement import retirement_boundary
        boundary = retirement_boundary(active.run_dir)
        if boundary is not None and boundary['status'] == 'retired':
            return {'run_dir': '', 'request_revision': '', 'retired_run_dir': str(active.run_dir),
                    'retired_request_revision': read_runtime_control(active.run_dir).get('request_revision', '')}
    return {"run_dir": str(active.run_dir) if active.run_dir else "",
            "request_revision": read_runtime_control(active.run_dir).get("request_revision", "") if active.run_dir else ""}


def _require_retired_intent(runs_root: Path, intent: dict) -> None:
    """Input: runs Path and captured intent dict. Output: None or ValueError. Retain historical identity/Stop CAS."""
    selected = intent.get('retired_run_dir')
    if not selected:
        return
    from wqb.workflow_state import load_active_run
    from wqb.research_retirement import retirement_boundary
    run = Path(selected)
    pointer = load_active_run(runs_root)
    boundary = retirement_boundary(run)
    if (run.resolve().parent != Path(runs_root).resolve() or pointer is None
            or Path(pointer.get('run_dir', '')).resolve() != run.resolve()
            or pointer.get('run_id') != run.name or boundary is None or boundary['status'] != 'retired'
            or read_runtime_control(run).get('request_revision', '') != intent.get('retired_request_revision')):
        raise ValueError('retired source runtime intent changed during preparation')


def _require_resolved_retrieval(paths, previous: dict) -> None:
    """Input: paths/prior Start. Output: None; unresolved model ownership cannot be erased by a new timestamp or Stop."""
    binding = previous.get('retrieval_design_task')
    if binding is None:
        return
    from wqb.console_api import _safe
    from wqb.retrieval_research_planning import read_design_task
    try:
        directory = _safe(paths.runs_root, Path(binding['directory']))
        if not directory.is_relative_to((paths.runs_root / 'start_preflight/preplanned').absolute()):
            raise ValueError('task outside preparation boundary')
        task = read_design_task(directory)
        owner = task['identity']['config'].get('retrieval_owner')
        known_rejection = task.get('status') == 'blocked' and isinstance(task.get('answer'), dict)
        if known_rejection:
            from wqb.semantic_compilation import _check_schema
            _check_schema(task['brief']['output_schema'], task['answer'])
        if (task['input_sha256'] != binding['input_sha256'] or owner != dict(
                runs_root=str(paths.runs_root), request_id=previous['request_id'])
                or task['status'] != 'completed' and not known_rejection):
            raise ValueError('original task not completed')
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError('unresolved retrieval preparation retained; maintenance must reconcile original model task') from error


def register_start(paths, form: dict, job_id: str) -> dict:
    """Input: ConsolePaths, form dict, job ID str. Output: request dict. Reserve local prep without mission creation."""
    selection = _selection(form)
    from wqb.config import DEFAULT_CONFIG, read_research_policy
    policy = read_research_policy(paths.configuration_root / 'configs/workflow_defaults.example.json',
                                  paths.configuration_root / 'configs/workflow_local.json')
    config = load_start_config(paths)
    if form.get('expected_start_config_digest') and form['expected_start_config_digest'] != _start_config_digest(config):
        raise ValueError('Start configuration changed; refresh before starting')
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
        _require_resolved_retrieval(paths, previous)
        extra = {}
        if preplanned:
            from wqb.console_server import _selected_option
            if _source_intent(paths.runs_root)['run_dir'] or (paths.runs_root / 'active_research_group.json').exists():
                raise ValueError('preplanned Start cannot adopt or replace an active mission')
            config['selected_scope'] = {**config.get('selected_scope', {}), **selection['scope']}
            config['selected_scope'].setdefault('instrument_type',
                config.get('instrument_type', DEFAULT_CONFIG['instrument_type']))
            config['selected_scope'].setdefault('as_of', datetime.now(timezone.utc).isoformat())
            config.update(selection['scope'])
            extra = dict(preplanned_config=config, preplanned_option=_selected_option(paths, selection['selected_option_id']))
            from wqb.multiplier_scope import multiplier_enabled, read_scope_catalog, select_multiplier_scope
            if extra['preplanned_option'].get('primary_incentive') == 'theme' and multiplier_enabled(config):
                select_multiplier_scope(read_scope_catalog(paths.knowledge_root), config, selection['scope'])
                from wqb.multiplier_preparation import validated_preparation_policy
                config['multiplier_preparation_policy'] = validated_preparation_policy(config.get('multiplier_preparation_policy'))
                extra['preplanned_option'] = {**extra['preplanned_option'],
                    'title': 'Multiplier · user-selected scope',
                    'candidate_scope': f"{selection['scope']['region']} D{selection['scope']['delay']} {selection['scope']['universe']}",
                    'manual_multiplier': dict(schema_version=1, eligibility='user_assessed', scope=selection['scope'])}
                extra['multiplier_preparation'] = dict(status='pending', stage='checking_fields', requests_used=0,
                    request_limit=config['multiplier_preparation_policy']['request_limit'])
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


def _retrieval_progress(paths, row: dict, binding: dict) -> dict:
    """Input: Console paths, Start/binding dicts. Output: sanitized dict bound to the original active task, or empty."""
    from wqb.console_api import _safe
    from wqb.retrieval_research_planning import read_design_task
    from wqb.research_tool_service import PROGRESS_PATH, OPERATIONS, tool_limits
    try:
        active = read_start_request(paths.runs_root)
        if (row.get('status') not in PREPARING_STATUSES
                or active.get('status') not in PREPARING_STATUSES
                or active.get('request_id') != row.get('request_id')
                or active.get('multiplier_preparation', {}).get('retrieval_task') != binding
                or active.get('source_intent') != row.get('source_intent')
                or row.get('source_intent') != _source_intent(paths.runs_root)):
            return {}
        directory = _safe(paths.runs_root, Path(binding['directory']))
        if not directory.is_relative_to((paths.runs_root / 'start_preflight/preplanned').absolute()):
            return {}
        task = read_design_task(directory)
        identity = task['identity']
        owner = identity['config'].get('retrieval_owner')
        scope = row.get('selection', {}).get('scope', {})
        if (task.get('status') != 'running' or task['input_sha256'] != binding['input_sha256']
                or owner != dict(runs_root=str(paths.runs_root), request_id=row['request_id'])
                or identity['knowledge_root'] != str(paths.knowledge_root)
                or any(key not in scope or identity['scope'].get(key) != scope[key]
                       for key in ('region', 'delay', 'universe'))
                or identity['scope'].get('instrument_type') != scope.get('instrument_type',
                    row.get('preplanned_config', {}).get('instrument_type'))):
            return {}
        path = _safe(directory, directory / PROGRESS_PATH)
        if path.stat().st_size > MAX_PREPARATION_STATE_BYTES:
            return {}
        progress = json.loads(path.read_text(encoding='utf-8'))
        if (progress.get('input_sha256') != task['input_sha256']
                or progress.get('stage') not in {'retrieving', 'validating', 'planning'}
                or progress.get('operation') not in OPERATIONS):
            return {}
        limits = tool_limits(identity['config'])
        for count, limit in (('queries', 'max_queries'), ('validations', 'max_validations'),
                             ('returned_bytes', 'max_returned_bytes')):
            if (type(progress.get(count)) is not int or type(progress.get(limit)) is not int
                    or progress[limit] != limits[limit] or not 0 <= progress[count] <= limits[limit]):
                return {}
        stamp = progress['activity_at']
        if not isinstance(stamp, str) or datetime.fromisoformat(stamp).tzinfo is None:
            return {}
        return {key: progress[key] for key in ('stage', 'operation', 'queries', 'validations',
            'returned_bytes', 'max_queries', 'max_validations', 'max_returned_bytes', 'activity_at')}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}


def preparation_projection(paths, row: dict) -> dict:
    """Input: Console paths/original request. Output: bounded display facts; never grant resource or execution authority."""
    current = row.get('multiplier_preparation')
    if not isinstance(current, dict):
        return {}
    result = dict(current)
    binding = result.pop('retrieval_task', None)
    result.pop('tool_progress', None)
    if isinstance(binding, dict):
        progress = _retrieval_progress(paths, row, binding)
        if progress:
            result['tool_progress'] = progress
    request_id = row.get('request_id', '')
    if isinstance(request_id, str) and re.fullmatch(r'[0-9a-f]{32}', request_id):
        from wqb.multiplier_preparation import _load
        from wqb.console_api import _safe
        try:
            path = _safe(paths.runs_root, paths.runs_root/'start_preflight/multiplier'/request_id/'state.json')
            if path.is_file() and path.stat().st_size <= MAX_PREPARATION_STATE_BYTES:
                saved = _load(path)
                selection = row.get('selection') if isinstance(row.get('selection'), dict) else {}
                if (saved.get('scope') == selection.get('scope')
                        and saved.get('knowledge_root') == str(paths.knowledge_root)):
                    count = saved.get('requests_used')
                    capture = saved.get('capture')
                    fields = capture.get('field_count') if isinstance(capture, dict) else None
                    if type(count) is int and 0 <= count <= result.get('request_limit', 0):
                        result['requests_used'] = count
                    config = row.get('preplanned_config') if isinstance(row.get('preplanned_config'), dict) else {}
                    policy = config.get('multiplier_preparation_policy')
                    limit = policy.get('max_fields', 100) if isinstance(policy, dict) else 100
                    if type(fields) is int and type(limit) is int and 0 <= fields <= limit:
                        result['field_count'] = fields
        except (OSError, ValueError, TypeError, KeyError):
            pass  # Missing/malformed display evidence never qualifies a field or changes authority.
    if row.get('status') in {'blocked', 'cancelled'}:
        result.update(status=row['status'], stage='failed' if row['status'] == 'blocked' else 'cancelled',
                      reason=str(row.get('error') or 'Start preparation stopped'))
        notice = row.get('notification') if isinstance(row.get('notification'), dict) else {}
        if notice.get('status') in {'failed', 'delivery_uncertain'}:
            result['reason'] += '; Maintenance delivery ' + notice['status'] + ': ' + str(notice.get('error', ''))
    return result


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
    blocked = {**row, "status": "blocked", "passed": False,
        "issues": receipt["issues"], "error": error, "preflight_receipt_path": str(receipt_path)}
    if 'multiplier_preparation' in row:
        blocked['multiplier_preparation'] = preparation_projection(paths, blocked)
    return _write_request(paths.runs_root, blocked)


def _notify_blocked_request(paths, row: dict) -> dict:
    """Input: ConsolePaths and blocked dict. Output: current dict. Notify unlocked, then CAS without undoing Stop."""
    binding = row.get('retrieval_design_task')
    if binding:
        from wqb.console_api import _safe
        from wqb.retrieval_research_planning import read_design_task
        try:
            directory = _safe(paths.runs_root, Path(binding['directory']))
            task = read_design_task(directory)
            ordinary = (task.get('status') == 'blocked' and isinstance(task.get('answer'), dict)
                and str(task.get('reason', '')).startswith('model_returned_no_plan:')
                and task['input_sha256'] == binding['input_sha256']
                and task['identity']['config'].get('retrieval_owner') == dict(
                    runs_root=str(paths.runs_root), request_id=row['request_id']))
        except (OSError, ValueError, KeyError, TypeError):
            ordinary = False
        if ordinary:
            with start_request_guard(paths.runs_root):
                current = read_start_request(paths.runs_root)
                if current.get('request_id') != row['request_id'] or current.get('status') != 'blocked':
                    return current
                return _write_request(paths.runs_root, {**current,
                    'error': '',
                    'planning_feedback': dict(status='incomplete', reason=task['reason']),
                    'notification': dict(status='not_required', reason='Known planning outcome; not a maintenance fault'),
                    'issues': [dict(code='planning_incomplete', level='warning', message=task['reason'])]})
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
        if 'multiplier_preparation' in row and row['multiplier_preparation'].get('status') != 'completed':
            row = _prepare_multiplier_start(paths, row)
            if row.get('status') not in PREPARING_STATUSES:
                return row
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


def _prepare_multiplier_start(paths, original: dict) -> dict:
    """Input: paths/original Start intent. Output: same intent with prepared fields or durable cancellation/blocker."""
    from wqb.multiplier_supervision import prepare_multiplier_fields_supervised
    from wqb.console_api import _safe

    next_check = 0.0

    def check_cancelled(force: bool = False):
        """Input: force bool. Output: bounded Stop checks; full authority always checked at phase boundaries."""
        nonlocal next_check
        now = time.monotonic()
        if not force and now < next_check:
            return
        with start_request_guard(paths.runs_root):
            row = read_start_request(paths.runs_root)
            if row.get('request_id') != original['request_id'] or row.get('status') not in PREPARING_STATUSES:
                raise InterruptedError('Multiplier preparation stopped or superseded')
            if row.get('source_intent') != _source_intent(paths.runs_root):
                _write_request(paths.runs_root, {**row, 'status': 'cancelled', 'passed': False,
                    'error': 'Source intent changed during Multiplier preparation'})
                raise InterruptedError('Source intent changed')
        next_check = time.monotonic() + PREPARATION_CHECK_INTERVAL_SECONDS

    def progress(update: dict):
        """Input: bounded progress dict. Output: None; publish only under the original Start CAS."""
        check_cancelled(force=True)
        with start_request_guard(paths.runs_root):
            row = read_start_request(paths.runs_root)
            if row.get('request_id') != original['request_id'] or row.get('status') not in PREPARING_STATUSES:
                raise InterruptedError('Multiplier preparation stopped or superseded')
            _write_request(paths.runs_root, {**row, 'multiplier_preparation': {**row['multiplier_preparation'], **update}})

    try:
        check_cancelled(force=True)
        if original['preplanned_config'].get('direct_knowledge_version') == 1:
            from wqb.research_query_index import prepare_query_index, query_fields
            generation = prepare_query_index(paths.knowledge_root)['generation']
            scope = dict(instrument_type=original['preplanned_config']['instrument_type'],
                **original['selection']['scope'])
            fields = query_fields(paths.knowledge_root, generation, scope, limit=1)
            check_cancelled(force=True)
            if fields['total']:
                progress(dict(stage='planning', status='completed', field_source='knowledge',
                    field_count=fields['total'], generation=generation,
                    warning='Knowledge quality/age/coverage are unknown or advisory; technical validation follows.'))
                return read_start_request(paths.runs_root)
        directory = _safe(paths.runs_root, paths.runs_root / 'start_preflight/multiplier' / original['request_id'])
        result = prepare_multiplier_fields_supervised(paths.knowledge_root, directory, original['selection']['scope'],
            check_cancelled=check_cancelled, progress=progress,
            policy=original['preplanned_config']['multiplier_preparation_policy'],
            allow_network=original['selection']['enable_live_api'])
        check_cancelled(force=True)
        if result.get('status') != 'completed':
            raise ValueError(result.get('reason', 'Multiplier field preparation did not complete'))
        progress({**result, 'stage': 'planning', 'status': 'completed'})
        return read_start_request(paths.runs_root)
    except Exception as error:
        with start_request_guard(paths.runs_root):
            row = read_start_request(paths.runs_root)
            if row.get('request_id') != original['request_id'] or row.get('status') not in PREPARING_STATUSES:
                return row
            row = {**row, 'multiplier_preparation': {**row['multiplier_preparation'],
                'status': 'blocked', 'stage': 'failed', 'reason': str(error)}}
            row = _blocked_request(paths, row, {}, str(error))
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
    config = deepcopy(original['preplanned_config'])
    runners = {}

    def check_original_start():
        """Input: none. Output: None; reject cancelled/superseded Start or changed original runtime intent."""
        with start_request_guard(paths.runs_root):
            row = read_start_request(paths.runs_root)
            if row.get('request_id') != original['request_id'] or row.get('status') not in PREPARING_STATUSES:
                raise InterruptedError('retrieval Start stopped or superseded')
            if row.get('source_intent') != _source_intent(paths.runs_root):
                raise InterruptedError('retrieval Start source intent changed')

    def retrieval_model_runner(directory: Path, brief: dict) -> dict:
        """Input: owning preparation task/compact brief. Output: one bounded existing Codex task result."""
        from wqb.retrieval_research_planning import create_retrieval_model_runner
        check_original_start()
        directory = _safe(paths.runs_root, directory)
        if not directory.is_relative_to(paths.runs_root / 'start_preflight/preplanned'):
            raise ValueError('retrieval task outside original Start preparation boundary')
        with start_request_guard(paths.runs_root):
            row = read_start_request(paths.runs_root)
            if row.get('request_id') != original['request_id'] or row.get('status') not in PREPARING_STATUSES:
                raise InterruptedError('retrieval Start stopped or superseded')
            from wqb.retrieval_research_planning import read_design_task
            task = read_design_task(directory)
            if task['identity']['config'].get('retrieval_owner') != dict(
                    runs_root=str(paths.runs_root), request_id=original['request_id']):
                raise ValueError('retrieval task owner differs from original Start')
            preparation = dict(row.get('multiplier_preparation', {}), stage='planning', status='running')
            preparation['retrieval_task'] = dict(directory=str(directory), input_sha256=task['input_sha256'])
            _write_request(paths.runs_root, {**row, 'multiplier_preparation': preparation,
                'retrieval_design_task': deepcopy(preparation['retrieval_task'])})
        if directory not in runners:
            runners[directory] = create_retrieval_model_runner(directory, config, check_original_start)
        return runners[directory](brief)

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
            _require_retired_intent(paths.runs_root, original.get('source_intent', {}))
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
        _require_retired_intent(paths.runs_root, original.get('source_intent', {}))
        if original.get('source_intent', {}).get('run_dir') or original['source_intent'] != _source_intent(paths.runs_root):
            raise ValueError('preplanned Start requires idle unchanged runtime intent')
        scope = config.get('selected_scope', {})
        if any(scope.get(k) != v for k, v in original['selection']['scope'].items()):
            raise ValueError('configured selected_scope differs from original Start')
        authority = dict(enable_live_api=original['selection']['enable_live_api'],
            max_runtime_seconds=config.get('max_runtime_seconds', DEFAULT_MAX_RUNTIME_SECONDS),
            max_recoveries=config.get('max_recoveries', DEFAULT_MAX_RECOVERIES))
        extra = {}
        if config.get('research_policy', {}).get('retrieval_design_version') == 1:
            config['retrieval_owner'] = dict(runs_root=str(paths.runs_root), request_id=original['request_id'])
            extra = dict(retrieval_model_runner=retrieval_model_runner, check_cancelled=check_original_start)
        result = prepare_preplanned_start(runtime_paths, original['preplanned_option'], authority, config,
                                           model_runner=model_runner, **extra)
        with start_request_guard(paths.runs_root):
            row = read_start_request(paths.runs_root)
            if row.get('request_id') != original['request_id'] or row.get('status') not in PREPARING_STATUSES:
                return row
            if result.get('status') != 'completed':
                raise ValueError(result.get('reason') or 'preplanned Start preparation blocked')
            group = result['group']
            if extra and not row.get('group_dir'):
                current_group = read_group(Path(group['group_dir']))
                if current_group['authority'] != authority:
                    raise ValueError('retrieval group authority differs from original Start')
                row = _write_request(paths.runs_root, {**row, 'group_dir': group['group_dir'],
                    'group_request_revision': group['request_revision']})
            if (row.get('group_dir') != group['group_dir']
                    or row.get('group_request_revision') != group['request_revision']
                    or read_group(Path(group['group_dir']))['request_revision'] != row['group_request_revision']):
                raise ValueError('preplanned Start group revision changed before commit')
            current_intent = _source_intent(paths.runs_root)
            _require_retired_intent(paths.runs_root, original.get('source_intent', {}))
            own_runs = {str((paths.runs_root / lane['run_id']).resolve()) for lane in group['lanes']}
            if current_intent['run_dir'] and str(Path(current_intent['run_dir']).resolve()) not in own_runs:
                raise ValueError('source runtime intent changed before group commit')
            initialize_group_runtime(runtime_paths, group)
            if extra:
                row = {**row, 'multiplier_preparation': {
                    **row.get('multiplier_preparation', {}), 'stage': 'ready', 'status': 'completed'}}
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
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--selected-option-id", required=True)
    parser.add_argument("--selected-region", required=True)
    parser.add_argument("--selected-delay", required=True, type=int)
    parser.add_argument("--selected-universe", required=True)
    parser.add_argument("--enable-live-api", action="store_true")
    parser.add_argument("--start-request-id", required=True)
    args = parser.parse_args(argv)
    paths = default_console_paths(args.knowledge_root, args.run_dir, project_root=args.workspace_root)
    result = execute_start(paths, vars(args), args.start_request_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "completed" and result.get("passed") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
