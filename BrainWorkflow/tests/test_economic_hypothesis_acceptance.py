"""Task7 offline acceptance: FAKE evidence, real compilation/planning/adapters.

Only the model CLI/process transport and platform client are fake. Never replace
compiled lists, the planner, binder, generator, checks or artifact import entry.
All generated evidence lives in a TemporaryDirectory and is not live authority.
"""

import copy
import hashlib
import json
import os
import subprocess
from subprocess import Popen
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from tests import test_orchestrator
from tests.test_template_binding import binding_fixture
from wqb import cli, generator, knowledge_compile, research_planning
from wqb.codex_ai_worker import run_worker
from wqb.discovery_runtime import DiscoveryRuntimeExecutor
from wqb.orchestrator import WorkflowOrchestrator
from wqb.recorder import RunRecorder
from wqb.repair_runtime import RepairRuntimeExecutor
from wqb.semantic_publication import read_semantic_release
from wqb.runtime_control import RuntimePaused, request_runtime_state, read_runtime_control, update_runtime_status
from wqb.workflow_auto_continue import auto_continue_workflow


NOW = '2026-10-14T00:00:00+00:00'
FAKE_ARGV = ['FAKE-offline-worker', '{input}', '{output}']
FAKE_LABEL = 'FAKE offline acceptance evidence; not platform research'


def write_json(path: Path, value: object) -> None:
    """Input: temporary Path/JSON value. Output: None. Write test fixture data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def write_rows(path: Path, rows: list[dict]) -> None:
    """Input: temporary Path/object rows. Output: None. Write raw/legacy fixtures."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')


def read_json(path: Path) -> dict:
    """Input: JSON Path. Output: dict. Read a complete durable test receipt."""
    return json.loads(path.read_text(encoding='utf-8'))


class FakeCodexBoundary:
    """Transport the actual worker in process; fake only the external model CLI."""

    def __init__(self, answer):
        """Input: callable(payload, run)->dict. Output: harness. Keep actual worker guards."""
        self.answer = answer
        self.calls = []
        self.errors = []
        self.current = None
        self.stack = ExitStack()

    def __enter__(self):
        """Input: harness. Output: self. Prevent real executable/process launches."""
        self.stack.enter_context(patch('wqb.codex_ai_worker.shutil.which', return_value='FAKE-codex'))
        self.stack.enter_context(patch('wqb.codex_ai_worker.subprocess.run', side_effect=self.model_cli))
        self.stack.enter_context(patch('wqb.ai_checkpoints.subprocess.Popen', side_effect=self.worker_transport))
        return self

    def __exit__(self, *args):
        """Input: exception tuple. Output: bool/None. Restore process boundaries."""
        return self.stack.__exit__(*args)

    def model_cli(self, argv, **kwargs):
        """Input: actual Codex argv/options. Output: CompletedProcess. Emit FAKE model JSON."""
        if argv[0] == 'taskkill':
            return subprocess.CompletedProcess(argv, 0, '', '')
        payload, run = self.current
        schema = read_json(Path(argv[argv.index('--output-schema') + 1]))
        prompt = argv[-1]
        self.calls.append(dict(checkpoint_type=payload['checkpoint_type'], schema=schema,
                               prompt=prompt, run=run, argv=list(argv)))
        answer = self.answer(payload, run)
        Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(answer), encoding='utf-8')
        return subprocess.CompletedProcess(argv, 0, '', '')

    def worker_transport(self, argv, **kwargs):
        """Input: checkpoint subprocess argv/options. Output: Popen fake. Run the real adapter."""
        source, target = Path(argv[1]), Path(argv[2])
        self.current = (read_json(source), source.resolve().parents[5])
        process = MagicMock(spec=Popen)
        process.pid = 0
        try:
            run_worker(source, target)
            process.returncode = 0
            process.communicate.return_value = ('', '')
        except (ValueError, RuntimeError) as exc:
            self.errors.append(str(exc))
            process.returncode = 1
            process.communicate.return_value = ('', str(exc))
        return process


class FakeResponse:
    def __init__(self, payload=None, headers=None):
        """Input: optional JSON/headers dicts. Output: fake response. Never contact HTTP."""
        self.payload = payload or {}
        self.headers = headers or {}

    def json(self):
        """Input: response. Output: JSON dict. Supply deterministic platform evidence."""
        return self.payload

    def raise_for_status(self):
        """Input: response. Output: None. Successful FAKE platform reply."""
        return None


class FakePlatform:
    def __init__(self, case, recorder, mode='repairable'):
        """Input: TestCase/RunRecorder/mode str. Output: client. Audit plan-before-POST."""
        self.case, self.recorder, self.mode = case, recorder, mode
        self.posts, self.gets, self.batches, self.alphas = [], [], {}, {}
        self.serial_locations = set()

    def authenticate(self):
        """Input: client. Output: None. No credentials or network."""
        return None

    def post_json(self, path, payload):
        """Input: endpoint/payload. Output: fake Location. Preserve actual submission bookkeeping."""
        self.case.assertEqual(path, '/simulations')
        plan = self.recorder.read_jsonl('planned_candidates.jsonl')
        self.case.assertTrue(plan, 'Real CLI must publish the full plan before the first POST')
        for row in plan:
            if getattr(self, 'repair_parent', None) is not None:
                self.case.assertEqual(row['parent_alpha_id'], self.repair_parent['alpha_id'])
                self.case.assertEqual(row['parent_expression_hash'], self.repair_parent['expression_hash'])
                self.case.assertEqual(row['settings'], dict(self.repair_parent['settings'], decay=32))
            else:
                self.case.assertTrue(row.get('hypothesis_id'), 'CLI dropped v2 hypothesis lineage')
                self.case.assertTrue(row.get('bindings'), 'CLI dropped named-slot bindings')
                if '(' in row['expression']:
                    self.case.assertTrue(row.get('operator_provenance'))
                else:
                    self.case.assertEqual(row.get('operator_provenance'), [])
        self.posts.append(copy.deepcopy(payload))
        if self.mode == '429':
            response = requests.Response()
            response.status_code = 429
            response.headers['Retry-After'] = '60'
            raise requests.HTTPError('FAKE rate limit', response=response)
        if self.mode == 'unknown':
            raise requests.Timeout('FAKE POST outcome unknown')
        rows = payload if isinstance(payload, list) else [payload]
        ids = []
        for row in rows:
            identifier = f'FAKE-{self.recorder.run_dir.name}-{len(self.alphas)}'
            self.alphas[identifier] = row
            ids.append(identifier)
        location = f'/simulations/FAKE-{len(self.batches)}'
        self.batches[location] = ids
        if not isinstance(payload, list):
            self.serial_locations.add(location)
        return FakeResponse(headers={'Location': location})

    def request(self, method, path):
        """Input: HTTP method/path strings. Output: fake finished simulation response."""
        self.case.assertEqual(method, 'GET')
        self.case.assertIn(path, self.batches)
        return FakeResponse(dict(alpha=self.batches[path][0] if path in self.serial_locations else self.batches[path]))

    def get_json(self, path):
        """Input: endpoint str. Output: FAKE metrics/checks. Reject any data capture or unknown call."""
        self.gets.append(path)
        identifier = path.split('/')[2]
        self.case.assertIn(identifier, self.alphas, f'Unexpected platform endpoint: {path}')
        if path.endswith('/check'):
            self.case.assertNotEqual(self.mode, 'repairable', 'Baseline failure must precede expensive checks')
            checks = [] if self.mode == 'partial' else [dict(name=name, result='PASS')
                for name in ('SELF_CORRELATION', 'PROD_CORRELATION')]
            return {'is': {'checks': checks}}
        self.case.assertEqual(path, '/alphas/' + identifier)
        baseline = [dict(name='LOW_SHARPE', result='PASS'),
                    dict(name='LOW_FITNESS', result='FAIL' if self.mode == 'repairable' else 'PASS')]
        sharpe = 0.1 if self.mode == 'repairable' and not identifier.endswith('-0') else 1.3
        return dict(id=identifier, status='UNSUBMITTED', regular=self.alphas[identifier]['regular'],
                    settings=self.alphas[identifier]['settings'],
                    **{'is': dict(sharpe=1.8 if self.mode == 'qualified' else sharpe,
                                  fitness=1.2 if self.mode == 'qualified' else 0.6, turnover=0.2, returns=0.08,
                                  checks=baseline, provenance=FAKE_LABEL)})


