"""Offline contracts for a disposable, read-only-query ledger offset index."""

import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest


SUPPORTING_FILES = {'operator_ledger': 'operator_ledger.jsonl', 'template_library': 'template_library.jsonl',
                    'mechanism_evidence': 'mechanism_evidence.json', 'semantic_release': 'semantic_release.json'}


class ResearchQueryIndexTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: None; create isolated canonical machine fixtures."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.machine = self.root / 'machine'
        self.machine.mkdir()
        self.scope = dict(instrument_type='EQUITY', region='ALL', delay=1, universe='LARGE')
        self.other = dict(self.scope, region='USA')
        self.rows = [dict(dataset_id='sample', field_id=f'f{i:03}', field_type='VECTOR' if i % 2 else 'MATRIX',
                          available_scopes=[self.scope], field_description=f'Original signal {i}',
                          source_paths=['raw/platform/sample.json'], source_updated_at='2026-11-23',
                          units=None, vector_grain='unknown', coverage_status='measured_raw',
                          field_semantics_ref={'path': 'machine/semantic_jobs/example.json'})
                     for i in range(45)]
        self.rows.append(dict(self.rows[0], available_scopes=[self.other]))
        self.write_rows('data_ledger', self.rows)
        self.write_rows('source_index', [dict(path='raw/platform/sample.json', content_hash='a' * 64)])

    def write_rows(self, name, rows):
        """Input: resource str and list[dict]. Output: None; write temporary JSONL bytes."""
        (self.machine / (name + '.jsonl')).write_bytes(
            b''.join((json.dumps(row, ensure_ascii=False) + '\r\n').encode() for row in rows))

    def module(self):
        """Input: None. Output: module; assert the required implementation exists."""
        self.assertIsNotNone(importlib.util.find_spec('wqb.research_query_index'),
                             'Task1 query-index implementation is missing')
        return importlib.import_module('wqb.research_query_index')

    def prepare(self):
        """Input: fixture. Output: tuple[module, dict] for explicit preparation."""
        module = self.module()
        return module, module.prepare_query_index(self.root)

    def snapshot(self):
        """Input: fixture. Output: dict of all bytes; detect query writes or implicit repair."""
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def test_exact_scope_pagination_beyond_shortlist_and_original_metadata(self):
        """Input: 45-field fixture. Output: None; assert complete pagination and unchanged provenance."""
        module, manifest = self.prepare()
        self.assertEqual(set(manifest), {'schema_version', 'generation', 'index_path', 'index_sha256',
                                         'ledger_sha256', 'source_index_sha256', 'supporting_sha256', 'inputs', 'row_count'})
        self.assertEqual(manifest['ledger_sha256'], hashlib.sha256(
            (self.machine / 'data_ledger.jsonl').read_bytes()).hexdigest())
        before = self.snapshot()
        page = module.query_fields(self.root, manifest['generation'], self.scope)
        self.assertEqual(set(page), {'generation', 'scope', 'query', 'field_type', 'offset', 'limit',
                                     'total', 'next_offset', 'items'})
        self.assertEqual(page['total'], 45)
        self.assertEqual(len(page['items']), 20)
        self.assertEqual(page['next_offset'], 20)
        page2 = module.query_fields(self.root, manifest['generation'], self.scope, offset=40)
        self.assertEqual([r['field_id'] for r in page2['items']], [f'f{i:03}' for i in range(40, 45)])
        self.assertIsNone(page2['next_offset'])
        selected = page2['items'][0]
        for key in ('source_paths', 'source_updated_at', 'field_description', 'units', 'vector_grain',
                    'field_semantics_ref'):
            self.assertEqual(selected[key], self.rows[40][key])
        self.assertEqual(selected['scope'], self.scope)
        self.assertEqual(len(selected['row_sha256']), 64)
        self.assertEqual(module.validate_query_generation(self.root, manifest['generation']), manifest)
        self.assertEqual(self.snapshot(), before)

    def test_search_type_and_literal_sql_metacharacters(self):
        """Input: prepared fixture. Output: None; assert literal search and independent type filtering."""
        module, manifest = self.prepare()
        result = module.query_fields(self.root, manifest['generation'], self.scope,
                                     query='SIGNAL 41', field_type='VECTOR')
        self.assertEqual([r['field_id'] for r in result['items']], ['f041'])
        for query in ('%', '_', "' OR 1=1 --"):
            self.assertEqual(module.query_fields(self.root, manifest['generation'], self.scope,
                                                query=query)['items'], [])

    def test_selected_rows_keep_unknowns_order_and_exact_scope(self):
        """Input: prepared fixture. Output: None; assert exact canonical materialization and selector rejection."""
        module, manifest = self.prepare()
        self.assertEqual(module.read_field_rows(self.root, manifest['generation'], self.scope,
                                               [('sample', 'f041'), ('sample', 'f000')]),
                         [self.rows[41], self.rows[0]])
        self.assertEqual(module.read_field_rows(self.root, manifest['generation'], self.other,
                                               [('sample', 'f000')]), [self.rows[-1]])
        for identities in ([('sample', 'missing')], [('sample', 'f000'), ('sample', 'f000')]):
            with self.assertRaises(ValueError):
                module.read_field_rows(self.root, manifest['generation'], self.scope, identities)

    def test_duplicate_same_scope_rejected_even_identical_or_overlapping_scopes(self):
        """Input: ambiguous fixture variants. Output: None; assert no duplicate can shadow an original."""
        module = self.module()
        for duplicate in (self.rows[0], dict(self.rows[0], field_type='VECTOR'),
                          dict(self.rows[0], available_scopes=[self.other, self.scope])):
            self.write_rows('data_ledger', self.rows + [duplicate])
            with self.assertRaisesRegex(ValueError, 'duplicate|ambiguous'):
                module.prepare_query_index(self.root)

    def test_generation_rejects_changes_to_either_input_and_wrong_generation(self):
        """Input: mutated canonical inputs. Output: None; assert every read fails closed without writing."""
        module, manifest = self.prepare()
        with self.assertRaises(ValueError):
            module.query_fields(self.root, '0' * 64, self.scope)
        for name in ('data_ledger', 'source_index'):
            path = self.machine / (name + '.jsonl')
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            before = self.snapshot()
            for operation in (
                lambda: module.validate_query_generation(self.root, manifest['generation']),
                lambda: module.query_fields(self.root, manifest['generation'], self.scope),
                lambda: module.read_field_rows(self.root, manifest['generation'], self.scope, []),
            ):
                with self.assertRaisesRegex(ValueError, 'generation|prepar'):
                    operation()
            self.assertEqual(self.snapshot(), before)
            path.write_bytes(original)
            manifest = module.prepare_query_index(self.root)

    def test_explicit_rebuild_and_content_bound_generation(self):
        """Input: stable then changed fixture. Output: None; assert deterministic and input-bound generations."""
        module, first = self.prepare()
        second = module.prepare_query_index(self.root)
        self.assertEqual(first['generation'], second['generation'])
        self.rows[0]['field_description'] = 'changed'
        self.write_rows('data_ledger', self.rows)
        third = module.prepare_query_index(self.root)
        self.assertNotEqual(first['generation'], third['generation'])
        with self.assertRaises(ValueError):
            module.read_field_rows(self.root, first['generation'], self.scope, [('sample', 'f000')])

    def test_missing_and_corrupt_index_are_read_only_errors_until_explicit_prepare(self):
        """Input: absent/corrupt cache. Output: None; assert only explicit prepare repairs it."""
        module = self.module()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            module.query_fields(self.root, '0' * 64, self.scope)
        self.assertEqual(before, self.snapshot())
        manifest = module.prepare_query_index(self.root)
        path = self.root / manifest['index_path']
        path.write_bytes(b'not sqlite')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            module.query_fields(self.root, manifest['generation'], self.scope)
        self.assertEqual(before, self.snapshot())
        repaired = module.prepare_query_index(self.root)
        self.assertEqual(module.query_fields(self.root, repaired['generation'], self.scope)['total'], 45)

    def test_warm_reads_never_scan_full_ledger(self):
        """Input: guarded ledger stream. Output: None; assert all warm APIs use only bounded row reads."""
        module, manifest = self.prepare()
        original = Path.open
        ledger = self.machine / 'data_ledger.jsonl'

        def guarded(path, *args, **kwargs):
            """Input: Path/open args. Output: stream; forbid ledger traversal except bounded selected reads."""
            stream = original(path, *args, **kwargs)
            if path == ledger:
                class SelectedOnly:
                    def __enter__(self):
                        """Input: self. Output: selected-reader wrapper."""
                        return self

                    def __exit__(self, *exc):
                        """Input: exception tuple. Output: None; close underlying stream."""
                        stream.close()

                    def seek(self, offset):
                        """Input: integer offset. Output: int stream position."""
                        return stream.seek(offset)

                    def read(self, size=-1):
                        """Input: int size. Output: bytes; require one bounded row read."""
                        self_test.assertGreater(size, 0)
                        self_test.assertLessEqual(size, module.MAX_LINE_BYTES)
                        return stream.read(size)

                return SelectedOnly()
            return stream

        self_test = self
        Path.open = guarded
        try:
            module.validate_query_generation(self.root, manifest['generation'])
            self.assertEqual(module.query_fields(self.root, manifest['generation'], self.scope,
                                                query='signal 41')['items'][0]['field_id'], 'f041')
            self.assertEqual(module.read_field_rows(self.root, manifest['generation'], self.scope,
                                                   [('sample', 'f041')]), [self.rows[41]])
        finally:
            Path.open = original

    def test_row_hash_rechecked_not_just_cached_locator(self):
        """Input: tampered row and unchanged stat witness. Output: None; assert independent row-hash validation."""
        module, manifest = self.prepare()
        path = self.machine / 'data_ledger.jsonl'
        before = path.stat()
        path.write_bytes(path.read_bytes().replace(b'Original signal 0', b'Tampered signal 0'))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        # Bypass file identity checks specifically to exercise selected-row hashing.
        original_identity = module._file_identity

        def unchanged_identity(path):
            """Input: Path. Output: dict; simulate an undetected ledger stat change only."""
            return manifest['inputs']['data_ledger'] if path == self.machine / 'data_ledger.jsonl' else original_identity(path)

        module._file_identity = unchanged_identity
        try:
            with self.assertRaises(ValueError):
                module.read_field_rows(self.root, manifest['generation'], self.scope, [('sample', 'f000')])
        finally:
            module._file_identity = original_identity

    def test_sql_contains_offsets_not_a_second_ledger(self):
        """Input: generated SQL cache. Output: None; assert locator/search-only schema."""
        _, manifest = self.prepare()
        connection = sqlite3.connect(self.root / manifest['index_path'])
        try:
            columns = {row[1] for row in connection.execute('PRAGMA table_info(fields)')}
            self.assertEqual(columns, {'scope', 'dataset_id', 'field_id', 'field_type', 'search_text',
                                       'offset', 'length', 'row_sha256'})
        finally:
            connection.close()

    def test_invalid_scope_and_bounds_reject_without_writes(self):
        """Input: invalid selectors/pages. Output: None; assert validation is read-only and strict."""
        module, manifest = self.prepare()
        before = self.snapshot()
        for kwargs in ({'offset': -1}, {'offset': True}, {'limit': 0}, {'limit': True},
                       {'limit': module.MAX_PAGE_SIZE + 1}, {'query': None}, {'field_type': []}):
            with self.assertRaises(ValueError):
                module.query_fields(self.root, manifest['generation'], self.scope, **kwargs)
        with self.assertRaises(ValueError):
            module.query_fields(self.root, manifest['generation'], dict(self.scope, delay=True))
        self.assertEqual(before, self.snapshot())

    def test_scope_as_of_is_validated_preserved_and_not_a_geographic_selector(self):
        """Input: exact scope with aware timestamps. Output: None; assert authority metadata survives queries."""
        module, manifest = self.prepare()
        before = self.snapshot()
        for timestamp in ('2026-11-24T10:30:00Z', '2026-11-24T18:30:00+08:00'):
            scope = dict(self.scope, as_of=timestamp)
            page = module.query_fields(self.root, manifest['generation'], scope, query='signal 41')
            self.assertEqual(page['scope'], scope)
            self.assertEqual(page['items'][0]['scope'], scope)
            self.assertEqual(page['total'], 1)
            self.assertEqual(module.read_field_rows(self.root, manifest['generation'], scope,
                                                   [('sample', 'f041')]), [self.rows[41]])
            self.assertEqual(scope['as_of'], timestamp)
        self.assertEqual(before, self.snapshot())

    def test_scope_rejects_invalid_as_of_and_arbitrary_extra_keys(self):
        """Input: malformed temporal/extra scope metadata. Output: None; assert no authority key is discarded."""
        module, manifest = self.prepare()
        before = self.snapshot()
        scopes = [dict(self.scope, as_of=value)
                  for value in (None, True, 123, '', 'not-a-date', '2026-11-24', '2026-11-24T10:30:00')]
        scopes += [dict(self.scope, authority='unapproved'),
                   dict(self.scope, as_of='2026-11-24T10:30:00Z', authorization='unapproved')]
        for scope in scopes:
            with self.subTest(scope=scope):
                with self.assertRaises(ValueError):
                    module.query_fields(self.root, manifest['generation'], scope)
                with self.assertRaises(ValueError):
                    module.read_field_rows(self.root, manifest['generation'], scope, [('sample', 'f000')])
        self.assertEqual(before, self.snapshot())

    def test_warm_prepare_keeps_all_file_identities_and_hashes_unchanged(self):
        """Input: prepared fixture. Output: None; assert repeat preparation reuses bytes and original files."""
        module, manifest = self.prepare()
        before = self.snapshot()
        identities = {p.relative_to(self.root).as_posix(): module._file_identity(p)
                      for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(module.prepare_query_index(self.root), manifest)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(identities, {p.relative_to(self.root).as_posix(): module._file_identity(p)
                                     for p in self.root.rglob('*') if p.is_file()})

    def test_warm_prepare_never_reopens_canonical_inputs(self):
        """Input: prepared fixture with forbidden input opens. Output: None; assert cache-only reuse."""
        module, manifest = self.prepare()
        original = Path.open

        def guarded(path, *args, **kwargs):
            """Input: Path/open arguments. Output: stream; reject full input reads during warm preparation."""
            self.assertNotIn(path, [self.machine / 'data_ledger.jsonl', self.machine / 'source_index.jsonl'])
            return original(path, *args, **kwargs)

        Path.open = guarded
        try:
            self.assertEqual(module.prepare_query_index(self.root), manifest)
        finally:
            Path.open = original

    def test_changed_inputs_replace_one_active_database_without_accumulating_generations(self):
        """Input: successive canonical input generations. Output: None; assert a single replaceable SQL cache."""
        module, manifest = self.prepare()
        catalog = self.machine / 'field_catalogs'
        expected = catalog / 'research-query.sqlite3'
        self.assertEqual(self.root / manifest['index_path'], expected)
        for revision in range(3):
            old_generation = manifest['generation']
            self.write_rows('source_index', [dict(path='raw/platform/sample.json', revision=revision)])
            manifest = module.prepare_query_index(self.root)
            self.assertNotEqual(old_generation, manifest['generation'])
            self.assertEqual(self.root / manifest['index_path'], expected)
            self.assertEqual(set(catalog.glob('*.sqlite3')), {expected})
            self.assertFalse(list(catalog.glob('.query-*')))
            with self.assertRaises(ValueError):
                module.validate_query_generation(self.root, old_generation)
            self.assertEqual(module.query_fields(self.root, manifest['generation'], self.scope)['total'], 45)

    def test_interrupted_slot_publication_keeps_old_receipt_and_fails_closed(self):
        """Input: failure after SQL replacement but before receipt publication. Output: None; assert no stale reads."""
        module, first = self.prepare()
        pointer = self.root / module.POINTER_PATH
        old_receipt = pointer.read_bytes()
        self.write_rows('source_index', [dict(path='raw/platform/sample.json', revision='next')])
        original = os.replace

        def interrupt(source, destination):
            """Input: source/destination Paths. Output: None; simulate failure only when publishing the receipt."""
            if destination == pointer:
                raise OSError('simulated receipt publication interruption')
            return original(source, destination)

        os.replace = interrupt
        try:
            with self.assertRaisesRegex(OSError, 'simulated'):
                module.prepare_query_index(self.root)
        finally:
            os.replace = original
        self.assertEqual(pointer.read_bytes(), old_receipt)
        slot = self.machine / 'field_catalogs/research-query.sqlite3'
        self.assertTrue(slot.is_file())
        self.assertNotEqual(hashlib.sha256(slot.read_bytes()).hexdigest(), first['index_sha256'])
        before = self.snapshot()
        with self.assertRaises(ValueError):
            module.validate_query_generation(self.root, first['generation'])
        with self.assertRaises(ValueError):
            module.query_fields(self.root, first['generation'], self.scope)
        with self.assertRaises(ValueError):
            module.read_field_rows(self.root, first['generation'], self.scope, [('sample', 'f000')])
        self.assertEqual(before, self.snapshot())
        recovered = module.prepare_query_index(self.root)
        self.assertNotEqual(recovered['generation'], first['generation'])
        self.assertEqual(set(slot.parent.glob('*.sqlite3')), {slot})
        self.assertEqual(module.query_fields(self.root, recovered['generation'], self.scope)['total'], 45)

    def test_prepare_preserves_existing_generation_named_cache_for_separate_cleanup(self):
        """Input: historical generation-named SQL fixture/receipt. Output: None; assert migration never deletes it."""
        module, first = self.prepare()
        historical = self.machine / 'field_catalogs' / ('research-query-' + first['generation'] + '.sqlite3')
        historical.write_bytes((self.root / first['index_path']).read_bytes())
        legacy_manifest = dict(first, index_path=historical.relative_to(self.root).as_posix())
        (self.root / module.POINTER_PATH).write_text(json.dumps(legacy_manifest), encoding='utf-8')
        before = historical.read_bytes()
        identity = module._file_identity(historical)
        current = module.prepare_query_index(self.root)
        self.assertEqual(current['index_path'], 'machine/field_catalogs/research-query.sqlite3')
        self.assertEqual(historical.read_bytes(), before)
        self.assertEqual(module._file_identity(historical), identity)

    def test_missing_optional_resources_remain_valid_and_explicitly_none(self):
        """Input: fixture without templates/operators/history/release. Output: None; assert no new knowledge gate."""
        module, manifest = self.prepare()
        self.assertEqual(manifest['supporting_sha256'], dict.fromkeys(SUPPORTING_FILES))
        self.assertEqual(set(manifest['inputs']), {'data_ledger', 'source_index', *SUPPORTING_FILES})
        for name in SUPPORTING_FILES:
            self.assertIsNone(manifest['inputs'][name])
        self.assertEqual(module.validate_query_generation(self.root, manifest['generation']), manifest)
        self.assertEqual(module.query_fields(self.root, manifest['generation'], self.scope)['total'], 45)

    def test_optional_resource_appearance_mutation_and_removal_invalidate_generation(self):
        """Input: optional-resource lifecycle with stable IDs. Output: None; assert exact-view generation binding."""
        module, manifest = self.prepare()
        ledger = (self.machine / 'data_ledger.jsonl').read_bytes()
        for name, filename in SUPPORTING_FILES.items():
            path = self.machine / filename
            for stage in ('appearance', 'mutation', 'removal'):
                with self.subTest(resource=name, stage=stage):
                    old_generation = manifest['generation']
                    if stage == 'removal':
                        path.unlink()
                    else:
                        path.write_text(json.dumps(dict(id='same', description=stage)), encoding='utf-8')
                    before = self.snapshot()
                    with self.assertRaises(ValueError):
                        module.validate_query_generation(self.root, old_generation)
                    with self.assertRaises(ValueError):
                        module.query_fields(self.root, old_generation, self.scope)
                    with self.assertRaises(ValueError):
                        module.read_field_rows(self.root, old_generation, self.scope, [('sample', 'f000')])
                    self.assertEqual(self.snapshot(), before)
                    manifest = module.prepare_query_index(self.root)
                    self.assertNotEqual(manifest['generation'], old_generation)
                    if stage == 'removal':
                        self.assertIsNone(manifest['inputs'][name])
                        self.assertIsNone(manifest['supporting_sha256'][name])
                    else:
                        self.assertEqual(manifest['supporting_sha256'][name],
                                         hashlib.sha256(path.read_bytes()).hexdigest())
                        self.assertEqual(manifest['inputs'][name], module._file_identity(path))
                    self.assertEqual(module.validate_query_generation(self.root, manifest['generation']), manifest)
                    self.assertEqual(set((self.machine / 'field_catalogs').glob('*.sqlite3')),
                                     {self.root / manifest['index_path']})
        self.assertEqual((self.machine / 'data_ledger.jsonl').read_bytes(), ledger)

    def test_supporting_hashes_are_prepared_once_and_warm_operations_only_stat_resources(self):
        """Input: all optional resources and guarded reads. Output: None; assert one cold hash and no warm rereads."""
        module = self.module()
        paths = {self.machine / filename for filename in SUPPORTING_FILES.values()}
        for path in paths:
            path.write_text('{}\n', encoding='utf-8')
        original_hash, original_open = module._hash_file, Path.open
        counts = dict.fromkeys(paths, 0)

        def observed_hash(path):
            """Input: Path. Output: SHA256 str; count full supporting hashes without changing the implementation."""
            if path in counts:
                counts[path] += 1
            return original_hash(path)

        def guarded_open(path, *args, **kwargs):
            """Input: Path/open args. Output: stream; forbid supporting/source-index reads during warm operations."""
            self.assertNotIn(path, paths | {self.machine / 'source_index.jsonl'})
            return original_open(path, *args, **kwargs)

        module._hash_file = observed_hash
        try:
            manifest = module.prepare_query_index(self.root)
            before = self.snapshot()
            Path.open = guarded_open
            try:
                self.assertEqual(module.validate_query_generation(self.root, manifest['generation']), manifest)
                module.query_fields(self.root, manifest['generation'], self.scope)
                module.read_field_rows(self.root, manifest['generation'], self.scope, [('sample', 'f000')])
                self.assertEqual(module.prepare_query_index(self.root), manifest)
            finally:
                Path.open = original_open
            self.assertEqual(counts, dict.fromkeys(paths, 1))
            self.assertEqual(self.snapshot(), before)
        finally:
            module._hash_file = original_hash

    def test_strict_manifest_rejects_unknown_or_missing_supporting_hash_keys(self):
        """Input: self-consistent but malformed receipt maps. Output: None; assert exact supporting schema."""
        module, manifest = self.prepare()
        for hashes in ({}, dict.fromkeys(SUPPORTING_FILES, None) | {'other': None}):
            invalid = dict(manifest, supporting_sha256=hashes)
            invalid['generation'] = module._generation(invalid)
            (self.root / module.POINTER_PATH).write_text(json.dumps(invalid), encoding='utf-8')
            with self.assertRaises(ValueError):
                module.validate_query_generation(self.root, invalid['generation'])


if __name__ == '__main__':
    unittest.main()
