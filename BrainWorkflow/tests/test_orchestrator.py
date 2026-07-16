import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from wqb.candidate_queue import (
    approve_candidate,
    load_approved_queue,
    load_approvals,
    queue_approved_candidate,
)
from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
from wqb.research_record import (
    empty_research_record,
    load_research_record,
    record_approval,
    record_candidate_gate,
    record_queue_update,
    write_research_record,
)
from wqb.workflow_events import append_workflow_event, read_workflow_events
from wqb.workflow_state import (
    WorkflowStageState,
    create_initial_state,
    diagnose_state_consistency,
    load_active_run,
    load_run_state,
    transition_run_state,
    write_active_run,
    write_run_state,
)


class WorkflowOrchestratorTests(unittest.TestCase):
    def paths(self, root: Path) -> OrchestratorPaths:
        return OrchestratorPaths(
            project_root=root,
            workflow_root=root / "BrainWorkflow",
            knowledge_root=root / "knowledge",
            run_root=root / "runs",
        )

    def advance_to_candidate_gate(self, started: dict[str, object]) -> None:
        """Input: start summary. Output: none. Put test state at the legal candidate gate boundary."""
        run_dir = Path(str(started["run_dir"]))
        state_path = run_dir / "run_state.json"
        state = load_run_state(state_path)
        if state.status == "created":
            state = transition_run_state(state, "running", "")
        stages = dict(state.stages)
        for stage_name in (
            "schedule", "scout_seed", "batch_generation", "backtest", "triage", "repair"
        ):
            if stages[stage_name].status in {"completed", "skipped"}:
                continue
            evidence = run_dir / "test_evidence" / f"{stage_name}.json"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text("{}", encoding="utf-8")
            stages[stage_name] = WorkflowStageState(
                name=stage_name,
                status="completed",
                started_at="2026-07-12T00:01:00Z",
                completed_at="2026-07-12T00:02:00Z",
                evidence_paths=[str(evidence)],
            )
        state = replace(
            state,
            stages=stages,
            current_stage="candidate_gate",
            last_completed_stage="repair",
            updated_at="2026-07-12T00:02:00Z",
        )
        write_run_state(state_path, state)
        self.persist_hard_pass_artifacts(run_dir)

    def persist_hard_pass_artifacts(self, run_dir: Path) -> None:
        """Input: run directory Path. Output: none. Write durable hard-pass evidence for test candidates."""
        candidates = (
            ("a1", "h1"),
            ("a1", "h2"),
            ("a2", "h2"),
        )
        with (run_dir / "candidates.csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=("alpha_id", "expression_hash"))
            writer.writeheader()
            for alpha_id, expression_hash in candidates:
                writer.writerow({"alpha_id": alpha_id, "expression_hash": expression_hash})
        (run_dir / "all_alphas.jsonl").write_text(
            "".join(
                json.dumps(
                    {
                        "alpha_id": alpha_id,
                        "expression_hash": expression_hash,
                        "hard_pass": True,
                        "failed": [],
                        "pending": [],
                    }
                )
                + "\n"
                for alpha_id, expression_hash in candidates
            ),
            encoding="utf-8",
        )

    def create_approved_candidate_run(
        self, root: Path
    ) -> tuple[WorkflowOrchestrator, dict[str, object]]:
        """Input: temp root Path. Output: orchestrator and run summary. Create one queued candidate."""
        orchestrator = WorkflowOrchestrator(self.paths(root))
        started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
        candidate = {
            "candidate_id": "c1",
            "platform_alpha_id": "a1",
            "version": 1,
            "expression_hash": "h1",
            "source_run_id": started["run_id"],
            "hard_pass": True,
        }
        self.advance_to_candidate_gate(started)
        orchestrator.request_candidate_approval([candidate], "2026-07-12T00:01:00Z")
        orchestrator.approve_candidates(["c1"], "2026-07-12T00:02:00Z", "user")
        return orchestrator, started

    def candidate_artifact_bytes(self, run_dir: Path) -> dict[str, bytes | None]:
        """Input: run directory Path. Output: optional artifact bytes by name. Snapshot mutation targets."""
        names = (
            "candidate_gate.json",
            "approval.jsonl",
            "approved_candidates.jsonl",
            "run_state.json",
            "workflow_events.jsonl",
            "research_record.json",
        )
        return {
            name: (run_dir / name).read_bytes() if (run_dir / name).exists() else None
            for name in names
        }

    def test_start_creates_manifest_state_events_and_active_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            result = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            state = load_run_state(Path(result["run_dir"]) / "run_state.json")
            active = load_active_run(root / "runs")

        self.assertEqual(result["status"], "created")
        self.assertEqual(state.objective, "Power Pool")
        self.assertEqual(active["run_id"], result["run_id"])

    def test_selected_scope_is_persisted_and_drives_schedule_for_generic_option_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            decisions = knowledge / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(json.dumps({
                "option_id": "option-1",
                "title": "Build Genius and Osmosis alpha pool",
                "primary_incentive": "cash",
                "candidate_scope": "Generate a later concrete plan across multiple region-delay scopes after user selection.",
            }) + "\n", encoding="utf-8")
            ledger = knowledge / "wiki" / "20_semantics" / "data_ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(json.dumps({
                "dataset_id": "fundamental3", "dataset_name": "Fundamentals", "field_id": "cash_field", "field_type": "MATRIX",
                "region": "USA", "delay": 1, "universe": "TOP3000", "semantic_tags": ["cash"], "coverage": 1.0,
                "alpha_count": 0, "user_count": 0, "simulation_usage_count": 0, "submitted_usage_count": 0,
                "last_used_at": "", "best_result_label": "unexplored", "correlation_risk": "low", "source_paths": [],
                "available_scopes": [
                    {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                    {"instrument_type": "EQUITY", "region": "EUR", "delay": 0, "universe": "TOP500"},
                ],
            }) + "\n", encoding="utf-8")
            templates = knowledge / "wiki" / "30_templates" / "template_library.jsonl"
            templates.parent.mkdir(parents=True)
            templates.write_text(json.dumps({
                "template_id": "matrix_ts_zscore_rank", "status": "discovery_ready", "required_field_types": ["MATRIX"],
                "compatible_regions": ["USA"], "compatible_delays": [1], "compatible_universes": ["TOP3000"],
            }) + "\n", encoding="utf-8")
            orchestrator = WorkflowOrchestrator(self.paths(root))

            started = orchestrator.start(
                "Build Genius and Osmosis alpha pool",
                "option-1",
                "2026-07-12T00:00:00Z",
                selected_scope={"region": "USA", "delay": 1, "universe": "TOP3000"},
            )
            run_dir = Path(str(started["run_dir"]))
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            created_event = read_workflow_events(run_dir)[0]
            orchestrator.continue_once("2026-07-12T00:01:00Z")
            orchestrator.continue_once("2026-07-12T00:02:00Z")
            schedule = json.loads((run_dir / "stages" / "schedule" / "research_schedule.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["selected_scope"], {"region": "USA", "delay": 1, "universe": "TOP3000"})
        self.assertEqual(created_event.payload["selected_scope"], manifest["selected_scope"])
        self.assertEqual((schedule["region"], schedule["delay"], schedule["universe"]), ("USA", 1, "TOP3000"))
        self.assertEqual([row["field_id"] for row in schedule["selected_data"]], ["cash_field"])

    def test_start_keeps_user_controlled_timestamp_run_directory_inside_run_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))

            result = orchestrator.start("Power Pool", "option-1", "../escaped")

            self.assertEqual(Path(str(result["run_dir"])).resolve().parent, (root / "runs").resolve())
            self.assertFalse(any(path.is_dir() for path in root.iterdir() if path.name.startswith("escaped-")))

    def test_start_respects_existing_run_root_mutation_lock_without_creating_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            runs.mkdir()
            (runs / "workflow_mutation.lock").write_text(
                json.dumps({"token": "other", "created_at": "9999999999"}),
                encoding="utf-8",
            )
            orchestrator = WorkflowOrchestrator(self.paths(root))

            with patch("wqb.orchestrator.WORKFLOW_MUTATION_LOCK_TIMEOUT_SECONDS", 0.01, create=True), patch(
                "wqb.orchestrator.WORKFLOW_MUTATION_LOCK_SLEEP_SECONDS", 0.001, create=True
            ):
                with self.assertRaisesRegex(ValueError, "workflow mutation lock is busy"):
                    orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")

            run_dirs = [path for path in runs.iterdir() if path.is_dir()]

        self.assertEqual(run_dirs, [])

    def test_status_respects_run_root_mutation_lock_without_repairing_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            runs = root / "runs"
            (runs / "active_run.json").unlink()
            (runs / "workflow_mutation.lock").write_text(
                json.dumps({"token": "other", "created_at": 9999999999}),
                encoding="utf-8",
            )

            with patch("wqb.orchestrator.WORKFLOW_MUTATION_LOCK_TIMEOUT_SECONDS", 0.01, create=True), patch(
                "wqb.orchestrator.WORKFLOW_MUTATION_LOCK_SLEEP_SECONDS", 0.001, create=True
            ):
                with self.assertRaisesRegex(ValueError, "workflow mutation lock is busy"):
                    orchestrator.status()

            active_exists = (runs / "active_run.json").exists()
            run_state_exists = (Path(str(started["run_dir"])) / "run_state.json").exists()

        self.assertFalse(active_exists)
        self.assertTrue(run_state_exists)

    def test_status_pauses_running_workflow_on_malformed_workflow_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            run_dir = Path(str(started["run_dir"]))
            state_path = run_dir / "run_state.json"
            state = transition_run_state(load_run_state(state_path), "running", "")
            write_run_state(state_path, replace(state, current_stage="schedule"))
            with (run_dir / "workflow_events.jsonl").open("ab") as file:
                file.write(b"{broken\n")

            status = orchestrator.status()
            persisted = load_run_state(state_path)

        self.assertEqual(status["status"], "paused")
        self.assertIn("malformed_workflow_events", status["diagnostics"])
        self.assertEqual(persisted.status, "paused")
        self.assertIn("malformed_workflow_events", persisted.pause_reason)

    def test_continue_once_respects_run_root_mutation_lock_without_advancing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            runs = root / "runs"
            (runs / "workflow_mutation.lock").write_text(
                json.dumps({"token": "other", "created_at": 9999999999}),
                encoding="utf-8",
            )
            state_path = Path(str(started["run_dir"])) / "run_state.json"
            before = state_path.read_bytes()

            with patch("wqb.orchestrator.WORKFLOW_MUTATION_LOCK_TIMEOUT_SECONDS", 0.01, create=True), patch(
                "wqb.orchestrator.WORKFLOW_MUTATION_LOCK_SLEEP_SECONDS", 0.001, create=True
            ):
                with self.assertRaisesRegex(ValueError, "workflow mutation lock is busy"):
                    orchestrator.continue_once("2026-07-12T00:01:00Z")

            after = state_path.read_bytes()

        self.assertEqual(after, before)

    def test_candidate_status_respects_run_root_mutation_lock_without_rewriting_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            orchestrator.sync_research_record("2026-07-12T00:03:00Z")
            run_dir = Path(str(started["run_dir"]))
            queue_path = run_dir / "approved_candidates.jsonl"
            before = queue_path.read_bytes()
            (root / "runs" / "workflow_mutation.lock").write_text(
                json.dumps({"token": "other", "created_at": 9999999999}),
                encoding="utf-8",
            )

            with patch("wqb.orchestrator.WORKFLOW_MUTATION_LOCK_TIMEOUT_SECONDS", 0.01, create=True), patch(
                "wqb.orchestrator.WORKFLOW_MUTATION_LOCK_SLEEP_SECONDS", 0.001, create=True
            ):
                with self.assertRaisesRegex(ValueError, "workflow mutation lock is busy"):
                    orchestrator.update_candidate_status(
                        "c1",
                        1,
                        "h1",
                        "manually_submitted",
                        "2026-07-12T00:04:00Z",
                        source_run_id=str(started["run_id"]),
                    )

            after = queue_path.read_bytes()

        self.assertEqual(after, before)

    def test_invalidate_candidate_approval_marks_superseded_identity_and_blocks_status_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            run_dir = Path(str(started["run_dir"]))

            invalidated = orchestrator.invalidate_candidate_approval(
                "c1",
                1,
                "h1",
                "candidate expression revised",
                "2026-07-12T00:03:00Z",
                source_run_id=str(started["run_id"]),
            )
            rows = load_approved_queue(run_dir)
            orchestrator.sync_research_record("2026-07-12T00:03:30Z")

            with self.assertRaisesRegex(ValueError, "invalidated"):
                orchestrator.update_candidate_status(
                    "c1",
                    1,
                    "h1",
                    "manually_submitted",
                    "2026-07-12T00:04:00Z",
                    source_run_id=str(started["run_id"]),
                )

            events = read_workflow_events(run_dir)
            record = load_research_record(run_dir / "research_record.json")

        self.assertEqual(invalidated["status"], "invalidated")
        self.assertEqual(rows[0]["status"], "invalidated")
        self.assertEqual(rows[0]["invalidation_reason"], "candidate expression revised")
        self.assertIn("candidate_approval_invalidated", [event.event_type for event in events])
        self.assertEqual(record.approved_queue[-1]["status"], "invalidated")

    def test_start_rejects_malformed_active_run_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            (root / "runs").mkdir()
            (root / "runs" / "active_run.json").write_text("{not-json", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "active workflow"):
                orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")

            durable_entries = [
                path for path in (root / "runs").iterdir() if not path.name.endswith(".guard")
            ]
            self.assertEqual(durable_entries, [root / "runs" / "active_run.json"])

    def test_start_rejects_active_run_state_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            run_dir = Path(str(started["run_dir"]))
            state_path = run_dir / "run_state.json"
            write_run_state(state_path, replace(load_run_state(state_path), run_id="other-run"))

            with self.assertRaisesRegex(ValueError, "active workflow"):
                orchestrator.start("Quality Pool", "option-2", "2026-07-12T00:01:00Z")

            self.assertEqual([path for path in (root / "runs").iterdir() if path.is_dir()], [run_dir])

    def test_missing_canonical_active_state_stays_damaged_and_blocks_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            run_dir = runs / "run1"
            run_dir.mkdir(parents=True)
            (runs / "active_run.json").write_text(
                json.dumps({"run_id": "run1", "run_dir": str(run_dir)}), encoding="utf-8"
            )
            orchestrator = WorkflowOrchestrator(self.paths(root))

            status = orchestrator.status()
            with self.assertRaisesRegex(ValueError, "active workflow"):
                orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")

            self.assertTrue(status["active"])
            self.assertEqual(status["status"], "damaged")
            self.assertIn("run_state_missing", status["diagnostics"])
            self.assertTrue((runs / "active_run.json").exists())

    def test_contradictory_terminal_completed_state_stays_damaged_and_keeps_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            run_dir = Path(str(started["run_dir"]))
            state_path = run_dir / "run_state.json"
            state = load_run_state(state_path)
            write_research_record(
                run_dir / "research_record.json",
                empty_research_record(str(started["run_id"]), "Power Pool"),
            )
            write_run_state(
                state_path,
                replace(
                    state,
                    status="completed",
                    current_stage="complete",
                    last_completed_stage="research_record_sync",
                    research_record_synced=True,
                ),
            )

            status = orchestrator.status()
            active = load_active_run(root / "runs")

        self.assertEqual(status["status"], "damaged")
        self.assertIn("terminal_state_incomplete_stages", status["diagnostics"])
        self.assertEqual(active["run_id"], started["run_id"])

    def test_missing_pointer_contradictory_terminal_run_stays_damaged_and_blocks_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            run_dir = Path(str(started["run_dir"]))
            state_path = run_dir / "run_state.json"
            state = load_run_state(state_path)
            write_research_record(
                run_dir / "research_record.json",
                empty_research_record(str(started["run_id"]), "Power Pool"),
            )
            write_run_state(
                state_path,
                replace(
                    state,
                    status="completed",
                    current_stage="complete",
                    last_completed_stage="research_record_sync",
                    research_record_synced=True,
                ),
            )
            (root / "runs" / "active_run.json").unlink()

            status = orchestrator.status()
            with self.assertRaisesRegex(ValueError, "active workflow"):
                orchestrator.start("Quality Pool", "option-2", "2026-07-12T00:01:00Z")

        self.assertEqual(status["status"], "damaged")
        self.assertIn("terminal_state_inconsistent", status["diagnostics"])
        self.assertIn("terminal_state_incomplete_stages", status["diagnostics"])

    def test_multiple_active_runs_remain_ambiguous_without_creating_a_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            for run_id in ("run1", "run2"):
                run_dir = runs / run_id
                run_dir.mkdir(parents=True)
                write_run_state(
                    run_dir / "run_state.json",
                    create_initial_state(
                        run_id, run_dir, "Power Pool", "2026-07-12T00:00:00Z"
                    ),
                )
            orchestrator = WorkflowOrchestrator(self.paths(root))

            status = orchestrator.status()
            with self.assertRaisesRegex(ValueError, "active workflow"):
                orchestrator.start("Other", "option-2", "2026-07-12T00:01:00Z")

            self.assertEqual(status["status"], "damaged")
            self.assertIn("multiple_active_runs", status["diagnostics"])
            self.assertFalse((runs / "active_run.json").exists())

    def test_abort_clears_canonical_pointer_to_terminal_state_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            run_dir = Path(str(started["run_dir"]))
            state_path = run_dir / "run_state.json"
            terminal_state = transition_run_state(load_run_state(state_path), "aborted", "interrupted")
            write_run_state(state_path, terminal_state)

            result = orchestrator.abort("retry abort", "2026-07-12T00:01:00Z")
            active = load_active_run(root / "runs")
            persisted = load_run_state(state_path)

        self.assertEqual(result, {"active": False, "status": "none"})
        self.assertEqual(active, {})
        self.assertEqual(persisted, terminal_state)

    def test_status_reports_next_action_without_chat_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            status = orchestrator.status()

        self.assertEqual(status["next_action"], "workflow-continue")
        self.assertEqual(status["current_stage"], "objective_selected")

    def test_status_recovers_durable_run_when_active_pointer_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            (root / "runs" / "active_run.json").unlink()

            status = orchestrator.status()
            active = load_active_run(root / "runs")

        self.assertTrue(status["active"])
        self.assertEqual(status["run_id"], started["run_id"])
        self.assertEqual(active["run_id"], started["run_id"])

    def test_status_recovers_durable_run_when_active_pointer_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            (root / "runs" / "active_run.json").write_text(
                '{"run_id": "missing", "run_dir": "missing"}', encoding="utf-8"
            )

            status = orchestrator.status()
            active = load_active_run(root / "runs")

        self.assertTrue(status["active"])
        self.assertEqual(status["run_id"], started["run_id"])
        self.assertEqual(active["run_id"], started["run_id"])

    def test_abort_releases_active_run_and_preserves_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            result = orchestrator.abort("user changed objective", "2026-07-12T00:05:00Z")
            state = load_run_state(Path(started["run_dir"]) / "run_state.json")
            active = load_active_run(root / "runs")

        self.assertEqual(result["status"], "aborted")
        self.assertEqual(state.status, "aborted")
        self.assertEqual(active, {})

    def test_abort_best_effort_syncs_available_research_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            run_dir = Path(started["run_dir"])
            write_research_record(
                run_dir / "research_record.json",
                empty_research_record(started["run_id"], "Power Pool"),
            )

            result = orchestrator.abort("user stop", "2026-07-12T00:05:00Z")
            state = load_run_state(run_dir / "run_state.json")
            events = read_workflow_events(run_dir)
            raw_path = (
                root / "knowledge" / "raw" / "research" / "runs"
                / started["run_id"] / "research_record.md"
            )
            raw_exists = raw_path.exists()

        self.assertEqual(result["status"], "aborted")
        self.assertTrue(state.research_record_synced)
        self.assertTrue(raw_exists)
        self.assertIn("abort_research_record_synced", [event.event_type for event in events])

    def test_abort_sync_failure_warns_but_still_aborts_and_clears_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            run_dir = Path(started["run_dir"])

            with patch(
                "wqb.orchestrator.sync_research_record_to_raw",
                side_effect=OSError("raw storage unavailable"),
            ):
                result = orchestrator.abort("user stop", "2026-07-12T00:05:00Z")

            state = load_run_state(run_dir / "run_state.json")
            events = read_workflow_events(run_dir)
            active = load_active_run(root / "runs")

        self.assertEqual(result["status"], "aborted")
        self.assertEqual(state.status, "aborted")
        self.assertEqual(active, {})
        self.assertTrue(result["warnings"])
        self.assertIn(
            "abort_research_record_sync_warning", [event.event_type for event in events]
        )

    def test_failed_run_remains_discoverable_and_abortable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            orchestrator.continue_once("2026-07-12T00:01:00Z")
            state_path = Path(started["run_dir"]) / "run_state.json"
            failed = transition_run_state(load_run_state(state_path), "failed", "schedule failed")
            write_run_state(state_path, failed)

            status = orchestrator.status()
            aborted = orchestrator.abort("user abort", "2026-07-12T00:03:00Z")
            final_state = load_run_state(state_path)
            active = load_active_run(root / "runs")

        self.assertEqual(status["status"], "failed")
        self.assertEqual(aborted["status"], "aborted")
        self.assertEqual(final_state.updated_at, "2026-07-12T00:03:00Z")
        self.assertEqual(active, {})

    def test_continue_once_advances_created_run_to_schedule_then_scout_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                '{"option_id":"option-1","title":"Power Pool","scope":"USA D1","score":{"total":10}}\n',
                encoding="utf-8",
            )
            orchestrator = WorkflowOrchestrator(self.paths(root))
            orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            first = orchestrator.continue_once("2026-07-12T00:01:00Z")
            second = orchestrator.continue_once("2026-07-12T00:02:00Z")

        self.assertEqual(first["current_stage"], "schedule")
        self.assertEqual(second["current_stage"], "scout_seed")

    def test_continue_once_advances_post_schedule_stages_from_local_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                '{"option_id":"option-1","title":"Power Pool","scope":"USA D1","score":{"total":10}}\n',
                encoding="utf-8",
            )
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            orchestrator.continue_once("2026-07-12T00:01:00Z")
            orchestrator.continue_once("2026-07-12T00:02:00Z")
            self.persist_hard_pass_artifacts(Path(str(started["run_dir"])))

            summaries = [
                orchestrator.continue_once(f"2026-07-12T00:0{minute}:00Z")
                for minute in range(3, 8)
            ]
            state = load_run_state(Path(str(started["run_dir"])) / "run_state.json")
            events = read_workflow_events(Path(str(started["run_dir"])))

        self.assertEqual(summaries[-1]["current_stage"], "candidate_gate")
        self.assertTrue(all(summary["current_stage"] != "scout_seed" for summary in summaries[1:]))
        for stage_name in ("scout_seed", "batch_generation", "backtest", "triage", "repair"):
            self.assertEqual(state.stages[stage_name].status, "completed")
            self.assertTrue(state.stages[stage_name].evidence_paths)
        self.assertGreaterEqual(
            [event.event_type for event in events].count("stage_completed"), 6
        )

    def test_continue_once_pauses_candidate_gate_with_durable_approval_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            self.advance_to_candidate_gate(started)
            run_dir = Path(str(started["run_dir"]))

            summary = orchestrator.continue_once("2026-07-12T00:03:00Z")
            state = load_run_state(run_dir / "run_state.json")
            events = read_workflow_events(run_dir)
            handoff_path = run_dir / "stages" / "candidate_gate" / "candidate_approval_request.json"
            handoff_exists = handoff_path.exists()

        self.assertEqual(summary["status"], "paused")
        self.assertEqual(summary["next_action"], "workflow-request-candidate-approval")
        self.assertEqual(state.stages["candidate_gate"].status, "paused")
        self.assertIn("candidate approval request required", state.stages["candidate_gate"].blocker)
        self.assertTrue(handoff_exists)
        self.assertIn("candidate_approval_request_required", [event.event_type for event in events])

    def test_status_and_continue_leave_progress_events_without_stale_state_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            run_dir = runs / "run1"
            run_dir.mkdir(parents=True)
            state_path = run_dir / "run_state.json"
            checkpoint_path = run_dir / "run_state_checkpoint.json"
            state_path.write_text("{broken", encoding="utf-8")
            checkpoint_path.write_text("{broken", encoding="utf-8")
            append_workflow_event(
                run_dir, "workflow_created",
                {"run_id": "run1", "objective": "Power Pool", "created_at": "2026-07-12T00:00:00Z"},
                "2026-07-12T00:00:00Z",
            )
            append_workflow_event(
                run_dir, "stage_completed", {"stage": "schedule"}, "2026-07-12T00:01:00Z"
            )
            write_active_run(runs, "run1", run_dir)
            before = state_path.read_bytes()
            orchestrator = WorkflowOrchestrator(self.paths(root))

            status = orchestrator.status()
            continued = orchestrator.continue_once("2026-07-12T00:02:00Z")
            after = state_path.read_bytes()

        self.assertEqual(after, before)
        for summary in (status, continued):
            self.assertEqual(summary["status"], "damaged")
            self.assertIn("run_state_invalid_with_events", summary["diagnostics"])

    def test_continue_once_completes_research_record_sync_and_releases_active_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")
            orchestrator.approve_candidates(["c1"], "2026-07-12T00:04:00Z", "user")

            completed = orchestrator.continue_once("2026-07-12T00:05:00Z")
            run_dir = Path(started["run_dir"])
            state = load_run_state(run_dir / "run_state.json")
            events = read_workflow_events(run_dir)
            active = load_active_run(root / "runs")

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["current_stage"], "complete")
        self.assertEqual(completed["next_action"], "")
        self.assertEqual(state.status, "completed")
        self.assertTrue(state.research_record_synced)
        self.assertEqual(active, {})
        self.assertEqual(events[-1].event_type, "workflow_completed")

    def test_candidate_gate_approval_persists_exact_subset_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            first_candidate = {
                "candidate_id": "c1",
                "platform_alpha_id": "a1",
                "version": 1,
                "expression_hash": "h1",
                "source_run_id": started["run_id"],
                "hard_pass": True,
            }
            second_candidate = {
                "candidate_id": "c2",
                "platform_alpha_id": "a2",
                "version": 1,
                "expression_hash": "h2",
                "source_run_id": started["run_id"],
                "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            gate = orchestrator.request_candidate_approval(
                [first_candidate, second_candidate], "2026-07-12T00:10:00Z"
            )
            approved = orchestrator.approve_candidates(["c1"], "2026-07-12T00:11:00Z", "user")
            with self.assertRaisesRegex(ValueError, "user approval stage"):
                orchestrator.approve_candidates(["c1"], "2026-07-12T00:12:00Z", "user")
            run_dir = Path(started["run_dir"])
            state = load_run_state(run_dir / "run_state.json")
            record = load_research_record(run_dir / "research_record.json")
            candidates = json.loads((run_dir / "candidate_gate.json").read_text(encoding="utf-8"))
            approvals = load_approvals(run_dir)
            queue = load_approved_queue(run_dir)
            events = read_workflow_events(run_dir)

        self.assertEqual(gate["status"], "waiting_for_user")
        self.assertEqual(approved["queued_count"], 1)
        self.assertEqual(state.status, "running")
        self.assertEqual([row["candidate_id"] for row in candidates], ["c1", "c2"])
        self.assertEqual([row["candidate_id"] for row in approvals], ["c1"])
        self.assertEqual([row["candidate_id"] for row in queue], ["c1"])
        self.assertEqual([row["candidate_id"] for row in record.candidate_gate], ["c1", "c2"])
        self.assertEqual([row["candidate_id"] for row in record.approvals], ["c1"])
        self.assertEqual([row["candidate_id"] for row in record.queue_updates], ["c1"])
        self.assertEqual(
            [event.event_type for event in events].count("candidates_approved"), 1
        )

    def test_candidate_gate_rejects_duplicate_candidate_ids_before_writing_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            base = {
                "candidate_id": "c1", "platform_alpha_id": "a1",
                "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            run_dir = Path(str(started["run_dir"]))

            with self.assertRaisesRegex(ValueError, "duplicate candidate ID"):
                orchestrator.request_candidate_approval(
                    [dict(base, version=1, expression_hash="h1"), dict(base, version=2, expression_hash="h2")],
                    "2026-07-12T00:10:00Z",
                )

            gate_exists = (run_dir / "candidate_gate.json").exists()
            record_path = run_dir / "research_record.json"
            gate_entries = [] if not record_path.exists() else load_research_record(record_path).candidate_gate

        self.assertFalse(gate_exists)
        self.assertEqual(gate_entries, [])

    def test_candidate_approval_revalidates_persisted_gate_rows(self):
        mutations = (
            ("hard pass", lambda candidate: candidate.update(hard_pass=False), "hard-pass"),
            ("source run", lambda candidate: candidate.update(source_run_id="other"), "source_run_id"),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                orchestrator = WorkflowOrchestrator(self.paths(root))
                started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
                candidate = {
                    "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                    "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
                }
                self.advance_to_candidate_gate(started)
                orchestrator.request_candidate_approval([candidate], "2026-07-12T00:10:00Z")
                gate_path = Path(started["run_dir"]) / "candidate_gate.json"
                persisted = json.loads(gate_path.read_text(encoding="utf-8"))
                mutate(persisted[0])
                gate_path.write_text(json.dumps(persisted), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, message):
                    orchestrator.approve_candidates(["c1"], "2026-07-12T00:11:00Z", "user")

    def test_interrupted_approval_retry_does_not_duplicate_artifacts_or_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval([candidate], "2026-07-12T00:10:00Z")
            run_dir = Path(started["run_dir"])
            approval = approve_candidate(run_dir, candidate, "2026-07-12T00:11:00Z", "user")
            queued = queue_approved_candidate(run_dir, approval)
            record = load_research_record(run_dir / "research_record.json")
            record = record_approval(record, approval)
            record = record_queue_update(record, queued)
            write_research_record(run_dir / "research_record.json", record)
            append_workflow_event(
                run_dir, "candidates_approved", {"queued_count": 1}, "2026-07-12T00:11:00Z"
            )

            result = orchestrator.approve_candidates(["c1"], "2026-07-12T00:11:00Z", "user")
            approvals = load_approvals(run_dir)
            queue = load_approved_queue(run_dir)
            final_record = load_research_record(run_dir / "research_record.json")
            events = read_workflow_events(run_dir)

        self.assertEqual(result["status"], "running")
        self.assertEqual(len(approvals), 1)
        self.assertEqual(len(queue), 1)
        self.assertEqual(len(final_record.user_approval), 1)
        self.assertEqual(len(final_record.approved_queue), 1)
        self.assertEqual([event.event_type for event in events].count("candidates_approved"), 1)

    def test_two_candidate_interrupted_approval_retry_dedupes_each_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidates = [
                {
                    "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                    "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
                },
                {
                    "candidate_id": "c2", "platform_alpha_id": "a2", "version": 1,
                    "expression_hash": "h2", "source_run_id": started["run_id"], "hard_pass": True,
                },
            ]
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval(candidates, "2026-07-12T00:10:00Z")
            run_dir = Path(started["run_dir"])
            record = load_research_record(run_dir / "research_record.json")
            for candidate in candidates:
                approval = approve_candidate(
                    run_dir, candidate, "2026-07-12T00:11:00Z", "user"
                )
                queued = queue_approved_candidate(run_dir, approval)
                record = record_approval(record, approval)
                record = record_queue_update(record, queued)
            write_research_record(run_dir / "research_record.json", record)
            append_workflow_event(
                run_dir, "candidates_approved", {"queued_count": 2}, "2026-07-12T00:11:00Z"
            )

            orchestrator.approve_candidates(
                ["c1", "c2"], "2026-07-12T00:11:00Z", "user"
            )
            final_record = load_research_record(run_dir / "research_record.json")
            events = read_workflow_events(run_dir)

        self.assertEqual(
            [row["candidate_id"] for row in final_record.approved_queue], ["c1", "c2"]
        )
        self.assertEqual([event.event_type for event in events].count("candidates_approved"), 1)

    def test_sync_research_record_writes_raw_markdown_and_updates_official_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1",
                "platform_alpha_id": "a1",
                "version": 1,
                "expression_hash": "h1",
                "source_run_id": started["run_id"],
                "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval([candidate], "2026-07-12T00:10:00Z")
            synced = orchestrator.sync_research_record("2026-07-12T00:12:00Z")
            run_dir = Path(started["run_dir"])
            state = load_run_state(run_dir / "run_state.json")
            events = read_workflow_events(run_dir)
            markdown = Path(synced["raw_path"]).read_text(encoding="utf-8")

        self.assertTrue(synced["synced"])
        self.assertEqual(
            Path(synced["raw_path"]),
            root / "knowledge" / "raw" / "research" / "runs" / started["run_id"] / "research_record.md",
        )
        self.assertTrue(state.research_record_synced)
        self.assertEqual(state.current_stage, "user_approval")
        self.assertEqual(state.last_completed_stage, "candidate_gate")
        self.assertEqual(state.stages["research_record_sync"].status, "not_started")
        self.assertEqual(state.stages["research_record_sync"].evidence_paths, [])
        self.assertIn("## Candidate Gate", markdown)
        self.assertIn("`c1`", markdown)
        self.assertIn("research_record_synced", [event.event_type for event in events])

    def test_sync_completes_stage_with_evidence_and_record_mutations_clear_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval([candidate], "2026-07-12T00:01:00Z")
            orchestrator.sync_research_record("2026-07-12T00:02:00Z")
            orchestrator.approve_candidates(["c1"], "2026-07-12T00:03:00Z", "user")
            state_path = Path(started["run_dir"]) / "run_state.json"
            after_approval = load_run_state(state_path)
            orchestrator.update_candidate_status(
                "c1", 1, "h1", "manually_submitted", "2026-07-12T00:04:00Z"
            )
            after_status = load_run_state(state_path)
            synced = orchestrator.sync_research_record("2026-07-12T00:05:00Z")
            after_sync = load_run_state(state_path)

        self.assertFalse(after_approval.research_record_synced)
        self.assertTrue(after_sync.research_record_synced)
        self.assertEqual(after_sync.stages["research_record_sync"].status, "completed")
        self.assertEqual(after_sync.stages["research_record_sync"].evidence_paths, [synced["raw_path"]])
        self.assertEqual(after_sync.current_stage, "complete")
        self.assertEqual(after_sync.last_completed_stage, "research_record_sync")
        self.assertEqual(after_sync.updated_at, "2026-07-12T00:05:00Z")
        self.assertEqual(after_sync.status, "completed")
        self.assertFalse(after_status.research_record_synced)

    def test_final_research_record_sync_failure_completes_with_warning_and_releases_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            run_dir = Path(str(started["run_dir"]))

            with patch(
                "wqb.orchestrator.sync_research_record_to_raw",
                side_effect=OSError("raw vault unavailable"),
            ):
                summary = orchestrator.sync_research_record("2026-07-12T00:03:00Z")

            state = load_run_state(run_dir / "run_state.json")
            events = read_workflow_events(run_dir)
            active = load_active_run(root / "runs")
            local_record_exists = (run_dir / "research_record.json").exists()

        self.assertTrue(local_record_exists)
        self.assertEqual(summary["status"], "completed_with_warnings")
        self.assertFalse(summary["synced"])
        self.assertTrue(summary["warnings"])
        self.assertEqual(state.status, "completed_with_warnings")
        self.assertEqual(state.current_stage, "complete")
        self.assertFalse(state.research_record_synced)
        self.assertIn("raw vault unavailable", state.stages["research_record_sync"].blocker)
        self.assertEqual(active, {})
        self.assertIn(
            "research_record_sync_warning", [event.event_type for event in events]
        )

    def test_completed_with_warnings_unsynced_terminal_run_does_not_block_new_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)

            with patch(
                "wqb.orchestrator.sync_research_record_to_raw",
                side_effect=OSError("raw vault unavailable"),
            ):
                orchestrator.sync_research_record("2026-07-12T00:03:00Z")

            next_started = orchestrator.start("Next objective", "option-2", "2026-07-12T00:04:00Z")
            warning_state = load_run_state(Path(str(started["run_dir"])) / "run_state.json")

        self.assertEqual(warning_state.status, "completed_with_warnings")
        self.assertFalse(warning_state.research_record_synced)
        self.assertEqual(next_started["status"], "created")

    def test_candidate_gate_rejects_non_hard_pass_and_source_run_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            base = {
                "candidate_id": "c1",
                "platform_alpha_id": "a1",
                "version": 1,
                "expression_hash": "h1",
                "source_run_id": started["run_id"],
            }
            self.advance_to_candidate_gate(started)

            with self.assertRaisesRegex(ValueError, "verified hard-pass"):
                orchestrator.request_candidate_approval([dict(base, hard_pass=False)], "2026-07-12T00:10:00Z")
            with self.assertRaisesRegex(ValueError, "source_run_id"):
                orchestrator.request_candidate_approval(
                    [dict(base, hard_pass=True, source_run_id="other-run")], "2026-07-12T00:10:00Z"
                )

    def test_candidate_gate_rejects_caller_hard_pass_without_durable_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            self.advance_to_candidate_gate(started)
            run_dir = Path(str(started["run_dir"]))
            (run_dir / "candidates.csv").unlink()
            (run_dir / "all_alphas.jsonl").unlink()
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }

            with self.assertRaisesRegex(ValueError, "verified hard-pass"):
                orchestrator.request_candidate_approval([candidate], "2026-07-12T00:10:00Z")

            self.assertFalse((run_dir / "candidate_gate.json").exists())

    def test_candidate_gate_accepts_matching_durable_hard_pass_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            self.advance_to_candidate_gate(started)
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }

            result = orchestrator.request_candidate_approval([candidate], "2026-07-12T00:10:00Z")

            self.assertEqual(result["status"], "waiting_for_user")

    def test_candidate_gate_rejects_duplicate_identity_before_writing_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            self.advance_to_candidate_gate(started)
            run_dir = Path(str(started["run_dir"]))
            with (run_dir / "candidates.csv").open("a", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=("alpha_id", "expression_hash"))
                writer.writerow({"alpha_id": "a2", "expression_hash": "h1"})
            with (run_dir / "all_alphas.jsonl").open("a", encoding="utf-8") as file:
                file.write(
                    json.dumps(
                        {
                            "alpha_id": "a2",
                            "expression_hash": "h1",
                            "hard_pass": True,
                            "failed": [],
                            "pending": [],
                        }
                    )
                    + "\n"
                )
            candidates = [
                {
                    "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                    "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
                },
                {
                    "candidate_id": "c1", "platform_alpha_id": "a2", "version": 1,
                    "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
                },
            ]

            with self.assertRaisesRegex(ValueError, "duplicate candidate"):
                orchestrator.request_candidate_approval(candidates, "2026-07-12T00:10:00Z")

            gate_exists = (run_dir / "candidate_gate.json").exists()
            record_path = run_dir / "research_record.json"
            gate_entries = [] if not record_path.exists() else load_research_record(record_path).candidate_gate

        self.assertFalse(gate_exists)
        self.assertEqual(gate_entries, [])

    def test_candidate_gate_rejects_durable_hard_pass_identity_mismatches(self):
        mismatches = (
            {"expression_hash": "other-hash"},
            {"platform_alpha_id": "other-alpha"},
        )
        for mismatch in mismatches:
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                orchestrator = WorkflowOrchestrator(self.paths(root))
                started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
                self.advance_to_candidate_gate(started)
                run_dir = Path(str(started["run_dir"]))
                candidate = {
                    "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                    "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
                }
                candidate.update(mismatch)

                with self.assertRaisesRegex(ValueError, "verified hard-pass"):
                    orchestrator.request_candidate_approval([candidate], "2026-07-12T00:10:00Z")

                self.assertFalse((run_dir / "candidate_gate.json").exists())

    def test_candidate_gate_requires_non_empty_candidate_identity_fields(self):
        for field_name in ("candidate_id", "version"):
            with self.subTest(field=field_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                orchestrator = WorkflowOrchestrator(self.paths(root))
                started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
                self.advance_to_candidate_gate(started)
                candidate = {
                    "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                    "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
                }
                candidate[field_name] = ""

                with self.assertRaisesRegex(ValueError, "candidate_id and version"):
                    orchestrator.request_candidate_approval([candidate], "2026-07-12T00:10:00Z")

    def test_candidate_approval_rejects_empty_and_unknown_selection_without_leaving_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1",
                "platform_alpha_id": "a1",
                "version": 1,
                "expression_hash": "h1",
                "source_run_id": started["run_id"],
                "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval([candidate], "2026-07-12T00:10:00Z")

            with self.assertRaisesRegex(ValueError, "at least one candidate"):
                orchestrator.approve_candidates([], "2026-07-12T00:11:00Z", "user")
            with self.assertRaisesRegex(ValueError, "unknown candidate"):
                orchestrator.approve_candidates(["missing"], "2026-07-12T00:11:00Z", "user")
            state = load_run_state(Path(started["run_dir"]) / "run_state.json")

        self.assertEqual(state.status, "waiting_for_user")
        self.assertTrue(state.waiting_for_user)

    def test_start_rejects_second_resumable_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")

            with self.assertRaisesRegex(ValueError, "active workflow"):
                orchestrator.start("Other", "option-2", "2026-07-12T00:01:00Z")

    def test_orchestrator_surfaces_pointer_sibling_ambiguity_without_rewriting_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            for run_id in ("run1", "run2"):
                run_dir = runs / run_id
                run_dir.mkdir(parents=True)
                write_run_state(
                    run_dir / "run_state.json",
                    create_initial_state(
                        run_id, run_dir, "Power Pool", "2026-07-12T00:00:00Z"
                    ),
                )
            write_active_run(runs, "run1", runs / "run1")
            pointer_before = (runs / "active_run.json").read_bytes()
            orchestrator = WorkflowOrchestrator(self.paths(root))

            status = orchestrator.status()
            resumed = orchestrator.resume("2026-07-12T00:01:00Z")
            continued = orchestrator.continue_once("2026-07-12T00:02:00Z")
            with self.assertRaisesRegex(ValueError, "active workflow"):
                orchestrator.start("Other", "option-2", "2026-07-12T00:03:00Z")
            pointer_unchanged = (runs / "active_run.json").read_bytes() == pointer_before

        for summary in (status, resumed, continued):
            self.assertIn("multiple_active_runs", summary["diagnostics"])
        self.assertTrue(pointer_unchanged)

    def test_candidate_gate_retry_after_research_record_write_does_not_duplicate_gate_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            run_dir = Path(started["run_dir"])
            record = record_candidate_gate(
                empty_research_record(str(started["run_id"]), "Power Pool"),
                candidate,
                "ready_for_approval",
                ["hard checks passed"],
            )
            write_research_record(run_dir / "research_record.json", record)

            orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")
            recovered = load_research_record(run_dir / "research_record.json")

        self.assertEqual(len(recovered.candidate_gate), 1)

    def test_status_exposes_and_pauses_on_consistency_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            orchestrator.continue_once("2026-07-12T00:01:00Z")
            run_dir = Path(started["run_dir"])
            (run_dir / "approved_candidates.jsonl").write_text('{"candidate_id":"c1"}\n', encoding="utf-8")

            status = orchestrator.status()
            state = load_run_state(run_dir / "run_state.json")

        self.assertIn("candidate_queue_without_approval", status["diagnostics"])
        self.assertFalse(status["consistent"])
        self.assertEqual(state.status, "paused")

    def test_status_exposes_damaged_active_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            run_dir = runs / "run1"
            run_dir.mkdir(parents=True)
            (runs / "active_run.json").write_text(
                json.dumps({"run_id": "run1", "run_dir": str(run_dir)}), encoding="utf-8"
            )
            (run_dir / "run_state.json").write_text("{broken", encoding="utf-8")

            status = WorkflowOrchestrator(self.paths(root)).status()

        self.assertTrue(status["active"])
        self.assertIn("run_state_invalid", status["diagnostics"])

    def test_continue_and_resume_expose_damaged_active_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            run_dir = runs / "run1"
            run_dir.mkdir(parents=True)
            (runs / "active_run.json").write_text(
                json.dumps({"run_id": "run1", "run_dir": str(run_dir)}), encoding="utf-8"
            )
            (run_dir / "run_state.json").write_text("{broken", encoding="utf-8")
            orchestrator = WorkflowOrchestrator(self.paths(root))

            continued = orchestrator.continue_once("2026-07-12T00:01:00Z")
            resumed = orchestrator.resume("2026-07-12T00:02:00Z")

        self.assertTrue(continued["active"])
        self.assertIn("run_state_invalid", continued["diagnostics"])
        self.assertTrue(resumed["active"])
        self.assertIn("run_state_invalid", resumed["diagnostics"])

    def test_status_and_resume_recover_checkpointed_active_state_and_repair_official_state(self):
        for method_name in ("status", "resume"):
            with self.subTest(method=method_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                orchestrator = WorkflowOrchestrator(self.paths(root))
                started = orchestrator.start(
                    "Power Pool", "option-1", "2026-07-12T00:00:00Z"
                )
                state_path = Path(started["run_dir"]) / "run_state.json"
                checkpoint_state = load_run_state(
                    Path(started["run_dir"]) / "run_state_checkpoint.json"
                )
                state_path.write_text("{broken", encoding="utf-8")

                if method_name == "status":
                    summary = orchestrator.status()
                else:
                    summary = orchestrator.resume("2026-07-12T00:01:00Z")
                repaired = load_run_state(state_path)

                self.assertEqual(summary["status"], "created")
                self.assertEqual(repaired, checkpoint_state)

    def test_stage_state_tracks_schedule_and_candidate_transitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                '{"option_id":"option-1","title":"Power Pool","scope":"USA D1"}\n', encoding="utf-8"
            )
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            orchestrator.continue_once("2026-07-12T00:01:00Z")
            running_schedule = load_run_state(Path(started["run_dir"]) / "run_state.json")
            orchestrator.continue_once("2026-07-12T00:02:00Z")
            completed_schedule = load_run_state(Path(started["run_dir"]) / "run_state.json")
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")
            waiting = load_run_state(Path(started["run_dir"]) / "run_state.json")
            orchestrator.approve_candidates(["c1"], "2026-07-12T00:04:00Z", "user")
            approved = load_run_state(Path(started["run_dir"]) / "run_state.json")

        self.assertEqual(running_schedule.stages["schedule"].status, "running")
        self.assertEqual(running_schedule.stages["schedule"].started_at, "2026-07-12T00:01:00Z")
        self.assertEqual(completed_schedule.stages["schedule"].status, "completed")
        self.assertTrue(completed_schedule.stages["schedule"].evidence_paths)
        self.assertEqual(completed_schedule.updated_at, "2026-07-12T00:02:00Z")
        self.assertEqual(waiting.current_stage, "user_approval")
        self.assertEqual(waiting.stages["candidate_gate"].status, "completed")
        self.assertEqual(waiting.stages["user_approval"].status, "paused")
        self.assertTrue(waiting.waiting_for_user)
        self.assertEqual(waiting.next_action, "workflow-approve-candidates")
        self.assertEqual(approved.current_stage, "research_record_sync")
        self.assertEqual(approved.last_completed_stage, "approved_queue")
        self.assertEqual(approved.stages["user_approval"].status, "completed")
        self.assertEqual(approved.stages["approved_queue"].status, "completed")
        self.assertFalse(approved.waiting_for_user)
        self.assertEqual(approved.next_action, "workflow-continue")

    def test_schedule_adapter_errors_are_persisted_as_failed_state_and_event(self):
        cases = (
            ("missing options", None, "option-1"),
            ("unknown option", '{"option_id":"option-1","title":"Power Pool","scope":"USA D1"}\n', "missing"),
        )
        for label, option_rows, selected_id in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if option_rows is not None:
                    decisions = root / "knowledge" / "wiki" / "70_decisions"
                    decisions.mkdir(parents=True)
                    (decisions / "research_option_cards.jsonl").write_text(option_rows, encoding="utf-8")
                orchestrator = WorkflowOrchestrator(self.paths(root))
                started = orchestrator.start("Power Pool", selected_id, "2026-07-12T00:00:00Z")
                orchestrator.continue_once("2026-07-12T00:01:00Z")

                summary = orchestrator.continue_once("2026-07-12T00:02:00Z")
                state = load_run_state(Path(started["run_dir"]) / "run_state.json")
                events = read_workflow_events(Path(started["run_dir"]))

                self.assertEqual(summary["status"], "failed")
                self.assertEqual(state.status, "failed")
                self.assertEqual(state.stages["schedule"].status, "failed")
                self.assertTrue(state.stages["schedule"].blocker)
                self.assertEqual(events[-1].event_type, "stage_failed")
                self.assertEqual(events[-1].payload["stage"], "schedule")

    def test_post_schedule_adapter_errors_are_persisted_as_failed_state_and_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                '{"option_id":"option-1","title":"Power Pool","scope":"USA D1"}\n',
                encoding="utf-8",
            )
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            orchestrator.continue_once("2026-07-12T00:01:00Z")
            orchestrator.continue_once("2026-07-12T00:02:00Z")
            run_dir = Path(str(started["run_dir"]))
            (run_dir / "candidates.csv").write_text("alpha_id,expression_hash\na1,h1\n", encoding="utf-8")
            (run_dir / "all_alphas.jsonl").write_text("{broken", encoding="utf-8")

            summary = orchestrator.continue_once("2026-07-12T00:03:00Z")
            state = load_run_state(run_dir / "run_state.json")
            events = read_workflow_events(run_dir)

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.stages["scout_seed"].status, "failed")
        self.assertIn("JSONDecodeError", state.stages["scout_seed"].blocker)
        self.assertEqual(events[-1].event_type, "stage_failed")
        self.assertEqual(events[-1].payload["stage"], "scout_seed")

    def test_missing_and_malformed_manifests_are_persisted_as_schedule_failures(self):
        for label, manifest_text in (("missing", None), ("malformed", "{broken")):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                orchestrator = WorkflowOrchestrator(self.paths(root))
                started = orchestrator.start(
                    "Power Pool", "option-1", "2026-07-12T00:00:00Z"
                )
                orchestrator.continue_once("2026-07-12T00:01:00Z")
                manifest_path = Path(started["run_dir"]) / "run_manifest.json"
                if manifest_text is None:
                    manifest_path.unlink()
                else:
                    manifest_path.write_text(manifest_text, encoding="utf-8")

                result = orchestrator.continue_once("2026-07-12T00:02:00Z")
                state = load_run_state(Path(started["run_dir"]) / "run_state.json")
                events = read_workflow_events(Path(started["run_dir"]))

                self.assertEqual(result["status"], "failed")
                self.assertEqual(state.stages["schedule"].status, "failed")
                self.assertEqual(events[-1].event_type, "stage_failed")

    def test_candidate_gate_request_rejects_created_schedule_and_scout_seed_states(self):
        for stage_name in ("created", "schedule", "scout_seed"):
            with self.subTest(stage=stage_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                decisions = root / "knowledge" / "wiki" / "70_decisions"
                decisions.mkdir(parents=True)
                (decisions / "research_option_cards.jsonl").write_text(
                    '{"option_id":"option-1","title":"Power Pool","scope":"USA D1"}\n',
                    encoding="utf-8",
                )
                orchestrator = WorkflowOrchestrator(self.paths(root))
                started = orchestrator.start(
                    "Power Pool", "option-1", "2026-07-12T00:00:00Z"
                )
                if stage_name in {"schedule", "scout_seed"}:
                    orchestrator.continue_once("2026-07-12T00:01:00Z")
                if stage_name == "scout_seed":
                    orchestrator.continue_once("2026-07-12T00:02:00Z")
                candidate = {
                    "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                    "expression_hash": "h1", "source_run_id": started["run_id"],
                    "hard_pass": True,
                }

                with self.assertRaisesRegex(ValueError, "candidate gate stage"):
                    orchestrator.request_candidate_approval(
                        [candidate], "2026-07-12T00:03:00Z"
                    )

                self.assertFalse((Path(started["run_dir"]) / "candidate_gate.json").exists())

    def test_candidate_gate_request_requires_completed_or_skipped_prerequisites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            state_path = Path(started["run_dir"]) / "run_state.json"
            state = transition_run_state(load_run_state(state_path), "running", "")
            write_run_state(state_path, replace(state, current_stage="candidate_gate"))
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }

            with self.assertRaisesRegex(ValueError, "prerequisite"):
                orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")

    def test_approve_candidates_rejects_waiting_state_outside_user_approval_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            self.advance_to_candidate_gate(started)
            state_path = Path(started["run_dir"]) / "run_state.json"
            waiting = transition_run_state(load_run_state(state_path), "waiting_for_user", "wait")
            write_run_state(state_path, replace(waiting, current_stage="candidate_gate"))

            with self.assertRaisesRegex(ValueError, "user approval stage"):
                orchestrator.approve_candidates(["c1"], "2026-07-12T00:04:00Z", "user")

            self.assertEqual(load_approvals(Path(started["run_dir"])), [])

    def test_update_candidate_status_records_event_and_research_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval([candidate], "2026-07-12T00:01:00Z")
            orchestrator.approve_candidates(["c1"], "2026-07-12T00:02:00Z", "user")
            updated = orchestrator.update_candidate_status(
                "c1", 1, "h1", "manually_submitted", "2026-07-12T00:03:00Z"
            )
            orchestrator.update_candidate_status(
                "c1", 1, "h1", "manually_submitted", "2026-07-12T00:04:00Z"
            )
            run_dir = Path(started["run_dir"])
            events = read_workflow_events(run_dir)
            record = load_research_record(run_dir / "research_record.json")

        self.assertEqual(updated["status"], "manually_submitted")
        self.assertIn("candidate_status_updated", [event.event_type for event in events])
        self.assertEqual(record.manual_submission_status[-1]["status"], "manually_submitted")
        self.assertEqual(
            [event.event_type for event in events].count("candidate_status_updated"), 1
        )
        self.assertEqual(len(record.manual_submission_status), 1)

    def test_candidate_status_rejects_manual_submission_reclassification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval([candidate], "2026-07-12T00:01:00Z")
            orchestrator.approve_candidates(["c1"], "2026-07-12T00:02:00Z", "user")
            orchestrator.update_candidate_status(
                "c1", 1, "h1", "manually_submitted", "2026-07-12T00:03:00Z"
            )
            claims_path = root / "runs" / "api_submission_claims.jsonl"

            with self.assertRaisesRegex(ValueError, "submitted.*immutable"):
                orchestrator.update_candidate_status(
                    "c1", 1, "h1", "queued", "2026-07-12T00:04:00Z"
                )
            with self.assertRaisesRegex(ValueError, "submitted.*immutable"):
                orchestrator.update_candidate_status(
                    "c1", 1, "h1", "api_submitted", "2026-07-12T00:05:00Z"
                )
            rows = load_approved_queue(Path(started["run_dir"]))
            events = [
                event.payload["status"]
                for event in read_workflow_events(Path(started["run_dir"]))
                if event.event_type == "candidate_status_updated"
            ]
            claim_exists = claims_path.exists()

        self.assertEqual(rows[0]["status"], "manually_submitted")
        self.assertEqual(events, ["manually_submitted"])
        self.assertFalse(claim_exists)

    def test_candidate_status_retry_restores_event_after_post_queue_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            run_dir = Path(started["run_dir"])

            with patch.object(
                orchestrator,
                "_load_or_create_research_record",
                side_effect=OSError("record read unavailable"),
            ):
                with self.assertRaisesRegex(OSError, "record read unavailable"):
                    orchestrator.update_candidate_status(
                        "c1", 1, "h1", "manually_submitted", "2026-07-12T00:03:00Z"
                    )

            self.assertEqual(load_approved_queue(run_dir)[0]["status"], "manually_submitted")
            self.assertNotIn(
                "candidate_status_updated",
                [event.event_type for event in read_workflow_events(run_dir)],
            )

            orchestrator.update_candidate_status(
                "c1", 1, "h1", "manually_submitted", "2026-07-12T00:04:00Z"
            )
            events = [
                event
                for event in read_workflow_events(run_dir)
                if event.event_type == "candidate_status_updated"
            ]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["candidate_id"], "c1")
        self.assertEqual(events[0].payload["platform_alpha_id"], "a1")
        self.assertEqual(events[0].payload["version"], 1)
        self.assertEqual(events[0].payload["expression_hash"], "h1")
        self.assertEqual(events[0].payload["source_run_id"], started["run_id"])
        self.assertEqual(events[0].payload["status"], "manually_submitted")

    def test_interleaved_candidate_status_retries_dedupe_per_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidates = [
                {
                    "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                    "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
                },
                {
                    "candidate_id": "c2", "platform_alpha_id": "a2", "version": 1,
                    "expression_hash": "h2", "source_run_id": started["run_id"], "hard_pass": True,
                },
            ]
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval(candidates, "2026-07-12T00:01:00Z")
            orchestrator.approve_candidates(["c1", "c2"], "2026-07-12T00:02:00Z", "user")
            updates = (("c1", "h1"), ("c2", "h2"), ("c1", "h1"), ("c2", "h2"))
            for index, (candidate_id, expression_hash) in enumerate(updates, start=3):
                orchestrator.update_candidate_status(
                    candidate_id,
                    1,
                    expression_hash,
                    "manually_submitted",
                    f"2026-07-12T00:0{index}:00Z",
                )
            run_dir = Path(started["run_dir"])
            record = load_research_record(run_dir / "research_record.json")
            events = [
                event
                for event in read_workflow_events(run_dir)
                if event.event_type == "candidate_status_updated"
            ]

        self.assertEqual(
            [row["candidate_id"] for row in record.manual_submission_status], ["c1", "c2"]
        )
        self.assertEqual([event.payload["candidate_id"] for event in events], ["c1", "c2"])

    def test_completed_run_candidate_status_update_uses_source_run_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval([candidate], "2026-07-12T00:01:00Z")
            orchestrator.approve_candidates(["c1"], "2026-07-12T00:02:00Z", "user")
            orchestrator.sync_research_record("2026-07-12T00:03:00Z")
            active_path = root / "runs" / "active_run.json"
            self.assertFalse(active_path.exists())

            updated = orchestrator.update_candidate_status(
                "c1",
                1,
                "h1",
                "manually_submitted",
                "2026-07-12T00:04:00Z",
                source_run_id=str(started["run_id"]),
            )
            run_dir = Path(started["run_dir"])
            state = load_run_state(run_dir / "run_state.json")
            record = load_research_record(run_dir / "research_record.json")
            raw_path = root / "knowledge" / "raw" / "research" / "runs" / str(started["run_id"]) / "research_record.md"
            events = [
                event
                for event in read_workflow_events(run_dir)
                if event.event_type == "candidate_status_updated"
            ]
            raw_text = raw_path.read_text(encoding="utf-8")
            active_exists = active_path.exists()

        self.assertEqual(updated["status"], "manually_submitted")
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.current_stage, "complete")
        self.assertTrue(state.research_record_synced)
        self.assertFalse(active_exists)
        self.assertEqual(record.manual_submission_status[-1]["status"], "manually_submitted")
        self.assertIn("manually_submitted", raw_text)
        self.assertEqual(events[0].payload["platform_alpha_id"], "a1")
        self.assertEqual(events[0].payload["source_run_id"], started["run_id"])

    def test_completed_run_candidate_status_sync_failure_persists_warning_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            orchestrator.sync_research_record("2026-07-12T00:03:00Z")
            run_dir = Path(str(started["run_dir"]))

            with patch(
                "wqb.orchestrator.sync_research_record_to_raw",
                side_effect=OSError("raw vault unavailable"),
            ):
                updated = orchestrator.update_candidate_status(
                    "c1",
                    1,
                    "h1",
                    "manually_submitted",
                    "2026-07-12T00:04:00Z",
                    source_run_id=str(started["run_id"]),
                )

            state = load_run_state(run_dir / "run_state.json")
            issues = diagnose_state_consistency(run_dir)
            events = read_workflow_events(run_dir)
            active_exists = (root / "runs" / "active_run.json").exists()

        self.assertEqual(updated["status"], "manually_submitted")
        self.assertEqual(state.status, "completed_with_warnings")
        self.assertFalse(state.research_record_synced)
        self.assertIn("raw vault unavailable", state.stages["research_record_sync"].blocker)
        self.assertIn("terminal_research_record_not_synced", issues)
        self.assertIn("research_record_sync_warning", [event.event_type for event in events])
        self.assertFalse(active_exists)

    def test_warning_terminal_allows_later_candidate_status_sync_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            orchestrator.sync_research_record("2026-07-12T00:03:00Z")
            run_dir = Path(str(started["run_dir"]))

            with patch(
                "wqb.orchestrator.sync_research_record_to_raw",
                side_effect=OSError("raw vault unavailable"),
            ):
                orchestrator.update_candidate_status(
                    "c1",
                    1,
                    "h1",
                    "manually_submitted",
                    "2026-07-12T00:04:00Z",
                    source_run_id=str(started["run_id"]),
                )

            updated = orchestrator.update_candidate_status(
                "c1",
                1,
                "h1",
                "manually_submitted",
                "2026-07-12T00:05:00Z",
                source_run_id=str(started["run_id"]),
            )
            state = load_run_state(run_dir / "run_state.json")
            rows = load_approved_queue(run_dir)
            events = read_workflow_events(run_dir)
            raw_path = (
                root
                / "knowledge"
                / "raw"
                / "research"
                / "runs"
                / str(started["run_id"])
                / "research_record.md"
            )

        self.assertEqual(updated["status"], "manually_submitted")
        self.assertEqual(rows[0]["status"], "manually_submitted")
        self.assertTrue(state.research_record_synced)
        self.assertEqual(state.stages["research_record_sync"].blocker, "")
        self.assertEqual(state.stages["research_record_sync"].evidence_paths, [str(raw_path)])
        self.assertIn("research_record_synced", [event.event_type for event in events])

    def test_completed_run_candidate_invalidation_sync_failure_persists_warning_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            orchestrator.sync_research_record("2026-07-12T00:03:00Z")
            run_dir = Path(str(started["run_dir"]))

            with patch(
                "wqb.orchestrator.sync_research_record_to_raw",
                side_effect=OSError("raw vault unavailable"),
            ):
                invalidated = orchestrator.invalidate_candidate_approval(
                    "c1",
                    1,
                    "h1",
                    "candidate expression revised",
                    "2026-07-12T00:04:00Z",
                    source_run_id=str(started["run_id"]),
                )

            state = load_run_state(run_dir / "run_state.json")
            rows = load_approved_queue(run_dir)
            events = read_workflow_events(run_dir)

        self.assertEqual(invalidated["status"], "invalidated")
        self.assertEqual(rows[0]["status"], "invalidated")
        self.assertEqual(state.status, "completed_with_warnings")
        self.assertFalse(state.research_record_synced)
        self.assertIn("raw vault unavailable", state.stages["research_record_sync"].blocker)
        self.assertIn("research_record_sync_warning", [event.event_type for event in events])

    def test_warning_terminal_allows_later_candidate_invalidation_sync_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            run_dir = Path(str(started["run_dir"]))

            with patch(
                "wqb.orchestrator.sync_research_record_to_raw",
                side_effect=OSError("raw vault unavailable"),
            ):
                orchestrator.sync_research_record("2026-07-12T00:03:00Z")

            invalidated = orchestrator.invalidate_candidate_approval(
                "c1",
                1,
                "h1",
                "candidate expression revised",
                "2026-07-12T00:04:00Z",
                source_run_id=str(started["run_id"]),
            )
            state = load_run_state(run_dir / "run_state.json")
            rows = load_approved_queue(run_dir)
            events = read_workflow_events(run_dir)
            raw_path = (
                root
                / "knowledge"
                / "raw"
                / "research"
                / "runs"
                / str(started["run_id"])
                / "research_record.md"
            )

        self.assertEqual(invalidated["status"], "invalidated")
        self.assertEqual(rows[0]["status"], "invalidated")
        self.assertTrue(state.research_record_synced)
        self.assertEqual(state.stages["research_record_sync"].blocker, "")
        self.assertEqual(state.stages["research_record_sync"].evidence_paths, [str(raw_path)])
        self.assertIn("research_record_synced", [event.event_type for event in events])

    def test_api_submission_limit_applies_across_completed_workflow_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_orchestrator, first = self.create_approved_candidate_run(root)
            first_orchestrator.sync_research_record("2026-07-12T00:03:00Z")
            second_orchestrator, second = self.create_approved_candidate_run(root)
            second_orchestrator.sync_research_record("2026-07-12T00:04:00Z")
            first_orchestrator.update_candidate_status(
                "c1",
                1,
                "h1",
                "api_submitted",
                "2026-07-12T01:00:00Z",
                source_run_id=str(first["run_id"]),
            )
            second_dir = Path(str(second["run_dir"]))
            before = self.candidate_artifact_bytes(second_dir)

            with self.assertRaisesRegex(ValueError, "daily API submission limit"):
                second_orchestrator.update_candidate_status(
                    "c1",
                    1,
                    "h1",
                    "api_submitted",
                    "2026-07-12T01:01:00Z",
                    source_run_id=str(second["run_id"]),
                )

            after = self.candidate_artifact_bytes(second_dir)

        self.assertEqual(after, before)

    def test_api_submission_claim_blocks_second_run_when_first_queue_is_not_yet_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_orchestrator, first = self.create_approved_candidate_run(root)
            first_orchestrator.sync_research_record("2026-07-12T00:03:00Z")
            second_orchestrator, second = self.create_approved_candidate_run(root)
            second_orchestrator.sync_research_record("2026-07-12T00:04:00Z")
            first_orchestrator.update_candidate_status(
                "c1", 1, "h1", "api_submitted", "2026-07-12T01:00:00Z",
                source_run_id=str(first["run_id"]),
            )
            (Path(str(first["run_dir"])) / "approved_candidates.jsonl").unlink()
            second_dir = Path(str(second["run_dir"]))
            before = self.candidate_artifact_bytes(second_dir)

            with self.assertRaisesRegex(ValueError, "daily API submission limit"):
                second_orchestrator.update_candidate_status(
                    "c1", 1, "h1", "api_submitted", "2026-07-12T01:01:00Z",
                    source_run_id=str(second["run_id"]),
                )

            after = self.candidate_artifact_bytes(second_dir)

        self.assertEqual(after, before)

    def test_api_submission_claim_rolls_back_when_queue_update_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            orchestrator.sync_research_record("2026-07-12T00:03:00Z")
            claims_path = root / "runs" / "api_submission_claims.jsonl"

            with patch(
                "wqb.orchestrator.update_candidate_queue_status",
                side_effect=ValueError("queue write failed"),
            ):
                with self.assertRaisesRegex(ValueError, "queue write failed"):
                    orchestrator.update_candidate_status(
                        "c1",
                        1,
                        "h1",
                        "api_submitted",
                        "2026-07-12T01:00:00Z",
                        source_run_id=str(started["run_id"]),
                    )

            claim_rows = [] if not claims_path.exists() else [
                line for line in claims_path.read_text(encoding="utf-8").splitlines() if line.strip()
            ]

        self.assertEqual(claim_rows, [])

    def test_invalidated_api_submission_rejection_does_not_consume_daily_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            orchestrator.invalidate_candidate_approval(
                "c1",
                1,
                "h1",
                "candidate expression revised",
                "2026-07-12T00:03:00Z",
                source_run_id=str(started["run_id"]),
            )
            orchestrator.sync_research_record("2026-07-12T00:03:30Z")
            claims_path = root / "runs" / "api_submission_claims.jsonl"

            with self.assertRaisesRegex(ValueError, "invalidated"):
                orchestrator.update_candidate_status(
                    "c1",
                    1,
                    "h1",
                    "api_submitted",
                    "2026-07-12T01:00:00Z",
                    source_run_id=str(started["run_id"]),
                )

            claim_exists = claims_path.exists()

        self.assertFalse(claim_exists)

    def test_candidate_gate_rejects_incomplete_approval_identity_without_writing_artifacts(self):
        cases = (
            ("platform_alpha_id", None, "platform_alpha_id"),
            ("expression_hash", None, "expression_hash"),
            ("source_run_id", None, "source_run_id"),
            ("source_run_id", "other-run", "source_run_id"),
            ("version", "one", "version"),
        )
        for field, value, error in cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                orchestrator = WorkflowOrchestrator(self.paths(root))
                started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
                self.advance_to_candidate_gate(started)
                candidate = {
                    "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                    "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
                }
                candidate[field] = value
                run_dir = Path(str(started["run_dir"]))

                with self.assertRaisesRegex(ValueError, error):
                    orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")

                gate_exists = (run_dir / "candidate_gate.json").exists()
                record_path = run_dir / "research_record.json"
                gate_entries = [] if not record_path.exists() else load_research_record(record_path).candidate_gate

                self.assertFalse(gate_exists)
                self.assertEqual(gate_entries, [])

    def test_candidate_gate_requires_canonical_hard_pass_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            self.advance_to_candidate_gate(started)
            run_dir = Path(str(started["run_dir"]))
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            (run_dir / "all_alphas.jsonl").unlink()

            with self.assertRaisesRegex(ValueError, "hard-pass evidence"):
                orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")

            self.assertFalse((run_dir / "candidate_gate.json").exists())

        for label, row in (
            ("hard_pass_false", {"hard_pass": False}),
            ("failed", {"hard_pass": True, "failed": True}),
            ("pending", {"hard_pass": True, "pending": True}),
            ("missing_expression_hash", {"hard_pass": True, "expression_hash": ""}),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                orchestrator = WorkflowOrchestrator(self.paths(root))
                started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
                self.advance_to_candidate_gate(started)
                run_dir = Path(str(started["run_dir"]))
                candidate = {
                    "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                    "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
                }
                canonical = {"alpha_id": "a1", "expression_hash": "h1", **row}
                (run_dir / "all_alphas.jsonl").write_text(json.dumps(canonical) + "\n", encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "hard-pass evidence"):
                    orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            self.advance_to_candidate_gate(started)
            run_dir = Path(str(started["run_dir"]))
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            duplicate_rows = (
                {"alpha_id": "a1", "expression_hash": "h1", "hard_pass": True},
                {"alpha_id": "a1", "expression_hash": "h1", "hard_pass": False},
            )
            (run_dir / "all_alphas.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in duplicate_rows),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "hard-pass evidence"):
                orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            self.advance_to_candidate_gate(started)
            run_dir = Path(str(started["run_dir"]))
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            (run_dir / "all_alphas.jsonl").write_text("{broken\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "hard-pass evidence"):
                orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            self.advance_to_candidate_gate(started)
            run_dir = Path(str(started["run_dir"]))
            (run_dir / "candidates.csv").unlink()
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }

            result = orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")

        self.assertEqual(result["status"], "waiting_for_user")

    def test_source_run_selector_rejects_non_completed_states_without_mutation(self):
        for selected_status in ("running", "failed", "aborted"):
            with self.subTest(selected_status=selected_status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                orchestrator, started = self.create_approved_candidate_run(root)
                run_dir = Path(started["run_dir"])
                state_path = run_dir / "run_state.json"
                state = load_run_state(state_path)
                if selected_status != "running":
                    state = transition_run_state(state, selected_status, "test terminal state")
                    write_run_state(state_path, state)
                before = self.candidate_artifact_bytes(run_dir)

                with self.assertRaisesRegex(ValueError, "completed workflow run"):
                    orchestrator.update_candidate_status(
                        "c1",
                        1,
                        "h1",
                        "manually_submitted",
                        "2026-07-12T00:03:00Z",
                        source_run_id=str(started["run_id"]),
                    )

                self.assertEqual(self.candidate_artifact_bytes(run_dir), before)

    def test_source_run_selector_rejects_inconsistent_completed_run_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            orchestrator.sync_research_record("2026-07-12T00:03:00Z")
            run_dir = Path(started["run_dir"])
            approval_path = run_dir / "approval.jsonl"
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approval["expression_hash"] = "mismatched-hash"
            approval_path.write_text(json.dumps(approval) + "\n", encoding="utf-8")
            before = self.candidate_artifact_bytes(run_dir)

            with self.assertRaisesRegex(ValueError, "consistency diagnostics"):
                orchestrator.update_candidate_status(
                    "c1",
                    1,
                    "h1",
                    "manually_submitted",
                    "2026-07-12T00:04:00Z",
                    source_run_id=str(started["run_id"]),
                )

            self.assertEqual(self.candidate_artifact_bytes(run_dir), before)

    def test_source_run_selector_rejects_state_run_dir_mismatch_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            orchestrator.sync_research_record("2026-07-12T00:03:00Z")
            run_dir = Path(started["run_dir"])
            state_path = run_dir / "run_state.json"
            state = load_run_state(state_path)
            write_run_state(state_path, replace(state, run_dir=str(run_dir / "other")))
            before = self.candidate_artifact_bytes(run_dir)

            with self.assertRaisesRegex(ValueError, "run_dir"):
                orchestrator.update_candidate_status(
                    "c1",
                    1,
                    "h1",
                    "manually_submitted",
                    "2026-07-12T00:04:00Z",
                    source_run_id=str(started["run_id"]),
                )

            self.assertEqual(self.candidate_artifact_bytes(run_dir), before)

    def test_source_run_selector_rejects_resolved_path_outside_run_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator, started = self.create_approved_candidate_run(root)
            orchestrator.sync_research_record("2026-07-12T00:03:00Z")
            selected_run_dir = Path(started["run_dir"])
            external_run_dir = root / "external-run"
            external_run_dir.mkdir()
            resolve = Path.resolve

            def resolve_with_external_selected_path(path, *args, **kwargs):
                """Input: Path and resolve args. Output: resolved Path. Model an unavailable symlink/junction."""
                if path == selected_run_dir:
                    return external_run_dir
                return resolve(path, *args, **kwargs)

            with patch(
                "wqb.orchestrator.Path.resolve",
                autospec=True,
                side_effect=resolve_with_external_selected_path,
            ):
                with self.assertRaisesRegex(ValueError, "outside run_root"):
                    orchestrator._candidate_status_state(str(started["run_id"]))

    def test_source_run_selector_rejects_cross_run_artifact_identities_without_mutation(self):
        corruptions = (
            "research_record",
            "candidate_artifacts",
            "missing_warning_record",
        )
        for corruption in corruptions:
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                orchestrator, started = self.create_approved_candidate_run(root)
                orchestrator.sync_research_record("2026-07-12T00:03:00Z")
                run_dir = Path(started["run_dir"])
                if corruption == "research_record":
                    record_path = run_dir / "research_record.json"
                    payload = json.loads(record_path.read_text(encoding="utf-8"))
                    payload["run_id"] = "other-run"
                    record_path.write_text(json.dumps(payload), encoding="utf-8")
                elif corruption == "candidate_artifacts":
                    gate_path = run_dir / "candidate_gate.json"
                    gate_rows = json.loads(gate_path.read_text(encoding="utf-8"))
                    gate_rows[0]["source_run_id"] = "other-run"
                    gate_path.write_text(json.dumps(gate_rows), encoding="utf-8")
                    for filename in ("approval.jsonl", "approved_candidates.jsonl"):
                        path = run_dir / filename
                        row = json.loads(path.read_text(encoding="utf-8"))
                        row["source_run_id"] = "other-run"
                        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
                else:
                    state_path = run_dir / "run_state.json"
                    state = load_run_state(state_path)
                    write_run_state(
                        state_path, replace(state, status="completed_with_warnings")
                    )
                    (run_dir / "research_record.json").unlink()
                before = self.candidate_artifact_bytes(run_dir)

                with self.assertRaisesRegex(ValueError, "consistency diagnostics"):
                    orchestrator.update_candidate_status(
                        "c1",
                        1,
                        "h1",
                        "manually_submitted",
                        "2026-07-12T00:04:00Z",
                        source_run_id=str(started["run_id"]),
                    )

                self.assertEqual(self.candidate_artifact_bytes(run_dir), before)

    def test_candidate_gate_diagnostics_pause_before_writing_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            run_dir = Path(started["run_dir"])
            (run_dir / "test_evidence" / "backtest.json").unlink()

            with self.assertRaisesRegex(ValueError, "consistency diagnostics"):
                orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")

            state = load_run_state(run_dir / "run_state.json")
            artifact_exists = {
                name: (run_dir / name).exists()
                for name in (
                    "candidate_gate.json", "approval.jsonl", "approved_candidates.jsonl"
                )
            }

        self.assertEqual(state.status, "paused")
        self.assertIn(
            "missing_stage_evidence:backtest", state.stages["candidate_gate"].blocker
        )
        self.assertFalse(any(artifact_exists.values()))

    def test_approval_diagnostics_reject_before_writing_approval_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
                "expression_hash": "h1", "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval([candidate], "2026-07-12T00:03:00Z")
            run_dir = Path(started["run_dir"])
            (run_dir / "test_evidence" / "backtest.json").unlink()

            with self.assertRaisesRegex(ValueError, "consistency diagnostics"):
                orchestrator.approve_candidates(["c1"], "2026-07-12T00:04:00Z", "user")

            state = load_run_state(run_dir / "run_state.json")
            approval_exists = (run_dir / "approval.jsonl").exists()
            queue_exists = (run_dir / "approved_candidates.jsonl").exists()

        self.assertEqual(state.status, "waiting_for_user")
        self.assertFalse(approval_exists)
        self.assertFalse(queue_exists)
