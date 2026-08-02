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
    def _write_compile_report(self, root: Path, name: str, payload: dict[str, object]) -> Path:
        path = root / "raw" / "maintenance" / "compile_reports" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

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

            report_path = self._write_compile_report(root, "compile.json", {"status": "completed"})
            summary = apply_obsolete_active_cleanup(
                root,
                "2026-07-30T00:00:00+00:00",
                dry_run=False,
                verification_report_path=report_path,
            )

            self.assertFalse(ordinary.exists())
            self.assertFalse(ordinary.parent.exists())
            self.assertTrue(sensitive.exists())
            self.assertTrue(private_note.exists())
            self.assertTrue(credentials.exists())
            self.assertEqual(summary["removed_count"], 1)
            self.assertEqual(summary["refused_count"], 3)
            self.assertTrue((root / "raw" / "maintenance" / "cleanup_logs").exists())

    def test_cleanup_blocks_non_dry_run_without_compile_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ordinary = root / "wiki" / "20_semantics" / "old.md"
            ordinary.parent.mkdir(parents=True)
            ordinary.write_text("# old\n", encoding="utf-8")

            summary = apply_obsolete_active_cleanup(root, dry_run=False)

            self.assertTrue(summary["blocked"])
            self.assertEqual(summary["verification_status"], "missing")
            self.assertTrue(ordinary.exists())

    def test_cleanup_blocks_failed_compile_report_and_logs_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ordinary = root / "wiki" / "20_semantics" / "old.md"
            ordinary.parent.mkdir(parents=True)
            ordinary.write_text("# old\n", encoding="utf-8")
            report_path = self._write_compile_report(root, "failed.json", {"status": "failed"})

            summary = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=report_path)
            rows = [json.loads(line) for line in Path(summary["cleanup_log_path"]).read_text(encoding="utf-8").splitlines()]

            self.assertTrue(summary["blocked"])
            self.assertEqual(summary["verification_status"], "failed")
            self.assertTrue(ordinary.exists())
            self.assertTrue(all(row["verification_report_path"] == str(report_path.resolve()) for row in rows))
            self.assertTrue(all(row["verification_status"] == "failed" for row in rows))

    def test_cleanup_removes_obsolete_files_with_successful_compile_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ordinary = root / "wiki" / "20_semantics" / "old.md"
            ordinary.parent.mkdir(parents=True)
            ordinary.write_text("# old\n", encoding="utf-8")
            report_path = self._write_compile_report(root, "passed.json", {"passed": True})

            summary = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=report_path)
            rows = [json.loads(line) for line in Path(summary["cleanup_log_path"]).read_text(encoding="utf-8").splitlines()]

            self.assertFalse(summary["blocked"])
            self.assertEqual(summary["verification_status"], "passed")
            self.assertFalse(ordinary.exists())
            self.assertTrue(all(row["verification_report_path"] == str(report_path.resolve()) for row in rows))
            self.assertTrue(all(row["verification_status"] == "passed" for row in rows))

    def test_cleanup_dry_run_remains_ungated_and_auditable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ordinary = root / "wiki" / "20_semantics" / "old.md"
            ordinary.parent.mkdir(parents=True)
            ordinary.write_text("# old\n", encoding="utf-8")

            summary = apply_obsolete_active_cleanup(root, dry_run=True)
            rows = [json.loads(line) for line in Path(summary["cleanup_log_path"]).read_text(encoding="utf-8").splitlines()]

            self.assertFalse(summary["blocked"])
            self.assertEqual(summary["verification_status"], "not_required")
            self.assertTrue(ordinary.exists())
            self.assertTrue(all(row["verification_status"] == "not_required" for row in rows))

    def test_cleanup_writes_auditable_noop_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("raw", "machine", "wiki"):
                (root / name).mkdir()

            report_path = self._write_compile_report(root, "compile.json", {"status": "passed"})
            summary = apply_obsolete_active_cleanup(
                root,
                "2026-07-30T00:00:00+00:00",
                dry_run=False,
                verification_report_path=report_path,
            )
            log_path = Path(summary["cleanup_log_path"])

            self.assertEqual(summary["candidate_count"], 0)
            self.assertTrue(log_path.exists())
            self.assertEqual(json.loads(log_path.read_text(encoding="utf-8"))["event"], "cleanup_run")


if __name__ == "__main__":
    unittest.main()
