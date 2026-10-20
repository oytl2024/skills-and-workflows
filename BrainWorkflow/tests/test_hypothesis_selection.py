import copy
import importlib.util
import json
import tempfile
from pathlib import Path
import unittest

from tests.test_template_binding import binding_fixture
from wqb.template_binding import bind_template


def paired_selection_fixture(root):
    """Input: temporary root Path. Output: snapshot/experiments tuple. Use accepted Task4 frozen fixtures."""
    from tests.test_hypothesis_pipeline import HypothesisSnapshotTests
    from wqb.hypothesis_selection import validate_operational_resource_context
    fixture = HypothesisSnapshotTests()
    knowledge, scope = fixture.paired_knowledge(root)
    snapshot = fixture.paired_snapshot(knowledge, scope)
    return snapshot, validate_operational_resource_context(snapshot)['experiments']


class PairedSelectionTests(unittest.TestCase):
    def test_all_groups_compiled_before_cap_and_shared_baseline_charges_once(self):
        from tests.test_hypothesis_pipeline import HypothesisSnapshotTests
        from wqb.hypothesis_selection import validate_operational_resource_context, select_experiment_batch
        fixture = HypothesisSnapshotTests()
        for shared, count, maximum, expected, pairs in [(False, 20, 90, 30, 15), (True, 3, 3, 3, 2)]:
            with self.subTest(shared=shared), tempfile.TemporaryDirectory() as tmp:
                knowledge, scope = fixture.paired_knowledge(Path(tmp), count=count, shared_baseline=shared)
                snapshot = fixture.paired_snapshot(knowledge, scope)
                experiments = validate_operational_resource_context(snapshot)['experiments']
                result = select_experiment_batch(snapshot, experiments, maximum)
                self.assertEqual(result['generated_count'], count * 2)
                self.assertEqual(len(result['selected']), expected)
                self.assertEqual(len(result['experiments']), pairs)
                self.assertEqual(len(result['sidecars']), pairs * 2)
                if shared:
                    self.assertEqual(len({row['baseline_expression_hash'] for row in result['sidecars']}), 1)

    def test_complete_pair_before_odd_budget_and_candidate_schema_unchanged(self):
        from wqb import hypothesis_selection as selection
        self.assertTrue(callable(getattr(selection, 'select_experiment_batch', None)))
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, experiments = paired_selection_fixture(Path(tmp))
            before = copy.deepcopy(snapshot)
            self.assertEqual(selection.select_experiment_batch(snapshot, experiments, 1)['selected'], [])
            result = selection.select_experiment_batch(snapshot, experiments, 3)
            self.assertEqual(len(result['selected']), 2)
            self.assertEqual(len(result['experiments']), 1)
            self.assertEqual({row['arm_id'] for row in result['sidecars']}, {'baseline', 'treatment'})
            self.assertTrue(all(set(row) <= selection.CANDIDATE_KEYS for row in result['selected']))
            self.assertEqual(snapshot, before)

    def test_reuse_requires_exact_identity_settings_scope_and_known_period_not_correlation(self):
        from wqb import hypothesis_selection as selection
        self.assertTrue(callable(getattr(selection, 'select_experiment_batch', None)))
        from wqb.cli import simulation_identity_hash
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, experiments = paired_selection_fixture(Path(tmp))
            snapshot['measurement_period'] = dict(start='2020-01-01', end='2025-12-31')
            baseline = experiments[0]['arms'][0]
            expression = baseline['binding']['bound_expression']
            identity = simulation_identity_hash(expression, baseline['settings'])
            measurement = dict(expression_hash=identity, expression=expression, settings=baseline['settings'],
                scope=baseline['scope'], measurement_period=snapshot['measurement_period'], status='measured',
                metrics=dict(sharpe=1.0))
            result = selection.select_experiment_batch(snapshot, experiments, 1, {identity: measurement})
            self.assertEqual(len(result['selected']), 1)
            self.assertEqual(sum(row['reused'] for row in result['sidecars']), 1)
            for key, value in [('scope', {}), ('settings', {}), ('measurement_period', None),
                               ('status', 'correlation_cached'), ('expression_hash', 'wrong'), ('metrics', {})]:
                with self.subTest(key=key):
                    invalid = dict(measurement, **{key: value})
                    self.assertEqual(selection.select_experiment_batch(snapshot, experiments, 1,
                        {identity: invalid})['selected'], [])
            del snapshot['measurement_period']
            self.assertEqual(selection.select_experiment_batch(snapshot, experiments, 1,
                {identity: measurement})['selected'], [])

    def test_tampered_identical_and_duplicate_experiment_arms_never_half_select(self):
        from wqb import hypothesis_selection as selection
        self.assertTrue(callable(getattr(selection, 'select_experiment_batch', None)))
        with tempfile.TemporaryDirectory() as tmp:
            snapshot, experiments = paired_selection_fixture(Path(tmp))
            invalid = copy.deepcopy(experiments[0])
            invalid['arms'][1]['binding'] = copy.deepcopy(invalid['arms'][0]['binding'])
            result = selection.select_experiment_batch(snapshot, [invalid], 30)
            self.assertEqual(result['selected'], [])
            self.assertTrue(result['reasons'])
            result = selection.select_experiment_batch(snapshot, experiments * 20, 30)
            self.assertEqual(len(result['selected']), 2)
            self.assertEqual(len(result['experiments']), 1)


