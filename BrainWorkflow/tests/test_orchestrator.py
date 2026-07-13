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
    record_queue_update,
    write_research_record,
)
from wqb.workflow_events import append_workflow_event, read_workflow_events
from wqb.workflow_state import (
    WorkflowStageState,
    load_active_run,
    load_run_state,
    transition_run_state,
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

    def test_candidate_approval_rejects_ambiguous_duplicate_candidate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            base = {
                "candidate_id": "c1", "platform_alpha_id": "a1",
                "source_run_id": started["run_id"], "hard_pass": True,
            }
            self.advance_to_candidate_gate(started)
            orchestrator.request_candidate_approval(
                [dict(base, version=1, expression_hash="h1"), dict(base, version=2, expression_hash="h2")],
                "2026-07-12T00:10:00Z",
            )

            with self.assertRaisesRegex(ValueError, "ambiguous candidate ID"):
                orchestrator.approve_candidates(["c1"], "2026-07-12T00:11:00Z", "user")

            self.assertEqual(load_approvals(Path(started["run_dir"])), [])

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

    def test_candidate_status_event_dedupe_allows_a_later_real_transition(self):
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
            orchestrator.update_candidate_status(
                "c1", 1, "h1", "queued", "2026-07-12T00:04:00Z"
            )
            orchestrator.update_candidate_status(
                "c1", 1, "h1", "manually_submitted", "2026-07-12T00:05:00Z"
            )
            events = [
                event.payload["status"]
                for event in read_workflow_events(Path(started["run_dir"]))
                if event.event_type == "candidate_status_updated"
            ]

        self.assertEqual(events, ["manually_submitted", "queued", "manually_submitted"])

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
