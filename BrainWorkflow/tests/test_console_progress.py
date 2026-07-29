import json
import os
import tempfile
import unittest
from pathlib import Path

from wqb.console_progress import (
    count_jsonl_rows,
    file_snapshot,
    latest_data_capture_dir,
    process_is_alive,
    probe_data_capture_progress,
)


class ConsoleProgressTests(unittest.TestCase):
    def test_count_jsonl_rows_skips_blank_lines_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "rows.jsonl"
            path.write_text('{"a":1}\n\n{"b":2}\n', encoding="utf-8")

            count = count_jsonl_rows(path)
            missing = count_jsonl_rows(root / "missing.jsonl")

        self.assertEqual(count, 2)
        self.assertEqual(missing, 0)

    def test_file_snapshot_reports_size_and_write_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data_fields.jsonl"
            path.write_text('{"field":"x"}\n', encoding="utf-8")

            snapshot = file_snapshot(path)
            missing = file_snapshot(root / "missing.jsonl")

        self.assertEqual(snapshot["exists"], True)
        self.assertGreater(snapshot["bytes"], 0)
        self.assertIn("last_write_at", snapshot)
        self.assertEqual(missing["exists"], False)
        self.assertEqual(missing["bytes"], 0)

    def test_process_is_alive_rejects_invalid_pid_and_accepts_current_process(self):
        self.assertFalse(process_is_alive(-1))
        self.assertFalse(process_is_alive("not-a-pid"))
        self.assertTrue(process_is_alive(os.getpid()))


class ConsoleCaptureProgressTests(unittest.TestCase):
    def test_probe_data_capture_progress_counts_raw_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge = Path(tmp) / "knowledge"
            capture = knowledge / "raw" / "platform" / "data_fields" / "2026-07-30"
            capture.mkdir(parents=True)
            (capture / "scopes.jsonl").write_text('{"scope":"usa"}\n', encoding="utf-8")
            (capture / "data_sets.jsonl").write_text('{"id":"ds1"}\n{"id":"ds2"}\n', encoding="utf-8")
            (capture / "data_fields.jsonl").write_text(
                '{"id":"f1"}\n{"id":"f2"}\n{"id":"f3"}\n', encoding="utf-8"
            )
            (capture / "errors.jsonl").write_text('{"error":"rate"}\n', encoding="utf-8")
            (capture / "manifest.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")

            latest = latest_data_capture_dir(knowledge)
            progress = probe_data_capture_progress(knowledge)

        self.assertEqual(latest, capture)
        self.assertEqual(progress["capture_dir"], str(capture))
        self.assertEqual(progress["scope_rows"], 1)
        self.assertEqual(progress["data_set_rows"], 2)
        self.assertEqual(progress["data_field_rows"], 3)
        self.assertEqual(progress["error_rows"], 1)
        self.assertGreater(progress["data_fields_bytes"], 0)
        self.assertEqual(progress["manifest_status"], "completed")
