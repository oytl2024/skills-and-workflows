"""Explicit lossless history for closed original-batch recovery copies, never live knowledge."""

from contextlib import ExitStack
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid
import zipfile

from wqb.knowledge_clean_compile import _safe_local_path, _is_reference_owner
from wqb.lockfile import json_lock_transition_guard
from wqb.semantic_inventory_archive import _open, _identity, _unchanged, _publish_no_replace
from wqb.semantic_publication import _load


MAX_COPY_BYTES = 2 * 1024**3
MAX_COPY_FILES = 20000
MAX_METADATA_BYTES = 16 * 1024**2
MAX_SCAN_BYTES = 2 * 1024**3
MAX_SCAN_FILES = 10000
MAX_REFERENCE_CACHE_ENTRIES = 4096
MAX_REFERENCE_VALUE_CHARS = 512
MAX_SECONDS = 180.0
# Archival verifies the full reference set twice plus compression and round-trip hashes.
ARCHIVE_MAX_SECONDS = 600.0
CHUNK_BYTES = 1024 * 1024
LOCK_SECONDS = 1.0
COPY_PATH = re.compile(r'runtime/knowledge_recovery/[a-f0-9]{20}/knowledge\Z')
RETIRED_MARKER = 'copy_retirement.json'
ARCHIVE_NAME = 'historical_knowledge.zip'
CLOSED_ROUTING_COMMANDS = {
    'workflow-continue': ('workflow-continue',), 'workflow-status': ('workflow-status',),
    'workflow-resume': ('workflow-resume',),
    'workflow-auto-continue': ('workflow-auto-continue', 'workflow-run'),
    'workflow-start-from-option': ('workflow-start',), 'workflow-stop': ('workflow-pause',),
    'workflow-acknowledge-source-rate-limit': ('workflow-acknowledge-source-rate-limit',),
}


def _tick(deadline: float) -> None:
    """Input: monotonic deadline float. Output: None; refuse work exceeding its finite bound."""
    if time.monotonic() >= deadline:
        raise ValueError('recovery history time bound exceeded')


def _safe(root: Path, path: Path) -> Path:
    """Input: root/path Paths. Output: checked Path; refuse escapes, links and unusual files."""
    reason = _safe_local_path(root, path)
    if reason:
        raise ValueError('unsafe recovery history path: ' + reason)
    return path


def _relative(name: str) -> str:
    """Input: relative member str. Output: unchanged safe portable name, never an extraction directive."""
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or any(part in {'', '.', '..'} or part.rstrip(' .') != part
                   or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?', part)
                   for part in name.split('/'))):
        raise ValueError('invalid recovery history member path')
    return name


def _paths(run_dir: Path, copy_path: str) -> tuple:
    """Input: existing run Path/exact relative copy str. Output: contained run/copy/job Paths."""
    run = Path(os.path.abspath(run_dir))
    if run.parent.name != 'runs' or not run.is_dir():
        raise ValueError('explicit existing runs owner required')
    _safe(run.parent.parent, run)
    if not isinstance(copy_path, str) or not COPY_PATH.fullmatch(copy_path):
        raise ValueError('exact recovery knowledge copy path required')
    copy = _safe(run, run / copy_path)
    return run, copy, copy.parent


def recovery_history_guard(run_dir: Path):
    """Input: run Path. Output: OS guard context shared by recovery writers and archive preparation."""
    run = Path(os.path.abspath(run_dir))
    base = _safe(run, run / 'runtime/knowledge_recovery_history')
    _safe(run, Path(str(base) + '.guard'))
    return json_lock_transition_guard(base, LOCK_SECONDS, .02, 'recovery history busy')


def _raw(root: Path, path: Path, limit=MAX_METADATA_BYTES) -> bytes:
    """Input: boundary/file Paths, byte limit int. Output: pinned bounded exact bytes."""
    with _open(root, path) as stream:
        identity = _identity(os.fstat(stream.fileno()))
        if identity[2] > limit:
            raise ValueError('recovery metadata byte bound: ' + str(path))
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('recovery metadata byte bound: ' + str(path))
        _unchanged(root, path, stream, identity)
        return data


def _record(root: Path, path: Path) -> dict:
    """Input: boundary/file Paths. Output: strict bounded JSON object, not a status-only assertion."""
    value = _load(_raw(root, path))
    if not isinstance(value, dict):
        raise ValueError('recovery record must be an object: ' + str(path))
    return value


def _hash_file(root: Path, path: Path, deadline: float) -> dict:
    """Input: boundary/file Paths, deadline float. Output: exact SHA/size/mtime/mode descriptor dict."""
    with _open(root, path) as stream:
        info = os.fstat(stream.fileno())
        identity = _identity(info)
        if info.st_size > MAX_COPY_BYTES:
            raise ValueError('recovery file byte bound: ' + str(path))
        digest, size = hashlib.sha256(), 0
        while data := stream.read(CHUNK_BYTES):
            _tick(deadline)
            size += len(data)
            if size > MAX_COPY_BYTES:
                raise ValueError('recovery file byte bound: ' + str(path))
            digest.update(data)
        _unchanged(root, path, stream, identity)
    if size != info.st_size:
        raise ValueError('recovery file changed: ' + str(path))
    return dict(sha256=digest.hexdigest(), bytes=size, mtime_ns=info.st_mtime_ns,
                mode=stat.S_IMODE(info.st_mode))


