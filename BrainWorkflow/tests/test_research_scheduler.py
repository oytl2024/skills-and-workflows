import tempfile
import unittest
from dataclasses import replace
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
        schedule = build_research_schedule(option_card(), data_records(), templates(), region="USA", delay=1, universe="TOP3000")

        self.assertEqual(schedule.primary_incentive, "power_pool")
        self.assertEqual(schedule.selected_data[0].field_id, "news12_sentiment_fast_d1")
        self.assertEqual(schedule.template_matches[0]["template_id"], "event_fast_delta_rank")
        self.assertEqual(schedule.batch_size, 30)
        self.assertEqual(schedule.activity, "power_pool")
        self.assertEqual(schedule.universe, "TOP3000")
        self.assertEqual(schedule.batch_count, 1)
        self.assertEqual(schedule.simulation_budget, 2)
        self.assertGreaterEqual(schedule.api_budget, schedule.simulation_budget)
        self.assertTrue(schedule.parallel_task_plan)
        self.assertIn("local_novelty_gate", schedule.local_gates)

    def test_research_schedule_to_dict_is_json_safe(self):
        schedule = build_research_schedule(option_card(), data_records(), templates(), region="USA", delay=1, universe="TOP3000")
        row = research_schedule_to_dict(schedule)

        self.assertEqual(row["option_title"], "Explore current Power Pool boards")
        self.assertEqual(row["selected_data"][0]["field_id"], "news12_sentiment_fast_d1")
        self.assertEqual(row["simulation_budget"], 2)
        self.assertTrue(row["parallel_task_plan"])

    def test_write_research_schedule_creates_markdown(self):
        schedule = build_research_schedule(option_card(), data_records(), templates(), region="USA", delay=1, universe="TOP3000")
        with tempfile.TemporaryDirectory() as tmp:
            output = write_research_schedule(Path(tmp) / "schedule.md", schedule, "2026-07-10T00:00:00Z")
            text = output.read_text(encoding="utf-8")

        self.assertIn("Explore current Power Pool boards", text)
        self.assertIn("news12_sentiment_fast_d1", text)
        self.assertIn("Simulation Budget: 2", text)
        self.assertIn("Parallel Task Plan", text)

    def test_schedule_filters_universe_and_counts_execution_units(self):
        top1000_record = replace(data_records()[1], dataset_id="alt_news", field_id="alt_news_field", universe="TOP1000")
        second_template = replace(templates()[0], template_id="event_fast_delta_mean")

        schedule = build_research_schedule(
            option_card(),
            data_records() + [top1000_record],
            templates() + [second_template],
            region="USA",
            delay=1,
            universe="TOP3000",
            max_data=5,
            templates_per_data=2,
            batch_size=1,
        )

        self.assertEqual([record.universe for record in schedule.selected_data], ["TOP3000", "TOP3000"])
        self.assertEqual(len(schedule.template_matches), 4)
        self.assertEqual(schedule.batch_count, 4)
        self.assertEqual(schedule.simulation_budget, 4)
        self.assertGreaterEqual(schedule.api_budget, 4)
        self.assertEqual(len(schedule.parallel_task_plan), 4)

    def test_schedule_matches_templates_against_selected_multi_scope(self):
        multi_scope_record = replace(
            data_records()[1],
            available_regions=["USA", "CAN"],
            available_delays=[0, 1],
            available_universes=["TOP1000", "TOP3000"],
        )
        selected_scope_template = replace(
            templates()[0],
            template_id="canada_d0_top1000",
            compatible_regions=["CAN"],
            compatible_delays=[0],
            compatible_universes=["TOP1000"],
        )
        primary_scope_template = replace(
            templates()[0],
            template_id="usa_d1_top3000",
            compatible_regions=["USA"],
            compatible_delays=[1],
            compatible_universes=["TOP3000"],
        )

        schedule = build_research_schedule(
            option_card(),
            [multi_scope_record],
            [selected_scope_template, primary_scope_template],
            region="CAN",
            delay=0,
            universe="TOP1000",
            templates_per_data=2,
        )

        self.assertEqual([record.field_id for record in schedule.selected_data], ["news12_sentiment_fast_d1"])
        self.assertEqual([match["template_id"] for match in schedule.template_matches], ["canada_d0_top1000"])


if __name__ == "__main__":
    unittest.main()
