"""Lossless bounded archives of script-selected package payloads; temporary inputs only."""
import importlib
import json
import unittest

from tests import test_execution_package as fixtures


class ExecutionPackageStorageTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated certified owning package; no model/platform."""
        self.fixture = fixtures.ExecutionPackageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.enable()
        self.fixture.fixture.freeze()
        self.run = self.fixture.run

    def test_archive_keeps_originals_and_roundtrips_exact_selected_inputs(self):
        storage = importlib.import_module('wqb.execution_package_storage')
        index = storage.prepare_package_archive(self.run)
        self.assertTrue(index['entries'])
        self.assertNotIn('run_manifest.json', [row['path'] for row in index['entries']])
        for row in index['entries']:
            before = (self.run / row['path']).read_bytes()
            self.assertEqual(storage.read_archived_input(self.run, row['path']), before)
        before = (self.run / storage.ARCHIVE_INDEX).read_bytes()
        self.assertEqual(storage.prepare_package_archive(self.run), index)
        self.assertEqual((self.run / storage.ARCHIVE_INDEX).read_bytes(), before)

    def test_archive_reader_does_not_restore_removed_payload_or_read_global_vault(self):
        storage = importlib.import_module('wqb.execution_package_storage')
        index = storage.prepare_package_archive(self.run)
        row = index['entries'][0]
        path = self.run / row['path']
        expected = path.read_bytes()
        path.unlink()
        self.fixture.fixture.vault.rename(self.fixture.fixture.root / 'removed-vault')
        self.assertEqual(storage.read_archived_input(self.run, row['path']), expected)
        self.assertFalse(path.exists())
        with self.assertRaises(ValueError):
            storage.read_archived_input(self.run, 'run_manifest.json')

    def test_archive_tampering_and_unexpected_members_reject(self):
        storage = importlib.import_module('wqb.execution_package_storage')
        index = storage.prepare_package_archive(self.run)
        row = index['entries'][0]
        path = self.run / row['object_path']
        before = path.read_bytes()
        path.write_bytes(before + b'bad')
        with self.assertRaises(ValueError):
            storage.read_archived_input(self.run, row['path'])
        path.write_bytes(before)
        index_path = self.run / storage.ARCHIVE_INDEX
        changed = json.loads(index_path.read_text())
        changed['entries'][0]['path'] = '../outside'
        index_path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            storage.read_archived_input(self.run, row['path'])

    def test_unowned_or_linked_archival_selector_rejects(self):
        storage = importlib.import_module('wqb.execution_package_storage')
        from wqb.execution_package import load_execution_package
        seal = load_execution_package(self.run)['seal']
        changed = dict(seal, certificate_refs=[dict(
            path='runtime/exploration/resources/../unexpected/' + 'a' * 64 + '.json', sha256='b' * 64)])
        with self.assertRaises(ValueError):
            storage._inputs(changed)


if __name__ == '__main__':
    unittest.main()