def _walk(root: Path, base: Path, deadline: float, skip=None, diagnostics=None):
    """Input: boundary/base Paths, deadline float, optional skipped Path. Output: contained entries iterator."""
    if diagnostics is not None:
        diagnostics.update(phase='traversal', current_owner=str(base))
    _tick(deadline)
    _safe(root, base)
    if base == skip or not base.exists():
        return
    for path in base.iterdir():
        if diagnostics is not None:
            diagnostics.update(phase='traversal', current_owner=str(path))
        _tick(deadline)
        _safe(root, path)
        if path == skip:
            continue
        yield path
        if path.is_dir():
            yield from _walk(root, path, deadline, skip, diagnostics)


def _inventory(run: Path, copy: Path, deadline: float) -> dict:
    """Input: run/copy Paths and deadline. Output: bounded byte-bound files and exact directory mtimes."""
    if not copy.is_dir():
        raise ValueError('expanded recovery copy missing')
    files, directories, total, names = [], [], 0, set()
    for path in _walk(run, copy, deadline):
        name = _relative(path.relative_to(copy).as_posix())
        if name.casefold() in names:
            raise ValueError('ambiguous recovery member name')
        names.add(name.casefold())
        if len(names) > MAX_COPY_FILES:
            raise ValueError('recovery entry bound exceeded')
        if path.is_dir():
            directories.append(dict(path=name, mtime_ns=path.stat().st_mtime_ns))
        else:
            proof = _hash_file(run, path, deadline)
            total += proof['bytes']
            if total > MAX_COPY_BYTES:
                raise ValueError('recovery copy byte bound exceeded')
            files.append(dict(path=name, **proof))
    return dict(files=sorted(files, key=lambda row: row['path']),
                directories=sorted(directories, key=lambda row: row['path']),
                bytes=total, root_mtime_ns=copy.stat().st_mtime_ns)


def _latest_source_closed(workspace: Path, source: Path, deadline: float) -> list:
    """Input: source/workspace Paths and deadline float. Output: extra proof paths; reject newer unfinished attempts/checks."""
    from wqb.submission_attempts import uncertain_submission_hashes
    events = [_load(line) for line in _raw(workspace, source / 'simulation_events.jsonl').splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in events):
        raise ValueError('original simulation events must be objects')
    if uncertain_submission_hashes(events):
        raise ValueError('original source has an uncertain newer POST')
    pending = set()
    for row in events:
        _tick(deadline)
        identity, event = row.get('expression_hash'), row.get('event')
        if event in {'SUBMISSION_STARTED', 'SUBMITTED', 'SIMULATION_COMPLETED', 'CHECK_PENDING', 'PROGRESS_WAIT'}:
            pending.add(identity)
        elif event in {'CHECKED', 'ERROR', 'SUBMISSION_REJECTED', 'LOCAL_SUBMISSION_REJECTED'}:
            pending.discard(identity)
    if pending:
        raise ValueError('original source has newer unfinished simulation or checks')
    paths = []
    for relative in ('pending_checks', 'pending_checks.json', 'stages/backtest/check_recovery.json',
                     'progress_wait.json', 'result_unknown.json'):
        path = _safe(workspace, source / relative)
        if not path.exists():
            continue
        candidates = ([child for child in _walk(workspace, path, deadline) if child.is_file()]
                      if path.is_dir() else [path])
        for child in candidates:
            if child.suffix != '.json' or _record(workspace, child).get('status') not in {'completed', 'resolved'}:
                raise ValueError('original source has unresolved recovery evidence: ' + str(child))
            paths.append(child)
    return paths


