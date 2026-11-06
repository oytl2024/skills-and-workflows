"""Fictional offline records exercise the Task2 proposal boundary only."""

from copy import deepcopy
import hashlib
import unittest

from wqb.hypothesis_design import design_output_schema, validate_hypothesis_design
from wqb.semantic_contracts import SemanticPolicy
from wqb.semantic_compilation import _check_schema


def fixture():
    """Input: none. Output: (answer, pack) dict pair with fictional sourced facts."""
    path = 'raw/platform/fictional/notes.txt'
    text = 'Fictional pulse is a matrix observation; fictional cluster is a grouping.'
    digest = hashlib.sha256(text.encode()).hexdigest()
    ref = dict(source_path=path, sha256=digest, capture_date='2026-10-14',
               kind='hypothesis', experiment_refs=[])
    pack = dict(source_index={path: dict(path=path, content_hash=digest,
                captured_at='2026-10-14T00:00:00Z', source_type='platform_learn_material',
                source_family='raw/platform/fictional')},
                scope=dict(region='FICTION', universe='OFFLINE', delay=1),
                allowed_role_semantics=['fictional_pulse', 'fictional_cluster'],
                allowed_operator_intents=['level', 'change', 'group_rank', 'group_demean'],
                source_texts={path: text}, histories=[])
    leaf = dict(kind='role', role='pulse')
    feature = dict(kind='level', input=leaf)
    design = dict(design_version=1, trigger_id=path, mechanism_family='fictional_response',
                  condition_id='fictional_scope', data_meaning='Fictional pulse records an observation.',
                  economic_rationale='A fictional response may follow the observation.',
                  prediction='The fictional response may be positive.', prediction_direction='positive',
                  conditions=dict(mode='interpretive', description='Interpret within the fictional scope.',
                                  observable_roles=[]),
                  alternative_explanation='A fictional common cause may explain the response.',
                  falsification='An absent response would challenge this prediction.',
                  operator_rationale='Level preserves the fictional observation.',
                  field_roles=[dict(name='pulse', required_semantics=['fictional_pulse'],
                                    field_type='MATRIX', required_metadata=['available_at', 'units'])],
                  feature_plan=feature,
                  experiment_plan=dict(baseline=deepcopy(feature), treatments=[],
                       controls=['Hold scope and non-treatment settings fixed.'],
                       rejection_criteria='Reject if the predicted direction reverses.',
                       inconclusive_criteria='Missing observations make the comparison inconclusive.'),
                  evidence_refs=[ref])
    return dict(summary='A fictional offline proposal.', designs=[design]), pack


