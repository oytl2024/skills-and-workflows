import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.probe_maintenance_sandbox import run_probe_command


class MaintenanceSandboxProbeTest(unittest.TestCase):
    def test_timeout_stops_owned_process_tree_and_records_failure(self):
        process = Mock(pid=1234)
        process.wait.side_effect = [subprocess.TimeoutExpired("probe", 30), 1]
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.probe_maintenance_sandbox.subprocess.Popen", return_value=process):
                with patch("scripts.probe_maintenance_sandbox.subprocess.run") as stop:
                    stop.return_value.returncode = 0
                    result = run_probe_command(["fake-codex"], Path(directory))
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["returncode"], -1)
        self.assertIn("1234", stop.call_args.args[0])
        self.assertIn("/T", stop.call_args.args[0])

    def test_failed_startup_is_not_success(self):
        process = Mock()
        process.wait.return_value = 1
        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.probe_maintenance_sandbox.subprocess.Popen", return_value=process):
                result = run_probe_command(["fake-codex"], Path(directory))
        self.assertEqual(result["returncode"], 1)
        self.assertFalse(result["timed_out"])

    def test_cleanup_timeout_remains_a_recorded_failure(self):
        process = Mock(pid=1234)
        process.wait.side_effect = [subprocess.TimeoutExpired("probe", 30),
                                    subprocess.TimeoutExpired("probe", 5)]
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.probe_maintenance_sandbox.subprocess.Popen", return_value=process):
                with patch("scripts.probe_maintenance_sandbox.subprocess.run",
                           side_effect=subprocess.TimeoutExpired("taskkill", 10)):
                    result = run_probe_command(["fake-codex"], Path(directory))
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["cleanup_required"])
        self.assertEqual(result["returncode"], -1)
