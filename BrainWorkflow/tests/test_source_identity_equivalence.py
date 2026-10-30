"""Source enrichment is not authority; byte verification remains mandatory."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb import semantic_compilation as subject


class SourceIdentityEquivalenceTests(unittest.TestCase):
    def setUp(self):
        """Input: none. Output: isolated source and registered identity on self."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'raw/platform/fixture.txt'
        self.path.parent.mkdir(parents=True)
        self.path.write_text('Documented fixture facts.', encoding='utf-8')
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.registered = dict(path='raw/platform/fixture.txt', content_hash=self.digest,
            captured_at='2026-10-23T00:00:00Z', source_type='platform_learn_material',
            source_family='raw/platform')

    def verify(self, frozen=None, registered=None):
        """Input: optional source dicts. Output: verification result, never mutate inputs."""
        return subject.verify_source_equivalence(self.root,
            self.registered if frozen is None else frozen,
            self.registered if registered is None else registered)

    def test_valid_optional_full_hash_is_verified_not_compared_as_authority(self):
        frozen = dict(self.registered, file_sha256=self.digest)
        before = deepcopy(frozen)
        result = self.verify(frozen)
        self.assertEqual(result['source_index']['file_sha256'], self.digest)
        self.assertEqual(result['source_text'], 'Documented fixture facts.')
        self.assertEqual(frozen, before)
        self.assertEqual(self.verify(self.registered, frozen), result)

    def test_asserted_full_hash_must_match_bytes_on_both_sides(self):
        for value in ('0' * 64, '', 7, None):
            with self.subTest(value=value):
                bad = dict(self.registered, file_sha256=value)
                with self.assertRaises(ValueError):
                    self.verify(bad)
                with self.assertRaises(ValueError):
                    self.verify(self.registered, bad)

    def test_start_context_consumes_verified_enrichment_without_mutating_index(self):
        from wqb.preplanned_start import _source_context
        path = self.registered['path']
        original = dict(self.registered)
        self.assertEqual(_source_context(self.root,
            {path: dict(original, file_sha256=self.digest)}, {path: original}),
            {path: 'Documented fixture facts.'})
        self.assertEqual(original, self.registered)
        with self.assertRaisesRegex(ValueError, 'canonical registration'):
            _source_context(self.root, {'wrong': original}, {'wrong': original})

    def test_all_non_enrichment_changes_remain_authority_conflicts(self):
        for key, value in [('captured_at', '2026-10-24T00:00:00Z'),
                ('source_family', 'raw/research'), ('source_type', 'platform_activity_snapshot'),
                ('scope', dict(region='KOR')), ('unknown_authority', True),
                ('target_ids', ['other']), ('content_status', 'verified_raw_extract')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(dict(self.registered, **{key: value}))

    def test_changed_body_is_not_accepted_by_matching_index_metadata(self):
        self.path.write_text('Changed source.', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'content_hash'):
            self.verify()

    def test_markdown_body_and_full_hash_are_independently_verified(self):
        path = self.root / 'raw/platform/page.md'
        path.write_text('---\nsource_type: platform_learn_material\n---\nBody.\n', encoding='utf-8')
        from wqb.knowledge_contracts import parse_markdown_front_matter
        _, body = parse_markdown_front_matter(path.read_text(encoding='utf-8'))
        row = dict(self.registered, path='raw/platform/page.md',
                   content_hash=hashlib.sha256(body.encode()).hexdigest())
        full_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertNotEqual(row['content_hash'], full_hash)
        result = self.verify(dict(row, file_sha256=full_hash), row)
        self.assertEqual(result['source_index']['file_sha256'], full_hash)
        with self.assertRaises(ValueError):
            self.verify(dict(row, file_sha256=row['content_hash']), row)

    def test_changed_full_bytes_between_reads_reject_same_body(self):
        path = self.root / 'raw/platform/race.md'
        path.write_text('---\ntitle: first\n---\nBody.\n', encoding='utf-8')
        from wqb.knowledge_contracts import parse_markdown_front_matter
        _, body = parse_markdown_front_matter(path.read_text(encoding='utf-8'))
        row = dict(self.registered, path='raw/platform/race.md',
                   content_hash=hashlib.sha256(body.encode()).hexdigest())
        original = subject._material
        calls = []
        def material(root, source):
            """Input: source verifier inputs. Output: real verified bytes with a simulated intervening write."""
            result = original(root, source)
            calls.append(source)
            if len(calls) == 1:
                path.write_text('---\ntitle: changed\n---\nBody.\n', encoding='utf-8')
            return result
        with patch.object(subject, '_material', side_effect=material):
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                self.verify(row, row)

    def test_equal_unsafe_paths_do_not_bypass_source_guards(self):
        row = dict(self.registered, path='raw/platform/../fixture.txt')
        with self.assertRaises(ValueError):
            self.verify(row, row)

    def test_invalid_repair_receipt_is_not_hidden_by_identity_equivalence(self):
        path = self.root / 'raw/platform/repaired.md'
        path.write_text('Body.', encoding='utf-8')
        row = dict(self.registered, path='raw/platform/repaired.md',
                   content_hash=hashlib.sha256(path.read_bytes()).hexdigest())
        with patch('wqb.knowledge_contracts.verify_source_repair', return_value=dict(status='invalid')):
            with self.assertRaisesRegex(ValueError, 'repair receipt'):
                self.verify(row, row)

    def test_hypothesis_source_never_expands_official_fact_authority(self):
        from wqb import resource_evidence
        path = 'raw/user/idea.txt'
        source = dict(self.registered, path=path, source_type='user_note', source_family='raw/user')
        ref = dict(source_path=path, sha256=self.digest, capture_date='2026-10-23',
                   kind='hypothesis', experiment_refs=[])
        index, texts = {path: source}, {path: 'Documented fixture facts.'}
        with self.assertRaisesRegex(ValueError, 'official source family'):
            resource_evidence._source(ref, index, texts)
        self.assertEqual(resource_evidence.verify_hypothesis_source(ref, index, texts), texts[path])
        with self.assertRaises(ValueError):
            resource_evidence.verify_hypothesis_source(dict(ref, kind='documented'), index, texts)
        with self.assertRaises(ValueError):
            resource_evidence.verify_hypothesis_source(ref,
                {path: dict(source, source_type='platform_learn_material')}, texts)
        with self.assertRaisesRegex(ValueError, 'hash'):
            resource_evidence.verify_hypothesis_source(ref, index, {path: 'Changed text'})


if __name__ == '__main__':
    unittest.main()
