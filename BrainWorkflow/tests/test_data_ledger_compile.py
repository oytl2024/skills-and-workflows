import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb.data_ledger import load_data_ledger
from wqb.data_ledger_compile import compile_data_ledger_from_raw, latest_capture_dir


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


class DataLedgerCompileTests(unittest.TestCase):
    def test_latest_capture_dir_selects_newest_data_field_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            old = root / "raw" / "platform" / "data_fields" / "2026-07-15"
            new = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            old.mkdir(parents=True)
            new.mkdir(parents=True)

            self.assertEqual(latest_capture_dir(root), new)

    def test_compile_data_ledger_from_raw_aggregates_scope_and_source_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            rows = [
                {
                    "generated_at": "2026-07-16T08:00:00+00:00",
                    "scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                    "data_set": {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                    "field": {"id": "fnd3_q_cash_fast_d1", "type": "MATRIX", "coverage": 0.84, "alphaCount": 1, "userCount": 1, "description": "Quarterly cash"},
                },
                {
                    "generated_at": "2026-07-16T08:00:00+00:00",
                    "scope": {"instrument_type": "EQUITY", "region": "EUR", "delay": 0, "universe": "TOP500"},
                    "data_set": {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                    "field": {"id": "fnd3_q_cash_fast_d1", "type": "MATRIX", "coverage": 0.72, "alphaCount": 3, "userCount": 2, "description": "Quarterly cash"},
                },
            ]
            write_jsonl(capture / "data_fields.jsonl", rows)
            (capture / "manifest.json").write_text(json.dumps({"status": "completed", "field_count": 2}), encoding="utf-8")

            summary = compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            ledger_path = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            records = load_data_ledger(ledger_path)
            raw_row = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(summary["record_count"], 1)
        self.assertEqual(records[0].field_id, "fnd3_q_cash_fast_d1")
        self.assertEqual(records[0].available_regions, ["EUR", "USA"])
        self.assertEqual(records[0].available_delays, [0, 1])
        self.assertEqual(records[0].available_universes, ["TOP3000", "TOP500"])
        self.assertIn("cash", records[0].semantic_tags)
        self.assertIn("raw/platform/data_fields/2026-07-16/data_fields.jsonl", raw_row["source_paths"][0])
        self.assertEqual(raw_row["source_quality"], "platform_raw_capture")
        self.assertEqual(raw_row["coverage_status"], "measured_raw")

    def test_compile_failure_keeps_existing_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            capture.mkdir(parents=True)
            ledger = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text('{"field_id": "last_good"}\n', encoding="utf-8")
            write_jsonl(
                capture / "data_fields.jsonl",
                [
                    {
                        "scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                        "data_set": {"id": "bad"},
                        "field": {"id": "bad_field", "type": "MATRIX"},
                    }
                ],
            )

            with patch("wqb.data_ledger_compile.load_data_ledger", side_effect=ValueError("validation failed")):
                with self.assertRaisesRegex(ValueError, "validation failed"):
                    compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")

            self.assertIn("last_good", ledger.read_text(encoding="utf-8"))

    def test_markdown_failure_keeps_existing_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            ledger = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            capture.mkdir(parents=True)
            ledger.write_text('{"field_id": "last_good"}\n', encoding="utf-8")
            write_jsonl(
                capture / "data_fields.jsonl",
                [{
                    "scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                    "data_set": {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                    "field": {"id": "cash_field", "type": "MATRIX", "description": "Quarterly cash"},
                }],
            )

            with patch("wqb.data_ledger_compile.write_data_ledger_markdown", side_effect=OSError("markdown failed")):
                with self.assertRaisesRegex(OSError, "markdown failed"):
                    compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")

            self.assertEqual(ledger.read_text(encoding="utf-8"), '{"field_id": "last_good"}\n')

    def test_manifest_failure_keeps_existing_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            ledger = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            capture.mkdir(parents=True)
            ledger.write_text('{"field_id": "last_good"}\n', encoding="utf-8")
            write_jsonl(
                capture / "data_fields.jsonl",
                [{
                    "scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                    "data_set": {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                    "field": {"id": "cash_field", "type": "MATRIX", "description": "Quarterly cash"},
                }],
            )

            with patch("wqb.data_ledger_compile._update_manifest", side_effect=OSError("manifest failed")):
                with self.assertRaisesRegex(OSError, "manifest failed"):
                    compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")

            self.assertEqual(ledger.read_text(encoding="utf-8"), '{"field_id": "last_good"}\n')


if __name__ == "__main__":
    unittest.main()
