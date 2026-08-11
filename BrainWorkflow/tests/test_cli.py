import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from argparse import Namespace
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import requests

from wqb.expression import expression_hash
from wqb.knowledge_contracts import SourceIndexRow, update_source_index
from wqb.principle_model import OptionCard, ScoreBreakdown, SourceEvidence
from wqb.cli import (
    authenticate_for_run,
    benchmark_fields_for_record,
    cache_metadata,
    config_overrides_from_args,
    complete_in_flight_simulations,
    dry_run,
    default_knowledge_root,
    default_option_output_dir,
    format_parallel_stage_plan,
    inspect_existing_alpha,
    is_http_status_error,
    list_fields_summary,
    load_novelty_reference_records,
    main,
    parse_operator_replacements,
    parse_blend_weights,
    parse_args,
    parse_setting_variations,
    parse_setting_overrides,
    run_field_batch,
    retry_planned_candidates,
    refresh_existing_alpha,
    refresh_existing_alpha_batch,
    simulation_identity_hash,
    submit_candidate_payloads,
    blend_repair_expression,
    repair_existing_alpha_with_field,
    run_expression_file,
    run_expression_file_batch,
    scan_existing,
    scan_existing_alpha_candidates,
    semantic_preview,
    summarize_run_dir,
)
from wqb.config import load_config
from wqb.recorder import RunRecorder
from wqb.simulator import SimulationPollTimeout


TESTS_DIR = Path(__file__).resolve().parent


def make_run_dir() -> Path:
    """Input: none. Output: Path. Create a unique workspace-local CLI test directory."""
    run_dir = TESTS_DIR / f"_tmp_cli_{uuid4().hex}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def cleanup_run_dir(run_dir: Path) -> None:
    """Input: Path. Output: none. Remove only verified workspace-local CLI test directories."""
    resolved = run_dir.resolve()
    if resolved.parent != TESTS_DIR or not resolved.name.startswith("_tmp_cli_"):
        raise RuntimeError(f"refusing to clean unexpected test path: {resolved}")
    shutil.rmtree(resolved)


