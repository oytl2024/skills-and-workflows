import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wqb.client import WQBClient
from wqb.console_jobs import build_cli_command
from wqb.console_state import default_console_paths
from wqb.runtime_control import RuntimePaused, request_runtime_state
from wqb.simulator import submit_multisimulation


class RuntimeIntegrationTests(unittest.TestCase):
    def test_cli_run_dispatches_driver_with_persisted_permission(self):
        from wqb.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            request_runtime_state(tmp, 'paused', enable_live_api=True)
            orch = Mock()
            orch.status.return_value = {'active': True, 'run_dir': tmp}
            with patch('sys.argv', ['wqb', 'workflow-run']), patch('wqb.cli.WorkflowOrchestrator', return_value=orch), patch('wqb.workflow_driver.run_workflow_driver', return_value={'runtime_status': 'completed'}) as driver, patch('builtins.print'):
                main()
            self.assertEqual(driver.call_count, 1)
            from wqb.runtime_control import read_runtime_control
            self.assertTrue(read_runtime_control(tmp)['enable_live_api'])
            self.assertEqual(read_runtime_control(tmp)['desired_state'], 'running')

    def test_cli_pause_keeps_active_run(self):
        from wqb.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            orch = Mock()
            orch.status.return_value = {'active': True, 'run_dir': tmp}
            with patch('sys.argv', ['wqb', 'workflow-pause']), patch('wqb.cli.WorkflowOrchestrator', return_value=orch), patch('builtins.print'):
                main()
            orch.abort.assert_not_called()
            from wqb.runtime_control import read_runtime_control
            self.assertEqual(read_runtime_control(tmp)['desired_state'], 'paused')

    def test_console_uses_driver_and_resumable_pause(self):
        paths = default_console_paths()
        self.assertIn('workflow-run', build_cli_command('workflow-auto-continue', paths))
        self.assertIn('workflow-pause', build_cli_command('workflow-stop', paths))

    def test_pause_prevents_multi_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            request_runtime_state(tmp, 'paused', enable_live_api=True)
            client = Mock()
            with patch.dict(os.environ, {'BRAIN_WORKFLOW_CONTROL_PATH': tmp}):
                with self.assertRaises(RuntimePaused):
                    submit_multisimulation(client, [{'regular': 'rank(close)'}])
            client.post_json.assert_not_called()

    def test_managed_submit_429_has_no_hidden_client_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            request_runtime_state(tmp, 'running', enable_live_api=True)
            session = Mock()
            response = Mock(status_code=429, headers={'Retry-After': '1'})
            session.request.return_value = response
            client = WQBClient(session=session)
            client.authenticated = True
            with patch.dict(os.environ, {'BRAIN_WORKFLOW_CONTROL_PATH': tmp}), patch('wqb.client.time.sleep'):
                result = client.request('POST', '/simulations', json=[{}])
            self.assertIs(result, response)
            self.assertEqual(session.request.call_count, 1)
