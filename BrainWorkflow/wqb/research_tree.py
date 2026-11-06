"""Durable adapter for the existing compiler, paired planner and batch executor.

freeze_tree(run: Path, proposed_tree: dict, resources: dict) -> dict authenticates
every supplied compiled_pairs value against the owning Start's recompiled receipt.
resources uses experiment_tree's {compiled_pairs, sources} schema; sources are
exact source_index rows, not caller-created provenance labels. Start must contain
measurement_period and pre-model resource certificates. No manifest is rewritten.

advance_tree(run: Path, checked_rows: list[dict], maximum: int) -> dict accepts
existing CHECKED all_alphas records (explicit scope, measurement_period, metrics,
check lists, Alpha/expression/settings identities), or pending/unknown/failed rows.
Evidence and decisions live in existing runtime/research_plans receipts; inputs
may be incremental. Conflicting terminal observations are retained, never replaced.
Ready receipts reserve complete comparisons logically, not daily/platform quota.

execute_tree_round(run, executor, checked_rows=None, maximum=30) -> dict injects
the existing executor(config_patch: dict, metadata: dict) -> dict. It durably
records consumption_audit BEFORE invocation. An interrupted/uncertain handoff requires
the existing executor's reconciliation, never automatic redispatch here. Unconsumed
plans replay exactly. The executor MUST retain its existing POST Stop/accounting/
group/429/recovery fences and publish actual checked rows/events. No transport,
runtime state machine, model invocation, quota charge or final-submit authority.

Optional frozen Start tree_comparison_policy is the seed_policy feature policy;
absent policy gives inconclusive comparisons, never an invented acceptance rule.
runtime/tree_execution.json is disposable projection, not a second state authority.
retained_expression_hashes aliases incumbent_expression_hashes for Seed: accepted
children or retained-parent rollbacks only, never every measured/signal child.
source_run_root, when present in Start, is the existing source batch history root;
otherwise peer runs are scanned. Parent production wiring is intentionally external.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from wqb.cli import run_root_expression_hashes, simulation_identity_hash
from wqb.experiment_tree import validate_tree, route_pair, _measurement, MAX_MEASUREMENTS
from wqb.exploration_eligibility import (
    _store_immutable, validate_operational_exploration, verify_exploration,
)
from wqb.hypothesis_selection import _experiment_candidate
from wqb.lockfile import json_lock_transition_guard
from wqb.research_planning import hypothesis_authorized_maximum
from wqb.runtime_control import _write, has_runtime_authority, read_runtime_control, RuntimePaused
from wqb.seed_policy import compare_versions, _research_errors, _comparison_policy, _period
from wqb.semantic_compilation import _safe


MAXIMUM = 30
LOCK_SECONDS = 5.0
LOCK_POLL_SECONDS = .05
ATTACHMENT = 'runtime/experiment_tree.json'


def _digest(value: object) -> str:
    """Input: finite JSON object. Output: canonical SHA256 str, not a simulation hash."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _root(run: Path) -> Path:
    """Input: run Path. Output: resolved existing Path; reject links before resolution."""
    run = Path(run).absolute()
    if any(path.is_symlink() or path.is_junction() for path in (run, *run.parents)):
        raise ValueError('tree run cannot traverse links')
    return run.resolve(strict=True)


def _read(run: Path, relative: str) -> dict:
    """Input: owning run Path/relative str. Output: JSON dict; corrupt evidence fails closed."""
    value = json.loads(_safe(run, relative).read_text(encoding='utf-8'))
    if type(value) is not dict:
        raise ValueError('tree evidence must be an object')
    return value


