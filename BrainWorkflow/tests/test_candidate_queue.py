import tempfile
import unittest

from wqb.candidate_queue import (
    approval_matches_candidate,
    approve_candidate,
    load_approved_queue,
    load_approvals,
    queue_approved_candidate,
    update_candidate_queue_status,
)


class CandidateQueueTests(unittest.TestCase):
    def candidate(self):
        return {
            "candidate_id": "c1",
            "platform_alpha_id": "a1",
            "version": 1,
            "expression_hash": "h1",
            "sharpe": 1.4,
        }

    def test_approval_binds_exact_candidate_version_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            approval = approve_candidate(tmp, self.candidate(), "2026-07-12T00:00:00Z", "user")
            loaded = load_approvals(tmp)

        self.assertEqual(approval["expression_hash"], "h1")
        self.assertEqual(loaded[0]["candidate_id"], "c1")
        self.assertTrue(approval_matches_candidate(approval, self.candidate()))
        changed = dict(self.candidate(), expression_hash="h2")
        self.assertFalse(approval_matches_candidate(approval, changed))

    def test_approval_does_not_match_different_platform_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            approval = approve_candidate(tmp, self.candidate(), "2026-07-12T00:00:00Z", "user")

        changed = dict(self.candidate(), platform_alpha_id="a2")
        self.assertFalse(approval_matches_candidate(approval, changed))

    def test_queue_deduplicates_same_candidate_version_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            approval = approve_candidate(tmp, self.candidate(), "2026-07-12T00:00:00Z", "user")
            queue_approved_candidate(tmp, approval)
            queue_approved_candidate(tmp, approval)
            rows = load_approved_queue(tmp)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "queued")

    def test_queue_status_update_requires_matching_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            approval = approve_candidate(tmp, self.candidate(), "2026-07-12T00:00:00Z", "user")
            queue_approved_candidate(tmp, approval)
            updated = update_candidate_queue_status(tmp, "c1", 1, "h1", "manually_submitted", "2026-07-12T01:00:00Z")
            rows = load_approved_queue(tmp)

        self.assertEqual(updated["status"], "manually_submitted")
        self.assertEqual(rows[0]["status"], "manually_submitted")