def _closure(run: Path, copy: Path, job: Path, deadline: float) -> tuple:
    """Input: exact owner/copy/job Paths and deadline. Output: original receipt plus immutable closure byte proofs."""
    from wqb.original_batch_recovery import read_original_batch, _inventory as original_inventory
    from wqb.runtime_control import has_runtime_authority
    workspace = run.parent.parent
    state = _record(run, run / 'run_state.json')
    status = _record(run, run / 'runtime_status.json')
    control = _record(run, run / 'runtime_control.json')
    if not isinstance(status.get('last_result'), dict):
        raise ValueError('original-batch terminal result missing')
    if (state.get('status') not in {'aborted', 'completed'} or status.get('status') != 'completed'
            or status.get('last_result', {}).get('status') != 'completed'
            or status.get('last_result', {}).get('next_action') != 'original-batch-complete'):
        raise ValueError('owning run is active, paused or original-batch closure is unknown')
    scope_path = run / 'runtime/original_batch_scope.json'
    scope = _record(run, scope_path)
    binding_path = run / 'stages/scout_seed/source_bridge_binding.json'
    binding = _record(run, binding_path)
    source = Path(scope.get('source_run_dir', ''))
    if (not source.is_absolute() or source.parent != run.parent or source == run
            or binding.get('source_run_dir') != str(source)):
        raise ValueError('unknown original source owner')
    _safe(workspace, source)
    owner_paths = [run / name for name in ('run_state.json', 'runtime_status.json', 'runtime_control.json')]
    checkpoint = run / 'run_state_checkpoint.json'
    if os.path.lexists(checkpoint):
        if _record(run, checkpoint) != state:
            raise ValueError('closed state checkpoint differs from owning state')
        owner_paths.append(checkpoint)
    owner_paths += [scope_path, binding_path]
    for folder in (run / 'runtime', source):
        path = folder / 'source_run_lock.json'
        if _record(workspace, path).get('status') != 'released' or os.path.lexists(folder / 'source_run_lock.acquire'):
            raise ValueError('active or uncertain worker protects recovery copy')
        owner_paths.append(path)
    owner_paths.extend(_latest_source_closed(workspace, source, deadline))
    for name in ('planned_candidates.jsonl', 'simulation_events.jsonl', 'all_alphas.jsonl'):
        path = source / name
        for line in _raw(workspace, path).splitlines():
            if not line.strip():
                continue
            row = _load(line)
            if not isinstance(row, dict):
                raise ValueError('original source row must be an object: ' + str(path))
            if row.get('event') == 'SUBMISSION_STARTED' and any(
                    not isinstance(row.get(key), str) or not row[key] for key in ('attempt_id', 'expression_hash')):
                raise ValueError('uncertain submission identity in original evidence')
        owner_paths.append(path)
    try:
        verified_scope = read_original_batch(run)
        if not verified_scope or not has_runtime_authority(run):
            raise ValueError('invalid original frozen authority')
        plan, submitted, done = original_inventory(source)
    except RuntimeError as error:
        raise ValueError('original closure: ' + str(error)) from error
    ids = [row.get('expression_hash') for row in plan]
    if (not plan or any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids)
            or len(plan) != scope.get('original_count') or set(ids) != done or submitted - done
            or scope.get('new_research_allowed') is not False
            or control.get('original_batch_scope_id') != scope.get('scope_id')):
        raise ValueError('original batch has unfinished identities or ambiguous authority')
    for name, maximum in (('simulation_attempts', 'max_simulations'), ('recovery_attempts', 'max_recoveries')):
        used = status.get(name)
        if type(used) is not int or not 0 <= used <= control[maximum]:
            raise ValueError('original accounting missing or invalid')
    elapsed = status.get('elapsed_seconds')
    if type(elapsed) not in (int, float) or not 0 <= elapsed <= control['max_runtime_seconds']:
        raise ValueError('original elapsed accounting missing or invalid')
    receipt_path = job / 'receipt.json'
    receipt = _record(run, receipt_path)
    captured = datetime.fromisoformat(receipt['generated_at'].replace('Z', '+00:00'))
    if (receipt.get('phase') != 'finished' or receipt.get('status') not in {'blocked', 'completed'}
            or receipt.get('knowledge_root') != str(copy) or receipt.get('effective_root') != str(copy)
            or receipt.get('receipt_path') != str(receipt_path) or captured.tzinfo is None
            or receipt.get('scope') != {name: scope['settings'][name] for name in ('region', 'delay', 'universe')}):
        raise ValueError('recovery receipt is incomplete or scope/identity differs')
    owner_paths.append(receipt_path)
    if not isinstance(receipt.get('evidence'), dict):
        raise ValueError('original recovery evidence missing')
    sources = receipt['evidence'].get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError('original recovery sources missing')
    for name in sources:
        path = Path(name)
        if not path.is_absolute() or not path.is_relative_to(job / 'sources'):
            raise ValueError('unknown recovery source owner')
        owner_paths.append(path)
    proofs = {path.relative_to(workspace).as_posix(): _hash_file(workspace, path, deadline)['sha256']
              for path in owner_paths}
    return receipt, proofs


def _reference_context(workspace: Path, owner: Path, copy: Path) -> tuple:
    """Input: workspace/owner/copy Paths. Output: per-owner lexical origins, routing rules and bounded negative cache."""
    origins = [workspace, workspace / 'knowledge', owner.parent]
    origins += [path for path in owner.parents if path.name == 'knowledge']
    if owner.is_relative_to(workspace / 'runs'):
        origins.append(workspace / 'runs' / owner.relative_to(workspace / 'runs').parts[0])
    routing = {str(workspace), str(workspace / 'knowledge')}
    ancestors = {os.path.normcase(str(path)) for path in copy.parents}
    target = os.path.normcase(str(copy))
    simple_names = {os.path.normcase(path.name) for path in (copy, *copy.parents)} | {'.', '..'}
    inside = any(origin.is_relative_to(copy) for origin in origins)
    return (list(dict.fromkeys(origins)), routing, ancestors, target, {}, copy.parents[3], owner,
            simple_names, os.path.normcase(copy.name), inside)