def _authenticate(run: Path, proposed: dict, resources: dict) -> tuple[dict, dict, str]:
    """Input: run/tree/resource dicts. Output: validated tree, frozen snapshot, manifest hash tuple."""
    manifest_path = _safe(run, 'run_manifest.json')
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    snapshot = manifest['start_snapshot']
    context = validate_operational_exploration(run, Path(manifest['knowledge_root']), snapshot)
    if (_digest(proposed.get('scope')) != _digest(snapshot['selected_scope']) or
            _digest(proposed.get('period')) != _digest(snapshot.get('measurement_period'))):
        raise ValueError('tree scope/period differs from owning frozen Start')
    if type(resources) is not dict or set(resources) != {'compiled_pairs', 'sources'}:
        raise ValueError('expected existing compiled_pairs/sources schema')
    receipts = [verify_exploration(row)['compiled'] for row in snapshot['exploration_context']['receipts']]
    if type(resources['compiled_pairs']) is not dict or not resources['compiled_pairs']:
        raise ValueError('missing compiled pairs')
    for claimed in resources['compiled_pairs'].values():
        if not any(_digest(claimed) == _digest(receipt) for receipt in receipts):
            raise ValueError('compiled pair differs from source-recompiled Start receipt')
    if type(resources['sources']) is not dict or not resources['sources']:
        raise ValueError('missing source provenance')
    for key, source in resources['sources'].items():
        if key not in context['source_index'] or _digest(source) != _digest(context['source_index'][key]):
            raise ValueError('tree source differs from owning Start source index')
    validated = validate_tree(proposed, resources)
    if validated['status'] != 'validated':
        raise ValueError('invalid tree: ' + str(validated['reasons']))
    refs = set()
    for node in validated['tree']['nodes']:
        refs.add(node['pair_ref'])
        refs.update(row['pair_ref'] for row in node['reverse'].values())
        expected = list(node['expected'].values()) + [row['expected'] for row in node['reverse'].values()]
        for config in expected:
            if config['simulation_identity'] != simulation_identity_hash(config['expression'], config['settings']):
                raise ValueError('tree simulation identity differs from CLI hash')
    # A routed reverse uses the existing COMPLETE pair executor, including its
    # other arm even when only one arm is a routing confirmation.
    validated['execution_simulation_identities'] = sorted({
        simulation_identity_hash(arm['binding']['bound_expression'], arm['settings'])
        for ref in refs for arm in resources['compiled_pairs'][ref]['experiment']['arms']})
    validated['simulation_count'] = len(validated['execution_simulation_identities'])
    policy = snapshot.get('tree_comparison_policy')
    if policy is not None and (_comparison_policy(policy) or policy.get('edit') != 'feature'):
        raise ValueError('tree requires a valid frozen feature comparison policy')
    if manifest_path.read_bytes() != raw:
        raise ValueError('owning Start changed during tree authentication')
    return validated, snapshot, hashlib.sha256(raw).hexdigest()


def freeze_tree(run: Path, proposed_tree: dict, resources: dict) -> dict:
    """Input: run Path/proposed graph/resources dicts. Output: immutable authenticated attachment dict."""
    run = _root(run)
    validated, snapshot, manifest_hash = _authenticate(run, proposed_tree, resources)
    attachment = dict(schema_version=1, status='frozen', run_id=run.name,
        manifest_sha256=manifest_hash, start_snapshot_sha256=_digest(snapshot),
        proposed_tree=deepcopy(proposed_tree), resources=deepcopy(resources),
        tree=validated['tree'], tree_digest=validated['tree_digest'],
        execution_simulation_identities=validated['execution_simulation_identities'],
        simulation_count=validated['simulation_count'])
    _store_immutable(run, ATTACHMENT, attachment)
    return deepcopy(attachment)


def _load(run: Path) -> tuple[dict, dict]:
    """Input: owning run Path. Output: authenticated attachment/snapshot tuple, never fresh planning."""
    saved = _read(run, ATTACHMENT)
    validated, snapshot, manifest_hash = _authenticate(run, saved['proposed_tree'], saved['resources'])
    expected = dict(schema_version=1, status='frozen', run_id=run.name,
        manifest_sha256=manifest_hash, start_snapshot_sha256=_digest(snapshot),
        proposed_tree=saved['proposed_tree'], resources=saved['resources'], tree=validated['tree'],
        execution_simulation_identities=validated['execution_simulation_identities'],
        tree_digest=validated['tree_digest'], simulation_count=validated['simulation_count'])
    if _digest(saved) != _digest(expected):
        raise ValueError('frozen tree attachment or owning Start changed')
    return saved, snapshot


