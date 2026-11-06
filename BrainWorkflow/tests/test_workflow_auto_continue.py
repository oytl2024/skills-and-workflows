import csv
import json
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from wqb.cli import default_orchestrator_paths
from wqb.orchestrator import WorkflowOrchestrator
from wqb.source_bridge import SourceBridgeDecision
from wqb.workflow_auto_continue import auto_continue_workflow


def fixed_test_root(name: str) -> Path:
    """Input: root name string. Output: Path. Create a writable non-tempfile test root under the test directory."""
    root = Path.cwd() / "tests" / f"_tmp_{name}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def remove_fixed_test_root(root: Path) -> None:
    """Input: test root path. Output: none. Remove a fixed test root created under the test directory."""
    if root.exists():
        shutil.rmtree(root)


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
    def test_failed_source_readiness_stops_instead_of_requesting_another_batch(self):
        """Input: source runner readiness failure. Output: assertions. Propagate the source gate before another simulation attempt."""
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            report = source / "readiness_report.json"
            report.write_text(json.dumps({"passed": False, "blocked": True, "issues": [
                {"level": "block", "code": "stale_scope_data", "message": "scope is stale"}]}))
            active = root / "active"
            active.mkdir()
            status = dict(active=True, status="paused", current_stage="scout_seed", run_dir=str(active),
                          pause_reason="checked research results required")
            engine = Mock()
            engine.status.return_value = status
            decision = SourceBridgeDecision("start_source_batch", "new batch", metadata={
                "local_construction_ready": True, "allow_live_fallback": False})
            runner = Mock(return_value=dict(status="readiness_blocked", run_dir=str(source),
                                            readiness_json_path=str(report)))
            with patch("wqb.workflow_auto_continue.WorkflowOrchestrator", return_value=engine), \
                 patch("wqb.workflow_auto_continue.inspect_scout_seed_source_bridge", return_value=decision), \
                 patch("wqb.workflow_auto_continue._readiness_blocker_for_status", return_value=None):
                result = auto_continue_workflow(SimpleNamespace(run_root=root), {}, "2026-10-21T00:00:00Z", True, source_batch_runner=runner)
            self.assertEqual(result["next_action"], "readiness-blocked")
            self.assertEqual(result["readiness_blocker"]["codes"], ["stale_scope_data"])
            self.assertEqual(runner.call_count, 1)
            from wqb.runtime_control import request_runtime_state, read_runtime_control
            from wqb.workflow_driver import run_workflow_driver
            request_runtime_state(active, "running", max_simulations=7, max_runtime_seconds=60)
            step = Mock(return_value=result)
            driven = run_workflow_driver(SimpleNamespace(), {"runtime_max_steps": 3}, step=step,
                                         status_reader=lambda: status)
            self.assertEqual(step.call_count, 1)
            self.assertEqual(driven["runtime_reason"], "readiness-blocked")
            self.assertEqual(read_runtime_control(active)["max_simulations"], 7)

    def test_source_readiness_failure_without_report_is_maintenance_not_retry(self):
        """Input: malformed source failure. Output: assertions. Missing error evidence cannot restart the source loop."""
        from wqb.workflow_auto_continue import _source_recovery_result
        result = _source_recovery_result({}, {}, {"status": "readiness_blocked"})
        self.assertEqual(result["next_action"], "maintenance-blocker")

    def test_created_workflow_advances_without_manual_continue(self):
        with patch('wqb.workflow_auto_continue.WorkflowOrchestrator') as factory, \
             patch('wqb.workflow_auto_continue._readiness_blocker_for_status', return_value=None):
            engine = factory.return_value
            engine.status.return_value = {'active': True, 'status': 'created', 'current_stage': 'objective_selected'}
            engine.continue_once.return_value = {'status': 'running'}
            result = auto_continue_workflow(Mock(), {}, '2026-09-23T00:00:00Z')
        self.assertEqual(result, {'status': 'running'})
        engine.continue_once.assert_called_once()

    def test_candidate_gate_automatically_requests_but_never_grants_approval(self):
        with patch('wqb.workflow_auto_continue.WorkflowOrchestrator') as factory, \
             patch('wqb.workflow_auto_continue._readiness_blocker_for_status', return_value=None):
            engine = factory.return_value
            engine.status.return_value = {'active': True, 'status': 'paused', 'current_stage': 'candidate_gate'}
            engine.request_candidate_approval_from_checked_results.return_value = {'status': 'waiting_for_user'}
            result = auto_continue_workflow(Mock(), {}, '2026-09-23T00:00:00Z')
        self.assertEqual(result['status'], 'waiting_for_user')
        engine.request_candidate_approval_from_checked_results.assert_called_once()

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

    def test_auto_continue_readiness_blocker_stops_old_live_retry_post(self):
        orchestrator = Mock()
        orchestrator.status.return_value = {
            "active": True,
            "status": "paused",
            "current_stage": "scout_seed",
            "pause_reason": "missing candidates.csv",
            "run_dir": "runs/active",
        }
        decision = SourceBridgeDecision(
            "retry_planned",
            "planned source candidates remain",
            "source1",
            "runs/source1",
            ["runs/source1/planned_candidates.jsonl"],
        )
        blocker = {
            "blocked": True,
            "passed": False,
            "codes": ["stale_scope_data"],
            "path": "runs/source1/readiness_report.json",
            "issues": [
                {
                    "level": "block",
                    "code": "stale_scope_data",
                    "message": "Compatible data ledger records for USA D1 TOP3000 are stale.",
                    "action": "Refresh platform raw data fields for this exact scope before research.",
                }
            ],
        }
        runner = Mock(side_effect=AssertionError("readiness blocker must stop live retry before runner"))
        with patch("wqb.workflow_auto_continue.WorkflowOrchestrator", return_value=orchestrator), patch(
            "wqb.workflow_auto_continue.inspect_scout_seed_source_bridge",
            return_value=decision,
        ), patch(
            "wqb.workflow_auto_continue._readiness_blocker_for_status",
            return_value=blocker,
        ):
            result = auto_continue_workflow(
                Mock(),
                {},
                "2026-09-02T06:15:00+00:00",
                enable_live_api=True,
                retry_planned_runner=runner,
            )

        runner.assert_not_called()
        self.assertEqual(result["next_action"], "readiness-blocked")
        self.assertEqual(result["readiness_blocker"]["codes"], ["stale_scope_data"])
        self.assertIn("Readiness is blocked", result["message"])

    def test_status_readiness_blocker_uses_bound_source_report_not_unrelated_newer_report(self):
        from wqb.workflow_auto_continue import decorate_workflow_status_with_source_bridge

        root = fixed_test_root("workflow_auto_continue_bound_readiness")
        try:
            runs = root / "runs"
            active = runs / "active"
            bound = runs / "bound-source"
            unrelated = runs / "unrelated-newer"
            bound.mkdir(parents=True)
            unrelated.mkdir(parents=True)
            (bound / "readiness_report.json").write_text(
                json.dumps({"passed": True, "blocked": False, "issues": []}),
                encoding="utf-8",
            )
            (unrelated / "readiness_report.json").write_text(
                json.dumps(
                    {
                        "passed": False,
                        "blocked": True,
                        "issues": [
                            {
                                "level": "block",
                                "code": "stale_scope_data",
                                "message": "Unrelated scope is stale.",
                                "action": "Refresh an unrelated scope.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            os.utime(bound / "readiness_report.json", (1000, 1000))
            os.utime(unrelated / "readiness_report.json", (2000, 2000))
            paths = default_orchestrator_paths({"run_root": str(runs), "knowledge_root": str(root / "knowledge")})
            status = {
                "active": True,
                "status": "paused",
                "current_stage": "scout_seed",
                "pause_reason": "missing candidates.csv",
                "run_dir": str(active),
            }
            decision = SourceBridgeDecision(
                "retry_planned",
                "planned source candidates remain",
                "bound-source",
                str(bound),
                [str(bound / "planned_candidates.jsonl")],
            )
            with patch("wqb.workflow_auto_continue.inspect_scout_seed_source_bridge", return_value=decision):
                result = decorate_workflow_status_with_source_bridge(paths, status, "2026-09-02T06:40:00+00:00")
        finally:
            remove_fixed_test_root(root)

        self.assertEqual(result["next_action"], "workflow-auto-continue")
        self.assertNotIn("readiness_blocker", result)
        self.assertEqual(result["source_bridge"]["source_run_id"], "bound-source")

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
        self.assertIn("next_check_at", result["source_bridge"]["metadata"])

    def test_auto_continue_blocks_start_source_batch_without_local_construction_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            active = Path(tmp) / "active"
            active.mkdir()
            orchestrator = Mock()
            orchestrator.status.return_value = {
                "active": True,
                "status": "paused",
                "current_stage": "scout_seed",
                "pause_reason": "missing candidates.csv",
                "run_dir": str(active),
            }
            runner = Mock(side_effect=AssertionError("source batch must not run without local provenance"))
            decision = SourceBridgeDecision(
                "start_source_batch",
                "no recoverable source run exists",
                "",
                "",
                [str(active / "stages" / "schedule" / "research_schedule.json")],
                {"field_search": "buzz_field", "dataset_id": "ai_equity_alpha"},
            )
            with patch("wqb.workflow_auto_continue.WorkflowOrchestrator", return_value=orchestrator), patch(
                "wqb.workflow_auto_continue.inspect_scout_seed_source_bridge", return_value=decision
            ):
                result = auto_continue_workflow(
                    Mock(),
                    {},
                    "2026-08-16T08:00:00+00:00",
                    enable_live_api=True,
                    source_batch_runner=runner,
                )

        runner.assert_not_called()
        self.assertEqual(result["next_action"], "maintenance-blocker")
        self.assertEqual(result["source_bridge"]["action"], "maintenance_blocker")
        self.assertIn("local construction provenance", result["source_bridge"]["reason"])

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
                json.dumps(
                    {
                        "selected_data": [
                            {
                                "field_id": "buzz_intensity_score_15",
                                "dataset_id": "analyst_buzz",
                                "source_quality": "platform_raw_capture",
                                "coverage_status": "measured_raw",
                                "source_paths": ["raw/platform/data_fields/2026-08-12/data_fields.jsonl"],
                                "source_updated_at": "2026-08-12",
                            }
                        ],
                        "template_matches": [
                            {
                                "field_id": "buzz_intensity_score_15",
                                "dataset_id": "analyst_buzz",
                                "template_id": "vector_event_count_surprise",
                                "skeleton": "rank(ts_delta(vec_count({field}), 1))",
                            }
                        ],
                    }
                ),
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
