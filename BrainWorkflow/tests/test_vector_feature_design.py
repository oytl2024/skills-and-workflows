"""Hermetic VECTOR tests using fictional captures shaped like official resources.

Only narrow audited syntax/type premises are reused; these generated receipts
are test fiction, not platform captures, freshness proof or research evidence.
No user knowledge directory, private source index or network is consulted.
"""

from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch

from tests.test_hypothesis_design import compiler_fixture
from tests.test_hypothesis_conditions import condition_fixture
from wqb.hypothesis_design import design_output_schema, validate_hypothesis_design
from wqb.hypothesis_template_compiler import compile_design
from wqb.semantic_contracts import SemanticPolicy
from wqb.semantic_compilation import _check_schema, _digest
from wqb.knowledge_contracts import render_front_matter, _learn_repair_body
from wqb import resource_evidence


def vector_fixture(operator='vec_avg', kind='level', conditioned=False):
    """Input: operator/kind str, conditioned bool. Output: raw design/resources/scope dict tuple; no IO."""
    design, resources, scope = condition_fixture() if conditioned else compiler_fixture(kind)
    design.pop('design_id', None)
    design['design_version'] = 3
    role = next(role for role in design['field_roles'] if role['name'] == 'pulse')
    role['field_type'] = 'VECTOR'
    role['required_metadata'].append('vector_grain')
    field = next(field for field in resources['field_rows'] if field['field_id'] == 'pulse_field')
    field.update(field_type='VECTOR', vector_grain='events per instrument per day')
    leaf = dict(kind='role', role='pulse', reduction=dict(operator=operator, parameters={}))
    feature = deepcopy(design['feature_plan'])
    if feature['kind'] == 'role':
        feature = leaf
    else:
        feature['input'] = leaf
    design['feature_plan'] = feature
    design['experiment_plan']['baseline'] = deepcopy(feature)
    if conditioned:
        design['experiment_plan']['treatments'][0]['feature']['input'] = deepcopy(leaf)
    operators = [dict(operator=name, definition=dict(description=meaning,
        input_types=['VECTOR'], output_type='MATRIX',
        parameters=[dict(name='x', type='VECTOR', required=True)]))
        for name, meaning in [('vec_avg', 'Taking mean of the vector field x'),
                              ('vec_sum', 'Sum of vector field x'),
                              ('vec_count', 'Number of elements in vector field x')]]
    path = 'raw/platform/learn/fictional_vector.json'
    text = json.dumps(dict(fields=[dict(field=dict(id=field['field_id'],
        description=field['field_description'], type='VECTOR',
        **{key: field[key] for key in ('units', 'available_at', 'semantic_tags', 'vector_grain')}),
        data_set=dict(id=field['dataset_id']), scope=scope)], operators=operators))
    digest = hashlib.sha256(text.encode()).hexdigest()
    for target in (resources, resources['evidence_pack']):
        target['resource_contract_version'] = 2
        target['resource_admission_policy'] = 'knowledge_catalog_v1'
        target['source_index'][path] = dict(path=path, content_hash=digest,
            captured_at='2026-10-14T00:00:00Z', source_type='platform_learn_material',
            source_family='raw/platform/learn')
        target['source_texts'][path] = text
    field['source_paths'] = [path]
    for row in operators:
        row['definition']['evidence_refs'] = [dict(source_path=path, sha256=digest,
            capture_date='2026-10-14', kind='documented', experiment_refs=[])]
    resources['operator_rows'].extend(operators)
    return design, resources, scope


def normalize(data):
    """Input: raw fixture tuple. Output: normalized design/resources/scope tuple."""
    design, resources, scope = data
    result = validate_hypothesis_design(dict(summary='An explicit vector proposal.', designs=[design]),
        resources['evidence_pack'], SemanticPolicy())['designs'][0]
    return result, resources, scope


