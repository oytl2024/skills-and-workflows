"""Offline Repair admission regressions; catalog visibility is not semantic proof."""

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_compiled_repair_policy import fixture
from tests.test_repair_search import search_fixture
from wqb.cli import simulation_identity_hash
from wqb.repair_rulebook import build_default_repair_policy
from wqb.repair_search import _materialize_parent, compile_repair_search_policy, prepare_search


POLICY = 'knowledge_catalog_v1'


def catalog_fixture(*, cadence=None, vector=False, complete=False):
    """Input: optional cadence int and vector/complete bools. Output: sourced resources/project/parent dicts."""
    resources, project = fixture()
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    row = resources['field_rows'][0]
    path = row['source_paths'][0]
    field = dict(id='cash', type='VECTOR' if vector else 'MATRIX', description='Cash balance', coverage=.8)
    if cadence is not None:
        field['sampling_frequency_sessions'] = cadence
    if complete:
        field['available_at'] = '2026-10-14T00:00:00Z'
    text = json.dumps(dict(scope={k: row[k] for k in ('instrument_type', 'region', 'delay', 'universe')},
                           field=field, data_set=dict(id='d')))
    resources['source_texts'][path] = text
    resources['source_index'][path].update(content_hash=hashlib.sha256(text.encode()).hexdigest(), captured_at=stamp)
    row.update(field_type=field['type'], coverage=.8, source_updated_at=now.date().isoformat(),
               source_quality='platform_raw_capture', coverage_status='measured_raw')
    if not complete:
        row.pop('available_at')
        row.pop('field_description')
    resources['evidence_pack'].update(scope=dict(resources['evidence_pack']['scope'], as_of=stamp),
                                      resource_admission_policy=POLICY)
    resources['resource_admission_policy'] = POLICY
    operator_path = 'raw/platform/learn/catalog.json'
    definitions = [dict(operator='signed_power', definition=dict(
        description='Technical catalog entry', input_types=['MATRIX'], output_type='MATRIX', parameters=[
            dict(name='x', type='MATRIX', required=True), dict(name='y', type='FLOAT', required=True)]))]
    if cadence is not None:
        definitions.append(dict(operator='ts_mean', definition=dict(
            description='Technical catalog entry', input_types=['MATRIX'], output_type='MATRIX', parameters=[
                dict(name='x', type='MATRIX', required=True), dict(name='d', type='INTEGER', required=True)])))
    if vector:
        definitions.append(dict(operator='vec_avg', definition=dict(
            description='Technical catalog entry', input_types=['VECTOR'], output_type='MATRIX',
            parameters=[dict(name='x', type='VECTOR', required=True)])))
    text = json.dumps(definitions)
    digest = hashlib.sha256(text.encode()).hexdigest()
    ref = dict(source_path=operator_path, sha256=digest, capture_date=now.date().isoformat(),
               kind='documented', experiment_refs=[])
    resources['source_texts'][operator_path] = text
    resources['source_index'][operator_path] = dict(path=operator_path, content_hash=digest,
        captured_at=stamp, source_type='platform_learn_material', source_family='raw/platform/learn')
    resources['operator_rows'] = deepcopy(definitions)
    for operator in resources['operator_rows']:
        operator['definition']['evidence_refs'] = [deepcopy(ref)]
    project['rules'][0].update(edit='transform', effect='bounded_weights', invariant='positive_signed_power',
        grid=[.5, 2.], requires=dict(matrix_observation=True) if not vector else dict(numeric_observation=True),
        transform=dict(operator='signed_power', parameter='y', parameter_kind='scalar', bounds=[.1, 3.],
                       frequency_trait=None, preserves_direction=True))
    parent, _ = search_fixture()
    parent.update(expression='vec_avg(cash)' if vector else 'cash', status='CHECKED',
                  failed=['LOW_FITNESS'], pending=[], hard_pass=False)
    parent['settings']['instrumentType'] = 'EQUITY'
    parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
    return resources, project, parent


def metric_transform(resources, project):
    """Input: source/project dicts. Output: V2 policy with the existing finite transform, not a new mapping."""
    policy = build_default_repair_policy(resources)
    rule = deepcopy(project['rules'][0])
    rule.pop('invariant')
    rule.update(trigger=dict(checks=['LOW_FITNESS'], metric=None, operator=None, threshold=None),
                basis='project_hypothesis', rationale='Bounded existing mathematical invariant.', parameter_direction='any')
    rule['evidence_refs'] = deepcopy(resources['operator_rows'][0]['definition']['evidence_refs'])
    policy['rules'] = [rule]
    return policy


