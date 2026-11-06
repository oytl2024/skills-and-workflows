"""Offline K3 field explanations: immutable selection is not factual authority."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from wqb.data_ledger import data_ledger_record_from_dict, data_ledger_record_to_dict
from wqb.data_ledger_compile import compile_data_ledger_from_raw
from wqb import knowledge_compile


SCOPE = dict(instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000')


def write_json(path, value):
    """Input: Path/JSON value. Output: None. Write isolated fixture JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding='utf-8')


class FieldSemanticEnrichmentTests(unittest.TestCase):
    def setUp(self):
        """Input: None. Output: None. Build certified raw and shared job fixtures in a temporary vault."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.capture = self.root / 'raw/platform/data_fields/2026-10-15'
        self.raw = dict(scope=SCOPE, capture_generation_id='g1', data_set=dict(id='d'),
                        field=dict(id='f', type='MATRIX', description='Cash balance', coverage=0.8,
                                   units='USD', available_at='2026-10-14T00:00:00Z'))
        write_json(self.capture / 'data_fields.jsonl', self.raw)
        write_json(self.capture / 'manifest.json', dict(generated_at='2026-10-15T00:00:00Z',
                   certification_status='complete', requested_matrix=[SCOPE]))
        write_json(self.capture / 'scopes.jsonl', dict(scope=SCOPE, status='completed',
                   certification_status='complete', capture_generation_id='g1'))
        compile_data_ledger_from_raw(self.root, self.capture)
        self.ledger = self.root / 'machine/data_ledger.jsonl'
        self.row = json.loads(self.ledger.read_text(encoding='utf-8'))
        relative = 'raw/platform/data_fields/2026-10-15/data_fields.jsonl'
        digest = hashlib.sha256((self.root / relative).read_bytes()).hexdigest()
        self.source = dict(path=relative, content_hash=digest, captured_at='2026-10-15T00:00:00Z',
                           source_type='platform_data_field_capture', source_family='raw/platform/data_fields')
        write_json(self.root / 'machine/source_index.jsonl', self.source)
        self.evidence = dict(source_path=relative, sha256=digest, capture_date='2026-10-15', kind='documented', experiment_refs=[])
        self.target = dict(dataset_id='d', field_id='f', field_type='MATRIX', allowed_scopes=[SCOPE],
                           literal_fact_explanation='Cash balance', facts=dict(units=self.fact('units', 'USD')),
                           hypothesis_cards=[], missing_facts=['polarity', 'cadence'])
        self.result = dict(schema_version=1, status='validated', source_index={relative: self.source}, fields=[self.target])
        self.attach()

    def fact(self, key, value):
        """Input: fact key str/value. Output: dict. Create an exact-field documented JSON premise."""
        return dict(value=value, premises=[dict(evidence_ref=self.evidence, locator=dict(kind='json_value',
                    row_identity=dict(dataset_id='d', field_id='f', scope=SCOPE),
                    value_path=['field', key], expected_value=value))])

    def attach(self):
        """Input: None. Output: None. Select exact job bytes from the canonical ledger row."""
        path = self.root / 'machine/semantic_jobs/job/field_explanations.json'
        write_json(path, self.result)
        self.row['field_semantics_ref'] = dict(schema_version=1, path=path.relative_to(self.root).as_posix(),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), dataset_id='d', field_id='f')

    def resolve(self, row=None):
        """Input: optional row dict. Output: resolver dict. Exercise the public consumer interface."""
        return knowledge_compile.resolve_field_semantics(self.root, self.row if row is None else row)

    def test_optional_reference_roundtrip_and_legacy_omission(self):
        self.assertNotIn('field_semantics_ref', data_ledger_record_to_dict(data_ledger_record_from_dict({})))
        self.assertEqual(data_ledger_record_to_dict(data_ledger_record_from_dict(self.row)), self.row)
        for key, value in [('schema_version', True), ('schema_version', 2), ('sha256', 'wrong'),
                           ('path', '../escape'), ('field_id', 'other')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                bad = deepcopy(self.row)
                bad['field_semantics_ref'][key] = value
                data_ledger_record_from_dict(bad)

    def test_absent_reference_remains_readable(self):
        row = dict(self.row)
        row.pop('field_semantics_ref')
        self.assertEqual(self.resolve(row)['status'], 'absent')

    def test_valid_reference_verifies_facts_without_promoting_hypotheses(self):
        from wqb.semantic_contracts import CARD_FIELDS
        self.target['hypothesis_cards'] = [dict(hypothesis_card={key: 'A test hypothesis' for key in CARD_FIELDS},
            evidence_refs=[dict(self.evidence, kind='hypothesis')])]
        self.attach()
        before = deepcopy(self.row)
        result = self.resolve()
        self.assertEqual(result['status'], 'supported', result)
        self.assertEqual(result['facts'], {'units': 'USD'})
        self.assertEqual(result['hypothesis_cards'], self.target['hypothesis_cards'])
        self.assertIn('polarity', result['missing_facts'])
        self.assertEqual(before, self.row)

    def test_verified_user_hypothesis_keeps_independent_official_facts(self):
        from wqb.semantic_contracts import CARD_FIELDS
        relative = 'raw/user/ideas/cash.md'
        path = self.root / relative
        path.parent.mkdir(parents=True)
        path.write_text('A cash buffer may matter under financing constraints.', encoding='utf-8')
        source = dict(path=relative, content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            captured_at='2026-10-15T00:00:00Z', source_type='user_note', source_family='raw/user')
        with (self.root / 'machine/source_index.jsonl').open('a', encoding='utf-8') as handle:
            handle.write('\n' + json.dumps(source))
        self.result['source_index'][relative] = source
        ref = dict(source_path=relative, sha256=source['content_hash'], capture_date='2026-10-15',
                   kind='hypothesis', experiment_refs=[])
        self.target['hypothesis_cards'] = [dict(hypothesis_card={key: 'A cash buffer hypothesis' for key in CARD_FIELDS},
            evidence_refs=[ref])]
        self.attach()
        result = self.resolve()
        self.assertEqual(result['status'], 'supported', result)
        self.assertEqual(result['facts'], {'units': 'USD'})
        self.assertEqual(result['hypothesis_cards'], self.target['hypothesis_cards'])
        ref['kind'] = 'documented'
        self.attach()
        self.assertEqual(self.resolve()['status'], 'rejected')

    def test_path_digest_identity_scope_and_current_fact_mismatches_reject(self):
        mutations = [dict(dataset_id='other'), dict(field_id='other'), dict(field_type='VECTOR'),
                     dict(region='EUR'), dict(delay=0), dict(universe='TOP500'), dict(coverage=0.1),
                     dict(source_updated_at='2026-10-16'), dict(field_description='Different meaning'),
                     dict(source_paths=[]), dict(coverage_status='partial')]
        for change in mutations:
            with self.subTest(change=change):
                row = dict(self.row, **change)
                # Changing the primary scope must not be hidden by available_scopes.
                self.assertEqual(self.resolve(row)['status'], 'rejected')
        for path in ('../escape.json', 'machine/other.json', '/absolute',
                     'machine/semantic_jobs/../outside.json', 'machine\\semantic_jobs\\job\\x'):
            with self.subTest(path=path):
                row = deepcopy(self.row)
                row['field_semantics_ref']['path'] = path
                self.assertEqual(self.resolve(row)['status'], 'rejected')
        row = deepcopy(self.row)
        row['field_semantics_ref']['sha256'] = '0' * 64
        self.assertEqual(self.resolve(row)['status'], 'rejected')

    def test_changed_source_generation_and_conflicting_index_reject(self):
        self.raw['capture_generation_id'] = 'g2'
        write_json(self.capture / 'data_fields.jsonl', self.raw)
        self.assertEqual(self.resolve()['status'], 'rejected')
        self.raw['capture_generation_id'] = 'g1'
        write_json(self.capture / 'data_fields.jsonl', self.raw)
        write_json(self.root / 'machine/source_index.jsonl', dict(self.source, captured_at='2026-10-16T00:00:00Z'))
        self.assertEqual(self.resolve()['status'], 'rejected')

    def test_duplicate_targets_unknown_keys_and_unsupported_claims_reject(self):
        original = deepcopy(self.result)
        for mutation in ('duplicate', 'unknown', 'literal', 'hypothesis_fact', 'wrong_premise', 'timing'):
            self.result = deepcopy(original)
            self.target = self.result['fields'][0]
            if mutation == 'duplicate':
                self.result['fields'].append(deepcopy(self.target))
            elif mutation == 'unknown':
                self.target['trusted'] = True
            elif mutation == 'literal':
                self.target['literal_fact_explanation'] = 'Cash always predicts profit'
            elif mutation == 'hypothesis_fact':
                self.target['facts']['units']['premises'][0]['evidence_ref']['kind'] = 'hypothesis'
            elif mutation == 'wrong_premise':
                self.target['facts']['units']['premises'][0]['locator']['row_identity']['field_id'] = 'other'
            else:
                self.target['facts']['timing_contract'] = dict(value={'kind': 'model_guess'}, premises=[])
            self.attach()
            with self.subTest(mutation=mutation):
                self.assertEqual(self.resolve()['status'], 'rejected')

    def test_recompile_preserves_reference_raw_optional_and_usage_not_historical_scope(self):
        self.row.update(simulation_usage_count=7, submitted_usage_count=2, submitted_alpha_ids=['a'],
                        submitted_legacy_usage_count=1, repair_usage_count=3)
        write_json(self.ledger, self.row)
        compile_data_ledger_from_raw(self.root, self.capture)
        rebuilt = json.loads(self.ledger.read_text(encoding='utf-8'))
        for key in ('field_semantics_ref', 'units', 'available_at', 'simulation_usage_count',
                    'submitted_usage_count', 'submitted_alpha_ids', 'submitted_legacy_usage_count', 'repair_usage_count'):
            self.assertEqual(rebuilt.get(key), self.row[key], key)
        self.assertEqual(self.resolve(rebuilt)['status'], 'supported')
        self.raw['capture_generation_id'] = 'g2'
        write_json(self.capture / 'data_fields.jsonl', self.raw)
        write_json(self.capture / 'scopes.jsonl', dict(scope=SCOPE, status='completed',
                   certification_status='complete', capture_generation_id='g2'))
        compile_data_ledger_from_raw(self.root, self.capture)
        changed = json.loads(self.ledger.read_text(encoding='utf-8'))
        self.assertNotIn('field_semantics_ref', changed)
        self.assertTrue(changed['field_semantics_history'])
        self.assertEqual(changed['simulation_usage_count'], 7)
        self.assertEqual(self.resolve(changed)['status'], 'absent')

    def test_merge_never_inherits_optional_values_or_coverage_from_other_scope(self):
        from wqb.data_ledger_compile import merge_field_enrichment
        captured = dict(self.row, universe='TOP500', available_scopes=[dict(SCOPE, universe='TOP500')], coverage=0.2)
        captured.pop('field_semantics_ref')
        captured.pop('units')
        captured.pop('available_at')
        merged = merge_field_enrichment(self.root, captured, self.row)
        self.assertNotIn('units', merged)
        self.assertNotIn('field_semantics_ref', merged)
        self.assertEqual(merged['coverage'], 0.2)

    def test_linked_job_directory_is_rejected(self):
        import os
        original = self.root / 'machine/semantic_jobs/job'
        alias = self.root / 'machine/semantic_jobs/alias'
        try:
            os.symlink(original, alias, target_is_directory=True)
        except OSError:
            self.skipTest('Windows symlink creation unavailable')
        self.row['field_semantics_ref']['path'] = 'machine/semantic_jobs/alias/field_explanations.json'
        self.assertEqual(self.resolve()['status'], 'rejected')

    def test_scope_outcome_generation_change_invalidates_old_selector(self):
        write_json(self.capture / 'scopes.jsonl', dict(scope=SCOPE, status='completed',
                   certification_status='complete', capture_generation_id='g2'))
        self.assertEqual(self.resolve()['status'], 'rejected')

    def test_capture_manifest_date_must_match_current_ledger_provenance(self):
        manifest = json.loads((self.capture / 'manifest.json').read_text(encoding='utf-8'))
        manifest['generated_at'] = '2026-10-16T00:00:00Z'
        write_json(self.capture / 'manifest.json', manifest)
        self.assertEqual(self.resolve()['status'], 'rejected')

    def test_rejected_legacy_timing_retains_diagnostic_history(self):
        from wqb.data_ledger_compile import merge_field_enrichment
        from tests.test_resource_evidence import timing_contract
        prior = dict(self.row, timing_contract=timing_contract())
        prior.pop('field_semantics_ref')
        merged = merge_field_enrichment(self.root, self.row, prior)
        self.assertNotIn('timing_contract', merged)
        self.assertEqual(merged['field_semantics_history'][0]['reference'],
                         {'timing_contract': prior['timing_contract']})
        self.assertEqual(data_ledger_record_to_dict(data_ledger_record_from_dict(merged)), merged)

    def test_asserted_source_digest_and_duplicate_canonical_index_reject(self):
        source = deepcopy(self.source)
        source['file_sha256'] = '0' * 64
        self.result['source_index'][source['path']] = source
        self.attach()
        self.assertEqual(self.resolve()['status'], 'rejected')
        self.result['source_index'][source['path']] = self.source
        self.attach()
        (self.root / 'machine/source_index.jsonl').write_text(
            json.dumps(self.source) + '\n' + json.dumps(dict(self.source, source_type='other')) + '\n', encoding='utf-8')
        self.assertEqual(self.resolve()['status'], 'rejected')

    def test_enrichment_history_is_idempotent_and_cannot_reactivate_reference(self):
        from wqb.data_ledger_compile import merge_field_enrichment
        prior = deepcopy(self.row)
        prior['field_semantics_ref']['sha256'] = '0' * 64
        captured = dict(self.row)
        captured.pop('field_semantics_ref')
        first = merge_field_enrichment(self.root, captured, prior)
        second = merge_field_enrichment(self.root, captured, first)
        self.assertEqual(first, second)
        self.assertEqual(self.resolve(second)['status'], 'absent')

    def test_prior_generation_fact_cannot_fill_current_missing_metadata(self):
        old_path = 'raw/platform/data_fields/2026-10-14/data_fields.jsonl'
        write_json(self.root / old_path, self.raw)
        old_source = dict(self.source, path=old_path)
        old_evidence = dict(self.evidence, source_path=old_path)
        self.raw['field'].pop('units')
        write_json(self.capture / 'data_fields.jsonl', self.raw)
        self.row.pop('units')
        current = dict(self.source, content_hash=hashlib.sha256((self.capture / 'data_fields.jsonl').read_bytes()).hexdigest())
        self.result['source_index'] = {current['path']: current, old_path: old_source}
        self.target['facts']['units']['premises'][0]['evidence_ref'] = old_evidence
        (self.root / 'machine/source_index.jsonl').write_text(
            json.dumps(current) + '\n' + json.dumps(old_source) + '\n', encoding='utf-8')
        self.attach()
        self.assertEqual(self.resolve()['status'], 'rejected')

    def certified_large_extract(self):
        """Input: None. Output: extraction dict. Use the real bounded extractor on a >2MB capture fixture."""
        from wqb.knowledge_contracts import SourceIndexRow, update_source_index, extract_field_source_subset
        from wqb.semantic_compilation import MAX_SOURCE_BYTES
        self.raw.update(endpoint='/data-fields', generated_at='2026-10-15T00:00:00Z')
        padding = [dict(self.raw, field=dict(id='padding_' + str(i), type='MATRIX', description='x' * 1000))
                   for i in range(2200)]
        source = self.capture / 'data_fields.jsonl'
        source.write_bytes((''.join(json.dumps(row) + '\n' for row in [*padding, self.raw])).encode('utf-8'))
        self.assertGreater(source.stat().st_size, MAX_SOURCE_BYTES)
        write_json(self.capture / 'manifest.json', dict(generated_at='2026-10-15T00:00:00Z', scope=SCOPE,
            capture_generation_id='g1', certification_status='complete', requested_matrix=[SCOPE], field_count=2201))
        relative = source.relative_to(self.root).as_posix()
        update_source_index(self.root, [SourceIndexRow(path=relative, source_type='platform_data_field_capture',
            source_family='raw/platform/data_fields', contents='Captured fixture fields', update_check='compare source bytes',
            captured_at='2026-10-15T00:00:00Z', record_count=2201, content_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
            content_status='raw_jsonl')])
        extracted = extract_field_source_subset(self.root, relative, [dict(dataset_id='d', field_id='f', scope=SCOPE)])
        index = {row['path']: row for row in (json.loads(line) for line in
            (self.root / 'machine/source_index.jsonl').read_text(encoding='utf-8').splitlines())}
        excerpt_path = extracted['excerpt_path']
        self.result['source_index'] = {excerpt_path: index[excerpt_path]}
        self.target['facts']['units']['premises'][0]['evidence_ref'] = dict(self.evidence,
            source_path=excerpt_path, sha256=index[excerpt_path]['content_hash'])
        self.attach()
        return extracted

    def test_certified_excerpt_maps_large_original_without_unbounded_reads_or_provenance_rewrite(self):
        from unittest.mock import patch
        extracted = self.certified_large_extract()
        original = self.capture / 'data_fields.jsonl'
        row_before = deepcopy(self.row)
        read_text, read_bytes = Path.read_text, Path.read_bytes

        def bounded_text(path, *args, **kwargs):
            """Input: Path/read arguments. Output: str. Reject whole-original reads during resolution."""
            self.assertNotEqual(path, original, 'original must be streamed by the existing receipt verifier')
            return read_text(path, *args, **kwargs)

        def bounded_bytes(path, *args, **kwargs):
            """Input: Path/read arguments. Output: bytes. Reject whole-original reads during resolution."""
            self.assertNotEqual(path, original, 'original must be streamed by the existing receipt verifier')
            return read_bytes(path, *args, **kwargs)

        with patch.object(Path, 'read_text', bounded_text), patch.object(Path, 'read_bytes', bounded_bytes):
            result = self.resolve()
        self.assertEqual(result['status'], 'supported', result)
        self.assertEqual(result['facts'], {'units': 'USD'})
        self.assertEqual(self.row, row_before)
        self.assertEqual(result['source_proofs'][0]['source_path'], extracted['source_path'])
        self.assertEqual(result['source_proofs'][0]['proof_path'], extracted['excerpt_path'])
        receipt = json.loads((self.root / extracted['receipt_path']).read_text(encoding='utf-8'))
        self.assertEqual(receipt['identity']['source_path'], self.row['source_paths'][0])

    def test_certified_excerpt_rejects_mutated_original_receipt_wrong_scope_and_coverage(self):
        extracted = self.certified_large_extract()
        self.assertEqual(self.resolve()['status'], 'supported', self.resolve())
        self.assertEqual(self.resolve(dict(self.row, coverage=0.1))['status'], 'rejected')
        self.assertEqual(self.resolve(dict(self.row, universe='TOP500',
            available_scopes=[dict(SCOPE, universe='TOP500')]))['status'], 'rejected')
        receipt_path = self.root / extracted['receipt_path']
        original_receipt = receipt_path.read_bytes()
        receipt = json.loads(original_receipt)
        receipt['row_receipts'][0]['row_sha256'] = '0' * 64
        write_json(receipt_path, receipt)
        self.assertEqual(self.resolve()['status'], 'rejected')
        receipt_path.write_bytes(original_receipt)
        with (self.capture / 'data_fields.jsonl').open('ab') as stream:
            stream.write(b'\n')
        self.assertEqual(self.resolve()['status'], 'rejected')

    def test_legacy_timing_can_use_certified_excerpt_of_current_original(self):
        from tests.test_resource_evidence import page_timing_fixture
        from wqb.knowledge_contracts import SourceIndexRow, update_source_index, extract_field_source_subset
        from wqb.data_ledger_compile import merge_field_enrichment
        contract, field, _, index, texts = page_timing_fixture()
        old_path = 'raw/platform/data_fields/fields.jsonl'
        original = self.capture / 'data_fields.jsonl'
        original_path = original.relative_to(self.root).as_posix()
        payload = json.loads(texts.pop(old_path))
        payload['capture_generation_id'] = 'g1'
        write_json(original, payload)
        write_json(self.capture / 'manifest.json', dict(generated_at='2026-10-15T00:00:00Z', scope=SCOPE,
            capture_generation_id='g1', certification_status='complete', requested_matrix=[SCOPE]))
        update_source_index(self.root, [SourceIndexRow(path=original_path, source_type='platform_data_field_capture',
            source_family='raw/platform/data_fields', contents='Timing fixture', update_check='compare',
            captured_at='2026-10-15T00:00:00Z', record_count=1, content_hash=hashlib.sha256(original.read_bytes()).hexdigest(),
            content_status='raw_jsonl')])
        extracted = extract_field_source_subset(self.root, original_path,
            [dict(dataset_id=field['dataset_id'], field_id=field['field_id'], scope=SCOPE)])
        index.pop(old_path)
        for path, text in texts.items():
            destination = self.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(text.encode('utf-8'))
        with (self.root / 'machine/source_index.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(''.join(json.dumps(source) + '\n' for source in index.values()))
        for premise in contract['premises']:
            if premise['evidence_ref']['source_path'] == old_path:
                premise['evidence_ref'].update(source_path=extracted['excerpt_path'],
                                               sha256=json.loads((self.root / extracted['receipt_path']).read_text())['body_sha256'])
                premise['locator']['expected_value'] = deepcopy(payload)
        compile_data_ledger_from_raw(self.root, self.capture)
        captured = json.loads(self.ledger.read_text(encoding='utf-8'))
        prior = dict(captured, timing_contract=contract)
        merged = merge_field_enrichment(self.root, captured, prior)
        self.assertEqual(merged.get('timing_contract'), contract, merged.get('field_semantics_history'))

    def test_windows_junction_job_directory_is_rejected(self):
        import os
        import subprocess
        if os.name != 'nt':
            self.skipTest('Windows junction regression')
        alias = self.root / 'machine/semantic_jobs/junction'
        completed = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias),
                                    str(self.root / 'machine/semantic_jobs/job')], capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.row['field_semantics_ref']['path'] = 'machine/semantic_jobs/junction/field_explanations.json'
        self.assertEqual(self.resolve()['status'], 'rejected')

    def test_valid_documented_timing_survives_recompile_without_historical_row_copy(self):
        from tests.test_resource_evidence import page_timing_fixture
        contract, _, _, index, texts = page_timing_fixture()
        old_path = 'raw/platform/data_fields/fields.jsonl'
        new_path = (self.capture / 'data_fields.jsonl').relative_to(self.root).as_posix()
        index[new_path] = dict(index.pop(old_path), path=new_path)
        texts[new_path] = texts.pop(old_path)
        for premise in contract['premises']:
            if premise['evidence_ref']['source_path'] == old_path:
                premise['evidence_ref']['source_path'] = new_path
        for path, text in texts.items():
            destination = self.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(text.encode('utf-8'))
        write_json(self.capture / 'scopes.jsonl', dict(scope=SCOPE, status='completed', certification_status='complete'))
        source_index = self.root / 'machine/source_index.jsonl'
        source_index.write_text(''.join(json.dumps(source) + '\n' for source in index.values()), encoding='utf-8')
        compile_data_ledger_from_raw(self.root, self.capture)
        prior = json.loads(self.ledger.read_text(encoding='utf-8'))
        prior['timing_contract'] = contract
        write_json(self.ledger, prior)
        compile_data_ledger_from_raw(self.root, self.capture)
        rebuilt = json.loads(self.ledger.read_text(encoding='utf-8'))
        self.assertEqual(rebuilt.get('timing_contract'), contract)
        self.assertEqual(rebuilt['field_description'], 'A captured measurement.')
        # The same fixture also exercises the immutable selector timing interface.
        target = dict(dataset_id=rebuilt['dataset_id'], field_id=rebuilt['field_id'], field_type='MATRIX',
                      allowed_scopes=[SCOPE], literal_fact_explanation=rebuilt['field_description'],
                      facts=dict(timing_contract=dict(value=contract, premises=contract['premises'])),
                      hypothesis_cards=[], missing_facts=['polarity'])
        self.result = dict(schema_version=1, status='validated', source_index=index, fields=[target])
        self.row = rebuilt
        self.attach()
        self.row['field_semantics_ref'].update(dataset_id=rebuilt['dataset_id'], field_id=rebuilt['field_id'])
        self.assertEqual(self.resolve()['status'], 'supported', self.resolve())

    def test_level_does_not_require_units_or_cadence_but_declared_cadence_and_vector_do(self):
        from tests.test_template_binding import binding_fixture
        from wqb.template_binding import bind_template, TemplateBindingError
        template, fields, operators, scope = binding_fixture()
        template['skeleton'] = 'rank({flow})'
        template['input_slots'] = [dict(template['input_slots'][0], required_metadata=[])]
        fields = [dict(fields[0])]
        fields[0].pop('units')
        self.assertEqual(bind_template(template, fields, operators, scope)['bound_expression'], 'rank(cash)')
        template['input_slots'][0]['required_metadata'] = ['cadence']
        with self.assertRaises(TemplateBindingError):
            bind_template(template, fields, operators, scope)
        template['input_slots'][0].update(required_metadata=[], field_type='VECTOR',
                                         reduction=dict(operator='vec_avg', parameters={}))
        fields[0]['field_type'] = 'VECTOR'
        with self.assertRaises(TemplateBindingError):
            bind_template(template, fields, operators, scope)
        fields[0]['vector_grain'] = 'event'
        self.assertEqual(bind_template(template, fields, operators, scope)['bound_expression'], 'rank(vec_avg(cash))')
        template['input_slots'][0]['reduction'] = None
        with self.assertRaises(TemplateBindingError):
            bind_template(template, fields, operators, scope)


if __name__ == '__main__':
    unittest.main()
