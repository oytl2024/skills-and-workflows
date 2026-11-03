"""Bounded bulk extraction tests; temporary captures only, no actual vault."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb import knowledge_contracts as contracts


class BulkFieldExtractTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated capture root and deterministic JSONL fixture."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.relative = 'raw/platform/data_fields/2026-10-23/data_fields.jsonl'
        self.source = self.root / self.relative
        self.source.parent.mkdir(parents=True)
        self.scope = dict(region='USA', delay=1, universe='TOP3000', instrument_type='EQUITY')
        self.rows = [dict(field=dict(id='f%03d' % i, type='MATRIX', description='Literal', coverage=0.8),
                          data_set=dict(id='prices'), scope=self.scope,
                          generated_at='2026-10-23T00:00:00Z', capture_generation_id='fixture',
                          endpoint='/data-fields') for i in range(65)]
        self.save()

    def save(self):
        """Input: fixture state. Output: None; serialize capture and matching partial manifest."""
        self.source.write_text(''.join(json.dumps(row) + '\n' for row in self.rows), encoding='utf-8')
        self.manifest = self.source.with_name('manifest.json')
        self.manifest.write_text(json.dumps(dict(generated_at=self.rows[0]['generated_at'],
            capture_generation_id='fixture', scope=self.scope, certification_status='partial',
            field_count=len(self.rows), error_count=1)), encoding='utf-8')

    def produce(self, **kwargs):
        """Input: finite producer keyword options. Output: bulk extraction result dict."""
        return contracts.extract_field_source_batches(self.root, [self.relative], **kwargs)

    def test_batch_schema_resume_and_exact_constant_original_reads(self):
        reads = []
        original_open = Path.open

        def counted(path, *args, **kwargs):
            """Input: Path/open arguments. Output: real file, recording original read opens."""
            if path == self.source and (not args or 'r' in args[0]):
                reads.append(path)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, 'open', counted):
            result = self.produce(max_batches=3, max_fields=65)
        self.assertEqual(len(reads), 2)
        self.assertEqual(result['selected_fields'], 65)
        self.assertEqual(result['pending_rows'], 0)
        self.assertEqual([r['selected_rows'] for r in result['extracts']], [30, 30, 5])
        for row in result['extracts']:
            self.assertLessEqual((self.root / row['excerpt_path']).stat().st_size, 512_000)
            proof = contracts.verify_field_source_extract(self.root, row['excerpt_path'])
            self.assertTrue(proof['partial'])
            self.assertEqual(proof['captured_at'], self.rows[0]['generated_at'])
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        replay = self.produce(max_batches=3, max_fields=65)
        self.assertEqual(replay['extracts'], result['extracts'])
        self.assertTrue(all(p.read_bytes() == raw for p, raw in before.items()))

    def test_finite_limits_and_byte_splitting_do_not_promote_coverage(self):
        self.rows = self.rows[:3]
        for row in self.rows:
            row['field']['description'] = 'x' * 300_000
        self.save()
        result = self.produce(max_batches=2, max_fields=3)
        self.assertEqual(len(result['extracts']), 2)
        self.assertEqual(result['selected_fields'], 2)
        self.assertEqual(result['pending_rows'], 1)
        self.assertTrue(result['partial'])
        self.assertEqual(result['model_calls'], 0)

    def test_invalid_capture_and_conflicting_index_fail_before_registration(self):
        self.rows[-1]['capture_generation_id'] = 'wrong'
        self.save()
        with self.assertRaises(ValueError):
            self.produce(max_batches=3, max_fields=65)
        self.assertFalse((self.root / 'machine/source_index.jsonl').exists())
        self.rows[-1]['capture_generation_id'] = 'fixture'
        self.save()
        result = self.produce(max_batches=3, max_fields=65)
        index = self.root / 'machine/source_index.jsonl'
        rows = [json.loads(line) for line in index.read_text(encoding='utf-8').splitlines()]
        rows[0]['content_hash'] = '0' * 64
        index.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        before = index.read_bytes()
        with self.assertRaisesRegex(ValueError, 'conflict|mismatch'):
            self.produce(max_batches=3, max_fields=65)
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(len(result['extracts']), 3)

    def test_final_digest_catches_restored_stat_mutation(self):
        scan = contracts._scan_field_source

        def mutate(*args, **kwargs):
            """Input: scan arguments. Output: actual scan, followed by stat-preserving source corruption."""
            result = scan(*args, **kwargs)
            raw, stat = self.source.read_bytes(), self.source.stat()
            self.source.write_bytes(raw.replace(b'Literal', b'Changed', 1))
            os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            return result

        with patch.object(contracts, '_scan_field_source', mutate):
            with self.assertRaisesRegex(ValueError, 'changed|mutat'):
                self.produce(max_batches=3, max_fields=65)

    def test_final_digest_detects_mutation_during_artifact_writes(self):
        write = contracts._write_immutable_source
        mutated = []

        def mutate(path, content):
            """Input: immutable artifact Path/bytes. Output: None, with a late fixture-only source mutation."""
            write(path, content)
            if not mutated:
                raw, stat = self.source.read_bytes(), self.source.stat()
                self.source.write_bytes(raw.replace(b'Literal', b'Changed', 1))
                os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                mutated.append(True)

        with patch.object(contracts, '_write_immutable_source', mutate):
            with self.assertRaisesRegex(ValueError, 'changed|mutat'):
                self.produce(max_batches=3, max_fields=65)

    def test_resume_after_partial_index_write_keeps_receipt_bytes(self):
        update = contracts._upsert_source_index_rows_unlocked

        def interrupt(*args, **kwargs):
            """Input: index update arguments. Output: simulated crash after durable machine/human index write."""
            update(*args, **kwargs)
            raise RuntimeError('fixture interruption')

        with patch.object(contracts, '_upsert_source_index_rows_unlocked', interrupt):
            with self.assertRaisesRegex(RuntimeError, 'interruption'):
                self.produce(max_batches=3, max_fields=65)
        before = {p: p.read_bytes() for p in (self.root / 'machine/semantic_jobs').rglob('field_source_extract.json')}
        result = self.produce(max_batches=3, max_fields=65)
        self.assertEqual(result['selected_fields'], 65)
        self.assertTrue(all(p.read_bytes() == raw for p, raw in before.items()))

    def test_large_original_is_streamed_without_whole_file_reads(self):
        self.rows = self.rows[:1]
        self.save()
        padding = dict(self.rows[0], field=dict(id='unselected', description='x' * 990_000))
        chunk = (json.dumps(padding) + '\n').encode('utf-8')
        with self.source.open('ab') as stream:
            for _ in range(205):
                stream.write(chunk)
        self.assertGreater(self.source.stat().st_size, 200_000_000)
        read_bytes, open_path, reads = Path.read_bytes, Path.open, []

        def bounded(path):
            """Input: Path. Output: small file bytes; disallow whole-original reads."""
            if path == self.source:
                raise AssertionError('whole original read forbidden')
            return read_bytes(path)

        def counted(path, *args, **kwargs):
            """Input: Path/open arguments. Output: real stream with exact original read counts."""
            if path == self.source:
                reads.append(path)
            return open_path(path, *args, **kwargs)

        with patch.object(Path, 'read_bytes', bounded), patch.object(Path, 'open', counted):
            result = self.produce(max_batches=1, max_fields=1)
        self.assertEqual(result['selected_fields'], 1)
        self.assertEqual(result['pending_rows'], 205)
        self.assertEqual(len(reads), 2)

    def test_invalid_limits_rejected_without_writes(self):
        for value in [0, -1, True, 1.5, '3']:
            for name in ['max_batches', 'max_fields']:
                with self.assertRaises(ValueError):
                    self.produce(**{name: value})
        self.assertFalse((self.root / 'machine').exists())

    def test_small_batch_reuses_preexisting_single_extract_without_original_rescan(self):
        """Input: independent late-field excerpt plus bounded prefix. Output: shared proof, two original reads."""
        single = contracts.extract_field_source_subset(self.root, self.relative,
            [dict(dataset_id='prices', field_id='f064', scope=self.scope)])
        reads, open_path = [], Path.open

        def counted(path, *args, **kwargs):
            """Input: Path/open arguments. Output: real stream counting only original reads."""
            if path == self.source:
                reads.append(path)
            return open_path(path, *args, **kwargs)

        with patch.object(Path, 'open', counted):
            result = self.produce(max_batches=1, max_fields=30, _defer_finalize=True)
            session = result['_verification_session']
            self.assertEqual(session.proof(single['excerpt_path'])['status'], 'verified')
            session.finalize()
        self.assertEqual(len(reads), 2)

    def test_exact_missing_identity_plan_extends_prefix_without_rewriting_prior_extract(self):
        """Input: successive finite exact-identity plans. Output: independent batches and preserved first receipt."""
        first = self.produce(max_batches=1, max_fields=30)
        receipt = self.root / first['extracts'][0]['receipt_path']
        before = receipt.read_bytes()
        identities = [dict(dataset_id='prices', field_id=row['field']['id'], scope=self.scope) for row in self.rows[30:60]]
        second = self.produce(max_batches=1, max_fields=30, identities_by_source={self.relative: identities})
        self.assertEqual(second['selected_fields'], 30)
        self.assertNotEqual(second['extracts'][0]['excerpt_path'], first['extracts'][0]['excerpt_path'])
        self.assertEqual(second['mappings'][0]['identities'], identities)
        self.assertEqual(receipt.read_bytes(), before)

    def test_oversized_plan_cannot_accumulate_an_entire_large_original(self):
        """Input: excessive finite batch/field limits. Output: rejection before any source writes."""
        for config in [dict(max_batches=10_000), dict(max_fields=100_000)]:
            with self.assertRaises(ValueError):
                self.produce(**config)
        self.assertFalse((self.root / 'machine').exists())

    def test_multiple_small_originals_share_one_snapshot_byte_bound(self):
        """Input: three captures each below per-file snapshot limit. Output: bounded aggregate retained originals."""
        paths = []
        for day in (23, 24, 25):
            self.relative = 'raw/platform/data_fields/2026-10-%d/data_fields.jsonl' % day
            self.source = self.root / self.relative
            self.source.parent.mkdir(parents=True, exist_ok=True)
            self.rows = self.rows[:3]
            for row in self.rows:
                row['generated_at'] = '2026-10-%dT00:00:00Z' % day
            for row in self.rows[1:]:
                row['field']['description'] = 'x' * 750_000
            self.save()
            paths.append(self.relative)
        result = contracts.extract_field_source_batches(self.root, paths,
            max_batches=1, max_fields=1, _defer_finalize=True)
        session = result['_verification_session']
        retained = sum(len(scan.get('source_bytes') or b'') for scan in session._originals.values())
        self.assertLessEqual(retained, 2_000_000)
        session.finalize()

    def test_too_many_sources_rejected_before_capture_reads(self):
        """Input: oversized source list. Output: finite-bound error before reading or publishing evidence."""
        with self.assertRaisesRegex(ValueError, 'finite bulk source bound'):
            contracts.extract_field_source_batches(self.root,
                [self.relative] * (contracts.MAX_BULK_FIELD_SOURCES + 1), max_batches=1, max_fields=1)
        self.assertFalse((self.root / 'machine').exists())


if __name__ == '__main__':
    unittest.main()
