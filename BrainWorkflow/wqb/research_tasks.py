"""Small durable task registry; isolate research intent while sharing workspace accounting."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import hashlib
from pathlib import Path
import re
from uuid import uuid4

from wqb.lockfile import json_lock_transition_guard
from wqb.runtime_control import _write


VERSION = 1
ID_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z')
TERMINAL = frozenset({'stopped', 'failed', 'stalled', 'awaiting_submission', 'completed_no_candidate'})
STATUSES = TERMINAL | {'accepted', 'preparing', 'planning', 'queued', 'running'}
SHANGHAI = timezone(timedelta(hours=8))


def _safe(path: Path) -> Path:
    """Input: storage Path. Output: absolute unlinked Path; never follow a task path outside its workspace."""
    path = Path(path).absolute()
    if '..' in path.parts or any(item.is_symlink() or item.is_junction() for item in (path, *path.parents)):
        raise ValueError('unsafe task storage path')
    return path


def _directory(root: Path, task_id: str) -> Path:
    """Input: workspace runs Path/task ID str. Output: contained task directory Path."""
    if not isinstance(task_id, str) or not ID_PATTERN.fullmatch(task_id):
        raise ValueError('invalid task identity')
    suffix = task_id.rsplit('_', 1)[-1]
    storage_key = suffix if re.fullmatch(r'[a-f0-9]{8}', suffix) else task_id
    return _safe(_safe(root) / 'research_tasks' / storage_key)


def read_task(root: Path, task_id: str) -> dict:
    """Input: workspace runs Path/task ID str. Output: validated independent task record dict."""
    directory = _directory(root, task_id)
    path = _safe(directory / 'task.json')
    if path.stat().st_size > 128_000:
        raise ValueError('task record exceeds storage bound')
    row = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(row, dict) or row.get('task_version') != VERSION or row.get('task_id') != task_id
            or row.get('status') not in STATUSES or row.get('runs_root') != str(directory / 'runs')):
        raise ValueError('invalid task record')
    return row


def list_tasks(root: Path) -> list[dict]:
    """Input: workspace runs Path. Output: most recent task records; never inspect historical run payloads."""
    directory = _safe(_safe(root) / 'research_tasks')
    if not directory.exists():
        return []
    rows = []
    for path in directory.iterdir():
        if not path.is_dir() or not ID_PATTERN.fullmatch(path.name) or not (path / 'task.json').exists():
            continue
        try:
            record = _safe(path / 'task.json')
            if record.stat().st_size > 128_000:
                raise ValueError('task record exceeds storage bound')
            rows.append(read_task(root, json.loads(record.read_text(encoding='utf-8'))['task_id']))
        except (OSError, ValueError, KeyError, TypeError):
            rows.append(dict(task_id='UNREADABLE_' + path.name, status='failed', reason='Task record unreadable; original outcomes remain unresolved.',
                created_at='', ended_at='', report_path='', selection={}, command_id=None, unreadable=True))
    return sorted(rows, key=lambda row: (row['created_at'], row['task_id']), reverse=True)


def create_task(root: Path, command_id: str, selection: dict) -> dict:
    """Input: workspace runs Path, command ID str, selection dict. Output: unique task; same command is idempotent."""
    root = _safe(root)
    if not isinstance(command_id, str) or not command_id or len(command_id) > 256 or not isinstance(selection, dict):
        raise ValueError('invalid task command/selection')
    json.dumps(selection, allow_nan=False)
    directory = _safe(root / 'research_tasks')
    directory.mkdir(parents=True, exist_ok=True)
    with json_lock_transition_guard(directory / 'create', 5, .02, 'task registration busy'):
        receipt = _safe(directory / '_commands' / (hashlib.sha256(command_id.encode()).hexdigest() + '.json'))
        if receipt.exists():
            prior = json.loads(receipt.read_text(encoding='utf-8'))
            if prior.get('selection') != selection or prior.get('command_id') != command_id:
                raise ValueError('task command payload conflict')
            return read_task(root, prior['task_id'])
        for row in list_tasks(root):
            if row['command_id'] == command_id:
                if row['selection'] != selection:
                    raise ValueError('task command payload conflict')
                return row
        scope = selection.get('scope') or {}
        def component(value):
            """Input: scope value. Output: bounded safe display component; unknown never becomes an invented scope."""
            return re.sub(r'[^A-Za-z0-9_-]', '_', str(value if value is not None else 'UNKNOWN'))[:40] or 'UNKNOWN'
        prefix = '_'.join((component(scope.get('region')), component(scope.get('universe')),
            'D' + component(scope.get('delay')), datetime.now(SHANGHAI).strftime('%Y%m%dT%H%M%S')))
        while True:
            task_id = prefix + '_' + uuid4().hex[:8]
            target = _directory(root, task_id)
            try:
                target.mkdir()
                break
            except FileExistsError:
                continue
        runtime = target / 'runs'
        runtime.mkdir()
        now = datetime.now(timezone.utc).isoformat()
        row = dict(task_version=VERSION, task_id=task_id, command_id=command_id,
            selection=deepcopy(selection), runs_root=str(runtime), status='accepted',
            created_at=now, updated_at=now, ended_at='', reason='', report_path='')
        _write(target / 'task.json', row)
        _write(receipt, dict(command_id=command_id, selection=selection, task_id=task_id))
        return row


def update_task(root: Path, task_id: str, **changes) -> dict:
    """Input: workspace Path/task ID/mutable state fields. Output: atomically updated task; terminal tasks cannot restart."""
    if set(changes) - {'status', 'reason', 'report_path', 'job_id', 'group_dir', 'report_error', 'report_recovery_generation'}:
        raise ValueError('task identity is immutable')
    directory = _directory(root, task_id)
    with json_lock_transition_guard(directory / 'update', 5, .02, 'task update busy'):
        row = read_task(root, task_id)
        status = changes.get('status', row['status'])
        if status not in STATUSES or (row['status'] in TERMINAL and status != row['status']):
            raise ValueError('invalid or terminal task transition')
        now = datetime.now(timezone.utc).isoformat()
        row.update(deepcopy(changes), updated_at=now)
        if status in TERMINAL and not row['ended_at']:
            row['ended_at'] = now
        _write(directory / 'task.json', row)
        return row


def task_runs_root(root: Path, task_id: str) -> Path:
    """Input: workspace runs Path/task ID. Output: verified task-local execution root Path."""
    return Path(read_task(root, task_id)['runs_root'])


def task_for_root(root: Path) -> tuple[Path, dict] | None:
    """Input: candidate runtime root Path. Output: workspace/task tuple or None for original legacy roots."""
    root = _safe(root)
    if root.name != 'runs' or root.parent.parent.name != 'research_tasks':
        return None
    workspace = root.parent.parent.parent
    identity = json.loads(_safe(root.parent / 'task.json').read_text(encoding='utf-8'))['task_id']
    row = read_task(workspace, identity)
    if row['runs_root'] != str(root):
        raise ValueError('task runtime ownership mismatch')
    return workspace, row


def canonical_runs_root(root: Path) -> Path:
    """Input: workspace/task runtime Path. Output: canonical shared accounting root, with no arbitrary redirect."""
    owner = task_for_root(root)
    return owner[0] if owner else _safe(root)


def task_paths(paths, task_id: str):
    """Input: ConsolePaths and task ID. Output: same product/vault/job paths with isolated intent/execution root."""
    root = canonical_runs_root(paths.runs_root)
    return replace(paths, runs_root=task_runs_root(root, task_id))
