import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

from wqb.console_server import _render_workflow_progress, _workflow_action_state, _workflow_action_hash, assert_workflow_action_current
from wqb.console_state import ConsolePaths, load_runtime_state
from wqb.runtime_control import request_runtime_state, update_runtime_status


class MaintenanceNotificationConsoleTests(unittest.TestCase):
    def test_console_start_schedules_only_one_nonblocking_notification_pass(self):
        """Input: mocked local server. Output: assertions. Startup compensates once, never by recurring model polling."""
        from types import SimpleNamespace
        from unittest.mock import Mock
        from wqb.console_server import run_console
        from wqb.maintenance_notifications import dispatch_startup_notifications
        server = SimpleNamespace(server_address=("127.0.0.1", 8765), serve_forever=Mock(), server_close=Mock())
        paths = SimpleNamespace(runs_root=Path("runs"))
        with patch("wqb.console_server.default_console_paths", return_value=paths), \
             patch("wqb.console_server.make_console_server", return_value=server), \
             patch("wqb.console_server.threading.Thread") as worker:
            run_console(open_browser=False)
        worker.assert_called_once_with(target=dispatch_startup_notifications, args=(paths.runs_root,),
                                       name="maintenance-startup-notice", daemon=True)
        worker.return_value.start.assert_called_once()
        server.serve_forever.assert_called_once()
        server.server_close.assert_called_once()

    def test_stale_verification_is_not_misreported_as_failed_transport(self):
        """Input: stale proof projection dict. Output: assertions. Keep proof and transport failure distinct."""
        state = {"active_workflow": {"exists": True}, "runtime_control": {
            "recovery_case": {"status": "awaiting_maintenance_confirmation",
                "verification_error": "maintenance_verification_stale",
                "notification": {"status": "not_requested"}}}}
        rendered = _render_workflow_progress(state)
        self.assertIn("Maintenance verification is outdated", rendered)
        self.assertIn("No maintenance-chat delivery attempted", rendered)
        self.assertNotIn("delivery failed", rendered)
        self.assertFalse(_workflow_action_state(state)["continue_workflow"])

    def test_invalid_fresh_status_preserves_confirmation_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = ConsolePaths(root, root, root / "knowledge", root / "runs", root / "milestone.md", root / "todo.md", root / "jobs")
            run = paths.runs_root / "run"
            request_runtime_state(run, "running")
            case = {"case_id": "a" * 24, "category": "code_or_contract", "status": "awaiting_maintenance_confirmation", "notification": {"status": "pending"}}
            update_runtime_status(run, recovery_case=case)
            evidence = run / "runtime" / "recovery"
            evidence.mkdir(parents=True)
            (evidence / (case["case_id"] + ".json")).write_text(json.dumps({**case, "status": ""}))
            with patch("wqb.console_state._active_workflow_summary", return_value=({"exists": True, "current_stage": "repair"}, run)):
                state = load_runtime_state(paths)
            self.assertFalse(_workflow_action_state(state)["continue_workflow"])

    def test_resume_post_cannot_bypass_confirmation(self):
        state = {"active_workflow": {"exists": True}, "runtime_control": {"request_revision": "r1",
            "recovery_case": {"status": "awaiting_maintenance_confirmation"}}}
        form = {"action": "workflow-auto-continue", "state_hash": _workflow_action_hash(state), "expected_runtime_revision": "r1"}
        with self.assertRaises(ValueError):
            assert_workflow_action_current(form, state)

    def test_approved_repair_still_blocks_resume_until_verified(self):
        state = {"active_workflow": {"exists": True}, "runtime_control": {
            "recovery_case": {"status": "maintenance_approved"}}}
        self.assertFalse(_workflow_action_state(state)["continue_workflow"])

    def test_pending_delivery_is_visible_and_cannot_resume(self):
        state = {"active_workflow": {"exists": True, "run_id": "test"},
                 "runtime_control": {"status": "blocked", "desired_state": "running",
                    "recovery_case": {"case_id": "a" * 24, "status": "awaiting_maintenance_confirmation",
                                      "notification": {"status": "pending"}}}}
        self.assertFalse(_workflow_action_state(state)["continue_workflow"])
        rendered = _render_workflow_progress(state)
        self.assertIn("Waiting for maintenance-chat delivery", rendered)
        self.assertIn("human confirmation", rendered)

    def test_delivery_uncertainty_and_receipt_have_distinct_labels(self):
        for status, label in (("claimed", "Delivery uncertain"), ("notified", "Maintenance chat notified")):
            with self.subTest(status=status):
                state = {"active_workflow": {"exists": True}, "runtime_control": {
                    "recovery_case": {"status": "awaiting_maintenance_confirmation", "notification": {"status": status}}}}
                self.assertIn(label, _render_workflow_progress(state))
