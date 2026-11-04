import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import wqb.knowledge_clean_compile as clean_compile

from wqb.knowledge_clean_compile import (
    apply_obsolete_active_cleanup,
    evaluate_clean_knowledge_structure,
    migrate_legacy_decision_artifacts,
    plan_obsolete_active_cleanup,
)


class KnowledgeCleanCompileTests(unittest.TestCase):
    def test_recovery_reports_and_run_events_are_retention_roots(self):
        """Input: job/recovery report or run event reference. Output: candidate retained, never successful deletion."""
        for owner in ('runs/run/recovery/report.json', 'runs/run/workflow_events.jsonl',
                      'machine/semantic_jobs/job/report.json'):
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target = root / 'old.md'
                target.write_text('referenced evidence', encoding='utf-8')
                source = root / owner
                source.parent.mkdir(parents=True)
                source.write_text(json.dumps({'evidence_path': str(target)}) + '\n', encoding='utf-8')
                evidence = self._successful_compile_evidence(root, 'passed.json')
                report = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
                self.assertTrue(target.exists())
                self.assertEqual(report['removed_count'], 0)
                self.assertEqual(report['refused_count'], 1)

    def test_linked_reference_ancestor_is_uncertain_not_empty(self):
        """Input: a junction hiding a capture manifest. Output: refuse deletion without following the link."""
        if os.name != 'nt':
            self.skipTest('Windows junction regression')
        import _winapi
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'knowledge'
            root.mkdir()
            target = root / 'old.md'
            target.write_text('protected', encoding='utf-8')
            outside = Path(tmp) / 'captures'
            outside.mkdir()
            (outside / 'manifest.json').write_text(json.dumps({'source_path': str(target)}), encoding='utf-8')
            (root / 'raw').mkdir()
            link = root / 'raw/captures'
            _winapi.CreateJunction(str(outside), str(link))
            try:
                evidence = self._successful_compile_evidence(root, 'passed.json')
                report = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
                self.assertTrue(target.exists())
                self.assertEqual(report['refused_count'], 1)
            finally:
                link.rmdir()

    def test_unrelated_large_capture_and_inventories_do_not_block_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('raw/platform/data_fields/day/data_fields.jsonl',
                         'machine/semantic_inventories/' + 'a' * 64 + '/inventory.jsonl',
                         'machine/semantic_jobs/' + 'b' * 64 + '/inventory.jsonl',
                         'machine/reports/full_semantic_coverage_example.json'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('unrelated payload' * 100, encoding='utf-8')
            target = root / 'wiki/20_semantics/old.md'
            target.parent.mkdir(parents=True)
            target.write_text('obsolete', encoding='utf-8')
            root_target = root / 'obsolete.md'
            root_target.write_text('obsolete', encoding='utf-8')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            with patch.object(clean_compile, 'REFERENCE_FILE_LIMIT', 256):
                result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertFalse(target.exists())
            self.assertFalse(root_target.exists())
            self.assertEqual(result['removed_count'], 2)

    def test_cleanup_returns_per_candidate_refusals_without_blocking_unrelated_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw/learn/source.json'
            raw.parent.mkdir(parents=True)
            raw.write_text('{}', encoding='utf-8')
            ordinary = root / 'old.md'
            ordinary.write_text('obsolete', encoding='utf-8')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(raw.exists())
            self.assertFalse(ordinary.exists())
            self.assertEqual(result['refusals'], [{'path': str(raw), 'reason': 'protected raw evidence'}])

    def test_cleanup_refuses_hardlinked_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'knowledge'
            root.mkdir()
            source = Path(tmp) / 'source.md'
            source.write_text('keep', encoding='utf-8')
            target = root / 'old.md'
            target.hardlink_to(source)
            evidence = self._successful_compile_evidence(root, 'passed.json')
            result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(target.exists())
            self.assertEqual(result['refused_count'], 1)

    def test_cleanup_releases_publication_lock_on_audit_failure(self):
        from wqb import semantic_publication
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'old.md'
            target.write_text('keep until audited', encoding='utf-8')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            with patch.object(clean_compile, 'write_cleanup_log', side_effect=OSError('disk full')), \
                 patch.object(semantic_publication, '_release_lock', wraps=semantic_publication._release_lock) as release:
                with self.assertRaisesRegex(OSError, 'disk full'):
                    apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            release.assert_called_once()
            self.assertTrue(release.call_args.args[0].closed)
            self.assertTrue(target.exists())

    def test_cleanup_preserves_unique_raw_learn_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'raw/learn/unique_evidence.json'
            target.parent.mkdir(parents=True)
            target.write_text('{}', encoding='utf-8')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(target.exists())
            self.assertEqual(result['refused_count'], 1)

    def test_cleanup_assesses_references_under_publication_lock(self):
        from wqb import semantic_publication
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'old.md'
            target.write_text('keep', encoding='utf-8')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            acquire = semantic_publication._acquire_lock
            held = []

            def acquire_with_publication(path):
                """Input: root (Path). Output: lock handle; publish a reference at the acquisition boundary."""
                handle = acquire(path)
                held.append(handle)
                (root / 'machine/source_index.jsonl').write_text(
                    json.dumps({'source_path': str(target)}), encoding='utf-8')
                return handle

            with patch.object(semantic_publication, '_acquire_lock', side_effect=acquire_with_publication), \
                 patch.object(semantic_publication, '_release_lock', wraps=semantic_publication._release_lock) as release:
                result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(target.exists())
            self.assertEqual(result['refused_count'], 1)
            release.assert_called_once_with(held[0])
            self.assertTrue(held[0].closed)

    def test_cleanup_diagnostic_paths_do_not_become_retention_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'old.md'
            target.write_text('obsolete', encoding='utf-8')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            payload = json.loads(evidence.read_text(encoding='utf-8'))
            payload['pre_cleanup_health']['issues'] = [{'path': str(target)}]
            evidence.write_text(json.dumps(payload), encoding='utf-8')
            result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertFalse(target.exists())
            self.assertEqual(result['removed_count'], 1)

    def test_cleanup_rechecks_reference_created_after_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'old.md'
            target.write_text('keep', encoding='utf-8')
            planned = plan_obsolete_active_cleanup(root)
            owner = root / 'machine/source_index.jsonl'
            owner.parent.mkdir()
            owner.write_text(json.dumps({'path': str(target)}), encoding='utf-8')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            with patch.object(clean_compile, 'plan_obsolete_active_cleanup', return_value=planned):
                result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(target.exists())
            self.assertEqual(result['refused_count'], 1)

    def test_cleanup_rechecks_canonical_migration_after_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'wiki/70_decisions/options.jsonl'
            canonical = root / 'machine/decisions/options.jsonl'
            for path in (target, canonical):
                path.parent.mkdir(parents=True)
                path.write_text('{}', encoding='utf-8')
            planned = plan_obsolete_active_cleanup(root)
            canonical.write_text('{"changed": true}', encoding='utf-8')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            with patch.object(clean_compile, 'plan_obsolete_active_cleanup', return_value=planned):
                result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(target.exists())
            self.assertEqual(result['refused_count'], 1)

    def test_cleanup_refuses_uncertain_or_oversized_reference_owner(self):
        for payload, limit in (('{invalid', 100), ('{}', 1),
                               ('{"path":"old.md","path":"elsewhere"}', 100),
                               ('{"value":NaN}', 100)):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target = root / 'old.md'
                target.write_text('keep', encoding='utf-8')
                owner = root / 'machine/source_index.jsonl'
                owner.parent.mkdir()
                owner.write_text(payload, encoding='utf-8')
                evidence = self._successful_compile_evidence(root, 'passed.json')
                with patch.object(clean_compile, 'REFERENCE_FILE_LIMIT', limit):
                    result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
                self.assertTrue(target.exists())
                self.assertEqual(result['refused_count'], 1)

    def test_cleanup_refuses_junction_installed_after_planning(self):
        if os.name != 'nt':
            self.skipTest('Windows junction regression')
        import _winapi
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'knowledge'
            base = root / 'wiki/20_semantics'
            base.mkdir(parents=True)
            target = base / 'old.md'
            target.write_text('old', encoding='utf-8')
            planned = plan_obsolete_active_cleanup(root)
            target.unlink()
            base.rmdir()
            outside = Path(tmp) / 'outside'
            outside.mkdir()
            retained = outside / 'old.md'
            retained.write_text('old', encoding='utf-8')
            _winapi.CreateJunction(str(outside), str(base))
            evidence = self._successful_compile_evidence(root, 'passed.json')
            with patch.object(clean_compile, 'plan_obsolete_active_cleanup', return_value=planned):
                result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(retained.exists())
            self.assertEqual(result['refused_count'], 1)
            self.assertTrue(base.is_junction())

    def test_cleanup_refuses_linked_audit_destination_before_deleting(self):
        if os.name != 'nt':
            self.skipTest('Windows junction regression')
        import _winapi
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'knowledge'
            root.mkdir()
            target = root / 'old.md'
            target.write_text('keep', encoding='utf-8')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            outside = Path(tmp) / 'outside'
            outside.mkdir()
            logs = root / 'raw/maintenance/cleanup_logs'
            _winapi.CreateJunction(str(outside), str(logs))
            with self.assertRaisesRegex(ValueError, 'unsafe cleanup log'):
                apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(target.exists())
            self.assertEqual(list(outside.iterdir()), [])

    def test_cleanup_revalidates_replaced_candidate_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'old.md'
            target.write_text('old', encoding='utf-8')
            planned = plan_obsolete_active_cleanup(root)
            target.write_text('replacement', encoding='utf-8')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            with patch.object(clean_compile, 'plan_obsolete_active_cleanup', return_value=planned):
                result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(target.exists())
            self.assertEqual(result['refused_count'], 1)

    def test_cleanup_protects_structured_evidence_references(self):
        for owner in ('machine/source_index.jsonl', 'machine/research_records.jsonl',
                      'machine/semantic_releases/release/manifest.json',
                      'machine/semantic_jobs/job/input.json', 'runs/run/run_state.json',
                      'runs/console_jobs/job/state.json', 'runs/run/recovery/state.json',
                      'raw/captures/manifest.json'):
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'knowledge'
                target = root / 'wiki/20_semantics/old.md'
                target.parent.mkdir(parents=True)
                target.write_text('evidence', encoding='utf-8')
                owner_path = (root.parent if owner.startswith('runs/') else root) / owner
                owner_path.parent.mkdir(parents=True, exist_ok=True)
                owner_path.write_text(json.dumps({'source_path': 'wiki/20_semantics/old.md'}), encoding='utf-8')
                evidence = self._successful_compile_evidence(root, 'passed.json')
                result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
                self.assertTrue(target.exists())
                self.assertEqual(result['refused_count'], 1)

    def test_cleanup_never_removes_research_stage1_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'raw/research/stage1/failed.json'
            target.parent.mkdir(parents=True)
            target.write_text('{}', encoding='utf-8')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(target.exists())
            self.assertEqual(result['refused_count'], 1)

    def test_cleanup_refuses_candidate_outside_original_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'machine/keep.json'
            target.parent.mkdir()
            target.write_text('{}', encoding='utf-8')
            forged = clean_compile.CleanupCandidate(str(target), 'obsolete', 'remove', clean_compile._sha256(target))
            evidence = self._successful_compile_evidence(root, 'passed.json')
            with patch.object(clean_compile, 'plan_obsolete_active_cleanup', return_value=[forged]):
                result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(target.exists())
            self.assertEqual(result['refused_count'], 1)

    def test_cleanup_refuses_linked_candidate_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'knowledge'
            outside = Path(tmp) / 'outside'
            outside.mkdir()
            target = outside / 'keep.md'
            target.write_text('keep', encoding='utf-8')
            base = root / 'wiki/20_semantics'
            base.parent.mkdir(parents=True)
            try:
                base.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest('directory symlink creation unavailable')
            evidence = self._successful_compile_evidence(root, 'passed.json')
            result = apply_obsolete_active_cleanup(root, dry_run=False, verification_report_path=evidence)
            self.assertTrue(target.exists())
            self.assertGreater(result['refused_count'], 0)

    def test_platform_compile_coordination_files_are_not_knowledge_or_cleanup_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('raw', 'machine', 'wiki'):
                (root / name).mkdir()
            for name in ('.data_capture_compile.lock', '.data_capture_compile.lock.guard'):
                (root / name).write_text('{}')
            self.assertEqual(evaluate_clean_knowledge_structure(root)['issue_count'], 0)
            self.assertEqual(plan_obsolete_active_cleanup(root), [])

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

    def test_clean_structure_allows_obsidian_config_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("raw", "machine", "wiki", ".obsidian"):
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

    def test_clean_structure_reports_retired_principles_and_index_wiki_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            principles = root / "wiki" / "00_principles" / "old.md"
            index = root / "wiki" / "90_index" / "old.md"
            principles.parent.mkdir(parents=True)
            index.parent.mkdir(parents=True)
            principles.write_text("# old principles\n", encoding="utf-8")
            index.write_text("# old index\n", encoding="utf-8")

            report = evaluate_clean_knowledge_structure(root)

        legacy_paths = {
            Path(issue["path"]).relative_to(root).as_posix()
            for issue in report["issues"]
            if issue["code"] == "legacy_active_path"
        }
        self.assertIn("wiki/00_principles", legacy_paths)
        self.assertIn("wiki/90_index", legacy_paths)
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

    def test_decision_artifact_migration_refuses_sensitive_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private_note = root / "wiki" / "70_decisions" / "private_notes.md"
            secret_json = root / "wiki" / "70_decisions" / "secret_token.json"
            ordinary = root / "wiki" / "70_decisions" / "research_option_cards.jsonl"
            private_note.parent.mkdir(parents=True)
            private_note.write_text("# Private Decision Notes\n", encoding="utf-8")
            secret_json.write_text('{"token":"do-not-copy"}', encoding="utf-8")
            ordinary.write_text('{"option_id":"option-1"}\n', encoding="utf-8")

            report = migrate_legacy_decision_artifacts(root)

            statuses = {
                Path(row["source_path"]).name: row["status"]
                for row in report["artifacts"]
            }
            self.assertEqual(report["status"], "completed")
            self.assertEqual(statuses["private_notes.md"], "refused_sensitive")
            self.assertEqual(statuses["secret_token.json"], "refused_sensitive")
            self.assertEqual(statuses["research_option_cards.jsonl"], "migrated")
            self.assertEqual("# Private Decision Notes\n", private_note.read_text(encoding="utf-8"))
            self.assertEqual('{"token":"do-not-copy"}', secret_json.read_text(encoding="utf-8"))
            self.assertFalse((root / "machine" / "decisions" / "private_notes.md").exists())
            self.assertFalse((root / "machine" / "decisions" / "secret_token.json").exists())
            self.assertTrue((root / "machine" / "decisions" / "research_option_cards.jsonl").exists())

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
