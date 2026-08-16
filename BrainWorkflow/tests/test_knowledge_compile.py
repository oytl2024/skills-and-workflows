import tempfile
import unittest
import json
from pathlib import Path

from wqb.knowledge_clean_compile import evaluate_clean_knowledge_structure
from wqb.knowledge_compile import compile_research_records
from wqb.knowledge_freshness import evaluate_knowledge_contract_health
from wqb.research_record import empty_research_record, record_alpha_result, sync_research_record_to_raw


class KnowledgeCompileTests(unittest.TestCase):
    def test_compile_research_records_writes_experiment_summary_from_raw_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = record_alpha_result(
                empty_research_record("run1", "Power Pool"),
                {
                    "alpha_id": "alpha1",
                    "expression_hash": "hash1",
                    "hard_pass": False,
                    "benchmark_label": "near_miss",
                    "failed": ["prod_correlation"],
                },
            )
            sync_research_record_to_raw(record, root / "raw")

            result = compile_research_records(root, generated_at="2026-07-16T00:00:00Z")

            output = Path(result["markdown_path"])
            text = output.read_text(encoding="utf-8")
            ledger_exists = (root / "machine" / "research_records.jsonl").exists()
            legacy_exists = (root / "wiki" / "40_experiments").exists()

        self.assertEqual(result["record_count"], 1)
        self.assertEqual(output, root / "wiki" / "60_research_cases" / "run1.md")
        self.assertIn("run1", text)
        self.assertIn("Power Pool", text)
        self.assertTrue(ledger_exists)
        self.assertFalse(legacy_exists)

    def test_compile_research_records_outputs_contract_compliant_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = record_alpha_result(
                empty_research_record("run1", "Power Pool"),
                {
                    "alpha_id": "alpha1",
                    "expression_hash": "hash1",
                    "hard_pass": False,
                    "benchmark_label": "near_miss",
                    "failed": ["prod_correlation"],
                },
            )
            sync_research_record_to_raw(record, root / "raw")

            compile_research_records(root, generated_at="2026-07-16T00:00:00Z")

            clean = evaluate_clean_knowledge_structure(root)
            health = evaluate_knowledge_contract_health(root)

        self.assertTrue(clean["clean"], clean["issues"])
        self.assertEqual(health["issue_count"], 0, health["issues"])

    def test_compile_research_records_preserves_existing_snapshots_for_same_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / "machine" / "research_records.jsonl"
            ledger.parent.mkdir(parents=True)
            first = {
                "run_id": "run1",
                "objective": "Power Pool",
                "synced_at": "2026-07-15T00:00:00Z",
                "final_state": "repair",
                "candidate_gate": [{"candidate_id": "c1"}],
            }
            second = {
                "run_id": "run1",
                "objective": "Power Pool",
                "synced_at": "2026-07-16T00:00:00Z",
                "final_state": "waiting_for_user",
                "candidate_gate": [{"candidate_id": "c2"}],
            }
            ledger.write_text(
                json.dumps(first, sort_keys=True) + "\n" + json.dumps(second, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            compile_research_records(root, generated_at="2026-07-17T00:00:00Z")
            rows = [
                json.loads(line)
                for line in ledger.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(rows, [first, second])

    def test_compile_research_records_is_idempotent_for_same_raw_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = record_alpha_result(
                empty_research_record("run1", "Power Pool"),
                {
                    "alpha_id": "alpha1",
                    "expression_hash": "hash1",
                    "hard_pass": False,
                    "benchmark_label": "near_miss",
                    "failed": ["prod_correlation"],
                },
            )
            sync_research_record_to_raw(record, root / "raw")

            compile_research_records(root, generated_at="2026-07-16T00:00:00Z")
            compile_research_records(root, generated_at="2026-07-17T00:00:00Z")
            rows = [
                json.loads(line)
                for line in (root / "machine" / "research_records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        compiled_rows = [row for row in rows if row.get("final_state") == "compiled_from_raw"]
        self.assertEqual(len(compiled_rows), 1)
        self.assertEqual(compiled_rows[0]["raw_source_path"], str(root / "raw" / "research" / "runs" / "run1" / "research_record.md"))

    def test_compile_research_records_appends_changed_same_path_raw_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = record_alpha_result(
                empty_research_record("run1", "Power Pool"),
                {
                    "alpha_id": "alpha1",
                    "expression_hash": "hash1",
                    "hard_pass": False,
                    "benchmark_label": "near_miss",
                    "failed": ["prod_correlation"],
                },
            )
            sync_research_record_to_raw(record, root / "raw")
            compile_research_records(root, generated_at="2026-07-16T00:00:00Z")

            updated = record_alpha_result(
                record,
                {
                    "alpha_id": "alpha2",
                    "expression_hash": "hash2",
                    "hard_pass": False,
                    "benchmark_label": "near_miss",
                    "failed": ["self_correlation"],
                },
            )
            sync_research_record_to_raw(updated, root / "raw")
            compile_research_records(root, generated_at="2026-07-17T00:00:00Z")
            rows = [
                json.loads(line)
                for line in (root / "machine" / "research_records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        compiled_rows = [row for row in rows if row.get("final_state") == "compiled_from_raw"]
        self.assertEqual(len(compiled_rows), 2)
        self.assertTrue(compiled_rows[0]["content_hash"])
        self.assertTrue(compiled_rows[1]["content_hash"])
        self.assertNotEqual(compiled_rows[0]["content_hash"], compiled_rows[1]["content_hash"])


if __name__ == "__main__":
    unittest.main()
