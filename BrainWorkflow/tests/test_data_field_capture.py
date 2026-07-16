import json
import tempfile
import unittest
from pathlib import Path

from wqb.data_field_capture import build_capture_scopes, capture_platform_data_fields
from wqb.data_ledger_compile import compile_data_ledger_from_raw


class FakeCaptureClient:
    def __init__(self):
        self.paths = []

    def get_json(self, path):
        self.paths.append(path)
        if path == "/operators":
            return {"results": [{"name": "rank"}, {"name": "ts_delta"}]}
        if path.startswith("/data-sets?"):
            if "region=EUR" in path:
                raise RuntimeError("scope rejected")
            return {
                "results": [
                    {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                    {"id": "news7", "name": "News", "category": "news"},
                ]
            }
        if path.startswith("/data-fields?") and "dataset.id=fundamental3" in path:
            return {
                "results": [
                    {
                        "id": "fnd3_q_cash_fast_d1",
                        "type": "MATRIX",
                        "coverage": 0.84,
                        "alphaCount": 1,
                        "userCount": 1,
                        "dataset": {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                        "description": "Quarterly cash",
                    }
                ]
            }
        if path.startswith("/data-fields?") and "dataset.id=news7" in path:
            return {"results": []}
        return {"results": []}


class FailingFieldCaptureClient(FakeCaptureClient):
    def get_json(self, path):
        if path.startswith("/data-fields?") and "dataset.id=fundamental3" in path:
            self.paths.append(path)
            raise RuntimeError("field endpoint failed")
        return super().get_json(path)


class MissingDatasetIdCaptureClient(FakeCaptureClient):
    def get_json(self, path):
        if path.startswith("/data-sets?"):
            self.paths.append(path)
            return {
                "results": [
                    {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                    {"name": "Malformed dataset", "category": "news"},
                ]
            }
        return super().get_json(path)


class DataFieldCaptureTests(unittest.TestCase):
    def test_build_capture_scopes_expands_matrix_and_applies_limit(self):
        scopes = build_capture_scopes(
            instrument_types=["EQUITY"],
            regions=["USA", "EUR"],
            delays=[0, 1],
            universes=["TOP3000", "TOP500"],
            max_scopes=3,
        )

        self.assertEqual(len(scopes), 3)
        self.assertEqual(scopes[0].region, "USA")
        self.assertEqual(scopes[0].delay, 0)
        self.assertEqual(scopes[0].universe, "TOP3000")

    def test_capture_platform_data_fields_writes_raw_snapshot_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            summary = capture_platform_data_fields(
                FakeCaptureClient(),
                root,
                generated_at="2026-07-16T08:30:00+00:00",
                instrument_types=["EQUITY"],
                regions=["USA", "EUR"],
                delays=[1],
                universes=["TOP3000"],
                max_fields_per_dataset=10,
            )
            capture_dir = Path(summary["capture_dir"])

            self.assertTrue((capture_dir / "index.md").exists())
            self.assertTrue((capture_dir / "manifest.json").exists())
            self.assertTrue((capture_dir / "operators.json").exists())
            self.assertTrue((capture_dir / "scopes.jsonl").exists())
            self.assertTrue((capture_dir / "data_sets.jsonl").exists())
            self.assertTrue((capture_dir / "data_fields.jsonl").exists())
            self.assertTrue((capture_dir / "errors.jsonl").exists())

            fields = [json.loads(line) for line in (capture_dir / "data_fields.jsonl").read_text(encoding="utf-8").splitlines()]
            errors = [json.loads(line) for line in (capture_dir / "errors.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(summary["field_count"], 1)
        self.assertEqual(summary["error_count"], 1)
        self.assertEqual(fields[0]["field"]["id"], "fnd3_q_cash_fast_d1")
        self.assertEqual(fields[0]["scope"]["region"], "USA")
        self.assertIn("scope rejected", errors[0]["message"])

    def test_limited_capture_records_requested_matrix_and_is_not_certification_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            summary = capture_platform_data_fields(
                FakeCaptureClient(),
                root,
                generated_at="2026-07-16T08:30:00+00:00",
                instrument_types=["EQUITY"],
                regions=["USA", "EUR"],
                delays=[1],
                universes=["TOP3000"],
                max_scopes=1,
                max_datasets_per_scope=1,
                max_fields_per_dataset=1,
            )
            manifest = json.loads((Path(summary["capture_dir"]) / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["certification_status"], "partial")
        self.assertEqual(manifest["active_limits"], {"max_scopes": 1, "max_datasets_per_scope": 1, "max_fields_per_dataset": 1})
        self.assertEqual(len(manifest["requested_matrix"]), 2)
        self.assertEqual(manifest["latest_scope_outcomes"][0]["status"], "completed")

    def test_resume_capture_skips_completed_scope_without_duplicate_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            scope = {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}
            capture.mkdir(parents=True)
            (capture / "scopes.jsonl").write_text(json.dumps({"scope": scope, "status": "completed"}) + "\n", encoding="utf-8")
            (capture / "data_fields.jsonl").write_text(json.dumps({"scope": scope, "field": {"id": "cash_field"}}) + "\n", encoding="utf-8")
            client = FakeCaptureClient()

            summary = capture_platform_data_fields(
                client,
                root,
                generated_at="2026-07-16T08:30:00+00:00",
                instrument_types=["EQUITY"],
                regions=["USA"],
                delays=[1],
                universes=["TOP3000"],
                resume_capture=True,
            )

            self.assertFalse(any(path.startswith("/data-sets?") or path.startswith("/data-fields?") for path in client.paths))
            self.assertEqual(summary["scope_count"], 1)
            self.assertEqual(summary["field_count"], 1)
            self.assertEqual(len((capture / "data_fields.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_resume_capture_retries_failed_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            scope = {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}
            capture.mkdir(parents=True)
            (capture / "scopes.jsonl").write_text(json.dumps({"scope": scope, "status": "failed"}) + "\n", encoding="utf-8")
            client = FakeCaptureClient()

            capture_platform_data_fields(
                client,
                root,
                generated_at="2026-07-16T08:30:00+00:00",
                instrument_types=["EQUITY"],
                regions=["USA"],
                delays=[1],
                universes=["TOP3000"],
                resume_capture=True,
            )

            self.assertTrue(any(path.startswith("/data-sets?") for path in client.paths))

    def test_resume_capture_retries_scope_when_a_field_fetch_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            first_client = FailingFieldCaptureClient()
            first_summary = capture_platform_data_fields(
                first_client,
                root,
                generated_at="2026-07-16T08:30:00+00:00",
                instrument_types=["EQUITY"],
                regions=["USA"],
                delays=[1],
                universes=["TOP3000"],
            )
            capture = Path(first_summary["capture_dir"])
            scope_rows = [json.loads(line) for line in (capture / "scopes.jsonl").read_text(encoding="utf-8").splitlines()]
            errors = [json.loads(line) for line in (capture / "errors.jsonl").read_text(encoding="utf-8").splitlines()]
            resumed_client = FailingFieldCaptureClient()

            capture_platform_data_fields(
                resumed_client,
                root,
                generated_at="2026-07-16T08:30:00+00:00",
                instrument_types=["EQUITY"],
                regions=["USA"],
                delays=[1],
                universes=["TOP3000"],
                resume_capture=True,
            )

        self.assertEqual(scope_rows[-1]["status"], "partial")
        self.assertIn("field endpoint failed", errors[-1]["message"])
        self.assertTrue(any(path.startswith("/data-sets?") for path in resumed_client.paths))
        self.assertTrue(any(path.startswith("/data-fields?") for path in resumed_client.paths))

    def test_successful_resume_clears_resolved_error_status_and_compiles_measured_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            first_summary = capture_platform_data_fields(
                FailingFieldCaptureClient(),
                root,
                generated_at="2026-07-16T08:30:00+00:00",
                instrument_types=["EQUITY"],
                regions=["USA"],
                delays=[1],
                universes=["TOP3000"],
            )

            resumed_summary = capture_platform_data_fields(
                FakeCaptureClient(),
                root,
                generated_at="2026-07-16T08:30:00+00:00",
                instrument_types=["EQUITY"],
                regions=["USA"],
                delays=[1],
                universes=["TOP3000"],
                resume_capture=True,
            )
            capture = Path(resumed_summary["capture_dir"])
            compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            row = json.loads((root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])
            historical_error_count = len((capture / "errors.jsonl").read_text(encoding="utf-8").splitlines())

        self.assertEqual(first_summary["status"], "completed_with_warnings")
        self.assertEqual(resumed_summary["status"], "completed")
        self.assertEqual(resumed_summary["error_count"], 0)
        self.assertEqual(historical_error_count, 1)
        self.assertEqual(row["coverage_status"], "measured_raw")

    def test_dataset_without_id_marks_scope_partial_and_records_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            summary = capture_platform_data_fields(
                MissingDatasetIdCaptureClient(),
                root,
                generated_at="2026-07-16T08:30:00+00:00",
                instrument_types=["EQUITY"],
                regions=["USA"],
                delays=[1],
                universes=["TOP3000"],
            )
            capture = Path(summary["capture_dir"])
            scope_rows = [json.loads(line) for line in (capture / "scopes.jsonl").read_text(encoding="utf-8").splitlines()]
            errors = [json.loads(line) for line in (capture / "errors.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(summary["status"], "completed_with_warnings")
        self.assertEqual(scope_rows[-1]["status"], "partial")
        self.assertTrue(any("missing dataset id" in row["message"] for row in errors))


if __name__ == "__main__":
    unittest.main()