def selection_fixture():
    """Input: none. Output: dict snapshot. Build reviewed offline rows without inventing availability."""
    template, fields, operators, scope = binding_fixture()
    template.update(hypothesis_id='resilience', hypothesis_version=1, semantic_status='reviewed',
                    hypothesis_card=dict(data_meaning='Cash relative to debt.', mechanism='Financial resilience.',
                        conditions='During funding stress.', alternative='Sector exposure.',
                        prediction='Higher relative returns.', operator_roles='Rank relative resilience.',
                        falsification='No relative return difference.'),
                    operator_roles=[dict(operator='rank', role='normalization', purpose='Compare firms.')])
    return dict(selected_scope=scope, template_rows=[template], data_ledger_rows=fields, operator_rows=operators)


def candidate_for(snapshot, identifier, *, mechanism=None, skeleton=None, window=None, conditions=None):
    """Input: snapshot dict, ID str, optional text/int variants. Output: dict real binder candidate; register frozen template."""
    template = copy.deepcopy(snapshot['template_rows'][0])
    template.update(template_id=identifier, hypothesis_id=identifier)
    if mechanism:
        template['hypothesis_card']['mechanism'] = mechanism
    if conditions:
        template['hypothesis_card']['conditions'] = conditions
    if skeleton:
        template['skeleton'] = skeleton
    if 'ts_mean' in template['skeleton']:
        template['operator_roles'].append(dict(operator='ts_mean', role='signal', purpose='Smooth observations.'))
    snapshot['template_rows'].append(template)
    scope = copy.deepcopy(snapshot['selected_scope'])
    binding_scope = dict(scope, window=window) if window is not None else scope
    candidate = dict(candidate_id=identifier, template_id=identifier, hypothesis_id=identifier,
                     hypothesis_version=1, binding_version=2, scope=scope,
                     settings={**{key: scope[key] for key in ('region', 'delay', 'universe')}, 'decay': 0},
                     **bind_template(template, snapshot['data_ledger_rows'], snapshot['operator_rows'], binding_scope))
    if window is not None:
        candidate['window'] = window
    return candidate


