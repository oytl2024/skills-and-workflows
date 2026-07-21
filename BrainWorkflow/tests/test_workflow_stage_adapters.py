import json
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_stage_adapters import schedule_research_stage, summarize_stage_artifacts


def valid_option(**overrides):
    """Input: optional overrides dict. Output: option-card dict. Build a strict scheduler fixture."""
    row = {
        "title": "Power Pool",
        "primary_incentive": "power_pool",
        "secondary_incentives": [],
        "why_now": "Fresh measured coverage is available.",
        "candidate_scope": "USA D1 TOP3000",
        "expected_asset_value": "A measured research direction.",
        "correlation_risk": "low",
        "resource_cost": "small",
        "evidence": [{"source_type": "ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "title": "Ledger", "timestamp": "2026-07-16"}],
        "failure_modes": [],
        "decision_needed": "Start the selected scope.",
        "score": {"total": 1.0, "components": {}, "penalties": {}, "reasons": ["measured coverage"]},
    }
    return {**row, **overrides}


class WorkflowStageAdaptersTests(unittest.TestCase):
    def test_schedule_research_stage_writes_stage_artifact_from_option_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            decisions = knowledge / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps(valid_option(option_id="option-1", score={"total": 10.0, "components": {}, "penalties": {}, "reasons": ["measured coverage"]})) + "\n",
                encoding="utf-8",
            )
            run_dir = root / "runs" / "run1"
            summary = schedule_research_stage(knowledge, run_dir, "option-1")
            artifact = json.loads(
                (run_dir / "stages" / "schedule" / "research_schedule.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["stage"], "schedule")
            self.assertTrue((run_dir / "stages" / "schedule" / "research_schedule.json").exists())
            self.assertTrue((run_dir / "stages" / "schedule" / "research_schedule.md").exists())
            self.assertEqual(artifact["selected_option"]["option_id"], "option-1")
            self.assertEqual(artifact["option_title"], "Power Pool")

    def test_schedule_research_stage_rejects_unknown_option_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps(valid_option(option_id="option-1")) + "\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "selected research option not found"):
                schedule_research_stage(root / "knowledge", root / "runs" / "run1", "unknown")

    def test_schedule_research_stage_uses_stable_positional_id_for_planner_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps(valid_option(title="First")) + "\n"
                + json.dumps(valid_option(title="Second")) + "\n",
                encoding="utf-8",
            )

            summary = schedule_research_stage(root / "knowledge", root / "runs" / "run1", "option-2")

        self.assertEqual(summary["option_title"], "Second")
        self.assertEqual(summary["selected_option"]["option_id"], "option-2")

    def test_schedule_research_stage_skips_invalid_rows_before_assigning_fallback_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                "{}\n" + json.dumps(valid_option(title="Valid recovered option")) + "\n",
                encoding="utf-8",
            )

            summary = schedule_research_stage(root / "knowledge", root / "runs" / "run1", "option-1")

        self.assertEqual(summary["option_title"], "Valid recovered option")
        self.assertEqual(summary["selected_option"]["option_id"], "option-1")

    def test_schedule_research_stage_rejects_duplicate_and_fallback_colliding_option_ids(self):
        cases = (
            [
                valid_option(option_id="dup", title="First"),
                valid_option(option_id="dup", title="Second"),
            ],
            [
                valid_option(title="Fallback option"),
                valid_option(option_id="option-1", title="Explicit collision"),
            ],
        )
        for rows in cases:
            with self.subTest(rows=[row.get("title") for row in rows]), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                decisions = root / "knowledge" / "wiki" / "70_decisions"
                decisions.mkdir(parents=True)
                (decisions / "research_option_cards.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in rows),
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, "duplicate research option id"):
                    schedule_research_stage(root / "knowledge", root / "runs" / "run1", "option-1")

    def test_summarize_stage_artifacts_counts_jsonl_and_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "all_alphas.jsonl").write_text('{"alpha_id":"a1"}\n', encoding="utf-8")
            (root / "candidates.csv").write_text("alpha_id,expression_hash\nA,h\n", encoding="utf-8")
            summary = summarize_stage_artifacts(root)

        self.assertEqual(summary["alpha_result_count"], 1)
        self.assertEqual(summary["candidate_file_exists"], True)
