"""Fictional offline typed conditions; no assertion about live platform support."""

from copy import deepcopy
import hashlib
import json
import unittest

from tests.test_hypothesis_design import compiler_fixture
from wqb.hypothesis_design import design_output_schema, validate_hypothesis_design
from wqb.hypothesis_template_compiler import compile_design
from wqb.semantic_compilation import _check_schema
from wqb.semantic_compilation import _digest
from wqb.semantic_contracts import SemanticPolicy


class LegacySchemaCompatibilityTests(unittest.TestCase):
    def test_default_schema_hash_preserves_pre_upgrade_frozen_release(self):
        expected = 'ab132ccb8b0684d4d150c2aa418fb5e9f855ac55413428811132096ed2f292e6'
        self.assertEqual(_digest([design_output_schema(1), design_output_schema(2)]), expected)
        self.assertNotEqual(_digest([design_output_schema(1, include_conditioned=True),
                                     design_output_schema(2, include_conditioned=True)]), expected)


def condition_fixture(comparator='greater', resource_version=1):
    """Input: comparator str/version int. Output: raw design/resources/scope dict tuple."""
    design, resources, scope = compiler_fixture()
    design.pop('design_id')
    design['design_version'] = 2
    role = dict(name='regime', field_type='MATRIX', required_semantics=['fictional_regime'],
                required_metadata=['available_at', 'units'])
    design['field_roles'].append(role)
    design['conditions'].update(mode='observable', observable_roles=['regime'])
    design['experiment_plan']['treatments'] = [dict(feature=dict(kind='conditioned',
        input=dict(kind='role', role='pulse'), condition_role=dict(kind='role', role='regime'),
        comparator=comparator, threshold=0.5), rationale='Compare the declared conditional response.')]
    field = dict(resources['field_rows'][0], field_id='regime_field',
                 field_description='fictional_regime', semantic_tags=['fictional_regime'])
    operators = []
    for name, inputs, types, meaning in [
        ('greater', ['MATRIX'], ['MATRIX', 'FLOAT'],
         'Returns a matrix mask of 1 where x is greater than threshold and 0 otherwise.'),
        ('less', ['MATRIX'], ['MATRIX', 'FLOAT'],
         'Returns a matrix mask of 1 where x is less than threshold and 0 otherwise.'),
        ('if_else', ['MATRIX', 'MATRIX'], ['MATRIX', 'MATRIX', 'FLOAT'],
         'Returns value where condition is nonzero and otherwise returns fallback.')]:
        operators.append(dict(operator=name, definition=dict(description=meaning,
            input_types=inputs, output_type='MATRIX', parameters=[
                dict(name=key, type=typ, required=True)
                for key, typ in zip(('x', 'threshold') if name != 'if_else'
                                    else ('condition', 'value', 'fallback'), types)])))
    path = 'raw/platform/data_fields/fictional_conditions.json'
    text = json.dumps(dict(fields=[dict(field=dict(id=field['field_id'],
        description=field['field_description'], type=field['field_type'],
        **{key: field[key] for key in ('units', 'available_at', 'semantic_tags')}),
        data_set=dict(id=field['dataset_id']), scope=scope)], operators=operators))
    digest = hashlib.sha256(text.encode()).hexdigest()
    pack = resources['evidence_pack']
    pack['source_index'][path] = dict(path=path, content_hash=digest,
        captured_at='2026-10-14T00:00:00Z', source_type='platform_data_field_capture',
        source_family='raw/platform/data_fields')
    pack['source_texts'][path] = text
    pack['allowed_role_semantics'].append('fictional_regime')
    pack['allowed_operator_intents'].append('conditioned')
    if resource_version == 2:
        pack['resource_contract_version'] = resources['resource_contract_version'] = 2
    field['source_paths'] = [path]
    resources['field_rows'].append(field)
    for row in operators:
        row['definition']['evidence_refs'] = [dict(source_path=path, sha256=digest,
            capture_date='2026-10-14', kind='documented', experiment_refs=[])]
    resources['operator_rows'].extend(operators)
    resources['source_index'] = deepcopy(pack['source_index'])
    resources['source_texts'] = deepcopy(pack['source_texts'])
    return design, resources, scope


def normalized_condition(data):
    """Input: raw fixture tuple. Output: normalized design/resources/scope tuple."""
    design, resources, scope = data
    normalized = validate_hypothesis_design(dict(summary='A conditional proposal.', designs=[design]),
        resources['evidence_pack'], SemanticPolicy())['designs'][0]
    return normalized, resources, scope