class HypothesisSelectionTests(unittest.TestCase):
    def test_operational_validator_is_available_and_legacy_remains_default(self):
        from wqb import hypothesis_selection as selection
        self.assertTrue(callable(getattr(selection, 'validate_operational_resource_context', None)))
        snapshot = selection_fixture()
        self.assertEqual(selection.validate_operational_resource_context(snapshot), {})
        snapshot['resource_contract_version'] = 2
        with self.assertRaisesRegex(ValueError, 'resource contract'):
            selection.validate_operational_resource_context(snapshot)

    def test_operational_validator_rejects_tampered_frozen_context(self):
        import tempfile
        from pathlib import Path
        from tests.test_hypothesis_pipeline import HypothesisSnapshotTests
        from wqb import hypothesis_selection as selection
        helper = HypothesisSnapshotTests()
        with tempfile.TemporaryDirectory() as tmp:
            knowledge, scope = helper.paired_knowledge(Path(tmp))
            snapshot = helper.paired_snapshot(knowledge, scope)
            for target in ('source', 'attachment', 'release', 'review', 'version', 'flag', 'missing'):
                changed = copy.deepcopy(snapshot)
                context = changed['operational_resource_context']
                if target in ('source', 'attachment'):
                    path = next(path for path in context['source_files']
                                if path.startswith('raw/research/' if target == 'attachment' else 'raw/platform/'))
                    context['source_files'][path] += '\nmutation'
                elif target == 'release':
                    changed['semantic_release']['resource_contract_version'] = 1
                elif target == 'review':
                    changed['template_rows'][0]['semantic_status'] = 'unreviewed'
                elif target == 'version':
                    context['schema_version'] = True
                elif target == 'flag':
                    changed['research_policy']['paired_scout'] = 'true'
                else:
                    del changed['operational_resource_context']
                with self.subTest(target=target), self.assertRaises(ValueError):
                    selection.validate_operational_resource_context(changed)

    def test_v2_resource_snapshot_is_rejected_not_silently_legacy_rebound(self):
        from wqb.hypothesis_selection import validate_hypothesis_match, enumerate_hypothesis_bindings
        snapshot = selection_fixture()
        candidate = candidate_for(snapshot, 'a')
        for marker in ('envelope', 'release', 'basis', 'timing'):
            changed = copy.deepcopy(snapshot)
            if marker == 'envelope':
                changed['resource_contract_version'] = 2
            elif marker == 'release':
                changed['semantic_release'] = dict(resource_contract_version=2)
            elif marker == 'basis':
                changed['operator_rows'][0]['definition_basis'] = {}
            else:
                changed['data_ledger_rows'][0]['timing_contract'] = {}
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError, 'resource contract'):
                self.select(changed, [candidate])
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError, 'resource contract'):
                validate_hypothesis_match(changed, candidate)
        fields = copy.deepcopy(snapshot['data_ledger_rows'])
        fields[0]['timing_contract'] = {}
        with self.assertRaisesRegex(ValueError, 'resource contract'):
            enumerate_hypothesis_bindings(snapshot['template_rows'][0], fields,
                                         snapshot['operator_rows'], snapshot['selected_scope'])

    def select(self, snapshot, candidates, maximum=30):
        """Input: snapshot dict, candidate list[dict], maximum int. Output: dict from real selector."""
        self.assertIsNotNone(importlib.util.find_spec('wqb.hypothesis_selection'), 'Task6 selector is not implemented')
        from wqb.hypothesis_selection import select_hypothesis_batch
        return select_hypothesis_batch(snapshot, candidates, maximum)

    def test_consumes_real_binding_and_preserves_inputs(self):
        snapshot = selection_fixture()
        candidate = candidate_for(snapshot, 'a')
        before = copy.deepcopy((snapshot, candidate))
        result = self.select(snapshot, [candidate])
        self.assertEqual(set(result), {'selected', 'rejected', 'reasons'})
        self.assertEqual(result['selected'], [candidate])
        self.assertEqual(result['rejected'], [])
        self.assertEqual(result['reasons'][0]['code'], 'selected')
        self.assertEqual((snapshot, candidate), before)
        result['selected'][0]['bindings']['flow']['metadata']['units'] = 'changed'
        self.assertEqual((snapshot, candidate), before)

    def test_mechanism_first_windows_are_not_new_families(self):
        snapshot = selection_fixture()
        a = candidate_for(snapshot, 'a', skeleton='rank(ts_mean({flow} / {liability}, {window}))', window=5)
        b = candidate_for(snapshot, 'b', skeleton='rank(ts_mean({flow} / {liability}, {window}))', window=20)
        c = candidate_for(snapshot, 'c', mechanism='Attention reversal.',
                          skeleton='-rank(ts_mean({flow} / {liability}, {window}))', window=5)
        for candidates in ([a, b, c], [c, b, a]):
            result = self.select(snapshot, candidates, 2)
            self.assertEqual([row['candidate_id'] for row in result['selected']], ['a', 'c'])
        result = self.select(snapshot, [a, b], 2)
        self.assertEqual([row['diversity']['mechanism'] for row in result['reasons']], [True, False])

    def test_secondary_conditions_before_window_variants(self):
        snapshot = selection_fixture()
        a = candidate_for(snapshot, 'a', skeleton='rank(ts_mean({flow} / {liability}, {window}))', window=5)
        b = candidate_for(snapshot, 'b', skeleton='rank(ts_mean({flow} / {liability}, {window}))', window=20)
        c = candidate_for(snapshot, 'c', conditions='During calm markets.', skeleton='-rank({flow} / {liability})')
        # Start with the simplest representative, then prefer a new condition over another window.
        result = self.select(snapshot, [a, b, c], 2)
        self.assertEqual([row['candidate_id'] for row in result['selected']], ['c', 'a'])

    def test_canonical_family_merges_alternate_mechanism_wording(self):
        snapshot = selection_fixture()
        a = candidate_for(snapshot, 'a')
        b = candidate_for(snapshot, 'b', mechanism='Balance sheet strength.', skeleton='-rank({flow} / {liability})')
        for template in snapshot['template_rows']:
            template['template_family'] = 'financial_resilience'
        result = self.select(snapshot, [b, a], 2)
        selected_reasons = {row['candidate_id']: row for row in result['reasons']}
        self.assertTrue(selected_reasons['a']['diversity']['mechanism'])
        self.assertFalse(selected_reasons['b']['diversity']['mechanism'])

    def test_equivalent_expressions_and_settings_deduplicate_across_stories(self):
        snapshot = selection_fixture()
        a = candidate_for(snapshot, 'a')
        b = candidate_for(snapshot, 'b', mechanism='Different narrative.')
        b['bound_expression'] = 'rank( (cash / debt) )'
        result = self.select(snapshot, [b, a])
        self.assertEqual(result['selected'], [a])
        self.assertEqual(result['rejected'], [b])
        self.assertEqual(next(row['code'] for row in result['reasons'] if row['candidate_id'] == 'b'), 'duplicate_simulation')
        b['settings']['decay'] = 4
        self.assertEqual(len(self.select(snapshot, [b, a])['selected']), 2)

    def test_unknown_or_changed_contract_is_rejected(self):
        mutations = [dict(template_id='outside'), dict(hypothesis_id='outside'), dict(hypothesis_version=2),
                     dict(hypothesis_version=True), dict(binding_version=1), dict(operator_call_count=100),
                     dict(bound_expression='rank(outside)'), dict(bindings={}), dict(operator_provenance=[]),
                     dict(arbitrary_schema='new'), dict(scope=dict(region='EUR', delay=1, universe='TOP3000'))]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                snapshot = selection_fixture()
                candidate = candidate_for(snapshot, 'a')
                candidate.update(mutation)
                result = self.select(snapshot, [candidate])
                self.assertEqual(result['selected'], [])
                self.assertEqual(result['rejected'], [candidate])

    def test_settings_cannot_change_scope_or_hide_nonfinite_values(self):
        for key, value in [('region', 'EUR'), ('delay', True), ('universe', 'OTHER'), ('decay', float('nan'))]:
            with self.subTest(key=key):
                snapshot = selection_fixture()
                candidate = candidate_for(snapshot, 'a')
                candidate['settings'][key] = value
                self.assertEqual(self.select(snapshot, [candidate])['selected'], [])

    def test_missing_frozen_dependencies_reject_without_padding(self):
        for resource in ('data_ledger_rows', 'operator_rows'):
            snapshot = selection_fixture()
            candidate = candidate_for(snapshot, 'a')
            snapshot[resource] = []
            self.assertEqual(self.select(snapshot, [candidate])['selected'], [])
        self.assertEqual(self.select(selection_fixture(), [])['selected'], [])

    def test_reviewed_v2_only_and_template_scope_restrictions(self):
        for mutation in [dict(semantic_status='unreviewed'), dict(binding_version=1), dict(hypothesis_card={}),
                         dict(compatible_regions=['EUR']), dict(compatible_delays=[0]), dict(compatible_universes=['OTHER'])]:
            with self.subTest(mutation=mutation):
                snapshot = selection_fixture()
                candidate = candidate_for(snapshot, 'a')
                snapshot['template_rows'][-1].update(mutation)
                self.assertEqual(self.select(snapshot, [candidate])['selected'], [])

    def test_duplicate_candidate_ids_and_ambiguous_template_rows_fail_closed(self):
        snapshot = selection_fixture()
        candidate = candidate_for(snapshot, 'a')
        self.assertEqual(self.select(snapshot, [candidate, copy.deepcopy(candidate)])['selected'], [])
        snapshot['template_rows'].append(copy.deepcopy(snapshot['template_rows'][-1]))
        self.assertEqual(self.select(snapshot, [candidate])['selected'], [])

    def test_scout_complexity_is_not_relaxed(self):
        snapshot = selection_fixture()
        candidate = candidate_for(snapshot, 'a', skeleton='rank(rank(rank(rank({flow} / {liability}))))')
        result = self.select(snapshot, [candidate])
        self.assertEqual(result['selected'], [])
        self.assertEqual(result['reasons'][0]['code'], 'scout_complexity')

    def test_no_new_call_count_limit_and_simplest_representative_first(self):
        snapshot = selection_fixture()
        a = candidate_for(snapshot, 'a', skeleton='rank({flow}) + rank({liability}) + rank({flow} / {liability}) + rank({liability} / {flow})')
        b = candidate_for(snapshot, 'b')
        result = self.select(snapshot, [a, b])
        self.assertEqual([row['candidate_id'] for row in result['selected']], ['b', 'a'])
        self.assertEqual(a['operator_call_count'], 4)

    def test_caps_remaining_authority_and_does_not_pad(self):
        snapshot = selection_fixture()
        candidates = []
        for index in range(35):
            candidate = candidate_for(snapshot, f'candidate-{index:02}')
            candidate['settings']['decay'] = index
            candidates.append(candidate)
        for maximum, count in [(0, 0), (7, 7), (30, 30), (100, 30)]:
            with self.subTest(maximum=maximum):
                result = self.select(snapshot, candidates, maximum)
                self.assertEqual(len(result['selected']), count)
                self.assertEqual(len(result['rejected']), 35 - count)
                self.assertEqual(len(result['reasons']), 35)
        self.assertEqual(len(self.select(snapshot, candidates[:2], 30)['selected']), 2)

    def test_invalid_maximum_and_snapshot_are_explicit_blockers(self):
        for maximum in (-1, True, 1.5, '7'):
            with self.assertRaises(ValueError):
                self.select(selection_fixture(), [], maximum)
        with self.assertRaises(ValueError):
            self.select({}, [])

    def test_windows_must_be_explicit_and_bounded(self):
        snapshot = selection_fixture()
        candidate = candidate_for(snapshot, 'a')
        candidate['window'] = 5
        self.assertEqual(self.select(snapshot, [candidate])['selected'], [])
        candidate = candidate_for(snapshot, 'b', skeleton='rank(ts_mean({flow} / {liability}, {window}))', window=5)
        candidate['window'] = 999
        self.assertEqual(self.select(snapshot, [candidate])['selected'], [])


if __name__ == '__main__':
    unittest.main()
