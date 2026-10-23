"""Local JSON representation and command receipts, never a workflow authority.

Parent wiring: state_reader() returns current Console state; action_runner(command,
state) performs the existing authorized action, including its final intent/CAS gate.
It returns a dict with status accepted/refused/unknown or an existing job status,
optional job_id/message. Accepted means dispatch acknowledged, NOT action success.
No callback is retried after dispatch, including across server restarts.

Application identity is an existing group ID, legacy:<run_id>, or none (UI
sentinels only, never new runtime authority). Group dispatch uses the owning
driver's CAS, independently of the composite application revision. Recent durable command
replies are projected for read-only reconciliation; missing replies never replay.

The optional active_research_group.json pointer is {group_id: str}. It selects an
existing verified group, not membership or authority. experiment_tree.json and
seed_selection.json are optional read-only attachments; absence creates no tree,
qualification or migration. Existing legacy seed/progress/repair readers remain.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from wqb.lockfile import json_lock_transition_guard
from wqb.research_group import read_group
from wqb.strategy_progress import PROGRESS_FILES, load_strategy_progress


MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_COMMAND_BYTES = 8192
MAX_ROWS = 4096
MAX_LANES = 32
MAX_COMMAND_RECEIPTS = 128
SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
PATH_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
RECEIPT_PREFIX = 'application-command-'


def _canonical(value):
    """Input: JSON value. Output: str; require finite, serializable data."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _safe(root: Path, path: Path) -> Path:
    """Input: trusted root/target Paths. Output: absolute Path; reject escape and links."""
    root, path = Path(root).absolute(), Path(path).absolute()
    if '..' in path.parts or not path.is_relative_to(root):
        raise ValueError('artifact path escapes owning root')
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('linked artifact path is not permitted')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('resolved artifact path escapes owning root')
    return path


def _reject_constant(value):
    """Input: invalid JSON constant str. Output: raises ValueError; never fabricate metrics."""
    raise ValueError('nonfinite JSON evidence')


def _read(root: Path, relative: str, *, optional=False, lines=False):
    """Input: root/relative path and flags. Output: object/list or None; bound local reads."""
    path = _safe(root, root / relative)
    try:
        with path.open('rb') as handle:
            if os.fstat(handle.fileno()).st_size > MAX_ARTIFACT_BYTES:
                raise ValueError('artifact exceeds size limit: ' + relative)
            raw = handle.read(MAX_ARTIFACT_BYTES + 1)
    except FileNotFoundError:
        if optional:
            return None
        raise ValueError('missing artifact: ' + relative) from None
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ValueError('artifact exceeds size limit: ' + relative)
    try:
        text = raw.decode('utf-8-sig')
        value = ([json.loads(line, parse_constant=_reject_constant) for line in text.splitlines()
                  if line.strip()] if lines else json.loads(text, parse_constant=_reject_constant))
        _canonical(value)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('invalid JSON evidence: ' + relative) from None
    if lines:
        return _rows(value)
    if not isinstance(value, dict):
        raise ValueError('expected object evidence: ' + relative)
    return value


def _rows(value):
    """Input: potential row list. Output: list[dict]; reject malformed or excessive evidence."""
    if not isinstance(value, list) or len(value) > MAX_ROWS or any(not isinstance(r, dict) for r in value):
        raise ValueError('invalid or oversized evidence rows')
    return value


def _node(row: dict) -> dict:
    """Input: persisted evidence dict. Output: node dict; missing facts stay null/empty."""
    result = {key: row.get(key) for key in ('node_id', 'parent_id', 'layer', 'hypothesis',
              'expression', 'settings', 'alpha_id', 'signal', 'reason')}
    result['node_id'] = row.get('node_id') or row.get('expression_hash') or row.get('key') or row.get('alpha_id')
    result['metrics'] = row.get('metrics') if isinstance(row.get('metrics'), dict) else {}
    result['state'] = _text(row.get('state') or row.get('status'))
    result['reason'] = _reason(row.get('reason', row.get('failures')))
    result['layer'] = row.get('layer') if type(row.get('layer')) is int and row['layer'] >= 0 else None
    result['score'] = row.get('score', row.get('signal_score'))
    for key in ('condition', 'field_characteristics', 'sources', 'comparison', 'raw_signal', 'directional_signal'):
        if key in row:
            result[key] = row[key]
    return result


