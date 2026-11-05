"""Temporary tombstone test; retire this file with the disabled board adapter."""

from contextlib import redirect_stderr
import io
import unittest
from unittest.mock import patch

from wqb.signboard_launcher import main


class SignboardLauncherTests(unittest.TestCase):
    def test_retired_entry_refuses_to_launch(self):
        """Input: retired entry. Output: assertions; never launch or probe services."""
        errors = io.StringIO()
        with patch("subprocess.Popen", side_effect=AssertionError("launch forbidden")), patch(
            "socket.socket", side_effect=AssertionError("network forbidden")
        ), redirect_stderr(errors):
            self.assertEqual(main(), 1)
        self.assertIn("retired", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
