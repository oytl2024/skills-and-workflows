import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from wqb.repair_scheduler import execute_repair_round
from wqb.repair_runtime import RepairProgressPending


class RepairSchedulerTests(unittest.TestCase):
    def test_deferred_first_parent_does_not_block_later_existing_progress(self):
        import os
        from unittest.mock import patch
        from wqb.runtime_control import DAILY_RECONCILE_ENV, DailyBudgetExhausted
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [{'alpha_id': name, 'expression_hash': name, 'benchmark_label': 'repairable_signal'} for name in ('a', 'b')]
            (root / 'all_alphas.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            executor = Mock()
            executor.prepare.side_effect = lambda root, parent, history, allowance: {
                'variants': [{'expression_hash': parent['alpha_id'] + '-child'}], 'evidence_digest': parent['alpha_id']}
            pending = [True]
            def execute(root, parent, actions, maximum):
                """Input: fixture parent/actions/cap. Output: checked rows. Recover b only after its first saved progress wait."""
                name = parent['alpha_id']
                if name == 'b' and pending[0]:
                    pending[0] = False
                    raise RepairProgressPending('2000-01-01T00:00:00+00:00', 'existing-b')
                return [{'alpha_id': 'child-' + name, 'expression_hash': name + '-child', 'parent_alpha_id': name,
                    'parent_expression_hash': name, 'status': 'CHECKED', 'hard_pass': name == 'b',
                    'failed': [] if name == 'b' else ['LOW_FITNESS'], 'pending': [], 'metrics': {}, 'expression': 'rank(cash)'}]
            executor.side_effect = execute
            execute_repair_round(root, {'rows': rows}, executor, 3)
            (root / 'runtime_control.json').write_text(json.dumps({'simulation_budget_mode': 'daily'}))
            with patch.dict(os.environ, {DAILY_RECONCILE_ENV: '1'}), patch(
                    'wqb.daily_simulation_budget.read_daily_budget', return_value={'remaining': 0}):
                with self.assertRaises(DailyBudgetExhausted):
                    execute_repair_round(root, {'rows': rows}, executor, 3)
            receipt = json.loads((root / 'stages/repair/repair_execution.json').read_text())
            self.assertEqual(receipt['attempts'][1]['phase'], 'checked')
            self.assertEqual(executor.prepare.call_count, 2)
            self.assertEqual(executor.call_count, 3)
            receipt['attempts'][1].update(phase='waiting', children=[], next_poll_at='2000-01-01T00:00:00+00:00')
            (root / 'stages/repair/repair_execution.json').write_text(json.dumps(receipt))
            executor.side_effect = ValueError('invalid recovered child evidence')
            with patch.dict(os.environ, {DAILY_RECONCILE_ENV: '1'}), patch(
                    'wqb.daily_simulation_budget.read_daily_budget', return_value={'remaining': 0}):
                blocked = execute_repair_round(root, {'rows': rows}, executor, 3)
            self.assertFalse(blocked['recovery_eligible'])
            self.assertIn('invalid recovered child evidence', blocked['blocker'])

    def test_daily_wait_preserves_prior_child_and_original_attempt_plans(self):
        from wqb.runtime_control import DailyBudgetExhausted
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [{'alpha_id': name, 'expression_hash': name, 'benchmark_label': 'repairable_signal'} for name in ('a', 'b')]
            (root / 'all_alphas.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            executor = Mock()
            executor.prepare.side_effect = lambda root, parent, history, allowance: {
                'variants': [{'expression_hash': parent['alpha_id'] + '-child'}], 'evidence_digest': parent['alpha_id']}
            waited = []
            def execute(root, parent, actions, maximum):
                """Input: local parent/actions/cap. Output: checked child dicts or daily wait. No platform client exists."""
                name = parent['alpha_id']
                if name == 'b' and not waited:
                    waited.append(True)
                    raise DailyBudgetExhausted({'remaining': 0})
                return [{'alpha_id': 'child-' + name, 'expression_hash': name + '-child', 'parent_alpha_id': name,
                         'parent_expression_hash': name, 'status': 'CHECKED', 'hard_pass': True,
                         'failed': [], 'pending': [], 'metrics': {}, 'expression': 'rank(cash)'}]
            executor.side_effect = execute
            with self.assertRaises(DailyBudgetExhausted):
                execute_repair_round(root, {'rows': rows}, executor, 2)
            receipt = json.loads((root / 'stages/repair/repair_execution.json').read_text())
            self.assertEqual(receipt['attempts'][0]['phase'], 'checked')
            self.assertEqual(receipt['attempts'][1]['phase'], 'ready')
            original_plan = receipt['attempts'][1]['plan']
            resumed = execute_repair_round(root, {'rows': rows}, executor, 2)
            self.assertEqual(resumed['status'], 'completed')
            self.assertEqual(resumed['attempts'][1]['plan'], original_plan)
            self.assertEqual(executor.prepare.call_count, 2)
            self.assertEqual(executor.call_count, 3)

    def test_modified_parent_evidence_is_not_append_only_recovery(self):
        import hashlib
        from wqb.runtime_control import _write
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {'alpha_id': 'a', 'expression_hash': 'a', 'benchmark_label': 'repairable_signal', 'metrics': {'fitness': .5}}
            source = root / 'all_alphas.jsonl'
            source.write_text(json.dumps(row) + '\n')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            _write(root / 'stages/repair/repair_execution.json', {'run_id': root.name, 'max_simulations': 8,
                'input_sha256': digest, 'last_sha256': digest, 'parent_keys': [['a', 'a']], 'attempts': []})
            row['metrics']['fitness'] = 99
            source.write_text(json.dumps(row) + '\n')
            executor = Mock()
            result = execute_repair_round(root, {'rows': [row]}, executor, 8)
            self.assertIn('lineage', result['blocker'])
            executor.prepare.assert_not_called()
    def test_waiting_parent_does_not_block_independent_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [{'alpha_id': name, 'expression_hash': name, 'benchmark_label': 'repairable_signal'} for name in ('a', 'b')]
            (root / 'all_alphas.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            executor = Mock()
            executor.prepare.side_effect = lambda root, parent, history, allowance: {
                'variants': [{'expression_hash': parent['alpha_id'] + '-child'}],
                'evidence_digest': parent['alpha_id']}
            def execute(root, parent, actions, maximum):
                if parent['alpha_id'] == 'a':
                    raise RepairProgressPending('2099-01-01T00:00:00+00:00', 'a')
                return [{'alpha_id': 'child-b', 'expression_hash': 'b-child', 'parent_alpha_id': 'b',
                         'parent_expression_hash': 'b', 'status': 'CHECKED', 'hard_pass': True,
                         'failed': [], 'pending': [], 'metrics': {}, 'expression': 'rank(cash)'}]
            executor.side_effect = execute
            result = execute_repair_round(root, {'rows': rows}, executor, 2)
            self.assertEqual(executor.call_count, 2)
            self.assertEqual(result['budget_reserved'], 2)
            self.assertEqual(result['status'], 'paused')
            self.assertIn('child-b', (root / 'all_alphas.jsonl').read_text())
            self.assertEqual(result['attempts'][1]['experiment_trace']['outcome'], 'inconclusive')
            execute_repair_round(root, {'rows': rows}, executor, 2)
            self.assertEqual(executor.call_count, 2, 'future wait and completed child must not run again')

    def test_model_stop_does_not_consume_simulations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {'alpha_id': 'a', 'expression_hash': 'a', 'benchmark_label': 'repairable_signal'}
            (root / 'all_alphas.jsonl').write_text(json.dumps(row) + '\n')
            executor = Mock()
            executor.prepare.return_value = {'variants': [], 'evidence_digest': 'stop'}
            result = execute_repair_round(root, {'rows': [row]}, executor, 8)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['budget_reserved'], 0)
            self.assertEqual(result['attempts'][0]['plan']['evidence_digest'], 'stop')
            executor.assert_not_called()