def _boundary(run: Path) -> None:
    """Input: run Path. Output: None or RuntimePaused; read Stop/time/authority without charging."""
    from wqb.research_group import require_group_running
    require_group_running(run)
    control = read_runtime_control(run)
    if not has_runtime_authority(run) or control.get('desired_state') != 'running':
        raise RuntimePaused('user_paused_or_authority_missing')
    elapsed = control.get('elapsed_seconds')
    if (type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0 or
            elapsed >= control['max_runtime_seconds']):
        raise RuntimePaused('runtime_budget_exhausted_or_unknown')
    # Existing accounting also checks the process's monotonic deadline at POST.


def _clean(value: object) -> object:
    """Input: JSON-like evidence. Output: finite JSON copy; invalid numeric metrics stay missing."""
    if type(value) is dict:
        return {key: _clean(item) for key, item in value.items()}
    if type(value) is list:
        return [_clean(item) for item in value]
    if type(value) is float and not math.isfinite(value):
        return None
    return value


def _row_identity(row: dict) -> str | None:
    """Input: existing checked/event row dict. Output: explicit simulation hash str or None."""
    return row.get('expression_hash', row.get('simulation_identity'))


def _evidence(run: Path, attachment: dict, incoming: list[dict]) -> tuple[list, list]:
    """Input: run/frozen attachment/incremental rows. Output: durable raw evidence and existing plans lists."""
    if (type(incoming) is not list or len(incoming) > MAX_MEASUREMENTS or
            any(type(row) is not dict for row in incoming)):
        raise ValueError('checked_rows must be an object list')
    directory = _safe(run, 'runtime/research_plans')
    plans, rows = [], []
    if directory.exists():
        for path in sorted(directory.glob('tree-*.json')):
            if path.name.endswith('.experiments.json'):
                continue
            saved = _read(run, path.relative_to(run).as_posix())
            if saved.get('tree_digest') != attachment['tree_digest']:
                raise ValueError('tree decision belongs to another attachment')
            if path.name.startswith('tree-decision-'):
                payload = {key: value for key, value in saved.items() if key != 'decision_id'}
                if saved.get('decision_id') != _digest(payload):
                    raise ValueError('tree decision evidence changed')
                rows.extend(saved['checked_rows'])
            elif path.name.startswith('tree-plan-'):
                _verify_plan(run, attachment, saved)
                plans.append(saved)
    known = set(attachment['execution_simulation_identities'])
    unique = {}
    for row in rows + _clean(incoming):
        if _row_identity(row) in known:
            unique[_digest(row)] = row
    rows = list(unique.values())
    # A checked observation supersedes intermediate polling state, not another
    # terminal result. Conflicting checked rows survive for route_pair to reject.
    finals = {_row_identity(row) for row in rows if row.get('status') == 'CHECKED'}
    rows = [row for row in rows if _row_identity(row) not in finals or row.get('status') == 'CHECKED']
    if len(rows) > MAX_MEASUREMENTS:
        raise ValueError('tree checked evidence exceeds routing bound')
    return sorted(rows, key=_digest), plans


def _measurements(rows: list) -> list:
    """Input: raw existing rows/list. Output: conservative route_pair measurement rows."""
    result = []
    for row in rows:
        identity = _row_identity(row)
        state = str(row.get('status', 'unknown')).lower()
        if row.get('status') == 'CHECKED':
            state = 'completed' if not _research_errors(row) else 'unknown'
        elif state not in ('pending', 'unknown', 'failed', 'exhausted'):
            state = 'unknown'
        if row.get('simulation_identity', identity) != identity:
            state = 'unknown'
        metric = row.get('metrics') if type(row.get('metrics')) is dict else {}
        period = _period(row.get('measurement_period'))
        if row.get('status') == 'CHECKED':
            if ('test_period' in row and _period(row['test_period']) != period) or period is None:
                state = 'unknown'
            if any(key in metric for key in ('startDate', 'endDate')):
                reported = _period(dict(start=metric.get('startDate'), end=metric.get('endDate')))
                if reported is None or reported != period:
                    state = 'unknown'
        measured = dict(simulation_identity=identity, status=state,
            scope=row.get('scope'), period=row.get('measurement_period'),
            expression=row.get('expression'), settings=row.get('settings'),
            sharpe=metric.get('sharpe'), returns=metric.get('returns'), evidence_sha256=_digest(row))
        result.append(measured)
    return result