def _refers(value, workspace: Path, owner: Path, copy: Path, deadline: float, *, context=None) -> bool:
    """Input: JSON value, owner/target Paths, deadline and optional context tuple. Output: unchanged dependency bool."""
    (origins, routing, ancestors, target, cache, run, owner,
     simple_names, target_component, inside) = context or _reference_context(workspace, owner, copy)
    values = [(value, '')]
    while values:
        _tick(deadline)
        item, key = values.pop()
        if isinstance(item, dict):
            values.extend((name, '') for name in item)
            values.extend((child, name) for name, child in item.items())
        elif isinstance(item, list):
            values.extend((child, '') for child in item)
        elif isinstance(item, str) and item and '\n' not in item and '\x00' not in item:
            if not any(mark in item for mark in ('/', '\\', ':')) and os.path.normcase(item) not in simple_names:
                continue
            cache_key = (item, key)
            if cache_key in cache:
                continue
            normalized = os.path.normcase(os.path.normpath(item))
            components = normalized.replace('\\', '/').split('/')
            # An outside origin cannot reach this subtree without its final directory component.
            # Ancestor selectors remain possible only when their normalized terminal name matches.
            if not inside and target_component not in components and os.path.basename(normalized) not in simple_names:
                if (len(cache) < MAX_REFERENCE_CACHE_ENTRIES and len(item) <= MAX_REFERENCE_VALUE_CHARS
                        and len(key) <= MAX_REFERENCE_VALUE_CHARS):
                    cache[cache_key] = False
                continue
            for origin in origins:
                path = Path(os.path.abspath(os.path.join(origin, item)))
                if key in {'root', 'knowledge_root'} and str(path) in routing:
                    continue
                if (key == 'run_dir' and owner in {run / 'run_state.json', run / 'runtime_status.json',
                                                  run / 'run_state_checkpoint.json'}
                        and path == run):
                    continue
                text = os.path.normcase(str(path))
                if text in ancestors or text == target or text.startswith(target + os.sep):
                    return True
            if (len(cache) < MAX_REFERENCE_CACHE_ENTRIES and len(item) <= MAX_REFERENCE_VALUE_CHARS
                    and len(key) <= MAX_REFERENCE_VALUE_CHARS):
                cache[cache_key] = False
    return False


def _closed_job_routing(value: object, workspace: Path, owner: Path, closed_run: Path) -> object:
    """Input: parsed owner and Paths. Output: reference view with only verified exited CLI routing arguments removed."""
    if (not isinstance(value, dict) or owner.name != 'job.json'
            or owner.parent.parent != workspace / 'runs/console_jobs'
            or type(value.get('exit_code')) is not int
            or not (value.get('status') in {'completed', 'paused', 'blocked'} and value['exit_code'] == 0
                    or value.get('status') == 'failed' and value['exit_code'] != 0)
            or value.get('job_id') != owner.parent.name
            or os.path.normcase(os.path.abspath(str(value.get('job_dir', '')))) != os.path.normcase(str(owner.parent))):
        return value
    command, action = value.get('command'), value.get('action')
    allowed_commands = CLOSED_ROUTING_COMMANDS.get(action, ())
    modules = ['wqb.cli'] + (['wqb.console_start'] if action == 'workflow-start-from-option' else [])
    if (not allowed_commands or not isinstance(command, list) or len(command) < 4
            or any(type(item) is not str for item in command)
            or command[1] not in {'-m', '--worker-module'} or command[2] not in modules
            or command[3] not in allowed_commands):
        return value
    try:
        completed_at = value.get('finished_at') or value.get('updated_at')
        if datetime.fromisoformat(completed_at.replace('Z', '+00:00')).tzinfo is None:
            return value
    except (KeyError, TypeError, ValueError, AttributeError):
        return value
    roots = {'--run-dir': workspace / 'runs', '--knowledge-root': workspace / 'knowledge'}
    projected = list(command)
    for index in range(4, len(command) - 1):
        root = roots.get(command[index])
        if root is not None and os.path.normcase(os.path.abspath(command[index + 1])) == os.path.normcase(str(root)):
            projected[index + 1] = '<routing-root>'
    cwd = value.get('cwd')
    if isinstance(cwd, str) and os.path.normcase(os.path.abspath(cwd)) == os.path.normcase(str(workspace)):
        cwd = '<routing-root>'
    metadata = value.get('metadata')
    if isinstance(metadata, dict) and isinstance(metadata.get('run_dir'), str):
        selected = os.path.normcase(os.path.abspath(metadata['run_dir']))
        if selected == os.path.normcase(str(closed_run)):
            metadata = dict(metadata, run_dir='<closed-owner-routing>')
    return dict(value, command=projected, cwd=cwd, metadata=metadata)


def _cancelled_start_routing(value: object, workspace: Path, owner: Path, closed_run: Path) -> object:
    """Input: parsed canonical Start receipt and Paths. Output: remove only cancelled closed-owner CAS routing identity."""
    if (owner != workspace / 'runs/console_start/request.json' or not isinstance(value, dict)
            or value.get('status') != 'cancelled' or not isinstance(value.get('request_id'), str)
            or not re.fullmatch('[a-f0-9]{32}', value['request_id'])):
        return value
    try:
        if datetime.fromisoformat(value['updated_at'].replace('Z', '+00:00')).tzinfo is None:
            return value
    except (KeyError, TypeError, ValueError, AttributeError):
        return value
    source = value.get('source_intent')
    if (not isinstance(source, dict) or not isinstance(source.get('run_dir'), str)
            or not isinstance(source.get('request_revision'), str) or not source['request_revision']
            or os.path.normcase(os.path.abspath(source['run_dir'])) != os.path.normcase(str(closed_run))):
        return value
    return dict(value, source_intent=dict(source, run_dir='<closed-owner-routing>'))


