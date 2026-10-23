"""Opt-in tree-to-source adapter; existing transport owns POST/recovery/accounting."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from wqb.lockfile import json_lock_transition_guard
from wqb.research_seed_stage import normalize_measured_row
from wqb.research_tree import advance_tree, execute_tree_round, _boundary
from wqb.runtime_control import RuntimePaused, _write, read_runtime_control
from wqb.semantic_compilation import _safe
from wqb.source_bridge import _decision_for_source
from wqb.source_run_lock import acquire_source_run_lock, release_source_run_lock
from wqb.stage_outcomes import checked_research_rows, validate_checked_rows


MAXIMUM = 30
LOCK_SECONDS = 5.0
LOCK_POLL_SECONDS = .05
ACTION_NAMES = {'rate_limit_wait': 'rate-limit-wait', 'maintenance_blocker': 'maintenance-blocker',
                'complete_in_flight': 'complete-in-flight', 'retry_planned': 'retry-planned'}


def measured_row(row: dict, lane_id: str) -> dict:
    """Input: checked dict/lane str. Output: copy with only identity-verified measured scope/dates."""
    result = normalize_measured_row(row, lane_id)
    settings = result.get('settings', {})
    if result.get('simulation_identity') == result.get('expression_hash'):
        if all(key in settings for key in ('region', 'delay', 'universe')):
            result.setdefault('scope', {key: settings[key] for key in ('region', 'delay', 'universe')})
            if 'instrumentType' in settings:
                result['scope'].setdefault('instrument_type', settings['instrumentType'])
        if isinstance(result.get('test_period'), dict):
            result.setdefault('measurement_period', deepcopy(result['test_period']))
    return result


def _sources(run: Path) -> list[tuple[Path, dict]]:
    """Input: owning run Path. Output: exact consumed-plan source matches; ambiguity blocks replay."""
    plans = {}
    directory = _safe(run, 'runtime/research_plans')
    if directory.exists():
        for path in directory.glob('tree-plan-*.json'):
            if path.name.endswith('.experiments.json'):
                continue
            plan = json.loads(path.read_text(encoding='utf-8'))
            if plan.get('consumption_audit'):
                plans[str(path.resolve())] = plan
    matched, seen = [], set()
    for source in run.parent.iterdir():
        if source == run or not source.is_dir() or source.is_symlink() or source.is_junction():
            continue
        meta = source / 'run_meta.jsonl'
        if not meta.is_file() or meta.is_symlink():
            continue
        rows = [json.loads(line) for line in meta.read_text(encoding='utf-8').splitlines() if line.strip()]
        refs = {row.get('ai_plan_receipt') for row in rows if isinstance(row, dict)}
        for ref in refs & plans.keys():
            if ref in seen:
                raise ValueError('multiple source runs claim the same consumed tree plan')
            plan = plans[ref]
            if not all(row.get('research_round_id') == plan['plan_id'] for row in rows
                       if row.get('ai_plan_receipt') == ref):
                raise ValueError('source round differs from frozen tree plan')
            seen.add(ref)
            matched.append((source, plan))
    return matched


def _collect(run: Path, sources: list[tuple[Path, dict]]) -> list[dict]:
    """Input: owning run/exact source matches. Output: measured rows retaining conflicting evidence."""
    rows = []
    for source, plan in sources:
        raw = checked_research_rows(source)
        path = source / 'all_alphas.jsonl'
        if path.exists() and path.stat().st_size and not raw:
            raise ValueError('source checked evidence is invalid')
        for row in raw:
            if row['expression_hash'] not in plan['reserved_simulation_identities']:
                raise ValueError('source result was not reserved by its tree plan')
            rows.append(measured_row(row, run.name))
    return rows


def _publish(run: Path, tree: dict, rows: list[dict], sources: list[tuple[Path, dict]], now: str) -> None:
    """Input: finished tree/checked rows/source matches/time. Output: None; seal cumulative Scout evidence."""
    if tree['status'] != 'finished' or not rows or not validate_checked_rows(rows):
        raise ValueError('only finished trees with checked evidence can enter Seed')
    unique = {json.dumps(row, sort_keys=True, allow_nan=False): row for row in rows}
    data = ''.join(json.dumps(unique[key], sort_keys=True, allow_nan=False) + '\n' for key in sorted(unique))
    digest = hashlib.sha256(data.encode('utf-8')).hexdigest()
    source_evidence = [dict(path=str(source / 'all_alphas.jsonl'),
        sha256=hashlib.sha256((source / 'all_alphas.jsonl').read_bytes()).hexdigest(), plan_id=plan['plan_id'])
        for source, plan in sources if (source / 'all_alphas.jsonl').is_file()]
    receipt = dict(mode='preplanned_tree', target_run_id=run.name, tree_digest=tree['tree_digest'],
        decision_id=tree['decision_id'], source_evidence=source_evidence,
        imported_artifacts=[dict(name='all_alphas.jsonl', sha256=digest)], imported_at=now)
    target = _safe(run, 'all_alphas.jsonl')
    path = _safe(run, 'stages/scout_seed/scout_seed_import.json')
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if any(saved.get(key) != receipt[key] for key in receipt if key != 'imported_at'):
            raise ValueError('tree result publication conflicts with existing import')
    elif target.exists():
        raise ValueError('tree cannot overwrite pre-existing research')
    _write(path, receipt)
    if target.exists() and target.read_text(encoding='utf-8') != data:
        raise ValueError('published tree measurements changed')
    temporary = target.with_suffix('.jsonl.tmp')
    temporary.write_bytes(data.encode('utf-8'))
    temporary.replace(target)


def verify_tree_results(run: Path) -> dict:
    """Input: owning run Path. Output: authenticated finished tree; reject a premature/changed Scout publication."""
    run = Path(run).resolve()
    receipt = json.loads(_safe(run, 'stages/scout_seed/scout_seed_import.json').read_text(encoding='utf-8'))
    tree = advance_tree(run, [], 0)
    if (tree['status'] != 'finished' or receipt.get('mode') != 'preplanned_tree'
            or receipt.get('target_run_id') != run.name or receipt.get('tree_digest') != tree['tree_digest']
            or receipt.get('decision_id') != tree['decision_id']):
        raise ValueError('Scout publication is not the completed authenticated tree')
    for evidence in receipt['source_evidence']:
        path = Path(evidence['path'])
        if path.parent.parent != run.parent or path.name != 'all_alphas.jsonl' or path.is_symlink():
            raise ValueError('tree measurement source outside source runs')
        if hashlib.sha256(path.read_bytes()).hexdigest() != evidence['sha256']:
            raise ValueError('original tree measurement evidence changed')
    imported = next(row for row in receipt['imported_artifacts'] if row['name'] == 'all_alphas.jsonl')
    if hashlib.sha256(_safe(run, 'all_alphas.jsonl').read_bytes()).hexdigest() != imported['sha256']:
        raise ValueError('tree measurement publication changed')
    return tree


def continue_tree(run: Path, config: dict, now: str, *, enable_live_api: bool = False,
                  source_batch_runner=None, complete_in_flight_runner=None, retry_planned_runner=None) -> dict:
    """Input: owning Path/config/time, authority bool/existing runners. Output: next-action/tree dict.

    Durable handoff precedes source execution. Unmatched or ambiguous handoffs
    require reconciliation, never a blind repeat. No model is called here.
    """
    run = Path(run).resolve()
    with json_lock_transition_guard(_safe(run, 'runtime/tree_driver_guard'), LOCK_SECONDS,
                                    LOCK_POLL_SECONDS, 'tree driver busy'):
        try:
            _boundary(run)
        except RuntimePaused as error:
            return dict(next_action='runtime-paused', message=str(error))
        sources = _sources(run)
        rows = _collect(run, sources)
        tree = advance_tree(run, rows, MAXIMUM)
        if tree['status'] == 'stopped':
            return dict(next_action='runtime-paused', tree=tree)
        # Reconcile an existing source before funding further branches; a single
        # early candidate never means the entire pair/batch has completed.
        for source, _ in sources:
            decision = _decision_for_source(source, now, require_complete_batch=True)
            if decision is None or decision.action in {'import_existing', 'import_research_outcome'}:
                continue
            action = decision.action
            if action in {'rate_limit_wait', 'maintenance_blocker'}:
                return dict(next_action=ACTION_NAMES[action], tree=tree, source_bridge=decision.to_dict())
            runner = complete_in_flight_runner if action == 'complete_in_flight' else retry_planned_runner
            if not enable_live_api:
                return dict(next_action='enable-live-api-required', tree=tree)
            if runner is None:
                return dict(next_action='maintenance-blocker', tree=tree, message='Tree source recovery runner missing')
            lock_action = ACTION_NAMES[action]
            lock = acquire_source_run_lock(str(source), lock_action, now)
            if lock.get('status') != 'acquired':
                return dict(next_action='source-lock-wait', tree=tree)
            try:
                _boundary(run)
                output = runner(str(source))
            finally:
                release_source_run_lock(str(source), lock_action, now, owner_id=str(lock.get('owner_id', '')))
            return dict(next_action='workflow-auto-continue', tree=tree, source_recovery=output)
        if tree['status'] == 'finished':
            _boundary(run)
            _publish(run, tree, rows, sources, now)
            return dict(next_action='workflow-auto-continue', tree=tree, tree_complete=True)
        if tree['status'] != 'ready':
            if tree['status'] == 'budget_wait' and read_runtime_control(run).get('simulation_budget_mode') == 'daily':
                from wqb.daily_simulation_budget import read_daily_budget
                budget = read_daily_budget(run, now)
                needed = min((wait['required_count'] for wait in tree['waits']
                              if wait.get('code') == 'insufficient_pair_budget'), default=2)
                _write(_safe(run, 'runtime/tree_budget_wait.json'), dict(run_id=run.name,
                    tree_digest=tree['tree_digest'], required_pair_count=needed,
                    daily_simulation_budget=budget))
                return dict(next_action='daily-budget-wait', tree=tree, daily_simulation_budget=budget,
                            required_pair_count=needed)
            return dict(next_action='maintenance-blocker', tree=tree,
                        message='Tree evidence or original finite source authority requires reconciliation')
        if not enable_live_api:
            return dict(next_action='enable-live-api-required', tree=tree)
        if source_batch_runner is None:
            return dict(next_action='maintenance-blocker', tree=tree, message='Tree source executor missing')
        def execute(patch: dict, metadata: dict) -> dict:
            """Input: authenticated patch/metadata. Output: existing executor result, without replanning."""
            source_config = dict(config, **patch, active_workflow_run_dir=str(run), run_root=str(run.parent),
                                 allow_live_source_fallback=False)
            return source_batch_runner(source_config, metadata)
        executed = execute_tree_round(run, execute, rows, MAXIMUM)
        return dict(next_action='workflow-auto-continue', tree=executed)
