"""Console adapter for independent tasks; reuse existing preparation and group drivers."""
import json
from datetime import datetime, timezone
from pathlib import Path
import threading
import time

from wqb.lockfile import json_lock_transition_guard
from wqb.research_tasks import (create_task, read_task, update_task, task_paths, task_for_root,
    canonical_runs_root, list_tasks, TERMINAL, _safe)
from wqb.research_task_report import publish_report


MONITOR_SECONDS = 2.0
_WATCHERS = set()
_WATCHER_LOCK = threading.Lock()


def enabled(paths) -> bool:
    """Input: ConsolePaths. Output: bool; only explicitly configured new Starts use task mode."""
    value = 0
    for filename in ('workflow_defaults.example.json', 'workflow_local.json'):
        try:
            row = json.loads((paths.configuration_root / 'configs' / filename).read_text(encoding='utf-8'))
            if isinstance(row, dict) and 'independent_tasks_version' in row:
                value = row['independent_tasks_version']
        except (OSError, ValueError, AttributeError):
            continue
    return type(value) is int and value == 1


def project_tasks(paths, state: dict, epoch: str, sequence: int, selected_task_id=None) -> dict:
    """Input: Console paths/state/sequence/optional selected task ID. Output: task summaries and selected task's existing view."""
    from wqb.console_api import project_application, _canonical
    from wqb.console_start import application_option, read_start_request, preparation_projection
    from wqb.console_state import load_runtime_state
    from datetime import datetime, timezone
    import hashlib
    root = canonical_runs_root(paths.runs_root)
    rows = list_tasks(root)
    selected = next((row for row in rows if row['task_id'] == selected_task_id), None) if selected_task_id else (rows[0] if rows else None)
    result = dict(schema_version=1, server_epoch=epoch, sequence=sequence,
        evidence_at=datetime.now(timezone.utc).isoformat(), request_revision='', task_mode=1,
        group=dict(group_id='none', status='idle', desired_state='paused'), lanes=[], blocker='',
        allowed_actions=dict(start=True, stop=False), start_mode='new', selected_task_id=None)
    if selected and selected.get('unreadable'):
        result.update(selected_task_id=selected['task_id'], blocker=selected['reason'])
    elif selected:
        scoped = task_paths(paths, selected['task_id'])
        detail = load_runtime_state(scoped)
        detail['option_cards'] = state.get('option_cards', [])
        view = project_application(scoped, detail, epoch, sequence)
        for key in ('group', 'lanes', 'preparation'):
            if key in view:
                result[key] = view[key]
        result['blocker'] = selected['reason'] or view.get('blocker', '')
        result['selected_task_id'] = selected['task_id']
        result['allowed_actions']['stop'] = selected['status'] not in TERMINAL
        request = read_start_request(scoped.runs_root)
        if request.get('status') in {'preparing', 'validating'}:
            preparation = preparation_projection(scoped, request)
            if preparation:
                result['preparation'] = preparation
    result['options'] = []
    for row in state.get('option_cards', []):
        if not isinstance(row, dict) or not row.get('option_id'):
            continue
        option = application_option(paths, row)
        option.update(startable=True, reason='')
        result['options'].append(option)
    result['tasks'] = [{key: row.get(key, '') for key in ('task_id', 'selection', 'status', 'reason', 'created_at',
        'ended_at', 'report_path', 'report_error', 'job_id')} for row in rows]
    result['request_revision'] = hashlib.sha256(_canonical([result['options'],
        selected['task_id'] if selected else None, selected.get('updated_at') if selected else None]).encode()).hexdigest()
    return result


def finish_task(paths, task_id: str, status: str, reason: str = '') -> dict:
    """Input: ConsolePaths/ID/terminal status/reason. Output: ended task with report or explicit local report failure."""
    root = canonical_runs_root(paths.runs_root)
    row = read_task(root, task_id)
    if row['status'] not in TERMINAL:
        row = update_task(root, task_id, status=status, reason=reason)
        from wqb.console_start import cancel_start
        try:
            cancel_start(Path(row['runs_root']))
        except Exception as error:
            row = update_task(root, task_id, reason=reason + '; Stop confirmation unavailable: ' + type(error).__name__)
    try:
        publish_report(root, task_id, paths.knowledge_root)
    except (OSError, ValueError, TypeError) as error:
        update_task(root, task_id, report_error=type(error).__name__ + ': ' + str(error))
    return read_task(root, task_id)


