import tempfile
import unittest
import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from wqb.research_record import (
    empty_research_record,
    load_research_record_ledger,
    load_research_record,
    record_alpha_result,
    record_candidate_gate,
    record_repair_version,
    render_research_record_markdown,
    sync_research_record_to_machine,
    sync_research_record_to_raw,
    write_research_record,
)


class ResearchRecordTests(unittest.TestCase):
    def test_sync_research_record_to_machine_appends_latest_run_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = empty_research_record("run-a", "Power Pool breadth-first scout")
            record = record_alpha_result(record, {
                "alpha_id": "alpha-a",
                "expression_hash": "hash-a",
                "hard_pass": False,
                "benchmark_label": "near_miss",
                "metrics": {"sharpe": 1.3},
                "failed": ["prod_correlation"],
            })

            path = sync_research_record_to_machine(record, tmp, "2026-07-30T00:00:00+00:00")
            rows = load_research_record_ledger(tmp)

        self.assertEqual(path, Path(tmp) / "machine" / "research_records.jsonl")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], "run-a")
        self.assertEqual(rows[0]["final_state"], "in_progress")

    def test_json_roundtrip_and_markdown_include_all_contract_sections(self):
        from wqb.research_record import ResearchRecord
        from wqb.workflow_contract import RESEARCH_RECORD_SECTIONS

        sections = {
            "backtest": [{"alpha_id": "a1"}],
            "triage": [{"alpha_id": "a1", "decision": "hard_pass"}],
            "repair": {"c1": [{"version": 1}]},
            "candidate_gate": [{"candidate_id": "c1"}],
            "user_approval": [{"candidate_id": "c1"}],
            "approved_queue": [{"candidate_id": "c1", "status": "queued"}],
            "manual_submission_status": [{"candidate_id": "c1", "status": "manually_submitted"}],
        }
        record = ResearchRecord(run_id="run1", objective="Power Pool", **sections)

        with tempfile.TemporaryDirectory() as tmp:
            path = write_research_record(Path(tmp) / "research_record.json", record)
            loaded = load_research_record(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
        markdown = render_research_record_markdown(loaded)

        self.assertEqual(asdict(loaded), asdict(record))
        self.assertTrue(set(RESEARCH_RECORD_SECTIONS).issubset(payload))
        for heading in (
            "## Backtest", "## Triage", "## Repair", "## Candidate Gate",
            "## User Approval", "## Approved Queue", "## Manual Submission Status",
        ):
            self.assertIn(heading, markdown)

    def test_load_old_record_uses_backward_compatible_section_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "research_record.json"
            path.write_text(json.dumps({"run_id": "run1", "objective": "old", "failures": []}), encoding="utf-8")
            loaded = load_research_record(path)

        self.assertEqual(loaded.backtest, [])
        self.assertEqual(loaded.manual_submission_status, [])
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

    def test_candidate_gate_is_idempotent_by_full_identity_and_decision(self):
        record = empty_research_record("run1", "Power Pool")
        candidate = {
            "candidate_id": "c1",
            "platform_alpha_id": "a1",
            "version": 1,
            "expression_hash": "h1",
            "source_run_id": "run1",
        }

        record = record_candidate_gate(
            record, candidate, "ready_for_approval", ["first reason"]
        )
        record = record_candidate_gate(
            record, candidate, "ready_for_approval", ["retry reason"]
        )

        self.assertEqual(len(record.candidate_gate), 1)
        self.assertEqual(record.candidate_gate[0]["reasons"], ["first reason"])

    def test_write_load_and_sync_to_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = empty_research_record("run1", "Power Pool")
            path = write_research_record(root / "research_record.json", record)
            loaded = load_research_record(path)
            raw_path = sync_research_record_to_raw(loaded, root / "raw")

        self.assertEqual(loaded.run_id, "run1")
        self.assertTrue(raw_path.name == "research_record.md")

    def test_interrupted_research_record_replace_preserves_previous_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "research_record.json"
            write_research_record(path, empty_research_record("run1", "old objective"))

            with patch.object(Path, "replace", side_effect=OSError("interrupted replace")):
                with self.assertRaisesRegex(OSError, "interrupted replace"):
                    write_research_record(path, empty_research_record("run1", "new objective"))

            loaded = load_research_record(path)

        self.assertEqual(loaded.objective, "old objective")

    def test_research_record_tracks_approvals_and_queue_updates(self):
        from wqb.research_record import (
            record_approval,
            record_manual_submission_status,
            record_queue_update,
        )

        record = empty_research_record("run1", "Power Pool")
        approval = {
            "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
            "expression_hash": "h1", "source_run_id": "run1", "approved_at": "t", "approved_by": "user",
        }
        queue_row = dict(approval, status="queued")
        manual_row = dict(approval, status="manually_submitted")
        record = record_approval(record, approval)
        record = record_approval(record, approval)
        record = record_queue_update(record, queue_row)
        record = record_queue_update(record, queue_row)
        record = record_manual_submission_status(record, manual_row)
        record = record_manual_submission_status(record, manual_row)

        self.assertEqual(record.approvals[0]["candidate_id"], "c1")
        self.assertEqual(record.queue_updates[0]["status"], "queued")
        self.assertEqual(len(record.user_approval), 1)
        self.assertEqual(len(record.approved_queue), 1)
        self.assertEqual(len(record.manual_submission_status), 1)

    def test_status_history_dedupes_only_immediate_retries(self):
        from wqb.research_record import record_manual_submission_status, record_queue_update

        record = empty_research_record("run1", "Power Pool")
        base = {
            "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
            "expression_hash": "h1", "source_run_id": "run1",
        }
        for status in ("queued", "manually_submitted", "queued"):
            row = dict(base, status=status)
            record = record_queue_update(record, row)
            record = record_manual_submission_status(record, row)

        self.assertEqual(
            [row["status"] for row in record.approved_queue],
            ["queued", "manually_submitted", "queued"],
        )
        self.assertEqual(
            [row["status"] for row in record.manual_submission_status],
            ["queued", "manually_submitted", "queued"],
        )
