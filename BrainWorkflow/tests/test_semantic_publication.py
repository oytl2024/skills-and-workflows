import hashlib
import importlib
import json
import tempfile
import unittest
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from wqb.knowledge_paths import existing_machine_resource_path
from wqb.knowledge_clean_compile import evaluate_clean_knowledge_structure
from wqb.knowledge_freshness import KnowledgeFreshnessRecord, evaluate_freshness
from datetime import date


class SemanticPublicationTests(unittest.TestCase):
    def test_source_repair_completion_guards_material_and_publication(self):
        """Input: incomplete or raced repair proof. Output: assertions. Neither consumer may bypass repair completion."""
        from wqb import knowledge_contracts
        from wqb.semantic_compilation import _material
        row = dict(path='raw/platform/operators.md', content_hash=hashlib.sha256(self.source.read_bytes()).hexdigest(),
                   captured_at='2026-10-15T00:00:00Z', source_type='platform_learn_material', source_family='raw/platform/learn')
        for mode in ('incomplete', 'raced_bytes'):
            result = dict(status='verified', source_sha256='0' * 64)
            options = dict(side_effect=ValueError('source repair publication incomplete')) if mode == 'incomplete' else dict(return_value=result)
            with self.subTest(mode=mode), patch.object(knowledge_contracts, 'verify_source_repair', create=True, **options):
                with self.subTest(consumer='material'), self.assertRaises(ValueError):
                    _material(self.root, row)
                with self.subTest(consumer='publication'), self.assertRaises(ValueError):
                    self.api().stage_semantic_release(self.root, self.proposals(), '2026-10-15T00:00:00Z')
            self.assertFalse((self.root / 'machine/semantic_release.json').exists())

    def test_extract_recognition_never_trusts_marker_or_reserved_name(self):
        for mode in ('header', 'canonical_name', 'index'):
            with self.subTest(mode=mode):
                path = ('raw/platform/data_fields/2026-07-30/semantic-subset-' + 'a' * 64 + '.md'
                        if mode == 'canonical_name' else 'raw/platform/learn/forged.md')
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('---\ncontent_status: verified_raw_extract\n---\nUnverified.\n'
                                  if mode == 'header' else 'Unverified.\n', encoding='utf-8')
                if mode == 'index':
                    (self.root / 'machine/source_index.jsonl').write_text(json.dumps(dict(
                        path=path, content_status='verified_raw_extract')) + '\n', encoding='utf-8')
                proposals = dict(self.proposals(), source_refs=[dict(path=path,
                    sha256=hashlib.sha256(target.read_bytes()).hexdigest())])
                with self.assertRaises(ValueError):
                    self.api().stage_semantic_release(self.root, proposals, '2026-10-15T00:00:00Z')
                self.assertFalse((self.root / 'machine/semantic_release.json').exists())

    def test_v2_contract_survives_release_and_snapshot(self):
        from copy import deepcopy
        from tests.test_resource_evidence import operator_fixture, timing_fixture
        from wqb.knowledge_compile import read_semantic_rows
        proposals = self.proposals()
        operator, _, _ = operator_fixture()
        proposals.update(resource_contract_version=2, validated_operators=[operator])
        staged = self.api().stage_semantic_release(self.root, proposals, '2026-10-15T00:00:00Z')
        self.assertEqual(staged['resource_contract_version'], 2)
        self.api().publish_semantic_release(self.root, staged)
        receipt, operators, templates = read_semantic_rows(self.root)
        snapshot = dict(semantic_release=deepcopy(receipt), operator_rows=operators,
                        template_rows=templates, data_ledger_rows=[dict(timing_contract=timing_fixture()[0])])
        frozen = json.loads(json.dumps(snapshot))
        self.assertEqual(frozen['operator_rows'][0]['definition_basis'], operator['definition_basis'])
        self.assertEqual(frozen['semantic_release']['resource_contract_version'], 2)
        self.assertEqual(frozen['data_ledger_rows'][0]['timing_contract'], timing_fixture()[0])

    def test_release_version_bool_and_pack_mismatch_reject(self):
        for value in (True, False, 0, 3, '2', 2.0):
            proposals = dict(self.proposals(), resource_contract_version=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.api().stage_semantic_release(self.root, proposals, '2026-10-15T00:00:00Z')
        proposals = dict(self.proposals(), resource_contract_version=2,
                         evidence_pack=dict(resource_contract_version=1))
        with self.assertRaises(ValueError):
            self.api().stage_semantic_release(self.root, proposals, '2026-10-15T00:00:00Z')

    def test_transient_windows_pointer_sharing_error_retries_without_mixing_resources(self):
        """Input: temporary release and one simulated Windows sharing conflict. Output: assertions. Recover a bounded atomic publication."""
        api = self.api()
        staged = self.stage()
        original = api.os.replace
        attempts = []
        def replace(source, target):
            """Input: atomic temporary/target paths. Output: None. Fail the first pointer replacement only."""
            if Path(target).name == 'semantic_release.json':
                attempts.append(str(target))
                if len(attempts) == 1:
                    error = PermissionError('FAKE transient Windows sharing conflict')
                    error.winerror = 5
                    raise error
            return original(source, target)
        with patch('wqb.semantic_publication.os.replace', side_effect=replace):
            api.publish_semantic_release(self.root, staged)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(api.read_semantic_release(self.root)['release_id'], staged['release_id'])

    def write_legacy_pair(self, version):
        """Input: integer version. Output: none. Replace both mutable temporary canonical resources."""
        for name in ('operator_ledger', 'template_library'):
            path = self.root / 'machine' / (name + '.jsonl')
            temporary = path.with_suffix('.replacement')
            temporary.write_text(json.dumps({'version': version}) + '\n', encoding='utf-8')
            temporary.replace(path)

    def test_persistent_windows_sharing_failure_is_bounded_and_keeps_prior_pointer(self):
        """Input: persistent simulated sharing denial. Output: assertions. Never claim publication or discard the old generation."""
        api = self.api()
        previous = api.publish_semantic_release(self.root, self.stage())
        staged = self.stage(2)
        error = PermissionError('FAKE persistent Windows sharing conflict')
        error.winerror = 32
        with patch('wqb.semantic_publication.os.replace', side_effect=error) as replace, patch('wqb.semantic_publication.time.sleep'):
            with self.assertRaises(PermissionError):
                api.publish_semantic_release(self.root, staged)
        self.assertEqual(replace.call_count, api.ATOMIC_REPLACE_MAX_ATTEMPTS)
        self.assertEqual(api.read_semantic_release(self.root), previous)

    def test_legacy_receipt_rejects_replacement_between_paired_reads(self):
        api = self.api()
        self.write_legacy_pair(0)
        receipt = api.read_semantic_release(self.root)
        first = existing_machine_resource_path(self.root, 'operator_ledger', receipt=receipt)
        self.assertEqual(json.loads(first.read_text())['version'], 0)
        self.write_legacy_pair(1)
        with self.assertRaises(ValueError):
            existing_machine_resource_path(self.root, 'template_library', receipt=receipt)
        with self.assertRaises(ValueError):
            api.validate_semantic_receipt(self.root, receipt)

    def test_legacy_receipt_digests_bind_both_resources_and_missing_state(self):
        api = self.api()
        empty = api.read_semantic_release(self.root)
        self.assertEqual(empty['digests'], {'operator_ledger': None, 'template_library': None})
        self.assertEqual(api.validate_semantic_receipt(self.root, empty), empty)
        self.write_legacy_pair(0)
        with self.assertRaises(ValueError):
            api.validate_semantic_receipt(self.root, empty)
        receipt = api.read_semantic_release(self.root)
        for name, path in receipt['paths'].items():
            self.assertEqual(receipt['digests'][name], hashlib.sha256(Path(path).read_bytes()).hexdigest())
        self.assertEqual(api.validate_semantic_receipt(self.root, receipt), receipt)
        Path(receipt['paths']['operator_ledger']).unlink()
        with self.assertRaises(ValueError):
            existing_machine_resource_path(self.root, 'template_library', receipt=receipt)

    def test_full_forged_legacy_receipt_cannot_bypass_active_or_corrupt_pointer(self):
        api = self.api()
        self.write_legacy_pair(0)
        forged = {
            'schema_version': 1, 'release_id': None,
            'paths': {name: str(self.root / 'machine' / (name + '.jsonl')) for name in ('operator_ledger', 'template_library')},
            'digests': {name: hashlib.sha256((self.root / 'machine' / (name + '.jsonl')).read_bytes()).hexdigest() for name in ('operator_ledger', 'template_library')},
        }
        generation = api.publish_semantic_release(self.root, self.stage())
        with self.assertRaises(ValueError):
            existing_machine_resource_path(self.root, 'operator_ledger', receipt=forged)
        (self.root / 'machine/semantic_release.json').write_text('{', encoding='utf-8')
        with self.assertRaises(ValueError):
            existing_machine_resource_path(self.root, 'template_library', receipt=forged)
        self.assertEqual(api.validate_semantic_receipt(self.root, generation), generation)
        self.assertEqual(existing_machine_resource_path(self.root, 'operator_ledger', receipt=generation), Path(generation['paths']['operator_ledger']))

    def test_legacy_final_validation_rejects_after_path_was_returned(self):
        api = self.api()
        self.write_legacy_pair(0)
        receipt = api.read_semantic_release(self.root)
        paths = [existing_machine_resource_path(self.root, name, receipt=receipt) for name in ('operator_ledger', 'template_library')]
        first = json.loads(paths[0].read_text())['version']
        self.write_legacy_pair(1)
        second = json.loads(paths[1].read_text())['version']
        self.assertEqual((first, second), (0, 1))  # Mutable paths alone are not a snapshot.
        with self.assertRaises(ValueError):
            api.validate_semantic_receipt(self.root, receipt)

    def setUp(self):
        """Input: none. Output: none. Create an isolated temporary vault and source."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('raw', 'machine', 'wiki'):
            (self.root / name).mkdir()
        self.source = self.root / 'raw/platform/operators.md'
        self.source.parent.mkdir()
        self.source.write_text('captured original definition', encoding='utf-8')

    def api(self):
        """Input: none. Output: module. Require the new publication implementation."""
        spec = importlib.util.find_spec('wqb.semantic_publication')
        self.assertIsNotNone(spec, 'Task4 publication module must exist')
        return importlib.import_module('wqb.semantic_publication')

    def proposals(self, version=1):
        """Input: integer version. Output: dict. Build already-validated generic test proposals."""
        return {
            'validated_operators': [{'name': 'rank', 'version': version}],
            'validated_templates': [{'template_id': 'test', 'version': version}],
            'source_refs': [{'path': 'raw/platform/operators.md', 'sha256': hashlib.sha256(self.source.read_bytes()).hexdigest()}],
            'wiki_materials': {'wiki/30_template_and_operator_patterns.md': '# Test hypotheses\n'},
        }

    def stage(self, version=1):
        """Input: integer version. Output: receipt dict. Stage an isolated test generation."""
        return self.api().stage_semantic_release(self.root, self.proposals(version), '2026-10-13T00:00:00Z')

    def test_stage_is_inactive_idempotent_and_publish_routes_fixed_receipt(self):
        api = self.api()
        staged = self.stage()
        self.assertFalse((self.root / 'machine/semantic_release.json').exists())
        self.assertEqual(staged, self.stage())
        receipt = api.publish_semantic_release(self.root, staged)
        self.assertEqual(receipt, api.read_semantic_release(self.root))
        for name in ('operator_ledger', 'template_library'):
            path = Path(receipt['paths'][name])
            self.assertIn(staged['release_id'], path.parts)
            self.assertEqual(existing_machine_resource_path(self.root, name, receipt=receipt), path)
            self.assertEqual(existing_machine_resource_path(self.root, name), path)
            self.assertFalse((self.root / 'machine' / path.name).exists())
        self.assertTrue(evaluate_clean_knowledge_structure(self.root)['clean'])

    def test_absent_pointer_preserves_legacy_without_recursion(self):
        api = self.api()
        path = self.root / 'wiki/30_templates/template_library.jsonl'
        path.parent.mkdir()
        path.write_text('{}\n', encoding='utf-8')
        receipt = api.read_semantic_release(self.root)
        self.assertIsNone(receipt['release_id'])
        self.assertEqual(Path(receipt['paths']['template_library']), path)

    def test_source_change_or_resource_tampering_cannot_publish(self):
        api = self.api()
        old = api.publish_semantic_release(self.root, self.stage())
        new = self.stage(2)
        self.source.write_text('changed', encoding='utf-8')
        with self.assertRaises(ValueError):
            api.publish_semantic_release(self.root, new)
        self.assertEqual(api.read_semantic_release(self.root), old)
        self.source.write_text('captured original definition', encoding='utf-8')
        Path(new['paths']['template_library']).write_text('{}\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            api.publish_semantic_release(self.root, new)
        self.assertEqual(api.read_semantic_release(self.root), old)

    def test_pointer_and_manifest_corruption_fail_closed(self):
        api = self.api()
        for content in ('{', '{}', '{"schema_version":1,"release_id":"../raw","manifest_sha256":"x"}'):
            (self.root / 'machine/semantic_release.json').write_text(content, encoding='utf-8')
            with self.assertRaises(ValueError):
                api.read_semantic_release(self.root)
            with self.assertRaises(ValueError):
                existing_machine_resource_path(self.root, 'operator_ledger')
        (self.root / 'machine/semantic_release.json').unlink()
        receipt = api.publish_semantic_release(self.root, self.stage())
        manifest = Path(receipt['manifest_path'])
        manifest.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            api.read_semantic_release(self.root)

    def test_traversal_and_sensitive_sources_rejected(self):
        api = self.api()
        for name in ('../escape', '/absolute', 'raw/../machine/data.json', 'raw/.env', 'raw/credentials.json', 'raw\\platform\\operators.md'):
            proposals = self.proposals()
            proposals['source_refs'][0]['path'] = name
            with self.subTest(name=name), patch.object(api, '_read', side_effect=AssertionError('unsafe source read')), self.assertRaises(ValueError):
                api.stage_semantic_release(self.root, proposals, '2026-10-13')

    def test_symlink_source_rejected(self):
        api = self.api()
        link = self.root / 'raw/platform/link.md'
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest('Windows account has no symlink privilege')
        proposals = self.proposals()
        proposals['source_refs'][0]['path'] = 'raw/platform/link.md'
        with self.assertRaises(ValueError):
            api.stage_semantic_release(self.root, proposals, '2026-10-13')

    def test_interrupted_pointer_swap_preserves_old_and_retry_recovers(self):
        api = self.api()
        old = api.publish_semantic_release(self.root, self.stage())
        new = self.stage(2)
        with patch.object(api.os, 'replace', side_effect=OSError('injected interruption')):
            with self.assertRaises(OSError):
                api.publish_semantic_release(self.root, new)
        self.assertEqual(api.read_semantic_release(self.root), old)
        self.assertTrue(Path(old['manifest_path']).exists())
        api.publish_semantic_release(self.root, new)
        self.assertEqual(api.read_semantic_release(self.root)['release_id'], new['release_id'])
        self.assertEqual(existing_machine_resource_path(self.root, 'operator_ledger', receipt=old), Path(old['paths']['operator_ledger']))

    def test_concurrent_reads_never_mix_versions(self):
        api = self.api()
        old = api.publish_semantic_release(self.root, self.stage())
        new = self.stage(2)
        def read_pair():
            """Input: none. Output: tuple[int, int]. Read both resources from one fixed receipt."""
            receipt = api.read_semantic_release(self.root)
            return tuple(json.loads(Path(receipt['paths'][name]).read_text())['version'] for name in ('operator_ledger', 'template_library'))
        with ThreadPoolExecutor(max_workers=4) as pool:
            reads = [pool.submit(read_pair) for _ in range(30)]
            api.publish_semantic_release(self.root, new)
            reads += [pool.submit(read_pair) for _ in range(30)]
        self.assertTrue(all(item.result() in ((1, 1), (2, 2)) for item in reads))
        self.assertTrue(Path(old['manifest_path']).exists())

    def test_wiki_version_and_freshness_follow_release_not_raw_capture_date(self):
        api = self.api()
        receipt = api.publish_semantic_release(self.root, self.stage())
        wiki = self.root / 'wiki/30_template_and_operator_patterns.md'
        self.assertIn(receipt['release_id'], wiki.read_text())
        self.assertEqual(self.source.read_text(), 'captured original definition')
        record = KnowledgeFreshnessRecord('template_library', 'machine/template_library.jsonl', '2020-01-01', 1)
        status = evaluate_freshness([record], date(2026, 10, 13), self.root)[0]
        self.assertTrue(status.artifact_exists)
        self.assertFalse(status.stale)
        self.assertEqual(status.updated_at, '2026-10-13')

    def test_clean_checker_detects_invalid_pointer(self):
        self.api()
        (self.root / 'machine/semantic_release.json').write_text('{}', encoding='utf-8')
        report = evaluate_clean_knowledge_structure(self.root)
        self.assertFalse(report['clean'])
        self.assertIn('semantic_release_invalid', {row['code'] for row in report['issues']})

    def test_forged_receipt_cannot_route_outside_generation(self):
        api = self.api()
        receipt = api.publish_semantic_release(self.root, self.stage())
        forged = dict(receipt, paths={'operator_ledger': str(self.source)})
        self.assertEqual(existing_machine_resource_path(self.root, 'operator_ledger', receipt=forged), Path(receipt['paths']['operator_ledger']))
        with self.assertRaises(ValueError):
            existing_machine_resource_path(self.root, 'operator_ledger', receipt={'release_id': None, 'paths': {'operator_ledger': str(self.source)}})

    def test_dirty_structure_blocks_publish(self):
        api = self.api()
        staged = self.stage()
        (self.root / 'wiki/old.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'structure'):
            api.publish_semantic_release(self.root, staged)
        self.assertFalse((self.root / 'machine/semantic_release.json').exists())

    def test_invalid_timestamp_and_json_rows_rejected(self):
        api = self.api()
        for timestamp in ('now', '2026-99-99', '20261013T000000'):
            with self.assertRaises(ValueError):
                api.stage_semantic_release(self.root, self.proposals(), timestamp)
        proposals = self.proposals()
        proposals['validated_operators'][0]['bad'] = float('nan')
        with self.assertRaises(ValueError):
            api.stage_semantic_release(self.root, proposals, '2026-10-13')

    def test_interrupted_staging_keeps_active_generation(self):
        api = self.api()
        old = api.publish_semantic_release(self.root, self.stage())
        write = api._write_new
        def interrupt(path, data):
            """Input: Path, bytes. Output: none. Simulate disk failure during generation creation."""
            if path.name == 'template_library.jsonl':
                raise OSError('disk interrupted')
            write(path, data)
        with patch.object(api, '_write_new', side_effect=interrupt), self.assertRaises(OSError):
            self.stage(2)
        self.assertEqual(api.read_semantic_release(self.root), old)
        self.assertNotEqual(self.stage(2)['release_id'], old['release_id'])

    def test_interrupted_wiki_is_visible_and_retry_repairs(self):
        api = self.api()
        old = api.publish_semantic_release(self.root, self.stage())
        new = self.stage(2)
        replace = api.os.replace
        def interrupt(source, target):
            """Input: source/target Paths. Output: none. Fail after machine pointer commit."""
            if target.parent.name == 'wiki':
                raise OSError('wiki interrupted')
            replace(source, target)
        with patch.object(api.os, 'replace', side_effect=interrupt), self.assertRaises(OSError):
            api.publish_semantic_release(self.root, new)
        self.assertEqual(api.read_semantic_release(self.root)['release_id'], new['release_id'])
        self.assertIn(old['release_id'], (self.root / 'wiki/30_template_and_operator_patterns.md').read_text())
        self.assertIn('semantic_wiki_version_mismatch', {row['code'] for row in evaluate_clean_knowledge_structure(self.root)['issues']})
        api.publish_semantic_release(self.root, new)
        self.assertTrue(evaluate_clean_knowledge_structure(self.root)['clean'])

    def test_bounded_lock_does_not_steal_existing_lock(self):
        api = self.api()
        lock = api._acquire_lock(self.root)
        try:
            with patch.object(api, 'LOCK_TIMEOUT_SECONDS', 0.01), self.assertRaises(TimeoutError):
                self.stage()
        finally:
            api._release_lock(lock)
        self.stage()

    def test_process_crash_releases_writer_lock(self):
        self.api()
        code = 'import os,sys; from pathlib import Path; from wqb.semantic_publication import _acquire_lock; lock = _acquire_lock(Path(sys.argv[1])); os._exit(0)'
        result = subprocess.run([sys.executable, '-c', code, str(self.root)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        api = self.api()
        with patch.object(api, 'LOCK_TIMEOUT_SECONDS', 0.01):
            self.stage()

    def test_windows_alias_and_sensitive_config_sources_rejected(self):
        api = self.api()
        for path in ('raw/platform/operators.md.', 'raw/platform/operators.md ', 'raw/CON', 'raw/.ssh/config', 'raw/auth.json', 'raw/session.json', 'raw/cookies.json'):
            if path in ('raw/.ssh/config', 'raw/auth.json', 'raw/session.json', 'raw/cookies.json'):
                target = self.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.source.read_bytes())
            proposals = self.proposals()
            proposals['source_refs'][0]['path'] = path
            with self.subTest(path=path), patch.object(api, '_read', side_effect=AssertionError('unsafe source read')), self.assertRaises(ValueError):
                api.stage_semantic_release(self.root, proposals, '2026-10-13')

    def test_symlink_pointer_and_generation_fail_closed(self):
        api = self.api()
        receipt = api.publish_semantic_release(self.root, self.stage())
        path = self.root / 'machine/semantic_release.json'
        backup = self.root / 'machine/pointer-backup.json'
        path.rename(backup)
        try:
            path.symlink_to(backup)
        except OSError:
            backup.rename(path)
            self.skipTest('Windows account has no symlink privilege')
        with self.assertRaises(ValueError):
            api.read_semantic_release(self.root)
        path.unlink()
        backup.rename(path)
        resource = Path(receipt['paths']['operator_ledger'])
        resource.unlink()
        resource.symlink_to(self.source)
        with self.assertRaises(ValueError):
            api.read_semantic_release(self.root)

    def test_first_publish_checks_wiki_target_before_pointer_commit(self):
        api = self.api()
        staged = self.stage()
        target = self.root / 'wiki/30_template_and_operator_patterns.md'
        target.mkdir()
        with self.assertRaises((ValueError, OSError)):
            api.publish_semantic_release(self.root, staged)
        self.assertFalse((self.root / 'machine/semantic_release.json').exists())

    def test_authenticated_manifest_cannot_escape_or_hide_extra_files(self):
        api = self.api()
        receipt = api.publish_semantic_release(self.root, self.stage())
        path = Path(receipt['manifest_path'])
        manifest = json.loads(path.read_text())
        manifest['resources']['operator_ledger']['path'] = '../../../raw/platform/operators.md'
        path.write_text(json.dumps(manifest), encoding='utf-8')
        pointer = self.root / 'machine/semantic_release.json'
        payload = json.loads(pointer.read_text())
        payload['manifest_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        pointer.write_text(json.dumps(payload), encoding='utf-8')
        with self.assertRaises(ValueError):
            api.read_semantic_release(self.root)
        # An unlisted file must not gain provenance simply by living in a release.
        other_root = self.root / 'other'
        other_root.mkdir()
        for name in ('raw', 'wiki', 'machine'):
            (other_root / name).mkdir()
        proposals = self.proposals()
        proposals['source_refs'] = []
        staged = api.stage_semantic_release(other_root, proposals, '2026-10-13')
        (Path(staged['manifest_path']).parent / 'unlisted.txt').write_text('untracked', encoding='utf-8')
        with self.assertRaises(ValueError):
            api.publish_semantic_release(other_root, staged)
