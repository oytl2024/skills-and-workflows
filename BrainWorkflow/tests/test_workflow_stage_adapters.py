import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from wqb.workflow_stage_adapters import create_start_snapshot, schedule_research_stage, summarize_stage_artifacts


def valid_option(**overrides):
    """Input: optional overrides dict. Output: option-card dict. Build a strict scheduler fixture."""
    row = {
        "title": "Power Pool",
        "primary_incentive": "power_pool",
        "secondary_incentives": [],
        "why_now": "Fresh measured coverage is available.",
        "candidate_scope": "USA D1 TOP3000",
        "expected_asset_value": "A measured research direction.",
        "correlation_risk": "low",
        "resource_cost": "small",
        "evidence": [{"source_type": "ledger", "path": "machine/data_ledger.jsonl", "title": "Ledger", "timestamp": "2026-07-16"}],
        "failure_modes": [],
        "decision_needed": "Start the selected scope.",
        "score": {"total": 1.0, "components": {}, "penalties": {}, "reasons": ["measured coverage"]},
    }
    return {**row, **overrides}


def write_start_artifacts(root: Path, ledger_row: dict[str, object] | list[dict[str, object]]) -> None:
    """Input: root and ledger row(s). Output: none. Write strict start-snapshot fixtures."""
    knowledge = root / "knowledge"
    decisions = knowledge / "wiki" / "70_decisions"
    decisions.mkdir(parents=True)
    (decisions / "research_option_cards.jsonl").write_text(
        json.dumps(valid_option(option_id="option-1")) + "\n",
        encoding="utf-8",
    )
    ledger = knowledge / "machine" / "data_ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    base = {
        "dataset_id": "fundamental3",
        "dataset_name": "Fundamentals",
        "field_id": "cash_field",
        "field_type": "MATRIX",
        "region": "USA",
        "delay": 1,
        "universe": "TOP3000",
        "semantic_tags": ["cash", "power_pool"],
        "coverage": 1.0,
        "alpha_count": 0,
        "user_count": 0,
        "simulation_usage_count": 0,
        "submitted_usage_count": 0,
        "last_used_at": "",
        "best_result_label": "unexplored",
        "correlation_risk": "low",
        "source_paths": [],
        "source_quality": "platform_raw_capture",
        "coverage_status": "measured_raw",
        "source_updated_at": date.today().isoformat(),
        "available_scopes": [{"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"}],
        "compatible_template_ids": ["matrix_ts_zscore_rank"],
    }
    ledger_rows = ledger_row if isinstance(ledger_row, list) else [ledger_row]
    ledger.write_text("".join(json.dumps({**base, **row}) + "\n" for row in ledger_rows), encoding="utf-8")
    templates = knowledge / "machine" / "template_library.jsonl"
    templates.parent.mkdir(parents=True, exist_ok=True)
    templates.write_text(
        json.dumps({
            "template_id": "matrix_ts_zscore_rank",
            "hypothesis": "Rank a z-scored matrix field.",
            "skeleton": "rank(ts_zscore({field}, 20))",
            "required_field_types": ["MATRIX"],
            "compatible_semantic_tags": ["cash", "power_pool"],
            "operator_tags": ["rank", "ts_zscore"],
            "status": "discovery_ready",
            "correlation_risk": "low",
            "repair_levers": [],
            "source_paths": [],
            "compatible_regions": ["USA"],
            "compatible_delays": [1],
            "compatible_universes": ["TOP3000"],
        }) + "\n",
        encoding="utf-8",
    )
    benchmark = knowledge / "machine" / "benchmark_rules.jsonl"
    benchmark.parent.mkdir(parents=True, exist_ok=True)
    benchmark.write_text(
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
    activity = knowledge / "wiki" / "10_foundations" / "activity_snapshot.md"
    activity.parent.mkdir(parents=True)
    activity.write_text("# Activity Snapshot\n", encoding="utf-8")
    maintenance = knowledge / "machine"
    maintenance.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "data_ledger": "machine/data_ledger.jsonl",
        "template_library": "machine/template_library.jsonl",
        "benchmark_rules": "machine/benchmark_rules.jsonl",
        "activity_snapshot": "wiki/10_foundations/activity_snapshot.md",
    }
    (maintenance / "freshness_manifest.json").write_text(
        json.dumps([
            {"name": name, "path": path, "updated_at": date.today().isoformat(), "max_age_days": 7}
            for name, path in artifacts.items()
        ]),
        encoding="utf-8",
    )


