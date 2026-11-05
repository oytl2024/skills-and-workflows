import concurrent.futures
import gzip
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from wqb import semantic_inventory_archive as archive


class InventoryArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / ('machine/semantic_jobs/' + 'a' * 64 + '/inventory.jsonl')
        self.source.parent.mkdir(parents=True)
        self.raw = b'{"row":1}\r\n\xff\x00\n' * 1000
        self.source.write_bytes(self.raw)
        self.sha = hashlib.sha256(self.raw).hexdigest()

    def prepare(self):
        return archive.prepare_inventory_archive(self.root, self.source.relative_to(self.root).as_posix(), self.sha)

    def test_lossless_deterministic_idempotent_and_reader(self):
        ref = self.prepare()
        self.assertEqual(set(ref), {'path', 'sha256', 'uncompressed_sha256', 'uncompressed_bytes'})
        target = self.root / ref['path']
        before = target.stat()
        self.assertEqual(target.read_bytes()[:10], b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff')
        self.assertEqual(ref, self.prepare())
        self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(archive.verify_inventory_archive(self.root, ref), ref)
        with archive.open_verified_inventory_archive(self.root, ref) as reader:
            self.assertEqual(reader.read(), self.raw)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_invalid_refs_and_exact_size(self):
        ref = self.prepare()
        for change in ({'path': '../inventory.jsonl'}, {'path': ref['path'].replace('/', '\\')},
                       {'sha256': '0' * 64}, {'uncompressed_sha256': '0' * 64},
                       {'uncompressed_bytes': len(self.raw) - 1}, {'uncompressed_bytes': len(self.raw) + 1},
                       {'uncompressed_bytes': True}, {'pointer': ref['path']}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                archive.verify_inventory_archive(self.root, dict(ref, **change))

    def test_corrupt_existing_never_repaired(self):
        ref = self.prepare()
        target = self.root / ref['path']
        target.write_bytes(b'corrupted')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(target.read_bytes(), b'corrupted')

    def test_bounds_and_bomb(self):
        ref = self.prepare()
        with patch.object(archive, 'MAX_UNCOMPRESSED_BYTES', 10):
            with self.assertRaises(ValueError):
                self.prepare()
            with self.assertRaises(ValueError):
                archive.verify_inventory_archive(self.root, ref)
        target = self.root / ref['path']
        buffer = io.BytesIO()
        with gzip.GzipFile(filename='', fileobj=buffer, mode='wb', mtime=0) as writer:
            writer.write(b'x' * 1000000)
        target.write_bytes(buffer.getvalue())
        ref['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
        ref['uncompressed_bytes'] = 1
        with self.assertRaises(ValueError):
            archive.verify_inventory_archive(self.root, ref)

    def test_bad_timeouts_and_source_namespace(self):
        for value in (True, 0, -1, float('nan'), float('inf'), '10'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                archive.prepare_inventory_archive(self.root, self.source.relative_to(self.root).as_posix(), self.sha, timeout_seconds=value)
        for path in ('machine/semantic_jobs/short/inventory.jsonl', str(self.source),
                     'machine/semantic_jobs/' + 'a' * 64 + '/../inventory.jsonl'):
            with self.assertRaises(ValueError):
                archive.prepare_inventory_archive(self.root, path, self.sha)

    def test_concurrent_publication(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            refs = list(pool.map(lambda _: self.prepare(), range(8)))
        self.assertTrue(all(ref == refs[0] for ref in refs))
        self.assertEqual(len(list((self.root / 'machine/semantic_inventories').rglob('*.gz'))), 1)

    def test_source_changes_and_interruption_cleanup(self):
        original = archive.gzip.GzipFile.write

        def changed(handle, data):
            result = original(handle, data)
            self.source.write_bytes(b'changed')
            return result

        with patch.object(archive.gzip.GzipFile, 'write', changed), self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(list(self.root.rglob('*.gz')))
        self.source.write_bytes(self.raw)
        with patch.object(archive.gzip.GzipFile, 'write', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.prepare()
        self.assertFalse(list(self.root.rglob('*.tmp')))
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_hardlinks_and_unsafe_targets(self):
        alias = self.source.with_name('alias')
        os.link(self.source, alias)
        with self.assertRaises(ValueError):
            self.prepare()
        alias.unlink()
        base = self.root / 'machine/semantic_inventories'
        base.write_bytes(b'not a directory')
        with self.assertRaises((ValueError, OSError)):
            self.prepare()

    def test_cross_process_publication(self):
        code = ('import sys; from pathlib import Path; '
                'from wqb.semantic_inventory_archive import prepare_inventory_archive; '
                'print(prepare_inventory_archive(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))')
        args = [sys.executable, '-c', code, str(self.root),
                self.source.relative_to(self.root).as_posix(), self.sha]
        processes = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
        try:
            results = [process.communicate(timeout=30) for process in processes]
            for process, (_, error) in zip(processes, results):
                self.assertEqual(process.returncode, 0, error.decode())
            self.assertTrue(all(result[0] == results[0][0] for result in results))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_timeout_and_invalid_limits(self):
        with patch.object(archive.time, 'monotonic', side_effect=[0, 1000]):
            with self.assertRaises(ValueError):
                self.prepare()
        for value in (True, 0, -1, float('inf')):
            with patch.object(archive, 'MAX_UNCOMPRESSED_BYTES', value):
                with self.assertRaises(ValueError):
                    self.prepare()

    def test_reject_header_flags_and_bad_gzip_payload(self):
        ref = self.prepare()
        target = self.root / ref['path']
        original = target.read_bytes()
        for body in (original[:3] + b'\x20' + original[4:], original[:10] + b'broken', original[:-5]):
            target.write_bytes(body)
            changed = dict(ref, sha256=hashlib.sha256(body).hexdigest())
            with self.assertRaises(ValueError):
                archive.verify_inventory_archive(self.root, changed)

    def test_object_hardlink_and_pointer_are_rejected(self):
        ref = self.prepare()
        target = self.root / ref['path']
        alias = target.with_name('alias')
        os.link(target, alias)
        with self.assertRaises(ValueError):
            archive.open_verified_inventory_archive(self.root, ref)
        alias.unlink()
        target.write_bytes(b'{"path":"inventory.jsonl"}')
        changed = dict(ref, sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):
            archive.verify_inventory_archive(self.root, changed)

    def test_source_and_target_symlinks(self):
        alias = self.source.with_name('link')
        try:
            alias.write_bytes(self.raw)
            self.source.unlink()
            self.source.symlink_to(alias)
        except OSError as exc:
            self.skipTest('symlink permission unavailable: ' + str(exc))
        with self.assertRaises(ValueError):
            self.prepare()
        self.source.unlink()
        self.source.write_bytes(self.raw)
        ref = self.prepare()
        target = self.root / ref['path']
        target.unlink()
        target.symlink_to(alias)
        with self.assertRaises(ValueError):
            archive.verify_inventory_archive(self.root, ref)

    def test_compressed_bound_and_mutated_object_during_verify(self):
        ref = self.prepare()
        target = self.root / ref['path']
        with patch.object(archive, 'MAX_COMPRESSED_BYTES', 10):
            with self.assertRaises(ValueError):
                archive.verify_inventory_archive(self.root, ref)
        original = archive._unchanged
        calls = 0

        def mutate(root, path, handle, identity):
            nonlocal calls
            calls += 1
            if calls == 2:
                path.write_bytes(b'changed')
            return original(root, path, handle, identity)

        with patch.object(archive, '_unchanged', mutate):
            with self.assertRaises(ValueError):
                archive.verify_inventory_archive(self.root, ref)

    def test_reparse_guard_and_target_rejection(self):
        original = archive._safe_local_path

        def reject(root, path):
            if path.name.endswith('.guard'):
                return 'link or reparse point'
            return original(root, path)

        with patch.object(archive, '_safe_local_path', reject):
            with self.assertRaisesRegex(ValueError, 'reparse'):
                self.prepare()
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertFalse(list(self.root.rglob('*.gz')))

    def test_publication_failure_cleans_only_owned_temp(self):
        directory = self.root / 'machine/semantic_inventories' / self.sha
        directory.mkdir(parents=True)
        foreign = directory / '.foreign.tmp'
        foreign.write_bytes(b'keep')
        with patch.object(archive, '_publish_no_replace', side_effect=OSError('interrupted publication')):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertEqual(list(directory.glob('*.tmp')), [foreign])
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_process_death_at_publication_retries_without_hardlinks(self):
        code = '''
import os
import sys
from pathlib import Path
from wqb import semantic_inventory_archive as archive
link, rename = os.link, os.rename
def die_after_link(*args, **kwargs):
    link(*args, **kwargs)
    os._exit(73)
def die_after_rename(*args, **kwargs):
    rename(*args, **kwargs)
    os._exit(73)
archive.os.link = die_after_link
archive.os.rename = die_after_rename
if hasattr(archive, '_publish_no_replace'):
    publish = archive._publish_no_replace
    def die_after_publish(*args, **kwargs):
        publish(*args, **kwargs)
        os._exit(73)
    archive._publish_no_replace = die_after_publish
archive.prepare_inventory_archive(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.root),
                                 self.source.relative_to(self.root).as_posix(), self.sha],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 73, result.stderr.decode())
        ref = self.prepare()
        self.assertEqual((self.root / ref['path']).stat().st_nlink, 1)
        self.assertFalse(list((self.root / ref['path']).parent.glob('*.tmp')))
        self.assertEqual(archive.verify_inventory_archive(self.root, ref), ref)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_reader_expiry_applies_to_all_consumption_methods(self):
        ref = self.prepare()
        for method in ('read', 'read1', 'readline', 'readinto', 'readinto1', '__next__'):
            with self.subTest(method=method):
                with patch.object(archive.time, 'monotonic', return_value=100):
                    reader = archive.open_verified_inventory_archive(self.root, ref, timeout_seconds=10)
                with reader, patch.object(archive.time, 'monotonic', return_value=111):
                    args = (bytearray(10),) if method.startswith('readinto') else ()
                    with self.assertRaisesRegex(ValueError, 'timeout'):
                        getattr(reader, method)(*args)

    def test_reader_rejects_post_open_same_inode_gzip_bomb(self):
        ref = self.prepare()
        target = self.root / ref['path']
        with archive.open_verified_inventory_archive(self.root, ref) as reader:
            inode = target.stat().st_ino
            with target.open('wb') as output:
                with gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0) as writer:
                    writer.write(b'x' * 2000000)
            self.assertEqual(target.stat().st_ino, inode)
            with self.assertRaises(ValueError):
                reader.read()

    def test_reader_rehashes_second_pass_even_with_restored_metadata(self):
        self.raw = b'aaaa\n' * 1000
        self.source.write_bytes(self.raw)
        self.sha = hashlib.sha256(self.raw).hexdigest()
        ref = self.prepare()
        target = self.root / ref['path']
        before = target.stat()
        buffer = io.BytesIO()
        with gzip.GzipFile(filename='', fileobj=buffer, mode='wb', mtime=0) as writer:
            writer.write(b'bbbb\n' * 1000)
        changed = buffer.getvalue()
        self.assertEqual(len(changed), before.st_size)
        with archive.open_verified_inventory_archive(self.root, ref) as reader:
            target.write_bytes(changed)
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
            with self.assertRaises(ValueError):
                reader.read()

    def test_reader_byte_bound_survives_same_size_restored_metadata_bomb(self):
        self.raw = os.urandom(4096)
        self.source.write_bytes(self.raw)
        self.sha = hashlib.sha256(self.raw).hexdigest()
        ref = self.prepare()
        target = self.root / ref['path']
        before = target.stat()
        buffer = io.BytesIO()
        with gzip.GzipFile(filename='', fileobj=buffer, mode='wb', mtime=0) as writer:
            writer.write(b'x' * 2000000)
        bomb = buffer.getvalue()
        self.assertLess(len(bomb), before.st_size)
        with archive.open_verified_inventory_archive(self.root, ref) as reader:
            target.write_bytes(bomb + b'\x00' * (before.st_size - len(bomb)))
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
            with self.assertRaisesRegex(ValueError, 'exact size exceeded'):
                reader.read()

    def test_reader_checks_compressed_hash_before_returning_final_sized_bytes(self):
        ref = self.prepare()
        target = self.root / ref['path']
        before = target.stat()
        changed = bytearray(target.read_bytes())
        changed[4] = 1  # Valid gzip timestamp change: same raw bytes, different compressed identity.
        with archive.open_verified_inventory_archive(self.root, ref) as reader:
            target.write_bytes(changed)
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
            with self.assertRaisesRegex(ValueError, 'compressed.*hash'):
                reader.read(len(self.raw))

    def test_reader_expiry_also_applies_to_buffered_data_and_during_reads(self):
        ref = self.prepare()
        with patch.object(archive.time, 'monotonic', return_value=100):
            reader = archive.open_verified_inventory_archive(self.root, ref, timeout_seconds=10)
            self.assertEqual(reader.read(1), self.raw[:1])
        with reader, patch.object(archive.time, 'monotonic', return_value=111):
            with self.assertRaisesRegex(ValueError, 'timeout'):
                reader.readline()
        now = [100]
        original = archive.gzip.GzipFile.read

        def expire_after_read(handle, size=-1):
            data = original(handle, size)
            now[0] = 111
            return data

        with patch.object(archive.time, 'monotonic', side_effect=lambda: now[0]):
            with archive.open_verified_inventory_archive(self.root, ref, timeout_seconds=10) as reader:
                with patch.object(archive.gzip.GzipFile, 'read', expire_after_read):
                    with self.assertRaisesRegex(ValueError, 'timeout'):
                        reader.read(10)

    def test_reader_forward_methods_validate_and_close_owned_descriptor(self):
        ref = self.prepare()
        with archive.open_verified_inventory_archive(self.root, ref) as reader:
            handle = reader._source.handle
            self.assertEqual(reader.read1(2), self.raw[:2])
            buffer = bytearray(3)
            self.assertEqual(reader.readinto1(buffer), 3)
            self.assertEqual(buffer, self.raw[2:5])
            self.assertEqual(b''.join(reader), self.raw[5:])
            self.assertEqual(reader.read(1), b'')
            self.assertFalse(reader.seekable())
        self.assertTrue(handle.closed)

    def test_publication_never_overwrites_racing_destination(self):
        original = archive._publish_no_replace
        targets = []

        def conflicting_publish(temp, target):
            targets.append(target)
            target.write_bytes(b'foreign object')
            original(temp, target)

        with patch.object(archive, '_publish_no_replace', conflicting_publish):
            with self.assertRaises(FileExistsError):
                self.prepare()
        self.assertEqual(targets[0].read_bytes(), b'foreign object')
        self.assertFalse(list(targets[0].parent.glob('*.tmp')))
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_wrong_source_hash_and_empty_inventory(self):
        self.source.write_bytes(b'wrong')
        with self.assertRaises(ValueError):
            self.prepare()
        self.source.write_bytes(b'')
        self.sha = hashlib.sha256(b'').hexdigest()
        ref = self.prepare()
        self.assertEqual(ref['uncompressed_bytes'], 0)
        with archive.open_verified_inventory_archive(self.root, ref) as reader:
            self.assertEqual(reader.read(), b'')


if __name__ == '__main__':
    unittest.main()
