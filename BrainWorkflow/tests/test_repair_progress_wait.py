import json
from pathlib import Path
import unittest
from unittest.mock import patch

import requests

from tests import test_repair_runtime as fixtures
from tests.test_repair_runtime import parent_row, repair_actions
from wqb.repair_runtime import RepairRuntimeExecutor, RepairProgressPending, RepairRateLimited
from wqb.simulator import SimulationPollTimeout
from wqb.workflow_driver import _repair_cooldown_result


class RepairProgressWaitTests(unittest.TestCase):
    setUp = fixtures.RepairRuntimeTests.setUp

    def test_legacy_variants_recover_pending_checks_with_separate_identities(self):
        from wqb.models import CheckItem, CheckSummary
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        actions = repair_actions() + [{'action_type': 'flip_direction'}]
        self.submit.side_effect = ['progress/a', 'progress/b']
        self.poll.side_effect = [{'alpha': 'a'}, {'alpha': 'b'}]
        pending_a = CheckSummary('a', False, [], [], [CheckItem('SHARPE', 'PENDING')], {})
        pending_b = CheckSummary('b', False, [], [], [CheckItem('SHARPE', 'PENDING')], {})
        done_a = CheckSummary('a', True, [], [], [], {'sharpe': 1.8})
        done_b = CheckSummary('b', True, [], [], [], {'sharpe': 1.9})
        with patch('wqb.cli.fetch_check_summary', side_effect=[pending_a, done_a, pending_b, done_b]):
            for _ in range(2):
                with self.assertRaises(RepairProgressPending):
                    executor(self.root, parent_row(), actions, 2)
                wait_path = self.root / 'stages/repair/parents/parent-parent-hash/progress_wait.json'
                wait = json.loads(wait_path.read_text())
                wait['next_poll_at'] = '2000-01-01T00:00:00+00:00'
                wait_path.write_text(json.dumps(wait))
            rows = executor(self.root, parent_row(), actions, 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.submit.call_count, 2)
        self.assertEqual(self.poll.call_count, 2)

    def test_pending_child_checks_resume_existing_alpha_without_post_or_repoll(self):
        from wqb.models import CheckItem, CheckSummary
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        pending = CheckSummary('child', False, [], [], [CheckItem('SHARPE', 'PENDING')], {})
        done = CheckSummary('child', True, [], [], [], {'sharpe': 1.8})
        with patch('wqb.cli.fetch_check_summary', side_effect=[pending, done]) as checks:
            with self.assertRaises(RepairProgressPending):
                executor(self.root, parent_row(), repair_actions(), 1)
            subrun = self.root / 'stages/repair/parents/parent-parent-hash'
            wait_path = subrun / 'progress_wait.json'
            wait = json.loads(wait_path.read_text())
            wait['next_poll_at'] = '2000-01-01T00:00:00+00:00'
            wait_path.write_text(json.dumps(wait))
            rows = executor(self.root, parent_row(), repair_actions(), 1)
        self.assertTrue(rows[0]['hard_pass'])
        self.assertEqual(self.submit.call_count, 1)
        self.assertEqual(self.poll.call_count, 1)
        self.assertEqual(checks.call_count, 2)

    def test_pause_during_executor_keeps_durable_attempt_resumable(self):
        from tests.test_workflow_stage_outcomes import checked_alpha, write_rows
        from wqb.workflow_stage_adapters import advance_post_schedule_stage
        from wqb.runtime_control import RuntimePaused
        write_rows(self.root, [checked_alpha()])
        def paused(*args):
            raise RuntimePaused('Stop requested')
        with self.assertRaises(RuntimePaused):
            advance_post_schedule_stage(self.root, 'repair', repair_executor=paused)
        receipt = json.loads((self.root / 'stages/repair/repair_execution.json').read_text())
        self.assertTrue(receipt['recovery_eligible'])
    def test_pending_progress_is_durable_wait_not_hot_retry_or_resubmit(self):
        response = requests.Response()
        response.status_code = 200
        response.headers['Retry-After'] = '5'
        self.poll.side_effect = SimulationPollTimeout('still pending', response=response)
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        with self.assertRaises(RepairProgressPending) as caught:
            executor(self.root, parent_row(), repair_actions(), 1)
        self.assertTrue(hasattr(caught.exception, 'next_poll_at'))
        self.assertEqual(self.poll.call_args.kwargs['max_retry_after_polls'], 0)
        with self.assertRaises(RepairProgressPending):
            executor(self.root, parent_row(), repair_actions(), 1)
        self.assertEqual(self.poll.call_count, 1)
        self.assertEqual(self.submit.call_count, 1)

    def test_driver_projects_progress_wait_separately_from_rate_limit(self):
        path = self.root / 'stages/repair/repair_execution.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'status': 'paused', 'recovery_eligible': True,
                                    'blocker': 'waiting for existing progress',
                                    'progress_retry_at': '2099-01-01T00:00:00+00:00',
                                    'progress_source_run_dir': str(self.root)}))
        result = _repair_cooldown_result(self.root, {'current_stage': 'repair', 'status': 'paused',
                                        'pause_reason': 'waiting for existing progress'},
                                        '2026-10-12T06:20:00+00:00')
        self.assertEqual(result['next_action'], 'simulation-progress-wait')

    def test_stale_progress_receipt_cannot_hide_current_evidence_blocker(self):
        path = self.root / 'stages/repair/repair_execution.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'status': 'paused', 'recovery_eligible': True,
            'blocker': 'old progress wait', 'progress_retry_at': '2099-01-01T00:00:00+00:00',
            'progress_source_run_dir': str(self.root)}))
        result = {'current_stage': 'repair', 'status': 'paused', 'pause_reason': 'repair plan changed'}
        self.assertEqual(_repair_cooldown_result(self.root, result, '2026-10-12T06:20:00+00:00'), result)

    def test_authentication_timeout_and_429_preserve_recoverability(self):
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        self.client.authenticate.side_effect = requests.Timeout('auth timeout')
        with self.assertRaises(RepairProgressPending):
            executor(self.root, parent_row(), repair_actions(), 1)
        self.submit.assert_not_called()
        wait_path = next((self.root / 'stages/repair/parents').iterdir()) / 'progress_wait.json'
        wait = json.loads(wait_path.read_text())
        wait['next_poll_at'] = '2000-01-01T00:00:00+00:00'
        wait_path.write_text(json.dumps(wait))
        self.client.authenticate.side_effect = None
        rows = executor(self.root, parent_row(), repair_actions(), 1)
        self.assertEqual(rows[0]['alpha_id'], 'child')
        self.assertEqual(self.submit.call_count, 1)

    def test_pause_before_post_is_definitely_local_and_can_resume(self):
        from wqb.runtime_control import RuntimePaused
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        with patch('wqb.runtime_control.check_submission_allowed', side_effect=RuntimePaused('Stop before POST')):
            with self.assertRaises(RuntimePaused):
                executor(self.root, parent_row(), repair_actions(), 1)
        self.submit.assert_not_called()
        rows = executor(self.root, parent_row(), repair_actions(), 1)
        self.assertEqual(rows[0]['alpha_id'], 'child')
        self.assertEqual(self.submit.call_count, 1)

    def test_pause_in_submission_gate_is_not_uncertain_post(self):
        from wqb.runtime_control import RuntimePaused
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        self.submit.side_effect = RuntimePaused('Stop at dispatch gate')
        with self.assertRaises(RuntimePaused):
            executor(self.root, parent_row(), repair_actions(), 1)
        self.submit.side_effect = None
        rows = executor(self.root, parent_row(), repair_actions(), 1)
        self.assertEqual(rows[0]['alpha_id'], 'child')

    def test_malformed_json_is_not_a_transient_progress_wait(self):
        self.poll.side_effect = requests.exceptions.JSONDecodeError('bad response', 'x', 0)
        with self.assertRaisesRegex(RuntimeError, 'invalid.*payload'):
            RepairRuntimeExecutor({}, enable_live_api=True)(self.root, parent_row(), repair_actions(), 1)

    def test_completed_alpha_is_saved_before_check_failure_and_not_repolled(self):
        executor = RepairRuntimeExecutor({}, enable_live_api=True)
        with patch('wqb.cli.fetch_check_summary', side_effect=requests.Timeout('check timeout')):
            with self.assertRaises(RepairProgressPending):
                executor(self.root, parent_row(), repair_actions(), 1)
        events = next((self.root / 'stages/repair/parents').iterdir()) / 'simulation_events.jsonl'
        saved = [json.loads(line) for line in events.read_text().splitlines()]
        self.assertTrue(any(row.get('event') == 'SIMULATION_COMPLETED' and row.get('alpha_id') == 'child'
                            for row in saved))
        wait_path = events.parent / 'progress_wait.json'
        wait = json.loads(wait_path.read_text())
        wait['next_poll_at'] = '2000-01-01T00:00:00+00:00'
        wait_path.write_text(json.dumps(wait))
        rows = executor(self.root, parent_row(), repair_actions(), 1)
        self.assertEqual(rows[0]['alpha_id'], 'child')
        self.assertEqual(self.poll.call_count, 1)
        self.assertEqual(self.submit.call_count, 1)

    def test_poll_429_is_real_cooldown_not_progress_pending(self):
        response = requests.Response()
        response.status_code = 429
        response.headers['Retry-After'] = '60'
        self.poll.side_effect = SimulationPollTimeout('limited response', response=response)
        with self.assertRaises(RepairRateLimited):
            RepairRuntimeExecutor({}, enable_live_api=True)(self.root, parent_row(), repair_actions(), 1)
        source = next((self.root / 'stages/repair/parents').iterdir())
        state = json.loads((source / 'rate_limit_state.json').read_text())
        self.assertEqual(state['consecutive_429_count'], 1)

    def test_programming_error_is_not_mislabeled_as_recoverable_network_wait(self):
        self.poll.side_effect = TypeError('bad adapter')
        with self.assertRaises(TypeError):
            RepairRuntimeExecutor({}, enable_live_api=True)(self.root, parent_row(), repair_actions(), 1)


if __name__ == '__main__':
    unittest.main()