def _text(value) -> str:
    """Input: optional JSON value. Output: nonempty str or explicit unknown label."""
    return value if isinstance(value, str) and value else 'unknown'


def _reason(value) -> str | None:
    """Input: optional reason JSON. Output: readable str or None without inventing conclusions."""
    return value if isinstance(value, str) or value is None else _canonical(value)


def _identity(row: dict) -> str | None:
    """Input: evidence dict. Output: existing simulation identity str, if provided."""
    return row.get('simulation_identity') or row.get('expression_hash')


def _stable_id(kind: str, value) -> str:
    """Input: display kind str and immutable identity JSON. Output: namespaced stable display ID str."""
    return kind + ':' + hashlib.sha256(_canonical(value).encode()).hexdigest()


def _tree_nodes(run: Path, tree: dict, rows: list[dict]) -> list[dict]:
    """Input: run Path/frozen tree dict/progress rows. Output: pair nodes with actual arm evidence/routing."""
    if tree.get('schema_version') != 1 or tree.get('status') == 'rejected':
        raise ValueError('unsupported or rejected experiment tree')
    if tree.get('run_id', run.name) != run.name:
        raise ValueError('tree belongs to another run')
    execution = _read(run, 'runtime/tree_execution.json', optional=True) or {}
    if execution and (execution.get('run_id') != run.name or
                      execution.get('tree_digest') != tree.get('tree_digest')):
        raise ValueError('tree execution identity mismatch')
    # Only the owning engine decision records supply checked rows, never arbitrary root JSON.
    directory = _safe(run, run / 'runtime/research_plans')
    decisions = sorted(directory.glob('tree-decision-*.json'))
    if len(decisions) > MAX_ROWS:
        raise ValueError('too many tree decisions')
    evidence = list(rows)
    for path in decisions:
        decision = _read(run, path.relative_to(run).as_posix())
        if decision.get('tree_digest') != tree.get('tree_digest'):
            raise ValueError('tree decision identity mismatch')
        evidence.extend(_rows(decision.get('checked_rows', [])))
    raw_nodes = tree.get('tree', tree).get('nodes')
    if isinstance(raw_nodes, dict):
        raw_nodes = list(raw_nodes.values())
    nodes = []
    for raw in _rows(raw_nodes):
        route = execution.get('routes', {}).get(raw['node_id'], {})
        node = _node(raw)
        receipt = raw.get('pair_receipt') or {}
        drafts = _rows(receipt.get('drafts', []))
        if drafts:
            node['hypothesis'] = raw.get('hypothesis') or drafts[0].get('hypothesis')
            node['field_characteristics'] = (drafts[0].get('hypothesis_card') or {}).get('data_meaning')
        node['condition'] = (receipt.get('experiment') or {}).get('conditions')
        if route:
            node.update(state=_text(route.get('status')), signal=route.get('arm_states'),
                        reason=_reason(route.get('reasons')), comparison=execution.get('comparisons', {}).get(raw['node_id']))
        elif execution:
            node['state'] = 'queued' if raw['node_id'] in execution.get('selected_node_ids', []) else 'unselected'
        if isinstance(raw.get('expected'), dict):
            node['arms'] = {}
            for arm, expected in raw['expected'].items():
                matches = [row for row in evidence if _identity(row) == _identity(expected) and
                           row.get('expression') == expected.get('expression') and row.get('settings') == expected.get('settings')]
                finals = [row for row in matches if str(row.get('status', '')).lower() in ('checked', 'qualified')]
                matches = finals or matches
                unique = {_canonical({key: row.get(key) for key in ('expression', 'settings', 'alpha_id', 'metrics')}) for row in matches}
                measured = matches[-1] if len(unique) == 1 else {}
                arm_node = _node(dict(expected, **{key: measured[key] for key in
                    ('alpha_id', 'metrics', 'status', 'score', 'signal_score') if key in measured}))
                arm_node['node_id'] = _stable_id('arm', [raw['node_id'], arm, _identity(expected)])
                arm_node['state'] = _text(measured.get('status') or route.get('arm_states', {}).get(arm))
                if len(unique) > 1:
                    arm_node.update(state='conflict', reason='Conflicting measurements for simulation identity')
                node['arms'][arm] = arm_node
        nodes.append(node)
    return nodes


