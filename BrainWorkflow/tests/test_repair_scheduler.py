import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from wqb.repair_scheduler import execute_repair_round
from wqb.repair_runtime import RepairProgressPending


class RepairSchedulerTests(unittest.TestCase):
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
