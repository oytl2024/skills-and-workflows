"""Strict model wire format is not a source trust decision."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from threading import Barrier
import time
import unittest
from unittest.mock import patch

from wqb import full_semantic_model_worker as subject


class FullSemanticWireTests(unittest.TestCase):
    def test_reservation_allows_only_one_dispatch_across_failed_and_new_checkpoints(self):
        """Input: one running reservation. Output: one transport despite failed retry and fresh checkpoint."""
        from tests.test_full_semantic_execution import FullSemanticExecutionTests
        from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
        from wqb.full_semantic_execution import run_full_semantic_compile
        fixture = FullSemanticExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        calls = []
        def dispatch(*args, **kwargs):
            """Input: fake transport arguments. Output: uncertain failure after counted dispatch."""
            calls.append(1)
            raise RuntimeError('uncertain transport')
        def execute(**kwargs):
            """Input: reserved job. Output: unresolved answer after attempts to replay its authority."""
            directory = Path(kwargs['job']['job_dir']) / 'stages/ai'
            first = append_ai_checkpoint(directory, 'full_semantic_explanation', 'Explain', ['input.json'], 'fixture')
            with patch('wqb.ai_checkpoints.subprocess.run', side_effect=dispatch), \
                 patch('wqb.ai_checkpoints._run_cancellable', side_effect=dispatch):
                for checkpoint in (first, first, append_ai_checkpoint(directory,
                        'full_semantic_explanation', 'Explain again', ['input.json'], 'fixture')):
                    run_ai_checkpoint(directory, checkpoint.checkpoint_id, ['fake', '{input}', '{output}'])
            return fixture.answer(kwargs['job'])
        run_full_semantic_compile(fixture.root, fixture.plan(), executor=execute)
        self.assertEqual(len(calls), 1)

    def test_checkpoint_requires_authority_bound_transport_controls(self):
        """Input: ten-second reservation. Output: mandatory cancellation supervisor and bounded timeout."""
        from tests.test_full_semantic_execution import FullSemanticExecutionTests
        from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
        from wqb.full_semantic_execution import run_full_semantic_compile
        fixture = FullSemanticExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        observed = []
        def execute(**kwargs):
            """Input: reserved job. Output: answer after checking supervisor cancellation wiring."""
            job = kwargs['job']
            directory = Path(job['job_dir']) / 'stages/ai'
            cp = append_ai_checkpoint(directory, 'full_semantic_explanation', 'Explain', ['input.json'], 'fixture')
            def dispatch(argv, timeout_seconds, cancellation_check, cancel_on_pause):
                """Input: supervisor arguments. Output: cancelled failure with exact control observations."""
                self.assertLessEqual(timeout_seconds, 10)
                self.assertFalse(cancel_on_pause)
                self.assertFalse(cancellation_check())
                (Path(job['job_dir']) / 'control.json').write_text('{"cancelled":true}')
                self.assertTrue(cancellation_check())
                observed.append(timeout_seconds)
                raise RuntimeError('cancelled')
            with patch('wqb.ai_checkpoints.subprocess.run', side_effect=AssertionError('unsupervised')), \
                 patch('wqb.ai_checkpoints._run_cancellable', side_effect=dispatch):
                run_ai_checkpoint(directory, cp.checkpoint_id, ['fake', '{input}', '{output}'])
            return fixture.answer(job)
        run_full_semantic_compile(fixture.root, fixture.plan(max_runtime_seconds=10), executor=execute)
        self.assertEqual(len(observed), 1)

    def setUp(self):
        """Input: none. Output: a canonical schema with optional and arbitrary JSON facts."""
        self.schema = dict(type='object', properties=dict(
            name=dict(type='string'), optional=dict(type='string'), value={},
            items=dict(type='array', items={})), required=['name', 'value', 'items'], additionalProperties=False)

    def test_wire_requires_nullable_optional_fields_and_encodes_json_values(self):
        wire = subject.strict_worker_schema(self.schema)
        self.assertEqual(set(wire['required']), set(wire['properties']))
        self.assertFalse(wire['additionalProperties'])
        self.assertEqual(wire['properties']['value']['type'], 'string')
        self.assertIn({'type': 'null'}, wire['properties']['optional']['anyOf'])
        answer = dict(name='fixture', optional=None, value='{"units":"USD"}', items=['1', 'true'])
        self.assertEqual(subject.normalize_worker_answer(self.schema, answer),
                         dict(name='fixture', value={'units': 'USD'}, items=[1, True]))

    def test_bad_json_nonfinite_duplicate_keys_and_missing_wire_fields_reject(self):
        for value in ('NaN', '{"x":1,"x":2}', 'not json'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                subject.normalize_worker_answer(self.schema,
                    dict(name='fixture', optional=None, value=value, items=[]))
        with self.assertRaises(ValueError):
            subject.normalize_worker_answer(self.schema, dict(name='fixture', value='1', items=[]))

    def test_union_normalization_uses_the_validated_wire_branch(self):
        schema = dict(anyOf=[dict(type='null'), self.schema])
        self.assertIsNone(subject.normalize_worker_answer(schema, None))
        answer = dict(name='fixture', optional='kept', value='null', items=[])
        self.assertEqual(subject.normalize_worker_answer(schema, answer),
                         dict(name='fixture', optional='kept', value=None, items=[]))

    def test_readonly_worker_preserves_full_explanation_answer(self):
        from tests.test_full_semantic_execution import FullSemanticExecutionTests
        from wqb.full_semantic_execution import full_semantic_output_schema, run_full_semantic_compile
        from wqb.codex_ai_worker import run_worker
        fixture = FullSemanticExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = fixture.plan()
        job = fixture.loaded(plan)
        answer = fixture.answer(job)
        wire = deepcopy(answer)
        properties = full_semantic_output_schema(job)['properties']['targets']['items']['properties']['typed_facts']['properties']
        for target in wire['targets']:
            target['typed_facts'] = {key: None for key in properties}
        source = Path(job['job_dir']) / 'stages/ai/ai_checkpoint_runs/fixture/attempt/input.json'
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps(dict(checkpoint_type='full_semantic_explanation',
            evidence_paths=['input.json'], reason='Explain frozen local resources.')), encoding='utf-8')
        def model(argv, *args, **kwargs):
            """Input: readonly worker argv/options. Output: fake complete model answer; never launch Codex."""
            self.assertEqual(argv[argv.index('--sandbox') + 1], 'read-only')
            self.assertIn('model_reasoning_effort=medium', argv)
            schema = json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text())
            self.assertEqual(set(schema['required']), {'summary', 'targets'})
            Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(wire), encoding='utf-8')
            return CompletedProcess(argv, 0, '', '')
        def execute(**kwargs):
            """Input: reserved explanation job kwargs. Output: complete fake worker answer under real authority."""
            with patch('wqb.codex_ai_worker.shutil.which', return_value='fake-codex'), \
                 patch('wqb.ai_checkpoints._run_cancellable', side_effect=model):
                result = run_worker(source, source.parent / 'output.json')
            self.assertEqual(result, answer)
            return result
        result = run_full_semantic_compile(fixture.root, plan, executor=execute)
        self.assertEqual(result['status'], 'completed', result)

    def test_checkpoint_retains_targets_and_rejects_stale_job_before_dispatch(self):
        from tests.test_full_semantic_execution import FullSemanticExecutionTests
        from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
        from wqb.full_semantic_execution import run_full_semantic_compile
        fixture = FullSemanticExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = fixture.plan()
        job = fixture.loaded(plan)
        answer = fixture.answer(job)
        directory = Path(job['job_dir']) / 'stages/ai'
        checkpoint = append_ai_checkpoint(directory, 'full_semantic_explanation',
            'Explain frozen local targets.', ['input.json'], '2026-10-28T00:00:00Z')
        def dispatch(argv, *args, **kwargs):
            """Input: checkpoint argv/options. Output: fake complete worker output; no process launch."""
            Path(argv[-1]).write_text(json.dumps(answer), encoding='utf-8')
            return CompletedProcess(argv, 0, '', '')
        def execute(**kwargs):
            """Input: reserved job kwargs. Output: complete fake checkpoint answer."""
            with patch('wqb.ai_checkpoints._run_cancellable', side_effect=dispatch):
                result = run_ai_checkpoint(directory, checkpoint.checkpoint_id, ['fake', '{input}', '{output}'])
            self.assertEqual(result['status'], 'completed', result)
            self.assertEqual(result['targets'], answer['targets'])
            return answer
        result = run_full_semantic_compile(fixture.root, plan, executor=execute)
        self.assertEqual(result['status'], 'completed', result)
        manifest = Path(job['job_dir']) / 'run_manifest.json'
        manifest.write_text('{}', encoding='utf-8')
        checkpoint = append_ai_checkpoint(directory, 'full_semantic_explanation',
            'Invalid source test.', ['input.json'], '2026-10-28T00:00:00Z')
        with patch('wqb.ai_checkpoints.subprocess.run', side_effect=AssertionError('model forbidden')):
            result = run_ai_checkpoint(directory, checkpoint.checkpoint_id, ['fake', '{input}', '{output}'])
        self.assertEqual(result['status'], 'failed')

    def test_factory_authenticates_job_and_preserves_deadline_and_one_attempt(self):
        from tests.test_full_semantic_execution import FullSemanticExecutionTests
        from wqb.full_semantic_execution import full_semantic_output_schema, run_full_semantic_compile
        fixture = FullSemanticExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = fixture.plan(max_runtime_seconds=60)
        job = fixture.loaded(plan)
        answer = fixture.answer(job)
        runner = subject.create_full_semantic_model_runner(fixture.root, plan, dict(ai_executor='codex'))
        with patch('wqb.ai_checkpoints.run_ai_checkpoint', return_value=dict(status='completed', **answer)) as dispatch:
            result = run_full_semantic_compile(fixture.root, plan, executor=runner)
            self.assertEqual(result['status'], 'completed', result)
            self.assertLessEqual(dispatch.call_args.kwargs['timeout_seconds'], 60)
            self.assertFalse(dispatch.call_args.kwargs['cancel_on_pause'])
            with self.assertRaises(ValueError):
                runner(job=job, output_schema=full_semantic_output_schema(job), deadline=time.time() + 60)
            self.assertEqual(dispatch.call_count, 1)
        with self.assertRaises(ValueError):
            subject.create_full_semantic_model_runner(fixture.root, plan, dict(ai_executor='unrestricted'))

    def test_prepared_input_alone_cannot_bypass_zero_model_budget(self):
        from tests.test_full_semantic_execution import FullSemanticExecutionTests
        from wqb.codex_ai_worker import run_worker
        from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
        fixture = FullSemanticExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        job = fixture.loaded(fixture.plan(0))
        directory = Path(job['job_dir']) / 'stages/ai'
        checkpoint = append_ai_checkpoint(directory, 'full_semantic_explanation',
            'A prepared input has no dispatch authority.', ['input.json'], '2026-10-28T00:00:00Z')
        source = directory / 'ai_checkpoint_runs/fixture/attempt/input.json'
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps(dict(checkpoint_type='full_semantic_explanation',
            evidence_paths=['input.json'])), encoding='utf-8')
        with patch('wqb.codex_ai_worker.subprocess.run', side_effect=AssertionError('model forbidden')):
            with self.assertRaisesRegex(ValueError, 'reservation'):
                run_worker(source, source.parent / 'output.json')
        with patch('wqb.ai_checkpoints.subprocess.run', side_effect=AssertionError('model forbidden')):
            result = run_ai_checkpoint(directory, checkpoint.checkpoint_id, ['fake', '{input}', '{output}'])
        self.assertEqual(result['status'], 'failed')


class FullSemanticDispatchTests(unittest.TestCase):
    def setUp(self):
        """Input: none. Output: isolated reserved-job fixture; no actual model processes."""
        from tests.test_full_semantic_execution import FullSemanticExecutionTests
        self.fixture = FullSemanticExecutionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.calls = []

    def worker_input(self, job, name):
        """Input: loaded job dict/name str. Output: temporary direct-worker input Path."""
        source = Path(job['job_dir']) / f'stages/ai/ai_checkpoint_runs/{name}/attempt/input.json'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps(dict(checkpoint_type='full_semantic_explanation',
            evidence_paths=['input.json'], reason='Explain frozen targets')), encoding='utf-8')
        return source

    def test_zero_budget_direct_worker_rejects_reflection_type_downgrade(self):
        """Input: prepared explanation relabeled advisory. Output: route rejection before any model process."""
        from wqb.codex_ai_worker import run_worker
        job = self.fixture.loaded(self.fixture.plan(0))
        source = self.worker_input(job, 'downgrade')
        payload = json.loads(source.read_text())
        payload['checkpoint_type'] = 'research_reflection'
        source.write_text(json.dumps(payload), encoding='utf-8')
        def model(argv, **kwargs):
            """Input: mocked model argv. Output: advisory answer demonstrating an unguarded transport."""
            Path(argv[argv.index('--output-last-message') + 1]).write_text('{"summary":"mock reflection"}')
            return CompletedProcess(argv, 0, '', '')
        with patch('wqb.codex_ai_worker.shutil.which', return_value='fake-codex'), \
             patch('wqb.codex_ai_worker.subprocess.run', side_effect=model) as dispatch:
            with self.assertRaisesRegex(ValueError, 'checkpoint type'):
                run_worker(source, source.parent / 'output.json')
            dispatch.assert_not_called()

    def test_zero_budget_checkpoint_rejects_reflection_type_downgrade(self):
        """Input: advisory checkpoint attached to prepared explanation. Output: no wrapper or model dispatch."""
        from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
        job = self.fixture.loaded(self.fixture.plan(0))
        directory = Path(job['job_dir']) / 'stages/ai'
        cp = append_ai_checkpoint(directory, 'research_reflection', 'Explain', ['input.json'], 'fixture')
        def dispatch(argv, **kwargs):
            """Input: fake wrapper argv. Output: advisory output demonstrating a missing route guard."""
            Path(argv[-1]).write_text('{"summary":"mock reflection"}')
            return CompletedProcess(argv, 0, '', '')
        with patch('wqb.ai_checkpoints.subprocess.run', side_effect=dispatch) as transport:
            result = run_ai_checkpoint(directory, cp.checkpoint_id, ['fake', '{input}', '{output}'])
        self.assertEqual(result['status'], 'failed', result)
        self.assertIn('checkpoint type', result['error'])
        transport.assert_not_called()

    def test_relabelled_manifest_cannot_enable_advisory_worker_dispatch(self):
        """Input: explanation manifest and input both relabeled advisory. Output: failed canonical authentication."""
        from wqb.codex_ai_worker import run_worker
        from wqb.full_semantic_compile import _bytes
        job = self.fixture.loaded(self.fixture.plan(0))
        source = self.worker_input(job, 'relabelled_manifest')
        payload = json.loads(source.read_text())
        payload['checkpoint_type'] = 'research_reflection'
        source.write_text(json.dumps(payload), encoding='utf-8')
        manifest = Path(job['job_dir']) / 'run_manifest.json'
        forged = json.loads(manifest.read_text())
        forged['kind'] = 'research_reflection'
        manifest.write_bytes(_bytes(forged))
        with patch('wqb.codex_ai_worker.subprocess.run', side_effect=AssertionError('model forbidden')) as dispatch:
            with self.assertRaisesRegex(ValueError, 'job kind'):
                run_worker(source, source.parent / 'output.json')
            dispatch.assert_not_called()

    def test_legacy_manifest_labels_cannot_bypass_zero_budget(self):
        """Input: explanation relabeled as either legacy kind. Output: no checkpoint transport before provenance proof."""
        from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
        from wqb.full_semantic_compile import _bytes
        for kind in ('semantic_compile', 'hypothesis_design'):
            with self.subTest(kind=kind):
                job = self.fixture.loaded(self.fixture.plan(0))
                manifest = Path(job['job_dir']) / 'run_manifest.json'
                original = manifest.read_bytes()
                forged = json.loads(original)
                forged['kind'] = 'knowledge_compile'
                if kind == 'hypothesis_design':
                    forged['task_kind'] = kind
                manifest.write_bytes(_bytes(forged))
                directory = Path(job['job_dir']) / 'stages/ai'
                cp = append_ai_checkpoint(directory, kind, 'Explain', ['input.json'], 'fixture')
                def dispatch(argv, **kwargs):
                    """Input: mock transport argv. Output: arbitrary valid advisory output showing premature dispatch."""
                    Path(argv[-1]).write_text('{"summary":"unbudgeted mock"}')
                    return CompletedProcess(argv, 0, '', '')
                try:
                    with patch('wqb.ai_checkpoints.subprocess.run', side_effect=dispatch) as transport:
                        result = run_ai_checkpoint(directory, cp.checkpoint_id, ['fake', '{input}', '{output}'])
                    self.assertEqual(result['status'], 'failed', result)
                    transport.assert_not_called()
                finally:
                    manifest.write_bytes(original)

    def model(self, job, argv, timeout, cancellation_check, cancel_on_pause):
        """Input: loaded job/transport options. Output: complete fake strict model answer."""
        from wqb.full_semantic_execution import full_semantic_output_schema
        self.calls.append(argv)
        self.assertLessEqual(timeout, 10)
        self.assertFalse(cancel_on_pause)
        self.assertFalse(cancellation_check())
        answer = self.fixture.answer(job)
        properties = full_semantic_output_schema(job)['properties']['targets']['items']['properties']['typed_facts']['properties']
        for target in answer['targets']:
            target['typed_facts'] = {key: None for key in properties}
        Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(answer), encoding='utf-8')
        return CompletedProcess(argv, 0, '', '')

    def test_direct_worker_claim_blocks_replay_new_input_and_checkpoint(self):
        """Input: one reservation/direct worker. Output: no second transport via any checkpoint input."""
        from wqb.codex_ai_worker import run_worker
        from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
        from wqb.full_semantic_execution import run_full_semantic_compile
        def execute(**kwargs):
            """Input: reserved job. Output: one answer after probing alternate replay entries."""
            job = kwargs['job']
            source = self.worker_input(job, 'direct')
            with patch('wqb.codex_ai_worker.shutil.which', return_value='fake-codex'), \
                 patch('wqb.ai_checkpoints._run_cancellable', side_effect=lambda *a: self.model(job, *a)):
                answer = run_worker(source, source.parent / 'output.json')
                for path in (source, self.worker_input(job, 'new')):
                    with self.assertRaisesRegex(ValueError, 'claimed'):
                        run_worker(path, path.parent / 'output.json')
                directory = Path(job['job_dir']) / 'stages/ai'
                cp = append_ai_checkpoint(directory, 'full_semantic_explanation', 'Explain', ['input.json'], 'fixture')
                self.assertEqual(run_ai_checkpoint(directory, cp.checkpoint_id,
                    ['fake', '{input}', '{output}'])['status'], 'failed')
            return answer
        result = run_full_semantic_compile(self.fixture.root,
            self.fixture.plan(max_runtime_seconds=10), executor=execute)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(self.calls), 1)

    def test_checkpoint_delegates_only_to_exact_input_and_one_worker(self):
        """Input: checkpoint delegation/token. Output: one child transport; copied/forged tokens reject."""
        from wqb.codex_ai_worker import run_worker
        from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
        from wqb.full_semantic_execution import run_full_semantic_compile
        def execute(**kwargs):
            """Input: reserved job. Output: normal checkpoint-to-worker answer through real claim gates."""
            job = kwargs['job']
            directory = Path(job['job_dir']) / 'stages/ai'
            cp = append_ai_checkpoint(directory, 'full_semantic_explanation', 'Explain', ['input.json'], 'fixture')
            def dispatch(argv, timeout, cancellation_check, cancel_on_pause):
                """Input: wrapper or model transport. Output: fake child/model completion with lineage probes."""
                if '--output-last-message' in argv:
                    return self.model(job, argv, timeout, cancellation_check, cancel_on_pause)
                source, output = Path(argv[-2]), Path(argv[-1])
                payload = json.loads(source.read_text())
                copied = self.worker_input(job, 'copied')
                copied.write_text(json.dumps(payload), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'lineage'):
                    run_worker(copied, copied.parent / 'output.json')
                forged = self.worker_input(job, 'forged')
                payload['full_semantic_dispatch_token'] = True
                forged.write_text(json.dumps(payload), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'token'):
                    run_worker(forged, forged.parent / 'output.json')
                run_worker(source, output)
                with self.assertRaisesRegex(ValueError, 'claimed'):
                    run_worker(source, output)
                return CompletedProcess(argv, 0, '', '')
            with patch('wqb.codex_ai_worker.shutil.which', return_value='fake-codex'), \
                 patch('wqb.ai_checkpoints._run_cancellable', side_effect=dispatch):
                result = run_ai_checkpoint(directory, cp.checkpoint_id, ['fake', '{input}', '{output}'])
            self.assertEqual(result['status'], 'completed', result)
            return dict(summary=result['summary'], targets=result['targets'])
        result = run_full_semantic_compile(self.fixture.root,
            self.fixture.plan(max_runtime_seconds=10), executor=execute)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(self.calls), 1)

    def test_concurrent_direct_workers_compete_for_one_reservation(self):
        """Input: two simultaneous direct workers. Output: one model dispatch, one rejected contender."""
        from wqb.codex_ai_worker import run_worker
        from wqb.full_semantic_execution import run_full_semantic_compile
        def execute(**kwargs):
            """Input: reserved job. Output: one answer after concurrent claim competition."""
            job = kwargs['job']
            sources = [self.worker_input(job, name) for name in ('left', 'right')]
            barrier = Barrier(2)
            def contender(source):
                """Input: temporary input Path. Output: complete answer or expected spent-claim exception."""
                barrier.wait(timeout=10)
                try:
                    return run_worker(source, source.parent / 'output.json')
                except ValueError as exc:
                    return exc
            with patch('wqb.codex_ai_worker.shutil.which', return_value='fake-codex'), \
                 patch('wqb.ai_checkpoints._run_cancellable', side_effect=lambda *a: self.model(job, *a)), \
                 ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(contender, sources))
            self.assertEqual(sum(isinstance(item, ValueError) for item in results), 1, results)
            return next(item for item in results if isinstance(item, dict))
        result = run_full_semantic_compile(self.fixture.root,
            self.fixture.plan(max_runtime_seconds=10), executor=execute)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(self.calls), 1)

    def test_unknown_direct_transport_cannot_replay_or_delegate(self):
        """Input: direct worker with unknown model outcome. Output: spent claim across direct/checkpoint entries."""
        from wqb.codex_ai_worker import run_worker
        from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
        from wqb.full_semantic_execution import run_full_semantic_compile
        def execute(**kwargs):
            """Input: running job. Output: preserved unknown error after blocked replay probes."""
            job = kwargs['job']
            source = self.worker_input(job, 'unknown')
            with patch('wqb.codex_ai_worker.shutil.which', return_value='fake-codex'), \
                 patch('wqb.ai_checkpoints._run_cancellable', side_effect=TimeoutExpired('model', 1)) as dispatch:
                with self.assertRaises(TimeoutExpired):
                    run_worker(source, source.parent / 'output.json')
                with self.assertRaisesRegex(ValueError, 'claimed'):
                    run_worker(source, source.parent / 'output.json')
                directory = Path(job['job_dir']) / 'stages/ai'
                cp = append_ai_checkpoint(directory, 'full_semantic_explanation', 'Explain', ['input.json'], 'fixture')
                self.assertEqual(run_ai_checkpoint(directory, cp.checkpoint_id,
                    ['fake', '{input}', '{output}'])['status'], 'failed')
                self.assertEqual(dispatch.call_count, 1)
            raise RuntimeError('unknown outcome remains unknown')
        result = run_full_semantic_compile(self.fixture.root,
            self.fixture.plan(max_runtime_seconds=10), executor=execute)
        self.assertEqual(result['jobs'][0]['status'], 'outcome_unknown', result)
        repeated = run_full_semantic_compile(self.fixture.root,
            self.fixture.plan(2, max_runtime_seconds=10), executor=lambda **kw: self.fail('replay'))
        self.assertEqual(repeated['model_calls'], 0)

    def test_cancel_and_deadline_stop_owned_process_during_checkpoint_transport(self):
        """Input: cancellation/expiry while child is pending. Output: process tree stopped before returning."""
        from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
        from wqb.full_semantic_execution import run_full_semantic_compile
        for mutation in ('job_cancel', 'plan_cancel', 'durable_cancel', 'deadline'):
            with self.subTest(mutation=mutation):
                plan = self.fixture.plan(max_runtime_seconds=10, rules_version=mutation)
                stopped, checked = [], []
                def execute(**kwargs):
                    """Input: running job. Output: answer after exercising real cancellation supervisor."""
                    job = kwargs['job']
                    directory = Path(job['job_dir']) / 'stages/ai'
                    cp = append_ai_checkpoint(directory, 'full_semantic_explanation', 'Explain', ['input.json'], 'fixture')
                    clock = [time.time()]
                    process = unittest.mock.Mock()
                    def communicate(**options):
                        """Input: bounded communicate options. Output: pending timeout after durable Stop/expiry."""
                        if mutation == 'deadline':
                            clock[0] = kwargs['deadline']
                        elif mutation == 'job_cancel':
                            (Path(job['job_dir']) / 'control.json').write_text('{"cancelled":true}')
                        else:
                            plan_dir = (self.fixture.root / plan['plan_path']).parent
                            filename = 'execution_state.json' if mutation == 'durable_cancel' else 'control.json'
                            value = dict(status='cancelled') if mutation == 'durable_cancel' else dict(cancelled=True)
                            (plan_dir / filename).write_text(json.dumps(value))
                        raise TimeoutExpired('fake worker', options['timeout'])
                    process.communicate.side_effect = communicate
                    with patch('wqb.ai_checkpoints.subprocess.Popen', return_value=process), \
                         patch('wqb.ai_checkpoints.stop_worker_tree', side_effect=lambda proc: stopped.append(proc)), \
                         patch('wqb.full_semantic_execution.time.time', side_effect=lambda: clock[0]):
                        result = run_ai_checkpoint(directory, cp.checkpoint_id, ['fake', '{input}', '{output}'])
                    self.assertEqual(result['status'], 'cancelled', result)
                    self.assertEqual(stopped, [process])
                    checked.append(True)
                    return self.fixture.answer(job)
                run_full_semantic_compile(self.fixture.root, plan, executor=execute)
                self.assertEqual(len(stopped), 1)
                self.assertEqual(checked, [True])


if __name__ == '__main__':
    unittest.main()
