"""Read-only completion evidence for version-one packages; never retirement authority.

The caller owns worker/intent/POST fences and must revalidate before committing.
This module creates no locks, receipts, projections, archives or filesystem paths.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

from wqb.execution_package import load_execution_package, SEAL_PATH
from wqb.knowledge_contracts import parse_markdown_front_matter
from wqb.research_record import ResearchRecord, render_research_record_markdown
from wqb.runtime_control import runtime_authority_is_complete
from wqb.stage_outcomes import validate_checked_rows
from wqb.submission_attempts import uncertain_submission_hashes


MAX_FILE_BYTES = 256_000_000
MAX_ROWS = 10000
# A checked row can require plan, journal, result and several recovery/absence
# proofs. Keep this capacity aligned with rows, not an unrelated 512-file gate.
MAX_EVIDENCE_FILES = MAX_ROWS * 20
MAX_SUMMARY_BYTES = 32_000_000


def _digest(value: object) -> str:
    """Input: JSON object. Output: canonical SHA256 str, without IO or authority."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _path(root: Path, relative: str) -> Path:
    """Input: owning root Path/relative str. Output: contained nonlinked Path or ValueError."""
    root = Path(root).absolute()
    part = Path(relative)
    if part.is_absolute() or '..' in part.parts:
        raise ValueError('unsafe_evidence_path: ' + relative)
    path = root / part
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError('linked_evidence_path: ' + str(path))
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('escaping_evidence_path: ' + str(path))
    return path


def _read(root: Path, relative: str, refs: dict, *, optional=False, lines=False, text=False, array=False):
    """Input: owner/relative path, ref dict and modes. Output: bounded parsed bytes; track exact present/absent evidence."""
    path = _path(root, relative)
    if str(path) not in refs and len(refs) >= MAX_EVIDENCE_FILES:
        raise ValueError('evidence_file_bound: ' + str(path))
    if not path.exists() and optional:
        refs[str(path)] = dict(path=str(path), sha256=None, size_bytes=0, exists=False)
        return None
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError('not a bounded regular file')
        with path.open('rb') as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError('file grew beyond bound')
        refs[str(path)] = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                               size_bytes=len(raw), exists=True)
        content = raw.decode('utf-8-sig')
        if text:
            return content.replace('\r\n', '\n').replace('\r', '\n')
        value = ([json.loads(line) for line in content.splitlines() if line.strip()]
                 if lines else json.loads(content))
        if lines or array:
            if len(value) > MAX_ROWS or any(type(row) is not dict for row in value):
                raise ValueError('bounded object rows required')
        elif type(value) is not dict:
            raise ValueError('object required')
        _digest(value)
        return value
    except (OSError, ValueError, UnicodeError) as error:
        raise ValueError('damaged_evidence: ' + str(path) + ': ' + str(error)) from error


def _files(run: Path, relative: str, refs: dict) -> list[Path]:
    """Input: run Path/local directory/ref dict. Output: bounded direct file list; no recursive vault scan."""
    directory = _path(run, relative)
    if not directory.exists():
        return []
    paths = []
    for index, path in enumerate(directory.iterdir()):
        _path(run, path.relative_to(run).as_posix())
        if index >= MAX_EVIDENCE_FILES:
            raise ValueError('evidence_directory_bound: ' + relative)
        if not path.is_file():
            raise ValueError('unexpected_evidence_entry: ' + str(path))
        if path.suffix == '.json':
            _read(run, path.relative_to(run).as_posix(), refs)
            paths.append(path)
        elif not path.name.endswith('.guard'):
            raise ValueError('unexpected_evidence_file: ' + str(path))
    return sorted(paths)


def _recovery_closed(run: Path, status: dict, control: dict, refs: dict) -> None:
    """Input: owner/status/intent/refs. Output: None; validate current resolution and retain closed history."""
    from wqb.recovery_cases import read_current_recovery_case
    paths = _files(run, 'runtime/recovery', refs)
    snapshot = control.get('recovery_case') or status.get('recovery_case')
    if not paths and not snapshot:
        return
    current = read_current_recovery_case(run)
    if current and current.get('status') != 'resolved':
        raise ValueError('recovery_current_unresolved: ' + str(current.get('verification_error', current.get('status'))))
    seen = set()
    for path in paths:
        case = _read(run, path.relative_to(run).as_posix(), refs)
        case_id = case.get('case_id', '')
        if (len(case_id) != 24 or any(c not in '0123456789abcdef' for c in case_id)
                or path.name != case_id + '.json' or case.get('status') != 'resolved'):
            raise ValueError('recovery_history_unresolved_or_damaged: ' + str(path))
        seen.add(case_id)
        relative = 'runtime/maintenance_verification/' + case_id + '.json'
        receipt = _read(run, relative, refs)
        approval = (case.get('repair_approval') or {}).get('approval_id')
        digest = receipt.get('code_digest', '')
        if (not isinstance(approval, str) or len(approval) != 32
                or any(c not in '0123456789abcdef' for c in approval)
                or receipt.get('case_id') != case_id or receipt.get('approval_id') != approval
                or receipt.get('status') != 'passed' or receipt.get('code_unchanged') is not True
                or type(receipt.get('returncode')) is not int or receipt['returncode'] != 0
                or type(receipt.get('tests_run')) is not int or receipt['tests_run'] <= 0
                or receipt.get('command') != [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q']
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)
                or case.get('verification_path') != str(run / relative)):
            raise ValueError('recovery_closed_receipt_invalid: ' + case_id)
    if snapshot and (not current or current.get('case_id') not in seen):
        raise ValueError('recovery_current_identity_missing')