def _seeds(selection: dict) -> list[dict]:
    """Input: persisted Seed selection dict. Output: normalized selected nodes joined to exact measured identities."""
    result = []
    for entry in _rows(selection.get('selected', [])):
        identity = entry.get('identity')
        if isinstance(identity, dict):
            matches = [row for row in _rows(selection.get('seed_rows', [])) if all(
                row.get(key) == value for key, value in identity.items() if key != 'lane_id')]
            if not matches or any(row != matches[0] for row in matches[1:]):
                raise ValueError('selected Seed measured identity missing or conflicting')
            row = dict(matches[0], node_id=_stable_id('seed', identity), score=entry.get('score'),
                       reason=entry.get('reasons', entry.get('reason')))
        else:
            row = dict(entry)
            row.setdefault('node_id', _stable_id('seed', [row.get('expression_hash'), row.get('alpha_id')]))
        result.append(_node(row))
    return result


def _repair_nodes(repair: dict) -> list[dict]:
    """Input: persisted Repair receipt dict. Output: stable variant rows with measured children/trace, no parent-as-child IDs."""
    attempts = []
    occurrences = {}
    for attempt in _rows(repair.get('attempts', [])):
        plan, trace = attempt.get('plan') or {}, attempt.get('experiment_trace') or {}
        variants = _rows(plan.get('variants', []))
        children = _rows(attempt.get('children', attempt.get('checked_children', [])))
        if not children and isinstance(trace.get('measured_child'), dict):
            children = [trace['measured_child']]
        for variant in variants or children or [{}]:
            identity = [attempt.get('parent_alpha_id'), attempt.get('parent_expression_hash'),
                        _identity(variant), plan.get('evidence_digest')]
            key = _canonical(identity)
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            matched = [row for row in children if _identity(row) and _identity(row) == _identity(variant)]
            conflict = len(matched) > 1 or any(
                key in variant and child.get(key) != variant[key]
                for child in matched for key in ('expression', 'settings'))
            child = matched[0] if len(matched) == 1 and not conflict else {}
            row = dict(variant)
            row.update(child)
            # Attempt summaries can contain parent IDs; only explicit variant/child IDs belong here.
            row.update(node_id=_stable_id('repair', [identity, occurrence]),
                       state=attempt.get('phase') or attempt.get('status'),
                       hypothesis=(plan.get('decision') or {}).get('hypothesis', attempt.get('hypothesis')),
                       reason=trace.get('reason') or trace.get('reasons') or attempt.get('reason') or attempt.get('blocker'),
                       comparison=trace or None)
            if conflict:
                row.update(state='conflict', reason='Repair child identity conflicts with planned variant')
            if row.get('score') is None and row.get('signal_score') is None:
                row['score'] = attempt.get('score')
            attempts.append(_node(row))
    return attempts


def _tree_progress(run: Path, tree: dict) -> dict:
    """Input: owning run Path/tree dict. Output: bounded exact consumed-source progress; local reads only."""
    from wqb.tree_runtime import _sources
    directory = _safe(run, run / 'runtime/research_plans')
    for index, path in enumerate(directory.glob('tree-plan-*.json')):
        if index >= MAX_ROWS:
            raise ValueError('too many tree plans')
        _read(run, path.relative_to(run).as_posix())
    # Bound and validate the inputs consumed by the existing source matcher.
    for index, source in enumerate(run.parent.iterdir()):
        if index >= MAX_ROWS:
            raise ValueError('too many source directories')
        if source == run or not source.is_dir() or source.is_symlink() or source.is_junction():
            continue
        _read(source, 'run_meta.jsonl', optional=True, lines=True)
    rows = []
    for source, plan in _sources(run):
        if plan.get('tree_digest') != tree.get('tree_digest'):
            raise ValueError('source plan tree identity mismatch')
        source = _safe(run.parent, source)
        for name in PROGRESS_FILES:
            _read(source, name, optional=True, lines=True)
        for row in _rows(load_strategy_progress(source).get('rows', [])):
            if _identity(row) not in plan.get('reserved_simulation_identities', []):
                raise ValueError('source progress was not reserved by tree plan')
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise ValueError('too many tree progress rows')
    return {'rows': rows}


