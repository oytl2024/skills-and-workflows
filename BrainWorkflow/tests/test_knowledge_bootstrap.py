import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from wqb.data_ledger import load_data_ledger
from wqb.knowledge_bootstrap import bootstrap_knowledge, bootstrap_summary_to_dict
from wqb.knowledge_clean_compile import evaluate_clean_knowledge_structure
from wqb.knowledge_freshness import evaluate_knowledge_contract_health


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
                root / "machine" / "data_ledger.jsonl",
                root / "machine" / "template_library.jsonl",
                root / "machine" / "freshness_manifest.json",
                root / "raw" / "platform" / "activities" / "bootstrap_activity_snapshot.md",
                root / "raw" / "maintenance" / "bootstrap_reports" / "2026-07-10.json",
            ]

            self.assertTrue(all(path.exists() for path in expected))
            self.assertFalse((root / "wiki" / "20_semantics" / "data_ledger.md").exists())
            self.assertFalse((root / "wiki" / "30_templates" / "template_library.md").exists())
            self.assertFalse((root / "wiki" / "80_maintenance" / "bootstrap_report.md").exists())
            self.assertFalse((root / "wiki" / "10_foundations" / "activity_snapshot.md").exists())
            self.assertFalse((root / "wiki" / "20_semantics" / "data_ledger.jsonl").exists())
            self.assertFalse((root / "wiki" / "30_templates" / "template_library.jsonl").exists())
            self.assertFalse((root / "wiki" / "80_maintenance" / "freshness_manifest.json").exists())
            self.assertEqual(summary.data_ledger_count, 1)
            self.assertEqual(summary.template_count, 1)

    def test_bootstrap_preserves_existing_compiled_ledger_and_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)
            ledger_jsonl = root / "machine" / "data_ledger.jsonl"
            template_jsonl = root / "machine" / "template_library.jsonl"
            existing = {
                ledger_jsonl: '{"field_id":"authoritative_field","source_quality":"platform_api"}\n',
                template_jsonl: '{"template_id":"curated_template","status":"submit_proven"}\n',
            }
            for path, content in existing.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            summary = bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")

            preserved = {path: path.read_text(encoding="utf-8") for path in existing}

        self.assertEqual(preserved, existing)
        self.assertTrue(any("preserved" in warning.lower() for warning in summary.warnings))

    def test_bootstrap_marks_seed_rows_as_schema_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)

            summary = bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")
            ledger_text = (root / "machine" / "data_ledger.jsonl").read_text(encoding="utf-8")
            template_text = (root / "machine" / "template_library.jsonl").read_text(encoding="utf-8")
            manifest = json.loads((root / "machine" / "freshness_manifest.json").read_text(encoding="utf-8"))
            payload = bootstrap_summary_to_dict(summary)

        self.assertIn('"source_quality": "schema_seed"', ledger_text)
        self.assertIn('"source_quality": "schema_seed"', template_text)
        self.assertTrue(any("freshness_manifest.json" in path for path in payload["artifact_paths"]))
        self.assertIn("data_ledger", {row["name"] for row in manifest})
        self.assertIn("template_library", {row["name"] for row in manifest})

    def test_bootstrap_hides_schema_seed_coverage_from_data_ledger_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)

            bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")
            ledger_path = root / "machine" / "data_ledger.jsonl"
            raw_row = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])
            loaded_record = load_data_ledger(ledger_path)[0]

        self.assertEqual(raw_row["source_quality"], "schema_seed")
        self.assertEqual(raw_row["coverage_status"], "partial")
        self.assertEqual(loaded_record.coverage, 0.0)

    def test_bootstrap_manifest_and_report_identify_non_refreshed_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)

            summary = bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")

            manifest = json.loads(
                (root / "machine" / "freshness_manifest.json").read_text(encoding="utf-8")
            )
            report = json.loads((root / "raw" / "maintenance" / "bootstrap_reports" / "2026-07-10.json").read_text(encoding="utf-8"))

        by_name = {row["name"]: row for row in manifest}
        self.assertEqual(
            by_name["benchmark_rules"]["path"],
            "machine/benchmark_rules.jsonl",
        )
        self.assertEqual(
            by_name["operator_catalog"]["path"],
            "machine/operator_ledger.jsonl",
        )
        for name in ("data_ledger", "template_library", "activity_snapshot"):
            self.assertEqual(by_name[name]["updated_at"], "2026-07-10")
            self.assertEqual(by_name[name]["status"], "refreshed")
        for name in ("benchmark_rules", "operator_catalog", "research_option_cards"):
            self.assertNotEqual(by_name[name]["updated_at"], "2026-07-10")
            self.assertEqual(by_name[name]["status"], "not_refreshed")
            self.assertTrue(by_name[name]["source_note"])
            self.assertGreater(by_name[name]["max_age_days"], 0)
        self.assertEqual(report["coverage_status"], "partial")
        self.assertEqual(report["source_quality"], "schema_seed")
        for name in ("benchmark_rules", "operator_catalog", "research_option_cards"):
            self.assertIn(name, report["not_refreshed"])
        self.assertTrue(any("not refreshed" in warning.lower() for warning in summary.warnings))

    def test_bootstrap_does_not_create_dirty_wiki_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)

            bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")

            clean = evaluate_clean_knowledge_structure(root)
            health = evaluate_knowledge_contract_health(root)

        self.assertTrue(clean["clean"], clean["issues"])
        self.assertEqual(health["issue_count"], 0, health["issues"])

    def test_bootstrap_backfills_metadata_and_source_index_for_existing_activity_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)
            activity = root / "raw" / "platform" / "activities" / "bootstrap_activity_snapshot.md"
            activity.parent.mkdir(parents=True)
            activity.write_text("# Existing Activity Snapshot\n", encoding="utf-8")

            bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")

            machine_index = root / "machine" / "source_index.jsonl"
            raw_index = root / "raw" / "source_index.md"
            health = evaluate_knowledge_contract_health(root)
            rows = [
                json.loads(line)
                for line in machine_index.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            raw_index_exists = raw_index.exists()

        self.assertEqual(health["issue_count"], 0, health["issues"])
        self.assertTrue(raw_index_exists)
        self.assertIn(
            "raw/platform/activities/bootstrap_activity_snapshot.md",
            {row["path"] for row in rows},
        )

    def test_bootstrap_normalizes_existing_freshness_manifest_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)
            manifest = root / "machine" / "freshness_manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    [
                        {
                            "name": "operator_catalog",
                            "path": "wiki/20_semantics/operator_catalog_official.md",
                            "updated_at": "2026-07-01",
                            "max_age_days": 30,
                            "status": "reviewed",
                        },
                        {
                            "name": "activity_snapshot",
                            "path": "wiki/10_foundations/activity_snapshot.md",
                            "updated_at": "2026-07-01",
                            "max_age_days": 1,
                            "status": "reviewed",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")
            rows = json.loads(manifest.read_text(encoding="utf-8"))

        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["operator_catalog"]["path"], "machine/operator_ledger.jsonl")
        self.assertEqual(
            by_name["activity_snapshot"]["path"],
            "raw/platform/activities/bootstrap_activity_snapshot.md",
        )
        self.assertEqual(by_name["operator_catalog"]["updated_at"], "2026-07-01")
        self.assertEqual(by_name["operator_catalog"]["status"], "reviewed")
        for name in ("data_ledger", "template_library", "benchmark_rules", "research_option_cards"):
            self.assertIn(name, by_name)

    def test_bootstrap_rewrites_stale_activity_metadata_managed_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)
            activity = root / "raw" / "platform" / "activities" / "bootstrap_activity_snapshot.md"
            activity.parent.mkdir(parents=True)
            body = "# Existing Activity Snapshot\n\nBody stays.\n"
            activity.write_text(
                "\n".join(
                    [
                        "---",
                        "source_type: old_type",
                        "source_family: wiki/10_foundations",
                        "source_path: raw/platform/activities/bootstrap_activity_snapshot.md",
                        "captured_at: 2026-07-01T00:00:00Z",
                        "capture_tool: old_tool",
                        "record_count: 1",
                        "content_hash: stale",
                        "update_check: stale",
                        "compiled_targets:",
                        "  - wiki/10_foundations/activity_snapshot.md",
                        "---",
                        body,
                    ]
                ),
                encoding="utf-8",
            )

            bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")
            text = activity.read_text(encoding="utf-8")

        self.assertIn("source_type: bootstrap_activity_snapshot", text)
        self.assertIn("source_family: raw/platform/activities", text)
        self.assertIn("capture_tool: wqb.knowledge_bootstrap", text)
        self.assertIn("update_check: rerun platform activity refresh or bootstrap", text)
        self.assertIn("  - wiki/00_start_here.md", text)
        self.assertNotIn("content_hash: stale", text)
        self.assertNotIn("wiki/10_foundations/activity_snapshot.md", text)
        self.assertIn("Body stays.", text)

    def test_bootstrap_repairs_stale_activity_captured_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)
            activity = root / "raw" / "platform" / "activities" / "bootstrap_activity_snapshot.md"
            activity.parent.mkdir(parents=True)
            body = "# Existing Activity Snapshot\n\nBody stays.\n"
            activity.write_text(
                "\n".join(
                    [
                        "---",
                        "source_type: bootstrap_activity_snapshot",
                        "source_family: raw/platform/activities",
                        "source_path: raw/platform/activities/bootstrap_activity_snapshot.md",
                        "captured_at: 2026-07-01T00:00:00Z",
                        "capture_tool: wqb.knowledge_bootstrap",
                        "record_count: 1",
                        f"content_hash: {hashlib.sha256(body.encode('utf-8')).hexdigest()}",
                        "update_check: rerun platform activity refresh or bootstrap",
                        "compiled_targets:",
                        "  - wiki/00_start_here.md",
                        "---",
                        body,
                    ]
                ),
                encoding="utf-8",
            )

            bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")
            text = activity.read_text(encoding="utf-8")

        self.assertIn("captured_at: 2026-07-10T00:00:00Z", text)
        self.assertNotIn("captured_at: 2026-07-01T00:00:00Z", text)
        self.assertIn("Body stays.", text)

    def test_bootstrap_merges_duplicate_known_freshness_manifest_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)
            manifest = root / "machine" / "freshness_manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    [
                        {
                            "name": "operator_catalog",
                            "path": "wiki/20_semantics/operator_catalog_official.md",
                            "updated_at": "2026-07-01",
                            "max_age_days": 30,
                            "status": "stale_reviewed",
                        },
                        {
                            "name": "operator_catalog",
                            "path": "machine/operator_ledger.jsonl",
                            "updated_at": "2026-07-03",
                            "max_age_days": 30,
                            "status": "latest_reviewed",
                        },
                        {
                            "name": "activity_snapshot",
                            "path": "wiki/10_foundations/activity_snapshot.md",
                            "updated_at": "2026-07-02",
                            "max_age_days": 1,
                            "status": "reviewed",
                        },
                        {
                            "name": "custom_note",
                            "path": "raw/community/advisor_notes/custom.md",
                            "updated_at": "2026-07-01",
                            "max_age_days": 7,
                        },
                    ]
                ),
                encoding="utf-8",
            )

            bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")
            rows = json.loads(manifest.read_text(encoding="utf-8"))

        operator_rows = [row for row in rows if row["name"] == "operator_catalog"]
        activity_rows = [row for row in rows if row["name"] == "activity_snapshot"]
        self.assertEqual(len(operator_rows), 1)
        self.assertEqual(operator_rows[0]["path"], "machine/operator_ledger.jsonl")
        self.assertEqual(operator_rows[0]["updated_at"], "2026-07-03")
        self.assertEqual(operator_rows[0]["status"], "latest_reviewed")
        self.assertEqual(len(activity_rows), 1)
        self.assertEqual(activity_rows[0]["path"], "raw/platform/activities/bootstrap_activity_snapshot.md")
        self.assertIn("custom_note", {row["name"] for row in rows})
