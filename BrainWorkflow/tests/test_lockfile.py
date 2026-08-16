import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb.lockfile import exclusive_json_lock


class LockfileTests(unittest.TestCase):
    def test_live_lock_holder_is_not_evicted_after_stale_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_path = root / "api_submission_claims.lock"
            nested_acquired = False

            with exclusive_json_lock(lock_path, 0.1, 0.001, 0.001, "outer lock is busy"):
                lock_path.write_text(
                    json.dumps({"token": "old-live", "created_at": 1}),
                    encoding="utf-8",
                )
                try:
                    with exclusive_json_lock(
                        lock_path,
                        0.01,
                        0.001,
                        0.001,
                        "nested lock is busy",
                    ):
                        nested_acquired = True
                except ValueError:
                    pass

        self.assertFalse(nested_acquired)

    def test_stale_recovery_blocks_nested_acquire_during_rename_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_path = root / "api_submission_claims.lock"
            lock_path.write_text(json.dumps({"token": "stale", "created_at": 1}), encoding="utf-8")
            nested_acquired = False
            original_rename = Path.rename

            def rename_with_nested_acquire(path: Path, target: Path):
                """Input: source and target paths. Output: rename result. Probe canonical-lock gap."""
                nonlocal nested_acquired
                result = original_rename(path, target)
                if path == lock_path and ".stale." in target.name:
                    try:
                        with exclusive_json_lock(
                            lock_path,
                            0.01,
                            0.001,
                            0.001,
                            "nested lock is busy",
                        ):
                            nested_acquired = True
                    except ValueError:
                        pass
                return result

            with patch("pathlib.Path.rename", autospec=True, side_effect=rename_with_nested_acquire):
                with exclusive_json_lock(
                    lock_path,
                    0.1,
                    0.001,
                    0.001,
                    "outer lock is busy",
                ):
                    pass

        self.assertFalse(nested_acquired)
