import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb import research_planning


class ResearchPlanningTests(unittest.TestCase):
    def test_paired_measurement_reuse_retains_complete_evidence_and_rejects_check_conflicts(self):
        from copy import deepcopy
        from tests.test_hypothesis_selection import paired_selection_fixture
        from wqb.cli import simulation_identity_hash
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, experiments = paired_selection_fixture(root)
            snapshot['measurement_period'] = dict(start='2020-01-01', end='2025-12-31')
            arm = experiments[0]['arms'][0]
            expression, settings = arm['binding']['bound_expression'], arm['settings']
            identity = simulation_identity_hash(expression, settings)
            measured = dict(alpha_id='old-baseline', simulation_id='old-sim', expression=expression,
                expression_hash=identity, settings=settings, scope=arm['scope'], measurement_period=snapshot['measurement_period'],
                metrics=dict(sharpe=1), status='CHECKED', hard_pass=True, failed=[], pending=[],
                checks=[dict(name='SHARPE', result='PASS')])
            path = root / 'all_alphas.jsonl'
            path.write_text(json.dumps(measured) + '\n', encoding='utf-8')
            reused = research_planning._paired_measurements(snapshot, experiments, str(root))[identity]
            for key in ('alpha_id', 'simulation_id', 'checks', 'hard_pass', 'failed', 'pending'):
                self.assertEqual(reused.get(key), measured[key])
            conflict = deepcopy(measured)
            conflict.update(hard_pass=False, failed=[dict(name='SHARPE', result='FAIL')],
                            checks=[dict(name='SHARPE', result='FAIL')])
            path.write_text(''.join(json.dumps(row) + '\n' for row in (measured, conflict)), encoding='utf-8')
            self.assertNotIn(identity, research_planning._paired_measurements(snapshot, experiments, str(root)))

    def test_paired_dispatch_is_scout_only_not_repair_or_discovery(self):
        from tests.test_hypothesis_selection import paired_selection_fixture
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, _ = paired_selection_fixture(root)
            (root / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)))
            with patch('wqb.research_planning.prepare_paired_hypothesis_plan', return_value=dict(kind='paired')) as paired, patch(
                    'wqb.research_planning.prepare_hypothesis_discovery_plan', return_value=dict(kind='discovery')), patch(
                    'wqb.research_planning.prepare_hypothesis_plan', return_value=dict(kind='existing')):
                self.assertEqual(research_planning.prepare_source_plan(root, {}, dict(workflow_stage='discovery'), 'now'), dict(kind='discovery'))
                self.assertEqual(research_planning.prepare_source_plan(root, {}, dict(workflow_stage='repair'), 'now'), dict(kind='existing'))
                paired.assert_not_called()

    def test_paired_original_remaining_quota_and_verified_baseline_measurement_reuse(self):
        from tests.test_hypothesis_selection import paired_selection_fixture
        from wqb.cli import simulation_identity_hash
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, experiments = paired_selection_fixture(root)
            snapshot['measurement_period'] = dict(start='2020-01-01', end='2025-12-31')
            run = root / 'run'
            run.mkdir()
            (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)))
            settings = experiments[0]['arms'][0]['settings']
            config = dict(settings, instrument_type=settings['instrumentType'], unit_handling=settings['unitHandling'],
                nan_handling=settings['nanHandling'], max_alphas_per_round=30, run_root=str(root))
            (run / 'runtime_control.json').write_text(json.dumps(dict(desired_state='running', max_simulations=150)))
            (run / 'runtime_status.json').write_text(json.dumps(dict(simulation_attempts=149)))
            before = (run / 'runtime_control.json').read_bytes()
            with self.assertRaises(research_planning.ResearchVariantsExhausted):
                research_planning.prepare_source_plan(run, config, {}, 'one')
            baseline = experiments[0]['arms'][0]
            expression = baseline['binding']['bound_expression']
            identity = simulation_identity_hash(expression, settings)
            history = root / 'history'
            history.mkdir()
            (history / 'all_alphas.jsonl').write_text(json.dumps(dict(alpha_id='measured-baseline',
                expression=expression, expression_hash=identity, settings=settings, scope=baseline['scope'],
                measurement_period=snapshot['measurement_period'], metrics=dict(sharpe=1), status='measured')) + '\n')
            plan = research_planning.prepare_source_plan(run, config, dict(research_round_id='reuse'), 'reuse')
            self.assertEqual(len(plan['scheduled_hypotheses']), 1)
            sidecar = json.loads(Path(plan['experiment_sidecar_path']).read_text())
            self.assertEqual(sum(arm['reused'] for arm in sidecar['arms']), 1)
            (run / 'runtime_status.json').write_text(json.dumps(dict(simulation_attempts=150)))
            self.assertEqual(plan, research_planning.prepare_source_plan(run, config, dict(research_round_id='reuse'), 'restart'))
            self.assertEqual((run / 'runtime_control.json').read_bytes(), before)

    def test_paired_plan_persists_sidecars_replays_exact_inputs_without_grid_or_model(self):
        from tests.test_hypothesis_selection import paired_selection_fixture
        from wqb import generator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, experiments = paired_selection_fixture(root)
            run = root / 'run'
            run.mkdir()
            (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)))
            settings = experiments[0]['arms'][0]['settings']
            config = dict(settings, instrument_type=settings['instrumentType'], unit_handling=settings['unitHandling'],
                nan_handling=settings['nanHandling'], max_alphas_per_round=3)
            with patch('wqb.research_planning._hypothesis_pool', side_effect=AssertionError('grid')), patch(
                    'wqb.research_planning.run_ai_checkpoint', side_effect=AssertionError('model')):
                first = research_planning.prepare_source_plan(run, config, {}, 'now')
                second = research_planning.prepare_source_plan(run, config, {}, 'later')
            self.assertEqual(first, second)
            sidecar = Path(first['experiment_sidecar_path'])
            self.assertTrue(sidecar.is_file())
            self.assertEqual(len(json.loads(sidecar.read_text())['arms']), 2)
            self.assertEqual(len(generator.generate_hypothesis_candidates(snapshot, first['scheduled_hypotheses'], 3)), 2)
            self.assertEqual(first['hypothesis_plan_quality']['generated_count'], 2)
            self.assertEqual(first['hypothesis_plan_quality']['selected_count'], 2)
            sidecar.write_text('{}')
            with self.assertRaisesRegex(research_planning.ResearchPlanningBlocked, 'sidecar'):
                research_planning.prepare_source_plan(run, config, {}, 'tampered')

    def test_verified_planning_release_preserves_stop_and_all_limits(self):
        """Input: resolved planning case and paused mission. Output: assertions. Release local fault only, never Start."""
        from dataclasses import replace
        from tests.test_research_rounds import round_fixture, write_json
        from wqb.workflow_state import load_run_state, write_run_state
        with tempfile.TemporaryDirectory() as tmp:
            _, run = round_fixture(Path(tmp), stage='scout_seed')
            state_path = run / 'run_state.json'
            state = load_run_state(state_path)
            write_run_state(state_path, replace(state, status='paused', pause_reason='research_planning_blocked: empty'))
            handoff = run / 'runtime/research_handoff.json'
            write_json(handoff, {'status': 'blocked', 'stop_reason': 'research_planning_blocked', 'message': 'empty'})
            control_path = run / 'runtime_control.json'
            control = json.loads(control_path.read_text())
            write_json(control_path, {**control, 'desired_state': 'paused'})
            before = control_path.read_bytes()
            with patch('wqb.recovery_cases.read_current_recovery_case', return_value={
                'case_id': 'verified', 'status': 'resolved', 'action': 'research-loop-blocked', 'stage': 'scout_seed'}):
                self.assertTrue(research_planning.release_verified_planning_stop(run, 'verified', 'now'))
                self.assertFalse(research_planning.release_verified_planning_stop(run, 'verified', 'restart'))
            self.assertEqual(control_path.read_bytes(), before)
            self.assertEqual(load_run_state(state_path).status, 'paused')
            self.assertIn('checked research results', load_run_state(state_path).pause_reason)
            self.assertEqual(json.loads(handoff.read_text())['message'], 'empty')

    def test_unverified_planning_case_cannot_release_handoff(self):
        """Input: unresolved or different case. Output: assertions. Fail closed before state mutation."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch('wqb.recovery_cases.read_current_recovery_case', return_value={'status': 'maintenance_approved'}):
                self.assertFalse(research_planning.release_verified_planning_stop(Path(tmp), 'case', 'now'))
            self.assertFalse((Path(tmp) / 'runtime/research_handoff.json').exists())

    def test_missing_bound_snapshot_blocks_before_model_or_platform(self):
        """Input: a real run manifest lacking snapshot. Output: assertions. Fail closed before research judgment."""
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / 'run_manifest.json').write_text('{}')
            metadata = {'exact_field_id': 'cash', 'template_provenance': {
                'template_id': 'cash', 'skeleton': 'rank({field})', 'hypothesis': 'Cash resilience'}}
            with patch('wqb.research_planning.run_ai_checkpoint') as model:
                with self.assertRaises(research_planning.ResearchPlanningBlocked):
                    research_planning.prepare_source_plan(run, {'ai_executor': 'codex'}, metadata, 'now')
            model.assert_not_called()

    def test_model_decision_is_validated_consumed_and_cached_per_round(self):
        """Input: bounded checkpoint decisions. Output: assertions. Consume actual AI decisions once per immutable plan."""
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            metadata = {'research_round_id': 'round-0001', 'exact_field_id': 'cash',
                        'template_provenance': {'template_id': 'cash', 'skeleton': 'rank({field})',
                                                'hypothesis': 'Cash resilience'}}
            config = {'ai_executor': 'codex'}
            result = {'status': 'completed', 'summary': 'Slow cash information favors longer holding.',
                      'decision': {'template_id': 'cash', 'field_id': 'cash', 'preferred_decay': 12}}
            with patch('wqb.research_planning.run_ai_checkpoint', return_value=result) as model:
                first = research_planning.prepare_source_plan(run, config, metadata, 'now')
                second = research_planning.prepare_source_plan(run, config, metadata, 'later')
            self.assertEqual(first, second)
            self.assertEqual(first['scheduled_template']['preferred_decay'], 12)
            self.assertEqual(model.call_count, 1)
            self.assertTrue(first['ai_plan_receipt'])

    def test_invalid_or_failed_ai_output_never_falls_back_to_invented_decision(self):
        """Input: mismatched model output. Output: assertions. Preserve a planning blocker instead of running live."""
        with tempfile.TemporaryDirectory() as tmp:
            metadata = {'research_round_id': 'round-0001', 'exact_field_id': 'cash',
                        'template_provenance': {'template_id': 'cash', 'skeleton': 'rank({field})',
                                                'hypothesis': 'Cash resilience'}}
            with patch('wqb.research_planning.run_ai_checkpoint', return_value={'status': 'failed'}):
                with self.assertRaises(research_planning.ResearchPlanningBlocked):
                    research_planning.prepare_source_plan(Path(tmp), {'ai_executor': 'codex'}, metadata, 'now')
