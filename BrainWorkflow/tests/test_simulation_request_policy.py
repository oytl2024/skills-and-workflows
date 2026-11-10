import unittest

from wqb.simulation_request_policy import choose_batch_size, next_poll_delay


class SimulationRequestPolicyTest(unittest.TestCase):
    def test_missing_evidence_cannot_raise_conservative_ceiling(self):
        self.assertEqual(choose_batch_size({"requested_size": 30, "supported_ceiling": 30}, 30, 30, None), 5)

    def test_quota_budget_and_no_work(self):
        self.assertEqual(choose_batch_size({}, 30, 3, 2), 2)
        self.assertEqual(choose_batch_size({}, 30, 0, None), 0)
        self.assertEqual(choose_batch_size({}, 0, 30, None), 0)

    def test_explicit_smaller_size_is_preserved(self):
        self.assertEqual(choose_batch_size({"requested_size": 2}, 30, 30, None), 2)

    def test_recovery_30_candidates_uses_six_not_fifteen_requests(self):
        remaining = 30
        requests = 0
        while remaining:
            remaining -= choose_batch_size({}, remaining, remaining, None)
            requests += 1
        self.assertEqual(requests, 6)

    def test_retry_after_zero_cannot_cause_busy_loop(self):
        self.assertGreaterEqual(next_poll_delay({}, 0, 0, 0), 1)
        self.assertGreaterEqual(next_poll_delay({}, 0, 12, 0), 12)
        self.assertLessEqual(next_poll_delay({}, 1000, None, 1), 60)