class WorkflowStageAdaptersTests(unittest.TestCase):
    def test_schedule_research_stage_reads_canonical_machine_decision_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "machine" / "decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps(valid_option(option_id="option-1")) + "\n",
                encoding="utf-8",
            )

            summary = schedule_research_stage(
                root / "knowledge",
                root / "runs" / "run1",
                "option-1",
            )

        self.assertEqual(summary["selected_option"]["option_id"], "option-1")

    def test_create_start_snapshot_requires_positive_coverage_and_fresh_source_date(self):
        cases = (
            {"coverage": 0.0, "source_updated_at": date.today().isoformat()},
            {"source_updated_at": ""},
            {"source_updated_at": (date.today() - timedelta(days=30)).isoformat()},
        )
        for row in cases:
            with self.subTest(row=row), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_start_artifacts(root, row)

                with self.assertRaisesRegex(ValueError, "start snapshot"):
                    create_start_snapshot(
                        root / "knowledge",
                        "option-1",
                        {"region": "USA", "delay": 1, "universe": "TOP3000"},
                    )

    def test_create_start_snapshot_skips_non_research_rows_when_template_match_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_start_artifacts(
                root,
                [
                    {
                        "dataset_id": "model10",
                        "field_id": "mdl10_group_name",
                        "field_type": "GROUP",
                        "semantic_tags": ["model"],
                        "coverage": 0.0,
                        "compatible_template_ids": ["matrix_ts_zscore_rank"],
                    },
                    {"field_id": "cash_field", "field_type": "MATRIX", "coverage": 1.0},
                ],
            )

            with patch("wqb.workflow_stage_adapters._require_start_snapshot_readiness"):
                snapshot = create_start_snapshot(
                    root / "knowledge",
                    "option-1",
                    {"region": "USA", "delay": 1, "universe": "TOP3000"},
                )

        self.assertEqual([row["field_id"] for row in snapshot["data_ledger_rows"]], ["cash_field"])
        self.assertEqual(snapshot["compatible_template_ids"], ["matrix_ts_zscore_rank"])
        self.assertEqual(snapshot["gate_metadata"]["matching_data_ledger_row_count"], 2)
        self.assertEqual(snapshot["gate_metadata"]["snapshot_data_ledger_row_count"], 1)

    def test_create_start_snapshot_caps_embedded_data_ledger_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_start_artifacts(
                root,
                [
                    {"field_id": f"cash_field_{index}", "field_type": "MATRIX", "coverage": 1.0}
                    for index in range(205)
                ],
            )

            with patch("wqb.workflow_stage_adapters._require_start_snapshot_readiness"):
                snapshot = create_start_snapshot(
                    root / "knowledge",
                    "option-1",
                    {"region": "USA", "delay": 1, "universe": "TOP3000"},
                )

        self.assertEqual(len(snapshot["data_ledger_rows"]), 200)
        self.assertEqual(snapshot["gate_metadata"]["matching_data_ledger_row_count"], 205)
        self.assertEqual(snapshot["gate_metadata"]["snapshot_data_ledger_row_count"], 200)
        self.assertEqual(snapshot["gate_metadata"]["data_ledger_row_limit"], 200)

    def test_schedule_research_stage_writes_stage_artifact_from_option_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            decisions = knowledge / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps(valid_option(option_id="option-1", score={"total": 10.0, "components": {}, "penalties": {}, "reasons": ["measured coverage"]})) + "\n",
                encoding="utf-8",
            )
            run_dir = root / "runs" / "run1"
            summary = schedule_research_stage(knowledge, run_dir, "option-1")
            artifact = json.loads(
                (run_dir / "stages" / "schedule" / "research_schedule.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["stage"], "schedule")
            self.assertTrue((run_dir / "stages" / "schedule" / "research_schedule.json").exists())
            self.assertTrue((run_dir / "stages" / "schedule" / "research_schedule.md").exists())
            self.assertEqual(artifact["selected_option"]["option_id"], "option-1")
            self.assertEqual(artifact["option_title"], "Power Pool")

    def test_schedule_research_stage_rejects_unknown_option_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps(valid_option(option_id="option-1")) + "\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "selected research option not found"):
                schedule_research_stage(root / "knowledge", root / "runs" / "run1", "unknown")

    def test_schedule_research_stage_rejects_manifest_without_start_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_start_artifacts(root, {})
            run_dir = root / "runs" / "run1"
            run_dir.mkdir(parents=True)
            (run_dir / "run_manifest.json").write_text(
                json.dumps({"run_id": "run1", "selected_option_id": "option-1"}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "start snapshot"):
                schedule_research_stage(root / "knowledge", run_dir, "option-1")

    def test_schedule_research_stage_rejects_marker_only_official_directories(self):
        for marker in ("run_state.json", "workflow_events.jsonl"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_start_artifacts(root, {})
                run_dir = root / "runs" / "run1"
                run_dir.mkdir(parents=True)
                (run_dir / marker).write_text("", encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "start snapshot.*authority"):
                    schedule_research_stage(root / "knowledge", run_dir, "option-1")

    def test_schedule_research_stage_uses_stable_positional_id_for_planner_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps(valid_option(title="First")) + "\n"
                + json.dumps(valid_option(title="Second")) + "\n",
                encoding="utf-8",
            )

            summary = schedule_research_stage(root / "knowledge", root / "runs" / "run1", "option-2")

        self.assertEqual(summary["option_title"], "Second")
        self.assertEqual(summary["selected_option"]["option_id"], "option-2")

    def test_schedule_research_stage_skips_invalid_rows_before_assigning_fallback_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                "{}\n" + json.dumps(valid_option(title="Valid recovered option")) + "\n",
                encoding="utf-8",
            )

            summary = schedule_research_stage(root / "knowledge", root / "runs" / "run1", "option-1")

        self.assertEqual(summary["option_title"], "Valid recovered option")
        self.assertEqual(summary["selected_option"]["option_id"], "option-1")

    def test_schedule_research_stage_rejects_duplicate_and_fallback_colliding_option_ids(self):
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
        for rows in cases:
            with self.subTest(rows=[row.get("title") for row in rows]), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                decisions = root / "knowledge" / "wiki" / "70_decisions"
                decisions.mkdir(parents=True)
                (decisions / "research_option_cards.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in rows),
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, "duplicate research option id"):
                    schedule_research_stage(root / "knowledge", root / "runs" / "run1", "option-1")

    def test_summarize_stage_artifacts_counts_jsonl_and_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "all_alphas.jsonl").write_text('{"alpha_id":"a1"}\n', encoding="utf-8")
            (root / "candidates.csv").write_text("alpha_id,expression_hash\nA,h\n", encoding="utf-8")
            summary = summarize_stage_artifacts(root)

        self.assertEqual(summary["alpha_result_count"], 1)
        self.assertEqual(summary["candidate_file_exists"], True)
