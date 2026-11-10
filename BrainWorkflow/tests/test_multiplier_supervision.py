"""Offline process containment tests; no platform/client use."""
import importlib
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class MultiplierSupervisionTests(unittest.TestCase):
    def supervise(self, command, *, seconds, cancel=lambda: None, permit=lambda: None):
        """Input: local child argv and callbacks. Output: owned subprocess result or bounded error."""
        module = importlib.import_module('wqb.multiplier_supervision')
        return module.supervise_command(command, cwd=Path.cwd(), deadline=time.time() + seconds,
            check_cancelled=cancel, progress=lambda: None, permit=permit)

    def test_total_deadline_terminates_slow_owned_process(self):
        started = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, 'deadline'):
            self.supervise([sys.executable, '-c', 'import time; time.sleep(60)'], seconds=1)
        self.assertLess(time.monotonic() - started, 8)

    def test_stop_terminates_child_before_returning(self):
        started = time.monotonic()
        def cancel():
            """Input: none. Output: interruption after enough time for a child to start."""
            if time.monotonic() - started > .3:
                raise InterruptedError('durable Stop')
        with self.assertRaisesRegex(InterruptedError, 'Stop'):
            self.supervise([sys.executable, '-c', 'import time; time.sleep(60)'], seconds=30, cancel=cancel)
        self.assertLess(time.monotonic() - started, 8)

    def test_admission_failure_never_leaves_child_running(self):
        def refuse():
            """Input: none. Output: admission failure before any work is allowed."""
            raise ValueError('refused admission')
        with self.assertRaisesRegex(ValueError, 'admission'):
            self.supervise([sys.executable, '-c', 'import time; time.sleep(60)'], seconds=20, permit=refuse)

    def test_success_waits_for_owned_child(self):
        self.assertEqual(self.supervise([sys.executable, '-c', 'pass'], seconds=10), 0)

    def test_packaged_preparation_worker_is_explicitly_allowlisted(self):
        from wqb.desktop_application import packaged_worker_command
        command = packaged_worker_command([sys.executable, '-m', 'wqb.multiplier_supervision', '--help'],
            frozen=True, executable=sys.executable)
        self.assertEqual(command[1:3], ['--worker-module', 'wqb.multiplier_supervision'])

    def test_real_worker_reuses_local_sources_without_network_and_preserves_deadline(self):
        from datetime import datetime, timezone
        from wqb.data_field_capture import capture_platform_data_fields
        from wqb.data_ledger_compile import compile_data_ledger_from_raw
        from wqb.multiplier_scope import publish_scope_catalog
        from tests.test_multiplier_scope import settings_fixture
        from wqb.multiplier_supervision import prepare_multiplier_fields_supervised
        from wqb.multiplier_preparation import _load
        class Client:
            def get_json(self, path):
                """Input: API-like path. Output: fictional source rows, never network."""
                if path == '/operators':
                    return []
                if path.startswith('/data-sets'):
                    return {'results': [{'id': 'd'}], 'count': 1}
                return {'results': [{'id': 'f', 'type': 'MATRIX', 'coverage': .8}], 'count': 1}
        with tempfile.TemporaryDirectory() as directory:
            root, job = Path(directory) / 'knowledge', Path(directory) / 'job'
            captured = datetime.now(timezone.utc).isoformat()
            summary = capture_platform_data_fields(Client(), root, generated_at=captured,
                instrument_types=['EQUITY'], regions=['USA'], delays=[1], universes=['TOP3000'])
            compile_data_ledger_from_raw(root, capture_dir=Path(summary['capture_dir']))
            publish_scope_catalog(root, settings_fixture(), captured)
            kwargs = dict(check_cancelled=lambda: None, progress=lambda row: None, allow_network=False)
            scope = dict(region='USA', delay=1, universe='TOP3000')
            first = prepare_multiplier_fields_supervised(root, job, scope, **kwargs)
            deadline = _load(job / 'supervisor.json')['deadline']
            second = prepare_multiplier_fields_supervised(root, job, scope, **kwargs)
            self.assertEqual(first['requests_used'], 0)
            self.assertEqual(second['requests_used'], 0)
            self.assertEqual(_load(job / 'supervisor.json')['deadline'], deadline)
            self.assertFalse(_load(job / 'supervisor.json')['permitted'])

    def test_expired_supervisor_does_not_spawn_or_renew(self):
        from wqb.multiplier_supervision import prepare_multiplier_fields_supervised
        from wqb.multiplier_preparation import _save, validated_preparation_policy, _load
        with tempfile.TemporaryDirectory() as directory:
            root, job = Path(directory) / 'knowledge', Path(directory) / 'job'
            job.mkdir()
            policy = validated_preparation_policy({'total_seconds': 1})
            scope = dict(region='USA', delay=1, universe='TOP3000')
            started = time.time() - 20
            _save(job / 'supervisor.json', dict(scope=scope, knowledge_root=str(root), policy=policy,
                allow_network=False, started=started, deadline=started + 1))
            with patch('wqb.multiplier_supervision.subprocess.Popen') as spawn, self.assertRaises(TimeoutError):
                prepare_multiplier_fields_supervised(root, job, scope, check_cancelled=lambda: None,
                    progress=lambda row: None, policy=policy, allow_network=False)
            spawn.assert_not_called()
            self.assertEqual(_load(job / 'supervisor.json')['deadline'], started + 1)


if __name__ == '__main__':
    unittest.main()