class HypothesisDesignTests(unittest.TestCase):
    def test_resource_version_is_producer_owned_and_strict(self):
        answer, pack = fixture()
        pack['resource_contract_version'] = 2
        first = validate_hypothesis_design(answer, pack, SemanticPolicy())
        self.assertNotEqual(first['designs'][0]['design_id'],
            validate_hypothesis_design(answer, fixture()[1], SemanticPolicy())['designs'][0]['design_id'])
        for value in (True, False, 0, 3, '2', 2.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_hypothesis_design(answer, dict(pack, resource_contract_version=value), SemanticPolicy())
        answer['resource_contract_version'] = 2
        with self.assertRaises(ValueError):
            validate_hypothesis_design(answer, pack, SemanticPolicy())

    def test_v2_role_timing_requirement_is_not_a_v1_escape(self):
        answer, pack = fixture()
        answer['designs'][0]['field_roles'][0]['required_metadata'] = ['timing_contract']
        with self.assertRaises(ValueError):
            validate_hypothesis_design(answer, pack, SemanticPolicy())
        pack['resource_contract_version'] = 2
        validate_hypothesis_design(answer, pack, SemanticPolicy())

    def setUp(self):
        """Input: unittest instance. Output: None; fresh independent JSON fixtures."""
        self.answer, self.pack = fixture()

    def validate(self, answer=None, pack=None, policy=None):
        """Input: optional dicts/policy. Output: dict from the real validator."""
        return validate_hypothesis_design(self.answer if answer is None else answer,
                                          self.pack if pack is None else pack,
                                          SemanticPolicy() if policy is None else policy)

    def test_schema_and_validator_agree_on_fixture(self):
        _check_schema(design_output_schema(), self.answer)
        result = self.validate()
        self.assertRegex(result['designs'][0]['design_id'], r'^design_[0-9a-f]{64}$')
        self.assertNotIn('design_id', self.answer['designs'][0])
        self.assertEqual(result['summary'], self.answer['summary'])

    def test_unknown_keys_and_ai_identity_are_rejected_at_every_boundary(self):
        targets = [self.answer, self.answer['designs'][0], self.answer['designs'][0]['conditions'],
                   self.answer['designs'][0]['field_roles'][0],
                   self.answer['designs'][0]['feature_plan'],
                   self.answer['designs'][0]['experiment_plan'],
                   self.answer['designs'][0]['evidence_refs'][0]]
        for target in targets:
            with self.subTest(target=list(target)):
                target['design_id'] = 'invented'
                with self.assertRaises(ValueError):
                    self.validate()
                del target['design_id']

    def test_missing_fields_and_empty_strings_are_rejected(self):
        for key in list(self.answer['designs'][0]):
            changed = deepcopy(self.answer)
            del changed['designs'][0][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(changed)
        for value in ['', ' ', 'One sentence. Another sentence.']:
            self.answer['designs'][0]['economic_rationale'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate()

    def test_measured_claims_require_supplied_history(self):
        for value in ['Sharpe is 2.4.', 'Backtest proved positive returns.',
                      'Correlation is low.', 'Measured performance is excellent.']:
            self.answer['designs'][0]['economic_rationale'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate()

    def test_natural_prose_is_data_not_an_executable_feature(self):
        for value in ['A fictional x / y comparison may be relevant.',
                      'The words ts_delta(field, days) are descriptive data.',
                      'The token __import__("os") remains text.']:
            self.answer['designs'][0]['economic_rationale'] = value
            self.validate()

    def test_non_json_nonfinite_overflow_and_bool_horizons(self):
        for value in [float('nan'), float('inf'), -float('inf'), 10**400, True, 0, 100000, '5']:
            changed = deepcopy(self.answer)
            feature = dict(kind='change', input=dict(kind='role', role='pulse'), horizon=value)
            changed['designs'][0]['feature_plan'] = feature
            changed['designs'][0]['experiment_plan']['baseline'] = deepcopy(feature)
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError):
                self.validate(changed)
        self.answer['summary'] = {'not_json': {1, 2}}
        with self.assertRaises(ValueError):
            self.validate()

    def test_supported_grammar_and_treatment(self):
        design = self.answer['designs'][0]
        leaf = dict(kind='role', role='pulse')
        group = dict(kind='role', role='cluster')
        for feature in [leaf, dict(kind='level', input=leaf),
                        dict(kind='change', input=leaf, horizon=5),
                        dict(kind='relative', input=leaf, group_role=group, comparison='group_rank'),
                        dict(kind='relative', input=leaf, group_role=group, comparison='group_demean')]:
            with self.subTest(feature=feature):
                if feature['kind'] == 'relative' and len(design['field_roles']) == 1:
                    design['field_roles'].append(dict(name='cluster', required_semantics=['fictional_cluster'],
                        field_type='GROUP', required_metadata=['available_at']))
                design['feature_plan'] = feature
                design['experiment_plan']['baseline'] = deepcopy(feature)
                self.validate()
        design['experiment_plan']['treatments'] = [dict(feature=dict(kind='level', input=leaf),
                                                       rationale='Compare level against relative intent.')]
        self.validate()

    def test_arbitrary_operators_nested_features_and_wrong_group_are_rejected(self):
        leaf = dict(kind='role', role='pulse')
        for feature in [dict(kind='ratio', input=leaf), dict(kind='operator', operator='add'),
                        dict(kind='level', input=dict(kind='level', input=leaf)),
                        dict(kind='change', input=leaf, horizon=5, formula='x/y'),
                        dict(kind='relative', input=leaf, group_role=leaf, comparison='group_rank'),
                        dict(kind='relative', input=leaf, group_role=leaf, comparison='regression'),
                        dict(kind='role', role='fabricated_field_id')]:
            changed = deepcopy(self.answer)
            changed['designs'][0]['feature_plan'] = feature
            changed['designs'][0]['experiment_plan']['baseline'] = deepcopy(feature)
            with self.subTest(feature=feature), self.assertRaises(ValueError):
                self.validate(changed)

    def test_roles_are_requirements_not_field_ids(self):
        for key, value in [('field_id', 'invented'), ('required_semantics', ['invented']),
                           ('field_type', 'UNKNOWN'), ('required_metadata', []),
                           ('required_metadata', ['invented']), ('name', 'x / y')]:
            changed = deepcopy(self.answer)
            changed['designs'][0]['field_roles'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(changed)
        self.answer['designs'][0]['field_roles'] *= 2
        with self.assertRaises(ValueError):
            self.validate()

    def test_conditions_do_not_turn_narratives_into_filters(self):
        condition = self.answer['designs'][0]['conditions']
        condition.update(mode='observable', observable_roles=['pulse'])
        self.validate()
        for mode, roles in [('observable', []), ('observable', ['invented']),
                            ('interpretive', ['pulse']), ('unidentifiable', ['pulse']),
                            ('filter', ['pulse'])]:
            condition.update(mode=mode, observable_roles=roles)
            with self.subTest(mode=mode, roles=roles), self.assertRaises(ValueError):
                self.validate()
        condition.update(mode='unidentifiable', observable_roles=[])
        self.validate()

    def test_source_identity_capture_kind_and_trigger_are_bound(self):
        for key, value in [('source_path', '../escape'), ('source_path', 'raw/platform/missing.txt'),
                           ('sha256', '0'*64), ('capture_date', '2026-10-13'), ('kind', 'measured'),
                           ('kind', 'invented'), ('experiment_refs', ['raw/research/invented'])]:
            changed = deepcopy(self.answer)
            changed['designs'][0]['evidence_refs'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(changed)
        self.answer['designs'][0]['trigger_id'] = 'invented'
        with self.assertRaises(ValueError):
            self.validate()

    def test_optional_source_bytes_checked_but_metadata_is_not_verification(self):
        self.pack.pop('source_texts')
        self.validate()  # Caller owns prior actual-source verification, not this parser.
        path = self.answer['designs'][0]['trigger_id']
        self.pack['source_texts'] = {path: 'Different bytes.'}
        with self.assertRaises(ValueError):
            self.validate()

    def test_missing_pack_scope_semantics_and_intents_fail_closed(self):
        for key in ['scope', 'source_index', 'allowed_role_semantics', 'allowed_operator_intents']:
            changed = deepcopy(self.pack)
            changed.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(pack=changed)
        self.pack['allowed_operator_intents'] = ['change']
        with self.assertRaises(ValueError):
            self.validate()

    def test_experiment_requires_baseline_controls_and_inconclusive_criteria(self):
        exp = self.answer['designs'][0]['experiment_plan']
        for key, value in [('controls', []), ('inconclusive_criteria', ''),
                           ('rejection_criteria', ''), ('baseline', dict(kind='role', role='pulse')),
                           ('treatments', [dict(feature=exp['baseline'], rationale='Same feature.')]),
                           ('treatments', [dict(feature=dict(kind='role', role='pulse'),
                                               rationale='Change the feature.')] * 2)]:
            changed = deepcopy(self.answer)
            changed['designs'][0]['experiment_plan'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(changed)

    def test_maxima_are_not_fill_targets_and_apply_per_trigger(self):
        self.validate()
        designs = self.answer['designs']
        for index in range(1, 4):
            branch = deepcopy(designs[0])
            branch['mechanism_family'] = f'fictional_{index}'
            designs.append(branch)
        with self.assertRaises(ValueError):
            self.validate()
        designs.pop()
        self.validate()
        with self.assertRaises(ValueError):
            self.validate(policy=SemanticPolicy(max_mechanisms=2))

    def test_conditions_require_structured_difference_not_narrative_or_window_padding(self):
        designs = self.answer['designs']
        other = deepcopy(designs[0])
        other['condition_id'] = 'other'
        other['conditions']['description'] = 'Interpret in another fictional condition.'
        designs.append(other)
        with self.assertRaises(ValueError):
            self.validate()
        other['feature_plan'] = dict(kind='change', input=dict(kind='role', role='pulse'), horizon=9)
        other['experiment_plan']['baseline'] = deepcopy(other['feature_plan'])
        with self.assertRaises(ValueError):
            self.validate()
        other['prediction_direction'] = 'negative'
        self.validate()
        third = deepcopy(other)
        third['condition_id'] = 'third'
        third['prediction_direction'] = 'unknown'
        designs.append(third)
        with self.assertRaises(ValueError):
            self.validate()

    def test_duplicate_branch_and_empty_designs_rejected(self):
        self.answer['designs'] *= 2
        with self.assertRaises(ValueError):
            self.validate()
        self.answer['designs'] = []
        with self.assertRaises(ValueError):
            self.validate()

    def test_identity_normalizes_order_whitespace_and_hash_case_without_mutation(self):
        before = deepcopy((self.answer, self.pack))
        first = self.validate()['designs'][0]['design_id']
        self.assertEqual((self.answer, self.pack), before)
        design = self.answer['designs'][0]
        design['economic_rationale'] = '  ' + design['economic_rationale'] + '  '
        design['evidence_refs'][0]['sha256'] = design['evidence_refs'][0]['sha256'].upper()
        design['field_roles'][0]['required_metadata'].reverse()
        self.assertEqual(self.validate()['designs'][0]['design_id'], first)
        self.answer['summary'] = 'Different batch summary.'
        self.assertEqual(self.validate()['designs'][0]['design_id'], first)

    def test_identity_binds_scope_evidence_and_contract_version(self):
        first = self.validate()['designs'][0]['design_id']
        self.pack['scope']['delay'] = 2
        self.assertNotEqual(self.validate()['designs'][0]['design_id'], first)
        self.pack['scope']['delay'] = 1
        path = self.answer['designs'][0]['trigger_id']
        text = 'A revised fictional sourced record.'
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.pack['source_texts'][path] = text
        self.pack['source_index'][path]['content_hash'] = digest
        self.answer['designs'][0]['evidence_refs'][0]['sha256'] = digest
        self.assertNotEqual(self.validate()['designs'][0]['design_id'], first)
        # Task3 must change the public version when lowering semantics change.
        from unittest.mock import patch
        with patch('wqb.hypothesis_design.COMPILER_VERSION', 'future-test-version'):
            future = self.validate()['designs'][0]['design_id']
        self.assertNotEqual(self.validate()['designs'][0]['design_id'], future)

    def test_history_is_bounded_and_cannot_supply_new_measurements(self):
        self.pack['histories'] = [dict(statement='Measured performance is excellent.', evidence_refs=[])]
        with self.assertRaises(ValueError):
            self.validate()
        self.pack['histories'] = [{}] * 33
        with self.assertRaises(ValueError):
            self.validate()

    def test_existing_source_index_optional_empty_metadata_is_accepted(self):
        from dataclasses import asdict
        from wqb.knowledge_contracts import SourceIndexRow
        path = self.answer['designs'][0]['trigger_id']
        source = self.pack['source_index'][path]
        self.pack['source_index'][path] = asdict(SourceIndexRow(**source,
            contents='', update_check='', content_status=''))
        self.validate()

    def test_role_renaming_is_not_a_conditional_distinction(self):
        other = deepcopy(self.answer['designs'][0])
        other['condition_id'] = 'renamed'
        other['field_roles'][0]['name'] = 'renamed_pulse'
        other['feature_plan']['input']['role'] = 'renamed_pulse'
        other['experiment_plan']['baseline'] = deepcopy(other['feature_plan'])
        self.answer['designs'].append(other)
        with self.assertRaises(ValueError):
            self.validate()

    def test_level_leaf_alias_is_not_a_treatment(self):
        self.answer['designs'][0]['experiment_plan']['treatments'] = [
            dict(feature=dict(kind='role', role='pulse'), rationale='A redundant alias.')]
        with self.assertRaises(ValueError):
            self.validate()

    def test_unused_roles_cannot_pad_a_branch(self):
        self.answer['designs'][0]['field_roles'].append(dict(name='unused',
            required_semantics=['fictional_cluster'], field_type='GROUP',
            required_metadata=['available_at']))
        with self.assertRaises(ValueError):
            self.validate()

    def test_measured_refs_require_existing_verified_history_not_just_index_rows(self):
        path = 'raw/research/fictional/result.json'
        text = 'Measured performance is excellent.'
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.pack['source_index'][path] = dict(path=path, content_hash=digest,
            captured_at='2026-10-14T00:00:00Z', source_type='research_record_source',
            source_family='raw/research/fictional')
        ref = dict(source_path=path, sha256=digest, capture_date='2026-10-14',
                   kind='measured', experiment_refs=[path])
        self.answer['designs'][0]['evidence_refs'].append(ref)
        with self.assertRaises(ValueError):
            self.validate()
        self.pack['source_texts'][path] = text
        self.pack['histories'] = [dict(statement=text, evidence_refs=[ref])]
        self.answer['designs'][0]['economic_rationale'] = text
        self.validate()
        self.pack['source_texts'].pop(path)
        with self.assertRaises(ValueError):
            self.validate()
        other_text = 'A fictional record with no performance statement.'
        other_digest = hashlib.sha256(other_text.encode()).hexdigest()
        self.pack['source_texts'][path] = other_text
        self.pack['source_index'][path]['content_hash'] = other_digest
        ref['sha256'] = other_digest
        with self.assertRaises(ValueError):
            self.validate()
        self.pack['source_texts'][path] = text
        self.pack['source_index'][path]['content_hash'] = digest
        ref['sha256'] = digest
        self.answer['designs'][0]['economic_rationale'] = 'Measured performance is poor.'
        with self.assertRaises(ValueError):
            self.validate()

    def test_exact_supplied_semantic_phrases_are_preserved(self):
        self.pack['allowed_role_semantics'] = ['Cash balance', 'Fictional pulse (Q2)']
        self.answer['designs'][0]['field_roles'][0]['required_semantics'] = ['Cash balance']
        result = self.validate()
        self.assertEqual(result['designs'][0]['field_roles'][0]['required_semantics'], ['Cash balance'])
        self.answer['designs'][0]['field_roles'][0]['required_semantics'] = ['Fictional pulse (Q2)']
        self.validate()
        self.answer['designs'][0]['field_roles'][0]['required_semantics'] = ['cash_balance']
        with self.assertRaises(ValueError):
            self.validate()

    def test_hypothesis_history_cannot_promote_retrospective_measurement(self):
        statement = 'Measured performance is excellent.'
        ref = self.answer['designs'][0]['evidence_refs'][0]
        self.pack['histories'] = [dict(statement=statement, evidence_refs=[ref])]
        self.answer['designs'][0]['economic_rationale'] = statement
        self.pack.pop('source_texts')
        with self.assertRaises(ValueError):
            self.validate()
        # Even matching hashed source text cannot upgrade a hypothesis grade.
        path = ref['source_path']
        digest = hashlib.sha256(statement.encode()).hexdigest()
        ref['sha256'] = digest
        self.pack['source_index'][path]['content_hash'] = digest
        self.pack['source_texts'] = {path: statement}
        with self.assertRaises(ValueError):
            self.validate()

    def test_numbers_and_quarter_labels_are_not_empirical_conclusions(self):
        for statement in ['Predict returns over 20 days.', 'Q2 contains a fictional observation.']:
            self.answer['designs'][0]['prediction'] = statement
            self.validate()

    def test_markdown_body_hash_and_frontmatter_agreement(self):
        old_path = self.answer['designs'][0]['trigger_id']
        path = 'raw/platform/fictional/notes.md'
        source = self.pack['source_index'].pop(old_path)
        source['path'] = path
        body = 'Fictional pulse is a sourced observation.\n'
        source['content_hash'] = hashlib.sha256(body.encode()).hexdigest()
        self.pack['source_index'][path] = source
        ref = self.answer['designs'][0]['evidence_refs'][0]
        ref.update(source_path=path, sha256=source['content_hash'])
        self.answer['designs'][0]['trigger_id'] = path
        header = ('---\ncontent_hash: ' + source['content_hash'] +
                  '\ncaptured_at: 2026-10-14T00:00:00Z\nsource_type: platform_learn_material\n'
                  'source_family: raw/platform/fictional\n---\n')
        self.pack['source_texts'] = {path: (header + body).replace('\n', '\r\n')}
        self.validate()
        for original, replacement in [('2026-10-14T00:00:00Z', '2026-10-13T00:00:00Z'),
                ('platform_learn_material', 'research_record_source'),
                ('raw/platform/fictional', 'raw/platform/other'),
                (source['content_hash'], '0' * 64)]:
            self.pack['source_texts'][path] = (header.replace(original, replacement) + body)
            with self.subTest(header=original), self.assertRaises(ValueError):
                self.validate()
        self.pack['source_texts'][path] = header + body + 'Altered body.\n'
        with self.assertRaises(ValueError):
            self.validate()

    def test_full_source_text_above_prose_limit_is_not_truncated(self):
        old_path = self.answer['designs'][0]['trigger_id']
        path = 'raw/platform/fictional/full.md'
        source = self.pack['source_index'].pop(old_path)
        source['path'] = path
        self.pack['source_index'][path] = source
        self.answer['designs'][0]['trigger_id'] = path
        self.answer['designs'][0]['evidence_refs'][0]['source_path'] = path
        body = 'Fictional sourced observation.\n' * 1500
        self.assertGreater(len(body.encode()), 7000)
        digest = hashlib.sha256(body.encode()).hexdigest()
        text = '---\ncontent_hash: ' + digest + '\n---\n' + body
        self.pack['source_texts'].pop(old_path)
        self.pack['source_texts'][path] = text
        source['content_hash'] = digest
        self.answer['designs'][0]['evidence_refs'][0]['sha256'] = digest
        source['file_sha256'] = hashlib.sha256(text.encode()).hexdigest()
        self.validate()
        source['file_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.validate()
        source.pop('file_sha256')
        self.pack['source_texts'][path] = text + 'A changed tail.'
        with self.assertRaises(ValueError):
            self.validate()
        oversized = 'x' * 999950
        self.pack['source_texts'][path] = oversized
        source['content_hash'] = hashlib.sha256(oversized.encode()).hexdigest()
        self.answer['designs'][0]['evidence_refs'][0]['sha256'] = source['content_hash']
        with self.assertRaisesRegex(ValueError, 'oversized evidence pack'):
            self.validate()

    def test_malformed_source_index_rows_raise_value_error(self):
        path = self.answer['designs'][0]['trigger_id']
        for source in [None, [], 'not a row', dict(content_hash=None)]:
            self.pack['source_index'][path] = source
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.validate()

    def test_explicit_plan_threshold_is_not_a_claim_of_measured_results(self):
        self.answer['designs'][0]['experiment_plan']['rejection_criteria'] = 'Reject if Sharpe is below 0.5.'
        self.validate()


def source_backed_compiler_fixture():
    """Input: none. Output: design/resources/scope tuple using offline actual-format policy facts."""
    from tests.test_resource_evidence import timing_fixture
    timing, row, scope, index, texts = timing_fixture()
    answer, pack = fixture()
    _, legacy, _ = compiler_fixture()
    pack.update(resource_contract_version=2, scope=scope, source_index=index, source_texts=texts,
                allowed_role_semantics=['A captured measurement.'])
    source = index['raw/platform/data_fields/fields.jsonl']
    ref = dict(source_path=source['path'], sha256=source['content_hash'],
               capture_date='2026-10-15', kind='hypothesis', experiment_refs=[])
    raw = answer['designs'][0]
    raw.update(trigger_id=source['path'], evidence_refs=[ref])
    raw['field_roles'][0].update(required_semantics=['A captured measurement.'],
                                required_metadata=['timing_contract'])
    row.update(timing_contract=timing, field_description='A captured measurement.',
               semantic_tags=[], source_paths=[source['path']])
    resources = dict(resource_contract_version=2, field_rows=[row], operator_rows=[],
                     source_index=index, source_texts=texts, evidence_pack=pack,
                     settings=dict(legacy['settings'], region='USA', universe='TOP3000'))
    design = validate_hypothesis_design(answer, pack, SemanticPolicy())['designs'][0]
    return design, resources, scope


def compiler_fixture(kind='level', treatment=False):
    """Input: feature kind str/pair bool. Output: normalized design/resources/scope dicts."""
    import json
    answer, pack = fixture()
    scope = dict(pack['scope'], as_of='2026-10-14T00:00:00Z', instrument_type='EQUITY')
    pack['scope'] = scope
    design = answer['designs'][0]
    leaf = dict(kind='role', role='pulse')
    if kind == 'change':
        design['feature_plan'] = dict(kind='change', input=leaf, horizon=5)
    if kind in ('group_rank', 'group_demean'):
        design['field_roles'].append(dict(name='cluster', field_type='GROUP',
            required_semantics=['fictional_cluster'], required_metadata=['available_at']))
        design['feature_plan'] = dict(kind='relative', input=leaf,
            group_role=dict(kind='role', role='cluster'), comparison=kind)
    design['experiment_plan']['baseline'] = deepcopy(design['feature_plan'])
    if treatment:
        design['experiment_plan']['treatments'] = [dict(
            feature=dict(kind='change', input=leaf, horizon=5), rationale='Compare change with level.')]
    fields = []
    for role in design['field_roles']:
        fields.append(dict(field_id=role['name'] + '_field', dataset_id='fictional',
            field_type=role['field_type'], field_description=role['required_semantics'][0],
            semantic_tags=role['required_semantics'], units='score',
            available_at='2026-10-13T00:00:00Z', **scope))
    operators = []
    for name, inputs, description in [
        ('ts_delta', ['MATRIX'], 'Returns x - ts_delay(x, d).'),
        ('group_rank', ['MATRIX', 'GROUP'], 'Ranks x within each group.'),
        ('group_neutralize', ['MATRIX', 'GROUP'], 'Subtracts the group mean from x.')]:
        parameters = [dict(name=param, type=typ, required=True)
                      for param, typ in zip(['x', 'group'], inputs)]
        if name == 'ts_delta':
            parameters.append(dict(name='d', type='INTEGER', required=True))
        operators.append(dict(operator=name, definition=dict(description=description,
            input_types=inputs, output_type='MATRIX', parameters=parameters)))
    path = 'raw/platform/fictional/compiler.json'
    text = json.dumps(dict(fields=[dict(field=dict(id=row['field_id'],
        description=row['field_description'], type=row['field_type'],
        **{key: row[key] for key in ('units', 'available_at', 'semantic_tags')}),
        data_set=dict(id=row['dataset_id']), scope=scope) for row in fields], operators=operators))
    digest = hashlib.sha256(text.encode()).hexdigest()
    pack['source_index'][path] = dict(path=path, content_hash=digest,
        captured_at='2026-10-14T00:00:00Z', source_type='platform_data_field_capture',
        source_family='raw/platform/fictional')
    pack['source_texts'][path] = text
    for row in fields:
        row['source_paths'] = [path]
    for row in operators:
        row['definition']['evidence_refs'] = [dict(source_path=path, sha256=digest,
            capture_date='2026-10-14', kind='documented', experiment_refs=[])]
    normalized = validate_hypothesis_design(answer, pack, SemanticPolicy())['designs'][0]
    resources = dict(field_rows=fields, operator_rows=operators,
        source_index=deepcopy(pack['source_index']), source_texts=deepcopy(pack['source_texts']),
        evidence_pack=pack, settings=dict(instrumentType='EQUITY', region=scope['region'],
            universe=scope['universe'], delay=1, decay=4, neutralization='NONE', truncation=0.08,
            pasteurization='ON', unitHandling='VERIFY', nanHandling='OFF', language='FASTEXPR',
            visualization=False))
    return normalized, resources, deepcopy(scope)


class HypothesisCompilerTests(unittest.TestCase):
    def test_v2_direct_typed_group_preserves_actual_description_without_basis(self):
        import json
        from tests.test_resource_evidence import operator_fixture
        from wqb.hypothesis_design import compile_hypothesis_design
        for kind, name in [('group_rank', 'group_rank'), ('group_demean', 'group_neutralize')]:
            design, resources, scope = compiler_fixture(kind)
            row = operator_fixture(name)[0]
            row.pop('definition_basis')
            description = row['definition']['description']
            path = 'raw/platform/learn/direct_group.json'
            # Explicitly typed offline source, not a claim about fetched operator details.
            text = json.dumps(dict(operator=name, definition={k: v for k, v in row['definition'].items()
                                                           if k != 'evidence_refs'}))
            digest = hashlib.sha256(text.encode()).hexdigest()
            row['definition']['evidence_refs'] = [dict(source_path=path, sha256=digest,
                capture_date='2026-10-14', kind='documented', experiment_refs=[])]
            resources['operator_rows'] = [row]
            pack = resources['evidence_pack']
            for target in (pack, resources):
                target['resource_contract_version'] = 2
                target['source_index'][path] = dict(path=path, content_hash=digest,
                    captured_at='2026-10-14T00:00:00Z', source_type='platform_learn_material',
                    source_family='raw/platform/learn')
                target['source_texts'][path] = text
            raw = {k: v for k, v in design.items() if k != 'design_id'}
            design = validate_hypothesis_design(dict(summary='A proposal.', designs=[raw]), pack, SemanticPolicy())['designs'][0]
            result = compile_hypothesis_design(design, resources, scope)
            self.assertEqual(result['status'], 'compiled', result)
            provenance = result['experiment']['arms'][0]['binding']['operator_provenance'][0]
            self.assertEqual(provenance['definition_receipt']['kind'], 'direct_documentation')
            self.assertEqual(provenance['definition_receipt']['definition']['description'], description)
            self.assertNotIn('definition_basis', provenance)

    def test_v2_direct_typed_change_and_missing_integer_derivation(self):
        from tests.test_resource_evidence import operator_fixture
        from wqb.hypothesis_design import compile_hypothesis_design
        design, resources, scope = compiler_fixture('change')
        resources['resource_contract_version'] = 2
        pack = resources['evidence_pack']
        pack['resource_contract_version'] = 2
        original_path = 'raw/platform/fictional/compiler.json'
        documented_path = 'raw/platform/learn/direct.json'
        for target in (pack, resources):
            target['source_index'][documented_path] = dict(target['source_index'][original_path],
                path=documented_path, source_type='platform_learn_material', source_family='raw/platform/learn')
            target['source_texts'][documented_path] = target['source_texts'][original_path]
        for row in resources['operator_rows']:
            row['definition']['evidence_refs'][0]['source_path'] = documented_path
        raw = {k: v for k, v in design.items() if k != 'design_id'}
        design = validate_hypothesis_design(dict(summary='A proposal.', designs=[raw]), pack, SemanticPolicy())['designs'][0]
        self.assertEqual(compile_hypothesis_design(design, resources, scope)['status'], 'compiled')
        row, index, texts = operator_fixture('ts_delta', integer=False)
        resources['operator_rows'] = [row]
        for target in (pack, resources):
            target['source_index'].update(index)
            target['source_texts'].update(texts)
        result = compile_hypothesis_design(design, resources, scope)
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['rejections'][0]['code'], 'missing_operator_definition')

    def test_source_backed_group_meaning_not_legacy_english_whitelist(self):
        from tests.test_resource_evidence import operator_fixture
        from wqb.hypothesis_design import compile_hypothesis_design
        for kind, name in [('group_rank', 'group_rank'), ('group_demean', 'group_neutralize')]:
            design, resources, scope = compiler_fixture(kind)
            row, index, texts = operator_fixture(name)
            resources['operator_rows'] = [row]
            resources['resource_contract_version'] = 2
            pack = resources['evidence_pack']
            pack['resource_contract_version'] = 2
            pack['source_index'].update(index)
            pack['source_texts'].update(texts)
            resources['source_index'].update(index)
            resources['source_texts'].update(texts)
            raw = {k: v for k, v in design.items() if k != 'design_id'}
            design = validate_hypothesis_design(dict(summary='A proposal.', designs=[raw]), pack, SemanticPolicy())['designs'][0]
            result = compile_hypothesis_design(design, resources, scope)
            self.assertEqual(result['status'], 'compiled', result)
            provenance = result['experiment']['arms'][0]['binding']['operator_provenance'][0]
            self.assertEqual(provenance['definition_basis'], row['definition_basis'])
            self.assertEqual(provenance['definition_receipt']['rule_id'], name)
            self.assertEqual(row['definition']['description'], operator_fixture(name)[0]['definition']['description'])
            row['definition']['description'] = 'Adds values across unrelated groups.'
            self.assertEqual(compile_hypothesis_design(design, resources, scope)['status'], 'rejected')

    def test_v2_proposal_to_binding_receipt(self):
        from wqb.hypothesis_design import compile_hypothesis_design
        design, resources, scope = source_backed_compiler_fixture()
        result = compile_hypothesis_design(design, resources, scope)
        self.assertEqual(result['status'], 'compiled', result)
        experiment = result['experiment']
        self.assertEqual(experiment['resource_contract_version'], 2)
        receipt = experiment['context_bindings']['pulse']['timing_receipt']
        self.assertEqual(receipt['rule_version'], 3)
        self.assertFalse(receipt['historical_pit_verified'])
        self.assertEqual(set(result['drafts'][0]['source_paths']), set(resources['source_index']))
        self.assertNotIn('available_at', experiment['context_bindings']['pulse']['metadata'])
        self.assertEqual(result['drafts'][0]['semantic_status'], 'unreviewed')
        self.assertEqual(result['drafts'][0]['status'], 'scout_only')
        resources['resource_contract_version'] = 1
        self.assertEqual(compile_hypothesis_design(design, resources, scope)['status'], 'rejected')

    def test_v2_explicit_future_timestamp_still_rejected(self):
        from wqb.hypothesis_design import compile_hypothesis_design
        design, resources, scope = source_backed_compiler_fixture()
        resources['field_rows'][0]['available_at'] = '2026-10-16T00:00:00Z'
        self.assertEqual(compile_hypothesis_design(design, resources, scope)['status'], 'rejected')

    def test_v2_optional_timestamp_must_still_be_an_exact_source_fact(self):
        from wqb.hypothesis_design import compile_hypothesis_design
        design, resources, scope = source_backed_compiler_fixture()
        resources['field_rows'][0]['available_at'] = '2026-10-14T00:00:00Z'
        self.assertEqual(compile_hypothesis_design(design, resources, scope)['status'], 'rejected')

    def compile(self, data=None):
        """Input: optional fixture tuple. Output: real public compiler result dict."""
        import wqb.hypothesis_design as module
        self.assertTrue(hasattr(module, 'compile_hypothesis_design'), 'Task3 public compiler missing')
        return module.compile_hypothesis_design(*(data or compiler_fixture()))

    def reject(self, data, code):
        """Input: fixture tuple/code str. Output: None; require atomic diagnostic rejection."""
        result = self.compile(data)
        self.assertEqual(result['status'], 'rejected', result)
        self.assertEqual(result['drafts'], [])
        self.assertIsNone(result['experiment'])
        self.assertIn(code, [r['code'] for r in result['rejections']], result)
        self.assertTrue(all(r['message'] for r in result['rejections']))

    def test_public_result_pure_replay_and_template_roundtrip(self):
        from wqb.template_library import template_record_from_dict, template_record_to_dict
        data = compiler_fixture()
        before = deepcopy(data)
        result = self.compile(data)
        self.assertEqual(result['status'], 'compiled', result)
        self.assertEqual(set(result), {'status', 'drafts', 'experiment', 'rejections', 'compilation_digest'})
        self.assertEqual(self.compile(data), result)
        self.assertEqual(data, before)
        draft = result['drafts'][0]
        self.assertEqual(template_record_to_dict(template_record_from_dict(draft)), draft)
        self.assertEqual(draft['semantic_status'], 'unreviewed')
        self.assertEqual(draft['status'], 'scout_only')
        self.assertEqual(draft['binding_version'], 2)
        self.assertEqual(draft['hypothesis_id'], data[0]['design_id'])
        self.assertEqual(draft['hypothesis_card']['mechanism'], data[0]['economic_rationale'])
        self.assertEqual(result['experiment']['arms'][0]['binding']['bound_expression'], 'pulse_field')

    def test_all_supported_features_use_documented_lowering(self):
        for kind, expression in [('level', 'pulse_field'), ('change', 'ts_delta(pulse_field, 5)'),
                ('group_rank', 'group_rank(pulse_field, cluster_field)'),
                ('group_demean', 'group_neutralize(pulse_field, cluster_field)')]:
            with self.subTest(kind=kind):
                result = self.compile(compiler_fixture(kind))
                self.assertEqual(result['status'], 'compiled', result)
                arm = result['experiment']['arms'][0]
                self.assertEqual(arm['binding']['bound_expression'], expression)
                self.assertEqual(set(arm['binding']['bindings']),
                                 {r['name'] for r in result['drafts'][0]['input_slots']})

    def test_controlled_pair_and_negative_orientation(self):
        data = compiler_fixture(treatment=True)
        data[0]['prediction_direction'] = 'negative'
        self.renormalize(data)
        result = self.compile(data)
        self.assertEqual(result['status'], 'compiled', result)
        arms = result['experiment']['arms']
        self.assertEqual(len(arms), 2)
        self.assertEqual(arms[0]['settings'], arms[1]['settings'])
        self.assertEqual(arms[0]['scope'], arms[1]['scope'])
        self.assertEqual(arms[0]['binding']['bound_expression'], '-pulse_field')
        self.assertEqual(arms[1]['binding']['bound_expression'], '-ts_delta(pulse_field, 5)')
        self.assertEqual(result['experiment']['orientation'], -1)
        self.assertEqual(result['experiment']['changed_dimension'], 'feature')

    def renormalize(self, data):
        """Input: mutable fixture tuple. Output: None; derive identity after intentional design edits."""
        raw = deepcopy(data[0])
        raw.pop('design_id')
        data[0].update(validate_hypothesis_design(dict(summary='An offline proposal.', designs=[raw]),
            data[1]['evidence_pack'], SemanticPolicy())['designs'][0])

    def test_unknown_direction_rejected_not_invented(self):
        data = compiler_fixture()
        data[0]['prediction_direction'] = 'unknown'
        self.renormalize(data)
        self.reject(data, 'unsupported_feature')

    def test_tampered_normalized_design_rejected(self):
        for key, value in [('design_id', 'design_' + '0'*64), ('economic_rationale', 'A changed inference.'),
                           ('formula', 'arbitrary(x)'), ('feature_plan', dict(kind='operator', operator='rank'))]:
            data = compiler_fixture()
            data[0][key] = value
            with self.subTest(key=key):
                self.reject(data, 'invalid_design')

    def test_missing_and_tampered_source_bytes_rejected(self):
        for mode in ['missing', 'changed', 'flag']:
            data = compiler_fixture()
            path = data[1]['field_rows'][0]['source_paths'][0]
            if mode == 'changed':
                data[1]['source_texts'][path] += 'changed'
            else:
                data[1]['source_texts'].pop(path)
            if mode == 'flag':
                data[1]['verified'] = True
            with self.subTest(mode=mode):
                self.reject(data, 'invalid_resources')

    def test_source_fact_tags_metadata_and_dataset_cannot_be_forged(self):
        for key, value in [('units', 'invented'), ('field_description', 'forged'),
                ('dataset_id', 'other'),
                ('available_at', '2026-10-12T00:00:00Z')]:
            data = compiler_fixture()
            data[1]['field_rows'][0][key] = value
            with self.subTest(key=key):
                self.reject(data, 'missing_field_semantics')

    def test_required_normalized_identity_metadata_uses_capture_locations(self):
        for key in ('dataset_id', 'field_type', 'region', 'universe', 'delay'):
            data = compiler_fixture()
            data[0]['field_roles'][0]['required_metadata'].append(key)
            self.renormalize(data)
            with self.subTest(key=key):
                result = self.compile(data)
                self.assertEqual(result['status'], 'compiled', result)

    def test_conflicting_raw_alias_or_metadata_type_is_not_hidden(self):
        import json
        from wqb.knowledge_compile import _coverage_field_supported
        for key, value in [('dataset_id', 'other'), ('field_type', 'VECTOR'),
                           ('region', 'other'), ('universe', 'other'), ('delay', True)]:
            _, resources, scope = compiler_fixture()
            row = resources['field_rows'][0]
            path = row['source_paths'][0]
            facts = json.loads(resources['source_texts'][path])
            facts['fields'][0]['field'][key] = value
            texts = dict(resources['source_texts'], **{path: json.dumps(facts)})
            with self.subTest(key=key):
                self.assertFalse(_coverage_field_supported(row, texts, resources['source_index'], scope, [key]))

    def test_missing_units_and_future_availability_have_explicit_diagnostics(self):
        for key, value, code in [('units', None, 'invalid_units'),
                ('available_at', '2099-01-01T00:00:00Z', 'lookahead_risk')]:
            data = compiler_fixture()
            data[1]['field_rows'][0][key] = value
            self.reject(data, code)

    def test_scope_and_settings_are_explicit_complete_and_fixed(self):
        for mode in ['scope', 'missing', 'mismatch', 'grid', 'bool', 'extra']:
            data = compiler_fixture()
            if mode == 'scope':
                data[2]['region'] = 'OTHER'
            elif mode == 'missing':
                data[1]['settings'].pop('decay')
            elif mode == 'extra':
                data[1]['settings']['extra'] = 2
            else:
                data[1]['settings']['delay'] = {'mismatch': 2, 'grid': [1, 2], 'bool': True}[mode]
            with self.subTest(mode=mode):
                self.reject(data, 'incompatible_scope' if mode == 'scope' else 'invalid_settings')

    def test_ambiguous_same_field_or_dataset_never_disappears(self):
        for mode in ['same', 'other_dataset', 'other_id']:
            data = compiler_fixture()
            row = deepcopy(data[1]['field_rows'][0])
            if mode == 'other_dataset':
                row['dataset_id'] = 'other'
            elif mode == 'other_id':
                row['field_id'] = 'other'
            data[1]['field_rows'].append(row)
            self.reject(data, 'ambiguous_field')

    def test_operator_missing_forged_signature_meaning_or_ambiguous(self):
        for mode in ['missing', 'meaning', 'signature', 'duplicate', 'evidence']:
            data = compiler_fixture('change')
            row = data[1]['operator_rows'][0]
            if mode == 'missing':
                data[1]['operator_rows'].pop(0)
            elif mode == 'meaning':
                row['definition']['description'] = 'An unrelated transformation.'
            elif mode == 'signature':
                row['definition']['parameters'][1]['type'] = 'FLOAT'
            elif mode == 'duplicate':
                data[1]['operator_rows'].append(deepcopy(row))
            else:
                row['definition']['evidence_refs'][0]['sha256'] = '0'*64
            with self.subTest(mode=mode):
                self.reject(data, 'missing_operator_definition')

    def test_invalid_treatment_rejects_whole_experiment(self):
        data = compiler_fixture(treatment=True)
        data[1]['operator_rows'] = []
        self.reject(data, 'missing_operator_definition')

    def test_condition_only_proxy_and_unidentifiable_are_not_filters(self):
        data = compiler_fixture()
        data[0]['conditions'].update(mode='unidentifiable')
        self.renormalize(data)
        self.reject(data, 'unsupported_feature')
        data = compiler_fixture()
        role = deepcopy(data[0]['field_roles'][0])
        role['name'] = 'condition_proxy'
        data[0]['field_roles'].append(role)
        data[0]['conditions'].update(mode='observable', observable_roles=['condition_proxy'])
        self.renormalize(data)
        self.reject(data, 'unsupported_feature')

    def test_observable_role_used_in_feature_is_proxy_only(self):
        data = compiler_fixture()
        data[0]['conditions'].update(mode='observable', observable_roles=['pulse'])
        self.renormalize(data)
        result = self.compile(data)
        self.assertEqual(result['status'], 'compiled', result)
        self.assertFalse(result['experiment']['condition_filter_applied'])

    def test_vector_rejected_without_structured_reduction_intent(self):
        data = compiler_fixture()
        data[0]['field_roles'][0]['field_type'] = 'VECTOR'
        data[0]['field_roles'][0]['required_metadata'].append('vector_grain')
        self.renormalize(data)
        self.reject(data, 'unsupported_feature')

    def test_each_arm_uses_only_its_roles_and_union_freezes_all_roles(self):
        data = compiler_fixture('group_rank')
        data[0]['experiment_plan']['treatments'] = [dict(feature=dict(kind='level',
            input=dict(kind='role', role='pulse')), rationale='Compare the ungrouped level.')]
        self.renormalize(data)
        result = self.compile(data)
        self.assertEqual(result['status'], 'compiled', result)
        self.assertEqual(set(result['experiment']['context_bindings']), {'pulse', 'cluster'})
        self.assertEqual(set(result['experiment']['arms'][1]['binding']['bindings']), {'pulse'})

    def relative_pair(self, comparison):
        """Input: comparison str. Output: validated Level-to-Relative fixture tuple."""
        data = compiler_fixture(comparison)
        relative = deepcopy(data[0]['feature_plan'])
        level = dict(kind='level', input=dict(kind='role', role='pulse'))
        data[0]['feature_plan'] = level
        data[0]['experiment_plan'].update(baseline=deepcopy(level), treatments=[dict(
            feature=relative, rationale='Compare the level with its grouped relative feature.')])
        self.renormalize(data)
        return data

    def test_alias_only_and_conflicting_field_ids_are_rejected(self):
        for mode in ['alias_only', 'invented_alias', 'conflicting_ids']:
            data = compiler_fixture()
            row = data[1]['field_rows'][0]
            if mode != 'conflicting_ids':
                row['id'] = row.pop('field_id')
            else:
                row['id'] = 'conflicting_field'
            if mode == 'invented_alias':
                row.update(id='invented_field', field_description='fictional_pulse fabricated', units='fabricated')
                row.pop('source_paths')
            with self.subTest(mode=mode):
                self.reject(data, 'invalid_resources')

    def test_level_to_both_relative_pairs_preserve_shared_and_union_context(self):
        for comparison in ['group_rank', 'group_demean']:
            with self.subTest(comparison=comparison):
                data = self.relative_pair(comparison)
                original = deepcopy(data)
                result = self.compile(data)
                self.assertEqual(result['status'], 'compiled', result)
                self.assertEqual(result, self.compile(data))
                self.assertEqual(data, original)
                exp = result['experiment']
                baseline, treatment = exp['arms']
                self.assertEqual(baseline['settings'], treatment['settings'])
                self.assertEqual(baseline['scope'], treatment['scope'])
                self.assertEqual(baseline['binding']['bindings']['pulse'], treatment['binding']['bindings']['pulse'])
                self.assertEqual(set(baseline['binding']['bindings']), {'pulse'})
                self.assertEqual(set(treatment['binding']['bindings']), {'pulse', 'cluster'})
                self.assertEqual({s['name'] for s in result['drafts'][0]['input_slots']}, {'pulse'})
                self.assertEqual({s['name'] for s in result['drafts'][1]['input_slots']}, {'pulse', 'cluster'})
                context = exp['context_bindings']
                self.assertEqual(set(context), {'pulse', 'cluster'})
                self.assertEqual(context['cluster']['field_type'], 'GROUP')
                self.assertEqual(context['cluster']['field_id'], 'cluster_field')
                self.assertTrue(context['cluster']['source_paths'])
                self.assertTrue(context['cluster']['evidence_refs'])
                from wqb.hypothesis_design import _canonical
                self.assertEqual(exp['context_bindings_digest'], hashlib.sha256(_canonical(context).encode()).hexdigest())
                self.assertFalse(exp['condition_filter_applied'])
                for draft in result['drafts']:
                    self.assertEqual(validate_semantic_record_for_test(draft, data[1]['source_index']), [])
                    self.assertTrue(draft['evidence_refs'])

    def test_relative_pair_missing_or_forged_group_rejects_atomically(self):
        for comparison in ['group_rank', 'group_demean']:
            for mode in ['missing', 'description', 'units', 'source_paths', 'alias']:
                data = self.relative_pair(comparison)
                group = data[1]['field_rows'][1]
                if mode == 'missing':
                    data[1]['field_rows'].pop(1)
                elif mode == 'description':
                    group['field_description'] = 'forged group description'
                elif mode == 'units':
                    data[0]['field_roles'][0]['required_metadata'].append('units')
                    self.renormalize(data)
                    group['units'] = 'forged units'
                elif mode == 'source_paths':
                    group.pop('source_paths')
                else:
                    group['id'] = group.pop('field_id')
                with self.subTest(comparison=comparison, mode=mode):
                    self.reject(data, 'invalid_resources' if mode == 'alias' else 'missing_field_semantics')

    def test_treatment_only_group_proxy_is_not_a_baseline_filter(self):
        data = self.relative_pair('group_rank')
        data[0]['conditions'].update(mode='observable', observable_roles=['cluster'])
        self.renormalize(data)
        self.reject(data, 'unsupported_feature')

    def test_context_receipt_and_shared_bindings_do_not_allow_changed_value_field(self):
        from unittest.mock import patch
        from wqb.template_binding import bind_template
        data = self.relative_pair('group_rank')
        def changed_value(template, *args):
            """Input: real binder args. Output: binding with an injected shared-role mutation."""
            result = bind_template(template, *args)
            if template['skeleton'].startswith('group_rank'):
                result['bindings']['pulse']['metadata']['units'] = 'changed'
            return result
        with patch('wqb.hypothesis_template_compiler.bind_template', side_effect=changed_value):
            self.reject(data, 'unsupported_feature')

    def test_unused_generic_tags_do_not_block_verified_description_pair(self):
        data = self.relative_pair('group_rank')
        for row in data[1]['field_rows']:
            row['semantic_tags'] = ['fundamental', 'matrix']
        result = self.compile(data)
        self.assertEqual(result['status'], 'compiled', result)
        baseline, treatment = result['experiment']['arms']
        self.assertEqual(baseline['binding']['bindings']['pulse'], treatment['binding']['bindings']['pulse'])
        self.assertEqual(set(result['experiment']['context_bindings']), {'pulse', 'cluster'})

    def test_unverified_tag_as_only_semantic_match_rejected(self):
        data = compiler_fixture()
        role = data[0]['field_roles'][0]
        role['required_semantics'] = ['generic_only']
        data[1]['evidence_pack']['allowed_role_semantics'].append('generic_only')
        data[1]['field_rows'][0]['semantic_tags'].append('generic_only')
        self.renormalize(data)
        self.reject(data, 'missing_field_semantics')

    def test_required_tag_metadata_cannot_be_silently_filtered(self):
        data = compiler_fixture()
        data[0]['field_roles'][0]['required_metadata'].append('semantic_tags')
        data[1]['field_rows'][0]['semantic_tags'].append('generic_extra')
        self.renormalize(data)
        self.reject(data, 'missing_field_semantics')

    def test_field_lookup_must_not_silently_skip_missing_canonical_identity(self):
        from unittest.mock import patch
        from wqb.template_binding import bind_template
        def missing_identity(*args):
            """Input: real binder args. Output: binding with injected nonexistent identity."""
            result = bind_template(*args)
            result['bindings']['pulse']['field_id'] = 'invented_field'
            return result
        with patch('wqb.hypothesis_template_compiler.bind_template', side_effect=missing_identity):
            self.reject(compiler_fixture(), 'missing_field_semantics')

    def test_conflicting_duplicate_canonical_row_cannot_escape_audit(self):
        data = compiler_fixture()
        other = deepcopy(data[1]['field_rows'][0])
        other.update(field_description='unrelated', semantic_tags=[])
        data[1]['field_rows'].append(other)
        self.reject(data, 'ambiguous_field')

    def test_matching_optional_id_alias_is_safe_with_canonical_field_id(self):
        data = compiler_fixture()
        data[1]['field_rows'][0]['id'] = data[1]['field_rows'][0]['field_id']
        self.assertEqual(self.compile(data)['status'], 'compiled')

    def test_negative_level_relative_pair_orients_both_arms(self):
        data = self.relative_pair('group_demean')
        data[0]['prediction_direction'] = 'negative'
        self.renormalize(data)
        result = self.compile(data)
        self.assertEqual(result['status'], 'compiled', result)
        self.assertEqual([arm['binding']['bound_expression'] for arm in result['experiment']['arms']],
            ['-pulse_field', '-group_neutralize(pulse_field, cluster_field)'])

    def test_treatment_group_has_independent_source_in_union_and_draft(self):
        import json
        data = self.relative_pair('group_rank')
        resources = data[1]
        group = resources['field_rows'][1]
        original_path = group['source_paths'][0]
        facts = json.loads(resources['source_texts'][original_path])
        text = json.dumps(facts['fields'][1])
        path = 'raw/platform/fictional/group.json'
        row = dict(resources['source_index'][original_path], path=path,
                   content_hash=hashlib.sha256(text.encode()).hexdigest())
        for target in [resources, resources['evidence_pack']]:
            target['source_index'][path] = deepcopy(row)
            target['source_texts'][path] = text
        group['source_paths'] = [path]
        self.renormalize(data)
        result = self.compile(data)
        self.assertEqual(result['status'], 'compiled', result)
        group_receipt = result['experiment']['context_bindings']['cluster']
        self.assertEqual(group_receipt['source_paths'], [path])
        self.assertEqual({ref['source_path'] for ref in group_receipt['evidence_refs']}, {path})
        self.assertIn(path, result['drafts'][1]['source_paths'])
        self.assertNotIn(path, result['drafts'][0]['source_paths'])

    def test_evidence_settings_and_version_change_compilation_identity(self):
        from unittest.mock import patch
        data = compiler_fixture()
        first = self.compile(data)
        data[1]['settings']['decay'] = 9
        second = self.compile(data)
        self.assertNotEqual(first['compilation_digest'], second['compilation_digest'])
        self.assertNotEqual(first['drafts'][0]['template_id'], second['drafts'][0]['template_id'])
        with patch('wqb.hypothesis_design.COMPILER_VERSION', 'future-compiler'):
            self.renormalize(data)
            third = self.compile(data)
        self.assertNotEqual(second['compilation_digest'], third['compilation_digest'])

    def test_no_io_during_compilation(self):
        from unittest.mock import patch
        data = compiler_fixture()
        self.compile(data)  # Load modules before forbidding IO.
        with patch('builtins.open', side_effect=AssertionError('IO forbidden')):
            self.assertEqual(self.compile(data)['status'], 'compiled')

    def test_compiler_reuses_markdown_body_and_full_byte_hash_contract(self):
        data = compiler_fixture()
        old = data[0]['trigger_id']
        path = old.replace('.txt', '.md')
        pack = data[1]['evidence_pack']
        row = pack['source_index'].pop(old)
        row['path'] = path
        body = pack['source_texts'].pop(old) + '\n' + 'A sourced observation.\n' * 500
        row['content_hash'] = hashlib.sha256(body.encode()).hexdigest()
        header = '---\ncontent_hash: ' + row['content_hash'] + '\ncaptured_at: ' + row['captured_at'] + '\n---\n'
        text = (header + body).replace('\n', '\r\n')
        row['file_sha256'] = hashlib.sha256(text.encode()).hexdigest()
        pack['source_index'][path] = row
        pack['source_texts'][path] = text
        data[0]['trigger_id'] = path
        data[0]['evidence_refs'][0].update(source_path=path, sha256=row['content_hash'])
        data[1]['source_index'] = deepcopy(pack['source_index'])
        data[1]['source_texts'] = deepcopy(pack['source_texts'])
        self.renormalize(data)
        self.assertEqual(self.compile(data)['status'], 'compiled')
        data[1]['source_texts'][path] = text.replace('2026-10-14', '2026-10-13')
        self.reject(data, 'invalid_resources')

    def test_hash_valid_but_incompatible_operator_meaning_is_rejected(self):
        import json
        data = compiler_fixture('group_demean')
        resource = data[1]
        path = resource['field_rows'][0]['source_paths'][0]
        facts = json.loads(resource['source_texts'][path])
        facts['operators'][2]['definition']['description'] = 'Ranks x within each group.'
        text = json.dumps(facts)
        digest = hashlib.sha256(text.encode()).hexdigest()
        resource['operator_rows'][2]['definition']['description'] = 'Ranks x within each group.'
        for row in resource['operator_rows']:
            row['definition']['evidence_refs'][0]['sha256'] = digest
        for target in [resource, resource['evidence_pack']]:
            target['source_index'][path]['content_hash'] = digest
            target['source_texts'][path] = text
        self.renormalize(data)
        self.reject(data, 'missing_operator_definition')

    def test_ast_settings_collision_guard_rejects_whole_pair(self):
        from unittest.mock import patch
        from wqb.template_binding import bind_template
        def collision(*args):
            """Input: binder args tuple. Output: real binding with injected AST collision."""
            result = bind_template(*args)
            result['bound_expression'] = 'pulse_field'
            return result
        with patch('wqb.hypothesis_template_compiler.bind_template', side_effect=collision):
            self.reject(compiler_fixture(treatment=True), 'duplicate_template')

    def test_cross_scope_field_has_explicit_scope_rejection(self):
        data = compiler_fixture()
        data[1]['field_rows'][0]['region'] = 'OTHER'
        self.reject(data, 'incompatible_scope')

    def test_draft_evidence_includes_consumed_field_and_operator_sources(self):
        data = compiler_fixture('change')
        result = self.compile(data)
        refs = result['drafts'][0]['evidence_refs']
        self.assertEqual({r['source_path'] for r in refs}, set(data[1]['source_index']))
        self.assertIn('documented', {r['kind'] for r in refs})
        self.assertIn('hypothesis', {r['kind'] for r in refs})
        self.assertEqual(validate_semantic_record_for_test(result['drafts'][0], data[1]['source_index']), [])

    def test_changed_source_evidence_changes_compilation_and_template_ids(self):
        data = compiler_fixture()
        first = self.compile(data)
        path = data[0]['trigger_id']
        text = data[1]['source_texts'][path] + ' An additional sourced observation.'
        digest = hashlib.sha256(text.encode()).hexdigest()
        for target in [data[1], data[1]['evidence_pack']]:
            target['source_texts'][path] = text
            target['source_index'][path]['content_hash'] = digest
        data[0]['evidence_refs'][0]['sha256'] = digest
        self.renormalize(data)
        second = self.compile(data)
        self.assertEqual(second['status'], 'compiled', second)
        self.assertNotEqual(first['compilation_digest'], second['compilation_digest'])
        self.assertNotEqual(first['drafts'][0]['template_id'], second['drafts'][0]['template_id'])


def validate_semantic_record_for_test(record, index):
    """Input: draft/index dicts. Output: existing provenance validator issue list."""
    from wqb.semantic_contracts import validate_semantic_record
    return validate_semantic_record(record, index)


if __name__ == '__main__':
    unittest.main()
