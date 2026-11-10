"""Prepared group lifecycle and process isolation, reusing the ordinary workflow driver.

Console calls initialize_group_runtime after complete_group_lanes, then calls
start_group_workers with the displayed group revision. Packaged hosts must route
the allowlisted ``-m wqb.research_group_driver lane`` helper before starting UI.
Tree dispatch/plan authentication belongs to workflow_auto_continue, not here.
"""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from wqb.daily_simulation_budget import DAILY_SIMULATION_LIMIT, activate_daily_policy
from wqb.exploration_eligibility import validate_operational_exploration
from wqb.lockfile import json_lock_transition_guard
from wqb.research_group import _digest, _guard, _read, read_group, discover_group_lane, resume_group
from wqb.runtime_control import (_write, read_runtime_control, request_runtime_state,
    update_runtime_status, has_runtime_authority, utc_now)
from wqb.source_run_lock import read_source_run_lock
from wqb.research_retirement import retirement_boundary
from wqb.owned_network_deadline import (OwnedExecutionTree, OwnedSubmissionFence, JOB_ENV, NONCE_ENV,
    DEFAULT_REQUEST_TIMEOUT_SECONDS, SUPERVISION_POLL_SECONDS, TERMINATION_WAIT_SECONDS,
    hex_identity, positive_number)


LOCK_SECONDS = 10.0
LOCK_SLEEP = 0.05
SOURCE_MULTI_CHUNK_SLEEP_SECONDS = 20.0
POSITIVE_CONFIG = frozenset({'request_timeout_seconds', 'base_backoff_seconds', 'runtime_max_steps',
    'runtime_no_progress_limit', 'max_alphas_per_round', 'max_rounds', 'max_retries'})
ENUM_CONFIG = {'instrument_type': {'EQUITY'}, 'language': {'FASTEXPR'},
    'pasteurization': {'ON', 'OFF'}, 'nan_handling': {'ON', 'OFF'},
    'unit_handling': {'VERIFY'}, 'neutralization': {'NONE', 'MARKET', 'SECTOR', 'INDUSTRY', 'SUBINDUSTRY'},
    'ai_executor': {'codex'}}
TERMINAL = frozenset({'completed', 'completed_with_warnings', 'aborted'})
# Retain real handles/fences if termination cannot yet be proved. The lane entry
# stays alive in quarantine; it never acknowledges Stop by simply exiting.
_UNCONFIRMED_OWNERS = {}


