"""Offline default Repair policy tests separating signals from GROUP context."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_compiled_repair_policy import fixture
from tests.test_hypothesis_design import compiler_fixture
from tests.test_repair_catalog_admission import persisted_fixture
from tests.test_repair_search import search_fixture
from wqb.cli import simulation_identity_hash
from wqb.hypothesis_design import compile_hypothesis_design, validate_hypothesis_design
from wqb.repair_rulebook import build_default_repair_policy, load_repair_rulebook
from wqb.repair_search import (compile_repair_search_policy, _validate_v2_sources,
    _materialize_parent, prepare_search, prepare_persisted_search, verify_persisted_search)
from wqb.semantic_contracts import SemanticPolicy
from wqb.template_binding import bind_template


def context_fixture(signal_type='MATRIX'):
    """Input: signal type str. Output: in-memory resource dict with independent raw signal/context sources."""
    _, resources, scope = compiler_fixture('group_rank')
    stamp = datetime.now(timezone.utc).isoformat()
    scope['as_of'] = stamp
    resources.update(resource_contract_version=2, resource_admission_policy='knowledge_catalog_v1',
                     source_index={}, source_texts={}, operator_rows=[])
    resources['evidence_pack'] = dict(scope=scope, resource_admission_policy='knowledge_catalog_v1')
    resources['field_rows'][0]['field_type'] = signal_type
    for row in resources['field_rows']:
        path = 'raw/platform/data_fields/' + row['field_id'] + '.jsonl'
        row.update(coverage=.8, source_updated_at=stamp[:10], source_quality='platform_raw_capture',
                   coverage_status='measured_raw', source_paths=[path])
        field = dict(id=row['field_id'], type=row['field_type'], coverage=row['coverage'])
        text = json.dumps(dict(scope=scope, field=field, data_set=dict(id=row['dataset_id']),
                               captured_at=stamp))
        resources['source_texts'][path] = text
        resources['source_index'][path] = dict(path=path, content_hash=hashlib.sha256(text.encode()).hexdigest(),
            captured_at=stamp, source_type='platform_data_field_capture', source_family='raw/platform/data_fields')
    return resources


def relative_parent_fixture(signal_type, comparison):
    """Input: signal type/comparison strs. Output: resources, measured parent, actual Relative compiler result dicts."""
    design, original, _ = compiler_fixture(comparison)
    resources = context_fixture(signal_type)
    pack = deepcopy(original['evidence_pack'])
    pack.update(resources['evidence_pack'], resource_contract_version=2, source_index=resources['source_index'],
                source_texts=resources['source_texts'])
    resources['evidence_pack'] = pack
    operators = deepcopy(original['operator_rows'])
    for row in operators:
        row['definition'].pop('evidence_refs')
    design.pop('design_id')
    if signal_type == 'VECTOR':
        design['design_version'] = 3
        next(role for role in design['field_roles'] if role['name'] == 'pulse')['field_type'] = 'VECTOR'
        design['feature_plan']['input']['reduction'] = dict(operator='vec_avg', parameters={})
        design['experiment_plan']['baseline'] = deepcopy(design['feature_plan'])
        operators.append(dict(operator='vec_avg', definition=dict(description='Taking mean of the vector field x',
            input_types=['VECTOR'], output_type='MATRIX', parameters=[dict(name='x', type='VECTOR', required=True)])))
    path = 'raw/platform/learn/relative.json'
    text = json.dumps(operators)
    digest = hashlib.sha256(text.encode()).hexdigest()
    stamp = pack['scope']['as_of']
    resources['source_texts'][path] = text
    resources['source_index'][path] = dict(path=path, content_hash=digest, captured_at=stamp,
        source_type='platform_learn_material', source_family='raw/platform/learn')
    for row in operators:
        row['definition']['evidence_refs'] = [dict(source_path=path, sha256=digest, capture_date=stamp[:10],
                                                   kind='documented', experiment_refs=[])]
    resources['operator_rows'] = operators
    path = resources['field_rows'][0]['source_paths'][0]
    design.update(trigger_id=path, evidence_refs=[dict(source_path=path,
        sha256=resources['source_index'][path]['content_hash'], capture_date=stamp[:10],
        kind='hypothesis', experiment_refs=[])])
    design = validate_hypothesis_design(dict(summary='A fictional Relative proposal.', designs=[design]),
                                        pack, SemanticPolicy())['designs'][0]
    compiled = compile_hypothesis_design(design, resources, pack['scope'])
    if compiled['status'] != 'compiled':
        raise AssertionError(compiled)
    arm = compiled['experiment']['arms'][0]
    parent, _ = search_fixture()
    parent.update(expression=arm['binding']['bound_expression'], settings=arm['settings'],
                  status='CHECKED', pending=[], failed=['HIGH_TURNOVER'], hard_pass=False)
    parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
    return resources, parent, compiled


def multiple_reduction_parent_fixture():
    """Input: none. Output: sourced resources/parent/compiler dicts with two reducers of one VECTOR field."""
    from tests.test_hypothesis_conditions import condition_fixture
    resources, parent, _ = relative_parent_fixture('VECTOR', 'group_rank')
    design, conditional, _ = condition_fixture()
    design['design_version'] = 3
    for role in design['field_roles']:
        role['field_type'] = 'VECTOR'
        role['required_semantics'] = ['fictional_pulse']
    design['feature_plan']['input']['reduction'] = dict(operator='vec_avg', parameters={})
    design['experiment_plan']['baseline'] = deepcopy(design['feature_plan'])
    feature = design['experiment_plan']['treatments'][0]['feature']
    feature['input']['reduction'] = dict(operator='vec_avg', parameters={})
    feature['condition_role']['reduction'] = dict(operator='vec_count', parameters={})
    resources['field_rows'] = resources['field_rows'][:1]
    resources['evidence_pack']['allowed_operator_intents'] = conditional['evidence_pack']['allowed_operator_intents']
    resources['operator_rows'].extend(row for row in conditional['operator_rows']
        if row['operator'] not in {item['operator'] for item in resources['operator_rows']})
    resources['operator_rows'].append(dict(operator='vec_count', definition=dict(
        description='Number of elements in vector field x', input_types=['VECTOR'], output_type='MATRIX',
        parameters=[dict(name='x', type='VECTOR', required=True)])))
    path = 'raw/platform/learn/multiple_reductions.json'
    operators = deepcopy(resources['operator_rows'])
    for row in operators:
        row['definition'].pop('evidence_refs', None)
    text = json.dumps(operators)
    stamp = resources['evidence_pack']['scope']['as_of']
    digest = hashlib.sha256(text.encode()).hexdigest()
    resources['source_texts'][path] = text
    resources['source_index'][path] = dict(path=path, content_hash=digest, captured_at=stamp,
        source_type='platform_learn_material', source_family='raw/platform/learn')
    for row in resources['operator_rows']:
        row['definition']['evidence_refs'] = [dict(source_path=path, sha256=digest,
            capture_date=stamp[:10], kind='documented', experiment_refs=[])]
    source = resources['field_rows'][0]['source_paths'][0]
    design.update(trigger_id=source, evidence_refs=[dict(source_path=source,
        sha256=resources['source_index'][source]['content_hash'], capture_date=stamp[:10],
        kind='hypothesis', experiment_refs=[])])
    normalized = validate_hypothesis_design(dict(summary='A fictional conditional VECTOR proposal.', designs=[design]),
        resources['evidence_pack'], SemanticPolicy())['designs'][0]
    compiled = compile_hypothesis_design(normalized, resources, resources['evidence_pack']['scope'])
    if compiled['status'] != 'compiled':
        raise AssertionError(compiled)
    arm = compiled['experiment']['arms'][1]
    parent.update(expression=arm['binding']['bound_expression'], settings=arm['settings'])
    parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
    return resources, parent, compiled


class RepairContextFieldsTests(unittest.TestCase):
    def test_same_vector_field_reductions_preserve_setting_variants_and_recovery(self):
        """Input: actual avg/count conditional parent. Output: exact AST/provenance and recoverable setting-only variants."""
        resources, parent, compiled = multiple_reduction_parent_fixture()
        expression = 'if_else(greater(vec_count(pulse_field), 0.5), vec_avg(pulse_field), 0)'
        self.assertEqual(parent['expression'], expression)
        policy = build_default_repair_policy(resources)
        before = deepcopy((resources, parent, policy))
        bound = _materialize_parent(policy, parent)
        self.assertEqual(bound['rules'], policy['rules'])
        frozen = bound['resources']
        self.assertEqual(len(frozen['field_rows']), 1)
        self.assertEqual({slot['reduction']['operator'] for slot in frozen['template']['input_slots']},
                         {'vec_avg', 'vec_count'})
        rebound = bind_template(frozen['template'], frozen['field_rows'], frozen['operator_rows'],
            frozen['scope'], resource_contract_version=2, evidence_context=frozen['evidence_context'])
        self.assertEqual(rebound['bound_expression'], expression)
        self.assertEqual(rebound['operator_provenance'],
                         compiled['experiment']['arms'][1]['binding']['operator_provenance'])
        for failure, edit in [('HIGH_TURNOVER', 'decay'), ('CONCENTRATED_WEIGHT', 'truncation')]:
            with self.subTest(edit=edit):
                parent['failed'] = [failure]
                result = prepare_search(Path('unused'), parent, [], 8, policy)
                self.assertEqual(result['status'], 'validated', result)
                self.assertTrue(result['variants'], result)
                for variant in result['variants']:
                    self.assertEqual(variant['expression'], expression)
                    self.assertEqual(variant['parent_expression_hash'], parent['expression_hash'])
                    self.assertEqual({key for key in parent['settings']
                        if variant['settings'][key] != parent['settings'][key]}, {edit})
                with tempfile.TemporaryDirectory() as directory:
                    run = Path(directory)
                    context = persisted_fixture(run, resources, policy)
                    with patch('wqb.hypothesis_selection.validate_operational_resource_context', return_value=context):
                        receipt = prepare_persisted_search(run, parent, [], 1)
                        self.assertEqual(receipt['variants'], result['variants'][:1])
                        self.assertEqual(verify_persisted_search(run, receipt), receipt)
                        self.assertEqual(prepare_persisted_search(run, parent, [], 1), receipt)
        parent['failed'] = before[1]['failed']
        self.assertEqual((resources, parent, policy), before)

    def test_multiple_reductions_keep_repeated_occurrences_and_source_checks(self):
        """Input: repeated avg/count AST and invalid variants. Output: unchanged binding or explicit source/type rejection."""
        resources, parent, _ = multiple_reduction_parent_fixture()
        policy = build_default_repair_policy(resources)
        parent['expression'] = ('if_else(greater(vec_count(pulse_field), 0.5), '
                                'vec_avg(pulse_field) + vec_avg(pulse_field), 0)')
        parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
        bound = _materialize_parent(policy, parent)['resources']
        rebound = bind_template(bound['template'], bound['field_rows'], bound['operator_rows'], bound['scope'],
            resource_contract_version=2, evidence_context=bound['evidence_context'])
        self.assertEqual(rebound['bound_expression'], parent['expression'])
        self.assertEqual([row['operator'] for row in rebound['operator_provenance']],
                         ['if_else', 'greater', 'vec_count', 'vec_avg', 'vec_avg'])
        for expression in ('if_else(greater(vec_count(pulse_field), 0.5), pulse_field, 0)',
                           'vec_avg(pulse_field, 2) + vec_count(pulse_field)'):
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError, 'explicit unary'):
                _materialize_parent(policy, dict(parent, expression=expression))
        invalid = deepcopy(policy)
        count = next(row for row in invalid['resources']['operator_rows'] if row['operator'] == 'vec_count')
        count['definition']['output_type'] = 'VECTOR'
        with self.assertRaisesRegex(ValueError, 'VECTOR to MATRIX signature'):
            _materialize_parent(invalid, parent)
        invalid = deepcopy(policy)
        path = resources['field_rows'][0]['source_paths'][0]
        invalid['resources']['evidence_context']['source_texts'][path] += '\nchanged'
        with self.assertRaises(ValueError):
            _materialize_parent(invalid, parent)

    def test_multiple_reductions_do_not_expand_legacy_or_transform_repair(self):
        """Input: multiple reducers under legacy/transform policies. Output: rejection, not new transform authority."""
        from wqb.repair_search import _policy
        resources, parent, _ = multiple_reduction_parent_fixture()
        legacy = compile_repair_search_policy(resources, dict(compile_version=1, rules=[], traits={}))
        with self.assertRaisesRegex(ValueError, 'setting-only metric-directed Repair'):
            _materialize_parent(legacy, parent)
        policy = build_default_repair_policy(resources)
        policy['rules'][0].update(edit='transform', effect='smoothing', parameter_direction='any', grid=[2],
            transform=dict(operator='ts_mean', parameter='d', parameter_kind='window', bounds=[1, 8],
                frequency_trait='sampling_frequency_sessions', preserves_direction=True))
        policy = _policy(policy)
        with self.assertRaisesRegex(ValueError, 'setting-only metric-directed Repair'):
            _materialize_parent(policy, parent)

    def test_compiled_relative_parents_persist_and_recover_setting_only_search(self):
        """Input: four actual mixed Relative compilations. Output: setting variants and exact frozen/replay identity."""
        for signal_type in ('MATRIX', 'VECTOR'):
            for comparison in ('group_rank', 'group_demean'):
                resources, parent, compiled = relative_parent_fixture(signal_type, comparison)
                policy = build_default_repair_policy(resources)
                before = deepcopy((resources, policy, compiled))
                for failure, edit in [('HIGH_TURNOVER', 'decay'), ('CONCENTRATED_WEIGHT', 'truncation')]:
                    with self.subTest(signal_type=signal_type, comparison=comparison, failure=failure):
                        parent['failed'] = [failure]
                        bound = _materialize_parent(policy, parent)
                        self.assertEqual(bound['rules'], policy['rules'])
                        self.assertEqual(bound['traits'], policy['traits'])
                        frozen = bound['resources']
                        self.assertEqual(sorted(frozen['field_rows'], key=lambda row: row['field_id']),
                                         sorted(resources['field_rows'], key=lambda row: row['field_id']))
                        group_slot = next(slot for slot in frozen['template']['input_slots']
                                          if slot['field_type'] == 'GROUP')
                        self.assertEqual(group_slot['role'], 'context')
                        self.assertIsNone(group_slot['reduction'])
                        self.assertEqual(frozen['evidence_context'], policy['resources']['evidence_context'])
                        rebound = bind_template(frozen['template'], frozen['field_rows'], frozen['operator_rows'],
                            frozen['scope'], resource_contract_version=2, evidence_context=frozen['evidence_context'])
                        original_binding = compiled['experiment']['arms'][0]['binding']
                        self.assertEqual(rebound['bound_expression'], original_binding['bound_expression'])
                        self.assertEqual(rebound['operator_provenance'], original_binding['operator_provenance'])
                        for key in ('field_id', 'dataset_id', 'field_type'):
                            self.assertEqual(rebound['bindings'][group_slot['name']][key],
                                             original_binding['bindings']['cluster'][key])
                        expected = prepare_search(Path('unused'), parent, [], 8, policy)
                        self.assertEqual(expected['status'], 'validated', expected)
                        self.assertTrue(expected['variants'], expected)
                        grid = load_repair_rulebook()[edit + '_grid']
                        values = [value for value in grid if (value > parent['settings'][edit]
                                  if edit == 'decay' else value < parent['settings'][edit])]
                        self.assertEqual([variant['decision']['value'] for variant in expected['variants']], values)
                        for variant in expected['variants']:
                            self.assertEqual(variant['decision']['edit'], edit)
                            self.assertEqual(variant['expression'], parent['expression'])
                            self.assertIn('cluster_field', variant['expression'])
                            self.assertEqual(variant['parent_expression_hash'], parent['expression_hash'])
                            self.assertEqual(variant['expression_hash'], simulation_identity_hash(
                                variant['expression'], variant['settings']))
                            self.assertEqual({key for key in parent['settings']
                                              if variant['settings'][key] != parent['settings'][key]}, {edit})
                        with tempfile.TemporaryDirectory() as directory:
                            run = Path(directory)
                            context = persisted_fixture(run, resources, policy)
                            # Only the owning snapshot envelope is isolated; source/type/compiler/search checks are real.
                            with patch('wqb.hypothesis_selection.validate_operational_resource_context', return_value=context):
                                receipt = prepare_persisted_search(run, parent, [], 1)
                                self.assertEqual(receipt['variants'], expected['variants'][:1])
                                evidence = json.loads(Path(receipt['receipt_path']).with_suffix('.input.json').read_text())
                                self.assertEqual(evidence['parent'], parent)
                                self.assertEqual(evidence['policy'], bound)
                                self.assertEqual(verify_persisted_search(run, receipt), receipt)
                                self.assertEqual(prepare_persisted_search(run, parent, [], 1), receipt)
                                manifest = json.loads((run / 'run_manifest.json').read_text())
                                manifest['start_snapshot']['data_ledger_rows'][1]['field_id'] = 'other_group'
                                (run / 'run_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
                                with self.assertRaisesRegex(ValueError, 'owning frozen snapshot'):
                                    verify_persisted_search(run, receipt)
                self.assertEqual((resources, policy, compiled), before)

    def test_group_context_cannot_be_used_as_numeric_or_lose_source_integrity(self):
        """Input: swapped numeric/GROUP arguments or changed GROUP bytes. Output: fail-closed parent materialization."""
        resources, parent, _ = relative_parent_fixture('MATRIX', 'group_rank')
        policy = build_default_repair_policy(resources)
        invalid = deepcopy(parent)
        invalid['expression'] = 'group_rank(cluster_field, pulse_field)'
        invalid['expression_hash'] = simulation_identity_hash(invalid['expression'], invalid['settings'])
        with self.assertRaisesRegex(ValueError, 'type GROUP does not match MATRIX'):
            _materialize_parent(policy, invalid)
        path = resources['field_rows'][1]['source_paths'][0]
        policy['resources']['evidence_context']['source_texts'][path] += '\nchanged group source'
        with self.assertRaises(ValueError):
            _materialize_parent(policy, parent)

    def test_parent_requires_real_numeric_signal_and_rejects_unknown_types(self):
        """Input: GROUP-only selected leaves or unknown types. Output: rejection despite unused numeric pack fields."""
        resources, parent, _ = relative_parent_fixture('MATRIX', 'group_rank')
        policy = build_default_repair_policy(resources)
        parent['expression'] = 'cluster_field'
        parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
        with self.assertRaisesRegex(ValueError, 'numeric signal'):
            _materialize_parent(policy, parent)
        parent['expression'] = 'group_rank(pulse_field, cluster_field)'
        parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
        policy['resources']['field_rows'][1]['field_type'] = 'UNKNOWN'
        with self.assertRaisesRegex(ValueError, 'unsupported type'):
            _materialize_parent(policy, parent)

    def test_group_evidence_cannot_substitute_for_numeric_trait_proof(self):
        """Input: real mixed parent with numeric trait relabeled to GROUP source. Output: missing numeric prerequisite."""
        resources, parent, _ = relative_parent_fixture('MATRIX', 'group_rank')
        policy = build_default_repair_policy(resources)
        path = resources['field_rows'][1]['source_paths'][0]
        source = resources['source_index'][path]
        policy['traits']['numeric_observation']['evidence_refs'] = [dict(source_path=path,
            sha256=source['content_hash'], capture_date=source['captured_at'][:10],
            kind='documented', experiment_refs=[])]
        bound = _materialize_parent(policy, parent)
        self.assertNotIn('numeric_observation', bound['traits'])
        result = prepare_search(Path('unused'), parent, [], 8, policy)
        self.assertFalse(result['variants'], result)
        self.assertEqual(result['stop_reason'], 'missing_prerequisites')

    def test_mixed_numeric_and_group_preserve_rules_and_frozen_identity(self):
        """Input: MATRIX/GROUP or VECTOR/GROUP resources. Output: unchanged finite rules and complete frozen context."""
        for signal_type in ('MATRIX', 'VECTOR'):
            with self.subTest(signal_type=signal_type):
                resources = context_fixture(signal_type)
                before = deepcopy(resources)
                numeric_only = deepcopy(resources)
                numeric_only['field_rows'] = numeric_only['field_rows'][:1]
                expected = build_default_repair_policy(numeric_only)
                policy = build_default_repair_policy(resources)
                certified = compile_repair_search_policy(resources, dict(compile_version=1, rules=[], traits={}))
                self.assertEqual(policy['rules'], expected['rules'])
                self.assertEqual(policy['traits']['numeric_observation'], expected['traits']['numeric_observation'])
                self.assertEqual(policy['resources'], {key: value for key, value in certified['resources'].items()
                                                      if key != 'producer'})
                self.assertEqual(policy['resources']['field_rows'][1]['field_type'], 'GROUP')
                self.assertEqual(set(policy['traits']), {'numeric_observation'})
                self.assertEqual({ref['source_path'] for ref in policy['traits']['numeric_observation']['evidence_refs']},
                                 set(resources['field_rows'][0]['source_paths']))
                self.assertEqual({rule['edit'] for rule in policy['rules']}, {'decay', 'truncation'})
                _validate_v2_sources(policy['resources'])
                self.assertEqual(resources, before)

    def test_group_only_still_rejects_numeric_policy(self):
        """Input: certified GROUP-only resources. Output: ValueError rather than fabricated numeric facts."""
        resources = context_fixture()
        resources['field_rows'] = resources['field_rows'][1:]
        compile_repair_search_policy(resources, dict(compile_version=1, rules=[], traits={}))
        with self.assertRaisesRegex(ValueError, 'requires sourced numeric fields'):
            build_default_repair_policy(resources)

    def test_group_context_still_requires_exact_source_type(self):
        """Input: GROUP row disagreeing with raw type. Output: rejection before default rules are built."""
        resources = context_fixture()
        resources['field_rows'][1]['field_type'] = 'MATRIX'
        with self.assertRaisesRegex(ValueError, 'sourced identity/scope/type/coverage/date'):
            build_default_repair_policy(resources)

    def test_legacy_numeric_policy_keeps_original_traits_resources_and_grids(self):
        """Input: unchanged legacy MATRIX fixture. Output: original source traits, identity and catalog rule space."""
        resources, _ = fixture()
        before = deepcopy(resources)
        certified = compile_repair_search_policy(resources, dict(compile_version=1, rules=[], traits={}))
        catalog = load_repair_rulebook()
        policy = build_default_repair_policy(resources)
        self.assertEqual(policy['resources'], {key: value for key, value in certified['resources'].items()
                                              if key != 'producer'})
        self.assertEqual(policy['traits']['matrix_observation'], certified['traits']['matrix_observation'])
        self.assertEqual(policy['traits']['numeric_observation'], certified['traits']['matrix_observation'])
        self.assertEqual(len(policy['rules']), len(catalog['rules']))
        for rule, original in zip(policy['rules'], catalog['rules']):
            original = deepcopy(original)
            original['trigger']['checks'].sort()
            self.assertEqual({key: rule[key] for key in original}, original)
            self.assertEqual(rule['grid'], catalog[rule['edit'] + '_grid'])
            self.assertEqual(rule['requires'], {'numeric_observation': True})
        self.assertEqual(resources, before)
