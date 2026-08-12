import json
import tempfile
import unittest
from pathlib import Path

from wqb.knowledge_source_resolver import resolve_source_inputs


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """Input: JSONL path and rows. Output: none. Write machine-ledger test fixtures."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class KnowledgeSourceResolverTests(unittest.TestCase):
    def test_resolver_prefers_matching_knowledge_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_jsonl(
                root / "machine" / "data_ledger.jsonl",
                [
                    {
                        "field_id": "buzz_intensity_score_15",
                        "field_type": "VECTOR",
                        "dataset_id": "analyst_buzz",
                        "coverage": 0.93,
                        "region": "USA",
                        "delay": 1,
                        "universe": "TOP3000",
                        "instrument_type": "EQUITY",
                        "source_quality": "platform_raw_capture",
                        "source_updated_at": "2026-08-12",
                        "source_paths": ["raw/platform/data_fields/2026-08-12/data_fields.md"],
                        "compatible_template_ids": ["vector_event_count_surprise"],
                    }
                ],
            )
            write_jsonl(root / "machine" / "operator_ledger.jsonl", [{"operator": "vec_count", "source_paths": ["raw/platform/operators.md"]}])
            write_jsonl(root / "machine" / "template_library.jsonl", [{"template_id": "vector_event_count_surprise", "skeleton": "rank(ts_delta(vec_count({field}), 1))"}])

            selection = resolve_source_inputs(
                root,
                {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                field_search="buzz",
                allow_live_fallback=False,
            )

        self.assertEqual(selection.field_source, "knowledge")
        self.assertEqual(selection.operator_source, "knowledge")
        self.assertEqual(selection.template_source, "template_library")
        self.assertEqual(selection.fields[0]["id"], "buzz_intensity_score_15")
        self.assertEqual(selection.provenance[0]["source_quality"], "platform_raw_capture")
        self.assertEqual(selection.blockers, [])

    def test_resolver_blocks_when_knowledge_missing_and_live_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            selection = resolve_source_inputs(
                Path(tmp),
                {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                field_search="buzz",
                allow_live_fallback=False,
            )

        self.assertEqual(selection.field_source, "missing")
        self.assertIn("knowledge_field_coverage_missing", selection.blockers)


if __name__ == "__main__":
    unittest.main()