class VectorFeatureTests(unittest.TestCase):
    def test_explicit_mean_sum_count_are_distinct_and_deterministic(self):
        results = []
        for operator in ('vec_avg', 'vec_sum', 'vec_count'):
            data = normalize(vector_fixture(operator))
            result = compile_design(*data)
            self.assertEqual(result['status'], 'compiled', result)
            self.assertEqual(result, compile_design(*data))
            self.assertEqual(result['experiment']['arms'][0]['binding']['bound_expression'],
                             operator + '(pulse_field)')
            self.assertEqual(result['drafts'][0]['input_slots'][0]['reduction'],
                             dict(operator=operator, parameters={}))
            results.append(result['compilation_digest'])
        self.assertEqual(len(set(results)), 3)

    def test_reduction_precedes_change_relative_and_condition(self):
        for kind in ('change', 'group_rank', 'group_demean'):
            result = compile_design(*normalize(vector_fixture('vec_sum', kind)))
            self.assertEqual(result['status'], 'compiled', result)
            expression = result['experiment']['arms'][0]['binding']['bound_expression']
            self.assertIn('(vec_sum(pulse_field),', expression)
        data = vector_fixture('vec_avg', conditioned=True)
        # Both condition and value operands may explicitly reduce vectors.
        data[0]['field_roles'][1]['field_type'] = 'VECTOR'
        data[1]['field_rows'][1]['field_type'] = 'VECTOR'
        data[0]['experiment_plan']['treatments'][0]['feature']['condition_role']['reduction'] = dict(
            operator='vec_count', parameters={})
        result = compile_design(*normalize(data))
        self.assertEqual(result['status'], 'compiled', result)
        self.assertEqual(result['experiment']['arms'][1]['binding']['bound_expression'],
            'if_else(greater(vec_count(regime_field), 0.5), vec_avg(pulse_field), 0)')
        self.assertTrue(result['experiment']['arms'][1]['condition_filter_applied'])

    def test_missing_reduction_wrong_type_and_old_versions_reject(self):
        for mode in ('missing', 'MATRIX', 'GROUP', 'v1', 'v2', 'unknown', 'parameters'):
            data = vector_fixture()
            design = data[0]
            leaf = design['feature_plan']['input']
            if mode == 'missing':
                leaf.pop('reduction')
            elif mode in ('MATRIX', 'GROUP'):
                design['field_roles'][0]['field_type'] = mode
            elif mode in ('v1', 'v2'):
                design['design_version'] = int(mode[-1])
            elif mode == 'unknown':
                leaf['reduction']['operator'] = 'vec_median'
            else:
                leaf['reduction']['parameters']['invented'] = 1
            design['experiment_plan']['baseline'] = deepcopy(design['feature_plan'])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                normalize(data)

    def test_mean_versus_sum_treatment_preserves_shared_field_and_per_arm_reductions(self):
        data = vector_fixture('vec_avg')
        treatment = deepcopy(data[0]['feature_plan'])
        treatment['input']['reduction']['operator'] = 'vec_sum'
        data[0]['experiment_plan']['treatments'] = [dict(feature=treatment,
            rationale='Compare the total with the representative mean.')]
        result = compile_design(*normalize(data))
        self.assertEqual(result['status'], 'compiled', result)
        self.assertEqual([arm['binding']['bound_expression'] for arm in result['experiment']['arms']],
                         ['vec_avg(pulse_field)', 'vec_sum(pulse_field)'])
        context = result['experiment']['context_bindings']['pulse']
        self.assertEqual(context['field_id'], 'pulse_field')
        self.assertEqual(context['arm_reductions'], dict(
            baseline=dict(operator='vec_avg', parameters={}),
            treatment=dict(operator='vec_sum', parameters={})))

    def test_condition_missing_reduction_and_conflicting_same_slot_reject(self):
        for mode in ('missing', 'same_slot'):
            data = vector_fixture(conditioned=True)
            feature = data[0]['experiment_plan']['treatments'][0]['feature']
            if mode == 'missing':
                data[0]['field_roles'][1]['field_type'] = 'VECTOR'
                with self.assertRaises(ValueError):
                    normalize(data)
            else:
                # Same role in both positions cannot have two InputSlot reductions.
                feature['condition_role'] = dict(kind='role', role='pulse', reduction=dict(
                    operator='vec_count', parameters={}))
                data[0]['field_roles'] = [data[0]['field_roles'][0]]
                data[0]['conditions']['observable_roles'] = ['pulse']
                result = compile_design(*normalize(data))
                self.assertEqual(result['status'], 'rejected', result)

    def test_fictional_official_shaped_sources_compile_without_global_publication(self):
        for name in resource_evidence.VECTOR_REDUCTIONS:
            data = vector_fixture(name)
            index, texts, refs = fictional_vector_sources()
            operator = resource_evidence.enrich_vector_operator_record(dict(operator=name), index, texts,
                catalog_ref=refs['catalog'], vector_ref=refs['tutorial'])
            for target in (data[1], data[1]['evidence_pack']):
                target['source_index'].update(index)
                target['source_texts'].update(texts)
            data[2]['as_of'] = '2026-11-24T02:00:00Z'
            data[1]['evidence_pack']['scope'] = deepcopy(data[2])
            data[1]['operator_rows'] = [operator]
            result = compile_design(*normalize(data))
            self.assertEqual(result['status'], 'compiled', result)
            provenance = result['experiment']['arms'][0]['binding']['operator_provenance'][0]
            self.assertEqual(provenance['operator'], name)
            self.assertEqual(len(provenance['evidence_refs']), 2)

    def test_reduction_does_not_authorize_unsourced_or_wrong_signature(self):
        for mode in ('no_operator', 'wrong_output', 'tampered_source'):
            data = vector_fixture()
            row = next(row for row in data[1]['operator_rows'] if row['operator'] == 'vec_avg')
            if mode == 'no_operator':
                data[1]['operator_rows'].remove(row)
            elif mode == 'wrong_output':
                row['definition']['output_type'] = 'VECTOR'
            else:
                path = row['definition']['evidence_refs'][0]['source_path']
                for target in (data[1], data[1]['evidence_pack']):
                    target['source_texts'][path] += ' '
            with self.subTest(mode=mode):
                try:
                    result = compile_design(*normalize(data))
                except ValueError:
                    continue
                self.assertEqual(result['status'], 'rejected', result)

    def test_legacy_schema_fingerprints_and_explicit_opt_in(self):
        self.assertEqual(_digest([design_output_schema(1), design_output_schema(2)]),
                         'ab132ccb8b0684d4d150c2aa418fb5e9f855ac55413428811132096ed2f292e6')
        answer = dict(summary='A vector proposal.', designs=[vector_fixture()[0]])
        with self.assertRaises(ValueError):
            _check_schema(design_output_schema(2, include_conditioned=True), answer)
        _check_schema(design_output_schema(2, include_vector=True), answer)


