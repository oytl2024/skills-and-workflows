import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

from tests.test_source_bridge import write_active_metadata, write_source_metadata
from wqb.source_bridge import inspect_scout_seed_source_bridge
from wqb.workflow_stage_adapters import advance_post_schedule_stage, import_scout_seed_artifacts
from wqb.stage_outcomes import research_outcome
from wqb.orchestrator import WorkflowOrchestrator
from wqb.workflow_state import load_run_state, write_run_state
from tests import test_orchestrator


def checked_alpha(label: str = "repairable", **overrides: object) -> dict:
    """Input: label str and row overrides. Output: dict. Build realistic checked research evidence."""
    row = {
        "alpha_id": "parent1", "expression_hash": "parent-hash", "expression": "rank(cash_field)",
        "status": "CHECKED", "hard_pass": label == "qualified",
        "failed": [] if label == "qualified" else ["LOW_FITNESS"], "pending": [],
        "metrics": {"sharpe": 1.3 if label != "weak" else 0.1, "fitness": 0.6,
                    "returns": 0.08, "turnover": 0.2},
    }
    return {**row, **overrides}


def write_rows(root: Path, rows: list[dict]) -> None:
    """Input: root Path and rows list[dict]. Output: None. Persist local checked alpha fixtures."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "all_alphas.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


class StageOutcomeTests(unittest.TestCase):
    def test_repair_retains_deferred_correlation_without_qualifying_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha()])

            def execute(run, parent, actions, maximum):
                """Input: repair context. Output: measured child list with deferred submission checks."""
                return [checked_alpha(alpha_id="child", expression_hash="child-hash",
                                      parent_alpha_id=parent["alpha_id"], pending=["SELF_CORRELATION"]) ]

            result = advance_post_schedule_stage(root, "repair", repair_executor=execute)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["next_stage"], "research_record_sync")
            self.assertFalse((root / "candidates.csv").exists())

    def test_orchestrator_wires_repair_executor_and_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = test_orchestrator.WorkflowOrchestratorTests()
            calls = []

            def execute(run_dir, parent, actions, maximum):
                """Input: repair arguments. Output: checked child list. Capture the injected budget."""
                calls.append(maximum)
                return [checked_alpha("qualified", alpha_id="child", expression_hash="child-hash",
                                      parent_alpha_id=parent["alpha_id"])]

            orchestrator = WorkflowOrchestrator(fixture.paths(Path(tmp)),
                                                repair_executor=execute, repair_max_simulations=3)
            started = orchestrator.start("Power Pool", "option-1", "2026-09-19T00:00:00Z")
            fixture.advance_to_candidate_gate(started)
            root = Path(started["run_dir"])
            state = load_run_state(root / "run_state.json")
            write_run_state(root / "run_state.json", replace(state, current_stage="repair"))
            write_rows(root, [checked_alpha()])
            result = orchestrator.continue_once("2026-09-19T00:01:00Z")
            self.assertEqual(result["current_stage"], "candidate_gate")
            self.assertEqual(calls, [3])
            record = json.loads((root / "research_record.json").read_text())
            self.assertEqual(record["backtest"][-1]["alpha_id"], "child")

    def test_automatic_approval_request_derives_checked_identity_without_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = test_orchestrator.WorkflowOrchestratorTests()
            orchestrator = WorkflowOrchestrator(fixture.paths(Path(tmp)))
            started = orchestrator.start("Power Pool", "option-1", "2026-09-19T00:00:00Z")
            fixture.advance_to_candidate_gate(started)
            root = Path(started["run_dir"])
            (root / "candidates.csv").unlink()
            write_rows(root, [checked_alpha("qualified", candidate_id="untrusted", version=99,
                                           source_run_id="other"), checked_alpha("weak", alpha_id="weak")])
            result = orchestrator.request_candidate_approval_from_checked_results("2026-09-19T00:01:00Z")
            self.assertEqual(result["status"], "waiting_for_user")
            candidates = json.loads((root / "candidate_gate.json").read_text())
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["candidate_id"], "parent1:parent-hash")
            self.assertEqual(candidates[0]["version"], 1)
            self.assertEqual(candidates[0]["platform_alpha_id"], "parent1")
            self.assertEqual(candidates[0]["source_run_id"], started["run_id"])
            self.assertFalse((root / "approved_candidates.jsonl").exists())

    def test_automatic_request_rejects_invalid_or_ambiguous_checked_evidence(self):
        cases = [[], [checked_alpha("weak")], [checked_alpha("qualified", status="SUBMITTED")],
                 [checked_alpha("qualified", pending=["CHECK"])],
                 [checked_alpha("qualified", failed=None)],
                 [checked_alpha("qualified", alpha_id=123)],
                 [checked_alpha("qualified", expression_hash=True)],
                 [checked_alpha("qualified"), checked_alpha("weak")],
                 [checked_alpha("qualified"), checked_alpha("qualified", expression_hash="other")]]
        for rows in cases:
            with self.subTest(rows=rows), tempfile.TemporaryDirectory() as tmp:
                fixture = test_orchestrator.WorkflowOrchestratorTests()
                orchestrator = WorkflowOrchestrator(fixture.paths(Path(tmp)))
                started = orchestrator.start("Power Pool", "option-1", "2026-09-19T00:00:00Z")
                fixture.advance_to_candidate_gate(started)
                root = Path(started["run_dir"])
                (root / "candidates.csv").unlink()
                write_rows(root, rows)
                before = (root / "run_state.json").read_bytes()
                with self.assertRaises(ValueError):
                    orchestrator.request_candidate_approval_from_checked_results("2026-09-19T00:01:00Z")
                self.assertEqual((root / "run_state.json").read_bytes(), before)
                self.assertFalse((root / "candidate_gate.json").exists())

    def test_automatic_request_supports_gate_pause_but_not_other_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = test_orchestrator.WorkflowOrchestratorTests()
            orchestrator = WorkflowOrchestrator(fixture.paths(Path(tmp)))
            started = orchestrator.start("Power Pool", "option-1", "2026-09-19T00:00:00Z")
            with self.assertRaisesRegex(ValueError, "candidate_gate"):
                orchestrator.request_candidate_approval_from_checked_results("2026-09-19T00:01:00Z")
            fixture.advance_to_candidate_gate(started)
            root = Path(started["run_dir"])
            (root / "candidates.csv").unlink()
            write_rows(root, [checked_alpha("qualified")])
            self.assertEqual(orchestrator.continue_once("2026-09-19T00:02:00Z")["status"], "paused")
            result = orchestrator.request_candidate_approval_from_checked_results("2026-09-19T00:03:00Z")
            self.assertEqual(result["status"], "waiting_for_user")

    def test_automatic_request_rejects_changed_import_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = test_orchestrator.WorkflowOrchestratorTests()
            orchestrator = WorkflowOrchestrator(fixture.paths(Path(tmp)))
            started = orchestrator.start("Power Pool", "option-1", "2026-09-19T00:00:00Z")
            root = Path(started["run_dir"])
            source = Path(tmp) / "source"
            write_rows(source, [checked_alpha("weak")])
            import_scout_seed_artifacts(root, source, "2026-09-19T00:01:00Z")
            fixture.advance_to_candidate_gate(started)
            (root / "candidates.csv").unlink()
            write_rows(root, [checked_alpha("qualified")])
            with self.assertRaisesRegex(ValueError, "import receipt"):
                orchestrator.request_candidate_approval_from_checked_results("2026-09-19T00:02:00Z")
            self.assertFalse((root / "candidate_gate.json").exists())

    def test_pending_checks_are_not_repairable_or_no_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha(pending=["NO_CHECKS"])])
            self.assertEqual(research_outcome(root)["outcome"], "pending_review")

    def test_deferred_correlation_does_not_hide_measured_signal(self):
        for label, expected in (("weak", "no_signal"), ("repairable", "repairable_signal")):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_rows(root, [checked_alpha(label, pending=["SELF_CORRELATION", "PROD_CORRELATION"])])
                result = research_outcome(root)
                self.assertEqual(result["outcome"], expected)
                self.assertFalse(result["rows"][0]["hard_pass"])
                self.assertEqual(result["rows"][0]["pending"], ["SELF_CORRELATION", "PROD_CORRELATION"])

    def test_deferred_checks_cannot_replace_missing_metrics_or_failed_checks(self):
        for overrides in ({"metrics": {}}, {"failed": []}, {"pending": ["UNKNOWN_CHECK"]}):
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_rows(root, [checked_alpha(pending=["SELF_CORRELATION"], **overrides)]
                           if "pending" not in overrides else [checked_alpha(**overrides)])
                self.assertEqual(research_outcome(root)["outcome"], "pending_review")

    def test_dictionary_pending_checks_are_classified_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending = [{"name": "SELF_CORRELATION", "result": "PENDING"}]
            write_rows(root, [checked_alpha(pending=pending)])
            result = research_outcome(root)
            self.assertEqual(result["outcome"], "repairable_signal")
            self.assertEqual(result["rows"][0]["pending"], pending)

    def test_malformed_pending_checks_fail_closed(self):
        for pending in ([{}], [["SELF_CORRELATION"]], [None], [1]):
            with self.subTest(pending=pending), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_rows(root, [checked_alpha(pending=pending)])
                self.assertEqual(research_outcome(root)["outcome"], "pending_review")

    def test_changed_import_cannot_complete_execution_stages(self):
        for stage in ("scout_seed", "batch_generation", "backtest", "triage", "repair"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                source, active = Path(tmp) / "source", Path(tmp) / "active"
                write_rows(source, [checked_alpha("weak")])
                active.mkdir()
                import_scout_seed_artifacts(active, source, "2026-09-19T00:00:00Z")
                write_rows(active, [checked_alpha("qualified")])
                self.assertEqual(advance_post_schedule_stage(active, stage)["status"], "paused")

    def test_repair_executes_optimizer_actions_and_persists_lineage_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha()])
            calls = []

            def execute(run_dir, parent, actions, max_simulations):
                """Input: executor contract. Output: checked child rows. Fake external repair only."""
                calls.append((run_dir, parent, actions, max_simulations))
                return [checked_alpha("qualified", alpha_id="child1", expression_hash="child-hash",
                                      parent_alpha_id=parent["alpha_id"])]

            result = advance_post_schedule_stage(root, "repair", repair_executor=execute, repair_max_simulations=3)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["execution"], "executed")
            self.assertEqual(result["next_stage"], "candidate_gate")
            self.assertEqual(calls[0][0], root)
            self.assertEqual(calls[0][1]["expression_hash"], "parent-hash")
            self.assertEqual(calls[0][3], 3)
            self.assertEqual([action["action_type"] for action in calls[0][2]],
                             ["improve_returns", "reduce_turnover", "change_window"])
            rows = research_outcome(root)["rows"]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["parent_expression_hash"], "parent-hash")
            self.assertIn("child1,child-hash", (root / "candidates.csv").read_text())
            replay = advance_post_schedule_stage(root, "repair", repair_executor=execute, repair_max_simulations=3)
            self.assertEqual(replay["status"], "completed")
            self.assertEqual(len(calls), 1)

    def test_empty_or_invalid_repair_cannot_complete_or_repeat_submission(self):
        for rows in ([], [checked_alpha()], [checked_alpha("qualified", alpha_id="child", expression_hash="ch",
                                                        parent_alpha_id="unrelated")]):
            with self.subTest(rows=rows), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_rows(root, [checked_alpha()])
                calls = []

                def execute(*args):
                    """Input: executor args. Output: invalid rows. Count external attempts."""
                    calls.append(args)
                    return rows

                result = advance_post_schedule_stage(root, "repair", repair_executor=execute)
                self.assertEqual(result["status"], "paused")
                self.assertFalse((root / "candidates.csv").exists())
                self.assertEqual(advance_post_schedule_stage(root, "repair", repair_executor=execute)["status"], "paused")
                self.assertEqual(len(calls), 1)

    def test_repair_resumes_only_a_recorded_poll_recovery(self):
        from wqb.repair_runtime import RepairRecoveryPending

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha()])
            calls = []

            def execute(run_dir, parent, actions, maximum):
                """Input: repair contract. Output: checked children. Simulate one safely resumable poll."""
                calls.append(parent["alpha_id"])
                if len(calls) == 1:
                    raise RepairRecoveryPending("recorded progress URL can be polled again")
                return [checked_alpha("qualified", alpha_id="child1", expression_hash="child-hash",
                                      parent_alpha_id=parent["alpha_id"])]

            first = advance_post_schedule_stage(root, "repair", repair_executor=execute)
            self.assertEqual(first["status"], "paused")
            second = advance_post_schedule_stage(root, "repair", repair_executor=execute)
            self.assertEqual(second["status"], "completed", second)
            self.assertEqual(calls, ["parent1", "parent1"])

    def test_imported_repair_resumes_after_first_child_persisted(self):
        from wqb.repair_runtime import RepairRecoveryPending

        with tempfile.TemporaryDirectory() as tmp:
            source, root = Path(tmp) / 'source', Path(tmp) / 'active'
            write_rows(source, [checked_alpha(alpha_id='p1', expression_hash='h1'),
                                checked_alpha(alpha_id='p2', expression_hash='h2')])
            root.mkdir()
            import_scout_seed_artifacts(root, source, '2026-09-23T00:00:00Z')
            calls = []

            def execute(_root, parent, actions, maximum):
                """Input: durable repair contract. Output: checked children. Fail one poll after first append."""
                calls.append(parent['alpha_id'])
                if parent['alpha_id'] == 'p2' and calls.count('p2') == 1:
                    raise RepairRecoveryPending('known progress URL')
                return [checked_alpha('qualified', alpha_id='child-' + parent['alpha_id'],
                                      expression_hash='child-h-' + parent['alpha_id'],
                                      parent_alpha_id=parent['alpha_id'])]

            first = advance_post_schedule_stage(root, 'repair', repair_executor=execute, repair_max_simulations=2)
            self.assertEqual(first['status'], 'paused')
            self.assertEqual(len(research_outcome(root)['rows']), 3)
            second = advance_post_schedule_stage(root, 'repair', repair_executor=execute, repair_max_simulations=2)
            self.assertEqual(second['status'], 'completed', second)
            self.assertEqual(calls, ['p1', 'p2', 'p2'])

    def test_orchestrator_imports_no_signal_but_requires_mission_authority_to_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = test_orchestrator.WorkflowOrchestratorTests()
            orchestrator = WorkflowOrchestrator(fixture.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-09-19T00:00:00Z")
            for _ in range(3):
                orchestrator.continue_once("2026-09-19T00:01:00Z")
            active = Path(started["run_dir"])
            source = root / "runs" / "source"
            write_rows(source, [checked_alpha("weak")])
            binding = active / "stages" / "scout_seed" / "source_bridge_binding.json"
            binding.write_text(json.dumps({"source_run_id": "source"}), encoding="utf-8")
            try:
                orchestrator.import_scout_seed_bridge_decision(
                    {"action": "import_research_outcome", "source_run_id": "source"}, "2026-09-19T00:02:00Z")
            except ValueError as exc:
                self.fail(f"research import route rejected: {exc}")
            orchestrator.resume("2026-09-19T00:03:00Z")
            for _ in range(6):
                result = orchestrator.continue_once("2026-09-19T00:04:00Z")
            self.assertEqual(result["status"], "paused")
            self.assertIn("research_mission_authority_required", str(result))
            record = json.loads((active / "research_record.json").read_text())
            self.assertEqual(record["backtest"][0]["alpha_id"], "parent1")
            self.assertEqual(record["triage"][0]["benchmark_label"], "weak_discard")
            self.assertFalse((active / "candidates.csv").exists())

    def test_empty_or_unchecked_artifacts_cannot_complete_any_stage(self):
        """Input: none. Output: None. Reject file existence and identity-only rows as execution proof."""
        for rows in ([], [{"alpha_id": "a1", "expression_hash": "h1"}]):
            for stage in ("scout_seed", "batch_generation", "backtest", "triage", "repair"):
                with self.subTest(rows=rows, stage=stage), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    write_rows(root, rows)
                    (root / "candidates.csv").write_text("alpha_id,expression_hash\na1,h1\n", encoding="utf-8")
                    result = advance_post_schedule_stage(root, stage)
                    self.assertEqual(result["status"], "paused")

    def test_checked_signal_import_and_triage_do_not_require_candidate_csv(self):
        """Input: none. Output: None. Route checked near misses through audited import and triage."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, active = root / "source", root / "active"
            write_rows(source, [checked_alpha()])
            active.mkdir()
            result = import_scout_seed_artifacts(active, source, "2026-09-05T00:00:00Z")
            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["outcome"], "repairable_signal")
            for stage in ("scout_seed", "batch_generation", "backtest", "triage"):
                receipt = advance_post_schedule_stage(active, stage)
                self.assertEqual(receipt["status"], "completed")
                self.assertEqual(receipt["checked_count"], 1)
            repair = advance_post_schedule_stage(active, "repair")
            self.assertEqual(repair["status"], "paused")
            self.assertIn("executor", repair["blocker"])
            self.assertFalse((active / "candidates.csv").exists())

    def test_weak_results_finish_research_without_requesting_candidate_approval(self):
        """Input: none. Output: None. Record weak research as a completed bounded outcome."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root, [checked_alpha("weak")])
            result = advance_post_schedule_stage(root, "repair")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["outcome"], "no_signal")
            self.assertEqual(result["next_stage"], "research_record_sync")
            self.assertEqual(result["execution"], "skipped")

    def test_bridge_routes_checked_research_before_exhausted_rate_retry_gate(self):
        """Input: none. Output: None. Import terminal checked samples despite old 429 retry evidence."""
        for label, outcome in (("repairable", "repairable_signal"), ("weak", "no_signal")):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                active, source = root / "active", root / "source"
                write_active_metadata(active)
                write_source_metadata(source)
                write_rows(source, [checked_alpha(label)])
                (source / "rate_limit_state.json").write_text(json.dumps({
                    "consecutive_429_count": 2, "max_consecutive_429": 3,
                    "status": "cooldown", "retry_at": "2026-08-01T00:00:00Z",
                }), encoding="utf-8")
                decision = inspect_scout_seed_source_bridge(root, active, "2026-09-05T00:00:00Z")
                self.assertEqual(decision.action, "import_research_outcome")
                self.assertEqual(decision.metadata["outcome"], outcome)
