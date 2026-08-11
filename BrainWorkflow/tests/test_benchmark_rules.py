import json
import tempfile
import unittest
from pathlib import Path

from wqb.benchmark import benchmark_alpha_record
from wqb.benchmark_rules import (
    BenchmarkRule,
    benchmark_rule_to_dict,
    benchmark_rulebook_digest,
    default_benchmark_rules,
    load_active_benchmark_rules,
    load_benchmark_rules,
    load_run_benchmark_rules,
    rules_for_issue_type,
    write_benchmark_rules_jsonl,
    write_benchmark_rules_markdown,
)


class BenchmarkRulesTests(unittest.TestCase):
    def test_gate_classification_uses_edited_persisted_rulebook(self):
        record = {
            "hard_pass": False,
            "metrics": {"sharpe": 0.7, "fitness": 0.1, "returns": 0.1, "turnover": 0.2},
            "failed": ["LOW_SHARPE"],
            "pending": [],
            "signal_note": "stable pnl",
        }
        unrelated = BenchmarkRule(
            rule_id="unrelated_rule",
            issue_types=["prod_correlation"],
            description="Handle production correlation.",
            promotion_condition="Production correlation fails.",
            action="Require novelty.",
            evidence_paths=[],
            consumed_by=["candidate_gate"],
            risk="May reject a repairable family.",
        )
        promotion = BenchmarkRule(
            rule_id="persisted_pnl_promotion",
            issue_types=["pnl_signal"],
            description="Promote stable PnL.",
            promotion_condition="Stable PnL is observed.",
            action="Send the candidate to repair.",
            evidence_paths=[],
            consumed_by=["candidate_gate"],
            risk="May promote a fragile signal.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            path = root / "machine" / "benchmark_rules.jsonl"
            write_benchmark_rules_jsonl(path, [unrelated])
            before = benchmark_alpha_record(
                record,
                knowledge_root=root,
                consumer="candidate_gate",
            )

            write_benchmark_rules_jsonl(path, [promotion])
            after = benchmark_alpha_record(
                record,
                knowledge_root=root,
                consumer="candidate_gate",
            )

        self.assertEqual(before.label, "weak_discard")
        self.assertEqual(after.label, "repairable_signal")
        self.assertIn("benchmark_rule:persisted_pnl_promotion", after.reasons)

    def test_present_empty_rulebook_does_not_restore_default_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            path = root / "machine" / "benchmark_rules.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("", encoding="utf-8")

            rules = load_active_benchmark_rules(root)

        self.assertEqual(rules, [])

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

        without_rule = benchmark_alpha_record(
            record,
            benchmark_rules=[],
            consumer="candidate_gate",
        )
        with_rule = benchmark_alpha_record(
            record,
            benchmark_rules=[rule],
            consumer="candidate_gate",
        )

        self.assertEqual(without_rule.label, "weak_discard")
        self.assertEqual(with_rule.label, "repairable_signal")
        self.assertIn("benchmark_rule:curated_pnl_promotion", with_rule.reasons)

    def test_gate_classification_filters_rules_by_consumer_before_issue_type(self):
        record = {
            "hard_pass": False,
            "metrics": {"sharpe": 0.7, "fitness": 0.1, "returns": 0.1, "turnover": 0.2},
            "failed": ["LOW_SHARPE"],
            "pending": [],
            "signal_note": "stable pnl",
        }
        proposal_rule = BenchmarkRule(
            rule_id="proposal_only_pnl",
            issue_types=["pnl_signal"],
            description="Draft a proposal for stable PnL.",
            promotion_condition="Stable PnL is observed.",
            action="Create a workflow proposal.",
            evidence_paths=[],
            consumed_by=["workflow_proposals"],
            risk="May create noisy proposals.",
        )
        repair_rule = BenchmarkRule(
            rule_id="repair_pnl",
            issue_types=["pnl_signal"],
            description="Promote stable PnL to repair.",
            promotion_condition="Stable PnL is observed.",
            action="Send the alpha to repair.",
            evidence_paths=[],
            consumed_by=["repair_loop"],
            risk="May promote a fragile signal.",
        )

        unrelated = benchmark_alpha_record(
            record,
            benchmark_rules=[proposal_rule],
            consumer="repair_loop",
        )
        applicable = benchmark_alpha_record(
            record,
            benchmark_rules=[proposal_rule, repair_rule],
            consumer="repair_loop",
        )

        self.assertEqual(unrelated.label, "weak_discard")
        self.assertEqual(applicable.label, "repairable_signal")
        self.assertNotIn("benchmark_rule:proposal_only_pnl", applicable.reasons)
        self.assertIn("benchmark_rule:repair_pnl", applicable.reasons)

    def test_missing_persisted_rulebook_does_not_restore_defaults_for_runtime_gate(self):
        record = {
            "hard_pass": False,
            "metrics": {"sharpe": 0.7, "fitness": 0.1, "returns": 0.1, "turnover": 0.2},
            "failed": ["LOW_SHARPE"],
            "pending": [],
            "signal_note": "stable pnl",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"

            result = benchmark_alpha_record(
                record,
                knowledge_root=root,
                consumer="repair_loop",
            )

        self.assertEqual(result.label, "weak_discard")
        self.assertNotIn("benchmark_rule:near_miss_stable_pnl_promotion", result.reasons)

    def test_official_run_without_snapshot_authority_rejects_vault_rulebook_fallback(self):
        record = {
            "hard_pass": False,
            "metrics": {"sharpe": 0.7, "fitness": 0.1, "returns": 0.1, "turnover": 0.2},
            "failed": ["LOW_SHARPE"],
            "pending": [],
            "signal_note": "stable pnl",
        }
        rule = BenchmarkRule(
            rule_id="mutable_vault_rule",
            issue_types=["pnl_signal"],
            description="This mutable vault rule must not classify a damaged official run.",
            promotion_condition="Stable PnL is observed.",
            action="Send the alpha to repair.",
            evidence_paths=[],
            consumed_by=["candidate_gate"],
            risk="May hide missing run authority.",
        )
        cases = ("missing manifest", "manifest without snapshot")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                knowledge = root / "knowledge"
                write_benchmark_rules_jsonl(
                    knowledge / "machine" / "benchmark_rules.jsonl",
                    [rule],
                )
                run_dir = root / "runs" / "run1"
                run_dir.mkdir(parents=True)
                (run_dir / "run_state.json").write_text("{}", encoding="utf-8")
                if case == "manifest without snapshot":
                    (run_dir / "run_manifest.json").write_text(
                        json.dumps({"run_id": "run1", "selected_option_id": "option-1"}),
                        encoding="utf-8",
                    )

                with self.assertRaisesRegex(ValueError, "benchmark rule authority"):
                    benchmark_alpha_record(
                        record,
                        knowledge_root=knowledge,
                        run_dir=run_dir,
                        consumer="candidate_gate",
                    )

    def test_official_run_authority_is_validated_before_early_classification_returns(self):
        cases = (
            (
                "hard pass",
                {
                    "hard_pass": True,
                    "metrics": {},
                    "failed": [],
                    "pending": [],
                },
            ),
            (
                "checks pending",
                {
                    "hard_pass": False,
                    "metrics": {},
                    "failed": [],
                    "pending": ["NO_CHECKS"],
                },
            ),
            (
                "non-repairable check",
                {
                    "hard_pass": False,
                    "metrics": {},
                    "failed": ["INVALID_OPERATOR"],
                    "pending": [],
                },
            ),
        )
        for label, record in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp) / "run1"
                run_dir.mkdir()
                (run_dir / "run_state.json").write_text("{}", encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "benchmark rule authority"):
                    benchmark_alpha_record(record, run_dir=run_dir)

    def test_injected_rules_cannot_bypass_missing_official_run_authority(self):
        record = {
            "hard_pass": False,
            "metrics": {"sharpe": 0.7, "fitness": 0.1, "returns": 0.1, "turnover": 0.2},
            "failed": ["LOW_SHARPE"],
            "pending": [],
            "signal_note": "stable pnl",
        }
        injected_rule = default_benchmark_rules()[0]
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            run_dir.mkdir()
            (run_dir / "workflow_events.jsonl").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "benchmark rule authority"):
                benchmark_alpha_record(
                    record,
                    benchmark_rules=[injected_rule],
                    run_dir=run_dir,
                )

    def test_official_run_authority_takes_precedence_over_injected_rules(self):
        record = {
            "hard_pass": False,
            "metrics": {"sharpe": 0.7, "fitness": 0.1, "returns": 0.1, "turnover": 0.2},
            "failed": ["LOW_SHARPE"],
            "pending": [],
            "signal_note": "stable pnl",
        }
        injected_rule = default_benchmark_rules()[0]
        bound_rule = BenchmarkRule(
            rule_id="bound_correlation_rule",
            issue_types=["prod_correlation"],
            description="Require novelty for production correlation.",
            promotion_condition="Production correlation fails.",
            action="Require a novel research direction.",
            evidence_paths=[],
            consumed_by=["candidate_gate"],
            risk="May reject a repairable family.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            run_dir.mkdir()
            (run_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run1",
                        "start_snapshot": {
                            "artifact_binding_version": 2,
                            "benchmark_rulebook": {
                                "path": "machine/benchmark_rules.jsonl",
                                "sha256": benchmark_rulebook_digest([bound_rule]),
                                "rules": [benchmark_rule_to_dict(bound_rule)],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = benchmark_alpha_record(
                record,
                benchmark_rules=[injected_rule],
                run_dir=run_dir,
            )

        self.assertEqual(result.label, "weak_discard")
        self.assertNotIn(f"benchmark_rule:{injected_rule.rule_id}", result.reasons)

    def test_historical_v2_snapshot_accepts_legacy_embedded_rulebook_path(self):
        rule = BenchmarkRule(
            rule_id="historical_bound_rule",
            issue_types=["pnl_signal"],
            description="Use the immutable historical snapshot rule.",
            promotion_condition="Stable PnL is observed.",
            action="Send the alpha to repair.",
            evidence_paths=["knowledge/wiki/50_benchmarks/legacy_rule.md"],
            consumed_by=["candidate_gate"],
            risk="May promote a fragile signal.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            run_dir.mkdir()
            (run_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run1",
                        "start_snapshot": {
                            "artifact_binding_version": 2,
                            "benchmark_rulebook": {
                                "path": "wiki/50_benchmarks/benchmark_rules.jsonl",
                                "sha256": benchmark_rulebook_digest([rule]),
                                "rules": [benchmark_rule_to_dict(rule)],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_run_benchmark_rules(run_dir)

        self.assertEqual([item.rule_id for item in loaded or []], ["historical_bound_rule"])

    def test_official_run_rejects_unknown_noncanonical_rulebook_path(self):
        rule = default_benchmark_rules()[0]
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            run_dir.mkdir()
            (run_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run1",
                        "start_snapshot": {
                            "artifact_binding_version": 2,
                            "benchmark_rulebook": {
                                "path": "wiki/random/benchmark_rules.jsonl",
                                "sha256": benchmark_rulebook_digest([rule]),
                                "rules": [benchmark_rule_to_dict(rule)],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "benchmark rule authority.*path is not canonical"):
                load_run_benchmark_rules(run_dir)

    def test_official_run_rejects_backslash_legacy_rulebook_path_alias(self):
        rule = default_benchmark_rules()[0]
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            run_dir.mkdir()
            (run_dir / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run1",
                        "start_snapshot": {
                            "artifact_binding_version": 2,
                            "benchmark_rulebook": {
                                "path": "wiki\\50_benchmarks\\benchmark_rules.jsonl",
                                "sha256": benchmark_rulebook_digest([rule]),
                                "rules": [benchmark_rule_to_dict(rule)],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "benchmark rule authority.*path is not canonical"):
                load_run_benchmark_rules(run_dir)

    def test_official_run_rejects_non_v2_start_snapshot_authority(self):
        record = {
            "hard_pass": False,
            "metrics": {"sharpe": 0.7, "fitness": 0.1, "returns": 0.1, "turnover": 0.2},
            "failed": ["LOW_SHARPE"],
            "pending": [],
            "signal_note": "stable pnl",
        }
        rule = default_benchmark_rules()[0]
        for version in (1, 2.5, "2", True, None):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp) / "run1"
                run_dir.mkdir()
                (run_dir / "run_manifest.json").write_text(
                    json.dumps(
                        {
                            "run_id": "run1",
                            "start_snapshot": {
                                "artifact_binding_version": version,
                                "benchmark_rulebook": {
                                    "path": "machine/benchmark_rules.jsonl",
                                    "sha256": benchmark_rulebook_digest([rule]),
                                    "rules": [benchmark_rule_to_dict(rule)],
                                },
                            },
                        }
                    ),
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, "benchmark rule authority.*version"):
                    benchmark_alpha_record(record, run_dir=run_dir)

    def test_default_rules_include_near_miss_and_correlation_cases(self):
        rules = default_benchmark_rules()
        ids = {rule.rule_id for rule in rules}

        self.assertIn("near_miss_stable_pnl_promotion", ids)
        self.assertIn("prod_correlation_novelty_required", ids)
        self.assertTrue(rules_for_issue_type(rules, "pnl_signal"))
        self.assertTrue(rules_for_issue_type(rules, "prod_correlation"))
        all_evidence = "\n".join(path for rule in rules for path in rule.evidence_paths)
        self.assertNotIn("wiki/50_benchmarks", all_evidence)
        self.assertIn("machine/benchmark_rules.jsonl", all_evidence)
        self.assertIn("wiki/40_benchmark_and_repair_rules.md", all_evidence)

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
