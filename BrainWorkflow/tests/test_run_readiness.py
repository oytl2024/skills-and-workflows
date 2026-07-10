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
