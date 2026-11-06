"""Offline contract tests for the pure, opt-in deterministic Repair provider."""

import copy
import ast
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from wqb.cli import simulation_identity_hash
from tests.test_template_binding import binding_fixture


def search_fixture():
    """Input: none. Output: parent/policy dict pair. Use fictional trusted frozen facts."""
    ref = dict(source_path='raw/platform/learn/repair.md', sha256='a' * 64,
               capture_date='2026-10-22', kind='documented')
    parent = dict(alpha_id='seed', expression='rank(cash / debt)',
                  settings=dict(region='USA', delay=1, universe='TOP3000', decay=2,
                                truncation=0.08, neutralization='INDUSTRY'),
                  metrics=dict(sharpe=1.4, fitness=0.8, turnover=0.35),
                  core_fields=['cash', 'debt'], conditions=['positive debt'], direction='positive')
    parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
    rules = [dict(rule_id='smooth', edit='decay', effect='smoothing', priority=10,
                  target_metric='turnover', target_direction='decrease', grid=[2, 4, 8],
                  requires=dict(noisy=True), evidence_refs=[ref]),
             dict(rule_id='bound', edit='truncation', effect='bounded_weights', priority=20,
                  target_metric='fitness', target_direction='increase', grid=[0.04, 0.06],
                  requires=dict(concentrated=True), evidence_refs=[ref])]
    traits = {name: dict(basis='source', value=True, evidence_refs=[ref])
              for name in ('noisy', 'concentrated')}
    return parent, dict(schema_version=1, rules=rules, traits=traits)


class RepairSearchTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: None. Detect missing provider as a meaningful red assertion."""
        self.assertIsNotNone(importlib.util.find_spec('wqb.repair_search'),
                             'Task4 deterministic Repair provider is not implemented')
        from wqb.repair_search import prepare_search
        self.prepare = prepare_search
        self.parent, self.policy = search_fixture()

    def plan(self, allowance=8, history=None):
        """Input: allowance int/history list or None. Output: plan dict; use no real run/files."""
        return self.prepare(Path('nonexistent-offline-run'), self.parent,
                            [] if history is None else history, allowance, self.policy)

    def test_settings_single_change_priority_and_cli_identity(self):
        result = self.plan()
        self.assertEqual(result['planner_kind'], 'deterministic')
        self.assertEqual(result['planner_version'], 1)
        self.assertEqual(result['status'], 'validated')
        self.assertEqual([v['decision']['value'] for v in result['variants']], [4, 8, 0.04, 0.06])
        for variant in result['variants']:
            self.assertEqual(variant['expression'], self.parent['expression'])
            self.assertEqual(sum(variant['settings'][k] != v
                                 for k, v in self.parent['settings'].items()), 1)
            self.assertEqual(variant['expression_hash'], simulation_identity_hash(
                variant['expression'], variant['settings']))
            self.assertEqual(variant['parent_expression_hash'], self.parent['expression_hash'])
            self.assertEqual(variant['parent_alpha_id'], 'seed')
        self.assertNotIn('judgment', result)
        self.assertNotIn('receipt_path', result)

    def test_budget_caps_without_mutation_or_files(self):
        before = copy.deepcopy((self.parent, self.policy))
        self.assertEqual(len(self.plan(1)['variants']), 1)
        self.assertEqual((self.parent, self.policy), before)
        self.assertFalse(Path('nonexistent-offline-run').exists())

    def test_zero_budget_and_explicit_stop(self):
        result = self.plan(0)
        self.assertEqual(result['stop_reason'], 'allowance_exhausted')
        self.assertEqual(result['variants'], [])
        self.policy['stop'] = True
        self.assertEqual(self.plan()['stop_reason'], 'stopped')

    def test_qualified_parent_stops(self):
        self.parent['hard_pass'] = True
        self.assertEqual(self.plan()['stop_reason'], 'already_qualified')

    def test_dedup_parent_payload_and_history_hashes_even_unknown_posts(self):
        first = self.plan()
        history = [dict(first['variants'][0], expression_hash='b' * 64, status='UNKNOWN_POST'),
                   dict(expression_hash=first['variants'][1]['expression_hash'], status='QUARANTINED_404')]
        result = self.plan(history=history)
        self.assertEqual(len(result['variants']), 2)
        self.assertTrue(all(v['decision']['edit'] == 'truncation' for v in result['variants']))
        exhausted = self.plan(history=first['variants'])
        self.assertEqual(exhausted['status'], 'exhausted')
        self.assertEqual(exhausted['stop_reason'], 'search_space_exhausted')

    def test_stable_replay_and_order_independent_rules_and_grids(self):
        original = json.dumps(self.plan(), sort_keys=True)
        self.policy['rules'].reverse()
        for rule in self.policy['rules']:
            rule['grid'].reverse()
        self.assertEqual(json.dumps(self.plan(), sort_keys=True), original)

    def test_unknown_or_hypothesis_trait_skips_instead_of_imputation(self):
        for trait in ({}, dict(basis='hypothesis', value=True, evidence_refs=[]),
                      dict(basis='source', value='unknown', evidence_refs=[])):
            with self.subTest(trait=trait):
                self.policy['traits']['noisy'] = trait
                result = self.plan()
                self.assertTrue(all(v['decision']['edit'] == 'truncation' for v in result['variants']))
                self.assertTrue(any(s['rule_id'] == 'smooth' and 'trait' in s['reason']
                                    for s in result['skipped']))

    def test_measured_trait_requires_measured_evidence_not_source_relabeling(self):
        trait = self.policy['traits']['noisy']
        trait['basis'] = 'measured'
        self.assertEqual(len(self.plan()['variants']), 2)
        trait['evidence_refs'] = [dict(trait['evidence_refs'][0], kind='measured',
                                     experiment_refs=['raw/research/noise.json'])]
        self.assertEqual(len(self.plan()['variants']), 4)

    def test_sourced_nuisance_exposure_neutralization(self):
        self.policy['traits']['sector_exposure'] = copy.deepcopy(self.policy['traits']['noisy'])
        rule = copy.deepcopy(self.policy['rules'][0])
        rule.update(rule_id='neutral', edit='neutralization', effect='nuisance_exposure',
                    grid=['SECTOR'], requires=dict(sector_exposure=True))
        self.policy['rules'] = [rule]
        result = self.plan()
        self.assertEqual(result['variants'][0]['settings']['neutralization'], 'SECTOR')
        self.policy['traits'].pop('sector_exposure')
        self.assertEqual(self.plan()['status'], 'exhausted')

    def test_source_less_rules_rejected_without_fallback(self):
        for rule in self.policy['rules']:
            rule['evidence_refs'] = []
        result = self.plan()
        self.assertEqual(result['variants'], [])
        self.assertTrue(all('source' in s['reason'] for s in result['skipped']))

    def test_invalid_policy_bounds_targets_and_unbounded_grids_fail_closed(self):
        for patch in (dict(grid=[-1]), dict(grid=[True]), dict(grid=[float('nan')]),
                      dict(grid=list(range(100))), dict(target_direction='increase'),
                      dict(target_metric=['turnover', 'fitness']), dict(edit='flip_direction'),
                      dict(priority=True), dict(extra_authority=True)):
            with self.subTest(patch=patch):
                parent, policy = search_fixture()
                policy['rules'][0].update(patch)
                result = self.prepare(Path('.'), parent, [], 8, policy)
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['stop_reason'], 'invalid_policy')
                self.assertEqual(result['variants'], [])

    def test_invalid_allowance_and_parent_identity(self):
        for allowance in (-1, True, 1.0, 9):
            with self.subTest(allowance=allowance):
                self.assertEqual(self.plan(allowance)['status'], 'blocked')
        self.parent['expression_hash'] = 'f' * 64
        self.assertEqual(self.plan()['stop_reason'], 'invalid_parent')

    def test_missing_measured_target_skips(self):
        self.parent['metrics']['turnover'] = float('nan')
        result = self.plan()
        self.assertEqual(len(result['variants']), 2)
        self.assertTrue(any(s['reason'] == 'target_unmeasured' for s in result['skipped']))

    def test_duplicate_rules_and_duplicate_grids_never_pad(self):
        self.policy['rules'][0]['grid'] = [4, 4, 8]
        extra = copy.deepcopy(self.policy['rules'][0])
        extra['rule_id'] = 'same-edit'
        self.policy['rules'].append(extra)
        self.assertEqual(len(self.plan()['variants']), 4)

    def transform_policy(self):
        """Input: TestCase. Output: None. Supply a fictional typed smoothing rule, not name-derived facts."""
        template, fields, operators, scope = binding_fixture()
        rule = self.policy['rules'][0]
        rule.update(edit='transform', grid=[2, 5, 10], transform=dict(
            operator='ts_mean', parameter='d', parameter_kind='window', bounds=[1, 32],
            frequency_trait='update_frequency', preserves_direction=True))
        self.policy['rules'] = [rule]
        self.policy['traits']['update_frequency'] = dict(
            basis='source', value=5, units='sessions', evidence_refs=rule['evidence_refs'])
        self.policy['resources'] = dict(template=template, field_rows=fields,
                                       operator_rows=operators, scope=scope, resource_contract_version=1)

    def test_typed_smoothing_uses_frequency_bounds_and_preserves_parent_subtree(self):
        self.transform_policy()
        original = copy.deepcopy((self.parent, self.policy))
        result = self.plan()
        self.assertEqual(result['status'], 'validated')
        self.assertEqual([v['decision']['value'] for v in result['variants']], [5, 10])
        for variant in result['variants']:
            tree = ast.parse(variant['expression'], mode='eval').body
            self.assertEqual(tree.func.id, 'ts_mean')
            self.assertEqual(ast.dump(tree.args[0]), ast.dump(ast.parse(self.parent['expression'], mode='eval').body))
            self.assertEqual(variant['settings'], self.parent['settings'])
            self.assertEqual(variant['expression_hash'], simulation_identity_hash(
                variant['expression'], variant['settings']))
            self.assertTrue(variant['binding']['operator_provenance'])
        self.assertEqual((self.parent, self.policy), original)
        self.assertTrue(any(s['reason'] == 'frequency_constraint' for s in result['skipped']))

    def test_source_less_transform_and_unknown_operator_are_rejected(self):
        self.transform_policy()
        for invalid in ('missing', 'untyped', 'source_less', 'wrong_type'):
            policy = copy.deepcopy(self.policy)
            operator = next(row for row in policy['resources']['operator_rows'] if row['operator'] == 'ts_mean')
            if invalid == 'missing':
                policy['resources']['operator_rows'].remove(operator)
            elif invalid == 'untyped':
                operator.pop('definition')
            elif invalid == 'source_less':
                operator['definition']['evidence_refs'] = []
            else:
                operator['definition']['parameters'][1]['type'] = 'STRING'
            result = self.prepare(Path('.'), self.parent, [], 8, policy)
            self.assertEqual(result['variants'], [], invalid)
            self.assertTrue(any(s['reason'] == 'unsupported_transform' for s in result['skipped']), invalid)

    def test_frequency_unknown_hypothesis_or_wrong_units_skip_with_reason(self):
        self.transform_policy()
        for patch in (dict(basis='hypothesis'), dict(value='unknown'), dict(units='calendar_days'),
                      dict(value=True), dict(evidence_refs=[])):
            with self.subTest(patch=patch):
                policy = copy.deepcopy(self.policy)
                policy['traits']['update_frequency'].update(patch)
                result = self.prepare(Path('.'), self.parent, [], 8, policy)
                self.assertEqual(result['variants'], [])
                self.assertTrue(any('frequency' in s['reason'] for s in result['skipped']))

    def test_transform_cannot_change_core_field_condition_or_direction(self):
        self.transform_policy()
        for skeleton in ('rank({flow}) + {liability}', '-rank({flow} / {liability})',
                         'rank({liability} / {flow})'):
            with self.subTest(skeleton=skeleton):
                self.policy['resources']['template']['skeleton'] = skeleton
                self.assertEqual(self.plan()['variants'], [])
        self.transform_policy()
        self.policy['rules'][0]['transform']['preserves_direction'] = False
        self.assertEqual(self.plan()['stop_reason'], 'invalid_policy')

    def test_transform_grid_type_and_bounds_not_silently_coerced(self):
        self.transform_policy()
        for grid in ([0], [33], [2.0], [True]):
            with self.subTest(grid=grid):
                self.policy['rules'][0]['grid'] = grid
                self.assertEqual(self.plan()['stop_reason'], 'invalid_policy')

    def test_transform_with_missing_binding_context_never_uses_legacy_bypass(self):
        self.transform_policy()
        self.policy['resources']['template']['binding_version'] = 1
        self.assertEqual(self.plan()['variants'], [])
        self.policy.pop('resources')
        self.assertEqual(self.plan()['variants'], [])

    def test_typed_weight_transform_needs_explicit_scalar_signature(self):
        self.transform_policy()
        rule = self.policy['rules'][0]
        rule.update(effect='bounded_weights', grid=[0.03, 0.05], transform=dict(
            operator='bounded_weight', parameter='limit', parameter_kind='scalar', bounds=[0.01, 0.1],
            frequency_trait=None, preserves_direction=True))
        # Fictional operator fixture: no fact about any real platform operator is inferred.
        self.policy['resources']['operator_rows'].append(dict(operator='bounded_weight', definition=dict(
            description='Fictional documented direction-preserving weight bound.', input_types=['MATRIX'],
            output_type='MATRIX', parameters=[dict(name='x', type='MATRIX', required=True),
                                             dict(name='limit', type='FLOAT', required=True)],
            evidence_refs=rule['evidence_refs'])))
        result = self.plan()
        self.assertEqual(len(result['variants']), 2)
        self.assertTrue(all(v['expression'].startswith('bounded_weight(') for v in result['variants']))

    def test_unknown_literal_never_establishes_applicability_even_if_rule_requests_it(self):
        self.policy['rules'][0]['requires']['noisy'] = 'unknown'
        self.policy['traits']['noisy']['value'] = 'unknown'
        self.assertEqual(len(self.plan()['variants']), 2)

    def test_transform_scope_must_match_parent_settings(self):
        self.transform_policy()
        for key, wrong in (('region', 'EUR'), ('delay', True), ('universe', 'TOP500')):
            with self.subTest(key=key):
                parent = copy.deepcopy(self.parent)
                parent['settings'][key] = wrong
                parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
                result = self.prepare(Path('.'), parent, [], 8, self.policy)
                self.assertEqual(result['variants'], [])
                self.assertTrue(any(s['reason'] == 'unsupported_transform' for s in result['skipped']))

    def test_decision_has_existing_trace_target_contract(self):
        from wqb.repair_trace import validate_experiment_target
        for variant in self.plan()['variants']:
            validate_experiment_target(variant['decision'], self.parent)

    def test_single_change_cumulative_settings_keep_economic_context(self):
        first = self.plan()['variants'][0]
        for key in ('core_fields', 'conditions', 'direction'):
            self.assertEqual(first.get(key), self.parent[key])
        incumbent = dict(self.parent, settings=first['settings'], expression_hash=first['expression_hash'])
        second = self.prepare(Path('.'), incumbent, [self.parent, first], 8, self.policy)
        variant = next(v for v in second['variants'] if v['decision']['edit'] == 'truncation')
        self.assertEqual(variant['settings']['decay'], first['settings']['decay'])
        self.assertEqual(variant['parent_expression_hash'], incumbent['expression_hash'])

    def test_no_platform_model_calls_or_disk_access(self):
        self.transform_policy()
        with patch('requests.sessions.Session.request', side_effect=AssertionError('network')), \
                patch('wqb.ai_checkpoints.run_ai_checkpoint', side_effect=AssertionError('model')), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('read')), \
                patch.object(Path, 'write_text', side_effect=AssertionError('write')):
            self.assertEqual(self.plan()['status'], 'validated')

    def test_legacy_parent_identity_can_be_read_without_changing_new_hash_scheme(self):
        import hashlib
        self.parent['expression_hash'] = hashlib.sha256(json.dumps(
            [self.parent['expression'], self.parent['settings']], sort_keys=True).encode()).hexdigest()
        result = self.plan()
        self.assertEqual(result['status'], 'validated')
        self.assertTrue(all(v['expression_hash'] == simulation_identity_hash(v['expression'], v['settings'])
                            for v in result['variants']))

    def test_numeric_representation_only_change_is_not_a_new_experiment(self):
        self.parent['settings']['decay'] = 2.0
        self.parent['expression_hash'] = simulation_identity_hash(self.parent['expression'], self.parent['settings'])
        self.policy['rules'] = [self.policy['rules'][0]]
        self.policy['rules'][0]['grid'] = [2]
        self.assertEqual(self.plan()['variants'], [])

    def test_policy_shape_duplicate_ids_and_setting_bounds(self):
        for patch in (dict(schema_version=True), dict(schema_version=2), dict(stop='false'),
                      dict(traits=[]), dict(rules=None), dict(rules=[]), dict(extra=True)):
            with self.subTest(patch=patch):
                parent, policy = search_fixture()
                policy.update(patch)
                result = self.prepare(Path('.'), parent, [], 8, policy)
                self.assertEqual(result['status'], 'exhausted' if patch == dict(rules=[]) else 'blocked')
        self.policy['rules'].append(copy.deepcopy(self.policy['rules'][0]))
        self.assertEqual(self.plan()['stop_reason'], 'invalid_policy')
        for value in (0, -0.01, 0.16, True, '0.04'):
            parent, policy = search_fixture()
            policy['rules'][1]['grid'] = [value]
            self.assertEqual(self.prepare(Path('.'), parent, [], 8, policy)['stop_reason'], 'invalid_policy')

    def test_history_order_independent_and_no_last_n_truncation(self):
        variants = self.plan()['variants']
        history = variants + [dict(expression_hash=str(index).zfill(64)) for index in range(20)]
        first = self.plan(history=history)
        second = self.plan(history=list(reversed(history)))
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'exhausted')

    def test_invalid_history_fails_closed_instead_of_ignoring_unknown_post(self):
        for history in (None, [None], [{}], [dict(status='UNKNOWN_POST')]):
            result = self.prepare(Path('.'), self.parent, history, 8, self.policy)
            self.assertEqual(result['stop_reason'], 'invalid_history')
            self.assertEqual(result['variants'], [])

    def test_operator_named_parameter_cannot_bypass_typed_domain_or_required_parameters(self):
        self.transform_policy()
        for parameter in ('x0', 'not_a_parameter'):
            self.policy['rules'][0]['transform']['parameter'] = parameter
            self.assertEqual(self.plan()['variants'], [])

    def test_condition_expression_subtree_and_scope_metadata_are_retained(self):
        self.transform_policy()
        self.parent['expression'] = 'rank(cash / debt) * rank(debt)'
        self.parent['expression_hash'] = simulation_identity_hash(self.parent['expression'], self.parent['settings'])
        self.policy['resources']['template']['skeleton'] = 'rank({flow} / {liability}) * rank({liability})'
        result = self.plan()
        self.assertEqual(len(result['variants']), 2)
        self.assertTrue(all(v['conditions'] == self.parent['conditions'] for v in result['variants']))
        self.assertTrue(all(v['binding']['bindings']['liability']['role'] == 'signal'
                            for v in result['variants']))

    def test_transform_rules_and_grid_replay_byte_stably(self):
        self.transform_policy()
        first = json.dumps(self.plan(), sort_keys=True, allow_nan=False)
        self.policy['rules'][0]['grid'].reverse()
        self.assertEqual(json.dumps(self.plan(), sort_keys=True, allow_nan=False), first)

    def test_finite_incremental_batches_exhaust_without_ai_or_padding(self):
        history = []
        for _ in range(4):
            result = self.plan(1, history)
            self.assertEqual(len(result['variants']), 1)
            history.extend(result['variants'])
        self.assertEqual(len({v['expression_hash'] for v in history}), 4)
        self.assertEqual(self.plan(1, history)['stop_reason'], 'search_space_exhausted')

    def test_negative_frozen_orientation_and_condition_metadata_are_not_reversed(self):
        self.transform_policy()
        self.parent.update(expression='-rank(cash / debt)', prediction_direction='negative',
                           direction='negative', orientation=-1, condition_filter_applied=False)
        self.parent['expression_hash'] = simulation_identity_hash(self.parent['expression'], self.parent['settings'])
        self.policy['resources']['template']['skeleton'] = '-rank({flow} / {liability})'
        result = self.plan()
        self.assertEqual(len(result['variants']), 2)
        for variant in result['variants']:
            self.assertEqual(variant.get('prediction_direction'), 'negative')
            self.assertEqual(variant.get('orientation'), -1)
            self.assertIs(variant.get('condition_filter_applied'), False)
            self.assertTrue(variant['expression'].startswith('ts_mean(-rank('))


if __name__ == '__main__':
    unittest.main()
