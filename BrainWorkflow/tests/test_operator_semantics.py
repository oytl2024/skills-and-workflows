import tempfile
import unittest
from pathlib import Path

from wqb.operator_semantics import (
    OperatorSemanticRecord,
    compile_operator_semantics,
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
            output = root / "wiki" / "20_semantics" / "operator_semantics.jsonl"
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
                "source_paths": ["wiki/20_semantics/operator_catalog_official.md"],
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
                "source_paths": "wiki/20_semantics/operator_catalog_official.md",
            }
        )

        self.assertEqual(record.workflow_uses, [])
        self.assertEqual(record.compatible_field_types, ["MATRIX"])
        self.assertEqual(record.template_tags, ["cross_sectional"])
        self.assertEqual(record.risk_tags, [])
        self.assertEqual(record.repair_levers, ["group_rank"])
        self.assertEqual(record.source_paths, ["wiki/20_semantics/operator_catalog_official.md"])

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
                source_paths=["wiki/20_semantics/operators.md"],
            )

            write_operator_semantics_jsonl(jsonl, [record])
            write_operator_semantics_markdown(md, [record], "2026-07-22T00:00:00+00:00")
            loaded = load_operator_semantics(jsonl)
            markdown = md.read_text(encoding="utf-8")

        self.assertEqual(loaded[0].operator, "vec_avg")
        self.assertIn("vector_to_matrix", markdown)
        self.assertIn("summarize_vector_values", markdown)
        self.assertIn("Sources", markdown)
        self.assertIn("wiki/20_semantics/operators.md", markdown)


if __name__ == "__main__":
    unittest.main()