def fictional_vector_sources():
    """Input: none. Output: in-memory fictional source index/texts/refs dicts; no IO or actual platform evidence.

    Reuse the raw operator writer and documentation test writer to bind complete
    minimal payloads, rendered bodies, receipts, paths and hashes. Only the
    audited conversion paragraph and seven direct table rows are needed.
    """
    from tests.test_resource_evidence import documentation_fixture
    generated = '2026-10-15T13:48:14+00:00'
    operators = [dict(name=name, category='Vector', scope=['REGULAR'], level='ALL',
        documentation='/operators/' + name, definition=name + '(x)', description=meaning)
        for name, meaning in resource_evidence.VECTOR_REDUCTIONS.items()]
    receipt = dict(generated_at=generated, target=dict(kind='operators'),
                   endpoint='/operators', payload=operators, error=None)
    path = ('raw/platform/learn/2026-10-15/subset-'
            + resource_evidence._capture_digest(receipt) + '/operators.md')
    body = (_learn_repair_body('operators', operators)
            + '\n## Raw GET Receipt\n\n```json\n'
            + json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + '\n```\n')
    policy = resource_evidence.OPERATOR_RECEIPT_POLICY
    row = dict(path=path, source_path=path, source_type='platform_learn_material',
        source_family='raw/platform/learn', captured_at=generated,
        content_hash=hashlib.sha256(body.encode()).hexdigest(),
        record_count=len(operators), payload_hash=resource_evidence._capture_digest(operators),
        **{key: deepcopy(policy[key]) for key in (
            'capture_tool', 'content_status', 'update_check', 'compiled_targets')})
    text = render_front_matter(row) + body
    row['file_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    catalog_ref = dict(source_path=path, sha256=row['content_hash'], capture_date='2026-10-15',
                       kind='documented', experiment_refs=[])
    page = dict(id='vector-datafields', title='Vector Data Fields', category='Data', sequence=1,
        lastModified=generated, content=[
            dict(id='fictional-note', type='TEXT', value='Fictional offline test resource.'),
            dict(id='conversion-premise', type='TEXT', value=resource_evidence.MATRIX_PAGE_CONTEXT),
            dict(id='fictional-image', type='IMAGE', value=dict(fileSize=1, height=1, width=1,
                title='Fictional illustration', url='https://example.invalid/fictional-vector.png')),
            dict(id='table-intro', type='TEXT', value=resource_evidence.VECTOR_TABLE_INTRO),
            dict(id='direct-signatures', type='TABLE', value=dict(firstColIsHeader=False,
                firstRowIsTableHeader=True, data=[['Operator', 'Description']] + [
                    [name + '(x)', meaning] for name, meaning in resource_evidence.VECTOR_TUTORIAL_MEANINGS.items()]))])
    vector_ref, index, texts = documentation_fixture(page)
    index[path], texts[path] = row, text
    return index, texts, dict(catalog=catalog_ref, tutorial=vector_ref)