def _state_and_control(run: Path, refs: dict) -> dict:
    """Input: run Path/ref dict. Output: final state dict; reject Stop, damaged intent, waits and protected stages."""
    state = _read(run, 'run_state.json', refs)
    if (state.get('run_id') != run.name or Path(state.get('run_dir', '')).absolute() != run
            or state.get('status') != 'completed' or state.get('current_stage') != 'complete'
            or state.get('last_completed_stage') != 'research_record_sync'
            or state.get('research_record_synced') is not True
            or state.get('waiting_for_user') is not False or state.get('pause_reason')
            or state.get('next_action')):
        raise ValueError('terminal_state_required: completed/complete with successful recording and no approval wait')
    stages = state.get('stages', {})
    for name in ('objective_selected', 'schedule', 'scout_seed', 'batch_generation', 'backtest',
                 'triage', 'repair', 'candidate_gate', 'user_approval', 'approved_queue', 'research_record_sync'):
        stage = stages.get(name, {})
        allowed = {'completed', 'skipped'} if name in {'candidate_gate', 'user_approval', 'approved_queue'} else {'completed'}
        if stage.get('status') not in allowed or stage.get('blocker'):
            raise ValueError('terminal_state_stage_incomplete: ' + name)
    control = _read(run, 'runtime_control.json', refs)
    status = _read(run, 'runtime_status.json', refs)
    if (not runtime_authority_is_complete(control) or control.get('desired_state') != 'running'
            or status.get('invalid') or status.get('status') in {'paused', 'blocked', 'waiting', 'error'}
            or status.get('reason') or status.get('next_wake_at')):
        raise ValueError('runtime_control_blocked: Stop, damaged authority or outstanding wait')
    for key in ('simulation_attempts', 'elapsed_seconds'):
        value = status.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('runtime_control_accounting_missing: ' + key)
    if control.get('simulation_budget_mode') == 'daily':
        from wqb.daily_simulation_budget import read_daily_budget, _store
        budget = read_daily_budget(run)
        store = _store(run.parent)
        _read(store, 'policy.json', refs)
        ledger = _read(store, 'ledger.json', refs)
        for day in ledger.get('archives', {}):
            _read(store, 'archive/' + day + '.json', refs)
        if budget['policy_id'] != control['daily_budget_policy_id']:
            raise ValueError('runtime_control_daily_identity_changed')
    binding = _read(run, 'research_group_binding.json', refs, optional=True)
    if binding is not None:
        group_id = binding.get('group_id', '')
        if not group_id or Path(group_id).name != group_id:
            raise ValueError('runtime_control_group_identity_invalid')
        group = _path(run.parent, 'research_groups/' + group_id)
        manifest = _read(group, 'group_manifest.json', refs)
        intent = _read(group, 'group_intent.json', refs)
        from wqb.research_group import _digest as group_digest
        identity = group_digest(manifest)
        if intent.get('manifest_sha256') != identity or intent.get('desired_state') != 'running':
            raise ValueError('runtime_control_group_stopped_or_damaged')
        lane = next((row for row in manifest['lanes'] if row.get('run_id') == run.name), None)
        if lane is None or binding != dict(group_id=group_id, manifest_sha256=identity, **lane):
            raise ValueError('runtime_control_group_binding_changed')
    for relative in ('runtime/daily_budget_wait.json', 'runtime/tree_budget_wait.json'):
        wait = _read(run, relative, refs, optional=True)
        if wait is not None and wait.get('status') not in {'ready', 'resolved'}:
            raise ValueError('outstanding_wait: ' + relative)
    rounds = _read(run, 'research_rounds.json', refs, optional=True)
    if rounds and (rounds.get('pending_transition') or rounds.get('status') not in {'completed', 'exhausted'}):
        raise ValueError('legacy_round_closure_unproven: research_rounds.json')
    discovery = _read(run, 'stages/batch_generation/discovery_execution.json', refs, optional=True)
    if discovery is not None:
        raise ValueError('derived_discovery_closure_unproven: version-one tree uses Seed selection, not legacy Discovery')
    _recovery_closed(run, status, control, refs)
    return state


def _checked(root: Path, refs: dict) -> list[dict]:
    """Input: exact source/owner Path and refs. Output: checked identities without required check recovery."""
    from wqb.cli import simulation_identity_hash
    from wqb.repair_runtime import _checks_need_recovery
    rows = _read(root, 'all_alphas.jsonl', refs, lines=True)
    normalized = validate_checked_rows(rows)
    if not rows or not normalized:
        raise ValueError('source_checked_evidence_invalid: ' + str(root))
    for row in normalized:
        if _checks_need_recovery(row) or row.get('expression_hash') != simulation_identity_hash(row['expression'], row['settings']):
            raise ValueError('source_pending_or_identity_invalid: ' + str(root))
    return normalized