def _external_references(run: Path, copy: Path, receipt: dict, deadline: float, diagnostics=None,
                         historical_marker=None) -> dict:
    """Input: owner/copy/receipt and deadline. Output: checked external owner SHA map; uncertainty protects."""
    workspace, snapshots, total, count = run.parent.parent, {}, 0, 0
    knowledge = workspace / 'knowledge'
    state = diagnostics if diagnostics is not None else {}
    state.update(phase='traversal', current_owner='', bytes=0, entries=0, limiting_bound='')
    for base in (knowledge, workspace / 'runs'):
        for owner in _walk(workspace, base, deadline, skip=copy, diagnostics=state):
            if not owner.is_file() or owner.suffix.lower() not in {'.json', '.jsonl'}:
                continue
            if owner == copy.parent / 'receipt.json' or owner == historical_marker:
                continue
            if owner.is_relative_to(knowledge) and not _is_reference_owner(knowledge, owner):
                continue
            count += 1
            state.update(phase='owner_metadata', entries=count)
            if count > MAX_SCAN_FILES:
                state['limiting_bound'] = 'entries'
                raise ValueError('external reference entry bound: ' + str(owner))
            before = owner.stat()
            if before.st_size > MAX_SCAN_BYTES or total + before.st_size > MAX_SCAN_BYTES:
                state['limiting_bound'] = 'file_bytes' if before.st_size > MAX_SCAN_BYTES else 'total_bytes'
                raise ValueError('external reference byte bound: ' + str(owner))
            digest = hashlib.sha256()
            context = _reference_context(workspace, owner, copy)
            with _open(workspace, owner) as raw, io.BufferedReader(raw, buffer_size=CHUNK_BYTES) as stream:
                identity = _identity(os.fstat(stream.fileno()))
                consumed = 0
                while data := (stream.readline(MAX_METADATA_BYTES + 1) if owner.suffix.lower() == '.jsonl'
                               else stream.read(MAX_METADATA_BYTES + 1)):
                    state['phase'] = 'read_owner'
                    _tick(deadline)
                    consumed += len(data)
                    total += len(data)
                    state['bytes'] = total
                    if len(data) > MAX_METADATA_BYTES or total > MAX_SCAN_BYTES:
                        state['limiting_bound'] = 'line_or_json_bytes' if len(data) > MAX_METADATA_BYTES else 'total_bytes'
                        raise ValueError('external reference byte bound: ' + str(owner))
                    digest.update(data)
                    if not data.strip():
                        continue
                    value = _load(data)
                    if (owner.name == 'job.json' and owner.parent.parent == workspace / 'runs/console_jobs'
                            and isinstance(value, dict) and isinstance(value.get('cwd'), str)
                            and Path(value['cwd']).is_absolute() and value['cwd'] not in context[0]):
                        context[0].append(value['cwd'])
                    value = _closed_job_routing(value, workspace, owner, run)
                    value = _cancelled_start_routing(value, workspace, owner, run)
                    if owner == workspace / 'runs/daily_simulation_budget/policy.json':
                        from wqb.daily_simulation_budget import _load as load_budget_store
                        policy, _ = load_budget_store(owner.parent)
                        if value != policy:
                            raise ValueError('daily policy changed during reference scan')
                        value = {name: child for name, child in value.items() if name != 'runs_root'}
                    state['phase'] = 'reference_values'
                    if (owner == run / 'runtime_status.json' and isinstance(value, dict)
                            and value.get('knowledge_recovery') == receipt):
                        value = {name: child for name, child in value.items() if name != 'knowledge_recovery'}
                    if (owner == run / 'runtime/source_run_lock.json' and isinstance(value, dict)
                            and value.get('status') == 'released' and value.get('run_id') == owner.parent.name):
                        # The owning lease names its lock container, not a data directory.
                        # Retain all other fields so actual resource references still protect.
                        value = {name: child for name, child in value.items() if name != 'run_id'}
                    if (owner.name == RETIRED_MARKER and owner.parent.parent == run / 'runtime/knowledge_recovery'
                            and COPY_PATH.fullmatch(owner.parent.relative_to(run).as_posix() + '/knowledge')):
                        sibling = _history(run, owner.parent.relative_to(run).as_posix() + '/knowledge', deadline)
                        if value != sibling:
                            raise ValueError('sibling recovery history changed while scanning')
                        value = {name: child for name, child in value.items() if name != 'run'}
                    if _refers(value, workspace, owner, copy, deadline, context=context):
                        raise ValueError('external recovery consumer: ' + str(owner))
                    if owner.suffix.lower() == '.json':
                        break
                _unchanged(workspace, owner, stream, identity)
                if consumed != identity[2]:
                    raise ValueError('external owner read incomplete: ' + str(owner))
            snapshots[owner.relative_to(workspace).as_posix()] = digest.hexdigest()
    return snapshots


def _check_proofs(run: Path, proofs: dict, deadline: float, diagnostics=None) -> None:
    """Input: run Path/relative SHA map/deadline. Output: None; reject changed original evidence."""
    workspace = run.parent.parent
    for name, expected in proofs.items():
        path = workspace / _relative(name)
        if diagnostics is not None:
            diagnostics.update(phase='revalidate', current_owner=str(path))
        if _hash_file(workspace, path, deadline)['sha256'] != expected:
            raise ValueError('original recovery evidence changed: ' + str(path))


