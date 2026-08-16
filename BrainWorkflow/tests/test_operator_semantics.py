import tempfile
import unittest
import json
from pathlib import Path

from wqb.operator_semantics import (
    OperatorSemanticRecord,
    compile_operator_semantics,
    expression_operator_provenance,
    extract_expression_operators,
    load_operator_semantics,
    operator_semantic_record_from_dict,
    score_operator_for_template,
    write_operator_semantics_jsonl,
    write_operator_semantics_markdown,
)


class OperatorSemanticsTests(unittest.TestCase):
    def test_compile_preserves_curated_records_and_adds_missing_canonical_operators(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            output = root / "machine" / "operator_ledger.jsonl"
            output.parent.mkdir(parents=True)
            curated = OperatorSemanticRecord(
                operator="rank",
                family="reviewed_family",
                workflow_uses=["reviewed_use"],
                compatible_field_types=["MATRIX"],
                template_tags=["reviewed"],
                risk_tags=[],
                repair_levers=[],
                source_paths=["raw/community/advisor_notes/rank.md"],
            )
            write_operator_semantics_jsonl(output, [curated])
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-22"
            capture.mkdir(parents=True)
            (capture / "operators.json").write_text(
                '{"generated_at":"2026-07-22T00:00:00Z","operators":[{"name":"rank"},{"name":"group_rank"}]}',
                encoding="utf-8",
            )

            summary = compile_operator_semantics(root, generated_at="2026-07-22T01:00:00Z")
            records = {record.operator: record for record in load_operator_semantics(output)}

        self.assertEqual(summary["record_count"], len(records))
        self.assertEqual(records["rank"].family, "reviewed_family")
        self.assertIn("group_rank", records)

    def test_compile_default_operator_sources_do_not_publish_legacy_wiki_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"

            summary = compile_operator_semantics(root, generated_at="2026-07-22T01:00:00Z")
            rows = [
                json.loads(line)
                for line in (root / "machine" / "operator_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            preview = Path(summary["markdown_path"]).read_text(encoding="utf-8")

        for row in rows:
            self.assertTrue(row["source_paths"])
            self.assertFalse(
                any(str(path).startswith("wiki/20_semantics") for path in row["source_paths"]),
                row,
            )
        self.assertNotIn("wiki/20_semantics", preview)

    def test_compile_normalizes_reviewed_legacy_operator_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            output = root / "machine" / "operator_ledger.jsonl"
            legacy_reviewed = OperatorSemanticRecord(
                operator="group_neutralize",
                family="reviewed_neutralization",
                workflow_uses=["reviewed_bias_control"],
                compatible_field_types=["MATRIX"],
                template_tags=["reviewed"],
                risk_tags=["over_neutralization"],
                repair_levers=["neutralization_subindustry"],
                source_paths=["wiki/20_semantics/operator_catalog_official.md"],
            )
            write_operator_semantics_jsonl(output, [legacy_reviewed])

            summary = compile_operator_semantics(root, generated_at="2026-07-22T01:00:00Z")
            records = {record.operator: record for record in load_operator_semantics(output)}
            preview = Path(summary["markdown_path"]).read_text(encoding="utf-8")

        self.assertEqual(records["group_neutralize"].family, "reviewed_neutralization")
        self.assertEqual(records["group_neutralize"].workflow_uses, ["reviewed_bias_control"])
        self.assertEqual(records["group_neutralize"].source_paths, ["docs/knowledge/operator_data_semantics.md"])
        self.assertNotIn("wiki/20_semantics", preview)

    def test_compile_normalizes_absolute_reviewed_legacy_operator_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            output = root / "machine" / "operator_ledger.jsonl"
            legacy_path = root / "wiki" / "20_semantics" / "operator_catalog_official.md"
            legacy_reviewed = OperatorSemanticRecord(
                operator="winsorize",
                family="reviewed_outlier_control",
                workflow_uses=["cap_outliers"],
                compatible_field_types=["MATRIX"],
                template_tags=["reviewed"],
                risk_tags=[],
                repair_levers=["adjust_std"],
                source_paths=[str(legacy_path)],
            )
            write_operator_semantics_jsonl(output, [legacy_reviewed])

            compile_operator_semantics(root, generated_at="2026-07-22T01:00:00Z")
            records = {record.operator: record for record in load_operator_semantics(output)}

        self.assertEqual(records["winsorize"].family, "reviewed_outlier_control")
        self.assertEqual(records["winsorize"].source_paths, ["docs/knowledge/operator_data_semantics.md"])

    def test_compile_preserves_non_legacy_archive_source_when_normalizing_mixed_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            output = root / "machine" / "operator_ledger.jsonl"
            legacy_path = root / "wiki" / "20_semantics" / "operator_catalog_official.md"
            archive_path = "docs/archive/wiki/20_semantics/operator_notes.md"
            mixed_reviewed = OperatorSemanticRecord(
                operator="zscore",
                family="reviewed_standardizer",
                workflow_uses=["standardize_signal"],
                compatible_field_types=["MATRIX"],
                template_tags=["reviewed"],
                risk_tags=[],
                repair_levers=["winsorize_first"],
                source_paths=[str(legacy_path), archive_path],
            )
            write_operator_semantics_jsonl(output, [mixed_reviewed])

            compile_operator_semantics(root, generated_at="2026-07-22T01:00:00Z")
            records = {record.operator: record for record in load_operator_semantics(output)}

        self.assertEqual(
            records["zscore"].source_paths,
            [archive_path, "docs/knowledge/operator_data_semantics.md"],
        )

    def test_operator_semantic_record_loads_workflow_use_and_risk(self):
        record = operator_semantic_record_from_dict(
            {
                "operator": "group_neutralize",
                "family": "neutralization",
                "workflow_uses": ["reduce_correlation", "remove_group_bias"],
                "compatible_field_types": ["MATRIX"],
                "template_tags": ["cross_sectional_normalizer", "repair"],
                "risk_tags": ["over_neutralization"],
                "repair_levers": ["neutralization_industry", "neutralization_subindustry"],
                "source_paths": ["docs/knowledge/operator_data_semantics.md"],
            }
        )

        self.assertEqual(record.operator, "group_neutralize")
        self.assertIn("reduce_correlation", record.workflow_uses)
        self.assertGreater(score_operator_for_template(record, "MATRIX", ["repair"]), 0.0)
        self.assertLess(
            score_operator_for_template(record, "VECTOR", ["repair"]),
            score_operator_for_template(record, "MATRIX", ["repair"]),
        )

    def test_operator_semantic_record_normalizes_none_and_scalar_list_fields(self):
        record = operator_semantic_record_from_dict(
            {
                "operator": "rank",
                "family": "cross_sectional_normalizer",
                "workflow_uses": None,
                "compatible_field_types": "matrix",
                "template_tags": "cross_sectional",
                "risk_tags": None,
                "repair_levers": "group_rank",
                "source_paths": "docs/knowledge/operator_data_semantics.md",
            }
        )

        self.assertEqual(record.workflow_uses, [])
        self.assertEqual(record.compatible_field_types, ["MATRIX"])
        self.assertEqual(record.template_tags, ["cross_sectional"])
        self.assertEqual(record.risk_tags, [])
        self.assertEqual(record.repair_levers, ["group_rank"])
        self.assertEqual(record.source_paths, ["docs/knowledge/operator_data_semantics.md"])

    def test_expression_operator_provenance_reads_operator_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_operator_semantics_jsonl(
                root / "machine" / "operator_ledger.jsonl",
                [
                    OperatorSemanticRecord(
                        operator="rank",
                        family="cross_sectional_normalizer",
                        workflow_uses=["normalize_cross_section"],
                        compatible_field_types=["MATRIX"],
                        template_tags=["cross_sectional_normalizer"],
                        risk_tags=["crowded_when_common"],
                        repair_levers=["group_rank"],
                        source_paths=["raw/platform/learn/operators.md"],
                    ),
                    OperatorSemanticRecord(
                        operator="ts_delta",
                        family="time_series_change",
                        workflow_uses=["capture_recent_change"],
                        compatible_field_types=["MATRIX"],
                        template_tags=["time_series_surprise"],
                        risk_tags=["turnover_inflation"],
                        repair_levers=["increase_window"],
                        source_paths=["raw/platform/learn/operators.md"],
                    ),
                    OperatorSemanticRecord(
                        operator="vec_avg",
                        family="vector_to_matrix",
                        workflow_uses=["summarize_vector_values"],
                        compatible_field_types=["VECTOR"],
                        template_tags=["vector_to_matrix"],
                        risk_tags=["invalid_raw_vector_use"],
                        repair_levers=["replace_vec_count_with_vec_avg"],
                        source_paths=["raw/platform/learn/operators.md"],
                    ),
                ],
            )

            operators = extract_expression_operators("rank(ts_delta(vec_avg(buzz_trend_metric_11), 5))")
            provenance = expression_operator_provenance(
                "rank(ts_delta(vec_avg(buzz_trend_metric_11), 5))",
                root,
            )

        self.assertEqual(operators, ["rank", "ts_delta", "vec_avg"])
        self.assertEqual([row["operator"] for row in provenance], ["rank", "ts_delta", "vec_avg"])
        self.assertEqual(provenance[0]["source"], "knowledge_operator_ledger")
        self.assertEqual(provenance[1]["family"], "time_series_change")
        self.assertIn("raw/platform/learn/operators.md", provenance[2]["source_paths"])

    def test_write_and_load_operator_semantics_jsonl_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jsonl = root / "operator_semantics.jsonl"
            md = root / "operator_semantics.md"
            record = OperatorSemanticRecord(
                operator="vec_avg",
                family="vector_to_matrix",
                workflow_uses=["summarize_vector_values"],
                compatible_field_types=["VECTOR"],
                template_tags=["event_value"],
                risk_tags=["invalid_raw_vector_use"],
                repair_levers=["replace_vec_count_with_vec_avg"],
                source_paths=["docs/knowledge/operator_data_semantics.md"],
            )

            write_operator_semantics_jsonl(jsonl, [record])
            write_operator_semantics_markdown(md, [record], "2026-07-22T00:00:00+00:00")
            loaded = load_operator_semantics(jsonl)
            markdown = md.read_text(encoding="utf-8")

        self.assertEqual(loaded[0].operator, "vec_avg")
        self.assertIn("vector_to_matrix", markdown)
        self.assertIn("summarize_vector_values", markdown)
        self.assertIn("Sources", markdown)
        self.assertIn("docs/knowledge/operator_data_semantics.md", markdown)


if __name__ == "__main__":
    unittest.main()
