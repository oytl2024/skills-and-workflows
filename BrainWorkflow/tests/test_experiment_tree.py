"""Offline contract/routing tests; receipts are fictional compiler fixtures."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from wqb import experiment_tree as subject


def fixture():
    """Input: none. Output: (tree, resources) dicts with fictional compiled pairs."""
    scope = {'region': 'USA', 'universe': 'TOP3000', 'delay': 1}
    settings = dict(scope, decay=0)
    pairs = {}
    for name, expressions in [('root', ('x', 'rank(x)')),
                              ('left', ('x', 'ts_mean(x, 5)')),
                              ('right', ('rank(x)', 'ts_mean(rank(x), 5)')),
                              ('fallback', ('y', 'rank(y)')),
                              ('reverse', ('-(x)', '-(rank(x))'))]:
        pairs[name] = {'status': 'compiled', 'experiment': {
            'experiment_id': name, 'compilation_digest': name + '-digest',
            'conditions': [], 'arms': [
                {'arm_id': arm, 'scope': deepcopy(scope), 'settings': deepcopy(settings),
                 'binding': {'bound_expression': expression}, 'template_id': name + arm}
                for arm, expression in zip(('baseline', 'treatment'), expressions)]}}
    tree = {'schema_version': 1, 'scope': scope,
            'period': {'start': '2020-01-01', 'end': '2025-12-31'},
            'source_ids': ['source'], 'roots': ['root'], 'nodes': []}
    for name, parent, parent_arm, ids in [
            ('root', None, None, ('s0', 's1')),
            ('left', 'root', 'baseline', ('s0', 's2')),
            ('right', 'root', 'treatment', ('s1', 's3'))]:
        tree['nodes'].append({'node_id': name, 'parent_id': parent,
            'parent_arm_id': parent_arm, 'pair_ref': name,
            'expected_simulation_identities': dict(zip(('baseline', 'treatment'), ids)),
            'targets': {'baseline': ['left'] if name == 'root' else [],
                        'treatment': ['right'] if name == 'root' else []},
            'fallback': [], 'reverse': {}})
    return tree, {'compiled_pairs': pairs, 'sources': {'source': {'digest': 'fixture'}}}


def freeze(tree=None, resources=None):
    """Input: optional tree/resources dicts. Output: validated frozen root dict."""
    default_tree, default_resources = fixture()
    result = subject.validate_tree(tree or default_tree, resources or default_resources)
    if result['status'] != 'validated':
        raise AssertionError(result)
    return next(node for node in result['tree']['nodes'] if node['node_id'] == 'root')


def row(identity, sharpe=1.0, returns=0.1, status='completed'):
    """Input: identity/metrics/status scalars. Output: fictional measured row dict."""
    tree, _ = fixture()
    return {'simulation_identity': identity, 'status': status,
            'scope': tree['scope'], 'period': tree['period'],
            'sharpe': sharpe, 'returns': returns}


class TreeTests(unittest.TestCase):
    def test_scope_requires_actual_region_universe_and_integer_delay(self):
        tree, resources = fixture()
        for scope in ({'anything': 'invented'}, {'region': '', 'universe': 'TOP3000', 'delay': 1},
                      {'region': 'USA', 'universe': 'TOP3000', 'delay': True}):
            with self.subTest(scope=scope):
                tree['scope'] = scope
                for pair in resources['compiled_pairs'].values():
                    for arm in pair['experiment']['arms']:
                        arm['scope'] = scope
                self.assertEqual(subject.validate_tree(tree, resources)['status'], 'rejected')

    def test_four_unique_roots(self):
        tree, resources = fixture()
        template = deepcopy(tree['nodes'][0])
        tree['nodes'] = []
        tree['roots'] = []
        for i in range(4):
            name = 'root' + str(i)
            root = deepcopy(template)
            root.update(node_id=name, pair_ref=name, targets={'baseline': [], 'treatment': []},
                        expected_simulation_identities={'baseline': name + 'a', 'treatment': name + 'b'})
            resources['compiled_pairs'][name] = deepcopy(resources['compiled_pairs']['root'])
            for arm in resources['compiled_pairs'][name]['experiment']['arms']:
                arm['binding']['bound_expression'] += '+' + str(i)
            tree['roots'].append(name)
            tree['nodes'].append(root)
        result = subject.validate_tree(tree, resources)
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(result['simulation_count'], 8)
        tree['limits'] = {'max_width': 3}
        self.assertEqual(subject.validate_tree(tree, resources)['status'], 'rejected')

    def test_two_children_per_arm_reuse_parent_and_count_only_distinct_identities(self):
        tree, resources = fixture()
        for old, arm, identity in [('left', 'baseline', 's4'), ('right', 'treatment', 's5')]:
            child = deepcopy(next(node for node in tree['nodes'] if node['node_id'] == old))
            new = old + '2'
            child.update(node_id=new, pair_ref=new)
            child['expected_simulation_identities']['treatment'] = identity
            resources['compiled_pairs'][new] = deepcopy(resources['compiled_pairs'][old])
            resources['compiled_pairs'][new]['experiment']['arms'][1]['binding']['bound_expression'] += '+1'
            tree['nodes'].append(child)
            tree['nodes'][0]['targets'][arm].append(new)
        result = subject.validate_tree(tree, resources)
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(result['simulation_count'], 6)
        self.assertEqual(subject.route_pair(freeze(tree, resources), [row('s0'), row('s1')])[
            'selected_node_ids'], ['left', 'left2', 'right', 'right2'])
        tree['nodes'][0]['targets']['baseline'].append('third')
        self.assertEqual(subject.validate_tree(tree, resources)['status'], 'rejected')

    def test_depth_three_is_supported_only_when_explicitly_bounded(self):
        tree, resources = fixture()
        grandchild = deepcopy(tree['nodes'][1])
        grandchild.update(node_id='third', parent_id='left', parent_arm_id='treatment', pair_ref='third',
                          expected_simulation_identities={'baseline': 's2', 'treatment': 's4'})
        pair = deepcopy(resources['compiled_pairs']['left'])
        pair['experiment']['arms'][0]['binding']['bound_expression'] = 'ts_mean(x, 5)'
        pair['experiment']['arms'][1]['binding']['bound_expression'] = 'ts_mean(x, 22)'
        resources['compiled_pairs']['third'] = pair
        tree['nodes'].append(grandchild)
        tree['nodes'][1]['targets']['treatment'] = ['third']
        self.assertEqual(subject.validate_tree(tree, resources)['status'], 'rejected')
        tree['limits'] = {'max_depth': 3}
        result = subject.validate_tree(tree, resources)
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(next(n for n in result['tree']['nodes'] if n['node_id'] == 'third')['layer'], 3)

    def test_identity_aliases_and_parent_baseline_substitution_are_rejected(self):
        for mutation in ('same_config_new_identity', 'same_identity_new_config', 'changed_parent'):
            with self.subTest(mutation=mutation):
                tree, resources = fixture()
                child = tree['nodes'][1]
                if mutation == 'same_config_new_identity':
                    child['expected_simulation_identities']['baseline'] = 'new'
                if mutation == 'same_identity_new_config':
                    child['expected_simulation_identities']['treatment'] = 's0'
                if mutation == 'changed_parent':
                    child['expected_simulation_identities']['baseline'] = 'new'
                    resources['compiled_pairs']['left']['experiment']['arms'][0]['binding']['bound_expression'] = 'z'
                self.assertEqual(subject.validate_tree(tree, resources)['status'], 'rejected')

    def test_cyclic_and_nonjson_inputs_reject_without_throwing(self):
        tree, resources = fixture()
        tree['nodes'].append(tree)
        self.assertEqual(subject.validate_tree(tree, resources)['status'], 'rejected')
        tree, resources = fixture()
        tree['nodes'][0]['predicate'] = lambda: True
        self.assertEqual(subject.validate_tree(tree, resources)['status'], 'rejected')

    def test_swapped_pair_is_not_novel_padding(self):
        tree, resources = fixture()
        root = deepcopy(tree['nodes'][0])
        root.update(node_id='swap', pair_ref='swap', targets={'baseline': [], 'treatment': []},
                    expected_simulation_identities={'baseline': 's1', 'treatment': 's0'})
        pair = deepcopy(resources['compiled_pairs']['root'])
        pair['experiment']['arms'][0]['binding']['bound_expression'] = 'rank(x)'
        pair['experiment']['arms'][1]['binding']['bound_expression'] = 'x'
        resources['compiled_pairs']['swap'] = pair
        tree['nodes'].append(root)
        tree['roots'].append('swap')
        self.assertEqual(subject.validate_tree(tree, resources)['status'], 'rejected')

    def test_freezes_sources_receipts_and_inputs_without_mutation(self):
        tree, resources = fixture()
        before = deepcopy((tree, resources))
        result = subject.validate_tree(tree, resources)
        self.assertEqual(result['status'], 'validated')
        self.assertEqual((tree, resources), before)
        self.assertEqual(result['simulation_count'], 4)
        self.assertEqual(result['tree']['limits'], {'max_depth': 2, 'max_width': 4})
        self.assertEqual(result['tree']['sources'], resources['sources'])
        resources['sources']['source']['digest'] = 'changed'
        self.assertNotEqual(result['tree']['sources'], resources['sources'])
        self.assertEqual(result, subject.validate_tree(*before))

    def test_invalid_schema_limits_sources_and_topology_reject_atomically(self):
        for mutation in ('bool_limit', 'zero_limit', 'depth', 'width', 'source',
                         'duplicate_root', 'duplicate_node', 'target', 'parent',
                         'cycle', 'predicate', 'identity', 'receipt', 'scope'):
            with self.subTest(mutation=mutation):
                tree, resources = fixture()
                root = tree['nodes'][0]
                if mutation == 'bool_limit': tree['limits'] = {'max_depth': True}
                if mutation == 'zero_limit': tree['limits'] = {'max_width': 0}
                if mutation == 'depth': tree['limits'] = {'max_depth': 1}
                if mutation == 'width': tree['limits'] = {'max_width': 0}
                if mutation == 'source': tree['source_ids'] = ['missing']
                if mutation == 'duplicate_root': tree['roots'] *= 2
                if mutation == 'duplicate_node': tree['nodes'].append(deepcopy(root))
                if mutation == 'target': root['targets']['baseline'] = ['missing']
                if mutation == 'parent': tree['nodes'][1]['parent_arm_id'] = 'treatment'
                if mutation == 'cycle': tree['nodes'][1]['targets']['baseline'] = ['root']
                if mutation == 'predicate': root['predicate'] = '__import__("os")'
                if mutation == 'identity': root['expected_simulation_identities']['treatment'] = 's0'
                if mutation == 'receipt': resources['compiled_pairs']['root']['status'] = 'rejected'
                if mutation == 'scope': resources['compiled_pairs']['root']['experiment']['arms'][1]['scope']['delay'] = 0
                result = subject.validate_tree(tree, resources)
                self.assertEqual(result['status'], 'rejected')
                self.assertIsNone(result['tree'])
                self.assertTrue(result['reasons'])

    def test_positive_generic_bounds_and_no_padded_duplicate_arms(self):
        tree, resources = fixture()
        tree['limits'] = {'max_depth': 3, 'max_width': 1}
        self.assertEqual(subject.validate_tree(tree, resources)['status'], 'validated')
        resources['compiled_pairs']['root']['experiment']['arms'][1]['binding'] = {'bound_expression': 'x'}
        self.assertEqual(subject.validate_tree(tree, resources)['status'], 'rejected')

    def test_node_tampering_is_inconclusive(self):
        node = freeze()
        node['targets']['baseline'] = ['invented']
        result = subject.route_pair(node, [row('s0'), row('s1')])
        self.assertEqual(result['status'], 'inconclusive')
        self.assertEqual(result['selected_node_ids'], [])


class RoutingTests(unittest.TestCase):
    def test_restart_uses_frozen_signal_policy_not_new_defaults(self):
        node = freeze()
        expected = subject.route_pair(node, [row('s0', 0.9), row('s1', 0.9)])
        with patch.object(subject, 'SIGNAL_SHARPE', 2.0):
            self.assertEqual(subject.route_pair(node, [row('s0', 0.9), row('s1', 0.9)]), expected)

    def test_supplied_expression_or_settings_conflict_cannot_route(self):
        for key, value in [('expression', 'fabricated'), ('settings', {'delay': 0})]:
            with self.subTest(key=key):
                bad = row('s0')
                bad[key] = value
                result = subject.route_pair(freeze(), [bad, row('s1')])
                self.assertEqual(result['status'], 'inconclusive')
                self.assertIn('identity_conflict', [r['code'] for r in result['reasons']])

    def test_two_negative_arms_require_two_actual_confirmations(self):
        tree, resources = fixture()
        tree['nodes'][0]['reverse'] = {arm: {
            'pair_ref': 'reverse', 'arm_id': arm, 'simulation_identity': identity,
            'interpretation': 'Frozen reverse semantics', 'targets': []}
            for arm, identity in [('baseline', 'r0'), ('treatment', 'r1')]}
        node = freeze(tree, resources)
        negatives = [row('s0', -0.9, -0.1), row('s1', -1, -0.2)]
        waiting = subject.route_pair(node, negatives)
        self.assertEqual(waiting['confirmation_simulation_identities'], ['r0', 'r1'])
        self.assertEqual(waiting['selected_arm_ids'], [])
        confirmed = subject.route_pair(node, negatives + [row('r1'), row('r0')])
        self.assertEqual(confirmed['selected_arm_ids'], ['baseline', 'treatment'])
        self.assertEqual(confirmed['selected_simulation_identities'], ['r0', 'r1'])
        self.assertEqual(confirmed['status'], 'finished')
        self.assertEqual(subject.validate_tree(tree, resources)['simulation_count'], 6)

    def test_opposite_signs_continue_positive_and_frozen_reverse_targets(self):
        tree, resources = fixture()
        root = tree['nodes'][0]
        root['reverse'] = {'baseline': {'pair_ref': 'reverse', 'arm_id': 'baseline',
            'simulation_identity': 'r0', 'interpretation': 'Frozen reverse semantics', 'targets': ['left']}}
        root['targets']['baseline'] = []
        tree['nodes'][1]['parent_arm_id'] = 'reverse:baseline'
        tree['nodes'][1]['expected_simulation_identities']['baseline'] = 'r0'
        resources['compiled_pairs']['left']['experiment']['arms'][0]['binding']['bound_expression'] = '-(x)'
        node = freeze(tree, resources)
        rows = [row('s0', -0.9, -0.1), row('s1')]
        pending = subject.route_pair(node, rows)
        self.assertEqual(pending['status'], 'waiting')
        self.assertEqual(pending['selected_node_ids'], ['right'])
        unknown = subject.route_pair(node, rows + [row('r0', status='unknown')])
        self.assertEqual(unknown['status'], 'recover')
        self.assertEqual(unknown['confirmation_simulation_identities'], [])
        complete = subject.route_pair(node, rows + [row('r0')])
        self.assertEqual(complete['status'], 'branched')
        self.assertEqual(complete['selected_node_ids'], ['left', 'right'])

    def test_permanent_exhaustion_and_malformed_inputs_fail_closed(self):
        result = subject.route_pair(freeze(), [row('s0'), row('s1', status='exhausted')])
        self.assertEqual(result['status'], 'inconclusive')
        self.assertIn('exhausted', [r['code'] for r in result['reasons']])
        for measurements in (None, {}, [None], ['bad']):
            self.assertEqual(subject.route_pair(freeze(), measurements)['status'], 'inconclusive')
        for tree, resources in [(None, {}), ({}, None), ([], [])]:
            self.assertEqual(subject.validate_tree(tree, resources)['status'], 'rejected')

    def test_zero_one_two_signals_and_boundaries(self):
        for a, b, selected in [(0.8, 0.8, []), (0.9, 0.8, ['baseline']),
                               (0.8, 0.9, ['treatment']), (0.9, 0.9, ['baseline', 'treatment'])]:
            with self.subTest(a=a, b=b):
                result = subject.route_pair(freeze(), [row('s1', b), row('s0', a)])
                self.assertEqual(result['selected_arm_ids'], selected)
                self.assertEqual(result['selected_node_ids'],
                                 [name for arm, name in [('baseline', 'left'), ('treatment', 'right')]
                                  if arm in selected])
                self.assertEqual(result['status'], 'branched' if selected else 'finished')
        for sharpe, returns in [(0.9, 0), (1, -0.1), (-0.9, 0), (-0.8, -0.1)]:
            result = subject.route_pair(freeze(), [row('s0', sharpe, returns), row('s1', 0)])
            self.assertEqual(result['status'], 'finished')

    def test_missing_pending_unknown_failed_conflict_are_not_no_signal(self):
        cases = [([row('s0', 0)], 'recover', 'missing'),
                 ([row('s0', 0), row('s1', status='pending')], 'waiting', 'pending'),
                 ([row('s0', 0), row('s1', status='unknown')], 'recover', 'unknown'),
                 ([row('s0', 0), row('s1', status='failed')], 'inconclusive', 'failed'),
                 ([row('s0'), row('s0', 2), row('s1')], 'inconclusive', 'conflict')]
        for rows, status, code in cases:
            with self.subTest(code=code):
                result = subject.route_pair(freeze(), rows)
                self.assertEqual(result['status'], status)
                self.assertIn(code, [reason['code'] for reason in result['reasons']])
                self.assertEqual(result['selected_node_ids'], [])

    def test_nonfinite_missing_scope_period_invalid_metrics_recover(self):
        for key, value in [('sharpe', float('nan')), ('returns', float('inf')),
                           ('sharpe', True), ('returns', None), ('scope', {}),
                           ('period', {'start': '2021-01-01', 'end': '2025-12-31'})]:
            with self.subTest(key=key, value=value):
                bad = row('s1', 0)
                bad[key] = value
                result = subject.route_pair(freeze(), [row('s0', 0), bad])
                self.assertEqual(result['status'], 'recover')
                self.assertEqual(result['selected_arm_ids'], [])

    def test_exact_duplicate_replay_and_order_are_idempotent(self):
        rows = [row('s0'), row('s1')]
        before = deepcopy(rows)
        expected = subject.route_pair(freeze(), rows)
        self.assertEqual(expected, subject.route_pair(freeze(), rows[::-1] + [row('s0')]))
        self.assertEqual(rows, before)

    def test_unknown_unrelated_rows_never_satisfy_missing_expected_arm(self):
        result = subject.route_pair(freeze(), [row('s0'), row('unrelated')])
        self.assertEqual(result['status'], 'recover')
        self.assertEqual(result['selected_node_ids'], [])
        result = subject.route_pair(freeze(), [row('s0'), row('s1'), row('unrelated', status='unknown')])
        self.assertEqual(result['status'], 'branched')

    def test_oversized_integer_metric_is_invalid_not_an_exception(self):
        result = subject.route_pair(freeze(), [row('s0', 10 ** 500), row('s1')])
        self.assertEqual(result['status'], 'recover')
        self.assertIn('invalid_metrics', [r['code'] for r in result['reasons']])

    def test_negative_requires_declaration_and_actual_confirmation(self):
        node = freeze()
        result = subject.route_pair(node, [row('s0', -0.9, -0.1), row('s1', 0)])
        self.assertEqual(result['status'], 'inconclusive')
        self.assertIn('reverse_not_declared', [r['code'] for r in result['reasons']])
        tree, resources = fixture()
        tree['nodes'][0]['reverse'] = {'baseline': {
            'pair_ref': 'reverse', 'arm_id': 'baseline', 'simulation_identity': 'r0',
            'interpretation': 'Explicit fictional reverse hypothesis', 'targets': []}}
        node = freeze(tree, resources)
        original = [row('s0', -0.9, -0.1), row('s1', 0)]
        result = subject.route_pair(node, original)
        self.assertEqual(result['status'], 'waiting')
        self.assertEqual(result['confirmation_simulation_identities'], ['r0'])
        self.assertEqual(result['selected_arm_ids'], [])
        result = subject.route_pair(node, original + [row('r0', 0.9, 0.1)])
        self.assertEqual(result['status'], 'finished')
        self.assertEqual(result['selected_arm_ids'], ['baseline'])
        self.assertEqual(result['selected_simulation_identities'], ['r0'])
        result = subject.route_pair(node, original + [row('r0', -1, -0.1)])
        self.assertEqual(result['selected_arm_ids'], [])
        self.assertIn('reverse_not_confirmed', [r['code'] for r in result['reasons']])

    def test_fallback_only_after_complete_zero_signal_pair(self):
        tree, resources = fixture()
        fallback = deepcopy(tree['nodes'][0])
        fallback.update(node_id='fallback', pair_ref='fallback', parent_id='root',
                        parent_arm_id='fallback', targets={'baseline': [], 'treatment': []},
                        expected_simulation_identities={'baseline': 'f0', 'treatment': 'f1'})
        tree['nodes'].append(fallback)
        tree['nodes'][0]['fallback'] = ['fallback']
        node = freeze(tree, resources)
        result = subject.route_pair(node, [row('s0', 0), row('s1', 0)])
        self.assertEqual(result['status'], 'branched')
        self.assertEqual(result['selected_node_ids'], ['fallback'])
        self.assertEqual(result['branch_kind'], 'fallback')
        self.assertEqual(subject.route_pair(node, [row('s0', 0)])['selected_node_ids'], [])


if __name__ == '__main__':
    unittest.main()
