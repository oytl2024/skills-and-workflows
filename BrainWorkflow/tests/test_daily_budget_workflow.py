import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wqb import daily_simulation_budget as budget
from wqb.runtime_control import check_submission_allowed, read_runtime_control, request_runtime_state
from wqb.workflow_driver import run_workflow_driver


class DailyBudgetWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'runs'
        self.run = self.root / 'mission'
        self.run.mkdir(parents=True)
        (self.run / 'run_manifest.json').write_text(json.dumps({'run_id': self.run.name}))
        self.current = datetime(2026, 10, 21, 15, 59, 58, tzinfo=timezone.utc)
        self.clock = patch.object(budget, '_clock', side_effect=lambda value: (
            datetime.fromisoformat(value.replace('Z', '+00:00')) if value else self.current).astimezone(budget.SHANGHAI))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        control = request_runtime_state(self.run, 'paused', enable_live_api=True)
        from wqb.runtime_control import update_runtime_status
        update_runtime_status(self.run, simulation_attempts=0)
        budget.activate_daily_policy(self.run, control['request_revision'], 'offline test')
        budget.charge_daily_budget(self.run, 4000, 'spent')
        request_runtime_state(self.run, 'running')
        self.calls = 0

    def now(self):
        """Input: fixture clock. Output: ISO str. Supply a deterministic runtime clock."""
        return self.current.isoformat()

    def sleep(self, seconds):
        """Input: float seconds. Output: None. Advance local time without sleeping or platform access."""
        self.current += timedelta(seconds=seconds)

    def status(self):
        """Input: local fixture. Output: status dict. Expose the unchanged mission identity."""
        return {'active': True, 'run_dir': str(self.run), 'current_stage': 'repair', 'status': 'running'}

    def step(self):
        """Input: local fixture. Output: result dict. Charge one simulated submission without a client."""
        self.calls += 1
        check_submission_allowed(1)
        return {**self.status(), 'status': 'waiting_for_user', 'waiting_for_user': True}

    def drive(self, sleep=None):
        """Input: optional sleeper callable. Output: driver result dict. Run existing driver entirely offline."""
        return run_workflow_driver(SimpleNamespace(run_root=self.root), {}, step=self.step,
            status_reader=self.status, now_func=self.now, sleep_func=sleep or self.sleep)

    def test_midnight_wait_resumes_without_model_polling_or_refunding(self):
        with patch('wqb.workflow_driver.schedule_run_checkpoint') as model:
            result = self.drive()
        self.assertEqual(result['runtime_status'], 'waiting_for_user')
        self.assertEqual(self.calls, 2)
        self.assertEqual(model.call_count, 1)
        row = budget.read_daily_budget(self.run)
        self.assertEqual((row['used'], row['lifetime_attempts']), (1, 4001))
        self.assertFalse((self.run / 'runtime/recovery').exists())

    def test_stop_during_daily_wait_wins(self):
        def stop(seconds):
            """Input: seconds float. Output: None. Simulate durable Stop while waiting."""
            self.sleep(seconds)
            request_runtime_state(self.run, 'paused')
        result = self.drive(stop)
        self.assertEqual(result['runtime_reason'], 'user_paused')
        self.assertEqual(self.calls, 1)
        self.assertEqual(read_runtime_control(self.run)['simulation_attempts'], 4000)

    def test_time_limit_remains_independent_of_midnight(self):
        request_runtime_state(self.run, 'running', max_runtime_seconds=1)
        with patch('wqb.runtime_boundaries.dispatch_boundary_notice', side_effect=lambda run, row, now: row):
            result = self.drive()
        self.assertEqual(result['runtime_reason'], 'runtime_budget_exhausted')
        self.assertEqual(self.calls, 1)

    def test_new_maintenance_during_wait_prevents_new_step(self):
        original = self.current
        with patch('wqb.workflow_driver.read_current_recovery_case', side_effect=lambda run: (
                {'status': 'awaiting_maintenance_confirmation'} if self.current > original else {})):
            result = self.drive()
        self.assertEqual(result['runtime_reason'], 'maintenance_confirmation_required')
        self.assertEqual(self.calls, 1)

    def test_console_wait_uses_shared_snapshot_and_no_new_button(self):
        from wqb.console_server import _render_workflow_progress, _workflow_action_state
        from wqb.console_timeline import select_current_work
        state = {'active_workflow': {'exists': True}, 'runtime_control': {
            **read_runtime_control(self.run), 'status': 'waiting', 'reason': 'daily_budget_exhausted'},
            'research_rounds': {'status': 'blocked', 'stop_reason': 'research_simulation_budget_exhausted'}}
        state['current_work'] = select_current_work(state, [])
        self.assertEqual(state['current_work']['next_action'], 'daily-budget-wait')
        self.assertFalse(_workflow_action_state(state)['continue_workflow'])
        self.assertTrue(_workflow_action_state(state)['stop_workflow'])
        html = _render_workflow_progress(state)
        self.assertIn('4000 / 4000', html)
        self.assertIn('Lifetime', html)
        self.assertIn('Asia/Shanghai', html)
        self.assertNotIn('Authorize extension', html)

    def test_console_restart_allows_resume_into_wait_but_maintenance_wins(self):
        from wqb.console_server import _workflow_action_state
        from wqb.console_timeline import select_current_work
        request_runtime_state(self.run, 'paused')
        state = {'active_workflow': {'exists': True}, 'runtime_control': {
            **read_runtime_control(self.run), 'status': 'paused'}}
        state['current_work'] = select_current_work(state, [])
        self.assertTrue(_workflow_action_state(state)['continue_workflow'])
        state['runtime_control']['recovery_case'] = {'status': 'awaiting_maintenance_confirmation'}
        state['current_work'] = select_current_work(state, [])
        self.assertEqual(state['current_work']['next_action'], 'maintenance-blocker')
        self.assertFalse(_workflow_action_state(state)['continue_workflow'])

    def test_restart_rechecks_saved_wait_and_does_not_repeat_planning(self):
        def stop(seconds):
            """Input: float seconds. Output: None. End the first worker with durable Stop."""
            self.sleep(seconds)
            request_runtime_state(self.run, 'paused')
        self.drive(stop)
        request_runtime_state(self.run, 'running')
        with patch('wqb.workflow_driver.schedule_run_checkpoint') as model:
            result = self.drive()
        self.assertEqual(result['runtime_status'], 'waiting_for_user')
        self.assertEqual(self.calls, 2)
        self.assertEqual(model.call_count, 1)

    def test_other_run_can_consume_new_day_before_waiter(self):
        request_runtime_state(self.run, 'running', max_runtime_seconds=4)
        other = self.root / 'other'
        other.mkdir()
        spent = []
        def consume(seconds):
            """Input: float seconds. Output: None. Let a distinct local mission win the midnight balance."""
            self.sleep(seconds)
            if self.current.hour == 16 and not spent:
                budget.charge_daily_budget(other, 4000, 'other-day')
                spent.append(True)
        with patch('wqb.runtime_boundaries.dispatch_boundary_notice', side_effect=lambda run, row, now: row):
            result = self.drive(consume)
        self.assertEqual(result['runtime_reason'], 'runtime_budget_exhausted')
        self.assertEqual(self.calls, 1)

    def test_corruption_during_wait_fails_before_new_work(self):
        def corrupt(seconds):
            """Input: float seconds. Output: None. Simulate lost accounting, never a synthetic reset."""
            self.sleep(seconds)
            (self.root / 'daily_simulation_budget/ledger.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'invalid during wait'):
            self.drive(corrupt)
        self.assertEqual(self.calls, 1)

    def test_stale_waiting_worker_can_be_resumed_after_app_restart(self):
        from wqb.console_server import _workflow_action_state, _render_workflow_progress
        from wqb.console_timeline import select_current_work
        state = {'active_workflow': {'exists': True}, 'runtime_control': {
            **read_runtime_control(self.run), 'status': 'waiting', 'reason': 'daily_budget_exhausted',
            'heartbeat_at': '2000-01-01T00:00:00Z'}}
        state['current_work'] = select_current_work(state, [])
        self.assertEqual(state['current_work']['status'], 'stale')
        self.assertTrue(_workflow_action_state(state)['continue_workflow'])
        self.assertIn('Resume workflow', _render_workflow_progress(state))

    def test_budget_day_and_integrity_participate_in_action_revision(self):
        from copy import deepcopy
        from wqb.console_server import _workflow_action_hash
        state = {'active_workflow': {'exists': True}, 'runtime_control': read_runtime_control(self.run)}
        original = _workflow_action_hash(state)
        newer = deepcopy(state)
        newer['runtime_control']['daily_simulation_budget']['budget_date'] = '2026-10-22'
        self.assertNotEqual(original, _workflow_action_hash(newer))
        newer = deepcopy(state)
        newer['runtime_control']['invalid'] = True
        self.assertNotEqual(original, _workflow_action_hash(newer))

    def test_interrupted_wait_retains_consumed_runtime(self):
        def interrupt(seconds):
            """Input: seconds float. Output: no return. Simulate abrupt interruption after elapsed waiting."""
            self.sleep(1000)
            raise KeyboardInterrupt('offline crash injection')
        with self.assertRaises(KeyboardInterrupt):
            self.drive(interrupt)
        self.assertGreaterEqual(read_runtime_control(self.run)['elapsed_seconds'], 1000)
        self.assertEqual(self.calls, 1)

    def test_daily_wait_still_reconciles_existing_repair_identity_without_new_planning(self):
        from wqb.runtime_control import DAILY_RECONCILE_ENV, DailyBudgetExhausted
        import os
        receipt = self.run / 'stages/repair/repair_execution.json'
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({'attempts': [{'phase': 'waiting', 'next_poll_at': self.now()}]}))
        recovered = []
        def stage():
            """Input: fixture stage. Output: result dict. Observe GET-only reconciliation, without a network client."""
            self.calls += 1
            if os.environ.get(DAILY_RECONCILE_ENV) == '1':
                check_submission_allowed()
                recovered.append('existing-progress-url')
                receipt.write_text(json.dumps({'attempts': [{'phase': 'checked'}]}))
                with self.assertRaises(DailyBudgetExhausted):
                    check_submission_allowed(1)
                return {**self.status(), 'next_action': 'workflow-auto-continue'}
            check_submission_allowed(1)
            return {**self.status(), 'status': 'waiting_for_user', 'waiting_for_user': True}
        with patch('wqb.workflow_driver.schedule_run_checkpoint') as model:
            result = run_workflow_driver(SimpleNamespace(run_root=self.root), {}, step=stage,
                status_reader=self.status, now_func=self.now, sleep_func=self.sleep)
        self.assertEqual(result['runtime_status'], 'waiting_for_user')
        self.assertEqual(recovered, ['existing-progress-url'])
        self.assertEqual(model.call_count, 1)
        self.assertEqual(budget.read_daily_budget(self.run)['lifetime_attempts'], 4001)