def _comparison(node: dict, rows: list, route: dict, snapshot: dict) -> dict:
    """Input: frozen node/raw evidence/route/snapshot dicts. Output: existing comparison envelope dict."""
    matches = {}
    for arm, expected in node['expected'].items():
        selected = [row for row in rows if _row_identity(row) == expected['simulation_identity']]
        if len(selected) == 1 and selected[0].get('status') == 'CHECKED':
            matches[arm] = deepcopy(selected[0])
    if len(matches) != 2 or any(route['arm_states'].get(arm) in (
            'conflict', 'identity_conflict', 'incomparable', 'invalid_metrics', 'unknown') for arm in ('baseline', 'treatment')):
        return dict(outcome='inconclusive', incumbent=None, reasons=['complete_comparable_checked_pair_required'])
    parent, child = matches['baseline'], matches['treatment']
    for row in (parent, child):
        row['simulation_identity'] = _row_identity(row)
        row.setdefault('lane_id', 'default')
    child.setdefault('parent_alpha_id', parent['alpha_id'])
    child.setdefault('parent_expression_hash', parent['expression_hash'])
    policy = snapshot.get('tree_comparison_policy')
    if policy is None:
        return dict(outcome='inconclusive', incumbent=None, reasons=['missing_frozen_comparison_policy'])
    return compare_versions(parent, child, policy, frozen_node=node)


def _verify_plan(run: Path, attachment: dict, plan: dict) -> None:
    """Input: run/attachment/persisted receipt dict. Output: None; verify immutable logical reservation."""
    if (plan.get('plan_id') != _plan_id(plan) or plan.get('status') != 'ready' or
            ('consumption_audit' in plan and plan['consumption_audit'] != {'handed_off': True})):
        raise ValueError('persisted tree plan changed')
    patch = plan['config_patch']
    sidecar = _safe(run, 'runtime/research_plans/tree-plan-' + plan['plan_id'] + '.experiments.json')
    if (plan['tree_digest'] != attachment['tree_digest'] or
            patch['hypothesis_snapshot'] != _read(run, 'run_manifest.json')['start_snapshot'] or
            not sidecar.is_file() or hashlib.sha256(sidecar.read_bytes()).hexdigest() != plan['sidecar_sha256']):
        raise ValueError('tree plan sidecar/snapshot changed')
    expected = dict(schema_version=1, manifest_sha256=attachment['manifest_sha256'],
                    experiments=plan['selection']['experiments'], arms=plan['selection']['sidecars'])
    if _digest(json.loads(sidecar.read_bytes())) != _digest(expected):
        raise ValueError('tree sidecar differs from reserved pair selection')
    receipt = sidecar.with_suffix('').with_suffix('.json')
    if (patch.get('ai_plan_receipt') != str(receipt) or
            patch.get('experiment_sidecar_path') != str(sidecar) or
            patch.get('experiment_sidecar_sha256') != plan['sidecar_sha256'] or
            patch.get('research_round_id') != plan['plan_id']):
        raise ValueError('tree executor paths differ from owning reservation')


def _reverse_comparisons(node: dict, rows: list, route: dict, snapshot: dict, resources: dict) -> dict:
    """Input: authenticated node/evidence/route/snapshot/resources. Output: controlled measured reverse comparisons."""
    confirmed = {node['reverse'][arm]['expected']['simulation_identity'] for arm, state in route['arm_states'].items()
                 if state == 'reverse_confirmed'}
    refs = {node['reverse'][arm]['pair_ref'] for arm, state in route['arm_states'].items()
            if state == 'reverse_confirmed'}
    comparisons = {}
    for ref in sorted(refs):
        receipt = resources['compiled_pairs'][ref]
        identities = {arm['arm_id']: simulation_identity_hash(arm['binding']['bound_expression'], arm['settings'])
                      for arm in receipt['experiment']['arms']}
        proposed = dict(schema_version=1, scope=node['scope'], period=node['period'],
            source_ids=sorted(resources['sources']), roots=['reverse-core'], nodes=[dict(
                node_id='reverse-core', parent_id=None, parent_arm_id=None, pair_ref=ref,
                expected_simulation_identities=identities, targets=dict(baseline=[], treatment=[]),
                fallback=[], reverse={})])
        validated = validate_tree(proposed, resources)
        if validated['status'] != 'validated':
            raise ValueError('frozen reverse comparison is invalid')
        reverse_node = validated['tree']['nodes'][0]
        comparison = _comparison(reverse_node, rows, route_pair(reverse_node, _measurements(rows)), snapshot)
        if (comparison.get('incumbent') or {}).get('expression_hash') not in confirmed:
            comparison = dict(comparison, incumbent=None)
        comparisons[ref] = comparison
    return comparisons


