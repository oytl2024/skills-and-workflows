import copy
import hashlib
import json
import unittest

from tests.test_resource_evidence import named_comparison_fixture, replace_timing_capture, timing_fixture
from wqb.template_binding import TemplateBindingError, bind_template


def binding_fixture():
    """Input: none. Output: tuple[dict, list[dict], list[dict], dict]. Build offline Task6 snapshot."""
    ref = dict(source_path='raw/platform/learn/operators.md', sha256='a' * 64,
               capture_date='2026-10-13', kind='documented')
    def operator(name, inputs, output, extra=()):
        """Input: name str, input list[str], output str, extra tuple. Output: dict typed definition."""
        parameters = [dict(name=f'x{i}', type=value, required=True) for i, value in enumerate(inputs)]
        parameters.extend(extra)
        return dict(operator=name, definition=dict(description='Documented mathematical transformation.',
                    input_types=inputs, output_type=output, parameters=parameters, evidence_refs=[ref]))
    scope = dict(region='USA', delay=1, universe='TOP3000', as_of='2026-10-13T09:00:00+00:00')
    fields = [dict(field_id='cash', dataset_id='fundamentals', field_type='MATRIX',
                   field_description='Operating cash flow.', units='USD', available_at='2026-10-12T09:00:00+00:00',
                   region='USA', delay=1, universe='TOP3000'),
              dict(field_id='debt', dataset_id='fundamentals', field_type='MATRIX',
                   field_description='Total debt.', units='USD', available_at='2026-10-12T09:00:00+00:00',
                   region='USA', delay=1, universe='TOP3000')]
    slots = [dict(name=name, role='signal', required_semantics=[meaning], field_type='MATRIX',
                  required_metadata=['units', 'available_at'], reduction=None)
             for name, meaning in [('flow', 'Operating cash flow'), ('liability', 'Total debt')]]
    template = dict(template_id='cash-debt', hypothesis='Cash relative to debt predicts resilience.',
                    binding_version=2, skeleton='rank({flow} / {liability})', input_slots=slots)
    operators = [operator('rank', ['MATRIX'], 'MATRIX'),
                 operator('ts_mean', ['MATRIX'], 'MATRIX', [dict(name='d', type='INTEGER', required=True)]),
                 operator('vec_avg', ['VECTOR'], 'MATRIX'), operator('vec_count', ['VECTOR'], 'MATRIX'),
                 operator('vec_percentage', ['VECTOR'], 'MATRIX',
                          [dict(name='percentage', type='FLOAT', required=True)])]
    return template, fields, operators, scope


