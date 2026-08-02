import json
from pathlib import Path
import tempfile
import unittest

from wqb.knowledge_experience_compile import compile_human_experience_wiki


class KnowledgeExperienceCompileTests(unittest.TestCase):
    def test_compile_writes_only_target_human_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            machine = root / "machine"
            machine.mkdir(parents=True)
            (machine / "data_ledger.jsonl").write_text(
                json.dumps(
                    {
                        "dataset_id": "analyst_ds",
                        "field_id": "analyst_revision",
                        "field_type": "MATRIX",
                        "semantic_tags": ["analyst", "revision"],
                        "correlation_risk": "low",
                        "coverage": 0.91,
                        "source_paths": ["raw/platform/data_fields/2026-07-30/data_fields.jsonl"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (machine / "template_library.jsonl").write_text(
                json.dumps(
                    {
                        "template_id": "analyst_revision_delay_rank",
                        "template_family": "event_revision",
                        "hypothesis": "Analyst revisions can proxy improving expectations.",
                        "required_field_types": ["MATRIX"],
                        "compatible_semantic_tags": ["analyst", "revision"],
                        "operator_tags": ["rank", "ts_delta"],
                        "status": "seed",
                        "correlation_risk": "low",
                        "repair_levers": ["neutralization", "decay"],
                        "source_paths": ["raw/community/forum/example.md"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (machine / "benchmark_rules.jsonl").write_text(
                json.dumps(
                    {
                        "rule_id": "near_miss_stable_pnl_promotion",
                        "issue_types": ["near_miss"],
                        "description": "Stable PnL deserves repair review.",
                        "promotion_condition": "PNL shape is straight enough.",
                        "action": "Create a repair candidate.",
                        "evidence_paths": ["raw/community/user_messages/example.md"],
                        "consumed_by": ["triage"],
                        "risk": "repair budget can be wasted",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            summary = compile_human_experience_wiki(root, "2026-07-30T00:00:00+00:00")

            self.assertEqual(summary["page_count"], 6)
            self.assertTrue((root / "wiki" / "00_start_here.md").exists())
            self.assertTrue((root / "wiki" / "20_data_semantics.md").exists())
            self.assertFalse((root / "wiki" / "20_semantics" / "data_ledger.jsonl").exists())

    def test_human_pages_are_compact_and_do_not_dump_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "machine").mkdir()
            (root / "machine" / "data_ledger.jsonl").write_text("", encoding="utf-8")
            summary = compile_human_experience_wiki(root, "2026-07-30T00:00:00+00:00")

            for path_text in summary["page_paths"]:
                text = Path(path_text).read_text(encoding="utf-8")
                self.assertLess(len(text), 12000)
                self.assertNotIn('{"', text)
                self.assertTrue(text.startswith("---\n"))


if __name__ == "__main__":
    unittest.main()
