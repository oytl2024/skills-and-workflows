"""Initial planning adapter regressions; every subprocess is an offline fake."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

from tests.test_initial_research_planning import InitialResearchPlanningTests
from wqb import ai_checkpoints, codex_ai_worker, initial_research_planning as planning
from wqb.exploration_eligibility import certify_exploration_resources, _digest


class InitialModelWorkerTests(unittest.TestCase):
    def setUp(self):
        """Input: test instance. Output: None; reuse isolated certified fixture, never real knowledge."""
        fixture = InitialResearchPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.run = fixture.run
        certificate = certify_exploration_resources(self.run, fixture.knowledge,
            fixture.resources, fixture.scope)
        brief = planning._brief(fixture.resources, fixture.manifest, certificate, [], fixture.policy)
        self.task = dict(schema_version=1, status='running', input_sha256='a' * 64,
            manifest=fixture.manifest, certificate=certificate, brief=brief)
        self.save_task()
        self.config = dict(ai_executor='codex')
        self.answer = deepcopy(fixture.answer)

    def save_task(self):
        """Input: self.task dict. Output: None; write test-only durable coordinator evidence."""
        planning._save_task(self.run / planning.TASK_PATH, self.task)

    def adapter(self):
        """Input: fixture configuration. Output: real callable factory under test."""
        from wqb.initial_model_worker import create_initial_model_runner
        return create_initial_model_runner(self.run, self.config)

    def fake_model(self, argv, **kwargs):
        """Input: fake Codex argv/options. Output: CompletedProcess; inspect readonly wire contract."""
        self.assertIn('read-only', argv)
        self.assertIn('model_reasoning_effort=medium', argv)
        self.prompt = argv[-1]
        self.assertLess(len(self.prompt.encode('utf-8')), 32000)
        schema = json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text(encoding='utf-8'))
        self.assertEqual(schema, self.task['brief']['output_schema'])
        Path(argv[argv.index('--output-last-message') + 1]).write_text(
            json.dumps(self.answer), encoding='utf-8')
        return subprocess.CompletedProcess(argv, 0, '', '')

    def fake_process(self, argv, **kwargs):
        """Input: checkpoint subprocess argv/options. Output: mocked process executing worker in-process."""
        process = Mock(returncode=0)
        def communicate(timeout=None):
            """Input: timeout number. Output: stdout/stderr tuple; run only offline worker code."""
            codex_ai_worker.run_worker(Path(argv[-2]), Path(argv[-1]))
            return '', ''
        process.communicate.side_effect = communicate
        return process

    def execute(self, runner=None):
        """Input: optional bound runner callable. Output: strict answer dict through both real worker layers."""
        with patch('wqb.ai_checkpoints.subprocess.Popen', side_effect=self.fake_process), patch(
                'wqb.codex_ai_worker.shutil.which', return_value='fake-codex'), patch(
                'wqb.codex_ai_worker.subprocess.run', side_effect=self.fake_model):
            return (runner or self.adapter())(deepcopy(self.task['brief']))

    def test_factory_preserves_full_answer_while_runtime_initially_paused(self):
        (self.run / 'runtime/control.json').write_text('{"desired_state":"paused"}', encoding='utf-8')
        self.assertEqual(self.execute(), self.answer)
        rows = ai_checkpoints.load_ai_checkpoints(self.run / 'stages/ai')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['checkpoint_type'], 'initial_research_plan')
        self.assertEqual(rows[0]['tree'], self.answer['tree'])
        self.assertEqual(rows[0]['designs'], self.answer['designs'])

    def test_projection_references_full_task_and_never_inlines_raw(self):
        from wqb.initial_model_worker import initial_model_projection
        projection = initial_model_projection(self.run)
        rendered = json.dumps(projection)
        self.assertNotIn(next(iter(self.task['brief']['source_texts'].values())), rendered)
        self.assertIn('/brief/source_texts/', rendered)
        self.assertIn(hashlib.sha256((self.run / planning.TASK_PATH).read_bytes()).hexdigest(), rendered)
        self.execute()
        self.assertIn('no live vault', self.prompt)
        self.assertIn('no formulas', self.prompt)

    def test_changed_callback_brief_rejected_before_subprocess(self):
        runner = self.adapter()
        brief = deepcopy(self.task['brief'])
        brief['plan_depth'] += 1
        with patch('wqb.ai_checkpoints.subprocess.Popen') as child:
            with self.assertRaises(ValueError):
                runner(brief)
            child.assert_not_called()

    def test_task_manifest_and_certificate_tampering_fail_closed(self):
        for target in ('task', 'manifest', 'certificate'):
            with self.subTest(target=target):
                path = (self.run / planning.TASK_PATH if target == 'task' else
                    self.run / 'run_manifest.json' if target == 'manifest' else
                    self.run / 'runtime/exploration/resources' / (self.task['certificate']['content_sha256'] + '.json'))
                original = path.read_bytes()
                try:
                    path.write_text('{}', encoding='utf-8')
                    with patch('wqb.ai_checkpoints.subprocess.Popen') as child:
                        with self.assertRaises((ValueError, KeyError)):
                            self.adapter()(self.task['brief'])
                        child.assert_not_called()
                finally:
                    path.write_bytes(original)

    def test_rehashed_wrong_source_or_schema_rejected(self):
        for key in ('source_texts', 'output_schema'):
            with self.subTest(key=key):
                original = deepcopy(self.task)
                try:
                    if key == 'source_texts':
                        name = next(iter(self.task['brief'][key]))
                        self.task['brief'][key][name] += 'invented'
                    else:
                        self.task['brief'][key] = dict(type='object')
                    self.save_task()
                    with self.assertRaises(ValueError):
                        self.adapter()(self.task['brief'])
                finally:
                    self.task = original
                    self.save_task()

    def test_second_factory_call_never_dispatches_again(self):
        self.execute()
        with patch('wqb.ai_checkpoints.subprocess.Popen') as child:
            with self.assertRaisesRegex(ValueError, 'replay|already|checkpoint'):
                self.adapter()(self.task['brief'])
            child.assert_not_called()

    def test_unknown_checkpoint_never_replays_even_through_checkpoint_api(self):
        checkpoint = ai_checkpoints.append_ai_checkpoint(self.run / 'stages/ai',
            'initial_research_plan', 'offline', [planning.TASK_PATH], '2026-10-23')
        ai_checkpoints._append_checkpoint_event(self.run / 'stages/ai',
            dict(checkpoint_id=checkpoint.checkpoint_id, status='unknown'))
        with patch('wqb.ai_checkpoints.subprocess.Popen') as child:
            result = ai_checkpoints.run_ai_checkpoint(self.run / 'stages/ai', checkpoint.checkpoint_id,
                ['fake', '{input}', '{output}'])
            self.assertNotEqual(result['status'], 'completed')
            child.assert_not_called()

    def test_invalid_output_is_not_reduced_to_successful_summary(self):
        for change in ('missing_tree', 'extra_key', 'wrong_type'):
            with self.subTest(change=change):
                # A fresh checkpoint API attempt, not a coordinator/model replay.
                checkpoint = ai_checkpoints.append_ai_checkpoint(self.run / 'stages/ai',
                    'initial_research_plan', 'offline', [planning.TASK_PATH], '2026-10-23')
                output = deepcopy(self.answer)
                if change == 'missing_tree':
                    output.pop('tree')
                elif change == 'extra_key':
                    output['expression'] = 'invented'
                else:
                    output['designs'] = 'not designs'
                def reply(argv, **kwargs):
                    """Input: fake executor argv. Output: completed result carrying intentionally invalid JSON."""
                    Path(argv[-1]).write_text(json.dumps(output), encoding='utf-8')
                    return subprocess.CompletedProcess(argv, 0, '', '')
                with patch('wqb.ai_checkpoints.subprocess.run', side_effect=reply):
                    result = ai_checkpoints.run_ai_checkpoint(self.run / 'stages/ai', checkpoint.checkpoint_id,
                        ['fake', '{input}', '{output}'])
                self.assertEqual(result['status'], 'failed')

    def test_planning_cancelled_before_dispatch(self):
        control = self.run / 'runtime/initial_research_planning/control.json'
        control.write_text('{"cancelled":true}', encoding='utf-8')
        with patch('wqb.ai_checkpoints.subprocess.Popen') as child:
            with self.assertRaises((RuntimeError, ValueError)):
                self.adapter()(self.task['brief'])
            child.assert_not_called()

    def test_pending_start_stop_or_replacement_cancels_bound_runner(self):
        path = self.run.parent / 'console_start/request.json'
        path.parent.mkdir()
        original = dict(status='preparing', request_id='request-one')
        for update in (dict(status='cancelled', request_id='request-one'),
                       dict(status='preparing', request_id='request-two')):
            path.write_text(json.dumps(original), encoding='utf-8')
            runner = self.adapter()
            path.write_text(json.dumps(update), encoding='utf-8')
            with patch('wqb.ai_checkpoints.subprocess.Popen') as child:
                with self.assertRaises((RuntimeError, ValueError)):
                    runner(self.task['brief'])
                child.assert_not_called()

    def test_compatible_certified_template_receipt_remains_available(self):
        """Input: actual fixture compiler receipt. Output: full answer; retain compatible template context."""
        from wqb.exploration_eligibility import validate_exploration
        receipt = validate_exploration(self.fixture.design, self.fixture.resources, self.fixture.scope)
        self.task['brief'] = planning._brief(self.fixture.resources, self.fixture.manifest,
            self.task['certificate'], [receipt], self.fixture.policy)
        self.save_task()
        self.assertEqual(self.execute(), self.answer)

    def test_group_stop_or_changed_planning_intent_cancels_model(self):
        initial = dict(group_id='fixture-group', request_revision='before', desired_state='paused')
        changed = dict(initial, request_revision='after')
        with patch('wqb.research_group.group_for_run', side_effect=[initial, changed]), patch(
                'wqb.ai_checkpoints.subprocess.Popen') as child:
            runner = self.adapter()
            with self.assertRaises(RuntimeError):
                runner(self.task['brief'])
            child.assert_not_called()

    def test_large_certified_raw_is_referenced_without_prompt_truncation(self):
        """Input: certified 50KB raw JSON fixture. Output: unchanged full answer with a sub-32KB prompt."""
        name, text = next(iter(self.fixture.resources['source_texts'].items()))
        padded = text + ' ' * 50000
        old_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        new_hash = hashlib.sha256(padded.encode('utf-8')).hexdigest()
        def replace(value):
            """Input: JSON value. Output: copied value with only exact raw text/hash identities replaced."""
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace(item) for item in value]
            if value == text:
                return padded
            return new_hash if value == old_hash else value
        resources = replace(self.fixture.resources)
        (self.fixture.knowledge / name).write_text(padded, encoding='utf-8')
        (self.fixture.knowledge / 'machine/source_index.jsonl').write_text(''.join(
            json.dumps(row) + '\n' for row in resources['source_index'].values()), encoding='utf-8')
        certificate = certify_exploration_resources(self.run, self.fixture.knowledge, resources, self.fixture.scope)
        self.task.update(certificate=certificate, brief=planning._brief(resources, self.fixture.manifest,
            certificate, [], self.fixture.policy))
        self.save_task()
        self.assertEqual(self.execute(), self.answer)
        self.assertNotIn(padded, self.prompt)

    def test_raw_changed_after_binding_rejects_dispatch(self):
        """Input: bound runner and changed raw fixture bytes. Output: rejection without subprocess."""
        runner = self.adapter()
        name = next(iter(self.fixture.resources['source_texts']))
        (self.fixture.knowledge / name).write_text('{}', encoding='utf-8')
        with patch('wqb.ai_checkpoints.subprocess.Popen') as child:
            with self.assertRaises(ValueError):
                runner(self.task['brief'])
            child.assert_not_called()

    def test_direct_checkpoint_rejects_tampered_task_before_executor(self):
        """Input: pending checkpoint with corrupt coordinator task. Output: failed status without executor."""
        checkpoint = ai_checkpoints.append_ai_checkpoint(self.run / 'stages/ai',
            'initial_research_plan', 'offline', [planning.TASK_PATH], '2026-10-23')
        (self.run / planning.TASK_PATH).write_text('{}', encoding='utf-8')
        with patch('wqb.ai_checkpoints.subprocess.run') as child:
            result = ai_checkpoints.run_ai_checkpoint(self.run / 'stages/ai', checkpoint.checkpoint_id,
                ['fake', '{input}', '{output}'])
            self.assertEqual(result['status'], 'failed')
            child.assert_not_called()

    def test_stop_during_model_cancels_checkpoint_and_discards_output(self):
        """Input: Stop arriving during fake model execution. Output: cancelled checkpoint, no accepted answer."""
        original = self.fake_model
        def stop(argv, **kwargs):
            """Input: fake argv/options. Output: process result after persisting planning cancellation."""
            result = original(argv, **kwargs)
            (self.run / 'runtime/initial_research_planning/control.json').write_text(
                '{"cancelled":true}', encoding='utf-8')
            return result
        with patch('wqb.ai_checkpoints.subprocess.Popen', side_effect=self.fake_process), patch(
                'wqb.codex_ai_worker.shutil.which', return_value='fake-codex'), patch(
                'wqb.codex_ai_worker.subprocess.run', side_effect=stop), patch(
                'wqb.ai_checkpoints.stop_worker_tree'):
            with self.assertRaises(RuntimeError):
                self.adapter()(self.task['brief'])
        self.assertEqual(ai_checkpoints.load_ai_checkpoints(self.run / 'stages/ai')[0]['status'], 'cancelled')
