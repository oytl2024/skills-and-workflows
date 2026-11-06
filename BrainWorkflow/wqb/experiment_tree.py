"""Pure, opt-in v1 experiment trees. No compiler, IO, scheduling or authority.

Input tree: schema_version=1, scope (nonempty dict), period={start,end} ISO
dates, source_ids, roots, nodes, optional limits={max_depth,max_width}.
Each node: node_id, parent_id/parent_arm_id (None at roots), pair_ref,
expected_simulation_identities={baseline:str,treatment:str},
targets={baseline:[node IDs],treatment:[node IDs]}, fallback=[node IDs],
reverse={arm:{pair_ref,arm_id,simulation_identity,interpretation,targets}}.
Reverse children use parent_arm_id='reverse:baseline'/'reverse:treatment';
fallback children use 'fallback'. Each edge advances one layer (roots layer1).

Resources: compiled_pairs={ref: existing compile_design result},
sources={source_id: nonempty provenance dict}. The caller MUST authenticate
compiler receipts and source provenance before calling; this module snapshots
them, never compiles expressions or certifies raw evidence. Simulation identities
are caller-supplied existing identities, not new expression hashes. Matching
expression/settings/scope/period configurations MUST reuse the same identity.

validate_tree returns {schema_version,status:'validated'|'rejected',tree,
tree_digest,simulation_count,simulation_identities,reasons:[{code,path,message}]}.
The returned tree contains normalized nodes and frozen sources/receipts. Nodes
are content-digested attachments for route_pair, not mutable runtime state.
Their routing_policy freezes the v1 signal threshold, including across restarts.
Digests detect content drift, not authenticate an attacker-rehashed attachment;
the caller must bind tree_digest to the owning run's approved frozen plan.
simulation_count is the finite distinct-identity ceiling INCLUDING declared
fallback/reverse work, not new-attempt usage or a resource reservation.

Measurements: list of {simulation_identity,status,scope,period,sharpe,returns}.
status is completed|pending|unknown|failed|exhausted. Metrics must be actual
finite numbers; completed primary arms both required. Exact duplicate rows are
idempotent, conflicting rows fail closed. Unrelated identities are ignored.
Reverse confirmation is a separately measured positive signal, not negated data.

route_pair returns schema_version, node_id, status (waiting|recover|branched|
finished|inconclusive), branch_kind (none|signal|fallback), selected_arm_ids,
selected_node_ids, selected_simulation_identities,
confirmation_simulation_identities, arm_states, reasons. Once the primary pair
is complete, independently confirmed arms remain selected even if another arm
needs confirmation/recovery; callers may dispatch ONLY selected_node_ids.
Confirmation identities request planned work, never authorize POST/replay.
All outputs are exploratory, never Seed or submission qualification.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
import math


DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_WIDTH = 4
MAX_DEPTH = 64
MAX_WIDTH = 256
MAX_NODES = 4096
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_MEASUREMENTS = 16384
MAX_CHILDREN_PER_ARM = 2
SIGNAL_SHARPE = 0.9
ARMS = ('baseline', 'treatment')


def _fail(code: str, path: str, message: str) -> None:
    """Input: diagnostic strings. Output: raises ValueError with structured reason."""
    raise ValueError({'code': code, 'path': path, 'message': message})


def _canonical(value: object) -> str:
    """Input: JSON-compatible object. Output: canonical JSON str; rejects nonfinite data."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value: object) -> str:
    """Input: JSON-compatible object. Output: content SHA256 str, not simulation identity."""
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _json(value: object, depth: int = 0) -> None:
    """Input: object/depth int. Output: None; enforce bounded plain JSON schema types."""
    if depth > 48:
        _fail('invalid_json', '', 'JSON nesting limit exceeded')
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail('invalid_json', '', 'JSON keys must be strings')
            _json(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _json(item, depth + 1)
    elif type(value) not in (str, int, float, bool, type(None)):
        _fail('invalid_json', '', 'Only plain JSON values supported')
    elif type(value) is float and not math.isfinite(value):
        _fail('invalid_json', '', 'Nonfinite plan data')


def _keys(value: object, required: set, optional: set, path: str) -> None:
    """Input: object/key sets/path str. Output: None; reject missing or unknown schema keys."""
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - optional:
        _fail('invalid_schema', path, 'Missing or unsupported keys')


def _text(value: object, path: str) -> str:
    """Input: object/path str. Output: nonblank bounded str or validation failure."""
    if type(value) is not str or not value.strip() or len(value) > 16000:
        _fail('invalid_text', path, 'Expected nonblank bounded text')
    return value


def _ids(value: object, path: str, maximum: int) -> list:
    """Input: object/path/maximum int. Output: unique ID list or validation failure."""
    if type(value) is not list or len(value) > maximum:
        _fail('invalid_ids', path, 'Expected bounded ID list')
    for item in value:
        _text(item, path)
    if len(set(value)) != len(value):
        _fail('duplicate', path, 'Duplicate IDs are not padded slots')
    return value


def _compiled(ref: str, resources: dict, scope: dict) -> tuple[dict, dict]:
    """Input: receipt ref/resources/scope dicts. Output: existing receipt and arm map."""
    _text(ref, 'pair_ref')
    receipt = resources['compiled_pairs'].get(ref)
    if type(receipt) is not dict or receipt.get('status') != 'compiled':
        _fail('invalid_receipt', ref, 'Expected successful existing compiler receipt')
    experiment = receipt.get('experiment')
    if type(experiment) is not dict:
        _fail('invalid_receipt', ref, 'Missing compiler experiment')
    for key in ('experiment_id', 'compilation_digest'):
        _text(experiment.get(key), ref + '.' + key)
    arms = experiment.get('arms')
    if (type(arms) is not list or len(arms) != 2 or
            any(type(a) is not dict for a in arms) or
            {a.get('arm_id') for a in arms} != set(ARMS)):
        _fail('invalid_receipt', ref, 'Complete baseline/treatment compiler pair required')
    mapped = {a['arm_id']: a for a in arms}
    for arm in arms:
        if _canonical(arm.get('scope')) != _canonical(scope):
            _fail('scope_mismatch', ref, 'Compiler arm scope differs from frozen scope')
        if type(arm.get('settings')) is not dict or not arm['settings']:
            _fail('invalid_receipt', ref, 'Missing compiled settings')
        binding = arm.get('binding')
        if type(binding) is not dict:
            _fail('invalid_receipt', ref, 'Missing existing bound expression')
        _text(binding.get('bound_expression'), ref + '.expression')
    if _canonical(mapped['baseline']['settings']) != _canonical(mapped['treatment']['settings']):
        _fail('settings_mismatch', ref, 'Pair settings must match')
    return receipt, mapped


def _configuration(arm: dict, scope: dict, period: dict) -> dict:
    """Input: compiled arm/scope/period dicts. Output: exact existing simulation configuration."""
    return {'expression': arm['binding']['bound_expression'], 'settings': arm['settings'],
            'scope': scope, 'period': period}


def validate_tree(tree: dict, resources: dict) -> dict:
    """Input: proposed tree/authenticated compiler resources dicts. Output: frozen envelope dict.

    Does not mutate inputs, read files, recompile receipts, or grant resource authority.
    """
    result = {'schema_version': 1, 'status': 'rejected', 'tree': None,
              'tree_digest': None, 'simulation_count': 0, 'simulation_identities': [], 'reasons': []}
    try:
        _json(tree)
        _json(resources)
        if len(_canonical([tree, resources]).encode('utf-8')) > MAX_JSON_BYTES:
            _fail('size_limit', '', 'Tree/resources exceed JSON byte limit')
        _keys(tree, {'schema_version', 'scope', 'period', 'source_ids', 'roots', 'nodes'}, {'limits'}, 'tree')
        _keys(resources, {'compiled_pairs', 'sources'}, set(), 'resources')
        if type(tree['schema_version']) is not int or tree['schema_version'] != 1:
            _fail('invalid_version', 'schema_version', 'Only explicit v1 trees supported')
        if type(resources['compiled_pairs']) is not dict or type(resources['sources']) is not dict:
            _fail('invalid_resources', 'resources', 'Expected receipt/source mappings')
        scope, period = tree['scope'], tree['period']
        if type(scope) is not dict or not scope:
            _fail('invalid_scope', 'scope', 'Explicit nonempty comparison scope required')
        for key in ('region', 'universe'):
            _text(scope.get(key), 'scope.' + key)
        if type(scope.get('delay')) is not int or scope['delay'] < 0:
            _fail('invalid_scope', 'scope.delay', 'Explicit nonnegative integer delay required')
        _keys(period, {'start', 'end'}, set(), 'period')
        for key in ('start', 'end'):
            if type(period[key]) is not str or date.fromisoformat(period[key]).isoformat() != period[key]:
                _fail('invalid_period', 'period', 'Expected ISO dates')
        if period['start'] > period['end']:
            _fail('invalid_period', 'period', 'Reversed comparison period')
        limits = {'max_depth': DEFAULT_MAX_DEPTH, 'max_width': DEFAULT_MAX_WIDTH}
        _keys(tree.get('limits', {}), set(), set(limits), 'limits')
        limits.update(tree.get('limits', {}))
        for key, cap in [('max_depth', MAX_DEPTH), ('max_width', MAX_WIDTH)]:
            if type(limits[key]) is not int or not 1 <= limits[key] <= cap:
                _fail('invalid_limit', key, 'Expected bounded positive integer')
        source_ids = _ids(tree['source_ids'], 'source_ids', MAX_NODES)
        if not source_ids:
            _fail('missing_sources', 'source_ids', 'Explicit source provenance required')
        sources = {}
        for source_id in source_ids:
            source = resources['sources'].get(source_id)
            if type(source) is not dict or not source:
                _fail('missing_sources', source_id, 'Source provenance unavailable')
            sources[source_id] = source
        roots = _ids(tree['roots'], 'roots', limits['max_width'])
        raw_nodes = tree['nodes']
        if not roots or type(raw_nodes) is not list or not 1 <= len(raw_nodes) <= MAX_NODES:
            _fail('invalid_nodes', 'nodes', 'Nonempty bounded tree required')
        nodes, receipts, identities, configurations, pairs = {}, {}, {}, {}, set()
        for raw in raw_nodes:
            _keys(raw, {'node_id', 'parent_id', 'parent_arm_id', 'pair_ref',
                       'expected_simulation_identities', 'targets', 'fallback', 'reverse'}, set(), 'node')
            node_id = _text(raw['node_id'], 'node_id')
            if node_id in nodes:
                _fail('duplicate', node_id, 'Duplicate node ID')
            _keys(raw['expected_simulation_identities'], set(ARMS), set(), node_id + '.identities')
            _keys(raw['targets'], set(ARMS), set(), node_id + '.targets')
            _keys(raw['reverse'], set(), set(ARMS), node_id + '.reverse')
            receipt, arms = _compiled(raw['pair_ref'], resources, scope)
            receipts[raw['pair_ref']] = receipt
            node = deepcopy(raw)
            node.update(schema_version=1, scope=scope, period=period, sources=sources,
                        pair_receipt=receipt, expected={}, reverse={},
                        routing_policy={'kind': 'paired_sharpe_returns_v1', 'signal_sharpe': SIGNAL_SHARPE})
            pair_configs = []
            for arm_id in ARMS:
                _ids(raw['targets'][arm_id], node_id + '.targets', MAX_CHILDREN_PER_ARM)
                config = _configuration(arms[arm_id], scope, period)
                identity = _text(raw['expected_simulation_identities'][arm_id], 'simulation_identity')
                node['expected'][arm_id] = dict(config, simulation_identity=identity)
                pair_configs.append(_canonical(config))
                _register(identity, config, identities, configurations)
                if arm_id in raw['reverse']:
                    reverse = raw['reverse'][arm_id]
                    _keys(reverse, {'pair_ref', 'arm_id', 'simulation_identity', 'interpretation', 'targets'}, set(), 'reverse')
                    _text(reverse['interpretation'], 'reverse.interpretation')
                    _ids(reverse['targets'], 'reverse.targets', MAX_CHILDREN_PER_ARM)
                    reverse_receipt, reverse_arms = _compiled(reverse['pair_ref'], resources, scope)
                    receipts[reverse['pair_ref']] = reverse_receipt
                    if type(reverse['arm_id']) is not str or reverse['arm_id'] not in ARMS:
                        _fail('invalid_reverse', node_id, 'Unknown reverse arm')
                    reverse_config = _configuration(reverse_arms[reverse['arm_id']], scope, period)
                    reverse_identity = _text(reverse['simulation_identity'], 'reverse.simulation_identity')
                    if (reverse_config['settings'] != config['settings'] or
                            reverse_config['expression'] == config['expression']):
                        _fail('invalid_reverse', node_id, 'Reverse must be a distinct compiled expression with fixed settings')
                    _register(reverse_identity, reverse_config, identities, configurations)
                    node['reverse'][arm_id] = dict(reverse, expected=dict(reverse_config,
                        simulation_identity=reverse_identity), pair_receipt=reverse_receipt)
            pair_key = tuple(sorted(pair_configs))
            if pair_configs[0] == pair_configs[1] or pair_key in pairs:
                _fail('duplicate', node_id, 'Duplicate compiled pair/arm; no padded experiments')
            pairs.add(pair_key)
            _ids(raw['fallback'], node_id + '.fallback', MAX_CHILDREN_PER_ARM)
            nodes[node_id] = node
        if any(root not in nodes for root in roots):
            _fail('invalid_root', 'roots', 'Root node missing')
        incoming = {}
        for node_id, node in nodes.items():
            edges = [(arm, node['targets'][arm], node['expected'][arm]) for arm in ARMS]
            edges += [('reverse:' + arm, rev['targets'], rev['expected']) for arm, rev in node['reverse'].items()]
            edges += [('fallback', node['fallback'], None)]
            for edge, targets, parent_expected in edges:
                for target in targets:
                    if target not in nodes or target in incoming or target in roots:
                        _fail('invalid_target', target, 'Missing, shared or cyclic target')
                    child = nodes[target]
                    if child['parent_id'] != node_id or child['parent_arm_id'] != edge:
                        _fail('parent_mismatch', target, 'Declared parent does not match routing edge')
                    if parent_expected is not None and child['expected']['baseline'] != parent_expected:
                        _fail('parent_identity_mismatch', target, 'Child must reuse measured parent baseline')
                    incoming[target] = node_id
        frontier, reached, layer = list(roots), set(), 1
        while frontier:
            if layer > limits['max_depth']:
                _fail('depth_limit', 'nodes', 'Tree exceeds frozen depth')
            next_frontier = []
            for node_id in frontier:
                if node_id in reached:
                    _fail('cycle', node_id, 'Tree is cyclic')
                reached.add(node_id)
                node = nodes[node_id]
                if node_id in roots and (node['parent_id'] is not None or node['parent_arm_id'] is not None):
                    _fail('invalid_root', node_id, 'Root cannot have a parent')
                node['layer'] = layer
                next_frontier.extend(target for target, parent in incoming.items() if parent == node_id)
            frontier, layer = next_frontier, layer + 1
        if reached != set(nodes):
            _fail('unreachable', 'nodes', 'Unreachable or cyclic nodes')
        frozen = {'schema_version': 1, 'scope': scope, 'period': period, 'limits': limits,
                  'source_ids': source_ids, 'sources': sources, 'roots': roots,
                  'compiled_pairs': receipts, 'nodes': [nodes[key] for key in sorted(nodes)],
                  'simulation_identities': sorted(identities)}
        tree_digest = _digest(frozen)
        for node in frozen['nodes']:
            node['tree_digest'] = tree_digest
            node['node_digest'] = _digest(node)
        result.update(status='validated', tree=deepcopy(frozen), tree_digest=tree_digest,
                      simulation_count=len(identities), simulation_identities=sorted(identities))
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        reason = exc.args[0] if exc.args and type(exc.args[0]) is dict else {
            'code': 'invalid_schema', 'path': '', 'message': 'Malformed or unsupported tree/resources'}
        result['reasons'] = [reason]
    return result


def _register(identity: str, config: dict, identities: dict, configurations: dict) -> None:
    """Input: identity/config and mutable local indexes. Output: None; reject identity aliasing."""
    key = _canonical(config)
    if identity in identities and identities[identity] != key:
        _fail('identity_conflict', identity, 'Simulation identity names different configurations')
    if key in configurations and configurations[key] != identity:
        _fail('duplicate_configuration', identity, 'Reuse the existing simulation identity')
    identities[identity], configurations[key] = key, identity


def _measurement(expected: dict, rows: list) -> tuple[str, dict | None]:
    """Input: frozen expected identity dict/measurement list. Output: state str and actual row/None."""
    matches = [row for row in rows if row.get('simulation_identity') == expected['simulation_identity']]
    if not matches:
        return 'missing', None
    first = matches[0]
    for other in matches[1:]:
        try:
            if _canonical(first) != _canonical(other):
                return 'conflict', None
        except (ValueError, TypeError, RecursionError):
            return 'invalid_metrics', None
    status = first.get('status')
    if status in ('pending', 'unknown', 'failed', 'exhausted'):
        return status, first
    if status != 'completed':
        return 'unknown', first
    try:
        if any(key in first and _canonical(first[key]) != _canonical(expected[key])
               for key in ('expression', 'settings')):
            return 'identity_conflict', first
        actual_scope, planned_scope = first.get('scope'), expected['scope']
        if not isinstance(actual_scope, dict):
            return 'incomparable', first
        # as_of dates source availability at planning, not a measured market
        # scope. Instrument identity remains bound by the exact settings/hash.
        scope_keys = ('region', 'delay', 'universe') + (('instrument_type',) if 'instrument_type' in planned_scope else ())
        if (any(key not in actual_scope or _canonical(actual_scope[key]) != _canonical(planned_scope[key])
                for key in scope_keys)
                or _canonical(first.get('period')) != _canonical(expected['period'])):
            return 'incomparable', first
    except (ValueError, TypeError, RecursionError):
        return 'incomparable', first
    if any(type(first.get(key)) not in (int, float) or not _finite(first[key]) for key in ('sharpe', 'returns')):
        return 'invalid_metrics', first
    return 'completed', first


def _finite(value: int | float) -> bool:
    """Input: numeric scalar. Output: bool, rejecting infinities and overflowing integers."""
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _signal(row: dict, threshold: float) -> str:
    """Input: complete measured row dict/frozen threshold float. Output: signal classification str."""
    if row['sharpe'] >= threshold and row['returns'] > 0:
        return 'positive'
    if row['sharpe'] <= -threshold and row['returns'] < 0:
        return 'negative'
    return 'no_signal'


def route_pair(node: dict, measurements: list[dict]) -> dict:
    """Input: validated frozen node and actual rows. Output: deterministic route envelope dict.

    Missing/unknown evidence never becomes no-signal. No state, IO, metric invention or eval.
    """
    result = {'schema_version': 1, 'node_id': None, 'status': 'inconclusive',
              'branch_kind': 'none', 'selected_arm_ids': [], 'selected_node_ids': [],
              'selected_simulation_identities': [], 'confirmation_simulation_identities': [],
              'arm_states': {}, 'reasons': []}
    try:
        _json(node)
        if type(node) is not dict or 'node_digest' not in node:
            _fail('invalid_node', '', 'Validated frozen node required')
        unsigned = {key: value for key, value in node.items() if key != 'node_digest'}
        if _digest(unsigned) != node['node_digest']:
            _fail('invalid_node', '', 'Frozen node content changed')
        policy = node['routing_policy']
        _keys(policy, {'kind', 'signal_sharpe'}, set(), 'routing_policy')
        threshold = policy['signal_sharpe']
        if (policy['kind'] != 'paired_sharpe_returns_v1' or
                type(threshold) not in (int, float) or not _finite(threshold) or threshold <= 0):
            _fail('invalid_node', 'routing_policy', 'Unsupported frozen routing policy')
        result['node_id'] = node['node_id']
        if (type(measurements) is not list or len(measurements) > MAX_MEASUREMENTS or
                any(type(row) is not dict for row in measurements)):
            _fail('invalid_measurements', '', 'Expected bounded measurement object list')
        rows = {}
        unresolved = []
        for arm in ARMS:
            state, measured = _measurement(node['expected'][arm], measurements)
            result['arm_states'][arm] = state
            if state != 'completed':
                unresolved.append(state)
                result['reasons'].append({'code': state, 'path': arm, 'message': 'Primary arm is not complete/comparable'})
            else:
                rows[arm] = measured
        if unresolved:
            result['status'] = _status(unresolved)
            return result
        signals = {arm: _signal(rows[arm], threshold) for arm in ARMS}
        result['arm_states'].update(signals)
        for arm in ARMS:
            direction = signals[arm]
            expected = node['expected'][arm]
            targets = node['targets'][arm]
            if direction == 'no_signal':
                continue
            if direction == 'negative':
                reverse = node['reverse'].get(arm)
                if reverse is None:
                    unresolved.append('reverse_not_declared')
                    result['reasons'].append({'code': 'reverse_not_declared', 'path': arm,
                                              'message': 'Negative signal has no frozen reverse interpretation'})
                    continue
                expected, targets = reverse['expected'], reverse['targets']
                state, measured = _measurement(expected, measurements)
                result['arm_states'][arm] = 'reverse_' + state
                if state != 'completed':
                    unresolved.append('confirmation_required' if state == 'missing' else state)
                    if state == 'missing':
                        result['confirmation_simulation_identities'].append(expected['simulation_identity'])
                    result['reasons'].append({'code': 'confirmation_required' if state == 'missing' else state,
                        'path': 'reverse.' + arm, 'message': 'Actual positive reverse confirmation required'})
                    continue
                if _signal(measured, threshold) != 'positive':
                    result['reasons'].append({'code': 'reverse_not_confirmed', 'path': arm,
                                              'message': 'Measured reverse is not a positive signal'})
                    result['arm_states'][arm] = 'reverse_not_confirmed'
                    continue
                result['arm_states'][arm] = 'reverse_confirmed'
            result['selected_arm_ids'].append(arm)
            result['selected_simulation_identities'].append(expected['simulation_identity'])
            result['selected_node_ids'].extend(targets)
        if result['selected_arm_ids']:
            result['branch_kind'] = 'signal'
        elif all(signals[arm] == 'no_signal' for arm in ARMS) and node['fallback']:
            result['selected_node_ids'] = list(node['fallback'])
            result['branch_kind'] = 'fallback'
        result['status'] = _status(unresolved) if unresolved else (
            'branched' if result['selected_node_ids'] else 'finished')
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        reason = exc.args[0] if exc.args and type(exc.args[0]) is dict else {
            'code': 'invalid_node', 'path': '', 'message': 'Malformed frozen node or evidence'}
        result.update(status='inconclusive', selected_arm_ids=[], selected_node_ids=[],
                      selected_simulation_identities=[], confirmation_simulation_identities=[], reasons=[reason])
    return result


def _status(states: list[str]) -> str:
    """Input: unresolved state strings. Output: strongest bounded recovery/routing status str."""
    if any(state in ('conflict', 'identity_conflict', 'failed', 'exhausted', 'reverse_not_declared') for state in states):
        return 'inconclusive'
    if any(state not in ('pending', 'confirmation_required') for state in states):
        return 'recover'
    return 'waiting'
