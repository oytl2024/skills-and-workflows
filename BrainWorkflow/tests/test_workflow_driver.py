import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wqb.runtime_control import RuntimePaused, read_runtime_control, request_runtime_state, check_submission_allowed, submission_request_gate
from wqb.workflow_driver import run_workflow_driver, resolve_ai_executor_argv


class WorkflowDriverTests(unittest.TestCase):
    def test_nonrecoverable_repair_receipt_is_explicit_blocker_not_no_progress(self):
        from wqb.workflow_driver import _repair_cooldown_result
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            path = run / 'stages/repair/repair_execution.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'status': 'paused', 'recovery_eligible': False,
                                       'blocker': 'Repair planning failed: bounded context'}))
            result = _repair_cooldown_result(run, {'current_stage': 'repair', 'status': 'paused',
                                                  'pause_reason': 'Repair planning failed: bounded context'}, 'now')
            self.assertEqual(result['next_action'], 'maintenance-blocker')

    def test_start_receipt_keeps_its_own_revision_after_concurrent_pause(self):
        from wqb import runtime_control

        with tempfile.TemporaryDirectory() as tmp:
            original_guard = runtime_control.json_lock_transition_guard
            inject_pause = [True]

            class PauseAfterRelease:
                def __init__(self, path, *args, **kwargs):
                    self.path = Path(path)
                    self.guard = original_guard(path, *args, **kwargs)

                def __enter__(self):
                    return self.guard.__enter__()

                def __exit__(self, *args):
                    result = self.guard.__exit__(*args)
                    if self.path.name == "control_intent" and inject_pause[0]:
                        inject_pause[0] = False
                        request_runtime_state(tmp, "paused")
                    return result

            with patch.object(runtime_control, "json_lock_transition_guard", side_effect=PauseAfterRelease):
                start_receipt = request_runtime_state(tmp, "paused", enable_live_api=True)
            current = read_runtime_control(tmp)
            self.assertFalse(inject_pause[0])
            self.assertNotEqual(start_receipt["request_revision"], current["request_revision"])
            with self.assertRaisesRegex(ValueError, "stale runtime intent"):
                request_runtime_state(tmp, "running", expected_revision=start_receipt["request_revision"])

    def test_delayed_resume_cannot_overwrite_newer_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = request_runtime_state(tmp, "paused", enable_live_api=True)
            old_revision = control["request_revision"]
            newer_pause = request_runtime_state(tmp, "paused")

            with self.assertRaisesRegex(ValueError, "stale runtime intent"):
                request_runtime_state(tmp, "running", expected_revision=old_revision)

            current = read_runtime_control(tmp)
            self.assertEqual(current["desired_state"], "paused")
            self.assertEqual(current["request_revision"], newer_pause["request_revision"])
            resumed = request_runtime_state(tmp, "running", expected_revision=newer_pause["request_revision"])
            self.assertEqual(resumed["desired_state"], "running")

    def test_pause_waits_for_in_flight_simulation_post_before_acknowledging(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            request_runtime_state(run, "running", enable_live_api=True)
            finished = threading.Event()

            def pause():
                request_runtime_state(run, "paused")
                finished.set()

            with submission_request_gate(run):
                thread = threading.Thread(target=pause)
                thread.start()
                deadline = time.monotonic() + 2
                while read_runtime_control(run).get("desired_state") != "paused" and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(read_runtime_control(run)["desired_state"], "paused")
                self.assertFalse(finished.is_set())
            thread.join(timeout=2)
            self.assertTrue(finished.is_set())

    def test_codex_executor_is_explicit_and_medium_worker_adapter(self):
        self.assertEqual(resolve_ai_executor_argv({}), [])
        argv = resolve_ai_executor_argv({"ai_executor": "codex"})
        self.assertEqual(argv[1:4], ["-m", "wqb.codex_ai_worker", "{input}"])
        self.assertEqual(argv[-1], "{output}")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'run-1'
        self.run.mkdir()
        self.paths = SimpleNamespace(run_root=self.root)
        self.current = datetime(2026, 9, 5, tzinfo=timezone.utc)

    def now(self):
        return self.current.isoformat()

    def sleep(self, seconds):
        self.current += timedelta(seconds=seconds)

    def status(self):
        return {'active': True, 'run_dir': str(self.run), 'run_id': 'run-1', 'status': 'running'}

    def test_drives_multiple_steps_and_stops_at_approval(self):
        request_runtime_state(self.run, 'running', enable_live_api=True)
        steps = iter([
            {**self.status(), 'current_stage': 'schedule', 'next_action': 'workflow-auto-continue'},
            {**self.status(), 'current_stage': 'scout_seed', 'next_action': 'workflow-auto-continue'},
            {**self.status(), 'status': 'waiting_for_user', 'waiting_for_user': True},
        ])
        calls = []
        def step():
            calls.append(1)
            return next(steps)
        result = run_workflow_driver(self.paths, {}, step=step, status_reader=self.status, now_func=self.now, sleep_func=self.sleep)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result['runtime_status'], 'waiting_for_user')

    def test_driver_schedules_selected_ai_checkpoint_after_stage_step(self):
        request_runtime_state(self.run, 'running', enable_live_api=False)
        (self.run / 'all_alphas.jsonl').write_text('{}\n', encoding='utf-8')
        results = iter([
            {**self.status(), 'current_stage': 'repair', 'next_action': 'workflow-auto-continue'},
            {**self.status(), 'status': 'waiting_for_user', 'waiting_for_user': True},
        ])
        with patch('wqb.workflow_driver.schedule_run_checkpoint') as checkpoint:
            run_workflow_driver(self.paths, {'ai_executor_argv': ['worker', '{input}', '{output}']},
                                step=lambda: next(results), status_reader=self.status,
                                now_func=self.now, sleep_func=self.sleep)
        self.assertEqual(checkpoint.call_count, 2)
        self.assertEqual(checkpoint.call_args_list[0].args[0], self.run)
        self.assertEqual(checkpoint.call_args_list[0].args[3], ['worker', '{input}', '{output}'])

    def test_pause_is_persisted_and_prevents_next_action(self):
        request_runtime_state(self.run, 'paused')
        calls = []
        result = run_workflow_driver(self.paths, {}, step=lambda: calls.append(1), status_reader=self.status, now_func=self.now, sleep_func=self.sleep)
        self.assertEqual(calls, [])
        self.assertEqual(result['runtime_status'], 'paused')

    def test_cooldown_auto_wakes_without_click(self):
        request_runtime_state(self.run, 'running', enable_live_api=True)
        wake = (self.current + timedelta(seconds=3)).isoformat()
        steps = iter([
            {**self.status(), 'next_action': 'rate-limit-wait', 'source_bridge': {'metadata': {'retry_at': wake}}},
            {**self.status(), 'status': 'completed', 'next_action': ''},
        ])
        result = run_workflow_driver(self.paths, {}, step=lambda: next(steps), status_reader=self.status, now_func=self.now, sleep_func=self.sleep)
        self.assertEqual(result['runtime_status'], 'completed')
        self.assertGreaterEqual(self.current.second, 3)

    def test_rate_recovery_preserves_429_count_and_uses_one_budget_credit(self):
        request_runtime_state(self.run, 'running', enable_live_api=True)
        source = self.root / 'source'
        source.mkdir()
        wake = (self.current + timedelta(seconds=2)).isoformat()
        (source / 'rate_limit_state.json').write_text(json.dumps({'status': 'cooldown',
            'updated_at': self.now(), 'retry_at': wake, 'consecutive_429_count': 3, 'attempt_count': 3}))
        calls = []

        def step():
            calls.append(1)
            if len(calls) == 1:
                return {**self.status(), 'next_action': 'maintenance-blocker', 'source_bridge': {
                    'source_run_dir': str(source), 'metadata': {'retry_at': wake, 'operator_acknowledgement_required': True}}}
            state = json.loads((source / 'rate_limit_state.json').read_text())
            self.assertEqual(state['consecutive_429_count'], 3)
            self.assertIn('bounded_retry', state)
            return {**self.status(), 'status': 'completed'}

        result = run_workflow_driver(self.paths, {}, step=step, status_reader=self.status, now_func=self.now, sleep_func=self.sleep)
        self.assertEqual(result['runtime_status'], 'completed')
        self.assertEqual(read_runtime_control(self.run)['recovery_attempts'], 1)

    def test_runtime_budget_expiring_during_cooldown_never_authorizes_retry(self):
        request_runtime_state(self.run, 'running', enable_live_api=True, max_runtime_seconds=2)
        wake = (self.current + timedelta(seconds=100)).isoformat()
        result = {**self.status(), 'next_action': 'maintenance-blocker', 'source_bridge': {
            'source_run_dir': str(self.root / 'source'), 'metadata': {'retry_at': wake, 'operator_acknowledgement_required': True}}}
        with patch('wqb.rate_limit_state.authorize_bounded_retry') as authorize:
            summary = run_workflow_driver(self.paths, {}, step=lambda: result, status_reader=self.status, now_func=self.now, sleep_func=self.sleep)
        authorize.assert_not_called()
        self.assertEqual(summary['runtime_reason'], 'runtime_budget_exhausted')

    def test_repair_cooldown_uses_receipt_and_resumes_without_click(self):
        request_runtime_state(self.run, 'running', enable_live_api=True)
        directory = self.run / 'stages' / 'repair'
        directory.mkdir(parents=True)
        wake = (self.current + timedelta(seconds=3)).isoformat()
        (directory / 'repair_execution.json').write_text(json.dumps({
            'status': 'paused', 'recovery_eligible': True, 'rate_limit_retry_at': wake,
            'rate_limit_source_run_dir': str(self.run / 'repair-source'),
        }), encoding='utf-8')
        steps = iter([
            {**self.status(), 'status': 'paused', 'current_stage': 'repair', 'next_action': 'workflow-resume'},
            {**self.status(), 'status': 'completed', 'next_action': ''},
        ])
        result = run_workflow_driver(self.paths, {}, step=lambda: next(steps),
                                     status_reader=self.status, now_func=self.now, sleep_func=self.sleep)
        self.assertEqual(result['runtime_status'], 'completed')
        self.assertGreaterEqual(self.current.second, 3)

    def test_repair_progress_wait_wakes_without_rate_lease_or_no_progress_case(self):
        request_runtime_state(self.run, 'running', enable_live_api=True)
        directory = self.run / 'stages/repair'
        directory.mkdir(parents=True)
        wake = (self.current + timedelta(seconds=3)).isoformat()
        (directory / 'repair_execution.json').write_text(json.dumps({
            'status': 'paused', 'recovery_eligible': True, 'progress_retry_at': wake, 'blocker': 'progress pending',
            'progress_source_run_dir': str(self.run / 'repair-source')}))
        steps = iter([{**self.status(), 'status': 'paused', 'current_stage': 'repair', 'pause_reason': 'progress pending'},
                      {**self.status(), 'status': 'completed', 'next_action': ''}])
        with patch('wqb.rate_limit_state.authorize_bounded_retry') as authorize:
            result = run_workflow_driver(self.paths, {}, step=lambda: next(steps),
                status_reader=self.status, now_func=self.now, sleep_func=self.sleep)
        self.assertEqual(result['runtime_status'], 'completed')
        authorize.assert_not_called()
        self.assertFalse(read_runtime_control(self.run).get('recovery_case'))

    def test_worker_status_never_overwrites_pause_request(self):
        request_runtime_state(self.run, 'running', enable_live_api=True)
        def step():
            request_runtime_state(self.run, 'paused')
            return {**self.status(), 'next_action': 'workflow-auto-continue'}
        run_workflow_driver(self.paths, {}, step=step, status_reader=self.status, now_func=self.now, sleep_func=self.sleep)
        self.assertEqual(read_runtime_control(self.run)['desired_state'], 'paused')

    def test_noop_loop_has_explicit_bound(self):
        request_runtime_state(self.run, 'running')
        result = run_workflow_driver(self.paths, {'runtime_no_progress_limit': 2}, step=lambda: self.status(), status_reader=self.status, now_func=self.now, sleep_func=self.sleep)
        self.assertEqual(result['runtime_status'], 'blocked')
        self.assertIn('no_progress', result['runtime_reason'])
        recovery = read_runtime_control(self.run).get('recovery_case', {})
        self.assertEqual(recovery.get('status'), 'awaiting_maintenance_confirmation')
        self.assertFalse(recovery.get('patch_execution_allowed'))

    def test_confirmation_reference_is_persisted_before_dispatch(self):
        request_runtime_state(self.run, 'running')

        def check_persisted(run, case, now):
            self.assertEqual(read_runtime_control(run).get('recovery_case', {}).get('case_id'), case['case_id'])
            return case

        with patch('wqb.workflow_driver.dispatch_notification', side_effect=check_persisted):
            run_workflow_driver(self.paths, {'runtime_no_progress_limit': 1}, step=lambda: self.status(),
                                status_reader=self.status, now_func=self.now, sleep_func=self.sleep)

    def test_confirmation_published_during_lock_acquisition_prevents_step(self):
        from wqb.recovery_cases import ensure_recovery_case, classify_blocker, advance_scripted_recovery
        from wqb.runtime_control import update_runtime_status
        from wqb.source_run_lock import acquire_source_run_lock

        request_runtime_state(self.run, 'running')

        def acquire_and_publish(*args, **kwargs):
            lock = acquire_source_run_lock(*args, **kwargs)
            case = ensure_recovery_case(self.run, classify_blocker({'next_action': 'no_progress_detected'}), self.now())
            case = advance_scripted_recovery(self.run, case, {}, self.now())
            update_runtime_status(self.run, recovery_case=case)
            return lock

        step = unittest.mock.Mock(return_value={**self.status(), 'status': 'completed'})
        with patch('wqb.workflow_driver.acquire_source_run_lock', side_effect=acquire_and_publish):
            result = run_workflow_driver(self.paths, {}, step=step, status_reader=self.status, now_func=self.now, sleep_func=self.sleep)
        step.assert_not_called()
        self.assertEqual(result['runtime_reason'], 'maintenance_confirmation_required')

    def test_pause_guard_preserves_planned_work_before_post(self):
        request_runtime_state(self.run, 'paused', enable_live_api=True)
        with patch.dict(os.environ, {'BRAIN_WORKFLOW_CONTROL_PATH': str(self.run)}):
            with self.assertRaises(RuntimePaused):
                check_submission_allowed(5)
        self.assertEqual(read_runtime_control(self.run).get('simulation_attempts', 0), 0)

    def test_budget_is_durable_across_resume(self):
        request_runtime_state(self.run, 'running', enable_live_api=True, max_simulations=5)
        with patch.dict(os.environ, {'BRAIN_WORKFLOW_CONTROL_PATH': str(self.run)}):
            check_submission_allowed(5)
            request_runtime_state(self.run, 'paused')
            request_runtime_state(self.run, 'running')
            with self.assertRaisesRegex(RuntimePaused, 'budget'):
                check_submission_allowed(1)
        self.assertEqual(read_runtime_control(self.run)['simulation_attempts'], 5)

    def test_invalid_control_fails_closed(self):
        (self.run / 'runtime_control.json').write_text('{broken', encoding='utf-8')
        with patch.dict(os.environ, {'BRAIN_WORKFLOW_CONTROL_PATH': str(self.run)}):
            with self.assertRaises(RuntimePaused):
                check_submission_allowed(1)
