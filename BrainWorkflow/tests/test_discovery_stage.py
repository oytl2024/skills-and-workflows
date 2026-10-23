import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tests.test_workflow_stage_outcomes import checked_alpha, write_rows
from wqb.workflow_stage_adapters import advance_post_schedule_stage


class DiscoveryStageTests(unittest.TestCase):
    def test_recovered_exhaustion_clears_old_failure_and_replays_once(self):
        """Input: recoverable network failure then exhausted variants. Output: assertions. Completed recovery must not retain a blocker."""
        from wqb.research_planning import ResearchVariantsExhausted
        from wqb.repair_runtime import RepairRecoveryPending
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            write_rows(run, [checked_alpha('repairable')])
            executor = Mock(side_effect=[RepairRecoveryPending('network'), ResearchVariantsExhausted('exhausted')])
            first = advance_post_schedule_stage(run, 'batch_generation', discovery_executor=executor)
            self.assertEqual(first['status'], 'paused')
            second = advance_post_schedule_stage(run, 'batch_generation', discovery_executor=executor)
            self.assertEqual(second['status'], 'completed')
            third = advance_post_schedule_stage(run, 'batch_generation', discovery_executor=executor)
            self.assertEqual(third['status'], 'completed')
            self.assertEqual(executor.call_count, 2)

    def test_exhausted_discovery_does_not_strand_measured_seed(self):
        """Input: horizon-free seed with no novel variants. Output: assertions. Continue to bounded Repair without repeated construction."""
        from wqb.research_planning import ResearchVariantsExhausted
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            write_rows(run, [checked_alpha('repairable')])
            executor = Mock(side_effect=ResearchVariantsExhausted('bounded variants exhausted'))
            first = advance_post_schedule_stage(run, 'batch_generation', discovery_executor=executor)
            second = advance_post_schedule_stage(run, 'batch_generation', discovery_executor=executor)
            self.assertEqual(first['status'], 'completed')
            self.assertEqual(second['status'], 'completed')
            self.assertEqual(executor.call_count, 1)
            receipt = json.loads((run / 'stages/batch_generation/discovery_execution.json').read_text())
            self.assertTrue(receipt['discovery_exhausted'])
            self.assertEqual(len((run / 'all_alphas.jsonl').read_text().splitlines()), 1)

    def test_restart_after_merged_publication_does_not_execute_discovery_twice(self):
        """Input: interrupted atomic publication. Output: assertions. Reconcile prepared receipt before repeating work."""
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            parent = checked_alpha('repairable')
            write_rows(run, [parent])
            child = {**checked_alpha('weak'), 'alpha_id': 'child', 'expression_hash': 'child-hash',
                     'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash']}
            executor = Mock(return_value=[child])
            replace = Path.replace
            def interrupted(source, target):
                """Input: Paths. Output: exception after move. Simulate a crash after durable merged evidence."""
                result = replace(source, target)
                if source.name == 'merged_alphas.jsonl':
                    raise OSError('interrupted after publish')
                return result
            with patch.object(Path, 'replace', interrupted):
                advance_post_schedule_stage(run, 'batch_generation', discovery_executor=executor)
            result = advance_post_schedule_stage(run, 'batch_generation', discovery_executor=executor)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(executor.call_count, 1)

    def test_promising_seed_executes_discovery_once_and_keeps_lineage(self):
        """Input: measured near miss and Discovery executor. Output: assertions. Do real stage work rather than reuse Scout."""
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            parent = checked_alpha('repairable')
            write_rows(run, [parent])
            child = {**checked_alpha('weak'), 'alpha_id': 'discovery-child', 'expression_hash': 'child-hash',
                     'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash']}
            executor = Mock(return_value=[child])
            first = advance_post_schedule_stage(run, 'batch_generation', discovery_executor=executor)
            second = advance_post_schedule_stage(run, 'batch_generation', discovery_executor=executor)
            self.assertEqual(first['status'], 'completed')
            self.assertEqual(second['status'], 'completed')
            self.assertEqual(executor.call_count, 1)
            self.assertEqual(len((run / 'all_alphas.jsonl').read_text().splitlines()), 2)
            self.assertTrue((run / 'stages/batch_generation/seed.json').exists())

    def test_weak_scout_does_not_spend_discovery_budget(self):
        """Input: weak Scout evidence. Output: assertions. Do not exploit an absent signal."""
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            write_rows(run, [checked_alpha('weak')])
            executor = Mock()
            advance_post_schedule_stage(run, 'batch_generation', discovery_executor=executor)
            executor.assert_not_called()
