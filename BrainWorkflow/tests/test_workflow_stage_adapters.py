import json
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_stage_adapters import schedule_research_stage, summarize_stage_artifacts


class WorkflowStageAdaptersTests(unittest.TestCase):
    def test_schedule_research_stage_writes_stage_artifact_from_option_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            decisions = knowledge / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps({"option_id": "option-1", "title": "Power Pool", "scope": "USA D1", "score": {"total": 10}}) + "\n",
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
                '{"option_id":"option-1","title":"Power Pool","scope":"USA D1"}\n', encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "selected research option not found"):
                schedule_research_stage(root / "knowledge", root / "runs" / "run1", "unknown")

    def test_schedule_research_stage_uses_stable_positional_id_for_planner_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                '{"title":"First","scope":"USA D1"}\n'
                '{"title":"Second","scope":"USA D1"}\n',
                encoding="utf-8",
            )

            summary = schedule_research_stage(root / "knowledge", root / "runs" / "run1", "option-2")

        self.assertEqual(summary["option_title"], "Second")
        self.assertEqual(summary["selected_option"]["option_id"], "option-2")

    def test_summarize_stage_artifacts_counts_jsonl_and_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "all_alphas.jsonl").write_text('{"alpha_id":"a1"}\n', encoding="utf-8")
            (root / "candidates.csv").write_text("alpha_id,expression_hash\nA,h\n", encoding="utf-8")
            summary = summarize_stage_artifacts(root)

        self.assertEqual(summary["alpha_result_count"], 1)
        self.assertEqual(summary["candidate_file_exists"], True)