def replace_operator_raw(resources, payload):
    """Input: resource dict/JSON raw payload. Output: None; rehash real changed raw without altering snapshot technical claims."""
    path = resources['operator_rows'][0]['definition']['evidence_refs'][0]['source_path']
    text = json.dumps(payload)
    digest = hashlib.sha256(text.encode()).hexdigest()
    resources['source_texts'][path] = text
    resources['source_index'][path]['content_hash'] = digest
    for row in resources['operator_rows']:
        for ref in row['definition']['evidence_refs']:
            if ref['source_path'] == path:
                ref['sha256'] = digest


def persisted_fixture(run, resources, policy):
    """Input: temporary run Path/resources/policy dicts. Output: owning source context dict for offline receipt tests."""
    snapshot = dict(research_policy=dict(deterministic_repair=True), repair_search_policy=policy,
                    data_ledger_rows=resources['field_rows'], operator_rows=resources['operator_rows'])
    (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)), encoding='utf-8')
    return dict(resource_contract_version=2, resource_admission_policy=POLICY,
                source_index=resources['source_index'], source_texts=resources['source_texts'])


def replace_field_raw(resources, payload, container):
    """Input: resources/payload dicts and container str. Output: None; replace fixture raw and its actual hash."""
    path = resources['field_rows'][0]['source_paths'][0]
    text = json.dumps(payload, indent=2 if container == 'json' else None)
    if container == 'markdown':
        text = '# Field capture\n\n```json\n' + text + '\n```\n'
    resources['source_texts'][path] = text + '\n'
    resources['source_index'][path]['content_hash'] = hashlib.sha256((text + '\n').encode()).hexdigest()


class MeasuredExtractRepairAdmissionTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: temporary authentic measured extract and unchanged canonical resource dict."""
        from tests.test_research_resource_catalog import ResearchResourceCatalogTests
        from wqb.research_resource_catalog import read_catalog_resources

        self.catalog = ResearchResourceCatalogTests()
        self.addCleanup(self.catalog.doCleanups)
        self.catalog.setUp()
        self.extract, settings = self.catalog.prepare_measured_extract()
        resources, diagnostics = read_catalog_resources(
            self.catalog.root, self.catalog.scope, 1, settings=settings)
        self.assertEqual(len(resources), 1, diagnostics)
        self.resources = self.catalog.validate_against_canonical(resources[0])
        self.assertEqual(self.resources['field_rows'], self.catalog.fields)
        self.assertEqual(self.resources['field_rows'][0]['source_paths'], [self.extract['source_path']])
        self.assertNotIn(self.extract['source_path'], self.resources['source_texts'])
        self.assertIn(self.extract['excerpt_path'], self.resources['source_texts'])
        _, self.project = fixture()
        self.project['rules'][0].update(edit='decay', grid=[2, 4, 8],
                                       requires=dict(matrix_observation=True))
        self.parent, _ = search_fixture()
        self.parent.update(expression='pulse', status='CHECKED', failed=['HIGH_TURNOVER'],
                           pending=[], hard_pass=False)
        self.parent['settings'] = dict(settings, decay=2)
        self.parent['metrics']['turnover'] = .7
        self.parent['expression_hash'] = simulation_identity_hash('pulse', self.parent['settings'])

    def assert_extract_policy(self, policy):
        """Input: compiled policy dict. Output: plan dict; assert actual evidence and finite accepted-parent decay cells."""
        self.assertEqual(policy['resources']['field_rows'], self.catalog.fields)
        refs = policy['traits']['matrix_observation']['evidence_refs']
        self.assertEqual({ref['source_path'] for ref in refs}, {self.extract['excerpt_path']})
        source = self.resources['source_index'][self.extract['excerpt_path']]
        for ref in refs:
            self.assertEqual(ref['sha256'], source['content_hash'])
            self.assertEqual(ref['capture_date'], self.catalog.stamp[:10])
        bound = _materialize_parent(policy, self.parent)
        self.assertEqual(bound['resources']['field_rows'], self.catalog.fields)
        result = prepare_search(self.catalog.root / 'unused-run', self.parent, [], 8, bound)
        self.assertEqual(result['status'], 'validated', result)
        self.assertTrue(result['variants'], result)
        for variant in result['variants']:
            self.assertEqual(variant['expression'], 'pulse')
            self.assertEqual(variant['decision']['edit'], 'decay')
            self.assertEqual({key for key in self.parent['settings']
                              if variant['settings'][key] != self.parent['settings'][key]}, {'decay'})
        return result

    def test_compile_repair_policy_uses_verified_extract_without_rewriting_canonical_row(self):
        """Input: real extracted catalog resources. Output: bounded V1 decay plan with original canonical identity."""
        before = deepcopy(self.resources)
        policy = compile_repair_search_policy(self.resources, self.project)
        result = self.assert_extract_policy(policy)
        self.assertEqual([v['decision']['value'] for v in result['variants']], [4, 8])
        self.assertEqual(self.resources, before)

    def test_compile_metric_repair_policy_uses_verified_extract_for_parent_traits(self):
        """Input: real extracted catalog resources. Output: applicable V2 decay rule, verified evidence, unchanged field row."""
        before = deepcopy(self.resources)
        policy = build_default_repair_policy(self.resources)
        refs = policy['traits']['numeric_observation']['evidence_refs']
        self.assertEqual({ref['source_path'] for ref in refs}, {self.extract['excerpt_path']})
        result = self.assert_extract_policy(policy)
        self.assertEqual({v['decision']['rule_id'] for v in result['variants']}, {'high-turnover-smoothing'})
        self.assertEqual([v['decision']['value'] for v in result['variants']], [4, 5, 8, 10, 16, 22, 32])
        self.assertEqual(self.resources, before)

    def test_verified_extract_does_not_bypass_identity_coverage_or_capture_date(self):
        """Input: authentic extract with contradictory canonical facts. Output: both Repair compilers reject without mutation."""
        for key, value in (('field_id', 'other'), ('dataset_id', 'other'), ('field_type', 'VECTOR'),
                           ('available_scopes', [dict(self.catalog.fields[0]['available_scopes'][0], region='CHN')]),
                           ('coverage', .9),
                           ('coverage', 0), ('coverage_status', 'schema_seeded'),
                           ('source_updated_at', '2020-01-01'), ('source_updated_at', '2099-01-01')):
            for metric in (False, True):
                with self.subTest(key=key, value=value, metric=metric):
                    resources = deepcopy(self.resources)
                    resources['field_rows'][0][key] = value
                    before = deepcopy(resources)
                    with self.assertRaises(ValueError):
                        if metric:
                            build_default_repair_policy(resources)
                        else:
                            compile_repair_search_policy(resources, self.project)
                    self.assertEqual(resources, before)

    def test_verified_extract_keeps_source_provenance_and_date_checks(self):
        """Input: real extract with invalid frozen registration. Output: both compilers reject untrusted or stale capture."""
        for key, value in (('source_type', 'user_note'), ('source_family', 'raw/user'),
                           ('captured_at', '2020-01-01T00:00:00Z'),
                           ('captured_at', '2099-01-01T00:00:00Z')):
            for metric in (False, True):
                with self.subTest(key=key, value=value, metric=metric):
                    resources = deepcopy(self.resources)
                    resources['source_index'][self.extract['excerpt_path']][key] = value
                    before = deepcopy(resources)
                    with self.assertRaises(ValueError):
                        if metric:
                            build_default_repair_policy(resources)
                        else:
                            compile_repair_search_policy(resources, self.project)
                    self.assertEqual(resources, before)

    def test_verified_extract_changed_bytes_are_rejected_by_both_compilers(self):
        """Input: changed frozen excerpt text with original hash. Output: fail-closed compilation, no canonical edits."""
        resources = deepcopy(self.resources)
        resources['source_texts'][self.extract['excerpt_path']] += '\ncorrupted\n'
        before = deepcopy(resources)
        for metric in (False, True):
            with self.subTest(metric=metric), self.assertRaises(ValueError):
                if metric:
                    build_default_repair_policy(resources)
                else:
                    compile_repair_search_policy(resources, self.project)
        self.assertEqual(resources, before)


class RepairCatalogAdmissionTests(unittest.TestCase):
    def test_compiled_transform_accepts_incomplete_semantics_and_preserves_marker(self):
        resources, project, parent = catalog_fixture()
        before = deepcopy(resources)
        policy = compile_repair_search_policy(resources, project)
        self.assertEqual(policy['resources'].get('resource_admission_policy'), POLICY)
        self.assertEqual(policy['resources']['evidence_context'].get('resource_admission_policy'), POLICY)
        bound = _materialize_parent(policy, parent)
        self.assertEqual(bound['resources'].get('resource_admission_policy'), POLICY)
        self.assertEqual(bound['resources']['evidence_context'].get('resource_admission_policy'), POLICY)
        result = prepare_search(Path('unused'), parent, [], 8, bound)
        self.assertEqual(result['status'], 'validated', result)
        self.assertEqual([v['decision']['value'] for v in result['variants']], [.5, 2.])
        for variant in result['variants']:
            self.assertEqual(variant['settings'], parent['settings'])
            node = ast.parse(variant['expression'], mode='eval').body
            self.assertEqual(node.func.id, 'signed_power')
            self.assertEqual(ast.dump(node.args[0]), ast.dump(ast.parse(parent['expression'], mode='eval').body))
        self.assertEqual(resources, before)

    def test_catalog_window_transform_uses_only_actual_cadence(self):
        resources, project, parent = catalog_fixture(cadence=1)
        project['rules'][0].update(effect='smoothing', invariant='positive_averaging', grid=[2, 4],
            transform=dict(operator='ts_mean', parameter='d', parameter_kind='window', bounds=[1, 10],
                           frequency_trait='sampling_frequency_sessions', preserves_direction=True))
        policy = compile_repair_search_policy(resources, project)
        result = prepare_search(Path('unused'), parent, [], 8, _materialize_parent(policy, parent))
        self.assertEqual(result['status'], 'validated', result)
        self.assertEqual([v['decision']['value'] for v in result['variants']], [2, 4])
        self.assertEqual(policy['traits']['sampling_frequency_sessions']['value'], 1)

    def test_catalog_parent_binds_multiple_fields_by_identity_not_description(self):
        resources, project, parent = catalog_fixture()
        path = resources['field_rows'][0]['source_paths'][0]
        payload = json.loads(resources['source_texts'][path])
        other = deepcopy(payload)
        other['field']['id'] = 'debt'
        text = json.dumps(payload) + '\n' + json.dumps(other)
        resources['source_texts'][path] = text
        resources['source_index'][path]['content_hash'] = hashlib.sha256(text.encode()).hexdigest()
        resources['field_rows'].append(dict(resources['field_rows'][0], field_id='debt'))
        parent['expression'] = 'cash / debt'
        parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
        bound = _materialize_parent(compile_repair_search_policy(resources, project), parent)
        result = prepare_search(Path('unused'), parent, [], 8, bound)
        self.assertEqual(result['status'], 'validated', result)
        bindings = result['variants'][0]['binding']['bindings']
        self.assertEqual({row['field_id'] for row in bindings.values()}, {'cash', 'debt'})

    def test_metric_transform_parent_traits_and_source_check_accept_catalog_mode(self):
        resources, project, parent = catalog_fixture()
        policy = metric_transform(resources, project)
        bound = _materialize_parent(policy, parent)
        self.assertTrue(bound['traits']['matrix_observation']['value'])
        self.assertEqual(bound['resources']['evidence_context'].get('resource_admission_policy'), POLICY)
        result = prepare_search(Path('unused'), parent, [], 8, policy)
        self.assertEqual(result['status'], 'validated', result)
        self.assertEqual(len(result['variants']), 2, result)

    def test_vector_parent_uses_explicit_reducer_without_inventing_grain(self):
        resources, project, parent = catalog_fixture(vector=True)
        policy = metric_transform(resources, project)
        result = prepare_search(Path('unused'), parent, [], 8, policy)
        self.assertEqual(result['status'], 'validated', result)
        self.assertEqual(len(result['variants']), 2, result)
        self.assertNotIn('grain', policy['traits'])
        self.assertNotIn('vector_grain', policy['resources']['field_rows'][0])
        parent['expression'] = 'cash'
        parent['expression_hash'] = simulation_identity_hash('cash', parent['settings'])
        result = prepare_search(Path('unused'), parent, [], 8, policy)
        self.assertEqual(result['stop_reason'], 'missing_prerequisites', result)
        self.assertEqual(result['variants'], [])

    def test_absent_marker_keeps_field_and_operator_semantics_strict(self):
        for complete in (False, True):
            with self.subTest(complete_field=complete):
                resources, project, _ = catalog_fixture(complete=complete)
                resources.pop('resource_admission_policy')
                resources['evidence_pack'].pop('resource_admission_policy')
                with self.assertRaises(ValueError):
                    compile_repair_search_policy(resources, project)

    def test_wrong_known_signature_rejected_by_compiler_and_transform_path(self):
        for change in (dict(output_type='VECTOR'), dict(input_types=['VECTOR']),
                       dict(parameters=[dict(name='x', type='MATRIX', required=True)])):
            with self.subTest(change=change):
                resources, project, parent = catalog_fixture()
                policy = metric_transform(resources, project)
                resources['operator_rows'][0]['definition'].update(deepcopy(change))
                with self.assertRaises(ValueError):
                    compile_repair_search_policy(resources, project)
                policy['resources']['operator_rows'][0]['definition'].update(deepcopy(change))
                result = prepare_search(Path('unused'), parent, [], 8, policy)
                self.assertEqual(result['variants'], [], result)
                self.assertEqual(result['stop_reason'], 'missing_prerequisites', result)

    def test_marker_is_explicit_validated_and_cannot_be_context_only(self):
        for value in ('unknown', '', None, True):
            with self.subTest(value=value):
                resources, _, _ = catalog_fixture(complete=True)
                resources['resource_admission_policy'] = value
                with self.assertRaisesRegex(ValueError, 'admission'):
                    compile_repair_search_policy(resources, dict(compile_version=1, rules=[], traits={}))
        resources, _, _ = catalog_fixture()
        resources.pop('resource_admission_policy')
        with self.assertRaisesRegex(ValueError, 'admission'):
            compile_repair_search_policy(resources, dict(compile_version=1, rules=[], traits={}))
        resources, _, _ = catalog_fixture()
        resources['evidence_pack'].pop('resource_admission_policy')
        with self.assertRaisesRegex(ValueError, 'admission'):
            compile_repair_search_policy(resources, dict(compile_version=1, rules=[], traits={}))

    def test_default_rules_grids_ranking_and_triggers_are_unchanged(self):
        resources, _, parent = catalog_fixture(complete=True)
        legacy = deepcopy(resources)
        legacy.pop('resource_admission_policy')
        legacy['evidence_pack'].pop('resource_admission_policy')
        old = build_default_repair_policy(legacy)
        resources['field_rows'][0].pop('available_at')
        resources['field_rows'][0].pop('field_description')
        new = build_default_repair_policy(resources)
        self.assertEqual(new['rules'], old['rules'])
        self.assertEqual(new['traits'], old['traits'])
        self.assertEqual(new['resources'].get('resource_admission_policy'), POLICY)
        old_result = prepare_search(Path('unused'), parent, [], 8, old)
        new_result = prepare_search(Path('unused'), parent, [], 8, new)
        self.assertNotEqual(new_result['evidence_digest'], old_result['evidence_digest'])
        self.assertEqual({k: v for k, v in new_result.items() if k != 'evidence_digest'},
                         {k: v for k, v in old_result.items() if k != 'evidence_digest'})
        self.assertEqual(new_result['status'], 'validated', new_result)

    def test_unknown_cadence_and_exposure_do_not_authorize_actions(self):
        resources, _, parent = catalog_fixture()
        policy = build_default_repair_policy(resources)
        for name in ('sampling_frequency_sessions', 'nuisance_exposure', 'grain'):
            self.assertNotIn(name, policy['traits'])
        window = dict(rule_id='window', edit='transform', effect='smoothing', priority=0,
            target_metric='turnover', target_direction='decrease', grid=[2, 4], requires=dict(numeric_observation=True),
            evidence_refs=deepcopy(policy['rules'][0]['evidence_refs']),
            trigger=dict(checks=['LOW_FITNESS'], metric=None, operator=None, threshold=None),
            basis='project_hypothesis', rationale='Existing window mapping.', parameter_direction='any',
            transform=dict(operator='ts_mean', parameter='d', parameter_kind='window', bounds=[1, 10],
                           frequency_trait='sampling_frequency_sessions', preserves_direction=True))
        with_cadence, _, _ = catalog_fixture(cadence=1)
        policy['resources']['operator_rows'].append(with_cadence['operator_rows'][1])
        policy['resources']['evidence_context']['source_index'].update(with_cadence['source_index'])
        policy['resources']['evidence_context']['source_texts'].update(with_cadence['source_texts'])
        # Keep field raw without cadence while adding the actual operator source.
        path = resources['field_rows'][0]['source_paths'][0]
        policy['resources']['evidence_context']['source_index'][path] = resources['source_index'][path]
        policy['resources']['evidence_context']['source_texts'][path] = resources['source_texts'][path]
        exposed = dict(window, rule_id='exposure', edit='neutralization', effect='nuisance_exposure',
                       grid=['SECTOR'], requires=dict(nuisance_exposure=True))
        exposed.pop('transform')
        policy['rules'] = [window, exposed]
        result = prepare_search(Path('unused'), parent, [], 8, policy)
        self.assertEqual(result['variants'], [], result)
        self.assertEqual(result['stop_reason'], 'missing_prerequisites', result)
        reasons = {row['reason'] for row in result['skipped']}
        self.assertIn('frequency_unknown_or_unestablished', reasons)
        self.assertIn('trait_unknown:nuisance_exposure', reasons)

    def test_catalog_mode_preserves_identity_scope_numeric_and_date_checks(self):
        for change in (dict(field_id='other'), dict(dataset_id='other'), dict(field_type='VECTOR'),
                       dict(region='EUR'), dict(coverage=0), dict(coverage=.7), dict(coverage=float('nan')),
                       dict(coverage_status='partial'), dict(source_updated_at='invalid'),
                       dict(source_updated_at=(datetime.now(timezone.utc) - timedelta(days=91)).date().isoformat())):
            with self.subTest(change=change):
                resources, _, _ = catalog_fixture()
                resources['field_rows'][0].update(change)
                with self.assertRaises(ValueError):
                    build_default_repair_policy(resources)

    def test_source_hash_and_missing_definition_still_reject(self):
        for missing in (False, True):
            with self.subTest(missing_definition=missing):
                resources, project, _ = catalog_fixture()
                if missing:
                    resources['operator_rows'][0].pop('definition')
                else:
                    resources['source_texts'][next(iter(resources['source_texts']))] += ' '
                with self.assertRaises(ValueError):
                    compile_repair_search_policy(resources, project)

    def test_stop_and_zero_allowance_never_materialize_or_add_actions(self):
        resources, _, parent = catalog_fixture()
        policy = build_default_repair_policy(resources)
        for stopped, allowance, reason in ((True, 8, 'stopped'), (False, 0, 'allowance_exhausted')):
            with self.subTest(stopped=stopped, allowance=allowance):
                policy['stop'] = stopped
                result = prepare_search(Path('unused'), parent, [], allowance, policy)
                self.assertEqual(result['variants'], [])
                self.assertEqual(result['stop_reason'], reason)

    def test_direct_transform_projects_outer_marker_to_binder_context(self):
        from wqb.repair_search import _typed_transform
        resources, project, parent = catalog_fixture()
        policy = _materialize_parent(compile_repair_search_policy(resources, project), parent)
        frozen = policy['resources']
        frozen['evidence_context'].pop('resource_admission_policy')
        before = deepcopy(frozen)
        binding = _typed_transform(parent, policy['rules'][0], .5, frozen)
        self.assertEqual(ast.parse(binding['bound_expression'], mode='eval').body.func.id, 'signed_power')
        self.assertEqual(frozen, before)

    def test_persisted_catalog_transform_replays_for_compiled_and_metric_policies(self):
        from wqb.repair_search import prepare_persisted_search, verify_persisted_search
        for metric in (False, True):
            with self.subTest(metric=metric):
                resources, project, parent = catalog_fixture()
                policy = (metric_transform(resources, project) if metric else
                          compile_repair_search_policy(resources, project))
                snapshot = dict(research_policy=dict(deterministic_repair=True), repair_search_policy=policy,
                                data_ledger_rows=resources['field_rows'], operator_rows=resources['operator_rows'])
                context = {key: resources[key] for key in ('source_index', 'source_texts')}
                context.update(resource_contract_version=2, resource_admission_policy=POLICY)
                with tempfile.TemporaryDirectory() as directory, patch(
                        'wqb.hypothesis_selection.validate_operational_resource_context', return_value=context):
                    run = Path(directory)
                    (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)), encoding='utf-8')
                    receipt = prepare_persisted_search(run, parent, [], 1)
                    self.assertEqual(len(receipt['variants']), 1, receipt)
                    self.assertEqual(verify_persisted_search(run, receipt), receipt)
                    self.assertEqual(prepare_persisted_search(run, parent, [], 1), receipt)
                    context.pop('resource_admission_policy')
                    with self.assertRaisesRegex(ValueError, 'admission'):
                        verify_persisted_search(run, receipt)

    def test_raw_technical_signature_must_equal_snapshot_claim(self):
        from wqb.repair_search import _repair_operator_supported
        for change in (dict(output_type='VECTOR'),
                       dict(input_types=['VECTOR'], parameters=[dict(name='x', type='VECTOR', required=True),
                                                               dict(name='y', type='FLOAT', required=True)]),
                       dict(parameters=[dict(name='x', type='MATRIX', required=True),
                                        dict(name='power', type='FLOAT', required=True)])):
            with self.subTest(change=change):
                resources, project, parent = catalog_fixture()
                path = resources['operator_rows'][0]['definition']['evidence_refs'][0]['source_path']
                raw = json.loads(resources['source_texts'][path])
                raw[0]['definition'].update(change)
                replace_operator_raw(resources, raw)
                self.assertFalse(_repair_operator_supported(resources['operator_rows'][0], resources, True))
                with self.assertRaises(ValueError):
                    compile_repair_search_policy(resources, project)
                result = prepare_search(Path('unused'), parent, [], 8, metric_transform(resources, project))
                self.assertEqual(result['variants'], [], result)
                self.assertEqual(result['stop_reason'], 'missing_prerequisites', result)

    def test_source_reference_without_explicit_technical_facts_cannot_certify_signature(self):
        from wqb.repair_search import _repair_operator_supported
        for raw in ([dict(operator='signed_power', description='Only prose')],
                    [dict(operator='signed_power', definition='signed_power(x, y)')],
                    [dict(operator='other', definition=dict(input_types=['MATRIX'], output_type='MATRIX',
                        parameters=[dict(name='x', type='MATRIX', required=True),
                                    dict(name='y', type='FLOAT', required=True)]))]):
            with self.subTest(raw=raw):
                resources, _, _ = catalog_fixture()
                replace_operator_raw(resources, raw)
                self.assertFalse(_repair_operator_supported(resources['operator_rows'][0], resources, True))

    def test_raw_technical_equality_does_not_require_economic_description(self):
        from wqb.repair_search import _repair_operator_supported
        for description in (None, 'Different raw economic explanation'):
            with self.subTest(description=description):
                resources, project, parent = catalog_fixture()
                path = resources['operator_rows'][0]['definition']['evidence_refs'][0]['source_path']
                raw = json.loads(resources['source_texts'][path])
                if description is None:
                    raw[0]['definition'].pop('description')
                else:
                    raw[0]['definition']['description'] = description
                replace_operator_raw(resources, dict(operators=raw))
                self.assertTrue(_repair_operator_supported(resources['operator_rows'][0], resources, True))
                policy = _materialize_parent(compile_repair_search_policy(resources, project), parent)
                result = prepare_search(Path('unused'), parent, [], 8, policy)
                self.assertEqual(len(result['variants']), 2, result)

    def test_field_row_date_cannot_renew_old_or_mismatched_capture(self):
        from wqb.repair_search import _repair_field_supported
        for days in (1, 91, -1):
            with self.subTest(captured_days_ago=days):
                resources, _, _ = catalog_fixture()
                row = resources['field_rows'][0]
                path = row['source_paths'][0]
                captured = datetime.now(timezone.utc) - timedelta(days=days)
                resources['source_index'][path]['captured_at'] = captured.isoformat()
                self.assertFalse(_repair_field_supported(row, resources['source_texts'], resources['source_index'],
                                                        resources['evidence_pack']['scope'], True))
                with self.assertRaises(ValueError):
                    build_default_repair_policy(resources)

    def test_fresh_matching_capture_date_is_preserved_not_replaced_by_today(self):
        resources, _, parent = catalog_fixture()
        row = resources['field_rows'][0]
        captured = datetime.now(timezone.utc) - timedelta(days=3)
        row['source_updated_at'] = captured.date().isoformat()
        resources['source_index'][row['source_paths'][0]]['captured_at'] = captured.isoformat()
        before = deepcopy(resources)
        policy = build_default_repair_policy(resources)
        self.assertEqual(policy['resources']['field_rows'][0]['source_updated_at'], captured.date().isoformat())
        self.assertEqual(prepare_search(Path('unused'), parent, [], 8, policy)['status'], 'validated')
        self.assertEqual(resources, before)

    def test_raw_generated_date_cannot_be_relabelled_by_a_fresh_index(self):
        from wqb.repair_search import _repair_field_supported
        for days in (1, 91, -1):
            with self.subTest(raw_days_ago=days):
                resources, _, _ = catalog_fixture()
                row = resources['field_rows'][0]
                path = row['source_paths'][0]
                raw = json.loads(resources['source_texts'][path])
                raw['generated_at'] = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                text = json.dumps(raw)
                resources['source_texts'][path] = text
                resources['source_index'][path]['content_hash'] = hashlib.sha256(text.encode()).hexdigest()
                self.assertFalse(_repair_field_supported(row, resources['source_texts'], resources['source_index'],
                                                        resources['evidence_pack']['scope'], True))
                with self.assertRaises(ValueError):
                    build_default_repair_policy(resources)

    def test_stale_enclosing_generated_date_rejects_nested_field_despite_fresh_ledger(self):
        """Input: nested raw fixtures. Output: assertions; fresh descendants cannot renew an enclosing capture."""
        from wqb.repair_search import _repair_field_supported
        for container in ('json', 'jsonl', 'markdown'):
            for key in ('results', 'fields', 'payload'):
                with self.subTest(container=container, key=key):
                    resources, _, _ = catalog_fixture()
                    row = resources['field_rows'][0]
                    path = row['source_paths'][0]
                    raw = json.loads(resources['source_texts'][path])
                    raw['generated_at'] = resources['source_index'][path]['captured_at']
                    payload = dict(generated_at='2026-07-01T00:00:00Z', **{key: [dict(records=[raw])]})
                    replace_field_raw(resources, payload, container)
                    self.assertFalse(_repair_field_supported(row, resources['source_texts'], resources['source_index'],
                                                            resources['evidence_pack']['scope'], True))
                    with self.assertRaisesRegex(ValueError, 'field facts'):
                        build_default_repair_policy(resources)

    def test_fresh_enclosing_generated_date_accepts_nested_field_without_mutation(self):
        """Input: nested raw fixtures. Output: assertions; preserve a valid enclosing capture without inventing metadata."""
        for container in ('json', 'jsonl', 'markdown'):
            for key in ('results', 'fields', 'payload'):
                with self.subTest(container=container, key=key):
                    resources, _, parent = catalog_fixture()
                    path = resources['field_rows'][0]['source_paths'][0]
                    raw = json.loads(resources['source_texts'][path])
                    stamp = resources['source_index'][path]['captured_at']
                    replace_field_raw(resources, dict(generated_at=stamp, **{key: [dict(records=[raw])]}), container)
                    before = deepcopy(resources)
                    policy = build_default_repair_policy(resources)
                    self.assertEqual(prepare_search(Path('unused'), parent, [], 8, policy)['status'], 'validated')
                    self.assertEqual(resources, before)

    def test_unrelated_sibling_capture_date_does_not_conflict_with_selected_field(self):
        """Input: sibling capture fixtures. Output: assertions; dates apply only to their own identity/scope branches."""
        for container in ('json', 'jsonl', 'markdown'):
            for mismatch in ('field', 'dataset', 'scope'):
                with self.subTest(container=container, mismatch=mismatch):
                    resources, _, parent = catalog_fixture()
                    path = resources['field_rows'][0]['source_paths'][0]
                    raw = json.loads(resources['source_texts'][path])
                    other = deepcopy(raw)
                    if mismatch == 'field':
                        other['field']['id'] = 'other'
                    elif mismatch == 'dataset':
                        other['data_set']['id'] = 'other'
                    else:
                        other['scope']['region'] = 'EUR'
                    stamp = resources['source_index'][path]['captured_at']
                    selected = dict(generated_at=stamp, results=[raw])
                    sibling = dict(generated_at='2026-07-01T00:00:00Z', results=[other])
                    replace_field_raw(resources, dict(captures=[selected, sibling]), container)
                    policy = build_default_repair_policy(resources)
                    self.assertEqual(prepare_search(Path('unused'), parent, [], 8, policy)['status'], 'validated')

    def test_technical_source_authentication_does_not_imply_official_semantic_publication(self):
        resources, project, parent = catalog_fixture()
        row = resources['operator_rows'][0]
        old_path = row['definition']['evidence_refs'][0]['source_path']
        path = 'raw/platform/operators/catalog.json'
        resources['source_texts'][path] = resources['source_texts'].pop(old_path)
        source = resources['source_index'].pop(old_path)
        source.update(path=path, source_family='raw/platform/operators')
        resources['source_index'][path] = source
        row['definition']['evidence_refs'][0]['source_path'] = path
        compiled = compile_repair_search_policy(resources, project)
        bound = _materialize_parent(compiled, parent)
        self.assertEqual(prepare_search(Path('unused'), parent, [], 8, bound)['status'], 'validated')
        policy = metric_transform(resources, project)
        self.assertEqual(prepare_search(Path('unused'), parent, [], 8, policy)['status'], 'validated')

    def test_persisted_unsupported_action_skips_without_disabling_other_rules_and_replays(self):
        from wqb.repair_search import prepare_persisted_search, verify_persisted_search
        for failure in ('unsupported_signature', 'raw_contradiction', 'missing_definition'):
            for keep_settings_rule in (False, True):
                with self.subTest(failure=failure, keep_settings_rule=keep_settings_rule):
                    resources, project, parent = catalog_fixture()
                    parent['metrics']['turnover'] = .7
                    policy = metric_transform(resources, project)
                    path = resources['operator_rows'][0]['definition']['evidence_refs'][0]['source_path']
                    raw = json.loads(resources['source_texts'][path])
                    if failure != 'missing_definition':
                        raw[0]['definition']['output_type'] = 'VECTOR'
                        if failure == 'unsupported_signature':
                            resources['operator_rows'][0]['definition']['output_type'] = 'VECTOR'
                        replace_operator_raw(resources, raw)
                    policy['rules'][0]['evidence_refs'] = deepcopy(resources['operator_rows'][0]['definition']['evidence_refs'])
                    if failure == 'missing_definition':
                        resources['operator_rows'][0].pop('definition')
                    policy['resources']['operator_rows'] = deepcopy(resources['operator_rows'])
                    policy['resources']['evidence_context'].update(
                        source_index=deepcopy(resources['source_index']), source_texts=deepcopy(resources['source_texts']))
                    if keep_settings_rule:
                        policy['rules'].append(deepcopy(build_default_repair_policy(resources)['rules'][0]))
                    expected = prepare_search(Path('unused'), parent, [], 1, policy)
                    self.assertTrue(any(s['reason'] == 'unsupported_transform' for s in expected['skipped']), expected)
                    self.assertEqual(bool(expected['variants']), keep_settings_rule, expected)
                    if not keep_settings_rule:
                        self.assertEqual(expected['stop_reason'], 'missing_prerequisites', expected)
                    before = deepcopy(policy)
                    with tempfile.TemporaryDirectory() as directory:
                        run = Path(directory)
                        context = persisted_fixture(run, resources, policy)
                        with patch('wqb.hypothesis_selection.validate_operational_resource_context', return_value=context):
                            receipt = prepare_persisted_search(run, parent, [], 1)
                            self.assertEqual(receipt['variants'], expected['variants'])
                            self.assertEqual(receipt['skipped'], expected['skipped'])
                            self.assertEqual(receipt['stop_reason'], expected['stop_reason'])
                            self.assertEqual(verify_persisted_search(run, receipt), receipt)
                            self.assertEqual(prepare_persisted_search(run, parent, [], 1), receipt)
                    self.assertEqual(policy, before)
