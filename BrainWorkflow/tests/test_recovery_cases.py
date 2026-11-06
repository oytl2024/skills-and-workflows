import json
import tempfile
import unittest
from pathlib import Path

from wqb.recovery_cases import classify_blocker, ensure_recovery_case, advance_scripted_recovery
from wqb.runtime_control import request_runtime_state


class RecoveryCasesTest(unittest.TestCase):
    def test_different_sources_and_unknown_attempts_have_distinct_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = []
            for source, hashes in (("source-a", ["a"]), ("source-b", ["a"]), ("source-b", ["b"])):
                blocker = classify_blocker({"next_action": "maintenance-blocker", "source_bridge": {
                    "source_run_id": source, "metadata": {"uncertain_expression_hashes": hashes}}})
                cases.append(ensure_recovery_case(root, blocker, "now")["case_id"])
            self.assertEqual(len(set(cases)), 3)

    def test_same_fault_is_one_durable_case_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_runtime_state(root, "running")
            blocker = classify_blocker({"next_action": "source-batch-runner-missing", "current_stage": "scout_seed"})
            first = ensure_recovery_case(root, blocker, "2026-10-11T00:00:00+00:00")
            second = ensure_recovery_case(root, blocker, "2026-10-11T01:00:00+00:00")
            self.assertEqual(first["case_id"], second["case_id"])
            self.assertEqual(first["created_at"], second["created_at"])
            self.assertEqual(len(list((root / "runtime" / "recovery").glob("*.json"))), 1)

    def test_unknown_submission_is_never_automatic_retry(self):
        blocker = classify_blocker({"next_action": "maintenance-blocker", "source_bridge": {
            "metadata": {"uncertain_submission_hashes": ["abc"]}}})
        self.assertEqual(blocker["category"], "reconciliation_required")

    def test_pause_wins_over_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_runtime_state(root, "running")
            case = ensure_recovery_case(root, classify_blocker({"next_action": "no_progress_detected"}), "now")
            request_runtime_state(root, "paused")
            result = advance_scripted_recovery(root, case, {}, "later")
            self.assertEqual(result["status"], "paused")
            self.assertEqual(result["attempts"], 0)

    def test_unavailable_sandbox_does_not_enable_patch_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_runtime_state(root, "running")
            case = ensure_recovery_case(root, classify_blocker({"next_action": "source-batch-runner-missing"}), "now")
            result = advance_scripted_recovery(root, case, {}, "later")
            self.assertEqual(result["status"], "awaiting_maintenance_confirmation")
            self.assertFalse(result["patch_execution_allowed"])
            self.assertEqual(result["notification"]["status"], "pending")
            self.assertEqual(result["reason"], "human_confirmation_required_before_code_repair")

    def test_invalid_case_is_preserved_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocker = classify_blocker({"next_action": "no_progress_detected"})
            case = ensure_recovery_case(root, blocker, "now")
            path = root / "runtime" / "recovery" / (case["case_id"] + ".json")
            path.write_text("broken")
            with self.assertRaises(ValueError):
                ensure_recovery_case(root, blocker, "later")
            self.assertEqual(path.read_text(), "broken")
