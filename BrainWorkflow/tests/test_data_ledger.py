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
            "available_regions": ["USA", "CAN"],
            "available_delays": [1, 0],
            "available_universes": ["TOP3000"],
            "activity_tags": ["power_pool"],
            "compatible_template_ids": ["event_fast_delta_rank"],
            "gate_requirements": ["field_availability_gate"],
            "experiment_paths": ["knowledge/wiki/40_experiments/news12.md"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data_ledger.jsonl"
            path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

            records = load_data_ledger(path)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].field_id, "news12_sentiment_fast_d1")
        self.assertEqual(data_ledger_record_to_dict(records[0])["dataset_id"], "news12")
        self.assertEqual(records[0].available_regions, ["USA", "CAN"])
        self.assertEqual(records[0].compatible_template_ids, ["event_fast_delta_rank"])

    def test_select_data_hard_filters_region_and_delay_before_ranking(self):
        matching = DataLedgerRecord(
            dataset_id="news12", dataset_name="News", field_id="usa_d1", field_type="MATRIX",
            region="USA", delay=1, universe="TOP3000", semantic_tags=["power_pool"], coverage=0.1,
            alpha_count=0, user_count=0, simulation_usage_count=0, submitted_usage_count=0, last_used_at="",
            best_result_label="unexplored", correlation_risk="low", source_paths=[],
        )
        wrong_region = DataLedgerRecord(
            dataset_id="eu1", dataset_name="Europe", field_id="eur_d1", field_type="MATRIX",
            region="EUR", delay=1, universe="TOP3000", semantic_tags=["power_pool"], coverage=1.0,
            alpha_count=0, user_count=0, simulation_usage_count=0, submitted_usage_count=0, last_used_at="",
            best_result_label="repairable_signal", correlation_risk="low", source_paths=[],
        )
        wrong_delay = DataLedgerRecord(
            dataset_id="news0", dataset_name="News", field_id="usa_d0", field_type="MATRIX",
            region="USA", delay=0, universe="TOP3000", semantic_tags=["power_pool"], coverage=1.0,
            alpha_count=0, user_count=0, simulation_usage_count=0, submitted_usage_count=0, last_used_at="",
            best_result_label="repairable_signal", correlation_risk="low", source_paths=[],
        )

        selected = select_data_for_research([wrong_region, wrong_delay, matching], "power_pool", "USA", 1, limit=3)

        self.assertEqual([record.field_id for record in selected], ["usa_d1"])

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
