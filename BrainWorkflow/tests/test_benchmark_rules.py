import tempfile
import unittest
from pathlib import Path

from wqb.benchmark_rules import (
    default_benchmark_rules,
    load_benchmark_rules,
    rules_for_issue_type,
    write_benchmark_rules_jsonl,
    write_benchmark_rules_markdown,
)


class BenchmarkRulesTests(unittest.TestCase):
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
