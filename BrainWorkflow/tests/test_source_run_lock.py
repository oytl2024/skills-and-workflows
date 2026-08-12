import tempfile
import threading
import time
import unittest
import os
import json
from pathlib import Path
from unittest.mock import patch

import wqb.source_run_lock as source_run_lock
from wqb.source_run_lock import _acquire_guard, _release_guard, acquire_source_run_lock, read_source_run_lock, release_source_run_lock


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
            loaded = read_source_run_lock(root)

        self.assertEqual(released["status"], "ownership_required")
        self.assertEqual(loaded["status"], "running")

    def test_correct_owner_identity_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquired = acquire_source_run_lock(root, "retry-planned", "2026-08-12T00:00:00+00:00", pid=123, process_alive=lambda pid: False)
            released = release_source_run_lock(
                root,
                "retry-planned",
                "2026-08-12T00:05:00+00:00",
                pid=acquired["pid"],
                owner_id=acquired["owner_id"],
            )

        self.assertEqual(released["status"], "released")

    def test_concurrent_acquisition_admits_only_one_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_read = source_run_lock.read_source_run_lock

            def slow_read(run_dir):
                row = original_read(run_dir)
                time.sleep(0.02)
                return row

            results = []

            def acquire(pid):
                results.append(
                    acquire_source_run_lock(
                        root,
                        "retry-planned",
                        "2026-08-12T00:00:00+00:00",
                        pid=pid,
                        process_alive=lambda process_id: True,
                    )
                )

            with patch.object(source_run_lock, "read_source_run_lock", side_effect=slow_read):
                threads = [threading.Thread(target=acquire, args=(pid,)) for pid in range(123, 127)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)

        self.assertEqual(len(results), 4)
        self.assertEqual(sum(result["status"] == "acquired" for result in results), 1)
        self.assertEqual(sum(result["status"] in {"locked", "busy"} for result in results), 3)

    def test_mismatched_release_does_not_release_active_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquired = acquire_source_run_lock(
                root,
                "retry-planned",
                "2026-08-12T00:00:00+00:00",
                pid=123,
                process_alive=lambda pid: True,
            )
            rejected = release_source_run_lock(root, "retry-planned", "2026-08-12T00:05:00+00:00", pid=124, owner_id="wrong-owner")
            loaded = read_source_run_lock(root)

        self.assertEqual(rejected["status"], "ownership_mismatch")
        self.assertEqual(loaded["status"], "running")
        self.assertEqual(loaded["owner_id"], acquired["owner_id"])

    def test_stale_guard_file_can_be_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard = root / "source_run_lock.acquire"
            root.mkdir(parents=True, exist_ok=True)
            guard.write_text('{"pid": 999}', encoding="utf-8")
            old = time.time() - 3600
            os.utime(guard, (old, old))
            acquired = acquire_source_run_lock(root, "retry-planned", "2026-08-12T00:00:00+00:00", pid=123)

        self.assertEqual(acquired["status"], "acquired")

    def test_active_guard_returns_bounded_busy_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(parents=True, exist_ok=True)
            guard = root / "source_run_lock.acquire"
            guard.write_text('{"pid": 999}', encoding="utf-8")
            started = time.monotonic()
            result = acquire_source_run_lock(root, "retry-planned", "2026-08-12T00:00:00+00:00", pid=123)
            elapsed = time.monotonic() - started

            self.assertEqual(result["status"], "busy")
            self.assertLess(elapsed, 1.0)

    def test_stale_live_guard_is_not_reclaimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard = root / "source_run_lock.acquire"
            guard.write_text(json.dumps({"pid": 999, "owner_id": "live-owner"}), encoding="utf-8")
            old = time.time() - 3600
            os.utime(guard, (old, old))
            result = acquire_source_run_lock(root, "retry-planned", "2026-08-12T00:00:00+00:00", pid=123, process_alive=lambda pid: True)

        self.assertEqual(result["status"], "busy")
        self.assertEqual(result["reason"], "active_guard")

    def test_stale_dead_owner_guard_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard = root / "source_run_lock.acquire"
            guard.write_text(json.dumps({"pid": 999, "owner_id": "dead-owner"}), encoding="utf-8")
            old = time.time() - 3600
            os.utime(guard, (old, old))
            result = acquire_source_run_lock(root, "retry-planned", "2026-08-12T00:00:00+00:00", pid=123, process_alive=lambda pid: False)

        self.assertEqual(result["status"], "acquired")

    def test_release_does_not_remove_another_guard_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guard_path = root / "source_run_lock.acquire"
            first_descriptor, first_owner = _acquire_guard(guard_path)
            guard_path.write_text(json.dumps({"pid": 124, "owner_id": "new-owner"}), encoding="utf-8")
            _release_guard(guard_path, first_descriptor, first_owner)
            current = json.loads(guard_path.read_text(encoding="utf-8"))

        self.assertEqual(current["owner_id"], "new-owner")


if __name__ == "__main__":
    unittest.main()
