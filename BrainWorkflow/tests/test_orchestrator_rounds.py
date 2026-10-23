import json
from pathlib import Path
import tempfile
import unittest

from tests.test_research_rounds import round_fixture, write_json
from tests.test_workflow_stage_outcomes import checked_alpha, write_rows
from wqb.workflow_state import load_run_state


class OrchestratorRoundTests(unittest.TestCase):
    def test_no_signal_triage_restarts_scout_instead_of_closing_mission(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, run = round_fixture(Path(tmp))
            result = controller.continue_once('2026-10-11T01:01:00Z')
            self.assertEqual(result['current_stage'], 'scout_seed')
            self.assertEqual(result['status'], 'running')
            self.assertTrue((run / 'rounds/round-0001/all_alphas.jsonl').exists())
            self.assertTrue((run / 'research_record.json').exists())
            record = json.loads((run / 'research_record.json').read_text())
            self.assertEqual(record['backtest'][0]['expression_hash'], 'parent-hash')

    def test_no_authority_blocks_instead_of_finishing_no_signal_mission(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, run = round_fixture(Path(tmp))
            write_json(run / 'runtime_control.json', {})
            result = controller.continue_once('2026-10-11T01:01:00Z')
            self.assertEqual(result['status'], 'paused')
            self.assertIn('research_mission_authority_required', result['pause_reason'])
            self.assertEqual(load_run_state(run / 'run_state.json').current_stage, 'triage')

    def test_repairable_triage_goes_to_repair_not_new_scout(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, run = round_fixture(Path(tmp))
            write_rows(run, [checked_alpha()])
            result = controller.continue_once('2026-10-11T01:01:00Z')
            self.assertEqual(result['current_stage'], 'repair')
            self.assertFalse((run / 'research_rounds.json').exists())

    def test_exhausted_checked_repair_selects_alternate_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, run = round_fixture(Path(tmp), 'repair')
            write_rows(run, [checked_alpha()])

            def execute(root, parent, actions, maximum):
                """Input: real executor arguments. Output: checked children list. Model a non-improving bounded repair."""
                return [checked_alpha('weak', alpha_id='child', expression_hash='child-hash',
                                      parent_alpha_id=parent['alpha_id'])]

            controller.repair_executor = execute
            result = controller.continue_once('2026-10-11T01:01:00Z')
            self.assertEqual(result['current_stage'], 'scout_seed')
            receipt = json.loads((run / 'rounds/round-0001/stages/repair/repair_execution.json').read_text())
            self.assertEqual(receipt['status'], 'completed')
            self.assertTrue((run / 'research_record.json').exists())
            record = json.loads((run / 'research_record.json').read_text())
            self.assertEqual(record['backtest'][-1]['expression_hash'], 'child-hash')
            self.assertFalse((run / 'approved_candidates.jsonl').exists())

    def test_qualified_repair_still_reaches_protected_candidate_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, run = round_fixture(Path(tmp), 'repair')
            write_rows(run, [checked_alpha('qualified')])
            result = controller.continue_once('2026-10-11T01:01:00Z')
            self.assertEqual(result['current_stage'], 'candidate_gate')
            self.assertFalse((run / 'research_rounds.json').exists())