class SourcedVectorDeclarationTests(unittest.TestCase):
    def test_sources_and_compilation_need_no_filesystem_knowledge(self):
        with patch('pathlib.Path.open', side_effect=AssertionError('workspace knowledge is unavailable')):
            index, texts, refs = fictional_vector_sources()
            data = vector_fixture('vec_sum')
            row = resource_evidence.enrich_vector_operator_record(dict(operator='vec_sum'), index, texts,
                catalog_ref=refs['catalog'], vector_ref=refs['tutorial'])
            for target in (data[1], data[1]['evidence_pack']):
                target['source_index'].update(index)
                target['source_texts'].update(texts)
            data[1]['operator_rows'] = [row]
            result = compile_design(*normalize(data))
            self.assertEqual(result['status'], 'compiled', result)

    def test_fictional_catalog_and_tutorial_enrich_without_mutation(self):
        index, texts, refs = fictional_vector_sources()
        before = deepcopy((index, texts))
        for name in ('vec_avg', 'vec_sum', 'vec_count', 'vec_min', 'vec_max', 'vec_stddev', 'vec_range'):
            row = resource_evidence.enrich_vector_operator_record(dict(operator=name), index, texts,
                catalog_ref=refs['catalog'], vector_ref=refs['tutorial'])
            definition = resource_evidence.catalog_operator_definition(row, index, texts)
            self.assertEqual(definition['input_types'], ['VECTOR'])
            self.assertEqual(definition['output_type'], 'MATRIX')
            self.assertEqual(definition['parameters'], [dict(name='x', type='VECTOR', required=True)])
            self.assertEqual(len(definition['evidence_refs']), 2)
        self.assertEqual((index, texts), before)

    def test_fully_rehashed_contradictory_tutorial_is_not_new_type_authority(self):
        from tests.test_resource_evidence import documentation_fixture
        index, texts, refs = fictional_vector_sources()
        page = resource_evidence.validated_documentation_page(refs['tutorial'], index, texts)
        page['content'].append(dict(id='contradiction', type='TEXT',
            value='The vec_sum operator returns VECTOR rather than MATRIX.'))
        ref, changed_index, changed_texts = documentation_fixture(page)
        index.update(changed_index)
        texts.update(changed_texts)
        # Receipt/render/path/hash all pass; the newly conflicting context does not.
        resource_evidence.validated_documentation_page(ref, index, texts)
        with self.assertRaisesRegex(ValueError, 'technical mapping claim'):
            resource_evidence.enrich_vector_operator_record(dict(operator='vec_sum'), index, texts,
                catalog_ref=refs['catalog'], vector_ref=ref)

    def test_unrelated_note_and_image_changes_do_not_invalidate_types(self):
        from tests.test_resource_evidence import documentation_fixture
        index, texts, refs = fictional_vector_sources()
        page = resource_evidence.validated_documentation_page(refs['tutorial'], index, texts)
        page['content'].append(dict(id='editorial-note', type='TEXT', value='Editorial note: this article was updated.'))
        page['content'][1]['value'] += '<p>Further reading is available in the help center.</p>'
        page['content'][2]['value']['title'] = 'A refreshed illustration'
        ref, changed_index, changed_texts = documentation_fixture(page)
        index.update(changed_index)
        texts.update(changed_texts)
        row = resource_evidence.enrich_vector_operator_record(dict(operator='vec_sum'), index, texts,
            catalog_ref=refs['catalog'], vector_ref=ref)
        self.assertEqual(resource_evidence.catalog_operator_definition(row, index, texts)['output_type'], 'MATRIX')

    def test_source_corruption_missing_proof_and_non_catalog_operator_reject(self):
        for mode in ('corrupt', 'missing', 'median', 'contradiction'):
            index, texts, refs = fictional_vector_sources()
            if mode == 'corrupt':
                texts[refs['tutorial']['source_path']] += 'altered'
            elif mode == 'missing':
                texts.pop(refs['tutorial']['source_path'])
            record = dict(operator='vec_median' if mode == 'median' else 'vec_sum')
            if mode == 'contradiction':
                record['definition'] = dict(input_types=['MATRIX'], output_type='VECTOR', parameters=[])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                resource_evidence.enrich_vector_operator_record(record, index, texts,
                    catalog_ref=refs['catalog'], vector_ref=refs['tutorial'])


if __name__ == '__main__':
    unittest.main()
