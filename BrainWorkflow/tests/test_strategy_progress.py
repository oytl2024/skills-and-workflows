import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


class StrategyProgressTests(unittest.TestCase):
    def test_source_join_keeps_multi_children_and_failure_metrics(self):
        """Input: source JSONL fixtures. Output: None. Verify sibling isolation and checked metrics."""
        self.assertIsNotNone(importlib.util.find_spec('wqb.strategy_progress'))
        from wqb.strategy_progress import load_strategy_progress
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'bound'
            source.mkdir()
            fixtures = {
                'planned_candidates.jsonl': [{'expression_hash': 'same', 'child_index': i} for i in (0, 1)],
                'simulation_events.jsonl': [
                    {'event': 'SUBMITTED', 'expression_hash': 'same', 'child_index': i, 'progress_url': '/simulations/parent'} for i in (0, 1)
                ] + [{'event': 'CHECKED', 'expression_hash': 'same', 'child_index': 0, 'alpha_id': 'A'}],
                'all_alphas.jsonl': [{'alpha_id': 'A', 'expression_hash': 'same', 'child_index': 0,
                                      'status': 'CHECKED', 'metrics': {'sharpe': 1.2}, 'failed': ['LOW_FITNESS'], 'hard_pass': False}],
            }
            for name, rows in fixtures.items():
                (source / name).write_text(''.join(json.dumps(row) + '\n' for row in rows))
            result = load_strategy_progress(source)
            self.assertEqual(len(result['rows']), 2)
            first, second = result['rows']
            self.assertEqual(first['status'], 'checked')
            self.assertEqual(first['metrics']['sharpe'], 1.2)
            self.assertEqual(first['failures'], ['LOW_FITNESS'])
            self.assertEqual(second['status'], 'running')
            self.assertNotEqual(first['key'], second['key'])
            self.assertEqual(second['source_run_dir'], str(source))
            self.assertTrue(second['updated_at'])

    def test_same_parent_url_different_hashes_are_not_one_alpha(self):
        """Input: parent simulation siblings. Output: None. Reject parent-URL-only joins."""
        self.assertIsNotNone(importlib.util.find_spec('wqb.strategy_progress'))
        from wqb.strategy_progress import load_strategy_progress
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'simulation_events.jsonl').write_text('\n'.join(json.dumps(row) for row in [
                {'event': 'SUBMITTED', 'progress_url': '/simulations/parent', 'expression_hash': 'h1'},
                {'event': 'SUBMITTED', 'progress_url': '/simulations/parent', 'expression_hash': 'h2'},
                {'event': 'ERROR', 'expression_hash': 'h1', 'message': 'failed check'},
            ]) + '\n{"partial":')
            rows = load_strategy_progress(root)['rows']
            self.assertEqual([row['status'] for row in rows], ['error', 'running'])
            self.assertEqual(rows[0]['failures'], ['failed check'])
