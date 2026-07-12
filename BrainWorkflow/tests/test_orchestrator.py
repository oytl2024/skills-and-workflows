import tempfile
import unittest
from pathlib import Path

from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
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