class EconomicHypothesisAcceptanceTests(unittest.TestCase):
    def test_official_producer_review_stop_restart_records_and_structured_feedback(self):
        from tests.test_hypothesis_design_acceptance import reviewed_pair_knowledge
        from tests.test_hypothesis_pipeline import HypothesisSnapshotTests
        from wqb.hypothesis_selection import validate_operational_resource_context
        from wqb.research_record import empty_research_record, record_alpha_result, sync_research_record_to_machine
        from wqb.semantic_compilation import verify_design_materials
        from wqb.semantic_contracts import SemanticPolicy
        knowledge, scope, proposal = reviewed_pair_knowledge(self.root / 'official')
        snapshot = HypothesisSnapshotTests().paired_snapshot(knowledge, scope)
        context = validate_operational_resource_context(snapshot)
        experiment = context['experiments'][0]
        self.assertNotIn('prediction_comparison', experiment)
        run = self.root / 'official-run'
        write_json(run / 'run_manifest.json', dict(start_snapshot=snapshot))
        frozen = (run / 'run_manifest.json').read_bytes()
        settings = experiment['arms'][0]['settings']
        config = dict(settings, instrument_type=settings['instrumentType'], unit_handling=settings['unitHandling'],
            nan_handling=settings['nanHandling'], max_alphas_per_round=3, knowledge_root=str(knowledge),
            run_root=str(self.root / 'official-sources'))
        plan = research_planning.prepare_source_plan(run, config, {}, NOW)
        self.assertEqual(len(plan['scheduled_hypotheses']), 2)
        receipt = Path(plan['ai_plan_receipt'])
        frozen_plan = read_json(receipt)['config_patch']
        self.assertEqual(plan, research_planning.prepare_source_plan(run, config, {}, 'restart'))
        self.assertEqual(frozen_plan, read_json(receipt)['config_patch'])
        recorder = RunRecorder(Path(config['run_root']) / 'partial')
        client = FakePlatform(self, recorder, 'partial')
        authority = request_runtime_state(run, 'running', enable_live_api=True, max_simulations=3,
                                          max_runtime_seconds=300, max_recoveries=1)
        request_runtime_state(run, 'paused', expected_revision=authority['request_revision'])
        with patch.dict(os.environ, {'BRAIN_WORKFLOW_CONTROL_PATH': str(run)}):
            with self.assertRaises(RuntimePaused):
                cli.run_field_batch(client, recorder, dict(config, **plan), workflow_stage='scout',
                                    submit_mode='multi', multi_chunk_sleep_seconds=0)
            self.assertEqual(client.posts, [])
            request_runtime_state(run, 'running')
            summaries = cli.run_field_batch(client, recorder, dict(config, **plan), workflow_stage='scout',
                                            submit_mode='multi', multi_chunk_sleep_seconds=0)
            self.assertEqual(len(summaries), 2)
            self.assertTrue(all(not row.hard_pass and row.pending for row in summaries))
            posts = len(client.posts)
            request_runtime_state(run, 'paused')
            cli.retry_planned_candidates(client, recorder, dict(config, **plan), multi_chunk_sleep_seconds=0)
            self.assertEqual(len(client.posts), posts)
        record = empty_research_record('official-run', 'Offline paired comparison')
        rows = recorder.read_jsonl('all_alphas.jsonl')
        partial = record_alpha_result(record, rows[0])
        sync_research_record_to_machine(partial, knowledge, NOW)
        knowledge_compile.compile_research_records(knowledge, generated_at=NOW)
        partial_view = read_json(knowledge / 'machine/mechanism_evidence.json')
        self.assertTrue(all(g['label'] == 'inconclusive' for g in partial_view['groups']))
        for row in rows:
            record = record_alpha_result(record, row)
        sync_research_record_to_machine(record, knowledge, NOW)
        knowledge_compile.compile_research_records(knowledge, generated_at=NOW)
        view = read_json(knowledge / 'machine/mechanism_evidence.json')
        self.assertTrue(all(g['label'] == 'inconclusive' for g in view['groups']))
        self.assertTrue(any(g['observed_differences'] for g in view['groups']))
        job = Path(proposal['job'])
        pack, resources = verify_design_materials(job, read_json(job / 'run_manifest.json'), SemanticPolicy())
        answer = dict(summary='New proposal remains unreviewed.', designs=[{
            k: v for k, v in proposal['designs'][0].items() if k != 'design_id'}])
        with FakeCodexBoundary(lambda payload, bound: answer) as model:
            next_result = knowledge_compile.compile_hypothesis_design_command(knowledge, dict(evidence_pack=pack,
                resources=resources, executor_argv=FAKE_ARGV, mechanism_query=dict(experiment_id=experiment['experiment_id'])))
        self.assertEqual(next_result['status'], 'completed', next_result)
        self.assertEqual(len(model.calls), 1)
        self.assertIn('mechanism_context', model.calls[0]['prompt'])
        self.assertIn('explicit new experiment', model.calls[0]['prompt'])
        self.assertEqual((run / 'run_manifest.json').read_bytes(), frozen)
        self.assertEqual(read_runtime_control(run)['desired_state'], 'paused')
        self.assertFalse((run / 'submission_receipt.json').exists())

    def setUp(self):
        """Input: TestCase. Output: None. Build temporary legacy context plus indexed FAKE raw definitions."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {'BRAIN_WORKFLOW_CONTROL_PATH': '', 'BRAIN_WORKFLOW_RUNTIME_DEADLINE': ''})
        environment.start()
        self.addCleanup(environment.stop)
        network = patch('requests.sessions.Session.request', side_effect=AssertionError('Real HTTP forbidden in Task7 acceptance'))
        network.start()
        self.addCleanup(network.stop)
        fixture = test_orchestrator.WorkflowOrchestratorTests()
        self.paths = fixture.paths(self.root)
        self.knowledge = self.paths.knowledge_root
        template, fields, operators, scope = binding_fixture()
        legacy_path = self.knowledge / 'wiki/20_semantics/data_ledger.jsonl'
        legacy = json.loads(legacy_path.read_text().splitlines()[0])
        fields = [dict(legacy, **row, instrument_type='EQUITY', provenance=FAKE_LABEL,
                       compatible_template_ids=[]) for row in fields]
        fixture.write_start_artifacts(self.root, [test_orchestrator.valid_option_row(option_id='option-1')],
                                      ledger_rows=fields)
        self.canonicalize_legacy_fixture()
        self.scope = scope
        self.config = cli.load_config('configs/stage1_usa_d1.yaml', overrides=dict(
            knowledge_root=str(self.knowledge), run_root=str(self.paths.run_root),
            max_alphas_per_round=7, allow_live_source_fallback=False))
        self.template = template
        self.definition = {key: value for key, value in operators[0]['definition'].items() if key != 'evidence_refs'}
        self.source = self.add_source('raw/platform/operators/FAKE-rank.json',
                                      dict(provenance=FAKE_LABEL, operator='rank', definition=self.definition))

    def canonicalize_legacy_fixture(self):
        """Input: temporary legacy fixture. Output: None. Place scaffolding in current canonical paths, before compilation."""
        mapping = {'wiki/20_semantics/data_ledger.jsonl': 'machine/data_ledger.jsonl',
                   'wiki/30_templates/template_library.jsonl': 'machine/template_library.jsonl',
                   'wiki/50_benchmarks/benchmark_rules.jsonl': 'machine/benchmark_rules.jsonl',
                   'wiki/80_maintenance/freshness_manifest.json': 'machine/freshness_manifest.json',
                   'wiki/70_decisions/research_option_cards.jsonl': 'machine/decisions/research_option_cards.jsonl',
                   'wiki/10_foundations/activity_snapshot.md': 'raw/platform/activities/FAKE-activity.md'}
        for old, new in mapping.items():
            target = self.knowledge / new
            target.parent.mkdir(parents=True, exist_ok=True)
            (self.knowledge / old).replace(target)
        manifest = self.knowledge / 'machine/freshness_manifest.json'
        write_json(manifest, [dict(row, path=mapping.get(row['path'], row['path'])) for row in read_json(manifest)])
        for directory in sorted((self.knowledge / 'wiki').iterdir()):
            directory.rmdir()

    def add_source(self, relative, value):
        """Input: raw relative path str/JSON value. Output: indexed source dict. Hash actual FAKE bytes."""
        path = self.knowledge / relative
        write_json(path, value)
        row = dict(path=relative, content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                   captured_at=NOW, source_type='platform_learn_material' if relative.startswith('raw/platform/')
                   else 'research_record_source', source_family=str(Path(relative).parent).replace('\\', '/'))
        return row

    def evidence(self, source, kind='hypothesis'):
        """Input: source dict/kind str. Output: EvidenceRef dict. Keep FAKE documented and untested claims separate."""
        return dict(source_path=source['path'], sha256=source['content_hash'], capture_date=source['captured_at'][:10],
                    kind=kind, experiment_refs=[])

    def proposals(self, source=None, version=1):
        """Input: optional source dict/version int. Output: model envelope dict. Supply two competing untested mechanisms."""
        source = source or self.source
        ref = self.evidence(source)
        templates = []
        for name, direction, mechanism, prediction, falsification in [
                ('resilience', '', 'Funding resilience supports future returns.',
                 'Higher cash to debt predicts higher relative returns.', 'No return spread weakens resilience.'),
                ('reversal', '-', 'Crowded balance sheet preferences reverse.',
                 'Higher cash to debt predicts lower relative returns.', 'Persistent positive spread weakens reversal.')]:
            row = dict(copy.deepcopy(self.template), template_id=f'FAKE-{name}-v{version}',
                hypothesis_id=f'FAKE-{name}', hypothesis_version=version, semantic_version=2,
                semantic_status='reviewed', status='scout_only', template_family=name,
                skeleton=direction + self.template['skeleton'], evidence_refs=[ref], source_paths=[source['path']],
                hypothesis_card=dict(data_meaning='FAKE cash flow relative to debt.', mechanism=mechanism,
                    conditions='Both fields are observable before the decision.', alternative='Sector exposure explains the spread.',
                    prediction=prediction, operator_roles='Rank compares relative balance sheet strength.', falsification=falsification),
                operator_roles=[dict(operator='rank', role='normalization', purpose='Compare relative strength.')])
            templates.append(dict(trigger_id='FAKE-balance-sheet', mechanism_id=name, condition_id='observable', record=row))
        operators = []
        if version == 1:
            operator = dict(operator='rank', family='normalizer', semantic_version=2, semantic_status='reviewed',
                definition=dict(self.definition, evidence_refs=[self.evidence(source, 'documented')]),
                evidence_refs=[ref], conditional_uses=[dict(conditions='Comparable FAKE observations.',
                    purpose='Test relative ordering without claiming predictive success.', failure_risks=['Noise.'], evidence_refs=[ref])])
            operators.append(dict(trigger_id='FAKE-balance-sheet', mechanism_id='resilience', condition_id='observable', record=operator))
        return dict(summary=FAKE_LABEL, proposals=dict(operators=operators, templates=templates))

    def compile(self, boundary, refs=None):
        """Input: model harness/optional source rows. Output: actual command result. Never fake compiler/publication."""
        return knowledge_compile.compile_semantic_knowledge_command(self.knowledge, dict(
            source_refs=refs or [self.source], executor_argv=FAKE_ARGV, generated_at=NOW))

    def start(self):
        """Input: prepared temporary vault. Output: (orchestrator, run Path). Freeze via actual Start."""
        engine = WorkflowOrchestrator(self.paths)
        started = engine.start('Power Pool', 'option-1', NOW, selected_scope=self.scope)
        return engine, Path(started['run_dir'])

    def compile_and_start(self):
        """Input: TestCase. Output: engine/run/release. Compile actual validated model output then Start."""
        with FakeCodexBoundary(lambda payload, run: self.proposals()) as boundary:
            compiled = self.compile(boundary)
        self.assertEqual(compiled['status'], 'completed', (compiled, boundary.errors))
        self.assertEqual(len(boundary.calls), 1)
        engine, run = self.start()
        return engine, run, compiled['release']

    def choose_bindings(self, payload, run):
        """Input: actual worker payload/run Path. Output: FAKE bounded decision using persisted candidate IDs."""
        evidence = next((run / 'runtime/research_plans').glob('*.input.json'))
        data = read_json(evidence)
        pool = data.get('allowed_bindings')
        if pool is None:
            # The brief may point at the full hash-bound selection material.
            reference = data['supporting_evidence']
            material = run / reference['path']
            self.assertEqual(hashlib.sha256(material.read_bytes()).hexdigest(), reference['sha256'])
            pool = read_json(material)['allowed_bindings']
        choices = []
        for identifier in ('FAKE-resilience', 'FAKE-reversal'):
            row = next(row for row in pool if row['hypothesis_id'] == identifier)
            choices.append(dict(binding_id=row['candidate_id'], hypothesis_id=identifier, hypothesis_version=1))
        return dict(summary=FAKE_LABEL, decision=dict(selected_bindings=choices))

    def test_actual_worker_multitemplate_plan_consumes_model_choice_and_frozen_release(self):
        """Input: raw FAKE definitions. Output: assertions. Exercise actual compile/worker/planner/generator interfaces."""
        _, run, release = self.compile_and_start()
        snapshot = read_json(run / 'run_manifest.json')['start_snapshot']
        self.assertEqual(snapshot['hypothesis_binding_version'], 2)
        self.assertEqual(snapshot['semantic_release']['release_id'], release['release_id'])
        self.assertEqual({row['field_id'] for row in snapshot['data_ledger_rows']}, {'cash', 'debt'})
        config = dict(self.config, ai_executor_argv=FAKE_ARGV)
        with FakeCodexBoundary(self.choose_bindings) as boundary:
            try:
                plan = research_planning.prepare_hypothesis_plan(run, config, {}, NOW)
            except research_planning.ResearchPlanningBlocked as exc:
                self.fail(f'Actual multi-template worker integration blocked: {exc}; adapter errors={boundary.errors}')
            replay = research_planning.prepare_source_plan(run, config, {}, NOW)
        self.assertEqual(plan, replay)
        self.assertEqual(len(boundary.calls), 1, boundary.errors)
        self.assertIn('decision', boundary.calls[0]['schema']['properties'])
        self.assertIn('model_reasoning_effort=medium', boundary.calls[0]['argv'])
        self.assertEqual(boundary.calls[0]['argv'][boundary.calls[0]['argv'].index('--sandbox') + 1], 'read-only')
        self.assertFalse(boundary.calls[0]['schema']['additionalProperties'])
        self.assertLess(len(boundary.calls[0]['prompt'].encode('utf-8')), 32000)
        material = next((run / 'runtime/research_plans').glob('*.input.json'))
        self.assertGreater(material.stat().st_size, 12000, 'Exercise the real oversized-pool case, not a tiny stub')
        self.assertEqual(len(plan['scheduled_hypotheses']), 2)
        self.assertEqual(plan['hypothesis_bindings'], plan['scheduled_hypotheses'])
        rows = generator.generate_hypothesis_candidates(snapshot, plan['scheduled_hypotheses'], 7)
        self.assertEqual({row.expression for row in rows}, {'rank(cash / debt)', '-rank(cash / debt)'})
        for binding in plan['hypothesis_bindings']:
            self.assertEqual(set(binding['bindings']), {'flow', 'liability'})
            self.assertEqual(binding['operator_call_count'], 1)
        self.assertTrue(all(ref['kind'] == 'hypothesis' for row in snapshot['template_rows'] for ref in row['evidence_refs']))

    def test_actual_knowledge_worker_strict_output_rejection_preserves_release(self):
        """Input: valid release then malformed FAKE model envelope. Output: assertions. No compiler bypass or promotion."""
        _, _, release = self.compile_and_start()
        source = self.add_source('raw/platform/operators/FAKE-other.json', dict(provenance=FAKE_LABEL, definition=self.definition))
        bad = self.proposals(source)
        bad['unauthorized_publish'] = True
        with FakeCodexBoundary(lambda payload, run: bad) as boundary:
            first = self.compile(boundary, [source])
            second = self.compile(boundary, [source])
        self.assertEqual(first['status'], 'blocked', first)
        self.assertEqual(second['status'], 'blocked')
        self.assertEqual(len(boundary.calls), 1)
        self.assertEqual(read_semantic_release(self.knowledge)['release_id'], release['release_id'])
        self.assertTrue(first['rejections'] or first['error'])

    def test_actual_worker_strict_subset_reaches_cli_and_post_without_unselected_family(self):
        """Input: two frozen families/valid reversal-only model choice. Output: assertions. Reject ignored or broadened model decisions."""
        _, run, _ = self.compile_and_start()
        selected = []
        def reversal_only(payload, active):
            """Input: actual worker context. Output: strict subset decision from a non-first frozen binding."""
            pool = read_json(next((active / 'runtime/research_plans').glob('*.input.json')))['allowed_bindings']
            self.assertEqual({row['hypothesis_id'] for row in pool}, {'FAKE-resilience', 'FAKE-reversal'})
            choice = next(row for row in reversed(pool) if row['hypothesis_id'] == 'FAKE-reversal')
            selected.append(copy.deepcopy(choice))
            return dict(summary=FAKE_LABEL, decision=dict(selected_bindings=[dict(binding_id=choice['candidate_id'],
                hypothesis_id=choice['hypothesis_id'], hypothesis_version=choice['hypothesis_version'])]))
        config = dict(self.config, ai_executor_argv=FAKE_ARGV)
        with FakeCodexBoundary(reversal_only) as boundary:
            plan = research_planning.prepare_source_plan(run, config, {}, NOW)
            recorder, client, summaries = self.source_batch(run, plan_config=plan)
        self.assertEqual(len(boundary.calls), 1, boundary.errors)
        self.assertEqual(plan['scheduled_hypotheses'], selected)
        self.assertEqual(read_json(Path(plan['ai_plan_receipt']))['config_patch']['hypothesis_bindings'], selected)
        planned = recorder.read_jsonl('planned_candidates.jsonl')
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]['hypothesis_binding'], selected[0])
        self.assertEqual(planned[0]['hypothesis_id'], 'FAKE-reversal')
        self.assertEqual(client.posts, [[generator.simulation_payload(selected[0]['settings'], selected[0]['bound_expression'])]])
        self.assertEqual(len(summaries), 1)
        self.assertEqual({row['hypothesis_id'] for row in recorder.read_jsonl('all_alphas.jsonl')}, {'FAKE-reversal'})

    def source_batch(self, run, mode='repairable', plan_config=None, source_name='FAKE-scout'):
        """Input: active run/mode/optional plan/source name. Output: recorder/client/summaries. Execute actual v2 CLI generation."""
        config = dict(self.config)
        config.update(plan_config or research_planning.prepare_source_plan(run, config, {}, NOW))
        recorder = RunRecorder(self.paths.run_root / source_name)
        client = FakePlatform(self, recorder, mode)
        summaries = cli.run_field_batch(client, recorder, config, workflow_stage='scout',
            submit_mode='multi', multi_chunk_sleep_seconds=0)
        planned = recorder.read_jsonl('planned_candidates.jsonl')
        self.assertEqual(len(planned), len(config['scheduled_hypotheses']))
        self.assertLessEqual(len(planned), 7)
        self.assertEqual({row['expression'] for row in planned},
                         {row['bound_expression'] for row in config['hypothesis_bindings']})
        for row in planned:
            self.assertEqual(set(row['bindings']), {'flow', 'liability'})
            self.assertEqual(row['expression_hash'], cli.simulation_identity_hash(row['expression'], row['settings']))
        return recorder, client, summaries

    def test_actual_cli_publishes_semantic_scout_before_post_and_partial_checks_never_qualify(self):
        """Input: real compiled v2 plan/FAKE partial checks. Output: assertions. No fallback templates or invented qualification."""
        _, run, _ = self.compile_and_start()
        recorder, client, summaries = self.source_batch(run, 'partial')
        self.assertEqual(len(summaries), 7)
        self.assertTrue(all(not item.hard_pass and item.pending for item in summaries))
        self.assertFalse((recorder.run_dir / 'candidates.csv').exists())
        self.assertTrue(any(path.endswith('/check') for path in client.gets))
        self.assertTrue(all(not row['hard_pass'] for row in recorder.read_jsonl('all_alphas.jsonl')))
        self.assertFalse((run / 'submission_receipt.json').exists())

    def test_semantic_scout_429_keeps_plan_and_restarts_without_post_during_cooldown(self):
        """Input: real v2 Scout/FAKE429. Output: assertions. Existing cooldown adapter preserves frozen settings."""
        _, run, _ = self.compile_and_start()
        self.assert_authorized_cli_fault(run, '429')

    def test_semantic_scout_unknown_post_is_not_replayed(self):
        """Input: real v2 Scout/FAKE lost POST response. Output: assertions. Reconciliation precedes any retry."""
        _, run, _ = self.compile_and_start()
        self.assert_authorized_cli_fault(run, 'unknown')

    def assert_authorized_cli_fault(self, run, mode):
        """Input: temporary run/fault str. Output: None. Exercise real CLI under original authority; retain charged attempts and durable Stop."""
        original = request_runtime_state(run, 'running', enable_live_api=True,
            max_simulations=14, max_runtime_seconds=3600, max_recoveries=2)
        update_runtime_status(run, simulation_attempts=7)
        control = run / 'runtime_control.json'
        before = control.read_bytes()
        manifest = (run / 'run_manifest.json').read_bytes()
        with patch.dict(os.environ, {'BRAIN_WORKFLOW_CONTROL_PATH': str(run)}):
            recorder, client, summaries = self.source_batch(run, mode)
            self.assertEqual(summaries, [])
            posts = len(client.posts)
            charged = sum(len(payload) if isinstance(payload, list) else 1 for payload in client.posts)
            self.assertGreater(charged, 0)
            self.assertLessEqual(charged, 7)
            self.assertEqual(read_runtime_control(run)['simulation_attempts'], 7 + charged,
                             '429/unknown outcomes must retain charged attempts, never refund or reset')
            self.assertEqual(control.read_bytes(), before)
            plan_bytes = (recorder.run_dir / 'planned_candidates.jsonl').read_bytes()
            if mode == '429':
                self.assertEqual(posts, 1)
                self.assertTrue(read_json(recorder.run_dir / 'rate_limit_state.json')['retry_at'])
                cli.retry_planned_candidates(client, recorder, self.config, multi_chunk_sleep_seconds=0)
            else:
                with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                    cli.retry_planned_candidates(client, recorder, self.config, multi_chunk_sleep_seconds=0)
            stopped = request_runtime_state(run, 'paused', expected_revision=original['request_revision'])
            stopped_bytes = control.read_bytes()
            if mode == '429':
                cli.retry_planned_candidates(client, recorder, self.config, multi_chunk_sleep_seconds=0)
            else:
                with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                    cli.retry_planned_candidates(client, recorder, self.config, multi_chunk_sleep_seconds=0)
            self.assertEqual(len(client.posts), posts)
            self.assertEqual(read_runtime_control(run)['simulation_attempts'], 7 + charged)
            self.assertEqual(control.read_bytes(), stopped_bytes)
            for key in ('max_simulations', 'max_runtime_seconds', 'max_recoveries', 'enable_live_api'):
                self.assertEqual(stopped[key], original[key])
            self.assertEqual(stopped['desired_state'], 'paused')
            self.assertEqual((recorder.run_dir / 'planned_candidates.jsonl').read_bytes(), plan_bytes)
        self.assertEqual((run / 'run_manifest.json').read_bytes(), manifest)
        self.assertEqual(recorder.read_jsonl('all_alphas.jsonl'), [])
        self.assertFalse((recorder.run_dir / 'candidates.csv').exists())
        self.assertFalse((run / 'submission_receipt.json').exists())

    def planned_submission(self, run, mode, source_dir=None):
        """Input: frozen run/FAKE platform mode. Output: recorder/client/summaries. Focused real generator->plan->submission adapter path."""
        config = research_planning.prepare_source_plan(run, self.config, {}, NOW)
        scheduled = config['scheduled_hypotheses']
        generated = generator.generate_hypothesis_candidates(config['hypothesis_snapshot'], scheduled, 7)
        recorder = RunRecorder(source_dir or self.paths.run_root / ('FAKE-focused-' + mode))
        metadata = []
        for candidate in generated:
            binding = next(row for row in scheduled if row['bound_expression'] == candidate.expression
                           and row['settings'] == candidate.settings)
            metadata.append(dict(generator.hypothesis_candidate_metadata(config['hypothesis_snapshot'], binding,
                                                                        config['ai_plan_receipt']),
                expression=candidate.expression, settings=candidate.settings,
                expression_hash=cli.simulation_identity_hash(candidate.expression, candidate.settings)))
        recorder.publish_plan(metadata)
        client = FakePlatform(self, recorder, mode)
        summaries = cli.submit_candidate_payloads(client, recorder,
            [generator.simulation_payload(candidate.settings, candidate.expression) for candidate in generated],
            metadata, 'multi', 'semantic_acceptance', multi_chunk_sleep_seconds=0, knowledge_root=self.knowledge)
        self.assertEqual(len(metadata), 7)
        for row in recorder.read_jsonl('planned_candidates.jsonl'):
            self.assertEqual(set(row['bindings']), {'flow', 'liability'})
        return recorder, client, summaries

    def test_semantic_focused_adapter_partial_check_cannot_become_measured_qualification(self):
        """Input: actual bound/generated candidates/FAKE incomplete check JSON. Output: assertions. Exercise actual checker despite pending CLI integration."""
        _, run, _ = self.compile_and_start()
        recorder, _, summaries = self.planned_submission(run, 'partial')
        self.assertEqual(len(summaries), 7)
        self.assertTrue(all(not summary.hard_pass and summary.pending for summary in summaries))
        self.assertFalse((recorder.run_dir / 'candidates.csv').exists())
        for row in recorder.read_jsonl('all_alphas.jsonl'):
            self.assertFalse(row['hard_pass'])
            self.assertTrue(row['pending'])
            self.assertTrue(row['hypothesis_id'].startswith('FAKE-'))

    def test_semantic_plan_stop_preserves_intent_before_actual_post(self):
        """Input: frozen v2 plan/durable Stop. Output: assertions. Actual simulator honors paused authority."""
        _, run, _ = self.compile_and_start()
        plan = research_planning.prepare_source_plan(run, self.config, {}, NOW)
        control = run / 'runtime_control.json'
        write_json(control, dict(desired_state='paused', request_revision='FAKE-user-stop', enable_live_api=False,
                                 max_simulations=7, max_runtime_seconds=60, max_recoveries=1))
        before = control.read_bytes()
        recorder = RunRecorder(self.paths.run_root / 'FAKE-stopped')
        client = FakePlatform(self, recorder)
        with patch.dict(os.environ, {'BRAIN_WORKFLOW_CONTROL_PATH': str(run)}):
            with self.assertRaisesRegex(RuntimePaused, 'paused'):
                cli.run_field_batch(client, recorder, dict(self.config, **plan), workflow_stage='scout',
                                   submit_mode='multi', multi_chunk_sleep_seconds=0)
        self.assertEqual(client.posts, [])
        self.assertEqual(control.read_bytes(), before)
        self.assertTrue(Path(plan['ai_plan_receipt']).exists())

    def test_actual_knowledge_model_failure_and_stop_do_not_publish_or_retry(self):
        """Input: failed model then cancellation after a real worker. Output: assertions. Knowledge authority remains separate."""
        from wqb.semantic_compilation import prepare_semantic_job
        from wqb.semantic_contracts import SemanticPolicy
        def unavailable(payload, run):
            """Input: worker context. Output: raises RuntimeError. Simulate unavailable external model only."""
            raise RuntimeError('FAKE model unavailable')
        with FakeCodexBoundary(unavailable) as boundary:
            first = self.compile(boundary)
            replay = self.compile(boundary)
        self.assertEqual((first['status'], replay['status']), ('blocked', 'blocked'))
        self.assertEqual(len(boundary.calls), 1)
        self.assertIsNone(read_semantic_release(self.knowledge)['release_id'])
        source = self.add_source('raw/platform/operators/FAKE-cancel.json',
                                 dict(provenance=FAKE_LABEL, definition=self.definition))
        job = prepare_semantic_job(self.knowledge, [source], SemanticPolicy())
        def cancelled(payload, run):
            """Input: actual model context. Output: valid FAKE answer after durable knowledge cancellation."""
            write_json(job / 'control.json', dict(cancelled=True))
            return self.proposals(source)
        with FakeCodexBoundary(cancelled) as boundary:
            result = self.compile(boundary, [source])
        self.assertEqual(result['status'], 'cancelled', (result, boundary.errors))
        self.assertIsNone(read_semantic_release(self.knowledge)['release_id'])
        self.assertFalse((job / 'mission.json').exists())
        self.assertFalse((self.paths.run_root / 'runtime_control.json').exists())

    def test_actual_hypothesis_worker_rejects_unknown_binding_without_model_replay(self):
        """Input: actual multi-template worker/unknown FAKE binding ID. Output: assertions. Strict output propagates to durable blocked plan."""
        _, run, _ = self.compile_and_start()
        config = dict(self.config, ai_executor_argv=FAKE_ARGV)
        invalid = dict(summary=FAKE_LABEL, decision=dict(selected_bindings=[dict(
            binding_id='FAKE-outside-snapshot', hypothesis_id='FAKE-reversal', hypothesis_version=1)]))
        with FakeCodexBoundary(lambda payload, unit: invalid) as boundary:
            for _ in range(2):
                with self.assertRaises(research_planning.ResearchPlanningBlocked):
                    research_planning.prepare_source_plan(run, config, {}, NOW)
        self.assertEqual(len(boundary.calls), 1)
        self.assertTrue(boundary.errors)
        receipts = [read_json(path) for path in (run / 'runtime/research_plans').glob('hypothesis-*.json')
                    if not path.name.endswith(('.input.json', '.brief.json'))]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]['status'], 'blocked')
        self.assertFalse((run / 'candidates.csv').exists())

    def test_zero_model_selected_hypotheses_is_explicit_exhaustion_not_generic_candidates(self):
        """Input: compiled v2 pool/model selecting nothing. Output: assertions. No padding, simulated success or repeated worker."""
        _, run, _ = self.compile_and_start()
        config = dict(self.config, ai_executor_argv=FAKE_ARGV)
        with FakeCodexBoundary(lambda payload, unit: dict(summary=FAKE_LABEL,
                              decision=dict(selected_bindings=[]))) as boundary:
            with self.assertRaises(research_planning.ResearchVariantsExhausted):
                research_planning.prepare_source_plan(run, config, {}, NOW)
            with self.assertRaises(research_planning.ResearchPlanningBlocked):
                research_planning.prepare_source_plan(run, config, {}, NOW)
        self.assertEqual(len(boundary.calls), 1)
        self.assertFalse((run / 'planned_candidates.jsonl').exists())
        self.assertFalse((run / 'candidates.csv').exists())

    def test_stop_before_hypothesis_worker_prevents_model_and_keeps_stop(self):
        """Input: frozen v2 pool/durable Stop. Output: assertions. Actual checkpoint cancels before spawning the model."""
        _, run, _ = self.compile_and_start()
        control = run / 'runtime_control.json'
        write_json(control, dict(desired_state='paused', request_revision='FAKE-user-stop', enable_live_api=True,
                                max_simulations=7, max_runtime_seconds=60, max_recoveries=1))
        before = control.read_bytes()
        with patch.dict(os.environ, {'BRAIN_WORKFLOW_CONTROL_PATH': str(run)}), FakeCodexBoundary(self.choose_bindings) as boundary, \
                patch.object(FakePlatform, 'post_json', side_effect=AssertionError('POST forbidden after Stop')) as post:
            with self.assertRaises((research_planning.ResearchPlanningBlocked, RuntimePaused)) as caught:
                research_planning.prepare_source_plan(run, dict(self.config, ai_executor_argv=FAKE_ARGV), {}, NOW)
        if isinstance(caught.exception, RuntimePaused):
            self.assertEqual(str(caught.exception), 'user_paused')
        else:
            from wqb.ai_checkpoints import load_ai_checkpoints
            cancelled = [row for row in load_ai_checkpoints(run / 'stages/ai')
                         if row.get('checkpoint_type') == 'hypothesis_batch_plan' and row.get('status') == 'cancelled']
            self.assertTrue(cancelled, 'Wrapped planning failure must have actual cancellation evidence')
            self.assertTrue(all(row.get('error') == 'user_paused' for row in cancelled))
        self.assertEqual(boundary.calls, [])
        post.assert_not_called()
        self.assertEqual(control.read_bytes(), before)
        self.assertFalse((run / 'candidates.csv').exists())

    def test_incremental_real_compile_reuses_untouched_source_and_preserves_frozen_start(self):
        """Input: first release then one new FAKE source. Output: assertions. Cache and immutable Start survive publication."""
        _, run, release = self.compile_and_start()
        manifest_bytes = (run / 'run_manifest.json').read_bytes()
        immutable = {name: Path(path).read_bytes() for name, path in release['paths'].items()}
        source = self.add_source('raw/research/runs/FAKE-learning.json', dict(provenance=FAKE_LABEL,
            observation='An unfinished observation is not measured success.'))
        with FakeCodexBoundary(lambda payload, unit: self.proposals(source, version=2)) as boundary:
            updated = self.compile(boundary, [self.source, source])
            replay = self.compile(boundary, [self.source, source])
        self.assertEqual(updated['status'], 'completed', (updated, boundary.errors))
        self.assertEqual(len(boundary.calls), 1, 'Only the changed material unit may call the model')
        self.assertEqual(replay['release']['release_id'], updated['release']['release_id'])
        self.assertNotEqual(updated['release']['release_id'], release['release_id'])
        self.assertEqual((run / 'run_manifest.json').read_bytes(), manifest_bytes)
        frozen_plan = research_planning.prepare_source_plan(run, self.config, {}, NOW)
        self.assertTrue(all(row['hypothesis_version'] == 1 for row in frozen_plan['scheduled_hypotheses']))
        for name, path in release['paths'].items():
            self.assertEqual(Path(path).read_bytes(), immutable[name])
        _, _, templates = knowledge_compile.read_semantic_rows(self.knowledge)
        new = [row for row in templates if row.get('hypothesis_version') == 2]
        self.assertEqual(len(new), 2)
        self.assertTrue(all(ref['kind'] == 'hypothesis' for row in new for ref in row['evidence_refs']))

    def checked_child(self, run, parent, stage):
        """Input: run/real parent row/stage str. Output: checked children list. Fake platform only; use real submission/check adapters."""
        recorder = RunRecorder(run / 'stages' / stage / ('FAKE-' + parent['alpha_id']))
        settings = dict(parent['settings'], decay=31 if stage == 'discovery' else 32)
        row = dict(copy.deepcopy(parent), settings=settings,
            expression_hash=cli.simulation_identity_hash(parent['expression'], settings),
            parent_alpha_id=parent['alpha_id'], parent_expression_hash=parent['expression_hash'])
        for key in ('alpha_id', 'status', 'hard_pass', 'metrics', 'failed', 'pending', 'warnings', 'benchmark_label'):
            row.pop(key, None)
        recorder.publish_plan([row])
        client = FakePlatform(self, recorder, 'repairable' if stage == 'discovery' else 'qualified')
        cli.submit_candidate_payloads(client, recorder, [generator.simulation_payload(settings, row['expression'])],
            [row], 'multi', stage, multi_chunk_sleep_seconds=0, knowledge_root=self.knowledge)
        result = recorder.read_jsonl('all_alphas.jsonl')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['hypothesis_id'], parent['hypothesis_id'])
        self.assertEqual(result[0]['bindings'], parent['bindings'])
        return result

    def execute_discovery(self, active, parent):
        """Input: active run/actual measured Seed. Output: real Discovery children. Assert fixed kernel/binding before workflow merge."""
        self.assertEqual(read_json(active / 'stages/batch_generation/seed.json')['parent'], parent)
        recorder = RunRecorder(active / 'stages/batch_generation/source')
        client = FakePlatform(self, recorder, 'repairable')
        executor = DiscoveryRuntimeExecutor(dict(self.config, ai_executor='none', ai_executor_argv=[]))
        with patch('wqb.cli.build_client', return_value=client), patch('wqb.cli.cooperative_sleep', return_value=None):
            children = executor(active, parent)
        planned = recorder.read_jsonl('planned_candidates.jsonl')
        self.assertTrue(planned)
        self.assertLessEqual(len(planned), 30)
        self.assertTrue(client.posts)
        for row in planned:
            self.assertEqual(row['hypothesis_id'], parent['hypothesis_id'],
                             'Discovery reselected a fresh hypothesis instead of the measured Seed')
            self.assertEqual(row['hypothesis_version'], parent['hypothesis_version'])
            self.assertEqual(row['bindings'], parent['bindings'], 'Discovery changed the measured multi-field binding')
            self.assertEqual(row['expression'], parent['expression'],
                             'This no-window Seed permits settings variants only, not a new economic kernel')
            self.assertNotEqual(row['expression_hash'], parent['expression_hash'])
        for child in children:
            self.assertEqual(child['parent_expression_hash'], parent['expression_hash'])
            self.assertEqual(child['parent_alpha_id'], parent['alpha_id'])
        return children

    def test_actual_discovery_adapter_uses_measured_v2_seed_not_scout_hypothesis_pool(self):
        """Input: real generated/checked Scout rows in a temporary run. Output: assertions. Stage adapter creates Seed; no copied/imported artifacts."""
        from wqb.workflow_stage_adapters import schedule_research_stage, advance_post_schedule_stage
        _, run, _ = self.compile_and_start()
        schedule_research_stage(self.knowledge, run, 'option-1')
        self.planned_submission(run, 'repairable', source_dir=run)
        result = advance_post_schedule_stage(run, 'batch_generation', discovery_executor=self.execute_discovery)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['execution'], 'executed', result)
        self.assertEqual(read_json(run / 'stages/batch_generation/discovery_execution.json')['status'], 'completed')

    def test_raw_compile_to_scout_seed_discovery_repair_record_and_incremental_compile(self):
        """Input: FAKE raw/model/platform only. Output: assertions. No manual import, copied result files or advanced stage fixtures."""
        engine, run, release = self.compile_and_start()
        manifest_bytes = (run / 'run_manifest.json').read_bytes()
        calls = []

        def source_runner(config, metadata):
            """Input: real auto-continue config/metadata. Output: source receipt. Consume actual model plan through actual CLI."""
            calls.append('scout')
            self.assertEqual(metadata['hypothesis_binding_version'], 2)
            config.update(research_planning.prepare_source_plan(run, config, metadata, NOW))
            recorder, client, summaries = self.source_batch(run, plan_config=config)
            self.assertEqual(len(summaries), 2)
            return dict(status='completed', run_dir=str(recorder.run_dir))

        def discovery(active, parent):
            """Input: actual workflow seed. Output: real Discovery adapter children. Fake platform transport only."""
            calls.append('discovery')
            return self.execute_discovery(active, parent)

        config = dict(self.config, ai_executor_argv=FAKE_ARGV)

        def model_answer(payload, active):
            """Input: actual checkpoint/run. Output: fake model JSON. Exercise both planner and Repair schemas."""
            if payload['checkpoint_type'] != 'repair_decision':
                return self.choose_bindings(payload, active)
            evidence = read_json(Path(payload['evidence_paths'][0]))
            parent = evidence['parent']
            return dict(summary=FAKE_LABEL, decision=dict(
                parent_alpha_id=parent['parent_alpha_id'], parent_expression_hash=parent['parent_expression_hash'],
                diagnosis='Measured fitness is below its threshold.', economic_rationale='The frozen resilience mechanism may persist.',
                hypothesis='Slower holding may reduce transient noise.', expected_improvement='Higher measured fitness.',
                risks='Smoothing may lag new information.', action='test', edit='decay', value=32,
                target_metric='fitness', target_direction='increase', falsification='Fitness does not improve.',
                applicability='Only the measured seed and its frozen binding.'))

        def repair_client(transport_config):
            """Input: actual client configuration. Output: fake transport bound to an executor-created plan, never a manual child."""
            plans = list((run / 'stages/repair/parents').rglob('repair_plan.json'))
            pending = [path for path in plans if not RunRecorder(path.parent).read_jsonl('all_alphas.jsonl')]
            self.assertEqual(len(pending), 1)
            plan_path = pending[0]
            plan = read_json(plan_path)
            self.assertLessEqual(len(plan['variants']), plan['maximum'])
            self.assertLessEqual(plan['maximum'], 8)
            parent = next(row for row in RunRecorder(run).read_jsonl('all_alphas.jsonl')
                          if row['alpha_id'] == plan['parent_alpha_id'] and row['expression_hash'] == plan['parent_expression_hash'])
            client = FakePlatform(self, RunRecorder(plan_path.parent), 'qualified')
            client.repair_parent = parent
            calls.append('repair')
            return client

        repair = RepairRuntimeExecutor(config, enable_live_api=True)
        with FakeCodexBoundary(model_answer) as boundary, patch('wqb.cli.build_client', side_effect=repair_client):
            result = {}
            for _ in range(25):
                result = auto_continue_workflow(self.paths, config, NOW, enable_live_api=True,
                    source_batch_runner=source_runner, discovery_executor=discovery, repair_executor=repair)
                if result.get('status') in {'waiting_for_user', 'failed'}:
                    break
        repair_receipt = run / 'stages/repair/repair_execution.json'
        diagnostic = read_json(repair_receipt) if repair_receipt.exists() else {}
        self.assertEqual(result.get('status'), 'waiting_for_user',
                         (result, calls, boundary.errors, diagnostic.get('status'), diagnostic.get('blocker'),
                          [(row.get('phase'), row.get('blocker')) for row in diagnostic.get('attempts', [])]))
        self.assertEqual(calls.count('scout'), 1)
        self.assertEqual(calls.count('discovery'), 1)
        self.assertIn('repair', calls)
        decisions = [path for path in (run / 'runtime/repair_decisions').glob('*.json')
                     if not path.name.endswith(('.input.json', '.support.json'))]
        self.assertTrue(decisions, 'Whole-flow acceptance must consume the real Repair model decision')
        self.assertTrue(all(read_json(path)['status'] == 'consumed' for path in decisions))
        self.assertEqual([row['checkpoint_type'] for row in boundary.calls],
                         ['hypothesis_batch_plan', *['repair_decision'] * len(decisions)])
        self.assertEqual(read_json(run / 'stages/scout_seed/scout_seed_import.json')['mode'], 'artifact_import')
        checked = RunRecorder(run).read_jsonl('all_alphas.jsonl')
        self.assertTrue(checked)
        for row in checked:
            context = row if row.get('hypothesis_id') else next(parent for parent in checked
                if parent['alpha_id'] == row['parent_alpha_id'] and parent['expression_hash'] == row['parent_expression_hash'])
            self.assertTrue(context['hypothesis_id'])
            self.assertEqual(set(context['bindings']), {'flow', 'liability'})
            self.assertIn('FAKE', row['alpha_id'])
            self.assertEqual(row['metrics']['provenance'], FAKE_LABEL)
        before = list(calls)
        with patch('wqb.cli.build_client', side_effect=AssertionError('Completed Repair must not rebuild a client')):
            auto_continue_workflow(self.paths, config, NOW, enable_live_api=True,
                source_batch_runner=source_runner, discovery_executor=discovery, repair_executor=repair)
        self.assertEqual(calls, before, 'Restart must reuse durable Scout/Discovery/Repair results')
        candidates = read_json(run / 'candidate_gate.json')
        engine.approve_candidates([candidates[0]['candidate_id']], NOW, 'FAKE offline human approval')
        for _ in range(4):
            engine.continue_once(NOW)
            if read_json(run / 'run_state.json')['status'] == 'completed':
                break
        terminal = read_json(run / 'run_state.json')
        self.assertEqual(terminal['status'], 'completed')
        self.assertEqual(terminal['current_stage'], 'complete')
        self.assertTrue(terminal['research_record_synced'])
        self.assertFalse(engine.status()['active'], 'Terminal completion must release the active mission pointer')
        record = read_json(run / 'research_record.json')
        self.assertTrue(record['backtest'])
        self.assertTrue(record['repair'])
        self.assertTrue(record['candidate_gate'])
        for row in record['backtest']:
            context = row if row.get('hypothesis_id') else next(parent for parent in checked
                if parent['alpha_id'] == row['parent_alpha_id'] and parent['expression_hash'] == row['parent_expression_hash'])
            self.assertTrue(context['hypothesis_id'].startswith('FAKE-'))
            self.assertEqual(set(context['bindings']), {'flow', 'liability'})
        self.assertFalse((run / 'submission_receipt.json').exists())
        summary = knowledge_compile.compile_research_records(self.knowledge, generated_at=NOW)
        self.assertEqual(summary['record_count'], 1)
        source_rows = RunRecorder(self.knowledge / 'machine').read_jsonl('source_index.jsonl')
        source = next(row for row in source_rows if row['path'].endswith('/research_record.md'))
        with FakeCodexBoundary(lambda payload, unit: self.proposals(source, version=2)) as boundary:
            updated = self.compile(boundary, [self.source, source])
            replay = self.compile(boundary, [self.source, source])
        self.assertEqual(updated['status'], 'completed', (updated, boundary.errors))
        self.assertEqual(len(boundary.calls), 1, 'Research records must incrementally compile through the real worker')
        self.assertEqual(updated['release']['release_id'], replay['release']['release_id'])
        self.assertNotEqual(updated['release']['release_id'], release['release_id'])
        self.assertEqual((run / 'run_manifest.json').read_bytes(), manifest_bytes)
        _, _, templates = knowledge_compile.read_semantic_rows(self.knowledge)
        lessons = [row for row in templates if row.get('hypothesis_version') == 2]
        self.assertEqual(len(lessons), 2)
        self.assertTrue(all(ref['kind'] == 'hypothesis' for row in lessons for ref in row['evidence_refs']))
