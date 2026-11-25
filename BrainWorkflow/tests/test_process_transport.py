"""UTF-8 diagnostics and hidden background children, with no model or platform calls."""
import os
import subprocess
import sys
import unittest


class ProcessTransportTests(unittest.TestCase):
    def test_cancellable_worker_reads_utf8_without_console(self):
        from wqb.ai_checkpoints import _run_cancellable
        command = [sys.executable, '-c',
            'import os,ctypes; os.write(1,"中文✓".encode("utf-8")); '
            'os.write(2,"错误".encode("utf-8")); '
            'print("|console="+str(ctypes.windll.kernel32.GetConsoleWindow()) if os.name=="nt" else "")']
        result = _run_cancellable(command, 10, cancel_on_pause=False)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith('中文✓'))
        self.assertEqual(result.stderr, '错误')
        if os.name == 'nt':
            self.assertIn('|console=0', result.stdout)

    def test_transport_options_preserve_non_windows_behavior(self):
        from wqb.process_transport import background_process_options
        from unittest.mock import patch
        with patch('wqb.process_transport.os.name', 'posix'):
            self.assertEqual(background_process_options(), {})
            self.assertEqual(background_process_options(text=True), dict(encoding='utf-8', errors='replace'))
