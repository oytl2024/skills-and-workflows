import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from wqb.cli import default_orchestrator_paths
from wqb.orchestrator import WorkflowOrchestrator
from wqb.source_bridge import SourceBridgeDecision
from wqb.workflow_auto_continue import auto_continue_workflow


def write_candidate_file(path: Path) -> None:
    """Input: candidate CSV path. Output: none. Write a valid source candidate file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["alpha_id", "expression_hash"])
        writer.writeheader()
        writer.writerow({"alpha_id": "a1", "expression_hash": "h1"})


def write_source_metadata(source: Path) -> None:
    """Input: source run directory. Output: none. Write metadata matching the default workflow fixture."""
    source.mkdir(parents=True, exist_ok=True)
    (source / "run_meta.jsonl").write_text(
        json.dumps(
            {
                "data_fields_path": (
                    "/data-fields?instrumentType=EQUITY&region=USA&delay=1&universe=TOP3000"
                    "&dataset.id=fundamental3&search=cash_field"
                ),
                "field_search": "cash_field",
                "exact_field_id": "cash_field",
                "dataset_id": "fundamental3",
                "workflow_stage": "scout",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def write_start_artifacts(root: Path) -> None:
    """Input: temporary root. Output: none. Write offline artifacts required to start a strict workflow."""
    knowledge = root / "knowledge"
    decisions = knowledge / "wiki" / "70_decisions"
    decisions.mkdir(parents=True)
    option = {
        "option_id": "option-1",
        "title": "Power Pool",
        "primary_incentive": "power_pool",
        "secondary_incentives": [],
        "why_now": "Fresh measured coverage is available.",
        "candidate_scope": "USA D1 TOP3000",
        "expected_asset_value": "A measured research direction.",
        "correlation_risk": "low",
        "resource_cost": "small",
        "evidence": [{"source_type": "ledger", "path": "machine/data_ledger.jsonl", "title": "Ledger", "timestamp": "2026-08-12"}],
        "failure_modes": [],
        "decision_needed": "Start the selected scope.",
        "score": {"total": 1.0, "components": {}, "penalties": {}, "reasons": ["measured coverage"]},
    }
    (decisions / "research_option_cards.jsonl").write_text(json.dumps(option) + "\n", encoding="utf-8")
    fresh_date = date.today().isoformat()
    source_path = f"raw/platform/data_fields/{fresh_date}/data_fields.jsonl"
    machine = knowledge / "machine"
    machine.mkdir(parents=True, exist_ok=True)
    ledger = {
        "dataset_id": "fundamental3", "dataset_name": "Fundamentals", "field_id": "cash_field", "field_type": "MATRIX",
        "region": "USA", "delay": 1, "universe": "TOP3000", "semantic_tags": ["cash", "power_pool"], "coverage": 1.0,
        "alpha_count": 0, "user_count": 0, "simulation_usage_count": 0, "submitted_usage_count": 0, "last_used_at": "",
        "best_result_label": "unexplored", "correlation_risk": "low", "source_paths": [source_path], "source_quality": "platform_raw_capture",
        "coverage_status": "measured_raw", "source_updated_at": fresh_date,
        "available_scopes": [{"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}],
        "compatible_template_ids": ["matrix_ts_zscore_rank"],
    }
    (machine / "data_ledger.jsonl").write_text(json.dumps(ledger) + "\n", encoding="utf-8")
    capture = knowledge / "raw" / "platform" / "data_fields" / fresh_date
    capture.mkdir(parents=True)
    scope = {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}
    (capture / "data_fields.jsonl").write_text(json.dumps({"scope": scope, "data_set": {"id": "fundamental3"}, "field": {"id": "cash_field"}}) + "\n", encoding="utf-8")
    (capture / "scopes.jsonl").write_text(json.dumps({"scope": scope, "status": "completed", "certification_status": "complete"}) + "\n", encoding="utf-8")
    (capture / "manifest.json").write_text(json.dumps({"generated_at": f"{fresh_date}T00:00:00Z", "certification_status": "complete", "requested_matrix": [scope]}), encoding="utf-8")
    template = {
        "template_id": "matrix_ts_zscore_rank", "hypothesis": "Rank a z-scored matrix field.", "skeleton": "rank(ts_zscore({field}, 20))",
        "required_field_types": ["MATRIX"], "compatible_semantic_tags": ["cash", "power_pool"], "operator_tags": ["rank", "ts_zscore"],
        "status": "discovery_ready", "correlation_risk": "low", "repair_levers": [], "source_paths": [],
        "compatible_regions": ["USA"], "compatible_delays": [1], "compatible_universes": ["TOP3000"],
    }
    (machine / "template_library.jsonl").write_text(json.dumps(template) + "\n", encoding="utf-8")
    rule = {"rule_id": "near_miss", "issue_types": ["pnl_signal"], "description": "Promote stable PnL.", "promotion_condition": "Stable PnL is observed.", "action": "Send to repair.", "evidence_paths": ["raw/research/near_misses/example.md"], "consumed_by": ["triage", "repair_loop", "candidate_gate"], "risk": "May promote a fragile signal."}
    (machine / "benchmark_rules.jsonl").write_text(json.dumps(rule) + "\n", encoding="utf-8")
    activity = knowledge / "wiki" / "10_foundations" / "activity_snapshot.md"
    activity.parent.mkdir(parents=True)
    activity.write_text("# Activity Snapshot\n", encoding="utf-8")
    (machine / "freshness_manifest.json").write_text(json.dumps([
        {"name": "data_ledger", "path": "machine/data_ledger.jsonl", "updated_at": fresh_date, "max_age_days": 7},
        {"name": "template_library", "path": "machine/template_library.jsonl", "updated_at": fresh_date, "max_age_days": 7},
        {"name": "benchmark_rules", "path": "machine/benchmark_rules.jsonl", "updated_at": fresh_date, "max_age_days": 7},
        {"name": "activity_snapshot", "path": "wiki/10_foundations/activity_snapshot.md", "updated_at": fresh_date, "max_age_days": 7},
    ]), encoding="utf-8")


class WorkflowAutoContinueTests(unittest.TestCase):
    def test_auto_continue_stops_at_user_approval_without_calling_runners(self):
        status = {
            "active": True,
            "status": "waiting_for_user",
            "waiting_for_user": True,
            "current_stage": "user_approval",
            "next_action": "user-approval",
            "run_dir": "runs/active",
        }
        orchestrator = Mock()
        orchestrator.status.return_value = status
        source_runner = Mock(side_effect=AssertionError("source runner must not run"))
        in_flight_runner = Mock(side_effect=AssertionError("in-flight runner must not run"))
        retry_runner = Mock(side_effect=AssertionError("retry runner must not run"))

        with patch("wqb.workflow_auto_continue.WorkflowOrchestrator", return_value=orchestrator):
            result = auto_continue_workflow(
                Mock(),
                {},
                "2026-08-16T00:00:00+00:00",
                enable_live_api=True,
                source_batch_runner=source_runner,
                complete_in_flight_runner=in_flight_runner,
                retry_planned_runner=retry_runner,
            )

        self.assertEqual(result["status"], "waiting_for_user")
        self.assertEqual(result["current_stage"], "user_approval")
        self.assertEqual(result["next_action"], "user-approval")
        self.assertEqual(result["message"], "User approval is required before automatic progress.")
        self.assertNotIn("submit", str(result).lower())
        orchestrator.resume.assert_not_called()
        orchestrator.continue_once.assert_not_called()
        orchestrator.import_scout_seed_bridge_decision.assert_not_called()
        source_runner.assert_not_called()
        in_flight_runner.assert_not_called()
        retry_runner.assert_not_called()

    def test_auto_continue_refuses_without_active_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = default_orchestrator_paths({"run_root": str(Path(tmp) / "runs"), "knowledge_root": str(Path(tmp) / "knowledge")})

            result = auto_continue_workflow(paths, {}, "2026-08-12T00:00:00+00:00")

        self.assertEqual(result["status"], "none")
        self.assertEqual(result["next_action"], "workflow-start")

    def test_auto_continue_does_not_complete_in_flight_without_live_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source1"
            source.mkdir()
            orchestrator = Mock()
            orchestrator.status.return_value = {
                "active": True,
                "status": "paused",
                "current_stage": "scout_seed",
                "pause_reason": "missing candidates.csv",
                "run_dir": str(Path(tmp) / "active"),
            }
            runner = Mock(side_effect=AssertionError("live recovery must not run"))
            decision = SourceBridgeDecision(
                "complete_in_flight", "submitted simulation needs recovery", "source1", str(source)
            )
            with patch("wqb.workflow_auto_continue.WorkflowOrchestrator", return_value=orchestrator), patch(
                "wqb.workflow_auto_continue.inspect_scout_seed_source_bridge", return_value=decision
            ):
                result = auto_continue_workflow(
                    Mock(),
                    {},
                    "2026-08-16T00:00:00+00:00",
                    enable_live_api=False,
                    complete_in_flight_runner=runner,
                )

        runner.assert_not_called()
        self.assertEqual(result["next_action"], "enable-live-api-required")
        self.assertIn("authorization", result["message"].lower())

    def test_auto_continue_does_not_retry_planned_without_live_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source1"
            source.mkdir()
            orchestrator = Mock()
            orchestrator.status.return_value = {
                "active": True,
                "status": "paused",
                "current_stage": "scout_seed",
                "pause_reason": "missing candidates.csv",
                "run_dir": str(Path(tmp) / "active"),
            }
            runner = Mock(side_effect=AssertionError("live recovery must not run"))
            decision = SourceBridgeDecision(
                "retry_planned", "planned source candidates remain", "source1", str(source)
            )
            with patch("wqb.workflow_auto_continue.WorkflowOrchestrator", return_value=orchestrator), patch(
                "wqb.workflow_auto_continue.inspect_scout_seed_source_bridge", return_value=decision
            ):
                result = auto_continue_workflow(
                    Mock(),
                    {},
                    "2026-08-16T00:00:00+00:00",
                    enable_live_api=False,
                    retry_planned_runner=runner,
                )

        runner.assert_not_called()
        self.assertEqual(result["next_action"], "enable-live-api-required")
        self.assertIn("authorization", result["message"].lower())

    def test_auto_continue_imports_valid_source_candidates_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_start_artifacts(root)
            paths = default_orchestrator_paths({"run_root": str(root / "runs"), "knowledge_root": str(root / "knowledge")})
            orchestrator = WorkflowOrchestrator(paths)
            orchestrator.start("Power Pool", "option-1", "2026-08-12T00:00:00+00:00")
            orchestrator.continue_once("2026-08-12T00:01:00+00:00")
            orchestrator.continue_once("2026-08-12T00:02:00+00:00")
            source = paths.run_root / "source1"
            write_source_metadata(source)
            write_candidate_file(source / "candidates.csv")
            orchestrator.continue_once("2026-08-12T00:03:00+00:00")

            result = auto_continue_workflow(paths, {}, "2026-08-12T00:04:00+00:00")
            second = auto_continue_workflow(paths, {}, "2026-08-12T00:05:00+00:00")
            imported_candidate_exists = (Path(result["run_dir"]) / "candidates.csv").exists()

        self.assertEqual(result["source_bridge"]["action"], "import_existing")
        self.assertIn(second["status"], {"running", "paused"})
        self.assertTrue(imported_candidate_exists)

    def test_auto_continue_reports_rate_limit_wait_without_live_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_start_artifacts(root)
            paths = default_orchestrator_paths({"run_root": str(root / "runs"), "knowledge_root": str(root / "knowledge")})
            orchestrator = WorkflowOrchestrator(paths)
            orchestrator.start("Power Pool", "option-1", "2026-08-12T00:00:00+00:00")
            orchestrator.continue_once("2026-08-12T00:01:00+00:00")
            orchestrator.continue_once("2026-08-12T00:02:00+00:00")
            source = paths.run_root / "source1"
            write_source_metadata(source)
            (source / "rate_limit_state.json").write_text('{"status":"cooldown","retry_at":"2099-01-01T00:00:00+00:00"}', encoding="utf-8")
            orchestrator.continue_once("2026-08-12T00:03:00+00:00")

            result = auto_continue_workflow(paths, {}, "2026-08-12T00:04:00+00:00")

        self.assertEqual(result["next_action"], "rate-limit-wait")
        self.assertEqual(result["source_bridge"]["action"], "rate_limit_wait")

    def test_auto_continue_exposes_maintenance_blocker_at_rate_limit_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_start_artifacts(root)
            paths = default_orchestrator_paths(
                {"run_root": str(root / "runs"), "knowledge_root": str(root / "knowledge")}
            )
            orchestrator = WorkflowOrchestrator(paths)
            orchestrator.start("Power Pool", "option-1", "2026-08-12T00:00:00+00:00")
            orchestrator.continue_once("2026-08-12T00:01:00+00:00")
            orchestrator.continue_once("2026-08-12T00:02:00+00:00")
            source = paths.run_root / "source1"
            write_source_metadata(source)
            (source / "rate_limit_state.json").write_text(
                json.dumps(
                    {
                        "status": "cooldown",
                        "retry_at": "2099-01-01T00:00:00+00:00",
                        "consecutive_429_count": 3,
                    }
                ),
                encoding="utf-8",
            )
            orchestrator.continue_once("2026-08-12T00:03:00+00:00")

            result = auto_continue_workflow(paths, {}, "2026-08-12T00:04:00+00:00")

        self.assertEqual(result["next_action"], "maintenance-blocker")
        self.assertEqual(result["source_bridge"]["action"], "maintenance_blocker")
        self.assertIn("rate limit", result["source_bridge"]["reason"])

    def test_auto_continue_starts_bounded_source_batch_when_live_enabled(self):
        calls = []

        def source_batch_runner(config, metadata):
            calls.append((dict(config), dict(metadata)))
            return {"status": "source_batch_completed", "run_dir": "runs/source1"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_start_artifacts(root)
            paths = default_orchestrator_paths({"run_root": str(root / "runs"), "knowledge_root": str(root / "knowledge")})
            orchestrator = WorkflowOrchestrator(paths)
            orchestrator.start("Power Pool", "option-1", "2026-08-12T00:00:00+00:00")
            orchestrator.continue_once("2026-08-12T00:01:00+00:00")
            orchestrator.continue_once("2026-08-12T00:02:00+00:00")
            schedule = next(paths.run_root.glob("*/stages/schedule/research_schedule.json"))
            schedule.write_text(
                '{"template_matches":[{"field_id":"buzz_intensity_score_15","dataset_id":"analyst_buzz","template_id":"vector_event_count_surprise"}]}',
                encoding="utf-8",
            )
            orchestrator.continue_once("2026-08-12T00:03:00+00:00")

            result = auto_continue_workflow(
                paths,
                {"max_alphas_per_round": 2},
                "2026-08-12T00:04:00+00:00",
                enable_live_api=True,
                source_batch_runner=source_batch_runner,
            )

        self.assertEqual(result["next_action"], "workflow-auto-continue")
        self.assertEqual(result["source_bridge"]["action"], "start_source_batch")
        self.assertEqual(calls[0][0]["max_alphas_per_round"], 30)
        self.assertEqual(calls[0][0]["region"], "USA")
        self.assertEqual(calls[0][0]["delay"], 1)
        self.assertEqual(calls[0][0]["universe"], "TOP3000")
        self.assertEqual(calls[0][1]["field_search"], "buzz_intensity_score_15")


if __name__ == "__main__":
    unittest.main()
