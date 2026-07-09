import unittest

from wqb.checker import classify_check_response, fetch_check_summary


class CheckerTests(unittest.TestCase):
    def test_hard_pass_when_all_hard_checks_pass_and_warnings_exist(self):
        response = {
            "is": {
                "checks": [
                    {"name": "LOW_SHARPE", "result": "PASS", "limit": 1.25},
                    {"name": "LOW_FITNESS", "result": "PASS", "limit": 1.0},
                    {"name": "MATCHES_THEMES", "result": "WARNING"},
                ]
            }
        }
        metrics = {"sharpe": 1.6, "fitness": 1.1, "turnover": 0.2}

        summary = classify_check_response("alpha1", response, metrics)

        self.assertTrue(summary.hard_pass)
        self.assertEqual(len(summary.warnings), 1)

    def test_pending_is_not_hard_pass(self):
        response = {"is": {"checks": [{"name": "SELF_CORRELATION", "result": "PENDING"}]}}

        summary = classify_check_response("alpha1", response, {})

        self.assertFalse(summary.hard_pass)
        self.assertEqual(summary.pending[0].name, "SELF_CORRELATION")

    def test_failed_hard_check_blocks_candidate(self):
        response = {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL", "limit": 1.25}]}}

        summary = classify_check_response("alpha1", response, {"sharpe": 0.8})

        self.assertFalse(summary.hard_pass)
        self.assertEqual(summary.failed[0].name, "LOW_SHARPE")

    def test_empty_checks_are_not_hard_pass(self):
        summary = classify_check_response("alpha1", {"is": {"checks": []}}, {})

        self.assertFalse(summary.hard_pass)
        self.assertEqual(summary.pending[0].name, "NO_CHECKS")

    def test_fetch_check_summary_retries_non_json_check_response(self):
        class FakeClient:
            def __init__(self):
                self.check_calls = 0

            def get_json(self, path):
                if path == "/alphas/alpha1":
                    return {"is": {"sharpe": 1.7}}
                if path == "/alphas/alpha1/check":
                    self.check_calls += 1
                    if self.check_calls == 1:
                        raise ValueError("empty response")
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

        sleeps = []

        summary = fetch_check_summary(
            FakeClient(),
            "alpha1",
            max_check_retries=1,
            sleep_seconds=0.25,
            sleep_func=sleeps.append,
        )

        self.assertTrue(summary.hard_pass)
        self.assertEqual(sleeps, [0.25])


if __name__ == "__main__":
    unittest.main()
