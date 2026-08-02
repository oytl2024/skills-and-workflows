import json
from pathlib import Path
import tempfile
import unittest

from wqb.knowledge_maintenance import run_knowledge_maintenance


class KnowledgeMaintenanceTests(unittest.TestCase):
    def test_compile_knowledge_creates_clean_machine_and_wiki_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "machine").mkdir()
            (root / "machine" / "data_ledger.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "template_library.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "benchmark_rules.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "research_records.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "operator_ledger.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "scope_matrix.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "freshness_manifest.json").write_text("[]", encoding="utf-8")

            report = run_knowledge_maintenance(root, "2026-07-30T00:00:00+00:00", apply_cleanup=True)

            report_path = root / "raw" / "maintenance" / "compile_reports" / "2026-07-30.json"
            self.assertEqual(report["status"], "completed")
            self.assertTrue((root / "wiki" / "00_start_here.md").exists())
            self.assertTrue(report_path.exists())
            self.assertEqual(report["report_path"], str(report_path))
            self.assertEqual(report["cleanup"]["verification_report_path"], str(report_path.resolve()))
            self.assertEqual(report["cleanup"]["verification_status"], "completed")
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["status"], "completed")

    def test_compile_knowledge_records_blocker_when_structure_is_not_clean_after_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw" / "learn").mkdir(parents=True)
            (root / "raw" / "learn" / ".env").write_text("SECRET=1\n", encoding="utf-8")

            report = run_knowledge_maintenance(root, "2026-07-30T00:00:00+00:00", apply_cleanup=True)

            self.assertEqual(report["status"], "blocked")
            self.assertGreater(report["health"]["issue_count"], 0)
            self.assertTrue((root / "raw" / "learn" / ".env").exists())
            self.assertEqual(report["cleanup"]["verification_status"], "completed")


if __name__ == "__main__":
    unittest.main()
