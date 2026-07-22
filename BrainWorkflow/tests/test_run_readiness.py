import json
import tempfile
import unittest
from pathlib import Path

from wqb.run_readiness import evaluate_run_readiness, write_readiness_reports


class RunReadinessTests(unittest.TestCase):
    def write_manifest(self, root: Path) -> None:
        manifest = root / "wiki" / "80_maintenance" / "freshness_manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                [
                    {"name": "data_ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-10", "max_age_days": 1},
                    {"name": "template_library", "path": "wiki/30_templates/template_library.jsonl", "updated_at": "2026-07-10", "max_age_days": 7},
                    {"name": "benchmark_rules", "path": "wiki/50_benchmarks/correlation_and_novelty.md", "updated_at": "2026-07-10", "max_age_days": 7},
                    {"name": "activity_snapshot", "path": "wiki/10_foundations/activity_snapshot.md", "updated_at": "2026-07-10", "max_age_days": 1},
                ]
            ),
            encoding="utf-8",
        )

    def test_research_mode_blocks_missing_compiled_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_manifest(root)

            report = evaluate_run_readiness(root, mode="research", today_value="2026-07-10")

        self.assertFalse(report.passed)
        self.assertTrue(report.blocked)
        self.assertIn("missing_artifact", {issue.code for issue in report.issues})

    def test_maintenance_mode_allows_missing_compiled_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_manifest(root)

            report = evaluate_run_readiness(root, mode="maintenance", today_value="2026-07-10")

        self.assertTrue(report.passed)
        self.assertFalse(report.blocked)
        self.assertIn("missing_artifact", {issue.code for issue in report.issues})

    def test_malformed_freshness_manifest_returns_blocking_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "wiki" / "80_maintenance" / "freshness_manifest.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text("{malformed\n", encoding="utf-8")

            report = evaluate_run_readiness(root, mode="research", today_value="2026-07-10")

        self.assertFalse(report.passed)
        self.assertTrue(report.blocked)
        self.assertIn("parse_error", {issue.code for issue in report.issues})

    def create_minimal_artifacts(self, root: Path) -> None:
        self.write_manifest(root)
        (root / "wiki" / "20_semantics").mkdir(parents=True, exist_ok=True)
        (root / "wiki" / "30_templates").mkdir(parents=True, exist_ok=True)
        (root / "wiki" / "50_benchmarks").mkdir(parents=True, exist_ok=True)
        (root / "wiki" / "10_foundations").mkdir(parents=True, exist_ok=True)
        (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text(json.dumps({"field_id": "f1"}) + "\n", encoding="utf-8")
        (root / "wiki" / "30_templates" / "template_library.jsonl").write_text(json.dumps({"template_id": "t1"}) + "\n", encoding="utf-8")
        (root / "wiki" / "50_benchmarks" / "correlation_and_novelty.md").write_text("# Benchmarks\n", encoding="utf-8")
        (root / "wiki" / "10_foundations" / "activity_snapshot.md").write_text("# Activity Snapshot\n", encoding="utf-8")

    def create_scope_ready_artifacts(self, root: Path) -> None:
        self.create_minimal_artifacts(root)
        (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text(
            json.dumps(
                {
                    "dataset_id": "news12",
                    "dataset_name": "News",
                    "field_id": "news_field",
                    "field_type": "MATRIX",
                    "region": "USA",
                    "delay": 1,
                    "universe": "TOP3000",
                    "semantic_tags": ["power_pool"],
                    "coverage": 0.8,
                    "alpha_count": 0,
                    "user_count": 0,
                    "simulation_usage_count": 0,
                    "submitted_usage_count": 0,
                    "last_used_at": "",
                    "best_result_label": "unexplored",
                    "correlation_risk": "low",
                    "source_paths": [],
                    "source_quality": "platform_raw_capture",
                    "coverage_status": "measured_raw",
                    "source_updated_at": "2026-07-10",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (root / "wiki" / "30_templates" / "template_library.jsonl").write_text(
            json.dumps(
                {
                    "template_id": "matrix_rank",
                    "hypothesis": "Rank the field.",
                    "skeleton": "rank({field})",
                    "required_field_types": ["MATRIX"],
                    "compatible_semantic_tags": ["power_pool"],
                    "operator_tags": [],
                    "status": "seed",
                    "correlation_risk": "low",
                    "repair_levers": [],
                    "source_paths": [],
                    "compatible_regions": ["USA"],
                    "compatible_delays": [1],
                    "compatible_universes": ["TOP3000"],
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_discovery_batch_smaller_than_30_blocks_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_minimal_artifacts(root)

            report = evaluate_run_readiness(root, mode="research", batch_size=12, today_value="2026-07-10")

        self.assertFalse(report.passed)
        self.assertIn("batch_size_too_small", {issue.code for issue in report.issues})

    def test_live_api_requires_explicit_enablement_for_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_minimal_artifacts(root)

            report = evaluate_run_readiness(root, mode="research", live_api_enabled=False, today_value="2026-07-10")

        self.assertFalse(report.passed)
        self.assertIn("live_api_disabled", {issue.code for issue in report.issues})

    def test_submit_candidate_requires_user_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_minimal_artifacts(root)

            report = evaluate_run_readiness(root, mode="submit-candidate", live_api_enabled=True, submit_confirmed=False, today_value="2026-07-10")

        self.assertFalse(report.passed)
        self.assertIn("submit_not_confirmed", {issue.code for issue in report.issues})

    def test_invalid_jsonl_blocks_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_minimal_artifacts(root)
            (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text("{invalid\n", encoding="utf-8")

            report = evaluate_run_readiness(root, mode="research", live_api_enabled=True, today_value="2026-07-10")

        self.assertFalse(report.passed)
        self.assertIn("parse_error", {issue.code for issue in report.issues})

    def test_research_blocks_incompatible_selected_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_scope_ready_artifacts(root)

            report = evaluate_run_readiness(
                root,
                mode="research",
                batch_size=30,
                live_api_enabled=True,
                region="EUR",
                universe="TOP3000",
                delay=1,
                today_value="2026-07-10",
            )

        self.assertFalse(report.passed)
        self.assertIn("no_compatible_data", {issue.code for issue in report.issues})

    def test_research_blocks_zero_coverage_schema_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_scope_ready_artifacts(root)
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8"))
            row["coverage"] = 0.0
            (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

            report = evaluate_run_readiness(
                root,
                mode="research",
                batch_size=30,
                live_api_enabled=True,
                region="USA",
                universe="TOP3000",
                delay=1,
                today_value="2026-07-10",
            )

        self.assertFalse(report.passed)
        self.assertIn("insufficient_data_coverage", {issue.code for issue in report.issues})

    def test_research_blocks_schema_seed_even_with_positive_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_scope_ready_artifacts(root)
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8"))
            row["source_quality"] = "schema_seed"
            row["coverage_status"] = "measured_raw"
            (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

            report = evaluate_run_readiness(
                root,
                mode="research",
                batch_size=30,
                live_api_enabled=True,
                region="USA",
                universe="TOP3000",
                delay=1,
                today_value="2026-07-10",
            )

        self.assertFalse(report.passed)
        self.assertIn("cache_only_data_ledger", {issue.code for issue in report.issues})

    def test_research_blocks_partial_coverage_status_even_with_positive_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_scope_ready_artifacts(root)
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8"))
            row["source_quality"] = "platform_raw_capture"
            row["coverage_status"] = "partial"
            (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

            report = evaluate_run_readiness(
                root,
                mode="research",
                batch_size=30,
                live_api_enabled=True,
                region="USA",
                universe="TOP3000",
                delay=1,
                today_value="2026-07-10",
            )

        self.assertFalse(report.passed)
        self.assertIn("cache_only_data_ledger", {issue.code for issue in report.issues})

    def test_research_readiness_blocks_cache_only_data_ledger_for_selected_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_scope_ready_artifacts(root)
            (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text(
                json.dumps(
                    {
                        "dataset_id": "fundamental3",
                        "dataset_name": "Fundamentals",
                        "field_id": "fnd3_q_cash_fast_d1",
                        "field_type": "MATRIX",
                        "region": "USA",
                        "delay": 1,
                        "universe": "TOP3000",
                        "semantic_tags": ["cash", "power_pool"],
                        "coverage": 0.8,
                        "alpha_count": 1,
                        "user_count": 1,
                        "simulation_usage_count": 0,
                        "submitted_usage_count": 0,
                        "last_used_at": "",
                        "best_result_label": "unexplored_cache_candidate",
                        "correlation_risk": "low",
                        "source_paths": ["docs/knowledge/cache/platform_metadata.json"],
                        "source_quality": "platform_metadata_cache",
                        "coverage_status": "measured_cache",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = evaluate_run_readiness(
                root,
                mode="research",
                batch_size=30,
                live_api_enabled=True,
                region="USA",
                delay=1,
                universe="TOP3000",
                today_value="2026-07-22",
            )

        self.assertTrue(report.blocked)
        self.assertIn("cache_only_data_ledger", [issue.code for issue in report.issues])

    def test_research_blocks_stale_per_record_source_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_scope_ready_artifacts(root)
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8"))
            row["source_updated_at"] = "2026-07-08"
            (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

            report = evaluate_run_readiness(
                root,
                mode="research",
                batch_size=30,
                live_api_enabled=True,
                region="USA",
                universe="TOP3000",
                delay=1,
                today_value="2026-07-10",
            )

        self.assertFalse(report.passed)
        self.assertIn("stale_scope_data", {issue.code for issue in report.issues})

    def test_research_blocks_missing_per_record_source_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_scope_ready_artifacts(root)
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8"))
            row.pop("source_updated_at")
            (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

            report = evaluate_run_readiness(
                root,
                mode="research",
                batch_size=30,
                live_api_enabled=True,
                region="USA",
                universe="TOP3000",
                delay=1,
                today_value="2026-07-10",
            )

        self.assertFalse(report.passed)
        self.assertIn("cache_only_data_ledger", {issue.code for issue in report.issues})

    def test_research_passes_with_scope_ready_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_scope_ready_artifacts(root)

            report = evaluate_run_readiness(
                root,
                mode="research",
                batch_size=30,
                live_api_enabled=True,
                region="USA",
                universe="TOP3000",
                delay=1,
                today_value="2026-07-10",
            )

        self.assertTrue(report.passed)
        self.assertFalse(report.blocked)

    def test_write_readiness_reports_creates_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_minimal_artifacts(root)
            report = evaluate_run_readiness(root, mode="plan-only", today_value="2026-07-10")
            json_path, md_path = write_readiness_reports(root / "runs" / "run1", report)

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")

        self.assertEqual(payload["mode"], "plan-only")
        self.assertIn("# Run Readiness Report", markdown)
