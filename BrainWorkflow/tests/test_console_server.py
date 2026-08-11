import json
from http.client import HTTPConnection
import sys
import tempfile
import threading
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wqb.console_server import build_action_command, create_console_proposal, make_console_server, render_dashboard, render_proposals, render_runtime_fragments, run_console_action, update_console_proposal_decision
from wqb.console_state import ConsolePaths, load_console_state
from wqb.data_ledger_compile import compile_data_ledger_from_raw
from wqb.knowledge_clean_compile import apply_obsolete_active_cleanup
from wqb.workflow_proposals import load_workflow_proposals


def make_paths(root: Path) -> ConsolePaths:
    """Input: temp root. Output: ConsolePaths. Create a server path fixture."""
    return ConsolePaths(root, root / "BrainWorkflow", root / "knowledge", root / "runs", root / "milestone.md", root / "todo.md", root / "runs" / "console_jobs")


def valid_option(**overrides):
    """Input: optional option-card overrides. Output: valid option-card row. Build durable console fixtures."""
    row = {
        "title": "Power Pool",
        "primary_incentive": "power_pool",
        "secondary_incentives": [],
        "why_now": "Fresh measured coverage is available.",
        "candidate_scope": "USA D1 TOP3000",
        "expected_asset_value": "A measured research direction.",
        "correlation_risk": "low",
        "resource_cost": "small",
        "evidence": [{"source_type": "ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "title": "Ledger", "timestamp": "2026-07-16"}],
        "failure_modes": [],
        "decision_needed": "Start the selected scope.",
        "score": {"total": 1.0, "components": {}, "penalties": {}, "reasons": ["measured coverage"]},
    }
    return {**row, **overrides}


def request_from_console_server(server, method: str, path: str, body: str = "") -> tuple[int, dict[str, str], bytes]:
    """Input: local Console server and HTTP request values. Output: status, headers, body. Exercise one handler request."""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection(*server.server_address, timeout=5)
    try:
        headers = {"Content-Type": "application/x-www-form-urlencoded"} if body else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class ConsoleServerTests(unittest.TestCase):
    def test_render_dashboard_has_single_page_timeline_control_center(self):
        state = {
            "readiness": {"exists": True, "passed": False},
            "freshness": {"exists": True, "valid": True, "stale_count": 1, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 60046, "scope_count": 7, "data_set_count": 453, "error_count": 0, "status": "completed"},
            "option_cards": [valid_option()],
            "startable_scopes": [{"region": "USA", "delay": 1, "universe": "TOP3000"}],
            "jobs": [{"job_id": "job-1", "action": "capture-platform-data-fields", "status": "completed"}],
            "active_workflow": {"exists": False},
            "workflow_events": [],
            "approved_queue": [],
            "queue_diagnostics": [],
            "proposal_counts": {"proposed": 1},
            "proposals": [{"proposal_id": "p1", "title": "Improve workflow", "status": "proposed"}],
            "ai_checkpoints": [{"checkpoint_id": "ai-1", "reason": "Explain blocker.", "status": "pending"}],
            "timeline": [
                {"stage_id": "platform_data_capture", "label": "Platform data capture", "status": "completed", "source": "deterministic", "explanation": "Captured raw fields.", "evidence_path": "raw/platform/data_fields/2026-07-30"},
                {"stage_id": "ai_checkpoint", "label": "AI checkpoint", "status": "waiting", "source": "ai_judgment", "explanation": "Explain blocker.", "evidence_path": "runs/readiness/report.md"},
            ],
            "current_work": {"title": "Knowledge health", "status": "blocked", "next_action": "Run knowledge health check", "details": ["Freshness has stale artifacts."], "evidence_paths": []},
        }

        html = render_dashboard(state)

        self.assertIn("BrainWorkflow Control Center", html)
        self.assertIn("Objective and Gate Summary", html)
        self.assertIn("Runtime Timeline", html)
        self.assertIn("Current Work", html)
        self.assertIn("Decisions and Approvals", html)
        self.assertIn("AI Checkpoints", html)
        self.assertIn("Platform data capture", html)
        self.assertIn("Explain blocker.", html)

    def test_render_dashboard_wires_interaction_capture_form(self):
        html = render_dashboard({"active_workflow": {"exists": False}, "jobs": []})

        self.assertIn('name="action" value="capture-interaction-note"', html)
        self.assertIn('name="category"', html)
        self.assertIn('value="workflow_rule"', html)
        self.assertIn('value="engineering_lesson"', html)
        self.assertIn('value="factor_lesson"', html)
        self.assertIn('value="proposal_seed"', html)

    def test_runtime_fragments_include_refreshed_timeline_work_badges_and_jobs(self):
        state = {
            "readiness": {"passed": True},
            "freshness": {"valid": True, "stale_count": 0, "missing_count": 0},
            "data_coverage": {"field_count": 2, "scope_count": 1, "data_set_count": 1, "error_count": 0, "status": "running"},
            "jobs": [{"job_id": "job-live", "action": "capture-platform-data-fields", "status": "running"}],
            "timeline": [{"label": "Platform data capture", "status": "running", "source": "deterministic", "explanation": "2 fields captured.", "evidence_path": "raw/platform/data_fields/2026-07-30"}],
            "current_work": {"title": "Capturing platform data", "status": "running", "next_action": "Wait for completion", "details": ["2 fields"], "evidence_paths": ["raw/platform/data_fields/2026-07-30"]},
        }

        fragments = render_runtime_fragments(state)
        html = render_dashboard(state)

        self.assertIn("Platform data capture", fragments["timeline"])
        self.assertIn("Capturing platform data", fragments["current_work"])
        self.assertIn("Data fields", fragments["objective"])
        self.assertIn("job-live", fragments["recent_jobs"])
        self.assertIn("data-runtime-fragment='timeline'", html)
        self.assertIn("/api/fragments", html)

    def test_render_dashboard_polling_does_not_overlap_refresh_requests(self):
        html = render_dashboard({"active_workflow": {"exists": False}, "jobs": []})

        self.assertIn("let refreshInFlight = false", html)
        self.assertIn("if (refreshInFlight) return", html)
        self.assertIn("refreshInFlight = true", html)
        self.assertIn("refreshInFlight = false", html)

    def test_render_dashboard_labels_cache_data_as_not_authoritative(self):
        state = {
            "readiness": {"exists": True, "passed": False},
            "freshness": {"valid": True, "stale_count": 0, "missing_count": 0},
            "data_coverage": {"field_count": 14, "scope_count": 1, "data_set_count": 4, "error_count": 0, "status": "completed"},
            "data_authority": {"record_count": 14, "authoritative_measured_count": 0, "seed_cache_count": 14, "unclassified_count": 0, "authoritative_ready": False},
            "knowledge_contracts": {"issue_count": 2, "legacy_count": 1, "issues": []},
            "semantic_ledgers": {"operator_semantic_count": 9, "matrix_ready_template_count": 4, "active_benchmark_rule_count": 3, "ready": True},
            "option_cards": [{"option_id": "option-1", "title": "Power Pool", "maintenance_blockers": ["Authoritative data ledger is missing."]}],
            "startable_scopes": [],
            "jobs": [],
            "active_workflow": {"exists": False},
            "approved_queue": [],
            "queue_diagnostics": [],
            "workflow_events": [],
            "proposal_counts": {"accepted_for_implementation": 1},
            "schedule": {"preview": ""},
        }

        html = render_dashboard(state)

        self.assertIn("Data Authority", html)
        self.assertIn("seed/cache", html)
        self.assertIn("authoritative measured", html)
        self.assertIn("Knowledge Contracts", html)
        self.assertIn("operator semantics</strong> 9", html)
        self.assertIn("matrix-ready templates", html)
        self.assertIn("active benchmark rules", html)
        self.assertIn("Authoritative data ledger is missing", html)

    def test_render_dashboard_exposes_research_progress_and_knowledge_controls(self):
        state = {
            "readiness": {"exists": True, "passed": True, "blocked": False},
            "freshness": {"exists": True, "stale_count": 0, "missing_count": 0},
            "option_cards": [valid_option()],
            "schedule": {"preview": "# Schedule"},
            "jobs": [{"job_id": "job1", "status": "completed", "action": "readiness-check"}],
            "proposal_counts": {"proposed": 1},
            "active_workflow": {"exists": False},
            "approved_queue": [],
            "queue_diagnostics": [],
        }

        html = render_dashboard(state)

        self.assertIn("Workflow Console", html)
        self.assertIn("Research Start", html)
        self.assertIn("Knowledge Maintenance", html)
        self.assertIn("Workflow Progress", html)
        self.assertIn("Power Pool", html)

    def test_render_dashboard_uses_selectable_option_cards_without_manual_option_id_input(self):
        state = {
            "readiness": {"exists": True, "passed": True, "blocked": False},
            "freshness": {"exists": True, "valid": True, "record_count": 6, "stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120, "scope_count": 4, "data_set_count": 8, "error_count": 0, "status": "completed"},
            "startable_scopes": [{"region": "USA", "delay": 1, "universe": "TOP3000"}],
            "option_cards": [valid_option(score={"total": 9.0, "components": {}, "penalties": {}, "reasons": ["measured coverage"]})],
            "schedule": {"preview": "# Schedule"},
            "jobs": [],
            "proposal_counts": {},
            "active_workflow": {"exists": False},
            "approved_queue": [],
            "queue_diagnostics": [],
            "workflow_events": [],
        }

        html = render_dashboard(state)

        self.assertIn('type="radio"', html)
        self.assertIn('name="selected_option_id"', html)
        self.assertIn('name="selected_scope"', html)
        self.assertIn('value="option-1"', html)
        self.assertIn('value="workflow-start-from-option"', html)
        self.assertNotIn('name="selected_option_id" value="option-1" checked', html)
        self.assertNotIn('<input name="objective"', html)
        self.assertNotIn('type="text" name="selected_option_id"', html)

    def test_render_dashboard_exposes_scout_seed_artifact_import_control(self):
        state = {
            "readiness": {"exists": True, "passed": True, "blocked": False},
            "freshness": {"exists": True, "valid": True, "record_count": 6, "stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120, "scope_count": 4, "data_set_count": 8, "error_count": 0, "status": "completed"},
            "startable_scopes": [],
            "option_cards": [],
            "schedule": {"preview": "# Schedule"},
            "jobs": [],
            "proposal_counts": {},
            "active_workflow": {"exists": True, "run_id": "active", "current_stage": "scout_seed", "status": "paused"},
            "approved_queue": [],
            "queue_diagnostics": [],
            "workflow_events": [],
        }

        html = render_dashboard(state)

        self.assertIn('value="workflow-import-scout-seed-artifacts"', html)
        self.assertIn('name="source_run_id"', html)
        self.assertIn("Import Scout/Seed artifacts", html)

    def test_workflow_import_scout_seed_artifacts_action_builds_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)

            command = build_action_command(
                "workflow-import-scout-seed-artifacts",
                paths,
                {"source_run_id": "source-stage1"},
            )

        self.assertIn("workflow-import-scout-seed-artifacts", command)
        self.assertIn("--source-run-id", command)
        self.assertIn("source-stage1", command)

    def test_render_dashboard_exposes_data_capture_and_compile_controls(self):
        state = {
            "readiness": {"exists": True, "passed": False, "blocked": True},
            "freshness": {"exists": True, "valid": True, "record_count": 6, "stale_count": 1, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120, "scope_count": 4, "data_set_count": 8, "error_count": 0, "status": "completed"},
            "option_cards": [],
            "schedule": {"preview": ""},
            "jobs": [],
            "proposal_counts": {},
            "active_workflow": {"exists": False},
            "approved_queue": [],
            "queue_diagnostics": [],
            "workflow_events": [],
        }

        html = render_dashboard(state)

        self.assertIn('value="capture-platform-data-fields"', html)
        self.assertIn('name="fields_per_scope" type="number" min="0" value="100"', html)
        self.assertIn('name="max_scopes" type="number" min="0" value="40"', html)
        self.assertIn('value="compile-data-ledger"', html)
        self.assertIn('value="compile-knowledge"', html)
        self.assertIn('value="delivery-gate"', html)
        self.assertIn('name="enable_live_api"', html)
        self.assertIn("120", html)

    def test_render_proposals_uses_select_controls_for_structured_fields(self):
        html = render_proposals([{"proposal_id": "proposal-1", "title": "Lifecycle review", "status": "proposed"}])

        self.assertIn("<select name=\"issue_type\"", html)
        self.assertIn("<select name=\"affected_modules\"", html)
        self.assertIn("template_innovation", html)
        self.assertIn("data_coverage", html)
        decision_form = html.split('action="/proposals/decision"', 1)[1]
        self.assertIn('name="proposal_id" value="proposal-1"', decision_form)
        self.assertIn('option value="accepted_for_implementation"', decision_form)
        self.assertIn('option value="accepted_as_experiment"', decision_form)

    def test_second_fallback_option_survives_invalid_jsonl_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            artifact = paths.knowledge_root / "machine" / "data_ledger.jsonl"
            artifact.parent.mkdir(parents=True)
            fresh_date = date.today().isoformat()
            artifact.write_text(
                json.dumps({"dataset_id": "fundamental3", "field_id": "cash_field", "field_type": "MATRIX", "region": "USA", "delay": 1, "universe": "TOP3000", "semantic_tags": ["cash"], "coverage": 1.0, "source_updated_at": fresh_date, "source_quality": "platform_raw_capture", "coverage_status": "measured_raw", "compatible_template_ids": ["matrix_ts_zscore_rank"]}) + "\n",
                encoding="utf-8",
            )
            maintenance = paths.knowledge_root / "machine"
            maintenance.mkdir(parents=True, exist_ok=True)
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps(
                    [
                        {"name": name, "path": "machine/data_ledger.jsonl", "updated_at": fresh_date, "max_age_days": 7}
                        for name in ("data_ledger", "template_library", "benchmark_rules", "activity_snapshot", "operator_catalog", "research_option_cards")
                    ]
                ),
                encoding="utf-8",
            )
            decisions = paths.knowledge_root / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps(valid_option(title="First objective")) + "\n\nnot-json\n" + json.dumps(valid_option(title="Second objective")) + "\n",
                encoding="utf-8",
            )
            template = paths.knowledge_root / "machine" / "template_library.jsonl"
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_text(json.dumps({"template_id": "matrix_ts_zscore_rank", "status": "discovery_ready", "required_field_types": ["MATRIX"]}) + "\n", encoding="utf-8")
            self._write_start_fixture(
                paths,
                {"title": "First objective"},
                [{"dataset_id": "fundamental3", "field_id": "cash_field", "region": "USA", "delay": 1, "universe": "TOP3000", "source_quality": "platform_raw_capture", "coverage_status": "measured_raw", "compatible_template_ids": ["matrix_ts_zscore_rank"]}],
            )
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps(valid_option(title="First objective")) + "\n\nnot-json\n" + json.dumps(valid_option(title="Second objective")) + "\n",
                encoding="utf-8",
            )
            html = render_dashboard({"option_cards": [valid_option(title="First objective"), valid_option(title="Second objective")]})
            command = build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-2", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"})

        self.assertIn('value="option-2"', html)
        self.assertIn("Second objective", " ".join(command))

    def test_malformed_option_card_does_not_render_or_start_and_does_not_consume_fallback_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            decisions = paths.knowledge_root / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                "{}\n" + json.dumps(valid_option(title="Valid second row")) + "\n", encoding="utf-8"
            )

            html = render_dashboard({"option_cards": [{}, valid_option(title="Valid second row")]})
            with self.assertRaisesRegex(ValueError, "not available"):
                build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-2", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"})

        self.assertNotIn("Research option", html)
        self.assertIn('value="option-1"', html)
        self.assertIn("Valid second row", html)

    def test_duplicate_option_ids_and_fallback_collisions_are_rejected(self):
        cases = (
            [
                valid_option(option_id="dup", title="First"),
                valid_option(option_id="dup", title="Second"),
            ],
            [
                valid_option(title="Fallback option"),
                valid_option(option_id="option-1", title="Explicit collision"),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            self._write_start_fixture(paths, {"title": "Power Pool"}, [{
                "dataset_id": "fundamental3",
                "field_id": "cash_field",
                "region": "USA",
                "delay": 1,
                "universe": "TOP3000",
                "source_quality": "platform_raw_capture",
                "coverage_status": "measured_raw",
                "compatible_template_ids": ["matrix_ts_zscore_rank"],
            }])
            decisions = paths.knowledge_root / "wiki" / "70_decisions"
            for rows in cases:
                with self.subTest(rows=[row.get("title") for row in rows]):
                    (decisions / "research_option_cards.jsonl").write_text(
                        "".join(json.dumps(row) + "\n" for row in rows),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValueError, "duplicate research option id"):
                        build_action_command(
                            "workflow-start-from-option",
                            paths,
                            {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"},
                        )

    def test_render_proposals_includes_input_form(self):
        html = render_proposals([{"proposal_id": "p1", "title": "Improve template", "status": "proposed"}])

        self.assertIn("Workflow Proposal Inbox", html)
        self.assertIn("textarea", html)
        self.assertIn("Improve template", html)

    def test_build_action_command_refuses_research_start_when_knowledge_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            maintenance = root / "knowledge" / "machine"
            maintenance.mkdir(parents=True, exist_ok=True)
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps([{"name": "data_ledger", "path": "machine/data_ledger.jsonl", "updated_at": "2026-01-01", "max_age_days": 1}]),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "direct console workflow-start"):
                build_action_command("workflow-start", paths, {"objective": "Power Pool", "selected_option_id": "option-1"})

    def test_build_action_command_refuses_research_start_when_freshness_manifest_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            maintenance = root / "knowledge" / "machine"
            maintenance.mkdir(parents=True, exist_ok=True)
            (maintenance / "freshness_manifest.json").write_text("{not-json}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "direct console workflow-start"):
                build_action_command("workflow-start", paths, {"objective": "Power Pool", "selected_option_id": "option-1"})

            (maintenance / "freshness_manifest.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "direct console workflow-start"):
                build_action_command("workflow-start", paths, {"objective": "Power Pool", "selected_option_id": "option-1"})

    def test_build_action_command_refuses_research_start_when_manifest_missing_required_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            maintenance = root / "knowledge" / "machine"
            artifact = root / "knowledge" / "machine" / "data_ledger.jsonl"
            maintenance.mkdir(parents=True, exist_ok=True)
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}\n", encoding="utf-8")
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps([{"name": "data_ledger", "path": "machine/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7}]),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "direct console workflow-start"):
                build_action_command("workflow-start", paths, {"objective": "Power Pool", "selected_option_id": "option-1"})

    def test_build_action_command_requires_live_checkbox_for_platform_option_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            with self.assertRaisesRegex(ValueError, "enable_live_api"):
                build_action_command("plan-research-options", paths, {})

            command = build_action_command("plan-research-options", paths, {"enable_live_api": "on"})

        self.assertIn("plan-research-options", command)
        self.assertIn("--enable-live-api", command)

    def test_build_action_command_starts_generic_planner_card_from_ledger_backed_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            self._write_start_fixture(
                paths,
                {"title": "Build Genius and Osmosis alpha pool", "primary_incentive": "genius_osmosis", "candidate_scope": "Generate a later concrete plan across multiple region-delay scopes after user selection."},
                [{"dataset_id": "fundamental3", "field_id": "cash_field", "region": "USA", "delay": 1, "universe": "TOP3000", "source_quality": "platform_raw_capture", "coverage_status": "measured_raw", "compatible_template_ids": ["matrix_ts_zscore_rank"]}],
            )

            command = build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"})

        self.assertIn("workflow-start", command)
        self.assertIn("--selected-option-id", command)
        self.assertIn("option-1", command)
        self.assertIn("--selected-region", command)
        self.assertIn("--selected-delay", command)
        self.assertIn("--selected-universe", command)
        self.assertIn("--objective", command)
        self.assertIn("Build Genius and Osmosis alpha pool", " ".join(command))
        self.assertIn("USA D1 TOP3000", " ".join(command))

    def test_build_action_command_rejects_cartesian_scope_from_exact_ledger_scopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            self._write_start_fixture(
                paths,
                {"title": "Power Pool", "candidate_scope": "USA D1 TOP3000"},
                [{
                    "dataset_id": "fundamental3",
                    "field_id": "cash_field",
                    "region": "USA",
                    "delay": 1,
                    "universe": "TOP3000",
                    "available_regions": ["USA", "EUR"],
                    "available_delays": [0, 1],
                    "available_universes": ["TOP500", "TOP3000"],
                    "available_scopes": [
                        {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                        {"instrument_type": "EQUITY", "region": "EUR", "delay": 0, "universe": "TOP500"},
                    ],
                    "source_quality": "platform_raw_capture",
                    "coverage_status": "measured_raw",
                    "compatible_template_ids": ["matrix_ts_zscore_rank"],
                }],
            )

            with self.assertRaisesRegex(ValueError, "no records matching"):
                build_action_command(
                    "workflow-start-from-option",
                    paths,
                    {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "0", "selected_universe": "TOP500"},
                )

    def test_build_action_command_requires_selected_ledger_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            self._write_start_fixture(paths, {"title": "Power Pool"}, [])

            with self.assertRaisesRegex(ValueError, "select a concrete"):
                build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1"})

    def test_build_action_command_requires_selected_option_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            with self.assertRaisesRegex(ValueError, "select a research option"):
                build_action_command("workflow-start-from-option", paths, {})

    def test_build_action_command_refuses_schema_seeded_or_partial_ledger_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            option = {"title": "Power Pool", "candidate_scope": "USA D1 TOP3000"}
            base = {"dataset_id": "fundamental3", "field_id": "cash_field", "region": "USA", "delay": 1, "universe": "TOP3000", "compatible_template_ids": ["matrix_ts_zscore_rank"]}

            for invalid in ({**base, "source_quality": "schema_seed", "coverage_status": "measured_raw"}, {**base, "source_quality": "platform_raw_capture", "coverage_status": "partial"}):
                self._write_start_fixture(paths, option, [invalid])
                with self.assertRaisesRegex(ValueError, "data coverage"):
                    build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"})

    def test_build_action_command_starts_certified_exact_scope_and_rejects_partial_exact_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            self._write_start_fixture(
                paths,
                {"title": "Power Pool"},
                [
                    {"dataset_id": "fundamental3", "field_id": "cash_field", "region": "USA", "delay": 1, "universe": "TOP3000", "source_quality": "platform_raw_capture", "coverage_status": "measured_raw", "compatible_template_ids": ["matrix_ts_zscore_rank"], "available_scopes": [{"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}]},
                    {"dataset_id": "fundamental3", "field_id": "cash_field", "region": "EUR", "delay": 1, "universe": "TOP3000", "source_quality": "platform_raw_capture", "coverage_status": "partial", "compatible_template_ids": ["matrix_ts_zscore_rank"], "available_scopes": [{"instrument_type": "EQUITY", "region": "EUR", "delay": 1, "universe": "TOP3000"}]},
                ],
            )

            command = build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"})
            with self.assertRaisesRegex(ValueError, "data coverage"):
                build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1", "selected_region": "EUR", "selected_delay": "1", "selected_universe": "TOP3000"})

        self.assertIn("USA D1 TOP3000", " ".join(command))

    def test_build_action_command_refuses_warning_capture_compiled_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            capture = paths.knowledge_root / "raw" / "platform" / "data_fields" / "2026-07-16"
            capture.mkdir(parents=True)
            (capture / "data_fields.jsonl").write_text(
                json.dumps({
                    "scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                    "data_set": {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                    "field": {"id": "cash_field", "type": "MATRIX", "description": "Quarterly cash"},
                }) + "\n",
                encoding="utf-8",
            )
            (capture / "manifest.json").write_text(json.dumps({"status": "completed_with_warnings"}), encoding="utf-8")
            compile_data_ledger_from_raw(paths.knowledge_root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            ledger = paths.knowledge_root / "machine" / "data_ledger.jsonl"
            compiled_row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
            decisions = paths.knowledge_root / "wiki" / "70_decisions"
            decisions.mkdir(parents=True, exist_ok=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps(valid_option()) + "\n",
                encoding="utf-8",
            )
            freshness_artifacts = {
                "data_ledger": ledger,
                "template_library": paths.knowledge_root / "machine" / "template_library.jsonl",
                "benchmark_rules": paths.knowledge_root / "machine" / "benchmark_rules.jsonl",
                "activity_snapshot": paths.knowledge_root / "wiki" / "80_maintenance" / "activity_snapshot.json",
                "operator_catalog": paths.knowledge_root / "wiki" / "20_semantics" / "operator_semantics.jsonl",
                "research_option_cards": decisions / "research_option_cards.jsonl",
            }
            for artifact in freshness_artifacts.values():
                artifact.parent.mkdir(parents=True, exist_ok=True)
                if artifact != ledger and not artifact.exists():
                    artifact.write_text("{}\n", encoding="utf-8")
            maintenance = paths.knowledge_root / "machine"
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps([
                    {"name": name, "path": artifact.relative_to(paths.knowledge_root).as_posix(), "updated_at": date.today().isoformat(), "max_age_days": 7}
                    for name, artifact in freshness_artifacts.items()
                ]),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "data coverage"):
                build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"})

        self.assertEqual(compiled_row["coverage_status"], "partial")

    def test_build_action_command_refuses_when_ledger_has_no_matching_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            self._write_start_fixture(
                paths,
                {"title": "Power Pool", "candidate_scope": "USA D1 TOP3000"},
                [{"dataset_id": "fundamental3", "field_id": "cash_field", "region": "EUR", "delay": 1, "universe": "TOP3000", "source_quality": "platform_raw_capture", "coverage_status": "measured_raw", "compatible_template_ids": ["matrix_ts_zscore_rank"]}],
            )

            with self.assertRaisesRegex(ValueError, "ledger"):
                build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"})

    def test_build_action_command_refuses_matching_scope_without_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            self._write_start_fixture(
                paths,
                {"title": "Power Pool", "candidate_scope": "USA D1 TOP3000"},
                [{"dataset_id": "fundamental3", "field_id": "cash_field", "region": "USA", "delay": 1, "universe": "TOP3000", "source_quality": "platform_raw_capture", "coverage_status": "measured_raw", "compatible_template_ids": []}],
            )

            with self.assertRaisesRegex(ValueError, "templates"):
                build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"})

    def _write_start_fixture(self, paths, option, ledger_rows, template=None):
        """Input: console paths, option, ledger rows. Output: none. Write valid freshness and start artifacts."""
        ledger = paths.knowledge_root / "machine" / "data_ledger.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        fresh_date = date.today().isoformat()
        source_path = f"raw/platform/data_fields/{fresh_date}/data_fields.jsonl"
        rows = [
            {
                "field_type": "MATRIX",
                "semantic_tags": ["cash"],
                "coverage": 1.0,
                "source_updated_at": fresh_date,
                "source_paths": [source_path],
                **row,
            }
            for row in ledger_rows
        ]
        ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        scope_rows = []
        raw_rows = []
        for row in rows:
            exact_scopes = row.get("available_scopes")
            if not isinstance(exact_scopes, list):
                exact_scopes = [{"instrument_type": "EQUITY", "region": row.get("region"), "delay": row.get("delay"), "universe": row.get("universe")}]
            for scope in exact_scopes:
                if not isinstance(scope, dict):
                    continue
                scope_rows.append(scope)
                raw_rows.append({"scope": scope, "data_set": {"id": row.get("dataset_id")}, "field": {"id": row.get("field_id")}})
        capture = paths.knowledge_root / "raw" / "platform" / "data_fields" / fresh_date
        capture.mkdir(parents=True, exist_ok=True)
        (capture / "data_fields.jsonl").write_text("".join(json.dumps(row) + "\n" for row in raw_rows), encoding="utf-8")
        (capture / "scopes.jsonl").write_text(
            "".join(json.dumps({"scope": scope, "status": "completed", "certification_status": "complete"}) + "\n" for scope in scope_rows),
            encoding="utf-8",
        )
        (capture / "manifest.json").write_text(
            json.dumps({"generated_at": f"{fresh_date}T00:00:00Z", "certification_status": "complete", "requested_matrix": scope_rows}),
            encoding="utf-8",
        )
        template_path = paths.knowledge_root / "machine" / "template_library.jsonl"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_row = template if template is not None else {"template_id": "matrix_ts_zscore_rank", "status": "discovery_ready", "required_field_types": ["MATRIX"], "compatible_regions": ["USA"], "compatible_delays": [1], "compatible_universes": ["TOP3000"]}
        template_path.write_text(json.dumps(template_row) + "\n", encoding="utf-8")
        benchmark_path = paths.knowledge_root / "machine" / "benchmark_rules.jsonl"
        benchmark_path.parent.mkdir(parents=True, exist_ok=True)
        benchmark_path.write_text(
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
        activity = paths.knowledge_root / "wiki" / "10_foundations" / "activity_snapshot.md"
        activity.parent.mkdir(parents=True, exist_ok=True)
        activity.write_text("# Activity Snapshot\n", encoding="utf-8")
        operator_catalog = paths.knowledge_root / "wiki" / "20_semantics" / "operator_catalog_official.md"
        operator_catalog.parent.mkdir(parents=True, exist_ok=True)
        operator_catalog.write_text("# Operator Catalog\n", encoding="utf-8")
        maintenance = paths.knowledge_root / "machine"
        maintenance.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "data_ledger": "machine/data_ledger.jsonl",
            "template_library": "machine/template_library.jsonl",
            "benchmark_rules": "machine/benchmark_rules.jsonl",
            "activity_snapshot": "wiki/10_foundations/activity_snapshot.md",
            "operator_catalog": "wiki/20_semantics/operator_catalog_official.md",
            "research_option_cards": "wiki/70_decisions/research_option_cards.jsonl",
        }
        (maintenance / "freshness_manifest.json").write_text(
            json.dumps([
                {"name": name, "path": path, "updated_at": fresh_date, "max_age_days": 7}
                for name, path in artifacts.items()
            ]),
            encoding="utf-8",
        )
        decisions = paths.knowledge_root / "wiki" / "70_decisions"
        decisions.mkdir(parents=True, exist_ok=True)
        (decisions / "research_option_cards.jsonl").write_text(json.dumps(valid_option(**option)) + "\n", encoding="utf-8")

    def test_build_action_command_rejects_direct_start_even_when_freshness_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            self._write_start_fixture(paths, {"title": "Power Pool"}, [])

            with self.assertRaisesRegex(ValueError, "direct console workflow-start"):
                build_action_command("workflow-start", paths, {"objective": "Power Pool", "selected_option_id": "option-1"})

    def test_build_action_command_requires_exact_coverage_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            base = {"dataset_id": "fundamental3", "field_id": "cash_field", "region": "USA", "delay": 1, "universe": "TOP3000", "compatible_template_ids": ["matrix_ts_zscore_rank"]}
            for invalid in ({**base, "coverage_status": "measured_raw"}, {**base, "source_quality": "unknown", "coverage_status": "measured_raw"}, {**base, "source_quality": "platform_raw_capture", "coverage_status": "unknown"}):
                self._write_start_fixture(paths, {"title": "Power Pool"}, [invalid])
                with self.assertRaisesRegex(ValueError, "data coverage"):
                    build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"})

    def test_build_action_command_requires_positive_coverage_and_fresh_source_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            base = {
                "dataset_id": "fundamental3",
                "field_id": "cash_field",
                "region": "USA",
                "delay": 1,
                "universe": "TOP3000",
                "source_quality": "platform_raw_capture",
                "coverage_status": "measured_raw",
                "compatible_template_ids": ["matrix_ts_zscore_rank"],
            }
            stale_date = (date.today() - timedelta(days=30)).isoformat()
            for invalid in (
                {**base, "coverage": 0.0, "source_updated_at": date.today().isoformat()},
                {**base, "source_updated_at": ""},
                {**base, "source_updated_at": stale_date},
            ):
                self._write_start_fixture(paths, {"title": "Power Pool"}, [invalid])
                with self.assertRaisesRegex(ValueError, "data coverage"):
                    build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"})

    def test_build_action_command_requires_existing_compatible_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            base = {"dataset_id": "fundamental3", "field_id": "cash_field", "field_type": "MATRIX", "region": "USA", "delay": 1, "universe": "TOP3000", "source_quality": "platform_raw_capture", "coverage_status": "measured_raw"}
            cases = ((["missing-template"], None), (["matrix_ts_zscore_rank"], {"template_id": "matrix_ts_zscore_rank", "status": "deprecated"}), (["matrix_ts_zscore_rank"], {"template_id": "matrix_ts_zscore_rank", "status": "discovery_ready", "required_field_types": ["VECTOR"]}))
            for template_ids, template in cases:
                self._write_start_fixture(paths, {"title": "Power Pool"}, [{**base, "compatible_template_ids": template_ids}], template=template)
                with self.assertRaisesRegex(ValueError, "templates"):
                    build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"})

    def test_build_action_command_ignores_non_tradeable_rows_when_template_matches_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            self._write_start_fixture(
                paths,
                {"title": "Power Pool", "candidate_scope": "USA D1 TOP3000"},
                [
                    {
                        "dataset_id": "model10",
                        "field_id": "mdl10_group_name",
                        "field_type": "GROUP",
                        "region": "USA",
                        "delay": 1,
                        "universe": "TOP3000",
                        "source_quality": "platform_raw_capture",
                        "coverage_status": "measured_raw",
                        "compatible_template_ids": ["matrix_ts_zscore_rank"],
                    },
                    {
                        "dataset_id": "fundamental3",
                        "field_id": "cash_field",
                        "field_type": "MATRIX",
                        "region": "USA",
                        "delay": 1,
                        "universe": "TOP3000",
                        "source_quality": "platform_raw_capture",
                        "coverage_status": "measured_raw",
                        "compatible_template_ids": ["matrix_ts_zscore_rank"],
                    },
                ],
            )

            command = build_action_command(
                "workflow-start-from-option",
                paths,
                {"selected_option_id": "option-1", "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000"},
            )

        self.assertIn("workflow-start", command)

    def test_build_action_command_refuses_data_capture_without_live_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            with self.assertRaisesRegex(ValueError, "enable_live_api"):
                build_action_command("capture-platform-data-fields", paths, {})

    def test_refused_action_writes_durable_job_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)

            completed = run_console_action(paths, {"action": "plan-research-options"})
            jobs = list(paths.job_root.glob("*/job.json"))
            milestone = paths.milestone_path.read_text(encoding="utf-8")

        self.assertEqual(completed.status, "refused")
        self.assertEqual(len(jobs), 1)
        self.assertIn("enable_live_api", completed.error)
        self.assertIn("Console Job Context", milestone)

    def test_run_console_action_starts_data_capture_async(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            with patch("wqb.console_server.start_job_async") as start_async:
                start_async.side_effect = lambda job, **_: job.__class__(**{**job.__dict__, "status": "running", "pid": 123})
                completed = run_console_action(paths, {"action": "capture-platform-data-fields", "enable_live_api": "on", "max_scopes": "4"})

        self.assertEqual(completed.status, "running")
        start_async.assert_called_once()

    def test_run_console_action_starts_all_long_maintenance_actions_async_and_records_terminal_context(self):
        actions = ("compile-data-ledger", "compile-research-records", "compile-knowledge", "delivery-gate", "bootstrap-knowledge", "plan-research-options")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            paths.workflow_root.mkdir()
            for action in actions:
                with patch("wqb.console_server.build_action_command", return_value=[sys.executable, "-c", "import time; time.sleep(0.2)"]):
                    started = run_console_action(paths, {"action": action, "enable_live_api": "on"})
                self.assertEqual(started.status, "running")
            self.assertFalse(paths.milestone_path.exists())
            terminal_paths = []
            for job_path in paths.job_root.glob("*/job.json"):
                for _ in range(100):
                    payload = json.loads(job_path.read_text(encoding="utf-8"))
                    if payload["status"] in {"completed", "failed", "refused", "timed_out"}:
                        terminal_paths.append(payload)
                        break
                    threading.Event().wait(0.02)
            milestone = paths.milestone_path.read_text(encoding="utf-8")
            todo = paths.todo_path.read_text(encoding="utf-8")

        self.assertEqual(len(terminal_paths), len(actions))
        self.assertTrue(all(payload["status"] == "completed" for payload in terminal_paths))
        self.assertEqual(milestone.count("Console Job Context"), len(actions))
        self.assertEqual(todo.count("### Console Job"), len(actions))

    def test_async_context_recording_failure_keeps_terminal_job_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            paths.workflow_root.mkdir()
            with patch("wqb.console_server.build_action_command", return_value=[sys.executable, "-c", "print('done')"]):
                with patch("wqb.console_server.record_console_job_context", side_effect=OSError("context unavailable")):
                    started = run_console_action(paths, {"action": "compile-data-ledger"})
            for _ in range(100):
                payload = json.loads((Path(started.job_dir) / "job.json").read_text(encoding="utf-8"))
                if payload["status"] in {"completed", "failed", "refused", "timed_out"}:
                    break
                threading.Event().wait(0.02)

        self.assertEqual(started.status, "running")
        self.assertEqual(payload["status"], "completed")

    def test_capture_job_persists_command_capture_directory_before_async_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            with patch("wqb.console_server.start_job_async", side_effect=lambda job, **_: SimpleNamespace(status="running", job_id=job.job_id)):
                run_console_action(paths, {"action": "capture-platform-data-fields", "enable_live_api": "on", "data_capture_date": "2026-07-29"})
            payload = json.loads(next(paths.job_root.glob("*/job.json")).read_text(encoding="utf-8"))

        self.assertEqual(payload["metadata"]["capture_dir"], str(paths.knowledge_root / "raw" / "platform" / "data_fields" / "2026-07-29"))
        command = payload["command"]
        self.assertEqual(command[command.index("--data-capture-date") + 1], "2026-07-29")

    def test_handler_api_state_matches_console_state_and_async_post_redirects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            expected = load_console_state(paths)
            state_server = make_console_server("127.0.0.1", 0, paths)
            status, headers, body = request_from_console_server(state_server, "GET", "/api/state")
            redirect_server = make_console_server("127.0.0.1", 0, paths)
            with patch("wqb.console_server.run_console_action", return_value=SimpleNamespace(status="running", job_id="job-async")):
                redirect_status, redirect_headers, _ = request_from_console_server(redirect_server, "POST", "/actions/run", "action=compile-data-ledger")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(json.loads(body.decode("utf-8")), expected)
        self.assertEqual(redirect_status, 303)
        self.assertEqual(redirect_headers["Location"], "/")

    def test_handler_reuses_cached_state_between_poll_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            server = make_console_server("127.0.0.1", 0, paths)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch(
                    "wqb.console_server.load_console_state",
                    return_value={"jobs": [{"job_id": "cached-state"}]},
                ) as loader:
                    first = HTTPConnection(*server.server_address, timeout=5)
                    first.request("GET", "/api/state")
                    first_response = first.getresponse()
                    first_body = first_response.read()
                    first.close()
                    second = HTTPConnection(*server.server_address, timeout=5)
                    second.request("GET", "/api/state")
                    second_response = second.getresponse()
                    second_body = second_response.read()
                    second.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

        self.assertEqual(first_response.status, 200)
        self.assertEqual(second_response.status, 200)
        self.assertEqual(json.loads(first_body.decode("utf-8"))["jobs"][0]["job_id"], "cached-state")
        self.assertEqual(json.loads(second_body.decode("utf-8"))["jobs"][0]["job_id"], "cached-state")
        self.assertEqual(loader.call_count, 1)

    def test_run_console_action_keeps_short_actions_synchronous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            with patch("wqb.console_server.run_job") as run_sync:
                run_sync.side_effect = lambda job: job.__class__(**{**job.__dict__, "status": "completed", "exit_code": 0})
                completed = run_console_action(paths, {"action": "knowledge-health-check"})

        self.assertEqual(completed.status, "completed")
        run_sync.assert_called_once()

    def test_run_console_action_finalizes_job_when_runner_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)

            with patch("wqb.console_server.run_job", side_effect=RuntimeError("runner failed")):
                completed = run_console_action(paths, {"action": "knowledge-health-check"})
            payload = json.loads(next(paths.job_root.glob("*/job.json")).read_text(encoding="utf-8"))
            milestone = paths.milestone_path.read_text(encoding="utf-8")

        self.assertEqual(completed.status, "failed")
        self.assertEqual(payload["status"], "failed")
        self.assertIn("runner failed", completed.error)
        self.assertIn("Console Job Context", milestone)

    def test_proposal_creation_writes_durable_job_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)

            completed = create_console_proposal(paths, {"summary": "Improve novelty.", "issue_type": "template_innovation"})
            proposal_path = paths.knowledge_root / "machine" / "decisions" / "workflow_change_proposals.jsonl"
            legacy = paths.knowledge_root / "wiki" / "20_semantics" / "obsolete.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("# obsolete\n", encoding="utf-8")
            evidence = paths.knowledge_root / "raw" / "maintenance" / "compile_reports" / "evidence.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                json.dumps(
                    {
                        "report_type": "knowledge_maintenance_pre_cleanup_evidence",
                        "status": "completed",
                        "compile": {"status": "completed"},
                        "pre_cleanup_health": {"blocking_issue_count": 0},
                    }
                ),
                encoding="utf-8",
            )
            apply_obsolete_active_cleanup(
                paths.knowledge_root,
                "2026-07-30T00:00:00+00:00",
                dry_run=False,
                verification_report_path=evidence,
            )
            jobs = list(paths.job_root.glob("*/job.json"))
            proposal_exists = proposal_path.exists()
            legacy_exists = legacy.exists()

        self.assertEqual(completed.status, "completed")
        self.assertTrue(proposal_exists)
        self.assertFalse(legacy_exists)
        self.assertEqual(len(jobs), 1)

    def test_update_console_proposal_decision_persists_lifecycle_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            proposal_job = create_console_proposal(paths, {"summary": "Improve novelty.", "issue_type": "template_innovation"})
            proposal = load_workflow_proposals(paths.knowledge_root / "machine" / "decisions")[0]

            completed = update_console_proposal_decision(
                paths,
                {
                    "proposal_id": proposal["proposal_id"],
                    "status": "accepted_as_experiment",
                    "user_decision": "Run an isolated experiment.",
                },
            )
            rows = load_workflow_proposals(paths.knowledge_root / "machine" / "decisions")

        self.assertEqual(proposal_job.status, "completed")
        self.assertEqual(completed.status, "completed")
        self.assertEqual(rows[0]["status"], "accepted_as_experiment")

    def test_make_console_server_constructs_local_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            class FakeServer:
                def __init__(self, address, handler):
                    self.server_address = address
                    self.handler = handler

                def server_close(self):
                    return None

            with patch("wqb.console_server.ThreadingHTTPServer", FakeServer):
                server = make_console_server("127.0.0.1", 0, make_paths(Path(tmp)))

            self.assertEqual(server.server_address[0], "127.0.0.1")
            self.assertTrue(hasattr(server, "console_paths"))


if __name__ == "__main__":
    unittest.main()
