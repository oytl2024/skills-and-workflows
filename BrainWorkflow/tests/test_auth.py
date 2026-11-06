import os
import unittest
from unittest.mock import patch

from wqb.auth import load_credentials


class AuthTests(unittest.TestCase):
    def test_load_credentials_falls_back_to_windows_user_environment(self):
        with patch.dict(os.environ, {"WQB_USERNAME": "", "WQB_PASSWORD": ""}):
            with patch(
                "wqb.auth._read_windows_user_env_var",
                side_effect=lambda name: {
                    "WQB_USERNAME": " user@example.com ",
                    "WQB_PASSWORD": " secret ",
                }.get(name, ""),
            ):
                self.assertEqual(("user@example.com", "secret"), load_credentials())

    def test_load_credentials_prefers_process_environment(self):
        with patch.dict(
            os.environ,
            {"WQB_USERNAME": "process-user", "WQB_PASSWORD": "process-pass"},
        ):
            with patch(
                "wqb.auth._read_windows_user_env_var",
                return_value="user-level-value",
            ):
                self.assertEqual(("process-user", "process-pass"), load_credentials())


if __name__ == "__main__":
    unittest.main()
