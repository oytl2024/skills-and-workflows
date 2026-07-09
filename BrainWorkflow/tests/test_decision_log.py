import json
import tempfile
import unittest
from pathlib import Path

from wqb.decision_log import write_option_cards
from wqb.principle_model import OptionCard, ScoreBreakdown, SourceEvidence


class DecisionLogTest(unittest.TestCase):
    # Input: none; Output: none; Purpose: verify option cards are persisted to durable JSONL and Markdown logs.
    def test_write_option_cards_creates_jsonl_and_markdown(self):
        card = OptionCard(
            title="Build Genius and Osmosis alpha pool",
            primary_incentive="genius_osmosis",
            secondary_incentives=["quarterly_payment"],
            why_now="Genius rules value signals and pyramids.",
            candidate_scope="Multiple scopes after selection.",
            expected_asset_value="Long-term pool diversity.",
            correlation_risk="Medium.",
            resource_cost="Read-only planning.",
            evidence=[SourceEvidence("api", "/tutorial-pages/brain-genius", "Brain Genius", "2026-07-09T00:00:00Z")],
            failure_modes=["Pool diversity takes time."],
            decision_needed="Choose this option.",
            score=ScoreBreakdown(total=9.0, components={"genius": 9.0}, penalties={}, reasons=["Durable incentive."]),
        )

        with tempfile.TemporaryDirectory() as tmp:
            jsonl_path, md_path = write_option_cards(Path(tmp), [card], "2026-07-09T00:00:00Z")

            rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
            markdown = md_path.read_text(encoding="utf-8")

        self.assertEqual(rows[0]["title"], "Build Genius and Osmosis alpha pool")
        self.assertIn("Build Genius and Osmosis alpha pool", markdown)
        self.assertIn("Decision Needed", markdown)


if __name__ == "__main__":
    unittest.main()
