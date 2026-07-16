import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb.console_server import build_action_command, create_console_proposal, make_console_server, render_dashboard, render_proposals, run_console_action
from wqb.console_state import ConsolePaths


def make_paths(root: Path) -> ConsolePaths:
    """Input: temp root. Output: ConsolePaths. Create a server path fixture."""
    return ConsolePaths(root, root / "BrainWorkflow", root / "knowledge", root / "runs", root / "milestone.md", root / "todo.md", root / "runs" / "console_jobs")


class ConsoleServerTests(unittest.TestCase):
    def test_render_dashboard_exposes_research_progress_and_knowledge_controls(self):
        state = {
            "readiness": {"exists": True, "passed": True, "blocked": False},
            "freshness": {"exists": True, "stale_count": 0, "missing_count": 0},
            "option_cards": [{"title": "Power Pool"}],
            "schedule": {"preview": "# Schedule"},
            "jobs": [{"job_id": "job1", "status": "completed", "action": "readiness-check"}],
            "proposal_counts": {"proposed": 1},
            "active_workflow": {"exists": False},
            "approved_queue": [],
            "queue_diagnostics": [],
        }

        html = render_dashboard(state)

        self.assertIn("Workflow Console", html)
        self.assertIn("Research Control", html)
        self.assertIn("Knowledge Maintenance", html)
        self.assertIn("Research Progress", html)
        self.assertIn("Power Pool", html)

    def test_render_proposals_includes_input_form(self):
        html = render_proposals([{"proposal_id": "p1", "title": "Improve template", "status": "proposed"}])

        self.assertIn("Workflow Proposal Inbox", html)
        self.assertIn("textarea", html)
        self.assertIn("Improve template", html)

    def test_build_action_command_refuses_research_start_when_knowledge_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            maintenance = root / "knowledge" / "wiki" / "80_maintenance"
            maintenance.mkdir(parents=True)
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps([{"name": "data_ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-01-01", "max_age_days": 1}]),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "knowledge maintenance"):
                build_action_command("workflow-start", paths, {"objective": "Power Pool", "selected_option_id": "option-1"})

    def test_build_action_command_refuses_research_start_when_freshness_manifest_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            maintenance = root / "knowledge" / "wiki" / "80_maintenance"
            maintenance.mkdir(parents=True)
            (maintenance / "freshness_manifest.json").write_text("{not-json}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "knowledge maintenance"):
                build_action_command("workflow-start", paths, {"objective": "Power Pool", "selected_option_id": "option-1"})

            (maintenance / "freshness_manifest.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "knowledge maintenance"):
                build_action_command("workflow-start", paths, {"objective": "Power Pool", "selected_option_id": "option-1"})

    def test_build_action_command_refuses_research_start_when_manifest_missing_required_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            maintenance = root / "knowledge" / "wiki" / "80_maintenance"
            artifact = root / "knowledge" / "wiki" / "20_semantics" / "data_ledger.jsonl"
            maintenance.mkdir(parents=True)
            artifact.parent.mkdir(parents=True)
            artifact.write_text("{}\n", encoding="utf-8")
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps([{"name": "data_ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7}]),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "knowledge maintenance"):
                build_action_command("workflow-start", paths, {"objective": "Power Pool", "selected_option_id": "option-1"})

    def test_build_action_command_requires_live_checkbox_for_platform_option_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            with self.assertRaisesRegex(ValueError, "enable_live_api"):
                build_action_command("plan-research-options", paths, {})

            command = build_action_command("plan-research-options", paths, {"enable_live_api": "on"})

        self.assertIn("plan-research-options", command)
        self.assertIn("--enable-live-api", command)

    def test_refused_action_writes_durable_job_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)

            completed = run_console_action(paths, {"action": "plan-research-options"})
            jobs = list(paths.job_root.glob("*/job.json"))
            milestone = paths.milestone_path.read_text(encoding="utf-8")

        self.assertEqual(completed.status, "refused")
        self.assertEqual(len(jobs), 1)
        self.assertIn("enable_live_api", completed.error)
        self.assertIn("Console Job Context", milestone)

    def test_run_console_action_finalizes_job_when_runner_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)

            with patch("wqb.console_server.run_job", side_effect=RuntimeError("runner failed")):
                completed = run_console_action(paths, {"action": "knowledge-health-check"})
            payload = json.loads(next(paths.job_root.glob("*/job.json")).read_text(encoding="utf-8"))
            milestone = paths.milestone_path.read_text(encoding="utf-8")

        self.assertEqual(completed.status, "failed")
        self.assertEqual(payload["status"], "failed")
        self.assertIn("runner failed", completed.error)
        self.assertIn("Console Job Context", milestone)

    def test_proposal_creation_writes_durable_job_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)

            completed = create_console_proposal(paths, {"summary": "Improve novelty.", "issue_type": "template_innovation"})
            proposal_path = paths.knowledge_root / "wiki" / "70_decisions" / "workflow_change_proposals.jsonl"
            jobs = list(paths.job_root.glob("*/job.json"))
            proposal_exists = proposal_path.exists()

        self.assertEqual(completed.status, "completed")
        self.assertTrue(proposal_exists)
        self.assertEqual(len(jobs), 1)

    def test_make_console_server_constructs_local_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            class FakeServer:
                def __init__(self, address, handler):
                    self.server_address = address
                    self.handler = handler

                def server_close(self):
                    return None

            with patch("wqb.console_server.ThreadingHTTPServer", FakeServer):
                server = make_console_server("127.0.0.1", 0, make_paths(Path(tmp)))

            self.assertEqual(server.server_address[0], "127.0.0.1")
            self.assertTrue(hasattr(server, "console_paths"))


if __name__ == "__main__":
    unittest.main()
