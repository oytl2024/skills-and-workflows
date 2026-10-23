import copy
import math
import unittest
from unittest.mock import patch

from wqb.benchmark import AlphaBenchmarkResult
from wqb.benchmark_rules import default_benchmark_rules
from wqb.cli import simulation_identity_hash
from wqb.experiment_tree import validate_tree
from wqb.seed_policy import compare_versions, select_seeds


def measured(alpha_id='p', lane='lane-1'):
    """Input: identity/lane strings. Output: dict of fictional checked research evidence."""
    row = {'alpha_id': alpha_id, 'expression_hash': alpha_id + '-hash',
            'lane_id': lane, 'expression': 'rank(x)', 'status': 'CHECKED',
            'settings': {'region': 'USA', 'delay': 1, 'universe': 'TOP3000', 'decay': 2},
            'test_period': '2014-2024', 'measurement_scope': 'IS',
            'metrics': {'sharpe': 1.5, 'fitness': .5, 'returns': .03, 'turnover': .2},
            'hard_pass': False, 'failed': ['LOW_FITNESS'],
            'pending': ['SELF_CORRELATION', 'PROD_CORRELATION']}
    row['simulation_identity'] = simulation_identity_hash(row['expression'], row['settings'])
    return row


def frozen_feature(parent, child):
    """Input: measured dicts. Output: fictional compiler-backed frozen node/dict, no live calls."""
    scope = {key: parent['settings'][key] for key in ('region', 'delay', 'universe')}
    period = {'start': '2014-01-01', 'end': '2024-12-31'}
    receipt = {'status': 'compiled', 'experiment': {
        'experiment_id': 'feature', 'compilation_digest': 'fictional-compiler-receipt',
        'arms': [{'arm_id': arm, 'scope': scope, 'settings': row['settings'],
                  'binding': {'bound_expression': row['expression']}}
                 for arm, row in [('baseline', parent), ('treatment', child)]]}}
    tree = {'schema_version': 1, 'scope': scope, 'period': period,
            'source_ids': ['fixture'], 'roots': ['feature'], 'nodes': [{
                'node_id': 'feature', 'parent_id': None, 'parent_arm_id': None,
                'pair_ref': 'compiled', 'expected_simulation_identities': {
                    'baseline': parent['simulation_identity'],
                    'treatment': child['simulation_identity']},
                'targets': {'baseline': [], 'treatment': []}, 'fallback': [], 'reverse': {}}]}
    result = validate_tree(tree, {'compiled_pairs': {'compiled': receipt},
                                  'sources': {'fixture': {'digest': 'fictional'}}})
    if result['status'] != 'validated':
        raise AssertionError(result)
    return result['tree']['nodes'][0]


