import tempfile
import unittest
from pathlib import Path

from wqb.source_run_lock import acquire_source_run_lock, read_source_run_lock, release_source_run_lock


class SourceRunLockTests(unittest.TestCase):
    def test_acquire_lock_creates_running_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = acquire_source_run_lock(Path(tmp), "retry-planned", "2026-08-12T00:00:00+00:00", pid=123)

        self.assertEqual(lock["status"], "acquired")
        self.assertEqual(lock["action"], "retry-planned")
        self.assertEqual(lock["pid"], 123)

    def test_active_lock_refuses_second_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquire_source_run_lock(root, "retry-planned", "2026-08-12T00:00:00+00:00", pid=123, process_alive=lambda pid: True)
            second = acquire_source_run_lock(root, "complete-in-flight", "2026-08-12T00:00:01+00:00", pid=124, process_alive=lambda pid: True)

        self.assertEqual(second["status"], "locked")
        self.assertEqual(second["active_action"], "retry-planned")

    def test_stale_lock_is_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquire_source_run_lock(root, "retry-planned", "2026-08-12T00:00:00+00:00", pid=123, process_alive=lambda pid: True)
            second = acquire_source_run_lock(root, "complete-in-flight", "2026-08-12T02:00:00+00:00", pid=124, ttl_seconds=60, process_alive=lambda pid: False)
            loaded = read_source_run_lock(root)

        self.assertEqual(second["status"], "acquired")
        self.assertEqual(loaded["action"], "complete-in-flight")

    def test_release_marks_lock_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquire_source_run_lock(root, "retry-planned", "2026-08-12T00:00:00+00:00", pid=123)
            released = release_source_run_lock(root, "retry-planned", "2026-08-12T00:05:00+00:00")

        self.assertEqual(released["status"], "released")


if __name__ == "__main__":
    unittest.main()
