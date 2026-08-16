import tempfile
import unittest
from pathlib import Path

from wqb.ai_checkpoints import append_ai_checkpoint, load_ai_checkpoints


class AICheckpointTests(unittest.TestCase):
    def test_append_and_load_ai_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            decisions = Path(tmp) / "knowledge" / "wiki" / "70_decisions"

            checkpoint = append_ai_checkpoint(
                decisions,
                "blocker_explanation",
                "Research readiness is blocked by stale data ledger.",
                ["runs/readiness/report.md"],
                "2026-07-30T00:00:00+00:00",
            )
            rows = load_ai_checkpoints(decisions)

        self.assertTrue(checkpoint.checkpoint_id.startswith("ai-"))
        self.assertEqual(rows[0]["checkpoint_type"], "blocker_explanation")
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["evidence_paths"], ["runs/readiness/report.md"])

    def test_load_ai_checkpoints_skips_malformed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            decisions = Path(tmp)
            (decisions / "ai_checkpoints.jsonl").write_text(
                "not-json\n"
                '{"checkpoint_id":"ai-good","checkpoint_type":"template_innovation","reason":"Need a novel template.","evidence_paths":[],"created_at":"2026-07-30T00:00:00+00:00","status":"pending"}\n',
                encoding="utf-8",
            )

            rows = load_ai_checkpoints(decisions)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["checkpoint_id"], "ai-good")
