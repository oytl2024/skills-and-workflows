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

    def _successful_compile_evidence(self, root: Path, name: str) -> Path:
        return self._write_compile_report(
            root,
            name,
            {
                "report_type": "knowledge_maintenance_pre_cleanup_evidence",
                "status": "completed",
                "compile": {"status": "completed"},
                "pre_cleanup_health": {"blocking_issue_count": 0},
            },
        )

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

    def test_clean_structure_reports_retired_foundation_and_workflow_wiki_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            foundation = root / "wiki" / "10_foundations" / "old.md"
            workflow = root / "wiki" / "60_workflows" / "old.md"
            foundation.parent.mkdir(parents=True)
            workflow.parent.mkdir(parents=True)
            foundation.write_text("# old foundation\n", encoding="utf-8")
            workflow.write_text("# old workflow\n", encoding="utf-8")

            report = evaluate_clean_knowledge_structure(root)

        legacy_paths = {
            Path(issue["path"]).relative_to(root).as_posix()
            for issue in report["issues"]
            if issue["code"] == "legacy_active_path"
        }
        self.assertIn("wiki/10_foundations", legacy_paths)
        self.assertIn("wiki/60_workflows", legacy_paths)
        self.assertFalse(report["clean"])

    def test_clean_structure_reports_missing_required_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw").mkdir()

            report = evaluate_clean_knowledge_structure(root)

        missing = {Path(issue["path"]).name for issue in report["issues"] if issue["code"] == "missing_required_layer"}
        self.assertEqual(missing, {"machine", "wiki"})
        self.assertFalse(report["clean"])

    def test_clean_structure_reports_root_level_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("raw", "machine", "wiki"):
                (root / name).mkdir()
            ordinary = root / "data_ledger.jsonl"
            ordinary.write_text("{}\n", encoding="utf-8")

            report = evaluate_clean_knowledge_structure(root)
            self.assertFalse(report["clean"])
            self.assertIn(
                str(ordinary),
                {issue["path"] for issue in report["issues"] if issue["code"] == "root_level_file"},
            )

    def test_cleanup_routes_root_level_files_through_sensitive_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ordinary = root / "old_notes.txt"
            sensitive = root / "private.txt"
            ordinary.write_text("obsolete\n", encoding="utf-8")
            sensitive.write_text("do not delete\n", encoding="utf-8")
            report_path = self._successful_compile_evidence(root, "compile.json")

            planned = plan_obsolete_active_cleanup(root)
            actions = {Path(item.path).name: item.action for item in planned}
            summary = apply_obsolete_active_cleanup(
                root,
                "2026-07-30T00:00:00+00:00",
                dry_run=False,
                verification_report_path=report_path,
            )
            self.assertEqual(actions["old_notes.txt"], "remove")
            self.assertEqual(actions["private.txt"], "refuse")
            self.assertFalse(ordinary.exists())
            self.assertTrue(sensitive.exists())
            self.assertEqual(summary["removed_count"], 1)
            self.assertEqual(summary["refused_count"], 1)

    def test_cleanup_refuses_unmigrated_active_decision_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "wiki" / "70_decisions" / "research_option_cards.jsonl"
            legacy.parent.mkdir(parents=True)
            legacy.write_text('{"option_id":"option-1"}\n', encoding="utf-8")
            report_path = self._successful_compile_evidence(root, "compile.json")

            planned = plan_obsolete_active_cleanup(root)
            summary = apply_obsolete_active_cleanup(
                root,
                "2026-07-30T00:00:00+00:00",
                dry_run=False,
                verification_report_path=report_path,
            )
            candidate = next(item for item in planned if Path(item.path) == legacy)
            self.assertEqual(candidate.action, "refuse")
            self.assertTrue(legacy.exists())
            self.assertEqual(summary["refused_count"], 1)

    def test_cleanup_removes_legacy_decision_artifact_after_exact_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "wiki" / "70_decisions" / "workflow_change_proposals.jsonl"
            canonical = root / "machine" / "decisions" / "workflow_change_proposals.jsonl"
            legacy.parent.mkdir(parents=True)
            canonical.parent.mkdir(parents=True)
            payload = '{"proposal_id":"proposal-1"}\n'
            legacy.write_text(payload, encoding="utf-8")
            canonical.write_text(payload, encoding="utf-8")
            report_path = self._successful_compile_evidence(root, "compile.json")

            planned = plan_obsolete_active_cleanup(root)
            apply_obsolete_active_cleanup(
                root,
                "2026-07-30T00:00:00+00:00",
                dry_run=False,
                verification_report_path=report_path,
            )
            candidate = next(item for item in planned if Path(item.path) == legacy)
            self.assertEqual(candidate.action, "remove")
            self.assertFalse(legacy.exists())
            self.assertTrue(canonical.exists())

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

            report_path = self._successful_compile_evidence(root, "compile.json")
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
            report_path = self._successful_compile_evidence(root, "passed.json")

            summary = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=report_path)
            rows = [json.loads(line) for line in Path(summary["cleanup_log_path"]).read_text(encoding="utf-8").splitlines()]

            self.assertFalse(summary["blocked"])
            self.assertEqual(summary["verification_status"], "completed")
            self.assertFalse(ordinary.exists())
            self.assertTrue(all(row["verification_report_path"] == str(report_path.resolve()) for row in rows))
            self.assertTrue(all(row["verification_status"] == "completed" for row in rows))

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

            report_path = self._successful_compile_evidence(root, "compile.json")
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
