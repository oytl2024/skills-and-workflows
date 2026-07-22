import tempfile
import unittest
from pathlib import Path

from wqb.benchmark import benchmark_alpha_record
from wqb.benchmark_rules import (
    BenchmarkRule,
    default_benchmark_rules,
    load_benchmark_rules,
    rules_for_issue_type,
    write_benchmark_rules_jsonl,
    write_benchmark_rules_markdown,
)


class BenchmarkRulesTests(unittest.TestCase):
    def test_candidate_gate_uses_applicable_active_rule_for_pnl_promotion(self):
        record = {
            "hard_pass": False,
            "metrics": {"sharpe": 0.7, "fitness": 0.1, "returns": 0.1, "turnover": 0.2},
            "failed": ["LOW_SHARPE"],
            "pending": [],
            "signal_note": "stable pnl",
        }
        rule = BenchmarkRule(
            rule_id="curated_pnl_promotion",
            issue_types=["pnl_signal"],
            description="Promote stable PnL.",
            promotion_condition="Stable PnL is observed.",
            action="Send the candidate to repair.",
            evidence_paths=[],
            consumed_by=["candidate_gate"],
            risk="May promote a fragile signal.",
        )

        without_rule = benchmark_alpha_record(record, benchmark_rules=[])
        with_rule = benchmark_alpha_record(record, benchmark_rules=[rule])

        self.assertEqual(without_rule.label, "weak_discard")
        self.assertEqual(with_rule.label, "repairable_signal")
        self.assertIn("benchmark_rule:curated_pnl_promotion", with_rule.reasons)

    def test_default_rules_include_near_miss_and_correlation_cases(self):
        rules = default_benchmark_rules()
        ids = {rule.rule_id for rule in rules}

        self.assertIn("near_miss_stable_pnl_promotion", ids)
        self.assertIn("prod_correlation_novelty_required", ids)
        self.assertTrue(rules_for_issue_type(rules, "pnl_signal"))
        self.assertTrue(rules_for_issue_type(rules, "prod_correlation"))

    def test_write_and_load_benchmark_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jsonl = root / "benchmark_rules.jsonl"
            md = root / "benchmark_rules.md"
            rules = default_benchmark_rules()

            write_benchmark_rules_jsonl(jsonl, rules)
            write_benchmark_rules_markdown(md, rules, "2026-07-22T00:00:00+00:00")
            loaded = load_benchmark_rules(jsonl)
            markdown = md.read_text(encoding="utf-8")

        self.assertEqual(len(loaded), len(rules))
        self.assertIn("near_miss_stable_pnl_promotion", markdown)
        self.assertIn("3q7OQaog", markdown)


if __name__ == "__main__":
    unittest.main()