def _plan_id(plan: dict) -> str:
    """Input: receipt dict. Output: logical plan digest independent of projected paths/byte encoding."""
    payload = deepcopy({key: value for key, value in plan.items()
                        if key not in ('status', 'plan_id', 'sidecar_sha256', 'consumption_audit')})
    for key in ('ai_plan_receipt', 'experiment_sidecar_path', 'experiment_sidecar_sha256', 'research_round_id'):
        payload['config_patch'].pop(key, None)
    return _digest(payload)


def _project(run: Path, plan: dict) -> dict:
    """Input: owning run Path/stored logical plan. Output: existing executor config and metadata dict."""
    result = deepcopy(plan['result'])
    receipt = _safe(run, 'runtime/research_plans/tree-plan-' + plan['plan_id'] + '.json')
    patch = deepcopy(plan['config_patch'])
    patch.update(ai_plan_receipt=str(receipt), experiment_sidecar_path=str(receipt.with_suffix('.experiments.json')),
                 experiment_sidecar_sha256=plan['sidecar_sha256'], research_round_id=plan['plan_id'])
    result.update(plan_id=plan['plan_id'], config_patch=patch, candidates=patch['scheduled_hypotheses'])
    return result


def _global_excluded(run: Path, snapshot: dict) -> set:
    """Input: run Path/Start snapshot. Output: global historical/peer-reserved identity set, never fake metrics."""
    root = Path(snapshot.get('source_run_root', run.parent))
    excluded = set(run_root_expression_hashes(root))
    for peer in run.parent.iterdir():
        if not peer.is_dir() or peer == run or peer.is_symlink() or peer.is_junction():
            continue
        directory = _safe(peer, 'runtime/research_plans')
        if directory.exists():
            for path in directory.glob('tree-plan-*.json'):
                if path.name.endswith('.experiments.json'):
                    continue
                plan = _read(peer, path.relative_to(peer).as_posix())
                _verify_plan(peer, _read(peer, ATTACHMENT), plan)
                excluded.update(plan['reserved_simulation_identities'])
    return excluded


