import json
import hashlib
import os
import tempfile
import unittest
import threading
from pathlib import Path
from unittest.mock import patch

from wqb.knowledge_contracts import (
    RawSourceMetadata,
    SourceIndexRow,
    canonical_source_family,
    parse_markdown_front_matter,
    render_front_matter,
    update_source_index,
    validate_raw_metadata,
    validate_wiki_metadata,
)


class KnowledgeContractTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows namespace aliases')
    def test_resolved_source_namespace_normalization_is_filesystem_only(self):
        """Input: mocked resolved Windows paths. Output: assertions. Normalize filesystem aliases, not device namespaces."""
        from wqb.knowledge_contracts import _resolved_source_path
        for resolved, expected in ((r'\\?\C:\vault\raw', r'C:\vault\raw'),
                                   (r'\\?\UNC\server\share\raw', r'\\server\share\raw'),
                                   (r'\\?\GLOBALROOT\Device\HarddiskVolume1', r'\\?\GLOBALROOT\Device\HarddiskVolume1')):
            with self.subTest(resolved=resolved), patch.object(Path, 'resolve', return_value=Path(resolved)):
                self.assertEqual(_resolved_source_path(Path('unused')), Path(expected))

    @unittest.skipUnless(os.name == 'nt', 'Windows namespace aliases')
    def test_source_contract_missing_index_namespace_alias_stays_contained(self):
        """Input: equivalent Windows resolved namespace. Output: assertions. Concurrent missing indexes are not escapes."""
        from wqb.knowledge_contracts import _source_contract_path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / 'machine/source_index.jsonl'
            resolve = Path.resolve

            def mixed(path, *args, **kwargs):
                """Input: Path/resolve arguments. Output: Path. Reproduce the observed first-index namespace race."""
                value = resolve(path, *args, **kwargs)
                return Path('\\\\?\\' + str(value)) if path == target else value

            with patch.object(Path, 'resolve', mixed):
                self.assertEqual(_source_contract_path(root, 'machine/source_index.jsonl'), target)
            self.assertFalse(target.parent.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows namespace aliases')
    def test_source_contract_namespace_normalization_does_not_allow_escape(self):
        """Input: extended namespace pointing outside root. Output: assertions. Namespace equality does not weaken containment."""
        from wqb.knowledge_contracts import _source_contract_path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / 'machine/source_index.jsonl'
            outside = root.parent / (root.name + '-outside') / 'source_index.jsonl'
            resolve = Path.resolve

            def escaped(path, *args, **kwargs):
                """Input: Path/resolve arguments. Output: Path. Model a genuine resolved escape."""
                return Path('\\\\?\\' + str(outside)) if path == target else resolve(path, *args, **kwargs)

            with patch.object(Path, 'resolve', escaped), self.assertRaises(ValueError):
                _source_contract_path(root, 'machine/source_index.jsonl')

    def test_parse_and_render_front_matter_preserves_body(self):
        text = "---\nsource_type: platform_api\nsource_family: data_fields\nrecord_count: 3\ncompiled_targets:\n  - wiki/20_data_semantics.md\n---\n# Body\n"

        metadata, body = parse_markdown_front_matter(text)
        rendered = render_front_matter(metadata) + body

        self.assertEqual(metadata["source_type"], "platform_api")
        self.assertEqual(metadata["source_family"], "data_fields")
        self.assertEqual(metadata["record_count"], 3)
        self.assertEqual(metadata["compiled_targets"], ["wiki/20_data_semantics.md"])
        self.assertIn("# Body", rendered)

    def test_parse_markdown_front_matter_preserves_body_without_trailing_newline(self):
        text = "---\nsource_type: platform_api\n---\n# Body"

        _, body = parse_markdown_front_matter(text)

        self.assertEqual(body, "# Body")

    def test_validate_raw_metadata_reports_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "knowledge" / "raw" / "platform" / "learn" / "2026-07-22" / "operators.md"
            path.parent.mkdir(parents=True)
            path.write_text("---\nsource_type: platform_api\n---\n# Operators\n", encoding="utf-8")

            issues = validate_raw_metadata(path)

        self.assertIn("missing source_family", issues)
        self.assertIn("missing captured_at", issues)
        self.assertIn("missing content_status", issues)
        self.assertIn("missing compiled_targets", issues)

    def test_validate_raw_metadata_rejects_unknown_content_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "knowledge" / "raw" / "platform" / "learn" / "2026-07-22" / "operators.md"
            path.parent.mkdir(parents=True)
            path.write_text(
                "---\n"
                "source_type: platform_api\n"
                "source_family: raw/platform/learn\n"
                "source_path: raw/platform/learn/2026-07-22/operators.md\n"
                "captured_at: 2026-07-22T00:00:00Z\n"
                "capture_tool: test\n"
                "content_status: typo_status\n"
                "record_count: 1\n"
                "content_hash: abc\n"
                "update_check: compare\n"
                "compiled_targets:\n"
                "  - wiki/20_data_semantics.md\n"
                "---\n"
                "# Operators\n",
                encoding="utf-8",
            )

            issues = validate_raw_metadata(path)

        self.assertIn("content_status must be raw_markdown", issues)

    def test_validate_wiki_metadata_requires_source_and_consumers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "knowledge" / "wiki" / "50_benchmarks" / "correlation_and_novelty.md"
            path.parent.mkdir(parents=True)
            path.write_text("---\ncompiled_at: 2026-07-22\n---\n# Rule\n", encoding="utf-8")

            issues = validate_wiki_metadata(path)

        self.assertIn("missing compiled_from", issues)
        self.assertIn("missing consumed_by", issues)
        self.assertIn("missing update_trigger", issues)
        self.assertIn("missing stale_after_days", issues)

    def test_canonical_source_family_identifies_legacy_and_canonical_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"

            canonical = canonical_source_family(root / "raw" / "platform" / "learn" / "2026-07-22" / "index.md", root)
            legacy = canonical_source_family(root / "raw" / "learn" / "old.md", root)
            wiki = canonical_source_family(root / "wiki" / "20_data_semantics.md", root)
            case_report = canonical_source_family(root / "wiki" / "60_research_cases" / "run-1.md", root)
            old_wiki = canonical_source_family(root / "wiki" / "20_semantics" / "operators.md", root)
            machine = canonical_source_family(root / "machine" / "data_ledger.jsonl", root)
            unknown_machine = canonical_source_family(root / "machine" / "untrusted.jsonl", root)

        self.assertEqual(canonical, "raw/platform/learn")
        self.assertEqual(legacy, "legacy")
        self.assertEqual(wiki, "wiki/20_data_semantics.md")
        self.assertEqual(case_report, "wiki/60_research_cases")
        self.assertEqual(old_wiki, "legacy")
        self.assertEqual(machine, "machine/data_ledger.jsonl")
        self.assertEqual(unknown_machine, "external")

    def test_update_source_index_writes_stable_markdown_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            row = SourceIndexRow(
                path="raw/platform/data_fields/2026-07-22/index.md",
                source_family="data_fields",
                source_type="platform_api",
                contents="platform data-field capture manifest",
                update_check="compare field ids and exact scopes",
                captured_at="2026-07-22T00:00:00+00:00",
                record_count=10,
                content_hash="abc123",
                content_status="raw_markdown",
                compiled_targets=["wiki/20_data_semantics.md"],
            )

            output = update_source_index(root, [row])
            text = output.read_text(encoding="utf-8")
            machine_rows = [
                json.loads(line)
                for line in (root / "machine" / "source_index.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertIn("raw/platform/data_fields/2026-07-22/index.md", text)
        self.assertIn("compare field ids and exact scopes", text)
        self.assertIn("wiki/20_data_semantics.md", text)
        self.assertEqual(machine_rows, [
            {
                "path": "raw/platform/data_fields/2026-07-22/index.md",
                "source_family": "data_fields",
                "source_type": "platform_api",
                "contents": "platform data-field capture manifest",
                "update_check": "compare field ids and exact scopes",
                "captured_at": "2026-07-22T00:00:00+00:00",
                "record_count": 10,
                "content_hash": "abc123",
                "content_status": "raw_markdown",
                "compiled_targets": ["wiki/20_data_semantics.md"],
            }
        ])


class SourceIndexConcurrencyTests(unittest.TestCase):
    def test_upsert_rejects_duplicate_and_mistyped_rows_without_coercion(self):
        from wqb.knowledge_contracts import source_index_row_to_dict, upsert_source_index_rows
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            row = SourceIndexRow(path='raw/platform/learn/fixture/first.md', source_family='raw/platform/learn',
                                 source_type='platform_learn_material', contents='fixture', update_check='compare')
            update_source_index(root, [row])
            index = root / 'machine/source_index.jsonl'
            payload = source_index_row_to_dict(row)
            malformed = [[payload, payload], [dict(payload, record_count=True)],
                         [dict(payload, compiled_targets='wiki/page.md')], [dict(payload, source_type=3)]]
            for records in malformed:
                with self.subTest(records=records):
                    index.write_text(''.join(json.dumps(item) + '\n' for item in records), encoding='utf-8')
                    before = index.read_bytes()
                    with self.assertRaises(ValueError):
                        upsert_source_index_rows(root, [row])
                    self.assertEqual(index.read_bytes(), before)
            index.write_text(json.dumps(payload) + '\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                upsert_source_index_rows(root, [row, row])

    def test_failed_atomic_replace_preserves_previous_index(self):
        from wqb.knowledge_contracts import _write_index_file
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'index.jsonl'
            path.write_bytes(b'old bytes')
            with patch.object(Path, 'replace', side_effect=OSError('fixture replace failure')):
                with self.assertRaises(OSError):
                    _write_index_file(path, 'new bytes')
            self.assertEqual(path.read_bytes(), b'old bytes')
            self.assertEqual([item.name for item in path.parent.iterdir()], ['index.jsonl'])

    def test_linked_index_parent_is_refused_before_guard_write(self):
        from wqb.knowledge_contracts import upsert_source_index_rows
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            linked = root / 'machine'
            original = Path.is_symlink

            def linked_parent(path):
                """Input: Path. Output: bool. Model a linked machine directory without symlink privileges."""
                return path == linked or original(path)

            with patch.object(Path, 'is_symlink', linked_parent), self.assertRaises(ValueError):
                upsert_source_index_rows(root, [])
            self.assertEqual(list(root.iterdir()), [])

    def test_concurrent_source_index_upserts_preserve_both_rows(self):
        from wqb.knowledge_contracts import upsert_source_index_rows
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = [SourceIndexRow(path='raw/platform/learn/fixture/' + name + '.md',
                source_family='raw/platform/learn', source_type='platform_learn_material',
                contents=name, update_check='compare actual source bytes')
                for name in ('base', 'first', 'second')]
            update_source_index(root, [rows[0]])
            index = root / 'machine/source_index.jsonl'
            first_read, second_read = threading.Event(), threading.Event()
            original = Path.read_text
            errors = []

            def read_snapshot(path, *args, **kwargs):
                """Input: Path/read arguments. Output: str. Expose old unguarded read-merge-write races."""
                result = original(path, *args, **kwargs)
                if path == index and threading.current_thread().name == 'index-first':
                    first_read.set()
                    second_read.wait(0.3)
                elif path == index and threading.current_thread().name == 'index-second':
                    second_read.set()
                return result

            def write(row):
                """Input: SourceIndexRow. Output: None. Capture thread errors for deterministic assertions."""
                try:
                    upsert_source_index_rows(root, [row])
                except Exception as error:
                    errors.append(error)

            with patch.object(Path, 'read_text', read_snapshot):
                first = threading.Thread(target=write, args=(rows[1],), name='index-first')
                second = threading.Thread(target=write, args=(rows[2],), name='index-second')
                first.start()
                self.assertTrue(first_read.wait(2))
                second.start()
                first.join(3)
                second.join(3)
                self.assertFalse(first.is_alive() or second.is_alive())
            self.assertEqual(errors, [])
            actual = [json.loads(line)['path'] for line in index.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(set(actual), {row.path for row in rows})


class FieldSourceExtractionTests(unittest.TestCase):
    def test_verified_excerpt_routes_capture_authority_only_for_selected_identity(self):
        from wqb.data_ledger import data_ledger_record_from_dict, is_authoritative_data_record
        from wqb.run_readiness import _batch_uncertified_records
        result = self.extract()
        source = self.root / self.source
        manifest = json.loads((source.parent / 'manifest.json').read_text(encoding='utf-8'))
        manifest['requested_matrix'] = [self.scope]
        # Generate a new excerpt after changing capture metadata; never repair a receipt by hand.
        (source.parent / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        result = self.extract()
        (source.parent / 'scopes.jsonl').write_text(json.dumps(dict(scope=self.scope, status='completed',
            certification_status='complete')) + '\n', encoding='utf-8')
        row = dict(dataset_id='fixture', field_id='second', field_type='MATRIX', region='USA', delay=1,
            universe='TOP3000', coverage=1, source_quality='platform_raw_capture', coverage_status='measured_raw',
            source_updated_at='2026-07-30', source_paths=[result['excerpt_path']])
        record = data_ledger_record_from_dict(row)
        self.assertTrue(is_authoritative_data_record(record, self.root))
        self.assertEqual(_batch_uncertified_records([record], self.root), [])
        for changed in (dict(field_id='first'), dict(dataset_id='other'), dict(universe='TOP1000')):
            other = data_ledger_record_from_dict(dict(row, **changed))
            with self.subTest(changed=changed):
                self.assertFalse(is_authoritative_data_record(other, self.root))
                self.assertEqual(_batch_uncertified_records([other], self.root), [other])
        excerpt = self.root / result['excerpt_path']
        excerpt.write_bytes(excerpt.read_bytes() + b'changed')
        self.assertFalse(is_authoritative_data_record(record, self.root))
        self.assertEqual(_batch_uncertified_records([record], self.root), [record])

    def setUp(self):
        """Input: TestCase. Output: None. Build isolated captured rows, never touch the real vault."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = 'raw/platform/data_fields/2026-07-30/data_fields.jsonl'
        self.scope = dict(instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000')
        self.date = '2026-07-30T00:00:00+00:00'
        self.rows = [dict(capture_generation_id='fixture-generation', endpoint='/data-fields',
            generated_at=self.date, scope=self.scope, data_set=dict(id='fixture'),
            field=dict(id=name, type='MATRIX', description='Fictional captured observation'))
            for name in ('first', 'second', 'third')]
        source = self.root / self.source
        source.parent.mkdir(parents=True)
        source.write_text(''.join(json.dumps(row) + '\n' for row in self.rows), encoding='utf-8')
        (source.parent / 'manifest.json').write_text(json.dumps(dict(generated_at=self.date,
            capture_generation_id='fixture-generation', certification_status='complete', field_count=3,
            error_count=0, scope=self.scope)), encoding='utf-8')

    def extract(self, identities=None):
        """Input: optional exact identity list. Output: extraction dict from the real planned API."""
        from wqb import knowledge_contracts
        self.assertTrue(hasattr(knowledge_contracts, 'extract_field_source_subset'))
        identities = identities or [dict(dataset_id='fixture', field_id='second', scope=self.scope)]
        return knowledge_contracts.extract_field_source_subset(self.root, self.source, identities)

    def verify(self, source_path):
        """Input: excerpt str. Output: dict. Exercise the read-only extraction verifier."""
        from wqb import knowledge_contracts
        self.assertTrue(hasattr(knowledge_contracts, 'verify_field_source_extract'))
        return knowledge_contracts.verify_field_source_extract(self.root, source_path)

    def test_extractor_refuses_missing_machine_history_before_overwriting_human_view(self):
        row = SourceIndexRow(path='raw/platform/learn/fixture/unrelated.md', source_family='raw/platform/learn',
            source_type='platform_learn_material', contents='unrelated history', update_check='compare')
        update_source_index(self.root, [row])
        human = self.root / 'raw/source_index.md'
        before = human.read_bytes()
        original = (self.root / self.source).read_bytes()
        (self.root / 'machine/source_index.jsonl').unlink()
        with self.assertRaises(ValueError):
            self.extract()
        self.assertEqual(human.read_bytes(), before)
        self.assertEqual((self.root / self.source).read_bytes(), original)
        self.assertFalse((self.root / 'machine/semantic_jobs').exists())

    def test_extractor_and_upsert_check_linked_index_leaf_before_any_read(self):
        from wqb.knowledge_contracts import upsert_source_index_rows
        update_source_index(self.root, [])
        index = self.root / 'machine/source_index.jsonl'
        real_link, real_read = Path.is_symlink, Path.read_text

        def linked_leaf(path):
            """Input: Path. Output: bool. Model a linked index leaf without OS symlink privileges."""
            return path == index or real_link(path)

        def refuse_index_read(path, *args, **kwargs):
            """Input: Path/read arguments. Output: str. Detect forbidden reading before link validation."""
            if path == index:
                raise AssertionError('linked index read before validation')
            return real_read(path, *args, **kwargs)

        with patch.object(Path, 'is_symlink', linked_leaf), patch.object(Path, 'read_text', refuse_index_read):
            for operation in (self.extract, lambda: upsert_source_index_rows(self.root, [])):
                with self.subTest(operation=operation), self.assertRaises(ValueError):
                    operation()

    def test_extractor_refuses_hardlinked_original_like_readonly_verifier(self):
        import os
        os.link(self.root / self.source, self.root / 'original-alias.jsonl')
        with self.assertRaises(ValueError):
            self.extract()
        self.assertFalse((self.root / 'machine/semantic_jobs').exists())

    def test_validator_cannot_downgrade_canonical_extract_to_raw_markdown(self):
        result = self.extract()
        excerpt = self.root / result['excerpt_path']
        metadata, body = parse_markdown_front_matter(excerpt.read_text(encoding='utf-8'))
        metadata['content_status'] = 'raw_markdown'
        metadata.pop('extraction_receipt')
        excerpt.write_text(render_front_matter(metadata) + body, encoding='utf-8')
        self.assertTrue(any('verification failed' in issue for issue in validate_raw_metadata(excerpt)))

    def test_extract_rechecks_original_after_artifact_writes_before_success(self):
        from wqb import knowledge_contracts
        real_write = knowledge_contracts._write_immutable_source
        original = self.root / self.source

        def mutate_after_write(path, content):
            """Input: Path/bytes. Output: None. Model external mutation during publication, not utility mutation."""
            real_write(path, content)
            if path.name == 'field_source_extract.json':
                original.write_bytes(original.read_bytes() + b'\n')

        with patch.object(knowledge_contracts, '_write_immutable_source', mutate_after_write), self.assertRaises(ValueError):
            self.extract()

    def test_readonly_extract_verification_never_publishes(self):
        result = self.extract()
        before = {p.relative_to(self.root).as_posix(): p.read_bytes()
                  for p in self.root.rglob('*') if p.is_file()}
        with patch('wqb.knowledge_contracts.extract_field_source_subset', side_effect=AssertionError('publication')):
            verified = self.verify(result['excerpt_path'])
        self.assertEqual(verified['original_sha256'], result['original_sha256'])
        self.assertEqual(verified['selected_rows'], 1)
        self.assertEqual(before, {p.relative_to(self.root).as_posix(): p.read_bytes()
                                for p in self.root.rglob('*') if p.is_file()})

    def test_readonly_extract_verification_rejects_each_consumed_artifact_tamper(self):
        result = self.extract()
        for relative in (self.source, result['receipt_path'], result['excerpt_path'],
                         'machine/source_index.jsonl', str(Path(self.source).parent / 'manifest.json')):
            path = self.root / relative
            saved = path.read_bytes()
            with self.subTest(path=relative):
                path.write_bytes(saved.replace(b'fixture-generation', b'forged-generation')
                                 if b'fixture-generation' in saved else saved + b'corruption')
                changed = path.read_bytes()
                with self.assertRaises(ValueError):
                    self.verify(result['excerpt_path'])
                self.assertEqual(path.read_bytes(), changed)
                path.write_bytes(saved)

    def test_readonly_extract_rejects_marker_only_path_alias_and_receipt_type_tamper(self):
        result = self.extract()
        for path in ('.', '../secret.md', 'raw/platform/learn/2026-07-29/semantic-subset-' + 'a' * 64 + '.md',
                     result['excerpt_path'].replace('/2026', '/./2026')):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.verify(path)
        receipt = self.root / result['receipt_path']
        saved = receipt.read_bytes()
        payload = json.loads(saved)
        payload['result']['selected_rows'] = True
        receipt.write_text(json.dumps(payload), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.verify(result['excerpt_path'])
        receipt.write_bytes(saved)
        excerpt = self.root / result['excerpt_path']
        metadata, _ = parse_markdown_front_matter(excerpt.read_text(encoding='utf-8'))
        excerpt.write_text(render_front_matter(metadata) + '# Marker only\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.verify(result['excerpt_path'])

    def test_readonly_extract_streams_original_and_rejects_linked_receipt(self):
        result = self.extract()
        real_read = Path.read_bytes

        def forbid_original_read(path):
            """Input: Path. Output: bytes. Refuse whole-file original JSONL reads in the verifier."""
            if path == self.root / self.source:
                raise AssertionError('original JSONL must stream')
            return real_read(path)

        with patch.object(Path, 'read_bytes', forbid_original_read):
            self.assertEqual(self.verify(result['excerpt_path'])['status'], 'verified')
        import os
        os.link(self.root / result['receipt_path'], self.root / 'linked-receipt.json')
        with self.assertRaises(ValueError):
            self.verify(result['excerpt_path'])

    def test_raw_metadata_accepts_verified_extract_only_after_readonly_receipt_check(self):
        result = self.extract()
        excerpt = self.root / result['excerpt_path']
        self.assertEqual(validate_raw_metadata(excerpt), [])
        original = self.root / self.source
        original.write_bytes(original.read_bytes() + b'\n')
        issues = validate_raw_metadata(excerpt)
        self.assertTrue(any('verified_raw_extract verification failed' in issue for issue in issues))

    def test_raw_metadata_rejects_marker_only_extract_without_receipt(self):
        result = self.extract()
        excerpt = self.root / result['excerpt_path']
        (self.root / result['receipt_path']).unlink()
        self.assertTrue(any('verified_raw_extract verification failed' in issue
                            for issue in validate_raw_metadata(excerpt)))

    def test_top_scope_explicit_unsuccessful_status_rejects(self):
        """Input: failed/in-progress fixture manifests. Output: no trusted extract or machine artifacts."""
        path = (self.root / self.source).parent / 'manifest.json'
        base = json.loads(path.read_text(encoding='utf-8'))
        for status in ('failed', 'running', 'in_progress', None):
            with self.subTest(status=status):
                path.write_text(json.dumps(dict(base, status=status, certification_status='partial')),
                                encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.extract()
                self.assertFalse((self.root / 'machine').exists())

    def test_large_jsonl_excerpt_preserves_original_hash_and_date(self):
        source = self.root / self.source
        rows = [dict(self.rows[0], field=dict(id='padding_' + str(i), type='MATRIX',
            description='Fictional observation ' + 'x' * 1000)) for i in range(2200)]
        source.write_text(''.join(json.dumps(row) + '\n' for row in rows + self.rows), encoding='utf-8')
        manifest_path = source.parent / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['field_count'] = len(rows) + len(self.rows)
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        before = source.read_bytes()
        result = self.extract()
        self.assertEqual(result['status'], 'extracted')
        self.assertEqual(result['original_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(result['selected_rows'], 1)
        excerpt = self.root / result['excerpt_path']
        metadata, body = parse_markdown_front_matter(excerpt.read_text(encoding='utf-8'))
        self.assertEqual(metadata['captured_at'], self.date)
        self.assertEqual(metadata['content_status'], 'verified_raw_extract')
        self.assertIn('second', body)
        self.assertNotIn('padding_2199', body)
        self.assertLess(excerpt.stat().st_size, 10000)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(self.extract(), result)

    def test_excerpt_replay_rejects_changed_original(self):
        result = self.extract()
        receipt = self.root / result['receipt_path']
        before = receipt.read_bytes()
        original = self.root / self.source
        original.write_bytes(original.read_bytes().replace(b'Fictional captured observation',
            b'Changed captured observation', 1))
        with self.assertRaises(ValueError):
            self.extract()
        self.assertEqual(receipt.read_bytes(), before)

    def test_exact_identity_scope_and_duplicate_rows_are_required(self):
        for mode in ('dataset', 'scope', 'duplicate'):
            with self.subTest(mode=mode):
                identity = dict(dataset_id='fixture', field_id='second', scope=dict(self.scope))
                if mode == 'dataset':
                    identity['dataset_id'] = 'other'
                elif mode == 'scope':
                    identity['scope']['delay'] = True
                else:
                    with (self.root / self.source).open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(self.rows[1]) + '\n')
                with self.assertRaises(ValueError):
                    self.extract([identity])

    def test_manifest_must_cover_exact_selected_scope(self):
        path = (self.root / self.source).parent / 'manifest.json'
        base = json.loads(path.read_text(encoding='utf-8'))
        other = dict(self.scope, region='CHN')
        for mode in ('foreign', 'boolean', 'matrix'):
            manifest = dict(base)
            if mode == 'foreign':
                manifest.update(scope=other, requested_matrix=[other], latest_scope_outcomes=[dict(
                    scope=other, generated_at=self.date, capture_generation_id='fixture-generation', status='completed')])
            elif mode == 'boolean':
                manifest['scope'] = dict(self.scope, delay=True)
            else:
                manifest['requested_matrix'] = [other]
            path.write_text(json.dumps(manifest), encoding='utf-8')
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.extract()

    def test_resumed_manifest_does_not_renew_selected_row_date(self):
        path = (self.root / self.source).parent / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest.update(generated_at='2026-07-30T12:00:00+00:00', capture_generation_id='resumed-generation',
            latest_scope_outcomes=[dict(scope=self.scope, generated_at=self.date,
                capture_generation_id='fixture-generation', status='completed')])
        path.write_text(json.dumps(manifest), encoding='utf-8')
        result = self.extract()
        metadata, _ = parse_markdown_front_matter((self.root / result['excerpt_path']).read_text(encoding='utf-8'))
        receipt = json.loads((self.root / result['receipt_path']).read_text(encoding='utf-8'))
        self.assertEqual(metadata['captured_at'], self.date)
        self.assertEqual(receipt['captured_at'], self.date)
        self.assertEqual(receipt['row_receipts'][0]['captured_at'], self.date)

    def test_mixed_capture_epochs_require_separate_excerpts(self):
        source = self.root / self.source
        later = '2026-07-30T12:00:00+00:00'
        second_scope = dict(self.scope, universe='TOP2000')
        self.rows[1] = dict(self.rows[1], scope=second_scope, generated_at=later, capture_generation_id='later-generation')
        source.write_text(''.join(json.dumps(row) + '\n' for row in self.rows), encoding='utf-8')
        manifest = json.loads((source.parent / 'manifest.json').read_text(encoding='utf-8'))
        manifest['latest_scope_outcomes'] = [dict(scope=scope, generated_at=date,
            capture_generation_id=generation, status='completed') for scope, date, generation in (
                (self.scope, self.date, 'fixture-generation'), (second_scope, later, 'later-generation'))]
        (source.parent / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        identities = [dict(dataset_id='fixture', field_id=name, scope=scope)
                      for name, scope in (('first', self.scope), ('second', second_scope))]
        with self.assertRaises(ValueError):
            self.extract(identities)

    def test_conflicting_original_index_requires_explicit_repair(self):
        result = self.extract()
        index = self.root / 'machine/source_index.jsonl'
        base = [json.loads(line) for line in index.read_text(encoding='utf-8').splitlines()]
        for key, value in [('captured_at', '2099-01-01T00:00:00+00:00'), ('record_count', 999),
                           ('content_status', 'verified_semantics'), ('scope', dict(self.scope, region='CHN'))]:
            changed = [dict(row, **{key: value}) if row['path'] == self.source else row for row in base]
            index.write_text(''.join(json.dumps(row) + '\n' for row in changed), encoding='utf-8')
            before = (self.root / result['receipt_path']).read_bytes()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.extract()
            self.assertEqual((self.root / result['receipt_path']).read_bytes(), before)

    def test_malformed_manifest_types_reject_with_value_error(self):
        path = (self.root / self.source).parent / 'manifest.json'
        base = json.loads(path.read_text(encoding='utf-8'))
        for key, value in [('latest_scope_outcomes', None), ('latest_scope_outcomes', {}),
                           ('capture_generation_id', True), ('requested_matrix', [dict(self.scope, delay=True)])]:
            path.write_text(json.dumps(dict(base, **{key: value})), encoding='utf-8')
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.extract()

    def test_receipt_type_tamper_and_conflicting_artifact_are_not_overwritten(self):
        result = self.extract()
        receipt = self.root / result['receipt_path']
        saved = receipt.read_bytes()
        changed = json.loads(saved)
        changed['result']['selected_rows'] = True
        receipt.write_text(json.dumps(changed), encoding='utf-8')
        before = receipt.read_bytes()
        with self.assertRaises(ValueError):
            self.extract()
        self.assertEqual(receipt.read_bytes(), before)
        receipt.write_bytes(saved)
        excerpt = self.root / result['excerpt_path']
        excerpt.write_bytes(b'conflicting owned-source evidence')
        with self.assertRaises(ValueError):
            self.extract()
        self.assertEqual(excerpt.read_bytes(), b'conflicting owned-source evidence')

    def test_interrupted_artifact_creation_can_replay_safely(self):
        original_open = Path.open
        for target in ('semantic-subset-', 'field_source_extract.json'):
            with self.subTest(target=target):
                class BrokenWrite:
                    def __init__(self, stream):
                        """Input: real binary stream. Output: wrapper. Inject an owned artifact write failure."""
                        self.stream = stream

                    def __enter__(self):
                        """Input: none. Output: wrapper. Enter the real file context."""
                        self.stream.__enter__()
                        return self

                    def __exit__(self, *args):
                        """Input: exception context tuple. Output: context result. Close the real file."""
                        return self.stream.__exit__(*args)

                    def write(self, content):
                        """Input: artifact bytes. Output: raises OSError after a partial write."""
                        self.stream.write(content[:10])
                        raise OSError('fixture partial artifact write')

                def fail_write(path, *args, **kwargs):
                    """Input: Path/open arguments. Output: stream or injected failing writer."""
                    stream = original_open(path, *args, **kwargs)
                    if args and args[0] == 'xb' and target in path.name:
                        return BrokenWrite(stream)
                    return stream

                identities = [dict(dataset_id='fixture', field_id=name, scope=self.scope)
                              for name in (['first'] if target == 'semantic-subset-' else ['third'])]
                with patch.object(Path, 'open', fail_write), self.assertRaises(OSError):
                    self.extract(identities)
                self.assertEqual(self.extract(identities)['status'], 'extracted')
        self.assertEqual(list(self.root.rglob('*.tmp')), [])


class SourceMetadataRepairTests(unittest.TestCase):
    def verify(self):
        """Input: none. Output: dict. Verify the fixture repair without publication."""
        from wqb import knowledge_contracts
        self.assertTrue(hasattr(knowledge_contracts, 'verify_source_repair'))
        return knowledge_contracts.verify_source_repair(self.root, self.source)

    def test_readonly_completion_rejects_partial_publication_then_accepts_replay(self):
        """Input: none. Output: None. Inject interrupted human publication and verify both consumers."""
        from wqb import knowledge_contracts, semantic_compilation, semantic_publication
        real_write = knowledge_contracts._write_index_file

        def fail_human(path, content):
            """Input: Path/str. Output: None or OSError. Interrupt human-index publication."""
            if path == self.root / 'raw/source_index.md':
                raise OSError('fixture interrupted human index')
            return real_write(path, content)

        with patch.object(knowledge_contracts, '_write_index_file', fail_human), self.assertRaises(OSError):
            self.repair(dry_run=False)
        row = json.loads((self.root / 'machine/source_index.jsonl').read_bytes())
        raw = (self.root / self.source).read_bytes()
        refs = [dict(path=self.source, sha256=hashlib.sha256(raw).hexdigest())]
        with self.assertRaises(ValueError):
            self.verify()
        with self.assertRaises(ValueError):
            semantic_compilation._material(self.root, row)
        with self.assertRaises(ValueError):
            semantic_publication._verify_sources(self.root, refs)
        self.repair(dry_run=False)
        result = self.verify()
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['source_sha256'], refs[0]['sha256'])
        semantic_compilation._material(self.root, row)
        semantic_publication._verify_sources(self.root, refs)

    def test_completion_is_readonly_and_legacy_does_not_require_index_agreement(self):
        """Input: none. Output: None. Assert no writes/locks for legacy and completed repairs."""
        from wqb import knowledge_contracts
        human = self.root / 'raw/source_index.md'
        saved = human.read_bytes()
        human.write_bytes(b'legacy disagreement is not a repair marker')
        self.assertEqual(self.verify(), dict(status='not_repaired', source_sha256=hashlib.sha256(self.before).hexdigest()))
        human.write_bytes(saved)
        self.repair(dry_run=False)
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(knowledge_contracts, '_source_index_guard', side_effect=AssertionError('no nested lock')):
            self.assertEqual(self.verify()['status'], 'verified')
        self.assertEqual(before, {p.relative_to(self.root).as_posix(): p.read_bytes()
                                 for p in self.root.rglob('*') if p.is_file()})

    def test_completion_rejects_unknown_removed_marker_and_exact_byte_tampering(self):
        """Input: none. Output: None. Reject removed/unknown markers and noncanonical source/receipt bytes."""
        from wqb.knowledge_contracts import _repair_markdown_parts
        result = self.repair(dry_run=False)['results'][0]
        source = self.root / self.source
        receipt = self.root / result['receipt_path']
        raw, receipt_raw = source.read_bytes(), receipt.read_bytes()
        metadata, _, body = _repair_markdown_parts(raw)
        removed = dict(metadata)
        removed.pop('source_repair_receipt')
        for changed in (render_front_matter(removed).encode() + body,
                        raw.replace(b'source_repair_receipt:', b'source_repair_unknown:'),
                        raw.replace(b'---\n', b'---\r\n', 1)):
            source.write_bytes(changed)
            with self.subTest(changed=changed[:80]), self.assertRaises(ValueError):
                self.verify()
        source.write_bytes(raw)
        receipt.write_bytes(receipt_raw + b' ')
        with self.assertRaises(ValueError):
            self.verify()
        receipt.write_bytes(receipt_raw)
        (self.cache / 'operators.json').write_bytes(b'[]')
        with self.assertRaises(ValueError):
            self.verify()

    def test_completion_rejects_lost_machine_index_and_index_only_unknown_marker(self):
        """Input: none. Output: None. Reject lost publication state and unknown index repair authority."""
        index = self.root / 'machine/source_index.jsonl'
        row = json.loads(index.read_bytes())
        index.write_text(json.dumps(dict(row, source_repair_unknown='unknown')), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.verify()
        index.write_text(json.dumps(row), encoding='utf-8')
        self.repair(dry_run=False)
        index.unlink()
        with self.assertRaises(ValueError):
            self.verify()
        self.repair(dry_run=False)
        self.assertEqual(self.verify()['status'], 'verified')

    def setUp(self):
        """Input: none. Output: temporary fixture. Use the actual legacy Learn writer/cache formats."""
        from scripts import capture_learn_material as capture
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.date = '2026-07-30T12:00:00+00:00'
        self.source = 'raw/platform/learn/2026-07-30/operators.md'
        self.payload = [dict(name='fixture_delta', category='Time Series', definition='fixture_delta(x, d)',
                             description='Fictional change.', scope=['REGULAR'], level='ALL')]
        directory = (self.root / self.source).parent
        with patch.object(capture, 'KNOWLEDGE_ROOT', self.root):
            capture.write_raw_operators(self.payload, self.date, directory)
        self.cache = self.root / 'docs/knowledge/cache/learn/2026-07-30'
        capture.write_json(self.cache / 'operators.json', self.payload)
        capture.write_json(self.cache / 'learn_capture_manifest.json', dict(generated_at=self.date,
            excluded=['courses'], counts=dict(operators=1), search_query_count=0))
        metadata, self.body = parse_markdown_front_matter((self.root / self.source).read_text(encoding='utf-8'))
        metadata.update(content_hash='bad-old-payload-digest', payload_hash='bad-old-payload-digest',
                        source_family='legacy', source_type='platform_api')
        # Transport CRLF must survive repair even though semantic body hashing normalizes LF.
        (self.root / self.source).write_bytes((render_front_matter(metadata) + self.body).replace('\n', '\r\n').encode())
        self.before = (self.root / self.source).read_bytes()
        self.metadata_before = metadata
        self.row = SourceIndexRow(path=self.source, source_family='legacy', source_type='platform_api',
            contents='Historical fixture', update_check=metadata['update_check'], compiled_targets=metadata['compiled_targets'],
            captured_at=self.date, record_count=1, content_hash='bad-old-payload-digest', content_status='raw_markdown')
        update_source_index(self.root, [self.row])

    def repair(self, paths=None, **kwargs):
        """Input: optional paths/list and keyword flags. Output: actual repair API dict."""
        from wqb import knowledge_contracts
        self.assertTrue(hasattr(knowledge_contracts, 'repair_source_metadata'))
        return knowledge_contracts.repair_source_metadata(self.root, paths or [self.source], **kwargs)

    def test_first_repair_refuses_missing_machine_history_before_any_publication(self):
        unrelated = SourceIndexRow(path='raw/platform/learn/fixture/unrelated.md', source_family='raw/platform/learn',
            source_type='platform_learn_material', contents='unrelated history', update_check='compare')
        update_source_index(self.root, [self.row, unrelated])
        human = self.root / 'raw/source_index.md'
        before = human.read_bytes()
        (self.root / 'machine/source_index.jsonl').unlink()
        with self.assertRaises(ValueError):
            self.repair(dry_run=False)
        self.assertEqual(human.read_bytes(), before)
        self.assertEqual((self.root / self.source).read_bytes(), self.before)
        self.assertFalse((self.root / 'machine/semantic_jobs').exists())

    def test_repair_rejects_all_retained_error_response_markers(self):
        for key in ('error', 'errors', 'detail'):
            with self.subTest(key=key):
                (self.cache / 'operators.json').write_text(json.dumps([dict(self.payload[0], **{key: 'API failure'})]),
                                                         encoding='utf-8')
                for dry_run in (True, False):
                    self.assertEqual(self.repair(dry_run=dry_run)['results'][0]['status'], 'need_fresh_capture')
                self.assertEqual((self.root / self.source).read_bytes(), self.before)
                self.assertFalse((self.root / 'machine/semantic_jobs').exists())

    def test_source_repair_dry_run_is_zero_write_and_preserves_original_metadata(self):
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.repair()
        self.assertEqual(result['results'][0]['status'], 'planned')
        self.assertEqual(before, {p.relative_to(self.root).as_posix(): p.read_bytes()
                                for p in self.root.rglob('*') if p.is_file()})

    def test_source_repair_preserves_date_and_payload_digest(self):
        from scripts import capture_learn_material as capture
        result = self.repair(dry_run=False)['results'][0]
        self.assertEqual(result['status'], 'repaired')
        after = (self.root / self.source).read_bytes()
        self.assertEqual(after.split(b'---\r\n', 2)[-1] if after.startswith(b'---\r\n') else
                         after.split(b'---\n', 2)[-1], self.before.split(b'---\r\n', 2)[-1])
        metadata, body = parse_markdown_front_matter(after.decode().replace('\r\n', '\n'))
        self.assertEqual(metadata['captured_at'], self.date)
        self.assertEqual(metadata['content_hash'], hashlib.sha256(body.encode()).hexdigest())
        self.assertEqual(metadata['payload_hash'], capture.stable_json_hash(self.payload))
        self.assertEqual(metadata['source_type'], 'platform_learn_material')
        self.assertEqual(metadata['source_family'], 'raw/platform/learn')
        receipt_file = self.root / result['receipt_path']
        saved = receipt_file.read_bytes()
        receipt = json.loads(saved)
        self.assertEqual(receipt['before_metadata'], self.metadata_before)
        self.assertEqual(receipt['before_sha256'], hashlib.sha256(self.before).hexdigest())
        self.assertEqual(self.repair(dry_run=False)['results'][0]['status'], 'repaired')
        self.assertEqual(receipt_file.read_bytes(), saved)

    def test_unverifiable_original_requires_fresh_capture(self):
        path = self.cache / 'operators.json'
        for content in (b'[]', b'{"error":"failed capture"}', b'[{"name":"unrelated"}]'):
            with self.subTest(content=content):
                path.write_bytes(content)
                result = self.repair(dry_run=False)['results'][0]
                self.assertEqual(result['status'], 'need_fresh_capture')
                self.assertEqual((self.root / self.source).read_bytes(), self.before)
                self.assertFalse((self.root / 'machine/semantic_jobs').exists())

    def test_matching_corrupt_header_hash_cannot_certify_changed_body(self):
        path = self.root / self.source
        path.write_bytes(self.before.replace(b'Fictional change.', b'Invented derived semantics.'))
        changed = path.read_bytes()
        self.assertEqual(self.repair(dry_run=False)['results'][0]['status'], 'need_fresh_capture')
        self.assertEqual(path.read_bytes(), changed)

    def test_index_correction_restart_fail_closed(self):
        from wqb import knowledge_contracts
        real_write = knowledge_contracts._write_index_file

        def fail_human(path, content):
            """Input: Path/text. Output: None or OSError. Interrupt only the human-index publication."""
            if path == self.root / 'raw/source_index.md':
                raise OSError('fixture interrupted human index')
            return real_write(path, content)

        with patch.object(knowledge_contracts, '_write_index_file', fail_human), self.assertRaises(OSError):
            self.repair(dry_run=False)
        stale_human = (self.root / 'raw/source_index.md').read_bytes()
        result = self.repair(dry_run=False)['results'][0]
        self.assertEqual(result['status'], 'repaired')
        self.assertNotEqual((self.root / 'raw/source_index.md').read_bytes(), stale_human)
        self.assertIn('platform_learn_material', (self.root / 'raw/source_index.md').read_text())
        self.assertEqual(len(list((self.root / 'machine/semantic_jobs').glob('*/source_repair.json'))), 1)

    def test_repair_refuses_path_alias_sensitive_and_hardlinked_sources(self):
        for path in ('../secret.md', 'raw/platform/learn/2026-07-30/../operators.md',
                     'C:/secret.md', 'raw/platform/learn/2026-07-30/.env', self.source.replace('/', '\\')):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.repair([path], dry_run=False)
        import os
        alias = self.root / 'alias.md'
        os.link(self.root / self.source, alias)
        with self.assertRaises(ValueError):
            self.repair(dry_run=False)

    def test_repair_replay_rejects_changed_original_cache_and_receipt(self):
        result = self.repair(dry_run=False)['results'][0]
        receipt = self.root / result['receipt_path']
        saved = receipt.read_bytes()
        changed = json.loads(saved)
        changed['before_metadata']['captured_at'] = '2099-01-01T00:00:00Z'
        receipt.write_text(json.dumps(changed), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.repair(dry_run=False)
        receipt.write_bytes(saved)
        (self.cache / 'operators.json').write_text('[]', encoding='utf-8')
        self.assertEqual(self.repair(dry_run=False)['results'][0]['status'], 'need_fresh_capture')
        self.assertEqual(receipt.read_bytes(), saved)

    def test_repair_replays_missing_machine_view_from_verified_receipt(self):
        result = self.repair(dry_run=False)['results'][0]
        receipt_file = self.root / result['receipt_path']
        saved = receipt_file.read_bytes()
        (self.root / 'machine/source_index.jsonl').unlink()
        self.assertEqual(self.repair(dry_run=False)['results'][0]['status'], 'repaired')
        self.assertEqual(receipt_file.read_bytes(), saved)
        self.assertIn('platform_learn_material', (self.root / 'machine/source_index.jsonl').read_text())

    def test_repair_never_discards_unrelated_human_rows_when_machine_index_is_lost(self):
        self.repair(dry_run=False)
        human = self.root / 'raw/source_index.md'
        human.write_bytes(human.read_bytes() + b'\n## `raw/unrelated.md`\nHistorical unrelated source\n')
        before = human.read_bytes()
        (self.root / 'machine/source_index.jsonl').unlink()
        with self.assertRaises(ValueError):
            self.repair(dry_run=False)
        self.assertEqual(human.read_bytes(), before)
        self.assertFalse((self.root / 'machine/source_index.jsonl').exists())

    def test_repair_checks_retained_original_again_before_acknowledging_publication(self):
        from wqb import knowledge_contracts
        real_upsert = knowledge_contracts._upsert_source_index_rows_unlocked

        def mutate_cache(root, rows):
            """Input: Path/rows. Output: Path. Change consumed original evidence during index publication."""
            result = real_upsert(root, rows)
            (self.cache / 'operators.json').write_bytes(b'[]')
            return result

        with patch.object(knowledge_contracts, '_upsert_source_index_rows_unlocked', mutate_cache):
            with self.assertRaises(ValueError):
                self.repair(dry_run=False)

    def test_repair_refuses_non_content_addressed_receipt_before_reading_it(self):
        from wqb import knowledge_contracts
        metadata = dict(self.metadata_before, source_repair_receipt='machine/semantic_jobs/private/source_repair.json')
        (self.root / self.source).write_text(render_front_matter(metadata) + self.body, encoding='utf-8')
        real_read = knowledge_contracts._source_contract_bytes

        def protected_read(path, limit):
            """Input: Path/int. Output: bytes. Detect even attempted access to an invalid receipt namespace."""
            if 'private' in path.parts:
                raise AssertionError('invalid receipt must not be read')
            return real_read(path, limit)

        with patch.object(knowledge_contracts, '_source_contract_bytes', protected_read), self.assertRaises(ValueError):
            self.repair(dry_run=False)

    def test_repair_rejects_unknown_family_and_conflicting_index_without_writes(self):
        unknown = self.source.replace('operators.md', 'unknown.md')
        (self.root / unknown).write_bytes(self.before)
        self.assertEqual(self.repair([unknown], dry_run=False)['results'][0]['status'], 'need_fresh_capture')
        index = self.root / 'machine/source_index.jsonl'
        index.write_bytes(index.read_bytes() * 2)
        with self.assertRaises(ValueError):
            self.repair(dry_run=False)
        self.assertEqual((self.root / self.source).read_bytes(), self.before)

    def test_repair_documentation_uses_actual_legacy_cache_without_endpoint_field(self):
        from scripts import capture_learn_material as capture
        from wqb.knowledge_contracts import _learn_repair_body
        pages = [dict(id='fictional-types', title='Fictional Types', category='Documentation',
                      content='<p>Fictional matrix documentation.</p>')]
        source = self.source.replace('operators.md', 'documentation_pages.md')
        with patch.object(capture, 'KNOWLEDGE_ROOT', self.root):
            capture.write_raw_documentation_pages(pages, self.date, (self.root / source).parent)
        # Current captures retain an extra payload section; this fixture is the
        # historical renderer whose original array cache authorizes repair.
        metadata, _ = parse_markdown_front_matter((self.root / source).read_text(encoding='utf-8'))
        (self.root / source).write_text(render_front_matter(metadata) + _learn_repair_body('documentation_pages', pages),
                                       encoding='utf-8')
        capture.write_json(self.cache / 'documentation_pages.json', pages)
        manifest = json.loads((self.cache / 'learn_capture_manifest.json').read_bytes())
        manifest['counts']['documentation_pages'] = 1
        capture.write_json(self.cache / 'learn_capture_manifest.json', manifest)
        self.assertEqual(self.repair([source], dry_run=False)['results'][0]['status'], 'repaired')
        metadata, _ = parse_markdown_front_matter((self.root / source).read_text(encoding='utf-8'))
        self.assertEqual(metadata['source_type'], 'platform_learn_material')
        self.assertNotIn('endpoint', metadata)


if __name__ == "__main__":
    unittest.main()
