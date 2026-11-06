import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wqb.runtime_control import request_runtime_state, update_runtime_status, read_runtime_control


class RuntimeRenewalTests(unittest.TestCase):
    def test_renewal_preserves_usage_and_is_idempotent(self):
        from wqb.runtime_control import renew_runtime_budget
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            old = request_runtime_state(run, 'running', enable_live_api=True)
            update_runtime_status(run, status='blocked', reason='runtime_budget_exhausted',
                                  elapsed_seconds=21600.4, simulation_attempts=31)
            new = renew_runtime_budget(run, 21600, old['request_revision'])
            again = renew_runtime_budget(run, 21600, old['request_revision'])
            self.assertEqual(new['request_revision'], again['request_revision'])
            self.assertEqual(new['max_runtime_seconds'], 43200)
            self.assertEqual(new['elapsed_seconds'], 21600.4)
            self.assertEqual(new['simulation_attempts'], 31)
            self.assertEqual(new['max_simulations'], 150)
            self.assertEqual(new['reason'], 'runtime_renewed')
            self.assertEqual(len(read_runtime_control(run)['runtime_renewals']), 1)
            update_runtime_status(run, status='running')
            self.assertEqual(read_runtime_control(run)['status'], 'running')

    def test_stop_revision_refuses_renewal(self):
        from wqb.runtime_control import renew_runtime_budget
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            old = request_runtime_state(run, 'running', enable_live_api=True)
            update_runtime_status(run, status='blocked', reason='runtime_budget_exhausted', elapsed_seconds=21601)
            request_runtime_state(run, 'paused')
            with self.assertRaises(ValueError):
                renew_runtime_budget(run, 21600, old['request_revision'])

    def test_non_exhausted_and_invalid_duration_refused(self):
        from wqb.runtime_control import renew_runtime_budget
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            old = request_runtime_state(run, 'running')
            for duration in (21600, True, -1, 999999999):
                with self.assertRaises(ValueError):
                    renew_runtime_budget(run, duration, old['request_revision'])

    def test_console_renders_explicit_duration_not_plain_resume(self):
        from wqb.console_server import _render_workflow_progress
        state = {'active_workflow': {'exists': True, 'run_id': 'run-a'},
                 'runtime_control': {'status': 'blocked', 'reason': 'runtime_budget_exhausted',
                                     'request_revision': 'rev-a'}}
        html = _render_workflow_progress(state)
        self.assertIn('workflow-renew-runtime', html)
        self.assertIn('value="21600"', html)
        self.assertIn('value="run-a"', html)
        self.assertIn('disabled>Resume workflow', html)

    def test_console_renews_then_uses_new_revision_for_existing_resume(self):
        from wqb.console_server import run_console_action
        from tests.test_console_server import make_paths
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = make_paths(root)
            run = root / 'runs' / 'run-a'
            old = request_runtime_state(run, 'running', enable_live_api=True)
            update_runtime_status(run, status='blocked', reason='runtime_budget_exhausted', elapsed_seconds=21601)
            with patch('wqb.console_server._active_auto_continue_job', return_value=None), \
                    patch('wqb.workflow_state.discover_active_workflow', return_value=SimpleNamespace(run_dir=run)), \
                    patch('wqb.console_server._run_console_action_unlocked', return_value='started') as execute:
                result = run_console_action(paths, {'action': 'workflow-renew-runtime', 'run_id': 'run-a',
                                                    'additional_seconds': '21600',
                                                    'expected_runtime_revision': old['request_revision']})
            self.assertEqual(result, 'started')
            new = read_runtime_control(run)
            self.assertEqual(execute.call_args.args[1]['expected_runtime_revision'], new['request_revision'])

    def test_replay_after_stop_does_not_grant_more_time(self):
        from wqb.runtime_control import renew_runtime_budget
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            old = request_runtime_state(run, 'running')
            update_runtime_status(run, status='blocked', reason='runtime_budget_exhausted', elapsed_seconds=21601)
            renew_runtime_budget(run, 21600, old['request_revision'])
            request_runtime_state(run, 'paused')
            with self.assertRaises(ValueError):
                renew_runtime_budget(run, 21600, old['request_revision'])
            self.assertEqual(read_runtime_control(run)['desired_state'], 'paused')

    def test_maintenance_case_blocks_renewal_server_side(self):
        from wqb.runtime_control import renew_runtime_budget
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            old = request_runtime_state(run, 'running')
            update_runtime_status(run, status='blocked', reason='runtime_budget_exhausted', elapsed_seconds=21601)
            with patch('wqb.recovery_cases.read_current_recovery_case',
                       return_value={'status': 'awaiting_maintenance_confirmation'}):
                with self.assertRaises(ValueError):
                    renew_runtime_budget(run, 21600, old['request_revision'])

    def test_malformed_history_keeps_exhaustion_and_refuses_extension(self):
        from wqb.runtime_control import renew_runtime_budget, _write, runtime_control_path
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            old = request_runtime_state(run, 'running')
            update_runtime_status(run, status='blocked', reason='runtime_budget_exhausted', elapsed_seconds=21601)
            for history in ([None], {'bad': True}):
                _write(runtime_control_path(run), {**old, 'runtime_renewals': history})
                self.assertEqual(read_runtime_control(run)['reason'], 'runtime_budget_exhausted')
                with self.assertRaises(ValueError):
                    renew_runtime_budget(run, 21600, old['request_revision'])

    def test_job_watchdog_uses_remaining_renewed_allowance(self):
        from wqb.console_jobs import create_job, timeout_for_job
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / 'run-a'
            request_runtime_state(run, 'running', max_runtime_seconds=64800)
            update_runtime_status(run, elapsed_seconds=21601)
            job = create_job(root / 'jobs', 'workflow-auto-continue', [], root, {'run_dir': str(run)})
            self.assertGreaterEqual(timeout_for_job(job, 3600), 43259)
