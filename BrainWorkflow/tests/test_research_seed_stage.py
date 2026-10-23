"""Frozen Seed stage uses only measured dates and retained tree identities."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_seed_policy import measured
from wqb.benchmark_rules import default_benchmark_rules
from wqb.research_seed_stage import normalize_measured_row, prepare_seed_selection


class ResearchSeedStageTests(unittest.TestCase):
    def test_no_invented_period_and_identity(self):
        row = measured()
        row['expression_hash'] = row['simulation_identity']
        row.pop('test_period')
        normalized = normalize_measured_row(row, 'lane')
        self.assertNotIn('test_period', normalized)
        row['metrics'].update(startDate='2020-01-01', endDate='2025-12-31')
        self.assertEqual(normalize_measured_row(row, 'lane')['test_period'],
                         dict(start='2020-01-01', end='2025-12-31'))

    def test_only_completed_tree_retained_rows_can_be_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'runtime').mkdir()
            (root / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=dict(
                research_policy=dict(preplanned_tree_version=1)))))
            row = measured()
            row['expression_hash'] = row['simulation_identity']
            path = root / 'runtime/tree_execution.json'
            path.write_text(json.dumps(dict(status='waiting')))
            with self.assertRaises(ValueError):
                prepare_seed_selection(root, [row])
            path.write_text(json.dumps(dict(status='finished', retained_expression_hashes=[row['expression_hash']])))
            with patch('wqb.research_seed_stage.load_run_benchmark_rules', return_value=default_benchmark_rules()):
                result = prepare_seed_selection(root, [row])
            self.assertEqual(len(result['seed_rows']), 1)
            self.assertFalse(result['submission_qualified'])


if __name__ == '__main__':
    unittest.main()