class TemplateBindingTests(unittest.TestCase):
    def test_actual_comparison_missing_cutoff_evidence_rejects_binding(self):
        contract, row, scope, index, texts = named_comparison_fixture()
        contract['premises'].pop(2)
        args, _ = self.timing_binding_fixture()
        row.update(field_description='Operating cash flow.', timing_contract=contract)
        with self.assertRaises(TemplateBindingError):
            bind_template(args[0], [row], args[2], scope, resource_contract_version=2,
                          evidence_context=dict(source_index=index, source_texts=texts))

    def test_actual_named_regular_comparison_binds_without_invented_raw_attributes(self):
        contract, row, scope, index, texts = named_comparison_fixture()
        args, _ = self.timing_binding_fixture()
        row.update(field_description='Operating cash flow.', timing_contract=contract)
        result = bind_template(args[0], [row], args[2], scope, resource_contract_version=2,
                               evidence_context=dict(source_index=index, source_texts=texts))
        self.assertEqual(result['bound_expression'], 'rank(snt_buzz)')
        self.assertNotIn('available_at', result['bindings']['flow']['metadata'])
        self.assertEqual(result['bindings']['flow']['timing_receipt']['rule_version'], 3)

    def test_nested_captured_scope_conflicts_reject_binding(self):
        for container in ('field', 'data_set', 'field.dataset'):
            for key, value in (('delay', 0), ('delay', True), ('region', 'EUR'), ('universe', 'TOP500')):
                with self.subTest(container=container, key=key, value=value):
                    args, context = self.timing_binding_fixture()
                    fixture = (args[1][0]['timing_contract'], args[1][0], args[3],
                               context['source_index'], context['source_texts'])
                    payload = json.loads(fixture[4]['raw/platform/data_fields/fields.jsonl'])
                    target = payload['field']['dataset'] if container == 'field.dataset' else payload[container]
                    target[key] = value
                    replace_timing_capture(fixture, payload)
                    with self.assertRaises(TemplateBindingError):
                        bind_template(*args, resource_contract_version=2, evidence_context=context)

    def timing_binding_fixture(self):
        """Input: TestCase. Output: binding args/context. Adapt the real binder to fictional timing sources."""
        contract, row, scope, index, texts = timing_fixture()
        template, _, operators, _ = binding_fixture()
        template['skeleton'] = 'rank({flow})'
        template['input_slots'] = [dict(template['input_slots'][0], required_metadata=['timing_contract'])]
        row.update(field_description='Operating cash flow.', timing_contract=contract)
        return (template, [row], operators, scope), dict(source_index=index, source_texts=texts)

    def test_v1_timestamp_path_unchanged(self):
        fixture = binding_fixture()
        self.assertEqual(bind_template(*fixture), bind_template(*fixture, resource_contract_version=1))
        args, context = self.timing_binding_fixture()
        with self.assertRaises(TemplateBindingError):
            bind_template(*args, evidence_context=context)
        fixture[1][0]['timing_contract'] = {'invalid': True}
        self.assertEqual(bind_template(*fixture), bind_template(*fixture, resource_contract_version=1))

    def test_v2_regular_delay_policy_receipt(self):
        args, context = self.timing_binding_fixture()
        result = bind_template(*args, resource_contract_version=2, evidence_context=context)
        self.assertEqual(result['bound_expression'], 'rank(f)')
        binding = result['bindings']['flow']
        self.assertNotIn('available_at', binding['metadata'])
        self.assertEqual(binding['metadata']['timing_contract'], args[1][0]['timing_contract'])
        self.assertIs(binding['timing_receipt']['historical_pit_verified'], False)
        self.assertEqual(binding['timing_receipt']['rule_id'], 'regular_delay_1')
        # Empty metadata cannot bypass timing checks or drop the receipt.
        args[0]['input_slots'][0]['required_metadata'] = []
        self.assertEqual(bind_template(*args, resource_contract_version=2, evidence_context=context), result)

    def test_v2_flag_alone_never_trusts_timing(self):
        args, context = self.timing_binding_fixture()
        for invalid in (None, {}, dict(source_index=context['source_index']),
                        dict(source_index={}, source_texts={})):
            with self.subTest(context=invalid), self.assertRaises(TemplateBindingError):
                bind_template(*args, resource_contract_version=2, evidence_context=invalid)
        for version in (True, '2', 2.0, 0, 3):
            with self.subTest(version=version), self.assertRaises(TemplateBindingError):
                bind_template(*args, resource_contract_version=version, evidence_context=context)

    def test_policy_cannot_override_future_timestamp(self):
        for value in ('2026-10-16T00:00:00Z', None, '', 'unknown', True):
            args, context = self.timing_binding_fixture()
            args[1][0]['available_at'] = value
            with self.subTest(value=value), self.assertRaises(TemplateBindingError):
                bind_template(*args, resource_contract_version=2, evidence_context=context)
        args, context = self.timing_binding_fixture()
        args[1][0]['available_at'] = '2026-10-14T00:00:00Z'
        result = bind_template(*args, resource_contract_version=2, evidence_context=context)
        self.assertEqual(result['bindings']['flow']['metadata']['available_at'], '2026-10-14T00:00:00Z')

    def test_v2_legacy_explicit_timestamp_and_units_remain_strict(self):
        args = binding_fixture()
        self.assertEqual(bind_template(*args, resource_contract_version=2), bind_template(*args))
        args, context = self.timing_binding_fixture()
        args[0]['input_slots'][0]['required_metadata'].append('units')
        with self.assertRaises(TemplateBindingError):
            bind_template(*args, resource_contract_version=2, evidence_context=context)

    def test_availability_is_mandatory_without_required_metadata_declaration(self):
        for value in [None, '2099-01-01T00:00:00+00:00', 'unknown']:
            with self.subTest(value=value):
                fixture = binding_fixture()
                for slot in fixture[0]['input_slots']:
                    slot['required_metadata'] = []
                fixture[1][0]['available_at'] = value
                self.reject(fixture, 'available_at|availability')

    def test_availability_requires_as_of_even_when_metadata_list_omits_it(self):
        fixture = binding_fixture()
        for slot in fixture[0]['input_slots']:
            slot['required_metadata'] = []
        del fixture[3]['as_of']
        self.reject(fixture, 'as_of')

    def test_mandatory_availability_is_retained_in_binding_audit(self):
        fixture = binding_fixture()
        for slot in fixture[0]['input_slots']:
            slot['required_metadata'] = []
        result = self.bind(fixture)
        self.assertEqual(result['bound_expression'], 'rank(cash / debt)')
        self.assertEqual(result['bindings']['flow']['metadata'],
                         {'available_at': '2026-10-12T09:00:00+00:00'})

    def test_window_placeholder_cannot_concatenate_numeric_literal(self):
        fixture = binding_fixture()
        fixture[0]['skeleton'] = 'rank(ts_mean({flow}, 1{window}) / {liability})'
        self.reject(fixture, 'placeholder')

    def test_quoted_placeholders_are_not_consumed_field_references(self):
        for skeleton in ["rank({flow}, label='{liability}')",
                         "rank({flow} / {liability}, label='{liability}')",
                         "rank({flow} / {liability}, label='{window}')"]:
            with self.subTest(skeleton=skeleton):
                fixture = binding_fixture()
                fixture[0]['skeleton'] = skeleton
                fixture[2][0]['definition']['parameters'].append(dict(name='label', type='STRING', required=True))
                self.reject(fixture, 'placeholder')

    def test_omitted_reducer_default_cannot_hide_declared_parameter_type(self):
        for declared, parameter_type, default in [(True, 'FLOAT', 1.0), (False, 'FLOAT', 0.0),
                                                    (1.0, 'INTEGER', 1), (1, 'BOOLEAN', True)]:
            with self.subTest(declared=declared, parameter_type=parameter_type):
                fixture = binding_fixture()
                fixture[0]['input_slots'] = [dict(fixture[0]['input_slots'][0], field_type='VECTOR',
                    reduction=dict(operator='vec_percentage', parameters={'percentage': declared}))]
                fixture[1][0].update(field_type='VECTOR', vector_grain='event')
                fixture[0]['skeleton'] = 'rank(vec_percentage({flow}))'
                fixture[2][-1]['definition']['parameters'][-1].update(type=parameter_type, required=False, default=default)
                self.reject(fixture, 'type')

    def test_omitted_reducer_default_with_matching_type_is_preserved(self):
        fixture = binding_fixture()
        fixture[0]['input_slots'] = [dict(fixture[0]['input_slots'][0], field_type='VECTOR',
            reduction=dict(operator='vec_percentage', parameters={'percentage': 1.0}))]
        fixture[1][0].update(field_type='VECTOR', vector_grain='event')
        fixture[0]['skeleton'] = 'rank(vec_percentage({flow}))'
        fixture[2][-1]['definition']['parameters'][-1].update(required=False, default=1.0)
        result = self.bind(fixture)
        self.assertEqual(result['bound_expression'], 'rank(vec_percentage(cash))')
        self.assertEqual(result['operator_call_count'], 2)

    def bind(self, fixture=None):
        """Input: optional fixture tuple. Output: dict. Invoke real pure binder."""
        from wqb.template_binding import bind_template
        return bind_template(*(fixture or binding_fixture()))

    def reject(self, fixture, message=None):
        """Input: tuple and optional regex str. Output: None. Require fail-closed binding."""
        from wqb.template_binding import TemplateBindingError
        with self.assertRaisesRegex(TemplateBindingError, message or '.'):
            self.bind(fixture)

    def test_fixture_output_is_pure_and_auditable(self):
        fixture = binding_fixture()
        original = copy.deepcopy(fixture)
        result = self.bind(fixture)
        self.assertEqual(fixture, original)
        self.assertEqual(set(result), {'bound_expression', 'bindings', 'operator_provenance', 'operator_call_count'})
        self.assertEqual(result['bound_expression'], 'rank(cash / debt)')
        self.assertEqual(result['bindings']['flow']['field_id'], 'cash')
        self.assertEqual(result['bindings']['flow']['dataset_id'], 'fundamentals')
        self.assertEqual(result['operator_call_count'], 1)
        self.assertEqual(result['operator_provenance'][0]['operator'], 'rank')
        self.assertEqual(result['operator_provenance'][0]['evidence_refs'][0]['kind'], 'documented')

    def test_no_inference_from_field_names(self):
        template, fields, operators, scope = binding_fixture()
        fields[0]['field_description'] = 'Unrelated measurement'
        self.reject((template, fields, operators, scope), 'flow')

    def test_missing_or_unknown_metadata_blocks(self):
        for key in ['units', 'available_at']:
            for value in [None, '', 'unknown']:
                with self.subTest(key=key, value=value):
                    fixture = binding_fixture()
                    fixture[1][0][key] = value
                    self.reject(fixture)

    def test_cross_scope_and_future_availability_block(self):
        for key, value in [('region', 'EUR'), ('delay', 0), ('universe', 'OTHER'),
                           ('available_at', '2026-10-14T09:00:00+00:00')]:
            with self.subTest(key=key):
                fixture = binding_fixture()
                fixture[1][0][key] = value
                self.reject(fixture)
        fixture = binding_fixture()
        del fixture[3]['as_of']
        self.reject(fixture)

    def test_ambiguity_and_same_name_across_datasets_block(self):
        for same_name in [False, True]:
            fixture = binding_fixture()
            other = dict(fixture[1][0], dataset_id='other')
            if not same_name:
                other['field_id'] = 'other_cash'
            fixture[1].append(other)
            self.reject(fixture, 'ambiguous')

    def test_explicit_scope_can_select_dataset(self):
        fixture = binding_fixture()
        fixture[1].append(dict(fixture[1][0], dataset_id='other'))
        fixture[3]['dataset_id'] = 'fundamentals'
        self.assertEqual(self.bind(fixture)['bindings']['flow']['dataset_id'], 'fundamentals')

    def test_vector_reducers_once_and_multiarg(self):
        for reducer, parameters in [('vec_avg', {}), ('vec_count', {}), ('vec_percentage', {'percentage': 0.5})]:
            for explicit in [False, True]:
                with self.subTest(reducer=reducer, explicit=explicit):
                    template, fields, operators, scope = binding_fixture()
                    template['input_slots'] = [dict(template['input_slots'][0], field_type='VECTOR',
                                                   reduction=dict(operator=reducer, parameters=parameters))]
                    fields = [dict(fields[0], field_type='VECTOR', vector_grain='news event')]
                    args = ', percentage=0.5' if parameters else ''
                    template['skeleton'] = f'rank({reducer}({{flow}}{args}))' if explicit else 'rank({flow})'
                    result = self.bind((template, fields, operators, scope))
                    self.assertEqual(result['bound_expression'], f'rank({reducer}(cash{args}))')
                    self.assertEqual(result['operator_call_count'], 2)
                    del fields[0]['vector_grain']
                    self.reject((template, fields, operators, scope))

    def test_unknown_definition_and_wrong_inputs_block(self):
        fixture = binding_fixture()
        fixture[2][0].pop('definition')
        fixture[2][0]['raw_definition'] = 'rank(x)'
        self.reject(fixture, 'definition')
        fixture = binding_fixture()
        fixture[2][0]['definition']['input_types'] = ['VECTOR']
        fixture[2][0]['definition']['parameters'][0]['type'] = 'VECTOR'
        self.reject(fixture, 'type')

    def test_actual_calls_not_unique_names(self):
        fixture = binding_fixture()
        fixture[0]['skeleton'] = 'rank(rank({flow}) / rank({liability}))'
        result = self.bind(fixture)
        self.assertEqual(result['operator_call_count'], 3)
        self.assertEqual(len(result['operator_provenance']), 3)

    def test_unsupported_grammar_and_unknown_placeholders_fail(self):
        for expression in ['rank({missing})', 'rank({flow}) if True else rank({liability})',
                           'rank({flow}.x)', 'rank({flow}); rank({liability})', 'rank({flow!r})']:
            fixture = binding_fixture()
            fixture[0]['skeleton'] = expression
            self.reject(fixture)

    def test_bad_parameters_fail_without_bool_integer_or_nan_coercion(self):
        for expression in ['rank(ts_mean({flow}, True))', 'rank(ts_mean({flow}, 5.0))',
                           'rank(ts_mean({flow}, 1e999))', 'rank(ts_mean({flow}))',
                           'rank(ts_mean({flow}, d=5, extra=2))', 'rank(ts_mean({flow}, 5, d=10))']:
            fixture = binding_fixture()
            fixture[0]['skeleton'] = expression
            self.reject(fixture)

    def test_required_semantics_cannot_bind_wrong_type(self):
        fixture = binding_fixture()
        fixture[1][0]['field_type'] = 'VECTOR'
        self.reject(fixture)

    def test_v2_requires_scope_and_dataset_identity(self):
        fixture = binding_fixture()
        fixture[3].clear()
        self.reject(fixture, 'scope')
        fixture = binding_fixture()
        del fixture[1][0]['dataset_id']
        self.reject(fixture, 'dataset')

    def test_available_scopes_do_not_form_synthetic_cross_product(self):
        fixture = binding_fixture()
        fixture[1][0]['available_scopes'] = [dict(region='USA', delay=0, universe='TOP3000'),
                                             dict(region='EUR', delay=1, universe='TOP3000')]
        self.reject(fixture)
        fixture[1][0]['available_scopes'].append(dict(region='USA', delay=1, universe='TOP3000'))
        self.assertEqual(self.bind(fixture)['bound_expression'], 'rank(cash / debt)')

    def test_partial_captured_scope_must_not_borrow_top_level_facts(self):
        fixture = binding_fixture()
        fixture[1][0]['available_scopes'] = [dict(delay=1, universe='TOP3000')]
        self.reject(fixture, 'scope')

    def test_units_and_grain_must_be_documented_text_not_boolean_facts(self):
        fixture = binding_fixture()
        fixture[1][0]['units'] = False
        self.reject(fixture, 'units')
        fixture = binding_fixture()
        fixture[0]['input_slots'][0]['field_type'] = 'VECTOR'
        fixture[0]['input_slots'][0]['reduction'] = dict(operator='vec_avg', parameters={})
        fixture[1][0].update(field_type='VECTOR', vector_grain=True)
        self.reject(fixture, 'vector_grain')

    def test_duplicate_operator_rows_do_not_select_first_definition(self):
        fixture = binding_fixture()
        fixture[2].append(copy.deepcopy(fixture[2][0]))
        self.reject(fixture, 'ambiguous')

    def test_explicit_multiarg_reduction_parameters_are_checked(self):
        fixture = binding_fixture()
        fixture[0]['input_slots'] = [dict(fixture[0]['input_slots'][0], field_type='VECTOR',
                                         reduction=dict(operator='vec_percentage', parameters={'percentage': 0.5}))]
        fixture[1][0].update(field_type='VECTOR', vector_grain='event')
        fixture[0]['skeleton'] = 'rank(vec_percentage({flow}, percentage=0.8))'
        self.reject(fixture, 'parameters')

    def test_same_id_distinct_semantics_still_ambiguous_across_datasets(self):
        fixture = binding_fixture()
        fixture[1].append(dict(fixture[1][0], dataset_id='other', field_description='Unrelated measurement'))
        self.reject(fixture, 'ambiguous')

    def test_missing_vector_reduction_not_inferred_from_name(self):
        fixture = binding_fixture()
        fixture[0]['input_slots'][0]['field_type'] = 'VECTOR'
        fixture[1][0].update(field_type='VECTOR', vector_grain='event')
        self.reject(fixture, 'type')

    def test_explicit_reduction_must_agree_with_declared_slot(self):
        fixture = binding_fixture()
        fixture[0]['input_slots'] = [dict(fixture[0]['input_slots'][0], field_type='VECTOR',
                                         reduction=dict(operator='vec_avg', parameters={}))]
        fixture[0]['skeleton'] = 'rank(vec_count({flow}))'
        fixture[1][0].update(field_type='VECTOR', vector_grain='event')
        self.reject(fixture, 'reduction')

    def test_optional_documented_parameter_and_typed_defaults(self):
        fixture = binding_fixture()
        fixture[2][0]['definition']['parameters'].append(dict(name='rate', type='FLOAT', required=False, default=0.5))
        self.assertEqual(self.bind(fixture)['operator_call_count'], 1)
        fixture[0]['skeleton'] = 'rank({flow} / {liability}, rate=True)'
        self.reject(fixture, 'type')

    def test_malformed_inputs_always_raise_binding_error(self):
        for template in [None, {}, dict(binding_version=True), dict(binding_version=3)]:
            self.reject((template, [], [], {}))


    def test_legacy_field_window_and_explicit_vector_preserved(self):
        template = dict(skeleton='rank(ts_mean(vec_count({field}), {window}))')
        result = self.bind((template, [dict(id='buzz', type='VECTOR')], [], {}))
        self.assertEqual(result['bound_expression'], 'rank(ts_mean(vec_count(buzz), 20))')
        self.assertEqual(result['operator_call_count'], 3)