def _check_receipt_closed(root: Path, receipt: dict, events: list[dict], refs: dict) -> bool:
    """Input: source/historical check receipt/journal/refs. Output: bool proving same-identity final checks, never erasing history."""
    identity, alpha_id = receipt.get('expression_hash'), receipt.get('alpha_id')
    matches = [row for row in _checked(root, refs) if row['expression_hash'] == identity
               and (alpha_id is None or row['alpha_id'] == alpha_id)]
    relevant = [event for event in events if event.get('expression_hash') == identity]
    if (len(matches) != 1 or not relevant or relevant[-1].get('event') != 'CHECKED'
            or relevant[-1].get('alpha_id') != matches[0]['alpha_id']):
        return False
    if receipt.get('phase') == 'completed':
        return isinstance(receipt.get('next_poll_at'), str)
    if (not alpha_id or type(receipt.get('attempts')) is not int or receipt['attempts'] < 1
            or not isinstance(receipt.get('pending'), list) or not receipt['pending']):
        return False
    return any(row.get('event') == 'CHECK_PENDING' and row.get('alpha_id') == alpha_id
               and row.get('attempts') == receipt['attempts'] for row in relevant[:-1])


def _source_final(root: Path, refs: dict) -> None:
    """Input: exact source Path/refs. Output: None; refuse incomplete POST, simulation/check/recovery evidence."""
    events = _read(root, 'simulation_events.jsonl', refs, lines=True, optional=True) or []
    planned = _read(root, 'planned_candidates.jsonl', refs, lines=True, optional=True) or []
    if uncertain_submission_hashes(events):
        raise ValueError('source_unknown_post: ' + str(root))
    pending = set()
    final = set()
    for row in events:
        identity = row.get('expression_hash')
        event = row.get('event')
        if not isinstance(identity, str) or not identity or not isinstance(event, str):
            raise ValueError('source_damaged_event: ' + str(root))
        if event not in {'SUBMISSION_STARTED', 'SUBMIT_INTENT', 'SUBMITTED', 'SIMULATION_COMPLETED',
                         'CHECK_PENDING', 'PROGRESS_WAIT', 'CHECKED', 'ERROR', 'SUBMISSION_REJECTED',
                         'LOCAL_SUBMISSION_REJECTED', 'RATE_LIMITED'}:
            raise ValueError('source_event_closure_unproven: ' + event)
        if event in {'SUBMIT_INTENT', 'SUBMITTED', 'SIMULATION_COMPLETED', 'CHECK_PENDING', 'PROGRESS_WAIT'}:
            pending.add(identity)
        elif event in {'CHECKED', 'ERROR', 'SUBMISSION_REJECTED', 'LOCAL_SUBMISSION_REJECTED'}:
            pending.discard(identity)
            final.add(identity)
    if pending or any(not row.get('expression_hash') or row['expression_hash'] not in final for row in planned):
        raise ValueError('source_pending_work: ' + str(root))
    for relative in ('result_unknown.json', 'pending_checks.json', 'progress_wait.json',
                     'stages/backtest/check_recovery.json', 'rate_limit_state.json'):
        receipt = _read(root, relative, refs, optional=True)
        if receipt is not None:
            if relative == 'result_unknown.json':
                raise ValueError('source_result_unknown: ' + str(root))
            if relative == 'rate_limit_state.json':
                from wqb.rate_limit_state import check_source_retry_authorization, RateLimitRecoveryRequired
                try:
                    if receipt.get('status') not in {'ready', 'none', 'cooldown'}:
                        raise ValueError('unsupported cooldown state')
                    if any(type(receipt.get(key, 0)) is not int or receipt.get(key, 0) < 0
                           for key in ('consecutive_429_count', 'attempt_count')):
                        raise ValueError('invalid cooldown counters')
                    if receipt.get('retry_at'):
                        datetime.fromisoformat(receipt['retry_at'].replace('Z', '+00:00'))
                    if receipt.get('status') == 'cooldown' and not receipt.get('retry_at'):
                        raise ValueError('cooldown timestamp missing')
                    check_source_retry_authorization(root, datetime.now(timezone.utc).isoformat())
                except (ValueError, TypeError, RateLimitRecoveryRequired) as error:
                    raise ValueError('source_cooldown_requires_closure: ' + str(root) + ': ' + str(error)) from error
            elif relative in {'pending_checks.json', 'progress_wait.json'}:
                if not _check_receipt_closed(root, receipt, events, refs):
                    raise ValueError('source_recovery_outstanding: ' + str(root / relative))
            elif (receipt.get('status') not in {'completed', 'resolved'}
                  or receipt.get('run_id') != root.name
                  or receipt.get('output_sha256') != refs[str(root / 'all_alphas.jsonl')]['sha256']):
                raise ValueError('source_recovery_outstanding: ' + str(root / relative))
    for path in _files(root, 'pending_checks', refs):
        receipt = _read(root, path.relative_to(root).as_posix(), refs)
        if not _check_receipt_closed(root, receipt, events, refs):
            raise ValueError('source_checks_outstanding: ' + str(path))


