import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wqb.maintenance_resolution import approve_repair, verify_and_resolve
from wqb.recovery_cases import classify_blocker, ensure_recovery_case, advance_scripted_recovery, read_current_recovery_case
from wqb.runtime_control import request_runtime_state, read_runtime_control, update_runtime_status
from wqb.workflow_driver import run_workflow_driver


class MaintenanceResolutionTests(unittest.TestCase):
    def test_verified_code_repair_cannot_clear_simulation_or_round_boundaries(self):
        """Input: valid code proof at true resource limit. Output: assertions. Verification is not renewal authority."""
        approved = approve_repair(self.run, self.case['case_id'], 'human-confirmation')
        for reason in ('research_simulation_budget_exhausted', 'research_round_budget_exhausted'):
            with self.subTest(reason=reason):
                update_runtime_status(self.run, status='blocked', reason=reason, simulation_attempts=30)
                with patch('wqb.maintenance_resolution.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', 'Ran 12 tests in 1s\nOK\n')):
                    verify_and_resolve(self.run, self.case['case_id'], approved['repair_approval']['approval_id'])
                self.assertEqual(read_runtime_control(self.run)['status'], 'blocked')
                self.assertEqual(read_runtime_control(self.run)['reason'], reason)

    def test_verified_planning_release_failure_can_replay_without_reverification(self):
        """Input: passed proof with interrupted release hook. Output: assertions. Replay local release without tests, Start or budget changes."""
        case = ensure_recovery_case(self.run, classify_blocker({
            'next_action': 'research-loop-blocked', 'current_stage': 'scout_seed',
            'stop_reason': 'research_planning_blocked', 'message': 'empty'}), 'now')
        case = advance_scripted_recovery(self.run, case, {}, 'now')
        update_runtime_status(self.run, recovery_case=case)
        approved = approve_repair(self.run, case['case_id'], 'confirmed')
        approval = approved['repair_approval']['approval_id']
        result = subprocess.CompletedProcess([], 0, '', 'Ran 12 tests in 1s\nOK\n')
        with patch('wqb.maintenance_resolution.subprocess.run', return_value=result), \
             patch('wqb.research_planning.release_verified_planning_stop', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                verify_and_resolve(self.run, case['case_id'], approval)
        before = (self.run / 'runtime_control.json').read_bytes()
        with patch('wqb.maintenance_resolution.subprocess.run') as execute, \
             patch('wqb.research_planning.release_verified_planning_stop', return_value=True) as release:
            resolved = verify_and_resolve(self.run, case['case_id'], approval)
        self.assertEqual(resolved['status'], 'resolved')
        self.assertEqual(release.call_count, 1)
        execute.assert_not_called()
        self.assertEqual((self.run / 'runtime_control.json').read_bytes(), before)

    def test_verified_code_fix_does_not_clear_exhausted_runtime_boundary(self):
        approved = approve_repair(self.run, self.case['case_id'], 'human-confirmation')
        update_runtime_status(self.run, status='blocked', reason='runtime_budget_exhausted', elapsed_seconds=21601)
        with patch('wqb.maintenance_resolution.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', 'Ran 12 tests in 1s\nOK\n')):
            verify_and_resolve(self.run, self.case['case_id'], approved['repair_approval']['approval_id'])
        control = read_runtime_control(self.run)
        self.assertEqual(control['status'], 'blocked')
        self.assertEqual(control['reason'], 'runtime_budget_exhausted')
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.run = Path(self.directory.name) / "run"
        request_runtime_state(self.run, "running", enable_live_api=False, max_simulations=30)
        self.blocker = classify_blocker({"next_action": "no_progress_detected"})
        self.case = ensure_recovery_case(self.run, self.blocker, "created")
        self.case = advance_scripted_recovery(self.run, self.case, {}, "routed")
        update_runtime_status(self.run, recovery_case=self.case)

    def test_receipt_alone_cannot_resolve_or_start_verification(self):
        with patch("wqb.maintenance_resolution.subprocess.run") as execute:
            with self.assertRaises(ValueError):
                verify_and_resolve(self.run, self.case["case_id"], "not-an-approval")
        execute.assert_not_called()

    def test_source_change_or_timeout_does_not_resolve(self):
        approved = approve_repair(self.run, self.case["case_id"], "human-confirmation-1")
        with patch("wqb.maintenance_resolution._code_digest", side_effect=["before", "after"]):
            with patch("wqb.maintenance_resolution.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "Ran 12 tests in 1s\nOK\n")):
                with self.assertRaises(ValueError):
                    verify_and_resolve(self.run, self.case["case_id"], approved["repair_approval"]["approval_id"])
        with patch("wqb.maintenance_resolution.subprocess.run", side_effect=subprocess.TimeoutExpired("tests", 600)):
            with self.assertRaises(subprocess.TimeoutExpired):
                verify_and_resolve(self.run, self.case["case_id"], approved["repair_approval"]["approval_id"])
        receipt = json.loads((self.run / "runtime" / "maintenance_verification" / (self.case["case_id"] + ".json")).read_text())
        self.assertEqual(receipt["status"], "failed")

    def test_approval_cannot_replace_another_active_blocker(self):
        update_runtime_status(self.run, recovery_case={"case_id": "b" * 24, "status": "awaiting_maintenance_confirmation"})
        with self.assertRaises(ValueError):
            approve_repair(self.run, self.case["case_id"], "human-confirmation-1")

    def test_incomplete_resolution_receipt_cannot_unblock(self):
        case_path = self.run / "runtime" / "recovery" / (self.case["case_id"] + ".json")
        case_path.write_text(json.dumps({**self.case, "status": "resolved"}))
        receipt = self.run / "runtime" / "maintenance_verification" / (self.case["case_id"] + ".json")
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"case_id": self.case["case_id"], "status": "passed", "code_unchanged": True, "tests_run": 12}))
        self.assertEqual(read_current_recovery_case(self.run)["status"], "awaiting_maintenance_confirmation")

    def test_changed_source_invalidates_resolution(self):
        approved = approve_repair(self.run, self.case["case_id"], "human-confirmation-1")
        with patch("wqb.maintenance_resolution.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "Ran 12 tests in 1s\nOK\n")):
            verify_and_resolve(self.run, self.case["case_id"], approved["repair_approval"]["approval_id"])
        with patch("wqb.maintenance_resolution._code_digest", return_value="different-source"):
            projected = read_current_recovery_case(self.run)
        self.assertEqual(projected["status"], "awaiting_maintenance_confirmation")
        self.assertEqual(projected["verification_error"], "maintenance_verification_stale")
        self.assertEqual(projected["notification"]["status"], "not_requested")
        self.assertNotEqual(projected["notification"].get("error"), "queue_process_not_started")
        from wqb.recovery_cases import verification_notification_path
        path = verification_notification_path(self.run, self.case["case_id"], "different-source")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"case_id": self.case["case_id"], "code_digest": "different-source", "status": "queued"}))
        with patch("wqb.maintenance_resolution._code_digest", return_value="different-source"):
            self.assertEqual(read_current_recovery_case(self.run)["notification"]["status"], "queued")
        with patch("wqb.maintenance_resolution._code_digest", return_value="newer-source"):
            self.assertEqual(read_current_recovery_case(self.run)["notification"]["status"], "not_requested")

    def test_missing_or_malformed_digest_is_invalid_not_stale(self):
        """Input: otherwise passed proof with invalid saved hash. Output: assertions. Never trigger stale-source delivery."""
        approved = approve_repair(self.run, self.case["case_id"], "human-confirmation")
        with patch("wqb.maintenance_resolution.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "Ran 12 tests in 1s\nOK\n")):
            verify_and_resolve(self.run, self.case["case_id"], approved["repair_approval"]["approval_id"])
        path = self.run / "runtime/maintenance_verification" / (self.case["case_id"] + ".json")
        original = json.loads(path.read_text())
        for digest in (None, "", "bad", "z" * 64):
            with self.subTest(digest=digest):
                path.write_text(json.dumps({**original, "code_digest": digest}))
                current = read_current_recovery_case(self.run)
                self.assertEqual(current["verification_error"], "maintenance_verification_invalid")
                self.assertEqual(current["notification"]["status"], "not_requested")

    def test_pause_does_not_cancel_unresolved_code_blocker(self):
        request_runtime_state(self.run, "paused")
        paused = advance_scripted_recovery(self.run, self.case, {}, "paused")
        update_runtime_status(self.run, recovery_case=paused)
        request_runtime_state(self.run, "running")
        status = {"active": True, "run_dir": str(self.run)}
        with patch("tests.test_maintenance_resolution.approve_repair"):
            step = unittest.mock.Mock(return_value={**status, "status": "completed"})
            result = run_workflow_driver(SimpleNamespace(), {}, step=step, status_reader=lambda: status)
        step.assert_not_called()
        self.assertEqual(result["runtime_status"], "blocked")
        approved = approve_repair(self.run, self.case["case_id"], "human-confirmation-after-pause")
        self.assertEqual(approved["status"], "maintenance_approved")

    def test_stale_resolution_can_be_explicitly_reopened_without_overwriting_history(self):
        approved = approve_repair(self.run, self.case["case_id"], "human-confirmation-1")
        with patch("wqb.maintenance_resolution.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "Ran 12 tests in 1s\nOK\n")):
            resolved = verify_and_resolve(self.run, self.case["case_id"], approved["repair_approval"]["approval_id"])
        with patch("wqb.maintenance_resolution._code_digest", return_value="changed-source"):
            reopened = approve_repair(self.run, self.case["case_id"], "human-confirmation-reverify")
        self.assertNotEqual(reopened["case_id"], resolved["case_id"])
        self.assertNotEqual(reopened["repair_approval"]["approval_id"], approved["repair_approval"]["approval_id"])
        path = self.run / "runtime" / "recovery" / (resolved["case_id"] + ".json")
        self.assertEqual(json.loads(path.read_text())["status"], "resolved")

    def test_verified_resolution_allows_explicit_driver_execution(self):
        approved = approve_repair(self.run, self.case["case_id"], "human-confirmation-1")
        with patch("wqb.maintenance_resolution.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "Ran 12 tests in 1s\nOK\n")):
            verify_and_resolve(self.run, self.case["case_id"], approved["repair_approval"]["approval_id"])
        status = {"active": True, "run_dir": str(self.run)}
        step = unittest.mock.Mock(return_value={**status, "status": "completed"})
        result = run_workflow_driver(SimpleNamespace(), {}, step=step, status_reader=lambda: status)
        self.assertEqual(step.call_count, 1)
        self.assertEqual(result["runtime_status"], "completed")

    def test_passed_verification_resolves_without_changing_pause_or_budget(self):
        approved = approve_repair(self.run, self.case["case_id"], "human-confirmation-1")
        request_runtime_state(self.run, "paused")
        before = read_runtime_control(self.run)
        with patch("wqb.maintenance_resolution.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "Ran 12 tests in 1.0s\n\nOK\n")):
            resolved = verify_and_resolve(self.run, self.case["case_id"], approved["repair_approval"]["approval_id"])
        self.assertEqual(resolved["status"], "resolved")
        self.assertFalse(resolved["patch_execution_allowed"])
        after = read_runtime_control(self.run)
        for key in ("desired_state", "enable_live_api", "max_simulations", "request_revision"):
            self.assertEqual(before[key], after[key])

    def test_failed_or_zero_test_verification_keeps_case_blocked(self):
        for exit_code, stderr in ((1, "FAILED"), (0, "Ran 0 tests in 0s\nOK")):
            with self.subTest(exit_code=exit_code):
                approved = approve_repair(self.run, self.case["case_id"], "human-confirmation-1")
                with patch("wqb.maintenance_resolution.subprocess.run", return_value=subprocess.CompletedProcess([], exit_code, "", stderr)):
                    with self.assertRaises(ValueError):
                        verify_and_resolve(self.run, self.case["case_id"], approved["repair_approval"]["approval_id"])
                path = self.run / "runtime" / "recovery" / (self.case["case_id"] + ".json")
                self.assertEqual(json.loads(path.read_text())["status"], "maintenance_approved")

    def test_new_occurrence_after_resolution_gets_new_case_and_notification(self):
        approved = approve_repair(self.run, self.case["case_id"], "human-confirmation-1")
        with patch("wqb.maintenance_resolution.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "Ran 12 tests in 1.0s\nOK\n")):
            verify_and_resolve(self.run, self.case["case_id"], approved["repair_approval"]["approval_id"])
        second = ensure_recovery_case(self.run, self.blocker, "new-failure")
        second = advance_scripted_recovery(self.run, second, {}, "new-route")
        self.assertNotEqual(second["case_id"], self.case["case_id"])
        self.assertEqual(second["notification"]["status"], "pending")
