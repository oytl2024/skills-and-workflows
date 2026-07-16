import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb.data_ledger import load_data_ledger
from wqb.data_field_capture import DATA_CAPTURE_LOCK_NAME
from wqb.data_ledger_compile import COMPILE_LOCK_NAME, compile_data_ledger_from_raw, latest_capture_dir


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

    def test_compile_data_ledger_from_raw_emits_one_record_per_exact_scope(self):
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
            write_jsonl(capture / "scopes.jsonl", [
                {"scope": rows[0]["scope"], "status": "completed", "certification_status": "complete"},
                {"scope": rows[1]["scope"], "status": "completed", "certification_status": "complete"},
            ])
            (capture / "manifest.json").write_text(json.dumps({"status": "completed", "field_count": 2, "certification_status": "complete"}), encoding="utf-8")

            summary = compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            ledger_path = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            records = load_data_ledger(ledger_path)
            raw_row = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(summary["record_count"], 2)
        self.assertEqual([record.field_id for record in records], ["fnd3_q_cash_fast_d1", "fnd3_q_cash_fast_d1"])
        self.assertEqual([record.available_scopes for record in records], [
            [{"instrument_type": "EQUITY", "region": "EUR", "delay": 0, "universe": "TOP500"}],
            [{"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}],
        ])
        self.assertIn("cash", records[0].semantic_tags)
        self.assertIn("raw/platform/data_fields/2026-07-16/data_fields.jsonl", raw_row["source_paths"][0])
        self.assertEqual(raw_row["source_quality"], "platform_raw_capture")
        self.assertEqual(raw_row["coverage_status"], "measured_raw")

    def test_compile_keeps_certified_and_partial_exact_scopes_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            certified = {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}
            partial = {"instrument_type": "EQUITY", "region": "EUR", "delay": 1, "universe": "TOP3000"}
            write_jsonl(capture / "data_fields.jsonl", [
                {"scope": certified, "data_set": {"id": "fundamental3"}, "field": {"id": "cash_field", "type": "MATRIX"}},
                {"scope": partial, "data_set": {"id": "fundamental3"}, "field": {"id": "cash_field", "type": "MATRIX"}},
            ])
            write_jsonl(capture / "scopes.jsonl", [
                {"scope": certified, "status": "completed", "certification_status": "complete"},
                {"scope": partial, "status": "partial", "certification_status": "partial"},
            ])
            (capture / "manifest.json").write_text(json.dumps({"status": "completed_with_warnings", "certification_status": "complete"}), encoding="utf-8")

            compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            rows = [json.loads(line) for line in (root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual([(row["region"], row["coverage_status"]) for row in rows], [("EUR", "partial"), ("USA", "measured_raw")])
        self.assertTrue(all(len(row["available_scopes"]) == 1 for row in rows))

    def test_compile_marks_negative_delay_scope_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            scope = {"instrument_type": "EQUITY", "region": "USA", "delay": -1, "universe": "TOP3000"}
            write_jsonl(capture / "data_fields.jsonl", [{"scope": scope, "data_set": {"id": "fundamental3"}, "field": {"id": "cash_field", "type": "MATRIX"}}])
            write_jsonl(capture / "scopes.jsonl", [{"scope": scope, "status": "completed", "certification_status": "complete"}])
            (capture / "manifest.json").write_text(json.dumps({"status": "completed", "certification_status": "complete"}), encoding="utf-8")

            compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(row["coverage_status"], "partial")

    def test_compile_marks_rows_partial_without_explicit_certified_scope_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            raw_row = {
                "scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                "data_set": {"id": "fundamental3"},
                "field": {"id": "cash_field", "type": "MATRIX"},
            }
            write_jsonl(capture / "data_fields.jsonl", [raw_row])
            (capture / "manifest.json").write_text(json.dumps({"status": "completed", "certification_status": "complete"}), encoding="utf-8")

            compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(row["coverage_status"], "partial")

    def test_compile_marks_invalid_raw_scope_partial_even_with_completed_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            raw_row = {
                "scope": {"instrument_type": "EQUITY", "region": "USA", "delay": "not-a-delay", "universe": "TOP3000"},
                "data_set": {"id": "fundamental3"},
                "field": {"id": "cash_field", "type": "MATRIX"},
            }
            write_jsonl(capture / "data_fields.jsonl", [raw_row])
            write_jsonl(capture / "scopes.jsonl", [{"scope": raw_row["scope"], "status": "completed", "certification_status": "complete"}])
            (capture / "manifest.json").write_text(json.dumps({"status": "completed", "certification_status": "complete"}), encoding="utf-8")

            compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(row["coverage_status"], "partial")

    def test_compile_rejects_non_object_jsonl_row_without_replacing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            ledger = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text('{"field_id":"last_good"}\n', encoding="utf-8")
            write_jsonl(capture / "data_fields.jsonl", [{
                "scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                "data_set": {"id": "fundamental3"},
                "field": {"id": "cash_field", "type": "MATRIX"},
            }])
            with (capture / "data_fields.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("null\n")

            with self.assertRaisesRegex(ValueError, "line 2"):
                compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            persisted = ledger.read_text(encoding="utf-8")

        self.assertEqual(persisted, '{"field_id":"last_good"}\n')

    def test_compile_marks_warning_capture_rows_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            write_jsonl(
                capture / "data_fields.jsonl",
                [{
                    "scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                    "data_set": {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                    "field": {"id": "cash_field", "type": "MATRIX", "description": "Quarterly cash"},
                }],
            )
            (capture / "manifest.json").write_text(json.dumps({"status": "completed_with_warnings"}), encoding="utf-8")

            summary = compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(summary["source_status"], "partial")
        self.assertEqual(row["coverage_status"], "partial")

    def test_compile_marks_limited_capture_rows_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            write_jsonl(capture / "data_fields.jsonl", [{"scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}, "data_set": {"id": "fundamental3"}, "field": {"id": "cash_field", "type": "MATRIX"}}])
            (capture / "manifest.json").write_text(json.dumps({"status": "completed", "active_limits": {"max_scopes": 0, "max_datasets_per_scope": 1, "max_fields_per_dataset": 0}, "certification_status": "partial"}), encoding="utf-8")

            compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(row["coverage_status"], "partial")

    def test_compile_preserves_field_description_and_existing_usage_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            ledger = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            write_jsonl(capture / "data_fields.jsonl", [{"scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}, "data_set": {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"}, "field": {"id": "cash_field", "type": "MATRIX", "description": "Quarterly cash"}}])
            write_jsonl(ledger, [{"dataset_id": "fundamental3", "field_id": "cash_field", "simulation_usage_count": 4, "submitted_usage_count": 2, "repair_usage_count": 1, "last_used_at": "2026-07-15", "best_result_label": "repairable_signal", "experiment_paths": ["wiki/40_experiments/run.md"], "activity_tags": ["power_pool"]}])

            compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            record = load_data_ledger(ledger)[0]

        self.assertEqual(record.field_description, "Quarterly cash")
        self.assertEqual(record.simulation_usage_count, 4)
        self.assertEqual(record.submitted_usage_count, 2)
        self.assertEqual(record.repair_usage_count, 1)
        self.assertEqual(record.last_used_at, "2026-07-15")
        self.assertEqual(record.best_result_label, "repairable_signal")
        self.assertEqual(record.experiment_paths, ["wiki/40_experiments/run.md"])
        self.assertEqual(record.activity_tags, ["power_pool"])

    def test_publish_failure_restores_all_existing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            write_jsonl(capture / "data_fields.jsonl", [{"scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}, "data_set": {"id": "fundamental3"}, "field": {"id": "cash_field", "type": "MATRIX"}}])
            ledger = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            markdown = root / "wiki" / "20_semantics" / "data_ledger.md"
            manifest = root / "wiki" / "80_maintenance" / "freshness_manifest.json"
            for path, content in ((ledger, '{"dataset_id": "old", "field_id": "old"}\n'), (markdown, "old markdown\n"), (manifest, "[{\"name\": \"old\"}]")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            original_replace = Path.replace

            def fail_ledger_replace(source, destination):
                if Path(destination) == ledger:
                    raise OSError("ledger publish failed")
                return original_replace(source, destination)

            with patch.object(Path, "replace", new=fail_ledger_replace):
                with self.assertRaisesRegex(OSError, "ledger publish failed"):
                    compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")

            self.assertEqual(ledger.read_text(encoding="utf-8"), '{"dataset_id": "old", "field_id": "old"}\n')
            self.assertEqual(markdown.read_text(encoding="utf-8"), "old markdown\n")
            self.assertEqual(manifest.read_text(encoding="utf-8"), "[{\"name\": \"old\"}]")

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

    def test_compile_keeps_completed_scope_measured_when_another_scope_failed_without_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            write_jsonl(capture / "data_fields.jsonl", [{"scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}, "data_set": {"id": "fundamental3"}, "field": {"id": "cash_field", "type": "MATRIX"}}])
            write_jsonl(capture / "scopes.jsonl", [
                {"scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}, "status": "completed", "certification_status": "complete"},
                {"scope": {"instrument_type": "EQUITY", "region": "EUR", "delay": 1, "universe": "TOP3000"}, "status": "failed"},
            ])
            (capture / "manifest.json").write_text(json.dumps({"status": "completed_with_warnings", "generated_at": "2026-07-16T08:00:00+00:00", "certification_status": "complete"}), encoding="utf-8")

            compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(row["coverage_status"], "measured_raw")

    def test_compile_uses_capture_source_day_for_freshness_not_compile_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2025-01-02"
            write_jsonl(capture / "data_fields.jsonl", [{"scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}, "data_set": {"id": "fundamental3"}, "field": {"id": "cash_field", "type": "MATRIX"}}])
            (capture / "manifest.json").write_text(json.dumps({"status": "completed", "generated_at": "2025-01-02T08:00:00+00:00"}), encoding="utf-8")

            compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            freshness = json.loads((root / "wiki" / "80_maintenance" / "freshness_manifest.json").read_text(encoding="utf-8"))

        entry = next(row for row in freshness if row["name"] == "data_ledger")
        self.assertEqual(entry["updated_at"], "2025-01-02")
        self.assertEqual(entry["compiled_at"], "2026-07-16T09:00:00+00:00")

    def test_compile_rejects_malformed_or_empty_raw_data_without_replacing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            ledger = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            markdown = root / "wiki" / "20_semantics" / "data_ledger.md"
            manifest = root / "wiki" / "80_maintenance" / "freshness_manifest.json"
            for path, content in ((ledger, '{"field_id": "last_good"}\n'), (markdown, "last good markdown\n"), (manifest, "[{\"name\": \"last_good\"}]")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            cases = [
                {"scope": {}, "data_set": {"id": "fundamental3"}, "field": {"type": "MATRIX"}},
                {"scope": {}, "data_set": {}, "field": {"id": "cash_field", "type": "MATRIX"}},
                None,
            ]
            for raw_row in cases:
                if raw_row is None:
                    write_jsonl(capture / "data_fields.jsonl", [])
                else:
                    write_jsonl(capture / "data_fields.jsonl", [raw_row])
                with self.assertRaisesRegex(ValueError, "raw data fields"):
                    compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
                self.assertEqual(ledger.read_text(encoding="utf-8"), '{"field_id": "last_good"}\n')
                self.assertEqual(markdown.read_text(encoding="utf-8"), "last good markdown\n")
                self.assertEqual(manifest.read_text(encoding="utf-8"), "[{\"name\": \"last_good\"}]")

    def test_compile_refuses_busy_knowledge_root_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            write_jsonl(capture / "data_fields.jsonl", [{"scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}, "data_set": {"id": "fundamental3"}, "field": {"id": "cash_field", "type": "MATRIX"}}])
            with patch("wqb.data_ledger_compile.exclusive_json_lock", side_effect=ValueError("compile lock is busy")) as lock:
                with self.assertRaisesRegex(ValueError, "compile lock is busy"):
                    compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")

        lock.assert_called_once()

    def test_capture_and_compile_share_the_same_knowledge_root_lock_name(self):
        self.assertEqual(COMPILE_LOCK_NAME, DATA_CAPTURE_LOCK_NAME)


if __name__ == "__main__":
    unittest.main()
