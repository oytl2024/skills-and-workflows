"""Finite producer tests using local official-shaped raw, without live authority."""
import copy
import hashlib
import json
import unittest

from tests.test_repair_search import search_fixture
from tests.test_resource_evidence import SCOPE


def fixture():
    """Input: none. Output: resources/policy dicts with exact raw field facts."""
    path = 'raw/platform/data_fields/fields.jsonl'
    field = dict(id='cash', type='MATRIX', description='Cash balance',
                 available_at='2026-10-14T00:00:00Z')
    text = json.dumps(dict(scope=SCOPE, field=field, data_set=dict(id='d')))
    source = dict(path=path, content_hash=hashlib.sha256(text.encode()).hexdigest(),
                  captured_at='2026-10-15T00:00:00Z', source_type='platform_data_field_capture',
                  source_family='raw/platform/data_fields')
    row = dict(SCOPE, dataset_id='d', field_id='cash', field_type='MATRIX',
               field_description=field['description'], available_at=field['available_at'], source_paths=[path])
    resources = dict(resource_contract_version=2, field_rows=[row], operator_rows=[],
        source_index={path: source}, source_texts={path: text},
        evidence_pack=dict(scope=dict(SCOPE, as_of='2026-10-22T00:00:00Z')))
    _, old = search_fixture()
    rule = dict(old['rules'][0], requires=dict(matrix_observation=True), evidence_refs=[])
    return resources, dict(compile_version=1, rules=[rule], traits={})