def _safe(path) -> Path:
    """Input: absolute str/Path. Output: Path; reject traversal, links and junctions."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute non-traversing lifecycle path required')
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError('lifecycle paths cannot traverse links')
    return path.resolve()


def _group_path(group) -> Path:
    """Input: group dict or absolute path. Output: validated owning group Path."""
    return _safe(group['group_dir'] if isinstance(group, dict) else group)


def _guard_dispatch(group):
    """Input: group Path. Output: serialized launch context; independent of Stop intent."""
    return json_lock_transition_guard(group / 'worker_dispatch', LOCK_SECONDS, LOCK_SLEEP, 'group launch busy')


def _validate_prepared_resource_context(run: Path, knowledge: Path, snapshot: dict, state) -> None:
    """Input: member owner/vault Paths, frozen snapshot and state object/dict. Output: None; retired members are history, not active resource authority."""
    boundary = retirement_boundary(run)
    if boundary is None:
        validate_operational_exploration(run, knowledge, snapshot)
        return
    from wqb.execution_package import package_enabled, _digest as package_digest
    from wqb.execution_package_lifecycle import load_retired_summary
    if boundary.get('status') != 'retired' or not package_enabled(snapshot):
        raise ValueError('group member retirement evidence is damaged or unsupported')
    summary = load_retired_summary(run)
    status = state.get('status') if isinstance(state, dict) else state.status
    stage = state.get('current_stage') if isinstance(state, dict) else state.current_stage
    if (status != 'completed' or stage != 'complete'
            or summary['authority']['snapshot_sha256'] != package_digest(snapshot)):
        raise ValueError('retired group member differs from frozen completed owner')
    from wqb.exploration_eligibility import validate_exploration_snapshot
    validate_exploration_snapshot(snapshot)


def _prepared(paths, group: Path) -> tuple[dict, list]:
    """Input: paths/group Path. Output: verified group and lane tuples; no runtime writes."""
    root = _safe(paths.run_root)
    if group.parent != root / 'research_groups':
        raise ValueError('group is outside owning runs root')
    row = read_group(group)
    members = row['lanes']
    if not members or len({l['run_id'] for l in members}) != len(members):
        raise ValueError('invalid frozen group membership')
    results = []
    for lane in members:
        run = _safe(root / lane['run_id'])
        for name in ('run_manifest.json', 'run_state.json', 'runtime_control.json', 'runtime_status.json'):
            _safe(run / name)
        manifest = _read(run / 'run_manifest.json')
        discovery = discover_group_lane(root, run)
        if discovery.state is None or discovery.diagnostics:
            raise ValueError('prepared lane state is inconsistent')
        if manifest.get('run_id') != run.name or _safe(manifest['knowledge_root']) != _safe(paths.knowledge_root):
            raise ValueError('prepared lane manifest identity mismatch')
        snapshot = manifest.get('start_snapshot')
        _validate_prepared_resource_context(run, paths.knowledge_root, snapshot, discovery.state)
        from wqb.workflow_stage_adapters import _snapshot_schedule_inputs
        _snapshot_schedule_inputs(snapshot, manifest['selected_option_id'], manifest['selected_scope'])
        receipts = snapshot['exploration_context']['receipts']
        # Certificates and group manifests intentionally use different JSON encodings.
        # Raw certification was verified above; compare plans in the group's encoding.
        if not receipts or any(_digest(r['compiler_input']['resources']) != lane['plan_digest'] for r in receipts):
            raise ValueError('prepared resources differ from frozen group plan')
        results.append((run, manifest, discovery.state))
    return row, results


def _read_only_retired(run: Path) -> bool:
    """Input: safe run Path. Output: bool; exempt only positively retired, identity-bound history."""
    boundary = retirement_boundary(run)
    if boundary is None:
        return False
    if boundary.get('status') != 'retired' or boundary.get('read_only') is not True:
        raise ValueError('damaged retirement evidence cannot permit a new group')
    manifest = _read(_safe(run / 'run_manifest.json'))
    state = _read(_safe(run / 'run_state.json'))
    if (manifest.get('run_id') != run.name or state.get('run_id') != run.name
            or _safe(state.get('run_dir', '')) != run):
        raise ValueError('retired mission identity evidence is incomplete or inconsistent')
    return True


def _exclusive(paths, row):
    """Input: paths/verified group dict. Output: None; refuse unrelated legacy/group activity."""
    root = _safe(paths.run_root)
    pointer = _safe(root / 'active_research_group.json')
    if pointer.exists() and _read(pointer) != {'group_id': row['group_id']}:
        raise ValueError('another research group is selected')
    active = _safe(root / 'active_run.json')
    if active.exists():
        saved = _read(active)
        run = _safe(saved.get('run_dir', ''))
        if run.parent != root or saved.get('run_id') != run.name:
            raise ValueError('invalid legacy active pointer')
        state = _read(_safe(run / 'run_state.json')) if (run / 'run_state.json').exists() else {}
        if not _read_only_retired(run) and state.get('status') not in TERMINAL:
            raise ValueError('unrelated active legacy mission; group cannot adopt or replace it')
    ids = {l['run_id'] for l in row['lanes']}
    for run in root.iterdir():
        if run.name in ids or not run.is_dir():
            continue
        run = _safe(run)
        if _read_only_retired(run):
            continue
        state_path = run / 'run_state.json'
        if state_path.exists() and _read(_safe(state_path)).get('status') not in TERMINAL:
            raise ValueError('unrelated active mission requires an explicit handoff')


def _validate_control(run, row):
    """Input: run Path/group dict. Output: existing control dict; reject widened or incomplete authority."""
    control = read_runtime_control(run)
    if (not has_runtime_authority(run) or control.get('invalid')
            or any(control.get(k) != v for k, v in row['authority'].items())
            or control.get('max_simulations') != DAILY_SIMULATION_LIMIT):
        raise ValueError('lane runtime authority differs from frozen group caps')
    return control


def initialize_group_runtime(paths, group) -> dict:
    """Input: paths object/group dict or Path. Output: group dict with paused new lane authority.

    All frozen states are validated before writing any intent. A durable new-run
    receipt permits interrupted initialization, never legacy adoption or usage reset.
    """
    group = _group_path(group)
    with _guard_dispatch(group):
        row, lanes = _prepared(paths, group)
        _exclusive(paths, row)
        for run, manifest, state in lanes:
            marker = _safe(run / 'runtime/group_initialization.json')
            control_path = run / 'runtime_control.json'
            status_path = run / 'runtime_status.json'
            binding = dict(group_id=row['group_id'], manifest_sha256=row['manifest_sha256'],
                           start_manifest_sha256=_digest(manifest))
            if marker.exists():
                if _read(marker) != binding:
                    raise ValueError('group initialization context changed')
            else:
                if (row['desired_state'] != 'paused' or control_path.exists() or status_path.exists()
                        or state.current_stage != 'objective_selected'
                        or not _initial_planning_stages_only(run, manifest)
                        or (run / 'runtime/original_batch_scope.json').exists()):
                    raise ValueError('only genuinely new prepared lanes can initialize')
                _write(marker, binding)
            if not status_path.exists():
                if control_path.exists():
                    raise ValueError('existing runtime is missing usage evidence')
                update_runtime_status(run, simulation_attempts=0, elapsed_seconds=0, recoveries_used=0)
            if not control_path.exists():
                if row['desired_state'] != 'paused':
                    raise ValueError('cannot initialize missing authority on running group')
                request_runtime_state(run, 'paused', expected_revision='', max_simulations=DAILY_SIMULATION_LIMIT,
                                      **row['authority'])
            control = _validate_control(run, row)
            if control.get('simulation_budget_mode') != 'daily':
                activate_daily_policy(run, control['request_revision'], 'Frozen research group ' + row['group_id'])
            _validate_control(run, row)
        # Publication is explicit and occurs only after every lane is fully ready.
        _exclusive(paths, row)
        _write(_safe(Path(paths.run_root) / 'active_research_group.json'), {'group_id': row['group_id']})
        return read_group(group)


def _initial_planning_stages_only(run: Path, manifest: dict) -> bool:
    """Input: prepared lane Path/manifest dict. Output: bool; only authenticated completed initial AI artifacts are new-run work."""
    from wqb.initial_research_planning import TASK_PATH, _load_task
    from wqb.ai_checkpoints import load_ai_checkpoints
    stages = _safe(run / 'stages')
    if not stages.exists():
        return True
    if {path.name for path in stages.iterdir()} != {'ai'}:
        return False
    directory = _safe(stages / 'ai')
    names = {'ai_checkpoints.jsonl', 'ai_checkpoint_events.jsonl', 'ai_checkpoint_runs', 'initial_model_guard.guard'}
    if any(path.name not in names or path.is_symlink() or path.is_junction() for path in directory.iterdir()):
        return False
    task = _load_task(_safe(run / TASK_PATH))
    if (task is None or task['status'] != 'completed' or task.get('attached_manifest') != manifest
            or task.get('result', {}).get('snapshot') != manifest['start_snapshot']):
        return False
    checkpoints = load_ai_checkpoints(directory)
    if len(checkpoints) != 1:
        return False
    checkpoint = checkpoints[0]
    if checkpoint.get('checkpoint_type') != 'initial_research_plan' or checkpoint.get('status') != 'completed':
        return False
    return all(checkpoint.get(key) == task.get('answer', {}).get(key) for key in ('summary', 'designs', 'tree'))


def sanitize_worker_config(config: dict) -> dict:
    """Input: untrusted runtime config dict. Output: scalar allowlist dict, never credentials/commands."""
    if not isinstance(config, dict):
        raise ValueError('worker config must be an object')
    clean = {}
    for key in POSITIVE_CONFIG:
        if key in config:
            value = config[key]
            if type(value) not in (int, float) or not 0 < value <= 1_000_000:
                raise ValueError('invalid numeric worker configuration')
            clean[key] = value
    for key, choices in ENUM_CONFIG.items():
        if key in config:
            if type(config[key]) is not str or config[key] not in choices:
                raise ValueError('invalid enumerated worker configuration')
            clean[key] = config[key]
    return clean


def _alive(pid):
    """Input: known int PID. Output: bool/None; never terminate an unknown process."""
    from wqb.console_progress import process_is_alive
    try:
        return process_is_alive(pid)
    except Exception:
        return None


def start_group_workers(paths, group, *, expected_revision, config, spawn_runner=subprocess.Popen) -> dict:
    """Input: paths/group, CAS revision str, config dict and Popen-compatible callable.

    Output: group dict plus durable workers list. Start resumes existing authority;
    uncertain launches are retained, not replayed. No global active-run mutation.
    """
    group = _group_path(group)
    clean = sanitize_worker_config(config)
    current = read_group(group)
    receipt_path = _safe(group / 'worker_start.json')
    prior = _read(receipt_path) if receipt_path.exists() else {}
    replay = (prior.get('expected_revision') == expected_revision
              and prior.get('request_revision') == current['request_revision']
              and current['desired_state'] == 'running')
    if current['request_revision'] != expected_revision and not replay:
        raise ValueError('stale group Start revision')
    initialize_group_runtime(paths, group)
    with _guard_dispatch(group):
        row, lanes = _prepared(paths, group)
        receipt_path = _safe(group / 'worker_start.json')
        prior = _read(receipt_path) if receipt_path.exists() else {}
        replay = (prior.get('expected_revision') == expected_revision
                  and prior.get('request_revision') == row['request_revision']
                  and row['desired_state'] == 'running')
        if not replay:
            # Write-ahead evidence makes a lost CAS acknowledgment recoverable.
            if row['request_revision'] != expected_revision:
                raise ValueError('stale group Start revision')
            planned_revision = uuid4().hex if row['desired_state'] != 'running' else row['request_revision']
            _write(receipt_path, dict(expected_revision=expected_revision,
                                     request_revision=planned_revision, status='starting'))
            if row['desired_state'] != 'running':
                row = resume_group(group, expected_revision, request_revision=planned_revision)
            _write(receipt_path, dict(expected_revision=expected_revision,
                request_revision=row['request_revision'], status='running'))
        workers = []
        for run, manifest, state in lanes:
            with _guard(group):
                current = read_group(group)
                if current['request_revision'] != row['request_revision'] or current['desired_state'] != 'running':
                    break
                control = _validate_control(run, row)
                if control['desired_state'] != 'running':
                    request_runtime_state(run, 'running', expected_revision=control['request_revision'])
            index = _safe(run / 'runtime/group_worker.json')
            old = _read(index) if index.exists() else {}
            if old:
                if old.get('group_id') != row['group_id'] or old.get('run_id') != run.name:
                    raise ValueError('worker ownership mismatch')
                alive = _alive(old['pid']) if type(old.get('pid')) is int else None
                if (old.get('status') in {'launching', 'unknown'}
                        or old.get('status') != 'cancelled' and alive is not False
                        or old.get('start_revision') == row['request_revision']):
                    workers.append(old)
                    continue
            lock = read_source_run_lock(run / 'runtime')
            if lock.get('status') not in {'none', 'released'}:
                if lock.get('status') != 'running' or _alive(lock.get('pid')) is not False:
                    workers.append(dict(run_id=run.name, status='existing_worker', lock=lock))
                    continue
            job_id = uuid4().hex
            job = _safe(run / 'runtime/group_workers' / job_id)
            job.mkdir(parents=True)
            worker_config = {**clean, **{k: manifest['selected_scope'][k] for k in ('region', 'universe', 'delay')},
                'knowledge_root': str(_safe(paths.knowledge_root)), 'bound_group_lane': str(run),
                'active_workflow_run_dir': str(run), 'managed_research_execution': True}
            _write(job / 'config.json', dict(config=worker_config, project_root=str(_safe(paths.project_root)),
                workflow_root=str(_safe(paths.workflow_root)), group_manifest_sha256=row['manifest_sha256']))
            worker = dict(group_id=row['group_id'], run_id=run.name, job_id=job_id,
                start_revision=row['request_revision'], status='launching', created_at=utc_now(),
                evidence_dir=str(job))
            _write(index, worker)
            _write(job / 'job.json', worker)
            argv = [sys.executable, '-m', 'wqb.research_group_driver', 'lane', '--run-dir', str(run),
                    '--group-dir', str(group), '--job-id', job_id]
            from wqb.desktop_application import packaged_worker_command
            argv = packaged_worker_command(argv)
            # Stop never waits for process launch. The child checks group intent before any step.
            if read_group(group)['desired_state'] != 'running':
                worker = {**worker, 'status': 'cancelled'}
            else:
                with (job / 'worker.log').open('ab') as log:
                    try:
                        process = spawn_runner(argv, cwd=str(_safe(paths.workflow_root)), stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT,
                            **({'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}))
                        if type(process.pid) is not int or process.pid <= 0:
                            raise ValueError('invalid spawn acknowledgment')
                        worker = {**worker, 'status': 'spawned', 'pid': process.pid}
                    except Exception:
                        # Exception messages may include environment credentials.
                        worker = {**worker, 'status': 'unknown', 'reason': 'spawn_acknowledgment_unknown'}
            _write(index, worker)
            _write(job / 'job.json', worker)
            workers.append(worker)
        return {**read_group(group), 'workers': workers}


def run_group_lane(paths, group, run_dir, *, config, step=None) -> dict:
    """Input: paths/group/run, sanitized config dict and optional offline step callable.

    Output: existing driver result dict. The verified tree dispatcher supplies source
    config patches; this adapter forwards them intact without preparing another plan.
    """
    group, run = _group_path(group), _safe(run_dir)
    row, lanes = _prepared(paths, group)
    if run not in [item[0] for item in lanes]:
        raise ValueError('lane is not a prepared member of this group')
    control = _validate_control(run, row)
    bound = {**sanitize_worker_config(config), 'bound_group_lane': str(run),
        'active_workflow_run_dir': str(run), 'knowledge_root': str(paths.knowledge_root),
        'run_root': str(_safe(paths.run_root)),
        'managed_research_execution': True}
    manifest = next(m for p, m, _ in lanes if p == run)
    bound.update({k: manifest['selected_scope'][k] for k in ('region', 'universe', 'delay')})
    if step is None:
        from wqb import cli
        from wqb.repair_runtime import RepairRuntimeExecutor
        from wqb.workflow_auto_continue import auto_continue_workflow
        live = control['enable_live_api'] and row['authority']['enable_live_api']
        def source_batch(run_config, metadata):
            """Input: authenticated tree config/metadata dicts. Output: existing field_batch result dict."""
            if Path(run_config['active_workflow_run_dir']).resolve() != run:
                raise ValueError('tree source callback lane identity mismatch')
            return cli.field_batch(run_config, field_search=str(metadata.get('field_search', '')),
                dataset_id=str(metadata.get('dataset_id', '')), template_mode=str(metadata.get('template_mode', 'economic')),
                workflow_stage=str(metadata.get('workflow_stage', 'scout')), exact_field_id=str(metadata.get('exact_field_id', '')),
                submit_mode='multi', multi_chunk_sleep_seconds=float(
                    metadata.get('multi_chunk_sleep_seconds') or SOURCE_MULTI_CHUNK_SLEEP_SECONDS))
        def complete(source):
            """Input: existing source path str. Output: existing source summary dict after reconciliation."""
            cli.complete_in_flight(bound, source)
            return cli.summarize_run_dir(source, paths.knowledge_root)
        def retry(source):
            """Input: existing source path str. Output: bounded retry summary dict, preserving identity."""
            cli.retry_planned(bound, source)
            return cli.summarize_run_dir(source, paths.knowledge_root)
        def step():
            """Input: closed-over lane authority/config. Output: next ordinary workflow step dict."""
            return auto_continue_workflow(paths, bound, utc_now(), enable_live_api=live,
                source_batch_runner=source_batch if live else None,
                complete_in_flight_runner=complete if live else None, retry_planned_runner=retry if live else None,
                repair_executor=RepairRuntimeExecutor(bound, enable_live_api=live) if live else None)
    from wqb.workflow_driver import run_workflow_driver
    return run_workflow_driver(paths, bound, step=step)


def _network_request(job, owner, now_func):
    """Input: job Path, owner dict, clock callable returning float. Output: validated request dict; fail closed."""
    path = _safe(job / 'network_current.json')
    if not path.exists():
        return {}
    row = _read(path)
    # A valid dispatch can be published during the read; sample the same injected clock afterwards.
    now = now_func()
    if (any(row.get(k) != owner[k] for k in ('owner_nonce', 'execution_pid', 'supervisor_pid'))
            or not hex_identity(row.get('request_id')) or row.get('state') not in {'entered', 'completed', 'transport_error'}
            or row.get('operation') not in {'request', 'authentication', 'simulation_submit'}
            or row.get('method') not in {'GET', 'POST', 'OPTIONS', 'HEAD', 'PUT', 'DELETE', 'PATCH', 'OTHER'}
            or not isinstance(row.get('simulation_identities'), list)
            or any(not hex_identity(v, 64) for v in row['simulation_identities'])):
        raise ValueError('owned request identity invalid')
    started, deadline = positive_number(row.get('started')), positive_number(row.get('deadline'))
    if (not owner['supervision_started'] <= started <= now or deadline <= started or deadline > owner['runtime_deadline']
            or deadline > started + owner['request_timeout_seconds']):
        raise ValueError('owned request deadline invalid')
    return row


def _confirm_tree(tree) -> bool:
    """Input: retained execution tree object. Output: bool; errors mean unconfirmed, never implicit fence release."""
    try:
        return tree.terminate_and_confirm() is True
    except Exception:
        return False


def _request_outcome(run, group, request):
    """Input: run/group Paths, authenticated request dict. Output: sanitized str; never alter reservation or WAL."""
    if request.get('operation') != 'simulation_submit':
        return 'not_submission'
    identities = request.get('simulation_identities') or []
    claims = _read(_safe(group.parent / 'simulation_reservations.json'))
    if identities and all(isinstance(claims.get(i), dict) and claims[i].get('run_id') == run.name
            and claims[i].get('group_id') == group.name and claims[i].get('submission_status') == 'sent'
            and type(claims[i].get('status_code')) is int and 200 <= claims[i]['status_code'] < 300
            and isinstance(claims[i].get('progress_url'), str) and claims[i]['progress_url'] for i in identities):
        return 'response_recorded_reconcile'
    return 'unknown'


def supervise_group_lane(paths, group, run_dir, *, config, spawn_runner=subprocess.Popen,
                         now_func=time.monotonic, sleep_func=time.sleep) -> dict:
    """Input: prepared paths/group/run, config dict, Popen/clock callables. Output: owned execution result dict.

    Retain OS containment handles throughout execution. A deadline/Stop never
    releases another worker's lease, refunds attempts, or replays an unknown POST.
    """
    group, run = _group_path(group), _safe(run_dir)
    row, lanes = _prepared(paths, group)
    if run not in [item[0] for item in lanes]:
        raise ValueError('supervised lane is not a prepared member')
    control = _validate_control(run, row)
    worker = _read(_safe(run / 'runtime/group_worker.json'))
    if (worker.get('pid') != os.getpid() or worker.get('status') != 'running'
            or not hex_identity(worker.get('job_id'))):
        raise ValueError('supervision requires the owning lane entry')
    job = _safe(run / 'runtime/group_workers' / worker['job_id'])
    if (job / 'network_owner.json').exists():
        raise ValueError('owned execution cannot be replayed')
    started = now_func()
    elapsed = float(control.get('elapsed_seconds', 0))
    group_elapsed = float(row['elapsed_seconds'])
    if row.get('active_since'):
        group_elapsed += max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(row['active_since'])).total_seconds())
    remaining = min(control['max_runtime_seconds'] - elapsed, row['authority']['max_runtime_seconds'] - group_elapsed)
    if row['desired_state'] != 'running' or control['desired_state'] != 'running':
        return dict(run_dir=str(run), runtime_status='paused', runtime_reason='user_paused')
    if remaining <= 0:
        return dict(run_dir=str(run), runtime_status='blocked', runtime_reason='runtime_budget_exhausted')
    clean = sanitize_worker_config(config)
    owner = dict(run_dir=str(run), job_id=job.name, supervisor_pid=os.getpid(), owner_nonce=uuid4().hex,
        supervision_started=started,
        runtime_deadline=started + remaining,
        request_timeout_seconds=positive_number(clean.get('request_timeout_seconds', DEFAULT_REQUEST_TIMEOUT_SECONDS)))
    argv = [sys.executable, '-m', 'wqb.research_group_driver', 'execute', '--run-dir', str(run),
        '--group-dir', str(group), '--job-id', job.name]
    from wqb.desktop_application import packaged_worker_command
    argv = packaged_worker_command(argv)
    environment = {**os.environ, JOB_ENV: str(job), NONCE_ENV: owner['owner_nonce'],
        'BRAIN_WORKFLOW_CONTROL_PATH': str(run)}
    tree = OwnedExecutionTree()
    request, reason, confirmed, exit_code, lease = {}, '', False, None, {}
    fence = OwnedSubmissionFence(run, job, owner)
    try:
        with (_safe(job / 'execution.log')).open('ab') as log:
            process = spawn_runner(argv, cwd=str(_safe(paths.workflow_root)), env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **tree.spawn_kwargs)
        tree.attach(process)
        owner['execution_pid'] = process.pid
        _write(_safe(job / 'network_owner.json'), owner)
        # The child cannot enter the driver until its retained tree is enrolled.
        _write(_safe(job / 'network_permit.json'), {'owner_nonce': owner['owner_nonce'], 'execution_pid': process.pid})
        while True:
            try:
                request = _network_request(job, owner, now_func)
            except (ValueError, OSError, TypeError):
                reason = 'owned_network_request_invalid'
                break
            current = read_group(group)
            # Read intent only: polling merged status can interfere with the
            # child's status/accounting publisher on Windows.
            intent = _read(_safe(run / 'runtime_control.json'))
            if current['desired_state'] != 'running' or intent['desired_state'] != 'running':
                reason = 'user_paused'
                break
            if current['request_revision'] != worker['start_revision']:
                reason = 'user_paused'
                break
            exit_code = tree.poll()
            if exit_code is not None:
                break
            if now_func() >= owner['runtime_deadline']:
                reason = 'runtime_budget_exhausted'
                break
            if request.get('state') == 'entered' and now_func() >= request['deadline']:
                # Re-read instead of killing from a stale projection at the deadline.
                latest = _network_request(job, owner, now_func)
                if latest == request:
                    reason = 'network_total_deadline_exceeded'
                    break
            fence.step()
            sleep_func(SUPERVISION_POLL_SECONDS)
        lease = read_source_run_lock(run / 'runtime')
        confirmed = _confirm_tree(tree)
    except Exception:
        reason = ('user_paused' if read_group(group)['desired_state'] != 'running'
            or _read(_safe(run / 'runtime_control.json'))['desired_state'] != 'running' else 'owned_lane_supervision_failed')
        lease = read_source_run_lock(run / 'runtime')
        confirmed = _confirm_tree(tree)
    finally:
        if confirmed:
            fence.release()
            tree.close()
        else:
            _UNCONFIRMED_OWNERS[str(job)] = (tree, fence)
    if not confirmed:
        reason = 'owned_network_termination_unconfirmed'
    # Only after the whole tree is dead may late response evidence be reconciled.
    try:
        request = _network_request(job, owner, now_func)
    except (ValueError, OSError, TypeError):
        pass
    outcome = _request_outcome(run, group, request)
    receipt = dict(termination_confirmed=confirmed, request_outcome=outcome,
        request_id=request.get('request_id', ''), owner_nonce=owner['owner_nonce'],
        execution_pid=owner.get('execution_pid'), reason=reason)
    _write(_safe(job / 'network_supervision.json'), receipt)
    if confirmed:
        from wqb.source_run_lock import release_source_run_lock
        lock = read_source_run_lock(run / 'runtime')
        if (lock.get('status') == 'running' and lock.get('pid') == owner.get('execution_pid')
                and lock.get('action') == 'workflow-driver' and lock == lease):
            release_source_run_lock(run / 'runtime', lock['action'], utc_now(),
                pid=owner['execution_pid'], owner_id=lock['owner_id'])
    result_path = _safe(job / 'execution_result.json')
    result = _read(result_path) if result_path.exists() else {}
    if not reason and exit_code == 0 and result.get('owner_nonce') == owner['owner_nonce']:
        return result['result']
    reason = reason or 'owned_lane_execution_failed'
    result = dict(run_dir=str(run), runtime_status='paused' if reason == 'user_paused' else 'blocked',
        runtime_reason=reason, next_action='maintenance-blocker', **{k: receipt[k] for k in
            ('termination_confirmed', 'request_outcome', 'request_id')})
    fields = dict(status=result['runtime_status'], reason=reason, last_result=result,
        elapsed_seconds=max(float(read_runtime_control(run).get('elapsed_seconds', 0)), elapsed + now_func() - started))
    update_runtime_status(run, **fields)
    if reason != 'user_paused':
        from wqb.recovery_cases import classify_blocker, ensure_recovery_case, advance_scripted_recovery
        from wqb.maintenance_notifications import dispatch_notification
        blocker = classify_blocker({**result, 'source_bridge': {'source_run_dir': str(run),
            'metadata': {'uncertain_submission_hashes': request.get('simulation_identities', [])
                if outcome == 'unknown' else []}}})
        case = ensure_recovery_case(run, blocker, utc_now())
        case = advance_scripted_recovery(run, case, clean, utc_now())
        update_runtime_status(run, recovery_case=case)
        case = dispatch_notification(run, case, utc_now())
        update_runtime_status(run, recovery_case=case)
    return result


def _execute_owned_lane(paths, group, run, job, config):
    """Input: validated lane paths/config. Output: int; wait for enrollment, then run the existing driver in-process."""
    from wqb.owned_network_deadline import authenticated_context
    if os.environ.get(JOB_ENV) != str(job) or not hex_identity(os.environ.get(NONCE_ENV)):
        raise ValueError('execute role requires an owning supervisor')
    end = time.monotonic() + TERMINATION_WAIT_SECONDS
    while not _safe(job / 'network_permit.json').exists():
        if time.monotonic() >= end:
            raise ValueError('owned execution enrollment timed out')
        time.sleep(SUPERVISION_POLL_SECONDS)
    context = authenticated_context()
    permit = _read(_safe(job / 'network_permit.json'))
    if context is None or permit != dict(owner_nonce=os.environ[NONCE_ENV], execution_pid=os.getpid()):
        raise ValueError('owned execution permit mismatch')
    result = run_group_lane(paths, group, run, config=config)
    _write(_safe(job / 'execution_result.json'), {'owner_nonce': os.environ[NONCE_ENV], 'result': result})
    return 0


def main(argv=None):
    """Input: optional argv list. Output: int exit code; execute only a recorded explicit lane job."""
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['lane', 'execute'])
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--group-dir', required=True)
    parser.add_argument('--job-id', required=True)
    args = parser.parse_args(argv)
    group, run = _group_path(args.group_dir), _safe(args.run_dir)
    if len(args.job_id) != 32 or any(c not in '0123456789abcdef' for c in args.job_id):
        raise ValueError('invalid worker job identity')
    if run.parent != group.parent.parent:
        raise ValueError('lane/group roots differ')
    from wqb.orchestrator import OrchestratorPaths
    job = _safe(run / 'runtime/group_workers' / args.job_id)
    saved = _read(job / 'config.json')
    config = saved['config']
    paths = OrchestratorPaths(project_root=_safe(saved['project_root']), workflow_root=_safe(saved['workflow_root']),
        knowledge_root=_safe(config['knowledge_root']), run_root=run.parent)
    if paths.workflow_root != Path(__file__).resolve().parents[1]:
        raise ValueError('worker package identity mismatch')
    row, _ = _prepared(paths, group)
    if saved['group_manifest_sha256'] != row['manifest_sha256'] or config['bound_group_lane'] != str(run):
        raise ValueError('worker frozen context mismatch')
    if args.command == 'execute':
        try:
            return _execute_owned_lane(paths, group, run, job, config)
        except Exception:
            # The ordinary driver retains its evidence. Never emit request
            # exception text (URLs/credentials/payloads) to the supervision log.
            return 1
    index = _safe(run / 'runtime/group_worker.json')
    with _guard_dispatch(group):
        worker = _read(index)
        if worker.get('job_id') != args.job_id or worker.get('status') not in {'launching', 'unknown', 'spawned'}:
            raise ValueError('worker job is not the current launch')
        current = read_group(group)
        if (current['desired_state'] != 'running'
                or worker.get('start_revision') != current['request_revision']):
            raise ValueError('worker launch superseded by newer group intent')
        worker = {**worker, 'pid': os.getpid(), 'status': 'running'}
        _write(index, worker)
        _write(job / 'job.json', worker)
    try:
        result = supervise_group_lane(paths, group, run, config=config)
        status = 'unknown' if result.get('termination_confirmed') is False else 'exited'
        _write(job / 'result.json', result)
    except Exception:
        status = 'failed'
        # Detailed workflow failures remain in the ordinary runtime evidence.
    with _guard_dispatch(group):
        worker = {**worker, 'status': status, 'finished_at': utc_now()}
        _write(job / 'job.json', worker)
        if _read(index).get('job_id') == args.job_id:
            _write(index, worker)
    quarantine = _UNCONFIRMED_OWNERS.get(str(job))
    if quarantine:
        tree, fence = quarantine
        while not _confirm_tree(tree):
            time.sleep(TERMINATION_WAIT_SECONDS)
        fence.release()
        tree.close()
        del _UNCONFIRMED_OWNERS[str(job)]
    return 0 if status == 'exited' else 1


if __name__ == '__main__':
    raise SystemExit(main())
