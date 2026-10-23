import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from wqb.runtime_control import request_runtime_state, update_runtime_status
from wqb.runtime_boundaries import record_runtime_boundary, dispatch_boundary_notice, project_runtime_boundary


class RuntimeBoundaryTests(unittest.TestCase):
    def test_default_round_boundary_counts_first_round_and_effective_limit(self):
        """Input: no explicit round cap or historical ledger. Output: assertions. Record scheduler-equivalent1/1."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            request_runtime_state(root, 'running', enable_live_api=True, max_simulations=30)
            receipt = record_runtime_boundary(root, 'research_round_budget_exhausted', {}, 'now')
            self.assertEqual(receipt['limit'], 1)
            self.assertEqual(receipt['used'], 1)

    def test_console_shows_quota_notice_and_disables_noop_continue(self):
        """Input: quota boundary and old blocked round. Output: assertions. Resource evidence dominates generic blocked UI."""
        from wqb.console_server import _workflow_action_state
        from wqb.console_timeline import select_current_work
        state = {'active_workflow': {'exists': True}, 'runtime_control': {
            'status': 'blocked', 'desired_state': 'running', 'reason': 'research_simulation_budget_exhausted',
            'runtime_boundary': {'used': 150, 'limit': 150, 'notification': {'status': 'queued'}}},
            'research_rounds': {'status': 'blocked', 'stop_reason': 'research_simulation_budget_exhausted'}}
        state['current_work'] = select_current_work(state, [])
        self.assertEqual(state['current_work']['next_action'], 'simulation-budget-exhausted')
        self.assertIn('Notice: queued', state['current_work']['details'])
        self.assertFalse(_workflow_action_state(state)['continue_workflow'])
        self.assertTrue(_workflow_action_state(state)['stop_workflow'])

    def test_driver_simulation_and_round_limits_send_one_resource_notice(self):
        """Input: typed research quota stop. Output: assertions. Notify once without repair or renewal authority."""
        from types import SimpleNamespace
        from wqb.workflow_driver import run_workflow_driver
        for kind in ('research_simulation_budget_exhausted', 'research_round_budget_exhausted'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'run'
                request_runtime_state(root, 'running', enable_live_api=True, max_simulations=150)
                update_runtime_status(root, simulation_attempts=150)
                (root / 'research_rounds.json').write_text(json.dumps({'max_rounds': 5, 'rounds': [{}, {}, {}, {}, {}]}))
                (root.parent / 'maintenance_channel.json').write_text(json.dumps({
                    'thread_id': '019f0c94-8cad-74f1-9fd5-14952c1f38b3'}))
                status = {'active': True, 'run_dir': str(root), 'current_stage': 'repair'}
                step = Mock(return_value={**status, 'status': 'paused',
                    'next_action': 'research-loop-blocked', 'pause_reason': kind})
                with patch('wqb.workflow_driver.schedule_run_checkpoint'), \
                     patch('wqb.runtime_boundaries.shutil.which', return_value='codex'), \
                     patch('wqb.runtime_boundaries.subprocess.run', return_value=Mock(returncode=0)) as send:
                    for _ in range(2):
                        result = run_workflow_driver(SimpleNamespace(), {}, step=step, status_reader=lambda: status)
                self.assertEqual(send.call_count, 1)
                self.assertEqual(result['runtime_reason'], kind)
                path = next((root / 'runtime/boundaries').glob('*.json'))
                receipt = json.loads(path.read_text())
                self.assertEqual(receipt['limit'], 150 if 'simulation' in kind else 5)
                self.assertEqual(receipt['used'], 150 if 'simulation' in kind else 5)
                self.assertFalse(receipt['repair_authorized'])
                self.assertFalse(receipt['runtime_renewal_authorized'])
                self.assertEqual(receipt['notification']['status'], 'queued')

    def test_runtime_deadline_blocks_model_to_post_and_records_boundary(self):
        from wqb.workflow_driver import run_workflow_driver
        from wqb.runtime_control import check_submission_allowed
        from types import SimpleNamespace
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            request_runtime_state(root, 'running', enable_live_api=True, max_runtime_seconds=10)
            status = {'active': True, 'run_dir': str(root), 'current_stage': 'repair'}
            posted = []
            def step():
                os.environ['BRAIN_WORKFLOW_RUNTIME_DEADLINE'] = '0'
                check_submission_allowed(1)
                posted.append(True)
                return {**status, 'status': 'completed'}
            with patch.dict(os.environ):
                result = run_workflow_driver(SimpleNamespace(), {}, step=step, status_reader=lambda: status)
            self.assertEqual(posted, [])
            self.assertEqual(result['runtime_reason'], 'runtime_budget_exhausted')

    def test_advisory_stop_is_paused_not_error(self):
        from wqb.workflow_driver import run_workflow_driver
        from wqb.runtime_control import RuntimePaused
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            request_runtime_state(root, 'running', enable_live_api=True)
            status = {'active': True, 'run_dir': str(root), 'current_stage': 'repair'}
            def stop(*args):
                request_runtime_state(root, 'paused')
                raise RuntimePaused('Stop requested')
            with patch('wqb.workflow_driver.schedule_run_checkpoint', side_effect=stop):
                result = run_workflow_driver(SimpleNamespace(), {}, step=lambda: status, status_reader=lambda: status)
            self.assertEqual(result['runtime_status'], 'paused')
    def test_driver_exhaustion_notifies_once_and_never_runs_step_on_resume(self):
        from wqb.workflow_driver import run_workflow_driver
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            request_runtime_state(root, 'running', enable_live_api=True, max_runtime_seconds=10)
            update_runtime_status(root, elapsed_seconds=11)
            status = {'active': True, 'run_dir': str(root), 'current_stage': 'repair',
                      'next_action': 'workflow-resume'}
            step = Mock()
            for _ in range(2):
                result = run_workflow_driver(SimpleNamespace(), {}, step=step, status_reader=lambda: status)
                self.assertEqual(result['next_action'], 'runtime-budget-exhausted')
            step.assert_not_called()
            self.assertEqual(len(list((root / 'runtime/boundaries').glob('*.json'))), 1)

    def test_long_simulation_notice_does_not_change_submission_evidence(self):
        from wqb.repair_scheduler import _stall_notice
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            request_runtime_state(root, 'running', enable_live_api=True)
            attempt = {'parent_expression_hash': 'hash', 'first_wait_at': '2026-10-12T00:00:00+00:00',
                       'source_run_dir': 'saved-progress', 'phase': 'waiting'}
            _stall_notice(root, attempt, '2026-10-12T00:31:00+00:00')
            self.assertEqual(attempt['phase'], 'waiting')
            self.assertEqual(attempt['stall_notice']['kind'], 'repair_simulation_stalled')
            self.assertFalse(attempt['stall_notice']['repair_authorized'])
    def test_console_disables_noop_resume_but_keeps_stop(self):
        from wqb.console_server import _workflow_action_state
        state = {'active_workflow': {'exists': True}, 'runtime_control': {
            'status': 'blocked', 'reason': 'runtime_budget_exhausted', 'desired_state': 'running'},
            'current_work': {'next_action': 'runtime-budget-exhausted'}}
        actions = _workflow_action_state(state)
        self.assertFalse(actions['continue_workflow'])
        self.assertTrue(actions['stop_workflow'])
    def test_exhaustion_is_durable_deduplicated_and_not_repair_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            request_runtime_state(root, 'running', enable_live_api=True, max_runtime_seconds=10)
            update_runtime_status(root, elapsed_seconds=11)
            one = record_runtime_boundary(root, 'runtime_budget_exhausted', {'current_stage': 'repair'}, 'now')
            two = record_runtime_boundary(root, 'runtime_budget_exhausted', {'current_stage': 'repair'}, 'later')
            self.assertEqual(one['boundary_id'], two['boundary_id'])
            self.assertFalse(one['repair_authorized'])
            self.assertEqual(one['limit'], 10)
            self.assertEqual(one['used'], 11)
            self.assertEqual(project_runtime_boundary({'next_action': 'workflow-resume'},
                                                     {'reason': 'runtime_budget_exhausted', 'status': 'blocked'})['next_action'],
                             'runtime-budget-exhausted')

    def test_notice_delivery_is_not_replayed_when_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            request_runtime_state(root, 'running', enable_live_api=True)
            (root.parent / 'maintenance_channel.json').write_text(json.dumps({'thread_id': '019f0c94-8cad-74f1-9fd5-14952c1f38b3'}))
            boundary = record_runtime_boundary(root, 'step_budget_exhausted', {'current_stage': 'repair'}, 'now')
            with patch('wqb.runtime_boundaries.shutil.which', return_value='codex'), patch(
                    'wqb.runtime_boundaries.subprocess.run', return_value=Mock(returncode=1)) as send:
                first = dispatch_boundary_notice(root, boundary, 'now')
                second = dispatch_boundary_notice(root, first, 'later')
            self.assertEqual(send.call_count, 1)
            self.assertEqual(second['notification']['status'], 'delivery_uncertain')

    def test_pause_prevents_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            request_runtime_state(root, 'paused')
            boundary = record_runtime_boundary(root, 'runtime_budget_exhausted', {}, 'now')
            with patch('wqb.runtime_boundaries.subprocess.run') as send:
                dispatch_boundary_notice(root, boundary, 'now')
            send.assert_not_called()
