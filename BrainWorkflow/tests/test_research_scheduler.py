import tempfile
import unittest
from pathlib import Path

from wqb.data_ledger import DataLedgerRecord
from wqb.principle_model import OptionCard, ScoreBreakdown, SourceEvidence
from wqb.research_scheduler import build_research_schedule, research_schedule_to_dict, write_research_schedule
from wqb.template_library import TemplateRecord


def option_card() -> OptionCard:
    """Input: none. Output: an OptionCard fixture for scheduler tests."""
    return OptionCard(
        title="Explore current Power Pool boards",
        primary_incentive="power_pool",
        secondary_incentives=["genius"],
        why_now="Visible Power Pool boards include USA D1.",
        candidate_scope="USA D1 underused event data.",
        expected_asset_value="Simple alpha assets with lower criteria.",
        correlation_risk="Medium-high unless new data and distinct templates are used.",
        resource_cost="One 30-alpha scout batch.",
        evidence=[SourceEvidence("api", "/consultant/boards/power-pool", "Power Pool boards", "2026-07-10T00:00:00Z")],
        failure_modes=["Power Pool correlation failure."],
        decision_needed="Choose this option.",
        score=ScoreBreakdown(total=8.0, components={"power_pool": 8.0}, penalties={}, reasons=["Visible board."]),
    )


def data_records() -> list[DataLedgerRecord]:
    """Input: none. Output: data-ledger records covering scheduler selection cases."""
    return [
        DataLedgerRecord(
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
        ),
        DataLedgerRecord(
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
        ),
    ]


def templates() -> list[TemplateRecord]:
    """Input: none. Output: a template-library fixture matching the test data."""
    return [
        TemplateRecord(
            template_id="event_fast_delta_rank",
            hypothesis="Fast event sentiment changes are incorporated gradually.",
            skeleton="rank(ts_delta({field}, 1))",
            required_field_types=["MATRIX"],
            compatible_semantic_tags=["event", "sentiment", "fast_d1", "power_pool"],
            operator_tags=["time_series_surprise", "cross_sectional_normalizer"],
            status="seed",
            correlation_risk="low",
            repair_levers=["group_neutralize"],
            source_paths=["wiki"],
        )
    ]


class ResearchSchedulerTest(unittest.TestCase):
    def test_build_schedule_prefers_underused_data_and_matching_template(self):
        schedule = build_research_schedule(option_card(), data_records(), templates(), region="USA", delay=1)

        self.assertEqual(schedule.primary_incentive, "power_pool")
        self.assertEqual(schedule.selected_data[0].field_id, "news12_sentiment_fast_d1")
        self.assertEqual(schedule.template_matches[0]["template_id"], "event_fast_delta_rank")
        self.assertEqual(schedule.batch_size, 30)
        self.assertIn("local_novelty_gate", schedule.local_gates)

    def test_research_schedule_to_dict_is_json_safe(self):
        schedule = build_research_schedule(option_card(), data_records(), templates(), region="USA", delay=1)
        row = research_schedule_to_dict(schedule)

        self.assertEqual(row["option_title"], "Explore current Power Pool boards")
        self.assertEqual(row["selected_data"][0]["field_id"], "news12_sentiment_fast_d1")

    def test_write_research_schedule_creates_markdown(self):
        schedule = build_research_schedule(option_card(), data_records(), templates(), region="USA", delay=1)
        with tempfile.TemporaryDirectory() as tmp:
            output = write_research_schedule(Path(tmp) / "schedule.md", schedule, "2026-07-10T00:00:00Z")
            text = output.read_text(encoding="utf-8")

        self.assertIn("Explore current Power Pool boards", text)
        self.assertIn("news12_sentiment_fast_d1", text)


if __name__ == "__main__":
    unittest.main()