class CompiledRepairTests(unittest.TestCase):
    def exposure_fixture(self, fact_name='nuisance_exposure'):
        """Input: captured fact name str. Output: resources/project/parent dicts with a true premise."""
        resources, project, parent = self.transform_fixture(1)
        path = resources['field_rows'][0]['source_paths'][0]
        payload = json.loads(resources['source_texts'][path])
        payload['field'][fact_name] = True
        text = json.dumps(payload)
        digest = hashlib.sha256(text.encode()).hexdigest()
        resources['source_texts'][path] = text
        resources['source_index'][path]['content_hash'] = digest
        premise = dict(evidence_ref=dict(source_path=path, sha256=digest,
            capture_date='2026-10-15', kind='documented', experiment_refs=[]),
            locator=dict(kind='json_value', row_identity=dict(dataset_id='d', field_id='cash', scope=SCOPE),
                         value_path=['field', fact_name], expected_value=True))
        project['traits'] = dict(nuisance_exposure=dict(value=True, premises=[premise]))
        project['rules'] = [dict(rule_id='exposure', edit='neutralization', effect='nuisance_exposure',
            priority=0, target_metric='turnover', target_direction='decrease', grid=['SECTOR'],
            requires=dict(nuisance_exposure=True), evidence_refs=[])]
        return resources, project, parent

    def test_true_unrelated_fact_cannot_prove_exposure(self):
        """Input: real true activity fact. Output: rejection instead of authorized neutralization."""
        resources, project, _ = self.exposure_fixture('is_active')
        with self.assertRaises(ValueError):
            self.compile(resources, project)

    def test_arbitrary_trait_alias_cannot_relabel_source_meaning(self):
        """Input: renamed exposure trait. Output: rejection of unsupported semantic aliases."""
        resources, project, _ = self.exposure_fixture()
        project['traits']['arbitrary_alias'] = project['traits'].pop('nuisance_exposure')
        project['rules'][0].update(edit='decay', effect='smoothing', grid=[2],
                                  requires=dict(arbitrary_alias=True))
        with self.assertRaises(ValueError):
            self.compile(resources, project)

    def test_parent_revalidates_field_specific_exposure(self):
        """Input: two certified fields, only cash exposed. Output: parent-local trait/rule authorization."""
        from pathlib import Path
        from wqb.cli import simulation_identity_hash
        from wqb.repair_search import _materialize_parent, prepare_search
        resources, project, parent = self.exposure_fixture()
        path = resources['field_rows'][0]['source_paths'][0]
        other_path = 'raw/platform/data_fields/other.jsonl'
        other_payload = json.loads(resources['source_texts'][path])
        other_payload['field'].update(id='other_cash', description='Other reserves')
        del other_payload['field']['nuisance_exposure']
        text = json.dumps(other_payload)
        resources['source_texts'][other_path] = text
        resources['source_index'][other_path] = dict(resources['source_index'][path], path=other_path,
            content_hash=hashlib.sha256(text.encode()).hexdigest())
        resources['field_rows'].append(dict(resources['field_rows'][0], field_id='other_cash',
                                           field_description='Other reserves', source_paths=[other_path]))
        project['rules'].append(dict(fixture()[1]['rules'][0], grid=[4]))
        compiled = self.compile(resources, project)
        for expression, count in (('cash', 1), ('other_cash', 0), ('cash + other_cash', 0)):
            with self.subTest(expression=expression):
                parent['expression'] = expression
                parent['expression_hash'] = simulation_identity_hash(expression, parent['settings'])
                policy = _materialize_parent(compiled, parent)
                result = prepare_search(Path('unused'), parent, [], 8, policy)
                self.assertEqual(sum(v['decision']['edit'] == 'neutralization'
                                     for v in result['variants']), count, result)
                self.assertEqual(sum(v['decision']['edit'] == 'decay'
                                     for v in result['variants']), 1, result)
                self.assertEqual('nuisance_exposure' in policy['traits'], bool(count))
        self.assertIn('nuisance_exposure', compiled['traits'])
        other_payload['field']['nuisance_exposure'] = True
        text = json.dumps(other_payload)
        digest = hashlib.sha256(text.encode()).hexdigest()
        resources['source_texts'][other_path] = text
        resources['source_index'][other_path]['content_hash'] = digest
        premise = copy.deepcopy(project['traits']['nuisance_exposure']['premises'][0])
        premise['evidence_ref'].update(source_path=other_path, sha256=digest)
        premise['locator']['row_identity']['field_id'] = 'other_cash'
        project['traits']['nuisance_exposure']['premises'].append(premise)
        for expression in ('cash', 'other_cash', 'cash + other_cash'):
            with self.subTest(fully_covered=expression):
                parent['expression'] = expression
                parent['expression_hash'] = simulation_identity_hash(expression, parent['settings'])
                policy = _materialize_parent(self.compile(resources, project), parent)
                result = prepare_search(Path('unused'), parent, [], 8, policy)
                self.assertEqual(len(result['variants']), 2, result)
                self.assertEqual(len(policy['traits']['nuisance_exposure']['evidence_refs']),
                                 2 if '+' in expression else 1)

    def test_parent_slots_are_atomic_through_sixteen_fields(self):
        """Input: certified 11/16-field parents. Output: exact AST and complete unique binding slots."""
        import ast
        from pathlib import Path
        from wqb.cli import simulation_identity_hash
        from wqb.repair_search import _materialize_parent, prepare_search
        for count in (11, 16):
            with self.subTest(count=count):
                resources, project, parent = self.transform_fixture(1)
                path = resources['field_rows'][0]['source_paths'][0]
                payload = json.loads(resources['source_texts'][path])
                rows, captures = [], []
                for i in range(count):
                    name = 'cash_' + str(i)
                    description = 'Unique balance ' + str(i) + ' end'
                    row = dict(resources['field_rows'][0], field_id=name, field_description=description)
                    capture = copy.deepcopy(payload)
                    capture['field'].update(id=name, description=description)
                    rows.append(row)
                    captures.append(capture)
                text = '\n'.join(json.dumps(capture) for capture in captures)
                resources['source_texts'][path] = text
                resources['source_index'][path]['content_hash'] = hashlib.sha256(text.encode()).hexdigest()
                resources['field_rows'] = rows
                parent['expression'] = ' + '.join(row['field_id'] for row in rows)
                parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
                policy = _materialize_parent(self.compile(resources, project), parent)
                self.assertEqual(len(policy['resources']['template']['input_slots']), count)
                result = prepare_search(Path('unused'), parent, [], 8, policy)
                self.assertEqual(len(result['variants']), 2, result)
                for variant in result['variants']:
                    node = ast.parse(variant['expression'], mode='eval').body
                    self.assertEqual(ast.dump(node.args[0]),
                                     ast.dump(ast.parse(parent['expression'], mode='eval').body))

    def test_actual_legacy_start_keeps_empty_policy_without_producer(self):
        """Input: explicitly supplied legacy policy. Output: unchanged empty v1 policy and paused authority."""
        from tests.test_preplanned_start import PreplannedStartTests
        helper = PreplannedStartTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        helper.config['repair_search_policy'] = dict(schema_version=1, rules=[], traits={})
        result = helper.prepare()
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['group']['desired_state'], 'paused')
        run = helper.paths.run_root / result['group']['lanes'][0]['run_id']
        snapshot = json.loads((run / 'run_manifest.json').read_text(encoding='utf-8'))['start_snapshot']
        self.assertEqual(snapshot['repair_search_policy']['rules'], [])
        self.assertNotIn('resources', snapshot['repair_search_policy'])
        self.assertFalse((run / 'runtime/control.json').exists())
        self.assertEqual(helper.runner.call_count, 1)

    def test_actual_opt_in_start_seed_repair_consumes_accepted_parent(self):
        """Input: isolated certified Start/fake HTTP. Output: compiled typed Repair bound to measured Seed/incumbent."""
        self.exercise_actual_start_repair(default_rules=False)

    def test_default_metric_rules_complete_start_seed_repair_without_late_model(self):
        """Input: certified Start without custom rules. Output: measured finite setting search, no late AI calls."""
        self.exercise_actual_start_repair(default_rules=True)

    def exercise_actual_start_repair(self, *, default_rules):
        """Input: bool selecting default/explicit rules. Output: assertions across real composer and fake HTTP."""
        import ast
        import os
        from pathlib import Path
        from unittest.mock import patch
        from tests.test_preplanned_start import PreplannedStartTests
        from tests.test_preplanned_research_acceptance import IntegratedFourRootAcceptanceTests, four_root_answer
        from wqb.semantic_compilation import prepare_design_job
        from wqb.semantic_contracts import SemanticPolicy
        from wqb.cli import submit_candidate_payloads
        from wqb.recorder import RunRecorder
        from wqb.repair_search import prepare_persisted_search, verify_persisted_search
        from wqb.repair_scheduler import execute_repair_round
        from wqb.research_seed_stage import prepare_seed_selection
        from wqb.tree_runtime import checked_research_rows
        from wqb.runtime_control import CONTROL_ENV
        from wqb.daily_simulation_budget import read_daily_budget
        helper = IntegratedFourRootAcceptanceTests()
        helper.fixture = PreplannedStartTests()
        helper.fixture.setUp()
        self.addCleanup(helper.fixture.doCleanups)
        base = helper.fixture
        resource = base.resources[0]
        row = resource['field_rows'][0]
        old = row['source_paths'][0]
        payload = json.loads(resource['source_texts'][old])
        payload['fields'][0]['field']['sampling_frequency_sessions'] = 1
        definition = dict(description='Returns the average value of x over the past d days.',
            input_types=['MATRIX'], output_type='MATRIX', parameters=[
                dict(name='x', type='MATRIX', required=True), dict(name='d', type='INTEGER', required=True)])
        payload['operators'].append(dict(operator='ts_mean', definition=definition))
        text = json.dumps(payload)
        path = 'raw/platform/data_fields/certified-repair.json'
        digest = hashlib.sha256(text.encode()).hexdigest()
        source = dict(path=path, content_hash=digest, captured_at='2026-10-14T00:00:00Z',
            source_type='platform_data_field_capture', source_family='raw/platform/data_fields')
        ref = dict(source_path=path, sha256=digest, capture_date='2026-10-14', kind='documented', experiment_refs=[])
        row['source_paths'] = [path]
        resource['operator_rows'].append(dict(operator='ts_mean', definition=copy.deepcopy(definition)))
        for operator in resource['operator_rows']:
            operator['definition']['evidence_refs'] = [copy.deepcopy(ref)]
        resource.update(resource_contract_version=2, source_index={path: source}, source_texts={path: text})
        resource['evidence_pack'].update(resource_contract_version=2,
            source_index=copy.deepcopy(resource['source_index']), source_texts=copy.deepcopy(resource['source_texts']))
        raw = base.paths.knowledge_root / path
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(text, encoding='utf-8')
        machine = base.paths.knowledge_root / 'machine'
        (machine / 'source_index.jsonl').write_text(json.dumps(source) + '\n', encoding='utf-8')
        (machine / 'data_ledger.jsonl').write_text(json.dumps(row) + '\n', encoding='utf-8')
        prepare_design_job(base.paths.knowledge_root, resource['evidence_pack'], SemanticPolicy(), resource)
        base.config['repair_search_policy'] = dict(compile_version=1, traits={}, rules=[dict(
            rule_id='certified-mean', edit='transform', effect='smoothing', priority=0,
            target_metric='turnover', target_direction='decrease', grid=[2],
            requires=dict(matrix_observation=True), evidence_refs=[], invariant='positive_averaging',
            transform=dict(operator='ts_mean', parameter='d', parameter_kind='window', bounds=[1, 5],
                           frequency_trait='sampling_frequency_sessions', preserves_direction=True))])
        if default_rules:
            base.config.pop('repair_search_policy')
        base.authority['enable_live_api'] = True
        base.paths.workflow_root = Path(__file__).resolve().parents[1]
        base.runner.side_effect = lambda brief: four_root_answer(base, brief)
        helper.start_group()
        helper.finish_trees()
        run = helper.runs[0]
        snapshot = json.loads((run / 'run_manifest.json').read_text())['start_snapshot']
        if default_rules:
            self.assertEqual(snapshot['repair_search_policy']['schema_version'], 2)
            self.assertTrue(snapshot['repair_search_policy']['rules'])
        else:
            self.assertEqual(snapshot['repair_search_policy']['resources']['producer']['compile_version'], 1)
        self.assertNotIn('template', snapshot['repair_search_policy']['resources'])
        selection = prepare_seed_selection(run, checked_research_rows(run))
        self.assertTrue(selection['seed_rows'])
        parent = selection['seed_rows'][0]
        authority_before = copy.deepcopy(helper.group['authority'])
        manifest_before = (run / 'run_manifest.json').read_bytes()
        calls = base.runner.call_count
        transport = helper.transport
        executions = []
        test = self

        class Executor:
            supports_plan_preparation = True
            supports_durable_recovery = True

            def prepare(self, root, current, history, maximum):
                """Input: scheduler accepted parent/history/cap. Output: real source-validated persisted plan."""
                return prepare_persisted_search(root, current, history, maximum)

            def __call__(self, root, current, actions, maximum):
                """Input: scheduler immutable action. Output: genuine checked CLI row through fake HTTP only."""
                plan = verify_persisted_search(root, actions[0]['repair_plan'])
                variant = plan['variants'][0]
                node = ast.parse(variant['expression'], mode='eval').body
                if default_rules:
                    test.assertEqual(variant['expression'], current['expression'])
                    test.assertNotEqual(variant['settings']['decay'], current['settings']['decay'])
                    test.assertEqual({k: v for k, v in variant['settings'].items() if k != 'decay'},
                                     {k: v for k, v in current['settings'].items() if k != 'decay'})
                    test.assertIn('LOW_FITNESS', plan['decision']['trigger_evidence']['failed_checks'])
                else:
                    test.assertEqual(ast.dump(node.args[0]), ast.dump(ast.parse(current['expression'], mode='eval').body))
                test.assertEqual(variant['parent_expression_hash'], current['expression_hash'])
                if not default_rules:
                    test.assertEqual(variant['settings'], current['settings'])
                executions.append(current['alpha_id'])
                change = dict(fitness=current['metrics']['fitness'] + .005) if default_rules else dict(
                    turnover=current['metrics']['turnover'] / 2)
                transport.metrics[variant['expression_hash']] = dict(current['metrics'], **change)
                recorder = RunRecorder(root / ('stages/repair/compiled-' + str(len(executions))))
                submit_candidate_payloads(transport.client, recorder,
                    [dict(type='REGULAR', regular=variant['expression'], settings=variant['settings'])],
                    [variant], 'multi', 'compiled-repair', knowledge_root=base.paths.knowledge_root)
                return recorder.read_jsonl('all_alphas.jsonl')

        before = read_daily_budget(run)['used']
        with patch.dict(os.environ, {CONTROL_ENV: str(run)}), patch(
                'wqb.ai_checkpoints.run_ai_checkpoint', side_effect=AssertionError('No late model')):
            first = execute_repair_round(run, dict(rows=[parent]), Executor(), 2)
            self.assertEqual(first['attempts'][0]['experiment_trace']['outcome'], 'accepted', first.get('blocker'))
            incumbent = first['attempts'][0]['children'][0]
            second = execute_repair_round(run, dict(rows=[parent]), Executor(), 2)
        self.assertEqual(second['attempts'][1]['parent_alpha_id'], incumbent['alpha_id'])
        plan = verify_persisted_search(run, second['attempts'][1]['plan'])
        evidence = json.loads(Path(plan['receipt_path']).with_suffix('.input.json').read_text(encoding='utf-8'))
        self.assertEqual(evidence['parent'], incumbent)
        if default_rules:
            self.assertEqual(plan['decision']['target_metric'], 'fitness')
        else:
            self.assertEqual(plan['decision']['rule_id'], 'certified-mean')
        self.assertEqual(plan['decision']['parent_expression_hash'], incumbent['expression_hash'])
        self.assertEqual(plan['decision']['parent_alpha_id'], incumbent['alpha_id'])
        from wqb.research_group import read_group
        self.assertEqual(read_group(Path(helper.group['group_dir']))['authority'], authority_before)
        self.assertEqual((run / 'run_manifest.json').read_bytes(), manifest_before)
        self.assertEqual(executions, [parent['alpha_id'], incumbent['alpha_id']])
        self.assertEqual(read_daily_budget(run)['used'], before + 2)
        self.assertEqual(base.runner.call_count, calls)
        self.assertEqual(calls, 1)
        self.assertFalse(any(path.endswith('/check') for _, path in transport.calls))

    def transform_fixture(self, cadence=None):
        """Input: optional cadence int. Output: resource/project/parent dicts with typed raw definition."""
        resources, policy = fixture()
        if cadence is not None:
            path = next(iter(resources['source_texts']))
            payload = json.loads(resources['source_texts'][path])
            payload['field']['sampling_frequency_sessions'] = cadence
            resources['source_texts'][path] = json.dumps(payload)
            resources['source_index'][path]['content_hash'] = hashlib.sha256(
                resources['source_texts'][path].encode()).hexdigest()
        path = 'raw/platform/learn/operators.json'
        definition = dict(description='Returns the average value of x over the past d days.',
            input_types=['MATRIX'], output_type='MATRIX', parameters=[
                dict(name='x', type='MATRIX', required=True), dict(name='d', type='INTEGER', required=True)])
        text = json.dumps(dict(operator='ts_mean', definition=definition))
        digest = hashlib.sha256(text.encode()).hexdigest()
        ref = dict(source_path=path, sha256=digest, capture_date='2026-10-15', kind='documented', experiment_refs=[])
        resources['source_index'][path] = dict(path=path, content_hash=digest,
            captured_at='2026-10-15T00:00:00Z', source_type='platform_learn_material', source_family='raw/platform/learn')
        resources['source_texts'][path] = text
        resources['operator_rows'] = [dict(operator='ts_mean', definition=dict(definition, evidence_refs=[ref]))]
        policy['rules'][0].update(edit='transform', invariant='positive_averaging', grid=[2, 4],
            transform=dict(operator='ts_mean', parameter='d', parameter_kind='window', bounds=[1, 10],
                frequency_trait='sampling_frequency_sessions', preserves_direction=True))
        parent, _ = search_fixture()
        parent['expression'] = 'cash'
        parent['settings']['instrumentType'] = 'EQUITY'
        from wqb.cli import simulation_identity_hash
        parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
        return resources, policy, parent

    def test_sourced_transform_parent_and_unknown_cadence(self):
        from wqb.repair_search import _materialize_parent, prepare_search
        from pathlib import Path
        for cadence, count in ((None, 0), (1, 2)):
            resources, project, parent = self.transform_fixture(cadence)
            policy = _materialize_parent(self.compile(resources, project), parent)
            result = prepare_search(Path('unused'), parent, [], 8, policy)
            self.assertEqual(len(result['variants']), count, result)
            for variant in result['variants']:
                self.assertEqual(variant['parent_expression_hash'], parent['expression_hash'])
                self.assertEqual(variant['settings'], parent['settings'])

    def test_unsupported_signature_and_parent_reject(self):
        from wqb.repair_search import _materialize_parent
        resources, project, parent = self.transform_fixture(1)
        compiled = self.compile(resources, project)
        parent['expression'] = 'missing'
        with self.assertRaises(ValueError):
            _materialize_parent(compiled, parent)
        resources['operator_rows'][0]['definition']['output_type'] = 'VECTOR'
        with self.assertRaises(ValueError):
            self.compile(resources, project)

    def test_persisted_restart_rebuilds_parent_and_rejects_changed_producer(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from wqb.repair_search import prepare_persisted_search, verify_persisted_search
        resources, project, parent = self.transform_fixture(1)
        compiled = self.compile(resources, project)
        snapshot = dict(research_policy=dict(deterministic_repair=True),
            repair_search_policy=compiled, data_ledger_rows=resources['field_rows'],
            operator_rows=resources['operator_rows'])
        context = {key: resources[key] for key in ('source_index', 'source_texts')}
        with tempfile.TemporaryDirectory() as directory, patch(
                'wqb.hypothesis_selection.validate_operational_resource_context', return_value=context):
            run = Path(directory)
            manifest = run / 'run_manifest.json'
            manifest.write_text(json.dumps(dict(start_snapshot=snapshot)), encoding='utf-8')
            plan = prepare_persisted_search(run, parent, [], 1)
            self.assertEqual(verify_persisted_search(run, plan), plan)
            self.assertEqual(prepare_persisted_search(run, parent, [], 1), plan)
            snapshot['repair_search_policy']['rules'][0]['grid'] = [9]
            manifest.write_text(json.dumps(dict(start_snapshot=snapshot)), encoding='utf-8')
            with self.assertRaises(ValueError):
                verify_persisted_search(run, plan)

    def compile(self, resources, policy):
        """Input: resource/project dicts. Output: strict compiled policy dict."""
        from wqb.repair_search import compile_repair_search_policy
        return compile_repair_search_policy(resources, policy)

    def test_matrix_finite_project_trial_and_legacy(self):
        from wqb.preplanned_start import _repair_policy
        resources, policy = fixture()
        compiled = self.compile(resources, policy)
        self.assertEqual(compiled['rules'][0]['grid'], [2, 4, 8])
        self.assertEqual(_repair_policy(resources, policy), compiled)
        self.assertTrue(_repair_policy(resources)['rules'])
        self.assertEqual(_repair_policy(resources)['schema_version'], 2)
        self.assertNotIn('noisy', compiled['traits'])

    def test_hash_unknown_trait_and_authority_fail_closed(self):
        resources, policy = fixture()
        for change in ('hash', 'trait', 'authority'):
            r, p = copy.deepcopy(resources), copy.deepcopy(policy)
            if change == 'hash':
                r['source_texts'][next(iter(r['source_texts']))] += ' '
            elif change == 'trait':
                p['rules'][0]['requires'] = dict(noisy=True)
            else:
                p['final_submit'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.compile(r, p)

    def test_flag_alone_is_not_transform_invariant(self):
        resources, policy = fixture()
        policy['rules'][0].update(edit='transform', transform=dict(operator='ts_mean',
            parameter='d', parameter_kind='window', bounds=[1, 10],
            frequency_trait='cadence', preserves_direction=True))
        with self.assertRaises(ValueError):
            self.compile(resources, policy)

    def test_invalid_cadence_remains_unknown_and_settings_remain_available(self):
        for cadence in (True, 0, -1, 'daily'):
            resources, project, _ = self.transform_fixture(cadence)
            compiled = self.compile(resources, project)
            self.assertNotIn('sampling_frequency_sessions', compiled['traits'])
            settings = fixture()[1]
            self.assertEqual(self.compile(resources, settings)['rules'][0]['edit'], 'decay')

    def test_vector_missing_grain_rejects_without_type_inference(self):
        resources, project = fixture()
        path = next(iter(resources['source_texts']))
        payload = json.loads(resources['source_texts'][path])
        payload['field']['type'] = 'VECTOR'
        resources['source_texts'][path] = json.dumps(payload)
        resources['source_index'][path]['content_hash'] = hashlib.sha256(
            resources['source_texts'][path].encode()).hexdigest()
        resources['field_rows'][0]['field_type'] = 'VECTOR'
        with self.assertRaises(ValueError):
            self.compile(resources, project)

    def test_neutralization_requires_exact_exposure_premise(self):
        resources, project = fixture()
        path = next(iter(resources['source_texts']))
        payload = json.loads(resources['source_texts'][path])
        payload['field']['nuisance_exposure'] = True
        text = json.dumps(payload)
        digest = hashlib.sha256(text.encode()).hexdigest()
        resources['source_texts'][path] = text
        resources['source_index'][path]['content_hash'] = digest
        ref = dict(source_path=path, sha256=digest, capture_date='2026-10-15', kind='documented', experiment_refs=[])
        premise = dict(evidence_ref=ref, locator=dict(kind='json_value',
            row_identity=dict(dataset_id='d', field_id='cash', scope=SCOPE),
            value_path=['field', 'nuisance_exposure'], expected_value=True))
        project['traits'] = dict(nuisance_exposure=dict(value=True, premises=[premise]))
        project['rules'][0].update(edit='neutralization', effect='nuisance_exposure',
            requires=dict(nuisance_exposure=True), grid=['SECTOR'])
        self.assertEqual(self.compile(resources, project)['rules'][0]['grid'], ['SECTOR'])
        premise['locator']['row_identity']['field_id'] = 'unrelated'
        with self.assertRaises(ValueError):
            self.compile(resources, project)

    def test_signed_power_positive_exact_meaning(self):
        from pathlib import Path
        from wqb.repair_search import _materialize_parent, prepare_search
        resources, project, parent = self.transform_fixture()
        row = resources['operator_rows'][0]
        row['operator'] = 'signed_power'
        definition = row['definition']
        definition['description'] = 'Raises the absolute value of x to the power y while preserving its sign.'
        definition['parameters'][1].update(name='y', type='FLOAT')
        path = definition['evidence_refs'][0]['source_path']
        raw_definition = {k: v for k, v in definition.items() if k != 'evidence_refs'}
        text = json.dumps(dict(operator='signed_power', definition=raw_definition))
        digest = hashlib.sha256(text.encode()).hexdigest()
        resources['source_texts'][path] = text
        resources['source_index'][path]['content_hash'] = digest
        definition['evidence_refs'][0]['sha256'] = digest
        rule = project['rules'][0]
        rule.update(invariant='positive_signed_power', effect='bounded_weights', grid=[0.5, 0.8])
        rule['transform'].update(operator='signed_power', parameter='y', parameter_kind='scalar',
                                 bounds=[0.1, 1], frequency_trait=None)
        policy = _materialize_parent(self.compile(resources, project), parent)
        result = prepare_search(Path('unused'), parent, [], 8, policy)
        self.assertEqual(len(result['variants']), 2, result)
        rule['grid'] = [-0.5]
        with self.assertRaises(ValueError):
            self.compile(resources, project)

    def test_vector_requires_explicit_parent_reducer_and_grain(self):
        from pathlib import Path
        from wqb.cli import simulation_identity_hash
        from wqb.repair_search import _materialize_parent, prepare_search
        resources, project, parent = self.transform_fixture(1)
        path = resources['field_rows'][0]['source_paths'][0]
        payload = json.loads(resources['source_texts'][path])
        payload['field'].update(type='VECTOR', vector_grain='events')
        text = json.dumps(payload)
        digest = hashlib.sha256(text.encode()).hexdigest()
        resources['source_texts'][path] = text
        resources['source_index'][path]['content_hash'] = digest
        resources['field_rows'][0].update(field_type='VECTOR', vector_grain='events')
        ref = dict(source_path=path, sha256=digest, capture_date='2026-10-15', kind='documented', experiment_refs=[])
        project['traits'] = dict(grain=dict(value='events', premises=[dict(evidence_ref=ref,
            locator=dict(kind='json_value', row_identity=dict(dataset_id='d', field_id='cash', scope=SCOPE),
                         value_path=['field', 'vector_grain'], expected_value='events'))]))
        project['rules'][0]['requires'] = dict(grain='events')
        definition = dict(description='Returns the average of vector elements.', input_types=['VECTOR'],
            output_type='MATRIX', parameters=[dict(name='x', type='VECTOR', required=True)])
        op = resources['operator_rows'][0]
        path = op['definition']['evidence_refs'][0]['source_path']
        text = json.dumps([dict(operator='ts_mean', definition={k: v for k, v in op['definition'].items()
            if k != 'evidence_refs'}), dict(operator='vec_avg', definition=definition)])
        digest = hashlib.sha256(text.encode()).hexdigest()
        resources['source_texts'][path] = text
        resources['source_index'][path]['content_hash'] = digest
        op['definition']['evidence_refs'][0]['sha256'] = digest
        resources['operator_rows'].append(dict(operator='vec_avg', definition=dict(definition,
            evidence_refs=copy.deepcopy(op['definition']['evidence_refs']))))
        compiled = self.compile(resources, project)
        with self.assertRaises(ValueError):
            _materialize_parent(compiled, parent)
        parent['expression'] = 'vec_avg(cash)'
        parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
        policy = _materialize_parent(compiled, parent)
        result = prepare_search(Path('unused'), parent, [], 8, policy)
        self.assertEqual(len(result['variants']), 2, result)