class SeedPolicyTests(unittest.TestCase):
    def test_deferred_correlations_do_not_block_research_or_qualify_submission(self):
        row = measured()
        original = copy.deepcopy(row)
        result = select_seeds([row], {})
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(result['selected'][0]['identity']['alpha_id'], 'p')
        self.assertEqual(result['selected'][0]['score'], .69)
        self.assertFalse(result['submission_qualified'])
        self.assertFalse(result['selected'][0]['submission_qualified'])
        self.assertEqual(row, original)

    def test_strict_sharpe_and_turnover_boundaries_precede_hard_pass_score(self):
        for metric, value, eligible in [('sharpe', 1.25, False),
                                        ('sharpe', 1.25000001, True),
                                        ('sharpe', -2., False),
                                        ('turnover', .4, False),
                                        ('turnover', .39999999, True),
                                        ('turnover', 0., True),
                                        ('turnover', -.001, False)]:
            row = measured()
            row.update(hard_pass=True, failed=[], pending=[])
            row['metrics'][metric] = value
            with self.subTest(metric=metric, value=value):
                self.assertEqual(bool(select_seeds([row], {})['selected']), eligible)

    def test_every_baseline_metric_must_be_present_finite_and_numeric(self):
        for key in ('sharpe', 'fitness', 'returns', 'turnover'):
            for value in (None, math.nan, math.inf, -math.inf, True, '1.5'):
                row = measured()
                row.update(hard_pass=True, failed=[], pending=[])
                row['metrics'][key] = value
                with self.subTest(key=key, value=value):
                    self.assertEqual(select_seeds([row], {})['selected'], [])
            row = measured()
            del row['metrics'][key]
            self.assertEqual(select_seeds([row], {})['selected'], [])

    def test_missing_or_invalid_baseline_check_evidence_fails_closed(self):
        for changes in ({'pending': ['NO_CHECKS']}, {'pending': ['LOW_FITNESS']},
                        {'pending': [{'name': 'SELF_CORRELATION', 'result': 'ERROR'}]},
                        {'failed': None}, {'failed': [{}]}, {'status': 'RUNNING'},
                        {'hard_pass': True}, {'failed': [{'name': 'LOW_FITNESS', 'result': 'PASS'}]}):
            with self.subTest(changes=changes):
                self.assertEqual(select_seeds([measured() | changes], {})['selected'], [])
        for key in ('failed', 'pending', 'alpha_id', 'expression_hash'):
            row = measured()
            del row[key]
            self.assertEqual(select_seeds([row], {})['selected'], [])

    def test_existing_score_gate_is_not_replaced_by_sharpe_or_supplied_score(self):
        row = measured()
        row['metrics'].update(fitness=.1, returns=0., turnover=0.)
        row['score'] = 1.
        result = select_seeds([row], {})
        self.assertEqual(result['selected'], [])
        self.assertIn('score_below_minimum', result['rejected'][0]['reasons'])
        # A hand-computed .69 must pass an inclusive .69 gate, not a higher one.
        row = measured()
        self.assertTrue(select_seeds([row], {'minimum_score': .69})['selected'])
        self.assertFalse(select_seeds([row], {'minimum_score': .690001})['selected'])

    def test_score_then_sharpe_then_identity_ranking_and_cap_per_lane(self):
        rows = [measured(f'a{i:02d}') for i in range(10)]
        high = measured('high')
        high['metrics']['fitness'] = 1.1
        sharpe = measured('sharpe')
        sharpe['metrics']['sharpe'] = 2.
        rows += [high, sharpe, measured('other', 'lane-2')]
        result = select_seeds(list(reversed(rows)), {})
        ids = [entry['identity']['alpha_id'] for entry in result['selected']]
        self.assertEqual(ids, ['high', 'sharpe', 'a00', 'a01', 'a02', 'a03', 'a04', 'a05', 'other'])
        self.assertEqual(len(result['rejected']), 4)
        self.assertTrue(all('lane_limit' in entry['reasons'] for entry in result['rejected']))
        self.assertEqual(result, select_seeds(rows, {}))

    def test_no_seed_exposes_rotation_without_starting_anything(self):
        result = select_seeds([], {})
        self.assertEqual(result['status'], 'no_seed')
        self.assertEqual(result['next_action'], 'rotate_research_choice')

    def test_duplicate_evidence_is_not_padded_and_conflicts_are_rejected(self):
        row = measured()
        self.assertEqual(len(select_seeds([row, copy.deepcopy(row)], {})['selected']), 1)
        other = copy.deepcopy(row)
        other['metrics']['sharpe'] = 2.
        result = select_seeds([row, other], {})
        self.assertEqual(result['selected'], [])
        self.assertIn('conflicting_identity', result['rejected'][0]['reasons'])

    def test_invalid_or_widening_policy_is_rejected(self):
        for policy in ({'schema_version': 2}, {'seed_selection_limit': 9},
                       {'seed_selection_limit': True}, {'seed_selection_limit': 0},
                       {'sharpe_floor': 1.}, {'turnover_max': .5},
                       {'minimum_score': .54}, {'minimum_score': math.nan},
                       {'typo': 1}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                select_seeds([measured()], policy)

    def test_negative_signal_needs_a_real_positive_reverse_measurement(self):
        negative = measured('negative')
        negative['metrics'].update(sharpe=-2., returns=-.03)
        reverse = measured('reverse')
        reverse.update(expression='-(rank(x))', parent_alpha_id='negative')
        reverse['simulation_identity'] = simulation_identity_hash(reverse['expression'], reverse['settings'])
        result = select_seeds([negative, reverse], {})
        self.assertEqual([r['identity']['alpha_id'] for r in result['selected']], ['reverse'])
        self.assertEqual(negative['metrics']['sharpe'], -2.)

    def test_invalid_duplicate_cannot_leave_a_conflicting_valid_seed(self):
        row = measured()
        conflict = copy.deepcopy(row)
        conflict['metrics']['fitness'] = None
        result = select_seeds([row, conflict], {})
        self.assertEqual(result['selected'], [])
        self.assertIn('conflicting_identity', result['rejected'][0]['reasons'])

    def test_unrepresentable_numbers_fail_closed_instead_of_crashing(self):
        row = measured()
        row['metrics']['fitness'] = 10 ** 1000
        self.assertEqual(select_seeds([row], {})['selected'], [])

    def test_lower_declared_limit_and_stricter_thresholds_are_enforced(self):
        result = select_seeds([measured('a'), measured('b')], {'seed_selection_limit': 1})
        self.assertEqual([r['identity']['alpha_id'] for r in result['selected']], ['a'])
        self.assertEqual(select_seeds([measured()], {'turnover_max': .2})['selected'], [])
        self.assertEqual(select_seeds([measured()], {'sharpe_floor': 1.5})['selected'], [])

    def test_existing_point_five_seven_score_passes_default_point_five_five_gate(self):
        row = measured()
        row['metrics']['fitness'] = .1
        result = select_seeds([row], {})
        self.assertEqual(result['selected'][0]['score'], .57)
        row['metrics']['returns'] = 0.
        self.assertEqual(select_seeds([row], {})['selected'], [])

    def test_score_does_not_override_weak_or_pending_labels(self):
        row = measured()
        row.update(failed=[], pending=[])
        result = select_seeds([row], {})
        self.assertEqual(result['selected'], [])
        self.assertEqual(result['rejected'][0]['benchmark_label'], 'weak_discard')
        self.assertEqual(result['rejected'][0]['score'], .59)
        for label in ('weak_discard', 'pending_review'):
            with self.subTest(label=label), patch('wqb.seed_policy.benchmark_alpha_record',
                    return_value=AlphaBenchmarkResult(label, .99, 1, [], 'repair')):
                self.assertEqual(select_seeds([measured()], {})['selected'], [])

    def test_submission_only_pending_is_deferred_but_baseline_pending_is_not(self):
        row = measured()
        row['pending'].append('LOW_2Y_SHARPE')
        with patch('wqb.seed_policy.benchmark_alpha_record') as benchmark:
            self.assertEqual(select_seeds([row], {})['selected'], [])
            benchmark.assert_not_called()
        row['pending'].remove('LOW_2Y_SHARPE')
        result = select_seeds([row], {})
        self.assertFalse(result['selected'][0]['submission_qualified'])
        self.assertEqual(row['pending'], ['SELF_CORRELATION', 'PROD_CORRELATION'])

    def test_explicit_frozen_benchmark_rules_empty_and_consumer_filtered(self):
        row = measured()
        row['metrics']['fitness'] = .1
        row['metrics']['returns'] = 0.
        row['pnl_note'] = 'steady'
        rules = default_benchmark_rules()
        original = copy.deepcopy(rules)
        self.assertTrue(select_seeds([row], {}, benchmark_rules=rules)['selected'])
        self.assertEqual(select_seeds([row], {}, benchmark_rules=[])['selected'], [])
        for rule in rules:
            rule.consumed_by[:] = ['candidate_gate']
        self.assertEqual(select_seeds([row], {}, benchmark_rules=rules)['selected'], [])
        self.assertTrue(select_seeds([row], {}, benchmark_rules=original)['selected'])
        for invalid in ({}, [None], [{'rule_id': 'bad'}]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                select_seeds([row], {}, benchmark_rules=invalid)

    def test_seed_requires_measured_expression_settings_cli_identity_scope_and_period(self):
        for key in ('expression', 'settings', 'simulation_identity', 'measurement_scope', 'test_period'):
            row = measured()
            del row[key]
            with self.subTest(missing=key):
                self.assertEqual(select_seeds([row], {})['selected'], [])
        for key, value in [('expression', 'rank(unmeasured)'), ('simulation_identity', 'forged'),
                           ('settings', {}), ('measurement_scope', True), ('test_period', 'unknown')]:
            with self.subTest(key=key, value=value):
                self.assertEqual(select_seeds([measured() | {key: value}], {})['selected'], [])
        row = measured()
        row['settings']['decay'] = 999
        self.assertEqual(select_seeds([row], {})['selected'], [])

    def test_seed_period_is_canonical_ordered_and_matches_reported_dates(self):
        for period in ('2024-2014', {'start': '2024-01-01', 'end': '2014-01-01'},
                       {'start': '2020-02-30', 'end': '2024-01-01'},
                       {'start': '20200101', 'end': '2024-01-01'}):
            with self.subTest(period=period):
                self.assertEqual(select_seeds([measured() | {'test_period': period}], {})['selected'], [])
        for dates in ({'startDate': '2014-01-01'},
                      {'startDate': '2013-01-01', 'endDate': '2024-01-01'},
                      {'startDate': '2024-01-01', 'endDate': '2014-01-01'},
                      {'startDate': '20140101', 'endDate': '20240101'}):
            row = measured()
            row['metrics'].update(dates)
            with self.subTest(dates=dates):
                self.assertEqual(select_seeds([row], {})['selected'], [])
        row = measured()
        row['test_period'] = {'start': '2020-01-02', 'end': '2024-01-01'}
        row['metrics'].update(startDate='2020-01-01', endDate='2024-01-01')
        self.assertEqual(select_seeds([row], {})['selected'], [])
        row['metrics']['startDate'] = '2020-01-02'
        self.assertTrue(select_seeds([row], {})['selected'])


class VersionComparisonTests(unittest.TestCase):
    def setUp(self):
        """Input: unittest instance. Output: None. Build isolated measured single-edit fixtures."""
        self.parent = measured()
        self.child = measured('c')
        self.child.update(parent_alpha_id='p', parent_expression_hash='p-hash')
        self.child['settings']['decay'] = 8
        self.child['metrics']['fitness'] = .7
        self.policy = {'target_metric': 'fitness', 'target_direction': 'increase',
                       'edit': 'decay', 'value': 8, 'turnover_max': .4}

    def compare(self):
        """Input: fixture attributes. Output: dict from the real pure comparator."""
        return compare_versions(self.parent, self.child, self.policy)

    def test_accepts_improvement_and_returns_actual_incumbent_identity(self):
        original = copy.deepcopy((self.parent, self.child, self.policy))
        result = self.compare()
        self.assertEqual(result['outcome'], 'accepted')
        self.assertEqual(result['incumbent']['alpha_id'], 'c')
        self.assertEqual(result['measured_child'], self.child)
        self.assertAlmostEqual(result['metric_changes']['fitness']['delta'], .2)
        self.assertFalse(result['submission_qualified'])
        self.assertEqual((self.parent, self.child, self.policy), original)
        result['measured_child']['metrics']['fitness'] = 999
        self.assertEqual(self.child['metrics']['fitness'], .7)

    def test_rejects_flat_target_sharpe_or_fitness_regression_with_zero_tolerance(self):
        for metric, value in [('fitness', .5), ('fitness', .4999999999),
                              ('sharpe', 1.4999999999)]:
            with self.subTest(metric=metric):
                self.setUp()
                self.child['metrics'][metric] = value
                result = self.compare()
                self.assertEqual(result['outcome'], 'rejected')
                self.assertEqual(result['incumbent']['alpha_id'], 'p')

    def test_turnover_may_increase_within_declared_bound_not_regress_other_metrics(self):
        self.child['metrics']['turnover'] = .39
        self.assertEqual(self.compare()['outcome'], 'accepted')
        for value in (.4, -.01):
            self.child['metrics']['turnover'] = value
            self.assertEqual(self.compare()['outcome'], 'rejected')
        self.policy.update(target_metric='turnover', target_direction='decrease')
        self.child['metrics']['turnover'] = .1
        self.assertEqual(self.compare()['outcome'], 'accepted')

    def test_new_baseline_failure_rejects_but_deferred_submission_checks_do_not(self):
        self.child['failed'].append({'name': 'CONCENTRATED_WEIGHT', 'result': 'FAIL'})
        self.assertEqual(self.compare()['outcome'], 'rejected')
        self.child['failed'] = ['LOW_FITNESS', 'SELF_CORRELATION']
        self.child['pending'] = ['PROD_CORRELATION']
        self.assertEqual(self.compare()['outcome'], 'accepted')

    def test_missing_invalid_or_incomparable_evidence_is_inconclusive(self):
        changes = [({'test_period': '2015-2024'}), {'measurement_scope': 'OS'},
                   {'parent_alpha_id': 'wrong'}, {'parent_expression_hash': 'wrong'},
                   {'lane_id': 'lane-2'}, {'pending': ['NO_CHECKS']},
                   {'expression': 'rank(y)'}, {'metrics': None}, {'alpha_id': ''}]
        for changeset in changes:
            with self.subTest(changeset=changeset):
                self.setUp()
                self.child.update(changeset)
                result = self.compare()
                self.assertEqual(result['outcome'], 'inconclusive')
                self.assertEqual(result['incumbent']['alpha_id'], 'p')
        for key in ('test_period', 'measurement_scope', 'expression', 'failed', 'pending'):
            self.setUp()
            self.parent.pop(key)
            self.child.pop(key)
            self.assertEqual(self.compare()['outcome'], 'inconclusive', key)

    def test_extra_setting_scope_changes_and_noop_are_not_controlled_edits(self):
        for key, value in [('region', 'EUR'), ('truncation', .1), ('decay', 2)]:
            self.setUp()
            self.child['settings'][key] = value
            self.assertEqual(self.compare()['outcome'], 'inconclusive')

    def test_reported_period_conflicts_or_incomplete_dates_are_inconclusive(self):
        self.parent['metrics']['startDate'] = '2014-01-01'
        self.child['metrics']['startDate'] = '2015-01-01'
        self.assertEqual(self.compare()['outcome'], 'inconclusive')
        self.child['metrics']['startDate'] = '2014-01-01'
        self.assertEqual(self.compare()['outcome'], 'inconclusive')
        self.parent['metrics']['endDate'] = self.child['metrics']['endDate'] = '2024-01-01'
        self.assertEqual(self.compare()['outcome'], 'accepted')

    def test_all_metrics_required_on_both_sides_even_if_not_target(self):
        for side in ('parent', 'child'):
            for key in ('sharpe', 'fitness', 'returns', 'turnover'):
                for value in (None, math.nan, math.inf, True, '1.5'):
                    self.setUp()
                    getattr(self, side)['metrics'][key] = value
                    with self.subTest(side=side, key=key, value=value):
                        self.assertEqual(self.compare()['outcome'], 'inconclusive')

    def test_missing_or_invalid_declared_policy_is_inconclusive_not_acceptance(self):
        for changes in ({'target_metric': 'unknown'}, {'target_direction': 'decrease'},
                        {'turnover_max': None}, {'turnover_max': math.inf},
                        {'comparison_tolerance': .01}, {'edit': 'unknown'}):
            self.setUp()
            self.policy.update(changes)
            self.assertEqual(self.compare()['outcome'], 'inconclusive')
        self.setUp()
        self.policy.pop('turnover_max')
        self.assertEqual(self.compare()['outcome'], 'inconclusive')

    def test_hard_pass_rejected_child_is_retained_for_separate_candidate_evaluation(self):
        self.child.update(hard_pass=True, failed=[], pending=[])
        self.child['metrics']['sharpe'] = 1.4
        result = self.compare()
        self.assertEqual(result['outcome'], 'rejected')
        self.assertEqual(result['incumbent']['alpha_id'], 'p')
        self.assertTrue(result['measured_child']['hard_pass'])
        self.assertFalse(result['submission_qualified'])

    def test_same_platform_alpha_cannot_masquerade_as_a_new_measured_version(self):
        self.child['alpha_id'] = self.parent['alpha_id']
        self.assertEqual(self.compare()['outcome'], 'inconclusive')

    def test_malformed_scope_period_and_controlled_values_are_inconclusive(self):
        for key in ('measurement_scope', 'test_period'):
            for value in (True, 12, [], {'unknown': None}):
                self.setUp()
                self.parent[key] = self.child[key] = value
                with self.subTest(key=key, value=value):
                    self.assertEqual(self.compare()['outcome'], 'inconclusive')
        for edit, value in [('decay', -1), ('decay', True), ('decay', {}),
                            ('neutralization', ''), ('truncation', math.nan)]:
            self.setUp()
            self.policy.update(edit=edit, value=value)
            self.child['settings'] = self.parent['settings'] | {edit: value}
            with self.subTest(edit=edit, value=value):
                self.assertEqual(self.compare()['outcome'], 'inconclusive')

    def test_baseline_turnover_cannot_be_negative(self):
        self.parent['metrics']['turnover'] = -.1
        self.assertEqual(self.compare()['outcome'], 'inconclusive')

    def test_all_supported_single_setting_edits_use_the_same_acceptance_contract(self):
        for edit, value in [('decay', 8), ('neutralization', 'INDUSTRY'), ('truncation', .05)]:
            self.setUp()
            self.policy.update(edit=edit, value=value)
            self.child['settings'] = self.parent['settings'] | {edit: value}
            self.assertEqual(self.compare()['outcome'], 'accepted')

    def test_invalid_scope_fields_cannot_make_two_invalid_measurements_comparable(self):
        for key, value in [('region', {}), ('universe', True), ('delay', True), ('delay', -1)]:
            self.setUp()
            self.parent['settings'][key] = self.child['settings'][key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(self.compare()['outcome'], 'inconclusive')

    def test_unplanned_setting_type_change_is_not_an_exact_controlled_change(self):
        self.child['settings']['delay'] = True
        self.assertEqual(self.compare()['outcome'], 'inconclusive')

    def test_legacy_comparator_stays_independent_of_new_turnover_policy(self):
        from wqb.repair_trace import compare_repair_experiment

        self.child['metrics']['turnover'] = .3
        self.assertEqual(self.compare()['outcome'], 'accepted')
        decision = self.policy | {'falsification': 'Fitness fails to improve',
                                  'applicability': 'Same measurement scope'}
        self.assertEqual(compare_repair_experiment(self.parent, self.child, decision)['outcome'], 'reject')

    def test_declared_and_reported_periods_must_be_canonical_ordered_and_consistent(self):
        for period in ('2024-2014', {'start': '2024-01-01', 'end': '2014-01-01'},
                       {'start': '20200101', 'end': '20241231'}):
            self.setUp()
            self.parent['test_period'] = self.child['test_period'] = period
            with self.subTest(period=period):
                self.assertEqual(self.compare()['outcome'], 'inconclusive')
        self.setUp()
        for row in (self.parent, self.child):
            row['metrics'].update(startDate='2013-01-01', endDate='2024-01-01')
        self.assertEqual(self.compare()['outcome'], 'inconclusive')
        for row in (self.parent, self.child):
            row['test_period'] = {'start': '2020-01-01', 'end': '2020-01-01'}
            row['metrics'].update(startDate='2020-01-01', endDate='2020-01-01')
        self.assertEqual(self.compare()['outcome'], 'accepted')


class FeatureComparisonTests(unittest.TestCase):
    def setUp(self):
        """Input: unittest instance. Output: None. Freeze a fictional compiler-backed Scout edit."""
        self.parent = measured()
        self.child = measured('c')
        self.child.update(expression='ts_mean(rank(x), 5)', parent_alpha_id='p',
                          parent_expression_hash='p-hash')
        self.child['simulation_identity'] = simulation_identity_hash(
            self.child['expression'], self.child['settings'])
        self.child['metrics']['fitness'] = .7
        self.node = frozen_feature(self.parent, self.child)
        self.policy = {'target_metric': 'fitness', 'target_direction': 'increase',
                       'edit': 'feature', 'turnover_max': .4}

    def compare(self):
        """Input: fixture attributes. Output: pure comparison dict using the approved frozen node."""
        return compare_versions(self.parent, self.child, self.policy, frozen_node=self.node)

    def test_accepts_only_the_frozen_compiled_feature_and_retains_incumbent_on_regression(self):
        original = copy.deepcopy((self.parent, self.child, self.policy, self.node))
        result = self.compare()
        self.assertEqual(result['outcome'], 'accepted')
        self.assertEqual(result['incumbent']['alpha_id'], 'c')
        self.assertFalse(result['submission_qualified'])
        self.assertEqual((self.parent, self.child, self.policy, self.node), original)
        self.child['metrics']['sharpe'] = 1.4
        self.assertEqual(self.compare()['outcome'], 'rejected')
        self.assertEqual(self.compare()['incumbent']['alpha_id'], 'p')

    def test_feature_requires_frozen_compiler_node_not_a_raw_expression_declaration(self):
        self.assertEqual(compare_versions(self.parent, self.child, self.policy)['outcome'], 'inconclusive')
        self.node = {'expression': self.child['expression']}
        self.assertEqual(self.compare()['outcome'], 'inconclusive')
        self.setUp()
        self.node['pair_receipt']['experiment']['arms'][1]['binding']['bound_expression'] = 'rank(z)'
        self.assertEqual(self.compare()['outcome'], 'inconclusive')

    def test_feature_rejects_unfrozen_identity_expression_settings_scope_period_and_lineage(self):
        changes = [('simulation_identity', 'wrong'), ('expression', 'rank(z)'),
                   ('parent_alpha_id', 'wrong'), ('expression_hash', ''),
                   ('test_period', '2015-2024'), ('measurement_scope', 'OS')]
        for key, value in changes:
            self.setUp()
            self.child[key] = value
            with self.subTest(key=key):
                self.assertEqual(self.compare()['outcome'], 'inconclusive')
        self.setUp()
        self.child['settings']['decay'] = 8
        self.child['simulation_identity'] = simulation_identity_hash(self.child['expression'], self.child['settings'])
        self.assertEqual(self.compare()['outcome'], 'inconclusive')
        self.setUp()
        self.parent['simulation_identity'] = 'wrong'
        self.assertEqual(self.compare()['outcome'], 'inconclusive')

    def test_feature_reported_dates_must_match_frozen_interval_not_just_each_other(self):
        for row in (self.parent, self.child):
            row['metrics'].update(startDate='2014-01-01', endDate='2024-01-01')
        self.assertEqual(self.compare()['outcome'], 'inconclusive')
        for row in (self.parent, self.child):
            row['metrics']['endDate'] = '2024-12-31'
        self.assertEqual(self.compare()['outcome'], 'accepted')

    def test_transform_and_expression_flags_do_not_enable_unverified_repair(self):
        self.policy['edit'] = 'transform'
        self.assertEqual(self.compare()['outcome'], 'inconclusive')
        self.setUp()
        self.policy['value'] = self.child['expression']
        self.assertEqual(self.compare()['outcome'], 'inconclusive')


if __name__ == '__main__':
    unittest.main()
