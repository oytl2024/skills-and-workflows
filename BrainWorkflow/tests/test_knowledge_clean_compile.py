import tempfile
import unittest
from pathlib import Path

from wqb.knowledge_clean_compile import (
    apply_obsolete_active_cleanup,
    evaluate_clean_knowledge_structure,
    plan_obsolete_active_cleanup,
)


class KnowledgeCleanCompileTests(unittest.TestCase):
    def test_clean_structure_accepts_only_raw_machine_wiki(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("raw", "machine", "wiki"):
                (root / name).mkdir()

            report = evaluate_clean_knowledge_structure(root)

            self.assertEqual(report["issue_count"], 0)
            self.assertTrue(report["clean"])

    def test_clean_structure_reports_legacy_active_paths_and_wiki_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw" / "learn").mkdir(parents=True)
            (root / "raw" / "learn" / "glossary.md").write_text("# old\n", encoding="utf-8")
            (root / "wiki" / "20_semantics").mkdir(parents=True)
            (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text("{}\n", encoding="utf-8")

            report = evaluate_clean_knowledge_structure(root)
            codes = {issue["code"] for issue in report["issues"]}

            self.assertIn("legacy_active_path", codes)
            self.assertIn("machine_resource_inside_wiki", codes)
            self.assertFalse(report["clean"])

    def test_cleanup_refuses_sensitive_files_and_removes_ordinary_legacy_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ordinary = root / "wiki" / "20_semantics" / "old.md"
            ordinary.parent.mkdir(parents=True)
            ordinary.write_text("# old\n", encoding="utf-8")
            sensitive = root / "raw" / "learn" / ".env"
            sensitive.parent.mkdir(parents=True)
            sensitive.write_text("SECRET=1\n", encoding="utf-8")

            planned = plan_obsolete_active_cleanup(root)
            by_name = {Path(item.path).name: item.action for item in planned}

            self.assertEqual(by_name["old.md"], "remove")
            self.assertEqual(by_name[".env"], "refuse")

            summary = apply_obsolete_active_cleanup(root, "2026-07-30T00:00:00+00:00", dry_run=False)

            self.assertFalse(ordinary.exists())
            self.assertFalse(ordinary.parent.exists())
            self.assertTrue(sensitive.exists())
            self.assertEqual(summary["removed_count"], 1)
            self.assertEqual(summary["refused_count"], 1)
            self.assertTrue((root / "raw" / "maintenance" / "cleanup_logs").exists())


if __name__ == "__main__":
    unittest.main()
