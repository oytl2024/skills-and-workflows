import json
import tempfile
import unittest
from pathlib import Path

from wqb.data_ledger import DataLedgerRecord
from wqb.template_library import (
    TemplateRecord,
    load_template_library,
    score_template_for_data,
    select_templates_for_data,
    template_matrix_ready,
    template_matrix_summary,
    template_record_from_dict,
    template_record_to_dict,
    write_template_library_markdown,
)


def sample_data() -> DataLedgerRecord:
    return DataLedgerRecord(
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


def complete_matrix_row() -> dict[str, object]:
    """Input: none. Output: template row dict. Build every required Spec B matrix dimension."""
    return {
        "template_id": "complete_event_matrix",
        "hypothesis": "Fresh event data is incorporated gradually.",
        "skeleton": "rank(ts_delta({field}, 1))",
        "required_field_types": ["MATRIX"],
        "compatible_semantic_tags": ["event"],
        "operator_tags": ["time_series_surprise"],
        "status": "discovery_ready",
        "correlation_risk": "medium",
        "repair_levers": ["group_neutralize"],
        "source_paths": ["wiki/30_templates/template_families.md"],
        "compatible_regions": ["USA"],
        "compatible_delays": [1],
        "compatible_universes": ["TOP3000"],
        "suitable_horizons": ["short"],
        "neutralization_styles": ["subindustry"],
        "turnover_bucket": "medium",
        "local_gates": ["field_type_gate"],
        "experiment_paths": ["wiki/40_experiments/event.md"],
        "intended_direction": "long positive event changes",
        "interpretation": "Fresh changes should precede excess returns.",
        "decay": "fast",
        "data_semantics": ["event", "fast_d1"],
        "economic_hypothesis": "Fresh event data is incorporated gradually.",
        "operator_composition": ["ts_delta", "rank"],
        "abandon_conditions": ["three_batches_no_signal"],
        "benchmark_rule_ids": ["near_miss_stable_pnl"],
        "template_family": "event_surprise",
    }


class TemplateLibraryTest(unittest.TestCase):
    def test_matrix_ready_requires_every_spec_b_dimension(self):
        complete = complete_matrix_row()
        required_dimensions = [
            "data_semantics",
            "economic_hypothesis",
            "required_field_types",
            "compatible_semantic_tags",
            "operator_tags",
            "compatible_regions",
            "compatible_delays",
            "compatible_universes",
            "suitable_horizons",
            "neutralization_styles",
            "turnover_bucket",
            "local_gates",
            "experiment_paths",
            "intended_direction",
            "interpretation",
            "decay",
            "source_paths",
            "repair_levers",
        ]

        self.assertTrue(template_matrix_ready(template_record_from_dict(complete)))
        for field_name in required_dimensions:
            incomplete = dict(complete)
            incomplete[field_name] = "" if isinstance(complete[field_name], str) else []
            with self.subTest(field=field_name):
                self.assertFalse(template_matrix_ready(template_record_from_dict(incomplete)))

        unknown_risk = dict(complete)
        unknown_risk["correlation_risk"] = "unknown"
        self.assertFalse(template_matrix_ready(template_record_from_dict(unknown_risk)))

    def test_template_record_loads_matrix_fields_with_backward_compatibility(self):
        legacy = template_record_from_dict(
            {
                "template_id": "matrix_fast_delta_rank",
                "hypothesis": "Fresh changes capture underreaction.",
                "skeleton": "rank(ts_delta({field}, 1))",
                "required_field_types": ["MATRIX"],
                "compatible_semantic_tags": ["event"],
                "operator_tags": ["time_series_surprise"],
                "status": "seed",
                "correlation_risk": "low",
                "repair_levers": ["window_3"],
                "source_paths": ["wiki/30_templates/template_families.md"],
            }
        )
        matrix = template_record_from_dict(complete_matrix_row())

        self.assertFalse(template_matrix_ready(legacy))
        self.assertTrue(template_matrix_ready(matrix))
        self.assertEqual(template_matrix_summary([legacy, matrix])["matrix_ready_count"], 1)

    def test_load_template_library_round_trips_jsonl(self):
        row = {
            "template_id": "event_fast_delta_rank",
            "hypothesis": "Fast event sentiment changes are incorporated gradually.",
            "skeleton": "rank(ts_delta({field}, 1))",
            "required_field_types": ["MATRIX"],
            "compatible_semantic_tags": ["event", "sentiment", "fast_d1"],
            "operator_tags": ["time_series_surprise", "cross_sectional_normalizer"],
            "status": "seed",
            "correlation_risk": "low",
            "repair_levers": ["group_neutralize", "window_5"],
            "source_paths": ["knowledge/wiki/30_templates/template_families.md"],
            "compatible_regions": ["USA"],
            "compatible_delays": [1],
            "compatible_universes": ["TOP3000"],
            "suitable_horizons": ["short"],
            "neutralization_styles": ["subindustry"],
            "turnover_bucket": "medium",
            "local_gates": ["field_type_gate"],
            "experiment_paths": ["knowledge/wiki/40_experiments/event.md"],
            "intended_direction": "long positive sentiment changes",
            "interpretation": "Rising fast sentiment should precede excess returns.",
            "decay": "fast",
            "known_antipatterns": ["raw_event_rank"],
            "crowded_variants": ["event_delta_rank_v1"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template_library.jsonl"
            path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

            templates = load_template_library(path)

        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0].template_id, "event_fast_delta_rank")
        self.assertEqual(template_record_to_dict(templates[0])["status"], "seed")
        self.assertEqual(templates[0].compatible_regions, ["USA"])
        self.assertEqual(templates[0].turnover_bucket, "medium")
        self.assertEqual(templates[0].intended_direction, "long positive sentiment changes")
        self.assertEqual(templates[0].interpretation, "Rising fast sentiment should precede excess returns.")
        self.assertEqual(templates[0].decay, "fast")
        self.assertEqual(templates[0].known_antipatterns, ["raw_event_rank"])
        self.assertEqual(templates[0].crowded_variants, ["event_delta_rank_v1"])
        serialized = template_record_to_dict(templates[0])
        self.assertEqual(serialized["intended_direction"], "long positive sentiment changes")
        self.assertEqual(serialized["crowded_variants"], ["event_delta_rank_v1"])

    def test_select_templates_prefers_compatible_low_risk_template(self):
        compatible = TemplateRecord(
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
        incompatible = TemplateRecord(
            template_id="vector_attention_avg",
            hypothesis="Vector attention breadth predicts return pressure.",
            skeleton="rank(vec_avg({field}))",
            required_field_types=["VECTOR"],
            compatible_semantic_tags=["attention"],
            operator_tags=["vector_reducer"],
            status="seed",
            correlation_risk="medium",
            repair_levers=["vec_sum"],
            source_paths=["wiki"],
        )

        selected = select_templates_for_data([incompatible, compatible], sample_data(), "power_pool", limit=1)

        self.assertEqual(selected[0].template_id, "event_fast_delta_rank")
        self.assertGreater(score_template_for_data(compatible, sample_data(), "power_pool"), score_template_for_data(incompatible, sample_data(), "power_pool"))

    def test_select_templates_excludes_incompatible_and_deprecated_records(self):
        compatible = TemplateRecord(
            template_id="matrix_ready", hypothesis="Compatible", skeleton="rank({field})",
            required_field_types=["MATRIX"], compatible_semantic_tags=[], operator_tags=[], status="seed",
            correlation_risk="low", repair_levers=[], source_paths=[],
        )
        incompatible = TemplateRecord(
            template_id="vector_only", hypothesis="Wrong type", skeleton="rank(vec_avg({field}))",
            required_field_types=["VECTOR"], compatible_semantic_tags=[], operator_tags=[], status="submit_proven",
            correlation_risk="low", repair_levers=[], source_paths=[],
        )
        deprecated = TemplateRecord(
            template_id="deprecated_matrix", hypothesis="Old", skeleton="rank({field})",
            required_field_types=["MATRIX"], compatible_semantic_tags=[], operator_tags=[], status="deprecated",
            correlation_risk="low", repair_levers=[], source_paths=[],
        )

        selected = select_templates_for_data([incompatible, deprecated, compatible], sample_data(), "power_pool", limit=3)

        self.assertEqual([template.template_id for template in selected], ["matrix_ready"])

    def test_write_template_library_markdown_creates_reviewable_table(self):
        template = TemplateRecord(
            template_id="quality_spread",
            hypothesis="Cashflow quality minus leverage pressure reprices gradually.",
            skeleton="rank({positive}) - rank({negative})",
            required_field_types=["MATRIX"],
            compatible_semantic_tags=["cashflow", "leverage_pressure"],
            operator_tags=["cross_sectional_normalizer"],
            status="discovery_ready",
            correlation_risk="medium",
            repair_levers=["subindustry_neutralize"],
            source_paths=["knowledge/wiki/30_templates/template_families.md"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = write_template_library_markdown(Path(tmp) / "template_library.md", [template], "2026-07-10T00:00:00Z")
            text = output.read_text(encoding="utf-8")

        self.assertIn("quality_spread", text)
        self.assertIn("Cashflow quality", text)


if __name__ == "__main__":
    unittest.main()