def _tree(run: Path, package: dict, refs: dict) -> tuple[dict, dict, list[dict]]:
    """Input: owner/package/refs. Output: final tree projection, verified final decision, original Scout rows."""
    from wqb import research_tree as tree
    from wqb.tree_runtime import measured_row
    attachment, snapshot = package['attachment'], package['snapshot']
    projection = _read(run, 'runtime/tree_execution.json', refs)
    imported = _read(run, 'stages/scout_seed/scout_seed_import.json', refs)
    if (projection.get('status') != 'finished' or projection.get('waits') or projection.get('selected_node_ids')
            or projection.get('run_id') != run.name or projection.get('tree_digest') != attachment['tree_digest']
            or imported.get('mode') != 'preplanned_tree' or imported.get('target_run_id') != run.name
            or imported.get('tree_digest') != attachment['tree_digest']
            or imported.get('decision_id') != projection.get('decision_id')):
        raise ValueError('tree_terminal_identity_invalid')
    paths = _files(run, 'runtime/research_plans', refs)
    plans, decisions = {}, {}
    for path in paths:
        value = _read(run, path.relative_to(run).as_posix(), refs)
        if path.name.startswith('tree-decision-'):
            unsigned = {key: row for key, row in value.items() if key != 'decision_id'}
            if (value.get('decision_id') != tree._digest(unsigned)
                    or value.get('tree_digest') != attachment['tree_digest']
                    or path.name != 'tree-decision-' + value['decision_id'] + '.json'):
                raise ValueError('tree_decision_damaged: ' + str(path))
            decisions[value['decision_id']] = value
        elif path.name.startswith('tree-plan-') and not path.name.endswith('.experiments.json'):
            tree._verify_plan(run, attachment, value)
            plans[value['plan_id']] = value
    decision = decisions.get(projection.get('decision_id'))
    if decision is None:
        raise ValueError('tree_final_decision_missing')
    rows = decision['checked_rows']
    measurements = tree._measurements(rows)
    nodes = {node['node_id']: node for node in attachment['tree']['nodes']}
    selected, routes, comparisons = list(attachment['tree']['roots']), {}, {}
    for node_id in selected:
        node = nodes[node_id]
        route = tree.route_pair(node, measurements)
        if route['status'] not in {'branched', 'finished'} or route['confirmation_simulation_identities']:
            raise ValueError('tree_routing_unfinished: ' + node_id)
        routes[node_id] = route
        comparisons[node_id] = tree._comparison(node, rows, route, snapshot)
        for ref, value in tree._reverse_comparisons(node, rows, route, snapshot, attachment['resources']).items():
            comparisons[node_id + ':reverse:' + ref] = value
        selected.extend(key for key in route['selected_node_ids'] if key not in selected)
    incumbents = {key: value['incumbent'] for key, value in comparisons.items() if value.get('incumbent') is not None}
    retained = sorted({row['expression_hash'] for row in incumbents.values()})
    if (decision['routes'] != routes or decision['comparisons'] != comparisons
            or projection['routes'] != routes or projection['comparisons'] != comparisons
            or projection['accepted_incumbents'] != incumbents
            or projection['retained_expression_hashes'] != retained):
        raise ValueError('tree_projection_or_decision_changed')
    originals, seen = [], set()
    for evidence in imported['source_evidence']:
        source_path = Path(evidence['path']).absolute()
        if source_path.name != 'all_alphas.jsonl' or source_path.parent.parent != run.parent or source_path.parent == run:
            raise ValueError('source_owner_outside_run_siblings')
        source = source_path.parent
        plan_id = evidence['plan_id']
        if plan_id in seen or plan_id not in plans or not plans[plan_id].get('consumption_audit'):
            raise ValueError('source_plan_binding_invalid')
        seen.add(plan_id)
        metadata = _read(source, 'run_meta.jsonl', refs, lines=True)
        if not metadata or any(row.get('research_round_id') != plan_id or
                row.get('ai_plan_receipt') != str(run / ('runtime/research_plans/tree-plan-' + plan_id + '.json'))
                for row in metadata):
            raise ValueError('source_metadata_binding_invalid')
        source_rows = _checked(source, refs)
        if refs[str(source_path)]['sha256'] != evidence['sha256']:
            raise ValueError('source_import_digest_changed')
        if {row['expression_hash'] for row in source_rows} != set(plans[plan_id]['reserved_simulation_identities']):
            raise ValueError('source_reserved_batch_incomplete_or_unreserved')
        _source_final(source, refs)
        originals.extend(measured_row(row, run.name) for row in source_rows)
    if not originals or seen != {key for key, value in plans.items() if value.get('consumption_audit')}:
        raise ValueError('source_consumed_handoff_unaccounted')
    unique = {json.dumps(row, sort_keys=True, allow_nan=False): row for row in originals}
    original_bytes = ''.join(key+'\n' for key in sorted(unique)).encode()
    claimed = [row for row in imported['imported_artifacts'] if row['name'] == 'all_alphas.jsonl']
    if len(claimed) != 1 or claimed[0]['sha256'] != hashlib.sha256(original_bytes).hexdigest():
        raise ValueError('source_original_publication_digest_changed')
    originals = [unique[key] for key in sorted(unique)]
    if sorted(tree._digest(row) for row in rows) != sorted(tree._digest(row) for row in originals):
        raise ValueError('tree_decision_source_rows_differ')
    return projection, decision, originals