def project_window_fixture(default=None, *, legacy=False):
    """Input: optional literal default, legacy bool. Output: design/resources/scope/template tuple; fictional sourced window policy."""
    from tests.test_hypothesis_design import compiler_fixture
    from tests.test_resource_evidence import operator_fixture
    from wqb.hypothesis_design import validate_hypothesis_design
    from wqb.semantic_contracts import SemanticPolicy
    from wqb.knowledge_contracts import render_front_matter
    design, resources, scope = compiler_fixture(treatment=True)
    row, index, texts = operator_fixture('ts_delta', integer=legacy)
    if not legacy:
        row['definition_basis'].update(rule_id='ts_delta_project_window', rule_version=2)
    if default is not None:
        premise = row['definition_basis']['signature_premise']
        path = premise['evidence_ref']['source_path']
        old = premise['locator']['quote']
        quote = old.replace('ts_delta(x, d)', f'ts_delta(x, d={default})')
        body = texts[path].split('---\n', 2)[-1].replace(old, quote)
        digest = hashlib.sha256(body.encode()).hexdigest()
        index[path]['content_hash'] = digest
        texts[path] = render_front_matter({k: v for k, v in index[path].items() if k != 'file_sha256'}) + body
        index[path]['file_sha256'] = hashlib.sha256(texts[path].encode()).hexdigest()
        premise['locator']['quote'] = quote
        premise['evidence_ref']['sha256'] = digest
        for ref in row['definition']['evidence_refs']:
            if ref['source_path'] == path:
                ref['sha256'] = digest
        row['definition']['parameters'][1].update(required=False, default=default)
        row['definition_basis']['definition_digest'] = hashlib.sha256(json.dumps(
            row['definition'], sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    resources['operator_rows'] = [row]
    pack = resources['evidence_pack']
    for target in (resources, pack):
        target['resource_contract_version'] = 2
        target['source_index'].update(copy.deepcopy(index))
        target['source_texts'].update(copy.deepcopy(texts))
    raw = {k: v for k, v in design.items() if k != 'design_id'}
    raw['experiment_plan']['treatments'][0]['feature']['horizon'] = 17
    design = validate_hypothesis_design(dict(summary='Fictional proposal.', designs=[raw]), pack, SemanticPolicy())['designs'][0]
    template = dict(template_id='project-window', binding_version=2,
                    skeleton='ts_delta({pulse}, 17)', input_slots=copy.deepcopy(design['field_roles']))
    for slot in template['input_slots']:
        slot['role'] = 'signal'
    return design, resources, scope, template


class ProjectWindowBindingTests(unittest.TestCase):
    def test_positive_forms_defaults_and_legacy_nonnegative_zero_are_preserved(self):
        """Input: valid project forms and legacy nonnegative rule. Output: None; no legacy bounds upgrade."""
        for expression, default in (('ts_delta({pulse}, 17)', None), ('ts_delta({pulse}, d=17)', None),
                                    ('ts_delta({pulse}, {window})', None), ('ts_delta({pulse})', 17)):
            with self.subTest(expression=expression):
                _, resources, scope, template = project_window_fixture(default)
                template['skeleton'], scope['window'] = expression, 17
                result = bind_template(template, resources['field_rows'], resources['operator_rows'], scope,
                                       resource_contract_version=2, evidence_context=resources)
                self.assertIn('ts_delta', result['bound_expression'])
        from tests.test_resource_evidence import OperatorDefinitionResolutionTests
        _, resources, scope, template = project_window_fixture(0, legacy=True)
        row = resources['operator_rows'][0]
        premise = row['definition_basis']['type_premises'][-1]
        path = premise['evidence_ref']['source_path']
        old = premise['locator']['quote']
        premise['locator']['quote'] = old.replace('positive', 'non-negative')
        body = resources['source_texts'][path].split('---\n', 2)[-1].replace(old, premise['locator']['quote'])
        OperatorDefinitionResolutionTests().rehash((row, resources['source_index'], resources['source_texts']), path, body)
        for expression in ('ts_delta({pulse}, 0)', 'ts_delta({pulse}, d=0)', 'ts_delta({pulse})',
                           'ts_delta({pulse}, 2521)'):
            template['skeleton'] = expression
            result = bind_template(template, resources['field_rows'], resources['operator_rows'], scope,
                                   resource_contract_version=2, evidence_context=resources)
            self.assertNotIn('parameter_policy', result['operator_provenance'][0]['definition_receipt'])
        template['binding_version'] = 1
        template['skeleton'] = 'ts_delta({field}, 17)'
        _, project, _, _ = project_window_fixture()
        with self.assertRaises(TemplateBindingError):
            bind_template(template, project['field_rows'], project['operator_rows'], scope,
                          resource_contract_version=2, evidence_context=project)

    def test_bound_project_windows_reject_invalid_argument_forms(self):
        """Input: literal/keyword/unary/placeholder/default cases. Output: None; invalid project d never binds."""
        for value in (0, -1, 2521):
            for form in ('positional', 'keyword', 'placeholder', 'default'):
                with self.subTest(value=value, form=form):
                    _, resources, scope, template = project_window_fixture(value if form == 'default' else None)
                    template['skeleton'] = {'positional': f'ts_delta({{pulse}}, {value})',
                        'keyword': f'ts_delta({{pulse}}, d={value})', 'placeholder': 'ts_delta({pulse}, {window})',
                        'default': 'ts_delta({pulse})'}[form]
                    scope['window'] = value
                    with self.assertRaises(TemplateBindingError):
                        bind_template(template, resources['field_rows'], resources['operator_rows'], scope,
                                      resource_contract_version=2, evidence_context=resources)

    def test_current_project_window_receipt_reused_and_v2_context_required(self):
        """Input: valid repeated operator and unsupported contexts. Output: None; one verified receipt per local operator."""
        from unittest.mock import patch
        from wqb.resource_evidence import resolve_operator_definition
        _, resources, scope, template = project_window_fixture()
        template['skeleton'] = 'ts_delta({pulse}, +17) + ts_delta({pulse}, d=2520)'
        with patch('wqb.resource_evidence.resolve_operator_definition', wraps=resolve_operator_definition) as resolver:
            result = bind_template(template, resources['field_rows'], resources['operator_rows'], scope,
                                   resource_contract_version=2, evidence_context=resources)
            self.assertEqual(resolver.call_count, 1)
        self.assertEqual(result['operator_call_count'], 2)
        self.assertEqual(result['operator_provenance'][0]['definition_receipt']['rule_id'], 'ts_delta_project_window')
        for version, context in ((1, resources), (2, None), (2, {})):
            with self.subTest(version=version, context=context is None), self.assertRaises(TemplateBindingError):
                bind_template(template, resources['field_rows'], resources['operator_rows'], scope,
                              resource_contract_version=version, evidence_context=context)


if __name__ == '__main__':
    unittest.main()