def _advance_tree(run: Path, checked_rows: list[dict], maximum: int) -> dict:
    """Input: run Path, incremental existing checked rows, maximum int. Output: durable bounded candidate plan dict."""
    if type(maximum) is not int or maximum < 0:
        raise ValueError('maximum must be a nonnegative integer')
    run = _root(run)
    attachment, snapshot = _load(run)
    empty = dict(schema_version=1, tree_digest=attachment['tree_digest'], status='recover',
        candidates=[], config_patch=None, plan_id=None, selected_node_ids=[], routes={}, comparisons={},
        decision_id=None, accepted_incumbents={}, waits=[], submission_qualified=False)
    # Shared lock only protects planning/identity claims. Never hold it across
    # executor IO or the existing runtime/group submission locks.
    with json_lock_transition_guard(run.parent / 'tree_planning_guard', LOCK_SECONDS, LOCK_POLL_SECONDS,
                                    'tree planning busy'):
        rows, plans = _evidence(run, attachment, checked_rows)
        measurements = _measurements(rows)
        nodes = {node['node_id']: node for node in attachment['tree']['nodes']}
        selected = list(attachment['tree']['roots'])
        routes, comparisons, requests = {}, {}, []
        for node_id in selected:
            node = nodes[node_id]
            route = route_pair(node, measurements)
            routes[node_id] = route
            comparisons[node_id] = _comparison(node, rows, route, snapshot)
            for ref, comparison in _reverse_comparisons(node, rows, route, snapshot, attachment['resources']).items():
                comparisons[node_id + ':reverse:' + ref] = comparison
            selected.extend(key for key in route['selected_node_ids'] if key not in selected)
            requests.append((node_id, node['pair_ref']))
            for identity in route['confirmation_simulation_identities']:
                reverse = next(row for row in node['reverse'].values() if row['simulation_identity'] == identity)
                requests.append((node_id, reverse['pair_ref']))
        result = empty | dict(selected_node_ids=selected, routes=routes, comparisons=comparisons,
            accepted_incumbents={key: value['incumbent'] for key, value in comparisons.items()
                                 if value.get('incumbent') is not None})
        # Roots are work too; on subsequent rounds expose only newly selected
        # descendant work, not already measured comparison roots.
        result['selected_node_ids'] = [key for key in selected if any(
            state in ('missing', 'pending', 'unknown') for state in routes[key]['arm_states'].values())
            or routes[key]['confirmation_simulation_identities']]
        decision = dict(tree_digest=attachment['tree_digest'], checked_rows=rows,
                        routes=routes, comparisons=comparisons)
        decision['decision_id'] = _digest(decision)
        result['decision_id'] = decision['decision_id']
        _store_immutable(run, 'runtime/research_plans/tree-decision-' + decision['decision_id'] + '.json', decision)
        try:
            _boundary(run)
        except RuntimePaused as error:
            return result | dict(status='stopped', waits=[str(error)])
        observed = {_row_identity(row) for row in rows}
        # Presence alone cannot fund a parent. route_pair enforces comparability;
        # retain only identities with a completed compatible observation.
        reusable = set()
        for node in nodes.values():
            expected = list(node['expected'].values()) + [row['expected'] for row in node['reverse'].values()]
            for config in expected:
                if _measurement(config, measurements)[0] == 'completed':
                    reusable.add(config['simulation_identity'])
        try:
            cap = hypothesis_authorized_maximum(run, min(maximum, MAXIMUM))
        except RuntimePaused as error:
            return result | dict(status='stopped', waits=[str(error)])
        excluded = _global_excluded(run, snapshot)
        reserved = {identity for plan in plans for identity in plan['reserved_simulation_identities']}
        ready = [plan for plan in plans if not plan.get('consumption_audit') and
                 set(plan['reserved_simulation_identities']) - reusable]
        legal_identities = {simulation_identity_hash(arm['binding']['bound_expression'], arm['settings'])
            for _, ref in requests for arm in attachment['resources']['compiled_pairs'][ref]['experiment']['arms']}
        quota_reserved = set()
        for plan in ready:
            identities = set(plan['reserved_simulation_identities'])
            remaining = identities - observed - excluded
            if not identities <= legal_identities:
                result['waits'].append(dict(code='reserved_route_no_longer_valid', plan_id=plan['plan_id']))
                continue
            if remaining == identities and len(remaining) <= cap:
                return _project(run, plan) | dict(routes=routes, comparisons=comparisons,
                    accepted_incumbents=result['accepted_incumbents'], selected_node_ids=result['selected_node_ids'],
                    decision_id=result['decision_id'], waits=result['waits'])
            if remaining == identities:
                quota_reserved.update(identities)
                result['waits'].append(dict(code='insufficient_pair_budget', plan_id=plan['plan_id'],
                                           required_count=len(identities)))
                continue
            # Existing plan has some observations: never redispatch the original
            # whole batch. Reconcile through the existing source executor instead.
            if identities - reusable:
                result['waits'].append(dict(code='reserved_pair_requires_reconciliation', plan_id=plan['plan_id']))
        funded, candidates, experiments, sidecars = set(), [], [], []
        seen_pairs = set()
        for node_id, ref in requests:
            if ref in seen_pairs:
                continue
            seen_pairs.add(ref)
            receipt = attachment['resources']['compiled_pairs'][ref]
            experiment = receipt['experiment']
            arms = [_experiment_candidate(snapshot, arm) for arm in experiment['arms']]
            ids = [simulation_identity_hash(row['bound_expression'], row['settings']) for row in arms]
            missing = set(ids) - reusable - funded
            if not missing:
                continue
            if missing & quota_reserved:
                continue
            if missing & (observed | reserved | excluded):
                result['waits'].append(dict(code='identity_recovery_required', node_id=node_id,
                                           simulation_identities=sorted(missing)))
                continue
            if len(funded | missing) > cap:
                result['waits'].append(dict(code='insufficient_pair_budget', node_id=node_id,
                                           required_count=len(missing)))
                continue
            experiments.append(experiment)
            for arm, candidate, identity in zip(experiment['arms'], arms, ids):
                sidecars.append(dict(experiment_id=experiment['experiment_id'], arm_id=arm['arm_id'],
                    candidate_id=candidate['candidate_id'], expression_hash=identity,
                    baseline_expression_hash=ids[0], baseline_template_id=experiment['baseline_template_id'],
                    reused=identity in reusable, measurement=next((row for row in rows
                        if _row_identity(row) == identity), None) if identity in reusable else None))
                if identity in missing and identity not in funded:
                    candidates.append(candidate)
                    funded.add(identity)
        if not candidates:
            statuses = {route['status'] for route in routes.values()}
            codes = {wait['code'] for wait in result['waits']}
            status = ('recover' if codes - {'insufficient_pair_budget'} else 'budget_wait' if codes else
                      'inconclusive' if 'inconclusive' in statuses else 'recover' if 'recover' in statuses else
                      'waiting' if 'waiting' in statuses else 'finished')
            return result | dict(status=status)
        result.update(status='ready')
        patch = dict(hypothesis_binding_version=2, hypothesis_execution_kind='paired_scout', scheduled_template=None,
            scheduled_hypotheses=candidates, hypothesis_bindings=candidates, hypothesis_snapshot=snapshot,
            max_alphas_per_round=len(candidates))
        selection = dict(selected=candidates, sidecars=sidecars, experiments=experiments)
        controls = candidates[0]['settings']
        if any(candidate['settings'] != controls for candidate in candidates):
            raise ValueError('tree Scout comparisons require identical frozen controls')
        sidecar = dict(schema_version=1, manifest_sha256=attachment['manifest_sha256'],
                       experiments=experiments, arms=sidecars)
        plan = dict(tree_digest=attachment['tree_digest'], status='ready', result=result,
            identity=dict(manifest_sha256=attachment['manifest_sha256'], settings=deepcopy(controls)), config_patch=patch,
            selection=selection, reserved_simulation_identities=sorted(funded))
        plan['plan_id'] = _plan_id(plan)
        relative = 'runtime/research_plans/tree-plan-' + plan['plan_id']
        sidecar_path = _store_immutable(run, relative + '.experiments.json', sidecar)
        plan['sidecar_sha256'] = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
        patch.update(ai_plan_receipt=str(_safe(run, relative + '.json')),
            experiment_sidecar_path=str(sidecar_path), experiment_sidecar_sha256=plan['sidecar_sha256'],
            research_round_id=plan['plan_id'])
        _store_immutable(run, relative + '.json', plan)
        return _project(run, plan)


