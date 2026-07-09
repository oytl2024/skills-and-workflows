import unittest

from wqb.benchmark import benchmark_alpha_record, benchmark_review_due


class BenchmarkTests(unittest.TestCase):
    def test_hard_pass_is_submit_check_candidate(self):
        result = benchmark_alpha_record(
            {
                "alpha_id": "pass1",
                "hard_pass": True,
                "metrics": {"sharpe": 1.8, "fitness": 1.3, "turnover": 0.18},
                "failed": [],
                "pending": [],
            }
        )

        self.assertEqual(result.label, "hard_pass")
        self.assertEqual(result.next_stage, "submit_check")
        self.assertEqual(result.repair_priority, 0)

    def test_straight_pnl_signal_is_repairable_even_below_hard_thresholds(self):
        result = benchmark_alpha_record(
            {
                "alpha_id": "3q7OQaog",
                "hard_pass": False,
                "metrics": {"sharpe": 0.95, "fitness": 0.42, "returns": 0.025, "turnover": 0.22},
                "failed": ["LOW_SHARPE", "LOW_FITNESS", "LOW_2Y_SHARPE"],
                "pending": [],
                "signal_note": "user observed straight PnL with clear signal",
            }
        )

        self.assertEqual(result.label, "repairable_signal")
        self.assertEqual(result.next_stage, "repair")
        self.assertIn("pnl_shape_signal", result.reasons)
        self.assertLessEqual(result.repair_priority, 2)

    def test_weak_low_metric_branch_stays_discard(self):
        result = benchmark_alpha_record(
            {
                "alpha_id": "weak1",
                "hard_pass": False,
                "metrics": {"sharpe": 0.15, "fitness": -0.2, "returns": -0.03, "turnover": 0.82},
                "failed": ["LOW_SHARPE", "LOW_FITNESS"],
                "pending": [],
            }
        )

        self.assertEqual(result.label, "weak_discard")
        self.assertEqual(result.next_stage, "discard")

    def test_benchmark_review_is_due_every_three_days(self):
        self.assertFalse(benchmark_review_due("2026-07-01", "2026-07-03"))
        self.assertTrue(benchmark_review_due("2026-07-01", "2026-07-04"))


if __name__ == "__main__":
    unittest.main()
