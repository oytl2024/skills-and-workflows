import json
import tempfile
import unittest
from pathlib import Path

from wqb.candidate_queue import load_approved_queue, load_approvals
from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
from wqb.research_record import load_research_record
from wqb.workflow_events import read_workflow_events
from wqb.workflow_state import load_active_run, load_run_state


class WorkflowOrchestratorTests(unittest.TestCase):
    def paths(self, root: Path) -> OrchestratorPaths:
        return OrchestratorPaths(
            project_root=root,
            workflow_root=root / "BrainWorkflow",
            knowledge_root=root / "knowledge",
            run_root=root / "runs",
        )

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

        self.assertEqual(status["next_action"], "workflow-start")
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
            }
            second_candidate = {
                "candidate_id": "c2",
                "platform_alpha_id": "a2",
                "version": 1,
                "expression_hash": "h2",
                "source_run_id": started["run_id"],
            }
            gate = orchestrator.request_candidate_approval(
                [first_candidate, second_candidate], "2026-07-12T00:10:00Z"
            )
            approved = orchestrator.approve_candidates(["c1"], "2026-07-12T00:11:00Z", "user")
            retry = orchestrator.approve_candidates(["c1"], "2026-07-12T00:12:00Z", "user")
            run_dir = Path(started["run_dir"])
            state = load_run_state(run_dir / "run_state.json")
            record = load_research_record(run_dir / "research_record.json")
            candidates = json.loads((run_dir / "candidate_gate.json").read_text(encoding="utf-8"))
            approvals = load_approvals(run_dir)
            queue = load_approved_queue(run_dir)
            events = read_workflow_events(run_dir)

        self.assertEqual(gate["status"], "waiting_for_user")
        self.assertEqual(approved["queued_count"], 1)
        self.assertEqual(retry["queued_count"], 0)
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
            }
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
