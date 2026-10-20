import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from wqb.runtime_control import request_runtime_state
from wqb.workflow_driver import run_workflow_driver


class RunAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / 'legacy'
        (self.run / 'stages' / 'schedule').mkdir(parents=True)
        (self.run / 'stages' / 'schedule' / 'research_schedule.json').write_text(
            json.dumps({'simulation_budget': 10, 'api_budget': 10}), encoding='utf-8')

    def test_driver_never_initializes_missing_authority_from_live_config(self):
        step = Mock(return_value={'status': 'completed'})
        status = {'active': True, 'run_dir': str(self.run)}
        result = run_workflow_driver(None, {'enable_live_api': True}, step=step,
                                     status_reader=lambda: status)
        step.assert_not_called()
        self.assertEqual(result['runtime_reason'], 'runtime_authority_required')
        self.assertFalse((self.run / 'runtime_control.json').exists())

    def test_legacy_running_request_does_not_create_default_authority(self):
        with self.assertRaisesRegex(ValueError, 'legacy.*authority'):
            request_runtime_state(self.run, 'running', enable_live_api=True)
        self.assertFalse((self.run / 'runtime_control.json').exists())

    def test_legacy_pause_remains_possible_but_does_not_authorize_resume(self):
        paused = request_runtime_state(self.run, 'paused')
        self.assertEqual(paused['desired_state'], 'paused')
        with self.assertRaisesRegex(ValueError, 'legacy.*authority'):
            request_runtime_state(self.run, 'running', enable_live_api=True)

    def test_partial_legacy_control_cannot_receive_default_authority(self):
        for desired in ('paused', 'running'):
            with self.subTest(desired=desired):
                (self.run / 'runtime_control.json').write_text(json.dumps({'desired_state': 'paused'}), encoding='utf-8')
                if desired == 'running':
                    with self.assertRaisesRegex(ValueError, 'legacy.*authority'):
                        request_runtime_state(self.run, desired, enable_live_api=True)
                else:
                    request_runtime_state(self.run, desired)
                    with self.assertRaisesRegex(ValueError, 'legacy.*authority'):
                        request_runtime_state(self.run, 'running', enable_live_api=True)

    def test_partial_live_control_cannot_submit_even_without_driver(self):
        from wqb.runtime_control import check_submission_allowed, RuntimePaused, CONTROL_ENV
        from unittest.mock import patch

        (self.run / 'runtime_control.json').write_text(json.dumps({
            'desired_state': 'running', 'enable_live_api': True}), encoding='utf-8')
        with patch.dict('os.environ', {CONTROL_ENV: str(self.run)}):
            with self.assertRaises(RuntimePaused):
                check_submission_allowed(1)

    def test_unknown_usage_never_becomes_known_remaining_budget(self):
        from wqb.run_authority import inspect_run_authority

        fresh = self.run.parent / 'fresh'
        request_runtime_state(fresh, 'paused', max_simulations=30)
        report = inspect_run_authority(fresh)
        self.assertIsNone(report['recorded_attempts'])
        self.assertIsNone(report['remaining_simulations'])

    def test_planning_numbers_and_http_counts_are_not_authority(self):
        from wqb.run_authority import inspect_run_authority

        source = self.run.parent / 'source'
        source.mkdir()
        events = [dict(event='SUBMITTED', expression_hash=f'e{i}', progress_url='same-batch') for i in range(20)]
        events += [events[0], dict(event='CHECKED', expression_hash='e0')]
        (source / 'simulation_events.jsonl').write_text(
            '\n'.join(json.dumps(row) for row in events), encoding='utf-8')
        directory = self.run / 'stages' / 'scout_seed'
        directory.mkdir()
        (directory / 'source_bridge_binding.json').write_text(
            json.dumps({'source_run_dir': str(source)}), encoding='utf-8')
        report = inspect_run_authority(self.run)
        self.assertEqual(report['status'], 'runtime_authority_required')
        self.assertEqual(report['planning_estimates']['simulation_budget'], 10)
        self.assertEqual(report['source_evidence']['submitted_event_rows'], 21)
        self.assertEqual(report['source_evidence']['distinct_submitted_candidates'], 20)
        self.assertEqual(report['source_evidence']['distinct_progress_urls'], 1)
        self.assertIsNone(report['remaining_simulations'])
        self.assertIsNone(report['platform_quota'])
        self.assertFalse((self.run / 'runtime_control.json').exists())

    def test_malformed_evidence_is_reported_not_silently_ignored(self):
        from wqb.run_authority import inspect_run_authority

        (self.run / 'runtime_control.json').write_text('{bad', encoding='utf-8')
        report = inspect_run_authority(self.run)
        self.assertEqual(report['status'], 'invalid_runtime_authority')
        self.assertIsNone(report['remaining_simulations'])

    def test_console_disables_resume_and_rejects_post_without_authority(self):
        from wqb.console_state import ConsolePaths, load_runtime_state
        from wqb.console_server import _workflow_action_state, _workflow_action_hash, assert_workflow_action_current
        from unittest.mock import patch

        root = self.run.parent
        paths = ConsolePaths(root, root, root / 'knowledge', root, root / 'milestone.md', root / 'todo.md', root / 'jobs')
        with patch('wqb.console_state._active_workflow_summary', return_value=(
                {'exists': True, 'current_stage': 'repair'}, self.run)):
            state = load_runtime_state(paths)
        self.assertFalse(_workflow_action_state(state)['continue_workflow'])
        form = {'action': 'workflow-auto-continue', 'state_hash': _workflow_action_hash(state),
                'expected_runtime_revision': ''}
        with self.assertRaisesRegex(ValueError, 'runtime authority'):
            assert_workflow_action_current(form, state)
        self.assertIn('authority', ' '.join(state['current_work']['details']))

    def test_existing_control_does_not_turn_unknown_historical_usage_into_remaining_budget(self):
        from wqb.run_authority import inspect_run_authority

        control = request_runtime_state(self.run.parent / 'fresh', 'paused', enable_live_api=True, max_simulations=30)
        (self.run / 'runtime_control.json').write_text(json.dumps(control), encoding='utf-8')
        source = self.run.parent / 'source'
        source.mkdir()
        (source / 'simulation_events.jsonl').write_text(json.dumps({
            'event': 'SUBMITTED', 'expression_hash': 'known'}), encoding='utf-8')
        binding = self.run / 'stages' / 'scout_seed'
        binding.mkdir()
        (binding / 'source_bridge_binding.json').write_text(json.dumps({'source_run_dir': str(source)}), encoding='utf-8')
        report = inspect_run_authority(self.run)
        self.assertEqual(report['status'], 'accounting_reconciliation_required')
        self.assertIsNone(report['recorded_attempts'])
        self.assertIsNone(report['remaining_simulations'])
