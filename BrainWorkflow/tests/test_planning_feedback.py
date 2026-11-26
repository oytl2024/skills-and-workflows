"""Returned invalid drafts are corrected locally; unknown process outcomes are not replayed."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class PlanningFeedbackTests(unittest.TestCase):
    def test_nonzero_exit_saves_bounded_fault_without_retry(self):
        from wqb import codex_ai_worker as worker
        with tempfile.TemporaryDirectory() as directory, patch('wqb.ai_checkpoints._run_cancellable',
                return_value=subprocess.CompletedProcess([], 7, 'x' * 5000, 'failed')) as dispatch:
            with self.assertRaisesRegex(RuntimeError, 'exited 7'):
                worker._run_planning_feedback(['fake-only'], Path(directory) / 'answer.json',
                    lambda _: self.fail('no returned draft'), lambda: None)
            fault = json.loads((Path(directory) / 'planning_fault.json').read_text(encoding='utf-8'))
            self.assertEqual(fault['exit_code'], 7)
            self.assertEqual(len(fault['stdout_tail']), 2000)
            self.assertEqual(dispatch.call_count, 1)

    def test_known_empty_plan_does_not_send_maintenance_notification(self):
        from types import SimpleNamespace
        from wqb import console_start
        with tempfile.TemporaryDirectory() as temporary:
            runs = Path(temporary).absolute()
            row = dict(request_id='original', status='blocked', retrieval_design_task=dict(
                directory=str(runs/'task'), input_sha256='digest'))
            console_start._write_request(runs, row)
            task = dict(status='blocked', answer={}, reason='model_returned_no_plan: planning_incomplete',
                input_sha256='digest', identity=dict(config=dict(retrieval_owner=dict(
                    runs_root=str(runs), request_id='original'))))
            with patch('wqb.retrieval_research_planning.read_design_task', return_value=task), \
                    patch('wqb.preflight_notifications.notify_preflight_blocker') as notify:
                result = console_start._notify_blocked_request(SimpleNamespace(runs_root=runs), row)
            notify.assert_not_called()
            self.assertEqual(result['issues'][0]['code'], 'planning_incomplete')
            self.assertEqual(result['notification']['status'], 'not_required')
            self.assertEqual(result['error'], '')

    def test_invalid_returned_plan_receives_diagnostics_then_succeeds(self):
        from wqb import codex_ai_worker as worker
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'answer.json'
            prompts = []
            def execute(argv, timeout_seconds, cancellation_check, cancel_on_pause):
                self.assertFalse(cancel_on_pause)
                cancellation_check()
                prompts.append(argv[-1])
                output.write_text(json.dumps(dict(summary='draft')), encoding='utf-8')
                return subprocess.CompletedProcess(argv, 0, '', '')
            def validate(answer):
                return dict(valid=len(prompts) == 2, diagnostics=[dict(message='tree node lacks child')])
            with patch('wqb.ai_checkpoints._run_cancellable', side_effect=execute):
                result = worker._run_planning_feedback(['codex', 'exec', 'initial'], output, validate, lambda: None)
            self.assertEqual(result['summary'], 'draft')
            self.assertEqual(len(prompts), 2)
            self.assertIn('tree node lacks child', prompts[1])

    def test_transport_failure_is_not_replayed(self):
        from wqb import codex_ai_worker as worker
        with tempfile.TemporaryDirectory() as directory, patch('wqb.ai_checkpoints._run_cancellable',
                side_effect=subprocess.TimeoutExpired('codex', 1)) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                worker._run_planning_feedback(['codex', 'exec', 'initial'], Path(directory)/'a.json',
                    lambda _: dict(valid=False), lambda: None)
            self.assertEqual(run.call_count, 1)
            fault = json.loads((Path(directory) / 'planning_fault.json').read_text(encoding='utf-8'))
            self.assertEqual(fault['exception_type'], 'TimeoutExpired')
            self.assertEqual(fault['outcome'], 'unknown')
            self.assertNotIn('argv', fault)

    def test_exhausted_known_drafts_return_explicit_empty_plan(self):
        from wqb import codex_ai_worker as worker
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'a.json'
            def execute(argv, *args):
                output.write_text('{}')
                return subprocess.CompletedProcess(argv, 0, '', '')
            with patch('wqb.ai_checkpoints._run_cancellable', side_effect=execute) as run:
                result = worker._run_planning_feedback(['codex', 'exec', 'initial'], output,
                    lambda _: dict(valid=False, diagnostics=['invalid tree']), lambda: None)
            self.assertEqual(run.call_count, worker.MAX_PLANNING_DRAFTS)
            self.assertEqual(result['designs'], [])
            self.assertIn('planning_incomplete', result['summary'])
