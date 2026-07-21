import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from wqb.console_server import build_action_command, create_console_proposal, make_console_server, render_dashboard, render_proposals, run_console_action
from wqb.console_state import ConsolePaths
from wqb.data_ledger_compile import compile_data_ledger_from_raw


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


class ConsoleServerTests(unittest.TestCase):
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
        self.assertIn('value="compile-data-ledger"', html)
        self.assertIn('name="enable_live_api"', html)
        self.assertIn("120", html)

    def test_render_proposals_uses_select_controls_for_structured_fields(self):
        html = render_proposals([])

        self.assertIn("<select name=\"issue_type\"", html)
        self.assertIn("<select name=\"affected_modules\"", html)
        self.assertIn("template_innovation", html)
        self.assertIn("data_coverage", html)

    def test_second_fallback_option_survives_invalid_jsonl_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            artifact = paths.knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            artifact.parent.mkdir(parents=True)
            fresh_date = date.today().isoformat()
            artifact.write_text(
                json.dumps({"dataset_id": "fundamental3", "field_id": "cash_field", "field_type": "MATRIX", "region": "USA", "delay": 1, "universe": "TOP3000", "semantic_tags": ["cash"], "coverage": 1.0, "source_updated_at": fresh_date, "source_quality": "platform_raw_capture", "coverage_status": "measured_raw", "compatible_template_ids": ["matrix_ts_zscore_rank"]}) + "\n",
                encoding="utf-8",
            )
            maintenance = paths.knowledge_root / "wiki" / "80_maintenance"
            maintenance.mkdir(parents=True)
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps(
                    [
                        {"name": name, "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": fresh_date, "max_age_days": 7}
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
            template = paths.knowledge_root / "wiki" / "30_templates" / "template_library.jsonl"
            template.parent.mkdir(parents=True)
            template.write_text(json.dumps({"template_id": "matrix_ts_zscore_rank", "status": "discovery_ready", "required_field_types": ["MATRIX"]}) + "\n", encoding="utf-8")
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
            maintenance = root / "knowledge" / "wiki" / "80_maintenance"
            maintenance.mkdir(parents=True)
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps([{"name": "data_ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-01-01", "max_age_days": 1}]),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "direct console workflow-start"):
                build_action_command("workflow-start", paths, {"objective": "Power Pool", "selected_option_id": "option-1"})

    def test_build_action_command_refuses_research_start_when_freshness_manifest_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            maintenance = root / "knowledge" / "wiki" / "80_maintenance"
            maintenance.mkdir(parents=True)
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
            maintenance = root / "knowledge" / "wiki" / "80_maintenance"
            artifact = root / "knowledge" / "wiki" / "20_semantics" / "data_ledger.jsonl"
            maintenance.mkdir(parents=True)
            artifact.parent.mkdir(parents=True)
            artifact.write_text("{}\n", encoding="utf-8")
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps([{"name": "data_ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7}]),
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
            ledger = paths.knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            compiled_row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
            maintenance = paths.knowledge_root / "wiki" / "80_maintenance"
            maintenance.mkdir(parents=True, exist_ok=True)
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps([
                    {"name": name, "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7}
                    for name in ("data_ledger", "template_library", "benchmark_rules", "activity_snapshot", "operator_catalog", "research_option_cards")
                ]),
                encoding="utf-8",
            )
            decisions = paths.knowledge_root / "wiki" / "70_decisions"
            decisions.mkdir(parents=True, exist_ok=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps(valid_option()) + "\n",
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
        ledger = paths.knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        fresh_date = date.today().isoformat()
        rows = [
            {
                "field_type": "MATRIX",
                "semantic_tags": ["cash"],
                "coverage": 1.0,
                "source_updated_at": fresh_date,
                **row,
            }
            for row in ledger_rows
        ]
        ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        template_path = paths.knowledge_root / "wiki" / "30_templates" / "template_library.jsonl"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_row = template if template is not None else {"template_id": "matrix_ts_zscore_rank", "status": "discovery_ready", "required_field_types": ["MATRIX"], "compatible_regions": ["USA"], "compatible_delays": [1], "compatible_universes": ["TOP3000"]}
        template_path.write_text(json.dumps(template_row) + "\n", encoding="utf-8")
        maintenance = paths.knowledge_root / "wiki" / "80_maintenance"
        maintenance.mkdir(parents=True, exist_ok=True)
        (maintenance / "freshness_manifest.json").write_text(
            json.dumps([
                {"name": name, "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": fresh_date, "max_age_days": 7}
                for name in ("data_ledger", "template_library", "benchmark_rules", "activity_snapshot", "operator_catalog", "research_option_cards")
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
            proposal_path = paths.knowledge_root / "wiki" / "70_decisions" / "workflow_change_proposals.jsonl"
            jobs = list(paths.job_root.glob("*/job.json"))
            proposal_exists = proposal_path.exists()

        self.assertEqual(completed.status, "completed")
        self.assertTrue(proposal_exists)
        self.assertEqual(len(jobs), 1)

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
