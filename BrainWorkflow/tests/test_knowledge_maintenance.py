import json
import os
from pathlib import Path
import tempfile
import unittest

from wqb.knowledge_maintenance import run_knowledge_maintenance


class KnowledgeMaintenanceTests(unittest.TestCase):
    def _write_machine_resources(self, root: Path) -> None:
        machine = root / "machine"
        machine.mkdir(parents=True, exist_ok=True)
        for name in (
            "data_ledger.jsonl",
            "template_library.jsonl",
            "benchmark_rules.jsonl",
            "research_records.jsonl",
            "operator_ledger.jsonl",
            "scope_matrix.jsonl",
        ):
            (machine / name).write_text("", encoding="utf-8")
        (machine / "freshness_manifest.json").write_text("[]", encoding="utf-8")

    def test_compile_knowledge_creates_clean_machine_and_wiki_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_machine_resources(root)

            report = run_knowledge_maintenance(root, "2026-07-30T00:00:00+00:00", apply_cleanup=True)

            report_path = Path(report["report_path"])
            self.assertEqual(report["status"], "completed")
            self.assertTrue((root / "wiki" / "00_start_here.md").exists())
            self.assertTrue(report_path.exists())
            self.assertEqual(report["report_path"], str(report_path))
            self.assertEqual(report_path.name, "20260730T000000Z.json")
            self.assertTrue((report_path.parent / "latest.json").exists())
            evidence_path = Path(report["cleanup"]["verification_report_path"])
            self.assertNotEqual(evidence_path, report_path)
            self.assertEqual(report["cleanup"]["verification_status"], "completed")
            self.assertEqual(json.loads(evidence_path.read_text(encoding="utf-8"))["status"], "completed")
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["status"], "completed")

    def test_compile_knowledge_records_blocker_when_structure_is_not_clean_after_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_machine_resources(root)
            (root / "raw" / "learn").mkdir(parents=True)
            (root / "raw" / "learn" / ".env").write_text("SECRET=1\n", encoding="utf-8")

            report = run_knowledge_maintenance(root, "2026-07-30T00:00:00+00:00", apply_cleanup=True)

            self.assertEqual(report["status"], "blocked")
            self.assertGreater(report["health"]["issue_count"], 0)
            self.assertTrue((root / "raw" / "learn" / ".env").exists())
            self.assertEqual(report["cleanup"]["verification_status"], "completed")

    def test_blocked_final_report_preserves_pre_cleanup_verification_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_machine_resources(root)
            (root / "raw" / "learn").mkdir(parents=True)
            (root / "raw" / "learn" / ".env").write_text("SECRET=1\n", encoding="utf-8")

            report = run_knowledge_maintenance(root, "2026-07-30T00:00:00+00:00", apply_cleanup=True)

            evidence_path = Path(report["cleanup"]["verification_report_path"])
            final_path = Path(report["report_path"])
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            final = json.loads(final_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "blocked")
            self.assertNotEqual(evidence_path, final_path)
            self.assertEqual(evidence["status"], "completed")
            self.assertEqual(evidence["report_type"], "knowledge_maintenance_pre_cleanup_evidence")
            self.assertEqual(evidence["pre_cleanup_health"]["blocking_issue_count"], 0)
            self.assertEqual(final["status"], "blocked")

    def test_non_dry_cleanup_refuses_when_pre_cleanup_health_has_unrelated_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obsolete = root / "wiki" / "20_semantics" / "old.jsonl"
            obsolete.parent.mkdir(parents=True)
            obsolete.write_text('{"legacy":true}\n', encoding="utf-8")
            extra_layer = root / "scratch" / "notes.md"
            extra_layer.parent.mkdir(parents=True)
            extra_layer.write_text("# unclassified active layer\n", encoding="utf-8")

            report = run_knowledge_maintenance(root, "2026-07-30T00:00:00+00:00", apply_cleanup=True)

            evidence = json.loads(Path(report["cleanup"]["verification_report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(report["cleanup"]["blocked"])
            self.assertTrue(obsolete.exists())
            self.assertTrue(extra_layer.exists())
            self.assertEqual(evidence["status"], "blocked")
            self.assertGreater(evidence["pre_cleanup_health"]["blocking_issue_count"], 0)

    def test_maintenance_migrates_active_decisions_before_legacy_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_machine_resources(root)
            legacy = root / "wiki" / "70_decisions"
            legacy.mkdir(parents=True)
            payloads = {
                "research_option_cards.jsonl": '{"option_id":"option-1"}\n',
                "workflow_change_proposals.jsonl": '{"proposal_id":"proposal-1"}\n',
                "research_schedule.md": "# Active schedule\n",
            }
            for name, payload in payloads.items():
                (legacy / name).write_text(payload, encoding="utf-8")

            report = run_knowledge_maintenance(
                root,
                "2026-07-30T00:00:00+00:00",
                apply_cleanup=True,
            )

            canonical = root / "machine" / "decisions"
            self.assertEqual(report["status"], "completed")
            self.assertFalse(legacy.exists())
            for name, payload in payloads.items():
                self.assertEqual((canonical / name).read_text(encoding="utf-8"), payload)
            self.assertEqual(
                {row["status"] for row in report["decision_migration"]["artifacts"]},
                {"migrated"},
            )

    def test_maintenance_reports_are_immutable_with_latest_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_machine_resources(root)

            first = run_knowledge_maintenance(root, "2026-07-30T00:00:00+00:00")
            second = run_knowledge_maintenance(root, "2026-07-30T00:00:00+00:00")

            self.assertNotEqual(first["report_path"], second["report_path"])
            self.assertTrue(Path(first["report_path"]).exists())
            self.assertTrue(Path(second["report_path"]).exists())
            self.assertTrue(
                (root / "raw" / "maintenance" / "compile_reports" / "latest.json").exists()
            )

    def test_maintenance_report_path_is_absolute_with_relative_knowledge_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "knowledge"
            self._write_machine_resources(root)
            old_cwd = Path.cwd()
            try:
                os.chdir(base)
                report = run_knowledge_maintenance(Path("knowledge"), "2026-07-30T00:00:00+00:00")
            finally:
                os.chdir(old_cwd)

            report_path = Path(report["report_path"])
            latest = json.loads((root / "raw" / "maintenance" / "compile_reports" / "latest.json").read_text(encoding="utf-8"))

        self.assertTrue(report_path.is_absolute())
        self.assertEqual(report_path, (root / "raw" / "maintenance" / "compile_reports" / "20260730T000000Z.json").resolve())
        self.assertEqual(latest["report_path"], str(report_path))

    def test_maintenance_removes_ordinary_root_file_and_refuses_sensitive_root_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_machine_resources(root)
            ordinary = root / "old_notes.txt"
            sensitive = root / "private.txt"
            ordinary.write_text("obsolete\n", encoding="utf-8")
            sensitive.write_text("keep\n", encoding="utf-8")

            report = run_knowledge_maintenance(
                root,
                "2026-07-30T00:00:00+00:00",
                apply_cleanup=True,
            )

            self.assertFalse(ordinary.exists())
            self.assertTrue(sensitive.exists())
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["cleanup"]["removed_count"], 1)
            self.assertEqual(report["cleanup"]["refused_count"], 1)


if __name__ == "__main__":
    unittest.main()
