"""Offline pre-model planning; no model service, platform transport or global writes."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_hypothesis_design import compiler_fixture
from wqb import initial_research_planning as planning
from wqb.cli import simulation_identity_hash
from wqb.exploration_eligibility import validate_exploration, validate_operational_exploration


class FakeRunner:
    def __init__(self, *, side_effect=None, return_value=None):
        """Input: callable/exception or JSON result. Output: counted offline callback object."""
        self.side_effect, self.return_value, self.call_count = side_effect, return_value, 0

    def __call__(self, brief):
        """Input: brief dict. Output: copied fixture result or explicitly simulated failure."""
        self.call_count += 1
        if isinstance(self.side_effect, BaseException):
            raise self.side_effect
        return self.side_effect(brief) if self.side_effect else deepcopy(self.return_value)

    def assert_not_called(self):
        """Input: None. Output: None; fail if a forbidden fake invocation occurred."""
        if self.call_count:
            raise AssertionError('forbidden fake model invocation')


class InitialResearchPlanningTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: None; build a private raw-indexed opt-in run fixture."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run = self.root / 'lane'
        self.run.mkdir()
        self.knowledge = self.root / 'knowledge'
        self.design, self.resources, self.scope = compiler_fixture(treatment=True)
        for name, text in self.resources['source_texts'].items():
            path = self.knowledge / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        index = self.knowledge / 'machine/source_index.jsonl'
        index.parent.mkdir(parents=True)
        index.write_text(''.join(json.dumps(row) + '\n'
            for row in self.resources['source_index'].values()), encoding='utf-8')
        self.period = dict(start='2020-01-01', end='2025-01-01')
        self.manifest = dict(run_id='lane', knowledge_root=str(self.knowledge),
            selected_scope=self.scope, start_snapshot=dict(selected_scope=self.scope,
                measurement_period=self.period, research_policy=dict(paired_scout=True,
                    exploration_scout=True, exploration_policy_version=1)))
        self.save_manifest()
        self.policy = dict(schema_version=1, plan_depth=2, initial_hypotheses=4)
        raw = {key: deepcopy(value) for key, value in self.design.items() if key != 'design_id'}
        reverse = deepcopy(raw)
        reverse['prediction_direction'] = 'negative'
        reverse['prediction'] = 'The fictional response may be negative.'
        self.answer = dict(summary='A fictional offline plan.', designs=[raw, reverse],
            tree=dict(roots=['root'], nodes=[dict(node_id='root', parent_id=None,
                parent_arm_id=None, design_index=0, targets=dict(baseline=[], treatment=[]),
                fallback=[], reverse={arm: dict(design_index=1, arm_id=arm,
                    interpretation='The opposite response may be informative.', targets=[])
                    for arm in ('baseline', 'treatment')})]))

    def save_manifest(self):
        """Input: fixture manifest dict on self. Output: None; save only temporary run state."""
        (self.run / 'run_manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def prepare(self, runner, receipts=None):
        """Input: fake callback and optional receipts list. Output: coordinator result dict."""
        return planning.prepare_initial_research(self.run, self.knowledge, self.resources,
            model_runner=runner, template_receipts=[] if receipts is None else receipts,
            tree_policy=self.policy)

    def test_certifies_before_one_call_and_completed_restart_reuses(self):
        def runner(brief):
            """Input: brief dict. Output: fictional plan; assert durable evidence already exists."""
            self.assertTrue(list((self.run / 'runtime/exploration/resources').glob('*.json')))
            task = json.loads((self.run / planning.TASK_PATH).read_text(encoding='utf-8'))
            self.assertEqual(task['status'], 'running')
            self.assertRegex(task['input_sha256'], '^[a-f0-9]{64}$')
            self.assertEqual(brief['plan_depth'], 2)
            self.assertEqual(brief['max_width'], 4)
            self.assertEqual(brief['data_traits'], self.resources['field_rows'])
            self.assertIn('output_schema', brief)
            return deepcopy(self.answer)
        fake = FakeRunner(side_effect=runner)
        result = self.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result, self.prepare(fake))
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(result['tree']['status'], 'frozen')
        self.assertLessEqual(result['tree']['simulation_count'], 4)
        for node in result['tree']['tree']['nodes']:
            for expected in list(node['expected'].values()) + [r['expected'] for r in node['reverse'].values()]:
                self.assertEqual(expected['simulation_identity'],
                    simulation_identity_hash(expected['expression'], expected['settings']))
        snapshot = json.loads((self.run / 'run_manifest.json').read_text(encoding='utf-8'))['start_snapshot']
        validate_operational_exploration(self.run, self.knowledge, snapshot)
        self.assertEqual(snapshot['research_policy'], self.manifest['start_snapshot']['research_policy'])
        self.assertTrue(all(row['semantic_status'] == 'unreviewed' for row in snapshot['template_rows']))

    def test_corrupt_raw_never_calls_model(self):
        path = self.knowledge / next(iter(self.resources['source_texts']))
        path.write_text('changed', encoding='utf-8')
        fake = FakeRunner(return_value=self.answer)
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        fake.assert_not_called()

    def test_changed_raw_or_context_after_completion_blocks_without_replay(self):
        fake = FakeRunner(return_value=self.answer)
        self.assertEqual(self.prepare(fake)['status'], 'completed')
        self.policy['initial_hypotheses'] = 3
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.policy['initial_hypotheses'] = 4
        path = self.knowledge / next(iter(self.resources['source_texts']))
        path.write_text('changed', encoding='utf-8')
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.assertEqual(fake.call_count, 1)

    def test_template_match_precedes_generation_without_review_promotion(self):
        receipt = validate_exploration(self.design, self.resources, self.scope)
        def runner(brief):
            """Input: brief dict. Output: plan; templates must be inspected before callback."""
            self.assertEqual(brief['compatible_template_receipts'], [receipt])
            return deepcopy(self.answer)
        result = self.prepare(runner, [receipt])
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['receipt_origins'], ['template', 'generated'])
        self.assertEqual(result['receipts'][0], receipt)

    def test_callback_uncertainty_never_replays(self):
        fake = FakeRunner(side_effect=TimeoutError('unknown model outcome'))
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.assertEqual(fake.call_count, 1)

    def test_strict_schema_failure_is_durable(self):
        self.answer['designs'][0]['expression'] = 'arbitrary()'
        fake = FakeRunner(return_value=self.answer)
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.assertEqual(fake.call_count, 1)

    def test_raw_changed_during_callback_blocks_attachment(self):
        def runner(brief):
            """Input: brief dict. Output: plan after simulated raw drift; no attachment is legal."""
            (self.knowledge / next(iter(self.resources['source_texts']))).write_text('changed', encoding='utf-8')
            return deepcopy(self.answer)
        fake = FakeRunner(side_effect=runner)
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.assertFalse((self.run / 'runtime/experiment_tree.json').exists())
        self.assertEqual(fake.call_count, 1)

    def test_unknown_negative_branch_or_claimed_identity_is_rejected(self):
        for change in ('negative', 'hash', 'roots'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                saved_run = self.run
                self.run = Path(tmp) / 'lane'
                self.run.mkdir()
                self.save_manifest()
                answer = deepcopy(self.answer)
                if change == 'negative':
                    answer['tree']['nodes'][0]['reverse']['invented'] = deepcopy(
                        answer['tree']['nodes'][0]['reverse']['baseline'])
                elif change == 'hash':
                    answer['tree']['nodes'][0]['simulation_identity'] = 'invented'
                else:
                    answer['tree']['roots'] *= 5
                self.assertEqual(self.prepare(FakeRunner(return_value=answer))['status'], 'blocked')
                self.run = saved_run

    def test_two_layers_have_complete_predefined_routes_and_finite_cost(self):
        root = self.answer['tree']['nodes'][0]
        for arm_id, horizons in (('baseline', (7, 9)), ('treatment', (11, 13))):
            for horizon in horizons:
                raw = deepcopy(self.answer['designs'][0])
                if arm_id == 'treatment':
                    raw['feature_plan'] = deepcopy(raw['experiment_plan']['treatments'][0]['feature'])
                    raw['experiment_plan']['baseline'] = deepcopy(raw['feature_plan'])
                raw['experiment_plan']['treatments'][0]['feature']['horizon'] = horizon
                index = len(self.answer['designs'])
                reverse = deepcopy(raw)
                reverse['prediction_direction'] = 'negative'
                reverse['prediction'] = 'The opposite response may be informative.'
                self.answer['designs'].extend([raw, reverse])
                child = dict(node_id=f'{arm_id}_{horizon}', parent_id='root', parent_arm_id=arm_id,
                    design_index=index, targets=dict(baseline=[], treatment=[]), fallback=[],
                    reverse={arm: dict(design_index=index + 1, arm_id=arm,
                        interpretation='The opposite response may be informative.', targets=[])
                        for arm in ('baseline', 'treatment')})
                root['targets'][arm_id].append(child['node_id'])
                self.answer['tree']['nodes'].append(child)
        fake = FakeRunner(return_value=self.answer)
        result = self.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        tree = result['tree']['tree']
        self.assertEqual(len(tree['nodes']), 5)
        self.assertEqual(max(node['layer'] for node in tree['nodes']), 2)
        self.assertEqual(result['tree']['simulation_count'], 12)
        from wqb.experiment_tree import route_pair
        node = next(node for node in tree['nodes'] if node['node_id'] == 'root')
        measured = [dict(simulation_identity=expected['simulation_identity'], status='completed',
            scope=self.scope, period=self.period, sharpe=1, returns=.1)
            for expected in node['expected'].values()]
        self.assertEqual(len(route_pair(node, measured)['selected_node_ids']), 4)
        for row in measured:
            row.update(sharpe=0, returns=0)
        self.assertEqual(route_pair(node, measured)['status'], 'finished')
        for row in measured:
            row.update(sharpe=-1, returns=-.1)
        route = route_pair(node, measured)
        self.assertEqual(route['status'], 'waiting')
        self.assertEqual(len(route['confirmation_simulation_identities']), 2)
        self.assertEqual(result, self.prepare(fake))
        self.assertEqual(fake.call_count, 1)

    def test_reentrant_runner_and_changed_input_cannot_overwrite_running_task(self):
        def runner(brief):
            """Input: brief dict. Output: plan after competing calls; prove single owner survives."""
            other = FakeRunner(return_value=self.answer)
            self.assertEqual(self.prepare(other)['reason'], 'model_outcome_unknown')
            self.policy['initial_hypotheses'] = 3
            self.assertEqual(self.prepare(other)['status'], 'blocked')
            self.policy['initial_hypotheses'] = 4
            task = json.loads((self.run / planning.TASK_PATH).read_text(encoding='utf-8'))
            self.assertEqual(task['status'], 'running')
            other.assert_not_called()
            return deepcopy(self.answer)
        fake = FakeRunner(side_effect=runner)
        self.assertEqual(self.prepare(fake)['status'], 'completed')
        self.assertEqual(fake.call_count, 1)

    def test_process_interruption_keeps_unknown_task_without_replay(self):
        fake = FakeRunner(side_effect=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.prepare(fake)
        self.assertEqual(self.prepare(fake)['reason'], 'model_outcome_unknown')
        self.assertEqual(fake.call_count, 1)

    def test_received_outcome_can_finish_after_restart_without_model(self):
        fake = FakeRunner(return_value=self.answer)
        original = self.prepare(fake)
        path = self.run / planning.TASK_PATH
        task = json.loads(path.read_text(encoding='utf-8'))
        task['status'] = 'outcome_received'
        task.pop('result')
        task.pop('state_sha256')
        task['state_sha256'] = planning._digest(task)
        path.write_text(json.dumps(task), encoding='utf-8')
        self.assertEqual(self.prepare(fake), original)
        self.assertEqual(fake.call_count, 1)

    def test_full_manifest_drift_during_callback_blocks(self):
        def runner(brief):
            """Input: brief dict. Output: plan after unrelated frozen context drift."""
            self.manifest['start_snapshot']['measurement_period']['end'] = '2026-01-01'
            self.save_manifest()
            return deepcopy(self.answer)
        fake = FakeRunner(side_effect=runner)
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.assertFalse((self.run / 'runtime/experiment_tree.json').exists())
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.assertEqual(fake.call_count, 1)

    def test_global_vault_bytes_are_never_published_or_changed(self):
        before = {p.relative_to(self.knowledge): p.read_bytes() for p in self.knowledge.rglob('*') if p.is_file()}
        self.assertEqual(self.prepare(FakeRunner(return_value=self.answer))['status'], 'completed')
        after = {p.relative_to(self.knowledge): p.read_bytes() for p in self.knowledge.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_absent_opt_in_and_invalid_policy_never_call_model(self):
        fake = FakeRunner(return_value=self.answer)
        for version in (True, 0, 2, '1'):
            self.manifest['start_snapshot']['research_policy']['exploration_policy_version'] = version
            self.save_manifest()
            self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.manifest['start_snapshot']['research_policy']['exploration_policy_version'] = 1
        self.save_manifest()
        for count in (True, 0, 17, 4.0, '4'):
            self.policy['initial_hypotheses'] = count
            self.assertEqual(self.prepare(fake)['status'], 'blocked')
        fake.assert_not_called()

    def test_condition_schema_is_explicit_without_changing_legacy_default(self):
        from wqb.hypothesis_design import design_output_schema
        legacy = deepcopy(design_output_schema(1))
        schema = planning._output_schema(1)
        self.assertEqual(len(schema['properties']['designs']['items']['anyOf']), 2)
        self.assertEqual(legacy, design_output_schema(1))
        self.assertNotIn('anyOf', legacy['properties']['designs']['items'])

    def test_conditioned_design_is_actually_compiled_not_prose_only(self):
        from tests.test_hypothesis_conditions import condition_fixture
        raw, self.resources, self.scope = condition_fixture()
        for name, text in self.resources['source_texts'].items():
            path = self.knowledge / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        (self.knowledge / 'machine/source_index.jsonl').write_text(''.join(json.dumps(row) + '\n'
            for row in self.resources['source_index'].values()), encoding='utf-8')
        reverse = deepcopy(raw)
        reverse['prediction_direction'] = 'negative'
        self.answer['designs'] = [raw, reverse]
        result = self.prepare(FakeRunner(return_value=self.answer))
        self.assertEqual(result['status'], 'completed', result)
        experiment = result['receipts'][0]['compiled']['experiment']
        self.assertTrue(experiment['condition_filter_applied'])
        self.assertIn('if_else(greater(', experiment['arms'][1]['binding']['bound_expression'])

    def test_optional_tree_helper_returns_validated_payload_for_parent(self):
        from wqb import research_tree
        freezer = research_tree.freeze_tree
        research_tree.freeze_tree = None
        self.addCleanup(setattr, research_tree, 'freeze_tree', freezer)
        fake = FakeRunner(return_value=self.answer)
        result = self.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['tree']['status'], 'validated')
        self.assertEqual(result, self.prepare(fake))
        self.assertEqual(fake.call_count, 1)
        self.assertFalse((self.run / 'runtime/experiment_tree.json').exists())

    def test_unrelated_reverse_features_cannot_masquerade_as_confirmation(self):
        self.answer['designs'][1]['experiment_plan']['treatments'][0]['feature']['horizon'] = 22
        fake = FakeRunner(return_value=self.answer)
        result = self.prepare(fake)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('reverse must preserve', result['reason'])
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.assertEqual(fake.call_count, 1)

    def test_settings_and_owner_drift_never_replay_completed_task(self):
        fake = FakeRunner(return_value=self.answer)
        self.assertEqual(self.prepare(fake)['status'], 'completed')
        self.resources['settings']['decay'] = 9
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.resources['settings']['decay'] = 4
        manifest = json.loads((self.run / 'run_manifest.json').read_text(encoding='utf-8'))
        manifest['selected_option_id'] = 'replacement'
        (self.run / 'run_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        self.assertEqual(self.prepare(fake)['status'], 'blocked')
        self.assertEqual(fake.call_count, 1)

    def test_template_parameter_mismatch_is_not_reused(self):
        other_resources = deepcopy(self.resources)
        other_resources['settings']['decay'] = 9
        incompatible = validate_exploration(self.design, other_resources, self.scope)
        def runner(brief):
            """Input: brief dict. Output: plan; incompatible parameter settings cannot be preferred."""
            self.assertEqual(brief['compatible_template_receipts'], [])
            return deepcopy(self.answer)
        result = self.prepare(FakeRunner(side_effect=runner), [incompatible])
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['receipt_origins'], ['generated', 'generated'])

    def test_missing_task_with_existing_frozen_evidence_never_calls_again(self):
        fake = FakeRunner(return_value=self.answer)
        self.assertEqual(self.prepare(fake)['status'], 'completed')
        (self.run / planning.TASK_PATH).unlink()
        result = self.prepare(fake)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('manual reconciliation', result['reason'])
        self.assertEqual(fake.call_count, 1)

    def test_reverse_arms_are_optional_without_fake_reverse_plans(self):
        self.answer['tree']['nodes'][0]['reverse'] = {}
        self.answer['designs'].pop()
        fake = FakeRunner(return_value=self.answer)
        result = self.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['tree']['simulation_count'], 2)
        from wqb.experiment_tree import route_pair
        node = result['tree']['tree']['nodes'][0]
        measured = [dict(simulation_identity=expected['simulation_identity'], status='completed',
            scope=self.scope, period=self.period, sharpe=-1, returns=-.1)
            for expected in node['expected'].values()]
        route = route_pair(node, measured)
        self.assertEqual(route['status'], 'inconclusive')
        self.assertEqual(route['confirmation_simulation_identities'], [])
        self.assertEqual(result, self.prepare(fake))
        self.assertEqual(fake.call_count, 1)

    def test_policy_defaults_and_future_positive_values_are_validated(self):
        self.assertEqual(planning._policy({}),
            dict(schema_version=1, plan_depth=2, initial_hypotheses=4))
        self.policy = dict(plan_depth=3, initial_hypotheses=6)
        result = self.prepare(FakeRunner(return_value=self.answer))
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['tree']['tree']['limits'], dict(max_depth=3, max_width=6))
        for value in (True, 0, 17, '2', 2.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                planning._policy(dict(plan_depth=value))

    def test_returned_snapshot_preserves_metadata_and_freeze_is_idempotent(self):
        self.manifest['start_snapshot']['parent_metadata'] = dict(group_id='fictional-group', lane_id='lane')
        self.save_manifest()
        fake = FakeRunner(return_value=self.answer)
        result = self.prepare(fake)
        self.assertEqual(result['status'], 'completed', result)
        snapshot = result['snapshot']
        self.assertEqual(snapshot['parent_metadata'], self.manifest['start_snapshot']['parent_metadata'])
        self.assertEqual(snapshot['measurement_period'], self.period)
        self.assertEqual(snapshot['research_policy'], self.manifest['start_snapshot']['research_policy'])
        before = (self.run / 'run_manifest.json').read_bytes()
        certificate = snapshot['exploration_context']['resource_certificates'][0]
        planning.freeze_initial_research_snapshot(self.run, self.knowledge, self.manifest,
            snapshot, certificate)
        self.assertEqual((self.run / 'run_manifest.json').read_bytes(), before)
        self.assertEqual(result, self.prepare(fake))


if __name__ == '__main__':
    unittest.main()