def start_task(paths, command: dict) -> dict:
    """Input: ConsolePaths/new Start command. Output: accepted task receipt; local preparation errors end only this task."""
    from wqb.console_start import application_start_form, application_option
    from wqb.console_server import _selected_option, _run_console_action_unlocked
    scope = command.get('selected_scope')
    if scope is None:
        try:
            scope = application_option(paths, _selected_option(paths, command['selected_option_id'])).get('scope')
        except (OSError, ValueError, KeyError, TypeError):
            scope = None
    selection = dict(selected_option_id=command.get('selected_option_id', ''), scope=scope or {})
    root = canonical_runs_root(paths.runs_root)
    row = create_task(root, command['command_id'], selection)
    scoped = task_paths(paths, row['task_id'])
    with json_lock_transition_guard(Path(row['runs_root']).parent / 'dispatch', 5, .02, 'task dispatch busy'):
        row = read_task(root, row['task_id'])
        if row.get('job_id') or row['status'] in TERMINAL:
            return dict(status='accepted', task_id=row['task_id'], job_id=row.get('job_id'), message=row['status'])
        try:
            form = application_start_form(scoped, command['selected_option_id'],
                **({'selected_scope': command['selected_scope']} if 'selected_scope' in command else {}))
            actual_scope = {key: form.get('selected_' + key) for key in ('region', 'universe', 'delay')}
            if scope and actual_scope != {key: scope.get(key) for key in ('region', 'universe', 'delay')}:
                raise ValueError('Selected scope changed during task acceptance; no research was dispatched')
            form.update(action='workflow-start-from-option', research_task_id=row['task_id'])
            update_task(root, row['task_id'], status='preparing')
            job = _run_console_action_unlocked(scoped, form, form['action'])
            update_task(root, row['task_id'], job_id=job.job_id)
            if job.status not in {'created', 'running', 'completed'}:
                finish_task(scoped, row['task_id'], 'failed', getattr(job, 'error', '') or 'Preparation failed')
        except Exception as error:
            finish_task(scoped, row['task_id'], 'failed', type(error).__name__ + ': ' + str(error))
    latest = read_task(root, row['task_id'])
    return dict(status='accepted', task_id=row['task_id'], job_id=latest.get('job_id'), message=latest['status'])


def stop_task(paths, task_id: str) -> dict:
    """Input: ConsolePaths/selected ID. Output: task-local Stop/report; retain unknown external work and shared accounting."""
    root = canonical_runs_root(paths.runs_root)
    ended = finish_task(paths, task_id, 'stopped', 'User stopped this task; unresolved external requests remain recorded.')
    return dict(status='accepted', task_id=task_id, message=ended['status'])


def complete_preparation(paths, job) -> None:
    """Input: task-local ConsolePaths/finished prep job. Output: None; route terminal failure or supervise owning group."""
    owner = task_for_root(paths.runs_root)
    if owner is None:
        return
    root, task = owner
    if read_task(root, task['task_id'])['status'] in TERMINAL:
        return
    from wqb.console_start import read_start_request
    request = read_start_request(paths.runs_root)
    if job.status != 'completed' or request.get('status') != 'completed' or not request.get('group_dir'):
        finish_task(paths, task['task_id'], 'failed', request.get('error') or getattr(job, 'error', '') or 'Preparation did not create a runnable group')
        return
    if request.get('group_dispatch', {}).get('status') != 'acknowledged':
        finish_task(paths, task['task_id'], 'failed', 'Group dispatch outcome unknown; task stopped without replaying external work.')
        return
    update_task(root, task['task_id'], status='running', group_dir=request['group_dir'])
    watch_task(paths, task['task_id'])


