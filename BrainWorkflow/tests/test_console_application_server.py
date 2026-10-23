"""Offline HTTP contracts; temporary evidence and injected jobs only."""
import copy
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wqb import console_server as server_module
from wqb.console_state import ConsolePaths
from wqb.research_group import create_group


def save(path, value):
    """Input: Path/JSON value. Output: None; persist isolated fictional evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class ConsoleApplicationServerTests(unittest.TestCase):
    def setUp(self):
        """Input: none. Output: None; start an offline local HTTP fixture."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.paths = ConsolePaths(root, root / 'product', root / 'knowledge', root / 'runs',
                                  root / 'milestone.md', root / 'todo.md', root / 'runs/console_jobs')
        self.run = self.paths.runs_root / 'fixture-run'
        self.state = {'active_workflow': {'exists': True, 'run_id': self.run.name,
                      'run_dir': str(self.run), 'status': 'paused', 'current_stage': 'scout_seed'},
                      'runtime_control': {'desired_state': 'paused', 'request_revision': 'r1'},
                      'option_cards': [{'option_id': 'option-a', 'title': 'Fixture'}]}
        save(self.run / 'run_state.json', self.state['active_workflow'])
        self.hot = patch.object(server_module, '_load_runtime_snapshot', side_effect=lambda *_: copy.deepcopy(self.state))
        self.hot.start()
        self.addCleanup(self.hot.stop)
        self.cold = patch.object(server_module, 'load_console_state', side_effect=AssertionError('cold path used'))
        self.cold.start()
        self.addCleanup(self.cold.stop)
        self.server = server_module.make_console_server('127.0.0.1', 0, self.paths)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.origin = 'http://%s:%s' % self.server.server_address

    def close_server(self):
        """Input: none. Output: None; stop fixture HTTP server before removing evidence."""
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()

    def request(self, method='GET', path='/api/application/snapshot', body=None, headers=None):
        """Input: request fields. Output: status/headers/body tuple; make one bounded localhost request."""
        connection = HTTPConnection(*self.server.server_address, timeout=3)
        try:
            outgoing = {'Origin': self.origin, 'Content-Type': 'application/json'}
            outgoing.update(headers or {})
            connection.request(method, path, body=body, headers=outgoing)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def snapshot(self):
        """Input: none. Output: snapshot dict; require JSON and no cold resource traversal."""
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertIn('application/json', headers['Content-Type'])
        return json.loads(body)

    def command(self, **changes):
        """Input: command overrides. Output: revision-bound fictional command dict."""
        snapshot = self.snapshot()
        return {'command_id': 'fixture-command', 'action': 'start',
                'expected_revision': snapshot['request_revision'],
                'group_id': snapshot['group']['group_id'], **changes}

    def post(self, command, **kwargs):
        """Input: command dict and request options. Output: HTTP tuple; send JSON once."""
        return self.request('POST', '/api/application/commands', json.dumps(command), **kwargs)

    def test_snapshot_sequence_epoch_and_two_lanes_are_read_only(self):
        first, second = self.snapshot(), self.snapshot()
        self.assertEqual(first['server_epoch'], second['server_epoch'])
        self.assertGreater(second['sequence'], first['sequence'])
        self.assertEqual(first['request_revision'], second['request_revision'])
        group = create_group(self.paths.runs_root,
                             [{'run_id': 'lane-a', 'plan_digest': 'a'*64},
                              {'run_id': 'lane-b', 'plan_digest': 'b'*64}],
                             {'enable_live_api': False, 'max_runtime_seconds': 100, 'max_recoveries': 1})
        save(self.paths.runs_root / 'active_research_group.json', {'group_id': group['group_id']})
        for run_id in ('lane-a', 'lane-b'):
            save(self.paths.runs_root / run_id / 'run_state.json',
                 {'run_id': run_id, 'status': 'paused', 'current_stage': 'repair'})
        result = self.snapshot()
        self.assertEqual([lane['lane_id'] for lane in result['lanes']], ['lane-a', 'lane-b'])
        self.assertFalse(result['allowed_actions']['start'])
        self.assertTrue(result['blocker'])
        self.state['active_workflow']['group_id'] = group['group_id']
        with patch.object(server_module, 'run_console_action') as runner:
            reply = json.loads(self.post(self.command(command_id='group-never-legacy'))[2])
            self.assertEqual(reply['status'], 'refused')
            runner.assert_not_called()

    def test_sequence_shared_across_pollers_and_epoch_changes_after_restart(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.snapshot())) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len({row['sequence'] for row in results}), 5)
        later = self.snapshot()
        self.assertGreater(later['sequence'], max(row['sequence'] for row in results))
        replacement = server_module.make_console_server('127.0.0.1', 0, self.paths)
        try:
            self.assertNotEqual(replacement.application_epoch, later['server_epoch'])
            self.assertEqual(replacement.application_sequence, 0)
        finally:
            replacement.server_close()

    def prepared_group(self, count):
        """Input: lane count int. Output: fixture/group tuple with certified offline authority."""
        from tests.test_research_group_driver import ResearchGroupDriverTests
        from wqb.research_group_driver import initialize_group_runtime
        case = ResearchGroupDriverTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        group = case.prepared(count, live=False)
        initialize_group_runtime(case.paths, group)
        p = case.paths
        self.paths = ConsolePaths(p.project_root, p.workflow_root, p.knowledge_root, p.run_root,
            p.project_root / 'milestone.md', p.project_root / 'todo.md', p.run_root / 'console_jobs')
        self.server.console_paths = self.paths
        # The legacy hot loader intentionally supplies no group ID or lane authority.
        self.state = {'active_workflow': {}, 'runtime_control': {}, 'option_cards': []}
        return case, group

    def test_real_group_http_start_stop_n1_n2_n4_and_receipt_replay(self):
        from wqb import research_group_driver as driver
        from wqb.research_group import read_group
        original = driver.start_group_workers
        for count in (1, 2, 4):
            with self.subTest(count=count):
                case, group = self.prepared_group(count)
                before = self.snapshot()
                self.assertEqual(len(before['lanes']), count)
                self.assertTrue(before['allowed_actions']['start'])
                self.assertNotEqual(before['request_revision'], group['request_revision'])
                command = self.command(command_id='start-' + str(count))
                def start(paths, target, **kwargs):
                    """Input: real dispatch args. Output: real driver result with fake process spawning."""
                    self.assertEqual(kwargs['expected_revision'], group['request_revision'])
                    return original(paths, target, **kwargs, spawn_runner=case.spawn)
                with patch.object(driver, 'start_group_workers', side_effect=start), \
                     patch.object(server_module, 'run_console_action') as legacy:
                    reply = json.loads(self.post(command)[2])
                    self.assertEqual(reply['status'], 'accepted', reply)
                    self.assertEqual(json.loads(self.post(command)[2]), reply)
                    self.assertEqual(len(case.spawned), count)
                    running = self.snapshot()
                    self.assertEqual(running['group']['desired_state'], 'running')
                    self.assertEqual(running['allowed_actions'], {'start': False, 'stop': True})
                    stop = self.command(command_id='stop-' + str(count), action='stop')
                    self.assertEqual(json.loads(self.post(stop)[2])['status'], 'accepted')
                    self.assertEqual(read_group(Path(group['group_dir']))['desired_state'], 'paused')
                    self.assertTrue(self.snapshot()['allowed_actions']['start'])
                    legacy.assert_not_called()
                self.assertFalse((p := self.paths.runs_root / 'active_run.json').exists(), str(p))

    def test_group_stop_survives_corrupt_lane_evidence(self):
        from wqb.research_group import resume_group, read_group
        case, group = self.prepared_group(2)
        resume_group(Path(group['group_dir']), group['request_revision'])
        (case.paths.run_root / 'lane-0/run_state.json').write_text('{', encoding='utf-8')
        snapshot = self.snapshot()
        self.assertEqual(snapshot['group']['group_id'], group['group_id'])
        self.assertTrue(snapshot['blocker'])
        self.assertEqual(snapshot['allowed_actions'], {'start': False, 'stop': True})
        stop = self.command(command_id='corrupt-lane-stop', action='stop')
        self.assertEqual(json.loads(self.post(stop)[2])['status'], 'accepted')
        self.assertEqual(read_group(Path(group['group_dir']))['desired_state'], 'paused')

    def test_idle_http_start_prepares_real_group_asynchronously_then_dispatches_fake_workers(self):
        """Input: persisted opt-in config/card. Output: HTTP async job through real composer/group, no CLI or live process."""
        from dataclasses import replace
        from tests.test_console_start import PreplannedConsoleStartTests
        from wqb import console_start, research_group_driver
        from wqb.console_jobs import finish_job
        case = PreplannedConsoleStartTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.paths = case.paths
        self.server.console_paths = self.paths
        self.state = dict(active_workflow={}, runtime_control={}, option_cards=[case.case.option])
        jobs, callbacks, spawned = [], [], []

        def launch(job, *, on_complete):
            """Input: durable job/callback. Output: fake async acknowledgement, never launch a process."""
            jobs.append(job)
            callbacks.append(on_complete)
            return replace(job, status='running')

        def spawn(argv, **kwargs):
            """Input: genuine lane argv/kwargs. Output: fake PID; retain dispatch evidence only."""
            spawned.append(argv)
            return SimpleNamespace(pid=800001)

        original = research_group_driver.start_group_workers
        def dispatch(paths, group, **kwargs):
            """Input: genuine group dispatch. Output: real group result with fake process spawning."""
            return original(paths, group, **kwargs, spawn_runner=spawn)

        command = self.command(command_id='idle-start', selected_option_id=case.case.option['option_id'])
        with patch.object(server_module, 'load_runtime_state', side_effect=lambda *_: copy.deepcopy(self.state)), \
             patch.object(server_module, 'start_job_async', side_effect=launch), \
             patch.object(server_module, '_record_async_console_job_context'):
            reply = json.loads(self.post(command)[2])
            self.assertEqual(reply['status'], 'accepted', reply)
            self.assertEqual(len(jobs), 1)
            self.assertIn('wqb.console_start', jobs[0].command)
            self.assertNotIn('--enable-live-api', jobs[0].command)
            request = console_start.read_start_request(self.paths.runs_root)
            self.state['start_preparation'] = request
            self.assertEqual(self.snapshot()['allowed_actions'], {'start': False, 'stop': True})
            self.assertEqual(json.loads(self.post(command)[2]), reply)
            with patch('wqb.initial_model_worker.create_initial_model_runner', return_value=case.case.runner):
                result = console_start.execute_start(self.paths, jobs[0].metadata['form'], request['request_id'])
            self.assertTrue(result['passed'], result)
            self.assertEqual(result['request_id'], request['request_id'])
            self.assertEqual(spawned, [])
            Path(jobs[0].stdout_path).write_text(json.dumps(result), encoding='utf-8')
            completed = finish_job(jobs[0], 'completed', exit_code=0)
            with patch.object(research_group_driver, 'start_group_workers', side_effect=dispatch):
                callbacks[0](completed)
                callbacks[0](completed)
            self.assertEqual(len(spawned), 1)
            self.state['start_preparation'] = console_start.read_start_request(self.paths.runs_root)
            snapshot = self.snapshot()
            self.assertEqual(snapshot['group']['group_id'], Path(result['group_dir']).name)
            self.assertEqual(snapshot['group']['desired_state'], 'running')
            self.assertEqual(snapshot['allowed_actions'], {'start': False, 'stop': True})
            stop = self.command(command_id='idle-group-stop', action='stop')
            self.assertEqual(json.loads(self.post(stop)[2])['status'], 'accepted')
            self.assertFalse((self.paths.runs_root / 'active_run.json').exists())

    def test_idle_json_start_uses_selected_kor_scope_not_usa_config_default(self):
        """Input: KOR card and USA defaults, JSON only option ID. Output: exact KOR form without a user gate."""
        from tests.test_workflow_stage_adapters import valid_option
        self.state = dict(active_workflow={}, runtime_control={}, option_cards=[dict(option_id='kor', title='KOR')])
        option = valid_option(option_id='kor')
        option['candidate_scope'] = 'KOR D0 TOP600'
        path = server_module.existing_decision_artifact_path(self.paths.knowledge_root, 'research_option_cards.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(option) + '\n', encoding='utf-8')
        save(self.paths.workflow_root / 'configs/workflow_local.json',
             dict(region='USA', delay=1, universe='TOP3000', live_api_enabled=False))
        command = self.command(command_id='kor-start', selected_option_id='kor')
        with patch.object(server_module, 'run_console_action', return_value=SimpleNamespace(status='running', job_id='kor-job')) as run:
            reply = json.loads(self.post(command)[2])
        self.assertEqual(reply['status'], 'accepted', reply)
        form = run.call_args.args[1]
        self.assertEqual(server_module._selected_scope(form), dict(region='KOR', delay=0, universe='TOP600'))
        self.assertFalse(form['enable_live_api'])

    def test_idle_json_ambiguous_option_is_inline_refusal_without_dispatch(self):
        """Input: card with two exact scopes. Output: refusal, not arbitrary USA or another manual gate."""
        from tests.test_workflow_stage_adapters import valid_option
        self.state = dict(active_workflow={}, runtime_control={}, option_cards=[dict(option_id='ambiguous', title='Multi')])
        option = valid_option(option_id='ambiguous')
        option['candidate_scope'] = 'USA D1 TOP3000 or KOR D0 TOP600'
        path = server_module.existing_decision_artifact_path(self.paths.knowledge_root, 'research_option_cards.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(option) + '\n', encoding='utf-8')
        command = self.command(command_id='ambiguous-start', selected_option_id='ambiguous')
        with patch.object(server_module, 'run_console_action') as run:
            reply = json.loads(self.post(command)[2])
        self.assertEqual(reply['status'], 'refused', reply)
        self.assertIn('scope', reply['message'])
        run.assert_not_called()

    def test_group_lost_dispatch_ack_never_replays_and_stale_cas_refuses(self):
        from wqb import research_group_driver as driver
        from wqb.research_group import stop_group
        _, group = self.prepared_group(1)
        command = self.command(command_id='lost-group-ack')
        with patch.object(driver, 'start_group_workers', side_effect=OSError('lost')) as start:
            self.assertEqual(json.loads(self.post(command)[2])['status'], 'unknown')
            self.assertEqual(json.loads(self.post(command)[2])['status'], 'unknown')
            self.assertEqual(start.call_count, 1)
        command = self.command(command_id='stale-group-cas')
        stop_group(Path(group['group_dir']), group['request_revision'])
        with patch.object(driver, 'start_group_workers') as start:
            self.assertEqual(json.loads(self.post(command)[2])['status'], 'refused')
            start.assert_not_called()

    def test_command_uses_existing_gate_returns_job_and_reconciles_duplicate(self):
        command = self.command()
        with patch.object(server_module, 'run_console_action', return_value=SimpleNamespace(
                status='running', job_id='fixture-job', error='', status_message='')) as runner:
            status, headers, body = self.post(command)
            reply = json.loads(body)
            self.assertEqual(status, 200)
            self.assertNotIn('Location', headers)
            self.assertEqual((reply['status'], reply['job_id']), ('accepted', 'fixture-job'))
            self.assertEqual(json.loads(self.post(command)[2]), reply)
            self.assertEqual(runner.call_count, 1)
            form = runner.call_args.args[1]
            self.assertEqual(form['action'], 'workflow-auto-continue')
            self.assertEqual(form['expected_runtime_revision'], 'r1')
            self.assertEqual(form['state_hash'], server_module._workflow_action_hash(self.state))
            self.assertIn(reply, self.snapshot()['command_statuses'])

    def test_foreign_origin_host_and_bad_bodies_are_json_refusals(self):
        command = self.command()
        with patch.object(server_module, 'run_console_action') as runner:
            for headers in ({'Origin': 'http://foreign.invalid'}, {'Host': 'foreign.invalid'}, {'Origin': ''}):
                status, response_headers, body = self.post(command, headers=headers)
                self.assertEqual(status, 403)
                self.assertIn('application/json', response_headers['Content-Type'])
                self.assertEqual(json.loads(body)['status'], 'refused')
            for body, headers, expected in [('{', {}, 400), ('[]', {}, 400),
                    ('{"x": NaN}', {}, 400), ('x'*8193, {}, 413),
                    ('{}', {'Content-Type': 'text/plain'}, 415),
                    ('{}', {'Transfer-Encoding': 'chunked'}, 400)]:
                status, _, result = self.request('POST', '/api/application/commands', body, headers)
                self.assertEqual(status, expected)
                self.assertEqual(json.loads(result)['status'], 'refused')
            runner.assert_not_called()

    def test_lost_callback_reply_is_unknown_and_never_replayed(self):
        command = self.command()
        with patch.object(server_module, 'run_console_action', side_effect=OSError('lost')) as runner:
            self.assertEqual(json.loads(self.post(command)[2])['status'], 'unknown')
            self.assertEqual(json.loads(self.post(command)[2])['status'], 'unknown')
            self.assertEqual(runner.call_count, 1)

    def test_stale_revision_group_mismatch_and_final_gate_refuse_without_dispatch(self):
        command = self.command()
        with patch.object(server_module, 'run_console_action') as runner:
            for changes in ({'expected_revision': 'stale'}, {'group_id': 'foreign'}):
                reply = json.loads(self.post(command | changes)[2])
                self.assertEqual(reply['status'], 'refused')
            with patch.object(server_module, 'assert_workflow_action_current', side_effect=ValueError('Stop won')):
                reply = json.loads(self.post(command | {'command_id': 'gate-race'})[2])
                self.assertEqual(reply['status'], 'refused')
            runner.assert_not_called()

    def test_runtime_failure_is_503_not_a_stale_success(self):
        with patch.object(server_module, '_load_runtime_snapshot', side_effect=OSError('fixture')):
            status, _, body = self.request()
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)['event'], 'runtime-error')

    def test_application_reads_reject_foreign_host_or_origin(self):
        for path in ('/api/application/snapshot', '/api/application/events'):
            for headers in ({'Host': 'foreign.invalid'}, {'Origin': 'http://foreign.invalid'}):
                status, response_headers, body = self.request(path=path, headers=headers)
                self.assertEqual(status, 403)
                self.assertIn('application/json', response_headers['Content-Type'])

    def test_unvisited_legacy_page_is_not_needed_to_load_option_cards(self):
        self.hot.stop()
        option_path = server_module.existing_decision_artifact_path(self.paths.knowledge_root, 'research_option_cards.jsonl')
        option_path.parent.mkdir(parents=True, exist_ok=True)
        option_path.write_text(json.dumps({'option_id': 'durable-option', 'title': 'Persisted option'}) + '\n', encoding='utf-8')
        with patch.object(server_module, 'load_runtime_state', return_value=self.state), \
             patch.object(server_module, '_normalized_option_rows', side_effect=lambda rows: rows):
            snapshot = self.snapshot()
        self.assertEqual(snapshot['options'][0]['option_id'], 'durable-option')

    def test_new_mission_uses_start_action_and_stale_stop_prevents_late_start(self):
        from tests.test_workflow_stage_adapters import valid_option
        path = server_module.existing_decision_artifact_path(self.paths.knowledge_root, 'research_option_cards.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(valid_option(option_id='option-a')) + '\n', encoding='utf-8')
        self.state['active_workflow'] = {}
        self.state['runtime_control'] = {}
        command = self.command(selected_option_id='option-a')
        with patch.object(server_module, 'run_console_action', return_value=SimpleNamespace(
                status='queued', job_id='start-job')) as runner:
            self.assertEqual(json.loads(self.post(command)[2])['status'], 'accepted')
            self.assertEqual(runner.call_args.args[1]['action'], 'workflow-start-from-option')
            self.assertEqual(runner.call_args.args[1]['selected_option_id'], 'option-a')
        command = self.command(command_id='stopped-before-dispatch')
        before = copy.deepcopy(self.state)
        self.state['runtime_control'] = {'desired_state': 'paused', 'request_revision': 'Stop-won'}
        with patch.object(server_module, '_fresh_application_state', side_effect=[before, copy.deepcopy(self.state)]), \
             patch.object(server_module, 'run_console_action') as runner:
            self.assertEqual(json.loads(self.post(command)[2])['status'], 'refused')
            runner.assert_not_called()

    def test_events_full_snapshot_heartbeat_error_and_recovery(self):
        states = [copy.deepcopy(self.state), copy.deepcopy(self.state), OSError('fixture'), copy.deepcopy(self.state)]
        connection = HTTPConnection(*self.server.server_address, timeout=3)
        def next_state(*_):
            """Input: ignored reader args. Output: fixture state or one explicit runtime error."""
            value = states.pop(0) if states else copy.deepcopy(self.state)
            if isinstance(value, Exception):
                raise value
            return value
        with patch.object(server_module, '_load_runtime_snapshot', side_effect=next_state), \
             patch.object(server_module, 'CONSOLE_EVENT_INTERVAL_SECONDS', .01), \
             patch.object(server_module, 'CONSOLE_STREAM_SECONDS', .3):
            try:
                connection.request('GET', '/api/application/events')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                frames = [(frame.splitlines()[0].removeprefix('event: '),
                           json.loads(frame.splitlines()[1].removeprefix('data: ')))
                          for frame in response.read().decode().strip().split('\n\n')]
                self.assertEqual([event for event, _ in frames[:4]], ['snapshot', 'heartbeat', 'runtime-error', 'snapshot'])
                sequences = [payload['sequence'] for _, payload in frames]
                self.assertEqual(sequences, sorted(set(sequences)))
                self.assertEqual(frames[1][1]['lanes'][0]['lane_id'], self.run.name)
            finally:
                if 'response' in locals():
                    response.close()
                connection.close()

    def test_static_dist_only_and_legacy_root_remains(self):
        self.assertEqual(self.request(path='/app')[0], 404)
        dist = self.paths.workflow_root / 'frontend/dist'
        (dist / 'assets').mkdir(parents=True)
        (dist / 'index.html').write_text('<main>Built fixture</main>', encoding='utf-8')
        (dist / 'assets/app.js').write_text('/* fixture */', encoding='utf-8')
        status, headers, _ = self.request(path='/app')
        self.assertEqual((status, headers.get('Location')), (307, '/app/'))
        self.assertIn(b'Built fixture', self.request(path='/app/')[2])
        status, headers, _ = self.request(path='/app/assets/app.js')
        self.assertEqual(status, 200)
        self.assertIn('javascript', headers['Content-Type'])
        for path in ('/app/../index.html', '/app/assets/%2e%2e/index.html',
                     '/app/assets/%5c..%5cindex.html', '/app/package.json'):
            self.assertEqual(self.request(path=path)[0], 404)
        with patch.object(server_module, '_load_cached_console_state', return_value=self.state), \
             patch.object(server_module, 'render_dashboard', return_value='legacy'):
            self.assertEqual(self.request(path='/')[2], b'legacy')


if __name__ == '__main__':
    unittest.main()
