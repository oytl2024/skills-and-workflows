import unittest

from wqb.models import CheckItem, CheckSummary
from wqb.optimizer import actions_for_check_summary


class OptimizerTests(unittest.TestCase):
    def test_low_sharpe_maps_to_signal_actions(self):
        summary = CheckSummary(
            alpha_id="a1",
            hard_pass=False,
            failed=[CheckItem(name="LOW_SHARPE", result="FAIL")],
            warnings=[],
            pending=[],
            metrics={"sharpe": 0.8},
        )

        actions = actions_for_check_summary("parent", summary)

        self.assertIn("flip_direction", {action.action_type for action in actions})
        self.assertIn("change_window", {action.action_type for action in actions})

    def test_high_turnover_maps_to_smoothing(self):
        summary = CheckSummary(
            alpha_id="a1",
            hard_pass=False,
            failed=[CheckItem(name="HIGH_TURNOVER", result="FAIL")],
            warnings=[],
            pending=[],
            metrics={"turnover": 0.9},
        )

        actions = actions_for_check_summary("parent", summary)

        self.assertIn("increase_decay", {action.action_type for action in actions})
        self.assertIn("smooth_signal", {action.action_type for action in actions})

    def test_pending_checks_also_create_actions(self):
        summary = CheckSummary(
            alpha_id="a1",
            hard_pass=False,
            failed=[],
            warnings=[],
            pending=[CheckItem(name="SELF_CORRELATION", result="PENDING")],
            metrics={},
        )

        actions = actions_for_check_summary("parent", summary)

        self.assertIn("change_dataset", {action.action_type for action in actions})

    def test_unknown_check_defaults_to_change_field(self):
        summary = CheckSummary(
            alpha_id="a1",
            hard_pass=False,
            failed=[CheckItem(name="NEW_PLATFORM_CHECK", result="FAIL")],
            warnings=[],
            pending=[],
            metrics={},
        )

        actions = actions_for_check_summary("parent", summary)

        self.assertEqual([action.action_type for action in actions], ["change_field"])
        self.assertEqual(actions[0].details["alpha_id"], "a1")


if __name__ == "__main__":
    unittest.main()