def refresh_task(paths, task_id: str) -> dict:
    """Input: ConsolePaths/ID. Output: task state from local group/runtime observations, no platform/model actions."""
    from wqb.research_group import read_group, stop_group
    root = canonical_runs_root(paths.runs_root)
    row = read_task(root, task_id)
    if row['status'] in TERMINAL:
        if not row.get('report_path'):
            return finish_task(paths, task_id, row['status'], row['reason'])
        return row
    if not row.get('group_dir'):
        if row.get('job_id'):
            from wqb.console_jobs import reconcile_job_dict, DEFAULT_TIMEOUT_SECONDS
            path = _safe(Path(paths.job_root) / row['job_id'] / 'job.json')
            job = reconcile_job_dict(json.loads(path.read_text(encoding='utf-8')), paths.knowledge_root)
            if job.get('status') == 'created':
                return finish_task(paths, task_id, 'failed', 'Preparation dispatch acknowledgement missing; no automatic replay.')
            if job.get('status') == 'running':
                started = job.get('started_at') or job.get('created_at') or row['created_at']
                if (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds() >= DEFAULT_TIMEOUT_SECONDS:
                    return finish_task(paths, task_id, 'stalled', 'Original preparation deadline exhausted; external outcomes remain recorded.')
            if job.get('status') not in {'created', 'running'}:
                from wqb.console_start import read_start_request
                request = read_start_request(Path(row['runs_root']))
                if job.get('status') == 'completed' and request.get('group_dir') and request.get('group_dispatch', {}).get('status') == 'acknowledged':
                    return update_task(root, task_id, status='running', group_dir=request['group_dir'])
                return finish_task(paths, task_id, 'failed', job.get('error') or 'Preparation owner ended; preserved outcome will not be replayed.')
        return row
    group = read_group(Path(row['group_dir']))
    observed = []
    for lane in group['lanes']:
        path = Path(row['runs_root']) / lane['run_id'] / 'runtime_status.json'
        if path.exists():
            observed.append(json.loads(path.read_text(encoding='utf-8')))
        worker_path = path.parent / 'runtime/group_worker.json'
        if worker_path.exists():
            worker = json.loads(worker_path.read_text(encoding='utf-8'))
            if worker.get('status') in {'failed', 'unknown'}:
                observed.append(dict(status='failed', reason='Lane process failed or execution outcome unknown'))
            elif worker.get('status') == 'exited' and (not path.exists() or observed[-1].get('status') not in {'completed', 'completed_with_warnings', 'waiting_for_user', 'blocked', 'failed'}):
                observed.append(dict(status='failed', reason='Lane process exited without a terminal research result'))
    failed = next((item for item in observed if item.get('status') in {'blocked', 'failed', 'aborted'}), None)
    waiting = next((item for item in observed if item.get('status') == 'waiting_for_user'), None)
    terminal = None
    if failed:
        terminal = ('stalled' if failed.get('reason') == 'no_progress_detected' else 'failed', failed.get('reason', 'Unresolved runtime fault'))
    elif waiting:
        stage = waiting.get('last_result', {}).get('current_stage')
        terminal = (('awaiting_submission', 'Research ended at its approval boundary; report retains actual qualification evidence.')
            if stage == 'user_approval' else ('failed', 'Unexpected approval boundary: ' + str(stage)))
    elif len(observed) == len(group['lanes']) and all(item.get('status') in {'completed', 'completed_with_warnings'} for item in observed):
        terminal = ('completed_no_candidate', 'All research lanes completed; see measured results and candidate checks.')
    else:
        elapsed = group['elapsed_seconds']
        if group.get('active_since'):
            elapsed += max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(group['active_since'])).total_seconds())
        if elapsed >= group['authority']['max_runtime_seconds']:
            terminal = ('stalled', 'Original group runtime deadline exhausted')
        elif group['desired_state'] == 'paused':
            terminal = ('failed', 'Group paused before a terminal research result')
    if terminal:
        return finish_task(paths, task_id, *terminal)
    return row


def watch_task(paths, task_id: str) -> None:
    """Input: ConsolePaths/ID. Output: None; one local observer per task, no recurring AI or server API polling."""
    key = (str(canonical_runs_root(paths.runs_root)), task_id)
    with _WATCHER_LOCK:
        if key in _WATCHERS:
            return
        _WATCHERS.add(key)
    def observe():
        """Input: none. Output: none; observe persisted state and end only this task on unresolved local error."""
        try:
            while refresh_task(paths, task_id)['status'] not in TERMINAL:
                time.sleep(MONITOR_SECONDS)
        except Exception as error:
            finish_task(paths, task_id, 'failed', 'Local task observer: ' + type(error).__name__ + ': ' + str(error))
        finally:
            with _WATCHER_LOCK:
                _WATCHERS.discard(key)
    threading.Thread(target=observe, name='research-task-' + task_id[-8:], daemon=True).start()


def restore_task_watchers(paths) -> None:
    """Input: ConsolePaths. Output: None; reattach local observers only, never restart preparation/model/platform work."""
    root = canonical_runs_root(paths.runs_root)
    for row in list_tasks(root):
        if row.get('unreadable'):
            continue
        if row['status'] in TERMINAL and row.get('report_path'):
            continue
        if row.get('job_id') or row.get('group_dir') or row['status'] in TERMINAL:
            watch_task(paths, row['task_id'])
        else:
            finish_task(paths, row['task_id'], 'failed', 'Interrupted task acceptance; no dispatch is automatically replayed.')
