import tempfile
import unittest
from pathlib import Path

from wqb.benchmark_rules import BenchmarkRule, write_benchmark_rules_jsonl
from wqb.research_workflow import (
    build_parallel_stage_plan,
    cap_simulation_count,
    is_near_miss,
    precheck_expression,
    workflow_action_for_platform_issue,
)


class ResearchWorkflowTests(unittest.TestCase):
    def test_scout_and_repair_cap_small_batches(self):
        self.assertEqual(cap_simulation_count("scout", 2), 30)
        self.assertEqual(cap_simulation_count("scout", 50), 30)
        self.assertEqual(cap_simulation_count("repair", 50), 8)
        self.assertEqual(cap_simulation_count("discovery", 50), 50)

    def test_precheck_rejects_complex_expressions_for_scout(self):
        multiline = "rank(ts_mean(field_a, 5))\nrank(field_b)"
        nested = "rank(ts_mean(ts_delta(ts_mean(field_a, 5), 10), 20))"
        many_params = "rank(ts_mean(ts_delta(field_a, 5), 10) + ts_mean(field_b, 20))"

        self.assertFalse(precheck_expression(multiline, "scout").ok)
        self.assertFalse(precheck_expression(nested, "scout").ok)
        self.assertFalse(precheck_expression(many_params, "scout").ok)
        self.assertTrue(precheck_expression("rank(field_a_fast_d1 - field_a)", "scout").ok)

    def test_near_miss_requires_good_core_metrics_and_repairable_failures(self):
        repairable = {
            "metrics": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.28},
            "failed": ["SELF_CORRELATION"],
            "pending": [],
        }
        weak = {
            "metrics": {"sharpe": 0.8, "fitness": 0.4, "turnover": 0.28},
            "failed": ["LOW_SHARPE", "LOW_FITNESS"],
            "pending": [],
        }
        unknown_failure = {
            "metrics": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.28},
            "failed": ["MATCHES_COMPETITION"],
            "pending": [],
        }

        self.assertTrue(is_near_miss(repairable))
        self.assertFalse(is_near_miss(weak))
        self.assertFalse(is_near_miss(unknown_failure))

    def test_near_miss_allows_stable_pnl_signal_before_hard_thresholds(self):
        stable_signal = {
            "metrics": {"sharpe": 0.95, "fitness": 0.42, "returns": 0.025, "turnover": 0.22},
            "failed": ["LOW_SHARPE", "LOW_FITNESS", "LOW_2Y_SHARPE"],
            "pending": [],
            "signal_note": "straight PnL",
        }

        self.assertTrue(is_near_miss(stable_signal))

    def test_near_miss_uses_persisted_repair_rules(self):
        stable_signal = {
            "metrics": {"sharpe": 0.7, "fitness": 0.1, "returns": 0.1, "turnover": 0.2},
            "failed": ["LOW_SHARPE"],
            "pending": [],
            "signal_note": "stable pnl",
        }
        promotion = BenchmarkRule(
            rule_id="persisted_near_miss",
            issue_types=["pnl_signal"],
            description="Promote stable PnL.",
            promotion_condition="Stable PnL is observed.",
            action="Send the candidate to repair.",
            evidence_paths=[],
            consumed_by=["repair_loop"],
            risk="May promote a fragile signal.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            path = root / "wiki" / "50_benchmarks" / "benchmark_rules.jsonl"
            write_benchmark_rules_jsonl(path, [])
            before = is_near_miss(
                stable_signal,
                knowledge_root=root,
                consumer="repair_loop",
            )

            write_benchmark_rules_jsonl(path, [promotion])
            after = is_near_miss(
                stable_signal,
                knowledge_root=root,
                consumer="repair_loop",
            )

        self.assertFalse(before)
        self.assertTrue(after)

    def test_near_miss_ignores_pnl_rule_for_unrelated_consumer(self):
        stable_signal = {
            "metrics": {"sharpe": 0.7, "fitness": 0.1, "returns": 0.1, "turnover": 0.2},
            "failed": ["LOW_SHARPE"],
            "pending": [],
            "signal_note": "stable pnl",
        }
        proposal_rule = BenchmarkRule(
            rule_id="proposal_only_pnl",
            issue_types=["pnl_signal"],
            description="Draft a workflow proposal.",
            promotion_condition="Stable PnL is observed.",
            action="Create a proposal.",
            evidence_paths=[],
            consumed_by=["workflow_proposals"],
            risk="May create noisy proposals.",
        )

        promoted = is_near_miss(
            stable_signal,
            benchmark_rules=[proposal_rule],
            consumer="repair_loop",
        )

        self.assertFalse(promoted)

    def test_scout_plan_splits_new_data_work_into_parallel_tasks(self):
        tasks = build_parallel_stage_plan("scout", ["search_interest", "news21"])
        scout_tasks = [task for task in tasks if task.task_type == "data_scout"]
        diagnosis_tasks = [task for task in tasks if task.task_type == "diagnosis"]
        knowledge_tasks = [task for task in tasks if task.task_type == "knowledge_update"]

        self.assertEqual([task.dataset_id for task in scout_tasks], ["search_interest", "news21"])
        self.assertEqual([task.parallel_group for task in scout_tasks], ["new_data_scout", "new_data_scout"])
        self.assertEqual(len(diagnosis_tasks), 1)
        self.assertEqual(set(diagnosis_tasks[0].depends_on), {task.task_id for task in scout_tasks})
        self.assertEqual(len(knowledge_tasks), 1)
        self.assertIn(diagnosis_tasks[0].task_id, knowledge_tasks[0].depends_on)

    def test_platform_issue_maps_to_workflow_action(self):
        missing_peer = workflow_action_for_platform_issue(
            'Attempted to use unknown variable "relative_interest_score_3"'
        )
        vector_type = workflow_action_for_platform_issue("Operator rank does not support event inputs")
        broad_search = workflow_action_for_platform_issue("broad field search selected an unintended field")
        network = workflow_action_for_platform_issue("ConnectionResetError 10054 during poll")
        rate_limit = workflow_action_for_platform_issue("HTTP 429 while submitting simulation")
        weak_branch = workflow_action_for_platform_issue("LOW_SHARPE and LOW_FITNESS in Scout")

        self.assertEqual(missing_peer["rule"], "disable_regular_peer_templates")
        self.assertEqual(vector_type["rule"], "convert_event_or_vector_field")
        self.assertEqual(broad_search["rule"], "use_exact_field_id")
        self.assertEqual(network["rule"], "recover_in_flight_before_resubmit")
        self.assertEqual(rate_limit["rule"], "cooldown_and_reduce_batch")
        self.assertEqual(weak_branch["rule"], "benchmark_signal_before_discard")

    def test_result_recovery_plan_forbids_resubmission_until_recovered(self):
        tasks = build_parallel_stage_plan("result_recovery", ["runs/20260630_001629"])

        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0].task_type, "result_recovery")
        self.assertIn("submit_simulation", tasks[0].forbidden_actions)
        self.assertIn("run_dir", tasks[0].inputs)
        self.assertIn("recovered_alpha_ids", tasks[0].outputs)
        self.assertIn(tasks[0].task_id, tasks[1].depends_on)


if __name__ == "__main__":
    unittest.main()
