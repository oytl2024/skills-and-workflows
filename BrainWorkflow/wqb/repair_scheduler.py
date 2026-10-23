"""Cooperative, identity-keyed Repair scheduling under one existing run worker lock."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from wqb.runtime_control import _write, check_submission_allowed, RuntimePaused, DailyBudgetExhausted
from wqb.repair_runtime import RepairProgressPending, RepairRateLimited, RepairResultUnknown
from wqb.repair_unknown import quarantine_source, record_unknown, local_completion_source
from wqb.repair_trace import compare_repair_experiment
from wqb.repair_identity import verified_platform_alias, matching_simulation_rows, identity_hash_scheme


REPAIR_STALL_NOTICE_SECONDS = 1800


def _root_parent_key(attempt: dict) -> list:
    """Input: attempt dict. Output: logical root identity list; old attempts retain original keys."""
    return attempt.get('root_parent_key', [attempt['parent_alpha_id'], attempt['parent_expression_hash']])


def _compare_attempt(parent: dict, child: dict, plan: dict, root: Path | None = None) -> dict:
    """Input: measured parent/child/plan dicts. Output: versioned comparison without changing evidence."""
    if plan.get('planner_kind') != 'deterministic':
        return compare_repair_experiment(parent, child, plan.get('decision', {}))
    from wqb.seed_policy import compare_versions
    decision = plan['decision']
    policy = {key: decision[key] for key in ('target_metric', 'target_direction', 'edit', 'value')}
    policy['turnover_max'] = .40
    if decision['edit'] == 'transform':
        from wqb.repair_search import verify_persisted_search
        if root is None:
            raise ValueError('transform comparison requires owning run')
        verify_persisted_search(root, plan)
        evidence = json.loads(Path(plan['receipt_path']).with_suffix('.input.json').read_text(encoding='utf-8'))
        return compare_versions(parent, child, policy,
                                frozen_search={key: evidence[key] for key in ('policy', 'history')})
    return compare_versions(parent, child, policy)


def _accepted_parent(root: Path, initial: dict, attempts: list) -> dict:
    """Input: run Path, root measured row and attempts list. Output: recomputed accepted incumbent row."""
    from wqb.repair_planning import verify_consumed_plan
    current = initial
    for attempt in attempts:
        plan = attempt.get('plan', {})
        if plan.get('planner_kind') != 'deterministic' or attempt.get('phase') != 'checked':
            continue
        verify_consumed_plan(root, plan)
        children = attempt.get('children', [])
        if not children:
            continue
        if (len(children) != 1 or attempt['parent_alpha_id'] != current['alpha_id']
                or attempt['parent_expression_hash'] != current['expression_hash']):
            raise ValueError('deterministic Repair incumbent lineage changed')
        if _compare_attempt(current, children[0], plan, root).get('outcome') == 'accepted':
            current = children[0]
    return current


def _record_alias(receipt: dict, saved: dict, child: dict) -> None:
    """Input: mutable scheduler receipt and checked rows. Output: None. Preserve both exact lineage/evidence hashes without duplicate publication."""
    alias = {'alpha_id': child['alpha_id'], 'parent_alpha_id': child.get('parent_alpha_id'),
             'parent_expression_hash': child.get('parent_expression_hash'),
             'expression_hash': child['expression_hash'], 'published_expression_hash': saved['expression_hash'],
             'saved_row_sha256': hashlib.sha256(json.dumps(saved, sort_keys=True).encode()).hexdigest(),
             'child_row_sha256': hashlib.sha256(json.dumps(child, sort_keys=True).encode()).hexdigest(),
             'identity_schemes': [identity_hash_scheme(row) for row in (saved, child)],
             'research_snapshot_alias_only': saved.get('hard_pass') is False and child.get('hard_pass') is False,
             'reason': 'same_checked_platform_identity; original settings and check receipts retained separately'}
    aliases = receipt.setdefault('publication_aliases', [])
    if alias not in aliases:
        aliases.append(alias)


def publication_matches(known: list[dict], child: dict) -> list[dict] | None:
    """Input: published rows and child dict. Output: compatible collision rows or None. Reject any true conflict regardless of order."""
    matches = [row for row in known if row.get('alpha_id') == child.get('alpha_id')
               or row.get('expression_hash') == child.get('expression_hash')]
    if any(row != child and not verified_platform_alias(row, child) for row in matches):
        return None
    return matches


def cached_collision_children(root: Path, attempt: dict, known: list[dict]) -> list[dict]:
    """Input: run Path, attempt/published rows. Output: verified cached children or []. Never executes work."""
    from wqb.stage_outcomes import validate_checked_rows
    if attempt.get('phase') != 'blocked' or attempt.get('blocker') != 'ValueError: Repair child identity collision':
        return []
    variants = attempt.get('plan', {}).get('variants', [])
    if len(variants) != 1:
        return []
    hashes = {v.get('expression_hash') for v in variants}
    try:
        journal = [c for p in (root / 'stages/repair/parents').glob('**/all_alphas.jsonl') for c in _rows(p)]
    except (OSError, ValueError, UnicodeError):
        return []
    if any(not isinstance(c, dict) for c in journal):
        return []
    cached = [c for c in journal if c.get('expression_hash') in hashes
              and c.get('parent_alpha_id') == attempt.get('parent_alpha_id')
              and c.get('parent_expression_hash') == attempt.get('parent_expression_hash')]
    checked = validate_checked_rows(cached)
    if len(checked) == len(cached) == 1 and all(publication_matches(known, child) for child in checked):
        return checked
    return []


def _stall_notice(root: Path, attempt: dict, now: str) -> None:
    """Input: run/attempt/time. Output: None. Notify once about long pending work without replaying its POST."""
    first = attempt.get('first_wait_at')
    if not first:
        return
    age = (datetime.fromisoformat(now) - datetime.fromisoformat(first)).total_seconds()
    if age < REPAIR_STALL_NOTICE_SECONDS:
        return
    from wqb.runtime_boundaries import record_runtime_boundary, dispatch_boundary_notice
    plan = attempt.get('plan', {})
    variant = (plan.get('variants') or [{}])[0]
    identity = variant.get('expression_hash') or attempt['parent_expression_hash']
    boundary = record_runtime_boundary(root, 'repair_simulation_stalled', {
        'current_stage': 'repair', 'expression_hash': identity, 'first_wait_at': first,
        'source_run_dir': attempt.get('source_run_dir'), 'age_seconds': age,
        'message': 'Saved simulation is still pending; inspect authoritative progress, never replay POST.'}, now)
    attempt['stall_notice'] = dispatch_boundary_notice(root, boundary, now)


def _sha(path: Path) -> str:
    """Input: file Path. Output: digest str. Bind adapter receipts to checked rows."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict]:
    """Input: JSONL Path. Output: dict list. Reject malformed durable research evidence."""
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _verified_prefix(source: Path, receipt: dict, root: Path) -> bool:
    """Input: source/receipt/run. Output: bool. Accept only exact prior bytes plus journal-backed checked appends."""
    raw = source.read_bytes()
    expected = receipt.get('last_sha256', receipt.get('input_sha256'))
    if hashlib.sha256(raw).hexdigest() == expected:
        return True
    # A crash can append up to the stage allowance before updating the parent receipt.
    lines = raw.splitlines(keepends=True)
    offset = None
    for count in range(1, min(8, len(lines)) + 1):
        prefix = b''.join(lines[:-count])
        if hashlib.sha256(prefix).hexdigest() == expected:
            offset = len(prefix)
            break
    if offset is None:
        return False
    try:
        journal = [r for p in (root / 'stages/repair/parents').glob('**/all_alphas.jsonl') for r in _rows(p)]
        appended = [json.loads(line) for line in raw[offset:].decode('utf-8').splitlines() if line.strip()]
    except (OSError, ValueError, UnicodeError):
        return False
    return all(row in journal for row in appended)


