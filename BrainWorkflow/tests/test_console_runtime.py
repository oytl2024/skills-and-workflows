import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen
from unittest.mock import patch
from datetime import datetime, timezone
from contextlib import contextmanager

from tests.test_console_state import make_paths
from wqb import console_state, console_server
from wqb.console_timeline import select_current_work


@contextmanager
def local_console(paths):
    """Input: ConsolePaths. Output: URL iterator. Serve only temporary local test artifacts."""
    server = console_server.make_console_server('127.0.0.1', 0, paths)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class ConsoleRuntimeTests(unittest.TestCase):
    def test_completed_original_scope_displays_new_option_start_not_resume(self):
        """Input: finished frozen recovery. Output: assertions. Make the fresh-mission control actually visible."""
        state = {'active_workflow': {'exists': True}, 'runtime_control': {
            'status': 'completed', 'original_batch_recovery': {'authorized': True, 'planned': 29,
                'checked': 29, 'remaining': 0}},
            'current_work': {'next_action': 'research-mission-authority-required'}}
        html = console_server.render_dashboard(state)
        self.assertIn('workflow-start-from-option', html)
        self.assertIn('Start workflow', html)

    def test_dashboard_subscribes_to_runtime_and_preserves_form_values(self):
        html = console_server.render_dashboard({})
        self.assertIn("new EventSource('/api/events')", html)
        self.assertIn("snapshot", html)
        self.assertIn("preservedInputs", html)
        self.assertIn('strategy-progress-body', html)

    def test_managed_running_worker_cannot_be_started_twice(self):
        state = {'active_workflow': {'exists': True},
                 'runtime_control': {'desired_state': 'running', 'status': 'waiting'}}
        actions = console_server._workflow_action_state(state)
        self.assertFalse(actions['continue_workflow'])
        self.assertTrue(actions['stop_workflow'])

    def test_managed_resume_reuses_run_permission_without_new_checkbox(self):
        state = {'active_workflow': {'exists': True},
                 'runtime_control': {'desired_state': 'paused', 'status': 'paused', 'enable_live_api': True}}
        html = console_server._render_workflow_progress(state)
        self.assertNotIn('type="checkbox"', html)
        self.assertIn('Resume workflow', html)

    def test_fragment_http_route_never_loads_cold_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            with local_console(make_paths(Path(tmp))) as url:
                with patch.object(console_state, '_load_cold_console_state', side_effect=AssertionError('cold scan')):
                    with urlopen(url + '/api/fragments', timeout=3) as response:
                        payload = json.load(response)
                self.assertIn('strategy_progress', payload)
                self.assertIn('runtime_control', payload)

    def test_sse_sends_snapshot_and_heartbeat_without_cold_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            with local_console(make_paths(Path(tmp))) as url:
                with patch.object(console_state, '_load_cold_console_state', side_effect=AssertionError('cold scan')):
                    with urlopen(url + '/api/events', timeout=4) as response:
                        self.assertEqual(response.headers.get_content_type(), 'text/event-stream')
                        self.assertEqual(response.readline().decode().strip(), 'event: snapshot')
                        payload = json.loads(response.readline().decode()[6:])
                        self.assertIn('state_hash', payload)
                        response.readline()
                        self.assertEqual(response.readline().decode().strip(), 'event: heartbeat')

    def test_runtime_status_distinguishes_missing_stale_and_error(self):
        cases = [
            ({'desired_state': 'running'}, 'unknown'),
            ({'desired_state': 'running', 'status': 'running', 'updated_at': '2000-01-01T00:00:00Z'}, 'stale'),
            ({'desired_state': 'running', 'status': 'error', 'reason': 'worker failed'}, 'error'),
            ({'desired_state': 'paused', 'status': 'running'}, 'pausing'),
            ({'desired_state': 'running', 'status': 'waiting', 'updated_at': datetime.now(timezone.utc).isoformat(),
              'next_wake_at': '2099-01-01T00:00:00Z'}, 'waiting'),
        ]
        for control, expected in cases:
            with self.subTest(expected=expected):
                state = {'active_workflow': {'exists': True}, 'runtime_control': control}
                work = select_current_work(state, [])
                self.assertEqual(work['status'], expected)
                if expected == 'error':
                    self.assertIn('worker failed', work['details'])

    def test_start_permission_reaches_cli_builder(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            with patch.object(console_server, '_selected_option', return_value={'option_id': 'one'}), \
                 patch.object(console_server, '_freshness_clean', return_value=True), \
                 patch.object(console_server, '_validate_option_data_coverage'), \
                 patch.object(console_server, 'build_raw_cli_command', wraps=console_server.build_raw_cli_command) as build:
                command = console_server.build_action_command('workflow-start-from-option', paths, {
                    'selected_region': 'USA', 'selected_delay': '1', 'selected_universe': 'TOP3000',
                    'enable_live_api': 'on',
                })
            self.assertIs(build.call_args.args[2]['enable_live_api'], True)
            self.assertEqual(command[2], 'wqb.console_start')

    def test_start_success_launches_driver_but_failure_does_not(self):
        from wqb.console_jobs import create_job, finish_job
        from wqb.console_start import _write_request
        from wqb.runtime_control import request_runtime_state

        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            run_dir = paths.runs_root / 'created'
            control = request_runtime_state(run_dir, 'paused', enable_live_api=True)
            receipt = {'request_id': 'start-id', 'runtime_request_revision': control['request_revision'],
                       'run_dir': str(run_dir), 'status': 'completed', 'passed': True}
            _write_request(paths.runs_root, receipt)
            for success in (True, False):
                with self.subTest(success=success), \
                     patch.object(console_server, 'record_console_job_context'), \
                     patch.object(console_server, 'load_runtime_state', side_effect=AssertionError('must use original start receipt')), \
                     patch.object(console_server, 'run_console_action') as start:
                    job = create_job(paths.job_root, 'workflow-start-from-option', ['fake'], paths.workflow_root)
                    Path(job.stdout_path).write_text(json.dumps(receipt), encoding='utf-8')
                    completed = finish_job(job, 'completed' if success else 'failed', exit_code=0 if success else 1)
                    console_server._complete_start_job(paths, completed)
                self.assertEqual(start.call_count, int(success))
                if success:
                    self.assertEqual(start.call_args.args[1]['action'], 'workflow-auto-continue')
                    self.assertEqual(start.call_args.args[1]['expected_runtime_revision'], control['request_revision'])

    def test_bound_readiness_ignores_newer_unrelated_blocker(self):
        """Input: local report fixtures. Output: None. Assert UI uses the CLI's bound evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            active = paths.runs_root / 'active'
            source = paths.runs_root / 'source'
            unrelated = paths.runs_root / 'unrelated'
            for directory in (active, source, unrelated):
                directory.mkdir(parents=True)
            (source / 'readiness_report.json').write_text(json.dumps({'passed': True}))
            (unrelated / 'readiness_report.json').write_text(json.dumps({'blocked': True}))
            os.utime(unrelated / 'readiness_report.json', (2000000000, 2000000000))
            binding = active / 'stages/scout_seed/source_bridge_binding.json'
            binding.parent.mkdir(parents=True)
            binding.write_text(json.dumps({'source_run_dir': str(source)}))
            with patch.object(console_state, '_active_workflow_summary', return_value=(
                {'exists': True, 'run_dir': str(active), 'current_stage': 'repair'}, active
            )):
                state = console_state.load_console_state(paths)
            self.assertTrue(state['readiness'].get('passed'))
            self.assertEqual(state['readiness']['path'], str(source / 'readiness_report.json'))

    def test_runtime_does_not_load_cold_knowledge(self):
        """Input: empty local roots. Output: None. Detect full ledger scans in the runtime route."""
        self.assertTrue(hasattr(console_state, 'load_runtime_state'))
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(console_state, '_data_authority_summary_from_rows', side_effect=AssertionError('cold scan')):
                state = console_state.load_runtime_state(make_paths(Path(tmp)))
            self.assertIn('strategy_progress', state)
            self.assertNotIn('data_authority', state)

    def test_cold_summary_reuses_ledger_until_its_file_changes(self):
        """Input: ledger updates. Output: None. Verify cache reuse and file-based invalidation."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            ledger = paths.knowledge_root / 'machine/data_ledger.jsonl'
            ledger.parent.mkdir(parents=True)
            ledger.write_text('{}\n')
            self.assertEqual(console_state.load_console_state(paths)['data_authority']['record_count'], 1)
            original = console_state._read_jsonl
            def guarded(path):
                """Input: Path. Output: list[dict]. Reject a second unchanged ledger read."""
                if path == ledger:
                    raise AssertionError('unchanged ledger reread')
                return original(path)
            with patch.object(console_state, '_read_jsonl', side_effect=guarded):
                self.assertEqual(console_state.load_console_state(paths)['data_authority']['record_count'], 1)
            ledger.write_text('{}\n{}\n')
            self.assertEqual(console_state.load_console_state(paths)['data_authority']['record_count'], 2)

    def test_health_does_not_build_dashboard(self):
        """Input: local HTTP request. Output: None. Verify reuse identity without loading runtime data."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            server = console_server.make_console_server('127.0.0.1', 0, paths)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.object(console_server, '_load_cached_console_state', side_effect=AssertionError('expensive health')):
                    try:
                        with urlopen(f'http://127.0.0.1:{server.server_port}/api/health') as response:
                            payload = json.load(response)
                    except Exception:
                        payload = {}
                self.assertEqual(payload.get('app'), 'BrainWorkflow')
                self.assertEqual(payload['workflow_root'], str(paths.workflow_root.resolve()))
                self.assertEqual(payload['runs_root'], str(paths.runs_root.resolve()))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