def _repair_child_source(run: Path, attempt: dict, parent: dict, refs: dict) -> tuple[dict, Path]:
    """Input: owner/checked attempt/current parent/refs. Output: exact journal-backed child and source Path."""
    plan = attempt['plan']
    variants, children = plan.get('variants'), attempt.get('children')
    if (type(variants) is not list or len(variants) != 1 or type(children) is not list or len(children) != 1
            or attempt.get('max_simulations') != 1 or attempt.get('phase') != 'checked'
            or attempt.get('status') != 'completed'):
        raise ValueError('repair_checked_attempt_shape_invalid')
    variant, child = variants[0], children[0]
    keys = ('expression', 'settings', 'expression_hash', 'parent_alpha_id', 'parent_expression_hash')
    from wqb.repair_runtime import _checks_need_recovery
    if (not validate_checked_rows(children) or _checks_need_recovery(child)
            or any(child.get(key) != variant.get(key) for key in keys)
            or child.get('parent_alpha_id') != parent['alpha_id']
            or child.get('parent_expression_hash') != parent['expression_hash']
            or child.get('alpha_id') == parent['alpha_id'] or child.get('expression_hash') == parent['expression_hash']):
        raise ValueError('repair_child_identity_or_checks_invalid')
    relative = ('stages/repair/parents/' + parent['alpha_id'] + '-' + parent['expression_hash'][:12]
                + '/iterations/' + plan['evidence_digest'])
    source = _path(run, relative)
    if attempt.get('source_run_dir') and Path(attempt['source_run_dir']).absolute() != source:
        raise ValueError('repair_child_source_binding_changed')
    persisted = _read(source, 'repair_plan.json', refs)
    expected = dict(parent_alpha_id=parent['alpha_id'], parent_expression_hash=parent['expression_hash'],
                    maximum=1, variants=variants)
    if persisted != expected:
        raise ValueError('repair_source_plan_changed')
    if _read(source, 'planned_candidates.jsonl', refs, lines=True) != variants:
        raise ValueError('repair_source_planned_identity_changed')
    if _checked(source, refs) != children:
        raise ValueError('repair_source_result_changed')
    _source_final(source, refs)
    events = _read(source, 'simulation_events.jsonl', refs, lines=True)
    relevant = [row for row in events if row.get('expression_hash') == child['expression_hash']]
    if len(relevant) != len(events):
        raise ValueError('repair_source_unowned_event')
    for event in ('SUBMITTED', 'SIMULATION_COMPLETED', 'CHECKED'):
        rows = [row for row in relevant if row.get('event') == event]
        if (len(rows) != 1 or any(rows[0].get(key) != variant.get(key) for key in keys)
                or event != 'SUBMITTED' and rows[0].get('alpha_id') != child['alpha_id']
                or event == 'SUBMITTED' and not isinstance(rows[0].get('progress_url'), str)):
            raise ValueError('repair_source_terminal_journal_invalid: ' + event)
    return child, source


def _repair_source_inventory(run: Path, expected: set[Path]) -> None:
    """Input: owner and exact executed subrun Paths. Output: None; refuse unclaimed local Repair sources, not vault scans."""
    root = _path(run, 'stages/repair/parents')
    observed = set()
    if not root.exists():
        if expected:
            raise ValueError('repair_source_directory_missing')
        return
    count = 0
    for parent in root.iterdir():
        _path(run, parent.relative_to(run).as_posix())
        if not parent.is_dir() or {path.name for path in parent.iterdir()} != {'iterations'}:
            raise ValueError('repair_source_inventory_unbound: ' + str(parent))
        iterations = _path(run, (parent / 'iterations').relative_to(run).as_posix())
        for source in iterations.iterdir():
            count += 1
            _path(run, source.relative_to(run).as_posix())
            if count > MAX_EVIDENCE_FILES or not source.is_dir() or source not in expected:
                raise ValueError('repair_source_inventory_unbound: ' + str(source))
            observed.add(source)
    if observed != expected:
        raise ValueError('repair_source_inventory_incomplete')