def execute_repair_round(root: Path, outcome: dict, executor: object, maximum: int) -> dict:
    """Input: run/outcome/executor/budget. Output: adapter receipt. Advance ready parents without blocking on one wait."""
    from wqb.stage_outcomes import validate_checked_rows, research_benchmark_label
    root = Path(root)
    path = root / 'stages/repair/repair_execution.json'
    source = root / 'all_alphas.jsonl'
    known = _rows(source)
    sha = _sha(source)
    if path.exists():
        receipt = json.loads(path.read_text(encoding='utf-8'))
        if receipt.get('run_id') != root.name or receipt.get('max_simulations') != maximum:
            return {'blocker': 'Repair reservation identity or budget changed'}
        from wqb.repair_planning import verify_consumed_plan, RepairPlanningBlocked
        try:
            for attempt in receipt.get('attempts', []):
                if attempt.get('phase') == 'result_unknown' and quarantine_source(root, attempt) is None:
                    raise ValueError('result-unknown isolation evidence changed')
                if attempt.get('reused_existing_simulation') is True:
                    reused = [row for row in known if hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                              == attempt.get('reused_source_sha256')]
                    children = attempt.get('children', [])
                    variants = attempt.get('plan', {}).get('variants', [])
                    if (len(reused) != 1 or len(children) != 1 or len(variants) != 1
                            or not verified_platform_alias(reused[0], children[0])
                            or children[0].get('expression_hash') != variants[0].get('expression_hash')
                            or children[0].get('parent_alpha_id') != attempt.get('parent_alpha_id')
                            or children[0].get('parent_expression_hash') != attempt.get('parent_expression_hash')):
                        raise ValueError('reuse evidence changed')
                if (attempt.get('max_simulations') == 0 and attempt.get('legacy') is False
                        and attempt.get('plan', {}).get('receipt_path')):
                    from wqb.repair_planning import verify_consumed_plan
                    verify_consumed_plan(root, attempt['plan'])
        except (RepairPlanningBlocked, ValueError, OSError, TypeError) as exc:
            receipt.update(status='paused', recovery_eligible=False,
                blocker='Repair persisted stop evidence invalid: ' + str(exc))
            _write(path, receipt)
            return receipt
        if receipt.get('status') == 'completed' and receipt.get('output_sha256') == sha:
            return {**receipt, 'execution': 'executed'}
        if not _verified_prefix(source, receipt, root):
            return {'blocker': 'Repair publication lineage changed'}
        receipt.setdefault('scheduler_version', 1)
    else:
        parents = [row for row in outcome['rows'] if row.get('benchmark_label') == 'repairable_signal']
        receipt = {'run_id': root.name, 'scheduler_version': 1, 'status': 'running',
                   'max_simulations': maximum, 'input_sha256': sha, 'last_sha256': sha,
                   'parent_keys': [[r['alpha_id'], r['expression_hash']] for r in parents], 'attempts': [], 'stopped_parents': []}
    parents = []
    for key in receipt['parent_keys']:
        parent = next((r for r in known if [r.get('alpha_id'), r.get('expression_hash')] == key), None)
        if parent is None:
            return {'blocker': 'Repair parent evidence changed'}
        parents.append(parent)
    receipt.setdefault('stopped_parents', [])
    receipt.setdefault('planning_waits', {})
    for attempt in receipt['attempts']:
        attempt.setdefault('phase', 'checked' if attempt.get('status') == 'completed' else 'ready')
        attempt.setdefault('legacy', 'plan' not in attempt)
        if attempt['legacy'] and not attempt.get('first_wait_at'):
            legacy_dir = root / 'stages/repair/parents' / (attempt['parent_alpha_id'] + '-' + attempt['parent_expression_hash'][:12])
            events = legacy_dir / 'simulation_events.jsonl'
            if events.exists():
                observed = [e['next_poll_at'] for e in _rows(events)
                            if e.get('event') == 'PROGRESS_WAIT' and e.get('next_poll_at')]
                if observed:
                    attempt['first_wait_at'] = min(observed)
    reserved = sum(a['max_simulations'] for a in receipt['attempts'])
    if reserved > maximum:
        return {'blocker': 'Repair reservations exceed authorized stage budget'}
    waits, blockers = [], []
    daily_wait = None
    now = datetime.now(timezone.utc).isoformat()
    for parent in parents:
        check_submission_allowed()
        key = [parent['alpha_id'], parent['expression_hash']]
        if key in receipt['stopped_parents']:
            continue
        attempts = [a for a in receipt['attempts'] if _root_parent_key(a) == key]
        if any(a.get('phase') == 'result_unknown' for a in attempts):
            continue
        history = [child for a in attempts for child in a.get('children', [])]
        if any(row.get('hard_pass') is True for row in history):
            continue
        attempt = next((a for a in attempts if a['phase'] != 'checked'), None)
        if any(a.get('plan', {}).get('planner_kind') == 'deterministic' for a in attempts):
            try:
                parent = _accepted_parent(root, parent, attempts)
            except (ValueError, OSError) as exc:
                blockers.append('Repair incumbent evidence invalid: ' + str(exc))
                continue
            receipt.setdefault('incumbents', {})[key[1]] = {
                'alpha_id': parent['alpha_id'], 'expression_hash': parent['expression_hash']}
        if attempt is None:
            if reserved >= maximum:
                continue
            planning_wait = receipt['planning_waits'].get('|'.join(key), {})
            if planning_wait.get('next_poll_at', '') > now:
                waits.append((planning_wait['next_poll_at'], planning_wait['source_run_dir']))
                continue
            try:
                from wqb.runtime_control import _read, DAILY_RECONCILE_ENV
                if _read(root / 'runtime_control.json').get('simulation_budget_mode') == 'daily':
                    from wqb.daily_simulation_budget import read_daily_budget
                    budget = read_daily_budget(root)
                    import os
                    if not budget['remaining'] or os.environ.get(DAILY_RECONCILE_ENV) == '1':
                        raise DailyBudgetExhausted(budget)
                plan = executor.prepare(root, parent, history, maximum - reserved)
                if getattr(executor, 'supports_ai_planning', False) is True:
                    from wqb.repair_planning import verify_consumed_plan
                    verify_consumed_plan(root, plan)
            except DailyBudgetExhausted as exc:
                daily_wait = exc
                continue
            except RuntimePaused:
                raise
            except RepairRateLimited as exc:
                receipt.update(status='paused', recovery_eligible=True, blocker=str(exc),
                               rate_limit_retry_at=exc.retry_at, rate_limit_source_run_dir=exc.source_run_dir,
                               budget_reserved=reserved)
                _write(path, receipt)
                return receipt
            except RepairProgressPending as exc:
                receipt['planning_waits']['|'.join(key)] = {'next_poll_at': exc.next_poll_at, 'source_run_dir': exc.source_run_dir}
                waits.append((exc.next_poll_at, exc.source_run_dir))
                _write(path, receipt)
                continue
            except Exception as exc:
                blockers.append('Repair planning failed: ' + type(exc).__name__ + ': ' + str(exc))
                continue
            receipt['planning_waits'].pop('|'.join(key), None)
            if not plan['variants']:
                receipt['stopped_parents'].append(key)
                receipt['attempts'].append({'parent_alpha_id': key[0], 'parent_expression_hash': key[1],
                    'max_simulations': 0, 'plan': plan, 'actions': [], 'phase': 'checked',
                    'status': 'completed', 'children': [], 'legacy': False,
                    'experiment_trace': {'schema_version': 1, 'baseline': parent,
                        'decision': plan.get('decision', {}), 'outcome': 'inconclusive',
                        'reason': 'AI stopped before simulation; no measured effect',
                        'metric_changes': {}, 'submission_qualified': False}})
                _write(path, receipt)
                continue
            used_hashes = {r.get('expression_hash') for r in known}
            planned_hashes = {v.get('expression_hash') for a in receipt['attempts']
                              for v in a.get('plan', {}).get('variants', [])}
            if plan['variants'][0]['expression_hash'] in planned_hashes:
                receipt['stopped_parents'].append(key)
                receipt.setdefault('discarded_plans', []).append({'parent_key': key,
                    'evidence_digest': plan['evidence_digest'], 'reason': 'duplicate_global_expression'})
                _write(path, receipt)
                continue
            duplicate_rows = matching_simulation_rows(known, plan['variants'][0])
            if duplicate_rows is None:
                blockers.append('Repair duplicate simulation evidence conflicts')
                continue
            if duplicate_rows and duplicate_rows[0].get('hard_pass') is False:
                saved = duplicate_rows[0]
                child = {**saved, 'expression_hash': plan['variants'][0]['expression_hash'],
                         'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash']}
                _record_alias(receipt, saved, child)
                cached_attempt = {'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash'],
                    'max_simulations': 0, 'plan': plan, 'actions': [], 'phase': 'checked',
                    'status': 'completed', 'children': [child], 'legacy': False,
                    'reused_existing_simulation': True,
                    'reused_source_sha256': hashlib.sha256(json.dumps(saved, sort_keys=True).encode()).hexdigest(),
                    'experiment_trace': _compare_attempt(parent, child, plan, root)}
                if plan.get('planner_kind') == 'deterministic':
                    cached_attempt['root_parent_key'] = key
                receipt['attempts'].append(cached_attempt)
                _write(path, receipt)
                continue
            if duplicate_rows:
                used_hashes.add(plan['variants'][0]['expression_hash'])
            used_hashes.update(v.get('expression_hash') for a in receipt['attempts']
                               for v in a.get('plan', {}).get('variants', []))
            if plan['variants'][0]['expression_hash'] in used_hashes:
                receipt['stopped_parents'].append(key)
                receipt.setdefault('discarded_plans', []).append({'parent_key': key,
                    'evidence_digest': plan['evidence_digest'], 'reason': 'duplicate_global_expression'})
                _write(path, receipt)
                continue
            attempt = {'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash'], 'max_simulations': 1,
                       'plan': plan, 'actions': [{'ai_plan': plan}], 'phase': 'ready', 'status': 'started',
                       'children': [], 'legacy': False}
            if plan.get('planner_kind') == 'deterministic':
                attempt['root_parent_key'] = key
            receipt['attempts'].append(attempt)
            reserved += 1
            _write(path, receipt)
        if attempt.get('phase') == 'blocked' and local_completion_source(root, attempt) is not None:
            attempt.update(phase='ready')
            attempt.pop('blocker', None)
            _write(path, receipt)
        if attempt.get('phase') == 'blocked':
            unknown_source = quarantine_source(root, attempt)
            if unknown_source is not None:
                evidence_path = record_unknown(unknown_source, key[0], key[1])
                attempt.update(phase='result_unknown', status='result_unknown', children=[],
                    unknown_evidence_path=str(evidence_path), automatic_resubmission_allowed=False)
                attempt['experiment_trace'] = {'schema_version': 1, 'baseline': parent,
                    'outcome': 'inconclusive', 'metric_changes': {}, 'submission_qualified': False,
                    'reason': 'Submitted result unknown after poll404; budget retained; no resubmission'}
                attempt.pop('blocker', None)
                _write(path, receipt)
                continue
            if attempt.get('blocker') == 'ValueError: Repair child identity collision':
                checked = cached_collision_children(root, attempt, known)
                pairs = [(c, publication_matches(known, c)) for c in checked]
                if checked:
                    for child, matches in pairs:
                        _record_alias(receipt, matches[0], child)
                    attempt.update(phase='checked', status='completed', children=checked)
                    attempt['experiment_trace'] = _compare_attempt(parent, checked[0], attempt.get('plan', {}), root)
                    attempt.pop('blocker', None)
                    _write(path, receipt)
                    continue
            blockers.append(attempt.get('blocker', 'Repair child requires maintenance'))
            continue
        if attempt.get('next_poll_at', '') > now:
            _stall_notice(root, attempt, now)
            waits.append((attempt['next_poll_at'], attempt.get('source_run_dir', '')))
            continue
        try:
            returned = executor(root, parent, attempt['actions'], attempt['max_simulations'])
            children = validate_checked_rows(returned)
            if not children or len(children) != len(returned) or len(children) > attempt['max_simulations']:
                raise ValueError('Repair executor returned incomplete checked children')
            for child in children:
                if (child.get('parent_alpha_id') != parent['alpha_id'] or child.get('parent_expression_hash') != parent['expression_hash']
                        or child['expression_hash'] == parent['expression_hash'] or child['alpha_id'] == parent['alpha_id']):
                    raise ValueError('Repair child lineage mismatch')
                if child.get('pending') and research_benchmark_label(child, root) == 'pending_review':
                    raise ValueError('Repair child checks are incomplete; saved identity requires check recovery')
                matches = publication_matches(known, child)
                if matches is None:
                    raise ValueError('Repair child identity collision')
                saved = matches[0] if matches else None
                if saved is not None and saved != child:
                    if not verified_platform_alias(saved, child):
                        raise ValueError('Repair child identity collision')
                    _record_alias(receipt, saved, child)
                if saved is None:
                    with source.open('a', encoding='utf-8') as handle:
                        handle.write(json.dumps(child) + '\n')
                    known.append(child)
            attempt.update(phase='checked', status='completed', children=children)
            attempt['experiment_trace'] = _compare_attempt(parent, children[0], attempt.get('plan', {}), root)
            if attempt.get('plan', {}).get('planner_kind') == 'deterministic':
                incumbent = children[0] if attempt['experiment_trace']['outcome'] == 'accepted' else parent
                receipt.setdefault('incumbents', {})[key[1]] = {
                    'alpha_id': incumbent['alpha_id'], 'expression_hash': incumbent['expression_hash']}
            receipt['last_sha256'] = _sha(source)
        except DailyBudgetExhausted as exc:
            daily_wait = exc
        except RuntimePaused:
            _write(path, receipt)
            raise
        except RepairResultUnknown as exc:
            attempt.update(phase='result_unknown', status='result_unknown', children=[],
                source_run_dir=exc.source_run_dir,
                unknown_evidence_path=str(Path(exc.source_run_dir) / 'result_unknown.json'),
                automatic_resubmission_allowed=False)
            if quarantine_source(root, attempt) is None:
                attempt.update(phase='blocked', blocker='Repair result-unknown evidence missing or changed')
                blockers.append(attempt['blocker'])
            else:
                attempt['experiment_trace'] = {'schema_version': 1, 'baseline': parent,
                    'outcome': 'inconclusive', 'metric_changes': {}, 'submission_qualified': False,
                    'reason': 'Submitted result unknown after poll404; budget retained; no resubmission'}
        except RepairRateLimited as exc:
            receipt.update(status='paused', recovery_eligible=True, blocker=str(exc),
                           rate_limit_retry_at=exc.retry_at, rate_limit_source_run_dir=exc.source_run_dir)
            receipt['budget_reserved'] = reserved
            _write(path, receipt)
            return receipt
        except RepairProgressPending as exc:
            attempt.update(phase='waiting', next_poll_at=exc.next_poll_at, source_run_dir=exc.source_run_dir)
            attempt.setdefault('first_wait_at', now)
            _stall_notice(root, attempt, now)
            waits.append((exc.next_poll_at, exc.source_run_dir))
        except Exception as exc:
            attempt.update(phase='blocked', blocker=type(exc).__name__ + ': ' + str(exc))
            blockers.append(attempt['blocker'])
        _write(path, receipt)
    receipt['budget_reserved'] = reserved
    receipt['unknown_result_count'] = sum(a.get('phase') == 'result_unknown' for a in receipt['attempts'])
    if daily_wait is not None and not blockers:
        receipt.update(status='paused', recovery_eligible=True, blocker=str(daily_wait))
        _write(path, receipt)
        raise daily_wait
    for key in ('rate_limit_retry_at', 'rate_limit_source_run_dir', 'progress_retry_at', 'progress_source_run_dir'):
        receipt.pop(key, None)
    if blockers:
        receipt.update(status='paused', recovery_eligible=False, blocker='; '.join(blockers)[:2000])
    elif waits:
        wake, source_dir = min(waits)
        receipt.update(status='paused', recovery_eligible=True, blocker='Repair independent simulations are processing',
                       progress_retry_at=wake, progress_source_run_dir=source_dir)
    elif reserved < maximum and any([p['alpha_id'], p['expression_hash']] not in receipt['stopped_parents']
            and not any(a.get('phase') == 'result_unknown' for a in receipt['attempts']
                        if _root_parent_key(a) == [p['alpha_id'], p['expression_hash']])
            and not any(c.get('hard_pass') for a in receipt['attempts'] if _root_parent_key(a) == [p['alpha_id'], p['expression_hash']]
                        for c in a.get('children', [])) for p in parents):
        receipt.update(status='paused', recovery_eligible=True, blocker='Repair next measured comparison is ready',
                       progress_retry_at=now, progress_source_run_dir=str(path.parent))
    else:
        receipt.update(status='completed', execution='executed', recovery_eligible=False, blocker='',
                       output_sha256=_sha(source), unattempted_parent_count=0)
    _write(path, receipt)
    return receipt
