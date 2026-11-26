"""Real query-to-package integration with a single fake model task per lane."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch

from tests import test_preplanned_start as fixtures


class RetrievalStartTests(unittest.TestCase):
    def test_expression_tool_plan_freezes_with_script_derived_identities(self):
        from wqb.preplanned_start import prepare_preplanned_start
        from wqb.retrieval_research_planning import query_design_task
        config=deepcopy(self.config)
        config['expression_tool_version']=1
        config['research_policy']['expression_tool_version']=1
        calls=[]
        def model(directory,brief):
            number=int(directory.name.rsplit('-',1)[1])
            source=self.fixture.resources[number]['field_rows'][0]
            node=dict(kind='field',dataset_id=source['dataset_id'],field_id=source['field_id'])
            compiled=query_design_task(directory,'compile',dict(expression=node))
            self.assertTrue(compiled['valid'],compiled)
            calls.append(compiled['expression'])
            answer=dict(summary='A hypothesis. A competing explanation.',selection=[],history_selection=[],
                data_characteristics=[],designs=[dict(design_version=4,hypothesis='Multiple sentences.\nUnknown timing is not a rejection.',
                    baseline=node,treatment=dict(kind='binary',operator='*',left=node,right=dict(kind='literal',value=0.5)),
                    repair_recipe=dict(rules=[dict(edit='wrap',template=dict(kind='call',operator='ts_delta',
                        args=[dict(kind='parent'),dict(kind='parameter')],kwargs={}),grid=[5,22],
                        target_metric='fitness',target_direction='increase')]))],
                tree=dict(roots=['r'],nodes=[dict(node_id='r',parent_id=None,parent_arm_id=None,design_index=0,
                    targets=dict(baseline=[],treatment=[]),fallback=[],reverse={})]))
            checked=query_design_task(directory,'validate',dict(selection=[],answer=answer))
            self.assertTrue(checked['valid'],checked)
            return answer
        result=prepare_preplanned_start(self.fixture.paths,self.fixture.option,self.fixture.authority,config,
            model_runner=lambda _:self.fail('legacy model'),retrieval_model_runner=model)
        self.assertEqual(result['status'],'completed',result)
        self.assertTrue(calls)
        from wqb.execution_package import load_execution_context
        run=self.fixture.paths.run_root/result['group']['lanes'][0]['run_id']
        with patch('wqb.exploration_eligibility._validate_operational_exploration_sources',
                side_effect=AssertionError('sealed execution must not reopen global knowledge')):
            frozen=load_execution_context(run)
        self.assertEqual(frozen['experiments'][0]['expression_tool_version'],1)
        from wqb.repair_search import prepare_persisted_search,verify_persisted_search
        from wqb.cli import simulation_identity_hash
        arm=frozen['experiments'][0]['arms'][1]
        parent=dict(alpha_id='offline-seed',expression=arm['binding']['bound_expression'],settings=arm['settings'],
            status='CHECKED',metrics=dict(sharpe=1.4,fitness=.8,turnover=.3),failed=['LOW_FITNESS'],pending=[],hard_pass=False)
        parent['expression_hash']=simulation_identity_hash(parent['expression'],parent['settings'])
        plan=prepare_persisted_search(run,parent,[],8)
        self.assertTrue(plan['variants'],plan)
        self.assertEqual(plan['decision']['edit'],'transform')
        self.assertEqual(verify_persisted_search(run,plan),plan)

    def test_contract_bootstrap_is_separate_from_knowledge_sources(self):
        from wqb.preplanned_start import prepare_preplanned_start
        from wqb.retrieval_research_planning import query_design_task

        def model(directory, brief):
            """Input: running task. Output: fake plan after reading contracts through the owning budgeted interface."""
            for section in ('overview', 'composition_contract', 'tool_contracts', 'output_schema'):
                page = query_design_task(directory, 'contract', dict(section=section, length=8000))
                self.assertEqual(page['kind'], 'task_contract')
                self.assertTrue(page['text'])
                self.assertEqual(page['scope'], brief['scope'])
                self.assertIn('queries', page['tool_budget'])
            with self.assertRaisesRegex(ValueError, 'source_path.*allowed:.*path'):
                query_design_task(directory, 'source', dict(source_path='runtime/task.json'))
            with self.assertRaisesRegex(ValueError, 'contract'):
                query_design_task(directory, 'contract', dict(section='../secrets'))
            return self.model(directory, brief)

        result = prepare_preplanned_start(self.fixture.paths, self.fixture.option, self.fixture.authority,
            self.config, model_runner=lambda _: self.fail('legacy model'), retrieval_model_runner=model)
        self.assertEqual(result['status'], 'completed', result)

    def test_known_rejected_answer_does_not_erase_or_replay_unknown_outcomes(self):
        from types import SimpleNamespace
        from wqb.console_start import _require_resolved_retrieval
        runs = self.fixture.paths.run_root.absolute()
        directory = runs / 'start_preflight/preplanned/offline'
        directory.mkdir(parents=True)
        paths = SimpleNamespace(runs_root=runs)
        before = dict(request_id='original', retrieval_design_task=dict(directory=str(directory), input_sha256='digest'))
        task = dict(input_sha256='digest', identity=dict(config=dict(retrieval_owner=dict(
            runs_root=str(runs), request_id='original'))), status='blocked', answer=dict(summary='rejected'),
            brief=dict(output_schema=dict(type='object', properties=dict(summary=dict(type='string')),
                required=['summary'], additionalProperties=False)))
        with patch('wqb.retrieval_research_planning.read_design_task', return_value=task):
            _require_resolved_retrieval(paths, before)
            task['status'] = 'unknown'
            with self.assertRaisesRegex(ValueError, 'unresolved retrieval'):
                _require_resolved_retrieval(paths, before)
    def test_empty_plan_reports_model_failure_instead_of_placeholder_field(self):
        from wqb.retrieval_research_planning import _resolve_answer, design_schema
        task = dict(identity=dict(knowledge_root=str(self.fixture.paths.knowledge_root), generation='g'),
            brief=dict(output_schema=design_schema()))
        with patch('wqb.research_query_index.validate_query_generation'):
            with self.assertRaisesRegex(ValueError, 'model_returned_no_plan: tool access denied'):
                _resolve_answer(task, dict(summary='tool access denied', designs=[], selection=[],
                    tree=dict(roots=[], nodes=[]), data_characteristics=[], history_selection=[]))

    def test_direct_console_start_uses_local_catalog_without_multiplier_quality_gate(self):
        from tests import test_console_start as console_fixtures
        from wqb import console_start as worker
        host = console_fixtures.PreplannedConsoleStartTests()
        host.setUp()
        self.addCleanup(host.doCleanups)
        self.fixture = host.case
        # This mode consumes current machine resources, never archived semantic jobs.
        operators = {row['operator']: row for resource in host.case.resources for row in resource['operator_rows']}
        (host.paths.knowledge_root / 'machine/operator_ledger.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in operators.values()), encoding='utf-8')
        config = {**self.config, **host.config,
            'research_policy': dict(preplanned_tree_version=1, execution_package_version=1,
                retrieval_design_version=1, direct_knowledge_version=1)}
        (host.paths.workflow_root / 'configs/workflow_local.json').write_text(json.dumps(config), encoding='utf-8')
        request = worker.register_start(host.paths, host.form, 'direct-console-job')
        request = dict(request, multiplier_preparation={})
        worker._write_request(host.paths.runs_root, request)

        def factory(directory, _config, check):
            """Input: task/config/Stop callback. Output: offline fake model using real local retrieval tools."""
            check()
            self.assertEqual(_config['direct_knowledge_version'], 1)
            return lambda brief: self.model(directory, brief)

        with patch('wqb.retrieval_research_planning.create_retrieval_model_runner', side_effect=factory), \
                patch('wqb.multiplier_supervision.prepare_multiplier_fields_supervised',
                    side_effect=AssertionError('legacy quality gate or capture reached')):
            prepared = worker._prepare_multiplier_start(host.paths, request)
            self.assertEqual(prepared['multiplier_preparation']['field_source'], 'knowledge')
            result = worker.execute_start(host.paths, host.form, request['request_id'])
        self.assertTrue(result['passed'], result)
        self.assertEqual(len(self.calls), 1)

    def setUp(self):
        """Input: TestCase. Output: isolated source-backed composer fixture, never platform resources."""
        self.fixture = fixtures.PreplannedStartTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        from wqb.config import DEFAULT_CONFIG
        self.config = {**DEFAULT_CONFIG, **self.fixture.config,
            'resource_admission_policy': 'knowledge_catalog_v1',
            'research_policy': dict(preplanned_tree_version=1, execution_package_version=1,
                                    retrieval_design_version=1)}
        self.calls = []

    def model(self, directory, brief):
        """Input: owning task/compact brief. Output: fictional answer after actual indexed query and local validation."""
        from wqb.retrieval_research_planning import query_design_task
        self.calls.append(str(directory))
        number = int(directory.name.rsplit('-', 1)[1])
        resource = self.fixture.resources[number]
        field = resource['field_rows'][0]
        pairs = [[field['dataset_id'], field['field_id']]]
        page = query_design_task(directory, 'fields', {'identities': pairs})
        self.assertEqual(page['items'][0]['field_id'], field['field_id'])
        selected = [dict(dataset_id=field['dataset_id'], field_id=field['field_id'])]
        context = query_design_task(directory, 'validate', {'selection': selected})
        self.assertTrue(context['valid'], context)
        answer = self.fixture.answer_for_brief(dict(data_traits=resource['field_rows'], sources=resource['source_index']))
        answer['selection'] = selected
        answer['history_selection'] = []
        if field['field_type'] == 'VECTOR':
            for design in answer['designs']:
                design['design_version'] = 3
                design['field_roles'][0]['field_type'] = 'VECTOR'
                for feature in [design['feature_plan'], design['experiment_plan']['baseline'],
                                *[item['feature'] for item in design['experiment_plan']['treatments']]]:
                    feature['input']['reduction'] = dict(operator='vec_avg', parameters={})
        answer['data_characteristics'] = [dict(dataset_id=row['dataset_id'], field_id=row['field_id'],
            known_trait_keys=list(row['known_facts']), unknown_trait_keys=row['unknown_trait_keys'],
            hypotheses=[], suggested_repair_rule_ids=[]) for row in context['annotation_context']['fields']]
        return answer

    def test_query_design_and_freeze_never_call_legacy_model_or_scan_shortlist(self):
        from wqb import preplanned_start as start
        with patch.object(start, '_local_resources', side_effect=AssertionError('old shortlist used')):
            result = start.prepare_preplanned_start(self.fixture.paths, self.fixture.option,
                self.fixture.authority, self.config, model_runner=lambda _: self.fail('second model call'),
                retrieval_model_runner=self.model)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(self.calls), 1)
        lane = self.fixture.paths.run_root / result['group']['lanes'][0]['run_id']
        manifest = json.loads((lane / 'run_manifest.json').read_text())
        self.assertEqual(manifest['start_snapshot']['research_policy']['retrieval_design_version'], 1)
        self.assertIn('initial_design_origin', manifest['start_snapshot'])
        self.assertTrue((lane / 'runtime/experiment_tree.json').exists())
        again = start.prepare_preplanned_start(self.fixture.paths, self.fixture.option,
            self.fixture.authority, self.config, model_runner=lambda _: self.fail('legacy model replay'),
            retrieval_model_runner=lambda *_: self.fail('retrieval model replay'))
        self.assertEqual(again['status'], 'completed', again)
        self.assertEqual(result['group']['group_id'], again['group']['group_id'])

    def test_invalid_draft_is_corrected_inside_the_same_design_task(self):
        """Input: an invalid proposal followed by a corrected one. Output: one model task, offline diagnostic, valid freeze."""
        from wqb import preplanned_start as start
        from wqb.retrieval_research_planning import query_design_task
        attempts = []

        def model(directory, brief):
            """Input: saved task/brief. Output: corrected tree without dispatching another model."""
            field = self.fixture.resources[0]['field_rows'][0]
            invalid = query_design_task(directory, 'validate', dict(selection=[dict(
                dataset_id=field['dataset_id'], field_id=field['field_id'])], design={}))
            self.assertFalse(invalid['valid'])
            self.assertTrue(invalid['diagnostics'])
            attempts.append(invalid)
            return self.model(directory, brief)

        result = start.prepare_preplanned_start(self.fixture.paths, self.fixture.option,
            self.fixture.authority, self.config, model_runner=lambda _: self.fail('second model call'),
            retrieval_model_runner=model)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(self.calls), 1)

    def test_console_original_start_binds_retrieval_group_without_legacy_model(self):
        from tests import test_console_start as console_fixtures
        from wqb import console_start as worker
        host = console_fixtures.PreplannedConsoleStartTests()
        host.setUp()
        self.addCleanup(host.doCleanups)
        self.fixture = host.case
        config = {**self.config, **host.config,
            'research_policy': dict(preplanned_tree_version=1, execution_package_version=1,
                                    retrieval_design_version=1)}
        (host.paths.workflow_root / 'configs/workflow_local.json').write_text(json.dumps(config), encoding='utf-8')
        request = worker.register_start(host.paths, host.form, 'retrieval-console-job')

        def factory(directory, _config, check):
            """Input: task owner/clean config/Stop callback. Output: fake model using actual local query/compile tools."""
            check()
            return lambda brief: self.model(directory, brief)

        with patch('wqb.retrieval_research_planning.create_retrieval_model_runner', side_effect=factory), \
                patch('wqb.initial_model_worker.create_initial_model_runner',
                      side_effect=AssertionError('legacy model path reached')):
            result = worker.execute_start(host.paths, host.form, request['request_id'])
        self.assertTrue(result['passed'], result)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result['request_id'], request['request_id'])
        self.assertTrue(result.get('group_dir'))
        self.assertEqual(result['multiplier_preparation']['status'], 'completed')
        self.assertEqual(result['multiplier_preparation']['stage'], 'ready')

    def test_repeated_console_start_preserves_unresolved_model_owner_even_after_stop(self):
        """Input: unknown model outcome and another Start. Output: original blocker, not a fresh as_of/model task."""
        from tests.test_console_start import PreplannedConsoleStartTests
        from wqb import console_start as worker
        host = PreplannedConsoleStartTests()
        host.setUp()
        self.addCleanup(host.doCleanups)
        config = {**self.config, **host.config, 'research_policy': dict(
            preplanned_tree_version=1, execution_package_version=1, retrieval_design_version=1)}
        config.get('selected_scope', {}).pop('as_of', None)
        (host.paths.workflow_root / 'configs/workflow_local.json').write_text(json.dumps(config), encoding='utf-8')
        dispatched = []

        def factory(directory, *_):
            """Input: original task owner. Output: one fake model with uncertain outcome."""
            def lost(_):
                """Input: compact brief. Output: never; preserve uncertain model accounting."""
                dispatched.append(str(directory))
                raise TimeoutError('unknown model outcome')
            return lost

        request = worker.register_start(host.paths, host.form, 'original')
        with patch('wqb.retrieval_research_planning.create_retrieval_model_runner', side_effect=factory):
            result = worker.execute_start(host.paths, host.form, request['request_id'])
            self.assertEqual(result['status'], 'blocked', result)
            for stop in (False, True):
                if stop:
                    worker.cancel_start(host.paths.runs_root)
                with self.assertRaisesRegex(ValueError, 'unresolved retrieval'):
                    worker.register_start(host.paths, host.form, 'repeated')
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(worker.read_start_request(host.paths.runs_root)['request_id'], request['request_id'])

    def test_independent_retrieved_evidence_is_retained_through_freeze(self):
        from wqb import preplanned_start as start
        knowledge = self.fixture.paths.knowledge_root
        path = 'raw/user/independent_hypothesis.md'
        text = 'An independent competing economic explanation for a fictional pulse.\n'
        target = knowledge / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8', newline='\n')
        source = dict(path=path, content_hash=hashlib.sha256(text.encode()).hexdigest(),
            captured_at='2026-10-14T00:00:00Z', source_type='user_research_note', source_family='raw/user')
        self.fixture.index[path] = source
        (knowledge / 'machine/source_index.jsonl').write_text(''.join(
            json.dumps(row) + '\n' for row in self.fixture.index.values()), encoding='utf-8')

        def model(directory, brief):
            """Input: task/brief. Output: proposal referencing actual independently queried evidence."""
            from wqb.retrieval_research_planning import query_design_task
            queried = query_design_task(directory, 'source', {'path': path})
            self.assertIn('independent', queried['items'][0]['excerpt'])
            answer = self.model(directory, brief)
            for design in answer['designs']:
                design['evidence_refs'].append(dict(source_path=path, sha256=source['content_hash'],
                    capture_date=source['captured_at'][:10], kind='hypothesis', experiment_refs=[]))
            return answer

        result = start.prepare_preplanned_start(self.fixture.paths, self.fixture.option,
            self.fixture.authority, self.config, model_runner=lambda _: self.fail('second model call'),
            retrieval_model_runner=model)
        self.assertEqual(result['status'], 'completed', result)
        lane = self.fixture.paths.run_root / result['group']['lanes'][0]['run_id']
        task = json.loads((lane / 'runtime/initial_research_planning/task.json').read_text())
        self.assertEqual(task['brief']['source_texts'][path], text)

    def test_two_vector_lanes_freeze_explicit_reductions_without_matrix_seeds(self):
        from wqb import preplanned_start as start
        self.fixture.add_lane(1)
        self.config['parallel_workflows'] = 2
        for resource in self.fixture.resources:
            field = resource['field_rows'][0]
            path = field['source_paths'][0]
            payload = json.loads(resource['source_texts'][path])
            field['field_type'] = payload['fields'][0]['field']['type'] = 'VECTOR'
            operator = dict(operator='vec_avg', definition=dict(description='Taking mean of the vector field x',
                input_types=['VECTOR'], output_type='MATRIX',
                parameters=[dict(name='x', type='VECTOR', required=True)]))
            payload['operators'].append(deepcopy(operator))
            text = json.dumps(payload)
            digest = hashlib.sha256(text.encode()).hexdigest()
            source = resource['source_index'][path]
            source['content_hash'] = digest
            resource['source_texts'][path] = text
            (self.fixture.paths.knowledge_root / path).write_text(text, encoding='utf-8')
            for old in resource['operator_rows']:
                for ref in old['definition']['evidence_refs']:
                    if ref['source_path'] == path:
                        ref['sha256'] = digest
            operator['definition']['evidence_refs'] = [dict(source_path=path, sha256=digest,
                capture_date=source['captured_at'][:10], kind='documented', experiment_refs=[])]
            resource['operator_rows'].append(operator)
            self.fixture.index[path] = source
        machine = self.fixture.paths.knowledge_root / 'machine'
        for name, rows in [('data_ledger', [r['field_rows'][0] for r in self.fixture.resources]),
                           ('source_index', self.fixture.index.values())]:
            (machine / (name + '.jsonl')).write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        result = start.prepare_preplanned_start(self.fixture.paths, self.fixture.option,
            self.fixture.authority, self.config, model_runner=lambda _: self.fail('second model call'),
            retrieval_model_runner=self.model)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(self.calls), 2)
        for lane in result['group']['lanes']:
            manifest = json.loads((self.fixture.paths.run_root / lane['run_id'] / 'run_manifest.json').read_text())
            self.assertEqual(manifest['start_snapshot']['data_ledger_rows'][0]['field_type'], 'VECTOR')

    def test_selected_historical_context_is_frozen_without_becoming_causal_proof(self):
        from tests.test_mechanism_evidence import evidence_fixture
        from wqb.mechanism_evidence import build_mechanism_evidence
        from wqb.retrieval_research_planning import query_design_task
        from wqb import preplanned_start as start
        records, experiments = evidence_fixture()
        scope = {key: self.fixture.scope[key] for key in ('instrument_type', 'region', 'delay', 'universe')}
        for arm in experiments[0]['arms']:
            arm['scope'] = deepcopy(scope)
        for row in records[0]['backtest']:
            row['scope'] = deepcopy(scope)
        view = build_mechanism_evidence(records, experiments)
        (self.fixture.paths.knowledge_root / 'machine/mechanism_evidence.json').write_text(
            json.dumps(view), encoding='utf-8')
        seen = []

        def model(directory, brief):
            """Input: task/brief. Output: proposal retaining a real queried inconclusive observation."""
            page = query_design_task(directory, 'experience', {})
            self.assertEqual(page['total'], 1)
            group = page['items'][0]
            seen.append(group['group_id'])
            answer = self.model(directory, brief)
            answer['history_selection'] = [dict(group_id=group['group_id'],
                view_sha256=group['evidence_view_ref']['sha256'])]
            return answer

        result = start.prepare_preplanned_start(self.fixture.paths, self.fixture.option,
            self.fixture.authority, self.config, model_runner=lambda _: self.fail('second model call'),
            retrieval_model_runner=model)
        self.assertEqual(result['status'], 'completed', result)
        run = self.fixture.paths.run_root / result['group']['lanes'][0]['run_id']
        task = json.loads((run / 'runtime/initial_research_planning/task.json').read_text())
        context = task['brief']['evidence_pack']['mechanism_context'][0]
        self.assertEqual(context['group_id'], seen[0])
        self.assertEqual(context['label'], 'inconclusive')
        material = run / context['supporting_ref']['path']
        self.assertEqual(hashlib.sha256(material.read_bytes()).hexdigest(), context['supporting_ref']['sha256'])

    def test_actual_tool_queries_cannot_bypass_task_wide_limits(self):
        from wqb import preplanned_start as start
        from wqb.retrieval_research_planning import query_design_task
        self.config['retrieval_max_queries'] = 1

        def model(directory, brief):
            """Input: task/brief. Output: never; second real tool request must exhaust this task's allowance."""
            query_design_task(directory, 'fields', {'limit': 1})
            with self.assertRaisesRegex(ValueError, 'query_budget_exhausted'):
                query_design_task(directory, 'fields', {'limit': 1})
            raise RuntimeError('bounded trial completed')

        result = start.prepare_preplanned_start(self.fixture.paths, self.fixture.option,
            self.fixture.authority, self.config, model_runner=lambda _: self.fail('second model call'),
            retrieval_model_runner=model)
        self.assertIn('bounded trial completed', result['reason'])

    def test_catalog_change_during_final_compilation_never_completes_task(self):
        """Input: publication during final compilation, no selected history. Output: blocked task, never frozen authority."""
        from wqb import preplanned_start as start, initial_research_planning as initial
        from wqb.retrieval_research_planning import read_design_task
        original = initial._compiled_graph
        path = self.fixture.paths.knowledge_root / 'machine/template_library.jsonl'
        path.write_text('', encoding='utf-8')

        def publish(*args, **kwargs):
            """Input: compiler arguments. Output: compiled graph after a conflicting local publication."""
            result = original(*args, **kwargs)
            path.write_text(path.read_text(encoding='utf-8') + '\n', encoding='utf-8')
            return result

        with patch.object(initial, '_compiled_graph', side_effect=publish):
            result = start.prepare_preplanned_start(self.fixture.paths, self.fixture.option,
                self.fixture.authority, self.config, model_runner=lambda _: self.fail('second model call'),
                retrieval_model_runner=self.model)
        self.assertNotEqual(result['status'], 'completed', result)
        self.assertEqual(len(self.calls), 1)
        task = read_design_task(__import__('pathlib').Path(self.calls[0]))
        self.assertEqual(task['status'], 'blocked', task.get('reason'))
