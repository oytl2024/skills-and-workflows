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
        self.assertIn("Research Start", html)
        self.assertIn("Knowledge Maintenance", html)
        self.assertIn("Workflow Progress", html)
        self.assertIn("Power Pool", html)

    def test_render_dashboard_uses_selectable_option_cards_without_manual_option_id_input(self):
        state = {
            "readiness": {"exists": True, "passed": True, "blocked": False},
            "freshness": {"exists": True, "valid": True, "record_count": 6, "stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120, "scope_count": 4, "data_set_count": 8, "error_count": 0, "status": "completed"},
            "option_cards": [{"title": "Power Pool", "primary_incentive": "power_pool", "candidate_scope": "USA D1 TOP3000", "score": {"total": 9.0}}],
            "schedule": {"preview": "# Schedule"},
            "jobs": [],
            "proposal_counts": {},
            "active_workflow": {"exists": False},
            "approved_queue": [],
            "queue_diagnostics": [],
            "workflow_events": [],
        }

        html = render_dashboard(state)

        self.assertIn('type="radio"', html)
        self.assertIn('name="selected_option_id"', html)
        self.assertIn('value="option-1"', html)
        self.assertIn('value="workflow-start-from-option"', html)
        self.assertNotIn('<input name="objective"', html)
        self.assertNotIn('type="text" name="selected_option_id"', html)

    def test_render_dashboard_exposes_data_capture_and_compile_controls(self):
        state = {
            "readiness": {"exists": True, "passed": False, "blocked": True},
            "freshness": {"exists": True, "valid": True, "record_count": 6, "stale_count": 1, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120, "scope_count": 4, "data_set_count": 8, "error_count": 0, "status": "completed"},
            "option_cards": [],
            "schedule": {"preview": ""},
            "jobs": [],
            "proposal_counts": {},
            "active_workflow": {"exists": False},
            "approved_queue": [],
            "queue_diagnostics": [],
            "workflow_events": [],
        }

        html = render_dashboard(state)

        self.assertIn('value="capture-platform-data-fields"', html)
        self.assertIn('value="compile-data-ledger"', html)
        self.assertIn('name="enable_live_api"', html)
        self.assertIn("120", html)

    def test_render_proposals_uses_select_controls_for_structured_fields(self):
        html = render_proposals([])

        self.assertIn("<select name=\"issue_type\"", html)
        self.assertIn("<select name=\"affected_modules\"", html)
        self.assertIn("template_innovation", html)
        self.assertIn("data_coverage", html)

    def test_second_fallback_option_survives_invalid_jsonl_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            artifact = paths.knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("{}\n", encoding="utf-8")
            maintenance = paths.knowledge_root / "wiki" / "80_maintenance"
            maintenance.mkdir(parents=True)
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps(
                    [
                        {"name": name, "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7}
                        for name in ("data_ledger", "template_library", "benchmark_rules", "activity_snapshot", "operator_catalog", "research_option_cards")
                    ]
                ),
                encoding="utf-8",
            )
            decisions = paths.knowledge_root / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps({"title": "First objective"}) + "\n\nnot-json\n" + json.dumps({"title": "Second objective"}) + "\n",
                encoding="utf-8",
            )
            html = render_dashboard({"option_cards": [{"title": "First objective"}, {"title": "Second objective"}]})
            command = build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-2"})

        self.assertIn('value="option-2"', html)
        self.assertIn("Second objective", command)

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

    def test_build_action_command_starts_workflow_from_selected_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            artifact = paths.knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("{}\n", encoding="utf-8")
            maintenance = paths.knowledge_root / "wiki" / "80_maintenance"
            maintenance.mkdir(parents=True)
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps(
                    [
                        {"name": "data_ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                        {"name": "template_library", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                        {"name": "benchmark_rules", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                        {"name": "activity_snapshot", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                        {"name": "operator_catalog", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                        {"name": "research_option_cards", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                    ]
                ),
                encoding="utf-8",
            )
            decisions = paths.knowledge_root / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps({"title": "Power Pool", "primary_incentive": "power_pool"}) + "\n",
                encoding="utf-8",
            )

            command = build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1"})

        self.assertIn("workflow-start", command)
        self.assertIn("--selected-option-id", command)
        self.assertIn("option-1", command)
        self.assertIn("--objective", command)
        self.assertIn("Power Pool", command)

    def test_build_action_command_refuses_data_capture_without_live_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            with self.assertRaisesRegex(ValueError, "enable_live_api"):
                build_action_command("capture-platform-data-fields", paths, {})

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
