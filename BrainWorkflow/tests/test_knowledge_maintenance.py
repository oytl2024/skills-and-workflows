import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb.knowledge_maintenance import run_knowledge_maintenance


class KnowledgeMaintenanceTests(unittest.TestCase):
    def test_source_preparation_finishes_all_fresh_bounded_chunks_and_replays(self):
        """Input: 65 modern captured rows. Output: automatic three-chunk local preparation, no prefix padding."""
        from tests.test_bulk_field_extracts import BulkFieldExtractTests
        from wqb.knowledge_maintenance import _prepare_capture_sources
        fixture = BulkFieldExtractTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        before = fixture.source.read_bytes()
        result = _prepare_capture_sources(fixture.root, fixture.source.parent, '2026-10-30T00:00:00Z',
                                          max_batches=1, max_fields=30)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['rounds'], 3)
        self.assertEqual(result['certified_fields'], 65)
        self.assertTrue(result['extraction_complete'])
        self.assertEqual(fixture.source.read_bytes(), before)
        prior = {p: p.read_bytes() for p in fixture.root.rglob('*') if p.is_file()}
        repeated = _prepare_capture_sources(fixture.root, fixture.source.parent, '2026-10-30T00:00:00Z',
                                            max_batches=1, max_fields=30)
        self.assertEqual(repeated['new_fields'], 0)
        self.assertEqual(prior, {p: p.read_bytes() for p in fixture.root.rglob('*') if p.is_file()})

    def test_source_preparation_indexes_old_capture_without_refresh_or_expansion(self):
        """Input: stale raw generation. Output: readable directory only, no thousands of unusable fresh-looking excerpts."""
        from tests.test_bulk_field_extracts import BulkFieldExtractTests
        from wqb.knowledge_maintenance import _prepare_capture_sources
        fixture = BulkFieldExtractTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        result = _prepare_capture_sources(fixture.root, fixture.source.parent, '2027-02-01T00:00:00Z')
        self.assertEqual(result['status'], 'deferred_source_age')
        self.assertEqual(result['source_updated_at'], '2026-10-23')
        self.assertEqual(result['catalog_rows'], 65)
        self.assertFalse(list(fixture.source.parent.glob('semantic-subset-*.md')))
        self.assertFalse((fixture.root / 'machine/data_ledger.jsonl').exists())

    def _field_capture(self, root: Path, day: str, region: str, description: str,
                       timestamp: str | None = None, partial: bool = False) -> Path:
        """Input: temporary root/date/scope/text and optional timestamp/status. Output: isolated raw capture Path."""
        capture = root / 'raw/platform/data_fields' / day
        capture.mkdir(parents=True)
        scope = dict(instrument_type='EQUITY', region=region, delay=1, universe='TOP3000')
        status = 'partial' if partial else 'complete'
        values = {
            'data_fields.jsonl': dict(scope=scope, capture_generation_id=day, data_set=dict(id='d'),
                field=dict(id='f', type='MATRIX', description=description, coverage=0.8)),
            'manifest.json': dict(generated_at=timestamp or day + 'T00:00:00Z',
                certification_status=status, requested_matrix=[scope]),
            'scopes.jsonl': dict(scope=scope, status='partial' if partial else 'completed',
                certification_status=status, capture_generation_id=day),
        }
        for name, value in values.items():
            (capture / name).write_text(json.dumps(value), encoding='utf-8')
        return capture

    def test_active_maintenance_compiles_all_scope_generations_and_keeps_partial(self):
        """Input: older USA ledger and newer USA/EUR captures. Output: latest per-scope facts, dates and partial status."""
        from wqb.data_ledger_compile import compile_data_ledger_from_raw
        from wqb.semantic_publication import read_semantic_release
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._active_release(root)
            oldest = self._field_capture(root, '2026-10-15', 'USA', 'Old USA')
            compile_data_ledger_from_raw(root, oldest)
            self._field_capture(root, '2026-10-16', 'USA', 'New USA', partial=True)
            self._field_capture(root, '2026-10-17', 'EUR', 'EUR field')
            report = run_knowledge_maintenance(root, '2026-10-30T00:00:00Z')
            rows = {row['region']: row for row in (json.loads(line) for line in
                (root / 'machine/data_ledger.jsonl').read_text(encoding='utf-8').splitlines())}
            self.assertEqual(rows['USA']['field_description'], 'New USA')
            self.assertEqual(rows['USA']['source_updated_at'], '2026-10-16')
            self.assertEqual(rows['USA']['coverage_status'], 'measured_raw')
            self.assertEqual(rows['EUR']['coverage_status'], 'measured_raw')
            self.assertEqual(report['status'], 'completed')
            self.assertEqual(len(report['data_compile']['captures']), 3)
            self.assertEqual(report['data_compile']['captures'][1]['source_status'], 'partial')
            self.assertEqual(read_semantic_release(root), release)

    def test_active_capture_order_uses_timezone_aware_manifest_time(self):
        """Input: captures whose lexical days disagree with absolute time. Output: genuinely latest scope generation wins."""
        from wqb.knowledge_maintenance import _compile_active_fields
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = self._field_capture(root, '2026-10-15', 'USA', 'Latest', '2026-10-15T23:30:00-02:00')
            earlier = self._field_capture(root, '2026-10-16', 'USA', 'Earlier', '2026-10-16T00:30:00Z')
            report = _compile_active_fields(root, '2026-10-30T00:00:00Z')
            row = json.loads((root / 'machine/data_ledger.jsonl').read_text(encoding='utf-8'))
            self.assertEqual(row['field_description'], 'Latest')
            self.assertEqual(row['source_updated_at'], '2026-10-15')
            self.assertEqual([item['capture_path'] for item in report['captures']],
                [earlier.relative_to(root).as_posix(), latest.relative_to(root).as_posix()])

    def test_active_capture_invalid_time_blocks_before_any_ledger_replacement(self):
        """Input: valid older capture and missing/invalid/naive newer timestamps. Output: blocked without inferred dates or writes."""
        from wqb.data_ledger_compile import compile_data_ledger_from_raw
        for timestamp in (None, 'not-a-time', '2026-10-16T00:00:00', '2026-10-17T00:00:00Z'):
            with self.subTest(timestamp=timestamp), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self._active_release(root)
                oldest = self._field_capture(root, '2026-10-15', 'USA', 'Old USA')
                compile_data_ledger_from_raw(root, oldest)
                before = (root / 'machine/data_ledger.jsonl').read_bytes()
                newest = self._field_capture(root, '2026-10-16', 'EUR', 'New EUR')
                manifest_path = newest / 'manifest.json'
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                manifest['generated_at'] = timestamp
                manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
                report = run_knowledge_maintenance(root, '2026-10-30T00:00:00Z')
                self.assertEqual(report['data_compile']['status'], 'blocked')
                self.assertEqual((root / 'machine/data_ledger.jsonl').read_bytes(), before)

    def test_active_replay_preserves_only_current_compatible_selected_explanation(self):
        """Input: selected current explanation plus historical capture. Output: revalidated selector survives replay, not new generations."""
        from tests.test_field_semantic_enrichment import FieldSemanticEnrichmentTests
        from wqb.knowledge_maintenance import _compile_active_fields
        fixture = FieldSemanticEnrichmentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.ledger.write_text(json.dumps(fixture.row), encoding='utf-8')
        self._field_capture(fixture.root, '2026-10-14', 'USA', 'Earlier generation')
        _compile_active_fields(fixture.root, '2026-10-30T00:00:00Z')
        row = json.loads(fixture.ledger.read_text(encoding='utf-8'))
        self.assertEqual(row.get('field_semantics_ref'), fixture.row['field_semantics_ref'])
        self.assertEqual(fixture.resolve(row)['status'], 'supported')
        self._field_capture(fixture.root, '2026-10-16', 'USA', 'Changed generation')
        _compile_active_fields(fixture.root, '2026-10-30T00:00:00Z')
        row = json.loads(fixture.ledger.read_text(encoding='utf-8'))
        self.assertNotIn('field_semantics_ref', row)

    def test_error_receipt_may_have_no_semantic_compile_target_but_regular_source_may_not(self):
        """Input: indexed-style diagnostic metadata. Output: valid empty diagnostic targets, no exemption for platform facts."""
        from wqb.knowledge_contracts import render_front_matter, validate_raw_metadata
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'request_error.md'
            body = '# Raw request failure\n'
            metadata = dict(source_type='platform_capture_error', source_family='raw/platform/learn',
                source_path='/tutorial-pages/example', captured_at='2026-10-15T00:00:00Z',
                capture_tool='fixture', content_status='raw_markdown', record_count=1,
                content_hash=hashlib.sha256(body.encode()).hexdigest(), update_check='compare error receipt',
                compiled_targets=[])
            path.write_text(render_front_matter(metadata) + body, encoding='utf-8')
            self.assertNotIn('missing compiled_targets', validate_raw_metadata(path))
            metadata['source_type'] = 'platform_learn_material'
            path.write_text(render_front_matter(metadata) + body, encoding='utf-8')
            self.assertIn('missing compiled_targets', validate_raw_metadata(path))

    def test_active_maintenance_compiles_new_raw_fields_without_replacing_release(self):
        """Input: active release plus new local capture. Output: updated field ledger and unchanged semantic release."""
        from wqb.semantic_publication import read_semantic_release
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = self._active_release(root)
            capture = root / 'raw/platform/data_fields/2026-10-15'
            capture.mkdir(parents=True)
            scope = dict(instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000')
            values = {
                'data_fields.jsonl': dict(scope=scope, capture_generation_id='g1', data_set=dict(id='new_data'),
                    field=dict(id='new_field', type='MATRIX', description='New literal field', coverage=0.8)),
                'manifest.json': dict(generated_at='2026-10-15T00:00:00Z', certification_status='complete',
                    requested_matrix=[scope]),
                'scopes.jsonl': dict(scope=scope, status='completed', certification_status='complete',
                    capture_generation_id='g1'),
            }
            for name, value in values.items():
                (capture / name).write_text(json.dumps(value), encoding='utf-8')
            report = run_knowledge_maintenance(root, '2026-10-30T00:00:00Z')
            rows = [json.loads(line) for line in (root / 'machine/data_ledger.jsonl').read_text().splitlines()]
            selected = [row for row in rows if row.get('field_id') == 'new_field']
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]['source_updated_at'], '2026-10-15')
            self.assertEqual(report['data_compile']['status'], 'completed')
            self.assertEqual(read_semantic_release(root), receipt)

    def test_compiled_principles_preserve_cheap_checks_first_and_batch_maximum(self):
        """Input: isolated ordinary maintenance. Output: human principles match current runtime boundaries."""
        from wqb.knowledge_experience_compile import compile_human_experience_wiki
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_machine_resources(root)
            compile_human_experience_wiki(root, '2026-10-30T00:00:00Z')
            text = (root / 'wiki/10_factor_principles.md').read_text(encoding='utf-8')
            self.assertIn('at most 30', text)
            self.assertIn('cheap baseline checks before SELF/PROD', text)
            self.assertNotIn('Use batches of 30', text)

    def _active_release(self, root: Path) -> dict:
        """Input: temporary root Path. Output: receipt dict. Publish an isolated semantic fixture."""
        from wqb.semantic_publication import stage_semantic_release, publish_semantic_release
        self._write_machine_resources(root)
        (root / "raw").mkdir()
        (root / "wiki").mkdir()
        from wqb.knowledge_contracts import render_front_matter
        from wqb.knowledge_experience_compile import _front_matter
        body = "# Captured operator definition\n"
        source = root / "raw/platform/learn/operators.md"
        source.parent.mkdir(parents=True)
        source.write_text(render_front_matter({
            "source_type": "platform_api", "source_family": "learn", "source_path": "/operators",
            "captured_at": "2026-07-30T00:00:00Z", "capture_tool": "fixture", "record_count": 1,
            "content_status": "raw_markdown", "content_hash": hashlib.sha256(body.encode()).hexdigest(),
            "update_check": "compare original", "compiled_targets": ["wiki/30_template_and_operator_patterns.md"],
        }) + body, encoding="utf-8")
        (root / "raw/source_index.md").write_text("# Sources\nraw/platform/learn/operators.md\n", encoding="utf-8")
        front = _front_matter("2026-08-01T00:00:00Z", ["machine/data_ledger.jsonl"], ["human_learning"])
        proposals = {
            "validated_operators": [{"operator": "rank", "captured_at": "2026-07-30"}],
            "validated_templates": [{"template_id": "selected", "template_family": "selected_family"}],
            "source_refs": [{"path": "raw/platform/learn/operators.md", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}],
            "wiki_materials": {
                "wiki/20_data_semantics.md": front + "\n# Selected data\n",
                "wiki/30_template_and_operator_patterns.md": front + "\n# Selected patterns\n",
            },
        }
        receipt = publish_semantic_release(root, stage_semantic_release(root, proposals, "2026-08-01T00:00:00Z"))
        (root / "machine/template_library.jsonl").write_text(
            json.dumps({"template_id": "shadow", "template_family": "stale_shadow"}) + "\n", encoding="utf-8")
        return receipt

    def _protected_bytes(self, root: Path) -> dict:
        """Input: temporary root Path. Output: path/bytes dict. Snapshot release and source authorities."""
        return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
                if path.is_file() and ("semantic_release" in path.as_posix()
                                     or path.parent == root / "machine"
                                     or path.is_relative_to(root / "raw/platform")
                                     or path == root / "raw/source_index.md"
                                     or path.name in {"20_data_semantics.md", "30_template_and_operator_patterns.md"})}

    def test_active_maintenance_preserves_release_and_skips_all_legacy_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = self._active_release(root)
            before = self._protected_bytes(root)
            with patch("wqb.knowledge_maintenance.run_knowledge_vault_migration") as migration, \
                    patch("wqb.knowledge_maintenance.migrate_legacy_decision_artifacts") as decisions:
                report = run_knowledge_maintenance(root, "2026-08-02T00:00:00Z")
            migration.assert_not_called()
            decisions.assert_not_called()
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["migration"]["mode"], "active_release_preserved")
            self.assertEqual(report["migration"]["release_id"], receipt["release_id"])
            self.assertEqual(before, self._protected_bytes(root))
            page = (root / "wiki/00_start_here.md").read_text(encoding="utf-8")
            self.assertIn(f"machine/semantic_releases/{receipt['release_id']}/template_library.jsonl", page)
            self.assertNotIn("  - machine/template_library.jsonl", page)
            self.assertTrue((root / "wiki/10_factor_principles.md").exists())

    def test_legacy_initialization_reports_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_knowledge_maintenance(Path(tmp), "2026-08-02T00:00:00Z")
            self.assertEqual(report["migration"]["mode"], "legacy_initialization")

    def test_corrupt_active_receipt_reports_blocked_without_fallback(self):
        for corrupt in ("pointer", "resource"):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                receipt = self._active_release(root)
                target = (root / "machine/semantic_release.json" if corrupt == "pointer"
                          else Path(receipt["paths"]["template_library"]))
                target.write_text("corrupt", encoding="utf-8")
                before = self._protected_bytes(root)
                with patch("wqb.knowledge_maintenance.run_knowledge_vault_migration") as migration:
                    report = run_knowledge_maintenance(root, "2026-08-02T00:00:00Z")
                migration.assert_not_called()
                self.assertEqual(report["status"], "blocked")
                self.assertTrue(report["error"])
                self.assertEqual(before, self._protected_bytes(root))
                self.assertEqual(json.loads(Path(report["report_path"]).read_text())["status"], "blocked")

    def test_partial_active_wiki_write_reports_blocked_and_never_cleans(self):
        from wqb import knowledge_experience_compile as wiki
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._active_release(root)
            before = self._protected_bytes(root)
            original = wiki._write_page
            calls = []

            def fail_second(path, *args):
                """Input: page Path and render args. Output: Path. Simulate a partial derived write failure."""
                calls.append(path)
                if len(calls) == 2:
                    raise OSError("fixture partial wiki write")
                return original(path, *args)

            with patch.object(wiki, "_write_page", side_effect=fail_second), \
                    patch("wqb.knowledge_maintenance.apply_obsolete_active_cleanup") as cleanup:
                report = run_knowledge_maintenance(root, "2026-08-02T00:00:00Z", apply_cleanup=True)
            self.assertEqual(len(calls), 2)
            self.assertEqual(report["status"], "blocked")
            self.assertIn("partial wiki write", report["error"])
            cleanup.assert_not_called()
            self.assertEqual(before, self._protected_bytes(root))
            self.assertTrue(calls[0].exists())

    def test_active_default_cleanup_never_deletes_legacy_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._active_release(root)
            source = root / "wiki/70_decisions/research_option_cards.jsonl"
            source.parent.mkdir()
            source.write_text('{"option_id":"preserve"}\n', encoding="utf-8")
            before = source.read_bytes()
            report = run_knowledge_maintenance(root, "2026-08-02T00:00:00Z")
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(report["cleanup"]["removed_count"], 0)

    def test_active_explicit_cleanup_preserves_unique_evidence_without_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._active_release(root)
            source = root / "raw/learn/unique_evidence.json"
            source.parent.mkdir()
            source.write_text('{"unique_evidence":"no other copy"}\n', encoding="utf-8")
            before = source.read_bytes()
            from wqb import knowledge_maintenance as maintenance
            with patch.object(maintenance, "apply_obsolete_active_cleanup", wraps=maintenance.apply_obsolete_active_cleanup) as cleanup:
                report = run_knowledge_maintenance(root, "2026-08-02T00:00:00Z", apply_cleanup=True)
            self.assertTrue(source.exists(), "active maintenance must not delete unique evidence")
            self.assertEqual(source.read_bytes(), before)
            cleanup.assert_called_once()
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["cleanup"]["status"], "blocked")
            self.assertGreater(report["cleanup"]["refused_count"], 0)
            self.assertEqual(report["cleanup"]["removed_count"], 0)
            self.assertIsNotNone(report["verification_report_path"])

    def test_active_explicit_cleanup_completes_without_candidates(self):
        from wqb import knowledge_maintenance as maintenance
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._active_release(root)
            with patch.object(maintenance, "apply_obsolete_active_cleanup", wraps=maintenance.apply_obsolete_active_cleanup) as cleanup:
                report = run_knowledge_maintenance(root, "2026-08-02T00:00:00Z", apply_cleanup=True)
            cleanup.assert_called_once()
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["cleanup"]["removed_count"], 0)
            self.assertIsNotNone(report["verification_report_path"])

    def test_malformed_research_rows_block_before_writes_and_replace_successful_latest(self):
        for invalid in (None, [], 42, "not an object", False):
            with self.subTest(row=invalid), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self._active_release(root)
                first = run_knowledge_maintenance(root, "2026-08-02T00:00:00Z")
                first_path = Path(first["report_path"])
                first_bytes = first_path.read_bytes()
                wiki_before = {path: path.read_bytes() for path in (root / "wiki").rglob("*.md")}
                ledger = root / "machine/research_records.jsonl"
                ledger.write_text("{}\n" * 201 + json.dumps(invalid) + "\n", encoding="utf-8")
                with patch("wqb.knowledge_experience_compile._write_page") as write_page, \
                        patch("wqb.knowledge_maintenance.compile_interaction_lessons") as interaction:
                    report = run_knowledge_maintenance(root, "2026-08-02T00:00:00Z")
                write_page.assert_not_called()
                interaction.assert_not_called()
                self.assertEqual(report["status"], "blocked")
                self.assertIn("research_records.jsonl", report["error"])
                self.assertIn("202", report["error"])
                self.assertEqual({path: path.read_bytes() for path in (root / "wiki").rglob("*.md")}, wiki_before)
                self.assertEqual(first_path.read_bytes(), first_bytes)
                latest = json.loads((first_path.parent / "latest.json").read_text(encoding="utf-8"))
                self.assertEqual(latest["status"], "blocked")
                self.assertEqual(latest["report_path"], report["report_path"])

    def test_direct_wiki_compile_rejects_non_object_research_row_before_writes(self):
        from wqb.knowledge_experience_compile import compile_human_experience_wiki
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._active_release(root)
            (root / "machine/research_records.jsonl").write_text("null\n", encoding="utf-8")
            with patch("wqb.knowledge_experience_compile._write_page") as write_page:
                with self.assertRaisesRegex(ValueError, "research_records.jsonl"):
                    compile_human_experience_wiki(root, "2026-08-02T00:00:00Z")
            write_page.assert_not_called()

    def test_active_maintenance_does_not_swallow_programming_attribute_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._active_release(root)
            with patch("wqb.knowledge_experience_compile._write_page", side_effect=AttributeError("fixture programming bug")):
                with self.assertRaisesRegex(AttributeError, "fixture programming bug"):
                    run_knowledge_maintenance(root, "2026-08-02T00:00:00Z")

    def test_failed_retry_keeps_prior_receipt_and_records_blocked_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._active_release(root)
            first = run_knowledge_maintenance(root, "2026-08-02T00:00:00Z")
            first_path = Path(first["report_path"])
            first_bytes = first_path.read_bytes()
            with patch("wqb.knowledge_maintenance.compile_interaction_lessons", side_effect=OSError("fixture write failure")):
                failed = run_knowledge_maintenance(root, "2026-08-02T00:00:00Z")
            self.assertEqual(first["status"], "completed")
            self.assertEqual(failed["status"], "blocked")
            self.assertEqual(first_path.read_bytes(), first_bytes)
            self.assertNotEqual(first["report_path"], failed["report_path"])
            latest = json.loads((first_path.parent / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["status"], "blocked")
            self.assertIn("fixture write failure", latest["error"])

    def test_active_maintenance_does_not_repair_publication_owned_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._active_release(root)
            page = root / "wiki/30_template_and_operator_patterns.md"
            stale = page.read_text(encoding="utf-8") + "\nStale shadow text\n"
            page.write_text(stale, encoding="utf-8")
            report = run_knowledge_maintenance(root, "2026-08-02T00:00:00Z")
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(page.read_text(encoding="utf-8"), stale)
            self.assertIn("semantic_wiki_version_mismatch", {row["code"] for row in report["health"]["issues"]})

    def test_health_does_not_treat_arbitrary_release_file_as_selected_authority(self):
        from wqb.knowledge_experience_compile import _front_matter
        from wqb.knowledge_freshness import evaluate_knowledge_contract_health
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._active_release(root)
            fake = root / "machine/semantic_releases/unselected/template_library.jsonl"
            fake.parent.mkdir()
            fake.write_text("{}\n", encoding="utf-8")
            page = root / "wiki/00_start_here.md"
            page.write_text(_front_matter("2026-08-02", [fake.relative_to(root).as_posix()], ["human_learning"]), encoding="utf-8")
            health = evaluate_knowledge_contract_health(root)
            self.assertIn("wiki_backlink_not_source_authority", {row["code"] for row in health["issues"]})

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
