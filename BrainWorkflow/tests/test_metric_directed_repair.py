"""Offline v2 Repair routing, source binding and frozen-v1 compatibility tests."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_compiled_repair_policy import fixture
from tests.test_repair_search import search_fixture
from wqb.cli import simulation_identity_hash
from wqb.repair_search import _materialize_parent, prepare_search


def metric_fixture():
    """Input: none. Output: parent/policy dicts with fictional, fully captured field facts."""
    resources, _ = fixture()
    parent, old = search_fixture()
    parent.update(expression='cash', failed=['LOW_FITNESS'], pending=[], status='CHECKED',
                  test_period='2014-2024', measurement_scope='IS', lane_id='lane-1', hard_pass=False)
    parent['settings']['instrumentType'] = 'EQUITY'
    parent['metrics']['returns'] = .03
    parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
    parent['simulation_identity'] = parent['expression_hash']
    path, source = next(iter(resources['source_index'].items()))
    ref = dict(source_path=path, sha256=source['content_hash'],
               capture_date=source['captured_at'][:10], kind='documented', experiment_refs=[])
    rules = []
    for old_rule, trigger, direction in (
            (old['rules'][0], dict(checks=['HIGH_TURNOVER'], metric='turnover', operator='gt', threshold=.4), 'increase'),
            (old['rules'][1], dict(checks=['LOW_FITNESS'], metric=None, operator=None, threshold=None), 'decrease')):
        rules.append(dict(old_rule, requires=dict(numeric_observation=True), evidence_refs=[ref],
                          trigger=trigger, basis='project_hypothesis',
                          rationale='A bounded project experiment, not a documented setting effect.',
                          parameter_direction=direction))
    frozen = {key: copy.deepcopy(resources[key]) for key in ('resource_contract_version', 'field_rows', 'operator_rows')}
    frozen.update(scope=resources['evidence_pack']['scope'], evidence_context={
        key: resources[key] for key in ('source_index', 'source_texts')})
    return parent, dict(schema_version=2, rulebook_id='metric-directed-defaults-v1', rules=rules,
        traits=dict(numeric_observation=dict(basis='source', value=True, evidence_refs=[ref])), resources=frozen)


class MetricDirectedRepairTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: None; isolate each pure planner test."""
        self.parent, self.policy = metric_fixture()

    def plan(self, history=None, allowance=8):
        """Input: optional history list/allowance int. Output: deterministic plan dict, no IO."""
        return prepare_search(Path('unused'), self.parent, [] if history is None else history, allowance, self.policy)

    def test_same_failed_fitness_selects_distinct_low_high_turnover_rules(self):
        self.parent['metrics']['turnover'] = .1
        low = self.plan()
        self.assertEqual(low['status'], 'validated', low)
        self.assertEqual(low['variants'][0]['decision']['rule_id'], 'bound')
        self.parent['metrics']['turnover'] = .7
        high = self.plan()
        self.assertEqual(high['variants'][0]['decision']['rule_id'], 'smooth')
        evidence = high['variants'][0]['decision']['trigger_evidence']
        self.assertTrue(evidence['metric_predicate'])
        self.assertAlmostEqual(evidence['normalized_gap'], .75)
        self.assertEqual(evidence['observed_value'], .7)
        self.assertEqual(high['variants'][0]['decision']['basis'], 'project_hypothesis')

    def test_named_actual_failures_activate_independently_of_predicate(self):
        self.parent.update(failed=[dict(name='HIGH_TURNOVER', result='FAIL')])
        self.parent['metrics']['turnover'] = .1
        result = self.plan()
        self.assertEqual(result['status'], 'validated', result)
        self.assertEqual({v['decision']['rule_id'] for v in result['variants']}, {'smooth'})
        self.assertEqual(result['variants'][0]['decision']['trigger_evidence']['failed_checks'], ['HIGH_TURNOVER'])

    def test_pending_never_activates_named_failure(self):
        self.parent.update(failed=[], pending=['LOW_FITNESS', 'HIGH_TURNOVER'])
        self.parent['metrics']['turnover'] = .1
        result = self.plan()
        self.assertEqual(result['stop_reason'], 'no_triggered_rules', result)
        self.assertTrue(all(row['reason'] == 'trigger_not_observed' for row in result['skipped']))

    def test_malformed_failure_or_pending_data_fails_closed(self):
        for patch in (dict(failed=None), dict(failed=[{}]), dict(failed=['UNKNOWN']),
                      dict(failed=[dict(name='LOW_FITNESS', result='PASS')]),
                      dict(failed=[dict(name='LOW_FITNESS', result='PENDING')]),
                      dict(pending=None), dict(pending=[False]),
                      dict(pending=[dict(name='LOW_FITNESS', result='FAIL')]),
                      dict(pending=['LOW_FITNESS'])):
            with self.subTest(patch=patch):
                self.parent, self.policy = metric_fixture()
                self.parent.update(patch)
                result = self.plan()
                self.assertEqual(result['status'], 'blocked', result)
                self.assertEqual(result['stop_reason'], 'invalid_check_evidence')

    def test_metric_predicate_can_activate_with_pending_checks_without_claiming_failure(self):
        self.parent.update(failed=[], pending=['HIGH_TURNOVER'])
        self.parent['metrics']['turnover'] = .7
        result = self.plan()
        self.assertEqual(result['status'], 'validated', result)
        self.assertEqual(result['variants'][0]['decision']['trigger_evidence']['failed_checks'], [])

    def test_severity_precedes_priority_then_rule_id(self):
        self.policy['rules'][1]['trigger'] = dict(checks=[], metric='fitness', operator='lt', threshold=1.)
        self.policy['rules'][1]['priority'] = 0
        self.policy['rules'][0]['priority'] = 100
        self.parent['metrics'].update(turnover=.7, fitness=.8)
        self.assertEqual(self.plan()['variants'][0]['decision']['rule_id'], 'smooth')
        self.parent['metrics']['fitness'] = .1
        self.assertEqual(self.plan()['variants'][0]['decision']['rule_id'], 'bound')
        self.parent['metrics'].update(turnover=.8, fitness=0.)
        self.assertEqual(self.plan()['variants'][0]['decision']['rule_id'], 'bound')

    def test_parameter_direction_is_relative_to_actual_parent_setting(self):
        self.policy['rules'] = [self.policy['rules'][1]]
        self.policy['rules'][0]['grid'] = [.02, .04, .08, .12]
        for direction, expected in (('decrease', [.02, .04]), ('increase', [.12]), ('any', [.02, .04, .12])):
            with self.subTest(direction=direction):
                self.policy['rules'][0]['parameter_direction'] = direction
                self.assertEqual([v['decision']['value'] for v in self.plan()['variants']], expected)
        del self.parent['settings']['truncation']
        self.parent['expression_hash'] = simulation_identity_hash(self.parent['expression'], self.parent['settings'])
        self.assertEqual(self.plan()['stop_reason'], 'missing_prerequisites')

    def test_v2_schema_is_exact_and_bounded(self):
        for changes in (dict(basis='source'), dict(rationale=''), dict(rationale='x' * 1601),
                        dict(parameter_direction='up'), dict(extra=True),
                        dict(trigger=dict(checks=['SELF_CORRELATION'], metric=None, operator=None, threshold=None)),
                        dict(trigger=dict(checks=[], metric='returns', operator='gt', threshold=0)),
                        dict(trigger=dict(checks=[], metric='fitness', operator=None, threshold=1)),
                        dict(trigger=dict(checks=[], metric='fitness', operator='lt', threshold=float('inf'))),
                        dict(trigger=dict(checks=[], metric=None, operator=None, threshold=None))):
            with self.subTest(changes=changes):
                self.parent, self.policy = metric_fixture()
                self.policy['rules'][0].update(changes)
                self.assertEqual(self.plan()['stop_reason'], 'invalid_policy')
        for rulebook in ('', 'x' * 1601, False):
            self.parent, self.policy = metric_fixture()
            self.policy['rulebook_id'] = rulebook
            self.assertEqual(self.plan()['stop_reason'], 'invalid_policy')

    def test_v2_rulebook_id_is_optional(self):
        del self.policy['rulebook_id']
        self.assertEqual(self.plan()['status'], 'validated')

    def test_stop_categories_keep_skips_and_authority_boundaries(self):
        self.policy['rules'] = []
        self.assertEqual(self.plan()['stop_reason'], 'no_rules_configured')
        self.assertEqual(self.plan(allowance=0)['stop_reason'], 'allowance_exhausted')
        self.assertEqual(self.plan(allowance=0)['planner_version'], 2)
        self.policy['stop'] = True
        self.assertEqual(self.plan()['stop_reason'], 'stopped')
        self.parent, self.policy = metric_fixture()
        self.policy['traits'] = {}
        result = self.plan()
        self.assertEqual(result['stop_reason'], 'missing_prerequisites', result)
        self.assertTrue(any('trait' in row['reason'] for row in result['skipped']))
        self.parent, self.policy = metric_fixture()
        self.policy['rules'] = [self.policy['rules'][1]]
        self.policy['rules'][0]['grid'] = [.08]
        self.assertEqual(self.plan()['stop_reason'], 'no_novel_candidates')
        self.policy['rules'][0]['grid'] = [.04]
        variants = self.plan()['variants']
        self.assertEqual(self.plan(history=variants)['stop_reason'], 'search_space_exhausted')
        self.assertEqual(self.plan(history=[dict(variants[0], status='UNKNOWN_POST')])['stop_reason'], 'search_space_exhausted')

    def test_tested_without_improvement_requires_complete_comparison(self):
        self.policy['rules'] = [self.policy['rules'][1]]
        self.policy['rules'][0]['grid'] = [.04]
        variant = self.plan()['variants'][0]
        child = dict(self.parent, **variant)
        child.update(alpha_id='child', status='CHECKED', metrics=dict(self.parent['metrics']))
        self.assertEqual(self.plan(history=[child])['stop_reason'], 'tested_without_improvement')
        child['pending'] = ['LOW_SHARPE']
        self.assertEqual(self.plan(history=[child])['stop_reason'], 'search_space_exhausted')

    def test_v2_parent_integrity_and_source_facts_are_revalidated(self):
        for expression in ('other_field', 'cash + other_field', 'unknown_operator(cash)', '1'):
            with self.subTest(expression=expression):
                self.parent, self.policy = metric_fixture()
                self.parent['expression'] = expression
                self.parent['expression_hash'] = simulation_identity_hash(expression, self.parent['settings'])
                result = self.plan()
                self.assertEqual(result['variants'], [])
                self.assertEqual(result['stop_reason'], 'missing_prerequisites', result)
        self.parent, self.policy = metric_fixture()
        self.policy['resources']['field_rows'][0]['field_type'] = 'VECTOR'
        self.assertEqual(self.plan()['stop_reason'], 'missing_prerequisites')

    def test_parent_materialization_keeps_v2_rulebook_and_never_adds_producer(self):
        bound = _materialize_parent(self.policy, self.parent)
        self.assertIn('template', bound['resources'])
        self.assertNotIn('producer', bound['resources'])
        self.assertEqual(bound['schema_version'], 2)
        self.assertEqual(bound['rules'], self.policy['rules'])
        self.assertEqual(bound['rulebook_id'], self.policy['rulebook_id'])

    def test_unrelated_or_invented_source_trait_does_not_authorize_rule(self):
        self.policy['traits']['nuisance_exposure'] = copy.deepcopy(self.policy['traits']['numeric_observation'])
        self.policy['rules'] = [dict(self.policy['rules'][1], edit='neutralization', effect='nuisance_exposure',
                                    requires=dict(nuisance_exposure=True), grid=['SECTOR'], parameter_direction='any')]
        result = self.plan()
        self.assertEqual(result['stop_reason'], 'missing_prerequisites', result)

    def test_replay_and_no_io_or_model_calls(self):
        original = copy.deepcopy((self.parent, self.policy))
        with patch('requests.sessions.Session.request', side_effect=AssertionError('network')), \
                patch('wqb.ai_checkpoints.run_ai_checkpoint', side_effect=AssertionError('model')), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('disk read')), \
                patch.object(Path, 'write_text', side_effect=AssertionError('disk write')):
            first = self.plan()
            self.assertEqual(first['status'], 'validated', first)
            self.policy['rules'].reverse()
            for rule in self.policy['rules']:
                rule['grid'].reverse()
            self.assertEqual(first, self.plan())
        self.policy = original[1]
        self.assertEqual((self.parent, self.policy), original)

    def test_v1_exact_prechange_receipt_bytes(self):
        parent, policy = search_fixture()
        result = prepare_search(Path('unused'), parent, [], 8, policy)
        self.assertEqual(hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(),
                         'd4232c66de05e50bca6119a0fb4be928ee08d164d944c1e3b14d8c6da96ebae8')

    def test_raw_source_and_trait_reference_tampering_fails_closed(self):
        for change in ('raw', 'trait', 'rule'):
            with self.subTest(change=change):
                self.parent, self.policy = metric_fixture()
                if change == 'raw':
                    path = next(iter(self.policy['resources']['evidence_context']['source_texts']))
                    self.policy['resources']['evidence_context']['source_texts'][path] += ' '
                elif change == 'trait':
                    self.policy['traits']['numeric_observation']['evidence_refs'][0]['sha256'] = 'f' * 64
                else:
                    self.policy['rules'][1]['evidence_refs'][0]['sha256'] = 'f' * 64
                self.assertEqual(self.plan()['stop_reason'], 'missing_prerequisites')

    def test_known_cadence_constrains_decay_unknown_does_not(self):
        self.policy['rules'] = [self.policy['rules'][0]]
        self.parent['metrics']['turnover'] = .7
        self.assertEqual([v['decision']['value'] for v in self.plan()['variants']], [4, 8])
        resources = self.policy['resources']
        path = next(iter(resources['evidence_context']['source_texts']))
        raw = json.loads(resources['evidence_context']['source_texts'][path])
        raw['field']['sampling_frequency_sessions'] = 5
        text = json.dumps(raw)
        digest = hashlib.sha256(text.encode()).hexdigest()
        resources['evidence_context']['source_texts'][path] = text
        resources['evidence_context']['source_index'][path]['content_hash'] = digest
        for rule in self.policy['rules']:
            rule['evidence_refs'][0]['sha256'] = digest
        trait = self.policy['traits']['numeric_observation']
        trait['evidence_refs'][0]['sha256'] = digest
        self.policy['traits']['sampling_frequency_sessions'] = dict(trait, value=5, units='sessions')
        self.assertEqual([v['decision']['value'] for v in self.plan()['variants']], [8])
        self.policy['traits'].pop('sampling_frequency_sessions')
        self.assertEqual([v['decision']['value'] for v in self.plan()['variants']], [8],
                         'known parent cadence is mandatory even if omitted from batch traits')
        attempted = self.plan()['variants']
        self.assertEqual(self.plan(history=attempted)['stop_reason'], 'search_space_exhausted')
        self.policy['rules'][0]['grid'] = [4]
        self.assertEqual(self.plan()['stop_reason'], 'no_novel_candidates')

    def test_unchecked_parent_is_not_failure_authority(self):
        self.parent['status'] = 'RUNNING'
        self.assertEqual(self.plan()['stop_reason'], 'invalid_check_evidence')

    def test_source_type_boolean_does_not_authorize_arbitrary_transform(self):
        from tests.test_compiled_repair_policy import CompiledRepairTests
        resources, _, parent = CompiledRepairTests().transform_fixture(1)
        self.parent['expression'] = 'cash'
        self.policy['resources']['operator_rows'] = resources['operator_rows']
        self.policy['resources']['evidence_context'].update({key: resources[key]
            for key in ('source_index', 'source_texts')})
        # Use the existing, genuinely certified field bytes (without a cadence claim).
        path, source = next(iter(resources['source_index'].items()))
        ref = dict(source_path=path, sha256=source['content_hash'], capture_date=source['captured_at'][:10], kind='documented')
        self.policy['traits']['numeric_observation']['evidence_refs'] = [ref]
        rule = self.policy['rules'][1]
        rule.update(edit='transform', effect='bounded_weights', parameter_direction='any', grid=[2],
            transform=dict(operator='ts_mean', parameter='d', parameter_kind='window', bounds=[1, 8],
                           frequency_trait='sampling_frequency_sessions', preserves_direction=True))
        self.policy['traits']['sampling_frequency_sessions'] = dict(
            basis='source', value=1, units='sessions', evidence_refs=[ref])
        rule['evidence_refs'] = resources['operator_rows'][0]['definition']['evidence_refs']
        self.policy['rules'] = [rule]
        self.assertEqual(self.plan()['variants'], [])

    def test_parent_operator_signature_output_and_raw_definition_are_checked(self):
        from tests.test_compiled_repair_policy import CompiledRepairTests
        resources, _, _ = CompiledRepairTests().transform_fixture(1)
        for mode in ('valid', 'wrong_output', 'changed_signature', 'unverified_source'):
            with self.subTest(mode=mode):
                self.parent, self.policy = metric_fixture()
                frozen = self.policy['resources']
                frozen['operator_rows'] = copy.deepcopy(resources['operator_rows'])
                operator_path = frozen['operator_rows'][0]['definition']['evidence_refs'][0]['source_path']
                for key in ('source_index', 'source_texts'):
                    frozen['evidence_context'][key][operator_path] = copy.deepcopy(resources[key][operator_path])
                self.parent['expression'] = 'ts_mean(cash, 4)'
                self.parent['expression_hash'] = simulation_identity_hash(self.parent['expression'], self.parent['settings'])
                definition = frozen['operator_rows'][0]['definition']
                if mode == 'wrong_output':
                    definition['output_type'] = 'VECTOR'
                elif mode == 'changed_signature':
                    definition['parameters'][0]['type'] = 'VECTOR'
                elif mode == 'unverified_source':
                    frozen['evidence_context']['source_texts'][operator_path] += ' '
                result = self.plan()
                self.assertEqual(result['status'], 'validated' if mode == 'valid' else 'exhausted', result)
                if mode != 'valid':
                    self.assertEqual(result['stop_reason'], 'missing_prerequisites')

    def test_v2_frozen_policy_and_persisted_receipt_rebuild(self):
        from wqb.repair_search import _frozen_policy, prepare_persisted_search, verify_persisted_search
        frozen = self.policy['resources']
        snapshot = dict(research_policy=dict(deterministic_repair=True), repair_search_policy=self.policy,
                        data_ledger_rows=frozen['field_rows'], operator_rows=frozen['operator_rows'])
        with tempfile.TemporaryDirectory(dir='output') as directory:
            run = Path(directory).resolve()
            manifest = run / 'run_manifest.json'
            manifest.write_text(json.dumps(dict(start_snapshot=snapshot)), encoding='utf-8')
            with patch('wqb.hypothesis_selection.validate_operational_resource_context',
                       return_value=frozen['evidence_context']):
                policy, _ = _frozen_policy(run)
                self.assertEqual(policy['rulebook_id'], 'metric-directed-defaults-v1')
                first = prepare_persisted_search(run, self.parent, [], 1)
                self.assertEqual(first['status'], 'validated', first)
                self.assertEqual(first, verify_persisted_search(run, first))
                self.assertEqual(first, prepare_persisted_search(run, self.parent, [], 1))
                changed = copy.deepcopy(first)
                changed['decision']['trigger_evidence']['failed_checks'] = ['HIGH_TURNOVER']
                with self.assertRaises(ValueError):
                    verify_persisted_search(run, changed)
                snapshot['repair_search_policy']['rulebook_id'] = 'changed-rulebook'
                manifest.write_text(json.dumps(dict(start_snapshot=snapshot)), encoding='utf-8')
                with self.assertRaises(ValueError):
                    verify_persisted_search(run, first)

    def test_zero_threshold_nonfinite_or_boolean_measurements_never_invent_gap(self):
        self.policy['rules'] = [self.policy['rules'][0]]
        self.policy['rules'][0]['trigger'].update(threshold=0, checks=[])
        self.parent['metrics']['turnover'] = .7
        result = self.plan()
        self.assertEqual(result['status'], 'validated', result)
        self.assertEqual(result['variants'][0]['decision']['trigger_evidence']['normalized_gap'], .7)
        for value in (float('nan'), float('inf'), True, '0.7', None):
            self.parent['metrics']['turnover'] = value
            self.assertEqual(self.plan()['stop_reason'], 'no_triggered_rules')

    def test_missing_target_retains_triggered_skip_instead_of_inventing_metric(self):
        self.parent['metrics']['fitness'] = None
        result = self.plan()
        self.assertEqual(result['stop_reason'], 'missing_prerequisites', result)
        self.assertTrue(any(row['reason'] == 'target_unmeasured' for row in result['skipped']))
        self.assertTrue(result['trigger_evidence']['bound']['activated'])

    def test_rejected_subspace_does_not_disprove_rules_with_missing_prerequisites(self):
        self.policy['rules'] = [self.policy['rules'][1]]
        self.policy['rules'][0]['grid'] = [.04]
        variant = self.plan()['variants'][0]
        child = dict(self.parent, **variant)
        child.update(alpha_id='child', status='CHECKED', metrics=dict(self.parent['metrics']))
        other = copy.deepcopy(self.policy['rules'][0])
        other.update(rule_id='unmeasured-quality', target_metric='sharpe', requires=dict(noisy=True))
        self.policy['rules'].append(other)
        result = self.plan(history=[child])
        self.assertEqual(result['stop_reason'], 'missing_prerequisites', result)

    def test_rule_id_breaks_equal_evidence_priority_ties(self):
        first = self.policy['rules'][1]
        second = copy.deepcopy(first)
        second.update(rule_id='a-quality', edit='decay', effect='smoothing', parameter_direction='increase', grid=[4])
        self.policy['rules'] = [first, second]
        self.assertEqual(self.plan()['variants'][0]['decision']['rule_id'], 'a-quality')

    def test_missing_resources_are_reported_without_losing_trigger_evidence(self):
        del self.policy['resources']
        result = self.plan()
        self.assertEqual(result['stop_reason'], 'missing_prerequisites')
        self.assertTrue(result['trigger_evidence']['bound']['activated'])

    def test_unrepresentable_target_metric_fails_closed(self):
        self.parent['metrics']['fitness'] = 10 ** 400
        self.assertEqual(self.plan()['stop_reason'], 'missing_prerequisites')

    def test_numeric_vector_trait_still_requires_grain_and_explicit_typed_reduction(self):
        resources = self.policy['resources']
        context = resources['evidence_context']
        path = next(iter(context['source_texts']))
        raw = json.loads(context['source_texts'][path])
        raw['field'].update(type='VECTOR', vector_grain='events')
        text = json.dumps(raw)
        digest = hashlib.sha256(text.encode()).hexdigest()
        context['source_texts'][path] = text
        context['source_index'][path]['content_hash'] = digest
        resources['field_rows'][0].update(field_type='VECTOR', vector_grain='events')
        for rule in self.policy['rules']:
            rule['evidence_refs'][0]['sha256'] = digest
        self.policy['traits']['numeric_observation']['evidence_refs'][0]['sha256'] = digest
        self.assertEqual(self.plan()['stop_reason'], 'missing_prerequisites')
        definition = dict(description='Returns the average of vector elements.', input_types=['VECTOR'],
                          output_type='MATRIX', parameters=[dict(name='x', type='VECTOR', required=True)])
        op_path = 'raw/platform/learn/vector.json'
        text = json.dumps(dict(operator='vec_avg', definition=definition))
        digest = hashlib.sha256(text.encode()).hexdigest()
        context['source_texts'][op_path] = text
        context['source_index'][op_path] = dict(path=op_path, content_hash=digest,
            captured_at='2026-10-15T00:00:00Z', source_type='platform_learn_material', source_family='raw/platform/learn')
        ref = dict(source_path=op_path, sha256=digest, capture_date='2026-10-15', kind='documented', experiment_refs=[])
        resources['operator_rows'] = [dict(operator='vec_avg', definition=dict(definition, evidence_refs=[ref]))]
        self.parent['expression'] = 'vec_avg(cash)'
        self.parent['expression_hash'] = simulation_identity_hash(self.parent['expression'], self.parent['settings'])
        self.assertEqual(self.plan()['status'], 'validated')
        del resources['field_rows'][0]['vector_grain']
        self.assertEqual(self.plan()['stop_reason'], 'missing_prerequisites')


if __name__ == '__main__':
    unittest.main()