def _publish_summary(run: Path, result: dict) -> dict:
    """Input: owning run Path/derived result dict. Output: same result; publish disposable Console/Seed read model."""
    attachment = _read(run, ATTACHMENT)
    incumbents = result['accepted_incumbents']
    summary = {key: deepcopy(result[key]) for key in (
        'schema_version', 'tree_digest', 'status', 'plan_id', 'decision_id', 'selected_node_ids',
        'routes', 'comparisons', 'accepted_incumbents', 'waits', 'submission_qualified')}
    summary.update(run_id=run.name, kind='derived_tree_execution',
        authority=ATTACHMENT, evidence_directory='runtime/research_plans',
        nodes=attachment['tree']['nodes'], simulation_count=attachment['simulation_count'],
        incumbent_expression_hashes=sorted({row['expression_hash'] for row in incumbents.values()}),
        incumbent_alpha_ids=sorted({row['alpha_id'] for row in incumbents.values()}),
        candidate_ids=[row['candidate_id'] for row in result['candidates']])
    summary['retained_expression_hashes'] = list(summary['incumbent_expression_hashes'])
    _write(_safe(run, 'runtime/tree_execution.json'), summary)
    return result


def advance_tree(run: Path, checked_rows: list[dict], maximum: int) -> dict:
    """Input: owning run Path/incremental checked rows/list/cap int. Output: plan dict and derived persisted read model."""
    run = _root(run)
    with json_lock_transition_guard(_safe(run, 'runtime/tree_projection_guard'),
            LOCK_SECONDS, LOCK_POLL_SECONDS, 'tree projection busy'):
        try:
            result = _advance_tree(run, checked_rows, maximum)
        except (OSError, ValueError, KeyError, TypeError):
            # A previous read model cannot stay ready when its provenance is no
            # longer authentic. Keep source evidence untouched and surface error.
            _write(_safe(run, 'runtime/tree_execution.json'), dict(schema_version=1,
                kind='derived_tree_execution', run_id=run.name, status='blocked',
                tree_digest=None, plan_id=None, decision_id=None, nodes=[], routes={}, comparisons={},
                accepted_incumbents={}, incumbent_expression_hashes=[], incumbent_alpha_ids=[],
                retained_expression_hashes=[],
                selected_node_ids=[], candidate_ids=[], submission_qualified=False,
                waits=[dict(code='tree_evidence_validation_failed')]))
            raise
        # Stop may win after planning but before projection/return. Reservations
        # survive; no candidate work is handed to a caller past this boundary.
        try:
            _boundary(run)
        except RuntimePaused as error:
            result.update(status='stopped', candidates=[], config_patch=None, waits=[str(error)])
        return _publish_summary(run, result)


