import tempfile
import unittest
from pathlib import Path

from wqb.knowledge_compile import compile_research_records


class KnowledgeCompileTests(unittest.TestCase):
    def test_compile_research_records_writes_experiment_summary_from_raw_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_record = root / "raw" / "research" / "runs" / "run1" / "research_record.md"
            raw_record.parent.mkdir(parents=True)
            raw_record.write_text(
                "# Research Record\n\n- Run ID: `run1`\n- Objective: Power Pool\n\n## Backtest\n- `alpha1` `hash1`\n",
                encoding="utf-8",
            )

            result = compile_research_records(root, generated_at="2026-07-16T00:00:00Z")

            output = Path(result["markdown_path"])
            text = output.read_text(encoding="utf-8")

        self.assertEqual(result["record_count"], 1)
        self.assertIn("Research Record Compile", text)
        self.assertIn("run1", text)
        self.assertIn("Power Pool", text)


if __name__ == "__main__":
    unittest.main()