def _seed_and_repair(run: Path, package: dict, projection: dict, originals: list, refs: dict,
                     checked: list) -> tuple[dict, dict]:
    """Input: frozen package/tree/original rows/refs. Output: recomputed Seed and terminal Repair evidence."""
    from wqb.benchmark_rules import benchmark_rules_from_start_snapshot
    from wqb.benchmark import benchmark_alpha_record
    from wqb.stage_outcomes import research_benchmark_label
    from wqb.research_seed_stage import normalize_measured_row
    from wqb.seed_policy import select_seeds
    selection = _read(run, 'stages/scout_seed/seed_selection.json', refs)
    rules = benchmark_rules_from_start_snapshot(package['snapshot'])
    normalized = [normalize_measured_row(dict(row, benchmark_label=research_benchmark_label(row, run)
        if row['pending'] else benchmark_alpha_record(row, benchmark_rules=rules, consumer='triage').label),
        run.name) for row in originals]
    eligible = [row for row in normalized if row['expression_hash'] in projection['retained_expression_hashes']]
    expected = select_seeds(eligible, {}, benchmark_rules=rules)
    identities = {row['identity']['expression_hash'] for row in expected['selected']}
    expected.update(seed_rows=[row for row in eligible if row['expression_hash'] in identities],
                    run_id=run.name, tree_digest=projection['tree_digest'])
    if selection != expected:
        raise ValueError('seed_selection_changed_or_unbound')
    parents = {(row['alpha_id'], row['expression_hash']):
               {key: value for key, value in row.items() if key != 'benchmark_label'}
               for row in expected['seed_rows'] if row['benchmark_label'] == 'repairable_signal'}
    repair = _read(run, 'stages/repair/repair_execution.json', refs, optional=True)
    if repair is None:
        _repair_source_inventory(run, set())
        if parents:
            raise ValueError('repair_completion_evidence_missing_for_selected_seeds')
        if checked != validate_checked_rows(originals):
            raise ValueError('repair_unaccounted_checked_publication')
        return selection, dict(execution='skipped_no_eligible_seeds', attempts=[])
    if (repair.get('run_id') != run.name or repair.get('status') != 'completed'
            or repair.get('recovery_eligible') is not False or repair.get('blocker')
            or repair.get('unknown_result_count', 0) or repair.get('planning_waits')
            or repair.get('progress_retry_at') or repair.get('rate_limit_retry_at')):
        raise ValueError('repair_not_terminal')
    from wqb.repair_policy import verify_consumed_plan
    from wqb.repair_scheduler import _exhaustion_trace, _compare_attempt, _root_parent_key, publication_matches
    original_bytes = ''.join(json.dumps(row, sort_keys=True, allow_nan=False)+'\n' for row in originals).encode()
    if (repair.get('input_sha256') != hashlib.sha256(original_bytes).hexdigest()
            or repair.get('output_sha256') != refs[str(run / 'all_alphas.jsonl')]['sha256']
            or repair.get('last_sha256') != repair.get('output_sha256')
            or repair.get('parent_keys') != [list(key) for key in parents]
            or repair.get('unattempted_parent_count') != 0):
        raise ValueError('repair_publication_or_parent_binding_changed')
    incumbents, histories = dict(parents), {key: [] for key in parents}
    prior, known = {key: [] for key in parents}, list(originals)
    stopped, qualified, sources = set(), set(), set()
    reserved = 0
    for index, attempt in enumerate(repair.get('attempts', [])):
        phase = attempt.get('phase', attempt.get('status'))
        if phase not in {'checked', 'completed', 'stopped', 'cached'}:
            raise ValueError('repair_attempt_not_terminal: ' + str(phase))
        plan = attempt.get('plan', {})
        digest = plan.get('evidence_digest', '')
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('repair_plan_digest_invalid')
        base = 'runtime/repair_decisions/deterministic-' + digest
        saved = _read(run, base + '.json', refs)
        evidence = _read(run, base + '.input.json', refs)
        try:
            verify_consumed_plan(run, plan)
        except ValueError as error:
            raise ValueError('repair_plan_invalid: ' + str(error)) from error
        key = tuple(_root_parent_key(attempt))
        parent = incumbents.get(key)
        if (parent is None or key in stopped or key in qualified
                or attempt.get('parent_alpha_id') != parent['alpha_id']
                or attempt.get('parent_expression_hash') != parent['expression_hash']
                or evidence['parent'] != parent or evidence['history'] != histories[key]):
            raise ValueError('repair_parent_or_history_changed')
        if not plan.get('variants'):
            if (attempt.get('children') or attempt.get('max_simulations') != 0
                    or list(key) not in repair.get('stopped_parents', [])
                    or attempt.get('source_run_dir')
                    or attempt.get('experiment_trace') != _exhaustion_trace(parent, plan, prior[key])):
                raise ValueError('repair_finite_stop_evidence_changed')
            stopped.add(key)
        else:
            if attempt.get('reused_existing_simulation') is True:
                from wqb.repair_identity import verified_platform_alias
                matches = [row for row in known if hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                           == attempt.get('reused_source_sha256')]
                children = attempt.get('children', [])
                if (len(matches) != 1 or len(children) != 1 or attempt.get('max_simulations') != 0
                        or children[0]['expression_hash'] != plan['variants'][0]['expression_hash']
                        or not verified_platform_alias(matches[0], children[0])):
                    raise ValueError('repair_reused_child_evidence_changed')
                child = children[0]
            else:
                if saved.get('status') != 'consumed':
                    raise ValueError('repair_simulation_plan_not_consumed')
                child, source = _repair_child_source(run, attempt, parent, refs)
                if source in sources:
                    raise ValueError('repair_source_claimed_twice')
                sources.add(source)
                reserved += 1
            comparison = _compare_attempt(parent, child, plan, run)
            if attempt.get('experiment_trace') != comparison:
                raise ValueError('repair_comparison_changed')
            matches = publication_matches(known, child)
            if matches is None:
                raise ValueError('repair_publication_conflicts')
            if not matches:
                known.append(child)
            histories[key].append(child)
            if comparison.get('outcome') == 'accepted':
                incumbents[key] = child
            if child.get('hard_pass'):
                qualified.add(key)
        prior[key].append(attempt)
    _repair_source_inventory(run, sources)
    if (sorted(_digest(row) for row in known) != sorted(_digest(row) for row in checked)
            or reserved != repair.get('budget_reserved')
            or type(repair.get('max_simulations')) is not int or not 0 <= reserved <= repair['max_simulations']):
        raise ValueError('repair_publication_or_accounting_changed')
    for key, parent in incumbents.items():
        saved = repair.get('incumbents', {}).get(key[1])
        if saved is not None and saved != dict(alpha_id=parent['alpha_id'], expression_hash=parent['expression_hash']):
            raise ValueError('repair_incumbent_changed')
    if set(parents) - stopped - qualified and reserved < repair['max_simulations']:
        raise ValueError('repair_selected_seed_closure_missing')
    return selection, repair


