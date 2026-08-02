import json
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

    def test_clean_structure_reports_missing_required_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw").mkdir()

            report = evaluate_clean_knowledge_structure(root)

        missing = {Path(issue["path"]).name for issue in report["issues"] if issue["code"] == "missing_required_layer"}
        self.assertEqual(missing, {"machine", "wiki"})
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
            private_note = root / "raw" / "learn" / "private" / "notes.md"
            private_note.parent.mkdir(parents=True)
            private_note.write_text("private note\n", encoding="utf-8")
            credentials = root / "raw" / "learn" / "credentials" / "config.md"
            credentials.parent.mkdir(parents=True)
            credentials.write_text("config\n", encoding="utf-8")

            planned = plan_obsolete_active_cleanup(root)
            actions = {Path(item.path).relative_to(root).as_posix(): item.action for item in planned}

            self.assertEqual(actions["wiki/20_semantics/old.md"], "remove")
            self.assertEqual(actions["raw/learn/.env"], "refuse")
            self.assertEqual(actions["raw/learn/private/notes.md"], "refuse")
            self.assertEqual(actions["raw/learn/credentials/config.md"], "refuse")

            blocked = apply_obsolete_active_cleanup(root, "2026-07-30T00:00:00+00:00", dry_run=False)

            self.assertTrue(blocked["blocked"])
            self.assertTrue(ordinary.exists())

            summary = apply_obsolete_active_cleanup(
                root,
                "2026-07-30T00:00:00+00:00",
                dry_run=False,
                verified_compile=True,
            )

            self.assertFalse(ordinary.exists())
            self.assertFalse(ordinary.parent.exists())
            self.assertTrue(sensitive.exists())
            self.assertTrue(private_note.exists())
            self.assertTrue(credentials.exists())
            self.assertEqual(summary["removed_count"], 1)
            self.assertEqual(summary["refused_count"], 3)
            self.assertTrue((root / "raw" / "maintenance" / "cleanup_logs").exists())

    def test_cleanup_writes_auditable_noop_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("raw", "machine", "wiki"):
                (root / name).mkdir()

            summary = apply_obsolete_active_cleanup(
                root,
                "2026-07-30T00:00:00+00:00",
                dry_run=False,
                verified_compile=True,
            )
            log_path = Path(summary["cleanup_log_path"])

            self.assertEqual(summary["candidate_count"], 0)
            self.assertTrue(log_path.exists())
            self.assertEqual(json.loads(log_path.read_text(encoding="utf-8"))["event"], "cleanup_run")


if __name__ == "__main__":
    unittest.main()