def _lane(run: Path, state=None, progress=None) -> dict:
    """Input: owning run Path and optional existing projections. Output: bounded read-only lane."""
    run = _safe(run.parent, run)
    persisted = _read(run, 'run_state.json')
    if persisted.get('run_id') != run.name:
        raise ValueError('run state identity mismatch')
    state = persisted if state is None else state
    tree = _read(run, 'runtime/experiment_tree.json', optional=True)
    if tree is None:
        tree = _read(run, 'experiment_tree.json', optional=True)
    manifest = _read(run, 'run_manifest.json', optional=True) or {}
    version = manifest.get('start_snapshot', {}).get('research_policy', {}).get('preplanned_tree_version')
    tree_mode = type(version) is int and version == 1
    binding = {} if tree_mode else (_read(run, 'stages/scout_seed/source_bridge_binding.json', optional=True) or {})
    source = run
    if binding.get('source_run_dir'):
        source = _safe(run.parent, Path(binding['source_run_dir']))
        if source == run.parent or source.parent != run.parent:
            raise ValueError('source must be an owning runs-root member')
    if tree_mode:
        if tree is None:
            raise ValueError('preplanned lane is missing frozen tree')
        progress = _tree_progress(run, tree)
    elif progress is not None and progress.get('source_run_dir'):
        projected_source = _safe(run.parent, Path(progress['source_run_dir']))
        if projected_source.parent != run.parent or projected_source != source:
            raise ValueError('source progress binding mismatch')
        source = projected_source
    if not tree_mode:
        for name in PROGRESS_FILES:
            _read(source, name, optional=True, lines=True)
    if progress is None:
        progress = load_strategy_progress(source)
    nodes = [_node(row) for row in _rows(progress.get('rows', []))]
    if tree is not None:
        nodes = _tree_nodes(run, tree, _rows(progress.get('rows', [])))
    ids = [node['node_id'] for node in nodes]
    if any(not isinstance(key, str) or not SAFE_ID.fullmatch(key) for key in ids) or len(set(ids)) != len(ids):
        raise ValueError('missing or conflicting node identity')
    seeds = []
    selection = _read(run, 'stages/scout_seed/seed_selection.json', optional=True)
    if selection is not None:
        seeds = _seeds(selection)
    else:
        seed = _read(run, 'stages/batch_generation/seed.json', optional=True)
        if seed is not None:
            if not isinstance(seed.get('parent'), dict):
                raise ValueError('invalid persisted seed parent')
            seeds = _seeds({'selected': [dict(seed['parent'], reason=seed.get('reason'))]})
    repair = _read(run, 'stages/repair/repair_execution.json', optional=True) or {}
    attempts = _repair_nodes(repair)
    return {'lane_id': run.name, 'name': state.get('objective') or run.name,
            'status': _text(state.get('status')), 'stage': _text(state.get('current_stage')),
            'nodes': nodes, 'seeds': seeds, 'repair': attempts}


def project_node(run: Path, node_id: str) -> dict:
    """Input: owning run Path/node ID str. Output: detailed existing node or explicit blocker."""
    try:
        if not isinstance(node_id, str) or not SAFE_ID.fullmatch(node_id):
            raise ValueError('invalid node ID')
        for node in _lane(Path(run))['nodes']:
            if node['node_id'] == node_id:
                return dict(node, schema_version=1, blocker='')
        raise ValueError('node evidence not found')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        return {'schema_version': 1, 'node_id': node_id, 'blocker': 'Node evidence unavailable: ' + str(exc)}


