import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from wqb.knowledge_freshness import (
    KnowledgeFreshnessRecord,
    evaluate_freshness,
    load_freshness_manifest,
    write_freshness_report,
)


class KnowledgeFreshnessTest(unittest.TestCase):
    def test_load_freshness_manifest(self):
        row = {
            "name": "data_ledger",
            "path": "knowledge/wiki/20_semantics/data_ledger.jsonl",
            "updated_at": "2026-07-08",
            "max_age_days": 1,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "freshness.json"
            path.write_text(json.dumps([row], sort_keys=True), encoding="utf-8")

            records = load_freshness_manifest(path)

        self.assertEqual(records[0].name, "data_ledger")
        self.assertEqual(records[0].max_age_days, 1)

    def test_evaluate_freshness_marks_stale_records(self):
        records = [
            KnowledgeFreshnessRecord("data_ledger", "knowledge/wiki/20_semantics/data_ledger.jsonl", "2026-07-08", 1),
            KnowledgeFreshnessRecord("template_library", "knowledge/wiki/30_templates/template_library.jsonl", "2026-07-10", 7),
        ]

        statuses = evaluate_freshness(records, today=date(2026, 7, 10))

        by_name = {status.name: status for status in statuses}
        self.assertTrue(by_name["data_ledger"].stale)
        self.assertFalse(by_name["template_library"].stale)
        self.assertEqual(by_name["data_ledger"].age_days, 2)

    def test_write_freshness_report(self):
        statuses = evaluate_freshness(
            [KnowledgeFreshnessRecord("benchmarks", "knowledge/wiki/50_benchmarks", "2026-07-06", 3)],
            today=date(2026, 7, 10),
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = write_freshness_report(Path(tmp) / "freshness_report.md", statuses, "2026-07-10T00:00:00Z")
            text = output.read_text(encoding="utf-8")

        self.assertIn("benchmarks", text)
        self.assertIn("stale", text)


if __name__ == "__main__":
    unittest.main()
