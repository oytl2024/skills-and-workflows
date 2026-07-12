import tempfile
import unittest
from pathlib import Path

from wqb.research_record import (
    empty_research_record,
    load_research_record,
    record_alpha_result,
    record_candidate_gate,
    record_repair_version,
    render_research_record_markdown,
    sync_research_record_to_raw,
    write_research_record,
)


class ResearchRecordTests(unittest.TestCase):
    def test_failed_alpha_summary_is_compact(self):
        record = empty_research_record("run1", "Power Pool")
        record = record_alpha_result(
            record,
            {
                "alpha_id": "a1",
                "expression_hash": "h1",
                "hard_pass": False,
                "benchmark_label": "weak_discard",
                "metrics": {"sharpe": 0.2},
                "failed": ["LOW_SHARPE"],
            },
        )

        self.assertEqual(record.failures[0]["alpha_id"], "a1")
        self.assertNotIn("expression", record.failures[0])

    def test_repair_version_history_is_idempotent_by_candidate_version_hash(self):
        record = empty_research_record("run1", "Power Pool")
        payload = {"sharpe": 1.3, "failed": []}
        record = record_repair_version(record, "c1", 1, "h1", "reduce turnover", payload)
        record = record_repair_version(record, "c1", 1, "h1", "reduce turnover", payload)

        self.assertEqual(len(record.repairs["c1"]), 1)

    def test_candidate_gate_and_markdown_rendering(self):
        record = empty_research_record("run1", "Power Pool")
        record = record_candidate_gate(record, {"candidate_id": "c1", "platform_alpha_id": "a1", "expression_hash": "h1"}, "ready_for_approval", ["hard checks passed"])
        markdown = render_research_record_markdown(record)

        self.assertIn("# Research Record", markdown)
        self.assertIn("ready_for_approval", markdown)

    def test_write_load_and_sync_to_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = empty_research_record("run1", "Power Pool")
            path = write_research_record(root / "research_record.json", record)
            loaded = load_research_record(path)
            raw_path = sync_research_record_to_raw(loaded, root / "raw")

        self.assertEqual(loaded.run_id, "run1")
        self.assertTrue(raw_path.name == "research_record.md")
