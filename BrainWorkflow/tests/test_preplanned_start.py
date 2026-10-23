"""Isolated, source-backed Start composition without platform or model services."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tests.test_hypothesis_design import compiler_fixture
from tests import test_initial_research_planning as planning_tests
from tests.test_workflow_stage_adapters import valid_option
from wqb.benchmark_rules import (benchmark_rules_path_for_knowledge,
    default_benchmark_rules, write_benchmark_rules_jsonl)
from wqb.semantic_compilation import prepare_design_job
from wqb.semantic_contracts import SemanticPolicy
from wqb import preplanned_start as start


class PreplannedStartTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: temporary raw, machine ledgers and compiler materials."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.paths = SimpleNamespace(knowledge_root=self.root / 'knowledge', run_root=self.root / 'runs',
                                     project_root=self.root, workflow_root=self.root)
        self.paths.knowledge_root.mkdir()
        self.option = valid_option(option_id='offline-option')
        self.authority = dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=3)
        self.resources = []
        self.index = {}
        self.jobs = []
        self.add_lane(0)
        self.option['candidate_scope'] = f"{self.scope['region']} D{self.scope['delay']} {self.scope['universe']}"
        self.config = dict(selected_scope=deepcopy(self.scope),
            measurement_period=dict(start='2020-01-01', end='2025-01-01'), parallel_workflows=1)
        fixture = planning_tests.InitialResearchPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.answer = deepcopy(fixture.answer)
        self.runner = planning_tests.FakeRunner(side_effect=self.answer_for_brief)
        write_benchmark_rules_jsonl(benchmark_rules_path_for_knowledge(self.paths.knowledge_root),
                                   default_benchmark_rules())

    def add_lane(self, number, *, prepare_job=True, omit_timing=False):
        """Input: lane number int. Output: None; write distinct fictional sourced field selection."""
        _, resource, self.scope = compiler_fixture(treatment=True)
        field = resource['field_rows'][0]
        old = field['source_paths'][0]
        path = f'raw/platform/fictional/compiler-{number}.json'
        payload = json.loads(resource['source_texts'].pop(old))
        row = payload['fields'][0]
        row['field']['id'] = field['field_id'] = f'pulse_{number}'
        row['field']['coverage'] = field['coverage'] = 0.8
        row['data_set']['id'] = field['dataset_id'] = f'fictional_{number}'
        if omit_timing:
            field.pop('available_at')
            row['field'].pop('available_at')
        field.update(source_paths=[path], source_updated_at='2026-10-14',
                     source_quality='platform_raw_capture', coverage_status='measured_raw')
        text = json.dumps(payload)
        digest = hashlib.sha256(text.encode()).hexdigest()
        source = resource['source_index'].pop(old)
        source.update(path=path, content_hash=digest)
        resource['source_index'][path] = source
        resource['source_texts'][path] = text
        for operator in resource['operator_rows']:
            operator['definition']['evidence_refs'][0].update(source_path=path, sha256=digest)
        if not prepare_job:
            from tests.test_resource_evidence import page_operator_fixture
            operator, source_index, source_texts = page_operator_fixture()
            resource['operator_rows'] = [operator]
            resource['source_index'].update(source_index)
            resource['source_texts'].update(source_texts)
        resource['evidence_pack'].update(source_index=deepcopy(resource['source_index']),
            source_texts=deepcopy(resource['source_texts']))
        for name, body in resource['source_texts'].items():
            target = self.paths.knowledge_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding='utf-8', newline='\n')
        self.index.update(resource['source_index'])
        self.resources.append(resource)
        machine = self.paths.knowledge_root / 'machine'
        machine.mkdir(exist_ok=True)
        for name, rows in [('source_index', self.index.values()),
                           ('data_ledger', [r for item in self.resources for r in item['field_rows']])]:
            (machine / (name + '.jsonl')).write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        if prepare_job:
            self.jobs.append(prepare_design_job(self.paths.knowledge_root, resource['evidence_pack'],
                                               SemanticPolicy(), resource))
        else:
            (machine / 'operator_ledger.jsonl').write_text(''.join(
                json.dumps(r) + '\n' for r in self.resources[0]['operator_rows']), encoding='utf-8')

    def prepare(self):
        """Input: fixture state. Output: real composer dict with counted offline model callback."""
        return start.prepare_preplanned_start(self.paths, self.option, self.authority,
                                             self.config, model_runner=self.runner)

    def answer_for_brief(self, brief):
        """Input: certified brief dict. Output: fictional answer citing the actual lane's supplied source."""
        answer = deepcopy(self.answer)
        path = brief['data_traits'][0]['source_paths'][0]
        source = brief['sources'][path]
        for design in answer['designs']:
            design['trigger_id'] = path
            design['evidence_refs'] = [dict(source_path=path, sha256=source['content_hash'],
                capture_date=source['captured_at'][:10], kind='hypothesis', experiment_refs=[])]
        return answer

    def test_real_composition_and_restart_for_n_1_2_4(self):
        for number in range(1, 4):
            self.add_lane(number)
        for count in (1, 2, 4):
            with self.subTest(count=count):
                self.config['parallel_workflows'] = count
                before = self.runner.call_count
                result = self.prepare()
                self.assertEqual(result['status'], 'completed', result)
                self.assertEqual(self.runner.call_count - before, count)
                self.assertEqual(len(result['group']['lanes']), count)
                self.assertEqual(result['group']['desired_state'], 'paused')
                calls = self.runner.call_count
                again = self.prepare()
                self.assertEqual(again['status'], 'completed', again)
                self.assertEqual(again['group']['group_id'], result['group']['group_id'])
                self.assertEqual(self.runner.call_count, calls)
                selections = []
                for lane in result['group']['lanes']:
                    run = self.paths.run_root / lane['run_id']
                    self.assertTrue((run / 'run_state.json').exists())
                    from wqb.initial_research_planning import TASK_PATH
                    from wqb.research_tree import _load
                    task = json.loads((run / TASK_PATH).read_text())
                    self.assertEqual(task['status'], 'completed')
                    _, snapshot = _load(run)
                    selections.append(tuple(sorted((row['dataset_id'], row['field_id'])
                                                   for row in snapshot['data_ledger_rows'])))
                    self.assertEqual(snapshot['measurement_period'], self.config['measurement_period'])
                    self.assertEqual(snapshot['research_policy']['plan_depth'], 2)
                    self.assertEqual(snapshot['research_policy']['initial_hypotheses'], 4)
                    self.assertFalse((run / 'runtime/control.json').exists())
                    self.assertFalse((run / 'runtime_control.json').exists())
                self.assertEqual(len(set(selections)), count)
                self.assertFalse((self.paths.run_root / 'active_research_group.json').exists())

    def test_verified_project_repair_policy_reaches_seed_selected_parent(self):
        from wqb.repair_search import prepare_persisted_search
        from wqb.seed_policy import select_seeds
        from wqb.benchmark_rules import load_run_benchmark_rules
        from wqb.cli import simulation_identity_hash
        traits = start._repair_policy(self.resources[0])['traits']
        refs = deepcopy(traits['matrix_observation']['evidence_refs'])
        rule = dict(rule_id='project-decay', edit='decay', effect='smoothing', priority=0,
            target_metric='turnover', target_direction='decrease', grid=[4, 8, 16],
            requires=dict(matrix_observation=True), evidence_refs=refs)
        self.config['repair_search_policy'] = dict(schema_version=1, rules=[rule], traits=traits)
        result = self.prepare()
        self.assertEqual(result['status'], 'completed', result)
        run = self.paths.run_root / result['group']['lanes'][0]['run_id']
        manifest = json.loads((run / 'run_manifest.json').read_text())
        receipt = manifest['start_snapshot']['exploration_context']['receipts'][0]['compiled']
        arm = receipt['experiment']['arms'][0]
        expression, settings = arm['binding']['bound_expression'], arm['settings']
        identity = simulation_identity_hash(expression, settings)
        parent = dict(status='CHECKED', alpha_id='fixture-seed', expression_hash=identity,
            simulation_identity=identity, expression=expression, settings=settings, lane_id=run.name,
            measurement_scope={key: settings[key] for key in ('region', 'delay', 'universe')},
            test_period=dict(start='2020-01-01', end='2025-01-01'), hard_pass=False,
            failed=['LOW_FITNESS'], pending=[],
            metrics=dict(sharpe=1.5, fitness=.8, returns=.1, turnover=.3))
        selected = select_seeds([parent], {}, benchmark_rules=load_run_benchmark_rules(run))
        self.assertTrue(selected['selected'], selected)
        plan = prepare_persisted_search(run, parent, [], 8)
        self.assertEqual(plan['planner_kind'], 'deterministic')
        self.assertEqual(len(plan['variants']), 1)
        self.assertEqual(plan['variants'][0]['expression'], expression)
        self.assertNotEqual(plan['variants'][0]['settings']['decay'], settings['decay'])

    def test_repair_policy_cannot_invent_traits_or_use_stale_source(self):
        traits = start._repair_policy(self.resources[0])['traits']
        for change in ('unknown_trait', 'stale_ref'):
            proposed = dict(schema_version=1, rules=[], traits=deepcopy(traits))
            if change == 'unknown_trait':
                proposed['traits']['monthly_sampling'] = dict(basis='source', value=True,
                    evidence_refs=deepcopy(traits['matrix_observation']['evidence_refs']))
            else:
                proposed['traits']['matrix_observation']['evidence_refs'][0]['sha256'] = '0'*64
            with self.subTest(change=change), self.assertRaises(ValueError):
                start._repair_policy(self.resources[0], proposed)

    def test_insufficient_resources_returns_smaller_group_with_reason(self):
        self.config.pop('parallel_workflows')
        result = self.prepare()
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['requested_lanes'], 2)
        self.assertEqual(result['prepared_lanes'], 1)
        self.assertTrue(result['warnings'])

    def test_unknown_model_outcome_does_not_create_replacement_group_or_replay(self):
        self.runner = planning_tests.FakeRunner(side_effect=TimeoutError('fictional unknown'))
        first = self.prepare()
        second = self.prepare()
        self.assertEqual(first['status'], 'blocked', first)
        self.assertEqual(second['status'], 'blocked', second)
        self.assertEqual(first['group']['group_id'], second['group']['group_id'])
        self.assertEqual(self.runner.call_count, 1)
        self.assertIn('model_outcome_unknown', second['reason'])

    def test_stop_during_model_prevents_completion_and_later_model_calls(self):
        from wqb.research_group import read_group, stop_group
        self.add_lane(1)
        self.config['parallel_workflows'] = 2
        def stop(brief):
            """Input: brief dict. Output: fake answer after durable group Stop."""
            group_path = next((self.paths.run_root / 'research_groups').iterdir())
            group = read_group(group_path)
            stop_group(group_path, group['request_revision'])
            return deepcopy(self.answer)
        self.runner = planning_tests.FakeRunner(side_effect=stop)
        self.assertEqual(self.prepare()['status'], 'blocked')
        self.assertEqual(self.prepare()['status'], 'blocked')
        self.assertEqual(self.runner.call_count, 1)

    def test_invalid_n_and_missing_period_never_call_model(self):
        for value in (True, 0, -1, '2', 33):
            self.config['parallel_workflows'] = value
            self.assertEqual(self.prepare()['status'], 'blocked')
        self.config['parallel_workflows'] = 1
        self.config.pop('measurement_period')
        self.assertEqual(self.prepare()['status'], 'blocked')
        self.runner.assert_not_called()

    def test_corrupt_raw_and_missing_timing_fail_before_model(self):
        source = self.paths.knowledge_root / self.resources[0]['field_rows'][0]['source_paths'][0]
        source.write_text('{}', encoding='utf-8')
        result = self.prepare()
        self.assertEqual(result['status'], 'blocked', result)
        self.assertTrue(result['missing_facts'])
        self.runner.assert_not_called()

    def test_completed_group_has_executable_tree_and_frozen_repair_policy(self):
        from wqb.research_tree import _load
        from wqb.repair_search import _frozen_policy
        result = self.prepare()
        self.assertEqual(result['status'], 'completed', result)
        run = self.paths.run_root / result['group']['lanes'][0]['run_id']
        tree, snapshot = _load(run)
        self.assertEqual(tree['status'], 'frozen')
        self.assertEqual(tree['manifest_sha256'], hashlib.sha256(
            (run / 'run_manifest.json').read_bytes()).hexdigest())
        self.assertEqual(snapshot['tree_comparison_policy'], dict(schema_version=1,
            edit='feature', target_metric='fitness', target_direction='increase', turnover_max=.4))
        self.assertEqual(snapshot['compatible_template_ids'],
                         sorted(row['template_id'] for row in snapshot['template_rows']))
        policy, _ = _frozen_policy(run)
        self.assertEqual(policy, snapshot['repair_search_policy'])
        self.assertEqual(policy['rules'], [])
        self.assertEqual(policy['traits']['matrix_observation']['basis'], 'source')
        for ref in policy['traits']['matrix_observation']['evidence_refs']:
            row = self.index[ref['source_path']]
            self.assertEqual(ref['sha256'], row['content_hash'])
            self.assertEqual(ref['capture_date'], row['captured_at'][:10])
            self.assertEqual(ref['kind'], 'documented')
        self.assertTrue(snapshot['repair_search_diagnostics'])

    def test_callback_is_bound_to_persisted_task_and_certificate(self):
        def runner(brief):
            """Input: worker brief dict. Output: fake plan after source-bound transport assertions."""
            context = brief['worker_context']
            run = Path(context['run_dir'])
            task = json.loads((run / context['task_path']).read_text())
            certificate = json.loads((run / context['certificate_path']).read_text())
            self.assertEqual(task['status'], 'running')
            self.assertEqual({key: value for key, value in brief.items() if key != 'worker_context'},
                             task['brief'])
            self.assertEqual(certificate['content_sha256'], brief['resource_certificate_sha256'])
            self.assertEqual(certificate['owning_run']['run_id'], run.name)
            snapshot = json.loads((run / context['manifest_path']).read_text())['start_snapshot']
            self.assertIn('repair_search_policy', snapshot)
            self.assertIn('tree_comparison_policy', snapshot)
            from wqb.research_group import group_for_run
            group = group_for_run(run)
            self.assertEqual(group['desired_state'], 'paused')
            return deepcopy(self.answer)
        self.runner = planning_tests.FakeRunner(side_effect=runner)
        self.assertEqual(self.prepare()['status'], 'completed')

    def test_no_artificial_raw_repair_rules_still_prepares_and_exhausts_visibly(self):
        """Input: ordinary sourced fixture. Output: no Scout blocker and explicit finite Repair exhaustion."""
        from wqb.repair_search import _frozen_policy, prepare_search
        from wqb.research_tree import _load
        for text in self.resources[0]['source_texts'].values():
            self.assertNotIn('repair_search_policy', text)
        result = self.prepare()
        self.assertEqual(result['status'], 'completed', result)
        run = self.paths.run_root / result['group']['lanes'][0]['run_id']
        policy, _ = _frozen_policy(run)
        tree, snapshot = _load(run)
        expected = tree['tree']['nodes'][0]['expected']['baseline']
        parent = dict(alpha_id='fictional-measured', expression=expected['expression'],
            settings=expected['settings'], expression_hash=expected['simulation_identity'])
        repair = prepare_search(run, parent, [], 1, policy)
        self.assertEqual(repair['status'], 'exhausted', repair)
        self.assertEqual(repair['variants'], [])
        self.assertEqual(repair['stop_reason'], 'search_space_exhausted')
        self.assertTrue(snapshot['repair_search_diagnostics'])
        self.assertNotIn('update_frequency', policy['traits'])
        self.assertNotIn('nuisance_exposure', policy['traits'])

    def test_canonical_machine_assembly_without_semantic_jobs_or_global_writes(self):
        """Input: canonical machine/raw fixtures only. Output: two real frozen trees without vault writes."""
        self.paths = SimpleNamespace(knowledge_root=self.root / 'canonical/knowledge',
            run_root=self.root / 'canonical/runs', project_root=self.root / 'canonical',
            workflow_root=self.root / 'canonical')
        self.paths.knowledge_root.mkdir(parents=True)
        self.resources, self.index, self.jobs = [], {}, []
        for number in range(2):
            self.add_lane(number, prepare_job=False)
        write_benchmark_rules_jsonl(benchmark_rules_path_for_knowledge(self.paths.knowledge_root),
                                   default_benchmark_rules())
        self.config['parallel_workflows'] = 2
        self.config.update(decay=4, neutralization='NONE', truncation=.08,
            pasteurization='ON', unit_handling='VERIFY', nan_handling='OFF', language='FASTEXPR')
        before = {p.relative_to(self.paths.knowledge_root): p.read_bytes()
                  for p in self.paths.knowledge_root.rglob('*') if p.is_file()}
        self.assertFalse((self.paths.knowledge_root / 'machine/semantic_jobs').exists())
        result = self.prepare()
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(result['group']['lanes']), 2)
        self.assertEqual(self.runner.call_count, 2)
        from wqb.research_tree import _load
        selections = []
        for lane in result['group']['lanes']:
            _, snapshot = _load(self.paths.run_root / lane['run_id'])
            selections.append(tuple((r['dataset_id'], r['field_id']) for r in snapshot['data_ledger_rows']))
            self.assertEqual(snapshot['selected_scope'], self.scope)
        self.assertEqual(len(set(selections)), 2)
        self.assertEqual(before, {p.relative_to(self.paths.knowledge_root): p.read_bytes()
            for p in self.paths.knowledge_root.rglob('*') if p.is_file()})

    def test_second_lane_unknown_keeps_all_lanes_unstarted_without_replay(self):
        """Input: two sourced lanes/unknown second model. Output: paused group with no executable lane state."""
        from wqb.initial_research_planning import TASK_PATH
        self.add_lane(1)
        self.config['parallel_workflows'] = 2
        def runner(brief):
            """Input: source-bound brief dict. Output: first plan; second transport outcome unknown."""
            if self.runner.call_count == 2:
                raise TimeoutError('fictional second lane uncertainty')
            return deepcopy(self.answer)
        self.runner = planning_tests.FakeRunner(side_effect=runner)
        result = self.prepare()
        self.assertEqual(result['status'], 'blocked', result)
        self.assertEqual(result['group']['desired_state'], 'paused')
        statuses = []
        for lane in result['group']['lanes']:
            run = self.paths.run_root / lane['run_id']
            statuses.append(json.loads((run / TASK_PATH).read_text())['status'])
            self.assertFalse((run / 'run_state.json').exists())
            self.assertFalse((run / 'runtime/control.json').exists())
            self.assertFalse((run / 'runtime_control.json').exists())
        self.assertEqual(statuses, ['completed', 'unknown'])
        self.assertEqual(self.prepare()['status'], 'blocked')
        self.assertEqual(self.runner.call_count, 2)
        self.assertFalse((self.paths.run_root / 'active_research_group.json').exists())

    def test_scope_setting_conflict_blocks_before_model(self):
        """Input: conflicting flat/scope configuration. Output: readiness blocker before model dispatch."""
        self.config['region'] = 'DIFFERENT'
        result = self.prepare()
        self.assertEqual(result['status'], 'blocked', result)
        self.assertIn('conflicts with selected_scope', result['reason'])
        self.runner.assert_not_called()

    def test_real_initial_model_checkpoint_then_paused_group_initialization(self):
        """Input: real adapters with offline process fakes. Output: initialized paused group and valid trees."""
        from wqb import ai_checkpoints, codex_ai_worker
        from wqb.initial_model_worker import create_initial_model_runner
        from wqb.initial_research_planning import TASK_PATH
        from wqb.research_group_driver import initialize_group_runtime
        from wqb.research_tree import _load
        from wqb.runtime_control import read_runtime_control
        self.add_lane(1)
        self.config.update(parallel_workflows=2, ai_executor='codex')
        model_calls = []

        def runner(supplied):
            """Input: transport brief dict. Output: real adapter answer after validating/removing context."""
            brief = deepcopy(supplied)
            context = brief.pop('worker_context')
            run = Path(context['run_dir'])
            self.assertEqual(context['task_path'], TASK_PATH)
            self.assertEqual(context['manifest_path'], 'run_manifest.json')
            self.assertEqual(Path(context['knowledge_root']), self.paths.knowledge_root)
            task = json.loads((run / TASK_PATH).read_text())
            self.assertEqual(brief, task['brief'])
            self.model_answer = self.answer_for_brief(brief)
            return create_initial_model_runner(run, self.config)(brief)

        def fake_model(argv, **kwargs):
            """Input: Codex argv/options. Output: offline CompletedProcess with strict structured answer."""
            self.assertIn('read-only', argv)
            self.assertIn('model_reasoning_effort=medium', argv)
            model_calls.append(argv)
            Path(argv[argv.index('--output-last-message') + 1]).write_text(
                json.dumps(self.model_answer), encoding='utf-8')
            return subprocess.CompletedProcess(argv, 0, '', '')

        def fake_process(argv, **kwargs):
            """Input: checkpoint worker argv/options. Output: fake process running the real worker locally."""
            process = Mock(returncode=0)
            def communicate(timeout=None):
                """Input: optional timeout number. Output: stdout/stderr pair; no real subprocess."""
                codex_ai_worker.run_worker(Path(argv[-2]), Path(argv[-1]))
                return '', ''
            process.communicate.side_effect = communicate
            return process

        self.runner = planning_tests.FakeRunner(side_effect=runner)
        with patch('wqb.ai_checkpoints.subprocess.Popen', side_effect=fake_process), patch(
                'wqb.codex_ai_worker.shutil.which', return_value='fake-codex'), patch(
                'wqb.codex_ai_worker.subprocess.run', side_effect=fake_model):
            result = self.prepare()
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(model_calls), 2)
        self.assertEqual(self.runner.call_count, 2)
        for lane in result['group']['lanes']:
            run = self.paths.run_root / lane['run_id']
            rows = ai_checkpoints.load_ai_checkpoints(run / 'stages/ai')
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['checkpoint_type'], 'initial_research_plan')
            self.assertEqual(rows[0]['status'], 'completed')
            _load(run)
        group = initialize_group_runtime(self.paths, result['group'])
        self.assertEqual(group['desired_state'], 'paused')
        for lane in group['lanes']:
            run = self.paths.run_root / lane['run_id']
            self.assertEqual(read_runtime_control(run)['desired_state'], 'paused')
            self.assertFalse((run / 'runtime/group_worker.json').exists())
            _load(run)
        again = self.prepare()
        self.assertEqual(again['status'], 'completed', again)
        self.assertEqual(self.runner.call_count, 2)
        self.assertEqual(len(model_calls), 2)

    def test_missing_raw_timing_is_not_inferred_from_capture_date_or_type(self):
        """Input: typed measured field lacking availability facts. Output: pre-model blocker, never a guess."""
        self.paths = SimpleNamespace(knowledge_root=self.root / 'untimed/knowledge',
            run_root=self.root / 'untimed/runs', project_root=self.root / 'untimed',
            workflow_root=self.root / 'untimed')
        self.paths.knowledge_root.mkdir(parents=True)
        self.resources, self.index, self.jobs = [], {}, []
        self.add_lane(0, prepare_job=False, omit_timing=True)
        self.config.update(decay=4, neutralization='NONE', truncation=.08,
            pasteurization='ON', unit_handling='VERIFY', nan_handling='OFF', language='FASTEXPR')
        result = self.prepare()
        self.assertEqual(result['status'], 'blocked', result)
        self.assertTrue(result['missing_facts'])
        self.assertIn('timing', result['missing_facts'][0]['reason'])
        self.assertFalse((self.paths.run_root / 'research_groups').exists())
        self.runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
