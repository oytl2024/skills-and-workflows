"""Offline fake-vault acceptance for catalog admission, not semantic release."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
import socket


class ResearchResourceCatalogTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated vault Path with authentic indexed catalogs."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = datetime.now(timezone.utc) - timedelta(hours=1)
        self.stamp = self.now.isoformat()
        self.scope = dict(instrument_type='EQUITY', region='USA', delay=1,
                          universe='TOP3000', as_of=datetime.now(timezone.utc).isoformat())
        self.fields = [dict(dataset_id='sample', field_id='pulse', field_type='VECTOR',
                            available_scopes=[{k: self.scope[k] for k in self.scope if k != 'as_of'}],
                            source_updated_at=self.stamp[:10], source_paths=['raw/platform/data_fields/sample.json'])]
        self.operators = [dict(id='catalog_op', source_paths=['raw/platform/learn/operators.json'])]
        self.raw_fields = [dict(field=dict(id='pulse', type='VECTOR'), data_set=dict(id='sample'),
                                scope=self.fields[0]['available_scopes'][0], generated_at=self.stamp)]
        self.raw_operators = [dict(id='catalog_op')]
        self.index = []
        self.refresh()

    def write_rows(self, name, rows):
        """Input: resource name str/rows list. Output: None; write a fake canonical JSONL."""
        path = self.root / 'machine' / (name + '.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

    def refresh(self):
        """Input: fixture state. Output: None; bind actual raw bytes to canonical index hashes."""
        self.index = []
        for path, value, source_type, family in [
                ('raw/platform/data_fields/sample.json', self.raw_fields, 'platform_data_field_capture', 'raw/platform/data_fields'),
                ('raw/platform/learn/operators.json', self.raw_operators, 'platform_learn_material', 'raw/platform/learn')]:
            raw = json.dumps(value).encode()
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            self.index.append(dict(path=path, content_hash=hashlib.sha256(raw).hexdigest(),
                                   captured_at=self.stamp, source_type=source_type, source_family=family))
        self.write_rows('data_ledger', self.fields)
        self.write_rows('operator_ledger', self.operators)
        self.write_rows('source_index', self.index)

    def read(self, count=1, max_fields=30):
        """Input: count/field limit ints. Output: actual catalog resources/diagnostics tuple."""
        module = importlib.import_module('wqb.research_resource_catalog')
        return module.read_catalog_resources(self.root, self.scope, count,
                                             settings={'decay': 0}, max_fields_per_lane=max_fields)

    def add_optional_published_definition(self):
        """Input: fixture state. Output: real sourced ts_delta dict and temporary published-generation Path."""
        from tests.test_resource_evidence import page_operator_fixture
        operator, index, texts = page_operator_fixture()
        self.raw_operators.append(dict(name='ts_delta', scope=['REGULAR'], category='Time Series',
                                       definition='ts_delta(x, d)', description='Current raw API wording.'))
        self.refresh()
        for path, text in texts.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode('utf-8'))
        self.index.extend(index.values())
        self.write_rows('source_index', self.index)
        operators = (json.dumps(operator) + '\n').encode()
        release_id = hashlib.sha256(operators).hexdigest()
        generation = self.root / 'machine/semantic_releases' / release_id
        generation.mkdir(parents=True)
        manifest = dict(schema_version=1, resource_contract_version=2, release_id=release_id,
                        generated_at=self.stamp, source_refs=[], resources={}, wiki={})
        for name, raw in (('operator_ledger', operators), ('template_library', b'')):
            filename = name + '.jsonl'
            (generation / filename).write_bytes(raw)
            manifest['resources'][name] = dict(path=filename, sha256=hashlib.sha256(raw).hexdigest())
        raw = json.dumps(manifest).encode()
        (generation / 'manifest.json').write_bytes(raw)
        (self.root / 'machine/semantic_release.json').write_text(json.dumps(dict(
            schema_version=1, release_id=release_id, manifest_sha256=hashlib.sha256(raw).hexdigest())), encoding='utf-8')
        return operator, generation

    def test_optional_release_enriches_technical_definition_not_admission(self):
        published, _ = self.add_optional_published_definition()
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        operators = {row['operator']: row for row in resources[0]['operator_rows']}
        self.assertEqual(set(operators), {'catalog_op', 'ts_delta'})
        selected = operators['ts_delta']
        self.assertEqual(selected.get('definition'), published['definition'], diagnostics)
        self.assertEqual(selected.get('definition_basis'), published['definition_basis'])
        self.assertEqual(selected['raw_definition'], 'ts_delta(x, d)')
        self.assertEqual(selected['raw_description'], 'Current raw API wording.')
        self.assertNotIn('definition', operators['catalog_op'])
        for ref in published['definition']['evidence_refs']:
            self.assertIn(ref['source_path'], selected['source_paths'])
            self.assertIn(ref['source_path'], resources[0]['source_index'])
            self.assertIn(ref['source_path'], resources[0]['source_texts'])
        from wqb.resource_evidence import catalog_operator_definition
        verified = catalog_operator_definition(selected, resources[0]['source_index'], resources[0]['source_texts'])
        self.assertEqual(verified, published['definition'])

    def test_invalid_enrichment_keeps_untyped_catalog_operator_visible(self):
        published, _ = self.add_optional_published_definition()
        path = published['definition']['evidence_refs'][0]['source_path']
        original = deepcopy(self.index)
        for failure in ('stale', 'hash', 'unindexed'):
            with self.subTest(failure=failure):
                self.index = deepcopy(original)
                row = next(r for r in self.index if r['path'] == path)
                if failure == 'stale':
                    row['captured_at'] = '2020-01-01T00:00:00Z'
                elif failure == 'hash':
                    row['content_hash'] = '0' * 64
                else:
                    self.index.remove(row)
                self.write_rows('source_index', self.index)
                resources, diagnostics = self.read()
                operators = {r['operator']: r for r in resources[0]['operator_rows']}
                self.assertEqual(set(operators), {'catalog_op', 'ts_delta'})
                self.assertNotIn('definition', operators['ts_delta'])
                self.assertNotIn('definition_basis', operators['ts_delta'])
                self.assertTrue(any(d.get('code') == 'operator_enrichment_rejected' for d in diagnostics), diagnostics)

    def test_oversized_optional_release_is_not_read_or_required(self):
        _, generation = self.add_optional_published_definition()
        from wqb.semantic_compilation import MAX_SOURCE_BYTES
        source = generation / 'operator_ledger.jsonl'
        source.write_bytes(b' ' * (MAX_SOURCE_BYTES + 1))
        original = Path.read_bytes

        def guarded(path):
            """Input: Path. Output: bytes; forbid blindly reading oversized optional publication."""
            self.assertNotEqual(path, source)
            return original(path)

        Path.read_bytes = guarded
        try:
            resources, diagnostics = self.read()
        finally:
            Path.read_bytes = original
        self.assertEqual({r['operator'] for r in resources[0]['operator_rows']}, {'catalog_op', 'ts_delta'})
        self.assertTrue(any(d.get('code') == 'operator_enrichment_unavailable' for d in diagnostics), diagnostics)

    def test_catalog_without_release_or_optional_metadata_is_visible(self):
        original_socket = socket.socket
        def forbidden(*args, **kwargs):
            """Input: arbitrary socket arguments. Output: never; forbid network creation."""
            raise AssertionError('network forbidden')
        socket.socket = forbidden
        try:
            resources, diagnostics = self.read()
        finally:
            socket.socket = original_socket
        self.assertEqual(len(resources), 1, diagnostics)
        resource = resources[0]
        self.assertEqual(resource['field_rows'], self.fields)
        self.assertEqual(resource['operator_rows'][0]['operator'], 'catalog_op')
        self.assertNotIn('definition', resource['operator_rows'][0])
        self.assertEqual(resource['settings'], {'decay': 0})
        for context in (resource, resource['evidence_pack']):
            self.assertEqual(context['resource_contract_version'], 2)
            self.assertEqual(context['resource_admission_policy'], 'knowledge_catalog_v1')
        pack = resource['evidence_pack']
        self.assertIn('field:sample/pulse', pack['allowed_role_semantics'])
        self.assertEqual(pack['source_index'], resource['source_index'])
        self.assertEqual(resource['source_index'], {r['path']: r for r in self.index})
        self.assertEqual(pack['source_texts'], resource['source_texts'])
        self.assertEqual(pack['scope'], self.scope)
        from wqb.hypothesis_design import INTENTS, _pack
        self.assertEqual(pack['allowed_operator_intents'], list(INTENTS))
        self.assertEqual(set(_pack(pack)['allowed_operator_intents']), set(INTENTS))
        self.assertTrue(any(d.get('code') == 'missing_operator_signature' for d in diagnostics))
        self.assertTrue(any(d.get('severity') == 'warning' for d in diagnostics))

    def test_actual_phrases_tags_and_technical_definition_are_preserved(self):
        self.raw_fields[0]['field'].update(description='Literal pulse', tags=['reported'])
        definition = dict(parameters=[dict(name='x', type='VECTOR')], output_type='MATRIX')
        self.raw_operators[0].update(definition=definition, description='Literal transform')
        self.fields[0].update(field_description='Literal pulse', semantic_tags=['reported'])
        self.refresh()
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        resource = resources[0]
        self.assertEqual({key: value for key, value in resource['operator_rows'][0]['definition'].items()
                          if key != 'evidence_refs'}, definition)
        self.assertEqual(resource['operator_rows'][0]['definition']['evidence_refs'][0]['source_path'],
                         self.index[1]['path'])
        self.assertEqual(resource['operator_rows'][0]['raw_description'], 'Literal transform')
        self.assertTrue({'field:sample/pulse', 'Literal pulse', 'reported'} <=
                        set(resource['evidence_pack']['allowed_role_semantics']))

    def test_bad_raw_identity_type_scope_hash_and_dates_are_diagnosed(self):
        for failure in ('identity', 'type', 'scope', 'hash', 'stale', 'future', 'invalid_date', 'missing_path'):
            with self.subTest(failure=failure):
                original_fields, original_raw = deepcopy(self.fields), deepcopy(self.raw_fields)
                if failure == 'identity':
                    self.raw_fields[0]['field']['id'] = 'different'
                elif failure == 'type':
                    self.raw_fields[0]['field']['type'] = 'MATRIX'
                elif failure == 'scope':
                    self.raw_fields[0]['scope'] = dict(self.raw_fields[0]['scope'], universe='TOP1000')
                elif failure in ('stale', 'future', 'invalid_date'):
                    self.fields[0]['source_updated_at'] = {'stale': '2020-01-01', 'future': '2099-01-01',
                                                         'invalid_date': 'unknown'}[failure]
                elif failure == 'missing_path':
                    self.fields[0]['source_paths'] = ['raw/platform/data_fields/absent.json']
                self.refresh()
                if failure == 'hash':
                    self.index[0]['content_hash'] = '0' * 64
                    self.write_rows('source_index', self.index)
                resources, diagnostics = self.read()
                self.assertEqual(resources, [], diagnostics)
                self.assertTrue(any(d.get('severity') == 'excluded' for d in diagnostics), diagnostics)
                self.fields, self.raw_fields = original_fields, original_raw

    def test_bounded_lanes_and_duplicate_identity_fail_closed(self):
        for number in range(35):
            row, raw = deepcopy(self.fields[0]), deepcopy(self.raw_fields[0])
            row['field_id'] = raw['field']['id'] = 'f' + str(number)
            self.fields.append(row)
            self.raw_fields.append(raw)
        self.refresh()
        resources, diagnostics = self.read(count=2, max_fields=30)
        self.assertEqual([len(r['field_rows']) for r in resources], [30, 6], diagnostics)
        selected = [r['field_id'] for resource in resources for r in resource['field_rows']]
        self.assertEqual(len(set(selected)), 36)
        self.fields.append(deepcopy(self.fields[0]))
        self.refresh()
        resources, diagnostics = self.read(count=2)
        self.assertNotIn('pulse', [r['field_id'] for resource in resources for r in resource['field_rows']])
        self.assertTrue(any('duplicate' in d['reason'] for d in diagnostics))

    def test_malformed_lines_do_not_hide_valid_neighbors(self):
        path = self.root / 'machine/data_ledger.jsonl'
        path.write_text('null\n{broken\n' + path.read_text(), encoding='utf-8')
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        self.assertEqual(sum(d.get('code') == 'malformed_catalog_row' for d in diagnostics), 2)

    def test_operator_explicit_identity_and_untyped_visibility(self):
        self.operators.extend([dict(source_paths=self.operators[0]['source_paths']),
                               dict(id='other', operator='catalog_op', source_paths=self.operators[0]['source_paths'])])
        self.refresh()
        resources, diagnostics = self.read()
        self.assertEqual([r['operator'] for r in resources[0]['operator_rows']], ['catalog_op'])
        self.assertTrue(any(d.get('code') == 'invalid_operator' for d in diagnostics))

    def test_latest_indexed_operator_capture_supersedes_old_ledger(self):
        path = 'raw/platform/data_fields/' + self.stamp[:10] + '/operators.json'
        definition = dict(parameters=[dict(name='x', type='MATRIX')], output_type='MATRIX')
        payload = dict(operators=[dict(name='fresh_op', definition=definition), dict(name='untyped_op')])
        raw = json.dumps(payload).encode()
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        self.index.append(dict(path=path, captured_at=(self.now + timedelta(minutes=1)).isoformat(),
                               content_hash=hashlib.sha256(raw).hexdigest(),
                               source_type='platform_learn_material', source_family='raw/platform/learn'))
        self.write_rows('source_index', self.index)
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        operators = {r['operator']: r for r in resources[0]['operator_rows']}
        self.assertEqual(set(operators), {'fresh_op', 'untyped_op'})
        self.assertEqual({key: value for key, value in operators['fresh_op']['definition'].items()
                          if key != 'evidence_refs'}, definition)
        self.assertNotIn('definition', operators['untyped_op'])
        self.assertNotIn('x', operators)
        self.assertEqual(operators['fresh_op']['source_paths'], [path])

    def test_embedded_typed_operators_without_ledger_are_visible(self):
        path = self.fields[0]['source_paths'][0]
        definition = dict(description='Returns the delayed difference.', input_types=['MATRIX'],
                          output_type='MATRIX', parameters=[dict(name='x', type='MATRIX', required=True),
                                                          dict(name='d', type='INTEGER', required=True)])
        # A field id and its nested parameter name are not operator identities.
        payload = dict(fields=self.raw_fields, operators=[dict(operator='ts_delta', definition=definition)])
        raw = json.dumps(payload).encode()
        (self.root / path).write_bytes(raw)
        self.index[0]['content_hash'] = hashlib.sha256(raw).hexdigest()
        self.write_rows('source_index', [self.index[0]])
        (self.root / 'machine/operator_ledger.jsonl').unlink()
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        operators = resources[0]['operator_rows']
        self.assertEqual([r['operator'] for r in operators], ['ts_delta'], diagnostics)
        self.assertEqual(operators[0]['source_paths'], [path])
        actual = deepcopy(operators[0]['definition'])
        refs = actual.pop('evidence_refs')
        self.assertEqual(actual, definition)
        self.assertEqual(refs, [dict(source_path=path, sha256=self.index[0]['content_hash'],
                                    capture_date=self.stamp[:10], kind='documented', experiment_refs=[])])
        self.assertEqual(resources[0]['source_index'], {path: self.index[0]})

    def test_selected_field_rows_are_not_implicit_operator_catalogs(self):
        self.write_rows('source_index', [self.index[0]])
        self.write_rows('operator_ledger', [])
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        self.assertEqual(resources[0]['operator_rows'], [])

    def test_indexed_markdown_operators_without_ledger_or_description(self):
        path = 'raw/platform/learn/latest/operators.md'
        text = '# Operators\n\n### `visible_op`\n\n- Source id: `visible_op`\n- Definition: `visible_op(x)`\n'
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8', newline='\n')
        self.index = [r for r in self.index if 'operators' not in r['path']]
        self.index.append(dict(path=path, captured_at=self.stamp, content_hash=hashlib.sha256(text.encode()).hexdigest(),
                               source_type='platform_learn_material', source_family='raw/platform/learn'))
        self.write_rows('source_index', self.index)
        self.write_rows('operator_ledger', [])
        resources, diagnostics = self.read()
        self.assertEqual([r['operator'] for r in resources[0]['operator_rows']], ['visible_op'], diagnostics)
        self.assertEqual(resources[0]['operator_rows'][0]['raw_definition'], 'visible_op(x)')
        self.assertNotIn('definition', resources[0]['operator_rows'][0])

    def test_invalid_bounds_are_rejected(self):
        for count, maximum in ((True, 30), (0, 30), (1, 0), (1, 31)):
            with self.subTest(count=count, maximum=maximum), self.assertRaises(ValueError):
                self.read(count, maximum)

    def test_stale_index_and_conflicting_full_file_hash_fail_closed(self):
        for key, value in (('captured_at', '2020-01-01T00:00:00Z'), ('file_sha256', '0' * 64)):
            with self.subTest(key=key):
                self.refresh()
                self.index[0][key] = value
                self.write_rows('source_index', self.index)
                resources, diagnostics = self.read()
                self.assertEqual(resources, [], diagnostics)

    def test_raw_capture_date_cannot_be_renewed_by_fresh_ledger(self):
        self.raw_fields[0]['generated_at'] = '2020-01-01T00:00:00Z'
        self.refresh()
        resources, diagnostics = self.read()
        self.assertEqual(resources, [], diagnostics)

    def test_existing_verified_extract_avoids_whole_large_original(self):
        from wqb.knowledge_contracts import extract_field_source_subset
        from wqb.semantic_compilation import MAX_SOURCE_BYTES
        path = 'raw/platform/data_fields/' + self.stamp[:10] + '/data_fields.jsonl'
        source = self.root / path
        source.parent.mkdir(parents=True, exist_ok=True)
        selected = deepcopy(self.raw_fields[0])
        selected.update(capture_generation_id='fixture', endpoint='/data-fields')
        fillers = []
        for number in range(3):
            item = deepcopy(selected)
            item['field'] = dict(id='padding' + str(number), type='MATRIX', description='x' * 800_000)
            fillers.append(item)
        source.write_text(''.join(json.dumps(r) + '\n' for r in [selected, *fillers]), encoding='utf-8', newline='\n')
        source.with_name('manifest.json').write_text(json.dumps(dict(
            generated_at=self.stamp, capture_generation_id='fixture', scope=selected['scope'],
            certification_status='partial', field_count=4, error_count=1)), encoding='utf-8')
        self.assertGreater(source.stat().st_size, MAX_SOURCE_BYTES)
        for row in self.index:
            row.update(contents='Fixture', update_check='Fixture')
        self.write_rows('source_index', self.index)
        result = extract_field_source_subset(self.root, path, [dict(
            dataset_id='sample', field_id='pulse', scope=selected['scope'])])
        self.fields[0]['source_paths'] = [path]
        self.write_rows('data_ledger', self.fields)
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        original = Path.read_bytes

        def guarded(file):
            """Input: Path. Output: bytes; original must be verified by streaming, never full read."""
            self.assertNotEqual(file, source)
            return original(file)

        Path.read_bytes = guarded
        try:
            resources, diagnostics = self.read()
        finally:
            Path.read_bytes = original
        self.assertEqual(len(resources), 1, diagnostics)
        self.assertEqual(resources[0]['field_rows'], self.fields)
        self.assertIn(result['excerpt_path'], resources[0]['source_texts'])
        registered = {r['path']: r for r in map(json.loads, (self.root / 'machine/source_index.jsonl').read_text().splitlines())}
        self.assertEqual(resources[0]['source_index'][result['excerpt_path']], registered[result['excerpt_path']])
        self.assertNotIn(path, resources[0]['source_texts'])
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in self.root.rglob('*') if p.is_file()})

    def test_ledger_only_typed_claim_is_not_invented_as_raw_definition(self):
        # No operator inventory filename: exercise the canonical ledger fallback.
        old = self.operators[0]['source_paths'][0]
        path = 'raw/platform/learn/documentation.json'
        self.operators[0]['source_paths'] = [path]
        self.operators[0]['definition'] = dict(output_type='MATRIX')
        self.refresh()
        (self.root / path).write_bytes((self.root / old).read_bytes())
        self.index[1]['path'] = path
        self.write_rows('source_index', self.index)
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        self.assertEqual([r['operator'] for r in resources[0]['operator_rows']], ['catalog_op'])
        self.assertNotIn('definition', resources[0]['operator_rows'][0])
        self.assertTrue(any(d.get('code') == 'unverified_operator_signature' for d in diagnostics))

    def test_bounded_catalog_scan_cannot_certify_unscanned_shadow_identity(self):
        from wqb import research_resource_catalog as catalog
        original = catalog.MAX_CATALOG_ROWS
        self.write_rows('data_ledger', [self.fields[0], self.fields[0]])
        catalog.MAX_CATALOG_ROWS = 1
        try:
            resources, diagnostics = self.read()
        finally:
            catalog.MAX_CATALOG_ROWS = original
        self.assertEqual(resources, [], diagnostics)
        self.assertTrue(any(d.get('code') == 'unreadable_catalog' for d in diagnostics))

    def test_stale_catalog_prefix_cannot_starve_fresh_sample(self):
        stale = []
        for number in range(150):
            row = deepcopy(self.fields[0])
            row.update(field_id='stale' + str(number), source_updated_at='2020-01-01')
            stale.append(row)
        self.write_rows('data_ledger', [*stale, *self.fields])
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        self.assertEqual(resources[0]['field_rows'][0]['field_id'], 'pulse')

    def test_diagnostic_saturation_does_not_hide_fatal_scan(self):
        from wqb import research_resource_catalog as catalog
        limits = catalog.MAX_DIAGNOSTICS, catalog.MAX_CATALOG_ROWS
        self.write_rows('data_ledger', [self.fields[0], None, self.fields[0]])
        catalog.MAX_DIAGNOSTICS, catalog.MAX_CATALOG_ROWS = 1, 2
        try:
            resources, diagnostics = self.read()
        finally:
            catalog.MAX_DIAGNOSTICS, catalog.MAX_CATALOG_ROWS = limits
        self.assertEqual(resources, [], diagnostics)
        self.assertLessEqual(len(diagnostics), 1)

    def test_invalid_raw_prefix_is_verified_before_selection_limit(self):
        invalid = []
        for number in range(125):
            row = deepcopy(self.fields[0])
            row.update(field_id='absent' + str(number))
            invalid.append(row)
        self.write_rows('data_ledger', [*invalid, *self.fields])
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        self.assertEqual(resources[0]['field_rows'][0]['field_id'], 'pulse')
        self.assertEqual(self.read()[0], resources)

    def test_late_duplicate_refills_from_previously_full_stream(self):
        first = deepcopy(self.fields[0])
        for number in range(3):
            row, raw = deepcopy(first), deepcopy(self.raw_fields[0])
            row['field_id'] = raw['field']['id'] = 'later' + str(number)
            self.fields.append(row)
            self.raw_fields.append(raw)
        self.fields.append(first)
        self.refresh()
        resources, diagnostics = self.read(max_fields=2)
        self.assertEqual(len(resources), 1, diagnostics)
        self.assertEqual([r['field_id'] for r in resources[0]['field_rows']], ['later0', 'later1'])
        self.assertEqual(self.read(max_fields=2)[0], resources)

    def test_operator_jsonl_record_byte_limit_is_enforced(self):
        from wqb import research_resource_catalog as catalog
        line = json.dumps(dict(operator='large', description='x' * catalog.MAX_LINE_BYTES))
        with self.assertRaisesRegex(ValueError, 'byte bound'):
            catalog._operator_facts(line + '\n', jsonl=True)

    def test_exact_scope_lane_can_mix_signal_and_group_datasets(self):
        row, raw = deepcopy(self.fields[0]), deepcopy(self.raw_fields[0])
        row.update(dataset_id='classifications', field_id='pulse', field_type='GROUP')
        raw['data_set']['id'] = row['dataset_id']
        raw['field']['type'] = 'GROUP'
        self.fields.append(row)
        self.raw_fields.append(raw)
        self.refresh()
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        self.assertEqual({(r['dataset_id'], r['field_id'], r['field_type']) for r in resources[0]['field_rows']},
                         {('sample', 'pulse', 'VECTOR'), ('classifications', 'pulse', 'GROUP')})
        self.assertTrue({'field:sample/pulse', 'field:classifications/pulse'} <=
                        set(resources[0]['evidence_pack']['allowed_role_semantics']))

    def test_indexed_jsonl_operator_records_are_not_lost(self):
        path = 'raw/platform/learn/operators.jsonl'
        definition = dict(parameters=[dict(name='x', type='MATRIX')], output_type='MATRIX')
        raw = ('\n'.join(json.dumps(r) for r in [dict(operator='jsonl_op', definition=definition),
                                                dict(operator='untyped_jsonl_op')]) + '\n').encode()
        (self.root / path).write_bytes(raw)
        self.index[1].update(path=path, content_hash=hashlib.sha256(raw).hexdigest())
        self.write_rows('source_index', self.index)
        self.write_rows('operator_ledger', [])
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        operators = {r['operator']: r for r in resources[0]['operator_rows']}
        self.assertEqual(set(operators), {'jsonl_op', 'untyped_jsonl_op'}, diagnostics)
        self.assertEqual({key: value for key, value in operators['jsonl_op']['definition'].items()
                          if key != 'evidence_refs'}, definition)
        self.assertNotIn('x', operators)

    def test_metadata_and_duplicated_lane_output_obey_context_byte_limit(self):
        from wqb import research_resource_catalog as catalog
        original = catalog.MAX_CONTEXT_BYTES
        for location in ('index', 'operator', 'output'):
            with self.subTest(location=location):
                self.fields = self.fields[:1]
                self.raw_fields = self.raw_fields[:1]
                self.operators = self.operators[:1]
                self.operators[0].pop('opaque_catalog_metadata', None)
                if location == 'operator':
                    self.operators[0]['opaque_catalog_metadata'] = 'x' * 20_000
                if location == 'output':
                    field, raw = deepcopy(self.fields[0]), deepcopy(self.raw_fields[0])
                    field['field_id'] = raw['field']['id'] = 'other'
                    self.fields.append(field)
                    self.raw_fields.append(raw)
                self.refresh()
                if location == 'index':
                    self.index[0]['contents'] = 'x' * 20_000
                    self.write_rows('source_index', self.index)
                if location == 'output':
                    baseline, _ = self.read(count=2, max_fields=1)
                    size = len(json.dumps(baseline, ensure_ascii=False, separators=(',', ':')).encode())
                    catalog.MAX_CONTEXT_BYTES = size - 1
                else:
                    catalog.MAX_CONTEXT_BYTES = 10_000
                try:
                    resources, diagnostics = self.read(count=2 if location == 'output' else 1, max_fields=1)
                    output_bytes = len(json.dumps(resources, ensure_ascii=False, separators=(',', ':')).encode())
                    self.assertLessEqual(output_bytes, catalog.MAX_CONTEXT_BYTES, diagnostics)
                    if location != 'output':
                        self.assertEqual(resources, [], diagnostics)
                    self.assertTrue(any('bound' in d['reason'] or 'limit' in d['reason'] for d in diagnostics), diagnostics)
                finally:
                    catalog.MAX_CONTEXT_BYTES = original

    def test_oversized_raw_is_not_read_blindly_or_written(self):
        from wqb.semantic_compilation import MAX_SOURCE_BYTES
        source = self.root / self.fields[0]['source_paths'][0]
        source.write_bytes(b' ' * (MAX_SOURCE_BYTES + 1))
        before = {p.relative_to(self.root) for p in self.root.rglob('*')}
        original = Path.read_bytes

        def guarded(path):
            """Input: Path. Output: bytes; fail if the reader attempts whole oversized-source IO."""
            self.assertNotEqual(path, source)
            return original(path)

        Path.read_bytes = guarded
        try:
            resources, diagnostics = self.read()
        finally:
            Path.read_bytes = original
        self.assertEqual(resources, [])
        self.assertTrue(diagnostics)
        self.assertEqual(before, {p.relative_to(self.root) for p in self.root.rglob('*')})

    def add_field_source(self, name, padding=0):
        """Input: field name str/padding bytes int. Output: ledger row dict; register isolated authentic fixture source."""
        row, raw = deepcopy(self.fields[0]), deepcopy(self.raw_fields[0])
        path = 'raw/platform/data_fields/' + name + '.json'
        row.update(field_id=name, source_paths=[path])
        raw['field']['id'] = name
        raw['opaque_capture_metadata'] = 'x' * padding
        content = json.dumps([raw]).encode('utf-8')
        (self.root / path).write_bytes(content)
        self.index.append(dict(self.index[0], path=path, content_hash=hashlib.sha256(content).hexdigest()))
        self.write_rows('source_index', self.index)
        return row

    def test_incomplete_operator_ledger_cannot_supply_fallback_prefix(self):
        """Input: over-bound fallback ledger. Output: no lanes; independent inventories are absent."""
        from wqb import research_resource_catalog as catalog
        old = self.operators[0]['source_paths'][0]
        path = 'raw/platform/learn/documentation.json'
        (self.root / old).rename(self.root / path)
        self.index[1]['path'] = path
        self.operators[0]['source_paths'] = [path]
        self.write_rows('source_index', self.index)
        self.write_rows('operator_ledger', self.operators)
        with (self.root / 'machine/operator_ledger.jsonl').open('ab') as stream:
            stream.write(b'x' * (catalog.MAX_LINE_BYTES + 1) + b'\n')
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 0, diagnostics)
        self.assertTrue(any(d.get('resource') == 'operator_ledger' for d in diagnostics))

    def test_independent_operator_inventory_survives_incomplete_ledger(self):
        """Input: authentic current inventory plus broken ledger. Output: inventory-derived operators remain visible."""
        from wqb import research_resource_catalog as catalog
        with (self.root / 'machine/operator_ledger.jsonl').open('ab') as stream:
            stream.write(b'x' * (catalog.MAX_LINE_BYTES + 1) + b'\n')
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        self.assertEqual([r['operator'] for r in resources[0]['operator_rows']], ['catalog_op'])

    def test_lane_byte_limit_splits_without_truncating_source_evidence(self):
        """Input: two individually usable sources exceeding the combined compiler cap. Output: two intact deterministic lanes."""
        from wqb import research_resource_catalog as catalog
        from wqb.hypothesis_design import MAX_JSON_BYTES
        from wqb.hypothesis_template_compiler import _resources
        from wqb.generator import build_settings
        from wqb.config import DEFAULT_CONFIG
        fields = [self.add_field_source(name, 260_000) for name in ('first', 'second')]
        self.write_rows('data_ledger', fields)
        settings = build_settings(dict(DEFAULT_CONFIG, region='USA', delay=1, universe='TOP3000'))
        resources, diagnostics = catalog.read_catalog_resources(self.root, self.scope, 2, settings=settings)
        self.assertEqual(len(resources), 2, diagnostics)
        self.assertEqual([[r['field_id'] for r in lane['field_rows']] for lane in resources], [['first'], ['second']])
        for lane in resources:
            self.assertLessEqual(catalog._size(lane), MAX_JSON_BYTES)
            _resources(lane, self.scope)
            for path, text in lane['source_texts'].items():
                self.assertEqual(text, (self.root / path).read_text(encoding='utf-8'))
        repeated, _ = catalog.read_catalog_resources(self.root, self.scope, 2, settings=settings)
        self.assertEqual(resources, repeated)

    def test_single_source_over_compiler_limit_refills_and_preserves_other_lanes(self):
        """Input: usable fields surrounding an indispensable 600KB original. Output: usable lanes plus exact technical exclusion."""
        from wqb import research_resource_catalog as catalog
        from wqb.hypothesis_design import MAX_JSON_BYTES
        fields = [self.add_field_source(name, padding) for name, padding in
                  [('first', 0), ('too_large', 600_000), ('last', 0)]]
        self.write_rows('data_ledger', fields)
        resources, diagnostics = self.read(count=2, max_fields=1)
        self.assertEqual([r['field_rows'][0]['field_id'] for r in resources], ['first', 'last'], diagnostics)
        exclusions = [d for d in diagnostics if d.get('code') == 'technical_context_limit']
        self.assertTrue(any(d.get('field_id') == 'too_large' and str(MAX_JSON_BYTES) in d['reason']
                            for d in exclusions), diagnostics)
        for resource in resources:
            self.assertLessEqual(catalog._size(resource), MAX_JSON_BYTES)

    def test_indispensable_single_source_over_compiler_limit_is_not_returned(self):
        """Input: only one source whose duplicated evidence exceeds 1MB. Output: technical blocker, never truncated evidence."""
        field = self.add_field_source('too_large', 600_000)
        self.write_rows('data_ledger', [field])
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 0, diagnostics)
        self.assertTrue(any(d.get('code') == 'technical_context_limit' and
                            'indispensable' in d['reason'] for d in diagnostics), diagnostics)

    def test_existing_extract_can_fit_original_below_source_cap_but_above_lane_cap(self):
        """Input: preexisting certified extract of a sub-2MB original. Output: intact extract-based lane, no vault writes."""
        from wqb.knowledge_contracts import extract_field_source_subset
        from wqb.hypothesis_design import MAX_JSON_BYTES
        from wqb import research_resource_catalog as catalog
        path = 'raw/platform/data_fields/' + self.stamp[:10] + '/data_fields.jsonl'
        source = self.root / path
        source.parent.mkdir(parents=True, exist_ok=True)
        selected = deepcopy(self.raw_fields[0])
        selected.update(capture_generation_id='fixture', endpoint='/data-fields')
        padding = deepcopy(selected)
        padding['field'] = dict(id='padding', type='MATRIX', description='x' * 600_000)
        source.write_text(''.join(json.dumps(r) + '\n' for r in [selected, padding]), encoding='utf-8', newline='\n')
        source.with_name('manifest.json').write_text(json.dumps(dict(
            generated_at=self.stamp, capture_generation_id='fixture', scope=selected['scope'],
            certification_status='partial', field_count=2, error_count=1)), encoding='utf-8')
        for row in self.index:
            row.update(contents='Fixture', update_check='Fixture')
        self.write_rows('source_index', self.index)
        result = extract_field_source_subset(self.root, path, [dict(
            dataset_id='sample', field_id='pulse', scope=selected['scope'])])
        self.fields[0]['source_paths'] = [path]
        self.write_rows('data_ledger', self.fields)
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        self.assertEqual(resources[0]['field_rows'], self.fields)
        self.assertLessEqual(catalog._size(resources[0]), MAX_JSON_BYTES)
        self.assertNotIn(path, resources[0]['source_texts'])
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in self.root.rglob('*') if p.is_file()})

    def add_typed_markdown_operator(self, *, duplicate=False):
        """Input: duplicate-heading bool. Output: indexed Markdown source path str with no economic Description."""
        path = 'raw/platform/learn/current/operators.md'
        section = ('### `typed_op`\n\n- Source id: `typed_op`\n'
                   '- Input types: `MATRIX`\n- Output type: `MATRIX`\n- Parameters:\n'
                   '  - `x`: type=`MATRIX`, required=`true`\n')
        text = '# Operators\n\n' + section * (2 if duplicate else 1)
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8', newline='\n')
        self.index = [self.index[0], dict(self.index[1], path=path,
                                       content_hash=hashlib.sha256(text.encode()).hexdigest())]
        self.write_rows('source_index', self.index)
        self.write_rows('operator_ledger', [])
        return path

    def test_typed_markdown_without_description_keeps_verified_technical_facts(self):
        """Input: explicit typed Markdown without Description. Output: usable technical signature and explicit unknown note."""
        from wqb.resource_evidence import catalog_operator_definition
        path = self.add_typed_markdown_operator()
        resources, diagnostics = self.read()
        operator = resources[0]['operator_rows'][0]
        self.assertIsInstance(operator.get('definition'), dict, diagnostics)
        self.assertEqual(operator['definition']['input_types'], ['MATRIX'])
        self.assertIn('unavailable', operator['definition']['description'])
        self.assertNotIn('raw_description', operator)
        verified = catalog_operator_definition(operator, resources[0]['source_index'], resources[0]['source_texts'])
        self.assertEqual(verified['output_type'], 'MATRIX')
        self.assertEqual(verified['evidence_refs'][0]['source_path'], path)

    def test_duplicate_typed_markdown_headings_report_ambiguity(self):
        """Input: duplicate technical Markdown headings. Output: explicit source ambiguity, no hidden selected definition."""
        self.add_typed_markdown_operator(duplicate=True)
        resources, diagnostics = self.read()
        self.assertEqual(resources[0]['operator_rows'], [], diagnostics)
        self.assertTrue(any(d.get('code') == 'invalid_operator_source' and 'ambiguous' in d['reason']
                            for d in diagnostics), diagnostics)

    def test_late_matrix_fields_seed_each_bounded_lane_without_hiding_vectors(self):
        """Input: VECTOR prefix longer than selection capacity, then two MATRIX fields. Output: two distinct mixed typed lanes."""
        self.fields, self.raw_fields = [], []
        for number in range(10):
            field_type = 'VECTOR' if number < 8 else 'MATRIX'
            name = 'field' + str(number)
            self.fields.append(dict(dataset_id='sample', field_id=name, field_type=field_type,
                available_scopes=[{k: self.scope[k] for k in self.scope if k != 'as_of'}],
                source_updated_at=self.stamp[:10], source_paths=['raw/platform/data_fields/sample.json']))
            self.raw_fields.append(dict(field=dict(id=name, type=field_type), data_set=dict(id='sample'),
                scope=self.fields[-1]['available_scopes'][0], generated_at=self.stamp))
        self.refresh()
        resources, diagnostics = self.read(count=2, max_fields=3)
        self.assertEqual(len(resources), 2, diagnostics)
        identities = []
        for resource in resources:
            rows = resource['field_rows']
            self.assertLessEqual(len(rows), 3)
            self.assertTrue(any(r['field_type'] == 'MATRIX' for r in rows), diagnostics)
            self.assertTrue(any(r['field_type'] == 'VECTOR' for r in rows), diagnostics)
            identities.extend((r['dataset_id'], r['field_id']) for r in rows)
            for row in rows:
                self.assertEqual(row['field_type'], next(r['field_type'] for r in self.fields
                                                       if r['field_id'] == row['field_id']))
            self.assert_matrix_lane_compiles(resource)
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(resources, self.read(count=2, max_fields=3)[0])

    def test_missing_matrix_capacity_is_explicit_technical_selection_gap(self):
        """Input: visible VECTOR-only pool. Output: unchanged fields and technical strategy diagnostic, not semantic rejection."""
        resources, diagnostics = self.read(count=2)
        self.assertEqual(resources[0]['field_rows'][0]['field_type'], 'VECTOR')
        self.assertTrue(any(d.get('code') == 'technical_selection_gap' and 'MATRIX' in d['reason']
                            for d in diagnostics), diagnostics)

    def test_technical_selection_gap_survives_warning_saturation(self):
        """Input: VECTOR-only pool with one diagnostic slot. Output: visible technical selection blocker despite optional warnings."""
        from wqb import research_resource_catalog as catalog
        original = catalog.MAX_DIAGNOSTICS
        catalog.MAX_DIAGNOSTICS = 1
        try:
            resources, diagnostics = self.read(count=2)
        finally:
            catalog.MAX_DIAGNOSTICS = original
        self.assertEqual(len(resources), 1)
        self.assertEqual(diagnostics[0]['code'], 'technical_selection_gap')

    def test_request_count_is_a_cap_not_a_minimum_matrix_lane_count(self):
        """Input: one MATRIX and one VECTOR, requested cap four. Output: one compatible mixed view, no fabricated fields."""
        matrix, raw = deepcopy(self.fields[0]), deepcopy(self.raw_fields[0])
        matrix.update(field_id='matrix', field_type='MATRIX')
        raw['field'].update(id='matrix', type='MATRIX')
        self.fields.append(matrix)
        self.raw_fields.append(raw)
        self.refresh()
        resources, diagnostics = self.read(count=4)
        self.assertEqual(len(resources), 1, diagnostics)
        self.assertEqual({r['field_type'] for r in resources[0]['field_rows']}, {'MATRIX', 'VECTOR'})
        self.assertEqual(len(resources[0]['field_rows']), 2)
        self.assert_matrix_lane_compiles(resources[0])

    def assert_matrix_lane_compiles(self, resource, *, kind='level', source_path=None):
        """Input: resource dict containing actual MATRIX/feature kind str. Output: None; assert existing DSL compiles without coercion."""
        from tests.test_hypothesis_design import fixture
        from wqb.config import DEFAULT_CONFIG
        from wqb.generator import build_settings
        from wqb.hypothesis_design import validate_hypothesis_design, compile_hypothesis_design
        from wqb.semantic_contracts import SemanticPolicy
        row = next(row for row in resource['field_rows'] if row['field_type'] == 'MATRIX')
        source = resource['source_index'][source_path or row['source_paths'][0]]
        answer, _ = fixture()
        design = answer['designs'][0]
        if kind == 'change':
            feature = dict(kind='change', input=dict(kind='role', role='pulse'), horizon=5)
            design['feature_plan'] = feature
            design['experiment_plan']['baseline'] = deepcopy(feature)
        design['trigger_id'] = source['path']
        design['field_roles'] = [dict(name='pulse', field_type='MATRIX', required_metadata=[],
                                     required_semantics=['field:' + row['dataset_id'] + '/' + row['field_id']])]
        design['evidence_refs'] = [dict(source_path=source['path'], sha256=source['content_hash'],
                                      capture_date=source['captured_at'][:10], kind='hypothesis', experiment_refs=[])]
        normalized = validate_hypothesis_design(answer, resource['evidence_pack'], SemanticPolicy())['designs'][0]
        resource = dict(resource, settings=build_settings(dict(DEFAULT_CONFIG, region='USA', delay=1, universe='TOP3000')))
        result = compile_hypothesis_design(normalized, resource, self.scope)
        self.assertEqual(result['status'], 'compiled', result)

    def prepare_measured_extract(self, filler_count=1):
        """Input: fixture state/filler count int. Output: existing extract result/settings dicts; create only temporary evidence."""
        from wqb.knowledge_contracts import extract_field_source_subset
        from wqb.config import DEFAULT_CONFIG
        from wqb.generator import build_settings
        path = 'raw/platform/data_fields/' + self.stamp[:10] + '/data_fields.jsonl'
        self.fields[0].update(field_type='MATRIX', coverage=0.8, coverage_status='measured_raw',
                              source_quality='platform_raw_capture', source_paths=[path])
        selected = deepcopy(self.raw_fields[0])
        selected['field'].update(type='MATRIX', coverage=0.8)
        selected.update(capture_generation_id='fixture', endpoint='/data-fields')
        padding = deepcopy(selected)
        padding['field'] = dict(id='padding', type='MATRIX', description='x' * 600_000)
        source = self.root / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(''.join(json.dumps(r) + '\n' for r in [selected, *[padding] * filler_count]),
                          encoding='utf-8', newline='\n')
        source.with_name('manifest.json').write_text(json.dumps(dict(
            generated_at=self.stamp, capture_generation_id='fixture', scope=selected['scope'],
            certification_status='partial', field_count=filler_count + 1, error_count=1)), encoding='utf-8')
        for row in self.index:
            row.update(contents='Fixture', update_check='Fixture')
        self.write_rows('source_index', self.index)
        result = extract_field_source_subset(self.root, path, [dict(
            dataset_id='sample', field_id='pulse', scope=selected['scope'])])
        self.write_rows('data_ledger', self.fields)
        settings = build_settings(dict(DEFAULT_CONFIG, region='USA', delay=1, universe='TOP3000'))
        return result, settings

    def validate_against_canonical(self, resource, *, index=None):
        """Input: resource dict/optional canonical index dict. Output: validated dict from actual Start integration."""
        from wqb.preplanned_start import _validate_resource
        if index is None:
            index = {r['path']: r for r in map(json.loads,
                     (self.root / 'machine/source_index.jsonl').read_text(encoding='utf-8').splitlines())}
        ledger = [json.loads(line) for line in (self.root / 'machine/data_ledger.jsonl').read_text(encoding='utf-8').splitlines()]
        return _validate_resource(self.root, resource, self.scope, ledger, index)

    def test_reader_verified_extract_reaches_start_with_canonical_field_identity(self):
        """Input: authentic measured ledger and preexisting verified extract. Output: Start validates without rewriting canonical rows."""
        from wqb import research_resource_catalog as catalog
        result, settings = self.prepare_measured_extract()
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        resources, diagnostics = catalog.read_catalog_resources(self.root, self.scope, 1, settings=settings)
        self.assertEqual(len(resources), 1, diagnostics)
        checked = self.validate_against_canonical(resources[0])
        self.assertEqual(checked['field_rows'], self.fields)
        self.assertIn(result['excerpt_path'], checked['source_texts'])
        self.assertNotIn(result['source_path'], checked['source_texts'])
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in self.root.rglob('*') if p.is_file()})

    def test_verified_extract_reaches_template_compiler_without_rewriting_ledger(self):
        """Input: canonical field plus verified excerpt. Output: compiled Level with actual excerpt evidence."""
        from wqb import research_resource_catalog as catalog
        result, settings = self.prepare_measured_extract()
        resources, diagnostics = catalog.read_catalog_resources(self.root, self.scope, 1, settings=settings)
        self.assertEqual(len(resources), 1, diagnostics)
        checked = self.validate_against_canonical(resources[0])
        self.assert_matrix_lane_compiles(checked, source_path=result['excerpt_path'])
        self.assertEqual(checked['field_rows'], self.fields)

    def test_extract_mapping_does_not_waive_canonical_field_digest(self):
        """Input: extract-backed resource with a changed field snapshot. Output: unchanged exact canonical digest rejection."""
        from wqb import research_resource_catalog as catalog
        _, settings = self.prepare_measured_extract()
        resources, diagnostics = catalog.read_catalog_resources(self.root, self.scope, 1, settings=settings)
        self.assertEqual(len(resources), 1, diagnostics)
        resources[0]['field_rows'][0]['coverage'] = 0.9
        with self.assertRaisesRegex(ValueError, 'changed exact-scope ledger field'):
            self.validate_against_canonical(resources[0])

    def test_start_rechecks_existing_extract_receipt_not_only_markdown_hash(self):
        """Input: extracted view followed by a contradictory immutable receipt. Output: Start rejects the source proof."""
        from wqb import research_resource_catalog as catalog
        result, settings = self.prepare_measured_extract()
        resources, diagnostics = catalog.read_catalog_resources(self.root, self.scope, 1, settings=settings)
        self.assertEqual(len(resources), 1, diagnostics)
        receipt = self.root / result['receipt_path']
        data = json.loads(receipt.read_text(encoding='utf-8'))
        data['identity']['original_sha256'] = '0' * 64
        receipt.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.validate_against_canonical(resources[0])

    def test_reader_rejects_corrupted_existing_extract_instead_of_inventing_evidence(self):
        """Input: corrupted existing excerpt bytes. Output: technical exclusion and no admitted field."""
        from wqb import research_resource_catalog as catalog
        result, settings = self.prepare_measured_extract()
        excerpt = self.root / result['excerpt_path']
        excerpt.write_bytes(excerpt.read_bytes() + b'corrupted')
        resources, diagnostics = catalog.read_catalog_resources(self.root, self.scope, 1, settings=settings)
        self.assertEqual(len(resources), 0, diagnostics)
        self.assertTrue(any(d.get('code') in ('invalid_field', 'technical_context_limit') for d in diagnostics))

    def test_extract_mapping_preserves_measured_coverage_comparison(self):
        """Input: canonical claimed coverage contradicting authentic extracted measurement. Output: Start rejects the measured mismatch."""
        from wqb import research_resource_catalog as catalog
        _, settings = self.prepare_measured_extract()
        self.fields[0]['coverage'] = 0.9
        self.write_rows('data_ledger', self.fields)
        resources, diagnostics = catalog.read_catalog_resources(self.root, self.scope, 1, settings=settings)
        self.assertEqual(len(resources), 1, diagnostics)
        with self.assertRaisesRegex(ValueError, 'measured coverage missing or differs'):
            self.validate_against_canonical(resources[0])

    def test_extract_mapping_requires_matching_original_registration_and_age(self):
        """Input: authentic extract but inconsistent caller canonical original metadata. Output: hash/date/registration rejection."""
        from wqb import research_resource_catalog as catalog
        result, settings = self.prepare_measured_extract()
        resources, diagnostics = catalog.read_catalog_resources(self.root, self.scope, 1, settings=settings)
        self.assertEqual(len(resources), 1, diagnostics)
        canonical = {r['path']: r for r in map(json.loads,
                     (self.root / 'machine/source_index.jsonl').read_text(encoding='utf-8').splitlines())}
        for failure in ('hash', 'date', 'missing'):
            with self.subTest(failure=failure):
                index = deepcopy(canonical)
                if failure == 'hash':
                    index[result['source_path']]['content_hash'] = '0' * 64
                elif failure == 'date':
                    index[result['source_path']]['captured_at'] = '2020-01-01T00:00:00Z'
                else:
                    index.pop(result['source_path'])
                with self.assertRaises(ValueError):
                    self.validate_against_canonical(resources[0], index=index)

    def test_large_original_extract_reaches_start_without_whole_original_reads(self):
        """Input: existing measured extract of a >2MB original. Output: canonical Start validation using receipt streaming only."""
        from wqb import research_resource_catalog as catalog
        result, settings = self.prepare_measured_extract(filler_count=4)
        source = self.root / result['source_path']
        self.assertGreater(source.stat().st_size, catalog.MAX_SOURCE_BYTES)
        original_read = Path.read_bytes

        def guarded(path):
            """Input: Path. Output: bytes; reject unbounded reads of the original while allowing streaming receipt verification."""
            self.assertNotEqual(path, source)
            return original_read(path)

        Path.read_bytes = guarded
        try:
            resources, diagnostics = catalog.read_catalog_resources(self.root, self.scope, 1, settings=settings)
            self.assertEqual(len(resources), 1, diagnostics)
            checked = self.validate_against_canonical(resources[0])
        finally:
            Path.read_bytes = original_read
        self.assertEqual(checked['field_rows'], self.fields)
        self.assertLessEqual(catalog._size(checked), catalog.MAX_JSON_BYTES)

    def check_typed_json_source_compiles(self, *, jsonl, description=True):
        """Input: JSONL mode bool. Output: None; reader-derived complete raw technical signature compiles without a semantic release."""
        self.fields[0]['field_type'] = self.raw_fields[0]['field']['type'] = 'MATRIX'
        definition = dict(description='Economic interpretation is unknown; captured technical declaration only.',
            input_types=['MATRIX'], output_type='MATRIX', parameters=[
                dict(name='x', type='MATRIX', required=True), dict(name='d', type='INTEGER', required=True)])
        if not description:
            definition.pop('description')
        self.raw_operators = [dict(operator='ts_delta', definition=definition)]
        self.refresh()
        self.write_rows('operator_ledger', [])
        path = self.index[1]['path']
        if jsonl:
            path = 'raw/platform/learn/operators.jsonl'
            raw = (json.dumps(self.raw_operators[0]) + '\n').encode('utf-8')
            (self.root / path).write_bytes(raw)
            self.index[1].update(path=path, content_hash=hashlib.sha256(raw).hexdigest())
            self.write_rows('source_index', self.index)
        resources, diagnostics = self.read()
        self.assertEqual(len(resources), 1, diagnostics)
        self.assert_matrix_lane_compiles(resources[0], kind='change')
        actual = deepcopy(resources[0]['operator_rows'][0]['definition'])
        refs = actual.pop('evidence_refs')
        expected = dict(definition)
        expected.setdefault('description', 'Economic description unavailable; technical declaration only.')
        self.assertEqual(actual, expected)
        self.assertEqual(refs, [dict(source_path=path, sha256=self.index[1]['content_hash'],
                                    capture_date=self.stamp[:10], kind='documented', experiment_refs=[])])
        self.assertNotIn('evidence_refs', self.raw_operators[0]['definition'])
        self.assertFalse((self.root / 'machine/semantic_release.json').exists())

    def test_complete_typed_json_without_refs_reaches_existing_compiler(self):
        """Input: complete typed JSON source with no copied evidence refs. Output: successful reader-to-change-DSL compilation."""
        self.check_typed_json_source_compiles(jsonl=False)

    def test_complete_typed_jsonl_without_refs_reaches_existing_compiler(self):
        """Input: complete typed JSONL source with no copied evidence refs. Output: successful reader-to-change-DSL compilation."""
        self.check_typed_json_source_compiles(jsonl=True)

    def test_typed_json_unknown_description_is_not_a_signature_gate(self):
        """Input: typed JSON/JSONL without economic description. Output: technical Change compiles with an explicit unknown note."""
        for jsonl in (False, True):
            with self.subTest(jsonl=jsonl):
                self.check_typed_json_source_compiles(jsonl=jsonl, description=False)


if __name__ == '__main__':
    unittest.main()