def project_group(group: Path) -> dict:
    """Input: existing group Path. Output: verified group/lane evidence; never creates or resumes runs."""
    result = {'schema_version': 1, 'group': None, 'lanes': [], 'request_revision': '', 'blocker': '',
              'allowed_actions': {'start': False, 'stop': False}}
    try:
        group = Path(group).absolute()
        if group.parent.name != 'research_groups' or not PATH_ID.fullmatch(group.name):
            raise ValueError('invalid group path')
        _safe(group.parent.parent, group)
        manifest = _read(group, 'group_manifest.json')
        _read(group, 'group_intent.json')
        lanes = _rows(manifest.get('lanes'))
        if not 1 <= len(lanes) <= MAX_LANES:
            raise ValueError('invalid group lane count')
        ids = [row.get('run_id') for row in lanes]
        if any(not isinstance(key, str) or not PATH_ID.fullmatch(key) for key in ids) or len(set(ids)) != len(ids):
            raise ValueError('invalid group membership')
        for run_id in ids:
            run = _safe(group.parent.parent, group.parent.parent / run_id)
            _read(run, 'research_group_binding.json')
        row = read_group(group)
        if not isinstance(row.get('request_revision'), str) or not row['request_revision']:
            raise ValueError('missing group request revision')
        result['group'] = {'group_id': row['group_id'], 'status': row['desired_state'],
                           'desired_state': row['desired_state']}
        result['request_revision'] = row['request_revision']
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        result.update(group=None, lanes=[], blocker='Group evidence unavailable: ' + str(exc))
        return result
    # Authenticated group intent is enough for Stop; lane display/Start evidence is separate.
    result['allowed_actions']['stop'] = True
    try:
        result['lanes'] = [_lane(group.parent.parent / run_id) for run_id in ids]
        from wqb.research_group_driver import _validate_control
        for run_id in ids:
            _validate_control(group.parent.parent / run_id, row)
        elapsed = row['elapsed_seconds']
        if row.get('active_since'):
            elapsed += max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(row['active_since'])).total_seconds())
        if elapsed >= row['authority']['max_runtime_seconds']:
            raise ValueError('group runtime authority exhausted')
        result['allowed_actions']['start'] = row['desired_state'] == 'paused'
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        result['blocker'] = 'Group lane/Start evidence unavailable: ' + str(exc)
    return result


def project_application(paths, state: dict, server_epoch: str, sequence: int) -> dict:
    """Input: Console paths/state, server epoch str/sequence int. Output: versioned read model dict."""
    # Reuse existing pure action predicates; handlers still recheck authoritative gates.
    from wqb.console_server import _workflow_action_state, _workflow_action_hash
    result = {'schema_version': 1, 'server_epoch': server_epoch, 'sequence': sequence,
              'evidence_at': datetime.now(timezone.utc).isoformat(), 'request_revision': '',
              'group': None, 'lanes': [], 'allowed_actions': {'start': False, 'stop': False},
              'options': [], 'blocker': ''}
    try:
        root = Path(paths.runs_root).absolute()
        active = state.get('active_workflow') or {}
        control = state.get('runtime_control') or {}
        allowed = _workflow_action_state(state)
        result['allowed_actions'] = {'start': bool(allowed['start_workflow'] or allowed['continue_workflow']),
                                     'stop': bool(allowed['stop_workflow'])}
        pointer = _read(root, 'active_research_group.json', optional=True)
        group_revision = ''
        if pointer is not None:
            result['allowed_actions'] = {'start': False, 'stop': False}
            group_id = pointer.get('group_id')
            if set(pointer) != {'group_id'} or not isinstance(group_id, str) or not PATH_ID.fullmatch(group_id):
                raise ValueError('invalid active research group pointer')
            projected = project_group(root / 'research_groups' / group_id)
            if projected['group'] is None:
                raise ValueError(projected['blocker'])
            result.update(group=projected['group'], lanes=projected['lanes'])
            group_revision = projected['request_revision']
            result['group_request_revision'] = group_revision
            result['allowed_actions'] = projected['allowed_actions']
            result['blocker'] = projected['blocker']
        elif active.get('exists'):
            run_id = active.get('run_id')
            if not isinstance(run_id, str) or not PATH_ID.fullmatch(run_id):
                raise ValueError('invalid active run identity')
            run = _safe(root, root / run_id)
            if active.get('run_dir') and Path(active['run_dir']).absolute() != run:
                raise ValueError('active run path mismatch')
            result['group'] = {'group_id': 'legacy:' + run_id, 'status': active.get('status', 'unknown'),
                               'desired_state': control.get('desired_state')}
            result['lanes'] = [_lane(run, active, state.get('strategy_progress'))]
        _canonical(state)
        if result['group'] is None:
            result['group'] = {'group_id': 'none', 'status': 'unknown',
                               'desired_state': control.get('desired_state', 'unknown')}
        for key in ('status', 'desired_state'):
            if not isinstance(result['group'].get(key), str):
                result['group'][key] = 'unknown'
        if not group_revision and isinstance(control.get('daily_simulation_budget'), dict):
            result['group']['daily_budget'] = control['daily_simulation_budget']
        result['request_revision'] = hashlib.sha256(_canonical([
            _workflow_action_hash(state), group_revision,
            result['group']['group_id'] if result['group'] else None]).encode()).hexdigest()
        result['options'] = [{'option_id': row['option_id'], 'title': row.get('title', row.get('name', ''))}
                             for row in _rows(state.get('option_cards', [])) if row.get('option_id')]
        if not result['blocker'] and not group_revision:
            result['blocker'] = str((state.get('current_work') or {}).get('blocker') or control.get('reason') or '')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        result.update(lanes=[], blocker='Application evidence unavailable: ' + str(exc))
        result['allowed_actions']['start'] = False
        if result['group'] is None:
            result['group'] = {'group_id': 'none', 'status': 'unknown', 'desired_state': 'unknown'}
        for key in ('status', 'desired_state'):
            if not isinstance(result['group'].get(key), str):
                result['group'][key] = 'unknown'
        # Damaged display evidence must not prevent an otherwise authorized durable Stop.
        if result['allowed_actions']['stop'] and not result['request_revision']:
            result['request_revision'] = hashlib.sha256(_canonical([
                _workflow_action_hash(state), 'evidence-unavailable', result['group']['group_id']]).encode()).hexdigest()
    return result


