import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import requests

from wqb.expression import expression_hash
from wqb.cli import (
    authenticate_for_run,
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


class CliTests(unittest.TestCase):
    def test_default_knowledge_root_uses_shared_workspace_vault(self):
        expected = TESTS_DIR.parents[2] / "knowledge"

        self.assertEqual(default_knowledge_root(), expected)
        self.assertEqual(Path(default_option_output_dir()), expected / "wiki" / "70_decisions")

        custom_root = TESTS_DIR / "_custom_knowledge"
        with patch.dict(os.environ, {"BRAIN_KNOWLEDGE_ROOT": str(custom_root)}):
            self.assertEqual(default_knowledge_root(), custom_root)
            self.assertEqual(Path(default_option_output_dir()), custom_root / "wiki" / "70_decisions")

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
            with patch("wqb.cli.build_client", return_value=FakeClient()), patch(
                "wqb.cli.refresh_incentive_snapshot", return_value=snapshot
            ):
                result = plan_research_options({"request_timeout_seconds": 1}, max_options=3, output_dir=tmp)

            self.assertGreaterEqual(result["option_count"], 1)
            self.assertTrue(Path(result["jsonl_path"]).exists())
            self.assertTrue(Path(result["markdown_path"]).exists())

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

            with patch("wqb.cli.build_client", return_value=FakeClient()):
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
            with patch("wqb.cli.make_run_dir", return_value=run_dir):
                with patch("wqb.cli.build_client", return_value=FakeClient()):
                    with patch("wqb.cli.run_field_batch", return_value=[]) as runner:
                        with redirect_stdout(io.StringIO()):
                            field_batch(config, field_search="field", multi_chunk_sleep_seconds=9)

            self.assertEqual(runner.call_args.kwargs["multi_chunk_sleep_seconds"], 9)
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
            with patch("wqb.cli.make_run_dir", return_value=run_dir), patch("wqb.cli.build_client", return_value=FakeClient()):
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
            with patch("wqb.cli.build_client", return_value=FakeClient()):
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
            with patch("wqb.cli.make_run_dir", return_value=run_dir), patch("wqb.cli.build_client", return_value=FakeClient()):
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


if __name__ == "__main__":
    unittest.main()