def _record(run: Path, package: dict, state: dict, checked: list, refs: dict, repair: dict) -> tuple[dict, dict]:
    """Input: owner/package/state/checked rows/refs. Output: actual matching local/raw/machine record and refs."""
    record = _read(run, 'research_record.json', refs)
    if record.get('run_id') != run.name or record.get('objective') != state.get('objective'):
        raise ValueError('record_local_identity_mismatch')
    try:
        typed = ResearchRecord(**record)
    except TypeError as error:
        raise ValueError('record_local_schema_invalid') from error
    from wqb.research_record import record_repair_attempts
    rendered_record = record_repair_attempts(typed, repair['attempts'])
    if rendered_record.repair != typed.repair:
        raise ValueError('record_repair_evidence_missing_or_changed')
    for row in checked:
        matches = [saved for saved in typed.backtest if saved.get('alpha_id') == row['alpha_id']
                   and saved.get('expression_hash') == row['expression_hash']]
        keys = ('expression', 'settings', 'metrics', 'failed', 'pending', 'hard_pass')
        if len(matches) != 1 or any(matches[0].get(key) != row.get(key) for key in keys):
            raise ValueError('record_checked_measurement_missing_or_changed')
    knowledge = Path(package['manifest']['knowledge_root']).absolute()
    relative = 'raw/research/runs/' + run.name + '/research_record.md'
    raw = _read(knowledge, relative, refs, text=True)
    metadata, body = parse_markdown_front_matter(raw)
    if (body != render_research_record_markdown(rendered_record) or metadata.get('source_path') != relative
            or metadata.get('source_type') != 'workflow_research_record'
            or metadata.get('content_hash') != hashlib.sha256(body.encode()).hexdigest()
            or not metadata.get('captured_at')):
        raise ValueError('record_raw_identity_or_content_mismatch')
    ledger = _read(knowledge, 'machine/research_records.jsonl', refs, lines=True)
    matches = [row for row in ledger if row.get('run_id') == run.name]
    if not matches or any(matches[-1].get(key) != value for key, value in record.items()):
        raise ValueError('record_machine_identity_or_content_mismatch')
    try:
        datetime.fromisoformat(matches[-1]['synced_at'].replace('Z', '+00:00'))
        datetime.fromisoformat(metadata['captured_at'].replace('Z', '+00:00'))
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError('record_sync_timestamp_invalid') from error
    return record, dict(local=refs[str(run / 'research_record.json')], raw=refs[str(knowledge / relative)],
                        machine=dict(refs[str(knowledge / 'machine/research_records.jsonl')],
                                     row_sha256=_digest(matches[-1]), synced_at=matches[-1]['synced_at']))


def _candidate_records(run: Path, package: dict, state: dict, checked: list, record: dict, refs: dict) -> list[dict]:
    """Input: owner/frozen package/final state/results/record/refs. Output: lossless candidate cache evidence, not live eligibility."""
    from wqb.candidate_evidence import (_canonical, _identity, _verified_payload,
                                      MAX_CANDIDATE_EVIDENCE_MAX_AGE_SECONDS)
    from wqb.research_record import _candidate_identity
    from wqb.candidate_queue import QUEUE_STATUSES, validate_candidate_approval
    qualified = [row for row in checked if row['hard_pass']]
    gate = _read(run, 'candidate_gate.json', refs, optional=True, array=True) or []
    approvals = _read(run, 'approval.jsonl', refs, optional=True, lines=True) or []
    queue = _read(run, 'approved_candidates.jsonl', refs, optional=True, lines=True) or []
    identities = {_candidate_identity(row): row for row in gate}
    if len(identities) != len(gate):
        raise ValueError('candidate_gate_duplicate_identity')
    for row in gate:
        matches = [value for value in qualified if value['alpha_id'] == row.get('platform_alpha_id')
                   and value['expression_hash'] == row.get('expression_hash')]
        if (len(matches) != 1 or row.get('source_run_id') != run.name
                or type(row.get('version')) is not int or row['version'] < 1 or row.get('hard_pass') is not True
                or not any(_candidate_identity(saved) == _candidate_identity(row)
                           for saved in record['candidate_gate'])):
            raise ValueError('candidate_gate_result_or_record_mismatch')
    for row in approvals:
        if (_candidate_identity(row) not in identities or
                validate_candidate_approval(row, row.get('approved_at'), row.get('approved_by')) != row
                or row not in record['user_approval']):
            raise ValueError('candidate_approval_identity_or_record_mismatch')
    for row in queue:
        identity = _candidate_identity(row)
        if (identity not in identities or not any(_candidate_identity(value) == identity for value in approvals)
                or row.get('status') not in QUEUE_STATUSES or row not in record['approved_queue']):
            raise ValueError('candidate_queue_identity_or_record_mismatch')
    claims = _read(run.parent, 'api_submission_claims.jsonl', refs, optional=True, lines=True) or []
    latest_queue = {_candidate_identity(row): row for row in queue}
    for claim in claims:
        if claim.get('source_run_id') == run.name:
            current = latest_queue.get(_candidate_identity(claim), {})
            if current.get('status') != 'api_submitted':
                raise ValueError('candidate_final_post_outcome_unknown')
    if not qualified:
        if gate or approvals or queue or record['candidate_gate'] or record['user_approval'] or record['approved_queue']:
            raise ValueError('candidate_artifacts_without_qualified_results')
        return []
    if any(state['stages'][name]['status'] != 'completed' for name in
           ('candidate_gate', 'user_approval', 'approved_queue')) or not approvals or not queue:
        raise ValueError('candidate_approval_or_preservation_incomplete')
    knowledge = Path(package['manifest']['knowledge_root']).absolute()
    _read(knowledge, 'machine/candidate_evidence/self_pool_revision', refs, optional=True)
    result = []
    for row in qualified:
        if not any(value.get('platform_alpha_id') == row['alpha_id']
                   and value.get('expression_hash') == row['expression_hash'] for value in gate):
            raise ValueError('candidate_qualified_result_not_recorded_at_gate')
        relative = 'machine/candidate_evidence/' + hashlib.sha256(row['alpha_id'].encode()).hexdigest()+'.json'
        cache = _read(knowledge, relative, refs)
        unsigned = {key: value for key, value in cache.items() if key != 'integrity_sha256'}
        verified = _verified_payload(row['alpha_id'], cache.get('alpha_detail'), cache.get('check_response'))
        identity = dict(alpha_id=row['alpha_id'], expression=row['expression'], settings=row['settings'])
        if (cache.get('schema_version') != 1 or cache.get('alpha_id') != row['alpha_id']
                or type(cache.get('invalidated')) is not bool
                or cache.get('integrity_sha256') != hashlib.sha256(_canonical(unsigned).encode()).hexdigest()
                or cache.get('identity') != identity or _identity(row['alpha_id'], cache.get('alpha_detail')) != identity
                or verified is None
                or verified[1] != {key: value for key, value in row['metrics'].items() if key != 'candidate_evidence'}):
            raise ValueError('candidate_cache_raw_identity_or_checks_invalid: ' + row['alpha_id'])
        before, end = cache.get('checked_at'), cache.get('expires_at')
        if (type(before) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(before) or not math.isfinite(end)
                or not 0 <= before < end <= before + MAX_CANDIDATE_EVIDENCE_MAX_AGE_SECONDS):
            raise ValueError('candidate_cache_historical_times_invalid: ' + row['alpha_id'])
        result.append(dict(alpha_id=row['alpha_id'], expression_hash=row['expression_hash'],
                           record=cache, source_ref=refs[str(knowledge / relative)], eligibility_revalidated=False))
    return result


