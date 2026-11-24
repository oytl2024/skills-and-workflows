"""Read-only query contracts using isolated, indexed fake knowledge."""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch


class ResearchQueriesTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: None; create temporary sources and a lazy index double."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scope = dict(instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000')
        self.stamp = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.index = []
        self.backend = ModuleType('wqb.research_query_index')
        self.backend.validate_query_generation = Mock(return_value={'generation': 'g1'})
        self.backend.query_fields = Mock(return_value=dict(items=[dict(dataset_id='d', field_id='outside_30',
            source_paths=['raw/platform/data_fields/d.json'])], total=61, offset=30, next_offset=31, warnings=[]))
        self.backend.read_field_rows = Mock(return_value=[dict(dataset_id='d', field_id='outside_30',
            source_paths=['raw/platform/data_fields/d.json'])])
        self.modules = patch.dict(sys.modules, {'wqb.research_query_index': self.backend})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.source('raw/platform/data_fields/d.json', {'field_id': 'outside_30'})

    def write_json(self, path, value):
        """Input: relative str/JSON object. Output: bytes; write only within the fixture."""
        raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return raw

    def source(self, path, value, stamp=None):
        """Input: raw relative str/object/date str. Output: index row dict with actual byte hash."""
        raw = self.write_json(path, value)
        row = dict(path=path, content_hash=hashlib.sha256(raw).hexdigest(), captured_at=stamp or self.stamp,
                   source_type='platform_learn_material', source_family='raw/platform/learn')
        self.index.append(row)
        target = self.root / 'machine/source_index.jsonl'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(''.join(json.dumps(item) + '\n' for item in self.index), encoding='utf-8')
        return row

    def query(self, operation, **arguments):
        """Input: operation str/arguments. Output: query response dict from the real adapter."""
        module = importlib.import_module('wqb.research_queries')
        return module.query_knowledge(self.root, 'g1', self.scope, operation, arguments)

    def test_fields_delegate_pagination_without_shortlist_or_ledger(self):
        """Input: index double. Output: None; assert delegated pagination and complete response keys."""
        result = self.query('fields', query='outside', offset=30, limit=1, field_type='VECTOR')
        self.assertEqual(result['items'][0]['field_id'], 'outside_30')
        self.assertEqual((result['total'], result['next_offset']), (61, 31))
        self.backend.query_fields.assert_called_once_with(self.root, 'g1', self.scope,
            query='outside', field_type='VECTOR', offset=30, limit=1)
        self.assertEqual(self.backend.validate_query_generation.call_count, 2)
        self.assertEqual(set(result), {'operation', 'generation', 'items', 'total', 'offset', 'next_offset', 'warnings'})

    def test_real_index_integration_and_stale_generation_all_operations(self):
        """Input: real temporary index. Output: None; assert read-only integration and shared stale gate."""
        self.modules.stop()
        backend = importlib.import_module('wqb.research_query_index')
        module = importlib.import_module('wqb.research_queries')
        source = self.source('raw/platform/learn/operators.json', [dict(id='op')])
        rows = [dict(dataset_id='d', field_id=f'f{i:03}', field_type='VECTOR', available_scopes=[self.scope],
                     source_updated_at=self.stamp[:10], source_paths=[source['path']], field_description='signal')
                for i in range(61)]
        ledger = self.root / 'machine/data_ledger.jsonl'
        ledger.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        manifest = backend.prepare_query_index(self.root)
        generation = manifest['generation']
        before = {path.relative_to(self.root).as_posix(): path.read_bytes()
                  for path in self.root.rglob('*') if path.is_file()}
        page = module.query_knowledge(self.root, generation, self.scope, 'fields', dict(offset=60, limit=1))
        self.assertEqual(page['items'][0]['field_id'], 'f060')
        self.assertEqual(page['items'][0]['role_selector'], 'field:d/f060')
        self.assertEqual(page['items'][0]['source_updated_at'], self.stamp[:10])
        selected = module.query_knowledge(self.root, generation, self.scope, 'fields',
                                           dict(identities=[['d', 'f060']]))
        expected_ref = dict(source_path=source['path'], sha256=source['content_hash'], capture_date=self.stamp[:10],
                            kind='documented', experiment_refs=[])
        self.assertEqual(selected['items'], [dict(rows[60], role_selector='field:d/f060', evidence_refs=[expected_ref])])
        for operation, arguments in [('operators', {}), ('source', dict(path=source['path'])),
                                     ('templates', {}), ('experience', {})]:
            module.query_knowledge(self.root, generation, self.scope, operation, arguments)
        self.assertEqual(before, {path.relative_to(self.root).as_posix(): path.read_bytes()
                                  for path in self.root.rglob('*') if path.is_file()})
        ledger.write_bytes(ledger.read_bytes() + b'\n')
        for operation in ('fields', 'operators', 'templates', 'experience', 'source'):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                module.query_knowledge(self.root, generation, self.scope, operation, {})

    def test_exact_field_identities_are_not_search_tokens(self):
        """Input: exact selectors. Output: None; assert canonical row resolution, not lexical matching."""
        result = self.query('fields', identities=[['d', 'outside_30']])
        self.assertEqual(result['items'][0]['field_id'], 'outside_30')
        self.backend.read_field_rows.assert_called_once_with(self.root, 'g1', self.scope, [('d', 'outside_30')])

    def test_field_role_selectors_are_exact_identity_labels_without_mutating_rows(self):
        """Input: indexed cards and selected rows. Output: None; bind exact roles without inventing economic meaning."""
        for arguments in ({}, {'identities': [['d', 'outside_30']]}):
            with self.subTest(arguments=arguments):
                card = self.query('fields', **arguments)['items'][0]
                self.assertEqual(card['role_selector'], 'field:d/outside_30')
                source = self.index[0]
                self.assertEqual(card['evidence_refs'], [dict(source_path=source['path'], sha256=source['content_hash'],
                    capture_date=self.stamp[:10], kind='documented', experiment_refs=[])])
                self.assertNotIn('economic_meaning', card)
        self.assertNotIn('role_selector', self.backend.query_fields.return_value['items'][0])
        self.assertNotIn('role_selector', self.backend.read_field_rows.return_value[0])

    def test_scope_accepts_only_exact_four_keys_and_optional_as_of(self):
        """Input: scope variations. Output: None; preserve four-key callers, accept as_of, reject hidden filters."""
        self.query('fields')
        self.scope['as_of'] = self.stamp
        self.query('fields')
        for key in ('dataset_id', 'private_path', 'query', 'unexpected'):
            with self.subTest(key=key):
                self.scope[key] = 'not-a-scope-key'
                with self.assertRaisesRegex(ValueError, 'scope'):
                    self.query('fields')
                del self.scope[key]

    def test_field_missing_source_date_does_not_fabricate_evidence(self):
        """Input: incomplete indexed source metadata. Output: None; preserve unknown types and explicitly missing refs."""
        self.index[0].pop('captured_at')
        (self.root / 'machine/source_index.jsonl').write_text(json.dumps(self.index[0]), encoding='utf-8')
        self.backend.query_fields.return_value['items'][0]['field_type'] = 'unknown'
        result = self.query('fields')
        self.assertEqual(result['items'][0]['field_type'], 'unknown')
        self.assertEqual(result['items'][0]['role_selector'], 'field:d/outside_30')
        self.assertEqual(result['items'][0]['evidence_refs'], [])
        self.assertTrue(any('field_source_evidence_unavailable' in str(w) for w in result['warnings']))

    def test_stale_generation_rejects_every_operation_before_read(self):
        """Input: stale index double. Output: None; assert every operation fails before source reads."""
        self.backend.validate_query_generation.side_effect = ValueError('stale generation')
        for operation in ('fields', 'operators', 'templates', 'experience', 'source'):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, 'stale generation'):
                self.query(operation)
        self.backend.query_fields.assert_not_called()

    def test_generation_is_revalidated_after_material_read(self):
        """Input: generation change double. Output: None; reject a result acquired across a change."""
        self.backend.validate_query_generation.side_effect = [dict(generation='g1'), ValueError('changed')]
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.query('fields')

    def test_operators_use_latest_catalog_and_keep_unknown_signature(self):
        """Input: two dated catalogs. Output: None; assert latest-only visibility and unknown signatures."""
        self.source('raw/platform/old/operators.json', [dict(id='obsolete')],
                    (datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
        current = self.source('raw/platform/learn/operators.json', [dict(id='current', description='vector average')])
        result = self.query('operators', operator='current')
        self.assertEqual([row['operator'] for row in result['items']], ['current'])
        self.assertEqual(result['items'][0]['signature_status'], 'unknown')
        self.assertEqual(result['items'][0]['source_refs'][0]['content_hash'], current['content_hash'])
        self.assertTrue(any('signature' in str(warning) for warning in result['warnings']))
        self.assertEqual(self.query('operators', operator='obsolete')['total'], 0)

    def test_source_is_index_only_bounded_and_hash_bound(self):
        """Input: indexed raw fixture. Output: None; assert excerpt bounds and source authenticity."""
        row = self.source('raw/platform/learn/guide.json', {'description': 'x' * 500})
        result = self.query('source', path=row['path'], start=10, length=40)
        item = result['items'][0]
        self.assertEqual(len(item['excerpt']), 40)
        self.assertEqual(item['source_refs'][0]['content_hash'], row['content_hash'])
        self.assertIn('file_sha256', item['source_refs'][0])
        for path in ('../private.json', 'machine/source_index.jsonl', 'raw/platform/config.json',
                     'raw/platform/unindexed.json', 'C:/private.json'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.query('source', path=path)
        (self.root / row['path']).write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.query('source', path=row['path'])

    def test_source_freshness_is_not_semantic_admission(self):
        """Input: stale indexed fixture. Output: None; assert independent age-policy enforcement."""
        row = self.source('raw/platform/learn/stale.json', {'description': 'unknown'}, '2020-01-01T00:00:00Z')
        with self.assertRaisesRegex(ValueError, 'age policy'):
            self.query('source', path=row['path'])

    def test_indexed_private_paths_are_still_denied(self):
        """Input: private indexed fixtures. Output: None; assert index membership cannot bypass path safety."""
        for path in ('machine/private.json', 'machine/source_index.jsonl', '.obsidian/config.json',
                     'private/indexed.json', 'raw/platform/credentials.json', 'raw/platform/.private.json'):
            with self.subTest(path=path):
                self.source(path, dict(secret='fixture-only'))
                with self.assertRaises(ValueError):
                    self.query('source', path=path)

    def test_source_duplicate_index_and_claimed_file_hash_fail_closed(self):
        """Input: ambiguous or forged source metadata. Output: None; reject both identities."""
        row = self.source('raw/platform/learn/guide.json', {'fact': 'visible'})
        index_path = self.root / 'machine/source_index.jsonl'
        index_path.write_text(json.dumps(row) + '\n' + json.dumps(row), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.query('source', path=row['path'])
        index_path.write_text(json.dumps(dict(row, file_sha256='0' * 64)), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.query('source', path=row['path'])

    def test_operator_pages_do_not_accumulate_unbounded_signature_warnings(self):
        """Input: large operator inventory. Output: None; assert a small page remains compact."""
        self.source('raw/platform/learn/operators.json', [dict(id='op_' + str(i)) for i in range(1200)])
        result = self.query('operators', limit=1)
        self.assertEqual(result['total'], 1200)
        self.assertEqual(len(result['items']), 1)
        self.assertLess(len(result['warnings']), 4)

    def test_equal_date_operator_conflicts_are_not_hidden(self):
        """Input: conflicting same-date sources. Output: None; reject instead of choosing silently."""
        self.source('raw/platform/a/operators.json', [dict(id='op', description='one')])
        self.source('raw/platform/b/operators.json', [dict(id='op', description='two')])
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            self.query('operators')

    def test_incomplete_definition_is_not_a_known_signature(self):
        """Input: descriptive definition dict. Output: None; keep incomplete technical facts explicitly unknown."""
        self.source('raw/platform/learn/operators.json', [dict(id='op', definition=dict(description='not a type signature'))])
        card = self.query('operators')['items'][0]
        self.assertEqual(card['signature_status'], 'unknown')

    def test_operator_design_evidence_refs_bind_consumed_sources_not_embedded_claims(self):
        """Input: raw operators with forged refs. Output: None; expose schema-shaped refs and original capture metadata."""
        for typed in (False, True):
            with self.subTest(typed=typed):
                self.index = []
                fact = dict(id='op', source_path='private/forged', content_hash='0' * 64,
                            captured_at='2000-01-01', evidence_refs=[dict(source_path='forged')])
                if typed:
                    fact['definition'] = dict(input_types=['MATRIX'], output_type='MATRIX', parameters=[],
                                              evidence_refs=[dict(source_path='forged')])
                source = self.source('raw/platform/learn/operators.json', [fact])
                card = self.query('operators')['items'][0]
                expected = dict(source_path=source['path'], sha256=source['content_hash'],
                                capture_date=self.stamp[:10], kind='documented', experiment_refs=[])
                self.assertEqual(card['source_path'], source['path'])
                self.assertEqual(card['content_hash'], source['content_hash'])
                self.assertEqual(card['captured_at'], self.stamp)
                self.assertEqual(card['evidence_refs'], [expected])
                self.assertEqual(card['signature_status'], 'documented' if typed else 'unknown')
                if typed:
                    self.assertEqual(card['definition']['evidence_refs'], [expected])
                else:
                    self.assertNotIn('definition', card)

    def test_templates_keep_status_and_exact_identity_after_30(self):
        """Input: 45 canonical templates. Output: None; preserve status, scope and exact identity."""
        rows = [dict(template_id='t' + str(i), semantic_status='legacy/unreviewed',
                     hypothesis='lexical meaning', compatible_regions=['USA']) for i in range(45)]
        self.write_json('machine/placeholder.json', {})
        (self.root / 'machine/template_library.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        result = self.query('templates', template_id='t44')
        self.assertEqual(result['items'][0]['template_id'], 't44')
        self.assertEqual(result['items'][0]['semantic_status'], 'legacy/unreviewed')
        self.assertEqual(self.query('templates', query='lexical', offset=40, limit=5)['total'], 45)
        self.scope['region'] = 'CHN'
        self.assertEqual(self.query('templates')['total'], 0)

    def test_experience_includes_negative_inconclusive_and_success_without_12_cap(self):
        """Input: 33 mixed observations. Output: None; assert scoped pagination beyond the prompt cap."""
        labels = ['supports_prediction_in_scope', 'contradicts_prediction_in_scope', 'inconclusive']
        groups = [dict(group_id=f'g{i:02}', experiment_id=f'e{i}', measurement_period=None,
                       experiment=dict(arms=[dict(scope=self.scope)]), cohort={},
                       label=labels[i % 3], mechanism_families=['sentiment'], limitations=['unknown'])
                  for i in range(33)]
        groups.append(dict(groups[0], group_id='foreign', cohort=dict(scope=dict(self.scope, region='CHN'))))
        self.write_json('machine/mechanism_evidence.json', dict(input_digest='evidence-generation', groups=groups))
        result = self.query('experience', query='sentiment', offset=20, limit=13)
        self.assertEqual((result['total'], len(result['items'])), (33, 13))
        all_items = self.query('experience', limit=40)['items']
        self.assertEqual({row['label'] for row in all_items}, set(labels))
        self.assertNotIn('foreign', {row['group_id'] for row in all_items})
        self.assertTrue(all(row['evidence_view_ref']['input_digest'] == 'evidence-generation' for row in all_items))

    def test_missing_experience_is_explicit_not_blocking(self):
        """Input: absent experience file. Output: None; assert successful empty result with explanation."""
        result = self.query('experience')
        self.assertEqual(result['items'], [])
        self.assertTrue(any('experience_unavailable' in str(w) for w in result['warnings']))

    def test_experience_cross_scope_opt_in_preserves_negative_evidence_and_original_scope(self):
        """Input: USA negative/inconclusive history and ALL request. Output: None; allow explicit transfer, not market proof."""
        original_scope = dict(self.scope)
        period = dict(start='2014-01-01', end='2023-12-29')
        self.scope.update(region='ALL', universe='LARGE')
        groups = [dict(group_id='g' + str(i), experiment_id='e' + str(i), measurement_period=period,
                       experiment=dict(arms=[dict(scope=original_scope)]), cohort=dict(scope=original_scope),
                       label=label, mechanism_families=['sentiment'], limitations=['limited_comparability'])
                  for i, label in enumerate(('contradicts_prediction_in_scope', 'inconclusive'))]
        groups.append(dict(groups[0], group_id='exact', experiment_id='exact', cohort=dict(scope=self.scope)))
        raw = self.write_json('machine/mechanism_evidence.json', dict(input_digest='original', groups=groups))
        default = self.query('experience')
        self.assertEqual([row['group_id'] for row in default['items']], ['exact'])
        self.assertEqual(default, self.query('experience', include_other_scopes=False))
        result = self.query('experience', query='sentiment', include_other_scopes=True)
        self.assertEqual(result['total'], 3)
        cards = {row['group_id']: row for row in result['items']}
        self.assertEqual(cards['exact']['scope_relation'], 'exact')
        for group in groups[:2]:
            card = cards[group['group_id']]
            self.assertEqual(card['scope_relation'], 'transfer_only')
            self.assertEqual(card['scope'], original_scope)
            self.assertEqual(card['measurement_period'], period)
            self.assertEqual(card['experiment'], group['experiment'])
            self.assertEqual(card['cohort'], group['cohort'])
            self.assertEqual(card['label'], group['label'])
            self.assertIn('not proof in the requested market', card['scope_warning'])
        self.assertTrue(any('not proof in the requested market' in str(w) for w in result['warnings']))
        self.assertEqual((self.root / 'machine/mechanism_evidence.json').read_bytes(), raw)

    def test_cross_scope_flag_is_experience_only_and_requires_exact_boolean(self):
        """Input: nonboolean opt-ins and other operations. Output: None; reject implicit scope widening."""
        for value in (1, 0, 'true', None, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'include_other_scopes'):
                self.query('experience', include_other_scopes=value)
        for operation in ('fields', 'operators', 'templates', 'source'):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, 'unknown query arguments'):
                self.query(operation, include_other_scopes=True)
        self.backend.query_fields.assert_not_called()

    def test_queries_are_deterministic_and_do_not_write(self):
        """Input: immutable source fixture. Output: None; compare responses and all fixture bytes."""
        row = self.source('raw/platform/learn/guide.json', {'description': 'immutable'})
        before = {path.relative_to(self.root).as_posix(): path.read_bytes()
                  for path in self.root.rglob('*') if path.is_file()}
        first = self.query('source', path=row['path'])
        self.assertEqual(first, self.query('source', path=row['path']))
        self.query('experience')
        after = {path.relative_to(self.root).as_posix(): path.read_bytes()
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_reject_oversize_instead_of_truncating_identity(self):
        """Input: oversized identity. Output: None; reject instead of returning a shortened identity."""
        self.backend.query_fields.return_value['items'][0]['field_id'] = 'x' * 100000
        with self.assertRaisesRegex(ValueError, 'response.*bound'):
            self.query('fields')

    def test_argument_errors_are_not_silently_ignored(self):
        """Input: invalid argument combinations. Output: None; assert explicit contract errors."""
        for operation, arguments in [('validate', {}), ('fields', {'limit': True}),
                ('operators', {'typo': 'x'}), ('source', {'path': 'x', 'length': 1000000}),
                ('fields', {'identities': [['d', 'f']], 'query': 'f'}),
                ('fields', {'identities': [['d', 'f'], ['d', 'f']]})]:
            with self.subTest(operation=operation, arguments=arguments), self.assertRaises(ValueError):
                self.query(operation, **arguments)


if __name__ == '__main__':
    unittest.main()
