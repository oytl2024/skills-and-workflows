import json
import tempfile
import unittest
from pathlib import Path

from wqb.data_ledger import (
    DataLedgerRecord,
    data_ledger_record_from_dict,
    data_ledger_record_to_dict,
    data_record_authority,
    is_authoritative_data_record,
    load_data_ledger,
    score_data_for_research,
    select_data_for_research,
    summarize_data_ledger_authority,
    write_data_ledger_markdown,
)


class DataLedgerTest(unittest.TestCase):
    def test_authority_requires_certified_canonical_raw_capture_evidence(self):
        scope = {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}
        record = data_ledger_record_from_dict(
            {
                "dataset_id": "fundamental3",
                "field_id": "cash_field",
                "field_type": "MATRIX",
                "region": "USA",
                "delay": 1,
                "universe": "TOP3000",
                "coverage": 1.0,
                "source_quality": "platform_raw_capture",
                "coverage_status": "measured_raw",
                "source_updated_at": "2026-07-22",
                "source_paths": ["raw/platform/data_fields/2026-07-22/data_fields.jsonl"],
                "available_scopes": [scope],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-22"
            capture.mkdir(parents=True)
            (capture / "data_fields.jsonl").write_text(
                json.dumps(
                    {
                        "scope": scope,
                        "data_set": {"id": "fundamental3"},
                        "field": {"id": "cash_field", "type": "MATRIX"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(data_record_authority(record, root), "unclassified")

            (capture / "manifest.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-22T08:00:00+00:00",
                        "certification_status": "complete",
                        "requested_matrix": [scope],
                    }
                ),
                encoding="utf-8",
            )
            (capture / "scopes.jsonl").write_text(
                json.dumps({"scope": scope, "status": "completed", "certification_status": "complete"}) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(data_record_authority(record, root), "authoritative_measured")
            self.assertTrue(is_authoritative_data_record(record, root))

    def test_data_record_authority_distinguishes_cache_and_measured_platform_rows(self):
        cache = DataLedgerRecord(
            dataset_id="fundamental3",
            dataset_name="Fundamentals",
            field_id="fnd3_q_cash_fast_d1",
            field_type="MATRIX",
            region="USA",
            delay=1,
            universe="TOP3000",
            semantic_tags=["cash"],
            coverage=0.8,
            alpha_count=1,
            user_count=1,
            simulation_usage_count=0,
            submitted_usage_count=0,
            last_used_at="",
            best_result_label="unexplored_cache_candidate",
            correlation_risk="low",
            source_paths=["docs/knowledge/cache/platform_metadata.json"],
            source_quality="platform_metadata_cache",
            coverage_status="measured_cache",
        )
        measured = data_ledger_record_from_dict(data_ledger_record_to_dict(cache) | {
            "source_quality": "platform_raw_capture",
            "coverage_status": "measured_raw",
            "source_updated_at": "2026-07-22",
            "source_paths": ["raw/platform/data_fields/2026-07-22/data_fields.jsonl"],
        })

        self.assertEqual(data_record_authority(cache), "seed_cache")
        self.assertEqual(data_record_authority(measured), "authoritative_measured")
        self.assertFalse(is_authoritative_data_record(cache))
        self.assertTrue(is_authoritative_data_record(measured))
        self.assertEqual(
            summarize_data_ledger_authority([cache, measured])["authoritative_measured_count"],
            1,
        )

    def test_select_data_rejects_cross_product_scope_when_exact_scopes_exist(self):
        record = DataLedgerRecord(
            dataset_id="fundamental3", dataset_name="Fundamentals", field_id="cash_field", field_type="MATRIX",
            region="USA", delay=1, universe="TOP3000", semantic_tags=["cash"], coverage=1.0,
            alpha_count=0, user_count=0, simulation_usage_count=0, submitted_usage_count=0,
            last_used_at="", best_result_label="unexplored", correlation_risk="low", source_paths=[],
            available_regions=["USA", "EUR"], available_delays=[0, 1], available_universes=["TOP500", "TOP3000"],
            available_scopes=[
                {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                {"instrument_type": "EQUITY", "region": "EUR", "delay": 0, "universe": "TOP500"},
            ],
        )

        selected = select_data_for_research([record], "cash", "USA", 0, limit=5, universe="TOP500")

        self.assertEqual(selected, [])

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
            "instrument_type": "EQUITY",
            "date_coverage": "2018-01-01 to 2026-07-09",
            "data_category": "news_sentiment",
            "crowding_risk": "medium",
            "known_operators": ["ts_delta", "rank"],
            "repair_usage_count": 2,
            "source_quality": "platform_raw_capture",
            "coverage_status": "measured_raw",
            "source_updated_at": "2026-07-09",
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
        self.assertEqual(records[0].instrument_type, "EQUITY")
        self.assertEqual(records[0].date_coverage, "2018-01-01 to 2026-07-09")
        self.assertEqual(records[0].data_category, "news_sentiment")
        self.assertEqual(records[0].crowding_risk, "medium")
        self.assertEqual(records[0].known_operators, ["ts_delta", "rank"])
        self.assertEqual(records[0].repair_usage_count, 2)
        self.assertEqual(records[0].source_quality, "platform_raw_capture")
        self.assertEqual(records[0].coverage_status, "measured_raw")
        self.assertEqual(records[0].source_updated_at, "2026-07-09")
        serialized = data_ledger_record_to_dict(records[0])
        self.assertEqual(serialized["instrument_type"], "EQUITY")
        self.assertEqual(serialized["repair_usage_count"], 2)
        self.assertEqual(serialized["source_quality"], "platform_raw_capture")
        self.assertEqual(serialized["coverage_status"], "measured_raw")
        self.assertEqual(serialized["source_updated_at"], "2026-07-09")

    def test_select_data_hard_filters_region_delay_and_universe_before_ranking(self):
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
        wrong_universe = DataLedgerRecord(
            dataset_id="smallcap", dataset_name="Small Cap", field_id="usa_d1_top1000", field_type="MATRIX",
            region="USA", delay=1, universe="TOP1000", semantic_tags=["power_pool"], coverage=1.0,
            alpha_count=0, user_count=0, simulation_usage_count=0, submitted_usage_count=0, last_used_at="",
            best_result_label="repairable_signal", correlation_risk="low", source_paths=[],
        )

        selected = select_data_for_research(
            [wrong_region, wrong_delay, wrong_universe, matching],
            "power_pool",
            "USA",
            1,
            limit=3,
            universe="TOP3000",
        )

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