def audit_recovery_copy_retirement(run_dir: Path, copy_path: str) -> dict:
    """Input: exact run/copy selector. Output: read-only bounded feasibility dict, never collection authority."""
    result = dict(disposition='protected', candidate_path='', execution_authorized=False,
                  source_certified=False, archival_history=True, reasons=[], reference_scan={})
    scan_started = None
    try:
        deadline = time.monotonic() + MAX_SECONDS
        run, copy, job = _paths(run_dir, copy_path)
        result['candidate_path'] = str(copy)
        marker = _history(run, copy_path, deadline) if os.path.lexists(job / RETIRED_MARKER) else None
        receipt, proofs = _closure(run, copy, job, deadline)
        inventory = _inventory(run, copy, deadline) if copy.exists() else marker['manifest'] if marker else None
        if inventory is None or marker and inventory != marker['manifest']:
            raise ValueError('expanded recovery copy missing or differs from retired evidence')
        result.update(file_count=len(inventory['files']), bytes=inventory['bytes'])
        result['expanded_copy_present'] = copy.exists()
        scan_started = time.monotonic()
        snapshots = _external_references(run, copy, receipt, deadline, result['reference_scan'],
                                         job / RETIRED_MARKER if marker else None)
        if marker:
            snapshots[(job / RETIRED_MARKER).relative_to(run.parent.parent).as_posix()] = hashlib.sha256(_json_bytes(marker)).hexdigest()
        _check_proofs(run, dict(proofs, **snapshots), deadline, result['reference_scan'])
        result['disposition'] = 'archived_history' if marker else 'archive_candidate'
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        result['reasons'].append(type(error).__name__ + ': ' + str(error)[:512])
        if scan_started is not None and time.monotonic() >= deadline:
            result['reference_scan']['limiting_bound'] = 'time_seconds'
    if scan_started is not None:
        result['reference_scan']['elapsed'] = time.monotonic() - scan_started
    return result


