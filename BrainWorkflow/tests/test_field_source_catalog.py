"""Derived SQLite directory tests; original captures remain the only source facts."""

import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch


class FieldSourceCatalogTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated existing-format partial capture with automatic cleanup."""
        from tests.test_bulk_field_extracts import BulkFieldExtractTests
        self.fixture = BulkFieldExtractTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.source
        self.root = self.fixture.root
        self.manifest = json.loads(self.fixture.manifest.read_text(encoding='utf-8'))
        self.identity = dict(dataset_id='prices', field_id='f032', scope=self.fixture.scope)

    def scan(self, **kwargs):
        """Input: optional catalog flags. Output: scan dict or None, never semantic certification."""
        from wqb.field_source_catalog import catalog_field_scan
        manifest = json.loads(self.fixture.manifest.read_text(encoding='utf-8'))
        return catalog_field_scan(self.source, [self.identity], manifest, **kwargs)

    def test_absent_optional_index_does_not_create_machine_files(self):
        self.assertIsNone(self.scan())
        self.assertFalse((self.root / 'machine').exists())

    def test_large_source_indexes_offsets_without_copying_full_payload(self):
        self.fixture.rows[0]['field']['description'] = 'x' * 900_000
        self.fixture.rows[1]['field']['description'] = 'y' * 900_000
        self.fixture.rows[2]['field']['description'] = 'z' * 900_000
        self.fixture.save()
        before = self.source.read_bytes()
        result = self.scan(create=True)
        self.assertEqual(result['original_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(result['original_rows'], 65)
        self.assertEqual(result['selected'][0]['row']['field']['id'], 'f032')
        databases = list((self.root / 'machine/field_catalogs').glob('*.sqlite3'))
        self.assertEqual(len(databases), 1)
        self.assertLess(databases[0].stat().st_size, len(before) // 4)
        self.assertEqual(self.source.read_bytes(), before)

    def test_index_hit_only_parses_requested_row_and_preserves_cache_bytes(self):
        self.scan(create=True)
        before = {p: p.read_bytes() for p in (self.root / 'machine').rglob('*') if p.is_file()}
        from wqb import knowledge_contracts
        with patch.object(knowledge_contracts, '_capture_json', wraps=knowledge_contracts._capture_json) as parse:
            result = self.scan()
        self.assertLessEqual(parse.call_count, 5, 'Pointer/manifest/metadata, one raw epoch witness and selected row only')
        self.assertEqual(result['selected'][0]['record_number'], 33)
        self.assertEqual(before, {p: p.read_bytes() for p in (self.root / 'machine').rglob('*') if p.is_file()})

    def test_exact_selection_uses_indexed_parameter_query_not_full_cursor(self):
        """Input: exact field query. Output: SQLite locates selected identities instead of visiting every field."""
        self.scan(create=True)
        statements = []
        connect = sqlite3.connect
        def traced(*args, **kwargs):
            """Input: SQLite connection arguments. Output: real connection with read-only query diagnostics."""
            connection = connect(*args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection
        with patch('wqb.field_source_catalog.sqlite3.connect', side_effect=traced):
            self.scan()
        selections = [sql for sql in statements if 'row_sha256' in sql]
        self.assertTrue(selections)
        self.assertTrue(all('WHERE identity IN' in sql for sql in selections))

    def test_changed_source_does_not_reuse_old_generation(self):
        previous = self.scan(create=True)
        self.fixture.rows[32]['field']['description'] = 'Changed'
        self.fixture.save()
        self.assertIsNone(self.scan())
        current = self.scan(create=True)
        self.assertNotEqual(previous['original_sha256'], current['original_sha256'])
        self.assertEqual(current['selected'][0]['row']['field']['description'], 'Changed')

    def test_corrupt_cache_falls_back_or_is_rebuilt_only_when_requested(self):
        expected = self.scan(create=True)
        database, = (self.root / 'machine/field_catalogs').glob('*.sqlite3')
        database.write_bytes(b'not a SQLite database')
        self.assertIsNone(self.scan())
        self.assertEqual(database.read_bytes(), b'not a SQLite database')
        recovered = self.scan(create=True)
        self.assertEqual(expected['selected'], recovered['selected'])

    def test_missing_exact_identity_cannot_be_reported_as_selected(self):
        self.scan(create=True)
        self.identity['scope'] = dict(self.fixture.scope, region='EUR')
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.scan()

    def test_duplicate_raw_identity_is_not_an_ambiguous_index(self):
        self.fixture.rows.append(self.fixture.rows[0])
        self.fixture.save()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.scan(create=True)
        self.assertFalse(list((self.root / 'machine/field_catalogs').glob('*.sqlite3')))

    def test_tampered_offsets_are_not_trusted_as_raw_facts(self):
        self.scan(create=True)
        database, = (self.root / 'machine/field_catalogs').glob('*.sqlite3')
        with sqlite3.connect(database) as connection:
            connection.execute('UPDATE fields SET offset = 0')
        self.assertIsNone(self.scan())

    def test_existing_extractor_uses_index_for_next_bounded_batch(self):
        """Input: two ordinary bounded extraction calls. Output: new prefix progress without reparsing old raw rows."""
        from wqb import field_source_catalog as catalog
        first = self.fixture.produce(max_batches=1, max_fields=30, resume_existing=True, use_catalog=True)
        with patch.object(catalog, '_row_identity', wraps=catalog._row_identity) as parse:
            second = self.fixture.produce(max_batches=1, max_fields=30, resume_existing=True, use_catalog=True)
        self.assertEqual(first['certified_fields'], 30)
        self.assertEqual(second['certified_fields'], 60)
        self.assertEqual(second['pending_rows'], 5)
        self.assertLessEqual(parse.call_count, 62, 'Revalidate prior 30 plus new 30 and bounded raw epoch witnesses')
        self.assertTrue(second['partial'])
        self.assertEqual(second['model_calls'], 0)

    def test_legacy_extract_receipts_are_identical_with_an_optional_index(self):
        """Input: default extraction before/after indexing. Output: byte-identical legacy receipts and plans."""
        first = self.fixture.produce(max_batches=3, max_fields=65)
        receipts = {self.root / row['receipt_path'] for row in first['extracts']}
        before = {p: p.read_bytes() for p in receipts}
        self.scan(create=True)
        second = self.fixture.produce(max_batches=3, max_fields=65)
        self.assertEqual(first, second)
        self.assertEqual(before, {p: p.read_bytes() for p in receipts})

    def test_cache_preserves_legacy_mixed_epoch_rejection(self):
        """Input: two valid scope epochs. Output: no single exact excerpt silently mixes their capture dates."""
        from wqb.field_source_catalog import catalog_field_scan
        rows = self.fixture.rows[:2]
        eur = dict(self.fixture.scope, region='EUR')
        rows[1].update(scope=eur, generated_at='2026-10-22T00:00:00Z', capture_generation_id='old')
        self.fixture.rows = rows
        self.fixture.save()
        manifest = json.loads(self.fixture.manifest.read_text())
        manifest['requested_matrix'] = [self.fixture.scope, eur]
        manifest['latest_scope_outcomes'] = [dict(scope=row['scope'], generated_at=row['generated_at'],
            capture_generation_id=row['capture_generation_id'], status='completed', certification_status='complete') for row in rows]
        self.fixture.manifest.write_text(json.dumps(manifest), encoding='utf-8')
        identities = [dict(dataset_id='prices', field_id=row['field']['id'], scope=row['scope']) for row in rows]
        with self.assertRaisesRegex(ValueError, 'mixed'):
            catalog_field_scan(self.source, identities, manifest, create=True)

    def test_index_flags_are_strict_before_build(self):
        for value in (1, 'yes', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.scan(create=value)
        self.assertFalse((self.root / 'machine').exists())

    def test_receipt_only_reads_recompute_raw_facts_even_if_pointer_is_forged(self):
        """Input: coordinated corrupted cache/derived checksum. Output: no forged proof from unchanged raw bytes."""
        self.scan(create=True)
        database, = (self.root / 'machine/field_catalogs').glob('*.sqlite3')
        pointer, = (self.root / 'machine/field_catalogs').glob('*.json')
        with sqlite3.connect(database) as connection:
            connection.execute('UPDATE fields SET content_sha256 = ?, captured_at = ?, generation_id = ?',
                ('0' * 64, '2026-10-21T00:00:00Z', 'forged'))
        receipt = json.loads(pointer.read_text(encoding='utf-8'))
        receipt['database_sha256'] = hashlib.sha256(database.read_bytes()).hexdigest()
        pointer.write_text(json.dumps(receipt), encoding='utf-8')
        self.assertIsNone(self.scan(receipts_only=True))

    def test_snapshot_read_never_uses_unbounded_read_bytes(self):
        """Input: a small source snapshot. Output: bounded reads, even if a later source stat could change."""
        read = Path.read_bytes
        def bounded(path):
            """Input: Path. Output: bytes for non-source fixtures; source unbounded reads are forbidden."""
            if path == self.source:
                raise AssertionError('unbounded source read')
            return read(path)
        with patch.object(Path, 'read_bytes', bounded):
            result = self.scan(create=True, receipts_only=True)
        self.assertEqual(result['original_rows'], 65)

    def test_cache_metadata_cannot_renew_original_capture_date(self):
        """Input: forged SQLite date plus matching pointer checksum. Output: optional cache miss, raw date unchanged."""
        self.scan(create=True)
        database, = (self.root / 'machine/field_catalogs').glob('*.sqlite3')
        pointer, = (self.root / 'machine/field_catalogs').glob('*.json')
        with sqlite3.connect(database) as connection:
            row = json.loads(connection.execute('SELECT value FROM metadata WHERE key = ?', ('catalog',)).fetchone()[0])
            row['original_captured_at'] = '2099-01-01T00:00:00Z'
            connection.execute('UPDATE metadata SET value = ? WHERE key = ?', (json.dumps(row), 'catalog'))
        receipt = json.loads(pointer.read_text(encoding='utf-8'))
        receipt['database_sha256'] = hashlib.sha256(database.read_bytes()).hexdigest()
        pointer.write_text(json.dumps(receipt), encoding='utf-8')
        self.assertIsNone(self.scan())

    def test_cache_ordinals_must_match_physical_raw_line_positions(self):
        """Input: forged SQL ordinals and checksum. Output: no cache-dependent line-number receipt."""
        self.scan(create=True)
        database, = (self.root / 'machine/field_catalogs').glob('*.sqlite3')
        pointer, = (self.root / 'machine/field_catalogs').glob('*.json')
        with sqlite3.connect(database) as connection:
            connection.execute('UPDATE fields SET ordinal = -ordinal')
            connection.execute('UPDATE fields SET ordinal = 66 + ordinal')
        receipt = json.loads(pointer.read_text(encoding='utf-8'))
        receipt['database_sha256'] = hashlib.sha256(database.read_bytes()).hexdigest()
        pointer.write_text(json.dumps(receipt), encoding='utf-8')
        self.identity['field_id'] = 'f064'
        self.assertIsNone(self.scan())

    def test_build_lock_and_guard_pass_through_checked_path_boundary(self):
        """Input: ordinary build. Output: explicit checks for both lock and link-sensitive guard."""
        from wqb import knowledge_contracts
        with patch.object(knowledge_contracts, '_source_contract_path', wraps=knowledge_contracts._source_contract_path) as checked:
            self.scan(create=True)
        paths = [str(call.args[1]).replace('\\', '/') for call in checked.call_args_list]
        self.assertIn('machine/field_catalogs/build.lock', paths)
        self.assertIn('machine/field_catalogs/build.lock.guard', paths)

