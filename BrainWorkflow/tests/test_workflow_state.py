import tempfile
import unittest
from pathlib import Path

from wqb.workflow_state import (
    WorkflowStateError,
    create_initial_state,
    diagnose_state_consistency,
    load_active_run,
    load_run_state,
    transition_run_state,
    write_active_run,
    write_run_state,
)


class WorkflowStateTests(unittest.TestCase):
    def test_initial_state_contains_all_stages_and_next_action(self):
        state = create_initial_state("run1", "runs/run1", "Power Pool", "2026-07-12T00:00:00Z")

        self.assertEqual(state.run_id, "run1")
        self.assertEqual(state.status, "created")
        self.assertEqual(state.current_stage, "objective_selected")
        self.assertEqual(state.next_action, "workflow-start")
        self.assertEqual(state.stages["schedule"].status, "not_started")

    def test_transition_rejects_illegal_jump_from_created_to_completed(self):
        state = create_initial_state("run1", "runs/run1", "Power Pool", "2026-07-12T00:00:00Z")

        with self.assertRaisesRegex(WorkflowStateError, "illegal run status transition"):
            transition_run_state(state, "completed")

    def test_state_write_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_state.json"
            state = create_initial_state("run1", Path(tmp), "Power Pool", "2026-07-12T00:00:00Z")
            write_run_state(path, state)
            loaded = load_run_state(path)

        self.assertEqual(loaded.run_id, "run1")
        self.assertEqual(loaded.objective, "Power Pool")

    def test_active_run_pointer_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_active_run(tmp, "run1", Path(tmp) / "run1")
            active = load_active_run(tmp)

        self.assertEqual(active["run_id"], "run1")

    def test_consistency_detects_candidate_queue_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "approved_candidates.jsonl").write_text('{"candidate_id":"c1"}\n', encoding="utf-8")
            issues = diagnose_state_consistency(root)

        self.assertIn("candidate_queue_without_approval", issues)