def terminal_retirement_proof(run: Path) -> dict:
    """Input: owning run Path. Output: identity-bound terminal evidence/summary dict, or precise ValueError.

    Pure reads, not a lock or permission to delete/resume/submit. No eligibility is
    returned for absent evidence; callers must hold fences and revalidate refs.
    """
    run = Path(run).absolute()
    refs = {}
    try:
        state = _state_and_control(run, refs)
        package = load_execution_package(run)
        seal = package['seal']
        _read(run, 'run_manifest.json', refs)
        saved_seal = _read(run, SEAL_PATH, refs)
        _read(run, 'runtime/experiment_tree.json', refs)
        if (saved_seal != seal or refs[str(run / 'run_manifest.json')]['sha256'] != seal['manifest_sha256']
                or refs[str(run / 'runtime/experiment_tree.json')]['sha256'] != seal['tree_sha256']):
            raise ValueError('package_changed_during_proof')
        for row in seal['certificate_refs'] + [seal['data_characteristics']]:
            _read(run, row['path'], refs)
            if refs[str(run / row['path'])]['sha256'] != row['sha256']:
                raise ValueError('package_payload_changed_during_proof: ' + row['path'])
        projection, decision, originals = _tree(run, package, refs)
        checked = _checked(run, refs)
        _source_final(run, refs)
        seed, repair = _seed_and_repair(run, package, projection, originals, refs, checked)
        from wqb.workflow_stage_adapters import research_evidence_blocker
        blocker = research_evidence_blocker(run)
        if blocker:
            raise ValueError('record_checked_publication_unbound: ' + blocker)
        record, record_refs = _record(run, package, state, checked, refs, repair)
        candidates = _candidate_records(run, package, state, checked, record, refs)
        from wqb.research_record import record_repair_attempts
        if record_repair_attempts(ResearchRecord(**record), repair['attempts']).repair != record['repair']:
            raise ValueError('record_repair_evidence_missing_or_changed')
        annotation = _read(run, seal['data_characteristics']['path'], refs)
        summary = dict(run_id=run.name, objective=state['objective'], tree_digest=projection['tree_digest'],
            decision_id=decision['decision_id'], status='completed', tree_status='finished',
            tree=deepcopy(package['attachment']['tree']), routes=decision['routes'],
            comparisons=decision['comparisons'], accepted_incumbents=projection['accepted_incumbents'],
            checked_rows=checked, seed=seed, repair=repair, annotations=annotation, candidate_evidence=candidates,
            research_record=record, authority_changed=False, grants_final_submission_authority=False,
            authority=dict(manifest_sha256=seal['manifest_sha256'], snapshot_sha256=seal['snapshot_sha256']))
        if len(json.dumps(summary, allow_nan=False).encode()) > MAX_SUMMARY_BYTES:
            raise ValueError('summary_bound_exceeded: retain evidence; never truncate')
        # Detect changes during the read. The owning transaction still supplies
        # the exclusion/fences needed to close races after this function returns.
        for ref in list(refs.values()):
            path = Path(ref['path'])
            check = {}
            _read(path.parent, path.name, check, optional=not ref['exists'], text=True)
            if check[str(path)] != ref:
                raise ValueError('evidence_changed_during_proof: ' + str(path))
        return dict(schema_version=1, kind='execution_package_terminal_proof', eligible=True,
            run_id=run.name, run_dir=str(run), seal=dict(refs[str(run / SEAL_PATH)],
                content_sha256=seal['content_sha256'], manifest_sha256=seal['manifest_sha256']),
            record_evidence=record_refs, evidence_refs=sorted(refs.values(), key=lambda row: row['path']),
            summary=summary, summary_sha256=_digest(summary))
    except (OSError, KeyError, TypeError, UnicodeError) as error:
        raise ValueError('terminal_evidence_incomplete: ' + str(error)) from error
