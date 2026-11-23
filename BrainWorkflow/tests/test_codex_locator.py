"""Executable discovery only; never execute Codex or query actual package state."""
import tempfile
import json
import os
import subprocess
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import patch


class CodexLocatorTests(unittest.TestCase):
    def test_registered_package_query_is_bounded_and_never_runs_codex(self):
        if os.name != 'nt':
            self.skipTest('Windows package discovery')
        from wqb.codex_locator import _installed_codex, DISCOVERY_TIMEOUT_SECONDS
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)/'OfficialPackage'
            executable = package/'app/resources/codex.exe'
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b'never executed')
            with patch('wqb.codex_locator.subprocess.run', return_value=SimpleNamespace(
                    returncode=0, stdout=json.dumps([str(package)]))) as query:
                result = _installed_codex()
            self.assertEqual(result['executable'], str(executable))
            self.assertIn('-NoProfile', query.call_args.args[0])
            self.assertEqual(query.call_args.kwargs['timeout'], DISCOVERY_TIMEOUT_SECONDS)
            self.assertTrue(query.call_args.kwargs['env'].get('SystemDrive'))
            self.assertEqual(query.call_args.kwargs['env'].get('PSModuleAnalysisCachePath'), 'NUL')
            self.assertIn('Get-AppxPackage', query.call_args.args[0][-1])

    def test_registered_package_timeout_is_distinct(self):
        if os.name != 'nt':
            self.skipTest('Windows package discovery')
        from wqb.codex_locator import _installed_codex
        with patch('wqb.codex_locator.subprocess.run', side_effect=subprocess.TimeoutExpired('query', 5)):
            result = _installed_codex()
        self.assertEqual(result['error'], 'codex_discovery_timeout')

    def test_path_success_never_queries_packages(self):
        from wqb.codex_locator import resolve_notification_target
        with patch('wqb.codex_locator._installed_codex') as discover:
            result = resolve_notification_target({'thread_id': '019ff06b-7447-7071-a13d-b2568f62bdb2'},
                path_lookup=lambda name: 'codex.exe')
        self.assertEqual(result['executable'], 'codex.exe')
        discover.assert_not_called()

    def test_invalid_channel_is_distinct_and_never_discovers(self):
        from wqb.codex_locator import resolve_notification_target
        with patch('wqb.codex_locator._installed_codex') as discover:
            result = resolve_notification_target({}, path_lookup=lambda name: None)
        self.assertEqual(result['error'], 'channel_not_configured')
        discover.assert_not_called()

    def test_desktop_missing_path_uses_registered_package(self):
        from wqb.codex_locator import resolve_notification_target
        with patch('wqb.codex_locator._installed_codex', return_value=dict(executable='package/codex.exe',
                source='registered_package', error='')):
            result = resolve_notification_target({'thread_id': '019ff06b-7447-7071-a13d-b2568f62bdb2'},
                path_lookup=lambda name: None)
        self.assertEqual(result['executable'], 'package/codex.exe')
        self.assertEqual(result['source'], 'registered_package')

    def test_explicit_executable_must_be_absolute_existing_file(self):
        from wqb.codex_locator import resolve_notification_target
        channel = dict(thread_id='019ff06b-7447-7071-a13d-b2568f62bdb2', codex_executable='relative.exe')
        result = resolve_notification_target(channel, path_lookup=lambda name: 'codex.exe')
        self.assertEqual(result['error'], 'codex_executable_invalid')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'codex.exe'
            path.write_bytes(b'fictional, never executed')
            result = resolve_notification_target(dict(channel, codex_executable=str(path)), path_lookup=lambda name: None)
        self.assertEqual(result['source'], 'configured')

    def test_discovery_failure_does_not_claim_a_channel_failure(self):
        from wqb.codex_locator import resolve_notification_target
        with patch('wqb.codex_locator._installed_codex', return_value=dict(executable=None,
                source='registered_package', error='codex_discovery_timeout')):
            result = resolve_notification_target({'thread_id': '019ff06b-7447-7071-a13d-b2568f62bdb2'},
                path_lookup=lambda name: None)
        self.assertEqual(result['error'], 'codex_discovery_timeout')
        self.assertIsNone(result['executable'])
