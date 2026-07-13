from dataclasses import replace
import json
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_state import (
    WorkflowStateError,
    WorkflowStageState,
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

    def test_load_rejects_semantically_invalid_state_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_state.json"
            state = create_initial_state("run1", tmp, "Power Pool", "2026-07-12T00:00:00Z")
            write_run_state(path, state)
            valid = json.loads(path.read_text(encoding="utf-8"))
            corruptions = (
                ("run status", lambda row: row.update(status="unknown")),
                ("current stage", lambda row: row.update(current_stage="unknown")),
                ("last stage", lambda row: row.update(last_completed_stage="unknown")),
                ("stage name", lambda row: row["stages"].update(unknown={"name": "unknown"})),
                ("stage row name", lambda row: row["stages"]["schedule"].update(name="triage")),
                ("stage status", lambda row: row["stages"]["schedule"].update(status="unknown")),
            )

            for label, mutate in corruptions:
                with self.subTest(label=label):
                    row = json.loads(json.dumps(valid))
                    mutate(row)
                    path.write_text(json.dumps(row), encoding="utf-8")
                    with self.assertRaises(WorkflowStateError):
                        load_run_state(path)

    def test_consistency_detects_exact_approval_queue_identity_mismatch(self):
        approval = {
            "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
            "expression_hash": "h1", "source_run_id": "run1",
        }
        queued = dict(approval, expression_hash="h2", status="queued")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "approval.jsonl").write_text(json.dumps(approval) + "\n", encoding="utf-8")
            (root / "approved_candidates.jsonl").write_text(json.dumps(queued) + "\n", encoding="utf-8")
            issues = diagnose_state_consistency(root)

        self.assertIn("candidate_queue_approval_identity_mismatch:c1:1:h2", issues)

    def test_consistency_requires_schedule_evidence_and_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = create_initial_state("run1", root, "Power Pool", "2026-07-12T00:00:00Z")
            stages = dict(state.stages)
            stages["schedule"] = WorkflowStageState(name="schedule", status="completed")
            write_run_state(root / "run_state.json", replace(state, stages=stages))
            empty_issues = diagnose_state_consistency(root)

            stages["schedule"] = WorkflowStageState(
                name="schedule", status="completed", evidence_paths=["stages/schedule/missing.json"]
            )
            write_run_state(root / "run_state.json", replace(state, stages=stages))
            missing_issues = diagnose_state_consistency(root)

        self.assertIn("completed_stage_without_evidence:schedule", empty_issues)
        self.assertIn(
            "missing_stage_evidence:schedule:stages/schedule/missing.json", missing_issues
        )
