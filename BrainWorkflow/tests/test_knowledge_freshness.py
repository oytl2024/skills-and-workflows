import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from wqb.knowledge_freshness import (
    KnowledgeFreshnessRecord,
    evaluate_knowledge_contract_health,
    evaluate_freshness,
    load_freshness_manifest,
    write_freshness_report,
)


class KnowledgeFreshnessTest(unittest.TestCase):
    def test_contract_health_accepts_indexed_raw_and_resolved_wiki_backlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            (root / "machine").mkdir(parents=True)
            raw = root / "raw" / "platform" / "learn" / "2026-07-22" / "operators.md"
            raw.parent.mkdir(parents=True)
            raw.write_text(
                "---\nsource_type: platform_api\nsource_family: learn\nsource_path: /operators\n"
                "captured_at: 2026-07-22T00:00:00Z\ncapture_tool: test\nrecord_count: 1\n"
                "content_status: raw_markdown\ncontent_hash: abc\nupdate_check: compare operators\ncompiled_targets:\n"
                "  - wiki/operators.md\n---\n# Operators\n",
                encoding="utf-8",
            )
            index = root / "raw" / "source_index.md"
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text("# Raw Source Index\n\n## `raw/platform/learn/2026-07-22/operators.md`\n", encoding="utf-8")
            wiki = root / "wiki" / "operators.md"
            wiki.parent.mkdir(parents=True)
            wiki.write_text(
                "---\ncompiled_from:\n  - raw/platform/learn/2026-07-22/operators.md\n"
                "compiled_at: 2026-07-22\ntrust_level: working_rule\nstale_after_days: 14\n"
                "update_trigger: operator catalog changed\nconsumed_by:\n  - research_planner\n---\n# Operators\n",
                encoding="utf-8",
            )

            report = evaluate_knowledge_contract_health(root)

        self.assertEqual(report["issue_count"], 0)

    def test_contract_health_reports_broken_backlink_index_gap_and_orphan_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            raw = root / "raw" / "platform" / "learn" / "2026-07-22" / "orphan.md"
            raw.parent.mkdir(parents=True)
            raw.write_text(
                "---\nsource_type: platform_api\nsource_family: learn\nsource_path: /orphan\n"
                "captured_at: 2026-07-22T00:00:00Z\ncapture_tool: test\nrecord_count: 1\n"
                "content_status: raw_markdown\ncontent_hash: abc\nupdate_check: compare\ncompiled_targets:\n  - wiki/20_semantics/operators.md\n"
                "---\n# Orphan\n",
                encoding="utf-8",
            )
            index = root / "raw" / "source_index.md"
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text("# Raw Source Index\n", encoding="utf-8")
            wiki = root / "wiki" / "20_semantics" / "operators.md"
            wiki.parent.mkdir(parents=True)
            wiki.write_text(
                "---\ncompiled_from:\n  - raw/platform/learn/2026-07-22/missing.md\n"
                "compiled_at: 2026-07-22\ntrust_level: working_rule\nstale_after_days: 14\n"
                "update_trigger: changed\nconsumed_by:\n  - research_planner\n---\n# Operators\n",
                encoding="utf-8",
            )

            report = evaluate_knowledge_contract_health(root)

        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("wiki_backlink_missing", codes)
        self.assertIn("source_index_coverage_missing", codes)
        self.assertIn("orphan_raw_source", codes)

    def test_contract_health_rejects_wiki_to_wiki_compiled_from_backlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            upstream = root / "wiki" / "20_semantics" / "upstream.md"
            upstream.parent.mkdir(parents=True)
            upstream.write_text("# Upstream wiki page\n", encoding="utf-8")
            compiled = root / "wiki" / "30_templates" / "compiled.md"
            compiled.parent.mkdir(parents=True)
            compiled.write_text(
                "---\ncompiled_from:\n  - wiki/20_semantics/upstream.md\n"
                "compiled_at: 2026-07-22\ntrust_level: working_rule\nstale_after_days: 14\n"
                "update_trigger: upstream changed\nconsumed_by:\n  - research_planner\n---\n# Compiled\n",
                encoding="utf-8",
            )

            report = evaluate_knowledge_contract_health(root)

        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("wiki_backlink_not_source_authority", codes)

    def test_contract_health_accepts_machine_resource_backlink_for_compiled_wiki(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            machine = root / "machine"
            machine.mkdir(parents=True)
            ledger = machine / "data_ledger.jsonl"
            ledger.write_text("{}\n", encoding="utf-8")
            wiki = root / "wiki" / "20_data_semantics.md"
            wiki.parent.mkdir(parents=True)
            wiki.write_text(
                "---\n"
                "compiled_from:\n"
                "  - machine/data_ledger.jsonl\n"
                "compiled_at: 2026-07-30T00:00:00+00:00\n"
                "trust_level: compiled_experience\n"
                "stale_after_days: 14\n"
                "update_trigger: compile-knowledge\n"
                "consumed_by:\n"
                "  - human_learning\n"
                "---\n"
                "# Data Semantics\n",
                encoding="utf-8",
            )

            report = evaluate_knowledge_contract_health(root)

        self.assertNotIn("wiki_backlink_not_source_authority", {issue["code"] for issue in report["issues"]})

    def test_load_freshness_manifest(self):
        row = {
            "name": "data_ledger",
            "path": "knowledge/machine/data_ledger.jsonl",
            "updated_at": "2026-07-08",
            "max_age_days": 1,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "freshness.json"
            path.write_text(json.dumps([row], sort_keys=True), encoding="utf-8")

            records = load_freshness_manifest(path)

        self.assertEqual(records[0].name, "data_ledger")
        self.assertEqual(records[0].max_age_days, 1)

    def test_load_freshness_manifest_rejects_missing_and_non_list_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            with self.assertRaisesRegex(FileNotFoundError, "freshness manifest not found"):
                load_freshness_manifest(missing)

            invalid = Path(tmp) / "invalid.json"
            invalid.write_text(json.dumps({"name": "data_ledger"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must contain a JSON list"):
                load_freshness_manifest(invalid)

    def test_load_freshness_manifest_strictly_requires_research_run_entries(self):
        partial = [{"name": "data_ledger", "path": "machine/data_ledger.jsonl", "updated_at": "2026-07-10", "max_age_days": 1}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "freshness.json"
            for manifest in ([], partial):
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "missing required entries"):
                    load_freshness_manifest(path, strict=True)

    def test_load_freshness_manifest_strictly_rejects_incomplete_required_entries(self):
        required_entries = [
            {"name": "data_ledger", "path": "wiki/data_ledger.jsonl", "updated_at": "2026-07-10", "max_age_days": 1},
            {"name": "template_library", "path": "wiki/template_library.jsonl", "updated_at": "2026-07-10", "max_age_days": 1},
            {"name": "benchmark_rules", "path": "wiki/benchmark_rules.md", "updated_at": "2026-07-10", "max_age_days": 1},
            {"name": "activity_snapshot", "path": "wiki/activity_snapshot.json", "updated_at": "2026-07-10", "max_age_days": 1},
        ]
        invalid_fields = {
            "path": "",
            "updated_at": "2026/07/10",
            "max_age_days": 0,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "freshness.json"
            for field, value in invalid_fields.items():
                manifest = [dict(row) for row in required_entries]
                manifest[0][field] = value
                path.write_text(json.dumps(manifest), encoding="utf-8")

                with self.subTest(field=field), self.assertRaises(ValueError):
                    load_freshness_manifest(path, strict=True)

    def test_load_freshness_manifest_strictly_rejects_null_required_path(self):
        required_entries = [
            {"name": "data_ledger", "path": None, "updated_at": "2026-07-10", "max_age_days": 1},
            {"name": "template_library", "path": "wiki/template_library.jsonl", "updated_at": "2026-07-10", "max_age_days": 1},
            {"name": "benchmark_rules", "path": "wiki/benchmark_rules.md", "updated_at": "2026-07-10", "max_age_days": 1},
            {"name": "activity_snapshot", "path": "wiki/activity_snapshot.json", "updated_at": "2026-07-10", "max_age_days": 1},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "freshness.json"
            path.write_text(json.dumps(required_entries), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_freshness_manifest(path, strict=True)

    def test_load_freshness_manifest_strictly_rejects_non_string_required_path(self):
        required_entries = [
            {"name": "data_ledger", "path": ["wiki", "data_ledger.jsonl"], "updated_at": "2026-07-10", "max_age_days": 1},
            {"name": "template_library", "path": "wiki/template_library.jsonl", "updated_at": "2026-07-10", "max_age_days": 1},
            {"name": "benchmark_rules", "path": "wiki/benchmark_rules.md", "updated_at": "2026-07-10", "max_age_days": 1},
            {"name": "activity_snapshot", "path": "wiki/activity_snapshot.json", "updated_at": "2026-07-10", "max_age_days": 1},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "freshness.json"
            path.write_text(json.dumps(required_entries), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_freshness_manifest(path, strict=True)

    def test_evaluate_freshness_marks_stale_records(self):
        records = [
            KnowledgeFreshnessRecord("data_ledger", "knowledge/machine/data_ledger.jsonl", "2026-07-08", 1),
            KnowledgeFreshnessRecord("template_library", "knowledge/machine/template_library.jsonl", "2026-07-10", 7),
        ]

        statuses = evaluate_freshness(records, today=date(2026, 7, 10))

        by_name = {status.name: status for status in statuses}
        self.assertTrue(by_name["data_ledger"].stale)
        self.assertFalse(by_name["template_library"].stale)
        self.assertEqual(by_name["data_ledger"].age_days, 2)

    def test_evaluate_freshness_marks_missing_artifacts_stale_when_root_is_provided(self):
        records = [KnowledgeFreshnessRecord("data_ledger", "machine/data_ledger.jsonl", "2026-07-10", 7)]
        with tempfile.TemporaryDirectory() as tmp:
            statuses = evaluate_freshness(records, today=date(2026, 7, 10), artifact_root=Path(tmp))

        self.assertTrue(statuses[0].stale)
        self.assertFalse(statuses[0].artifact_exists)

    def test_write_freshness_report(self):
        statuses = evaluate_freshness(
            [KnowledgeFreshnessRecord("benchmarks", "knowledge/wiki/50_benchmarks", "2026-07-06", 3)],
            today=date(2026, 7, 10),
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = write_freshness_report(Path(tmp) / "freshness_report.md", statuses, "2026-07-10T00:00:00Z")
            text = output.read_text(encoding="utf-8")

        self.assertIn("benchmarks", text)
        self.assertIn("stale", text)


class KnowledgeContractHealthTests(unittest.TestCase):
    def _note_report(self, metadata="", relative="raw/community/user_messages/design.md"):
        """Input: extra metadata str and vault-relative str. Output: dict. Check an isolated note without editing it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "machine").mkdir()
            (root / "wiki").mkdir()
            note = root / relative
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(
                "---\nsource_type: user_design_input\ncaptured_on: 2026-11-03\n"
                "status: design_discussion_not_implemented\n" + metadata + "---\n# Design input\n",
                encoding="utf-8",
            )
            before = note.read_bytes()
            report = evaluate_knowledge_contract_health(root)
            self.assertEqual(note.read_bytes(), before)
            return report

    def test_date_only_local_design_note_has_housekeeping_warnings_not_blockers(self):
        report = self._note_report()

        self.assertEqual(report["issues"], [])
        self.assertEqual(report["issue_count"], 0)
        self.assertEqual(report["warning_count"], 11)
        self.assertEqual(report["warning_count"], len(report["warnings"]))
        self.assertEqual(
            {row["code"] for row in report["warnings"]},
            {"raw_metadata_missing", "source_index_coverage_missing", "orphan_raw_source"},
        )

    def test_design_note_invalid_date_remains_blocking(self):
        for value in ("2026-02-30", "20261103", "2026-11-03T00:00:00Z", "unknown", ""):
            with self.subTest(value=value):
                report = self._note_report("captured_on: " + value + "\n")
                self.assertIn("user_note_date_invalid", {row["code"] for row in report["issues"]})

    def test_official_type_under_user_path_is_not_whitelisted(self):
        report = self._note_report("source_type: platform_api\n")

        self.assertGreater(report["issue_count"], 0)
        self.assertEqual(report["warnings"], [])
        self.assertIn("raw_metadata_missing", {row["code"] for row in report["issues"]})

    def test_platform_note_missing_metadata_is_still_blocking(self):
        report = self._note_report("source_type: platform_api\n", "raw/platform/learn/note.md")

        self.assertGreater(report["issue_count"], 0)
        self.assertEqual(report["warning_count"], 0)

    def test_unknown_notes_and_lookalike_paths_are_not_whitelisted(self):
        cases = (
            ("source_type: unknown\n", "raw/community/user_messages/note.md"),
            ("status: unknown\n", "raw/community/user_messages/note.md"),
            ("", "raw/community/user_messages_extra/note.md"),
            ("", "raw/community/forum/note.md"),
        )
        for metadata, relative in cases:
            with self.subTest(metadata=metadata, relative=relative):
                report = self._note_report(metadata, relative)
                self.assertGreater(report["issue_count"], 0)
                self.assertEqual(report["warning_count"], 0)

    def test_invalid_declared_provenance_is_not_also_a_warning(self):
        report = self._note_report("content_status: forged\ncompiled_targets: invalid\n")

        blocking = {(row["code"], row["path"], row["message"]) for row in report["issues"]}
        warnings = {(row["code"], row["path"], row["message"]) for row in report["warnings"]}
        self.assertTrue(any("content_status must" in row[2] for row in blocking))
        self.assertTrue(any("compiled_targets must" in row[2] for row in blocking))
        self.assertFalse(blocking & warnings)
        self.assertEqual(len(blocking), report["issue_count"])
        self.assertEqual(len(warnings), report["warning_count"])

    def test_design_note_unsafe_declared_path_remains_blocking(self):
        for metadata in (
            "compiled_targets:\n  - ../../../outside.md\n",
            "source_path: ../outside.md\n",
            "compiled_targets:\n  - wiki/../wiki/page.md\n",
            "captured_at: 2026-02-30T00:00:00Z\n",
        ):
            with self.subTest(metadata=metadata):
                report = self._note_report(metadata)
                self.assertIn("user_note_provenance_invalid", {row["code"] for row in report["issues"]})

    def test_design_note_invalid_extract_provenance_stays_blocking(self):
        report = self._note_report("original_sha256: forged\n")

        self.assertTrue(any("verification failed" in row["message"] for row in report["issues"]))
        self.assertFalse(any("verification failed" in row["message"] for row in report["warnings"]))

    def test_linked_raw_source_is_blocking_not_a_local_note_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            (root / "machine").mkdir(parents=True)
            (root / "wiki").mkdir()
            target = Path(tmp) / "outside.md"
            target.write_text(
                "---\nsource_type: user_design_input\ncaptured_on: 2026-11-03\n"
                "status: design_discussion_not_implemented\n---\n# Note\n",
                encoding="utf-8",
            )
            note = root / "raw/community/user_messages/note.md"
            note.parent.mkdir(parents=True)
            try:
                note.symlink_to(target)
            except OSError as error:
                self.skipTest(f"Symlink creation unavailable: {error}")

            report = evaluate_knowledge_contract_health(root)

        self.assertIn("raw_source_path_unsafe", {row["code"] for row in report["issues"]})
        self.assertEqual(report["warnings"], [])

    def test_contract_health_reports_legacy_paths_and_missing_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            legacy = root / "raw" / "learn" / "old.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("# Old raw source\n", encoding="utf-8")
            canonical = root / "raw" / "platform" / "learn" / "2026-07-22" / "operators.md"
            canonical.parent.mkdir(parents=True)
            canonical.write_text("---\nsource_type: platform_api\n---\n# Operators\n", encoding="utf-8")
            wiki = root / "wiki" / "20_semantics" / "operators.md"
            wiki.parent.mkdir(parents=True)
            wiki.write_text("---\ncompiled_at: 2026-07-22\n---\n# Operators\n", encoding="utf-8")

            report = evaluate_knowledge_contract_health(root)

        codes = [issue["code"] for issue in report["issues"]]
        self.assertIn("legacy_path", codes)
        self.assertIn("raw_metadata_missing", codes)
        self.assertIn("wiki_metadata_missing", codes)
        self.assertEqual(report["legacy_count"], 1)
        self.assertGreaterEqual(report["issue_count"], 3)


class KnowledgeHealthBatchVerificationTests(unittest.TestCase):
    def setUp(self):
        """Input: none. Output: None. Prepare two certified excerpts sharing one isolated original capture."""
        from tests.test_bulk_field_extracts import BulkFieldExtractTests
        from wqb.knowledge_contracts import extract_field_source_subset

        self.fixture = BulkFieldExtractTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.rows = self.fixture.rows[:2]
        self.fixture.save()
        self.extracts = [extract_field_source_subset(self.fixture.root, self.fixture.relative,
            [dict(dataset_id="prices", field_id=row["field"]["id"], scope=self.fixture.scope)])
            for row in self.fixture.rows]
        self.assertEqual(len(self.extracts), 2)
        (self.fixture.root / "wiki").mkdir(exist_ok=True)

    def test_two_excerpts_scan_shared_original_once_without_writes(self):
        from wqb import knowledge_contracts as contracts

        before = {path: path.read_bytes() for path in self.fixture.root.rglob("*") if path.is_file()}
        with patch.object(contracts, "_scan_field_source", wraps=contracts._scan_field_source) as scan, \
                patch.object(contracts._FieldExtractSession, "finalize", autospec=True,
                             side_effect=contracts._FieldExtractSession.finalize) as finalize:
            report = evaluate_knowledge_contract_health(self.fixture.root)

        self.assertEqual(scan.call_count, 1)
        self.assertEqual(finalize.call_count, 1)
        self.assertEqual(report["issue_count"], 0)
        self.assertEqual(report["warning_count"], 0)
        self.assertEqual(before, {path: path.read_bytes() for path in self.fixture.root.rglob("*") if path.is_file()})

    def test_batch_verification_preserves_local_note_warning_classification(self):
        note = self.fixture.root / "raw/community/user_messages/design.md"
        note.parent.mkdir(parents=True)
        note.write_text(
            "---\nsource_type: user_design_input\ncaptured_on: 2026-11-03\n"
            "status: design_discussion_not_implemented\n---\n# Note\n", encoding="utf-8",
        )

        report = evaluate_knowledge_contract_health(self.fixture.root)

        self.assertEqual(report["issue_count"], 0)
        self.assertEqual(report["warning_count"], 11)
        self.assertTrue(all(row["path"] == str(note) for row in report["warnings"]))

    def test_mutations_after_file_validation_are_blocked_by_final_digest_check(self):
        from wqb import knowledge_contracts as contracts

        receipt = self.fixture.root / self.extracts[0]["receipt_path"]
        for target in (self.fixture.source, receipt):
            with self.subTest(target=target):
                before = target.read_bytes()
                calls = []

                def validate_then_mutate(path, **kwargs):
                    """Input: Path and validator keywords. Output: list[str]. Change fixture evidence after the last file check."""
                    result = contracts.validate_raw_metadata(path, **kwargs)
                    calls.append(path)
                    if len(calls) == 2:
                        target.write_bytes(before + b" ")
                    return result

                try:
                    with patch("wqb.knowledge_freshness.validate_raw_metadata", side_effect=validate_then_mutate):
                        report = evaluate_knowledge_contract_health(self.fixture.root)
                    self.assertIn("raw_extract_verification_changed", {row["code"] for row in report["issues"]})
                    self.assertFalse(any(row["code"] == "raw_extract_verification_changed" for row in report["warnings"]))
                finally:
                    target.write_bytes(before)

    def test_tampered_receipt_is_reported_per_file_without_rescanning(self):
        from wqb import knowledge_contracts as contracts

        receipt = self.fixture.root / self.extracts[0]["receipt_path"]
        receipt.write_text("{}", encoding="utf-8")
        with patch.object(contracts, "_scan_field_source", wraps=contracts._scan_field_source) as scan:
            report = evaluate_knowledge_contract_health(self.fixture.root)

        self.assertLessEqual(scan.call_count, 1)
        self.assertTrue(any(row["code"] == "raw_metadata_missing"
                            and "verification failed" in row["message"]
                            and row["path"] == str(self.fixture.root / self.extracts[0]["excerpt_path"])
                            for row in report["issues"]))


if __name__ == "__main__":
    unittest.main()
