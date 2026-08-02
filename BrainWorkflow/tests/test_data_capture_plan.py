import tempfile
import unittest
from pathlib import Path

from wqb.data_capture_plan import (
    build_stratified_capture_plan,
    discover_scope_matrix,
    load_capture_plan,
    write_capture_plan,
)


class FakeClient:
    def get_json(self, path):
        if path.startswith("/data-sets?"):
            return {
                "count": 2,
                "results": [
                    {"id": "ds_a", "category": "analyst"},
                    {"id": "ds_b", "category": "news"},
                ],
            }
        raise AssertionError(path)


class DataCapturePlanTests(unittest.TestCase):
    def test_discover_scope_matrix_writes_machine_scope_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = discover_scope_matrix(
                FakeClient(),
                tmp,
                generated_at="2026-07-30T00:00:00+00:00",
                regions=["USA", "EUR"],
                delays=[0, 1],
                universes=["TOP3000"],
            )

            self.assertEqual(summary["scope_count"], 4)
            self.assertEqual(summary["available_scope_count"], 4)
            self.assertTrue((Path(tmp) / "machine" / "scope_matrix.jsonl").exists())

    def test_stratified_plan_balances_scopes_and_caps_fields_per_scope(self):
        rows = [
            {
                "instrument_type": "EQUITY",
                "region": "USA",
                "delay": 1,
                "universe": "TOP3000",
                "status": "available",
                "dataset_count": 10,
            },
            {
                "instrument_type": "EQUITY",
                "region": "EUR",
                "delay": 1,
                "universe": "TOP1200",
                "status": "available",
                "dataset_count": 8,
            },
            {
                "instrument_type": "EQUITY",
                "region": "ASI",
                "delay": 1,
                "universe": "MINVOL1M",
                "status": "failed",
                "dataset_count": 0,
            },
        ]

        plan = build_stratified_capture_plan(rows, fields_per_scope=50, max_scopes=2)

        self.assertEqual(len(plan), 2)
        self.assertEqual({row["field_budget"] for row in plan}, {50})
        self.assertEqual({row["status"] for row in plan}, {"planned"})

    def test_write_and_load_capture_plan_round_trips_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                {
                    "instrument_type": "EQUITY",
                    "region": "USA",
                    "delay": 1,
                    "universe": "TOP3000",
                    "field_budget": 50,
                    "status": "planned",
                }
            ]

            path = write_capture_plan(tmp, rows, "2026-07-30T00:00:00+00:00")

            self.assertTrue(path.as_posix().endswith("raw/platform/data_fields/capture_plans/2026-07-30.jsonl"))
            self.assertEqual(load_capture_plan(path), rows)


if __name__ == "__main__":
    unittest.main()