def refresh_condition_source(resources):
    """Input: fixture resources dict. Output: None; source changed typed facts with a new hash."""
    path = 'raw/platform/data_fields/fictional_conditions.json'
    facts = json.loads(resources['source_texts'][path])
    facts['operators'] = [dict(operator=row['operator'], definition={
        k: v for k, v in row['definition'].items() if k != 'evidence_refs'})
        for row in resources['operator_rows'] if row['operator'] in ('greater', 'less', 'if_else')]
    text = json.dumps(facts)
    digest = hashlib.sha256(text.encode()).hexdigest()
    for target in (resources, resources['evidence_pack']):
        target['source_texts'][path] = text
        target['source_index'][path]['content_hash'] = digest
    for row in resources['operator_rows']:
        for ref in row['definition']['evidence_refs']:
            if ref['source_path'] == path:
                ref['sha256'] = digest


class HypothesisConditionTests(unittest.TestCase):
    def test_compiles_actual_condition_with_per_arm_flags_and_sourced_bindings(self):
        """Input: none. Output: None; verify deterministic typed executable conditions."""
        for version in (1, 2):
            for comparator in ('greater', 'less'):
                with self.subTest(version=version, comparator=comparator):
                    data = normalized_condition(condition_fixture(comparator, version))
                    result = compile_design(*data)
                    self.assertEqual(result['status'], 'compiled', result['rejections'])
                    self.assertEqual(result, compile_design(*data))
                    experiment = result['experiment']
                    baseline, treatment = experiment['arms']
                    self.assertFalse(baseline['condition_filter_applied'])
                    self.assertTrue(treatment['condition_filter_applied'])
                    self.assertTrue(experiment['condition_filter_applied'])
                    self.assertEqual(baseline['binding']['bound_expression'], 'pulse_field')
                    self.assertEqual(treatment['binding']['bound_expression'],
                        f'if_else({comparator}(regime_field, 0.5), pulse_field, 0)')
                    self.assertEqual(set(treatment['binding']['bindings']), {'pulse', 'regime'})
                    self.assertEqual(set(baseline['binding']['bindings']), {'pulse'})
                    self.assertEqual({p['operator'] for p in treatment['binding']['operator_provenance']},
                                     {comparator, 'if_else'})
                    self.assertTrue(all(p['evidence_refs'] for p in treatment['binding']['operator_provenance']))
                    self.assertTrue(all(d['semantic_status'] == 'unreviewed' for d in result['drafts']))

    def test_condition_requires_explicit_v2_and_allowed_intent(self):
        """Input: none. Output: None; reject implicit v2 or unauthorized condition intent."""
        for mode in ('v1', 'missing_version', 'intent'):
            data = condition_fixture()
            if mode == 'v1':
                data[0]['design_version'] = 1
            elif mode == 'missing_version':
                data[0].pop('design_version')
            else:
                data[1]['evidence_pack']['allowed_operator_intents'].remove('conditioned')
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                normalized_condition(data)

    def test_sourced_but_unsupported_types_and_meanings_are_not_inferred(self):
        """Input: none. Output: None; exact raw matching alone cannot grant new semantics."""
        for mode in ('matrix_threshold', 'boolean_mask', 'meaning', 'optional', 'extra'):
            data = condition_fixture()
            definition = next(row['definition'] for row in data[1]['operator_rows']
                              if row['operator'] == 'greater')
            if mode == 'matrix_threshold':
                definition['parameters'][1]['type'] = 'MATRIX'
            elif mode == 'boolean_mask':
                definition['output_type'] = 'BOOLEAN'
            elif mode == 'meaning':
                definition['description'] = 'Returns a matrix mask of the opposite comparison.'
            elif mode == 'optional':
                definition['parameters'][1].update(required=False, default=0.5)
            else:
                definition['parameters'].append(dict(name='hidden', type='FLOAT', required=True))
            refresh_condition_source(data[1])
            with self.subTest(mode=mode):
                result = compile_design(*normalized_condition(data))
                self.assertEqual(result['status'], 'rejected')
                self.assertEqual(result['rejections'][0]['code'], 'missing_operator_definition')

    def test_declared_observable_matrix_role_is_required(self):
        """Input: none. Output: None; reject condition role/type or applicability mismatches."""
        for mode in ('GROUP', 'VECTOR', 'interpretive', 'unused_observable'):
            data = condition_fixture()
            if mode in ('GROUP', 'VECTOR'):
                data[0]['field_roles'][1]['field_type'] = mode
            elif mode == 'interpretive':
                data[0]['conditions'].update(mode=mode, observable_roles=[])
            else:
                data[0]['conditions']['observable_roles'].append('pulse')
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                normalized_condition(data)

    def test_sourced_selection_parameter_order_cannot_swap_condition_and_value(self):
        """Input: none. Output: None; same-typed arguments retain sourced named semantics."""
        data = condition_fixture()
        definition = next(row['definition'] for row in data[1]['operator_rows']
                          if row['operator'] == 'if_else')
        definition['parameters'][0]['name'] = 'value'
        definition['parameters'][1]['name'] = 'condition'
        refresh_condition_source(data[1])
        result = compile_design(*normalized_condition(data))
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['rejections'][0]['code'], 'missing_operator_definition')

    def test_negative_orientation_and_unconditioned_v2_flags(self):
        """Input: none. Output: None; orient whole conditional and never mark prose as a filter."""
        data = condition_fixture()
        data[0]['prediction_direction'] = 'negative'
        data[0]['experiment_plan']['treatments'][0]['feature']['threshold'] = -2
        result = compile_design(*normalized_condition(data))
        self.assertEqual(result['status'], 'compiled', result['rejections'])
        self.assertEqual(result['experiment']['arms'][1]['binding']['bound_expression'],
                         '-if_else(greater(regime_field, -2), pulse_field, 0)')
        design, resources, scope = compiler_fixture()
        design.pop('design_id')
        design['design_version'] = 2
        result = compile_design(*normalized_condition((design, resources, scope)))
        self.assertEqual(result['status'], 'compiled', result['rejections'])
        self.assertFalse(result['experiment']['condition_filter_applied'])
        self.assertFalse(result['experiment']['arms'][0]['condition_filter_applied'])

    def test_rejects_unbounded_raw_wrong_role_and_nonfinite_threshold(self):
        """Input: none. Output: None; reject unsupported grammar, roles and numeric values."""
        for key, value in [('comparator', 'equal'), ('threshold', float('nan')),
                           ('threshold', float('inf')), ('threshold', True), ('threshold', '0.5'),
                           ('input', dict(kind='change', input=dict(kind='role', role='pulse'), horizon=5)),
                           ('condition_role', dict(kind='role', role='absent')),
                           ('expression', 'arbitrary(regime)')]:
            data = condition_fixture()
            data[0]['experiment_plan']['treatments'][0]['feature'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                normalized_condition(data)

    def test_missing_provenance_wrong_signature_or_meaning_rejects_atomically(self):
        """Input: none. Output: None; ensure trusted facts and signatures cannot be bypassed."""
        for mode in ('missing', 'provenance', 'signature', 'meaning', 'duplicate'):
            data = normalized_condition(condition_fixture())
            rows = data[1]['operator_rows']
            row = next(row for row in rows if row['operator'] == 'greater')
            if mode == 'missing':
                rows.remove(row)
            elif mode == 'provenance':
                row['definition']['evidence_refs'] = []
            elif mode == 'signature':
                row['definition']['parameters'][1]['type'] = 'MATRIX'
            elif mode == 'meaning':
                row['definition']['description'] = 'Returns an unrelated quantity.'
            else:
                rows.append(deepcopy(row))
            with self.subTest(mode=mode):
                result = compile_design(*data)
                self.assertEqual(result['status'], 'rejected')
                self.assertEqual(result['drafts'], [])
                self.assertEqual(result['rejections'][0]['code'], 'missing_operator_definition')

    def test_legacy_fixture_outputs_remain_byte_identical(self):
        """Input: none. Output: None; lock complete pre-change v1 outputs, not only expressions."""
        expected = [
            ('level', False, '710dc74edb57213e202f9465543a6d72676a30d8a5e5e3f85bd883335afa4c22'),
            ('level', True, '0da8a09051defd839dd1a1c624111aa46bea7553cb6de9e95ef80723a4009296'),
            ('change', False, '2323251f3d7b0a510413c576bb630de95f249c44d9cd91d7fded7d013b913b66'),
            ('group_rank', False, '0d662a677980050b64c9ddfe6b45b7b3bc473215a6e3570df8a724da6d375530'),
            ('group_demean', False, '8340c929c1cde2ff0e4cfd6153e1802b824caf4c01a7a2eb02db1bacf05133f3')]
        for kind, treatment, digest in expected:
            result = compile_design(*compiler_fixture(kind, treatment))
            encoded = json.dumps(result, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
            with self.subTest(kind=kind, treatment=treatment):
                self.assertEqual(hashlib.sha256(encoded).hexdigest(), digest)

    def test_versioned_schema_rejects_condition_in_v1(self):
        """Input: none. Output: None; syntax admits the condition only in the explicit v2 branch."""
        data = condition_fixture()
        answer = dict(summary='A conditional proposal.', designs=[data[0]])
        _check_schema(design_output_schema(include_conditioned=True), answer)
        data[0]['design_version'] = 1
        with self.assertRaises(ValueError):
            _check_schema(design_output_schema(include_conditioned=True), answer)
