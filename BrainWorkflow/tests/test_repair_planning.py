import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_repair_runtime import parent_row
from wqb.repair_planning import prepare_repair_decision, RepairPlanningBlocked


class RepairPlanningTests(unittest.TestCase):
    def test_snapshot_semantics_exclude_similar_field_and_large_administrative_history(self):
        from wqb.repair_planning import _knowledge
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = {'data_ledger_rows': [
                {'field_id': 'buzz_trend_metric_1', 'field_description': 'wrong prefix'},
                {'field_id': 'buzz_trend_metric_11', 'field_description': 'Attention trend',
                 'field_type': 'VECTOR', 'source_paths': ['x' * 20000]}],
                'template_rows': [{'template_id': 'trend', 'hypothesis': 'Persistent attention',
                                   'repair_levers': ['decay'], 'experiment_paths': ['x' * 20000]}]}
            (root / 'run_manifest.json').write_text(json.dumps({'start_snapshot': snapshot}))
            evidence = _knowledge(root, {'expression': 'rank(vec_avg(buzz_trend_metric_11))'})
            self.assertEqual([row['field_id'] for row in evidence['fields']], ['buzz_trend_metric_11'])
            self.assertLess(len(json.dumps(evidence)), 3000)
            self.assertEqual(evidence['templates'][0]['hypothesis'], 'Persistent attention')
            self.assertIn('source_row_sha256', evidence['fields'][0])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.parent = parent_row()
        self.parent['metrics'] = {'fitness': .5, 'sharpe': 1., 'turnover': .3}
        self.config = {'ai_executor_argv': ['fake', '{input}', '{output}']}
        self.answer = {'status': 'completed', 'summary': 'Test slower holding.', 'decision': {
            'parent_alpha_id': 'parent', 'parent_expression_hash': 'parent-hash',
            'diagnosis': 'Fitness weak; test lower turnover.', 'economic_rationale': 'Persistent cash signal.',
            'hypothesis': 'Longer holding may reduce noise.', 'expected_improvement': 'fitness',
            'risks': 'May lag changes.', 'action': 'test', 'edit': 'decay', 'value': 8,
            'target_metric': 'fitness', 'target_direction': 'increase',
            'falsification': 'Fitness does not improve.', 'applicability': 'Persistent cash signals only.'}}

    def test_decision_is_persisted_and_restart_reuses_it(self):
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=self.answer) as worker:
            first = prepare_repair_decision(self.root, self.parent, [], 2, self.config, '2026-10-12T00:00:00Z')
            second = prepare_repair_decision(self.root, self.parent, [], 2, self.config, '2026-10-12T00:01:00Z')
        self.assertEqual(first, second)
        self.assertEqual(first['variants'][0]['settings']['decay'], 8)
        self.assertEqual(worker.call_count, 1)
        self.assertEqual(first['decision']['hypothesis'], self.answer['decision']['hypothesis'])

    def test_versioned_contract_requires_measured_target(self):
        from wqb.repair_planning import validate_repair_decision
        evidence = {'schema_version': 2, 'parent': self.parent | {
            'parent_alpha_id': 'parent', 'parent_expression_hash': 'parent-hash'}, 'history': []}
        self.answer['decision'].pop('target_metric')
        with self.assertRaises(RepairPlanningBlocked):
            validate_repair_decision(self.answer['decision'], evidence)

    def test_stale_parent_rejected(self):
        self.answer['decision']['parent_expression_hash'] = 'other'
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=self.answer):
            with self.assertRaises(RepairPlanningBlocked):
                prepare_repair_decision(self.root, self.parent, [], 2, self.config, 'now')

    def test_missing_ai_is_not_rule_fallback(self):
        with self.assertRaises(RepairPlanningBlocked):
            prepare_repair_decision(self.root, self.parent, [], 2, {}, 'now')

    def test_tampered_receipt_cannot_claim_model_authorship(self):
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=self.answer):
            plan = prepare_repair_decision(self.root, self.parent, [], 2, self.config, 'now')
        saved = json.loads(Path(plan['receipt_path']).read_text())
        saved['judgment']['decision']['value'] = 20
        Path(plan['receipt_path']).write_text(json.dumps(saved))
        with self.assertRaises(RepairPlanningBlocked):
            prepare_repair_decision(self.root, self.parent, [], 2, self.config, 'later')

    def test_stop_decision_has_no_variants(self):
        self.answer['decision'].update(action='stop', edit='none', value=0)
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=self.answer):
            result = prepare_repair_decision(self.root, self.parent, [], 2, self.config, 'now')
        self.assertEqual(result['variants'], [])

    def test_history_changes_identity_and_missing_pnl_is_explicit(self):
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=self.answer) as worker:
            first = prepare_repair_decision(self.root, self.parent, [], 2, self.config, 'now')
            self.answer['decision']['value'] = 12
            second = prepare_repair_decision(self.root, self.parent, [{'alpha_id': 'c', 'metrics': {'fitness': .5}}], 1, self.config, 'later')
        self.assertNotEqual(first['evidence_digest'], second['evidence_digest'])
        self.assertEqual(worker.call_count, 2)
        inputs = list((self.root / 'runtime/repair_decisions').glob('*.input.json'))
        evidence = json.loads(inputs[0].read_text())
        self.assertEqual(evidence['pnl']['status'], 'unavailable')
        self.assertEqual(evidence['knowledge']['status'], 'unavailable')

    def test_unsupported_edit_or_duplicate_is_rejected(self):
        for edit, value in [('arbitrary_code', 1), ('decay', 100), ('decay', True), ('decay', 2)]:
            with self.subTest(edit=edit, value=value):
                self.answer['decision'].update(edit=edit, value=value)
                with patch('wqb.repair_planning.run_ai_checkpoint', return_value=self.answer):
                    with self.assertRaises(RepairPlanningBlocked):
                        prepare_repair_decision(self.root, self.parent, [], 2, self.config, 'now')

    def test_worker_pause_cancels_process(self):
        from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
        from wqb.runtime_control import RuntimePaused
        from unittest.mock import Mock
        checkpoint = append_ai_checkpoint(self.root, 'repair_decision', 'test', [], 'now')
        process = Mock(pid=123)
        with patch('wqb.ai_checkpoints.subprocess.Popen', return_value=process), patch(
                'wqb.ai_checkpoints.check_submission_allowed', side_effect=[None, RuntimePaused('stopped')]), patch(
                'wqb.ai_checkpoints.stop_worker_tree') as stop:
            with self.assertRaises(RuntimePaused):
                run_ai_checkpoint(self.root, checkpoint.checkpoint_id,
                                  ['fake', '{input}', '{output}'], cancel_on_pause=True)
        stop.assert_called_once_with(process)
