import json
import tempfile
import unittest
from pathlib import Path

from wqb.knowledge_bootstrap import bootstrap_knowledge, bootstrap_summary_to_dict


class KnowledgeBootstrapTests(unittest.TestCase):
    def create_seed_files(self, seed_root: Path) -> None:
        seed_root.mkdir(parents=True, exist_ok=True)
        (seed_root / "data_ledger.example.jsonl").write_text(
            json.dumps(
                {
                    "dataset_id": "news12",
                    "dataset_name": "News Events",
                    "field_id": "news12_sentiment_fast_d1",
                    "field_type": "MATRIX",
                    "region": "USA",
                    "delay": 1,
                    "universe": "TOP3000",
                    "semantic_tags": ["event", "sentiment", "power_pool"],
                    "coverage": 0.82,
                    "alpha_count": 12,
                    "user_count": 4,
                    "simulation_usage_count": 1,
                    "submitted_usage_count": 0,
                    "last_used_at": "2026-07-09",
                    "best_result_label": "repairable_signal",
                    "correlation_risk": "medium",
                    "source_paths": ["seed"],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (seed_root / "template_library.example.jsonl").write_text(
            json.dumps(
                {
                    "template_id": "event_fast_delta_rank",
                    "hypothesis": "Fast event sentiment changes are incorporated gradually.",
                    "skeleton": "rank(ts_delta({field}, 1))",
                    "required_field_types": ["MATRIX"],
                    "compatible_semantic_tags": ["event", "sentiment", "power_pool"],
                    "operator_tags": ["time_series_surprise"],
                    "status": "seed",
                    "correlation_risk": "low",
                    "repair_levers": ["group_neutralize"],
                    "source_paths": ["seed"],
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_bootstrap_creates_formal_vault_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)

            summary = bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")

            expected = [
                root / "wiki" / "20_semantics" / "data_ledger.jsonl",
                root / "wiki" / "20_semantics" / "data_ledger.md",
                root / "wiki" / "30_templates" / "template_library.jsonl",
                root / "wiki" / "30_templates" / "template_library.md",
                root / "wiki" / "80_maintenance" / "freshness_manifest.json",
                root / "wiki" / "80_maintenance" / "bootstrap_report.md",
                root / "wiki" / "10_foundations" / "activity_snapshot.md",
            ]

            self.assertTrue(all(path.exists() for path in expected))
            self.assertEqual(summary.data_ledger_count, 1)
            self.assertEqual(summary.template_count, 1)

    def test_bootstrap_marks_seed_rows_as_schema_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)

            summary = bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")
            ledger_text = (root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8")
            template_text = (root / "wiki" / "30_templates" / "template_library.jsonl").read_text(encoding="utf-8")
            manifest = json.loads((root / "wiki" / "80_maintenance" / "freshness_manifest.json").read_text(encoding="utf-8"))
            payload = bootstrap_summary_to_dict(summary)

        self.assertIn('"source_quality": "schema_seed"', ledger_text)
        self.assertIn('"source_quality": "schema_seed"', template_text)
        self.assertTrue(any("freshness_manifest.json" in path for path in payload["artifact_paths"]))
        self.assertIn("data_ledger", {row["name"] for row in manifest})
        self.assertIn("template_library", {row["name"] for row in manifest})
