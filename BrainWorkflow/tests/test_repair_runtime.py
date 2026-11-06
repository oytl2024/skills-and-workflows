import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from wqb.models import CheckSummary
from wqb.repair_runtime import RepairRuntimeExecutor


def parent_row():
    """Input: none. Output: dict. Supply local checked parent and exact simulation settings."""
    return {"alpha_id": "parent", "expression_hash": "parent-hash", "expression": "rank(cash)",
            "hard_pass": False, "failed": ["LOW_FITNESS"], "pending": [],
            "settings": {"instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000",
                         "delay": 1, "decay": 2, "neutralization": "SUBINDUSTRY", "truncation": 0.08,
                         "pasteurization": "ON", "unitHandling": "VERIFY", "nanHandling": "OFF",
                         "language": "FASTEXPR", "visualization": False}}


def repair_actions():
    """Input: none. Output: list[dict]. Supply optimizer-compatible local repair actions."""
    return [{"parent_hash": "parent-hash", "reason": "LOW_FITNESS", "action_type": "reduce_turnover"}]


class RepairRuntimeTests(unittest.TestCase):
    def test_parent_settings_recovery_rejects_threshold_and_invalid_evidence_without_network(self):
        """Input: local rate-limit states. Output: assertions. Enforce retry authority before settings GET."""
        from wqb.repair_runtime import RepairRateLimited
        parent = parent_row()
        del parent['settings']
        executor = RepairRuntimeExecutor({'allow_parent_settings_recovery': True}, enable_live_api=True)
        subrun = self.root / 'stages/repair/parents/parent-parent-hash'
        subrun.mkdir(parents=True)
        for state, expected in [
            ({'status': 'cooldown', 'retry_at': '2000-01-01T00:00:00+00:00',
              'consecutive_429_count': 3}, RepairRateLimited),
            ({'status': 'invalid'}, ValueError),
        ]:
            with self.subTest(state=state):
                (subrun / 'rate_limit_state.json').write_text(json.dumps(state), encoding='utf-8')
                with self.assertRaises(expected):
                    executor(self.root, parent, repair_actions(), 1)
                self.factory.assert_not_called()

    def test_parent_settings_recovery_honors_cooldown_before_network(self):
        from wqb.repair_runtime import RepairRateLimited
        parent = parent_row()
        del parent["settings"]
        executor = RepairRuntimeExecutor({"allow_parent_settings_recovery": True}, enable_live_api=True)
        state = {"status": "cooldown", "retry_at": "2099-01-01T00:00:00+00:00"}
        with patch("wqb.repair_runtime.read_rate_limit_state", return_value=state):
            with self.assertRaises(RepairRateLimited):
                executor(self.root, parent, repair_actions(), 1)
        self.factory.assert_not_called()

    def test_parent_settings_timeout_remains_recoverable_without_submit(self):
        import requests
        from wqb.repair_runtime import RepairRecoveryPending
        parent = parent_row()
        del parent["settings"]
        self.client.authenticate.side_effect = requests.exceptions.Timeout("bounded GET recovery")
        executor = RepairRuntimeExecutor({"allow_parent_settings_recovery": True}, enable_live_api=True)
        with self.assertRaises(RepairRecoveryPending):
            executor(self.root, parent, repair_actions(), 1)
        self.submit.assert_not_called()

    def test_local_expired_retry_does_not_become_unknown_submission(self):
        from wqb.rate_limit_state import RateLimitRecoveryRequired
        from wqb.repair_runtime import RepairRateLimited

        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        self.submit.side_effect = RateLimitRecoveryRequired(self.root, {"retry_at": "2000-01-01T00:00:00+00:00"})
        with self.assertRaises(RepairRateLimited):
            executor(self.root, parent_row(), repair_actions(), 1)
        self.submit.side_effect = None
        rows = executor(self.root, parent_row(), repair_actions(), 1)
        self.assertEqual(len(rows), 1)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.client = Mock()
        self.gate = self.enterContext(patch("wqb.cli.require_readiness_gate"))
        self.factory = self.enterContext(patch("wqb.cli.build_client", return_value=self.client))
        self.submit = self.enterContext(patch("wqb.cli.submit_simulation", return_value="progress/1"))
        self.poll = self.enterContext(patch("wqb.cli.poll_simulation", return_value={"alpha": "child"}))
        self.enterContext(patch("wqb.cli.fetch_check_summary", return_value=CheckSummary(
            "child", True, [], [], [], {"sharpe": 1.8, "fitness": 1.2})))
        self.enterContext(patch("wqb.cli.benchmark_fields_for_record", return_value={}))

    def test_checked_child_is_bounded_persisted_and_replayed_without_submit(self):
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        rows = executor(self.root, parent_row(), repair_actions(), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["parent_alpha_id"], "parent")
        self.assertEqual(rows[0]["parent_expression_hash"], "parent-hash")
        self.assertEqual(rows[0]["settings"]["decay"], 4)
        self.assertEqual(rows[0]["expression"], "rank(cash)")
        self.assertEqual(self.submit.call_count, 1)
        self.assertEqual(executor(self.root, parent_row(), repair_actions(), 1), rows)
        self.assertEqual(self.submit.call_count, 1)
        subrun = next((self.root / "stages" / "repair" / "parents").iterdir())
        self.assertTrue((subrun / "planned_candidates.jsonl").exists())
        self.assertTrue((subrun / "simulation_events.jsonl").exists())
        self.assertFalse((self.root / "all_alphas.jsonl").exists())

    def test_submitted_poll_failure_recovers_without_second_post(self):
        import requests
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        self.poll.side_effect = requests.exceptions.Timeout("offline poll timeout")
        with self.assertRaisesRegex(RuntimeError, "recovery"):
            executor(self.root, parent_row(), repair_actions(), 1)
        self.poll.side_effect = None
        wait_path = next((self.root / 'stages/repair/parents').iterdir()) / 'progress_wait.json'
        wait = json.loads(wait_path.read_text())
        wait['next_poll_at'] = '2000-01-01T00:00:00+00:00'
        wait_path.write_text(json.dumps(wait))
        rows = executor(self.root, parent_row(), repair_actions(), 1)
        self.assertEqual(rows[0]["parent_expression_hash"], "parent-hash")
        self.assertEqual(self.submit.call_count, 1)

    def test_uncertain_post_is_not_retried(self):
        import requests
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        self.submit.side_effect = requests.exceptions.Timeout("ambiguous POST")
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "recovery"):
                executor(self.root, parent_row(), repair_actions(), 1)
        self.assertEqual(self.submit.call_count, 1)

    def test_explicit_429_waits_then_retries_same_planned_child(self):
        import requests
        from wqb.repair_runtime import RepairRateLimited

        response = requests.Response()
        response.status_code = 429
        response.headers['Retry-After'] = '60'
        self.submit.side_effect = requests.exceptions.HTTPError('limited', response=response)
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        with self.assertRaises(RepairRateLimited):
            executor(self.root, parent_row(), repair_actions(), 1)
        with self.assertRaises(RepairRateLimited):
            executor(self.root, parent_row(), repair_actions(), 1)
        self.assertEqual(self.submit.call_count, 1)
        subrun = next((self.root / 'stages' / 'repair' / 'parents').iterdir())
        state_path = subrun / 'rate_limit_state.json'
        state = json.loads(state_path.read_text(encoding='utf-8'))
        state['retry_at'] = '2000-01-01T00:00:00+00:00'
        state_path.write_text(json.dumps(state), encoding='utf-8')
        self.submit.side_effect = None
        rows = executor(self.root, parent_row(), repair_actions(), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.submit.call_count, 2)

    def test_disabled_or_unready_executor_never_creates_client(self):
        with self.assertRaisesRegex(ValueError, "live"):
            RepairRuntimeExecutor({})(self.root, parent_row(), repair_actions(), 1)
        self.gate.side_effect = ValueError("readiness blocked")
        with self.assertRaisesRegex(ValueError, "readiness"):
            RepairRuntimeExecutor({}, enable_live_api=True)(self.root, parent_row(), repair_actions(), 1)
        self.factory.assert_not_called()
        self.submit.assert_not_called()

    def test_missing_local_settings_and_unsupported_actions_fail_before_network(self):
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        parent = parent_row()
        del parent["settings"]
        with self.assertRaisesRegex(ValueError, "settings"):
            executor(self.root, parent, repair_actions(), 1)
        with self.assertRaisesRegex(ValueError, "supported"):
            executor(self.root, parent_row(), [{"parent_hash": "parent-hash", "action_type": "change_dataset"}], 1)
        self.factory.assert_not_called()

    def test_changed_budget_or_parent_cannot_replace_persistent_plan(self):
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        executor(self.root, parent_row(), repair_actions(), 1)
        with self.assertRaisesRegex(ValueError, "plan"):
            executor(self.root, parent_row(), repair_actions(), 2)
        self.assertEqual(self.submit.call_count, 1)

    def test_auto_continue_ignores_executor_without_live_flag(self):
        from wqb.orchestrator import OrchestratorPaths
        from wqb.workflow_auto_continue import auto_continue_workflow
        paths = OrchestratorPaths(self.root, self.root, self.root, self.root)
        with patch("wqb.workflow_auto_continue.WorkflowOrchestrator") as controller:
            controller.return_value.status.return_value = {"active": False}
            auto_continue_workflow(paths, {}, "2026-09-23T00:00:00Z", repair_executor=object())
        self.assertIsNone(controller.call_args.kwargs["repair_executor"])


if __name__ == "__main__":
    unittest.main()