def write_ready_knowledge_artifacts(root: Path) -> None:
    """Input: knowledge root. Output: none. Create minimal scope-ready knowledge test artifacts."""
    fresh_date = date.today().isoformat()
    (root / "machine").mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "10_foundations").mkdir(parents=True, exist_ok=True)
    scope = {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}
    capture = root / "raw" / "platform" / "data_fields" / fresh_date
    capture.mkdir(parents=True, exist_ok=True)
    (capture / "data_fields.jsonl").write_text(
        json.dumps({"scope": scope, "data_set": {"id": "news12"}, "field": {"id": "news_field"}}) + "\n",
        encoding="utf-8",
    )
    (capture / "scopes.jsonl").write_text(
        json.dumps({"scope": scope, "status": "completed", "certification_status": "complete"}) + "\n",
        encoding="utf-8",
    )
    (capture / "manifest.json").write_text(
        json.dumps({"generated_at": f"{fresh_date}T00:00:00Z", "certification_status": "complete", "requested_matrix": [scope]}),
        encoding="utf-8",
    )
    (root / "machine" / "data_ledger.jsonl").write_text(
        json.dumps(
            {
                "dataset_id": "news12",
                "dataset_name": "News",
                "field_id": "news_field",
                "field_type": "MATRIX",
                "region": "USA",
                "delay": 1,
                "universe": "TOP3000",
                "semantic_tags": ["power_pool"],
                "coverage": 0.8,
                "alpha_count": 0,
                "user_count": 0,
                "simulation_usage_count": 0,
                "submitted_usage_count": 0,
                "last_used_at": "",
                "best_result_label": "unexplored",
                "correlation_risk": "low",
                "source_paths": [f"raw/platform/data_fields/{fresh_date}/data_fields.jsonl"],
                "source_quality": "platform_raw_capture",
                "coverage_status": "measured_raw",
                "source_updated_at": fresh_date,
                "available_regions": ["USA"],
                "available_delays": [1],
                "available_universes": ["TOP3000"],
                "available_scopes": [scope],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "machine" / "template_library.jsonl").write_text(
        json.dumps(
            {
                "template_id": "matrix_rank",
                "hypothesis": "Rank the field.",
                "skeleton": "rank({field})",
                "required_field_types": ["MATRIX"],
                "compatible_semantic_tags": ["power_pool"],
                "operator_tags": [],
                "status": "seed",
                "correlation_risk": "low",
                "repair_levers": [],
                "source_paths": [],
                "compatible_regions": ["USA"],
                "compatible_delays": [1],
                "compatible_universes": ["TOP3000"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "machine" / "benchmark_rules.jsonl").write_text(
        json.dumps(
            {
                "rule_id": "near_miss",
                "issue_types": ["pnl_signal"],
                "description": "Promote stable PnL.",
                "promotion_condition": "Stable PnL is observed.",
                "action": "Send to repair.",
                "evidence_paths": ["raw/research/near_misses/example.md"],
                "consumed_by": ["triage", "repair_loop", "candidate_gate"],
                "risk": "May promote a fragile signal.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "wiki" / "10_foundations" / "activity_snapshot.md").write_text("# Activity Snapshot\n", encoding="utf-8")
    (root / "machine" / "freshness_manifest.json").write_text(
        json.dumps(
            [
                {"name": "data_ledger", "path": "machine/data_ledger.jsonl", "updated_at": fresh_date, "max_age_days": 7},
                {"name": "template_library", "path": "machine/template_library.jsonl", "updated_at": fresh_date, "max_age_days": 7},
                {"name": "benchmark_rules", "path": "machine/benchmark_rules.jsonl", "updated_at": fresh_date, "max_age_days": 7},
                {"name": "activity_snapshot", "path": "wiki/10_foundations/activity_snapshot.md", "updated_at": fresh_date, "max_age_days": 7},
            ]
        ),
        encoding="utf-8",
    )


class CliTests(unittest.TestCase):
    def test_benchmark_fields_use_persisted_rulebook(self):
        from wqb.benchmark_rules import BenchmarkRule, write_benchmark_rules_jsonl

        record = {
            "hard_pass": False,
            "metrics": {"sharpe": 0.7, "fitness": 0.1, "returns": 0.1, "turnover": 0.2},
            "failed": ["LOW_SHARPE"],
            "pending": [],
            "signal_note": "stable pnl",
        }
        promotion = BenchmarkRule(
            rule_id="cli_persisted_promotion",
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
            write_benchmark_rules_jsonl(path, [])
            before = benchmark_fields_for_record(
                record,
                knowledge_root=root,
                consumer="candidate_gate",
            )

            write_benchmark_rules_jsonl(path, [promotion])
            after = benchmark_fields_for_record(
                record,
                knowledge_root=root,
                consumer="candidate_gate",
            )

        self.assertEqual(before["benchmark_label"], "weak_discard")
        self.assertEqual(after["benchmark_label"], "repairable_signal")

    def test_benchmark_fields_ignore_rule_for_unrelated_consumer(self):
        from wqb.benchmark_rules import BenchmarkRule

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
            description="Draft a workflow proposal.",
            promotion_condition="Stable PnL is observed.",
            action="Create a proposal.",
            evidence_paths=[],
            consumed_by=["workflow_proposals"],
            risk="May create noisy proposals.",
        )

        fields = benchmark_fields_for_record(
            record,
            benchmark_rules=[proposal_rule],
            consumer="triage",
        )

        self.assertEqual(fields["benchmark_label"], "weak_discard")

    def test_launch_workflow_writes_manifest_readiness_and_handoffs(self):
        from wqb.cli import launch_workflow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = root / "workflow_defaults.json"
            defaults.write_text(
                json.dumps(
                    {
                        "knowledge_root": str(root / "knowledge"),
                        "run_root": str(root / "runs"),
                        "objective": "Power Pool",
                        "region": "USA",
                        "delay": 1,
                        "mode": "plan-only",
                    }
                ),
                encoding="utf-8",
            )

            result = launch_workflow(defaults, None, overrides={}, write_handoffs=True, today_value="2026-07-10")

            self.assertTrue(Path(result["manifest_path"]).exists())
            self.assertTrue(Path(result["readiness_json_path"]).exists())
            self.assertGreaterEqual(len(result["handoffs"]), 1)
            self.assertEqual(result["mode"], "plan-only")

    def test_launch_workflow_blocks_research_before_manifest_and_handoffs(self):
        from wqb.cli import launch_workflow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = root / "workflow_defaults.json"
            defaults.write_text(
                json.dumps(
                    {
                        "knowledge_root": str(root / "missing_knowledge"),
                        "run_root": str(root / "runs"),
                        "objective": "Power Pool",
                        "region": "USA",
                        "delay": 1,
                        "mode": "research",
                        "batch_size": 30,
                        "live_api_enabled": True,
                    }
                ),
                encoding="utf-8",
            )

            result = launch_workflow(defaults, None, overrides={}, write_handoffs=True, today_value="2026-07-10")

            self.assertTrue(result["readiness_blocked"])
            self.assertEqual(result["manifest_path"], "")
            self.assertEqual(result["handoffs"], [])
            self.assertTrue(Path(result["readiness_markdown_path"]).exists())
            self.assertEqual(list((root / "runs").glob("*/run_manifest.json")), [])

    def test_launch_workflow_submit_policy_ask_does_not_confirm_submit_candidate(self):
        from wqb.cli import launch_workflow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            write_ready_knowledge_artifacts(knowledge)
            defaults = root / "workflow_defaults.json"
            defaults.write_text(
                json.dumps(
                    {
                        "knowledge_root": str(knowledge),
                        "run_root": str(root / "runs"),
                        "objective": "Power Pool",
                        "region": "USA",
                        "delay": 1,
                        "mode": "submit-candidate",
                        "submit_policy": "ask",
                    }
                ),
                encoding="utf-8",
            )

            blocked = launch_workflow(defaults, None, overrides={}, write_handoffs=True, today_value="2026-07-10")
            confirmed = launch_workflow(defaults, None, overrides={}, write_handoffs=False, submit_confirmed=True, today_value="2026-07-10")

            self.assertTrue(blocked["readiness_blocked"])
            self.assertEqual(blocked["manifest_path"], "")
            self.assertFalse(confirmed["readiness_blocked"])
            self.assertTrue(Path(confirmed["manifest_path"]).exists())

    def test_launch_workflow_main_dispatches_without_simulation(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "launch-workflow"]), patch(
            "wqb.cli.launch_workflow",
            return_value={"run_id": "run1", "mode": "plan-only", "manifest_path": "run_manifest.json", "readiness_json_path": "readiness_report.json", "readiness_markdown_path": "readiness_report.md", "handoffs": []},
        ) as launcher, redirect_stdout(output):
            main()

        launcher.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["run_id"], "run1")

    def test_launch_workflow_main_preserves_local_config_when_flags_omitted(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "launch-workflow", "--workflow-local", "workflow.local.json"]), patch(
            "wqb.cli.launch_workflow",
            return_value={"run_id": "run1", "mode": "plan-only"},
        ) as launcher, redirect_stdout(output):
            main()

        overrides = launcher.call_args.kwargs["overrides"]
        self.assertNotIn("knowledge_root", overrides)
        self.assertNotIn("batch_size", overrides)
        self.assertNotIn("live_api_enabled", overrides)
        self.assertEqual(json.loads(output.getvalue())["run_id"], "run1")

    def test_launch_workflow_main_passes_only_provided_cli_overrides(self):
        output = io.StringIO()
        with patch(
            "sys.argv",
            [
                "wqb",
                "launch-workflow",
                "--knowledge-root",
                "custom_knowledge",
                "--batch-size",
                "44",
                "--enable-live-api",
                "--confirm-submit",
            ],
        ), patch(
            "wqb.cli.launch_workflow",
            return_value={"run_id": "run1", "mode": "research"},
        ) as launcher, redirect_stdout(output):
            main()

        overrides = launcher.call_args.kwargs["overrides"]
        self.assertEqual(overrides["knowledge_root"], "custom_knowledge")
        self.assertEqual(overrides["batch_size"], 44)
        self.assertTrue(overrides["live_api_enabled"])
        self.assertTrue(launcher.call_args.kwargs["submit_confirmed"])

    def test_launch_workflow_main_does_not_load_stage1_config(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "launch-workflow"]), patch(
            "wqb.cli.load_config", side_effect=AssertionError("Stage 1 config must not load")
        ) as config_loader, patch(
            "wqb.cli.launch_workflow",
            return_value={"run_id": "run1", "mode": "plan-only"},
        ) as launcher, redirect_stdout(output):
            main()

        config_loader.assert_not_called()
        launcher.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["run_id"], "run1")

    def test_readiness_check_function_writes_reports(self):
        from wqb.cli import readiness_check
        from wqb.run_readiness import ReadinessReport

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "runs" / "run1"
            fake_report = ReadinessReport(mode="plan-only", generated_at="2026-07-10T00:00:00Z", passed=True, blocked=False, issues=[])
            with patch("wqb.cli.evaluate_run_readiness", return_value=fake_report), patch("wqb.cli.write_readiness_reports", return_value=(output_dir / "readiness_report.json", output_dir / "readiness_report.md")) as writer:
                result = readiness_check(root, output_dir, "plan-only", 30, False, False, today_value="2026-07-10")

        writer.assert_called_once()
        self.assertTrue(result["passed"])
        self.assertEqual(result["mode"], "plan-only")

    def test_parse_args_accepts_readiness_check(self):
        with patch("sys.argv", ["wqb", "readiness-check", "--readiness-mode", "research", "--batch-size", "30", "--enable-live-api"]):
            args = parse_args()

        self.assertEqual(args.command, "readiness-check")
        self.assertEqual(args.readiness_mode, "research")
        self.assertTrue(args.enable_live_api)

    def test_compile_knowledge_dispatches_maintenance_pipeline(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "compile-knowledge", "--knowledge-root", "knowledge", "--apply-cleanup", "--max-case-reports", "7"]), patch(
            "wqb.cli.run_knowledge_maintenance",
            return_value={"status": "completed", "report_path": "knowledge/raw/maintenance/compile_reports/2026-07-30.json"},
        ) as maintenance, redirect_stdout(output):
            main()

        maintenance.assert_called_once_with("knowledge", apply_cleanup=True, max_case_reports=7)
        self.assertEqual(json.loads(output.getvalue())["status"], "completed")

    def test_delivery_gate_dispatches_with_required_roots(self):
        output = io.StringIO()
        with patch(
            "sys.argv",
            ["wqb", "delivery-gate", "--knowledge-root", "knowledge", "--runs-root", "runs", "--console-base-url", "http://127.0.0.1:8765"],
        ), patch(
            "wqb.cli.run_delivery_gate",
            return_value={"status": "passed", "report_path": "knowledge/raw/maintenance/delivery_gates/2026-07-30.json"},
        ) as gate, redirect_stdout(output):
            main()

        gate.assert_called_once_with("knowledge", "runs", console_base_url="http://127.0.0.1:8765")
        self.assertEqual(json.loads(output.getvalue())["status"], "passed")

    def test_delivery_verify_dispatches_local_verification_runner(self):
        output = io.StringIO()
        with patch(
            "sys.argv",
            ["wqb", "delivery-verify", "--knowledge-root", "knowledge"],
        ), patch(
            "wqb.cli.run_delivery_verification",
            return_value={
                "status": "passed",
                "report_path": "knowledge/raw/maintenance/delivery_checks/20260730T000000Z.json",
            },
        ) as verify, redirect_stdout(output):
            main()

        verify.assert_called_once_with("knowledge")
        self.assertEqual(json.loads(output.getvalue())["status"], "passed")

    def test_readiness_check_main_dispatches_without_simulation(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "readiness-check"]), patch(
            "wqb.cli.readiness_check",
            return_value={"mode": "plan-only", "passed": True, "blocked": False, "issue_count": 0, "json_path": "readiness_report.json", "markdown_path": "readiness_report.md"},
        ) as readiness, redirect_stdout(output):
            main()

        readiness.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["json_path"], "readiness_report.json")

    def test_bootstrap_knowledge_command_returns_summary(self):
        from wqb.cli import bootstrap_knowledge_command
        from wqb.knowledge_bootstrap import BootstrapSummary

        fake_summary = BootstrapSummary(
            generated_at="2026-07-10T00:00:00Z",
            knowledge_root="knowledge",
            data_ledger_count=1,
            template_count=1,
            artifact_paths=["knowledge/machine/data_ledger.jsonl"],
            warnings=[],
        )
        with patch("wqb.cli.bootstrap_knowledge", return_value=fake_summary):
            result = bootstrap_knowledge_command("knowledge", "docs/knowledge")

        self.assertEqual(result["data_ledger_count"], 1)
        self.assertEqual(result["template_count"], 1)

    def test_bootstrap_knowledge_main_dispatches_without_simulation(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "bootstrap-knowledge"]), patch(
            "wqb.cli.bootstrap_knowledge_command",
            return_value={"generated_at": "2026-07-10T00:00:00Z", "knowledge_root": "knowledge", "data_ledger_count": 1, "template_count": 1, "artifact_paths": [], "warnings": []},
        ) as bootstrap, redirect_stdout(output):
            main()

        bootstrap.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["data_ledger_count"], 1)

    def test_default_knowledge_root_uses_shared_workspace_vault(self):
        expected = TESTS_DIR.parents[2] / "knowledge"

        self.assertEqual(default_knowledge_root(), expected)
        self.assertEqual(Path(default_option_output_dir()), expected / "machine" / "decisions")

        custom_root = TESTS_DIR / "_custom_knowledge"
        with patch.dict(os.environ, {"BRAIN_KNOWLEDGE_ROOT": str(custom_root)}):
            self.assertEqual(default_knowledge_root(), custom_root)
            self.assertEqual(Path(default_option_output_dir()), custom_root / "machine" / "decisions")

    def test_learn_capture_defaults_to_raw_layer(self):
        from scripts import capture_learn_material

        expected = TESTS_DIR.parents[2] / "knowledge"
        cache_root = TESTS_DIR.parents[0] / "docs" / "knowledge" / "cache" / "learn"

        self.assertEqual(capture_learn_material.KNOWLEDGE_ROOT, expected)
        self.assertEqual(capture_learn_material.RAW_LEARN_ROOT, expected / "raw" / "platform" / "learn")
        self.assertEqual(capture_learn_material.JSON_CACHE_ROOT, cache_root)
        self.assertEqual(
            capture_learn_material.raw_capture_dir("2026-07-09T10:03:26+00:00"),
            expected / "raw" / "platform" / "learn" / "2026-07-09",
        )
        self.assertEqual(
            capture_learn_material.json_cache_dir("2026-07-09T10:03:26+00:00"),
            cache_root / "2026-07-09",
        )
        self.assertEqual(
            capture_learn_material.WIKI_LEARN_PAGE,
            expected / "machine" / "previews" / "learn_material_index.md",
        )
        self.assertEqual(
            capture_learn_material.WIKI_OPERATOR_PAGE,
            expected / "machine" / "previews" / "operator_catalog_official.md",
        )

    def test_config_overrides_from_args_includes_request_hyperparameters(self):
        args = Namespace(
            max_alphas_per_round=30,
            max_rounds=None,
            request_timeout_seconds=20,
            request_max_retries=1,
            request_base_backoff_seconds=2,
        )

        overrides = config_overrides_from_args(args)

        self.assertEqual(overrides["max_alphas_per_round"], 30)
        self.assertEqual(overrides["request_timeout_seconds"], 20)
        self.assertEqual(overrides["max_retries"], 1)
        self.assertEqual(overrides["base_backoff_seconds"], 2)

    def test_plan_research_options_writes_cards_without_simulation(self):
        from wqb.cli import plan_research_options
        from wqb.principle_model import IncentiveSnapshot, SourceEvidence

        snapshot = IncentiveSnapshot(
            generated_at="2026-07-09T00:00:00Z",
            account={"geniusLevel": "GOLD"},
            activities=[],
            competitions=[],
            power_pool_boards=[{"value": "lyvRddy", "label": "USA/D1 Power Pool July'26"}],
            rule_pages={"brain-genius": "signals pyramids", "getting-started-power-pool-alphas": "Power Pool"},
            evidence=[SourceEvidence("api", "/users/self", "User account state", "2026-07-09T00:00:00Z")],
            refresh_errors=[],
        )

        class FakeClient:
            pass

        with tempfile.TemporaryDirectory() as tmp:
            knowledge_root = Path(tmp) / "knowledge"
            write_ready_knowledge_artifacts(knowledge_root)
            machine = knowledge_root / "machine"
            (machine / "operator_ledger.jsonl").write_text(
                json.dumps(
                    {
                        "operator": "rank",
                        "family": "cross_sectional",
                        "workflow_uses": ["discovery"],
                        "compatible_field_types": ["MATRIX"],
                        "template_tags": ["power_pool"],
                        "risk_tags": [],
                        "repair_levers": [],
                        "source_paths": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (machine / "benchmark_rules.jsonl").write_text(
                json.dumps(
                    {
                        "rule_id": "test_rule",
                        "issue_types": ["correlation"],
                        "description": "Test rule.",
                        "promotion_condition": "Test condition.",
                        "action": "Test action.",
                        "evidence_paths": [],
                        "consumed_by": ["research_planner"],
                        "risk": "low",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch("wqb.cli.build_client", return_value=FakeClient()), patch(
                "wqb.cli.refresh_incentive_snapshot", return_value=snapshot
            ):
                result = plan_research_options(
                    {"request_timeout_seconds": 1, "knowledge_root": str(knowledge_root)},
                    max_options=3,
                    output_dir=tmp,
                )

            self.assertGreaterEqual(result["option_count"], 1)
            self.assertTrue(Path(result["jsonl_path"]).exists())
            self.assertTrue(Path(result["markdown_path"]).exists())
            row = json.loads(Path(result["jsonl_path"]).read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("data_authority", row)
            self.assertEqual(row["operator_semantic_count"], 1)
            self.assertIn("template_matrix_ready_count", row)
            self.assertEqual(row["benchmark_rule_count"], 1)
            self.assertIn("maintenance_blockers", row)

    def test_plan_research_options_main_requires_live_api_flag(self):
        with patch("sys.argv", ["wqb", "plan-research-options"]):
            with self.assertRaisesRegex(SystemExit, "--enable-live-api is required"):
                main()

    def test_plan_research_options_main_dispatches_when_live_api_enabled(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "plan-research-options", "--enable-live-api"]), patch(
            "wqb.cli.plan_research_options",
            return_value={"option_count": 1, "jsonl_path": "cards.jsonl", "markdown_path": "cards.md"},
        ) as planner, redirect_stdout(output):
            main()

        planner.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["option_count"], 1)

    def test_knowledge_health_check_writes_report_without_simulation(self):
        from wqb.cli import knowledge_health_check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge_root = root / "knowledge"
            for name in ("raw", "machine", "wiki"):
                (knowledge_root / name).mkdir(parents=True)
            manifest = root / "freshness.json"
            report = root / "freshness_report.md"
            manifest.write_text(
                json.dumps(
                    [
                        {
                            "name": "data_ledger",
                            "path": "machine/data_ledger.jsonl",
                            "updated_at": "2026-07-08",
                            "max_age_days": 1,
                        },
                        {"name": "template_library", "path": "machine/template_library.jsonl", "updated_at": "2026-07-08", "max_age_days": 7},
                        {"name": "benchmark_rules", "path": "machine/benchmark_rules.jsonl", "updated_at": "2026-07-08", "max_age_days": 3},
                        {"name": "activity_snapshot", "path": "raw/platform/activities/activity_snapshot.md", "updated_at": "2026-07-08", "max_age_days": 1},
                    ]
                ),
                encoding="utf-8",
            )

            result = knowledge_health_check(knowledge_root, manifest, report, today_value="2026-07-10")

            self.assertTrue(Path(result["report_path"]).exists())
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("missing", report_text)
            self.assertIn("Knowledge Contract Health", report_text)

        self.assertEqual(result["stale_count"], 4)
        self.assertEqual(result["missing_count"], 4)
        self.assertEqual(result["contract_issue_count"], 0)

    def test_knowledge_health_check_rejects_partial_manifest(self):
        from wqb.cli import knowledge_health_check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "freshness.json"
            manifest.write_text(json.dumps([]), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing required entries"):
                knowledge_health_check(root, manifest, root / "freshness_report.md", today_value="2026-07-10")

    def test_schedule_research_from_option_uses_ledger_and_templates(self):
        from wqb.cli import schedule_research_from_option
        from wqb.principle_model import option_card_to_dict

        option = OptionCard(
            title="Explore current Power Pool boards",
            primary_incentive="power_pool",
            secondary_incentives=["genius"],
            why_now="Visible Power Pool boards include USA D1.",
            candidate_scope="USA D1 underused event data.",
            expected_asset_value="Simple alpha assets with lower criteria.",
            correlation_risk="Medium-high unless new data and distinct templates are used.",
            resource_cost="One 30-alpha scout batch.",
            evidence=[SourceEvidence("api", "/consultant/boards/power-pool", "Power Pool boards", "2026-07-10T00:00:00Z")],
            failure_modes=["Power Pool correlation failure."],
            decision_needed="Choose this option.",
            score=ScoreBreakdown(total=8.0, components={"power_pool": 8.0}, penalties={}, reasons=["Visible board."]),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_ready_knowledge_artifacts(root)
            option_path = root / "option.json"
            option_path.write_text(json.dumps(option_card_to_dict(option)), encoding="utf-8")
            ledger_dir = root / "machine"
            template_dir = root / "machine"
            ledger_dir.mkdir(parents=True, exist_ok=True)
            template_dir.mkdir(parents=True, exist_ok=True)
            (ledger_dir / "data_ledger.jsonl").write_text(
                json.dumps(
                    {
                        "dataset_id": "news12",
                        "dataset_name": "News Events",
                        "field_id": "news12_sentiment_fast_d1",
                        "field_type": "MATRIX",
                        "region": "USA",
                        "delay": 1,
                        "universe": "TOP3000",
                        "semantic_tags": ["event", "sentiment", "fast_d1", "power_pool"],
                        "coverage": 0.82,
                        "alpha_count": 12,
                        "user_count": 4,
                        "simulation_usage_count": 1,
                        "submitted_usage_count": 0,
                        "last_used_at": "2026-07-09",
                        "best_result_label": "repairable_signal",
                        "correlation_risk": "medium",
                        "source_paths": [f"raw/platform/data_fields/{date.today().isoformat()}/data_fields.jsonl"],
                        "source_quality": "platform_raw_capture",
                        "coverage_status": "measured_raw",
                        "source_updated_at": date.today().isoformat(),
                        "available_scopes": [{"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            capture_fields = root / "raw" / "platform" / "data_fields" / date.today().isoformat() / "data_fields.jsonl"
            capture_fields.write_text(
                json.dumps({"scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}, "data_set": {"id": "news12"}, "field": {"id": "news12_sentiment_fast_d1"}}) + "\n",
                encoding="utf-8",
            )
            (template_dir / "template_library.jsonl").write_text(
                json.dumps(
                    {
                        "template_id": "event_fast_delta_rank",
                        "hypothesis": "Fast event sentiment changes are incorporated gradually.",
                        "skeleton": "rank(ts_delta({field}, 1))",
                        "required_field_types": ["MATRIX"],
                        "compatible_semantic_tags": ["event", "sentiment", "fast_d1", "power_pool"],
                        "operator_tags": ["time_series_surprise"],
                        "status": "seed",
                        "correlation_risk": "low",
                        "repair_levers": ["group_neutralize"],
                        "source_paths": ["wiki"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            output_path = root / "wiki" / "70_decisions" / "research_schedule.md"

            result = schedule_research_from_option(option_path, root, output_path, "USA", 1)

            self.assertTrue(Path(result["schedule_path"]).exists())

        self.assertEqual(result["selected_data_count"], 1)
        self.assertEqual(result["template_match_count"], 1)

    def test_schedule_research_from_option_selects_one_based_option_from_jsonl(self):
        from wqb.cli import schedule_research_from_option
        from wqb.decision_log import write_option_cards

        first = OptionCard(
            title="First option", primary_incentive="power_pool", secondary_incentives=[], why_now="First.",
            candidate_scope="USA D1", expected_asset_value="Assets.", correlation_risk="Medium.",
            resource_cost="One batch.", evidence=[SourceEvidence("api", "/first", "First", "2026-07-10T00:00:00Z")],
            failure_modes=["Correlation."], decision_needed="Choose.",
            score=ScoreBreakdown(total=1.0, components={}, penalties={}, reasons=["First"]),
        )
        second = OptionCard(
            title="Selected JSONL option", primary_incentive="power_pool", secondary_incentives=[], why_now="Second.",
            candidate_scope="USA D1", expected_asset_value="Assets.", correlation_risk="Medium.",
            resource_cost="One batch.", evidence=[SourceEvidence("api", "/second", "Second", "2026-07-10T00:00:00Z")],
            failure_modes=["Correlation."], decision_needed="Choose.",
            score=ScoreBreakdown(total=2.0, components={}, penalties={}, reasons=["Second"]),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_ready_knowledge_artifacts(root)
            option_path, _ = write_option_cards(root / "cards", [first, second], "2026-07-10T00:00:00Z")
            ledger_dir = root / "wiki" / "20_semantics"
            template_dir = root / "wiki" / "30_templates"
            ledger_dir.mkdir(parents=True, exist_ok=True)
            template_dir.mkdir(parents=True, exist_ok=True)
            (ledger_dir / "data_ledger.jsonl").write_text(
                json.dumps({"dataset_id": "news12", "dataset_name": "News", "field_id": "news_field", "field_type": "MATRIX", "region": "USA", "delay": 1, "universe": "TOP3000", "semantic_tags": ["power_pool"], "coverage": 0.8, "alpha_count": 0, "user_count": 0, "simulation_usage_count": 0, "submitted_usage_count": 0, "last_used_at": "", "best_result_label": "unexplored", "correlation_risk": "low", "source_paths": [f"raw/platform/data_fields/{date.today().isoformat()}/data_fields.jsonl"], "source_quality": "platform_raw_capture", "coverage_status": "measured_raw", "source_updated_at": date.today().isoformat(), "available_scopes": [{"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}]}) + "\n",
                encoding="utf-8",
            )
            (template_dir / "template_library.jsonl").write_text(
                json.dumps({"template_id": "matrix_rank", "hypothesis": "Rank the field.", "skeleton": "rank({field})", "required_field_types": ["MATRIX"], "compatible_semantic_tags": ["power_pool"], "operator_tags": [], "status": "seed", "correlation_risk": "low", "repair_levers": [], "source_paths": []}) + "\n",
                encoding="utf-8",
            )
            output_path = root / "wiki" / "70_decisions" / "schedule.md"

            with self.assertRaisesRegex(ValueError, "option_index is required"):
                schedule_research_from_option(option_path, root, output_path, "USA", 1)
            result = schedule_research_from_option(option_path, root, output_path, "USA", 1, option_index=2)

            schedule_text = Path(result["schedule_path"]).read_text(encoding="utf-8")
        self.assertIn("Selected JSONL option", schedule_text)

    def test_schedule_research_blocks_before_writing_schedule_when_readiness_fails(self):
        from wqb.cli import schedule_research_from_option
        from wqb.principle_model import option_card_to_dict

        option = OptionCard(
            title="Blocked option",
            primary_incentive="power_pool",
            secondary_incentives=[],
            why_now="Need research.",
            candidate_scope="USA D1",
            expected_asset_value="Assets.",
            correlation_risk="Medium.",
            resource_cost="One batch.",
            evidence=[SourceEvidence("api", "/blocked", "Blocked", "2026-07-10T00:00:00Z")],
            failure_modes=["Correlation."],
            decision_needed="Choose.",
            score=ScoreBreakdown(total=1.0, components={}, penalties={}, reasons=["Blocked"]),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            option_path = root / "option.json"
            output_path = root / "wiki" / "70_decisions" / "schedule.md"
            option_path.write_text(json.dumps(option_card_to_dict(option)), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "Readiness blocked"):
                schedule_research_from_option(option_path, root, output_path, "USA", 1)

            self.assertFalse(output_path.exists())
            self.assertTrue((output_path.parent / "readiness" / "readiness_report.md").exists())

    def test_parse_args_accepts_knowledge_health_and_option_index(self):
        with patch("sys.argv", ["wqb", "knowledge-health-check", "--today", "2026-07-10"]):
            health_args = parse_args()
        with patch("sys.argv", ["wqb", "schedule-research", "--option-json", "cards.jsonl", "--option-index", "2"]):
            schedule_args = parse_args()
        with patch("sys.argv", ["wqb", "schedule-research", "--option-json", "cards.jsonl"]):
            schedule_without_index = parse_args()

        self.assertEqual(health_args.command, "knowledge-health-check")
        self.assertEqual(schedule_args.option_index, 2)
        self.assertIsNone(schedule_without_index.option_index)

    def test_knowledge_contract_check_main_reports_contract_issues_without_simulation(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            raw_path = root / "raw" / "platform" / "learn" / "2026-07-22" / "operators.md"
            raw_path.parent.mkdir(parents=True)
            raw_path.write_text("---\nsource_type: platform_api\n---\n# Operators\n", encoding="utf-8")
            source_index = update_source_index(
                root,
                [
                    SourceIndexRow(
                        path="raw/platform/learn/2026-07-22/operators.md",
                        source_family="learn",
                        source_type="platform_api",
                        contents="operator capture",
                        update_check="compare operators",
                        compiled_targets=[],
                    )
                ],
            )

            with patch("sys.argv", ["wqb", "knowledge-contract-check", "--knowledge-root", str(root)]), redirect_stdout(output):
                main()

        result = json.loads(output.getvalue())
        self.assertGreater(result["issue_count"], 0)
        self.assertIn("missing source_family", [item["issue"] for item in result["issues"]])
        self.assertNotIn(str(source_index), [item["path"] for item in result["issues"]])

    def test_schedule_research_main_requires_option_json(self):
        with patch("sys.argv", ["wqb", "schedule-research"]):
            with self.assertRaisesRegex(SystemExit, "--option-json is required"):
                main()

    def test_schedule_research_main_uses_explicit_knowledge_root(self):
        output = io.StringIO()
        with patch(
            "sys.argv",
            [
                "wqb",
                "schedule-research",
                "--option-json",
                "cards.jsonl",
                "--knowledge-root",
                "custom_knowledge",
            ],
        ), patch(
            "wqb.cli.schedule_research_from_option",
            return_value={"schedule_path": "schedule.md", "selected_data_count": 1, "selected_template_count": 1},
        ) as scheduler, redirect_stdout(output):
            main()

        scheduler.assert_called_once()
        self.assertEqual(scheduler.call_args.args[1], "custom_knowledge")
        self.assertEqual(json.loads(output.getvalue())["schedule_path"], "schedule.md")

    def test_knowledge_health_check_main_dispatches_without_simulation(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "knowledge-health-check"]), patch(
            "wqb.cli.knowledge_health_check", return_value={"record_count": 1, "stale_count": 0, "missing_count": 0, "report_path": "report.md"}
        ) as health_check, redirect_stdout(output):
            main()

        health_check.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["report_path"], "report.md")

    def test_knowledge_health_check_main_uses_explicit_knowledge_root(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "knowledge-health-check", "--knowledge-root", "custom_knowledge"]), patch(
            "wqb.cli.knowledge_health_check", return_value={"record_count": 1, "stale_count": 0, "missing_count": 0, "report_path": "report.md"}
        ) as health_check, redirect_stdout(output):
            main()

        self.assertEqual(health_check.call_args.args[0], "custom_knowledge")
        self.assertEqual(json.loads(output.getvalue())["report_path"], "report.md")
        self.assertEqual(health_check.call_args.args[2], "machine/reports/freshness_report.md")

    def test_compile_research_records_main_dispatches_without_network(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "compile-research-records", "--knowledge-root", "custom_knowledge"]), patch(
            "wqb.cli.compile_research_records_command",
            return_value={"record_count": 1, "markdown_path": "compile.md", "json_path": "compile.json"},
        ) as compiler, redirect_stdout(output):
            main()

        compiler.assert_called_once_with("custom_knowledge")
        self.assertEqual(json.loads(output.getvalue())["markdown_path"], "compile.md")

    def test_capture_interaction_note_main_writes_raw_note_without_network(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "sys.argv",
                [
                    "wqb",
                    "capture-interaction-note",
                    "--knowledge-root",
                    str(root),
                    "--summary",
                    "Keep a regression test for every fixed workflow bug.",
                    "--category",
                    "workflow_rule",
                    "--tag",
                    "maintenance",
                    "--evidence-path",
                    "milestone.md",
                ],
            ), redirect_stdout(output):
                main()

            result = json.loads(output.getvalue())
            notes = (root / "raw" / "community" / "user_messages").rglob("interaction_notes.jsonl")
            note_paths = list(notes)

        self.assertEqual(len(note_paths), 1)
        self.assertEqual(Path(result["path"]), note_paths[0])

    def test_capture_platform_data_fields_requires_live_api_flag(self):
        with patch("sys.argv", ["wqb", "capture-platform-data-fields"]):
            with self.assertRaises(SystemExit) as ctx:
                main()

        self.assertIn("--enable-live-api", str(ctx.exception))

    def test_capture_platform_data_fields_dispatches_with_scope_limits(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "capture-platform-data-fields", "--enable-live-api", "--capture-region", "USA,EUR", "--capture-delay", "1", "--capture-universe", "TOP3000", "--max-scopes", "2"]):
            with patch("wqb.cli.capture_platform_data_fields_command", return_value={"field_count": 7}) as command:
                with redirect_stdout(output):
                    main()

        kwargs = command.call_args.kwargs
        self.assertEqual(kwargs["regions"], ["USA", "EUR"])
        self.assertEqual(kwargs["delays"], [1])
        self.assertEqual(kwargs["universes"], ["TOP3000"])
        self.assertEqual(kwargs["max_scopes"], 2)
        self.assertEqual(json.loads(output.getvalue())["field_count"], 7)

    def test_stratified_capture_commands_dispatch_without_live_field_capture(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "plan-stratified-data-capture", "--knowledge-root", "knowledge", "--fields-per-scope", "25", "--max-scopes", "4"]):
            with patch("wqb.cli.plan_stratified_data_capture_command", return_value={"scope_count": 4}) as command:
                with redirect_stdout(output):
                    main()

        self.assertEqual(command.call_args.args[0], "knowledge")
        self.assertEqual(command.call_args.kwargs["fields_per_scope"], 25)
        self.assertEqual(command.call_args.kwargs["max_scopes"], 4)
        self.assertEqual(json.loads(output.getvalue())["scope_count"], 4)

    def test_capture_platform_data_fields_forwards_stratified_plan_arguments(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "capture-platform-data-fields", "--enable-live-api", "--capture-plan-path", "plan.jsonl", "--fields-per-scope", "25"]):
            with patch("wqb.cli.capture_platform_data_fields_command", return_value={"field_count": 2}) as command:
                with redirect_stdout(output):
                    main()

        self.assertEqual(command.call_args.kwargs["capture_plan_path"], "plan.jsonl")
        self.assertEqual(command.call_args.kwargs["fields_per_scope"], 25)

    def test_compile_data_ledger_dispatches_without_live_api(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "compile-data-ledger", "--knowledge-root", "knowledge"]):
            with patch("wqb.cli.compile_data_ledger_command", return_value={"record_count": 3}) as command:
                with redirect_stdout(output):
                    main()

        self.assertEqual(command.call_args.args[0], "knowledge")
        self.assertEqual(json.loads(output.getvalue())["record_count"], 3)

    def test_compile_operator_semantics_writes_local_ledger_without_live_api(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("sys.argv", ["wqb", "compile-operator-semantics", "--knowledge-root", str(root)]), redirect_stdout(output):
                main()

            result = json.loads(output.getvalue())
            jsonl_path = root / "machine" / "operator_ledger.jsonl"
            markdown_path = root / "machine" / "previews" / "operator_semantics.md"
            self.assertEqual(result["record_count"], 3)
            self.assertEqual(Path(result["jsonl_path"]), jsonl_path)
            self.assertEqual(Path(result["markdown_path"]), markdown_path)
            self.assertTrue(jsonl_path.exists())
            self.assertIn("vec_avg", markdown_path.read_text(encoding="utf-8"))
            self.assertFalse((root / "wiki" / "20_operator_semantics.md").exists())

    def test_migrate_knowledge_vault_dispatches_without_live_api(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "migrate-knowledge-vault", "--knowledge-root", "knowledge"]):
            with patch("wqb.cli.run_knowledge_vault_migration", return_value={"status": "completed"}) as command:
                with redirect_stdout(output):
                    main()

        command.assert_called_once_with("knowledge")
        self.assertEqual(json.loads(output.getvalue())["status"], "completed")

    def test_launch_console_parse_and_dispatch(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "launch-console", "--console-host", "127.0.0.1", "--console-port", "0", "--no-open-browser"]), patch(
            "wqb.cli.run_console",
            return_value={"url": "http://127.0.0.1:0", "host": "127.0.0.1", "port": 0},
        ) as launcher, redirect_stdout(output):
            args = parse_args()
            self.assertEqual(args.command, "launch-console")
            main()

        launcher.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["url"], "http://127.0.0.1:0")

    def test_dry_run_prints_payloads_without_network(self):
        config = load_config(
            "configs/stage1_usa_d1.yaml",
            overrides={"max_alphas_per_round": 4},
        )
        output = io.StringIO()

        with redirect_stdout(output):
            dry_run(config)

        result = json.loads(output.getvalue())
        self.assertEqual(result["payload_count"], 4)
        self.assertEqual(len(result["payloads"]), 4)
        self.assertEqual(result["payloads"][0]["payload"]["type"], "REGULAR")
        self.assertTrue(result["payloads"][0]["complexity_ok"])

    def test_format_parallel_stage_plan_outputs_assignable_tasks(self):
        output = format_parallel_stage_plan("scout", ["search_interest", "news21"])
        result = json.loads(output)

        self.assertEqual(result["stage"], "scout")
        self.assertEqual(result["dataset_ids"], ["search_interest", "news21"])
        self.assertEqual(result["tasks"][0]["task_type"], "data_scout")
        self.assertEqual(result["tasks"][0]["parallel_group"], "new_data_scout")
        self.assertIn("depends_on", result["tasks"][-1])

    def test_inspect_existing_alpha_records_benchmark_signal_note(self):
        class FakeClient:
            def get_json(self, path):
                if path == "/alphas/3q7OQaog":
                    return {
                        "is": {
                            "sharpe": 0.95,
                            "fitness": 0.42,
                            "returns": 0.025,
                            "turnover": 0.22,
                        }
                    }
                if path == "/alphas/3q7OQaog/check":
                    return {
                        "is": {
                            "checks": [
                                {"name": "LOW_SHARPE", "result": "FAIL"},
                                {"name": "LOW_FITNESS", "result": "FAIL"},
                                {"name": "LOW_2Y_SHARPE", "result": "FAIL"},
                            ]
                        }
                    }
                raise AssertionError(path)

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            summary = inspect_existing_alpha(
                FakeClient(),
                recorder,
                "3q7OQaog",
                signal_note="straight PnL observed by user",
            )
            record = recorder.read_jsonl("all_alphas.jsonl")[0]

            self.assertFalse(summary.hard_pass)
            self.assertEqual(record["benchmark_label"], "repairable_signal")
            self.assertEqual(record["next_stage"], "repair")
            self.assertIn("pnl_shape_signal", record["benchmark_reasons"])
        finally:
            cleanup_run_dir(run_dir)

    def test_list_fields_summary_filters_suffix_and_formats_fields(self):
        class FakeClient:
            def get_json(self, path):
                self.path = path
                return {
                    "results": [
                        {
                            "id": "opt_signal_fast_d1",
                            "type": "MATRIX",
                            "coverage": 0.91,
                            "alphaCount": 3,
                            "dataset": {"id": "option_fast"},
                        },
                        {"id": "opt_signal", "type": "MATRIX", "coverage": 0.91, "alphaCount": 12},
                    ]
                }

        result = list_fields_summary(
            FakeClient(),
            load_config("configs/stage1_usa_d1.yaml"),
            dataset_id="option_fast",
            field_search="option",
            field_suffix="_fast_d1",
            max_fields=5,
        )

        self.assertEqual(result["dataset_id"], "option_fast")
        self.assertEqual(result["field_search"], "option")
        self.assertEqual(result["field_suffix"], "_fast_d1")
        self.assertEqual(result["field_count"], 1)
        self.assertEqual(result["fields"][0]["id"], "opt_signal_fast_d1")
        self.assertEqual(result["fields"][0]["dataset_id"], "option_fast")

    def test_cache_metadata_passes_skip_data_sets_to_builder(self):
        class FakeClient:
            def authenticate(self):
                return None

        run_dir = make_run_dir()
        try:
            output = io.StringIO()
            cache = {
                "operators": [{"name": "rank"}],
                "data_sets": [],
                "field_queries": [{"fields": [{"id": "fnd3_q_cash_fast_d1"}]}],
            }
            with patch("wqb.cli.build_client", return_value=FakeClient()):
                with patch("wqb.cli.build_metadata_cache", return_value=cache) as build_cache:
                    with redirect_stdout(output):
                        cache_path = cache_metadata(
                            load_config("configs/stage1_usa_d1.yaml"),
                            dataset_id_arg="fundamental3",
                            field_search_arg="cash",
                            field_suffix="_fast_d1",
                            max_fields=50,
                            cache_dir=str(run_dir),
                            include_data_sets=False,
                        )

            self.assertTrue(cache_path.exists())
            self.assertFalse(build_cache.call_args.kwargs["include_data_sets"])
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["data_set_count"], 0)
            self.assertEqual(summary["field_count"], 1)
        finally:
            cleanup_run_dir(run_dir)

    def test_summarize_run_dir_counts_records_and_failures(self):
        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            recorder.append_jsonl(
                "all_alphas.jsonl",
                {
                    "alpha_id": "a1",
                    "hard_pass": False,
                    "failed": ["LOW_SHARPE", "LOW_FITNESS"],
                    "pending": ["SELF_CORRELATION"],
                    "warnings": ["MATCHES_THEMES"],
                },
            )
            recorder.append_jsonl(
                "all_alphas.jsonl",
                {
                    "alpha_id": "a2",
                    "hard_pass": True,
                    "failed": [],
                    "pending": [],
                    "warnings": [],
                },
            )
            recorder.append_jsonl(
                "all_alphas.jsonl",
                {
                    "alpha_id": "a3",
                    "hard_pass": False,
                    "metrics": {"sharpe": 0.95, "fitness": 0.42, "returns": 0.025, "turnover": 0.22},
                    "failed": ["LOW_SHARPE", "LOW_FITNESS", "LOW_2Y_SHARPE"],
                    "pending": [],
                    "warnings": [],
                    "signal_note": "straight PnL",
                },
            )
            recorder.append_jsonl(
                "optimization_trace.jsonl",
                {"action_type": "change_window", "reason": "LOW_SHARPE"},
            )
            recorder.append_jsonl("run_errors.jsonl", {"status_code": 429, "stage": "submit_simulation"})
            recorder.append_jsonl(
                "existing_alpha_scan.jsonl",
                {"alpha_id": "scan1", "hard_pass": False, "failed": ["LOW_SHARPE"], "pending": []},
            )
            recorder.append_jsonl(
                "existing_alpha_scan.jsonl",
                {"alpha_id": "scan2", "hard_pass": True, "failed": [], "pending": []},
            )
            recorder.append_jsonl(
                "existing_alpha_scan.jsonl",
                {
                    "alpha_id": "scan3",
                    "hard_pass": False,
                    "metrics": {"sharpe": 0.96, "fitness": 0.54, "returns": 0.2, "turnover": 0.63},
                    "failed": ["LOW_SHARPE", "LOW_FITNESS", "LOW_2Y_SHARPE"],
                    "pending": [],
                    "warnings": [],
                    "benchmark_label": "repairable_signal",
                    "signal_score": 0.62,
                    "repair_priority": 2,
                    "benchmark_reasons": ["near_threshold_sharpe"],
                    "next_stage": "repair",
                },
            )
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {"event": "SUBMITTED", "expression_hash": "hash_checked", "progress_url": "/simulations/done"},
            )
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {"event": "CHECKED", "expression_hash": "hash_checked", "alpha_id": "a1"},
            )
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {"event": "SUBMITTED", "expression_hash": "hash_running", "progress_url": "/simulations/running"},
            )

            summary = summarize_run_dir(run_dir)

            self.assertEqual(summary["checked_count"], 3)
            self.assertEqual(summary["hard_pass_count"], 1)
            self.assertEqual(summary["failed_counts"]["LOW_SHARPE"], 2)
            self.assertEqual(summary["pending_counts"]["SELF_CORRELATION"], 1)
            self.assertEqual(summary["action_counts"]["change_window"], 1)
            self.assertEqual(summary["error_counts"]["429"], 1)
            self.assertEqual(summary["existing_scan_count"], 3)
            self.assertEqual(summary["existing_scan_hard_pass_count"], 1)
            self.assertEqual(summary["existing_scan_failed_counts"]["LOW_SHARPE"], 2)
            self.assertEqual(summary["existing_scan_benchmark_counts"]["repairable_signal"], 1)
            self.assertEqual(summary["existing_repair_queue"][0]["alpha_id"], "scan3")
            self.assertEqual(summary["benchmark_counts"]["repairable_signal"], 1)
            self.assertEqual(summary["repair_queue"][0]["alpha_id"], "a3")
            self.assertEqual(summary["submitted_count"], 2)
            self.assertEqual(summary["in_flight_count"], 1)
            self.assertEqual(summary["in_flight_progress_urls"], ["/simulations/running"])
        finally:
            cleanup_run_dir(run_dir)

    def test_summarize_run_dir_deduplicates_in_flight_progress_urls(self):
        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {"event": "SUBMITTED", "expression_hash": "h1", "progress_url": "/simulations/shared"},
            )
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {"event": "SUBMITTED", "expression_hash": "h2", "progress_url": "/simulations/shared"},
            )

            summary = summarize_run_dir(run_dir)

            self.assertEqual(summary["in_flight_count"], 2)
            self.assertEqual(summary["in_flight_progress_urls"], ["/simulations/shared"])
        finally:
            cleanup_run_dir(run_dir)

    def test_summarize_run_dir_treats_simulation_error_as_terminal(self):
        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "SUBMITTED",
                    "expression_hash": "abc",
                    "progress_url": "https://api.worldquantbrain.com/simulations/abc",
                },
            )
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "ERROR",
                    "expression_hash": "abc",
                    "message": "bad operator",
                },
            )

            summary = summarize_run_dir(run_dir)

            self.assertEqual(summary["submitted_count"], 1)
            self.assertEqual(summary["in_flight_count"], 0)
            self.assertEqual(summary["in_flight_progress_urls"], [])
        finally:
            cleanup_run_dir(run_dir)

    def test_is_http_status_error_detects_response_status(self):
        response = requests.Response()
        response.status_code = 429
        err = requests.exceptions.HTTPError("rate limited", response=response)

        self.assertTrue(is_http_status_error(err, 429))
        self.assertFalse(is_http_status_error(err, 500))

    def test_authenticate_for_run_records_recoverable_error(self):
        class FakeClient:
            def authenticate(self):
                raise requests.exceptions.ConnectionError("proxy reset")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)

            authenticated = authenticate_for_run(FakeClient(), recorder, "complete_in_flight_auth")

            self.assertFalse(authenticated)
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["stage"], "complete_in_flight_auth")
            self.assertEqual(errors[0]["status_code"], "NETWORK_ERROR")
            self.assertTrue(errors[0]["recoverable"])
        finally:
            cleanup_run_dir(run_dir)

    def test_record_recoverable_http_error_keeps_status_code(self):
        from wqb.cli import record_recoverable_network_error

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "60"
            response.headers["X-Ratelimit-Remaining"] = "0"
            response.headers["X-Ratelimit-Reset"] = "3600"
            err = requests.exceptions.HTTPError("429 Client Error", response=response)

            record_recoverable_network_error(recorder, "submit", err)

            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["status_code"], 429)
            self.assertEqual(errors[0]["retry_after"], "60")
            self.assertEqual(errors[0]["x_ratelimit_remaining"], "0")
            self.assertEqual(errors[0]["x_ratelimit_reset"], "3600")
        finally:
            cleanup_run_dir(run_dir)

    def test_parse_operator_replacements_reads_old_new_pairs(self):
        replacements = parse_operator_replacements(["group_normalize=group_zscore"])

        self.assertEqual(replacements, {"group_normalize": "group_zscore"})
        with self.assertRaises(ValueError):
            parse_operator_replacements(["missing_separator"])

    def test_parse_setting_overrides_coerces_values(self):
        overrides = parse_setting_overrides(["decay=15", "truncation=0.05", "neutralization=SUBINDUSTRY"])

        self.assertEqual(overrides, {"decay": 15, "truncation": 0.05, "neutralization": "SUBINDUSTRY"})
        with self.assertRaises(ValueError):
            parse_setting_overrides(["missing_separator"])

    def test_parse_setting_variations_builds_cartesian_variants(self):
        variants = parse_setting_variations(["decay=15,20", "truncation=0.05,0.08"])

        self.assertEqual(
            variants,
            [
                {"decay": 15, "truncation": 0.05},
                {"decay": 15, "truncation": 0.08},
                {"decay": 20, "truncation": 0.05},
                {"decay": 20, "truncation": 0.08},
            ],
        )
        with self.assertRaises(ValueError):
            parse_setting_variations(["decay"])

    def test_parse_blend_weights_reads_comma_values(self):
        self.assertEqual(parse_blend_weights("0.25,0.5"), [0.25, 0.5])
        with self.assertRaises(ValueError):
            parse_blend_weights("bad")

    def test_blend_repair_expression_preserves_assignments(self):
        base = "c = rank(close) > 0;\nd = rank(volume);\ntrade_when(c, d, -1)"

        blended = blend_repair_expression(base, "annual_basic_eps_value_fast_d1 - annual_basic_eps_value", 0.25)

        self.assertEqual(
            blended,
            "c = rank(close) > 0;\nd = rank(volume);\ntrade_when(c, rank((d)) + 0.25 * rank(annual_basic_eps_value_fast_d1 - annual_basic_eps_value), -1)",
        )

    def test_blend_repair_expression_keeps_non_trade_when_blend(self):
        base = "rank(close - open)"

        blended = blend_repair_expression(base, "annual_basic_eps_value_fast_d1 - annual_basic_eps_value", 0.25)

        self.assertEqual(
            blended,
            "rank((rank(close - open))) + 0.25 * rank(annual_basic_eps_value_fast_d1 - annual_basic_eps_value)",
        )

    def test_scan_existing_alpha_candidates_records_only_hard_pass(self):
        class FakeClient:
            def get_json(self, path):
                if path.startswith("/users/self/alphas"):
                    return {"results": [{"id": "a1"}, {"id": "a2"}]}
                if path == "/alphas/a1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.1, "turnover": 0.2, "returns": 0.05}}
                if path == "/alphas/a1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                if path == "/alphas/a2":
                    return {"is": {"sharpe": 0.96, "fitness": 0.54, "returns": 0.2, "turnover": 0.63}}
                if path == "/alphas/a2/check":
                    return {
                        "is": {
                            "checks": [
                                {"name": "LOW_SHARPE", "result": "FAIL"},
                                {"name": "LOW_FITNESS", "result": "FAIL"},
                                {"name": "LOW_2Y_SHARPE", "result": "FAIL"},
                            ]
                        }
                    }
                raise AssertionError(f"unexpected path: {path}")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)

            candidates = scan_existing_alpha_candidates(FakeClient(), recorder, max_scan=2, page_limit=2)

            self.assertEqual([candidate["alpha_id"] for candidate in candidates], ["a1"])
            records = recorder.read_jsonl("existing_alpha_scan.jsonl")
            self.assertEqual(records[0]["alpha_id"], "a1")
            self.assertEqual(records[1]["benchmark_label"], "repairable_signal")
            self.assertEqual(records[1]["next_stage"], "repair")
            self.assertTrue((run_dir / "candidates.csv").exists())
        finally:
            cleanup_run_dir(run_dir)

    def test_scan_existing_can_write_to_existing_run_dir(self):
        class FakeClient:
            def authenticate(self):
                return None

            def get_json(self, path):
                if path.startswith("/users/self/alphas"):
                    return {"results": [{"id": "a1"}]}
                if path == "/alphas/a1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.18}}
                if path == "/alphas/a1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(path)

        run_dir = make_run_dir()
        try:
            output = io.StringIO()
            with patch("wqb.cli.build_client", return_value=FakeClient()):
                with redirect_stdout(output):
                    scan_existing(load_config("configs/stage1_usa_d1.yaml"), max_scan=1, run_dir=str(run_dir))

            result = json.loads(output.getvalue())
            self.assertEqual(Path(result["run_dir"]), run_dir)
            self.assertEqual(len(RunRecorder(run_dir).read_jsonl("existing_alpha_scan.jsonl")), 1)
        finally:
            cleanup_run_dir(run_dir)

    def test_scan_existing_records_recoverable_auth_error(self):
        class FakeClient:
            def authenticate(self):
                raise requests.exceptions.ConnectionError("auth reset")

        run_dir = make_run_dir()
        try:
            output = io.StringIO()
            with patch("wqb.cli.build_client", return_value=FakeClient()):
                with redirect_stdout(output):
                    scan_existing(load_config("configs/stage1_usa_d1.yaml"), max_scan=1, run_dir=str(run_dir))

            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "auth_recoverable_error")
            errors = RunRecorder(run_dir).read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["stage"], "scan_existing_auth")
        finally:
            cleanup_run_dir(run_dir)

    def test_scan_existing_alpha_candidates_records_recoverable_check_error(self):
        class FakeClient:
            def get_json(self, path):
                if path.startswith("/users/self/alphas"):
                    return {"results": [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]}
                if path == "/alphas/a1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/a1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                if path == "/alphas/a2":
                    raise requests.exceptions.ConnectionError("proxy reset")
                if path == "/alphas/a3":
                    return {"is": {"sharpe": 0.5}}
                if path == "/alphas/a3/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL"}]}}
                raise AssertionError(f"unexpected path: {path}")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)

            candidates = scan_existing_alpha_candidates(FakeClient(), recorder, max_scan=3, page_limit=3)

            self.assertEqual([candidate["alpha_id"] for candidate in candidates], ["a1"])
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["stage"], "scan_existing_check")
            self.assertEqual(errors[0]["alpha_id"], "a2")
            self.assertEqual(len(recorder.read_jsonl("existing_alpha_scan.jsonl")), 2)
        finally:
            cleanup_run_dir(run_dir)

    def test_refresh_existing_alpha_resimulates_and_records_check(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/old1":
                    return {
                        "settings": {"region": "USA"},
                        "regular": {"code": "rank(close)"},
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/refresh1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)

            summary = refresh_existing_alpha(FakeClient(), recorder, "old1")

            self.assertTrue(summary.hard_pass)
            records = recorder.read_jsonl("simulation_events.jsonl")
            self.assertEqual(records[0]["event"], "SUBMITTED")
            self.assertEqual(records[0]["parent_alpha_id"], "old1")
            self.assertEqual(records[1]["event"], "CHECKED")
            self.assertEqual(recorder.read_jsonl("all_alphas.jsonl")[0]["alpha_id"], "new1")
            self.assertTrue((run_dir / "candidates.csv").exists())
        finally:
            cleanup_run_dir(run_dir)

    def test_refresh_existing_alpha_applies_operator_replacements(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/old1":
                    return {
                        "settings": {"region": "USA"},
                        "regular": {"code": "group_normalize(rank(close), industry)"},
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/refresh1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            client = FakeClient()

            refresh_existing_alpha(client, recorder, "old1", operator_replacements={"group_normalize": "group_zscore"})

            self.assertEqual(client.posts[0][1]["regular"], "group_zscore(rank(close), industry)")
            self.assertEqual(recorder.read_jsonl("simulation_events.jsonl")[0]["operator_replacements"], {"group_normalize": "group_zscore"})
        finally:
            cleanup_run_dir(run_dir)

    def test_refresh_existing_alpha_applies_setting_overrides(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/old1":
                    return {
                        "settings": {"region": "USA", "decay": 5},
                        "regular": {"code": "rank(close)"},
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/refresh1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            client = FakeClient()

            refresh_existing_alpha(client, recorder, "old1", setting_overrides={"decay": 15})

            self.assertEqual(client.posts[0][1]["settings"]["decay"], 15)
            self.assertEqual(recorder.read_jsonl("simulation_events.jsonl")[0]["setting_overrides"], {"decay": 15})
        finally:
            cleanup_run_dir(run_dir)

    def test_refresh_existing_alpha_records_simulation_error(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def get_json(self, path):
                if path == "/alphas/old1":
                    return {
                        "settings": {"region": "USA"},
                        "regular": {"code": "rank(close)"},
                    }
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                return FakeResponse(headers={"Location": "/simulations/error1"})

            def request(self, method, path):
                return FakeResponse(payload={"status": "ERROR", "message": "bad operator"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)

            summary = refresh_existing_alpha(FakeClient(), recorder, "old1")

            self.assertIsNone(summary)
            events = recorder.read_jsonl("simulation_events.jsonl")
            self.assertEqual(events[1]["event"], "ERROR")
            self.assertEqual(events[1]["message"], "bad operator")
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["stage"], "refresh_alpha")
            self.assertEqual(errors[0]["status"], "ERROR")
        finally:
            cleanup_run_dir(run_dir)

    def test_refresh_existing_alpha_records_recoverable_poll_error(self):
        class FakeResponse:
            def __init__(self, headers=None):
                self.headers = headers or {}

            def raise_for_status(self):
                return None

        class FakeClient:
            def get_json(self, path):
                if path == "/alphas/old1":
                    return {
                        "settings": {"region": "USA"},
                        "regular": {"code": "rank(close)"},
                    }
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                return FakeResponse(headers={"Location": "/simulations/recoverable1"})

            def request(self, method, path):
                raise requests.exceptions.ConnectionError("proxy reset")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)

            summary = refresh_existing_alpha(FakeClient(), recorder, "old1")

            self.assertIsNone(summary)
            events = recorder.read_jsonl("simulation_events.jsonl")
            self.assertEqual([event["event"] for event in events], ["SUBMITTED"])
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["status_code"], "NETWORK_ERROR")
            self.assertTrue(errors[0]["recoverable"])
            self.assertEqual(summarize_run_dir(run_dir)["in_flight_count"], 1)
        finally:
            cleanup_run_dir(run_dir)

    def test_refresh_existing_alpha_batch_submits_variants_and_records_checks(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/old1":
                    return {
                        "settings": {"region": "USA", "decay": 10},
                        "regular": {"code": "rank(close)"},
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                if path == "/alphas/new2":
                    return {"is": {"sharpe": 0.7, "fitness": 0.4, "turnover": 0.2}}
                if path == "/alphas/new2/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/multi1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": ["new1", "new2"]})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            client = FakeClient()

            summaries = refresh_existing_alpha_batch(
                client,
                recorder,
                "old1",
                setting_variants=[{"decay": 15}, {"decay": 20}],
            )

            self.assertEqual([summary.alpha_id for summary in summaries], ["new1", "new2"])
            self.assertEqual([payload["settings"]["decay"] for payload in client.posts[0][1]], [15, 20])
            events = recorder.read_jsonl("simulation_events.jsonl")
            self.assertEqual([event["event"] for event in events[:2]], ["SUBMITTED", "SUBMITTED"])
            self.assertEqual([event["event"] for event in events[2:]], ["CHECKED", "CHECKED"])
            self.assertEqual(recorder.read_jsonl("all_alphas.jsonl")[0]["alpha_id"], "new1")
            self.assertTrue((run_dir / "candidates.csv").exists())
        finally:
            cleanup_run_dir(run_dir)

    def test_refresh_existing_alpha_batch_records_recoverable_child_poll_error(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def get_json(self, path):
                if path == "/alphas/old1":
                    return {
                        "settings": {"region": "USA", "decay": 10},
                        "regular": {"code": "rank(close)"},
                    }
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                return FakeResponse(headers={"Location": "/simulations/parent"})

            def request(self, method, path):
                if path == "/simulations/parent":
                    return FakeResponse(payload={"children": ["child1"]})
                if path == "/simulations/child1":
                    raise SimulationPollTimeout("simulation poll exceeded Retry-After limit for /simulations/child1")
                raise AssertionError(f"unexpected request: {method} {path}")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)

            summaries = refresh_existing_alpha_batch(
                FakeClient(),
                recorder,
                "old1",
                setting_variants=[{"decay": 15}],
            )

            self.assertEqual(summaries, [])
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["stage"], "refresh_alpha_batch_child_poll")
            self.assertEqual(errors[0]["status_code"], "SIMULATION_POLL_TIMEOUT")
            self.assertEqual(errors[0]["progress_url"], "/simulations/parent")
            self.assertIn("/simulations/child1", errors[0]["message"])
            self.assertEqual(summarize_run_dir(run_dir)["in_flight_count"], 1)
        finally:
            cleanup_run_dir(run_dir)

    def test_complete_in_flight_simulations_records_checked_alpha(self):
        class FakeResponse:
            def __init__(self, payload=None):
                self.headers = {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

            def get_json(self, path):
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "SUBMITTED",
                    "parent_alpha_id": "old1",
                    "expression_hash": "abc",
                    "expression": "rank(sentiment_a)",
                    "field_search": "sentiment",
                    "dataset_id": "",
                    "progress_url": "/simulations/abc",
                    "operator_replacements": {},
                },
            )

            completed = complete_in_flight_simulations(FakeClient(), recorder)

            self.assertEqual(completed, ["new1"])
            events = recorder.read_jsonl("simulation_events.jsonl")
            self.assertEqual(events[1]["event"], "CHECKED")
            self.assertEqual(events[1]["alpha_id"], "new1")
            alpha_record = recorder.read_jsonl("all_alphas.jsonl")[0]
            self.assertEqual(alpha_record["alpha_id"], "new1")
            self.assertEqual(alpha_record["expression"], "rank(sentiment_a)")
            self.assertEqual(alpha_record["field_search"], "sentiment")
            self.assertTrue((run_dir / "candidates.csv").exists())
        finally:
            cleanup_run_dir(run_dir)

    def test_refresh_existing_alpha_batch_serial_submits_single_payloads(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/old1":
                    return {
                        "settings": {"region": "USA", "decay": 10},
                        "regular": {"code": "rank(close)"},
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                if path == "/alphas/new2":
                    return {"is": {"sharpe": 1.8, "fitness": 1.3, "turnover": 0.2}}
                if path == "/alphas/new2/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                suffix = len(self.posts)
                return FakeResponse(headers={"Location": f"/simulations/serial{suffix}"})

            def request(self, method, path):
                if path == "/simulations/serial1":
                    return FakeResponse(payload={"alpha": "new1"})
                if path == "/simulations/serial2":
                    return FakeResponse(payload={"alpha": "new2"})
                raise AssertionError(f"unexpected path: {path}")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            client = FakeClient()

            summaries = refresh_existing_alpha_batch(
                client,
                recorder,
                "old1",
                setting_variants=[{"decay": 15}, {"decay": 20}],
                submit_mode="serial",
            )

            self.assertEqual([summary.alpha_id for summary in summaries], ["new1", "new2"])
            self.assertEqual(len(client.posts), 2)
            self.assertIsInstance(client.posts[0][1], dict)
            self.assertEqual([post[1]["settings"]["decay"] for post in client.posts], [15, 20])
            checked = [event for event in recorder.read_jsonl("simulation_events.jsonl") if event["event"] == "CHECKED"]
            self.assertEqual([event["alpha_id"] for event in checked], ["new1", "new2"])
        finally:
            cleanup_run_dir(run_dir)

    def test_repair_existing_alpha_with_field_blends_new_data(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/old1":
                    return {
                        "settings": {"region": "USA", "decay": 10},
                        "regular": {"code": "rank(close)"},
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/repair1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            client = FakeClient()

            summaries = repair_existing_alpha_with_field(
                client,
                recorder,
                "old1",
                "annual_basic_eps_value_fast_d1 - annual_basic_eps_value",
                blend_weights=[0.25],
            )

            self.assertEqual([summary.alpha_id for summary in summaries], ["new1"])
            self.assertEqual(
                client.posts[0][1]["regular"],
                "rank((rank(close))) + 0.25 * rank(annual_basic_eps_value_fast_d1 - annual_basic_eps_value)",
            )
            event = recorder.read_jsonl("simulation_events.jsonl")[0]
            self.assertEqual(event["workflow_stage"], "repair")
            self.assertEqual(event["field_expression"], "annual_basic_eps_value_fast_d1 - annual_basic_eps_value")
        finally:
            cleanup_run_dir(run_dir)

    def test_repair_existing_alpha_with_field_stops_after_rate_limit(self):
        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/old1":
                    return {
                        "settings": {"region": "USA", "decay": 10},
                        "regular": {"code": "rank(close)"},
                    }
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                response = requests.Response()
                response.status_code = 429
                raise requests.exceptions.HTTPError("429 Client Error", response=response)

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            client = FakeClient()

            summaries = repair_existing_alpha_with_field(
                client,
                recorder,
                "old1",
                "annual_basic_eps_value_fast_d1 - annual_basic_eps_value",
                blend_weights=[0.1, 0.2, 0.3],
            )

            self.assertEqual(summaries, [])
            self.assertEqual(len(client.posts), 1)
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["status_code"], 429)
        finally:
            cleanup_run_dir(run_dir)

    def test_run_expression_file_batch_clones_base_settings_and_records_tag(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/base1":
                    return {
                        "settings": {"region": "USA", "decay": 20, "neutralization": "INDUSTRY"},
                        "regular": {"code": "rank(close)"},
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/custom1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            batch_path = run_dir / "batch.jsonl"
            batch_path.write_text(
                json.dumps({"base_alpha_id": "base1", "tag": "unit_clean", "expression": "rank(open)"}) + "\n",
                encoding="utf-8",
            )
            recorder = RunRecorder(run_dir)
            client = FakeClient()

            summaries = run_expression_file_batch(client, recorder, batch_path)

            self.assertEqual([summary.alpha_id for summary in summaries], ["new1"])
            self.assertEqual(client.posts[0][1]["regular"], "rank(open)")
            self.assertEqual(client.posts[0][1]["settings"]["decay"], 20)
            record = recorder.read_jsonl("all_alphas.jsonl")[0]
            self.assertEqual(record["tag"], "unit_clean")
            self.assertEqual(record["base_alpha_id"], "base1")
        finally:
            cleanup_run_dir(run_dir)

    def test_run_expression_file_batch_multisimulation_submits_payload_list(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/base1":
                    return {"settings": {"region": "USA", "decay": 20}}
                if path in {"/alphas/new1", "/alphas/new2"}:
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path in {"/alphas/new1/check", "/alphas/new2/check"}:
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/multi1"})

            def request(self, method, path):
                if method == "GET" and path == "/simulations/multi1":
                    return FakeResponse(payload={"alpha": ["new1", "new2"]})
                raise AssertionError(f"unexpected request: {method} {path}")

        run_dir = make_run_dir()
        try:
            batch_path = run_dir / "batch.jsonl"
            batch_path.write_text(
                "\n".join(
                    [
                        json.dumps({"base_alpha_id": "base1", "tag": "first", "expression": "rank(open)"}),
                        json.dumps({"base_alpha_id": "base1", "tag": "second", "expression": "rank(close)"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            recorder = RunRecorder(run_dir)
            client = FakeClient()

            summaries = run_expression_file_batch(client, recorder, batch_path, submit_mode="multi")

            self.assertEqual([summary.alpha_id for summary in summaries], ["new1", "new2"])
            self.assertEqual(len(client.posts), 1)
            self.assertIsInstance(client.posts[0][1], list)
            self.assertEqual([payload["regular"] for payload in client.posts[0][1]], ["rank(open)", "rank(close)"])
            events = recorder.read_jsonl("simulation_events.jsonl")
            self.assertEqual([event["event"] for event in events], ["SUBMITTED", "SUBMITTED", "CHECKED", "CHECKED"])
            self.assertEqual([event["tag"] for event in events[:2]], ["first", "second"])
        finally:
            cleanup_run_dir(run_dir)

    def test_run_expression_file_batch_stops_after_rate_limit(self):
        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/base1":
                    return {
                        "settings": {"region": "USA", "decay": 20},
                        "regular": {"code": "rank(close)"},
                    }
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                response = requests.Response()
                response.status_code = 429
                raise requests.exceptions.HTTPError("429 Client Error", response=response)

        run_dir = make_run_dir()
        try:
            batch_path = run_dir / "batch.jsonl"
            batch_path.write_text(
                "\n".join(
                    [
                        json.dumps({"base_alpha_id": "base1", "tag": "first", "expression": "rank(open)"}),
                        json.dumps({"base_alpha_id": "base1", "tag": "second", "expression": "rank(close)"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            recorder = RunRecorder(run_dir)
            client = FakeClient()

            summaries = run_expression_file_batch(client, recorder, batch_path)

            self.assertEqual(summaries, [])
            self.assertEqual(len(client.posts), 1)
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["status_code"], 429)
        finally:
            cleanup_run_dir(run_dir)

    def test_run_expression_file_batch_skips_seen_hashes_in_run(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/base1":
                    return {
                        "settings": {"region": "USA", "decay": 20},
                        "regular": {"code": "rank(close)"},
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/custom1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            settings = {"region": "USA", "decay": 20}
            seen_hash = simulation_identity_hash("rank(open)", settings)
            batch_path = run_dir / "batch.jsonl"
            batch_path.write_text(
                "\n".join(
                    [
                        json.dumps({"base_alpha_id": "base1", "tag": "seen", "expression": "rank(open)"}),
                        json.dumps({"base_alpha_id": "base1", "tag": "new", "expression": "rank(close)"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            recorder = RunRecorder(run_dir)
            recorder.append_jsonl("simulation_events.jsonl", {"event": "SUBMITTED", "expression_hash": seen_hash})
            client = FakeClient()

            summaries = run_expression_file_batch(client, recorder, batch_path)

            self.assertEqual([summary.alpha_id for summary in summaries], ["new1"])
            self.assertEqual(len(client.posts), 1)
            self.assertEqual(client.posts[0][1]["regular"], "rank(close)")
        finally:
            cleanup_run_dir(run_dir)

    def test_run_expression_file_batch_skips_external_seen_hashes(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/base1":
                    return {"settings": {"region": "USA", "decay": 20}}
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/custom1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            settings = {"region": "USA", "decay": 20}
            seen_hash = simulation_identity_hash("rank(open)", settings)
            batch_path = run_dir / "batch.jsonl"
            batch_path.write_text(
                "\n".join(
                    [
                        json.dumps({"base_alpha_id": "base1", "tag": "external_seen", "expression": "rank(open)"}),
                        json.dumps({"base_alpha_id": "base1", "tag": "new", "expression": "rank(close)"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            recorder = RunRecorder(run_dir)
            client = FakeClient()

            summaries = run_expression_file_batch(client, recorder, batch_path, seen_hashes={seen_hash})

            self.assertEqual([summary.alpha_id for summary in summaries], ["new1"])
            self.assertEqual(len(client.posts), 1)
            self.assertEqual(client.posts[0][1]["regular"], "rank(close)")
        finally:
            cleanup_run_dir(run_dir)

    def test_run_expression_file_batch_filters_low_novelty_candidates(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/alphas/base1":
                    return {"settings": {"region": "USA", "decay": 20, "neutralization": "SUBINDUSTRY"}}
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/custom1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            batch_path = run_dir / "batch.jsonl"
            batch_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "base_alpha_id": "base1",
                                "tag": "crowded_pv",
                                "expression": "rank(ts_delta(open, 5))",
                            }
                        ),
                        json.dumps(
                            {
                                "base_alpha_id": "base1",
                                "tag": "fresh_fast_d1",
                                "expression": "group_neutralize(rank(snt_buzz_fast_d1 - snt_buzz), industry)",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            recorder = RunRecorder(run_dir)
            client = FakeClient()
            novelty_reference_records = [
                {
                    "expression": "rank(ts_delta(close, 5))",
                    "settings": {"neutralization": "SUBINDUSTRY"},
                    "benchmark_label": "repairable_signal",
                }
            ]

            summaries = run_expression_file_batch(
                client,
                recorder,
                batch_path,
                novelty_reference_records=novelty_reference_records,
                min_novelty_score=1,
            )

            self.assertEqual([summary.alpha_id for summary in summaries], ["new1"])
            self.assertEqual(len(client.posts), 1)
            self.assertEqual(client.posts[0][1]["regular"], "group_neutralize(rank(snt_buzz_fast_d1 - snt_buzz), industry)")
            rejections = recorder.read_jsonl("novelty_rejections.jsonl")
            self.assertEqual(rejections[0]["tag"], "crowded_pv")
            self.assertEqual(rejections[0]["novelty_label"], "low_novelty")
            self.assertIn("overlapping_data_family", rejections[0]["novelty_reasons"])
        finally:
            cleanup_run_dir(run_dir)

    def test_semantic_preview_marks_missing_regular_peer_like_field_batch(self):
        run_dir = make_run_dir()
        try:
            cache_path = run_dir / "cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "field_queries": [
                            {
                                "dataset_id": "news7",
                                "field_search": "",
                                "field_suffix": "_fast_d1",
                                "fields": [
                                    {
                                        "id": "news_item_count_300_fast_d1",
                                        "type": "MATRIX",
                                        "coverage": 1.0,
                                        "dataset": {"id": "news7"},
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 3, "run_root": str(TESTS_DIR)},
            )

            with redirect_stdout(io.StringIO()):
                preview = semantic_preview(
                    config,
                    str(cache_path),
                    dataset_id="news7",
                    field_search="",
                    field_suffix="_fast_d1",
                    template_mode="economic",
                    max_count=3,
                )

            expressions = [item["expression"] for item in preview["candidates"]]
            self.assertNotIn("rank(news_item_count_300_fast_d1 - news_item_count_300)", expressions)
            self.assertIn("rank(news_item_count_300_fast_d1)", expressions)
        finally:
            cleanup_run_dir(run_dir)

    def test_load_novelty_reference_records_reads_multiple_jsonl_files(self):
        run_dir = make_run_dir()
        try:
            first = run_dir / "first.jsonl"
            second = run_dir / "second.jsonl"
            first.write_text(json.dumps({"expression": "rank(close)"}) + "\n", encoding="utf-8")
            second.write_text(json.dumps({"expression": "rank(volume)"}) + "\n", encoding="utf-8")

            records = load_novelty_reference_records([str(first), str(second)])

            self.assertEqual([record["expression"] for record in records], ["rank(close)", "rank(volume)"])
        finally:
            cleanup_run_dir(run_dir)

    def test_run_expression_file_passes_novelty_gate_options_to_batch_runner(self):
        class FakeClient:
            def authenticate(self):
                return None

        run_dir = make_run_dir()
        try:
            batch_path = run_dir / "batch.jsonl"
            reference_path = run_dir / "refs.jsonl"
            batch_path.write_text(json.dumps({"base_alpha_id": "base1", "expression": "rank(open)"}) + "\n", encoding="utf-8")
            reference_path.write_text(json.dumps({"expression": "rank(close)"}) + "\n", encoding="utf-8")
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"run_root": str(TESTS_DIR)},
            )
            captured = {}

            def fake_batch(client, recorder, expression_file, **kwargs):
                captured.update(kwargs)
                return []

            with patch("wqb.cli.require_readiness_gate"), patch("wqb.cli.build_client", return_value=FakeClient()):
                with patch("wqb.cli.run_expression_file_batch", side_effect=fake_batch):
                    with redirect_stdout(io.StringIO()):
                        run_expression_file(
                            config,
                            str(batch_path),
                            run_dir=str(run_dir),
                            novelty_reference_files=[str(reference_path)],
                            min_novelty_score=2,
                        )

            self.assertEqual(captured["min_novelty_score"], 2)
            self.assertEqual(captured["novelty_reference_records"], [{"expression": "rank(close)"}])
        finally:
            cleanup_run_dir(run_dir)

    def test_parse_args_accepts_novelty_gate_options(self):
        argv = [
            "wqb",
            "run-expression-file",
            "--expression-file",
            "batch.jsonl",
            "--novelty-reference-file",
            "refs1.jsonl",
            "--novelty-reference-file",
            "refs2.jsonl",
            "--min-novelty-score",
            "2",
        ]

        with patch("sys.argv", argv):
            args = parse_args()

        self.assertEqual(args.novelty_reference_file, ["refs1.jsonl", "refs2.jsonl"])
        self.assertEqual(args.min_novelty_score, 2)

    def test_submit_candidate_payloads_sleeps_between_multi_chunks(self):
        class FakeResponse:
            def __init__(self, headers=None):
                self.headers = headers or {}

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self):
                self.posts = []

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": f"/simulations/multi{len(self.posts)}"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            client = FakeClient()
            payloads = [{"type": "REGULAR", "regular": f"rank(field_{idx})", "settings": {}} for idx in range(6)]
            metadata = [{"expression_hash": f"h{idx}", "expression": f"rank(field_{idx})"} for idx in range(6)]
            sleep_calls = []

            summaries = submit_candidate_payloads(
                client,
                recorder,
                payloads,
                metadata,
                submit_mode="multi",
                stage_prefix="unit",
                defer_poll=True,
                multi_chunk_sleep_seconds=7.0,
                sleep_func=sleep_calls.append,
            )

            self.assertEqual(summaries, [])
            self.assertEqual([len(post[1]) for post in client.posts], [5, 1])
            self.assertEqual(sleep_calls, [7.0])
        finally:
            cleanup_run_dir(run_dir)

    def test_submit_candidate_payloads_records_recoverable_multi_child_poll_error(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def post_json(self, path, payload):
                return FakeResponse(headers={"Location": "/simulations/parent"})

            def request(self, method, path):
                if path == "/simulations/parent":
                    return FakeResponse(payload={"children": ["child1"]})
                if path == "/simulations/child1":
                    raise SimulationPollTimeout("simulation poll exceeded Retry-After limit for /simulations/child1")
                raise AssertionError(f"unexpected request: {method} {path}")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            payloads = [{"type": "REGULAR", "regular": "rank(field_0)", "settings": {}}]
            metadata = [{"expression_hash": "h0", "expression": "rank(field_0)"}]

            summaries = submit_candidate_payloads(
                FakeClient(),
                recorder,
                payloads,
                metadata,
                submit_mode="multi",
                stage_prefix="unit",
            )

            self.assertEqual(summaries, [])
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["stage"], "unit_multi_child_poll")
            self.assertEqual(errors[0]["status_code"], "SIMULATION_POLL_TIMEOUT")
            self.assertEqual(errors[0]["progress_url"], "/simulations/parent")
            self.assertIn("/simulations/child1", errors[0]["message"])
            self.assertEqual(summarize_run_dir(run_dir)["in_flight_count"], 1)
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_uses_field_search_and_records_check(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []
                self.paths = []

            def get_json(self, path):
                self.paths.append(path)
                if path.startswith("/data-fields"):
                    return {
                        "results": [
                            {"id": "sentiment_a", "coverage": 1.0, "alphaCount": 10},
                            {"id": "sentiment_b", "coverage": 0.9, "alphaCount": 2},
                        ]
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/field1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config("configs/stage1_usa_d1.yaml", overrides={"max_alphas_per_round": 1})

            summaries = run_field_batch(FakeClient(), recorder, config, field_search="sentiment")

            self.assertEqual([summary.alpha_id for summary in summaries], ["new1"])
            self.assertIn("search=sentiment", recorder.read_jsonl("run_meta.jsonl")[0]["data_fields_path"])
            self.assertEqual(recorder.read_jsonl("all_alphas.jsonl")[0]["alpha_id"], "new1")
            self.assertTrue((run_dir / "candidates.csv").exists())
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_filters_suffix_and_uses_economic_templates(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {
                        "results": [
                            {"id": "snt_value", "coverage": 1.0, "alphaCount": 20},
                            {"id": "snt_value_fast_d1", "coverage": 0.95, "alphaCount": 4},
                        ]
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/field1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 1, "run_root": str(TESTS_DIR)},
            )
            client = FakeClient()

            run_field_batch(
                client,
                recorder,
                config,
                field_search="snt_value",
                dataset_id="socialmedia12",
                field_suffix="_fast_d1",
                template_mode="economic",
            )

            self.assertEqual(client.posts[0][1]["regular"], "rank(snt_value_fast_d1 - snt_value)")
            meta = recorder.read_jsonl("run_meta.jsonl")[0]
            self.assertEqual(meta["field_suffix"], "_fast_d1")
            self.assertEqual(meta["template_mode"], "economic")
            self.assertEqual(meta["seed_field_ids"], ["snt_value_fast_d1"])
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_marks_missing_regular_peer(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {
                        "results": [
                            {
                                "id": "relative_interest_score_3_fast_d1",
                                "type": "VECTOR",
                                "coverage": 1.0,
                                "alphaCount": 3,
                            }
                        ]
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/field1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 1, "run_root": str(TESTS_DIR)},
            )
            client = FakeClient()

            run_field_batch(
                client,
                recorder,
                config,
                dataset_id="search_interest",
                field_suffix="_fast_d1",
                template_mode="economic",
            )

            self.assertEqual(client.posts[0][1]["regular"], "rank(vec_avg(relative_interest_score_3_fast_d1))")
            self.assertEqual(recorder.read_jsonl("run_meta.jsonl")[0]["regular_peer_missing_ids"], ["relative_interest_score_3_fast_d1"])
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_exact_field_id_filters_catalog(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {
                        "results": [
                            {"id": "relative_interest_score_3_fast_d1", "type": "VECTOR", "coverage": 1.0, "alphaCount": 9},
                            {
                                "id": "trend_estimation_confidence_score_2_fast_d1",
                                "type": "VECTOR",
                                "coverage": 0.8,
                                "alphaCount": 1,
                            },
                        ]
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/field1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 1, "run_root": str(TESTS_DIR)},
            )
            client = FakeClient()

            run_field_batch(
                client,
                recorder,
                config,
                dataset_id="search_interest",
                field_suffix="_fast_d1",
                template_mode="economic",
                exact_field_id="trend_estimation_confidence_score_2_fast_d1",
            )

            self.assertEqual(
                client.posts[0][1]["regular"],
                "rank(vec_avg(trend_estimation_confidence_score_2_fast_d1))",
            )
            self.assertEqual(
                recorder.read_jsonl("run_meta.jsonl")[0]["exact_field_id"],
                "trend_estimation_confidence_score_2_fast_d1",
            )
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_accepts_relational_template_mode(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {
                        "results": [
                            {
                                "id": "annual_operating_cashflow_amount_fast_d1",
                                "type": "MATRIX",
                                "coverage": 0.95,
                                "alphaCount": 3,
                            },
                            {
                                "id": "fnd3_a_capex_fast_d1",
                                "type": "MATRIX",
                                "coverage": 0.94,
                                "alphaCount": 2,
                            },
                        ]
                    }
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/field1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 1, "run_root": str(TESTS_DIR)},
            )
            client = FakeClient()

            run_field_batch(
                client,
                recorder,
                config,
                dataset_id="fundamental3",
                field_suffix="_fast_d1",
                template_mode="relational",
            )

            self.assertEqual(
                client.posts[0][1]["regular"],
                "rank(annual_operating_cashflow_amount_fast_d1) - rank(fnd3_a_capex_fast_d1)",
            )
            self.assertEqual(recorder.read_jsonl("run_meta.jsonl")[0]["template_mode"], "relational")
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_can_use_cached_fields_without_field_api(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    raise AssertionError("field API should not be called when field cache is supplied")
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/field1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        run_dir = make_run_dir()
        cache_path = run_dir / "field_cache.json"
        cache_path.write_text(
            json.dumps(
                {
                    "field_queries": [
                        {
                            "dataset_id": "fundamental3",
                            "field_search": "cash",
                            "field_suffix": "_fast_d1",
                            "fields": [
                                {
                                    "id": "annual_operating_cashflow_amount_fast_d1",
                                    "type": "MATRIX",
                                    "coverage": 1.0,
                                },
                                {
                                    "id": "fnd3_a_capex_fast_d1",
                                    "type": "MATRIX",
                                    "coverage": 0.9,
                                },
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 1, "run_root": str(TESTS_DIR)},
            )
            client = FakeClient()

            run_field_batch(
                client,
                recorder,
                config,
                dataset_id="fundamental3",
                field_search="cash",
                field_suffix="_fast_d1",
                template_mode="semantic",
                field_cache_path=str(cache_path),
            )

            self.assertEqual(
                client.posts[0][1]["regular"],
                "rank(annual_operating_cashflow_amount_fast_d1) - rank(fnd3_a_capex_fast_d1)",
            )
            self.assertEqual(recorder.read_jsonl("run_meta.jsonl")[0]["field_source"], "cache")
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_semantic_uses_wide_seed_field_pool(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def get_json(self, path):
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                return FakeResponse(headers={"Location": "/simulations/field1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        filler_fields = []
        for index in range(10):
            filler_fields.append(
                {
                    "id": f"fnd3_q_assets_{index}_fast_d1",
                    "type": "MATRIX",
                    "coverage": 1.0 - index * 0.01,
                }
            )
            filler_fields.append(
                {
                    "id": f"fnd3_q_liabilities_{index}_fast_d1",
                    "type": "MATRIX",
                    "coverage": 0.99 - index * 0.01,
                }
            )
        cache_fields = filler_fields + [
            {"id": "annual_operating_cashflow_amount_fast_d1", "type": "MATRIX", "coverage": 0.5},
            {"id": "fnd3_a_capex_fast_d1", "type": "MATRIX", "coverage": 0.49},
        ]

        run_dir = make_run_dir()
        cache_path = run_dir / "field_cache.json"
        cache_path.write_text(
            json.dumps(
                {
                    "field_queries": [
                        {
                            "dataset_id": "fundamental3",
                            "field_search": "",
                            "field_suffix": "_fast_d1",
                            "fields": cache_fields,
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 1, "run_root": str(TESTS_DIR)},
            )

            run_field_batch(
                FakeClient(),
                recorder,
                config,
                dataset_id="fundamental3",
                field_suffix="_fast_d1",
                template_mode="semantic",
                field_cache_path=str(cache_path),
            )

            seed_field_ids = recorder.read_jsonl("run_meta.jsonl")[0]["seed_field_ids"]
            self.assertIn("annual_operating_cashflow_amount_fast_d1", seed_field_ids)
            self.assertIn("fnd3_a_capex_fast_d1", seed_field_ids)
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_records_workflow_stage_and_caps_scout(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {"results": [{"id": f"field_{idx}", "coverage": 1.0, "alphaCount": idx} for idx in range(20)]}
                alpha_index = int(path.split("/")[2].replace("new", "")) if path.startswith("/alphas/new") else None
                if alpha_index is not None and path.endswith("/check"):
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL"}]}}
                if alpha_index is not None:
                    return {"is": {"sharpe": 0.3, "fitness": 0.1, "turnover": 0.2}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": f"/simulations/field{len(self.posts)}"})

            def request(self, method, path):
                suffix = path.replace("/simulations/field", "")
                return FakeResponse(payload={"alpha": f"new{suffix}"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config("configs/stage1_usa_d1.yaml", overrides={"max_alphas_per_round": 20})
            client = FakeClient()

            run_field_batch(
                client,
                recorder,
                config,
                field_search="field",
                workflow_stage="scout",
                human_idea="Test simple data-field signal.",
            )

            self.assertEqual(len(client.posts), 30)
            meta = recorder.read_jsonl("run_meta.jsonl")[0]
            self.assertEqual(meta["workflow_stage"], "scout")
            self.assertEqual(meta["human_idea"], "Test simple data-field signal.")
            self.assertEqual(meta["requested_max_alphas"], 20)
            self.assertEqual(meta["effective_max_alphas"], 30)
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_skips_expression_seen_in_other_run_dirs(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {"results": [{"id": "field_0", "coverage": 1.0, "alphaCount": 0}]}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL"}]}}
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 0.3, "fitness": 0.1, "turnover": 0.2}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/field1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "new1"})

        old_run_dir = make_run_dir()
        run_dir = make_run_dir()
        try:
            old_recorder = RunRecorder(old_run_dir)
            old_recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "SUBMITTED",
                    "expression_hash": expression_hash("rank(field_0)"),
                    "expression": "rank(field_0)",
                    "progress_url": "/simulations/old",
                },
            )
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 2, "run_root": str(TESTS_DIR)},
            )
            client = FakeClient()

            run_field_batch(client, recorder, config, field_search="field", workflow_stage="discovery")

            self.assertEqual(len(client.posts), 2)
            self.assertEqual(client.posts[0][1]["regular"], "-rank(field_0)")
            self.assertEqual(client.posts[1][1]["regular"], "rank(ts_mean(field_0, 5))")
            duplicate_records = recorder.read_jsonl("duplicate_rejections.jsonl")
            self.assertEqual(duplicate_records[0]["expression"], "rank(field_0)")
            self.assertEqual(len(recorder.read_jsonl("planned_candidates.jsonl")), 2)
        finally:
            cleanup_run_dir(run_dir)
            cleanup_run_dir(old_run_dir)

    def test_run_field_batch_multisimulation_submits_payload_list(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {"results": [{"id": "field_0", "coverage": 1.0, "alphaCount": 0}]}
                if path.endswith("/check"):
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL"}]}}
                if path in {"/alphas/a1", "/alphas/a2"}:
                    return {"is": {"sharpe": 0.3, "fitness": 0.1, "turnover": 0.2}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/multi1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": ["a1", "a2"]})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 2, "run_root": str(TESTS_DIR)},
            )
            client = FakeClient()

            summaries = run_field_batch(
                client,
                recorder,
                config,
                field_search="field",
                workflow_stage="discovery",
                submit_mode="multi",
            )

            self.assertEqual(len(summaries), 2)
            self.assertEqual(len(client.posts), 1)
            self.assertIsInstance(client.posts[0][1], list)
            self.assertEqual(len(client.posts[0][1]), 2)
            submitted = recorder.read_jsonl("simulation_events.jsonl")
            self.assertEqual([item["event"] for item in submitted[:2]], ["SUBMITTED", "SUBMITTED"])
            self.assertEqual({item["progress_url"] for item in submitted[:2]}, {"/simulations/multi1"})
            self.assertEqual(len(recorder.read_jsonl("all_alphas.jsonl")), 2)
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_records_recoverable_poll_timeout(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {"results": [{"id": "field_0", "coverage": 1.0, "alphaCount": 0}]}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                return FakeResponse(headers={"Location": "/simulations/stuck"})

            def request(self, method, path):
                raise SimulationPollTimeout("simulation poll exceeded Retry-After limit for /simulations/stuck")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 1, "run_root": str(TESTS_DIR)},
            )

            summaries = run_field_batch(
                FakeClient(),
                recorder,
                config,
                field_search="field",
                workflow_stage="seed",
                submit_mode="serial",
            )

            self.assertEqual(summaries, [])
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["stage"], "run_field_batch_poll")
            self.assertEqual(errors[0]["status"], "RECOVERABLE")
            self.assertEqual(errors[0]["status_code"], "SIMULATION_POLL_TIMEOUT")
            self.assertEqual(errors[0]["progress_url"], "/simulations/stuck")
            self.assertEqual(summarize_run_dir(run_dir)["in_flight_count"], 1)
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_records_recoverable_multi_child_poll_timeout(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {"results": [{"id": "field_0", "coverage": 1.0, "alphaCount": 0}]}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                return FakeResponse(headers={"Location": "/simulations/parent"})

            def request(self, method, path):
                if path == "/simulations/parent":
                    return FakeResponse(payload={"children": ["child1"]})
                if path == "/simulations/child1":
                    raise SimulationPollTimeout("simulation poll exceeded Retry-After limit for /simulations/child1")
                raise AssertionError(f"unexpected request: {method} {path}")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 1, "run_root": str(TESTS_DIR)},
            )

            summaries = run_field_batch(
                FakeClient(),
                recorder,
                config,
                field_search="field",
                workflow_stage="seed",
                submit_mode="multi",
            )

            self.assertEqual(summaries, [])
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["stage"], "run_field_batch_multi_child_poll")
            self.assertEqual(errors[0]["status"], "RECOVERABLE")
            self.assertEqual(errors[0]["status_code"], "SIMULATION_POLL_TIMEOUT")
            self.assertEqual(errors[0]["progress_url"], "/simulations/parent")
            self.assertIn("/simulations/child1", errors[0]["message"])
            self.assertEqual(summarize_run_dir(run_dir)["in_flight_count"], 1)
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_multisimulation_sleeps_between_chunks(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {"results": [{"id": "field_0", "coverage": 1.0, "alphaCount": 0}]}
                if path in {"/alphas/a1", "/alphas/a2"}:
                    return {"is": {"sharpe": 0.3, "fitness": 0.1, "turnover": 0.2}}
                if path in {"/alphas/a1/check", "/alphas/a2/check"}:
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL"}]}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": f"/simulations/multi{len(self.posts)}"})

            def request(self, method, path):
                if path == "/simulations/multi1":
                    return FakeResponse(payload={"alpha": ["a1"]})
                if path == "/simulations/multi2":
                    return FakeResponse(payload={"alpha": ["a2"]})
                raise AssertionError(f"unexpected request: {method} {path}")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 2, "run_root": str(TESTS_DIR)},
            )
            client = FakeClient()

            with patch("wqb.cli.FIELD_BATCH_MULTI_CHUNK_SIZE", 1):
                with patch("wqb.cli.time.sleep") as sleep:
                    summaries = run_field_batch(
                        client,
                        recorder,
                        config,
                        field_search="field",
                        workflow_stage="discovery",
                        submit_mode="multi",
                        multi_chunk_sleep_seconds=7,
                    )

            self.assertEqual(len(summaries), 2)
            self.assertEqual(len(client.posts), 2)
            sleep.assert_called_once_with(7)
        finally:
            cleanup_run_dir(run_dir)

    def test_field_batch_passes_multi_chunk_sleep_to_runner(self):
        from wqb.cli import field_batch

        class FakeClient:
            def authenticate(self):
                return None

        run_dir = make_run_dir()
        try:
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 2, "run_root": str(TESTS_DIR)},
            )
            with patch("wqb.cli.require_readiness_gate"), patch("wqb.cli.make_run_dir", return_value=run_dir):
                with patch("wqb.cli.build_client", return_value=FakeClient()):
                    with patch("wqb.cli.run_field_batch", return_value=[]) as runner:
                        with redirect_stdout(io.StringIO()):
                            field_batch(config, field_search="field", multi_chunk_sleep_seconds=9)

            self.assertEqual(runner.call_args.kwargs["multi_chunk_sleep_seconds"], 9)
        finally:
            cleanup_run_dir(run_dir)

    def test_field_batch_blocks_before_auth_when_readiness_fails(self):
        from wqb.cli import field_batch

        class FakeClient:
            def authenticate(self):
                raise AssertionError("readiness gate should run before auth")

        run_dir = make_run_dir()
        try:
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 2, "run_root": str(TESTS_DIR), "knowledge_root": str(run_dir / "missing_knowledge")},
            )
            output = io.StringIO()
            with patch("wqb.cli.make_run_dir", return_value=run_dir), patch("wqb.cli.build_client", return_value=FakeClient()):
                with redirect_stdout(output):
                    field_batch(config, field_search="field")

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "readiness_blocked")
            self.assertTrue(Path(payload["readiness_markdown_path"]).exists())
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_multisimulation_can_defer_polling(self):
        class FakeResponse:
            def __init__(self, headers=None):
                self.headers = headers or {}

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {"results": [{"id": "field_0", "coverage": 1.0, "alphaCount": 0}]}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": f"/simulations/multi{len(self.posts)}"})

            def request(self, method, path):
                raise AssertionError("deferred polling should not request simulation progress")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 6, "run_root": str(TESTS_DIR)},
            )

            summaries = run_field_batch(
                FakeClient(),
                recorder,
                config,
                field_search="field",
                workflow_stage="discovery",
                submit_mode="multi",
                defer_poll=True,
            )

            self.assertEqual(summaries, [])
            events = recorder.read_jsonl("simulation_events.jsonl")
            self.assertEqual(len(events), 6)
            self.assertEqual(len(recorder.read_jsonl("all_alphas.jsonl")), 0)
            self.assertEqual(summarize_run_dir(run_dir)["in_flight_count"], 6)
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_multi_bad_request_falls_back_to_serial(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []
                self.serial_count = 0

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {"results": [{"id": "field_0", "coverage": 1.0, "alphaCount": 0}]}
                if path.endswith("/check"):
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL"}]}}
                if path in {"/alphas/a1", "/alphas/a2"}:
                    return {"is": {"sharpe": 0.3, "fitness": 0.1, "turnover": 0.2}}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                if isinstance(payload, list):
                    response = type("Response", (), {"status_code": 400})()
                    err = requests.exceptions.HTTPError("400 Client Error: Bad Request")
                    err.response = response
                    raise err
                self.serial_count += 1
                return FakeResponse(headers={"Location": f"/simulations/serial{self.serial_count}"})

            def request(self, method, path):
                suffix = path.replace("/simulations/serial", "")
                return FakeResponse(payload={"alpha": f"a{suffix}"})

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 2, "run_root": str(TESTS_DIR)},
            )
            client = FakeClient()

            summaries = run_field_batch(
                client,
                recorder,
                config,
                field_search="field",
                workflow_stage="discovery",
                submit_mode="multi",
            )

            self.assertEqual(len(summaries), 2)
            self.assertIsInstance(client.posts[0][1], list)
            self.assertFalse(isinstance(client.posts[1][1], list))
            self.assertEqual(len(recorder.read_jsonl("planned_candidates.jsonl")), 2)
            self.assertEqual(recorder.read_jsonl("run_errors.jsonl")[0]["stage"], "run_field_batch_multi_submit")
        finally:
            cleanup_run_dir(run_dir)

    def test_run_field_batch_multi_stops_after_rate_limit(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {"results": [{"id": "field_0", "coverage": 1.0, "alphaCount": 0}]}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                response = type("Response", (), {"status_code": 429})()
                err = requests.exceptions.HTTPError("429 Client Error: Too Many Requests")
                err.response = response
                raise err

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 5, "run_root": str(TESTS_DIR)},
            )
            client = FakeClient()

            with patch("wqb.cli.FIELD_BATCH_MULTI_CHUNK_SIZE", 2):
                summaries = run_field_batch(
                    client,
                    recorder,
                    config,
                    field_search="field",
                    workflow_stage="discovery",
                    submit_mode="multi",
                )

            self.assertEqual(summaries, [])
            self.assertEqual(len(client.posts), 1)
            self.assertEqual(recorder.read_jsonl("run_errors.jsonl")[0]["stage"], "run_field_batch_multi_submit")
        finally:
            cleanup_run_dir(run_dir)

    def test_field_batch_reports_submit_recoverable_error_when_no_progress_urls(self):
        from wqb.cli import field_batch

        class FakeClient:
            def authenticate(self):
                return None

            def get_json(self, path):
                if path.startswith("/data-fields"):
                    return {"results": [{"id": "fresh_status_field", "coverage": 1.0, "alphaCount": 0}]}
                raise AssertionError(f"unexpected path: {path}")

            def post_json(self, path, payload):
                raise requests.exceptions.ConnectionError("proxy reset")

        run_dir = make_run_dir()
        try:
            config = load_config(
                "configs/stage1_usa_d1.yaml",
                overrides={"max_alphas_per_round": 1, "run_root": str(TESTS_DIR)},
            )
            output = io.StringIO()
            with patch("wqb.cli.require_readiness_gate"), patch("wqb.cli.make_run_dir", return_value=run_dir), patch("wqb.cli.build_client", return_value=FakeClient()):
                with redirect_stdout(output):
                    field_batch(config, field_search="fresh_status_field", submit_mode="multi")

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "submit_recoverable_error")
            self.assertEqual(summarize_run_dir(run_dir)["submitted_count"], 0)
            self.assertEqual(summarize_run_dir(run_dir)["checked_count"], 0)
        finally:
            cleanup_run_dir(run_dir)

    def test_retry_planned_candidates_submits_only_unsubmitted_items(self):
        class FakeResponse:
            def __init__(self, headers=None, payload=None):
                self.headers = headers or {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.posts = []

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": "/simulations/retry1"})

            def request(self, method, path):
                return FakeResponse(payload={"alpha": "retryAlpha"})

            def get_json(self, path):
                if path == "/alphas/retryAlpha/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL"}]}}
                if path == "/alphas/retryAlpha":
                    return {"is": {"sharpe": 0.1, "fitness": 0.1, "turnover": 0.2}}
                raise AssertionError(f"unexpected path: {path}")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config("configs/stage1_usa_d1.yaml", overrides={"run_root": str(TESTS_DIR)})
            first = {"expression": "rank(already_submitted)", "expression_hash": "seen_hash"}
            second = {"expression": "rank(needs_retry)", "expression_hash": "retry_hash"}
            recorder.append_jsonl("planned_candidates.jsonl", first)
            recorder.append_jsonl("planned_candidates.jsonl", second)
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {"event": "SUBMITTED", "expression_hash": "seen_hash", "progress_url": "/simulations/old"},
            )

            summaries = retry_planned_candidates(FakeClient(), recorder, config, submit_mode="serial")

            self.assertEqual([summary.alpha_id for summary in summaries], ["retryAlpha"])
            self.assertEqual(len(recorder.read_jsonl("retry_planned_skips.jsonl")), 1)
            submitted = [event for event in recorder.read_jsonl("simulation_events.jsonl") if event.get("event") == "SUBMITTED"]
            self.assertEqual(len(submitted), 2)
            self.assertEqual(submitted[-1]["expression_hash"], "retry_hash")
        finally:
            cleanup_run_dir(run_dir)

    def test_retry_planned_candidates_can_defer_polling(self):
        class FakeResponse:
            def __init__(self, headers=None):
                self.headers = headers or {}

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self):
                self.posts = []

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                return FakeResponse(headers={"Location": f"/simulations/retry{len(self.posts)}"})

            def request(self, method, path):
                raise AssertionError("deferred retry should not request simulation progress")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config("configs/stage1_usa_d1.yaml", overrides={"run_root": str(TESTS_DIR)})
            for index in range(4):
                recorder.append_jsonl(
                    "planned_candidates.jsonl",
                    {"expression": f"rank(field_{index})", "expression_hash": f"hash_{index}"},
                )

            with patch("wqb.cli.FIELD_BATCH_MULTI_CHUNK_SIZE", 2):
                summaries = retry_planned_candidates(
                    FakeClient(),
                    recorder,
                    config,
                    submit_mode="multi",
                    defer_poll=True,
                )

            self.assertEqual(summaries, [])
            submitted = [event for event in recorder.read_jsonl("simulation_events.jsonl") if event.get("event") == "SUBMITTED"]
            self.assertEqual(len(submitted), 4)
            self.assertEqual(len(recorder.read_jsonl("all_alphas.jsonl")), 0)
            self.assertEqual(summarize_run_dir(run_dir)["in_flight_count"], 4)
        finally:
            cleanup_run_dir(run_dir)

    def test_retry_planned_serial_stops_after_rate_limit(self):
        class FakeClient:
            def __init__(self):
                self.posts = []

            def post_json(self, path, payload):
                self.posts.append((path, payload))
                response = requests.Response()
                response.status_code = 429
                raise requests.exceptions.HTTPError("429 Client Error", response=response)

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            config = load_config("configs/stage1_usa_d1.yaml", overrides={"run_root": str(TESTS_DIR)})
            for index in range(3):
                recorder.append_jsonl(
                    "planned_candidates.jsonl",
                    {"expression": f"rank(field_{index})", "expression_hash": f"hash_{index}"},
                )
            client = FakeClient()

            summaries = retry_planned_candidates(
                client,
                recorder,
                config,
                submit_mode="serial",
                defer_poll=True,
            )

            self.assertEqual(summaries, [])
            self.assertEqual(len(client.posts), 1)
            self.assertEqual(len(recorder.read_jsonl("simulation_events.jsonl")), 0)
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["status_code"], 429)
        finally:
            cleanup_run_dir(run_dir)

    def test_retry_planned_cli_reports_pending_recovery(self):
        from wqb.cli import retry_planned

        class FakeClient:
            def authenticate(self):
                return None

        run_dir = make_run_dir()
        try:
            config = load_config("configs/stage1_usa_d1.yaml", overrides={"run_root": str(TESTS_DIR)})
            output = io.StringIO()
            with patch("wqb.cli.require_readiness_gate"), patch("wqb.cli.build_client", return_value=FakeClient()):
                with patch("wqb.cli.retry_planned_candidates", return_value=[]):
                    with patch("wqb.cli.summarize_run_dir", return_value={"in_flight_count": 1, "submitted_count": 1, "error_counts": {}}):
                        with redirect_stdout(output):
                            retry_planned(config, str(run_dir), submit_mode="multi")

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["status"], "pending_recovery")
            self.assertEqual(payload["run_dir"], str(run_dir))
        finally:
            cleanup_run_dir(run_dir)

    def test_field_batch_records_recoverable_auth_error(self):
        from wqb.cli import field_batch

        class FakeClient:
            def authenticate(self):
                raise requests.exceptions.ConnectionError("proxy reset")

        run_dir = make_run_dir()
        try:
            config = load_config("configs/stage1_usa_d1.yaml", overrides={"max_alphas_per_round": 1})
            output = io.StringIO()
            with patch("wqb.cli.require_readiness_gate"), patch("wqb.cli.make_run_dir", return_value=run_dir), patch("wqb.cli.build_client", return_value=FakeClient()):
                with redirect_stdout(output):
                    field_batch(config, field_search="x")

            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "auth_recoverable_error")
            errors = RunRecorder(run_dir).read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["stage"], "field_batch_auth")
            self.assertEqual(errors[0]["status_code"], "NETWORK_ERROR")
        finally:
            cleanup_run_dir(run_dir)

    def test_complete_in_flight_simulations_records_recoverable_poll_error(self):
        class FakeClient:
            def request(self, method, path):
                raise requests.exceptions.ConnectionError("proxy reset")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "SUBMITTED",
                    "parent_alpha_id": "old1",
                    "expression_hash": "abc",
                    "progress_url": "/simulations/abc",
                    "operator_replacements": {},
                },
            )

            completed = complete_in_flight_simulations(FakeClient(), recorder)

            self.assertEqual(completed, [])
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["stage"], "complete_in_flight")
            self.assertEqual(errors[0]["status_code"], "NETWORK_ERROR")
            self.assertEqual(summarize_run_dir(run_dir)["in_flight_count"], 1)
        finally:
            cleanup_run_dir(run_dir)

    def test_complete_in_flight_simulations_records_recoverable_child_poll_error(self):
        class FakeResponse:
            def __init__(self, payload=None):
                self.headers = {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def request(self, method, path):
                if path == "/simulations/parent1":
                    return FakeResponse(payload={"children": ["child1"]})
                if path == "/simulations/child1":
                    raise SimulationPollTimeout("simulation poll exceeded Retry-After limit for /simulations/child1")
                raise AssertionError(f"unexpected path: {path}")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "SUBMITTED",
                    "parent_alpha_id": "old1",
                    "expression_hash": "abc",
                    "progress_url": "/simulations/parent1",
                    "operator_replacements": {},
                },
            )

            completed = complete_in_flight_simulations(FakeClient(), recorder)

            self.assertEqual(completed, [])
            errors = recorder.read_jsonl("run_errors.jsonl")
            self.assertEqual(errors[0]["stage"], "complete_in_flight_child_poll")
            self.assertEqual(errors[0]["status"], "RECOVERABLE")
            self.assertEqual(errors[0]["status_code"], "SIMULATION_POLL_TIMEOUT")
            self.assertEqual(errors[0]["progress_url"], "/simulations/parent1")
            self.assertIn("/simulations/child1", errors[0]["message"])
            self.assertEqual(summarize_run_dir(run_dir)["in_flight_count"], 1)
        finally:
            cleanup_run_dir(run_dir)

    def test_complete_in_flight_simulations_resolves_multisimulation_children(self):
        class FakeResponse:
            def __init__(self, payload=None):
                self.headers = {}
                self.payload = payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def request(self, method, path):
                if path == "/simulations/parent1":
                    return FakeResponse(payload={"children": ["child1", "child2"]})
                if path == "/simulations/child1":
                    return FakeResponse(payload={"alpha": "new1"})
                if path == "/simulations/child2":
                    return FakeResponse(payload={"alpha": "new2"})
                raise AssertionError(f"unexpected path: {path}")

            def get_json(self, path):
                if path == "/alphas/new1":
                    return {"is": {"sharpe": 1.7, "fitness": 1.2, "turnover": 0.2}}
                if path == "/alphas/new1/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "PASS"}]}}
                if path == "/alphas/new2":
                    return {"is": {"sharpe": 0.7, "fitness": 0.4, "turnover": 0.2}}
                if path == "/alphas/new2/check":
                    return {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL"}]}}
                raise AssertionError(f"unexpected path: {path}")

        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            for sim_hash, decay in [("abc1", 15), ("abc2", 20)]:
                recorder.append_jsonl(
                    "simulation_events.jsonl",
                    {
                        "event": "SUBMITTED",
                        "parent_alpha_id": "old1",
                        "expression_hash": sim_hash,
                        "progress_url": "/simulations/parent1",
                        "setting_variant": {"decay": decay},
                    },
                )

            completed = complete_in_flight_simulations(FakeClient(), recorder)

            self.assertEqual(completed, ["new1", "new2"])
            checked = [event for event in recorder.read_jsonl("simulation_events.jsonl") if event["event"] == "CHECKED"]
            self.assertEqual([event["alpha_id"] for event in checked], ["new1", "new2"])
            self.assertEqual(len(recorder.read_jsonl("all_alphas.jsonl")), 2)
        finally:
            cleanup_run_dir(run_dir)


class WorkflowOrchestratorCliTests(unittest.TestCase):
    def test_cli_and_console_defaults_share_run_root(self):
        from wqb.cli import default_orchestrator_paths
        from wqb.console_state import default_console_paths

        self.assertEqual(
            default_orchestrator_paths({"knowledge_root": "knowledge"}).run_root,
            default_console_paths().runs_root,
        )

    def test_parse_args_accepts_workflow_start(self):
        with patch(
            "sys.argv",
            ["wqb", "workflow-start", "--objective", "Power Pool", "--selected-option-id", "option-1"],
        ):
            from wqb.cli import parse_args

            args = parse_args()

        self.assertEqual(args.command, "workflow-start")
        self.assertEqual(args.objective, "Power Pool")

    def test_workflow_status_dispatches_orchestrator(self):
        from wqb.cli import main

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "workflow.yaml"
            run_root = root / "configured_runs"
            knowledge_root = root / "configured_knowledge"
            config_path.write_text(
                "\n".join(
                    [
                        "region: USA",
                        "universe: TOP3000",
                        "delay: 1",
                        f"run_root: {run_root.as_posix()}",
                        f"knowledge_root: {knowledge_root.as_posix()}",
                    ]
                ),
                encoding="utf-8",
            )
            with patch("sys.argv", ["wqb", "workflow-status", "--config", str(config_path)]), patch(
                "wqb.cli.WorkflowOrchestrator"
            ) as orchestrator_cls, redirect_stdout(output):
                orchestrator_cls.return_value.status.return_value = {"status": "created"}
                main()

        self.assertEqual(json.loads(output.getvalue())["status"], "created")
        paths = orchestrator_cls.call_args.args[0]
        self.assertEqual(paths.run_root, run_root)
        self.assertEqual(paths.knowledge_root, knowledge_root)

    def test_workflow_status_run_dir_overrides_configured_run_root(self):
        from wqb.cli import main

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "workflow.yaml"
            configured_run_root = root / "configured_runs"
            override_run_root = root / "console_runs"
            config_path.write_text(
                "\n".join(
                    [
                        "region: USA",
                        "universe: TOP3000",
                        "delay: 1",
                        f"run_root: {configured_run_root.as_posix()}",
                    ]
                ),
                encoding="utf-8",
            )
            with patch("sys.argv", ["wqb", "workflow-status", "--config", str(config_path), "--run-dir", str(override_run_root)]), patch(
                "wqb.cli.WorkflowOrchestrator"
            ) as orchestrator_cls, redirect_stdout(output):
                orchestrator_cls.return_value.status.return_value = {"status": "created"}
                main()

        paths = orchestrator_cls.call_args.args[0]
        self.assertEqual(paths.run_root, override_run_root)

    def test_workflow_continue_dispatches_orchestrator(self):
        from wqb.cli import main

        output = io.StringIO()
        with patch("sys.argv", ["wqb", "workflow-continue", "--now", "2026-07-12T00:01:00Z"]), patch(
            "wqb.cli.WorkflowOrchestrator"
        ) as orchestrator_cls, redirect_stdout(output):
            orchestrator_cls.return_value.continue_once.return_value = {"current_stage": "schedule"}
            main()

        orchestrator_cls.return_value.continue_once.assert_called_once_with("2026-07-12T00:01:00Z")
        self.assertEqual(json.loads(output.getvalue())["current_stage"], "schedule")

    def test_workflow_import_scout_seed_artifacts_dispatches_orchestrator(self):
        from wqb.cli import main

        output = io.StringIO()
        argv = [
            "wqb",
            "workflow-import-scout-seed-artifacts",
            "--source-run-id",
            "source-stage1",
            "--now",
            "2026-07-12T00:04:00Z",
        ]
        with patch("sys.argv", argv), patch("wqb.cli.WorkflowOrchestrator") as orchestrator_cls, redirect_stdout(output):
            orchestrator_cls.return_value.import_scout_seed_artifacts.return_value = {
                "status": "paused",
                "imported_artifacts": ["candidates.csv"],
            }
            main()

        orchestrator_cls.return_value.import_scout_seed_artifacts.assert_called_once_with(
            "source-stage1",
            "2026-07-12T00:04:00Z",
        )
        self.assertEqual(json.loads(output.getvalue())["imported_artifacts"], ["candidates.csv"])

    def test_workflow_request_candidate_approval_loads_json_and_dispatches(self):
        from wqb.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            candidate_path = Path(tmp) / "candidates.json"
            candidates = [{"candidate_id": "c1"}]
            candidate_path.write_text(json.dumps(candidates), encoding="utf-8")
            output = io.StringIO()
            argv = [
                "wqb", "workflow-request-candidate-approval", "--candidate-json", str(candidate_path),
                "--now", "2026-07-12T00:01:00Z",
            ]
            with patch("sys.argv", argv), patch("wqb.cli.WorkflowOrchestrator") as orchestrator_cls, redirect_stdout(output):
                orchestrator_cls.return_value.request_candidate_approval.return_value = {"status": "waiting_for_user"}
                main()

        orchestrator_cls.return_value.request_candidate_approval.assert_called_once_with(
            candidates, "2026-07-12T00:01:00Z"
        )
        self.assertEqual(json.loads(output.getvalue())["status"], "waiting_for_user")

    def test_workflow_request_candidate_approval_rejects_non_object_list_items(self):
        from wqb.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            candidate_path = Path(tmp) / "candidates.json"
            candidate_path.write_text(json.dumps(["c1"]), encoding="utf-8")
            with patch("sys.argv", ["wqb", "workflow-request-candidate-approval", "--candidate-json", str(candidate_path)]):
                with self.assertRaisesRegex(SystemExit, "list of objects"):
                    main()

    def test_workflow_update_candidate_status_dispatches_through_orchestrator(self):
        from wqb.cli import main

        output = io.StringIO()
        argv = [
            "wqb",
            "workflow-update-candidate-status",
            "--candidate-id",
            "c1",
            "--candidate-version",
            "1",
            "--candidate-expression-hash",
            "h1",
            "--candidate-status",
            "manually_submitted",
            "--now",
            "2026-07-12T01:00:00Z",
        ]
        with patch("sys.argv", argv), patch("wqb.cli.WorkflowOrchestrator") as orchestrator_cls, redirect_stdout(output):
            orchestrator_cls.return_value.update_candidate_status.return_value = {"status": "manually_submitted"}
            main()

        orchestrator_cls.return_value.update_candidate_status.assert_called_once_with(
            "c1", 1, "h1", "manually_submitted", "2026-07-12T01:00:00Z"
        )

    def test_workflow_update_candidate_status_forwards_source_run_selector(self):
        from wqb.cli import main

        output = io.StringIO()
        argv = [
            "wqb",
            "workflow-update-candidate-status",
            "--candidate-id", "c1",
            "--candidate-version", "1",
            "--candidate-expression-hash", "h1",
            "--candidate-status", "manually_submitted",
            "--source-run-id", "run-completed",
            "--now", "2026-07-12T01:00:00Z",
        ]
        with patch("sys.argv", argv), patch("wqb.cli.WorkflowOrchestrator") as orchestrator_cls, redirect_stdout(output):
            orchestrator_cls.return_value.update_candidate_status.return_value = {
                "status": "manually_submitted"
            }
            main()

        orchestrator_cls.return_value.update_candidate_status.assert_called_once_with(
            "c1",
            1,
            "h1",
            "manually_submitted",
            "2026-07-12T01:00:00Z",
            source_run_id="run-completed",
        )

    def test_workflow_update_candidate_status_rejects_invalidated_without_dispatch(self):
        from wqb.cli import main

        output = io.StringIO()
        error = io.StringIO()
        argv = [
            "wqb",
            "workflow-update-candidate-status",
            "--candidate-id", "c1",
            "--candidate-version", "1",
            "--candidate-expression-hash", "h1",
            "--candidate-status", "invalidated",
        ]
        with (
            patch("sys.argv", argv),
            patch("wqb.cli.WorkflowOrchestrator") as orchestrator_cls,
            redirect_stdout(output),
            redirect_stderr(error),
        ):
            orchestrator_cls.return_value.update_candidate_status.return_value = {"status": "invalidated"}
            with self.assertRaises(SystemExit) as raised:
                main()

        self.assertEqual(raised.exception.code, 2)
        orchestrator_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
