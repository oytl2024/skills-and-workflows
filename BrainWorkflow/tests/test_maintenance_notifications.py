import tempfile
import unittest
import json
import subprocess
from unittest.mock import patch
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from wqb.maintenance_notifications import list_notifications, transition_notification, dispatch_notification
from wqb.recovery_cases import classify_blocker, ensure_recovery_case, advance_scripted_recovery
from wqb.runtime_control import request_runtime_state


class MaintenanceNotificationTests(unittest.TestCase):
    def test_startup_routes_stale_proof_once_without_resuming_paused_run(self):
        """Input: paused run with stale verification. Output: assertions. Startup queues one evidence-only notice."""
        from types import SimpleNamespace
        from wqb.maintenance_notifications import dispatch_startup_notifications
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "maintenance_channel.json").write_text(json.dumps({"thread_id": "019f0c94-8cad-74f1-9fd5-14952c1f38b3"}))
            run = root / "run"
            case = self.make_request(run)
            request_runtime_state(run, "paused")
            before = (run / "runtime_control.json").read_bytes()
            case_file = run / "runtime/recovery" / (case["case_id"] + ".json")
            evidence_before = case_file.read_bytes()
            projected = {**case, "verification_error": "maintenance_verification_stale",
                         "verification_code_digest": "a" * 64,
                         "notification": {"status": "not_requested"}}
            with patch("wqb.workflow_state.discover_active_workflow", return_value=SimpleNamespace(run_dir=run)), \
                 patch("wqb.maintenance_notifications.read_current_recovery_case", return_value=projected), \
                 patch("wqb.maintenance_notifications.shutil.which", return_value="codex.exe"), \
                 patch("wqb.maintenance_notifications.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as send:
                first = dispatch_startup_notifications(root)
                second = dispatch_startup_notifications(root)
            self.assertEqual(first["status"], "queued")
            self.assertEqual(second["status"], "queued")
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.args[0][1], "queue")
            self.assertIn("NOT repair or renewal authorization", send.call_args.args[0][-1])
            self.assertEqual((run / "runtime_control.json").read_bytes(), before)
            self.assertEqual(case_file.read_bytes(), evidence_before)
            from wqb.maintenance_notifications import acknowledge_verification_notification
            rows = list_notifications(root)
            notices = [row for row in rows if row.get("notification_kind") == "verification_stale"]
            self.assertEqual(len(notices), 1)
            self.assertEqual(notices[0]["code_digest"], "a" * 64)
            acknowledged = acknowledge_verification_notification(run, case["case_id"], "a" * 64, "receipt")
            self.assertTrue(acknowledged["changed"])
            self.assertFalse(acknowledge_verification_notification(run, case["case_id"], "a" * 64, "again")["changed"])
            self.assertEqual(case_file.read_bytes(), evidence_before)
            self.assertEqual((run / "runtime_control.json").read_bytes(), before)
            self.assertFalse(any(row.get("notification_kind") == "verification_stale" for row in list_notifications(root)))

    def test_startup_timeout_is_not_replayed_or_mistaken_for_success(self):
        """Input: uncertain startup transport. Output: assertions. Persist uncertainty and never auto-replay."""
        from types import SimpleNamespace
        from wqb.maintenance_notifications import dispatch_startup_notifications
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "maintenance_channel.json").write_text(json.dumps({"thread_id": "019f0c94-8cad-74f1-9fd5-14952c1f38b3"}))
            run = root / "run"
            projected = {"case_id": "a" * 24, "verification_error": "maintenance_verification_stale",
                         "verification_code_digest": "b" * 64}
            with patch("wqb.workflow_state.discover_active_workflow", return_value=SimpleNamespace(run_dir=run)), \
                 patch("wqb.maintenance_notifications.read_current_recovery_case", return_value=projected), \
                 patch("wqb.maintenance_notifications.shutil.which", return_value="codex.exe"), \
                 patch("wqb.maintenance_notifications.subprocess.run", side_effect=subprocess.TimeoutExpired("queue", 15)) as send:
                first = dispatch_startup_notifications(root)
                second = dispatch_startup_notifications(root)
            self.assertEqual(first["status"], "delivery_uncertain")
            self.assertEqual(second["status"], "delivery_uncertain")
            self.assertEqual(send.call_count, 1)

    def test_startup_without_stale_proof_never_launches_transport(self):
        """Input: normal/invalid proof or no active run. Output: assertions. Only a known stale-source event is routable."""
        from types import SimpleNamespace
        from wqb.maintenance_notifications import dispatch_startup_notifications
        for run, case in ((None, {}), (Path("run"), {}),
                          (Path("run"), {"verification_error": "maintenance_evidence_invalid"})):
            with self.subTest(case=case), \
                 patch("wqb.workflow_state.discover_active_workflow", return_value=SimpleNamespace(run_dir=run)), \
                 patch("wqb.maintenance_notifications.read_current_recovery_case", return_value=case), \
                 patch("wqb.maintenance_notifications.subprocess.run") as send:
                self.assertEqual(dispatch_startup_notifications(Path("runs"))["status"], "not_needed")
                send.assert_not_called()

    def test_startup_receipt_wins_over_late_transport_completion(self):
        """Input: receipt acknowledged while queue exits. Output: assertions. Late completion never overwrites notified status."""
        from types import SimpleNamespace
        from wqb.maintenance_notifications import dispatch_startup_notifications, acknowledge_verification_notification
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "maintenance_channel.json").write_text(json.dumps({"thread_id": "019f0c94-8cad-74f1-9fd5-14952c1f38b3"}))
            run = root / "run"
            case_id, digest = "a" * 24, "b" * 64
            projected = {"case_id": case_id, "verification_error": "maintenance_verification_stale",
                         "verification_code_digest": digest}

            def receive(*args, **kwargs):
                """Input: mocked transport args. Output: CompletedProcess. Simulate receipt before process completion."""
                acknowledge_verification_notification(run, case_id, digest, "receipt")
                return subprocess.CompletedProcess([], 0)

            with patch("wqb.workflow_state.discover_active_workflow", return_value=SimpleNamespace(run_dir=run)), \
                 patch("wqb.maintenance_notifications.read_current_recovery_case", return_value=projected), \
                 patch("wqb.maintenance_notifications.shutil.which", return_value="codex.exe"), \
                 patch("wqb.maintenance_notifications.subprocess.run", side_effect=receive):
                self.assertEqual(dispatch_startup_notifications(root)["status"], "notified")

    def make_request(self, root, action="no_progress_detected"):
        """Input: run Path/action str. Output: dict. Create a synthetic code-blocker request."""
        request_runtime_state(root, "running")
        case = ensure_recovery_case(root, classify_blocker({"next_action": action}), "now")
        return advance_scripted_recovery(root, case, {}, "later")

    def test_restart_deduplicates_and_preserves_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            case = self.make_request(run)
            first = transition_notification(run, case["case_id"], "claim", "claimed-time")
            self.assertTrue(first["changed"])
            self.assertFalse(transition_notification(run, case["case_id"], "claim", "again")["changed"])
            advance_scripted_recovery(run, case, {}, "restart")
            rows = list_notifications(Path(directory))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["delivery_status"], "claimed")
            self.assertFalse(rows[0]["patch_execution_allowed"])
            transition_notification(run, case["case_id"], "acknowledge", "ack-time")
            self.assertEqual(list_notifications(Path(directory)), [])

    def test_acknowledgement_cannot_skip_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            case = self.make_request(run)
            result = transition_notification(run, case["case_id"], "acknowledge", "now")
            self.assertFalse(result["changed"])
            self.assertEqual(list_notifications(Path(directory))[0]["delivery_status"], "pending")

    def test_external_blocker_is_not_a_code_request(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_request(Path(directory) / "run", "rate-limit-wait")
            self.assertEqual(list_notifications(Path(directory)), [])

    def test_pause_prevents_new_claim_but_keeps_pending_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            case = self.make_request(run)
            request_runtime_state(run, "paused")
            self.assertFalse(transition_notification(run, case["case_id"], "claim", "now")["changed"])

    def test_invalid_identity_cannot_escape_case_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                transition_notification(Path(directory), "../secret", "claim", "now")

    def test_simultaneous_consumers_only_claim_once(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            case = self.make_request(run)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: transition_notification(run, case["case_id"], "claim", "now"), range(2)))
            self.assertEqual(sum(row["changed"] for row in results), 1)

    def test_event_delivery_queues_once_without_starting_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "maintenance_channel.json").write_text(json.dumps({"thread_id": "019f0c94-8cad-74f1-9fd5-14952c1f38b3"}))
            run = root / "run"
            case = self.make_request(run)
            with patch("wqb.maintenance_notifications.shutil.which", return_value="codex.exe"):
                with patch("wqb.maintenance_notifications.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as execute:
                    first = dispatch_notification(run, case, "now")
                    second = dispatch_notification(run, first, "again")
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.args[0][1], "queue")
            self.assertNotIn("exec", execute.call_args.args[0])
            self.assertEqual(second["notification"]["status"], "queued")

    def test_timeout_is_uncertain_and_never_auto_repeated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "maintenance_channel.json").write_text(json.dumps({"thread_id": "019f0c94-8cad-74f1-9fd5-14952c1f38b3"}))
            run = root / "run"
            case = self.make_request(run)
            with patch("wqb.maintenance_notifications.shutil.which", return_value="codex.exe"):
                with patch("wqb.maintenance_notifications.subprocess.run", side_effect=subprocess.TimeoutExpired("queue", 15)) as execute:
                    result = dispatch_notification(run, case, "now")
                    dispatch_notification(run, result, "again")
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(result["notification"]["status"], "delivery_uncertain")
            receipt = transition_notification(run, case["case_id"], "acknowledge", "receipt")
            self.assertTrue(receipt["changed"])
            self.assertFalse(receipt["patch_execution_allowed"])