def _reply(command_id, status, message, job_id=None, execution_status=None):
    """Input: command identity/status/message and optional job facts. Output: receipt response dict."""
    return {'command_id': command_id, 'status': status, 'job_id': job_id,
            'message': message, 'execution_status': execution_status}


def _publish(root: Path, path: Path, receipt: dict):
    """Input: receipt root/target Paths and dict. Output: None; atomically persist fsynced receipt."""
    _safe(root, path)
    temporary = _safe(root, path.with_name(path.name + '.' + uuid4().hex + '.tmp'))
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            handle.write(_canonical(receipt))
            handle.flush()
            os.fsync(handle.fileno())
        _safe(root, path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def submit_command(paths, command: dict, *, action_runner, state_reader) -> dict:
    """Input: paths/command dict and injected callbacks. Output: idempotent receipt dict.

    state_reader() -> raw Console dict; action_runner(command, state) -> result dict.
    The parent MUST enforce current action gates/Stop fences inside action_runner;
    this adapter's read-model check is not a replacement transaction or authority.
    """
    command_id = command.get('command_id') if isinstance(command, dict) else None
    dispatched = False
    try:
        if (not isinstance(command, dict) or not isinstance(command_id, str)
                or not SAFE_ID.fullmatch(command_id)
                or set(command) - {'command_id', 'action', 'expected_revision', 'selected_option_id', 'group_id'}
                or command.get('action') not in {'start', 'stop'}
                or ('group_id' in command and (not isinstance(command['group_id'], str)
                    or not SAFE_ID.fullmatch(command['group_id'])))
                or not isinstance(command.get('expected_revision'), str)
                or not command['expected_revision']):
            raise ValueError('invalid command schema or identity')
        payload = _canonical(command)
        if len(payload.encode()) > MAX_COMMAND_BYTES:
            raise ValueError('command exceeds size limit')
        root = _safe(Path(paths.runs_root), Path(paths.job_root))
        if root != Path(paths.runs_root).absolute() / 'console_jobs':
            raise ValueError('command receipts must use existing console_jobs area')
        root.mkdir(parents=True, exist_ok=True)
        key = RECEIPT_PREFIX + hashlib.sha256(command_id.encode()).hexdigest()
        receipt_path = _safe(root, root / (key + '.json'))
        guard = _safe(root, root / key)
        # Release the receipt lock BEFORE callbacks: Stop must not wait for Start.
        with json_lock_transition_guard(guard, 5.0, .05, 'command receipt busy'):
            try:
                receipt = _read(root, receipt_path.name, optional=True)
            except (OSError, ValueError, TypeError, RecursionError):
                return _reply(command_id, 'unknown', 'Unreadable receipt; action will not be replayed')
            if receipt is not None:
                if receipt.get('command') != command:
                    return _reply(command_id, 'refused', 'command_id payload conflict')
                response = receipt.get('response')
                if not isinstance(response, dict) or response.get('status') not in {'accepted', 'refused', 'unknown'}:
                    return _reply(command_id, 'unknown', 'Invalid receipt; action will not be replayed')
                return response
            state = state_reader()
            current = project_application(paths, state, '', 0)
            response = None
            if command['expected_revision'] != current['request_revision']:
                response = _reply(command_id, 'refused', 'Stale expected_revision; resnapshot required')
            elif 'group_id' in command and command['group_id'] != (current['group'] or {}).get('group_id'):
                response = _reply(command_id, 'refused', 'Group identity mismatch; resnapshot required')
            elif not current['allowed_actions'][command['action']]:
                response = _reply(command_id, 'refused', current['blocker'] or 'Action is not allowed')
            elif 'selected_option_id' in command and (command['action'] != 'start' or
                    command['selected_option_id'] not in {r['option_id'] for r in current['options']}):
                response = _reply(command_id, 'refused', 'Invalid selected_option_id')
            pending = response or _reply(command_id, 'unknown', 'Dispatch outcome unknown; never automatically replay')
            receipt = {'schema_version': 1, 'command': command, 'response': pending}
            _publish(root, receipt_path, receipt)
            if response is not None:
                return response
        dispatched = True
        outcome = action_runner(dict(command), state)
        if not isinstance(outcome, dict):
            raise ValueError('action callback must return an explicit result dict')
        execution = outcome.get('status')
        status = execution if execution in {'accepted', 'refused', 'unknown'} else (
            'accepted' if execution in {'queued', 'created', 'running', 'completed', 'succeeded'} else 'unknown')
        response = _reply(command_id, status, str(outcome.get('message') or (
            'Dispatch acknowledged; inspect authoritative state for completion' if status == 'accepted'
            else 'Action outcome requires reconciliation; never automatically replay')),
            outcome.get('job_id'), execution)
        _canonical(response)
        if len(_canonical(response).encode()) > MAX_COMMAND_BYTES:
            raise ValueError('action response exceeds receipt limit')
        _publish(root, receipt_path, dict(receipt, response=response))
        return response
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return _reply(command_id, 'unknown' if dispatched else 'refused',
                      'Command dispatch uncertain; do not replay' if dispatched else 'Command validation or local evidence failed')
    except Exception:
        return _reply(command_id, 'unknown', 'Action callback failed; do not replay')


def project_command_statuses(paths) -> list:
    """Input: Console paths. Output: list[dict]; bounded recent durable replies, never dispatch."""
    root = _safe(Path(paths.runs_root), Path(paths.job_root))
    if root != Path(paths.runs_root).absolute() / 'console_jobs':
        raise ValueError('invalid command receipt area')
    replies = []
    # Only this adapter's receipts, never job logs or private diagnostic contents.
    files = sorted(root.glob(RECEIPT_PREFIX + '*.json'), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    for path in files[:MAX_COMMAND_RECEIPTS]:
        try:
            if path.stat().st_size > MAX_COMMAND_BYTES:
                continue
            receipt = _read(root, path.name)
            command = receipt.get('command') or {}
            response = receipt.get('response') or {}
            command_id = command.get('command_id')
            if (isinstance(command_id, str) and SAFE_ID.fullmatch(command_id)
                    and path.name == RECEIPT_PREFIX + hashlib.sha256(command_id.encode()).hexdigest() + '.json'
                    and response.get('command_id') == command_id
                    and response.get('status') in {'accepted', 'refused', 'unknown'}):
                replies.append({key: response.get(key) for key in
                                ('command_id', 'status', 'job_id', 'message', 'execution_status')})
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            continue
    return replies
