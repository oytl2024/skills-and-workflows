from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb.delivery_gate import run_delivery_gate
from wqb.run_readiness import ReadinessIssue, ReadinessReport
from wqb.workflow_state import create_initial_state, write_run_state


class DeliveryGateTests(unittest.TestCase):
    def _write_minimal_clean_knowledge(self, root: Path) -> None:
        for name in ("raw", "machine", "wiki"):
            (root / name).mkdir(parents=True, exist_ok=True)
        for name in (
            "scope_matrix.jsonl",
            "data_ledger.jsonl",
            "operator_ledger.jsonl",
            "template_library.jsonl",
            "benchmark_rules.jsonl",
            "research_records.jsonl",
            "source_index.jsonl",
        ):
            (root / "machine" / name).write_text("{}\n", encoding="utf-8")
        (root / "machine" / "freshness_manifest.json").write_text("[]", encoding="utf-8")
        for page in (
            "00_start_here.md",
            "10_factor_principles.md",
            "20_data_semantics.md",
            "30_template_and_operator_patterns.md",
            "40_benchmark_and_repair_rules.md",
            "50_engineering_lessons.md",
        ):
            (root / "wiki" / page).write_text(
                "---\ncompiled_from:\n  - raw/platform/learn/doc.md\n"
                "compiled_at: 2026-07-30T00:00:00+00:00\n"
                "trust_level: compiled_experience\nstale_after_days: 14\n"
                "update_trigger: compile-knowledge\nconsumed_by:\n  - human_learning\n"
                "---\n# Page\n",
                encoding="utf-8",
            )

    def _passing_readiness(self) -> ReadinessReport:
        """Input: none. Output: ReadinessReport. Build a non-live readiness pass for delivery tests."""
        return ReadinessReport("plan-only", "2026-07-30T00:00:00+00:00", True, False, [])

    def _write_run_state(
        self,
        runs: Path,
        run_id: str,
        status: str,
        current_stage: str,
        updated_at: str,
        pause_reason: str = "",
        waiting_for_user: bool = False,
    ) -> Path:
        """Input: workflow state fields. Output: run directory. Write one durable real-schema workflow state."""
        run_dir = runs / run_id
        run_dir.mkdir(parents=True)
        state = create_initial_state(run_id, run_dir, "Delivery test", "2026-07-30T00:00:00+00:00")
        write_run_state(
            run_dir / "run_state.json",
            replace(
                state,
                status=status,
                current_stage=current_stage,
                pause_reason=pause_reason,
                waiting_for_user=waiting_for_user,
                updated_at=updated_at,
            ),
        )
        return run_dir

    def test_delivery_gate_accepts_expected_durable_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "passed")
            self.assertIn("expected_pause", {check["code"] for check in report["checks"]})

    def test_delivery_gate_accepts_waiting_for_user_approval_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_run_state(
                runs,
                "20260730T000000-approval",
                "waiting_for_user",
                "user_approval",
                "2026-07-30T00:00:00+00:00",
                waiting_for_user=True,
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "passed")
            self.assertEqual(
                "passed",
                next(check["status"] for check in report["checks"] if check["code"] == "expected_pause"),
            )

    def test_delivery_gate_fails_for_plan_only_readiness_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )
            readiness = ReadinessReport(
                "plan-only",
                "2026-07-30T00:00:00+00:00",
                True,
                False,
                [ReadinessIssue("warn", "stale_artifact", "Required artifact is stale.")],
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=readiness):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "failed")
            self.assertEqual(
                "failed",
                next(check["status"] for check in report["checks"] if check["code"] == "run_readiness"),
            )

    def test_delivery_gate_uses_latest_valid_state_updated_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_run_state(
                runs,
                "20260731T000000-failed",
                "failed",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
            )
            self._write_run_state(
                runs,
                "20260730T000000-resumed",
                "waiting_for_user",
                "user_approval",
                "2026-07-31T00:00:00+00:00",
                waiting_for_user=True,
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "passed")

    def test_delivery_gate_fails_when_machine_ledger_is_inside_wiki(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            (knowledge / "wiki" / "20_semantics").mkdir(parents=True)
            (knowledge / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text("{}\n", encoding="utf-8")

            report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "failed")
            self.assertIn(
                "clean_knowledge_structure",
                {check["code"] for check in report["checks"] if check["status"] == "failed"},
            )


if __name__ == "__main__":
    unittest.main()
