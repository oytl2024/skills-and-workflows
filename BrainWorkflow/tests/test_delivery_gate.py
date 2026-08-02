import json
from pathlib import Path
import tempfile
import unittest

from wqb.delivery_gate import run_delivery_gate


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

    def test_delivery_gate_accepts_expected_durable_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            run_dir = runs / "20260730T000000-paused"
            run_dir.mkdir(parents=True)
            (run_dir / "run_state.json").write_text(
                json.dumps(
                    {
                        "run_id": "20260730T000000-paused",
                        "status": "paused",
                        "stage": "scout_seed",
                        "pause_reason": "missing candidates.csv",
                        "evidence_paths": ["stages/scout_seed/scout_seed_handoff.json"],
                    }
                ),
                encoding="utf-8",
            )
            handoff = run_dir / "stages" / "scout_seed" / "scout_seed_handoff.json"
            handoff.parent.mkdir(parents=True)
            handoff.write_text("{}", encoding="utf-8")

            report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "passed")
            self.assertIn("expected_pause", {check["code"] for check in report["checks"]})

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