def execute_tree_round(run: Path, executor, checked_rows: list[dict] | None = None,
                       maximum: int = MAXIMUM) -> dict:
    """Input: owning run, existing executor callable, optional rows/cap. Output: plan and executor result dict."""
    result = advance_tree(run, checked_rows or [], maximum)
    if result['status'] != 'ready':
        return result
    run = _root(run)
    try:
        _boundary(run)
        relative = 'runtime/research_plans/tree-plan-' + result['plan_id'] + '.json'
        with json_lock_transition_guard(_safe(run, relative), LOCK_SECONDS, LOCK_POLL_SECONDS, 'tree dispatch busy'):
            attachment, _ = _load(run)
            plan = _read(run, relative)
            _verify_plan(run, attachment, plan)
            if plan.get('consumption_audit'):
                return result | dict(status='recover', candidates=[], config_patch=None,
                                     waits=[dict(code='executor_handoff_requires_reconciliation')])
            _boundary(run)
            _write(_safe(run, relative), plan | dict(consumption_audit={'handed_off': True}))
        _boundary(run)
    except RuntimePaused as error:
        return result | dict(status='stopped', candidates=[], config_patch=None, waits=[str(error)])
    # Reproject the durable handoff before external code can fail or be killed.
    # The ready compiler receipt remains readable by the existing generator.
    advance_tree(run, [], maximum)
    _boundary(run)
    output = executor(result['config_patch'], dict(tree_plan_id=result['plan_id'],
        tree_digest=result['tree_digest'], workflow_stage='scout'))
    return result | dict(executor_result=output)


def source_tree_patch(run: Path, config: dict) -> dict:
    """Input: owning run Path/executor config. Output: verified exact existing tree patch, never a new plan."""
    run = _root(run)
    attachment, _ = _load(run)
    path = Path(config.get('ai_plan_receipt', ''))
    if path.parent != _safe(run, 'runtime/research_plans') or not path.name.startswith('tree-plan-'):
        raise ValueError('source tree receipt must belong to owning run')
    plan = _read(run, path.relative_to(run).as_posix())
    _verify_plan(run, attachment, plan)
    patch = _project(run, plan)['config_patch']
    if any(config.get(key) != value for key, value in patch.items()):
        raise ValueError('source tree config differs from authenticated plan')
    from wqb.cli import _hypothesis_source_selection
    _hypothesis_source_selection(patch)
    return patch
