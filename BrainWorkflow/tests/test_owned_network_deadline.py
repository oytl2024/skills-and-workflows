"""Offline request receipts and owned-process deadline regressions."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wqb.client import WQBClient
from wqb.runtime_control import CONTROL_ENV, DEADLINE_ENV, _write


def fixture_execution(arguments):
    """Input: real execute-role argv list. Output: exit code; only local fixture HTTP replaces the workflow step."""
    from wqb import research_group_driver as driver
    from wqb.recorder import RunRecorder
    from wqb.submission_attempts import start_submission_attempt, finish_submission_attempt
    from wqb.workflow_driver import run_workflow_driver
    import hashlib
    def lane(paths, group, run, *, config):
        """Input: authenticated lane arguments. Output: real driver result using one local POST."""
        initial = dict(active=True, run_dir=str(run))
        config = {**config, 'bound_group_lane': str(run)}
        def step():
            """Input: none. Output: result after a bounded local HTTP POST and real submission WAL."""
            # This descendant cannot escape the real supervisor's Job/session.
            descendant = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(60)'])
            _write(run / 'fixture_descendant.json', {'pid': descendant.pid})
            recorder = RunRecorder(run / 'stages/offline-network')
            metadata = [{'expression_hash': hashlib.sha256(b'rank(close)').hexdigest()}]
            attempt = start_submission_attempt(recorder, metadata, 'offline-network')
            client = WQBClient(timeout_seconds=.6, max_retries=0)
            client.session.trust_env = False
            client.authenticated = True
            response = client.request('POST', os.environ['FIXTURE_HTTP'] + '/simulations',
                json={'regular': 'rank(close)', 'settings': {}})
            finish_submission_attempt(recorder, metadata, attempt, 'SUBMITTED',
                progress_url=response.headers['Location'])
            descendant.terminate()
            descendant.wait(5)
            return {**initial, 'status': 'completed'}
        return run_workflow_driver(paths, config, step=step, status_reader=lambda: initial)
    with patch.object(driver, 'run_group_lane', side_effect=lane):
        return driver.main(arguments)


class OwnedRequestTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: None; create an isolated owning-lane receipt."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / 'lane'
        self.job = self.run / 'runtime/group_workers' / ('a' * 32)
        self.nonce = 'b' * 32
        self.owner = dict(run_dir=str(self.run), job_id=self.job.name, owner_nonce=self.nonce,
            supervisor_pid=os.getppid(), execution_pid=os.getpid(),
            request_timeout_seconds=2.0, runtime_deadline=time.monotonic() + 10)
        _write(self.job / 'network_owner.json', self.owner)
        _write(self.run / 'runtime/group_worker.json', dict(job_id=self.job.name,
            pid=os.getppid(), status='running'))
        self.environment = {CONTROL_ENV: str(self.run),
            'BRAIN_WORKFLOW_NETWORK_JOB': str(self.job),
            'BRAIN_WORKFLOW_NETWORK_NONCE': self.nonce}

    def test_unmanaged_injected_session_is_not_serialized_or_supervised(self):
        session = SimpleNamespace(headers={}, request=lambda *a, **k: 'unchanged')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(WQBClient(session=session)._dispatch('GET', 'private-url'), 'unchanged')
        self.assertFalse((self.job / 'network_current.json').exists())

    def test_dispatch_receipt_is_sanitized_and_clamped_to_original_deadline(self):
        deadline = time.monotonic() + .5
        def request(*args, **kwargs):
            """Input: fake HTTP call. Output: response after inspecting dispatch-time evidence."""
            current = json.loads((self.job / 'network_current.json').read_text())
            self.assertEqual(current['state'], 'entered')
            self.assertEqual(current['simulation_identities'], ['c' * 64])
            self.assertLessEqual(current['deadline'], deadline)
            self.assertEqual(current['operation'], 'simulation_submit')
            return SimpleNamespace(status_code=201, headers={'Location': 'private-response-url'})
        session = SimpleNamespace(headers={}, request=request)
        with patch.dict(os.environ, {**self.environment, DEADLINE_ENV: str(deadline)}, clear=True), \
                patch('wqb.research_group.record_payload_outcome'):
            response = WQBClient(timeout_seconds=5, session=session)._dispatch('POST',
                'https://private-host/simulations?token=secret', simulation_identities=['c' * 64],
                json={'secret-payload': 'secret'}, timeout=5)
        self.assertEqual(response.status_code, 201)
        current = json.loads((self.job / 'network_current.json').read_text())
        self.assertEqual(current['state'], 'completed')
        evidence = '\n'.join(p.read_text() for p in self.job.rglob('network*.json'))
        for secret in ('private-host', 'private-response-url', 'secret-payload', 'token=secret'):
            self.assertNotIn(secret, evidence)
        self.assertEqual(len(list((self.job / 'network_requests').glob('*.json'))), 2)

    def test_bad_nonce_pid_and_runtime_deadline_fail_before_dispatch(self):
        for field, value in [('owner_nonce', 'd' * 32), ('execution_pid', os.getpid() + 1),
                             ('runtime_deadline', float('nan'))]:
            with self.subTest(field=field):
                _write(self.job / 'network_owner.json', {**self.owner, field: value})
                session = SimpleNamespace(headers={}, request=lambda *a, **k: self.fail('not authenticated'))
                with patch.dict(os.environ, self.environment, clear=True), self.assertRaises(ValueError):
                    WQBClient(session=session)._dispatch('GET', 'https://private-host/')

    def test_streaming_cannot_escape_the_owned_total_bound(self):
        session = SimpleNamespace(headers={}, request=lambda *a, **k: self.fail('stream must be rejected'))
        with patch.dict(os.environ, self.environment, clear=True), self.assertRaises(ValueError):
            WQBClient(session=session)._dispatch('GET', 'https://private-host/', stream=True)

    def test_no_dispatch_deadline_exists_while_waiting_for_fair_admission(self):
        from wqb.owned_network_deadline import owned_submission_gate, OwnedSubmissionFence
        broker = OwnedSubmissionFence(self.run, self.job, self.owner)
        done, failures = threading.Event(), []
        def dispatch():
            """Input: none. Output: None; enter a fake request only after the supervisor grants the original fence."""
            try:
                with owned_submission_gate(self.run):
                    session = SimpleNamespace(headers={}, request=lambda *a, **k:
                        SimpleNamespace(status_code=200, headers={}))
                    WQBClient(session=session)._dispatch('GET', 'https://private-host/')
            except Exception as error:
                failures.append(repr(error))
            finally:
                done.set()
        with patch.dict(os.environ, self.environment, clear=True), \
                patch('wqb.runtime_control.check_submission_allowed'):
            worker = threading.Thread(target=dispatch)
            worker.start()
            try:
                until = time.monotonic() + 3
                while not (self.job / 'network_admission.json').exists() and time.monotonic() < until:
                    time.sleep(.01)
                self.assertFalse((self.job / 'network_current.json').exists())
                broker.step()
                self.assertTrue(done.wait(3))
                self.assertEqual(failures, [])
                self.assertIsNotNone(broker.gate)
                broker.step()
                self.assertIsNone(broker.gate)
            finally:
                broker.release()
                worker.join(3)

    def test_existing_packaged_module_allows_execute_role_without_new_allowlist(self):
        from wqb.desktop_application import packaged_worker_command, dispatch_worker
        command = packaged_worker_command(['offline-host.exe', '-m', 'wqb.research_group_driver', 'execute'],
            frozen=True, executable='offline-host.exe')
        self.assertEqual(command, ['offline-host.exe', '--worker-module', 'wqb.research_group_driver', 'execute'])
        with patch('wqb.desktop_application.runpy.run_module') as execute, patch.object(sys, 'argv', []):
            dispatch_worker('wqb.research_group_driver', ['execute'])
        execute.assert_called_once()


if __name__ == '__main__':
    unittest.main()
