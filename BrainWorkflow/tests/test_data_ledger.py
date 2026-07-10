import json
import tempfile
import unittest
from pathlib import Path

from wqb.data_ledger import (
    DataLedgerRecord,
    data_ledger_record_to_dict,
    load_data_ledger,
    score_data_for_research,
    select_data_for_research,
    write_data_ledger_markdown,
)


class DataLedgerTest(unittest.TestCase):
    def test_load_data_ledger_round_trips_jsonl(self):
        row = {
            "dataset_id": "news12",
            "dataset_name": "News Events",
            "field_id": "news12_sentiment_fast_d1",
            "field_type": "MATRIX",
            "region": "USA",
            "delay": 1,
            "universe": "TOP3000",
            "semantic_tags": ["event", "sentiment", "fast_d1"],
            "coverage": 0.82,
            "alpha_count": 12,
            "user_count": 4,
            "simulation_usage_count": 1,
            "submitted_usage_count": 0,
            "last_used_at": "2026-07-09",
            "best_result_label": "repairable_signal",
            "correlation_risk": "medium",
            "source_paths": ["knowledge/raw/platform/learn/2026-07-09/documentation_pages.md"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data_ledger.jsonl"
            path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

            records = load_data_ledger(path)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].field_id, "news12_sentiment_fast_d1")
        self.assertEqual(data_ledger_record_to_dict(records[0])["dataset_id"], "news12")

    def test_score_data_prefers_underused_matching_incentive_data(self):
        preferred = DataLedgerRecord(
            dataset_id="news12",
            dataset_name="News Events",
            field_id="news12_sentiment_fast_d1",
            field_type="MATRIX",
            region="USA",
            delay=1,
            universe="TOP3000",
            semantic_tags=["event", "sentiment", "fast_d1", "power_pool"],
            coverage=0.82,
            alpha_count=12,
            user_count=4,
            simulation_usage_count=1,
            submitted_usage_count=0,
            last_used_at="2026-07-09",
            best_result_label="repairable_signal",
            correlation_risk="medium",
            source_paths=["raw"],
        )
        crowded = DataLedgerRecord(
            dataset_id="pv1",
            dataset_name="Price Volume",
            field_id="volume",
            field_type="MATRIX",
            region="USA",
            delay=1,
            universe="TOP3000",
            semantic_tags=["liquidity"],
            coverage=0.99,
            alpha_count=900,
            user_count=300,
            simulation_usage_count=30,
            submitted_usage_count=5,
            last_used_at="2026-07-09",
            best_result_label="prod_correlation_fail",
            correlation_risk="high",
            source_paths=["raw"],
        )

        selected = select_data_for_research([crowded, preferred], "power_pool", "USA", 1, limit=1)

        self.assertEqual(selected[0].field_id, "news12_sentiment_fast_d1")
        self.assertGreater(score_data_for_research(preferred, "power_pool", "USA", 1), score_data_for_research(crowded, "power_pool", "USA", 1))

    def test_write_data_ledger_markdown_creates_reviewable_table(self):
        record = DataLedgerRecord(
            dataset_id="analyst9",
            dataset_name="Analyst Revisions",
            field_id="analyst9_eps_revision",
            field_type="MATRIX",
            region="USA",
            delay=1,
            universe="TOP3000",
            semantic_tags=["analyst_revision", "growth"],
            coverage=0.76,
            alpha_count=40,
            user_count=11,
            simulation_usage_count=0,
            submitted_usage_count=0,
            last_used_at="",
            best_result_label="unexplored",
            correlation_risk="low",
            source_paths=["knowledge/raw/platform/learn/2026-07-09/documentation_pages.md"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = write_data_ledger_markdown(Path(tmp) / "data_ledger.md", [record], "2026-07-10T00:00:00Z")
            text = output.read_text(encoding="utf-8")

        self.assertIn("analyst9_eps_revision", text)
        self.assertIn("analyst_revision, growth", text)


if __name__ == "__main__":
    unittest.main()
