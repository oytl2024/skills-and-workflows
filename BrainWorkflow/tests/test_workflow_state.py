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
    discover_active_workflow,
    load_active_run,
    load_run_state,
    transition_run_state,
    write_active_run,
    write_run_state,
)
from wqb.workflow_events import append_workflow_event


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

    def test_consistency_compares_approval_and_queue_to_candidate_gate_full_identity(self):
        gate = {
            "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
            "expression_hash": "h1", "source_run_id": "run1",
        }
        mutations = (
            ("candidate_id", "c2"),
            ("platform_alpha_id", "a2"),
            ("version", 2),
            ("expression_hash", "h2"),
            ("source_run_id", "run2"),
        )
        for field, value in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                persisted = dict(gate, **{field: value})
                (root / "candidate_gate.json").write_text(
                    json.dumps([gate]), encoding="utf-8"
                )
                (root / "approval.jsonl").write_text(
                    json.dumps(persisted) + "\n", encoding="utf-8"
                )
                (root / "approved_candidates.jsonl").write_text(
                    json.dumps(dict(persisted, status="queued")) + "\n", encoding="utf-8"
                )

                issues = diagnose_state_consistency(root)

                self.assertTrue(
                    any(issue.startswith("approval_candidate_gate_identity_mismatch:") for issue in issues)
                )
                self.assertTrue(
                    any(issue.startswith("candidate_queue_gate_identity_mismatch:") for issue in issues)
                )

    def test_consistency_reports_malformed_json_and_trailing_jsonl_without_raising(self):
        valid = {
            "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
            "expression_hash": "h1", "source_run_id": "run1",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "candidate_gate.json").write_text("{broken", encoding="utf-8")
            (root / "approval.jsonl").write_text(
                json.dumps(valid) + '\n{"candidate_id":', encoding="utf-8"
            )
            (root / "approved_candidates.jsonl").write_text(
                json.dumps(dict(valid, status="queued")) + '\n{"candidate_id":',
                encoding="utf-8",
            )
            (root / "research_record.json").write_text("{broken", encoding="utf-8")
            (root / "run_state.json").write_text("{broken", encoding="utf-8")

            issues = diagnose_state_consistency(root)

        self.assertIn("malformed_json:candidate_gate.json", issues)
        self.assertIn("malformed_jsonl:approval.jsonl:2", issues)
        self.assertIn("malformed_jsonl:approved_candidates.jsonl:2", issues)
        self.assertIn("malformed_json:research_record.json", issues)
        self.assertIn("malformed_json:run_state.json", issues)

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

    def test_discovery_diagnoses_non_object_active_pointer_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            root.mkdir()
            pointer_path = root / "active_run.json"
            pointer_path.write_text("[]", encoding="utf-8")
            before = pointer_path.read_bytes()

            discovery = discover_active_workflow(root)

            self.assertIsNone(discovery.state)
            self.assertIn("active_run_invalid", discovery.diagnostics)
            self.assertEqual(pointer_path.read_bytes(), before)

    def test_discovery_reports_missing_state_for_canonical_active_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            run_dir = root / "run1"
            run_dir.mkdir(parents=True)
            write_active_run(root, "run1", run_dir)
            before = (root / "active_run.json").read_bytes()

            discovery = discover_active_workflow(root)

            self.assertIsNone(discovery.state)
            self.assertEqual(discovery.run_dir, run_dir)
            self.assertEqual(discovery.run_id, "run1")
            self.assertEqual(discovery.diagnostics, ["run_state_missing"])
            self.assertEqual((root / "active_run.json").read_bytes(), before)

    def test_discovery_reports_multiple_nonterminal_runs_without_selecting_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            for run_id in ("run1", "run2"):
                run_dir = root / run_id
                run_dir.mkdir(parents=True)
                write_run_state(
                    run_dir / "run_state.json",
                    create_initial_state(
                        run_id, run_dir, "Power Pool", "2026-07-12T00:00:00Z"
                    ),
                )

            discovery = discover_active_workflow(root)

            self.assertIsNone(discovery.state)
            self.assertIsNone(discovery.run_dir)
            self.assertIn("multiple_active_runs", discovery.diagnostics)
            self.assertFalse((root / "active_run.json").exists())

    def test_discovery_reports_sibling_active_run_despite_valid_pointer_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            run_dirs = {}
            for run_id in ("run1", "run2"):
                run_dir = root / run_id
                run_dir.mkdir(parents=True)
                run_dirs[run_id] = run_dir
                write_run_state(
                    run_dir / "run_state.json",
                    create_initial_state(
                        run_id, run_dir, "Power Pool", "2026-07-12T00:00:00Z"
                    ),
                )
            write_active_run(root, "run1", run_dirs["run1"])
            pointer_before = (root / "active_run.json").read_bytes()

            discovery = discover_active_workflow(root)
            pointer_unchanged = (root / "active_run.json").read_bytes() == pointer_before

        self.assertIsNone(discovery.state)
        self.assertIsNone(discovery.run_dir)
        self.assertIn("multiple_active_runs", discovery.diagnostics)
        self.assertTrue(pointer_unchanged)

    def test_write_state_creates_checkpoint_and_discovery_recovers_damaged_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            run_dir = root / "run1"
            run_dir.mkdir(parents=True)
            state_path = run_dir / "run_state.json"
            state = create_initial_state(
                "run1", run_dir, "Power Pool", "2026-07-12T00:00:00Z"
            )
            write_run_state(state_path, state)
            checkpoint_path = run_dir / "run_state_checkpoint.json"
            checkpoint_state = load_run_state(checkpoint_path)
            state_path.write_text("{broken", encoding="utf-8")
            write_active_run(root, "run1", run_dir)

            discovery = discover_active_workflow(root)

        self.assertEqual(checkpoint_state, state)
        self.assertEqual(discovery.state, state)
        self.assertTrue(discovery.recovered)
        self.assertIn("run_state_recovered_from_checkpoint", discovery.diagnostics)

    def test_discovery_recovers_minimal_state_from_valid_events_when_state_and_checkpoint_are_damaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            run_dir = root / "run1"
            run_dir.mkdir(parents=True)
            (run_dir / "run_state.json").write_text("{broken", encoding="utf-8")
            (run_dir / "run_state_checkpoint.json").write_text("{broken", encoding="utf-8")
            append_workflow_event(
                run_dir,
                "workflow_created",
                {
                    "run_id": "run1",
                    "objective": "Power Pool",
                    "selected_option_id": "option-1",
                    "created_at": "2026-07-12T00:00:00Z",
                },
                "2026-07-12T00:00:00Z",
            )
            append_workflow_event(
                run_dir,
                "stage_started",
                {"stage": "schedule"},
                "2026-07-12T00:01:00Z",
            )
            write_active_run(root, "run1", run_dir)

            discovery = discover_active_workflow(root)

        self.assertIsNotNone(discovery.state)
        self.assertEqual(discovery.state.run_id, "run1")
        self.assertEqual(discovery.state.status, "created")
        self.assertEqual(discovery.state.current_stage, "objective_selected")
        self.assertEqual(discovery.state.stages["objective_selected"].status, "completed")
        self.assertTrue(discovery.recovered)
        self.assertIn("run_state_recovered_from_events", discovery.diagnostics)

    def test_discovery_rejects_checkpoint_with_mismatched_run_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            run_dir = root / "run1"
            run_dir.mkdir(parents=True)
            state_path = run_dir / "run_state.json"
            write_run_state(
                state_path,
                create_initial_state(
                    "run1", run_dir, "Power Pool", "2026-07-12T00:00:00Z"
                ),
            )
            checkpoint_path = run_dir / "run_state_checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["run_id"] = "other-run"
            checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
            state_path.write_text("{broken", encoding="utf-8")
            write_active_run(root, "run1", run_dir)

            discovery = discover_active_workflow(root)

        self.assertIsNone(discovery.state)
        self.assertFalse(discovery.recovered)
        self.assertIn("run_state_run_id_mismatch", discovery.diagnostics)

    def test_discovery_rejects_out_of_root_active_pointer_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            outside = Path(tmp) / "outside" / "run1"
            outside.mkdir(parents=True)
            root.mkdir()
            write_run_state(
                outside / "run_state.json",
                create_initial_state(
                    "run1", outside, "Power Pool", "2026-07-12T00:00:00Z"
                ),
            )
            write_active_run(root, "run1", outside)
            before = {
                "pointer": (root / "active_run.json").read_bytes(),
                "state": (outside / "run_state.json").read_bytes(),
            }

            discovery = discover_active_workflow(root)

            self.assertIsNone(discovery.state)
            self.assertIn("active_run_outside_run_root", discovery.diagnostics)
            self.assertEqual((root / "active_run.json").read_bytes(), before["pointer"])
            self.assertEqual((outside / "run_state.json").read_bytes(), before["state"])

    def test_discovery_rejects_pointer_and_state_directory_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            run_dir = root / "run1"
            run_dir.mkdir(parents=True)
            mismatched_dir = root / "run2"
            write_run_state(
                run_dir / "run_state.json",
                create_initial_state(
                    "run1", mismatched_dir, "Power Pool", "2026-07-12T00:00:00Z"
                ),
            )
            write_active_run(root, "run1", run_dir)
            before = {
                "pointer": (root / "active_run.json").read_bytes(),
                "state": (run_dir / "run_state.json").read_bytes(),
            }

            discovery = discover_active_workflow(root)

            self.assertIsNone(discovery.state)
            self.assertIn("run_state_run_dir_mismatch", discovery.diagnostics)
            self.assertEqual((root / "active_run.json").read_bytes(), before["pointer"])
            self.assertEqual((run_dir / "run_state.json").read_bytes(), before["state"])

    def test_scanned_discovery_rejects_out_of_root_state_run_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            run_dir = root / "run1"
            outside = Path(tmp) / "outside" / "run1"
            run_dir.mkdir(parents=True)
            write_run_state(
                run_dir / "run_state.json",
                create_initial_state(
                    "run1", outside, "Power Pool", "2026-07-12T00:00:00Z"
                ),
            )
            before = (run_dir / "run_state.json").read_bytes()

            discovery = discover_active_workflow(root)

            self.assertIsNone(discovery.state)
            self.assertIn("run_state_run_dir_mismatch", discovery.diagnostics)
            self.assertFalse((root / "active_run.json").exists())
            self.assertEqual((run_dir / "run_state.json").read_bytes(), before)

    def test_discovery_diagnoses_pointer_run_id_directory_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            run_dir = root / "run1"
            run_dir.mkdir(parents=True)
            write_run_state(
                run_dir / "run_state.json",
                create_initial_state(
                    "run1", run_dir, "Power Pool", "2026-07-12T00:00:00Z"
                ),
            )
            write_active_run(root, "run2", run_dir)
            before = (root / "active_run.json").read_bytes()

            discovery = discover_active_workflow(root)

            self.assertEqual(discovery.state.run_id, "run1")
            self.assertTrue(discovery.recovered)
            self.assertIn("active_run_directory_mismatch", discovery.diagnostics)
            self.assertEqual((root / "active_run.json").read_bytes(), before)

    def test_scanned_discovery_rejects_state_run_id_directory_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            run_dir = root / "run1"
            run_dir.mkdir(parents=True)
            write_run_state(
                run_dir / "run_state.json",
                create_initial_state(
                    "run2", run_dir, "Power Pool", "2026-07-12T00:00:00Z"
                ),
            )
            before = (run_dir / "run_state.json").read_bytes()

            discovery = discover_active_workflow(root)

            self.assertIsNone(discovery.state)
            self.assertIn("run_state_run_id_mismatch", discovery.diagnostics)
            self.assertFalse((root / "active_run.json").exists())
            self.assertEqual((run_dir / "run_state.json").read_bytes(), before)

    def test_consistency_binds_research_and_candidate_artifacts_to_state_run(self):
        candidate = {
            "candidate_id": "c1",
            "platform_alpha_id": "a1",
            "version": 1,
            "expression_hash": "h1",
            "source_run_id": "other-run",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = create_initial_state(
                "run1", root, "Power Pool", "2026-07-12T00:00:00Z"
            )
            write_run_state(root / "run_state.json", state)
            (root / "research_record.json").write_text(
                json.dumps({"run_id": "other-run"}), encoding="utf-8"
            )
            (root / "candidate_gate.json").write_text(
                json.dumps([candidate]), encoding="utf-8"
            )
            (root / "approval.jsonl").write_text(
                json.dumps(candidate) + "\n", encoding="utf-8"
            )
            (root / "approved_candidates.jsonl").write_text(
                json.dumps(dict(candidate, status="queued")) + "\n", encoding="utf-8"
            )

            issues = diagnose_state_consistency(root)

        self.assertIn("research_record_run_id_mismatch:other-run", issues)
        for artifact in (
            "candidate_gate.json",
            "approval.jsonl",
            "approved_candidates.jsonl",
        ):
            self.assertIn(
                f"candidate_source_run_id_mismatch:{artifact}:c1:other-run", issues
            )

    def test_consistency_requires_research_record_for_completed_with_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = create_initial_state(
                "run1", root, "Power Pool", "2026-07-12T00:00:00Z"
            )
            write_run_state(
                root / "run_state.json",
                replace(state, status="completed_with_warnings"),
            )

            issues = diagnose_state_consistency(root)

        self.assertIn("completed_without_research_record", issues)
