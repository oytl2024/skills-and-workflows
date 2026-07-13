import json
import tempfile
import unittest
from pathlib import Path

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
            "source_run_id": "run1",
            "sharpe": 1.4,
        }

    def test_approval_and_queue_require_source_run_id(self):
        candidate = dict(self.candidate(), source_run_id="")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "source_run_id"):
                approve_candidate(tmp, candidate, "2026-07-12T00:00:00Z", "user")
            with self.assertRaisesRegex(ValueError, "source_run_id"):
                queue_approved_candidate(tmp, candidate)

    def test_approval_rejects_every_blank_required_value(self):
        cases = (
            ("candidate_id", {"candidate_id": ""}, "2026-07-12T00:00:00Z", "user"),
            ("platform_alpha_id", {"platform_alpha_id": " "}, "2026-07-12T00:00:00Z", "user"),
            ("version", {"version": ""}, "2026-07-12T00:00:00Z", "user"),
            ("expression_hash", {"expression_hash": ""}, "2026-07-12T00:00:00Z", "user"),
            ("source_run_id", {"source_run_id": ""}, "2026-07-12T00:00:00Z", "user"),
            ("approved_at", {}, "", "user"),
            ("approved_by", {}, "2026-07-12T00:00:00Z", " "),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for field, changes, approved_at, approved_by in cases:
                with self.subTest(field=field):
                    candidate = dict(self.candidate(), **changes)
                    with self.assertRaisesRegex(ValueError, field):
                        approve_candidate(tmp, candidate, approved_at, approved_by)

    def test_approval_append_is_idempotent_for_exact_candidate_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = approve_candidate(tmp, self.candidate(), "2026-07-12T00:00:00Z", "user")
            retry = approve_candidate(tmp, self.candidate(), "2026-07-12T00:01:00Z", "user")
            rows = load_approvals(tmp)

        self.assertEqual(retry, first)
        self.assertEqual(len(rows), 1)

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

    def test_approval_does_not_match_different_source_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            approval = approve_candidate(tmp, self.candidate(), "2026-07-12T00:00:00Z", "user")

        self.assertFalse(approval_matches_candidate(approval, dict(self.candidate(), source_run_id="run2")))

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

    def test_retry_recovers_from_one_incomplete_trailing_jsonl_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "approval.jsonl").write_text('{"candidate_id":', encoding="utf-8")
            approval = approve_candidate(
                root, self.candidate(), "2026-07-12T00:00:00Z", "user"
            )
            approvals = load_approvals(root)

            (root / "approved_candidates.jsonl").write_text(
                json.dumps(dict(approval, status="queued")) + '\n{"candidate_id":',
                encoding="utf-8",
            )
            queued = queue_approved_candidate(root, approval)
            queue = load_approved_queue(root)
            approval_lines = (root / "approval.jsonl").read_text(encoding="utf-8").splitlines()
            queue_lines = (root / "approved_candidates.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["candidate_id"], "c1")
        self.assertEqual(queued["candidate_id"], "c1")
        self.assertEqual(len(queue), 1)
        self.assertEqual(len(approval_lines), 1)
        self.assertEqual(len(queue_lines), 1)
        self.assertIsInstance(json.loads(approval_lines[0]), dict)
        self.assertIsInstance(json.loads(queue_lines[0]), dict)