def _json_bytes(value: dict) -> bytes:
    """Input: JSON dict. Output: deterministic UTF-8 bytes binding manifests and markers."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def _verify_archive(run: Path, marker: dict, deadline: float) -> None:
    """Input: run/marker/deadline. Output: None; verify exact ZIP namespace, lengths and every member SHA."""
    manifest = marker['manifest']
    files, directories = manifest['files'], manifest['directories']
    if (not isinstance(files, list) or not isinstance(directories, list)
            or len(files) + len(directories) > MAX_COPY_FILES
            or type(manifest['bytes']) is not int or not 0 <= manifest['bytes'] <= MAX_COPY_BYTES):
        raise ValueError('invalid recovery archive manifest')
    names = [_relative(row['path']).casefold() for row in files + directories]
    if len(names) != len(set(names)):
        raise ValueError('ambiguous recovery archive manifest paths')
    try:
        stack, path, stream, archive, identity = _archive_reader(run, marker, deadline)
        with stack:
            expected = {'manifest.json'} | {'knowledge/' + _relative(row['path']) for row in manifest['files']}
            infos = archive.infolist()
            if (len(infos) != len(expected) or {info.filename for info in infos} != expected
                    or len(infos) > MAX_COPY_FILES + 1 or sum(info.file_size for info in infos) > MAX_COPY_BYTES + MAX_METADATA_BYTES):
                raise ValueError('recovery archive member/size mismatch')
            meta = archive.getinfo('manifest.json')
            if meta.file_size > MAX_METADATA_BYTES or archive.read(meta) != _json_bytes(manifest):
                raise ValueError('recovery archive manifest mismatch')
            total = 0
            for row in manifest['files']:
                info = archive.getinfo('knowledge/' + row['path'])
                if info.file_size != row['bytes'] or row['bytes'] < 0:
                    raise ValueError('recovery archive member size mismatch')
                digest, size = hashlib.sha256(), 0
                with archive.open(info) as member:
                    while data := member.read(CHUNK_BYTES):
                        _tick(deadline)
                        digest.update(data)
                        size += len(data)
                        total += len(data)
                        if total > MAX_COPY_BYTES or size > row['bytes']:
                            raise ValueError('recovery archive expansion bound')
                if size != row['bytes'] or digest.hexdigest() != row['sha256']:
                    raise ValueError('recovery archive member hash mismatch')
            if total != manifest['bytes']:
                raise ValueError('recovery archive total mismatch')
            _unchanged(run, path, stream, identity)
    except (zipfile.BadZipFile, RuntimeError, EOFError) as error:
        raise ValueError('invalid recovery archive') from error


def _archive_reader(run: Path, marker: dict, deadline: float) -> tuple:
    """Input: owner/marker/deadline. Output: owned ExitStack and ZIP pinned to its exact compressed hash."""
    stack = ExitStack()
    try:
        path = run / _relative(marker['archive_ref']['path'])
        stream = stack.enter_context(_open(run, path))
        identity = _identity(os.fstat(stream.fileno()))
        if identity[2] > MAX_COPY_BYTES:
            raise ValueError('recovery archive compressed byte bound')
        digest, size = hashlib.sha256(), 0
        while data := stream.read(CHUNK_BYTES):
            _tick(deadline)
            size += len(data)
            if size > MAX_COPY_BYTES:
                raise ValueError('recovery archive compressed byte bound')
            digest.update(data)
        if digest.hexdigest() != marker['archive_ref']['sha256']:
            raise ValueError('recovery archive hash mismatch')
        _unchanged(run, path, stream, identity)
        stream.seek(0)
        end = zipfile._EndRecData(stream)
        if (end is None or end[zipfile._ECD_ENTRIES_TOTAL] > MAX_COPY_FILES + 1
                or end[zipfile._ECD_SIZE] > MAX_METADATA_BYTES):
            raise ValueError('recovery ZIP directory bound exceeded')
        stream.seek(0)
        archive = stack.enter_context(zipfile.ZipFile(stream))
        return stack, path, stream, archive, identity
    except BaseException:
        stack.close()
        raise


def _publish_marker(path: Path, marker: dict) -> None:
    """Input: exact marker Path/dict. Output: None; reuse immutable publication, never rewrite original receipts."""
    from wqb.knowledge_contracts import _write_immutable_source
    _write_immutable_source(path, _json_bytes(marker))


def _history(run: Path, copy_path: str, deadline: float) -> dict:
    """Input: run/exact selector/deadline. Output: validated historical marker; no live-source certification."""
    try:
        return _read_history(run, copy_path, deadline)
    except (KeyError, TypeError, AttributeError, zipfile.BadZipFile) as error:
        raise ValueError('malformed recovery retirement evidence') from error


def _read_history(run: Path, copy_path: str, deadline: float) -> dict:
    """Input: historical selector/deadline. Output: exact marker after schema, owner and archive verification."""
    run, copy, job = _paths(run, copy_path)
    marker = _record(run, job / RETIRED_MARKER)
    if (set(marker) != {'schema_version', 'kind', 'run', 'copy_path', 'archive_ref', 'manifest', 'evidence_refs',
                        'read_only', 'execution_authorized', 'source_certified'}
            or type(marker['schema_version']) is not int or marker['schema_version'] != 1
            or marker['kind'] != 'recovery_copy_retirement'
            or marker['run'] != str(run) or marker['copy_path'] != copy_path or marker['read_only'] is not True
            or marker['execution_authorized'] is not False or marker['source_certified'] is not False
            or marker['archive_ref']['path'] != job.relative_to(run).as_posix() + '/' + ARCHIVE_NAME):
        raise ValueError('invalid recovery retirement marker')
    if _closure(run, copy, job, deadline)[1] != marker['evidence_refs']:
        raise ValueError('retirement marker omits or changes original evidence bindings')
    _check_proofs(run, marker['evidence_refs'], deadline)
    _verify_archive(run, marker, deadline)
    if _raw(run, job / RETIRED_MARKER) != _json_bytes(marker):
        raise ValueError('recovery retirement marker changed or is not canonical')
    return marker


def retired_recovery_reference_view(run_dir: Path, copy_path: str, record: dict, deadline: float) -> tuple:
    """Input: owner/copy Paths, parsed marker and deadline. Output: live-reference view plus consumed dependency SHA map."""
    run = Path(os.path.abspath(run_dir))
    marker = _history(run, copy_path, min(deadline, time.monotonic() + MAX_SECONDS))
    if record != marker:
        raise ValueError('recovery archive marker changed during reference inspection')
    dependencies = {str(run.parent.parent / name): digest for name, digest in marker['evidence_refs'].items()}
    dependencies[str(run / marker['archive_ref']['path'])] = marker['archive_ref']['sha256']
    # Members are relative to the verified ZIP, never to the current global vault.
    view = {name: value for name, value in marker.items() if name != 'manifest'}
    return view, dependencies


def prepare_recovery_copy_retirement(run_dir: Path, copy_path: str) -> dict:
    """Input: exact closed copy selector. Output: immutable lossless-history marker; never removes expanded bytes."""
    run, copy, job = _paths(run_dir, copy_path)
    deadline = time.monotonic() + ARCHIVE_MAX_SECONDS
    with ExitStack() as guards:
        guards.enter_context(recovery_history_guard(run))
        _safe(run, run / 'runtime/control_intent.guard')
        guards.enter_context(json_lock_transition_guard(run / 'runtime/control_intent', LOCK_SECONDS, .02, 'intent busy'))
        if os.path.lexists(job / RETIRED_MARKER):
            return _history(run, copy_path, deadline)
        receipt, proofs = _closure(run, copy, job, deadline)
        manifest = _inventory(run, copy, deadline)
        snapshots = _external_references(run, copy, receipt, deadline)
        archive_path = _safe(run, job / ARCHIVE_NAME)
        marker = dict(schema_version=1, kind='recovery_copy_retirement', run=str(run), copy_path=copy_path,
            archive_ref=dict(path=archive_path.relative_to(run).as_posix(), sha256=''), manifest=manifest,
            evidence_refs=proofs, read_only=True, execution_authorized=False, source_certified=False)
        if not archive_path.exists():
            temporary = _safe(run, job / ('.archive-' + uuid.uuid4().hex + '.tmp'))
            created = False
            try:
                with temporary.open('xb') as stream:
                    created = True
                    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                        archive.writestr('manifest.json', _json_bytes(manifest))
                        for row in manifest['files']:
                            path = copy / row['path']
                            with _open(run, path) as source, archive.open('knowledge/' + row['path'], 'w', force_zip64=True) as member:
                                identity = _identity(os.fstat(source.fileno()))
                                while data := source.read(CHUNK_BYTES):
                                    _tick(deadline)
                                    member.write(data)
                                _unchanged(run, path, source, identity)
                    stream.flush()
                    os.fsync(stream.fileno())
                _publish_no_replace(temporary, archive_path)
            finally:
                if created and temporary.exists():
                    temporary.unlink()
        marker['archive_ref']['sha256'] = _hash_file(run, archive_path, deadline)['sha256']
        _verify_archive(run, marker, deadline)
        if _inventory(run, copy, deadline) != manifest or _closure(run, copy, job, deadline)[1] != proofs:
            raise ValueError('recovery copy or closure changed before retirement')
        _external_references(run, copy, receipt, deadline)
        _check_proofs(run, dict(proofs, **snapshots), deadline)
        _publish_marker(_safe(run, job / RETIRED_MARKER), marker)
        return marker


def retired_recovery_blocker(run_dir: Path) -> dict | None:
    """Input: run Path. Output: blocked historical/invalid-marker dict or None; never rehydrate or refetch."""
    run = Path(os.path.abspath(run_dir))
    base = run / 'runtime/knowledge_recovery'
    try:
        _safe(run, base)
        if not base.exists():
            return None
        for index, job in enumerate(base.iterdir()):
            if index >= MAX_COPY_FILES:
                raise ValueError('recovery owner scan bound exceeded')
            _safe(run, job)
            if job.is_dir() and os.path.lexists(job / RETIRED_MARKER):
                marker = _history(run, job.relative_to(run).as_posix() + '/knowledge', time.monotonic() + MAX_SECONDS)
                return dict(status='blocked', archival_history=True, read_only=True,
                    execution_authorized=False, source_certified=False, errors=[dict(error='retired recovery copy is historical only')],
                    retirement_path=str(job / RETIRED_MARKER), archive_ref=marker['archive_ref'])
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        return dict(status='blocked', archival_history=True, read_only=True,
                    errors=[dict(error='recovery history uncertain: ' + str(error)[:256])])
    return None


def read_retired_recovery_file(run_dir: Path, copy_path: str, member_path: str, *, max_bytes=MAX_METADATA_BYTES) -> bytes:
    """Input: exact historical selectors and explicit byte cap int. Output: original bytes, never a live resource."""
    name = _relative(member_path)
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_COPY_BYTES:
        raise ValueError('invalid historical read byte bound')
    run, copy, job = _paths(run_dir, copy_path)
    deadline = time.monotonic() + MAX_SECONDS
    marker = _history(run, copy_path, deadline)
    row = next((item for item in marker['manifest']['files'] if item['path'] == name), None)
    if row is None or row['bytes'] > max_bytes:
        raise ValueError('historical member missing or exceeds read bound')
    stack, path, stream, archive, identity = _archive_reader(run, marker, deadline)
    with stack:
        with archive.open('knowledge/' + name) as member:
            data = member.read(max_bytes + 1)
        _unchanged(run, path, stream, identity)
    if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
        raise ValueError('historical consumed bytes differ from archive proof')
    return data


def restore_retired_recovery_copy(run_dir: Path, copy_path: str, *, approval_reference: str) -> dict:
    """Input: exact selector and explicit history-only approval str. Output: isolated restored path, never active knowledge."""
    if not isinstance(approval_reference, str) or not approval_reference.strip() or len(approval_reference) > 512:
        raise ValueError('explicit historical restore approval required')
    run, copy, job = _paths(run_dir, copy_path)
    deadline = time.monotonic() + MAX_SECONDS
    with recovery_history_guard(run):
        marker = _history(run, copy_path, deadline)
        destination = _safe(run, job / ('historical_restore_' + marker['archive_ref']['sha256']))
        if destination.exists():
            if _inventory(run, destination, deadline) != marker['manifest']:
                raise ValueError('historical restore differs; no overwrite permitted')
            return dict(restored_path=str(destination), read_only=True, execution_authorized=False)
        stage = _safe(run, job / ('.restore-' + uuid.uuid4().hex))
        stage.mkdir()
        # Interrupted stages remain visibly isolated; never rename partial data into an active knowledge directory.
        stack, path, stream, archive, identity = _archive_reader(run, marker, deadline)
        with stack:
            for directory in marker['manifest']['directories']:
                _safe(run, stage / _relative(directory['path'])).mkdir(parents=True, exist_ok=True)
            for row in marker['manifest']['files']:
                _tick(deadline)
                target = _safe(run, stage / _relative(row['path']))
                target.parent.mkdir(parents=True, exist_ok=True)
                digest, size = hashlib.sha256(), 0
                with archive.open('knowledge/' + row['path']) as member, target.open('xb') as output:
                    while data := member.read(CHUNK_BYTES):
                        _tick(deadline)
                        size += len(data)
                        if size > row['bytes']:
                            raise ValueError('historical restore size exceeded')
                        digest.update(data)
                        output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                if size != row['bytes'] or digest.hexdigest() != row['sha256']:
                    raise ValueError('historical restore bytes differ')
                os.chmod(target, row['mode'])
                os.utime(target, ns=(row['mtime_ns'], row['mtime_ns']))
            _unchanged(run, path, stream, identity)
        for directory in sorted(marker['manifest']['directories'], key=lambda row: len(row['path']), reverse=True):
            target = stage / directory['path']
            os.utime(target, ns=(directory['mtime_ns'], directory['mtime_ns']))
        stamp = marker['manifest']['root_mtime_ns']
        os.utime(stage, ns=(stamp, stamp))
        if _inventory(run, stage, deadline) != marker['manifest']:
            raise ValueError('historical restore verification failed')
        _publish_no_replace(stage, destination)
        return dict(restored_path=str(destination), read_only=True, execution_authorized=False)
