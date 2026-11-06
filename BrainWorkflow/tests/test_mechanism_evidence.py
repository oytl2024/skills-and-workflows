import copy
import importlib.util
import unittest


def evidence_fixture():
    """Input: none. Output: record/experiment lists with exact paired identities."""
    arms = [dict(arm_id=name, template_id=name, scope=dict(region='USA', delay=1),
                 settings=dict(decay=0), binding=dict(bound_expression=name, bindings=dict(pulse=dict(field_id='f'))))
            for name in ('baseline', 'treatment')]
    experiment = dict(experiment_id='e', design_id='d', compiler_version='1', compilation_digest='abc',
                      arms=arms, controls=['Hold scope and settings fixed.'], prediction_direction='positive',
                      conditions=[], context_bindings=dict(pulse=dict(field_id='f')))
    rows = [dict(alpha_id=name, expression_hash=name, expression=name, settings=arm['settings'],
                 scope=arm['scope'], measurement_period=dict(start='2020-01-01', end='2025-01-01'),
                 metrics=dict(returns=value), failed=[], pending=[], status='CHECKED', hard_pass=True,
                 experiment_arms=[dict(experiment_id='e', arm_id=name, expression_hash=name)])
            for arm, name, value in zip(arms, ('baseline', 'treatment'), (0.1, 0.2))]
    return [dict(run_id='r', backtest=rows)], [experiment]


class MechanismEvidenceTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('wqb.mechanism_evidence'), 'Task6 pure helper missing')
        from wqb import mechanism_evidence
        return mechanism_evidence

    def test_reordering_and_duplicate_snapshots_do_not_inflate_simulations(self):
        api = self.api()
        records, experiments = evidence_fixture()
        before = copy.deepcopy(records)
        view = api.build_mechanism_evidence(records, experiments)
        duplicate = copy.deepcopy(records[0])
        duplicate['synced_at'] = 'later'
        duplicate['backtest'].reverse()
        self.assertEqual(view, api.build_mechanism_evidence([duplicate, *records], experiments * 2))
        self.assertEqual(view['groups'][0]['unique_simulations'], 2)
        self.assertEqual(records, before)

    def test_measured_pair_without_numeric_comparison_is_inconclusive(self):
        api = self.api()
        records, experiments = evidence_fixture()
        group = api.build_mechanism_evidence(records, experiments)['groups'][0]
        self.assertEqual(group['label'], 'inconclusive')
        self.assertAlmostEqual(group['observed_differences']['returns'], 0.1)
        self.assertIn('explicit_comparison_absent', group['limitations'])

    def test_explicit_recorded_comparison_not_gate_or_submission_controls_label(self):
        api = self.api()
        records, experiments = evidence_fixture()
        # Caller-supplied explicit comparison, never inferred from compiler prose.
        experiments[0]['prediction_comparison'] = dict(metric='returns', direction='greater', control_arm='baseline')
        row = records[0]['backtest'][1]
        row.update(hard_pass=False, failed=[dict(name='PROD_CORRELATION', result='FAIL')])
        self.assertEqual(api.build_mechanism_evidence(records, experiments)['groups'][0]['label'], 'supports_prediction_in_scope')
        row['metrics']['returns'] = -0.2
        self.assertEqual(api.build_mechanism_evidence(records, experiments)['groups'][0]['label'], 'contradicts_prediction_in_scope')
        records[0]['manual_submission_status'] = [dict(status='submitted')]
        records[0]['backtest'] = []
        self.assertEqual(api.build_mechanism_evidence(records, experiments)['groups'][0]['label'], 'inconclusive')

    def test_missing_period_control_pending_conflicts_and_operational_failure(self):
        api = self.api()
        for change in ('period', 'control', 'pending', 'metrics', 'checks', '429', 'timeout'):
            records, experiments = evidence_fixture()
            experiments[0]['prediction_comparison'] = dict(metric='returns', direction='greater', control_arm='baseline')
            row = records[0]['backtest'][1]
            if change == 'period':
                row.pop('measurement_period')
            elif change == 'control':
                records[0]['backtest'].pop(0)
            elif change == 'pending':
                row['pending'] = ['SHARPE']
            elif change in ('metrics', 'checks'):
                other = copy.deepcopy(records[0])
                if change == 'metrics':
                    other['backtest'][1]['metrics']['returns'] = 9
                else:
                    other['backtest'][1]['failed'] = ['SHARPE']
                records.append(other)
            else:
                row.update(status='failed', error=change)
            with self.subTest(change=change):
                group = api.build_mechanism_evidence(records, experiments)['groups'][0]
                self.assertEqual(group['label'], 'operational_failure' if change in ('429', 'timeout') else 'inconclusive')

    def test_incompatible_scope_settings_period_versions_roles_never_pool(self):
        api = self.api()
        for key in ('scope', 'settings', 'measurement_period'):
            records, experiments = evidence_fixture()
            records[0]['backtest'][1][key] = dict(other='different')
            group = api.build_mechanism_evidence(records, experiments)['groups'][0]
            self.assertEqual(group['label'], 'inconclusive')
        for key in ('compiler_version', 'context_bindings', 'compilation_digest'):
            records, experiments = evidence_fixture()
            other = copy.deepcopy(experiments[0])
            other[key] = 'different'
            view = api.build_mechanism_evidence(records, [*experiments, other])
            self.assertTrue(all(g['label'] == 'inconclusive' for g in view['groups']))

    def test_context_strict_limit_relevance_and_omissions_including_zero(self):
        api = self.api()
        records, experiments = evidence_fixture()
        view = api.build_mechanism_evidence(records, experiments)
        for maximum in (True, -1, 13, 1.0):
            with self.assertRaises(ValueError):
                api.select_mechanism_context(view, {}, maximum)
        result = api.select_mechanism_context(view, dict(experiment_id='e'), 0)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['omitted_count'], 1)
        self.assertEqual(len(api.select_mechanism_context(view, {}, 12)['items']), 1)
        self.assertEqual(api.select_mechanism_context(view, dict(experiment_id='unrelated'))['items'], [])

    def test_versions_scopes_and_settings_form_separate_observation_cohorts(self):
        api = self.api()
        for key, first, second in [('hypothesis_version', 1, 2), ('semantic_release', {'release_id': 'a'}, {'release_id': 'b'}),
                                   ('scope', {'region': 'USA'}, {'region': 'CHN'}),
                                   ('settings', {'decay': 0}, {'decay': 1})]:
            records, experiments = evidence_fixture()
            other = copy.deepcopy(records[0])
            for record, value in ((records[0], first), (other, second)):
                for row in record['backtest']:
                    row[key] = value
            view = api.build_mechanism_evidence([*records, other], experiments)
            with self.subTest(key=key):
                self.assertEqual(len(view['groups']), 2)
                self.assertTrue(all(g['unique_simulations'] == 2 for g in view['groups']))

    def test_source_fingerprints_bound_to_digest_and_reused_control_is_visible(self):
        api = self.api()
        records, experiments = evidence_fixture()
        records[0]['backtest'][0]['source_provenance'] = [dict(content_hash='a')]
        first = api.build_mechanism_evidence(records, experiments)
        records[0]['backtest'][0]['source_provenance'][0]['content_hash'] = 'b'
        self.assertNotEqual(first['input_digest'], api.build_mechanism_evidence(records, experiments)['input_digest'])
        baseline = records[0]['backtest'].pop(0)
        records[0]['backtest'][0]['mechanism_reused_measurements'] = [dict(experiment_id='e', arm_id='baseline',
            expression_hash='baseline', reused=True, measurement={k: v for k, v in baseline.items() if k != 'experiment_arms'})]
        group = api.build_mechanism_evidence(records, experiments)['groups'][0]
        self.assertEqual(group['unique_simulations'], 2)
        self.assertEqual(len(group['observations']), 2)
        self.assertTrue(any(r.get('measurement_origin') == 'reused_control' for r in group['observations']))

    def test_missing_checks_and_simulation_identity_remain_insufficient(self):
        api = self.api()
        records, experiments = evidence_fixture()
        experiments[0]['prediction_comparison'] = dict(metric='returns', direction='greater', control_arm='baseline')
        for row in records[0]['backtest']:
            row.pop('pending')
            row.pop('failed')
            row.pop('hard_pass')
        group = api.build_mechanism_evidence(records, experiments)['groups'][0]
        self.assertEqual(group['label'], 'inconclusive')

    def test_changed_data_role_binding_never_counts_as_support(self):
        api = self.api()
        records, experiments = evidence_fixture()
        experiments[0]['prediction_comparison'] = dict(metric='returns', direction='greater', control_arm='baseline')
        records[0]['backtest'][1]['bindings'] = dict(pulse=dict(field_id='different'))
        self.assertEqual(api.build_mechanism_evidence(records, experiments)['groups'][0]['label'], 'inconclusive')

    def test_transport_status_code_and_conflicting_check_results_are_not_economic_labels(self):
        api = self.api()
        records, experiments = evidence_fixture()
        experiments[0]['prediction_comparison'] = dict(metric='returns', direction='greater', control_arm='baseline')
        records[0]['backtest'][1].update(status='failed', status_code=429)
        self.assertEqual(api.build_mechanism_evidence(records, experiments)['groups'][0]['label'], 'operational_failure')
        records[0]['backtest'][1].update(status='CHECKED', status_code=200,
            checks=[dict(name='SHARPE', result='PASS'), dict(name='SHARPE', result='FAIL')])
        self.assertEqual(api.build_mechanism_evidence(records, experiments)['groups'][0]['label'], 'inconclusive')

    def test_conflicting_reused_control_does_not_disappear_behind_recorded_baseline(self):
        api = self.api()
        records, experiments = evidence_fixture()
        experiments[0]['prediction_comparison'] = dict(metric='returns', direction='greater', control_arm='baseline')
        baseline = copy.deepcopy(records[0]['backtest'][0])
        baseline['metrics']['returns'] = 10
        records[0]['backtest'][1]['mechanism_reused_measurements'] = [dict(experiment_id='e', arm_id='baseline',
            expression_hash='baseline', reused=True, measurement=baseline)]
        group = api.build_mechanism_evidence(records, experiments)['groups'][0]
        self.assertEqual(group['label'], 'inconclusive')
        self.assertEqual(group['unique_simulations'], 2)
        self.assertIn('conflicting_metrics', group['limitations'])

    def test_context_keeps_relevant_failures_and_exact_omissions_at_twelve(self):
        api = self.api()
        records, experiments = [], []
        for index in range(15):
            rs, es = evidence_fixture()
            es[0]['experiment_id'] = str(index)
            es[0]['prediction_comparison'] = dict(metric='returns', direction='greater', control_arm='baseline')
            for row in rs[0]['backtest']:
                row['experiment_arms'][0]['experiment_id'] = str(index)
                row['template_provenance'] = dict(template_family='mechanism')
            if index < 2:
                rs[0]['backtest'][1].update(status='failed', error='timeout')
            records.extend(rs)
            experiments.extend(es)
        view = api.build_mechanism_evidence(records, experiments)
        selected = api.select_mechanism_context(view, dict(mechanism_family='mechanism'))
        self.assertEqual(len(selected['items']), 12)
        self.assertEqual(selected['omitted_count'], 3)
        self.assertEqual(sum(g['label'] == 'operational_failure' for g in selected['items']), 2)
        self.assertEqual(selected, api.select_mechanism_context(api.build_mechanism_evidence(records[::-1], experiments[::-1]),
                                                             dict(mechanism_family='mechanism')))

    def test_malformed_or_summary_conflicting_raw_checks_never_support(self):
        api = self.api()
        for checks in (['PENDING'], {'SHARPE': 'PASS'}, [dict(name='SHARPE', result='PENDING')],
                       [dict(name='SHARPE', result='FAIL')], [dict(result='PASS')]):
            records, experiments = evidence_fixture()
            experiments[0]['prediction_comparison'] = dict(metric='returns', direction='greater', control_arm='baseline')
            records[0]['backtest'][1]['checks'] = checks
            with self.subTest(checks=checks):
                group = api.build_mechanism_evidence(records, experiments)['groups'][0]
                self.assertEqual(group['label'], 'inconclusive')
                self.assertTrue(group['limitations'])

    def test_empty_raw_checks_cannot_replace_absent_check_summary(self):
        api = self.api()
        records, experiments = evidence_fixture()
        experiments[0]['prediction_comparison'] = dict(metric='returns', direction='greater', control_arm='baseline')
        row = records[0]['backtest'][1]
        row['checks'] = []
        for key in ('failed', 'pending', 'hard_pass'):
            row.pop(key)
        group = api.build_mechanism_evidence(records, experiments)['groups'][0]
        self.assertEqual(group['label'], 'inconclusive')
        self.assertIn('measurement_or_checks_incomplete', group['limitations'])

    def test_reused_status_identity_and_one_sided_checks_affect_evidence(self):
        api = self.api()
        for change in (dict(status='timeout', error='timeout'), dict(alpha_id='different'),
                       dict(checks=[dict(name='SHARPE', result='PENDING')])):
            records, experiments = evidence_fixture()
            experiments[0]['prediction_comparison'] = dict(metric='returns', direction='greater', control_arm='baseline')
            before = api.build_mechanism_evidence(records, experiments)
            baseline = copy.deepcopy(records[0]['backtest'][0])
            baseline.update(change)
            records[0]['backtest'][1]['mechanism_reused_measurements'] = [dict(experiment_id='e', arm_id='baseline',
                expression_hash='baseline', reused=True, measurement=baseline)]
            with self.subTest(change=change):
                view = api.build_mechanism_evidence(records, experiments)
                self.assertNotEqual(view['input_digest'], before['input_digest'])
                group = view['groups'][0]
                self.assertEqual(group['label'], 'operational_failure' if 'error' in change else 'inconclusive')
                self.assertEqual(len(group['observations']), 3)
