from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb.delivery_gate import run_delivery_gate
from wqb.run_readiness import ReadinessIssue, ReadinessReport
from wqb.workflow_events import append_workflow_event
from wqb.workflow_state import create_initial_state, write_run_state


class DeliveryGateTests(unittest.TestCase):
    def _write_minimal_clean_knowledge(self, root: Path) -> Path:
        for name in ("raw", "machine", "wiki"):
            (root / name).mkdir(parents=True, exist_ok=True)
        source = root / "raw" / "platform" / "learn" / "doc.md"
        source.parent.mkdir(parents=True)
        source.write_text(
            "---\n"
            "source_type: platform_document\n"
            "source_family: raw/platform/learn\n"
            "source_path: /learn/doc\n"
            "captured_at: 2026-07-30T00:00:00+00:00\n"
            "capture_tool: delivery_test\n"
            "record_count: 1\n"
            "content_hash: abc\n"
            "update_check: compare source\n"
            "compiled_targets:\n"
            "  - wiki/00_start_here.md\n"
            "---\n"
            "# Source\n",
            encoding="utf-8",
        )
        data_row = {
            "dataset_id": "fundamental3",
            "dataset_name": "Fundamentals",
            "field_id": "cash_field",
            "field_type": "MATRIX",
            "region": "USA",
            "delay": 1,
            "universe": "TOP3000",
            "semantic_tags": ["cash"],
            "coverage": 1.0,
            "alpha_count": 0,
            "user_count": 0,
            "simulation_usage_count": 0,
            "submitted_usage_count": 0,
            "last_used_at": "",
            "best_result_label": "unexplored",
            "correlation_risk": "low",
            "source_paths": ["raw/platform/learn/doc.md"],
            "source_quality": "platform_raw_capture",
            "coverage_status": "measured_raw",
            "source_updated_at": "2026-07-30",
        }
        operator_row = {
            "operator": "rank",
            "family": "cross_sectional",
            "workflow_uses": ["discovery"],
            "compatible_field_types": ["MATRIX"],
            "template_tags": ["cash"],
            "risk_tags": [],
            "repair_levers": [],
            "source_paths": ["raw/platform/learn/doc.md"],
        }
        template_row = {
            "template_id": "matrix_rank",
            "hypothesis": "Rank a matrix field.",
            "skeleton": "rank({field})",
            "required_field_types": ["MATRIX"],
            "compatible_semantic_tags": ["cash"],
            "operator_tags": ["rank"],
            "status": "discovery_ready",
            "correlation_risk": "low",
            "repair_levers": [],
            "source_paths": ["raw/platform/learn/doc.md"],
        }
        benchmark_row = {
            "rule_id": "delivery_rule",
            "issue_types": ["correlation"],
            "description": "Check correlation.",
            "promotion_condition": "Checks pass.",
            "action": "Continue.",
            "evidence_paths": ["raw/platform/learn/doc.md"],
            "consumed_by": ["research_planner"],
            "risk": "low",
        }
        source_index_row = {
            "path": "raw/platform/learn/doc.md",
            "source_family": "raw/platform/learn",
            "source_type": "platform_document",
            "contents": "Delivery test source.",
            "update_check": "compare source",
            "compiled_targets": ["wiki/00_start_here.md"],
        }
        jsonl_rows = {
            "scope_matrix.jsonl": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
            "data_ledger.jsonl": data_row,
            "operator_ledger.jsonl": operator_row,
            "template_library.jsonl": template_row,
            "benchmark_rules.jsonl": benchmark_row,
            "research_records.jsonl": {"run_id": "delivery-history", "final_state": "completed"},
            "source_index.jsonl": source_index_row,
        }
        for name, row in jsonl_rows.items():
            (root / "machine" / name).write_text(json.dumps(row) + "\n", encoding="utf-8")
        manifest_rows = [
            {"name": "data_ledger", "path": "machine/data_ledger.jsonl", "updated_at": "2026-07-30", "max_age_days": 7},
            {"name": "template_library", "path": "machine/template_library.jsonl", "updated_at": "2026-07-30", "max_age_days": 7},
            {"name": "benchmark_rules", "path": "machine/benchmark_rules.jsonl", "updated_at": "2026-07-30", "max_age_days": 7},
            {"name": "activity_snapshot", "path": "raw/platform/learn/doc.md", "updated_at": "2026-07-30", "max_age_days": 7},
        ]
        (root / "machine" / "freshness_manifest.json").write_text(
            json.dumps(manifest_rows),
            encoding="utf-8",
        )
        (root / "raw" / "source_index.md").write_text(
            "# Raw Source Index\n\n## `raw/platform/learn/doc.md`\n",
            encoding="utf-8",
        )
        for page in (
            "00_start_here.md",
            "10_factor_principles.md",
            "20_data_semantics.md",
            "30_template_and_operator_patterns.md",
            "40_benchmark_and_repair_rules.md",
            "50_engineering_lessons.md",
        ):
            (root / "wiki" / page).write_text(
                "---\ncompiled_from:\n  - raw/platform/learn/doc.md\n"
                "compiled_at: 2026-07-30T00:00:00+00:00\n"
                "trust_level: compiled_experience\nstale_after_days: 14\n"
                "update_trigger: compile-knowledge\nconsumed_by:\n  - human_learning\n"
                "---\n# Page\n",
                encoding="utf-8",
            )
        cleanup_log = root / "raw" / "maintenance" / "cleanup_logs" / "2026-07-30.jsonl"
        cleanup_log.parent.mkdir(parents=True)
        cleanup_log.write_text(
            json.dumps(
                {
                    "event": "cleanup_run",
                    "generated_at": "2026-07-30T00:00:00+00:00",
                    "dry_run": False,
                    "blocked": False,
                    "candidate_count": 0,
                    "removed_count": 0,
                    "refused_count": 0,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        maintenance = root / "raw" / "maintenance" / "compile_reports" / "20260730T000000Z.json"
        maintenance.parent.mkdir(parents=True)
        maintenance.write_text(
            json.dumps(
                {
                    "report_type": "knowledge_maintenance",
                    "generated_at": "2026-07-30T00:00:00+00:00",
                    "status": "completed",
                    "health": {"issue_count": 0},
                    "cleanup": {
                        "status": "completed",
                        "dry_run": False,
                        "blocked": False,
                        "cleanup_log_path": str(cleanup_log),
                    },
                }
            ),
            encoding="utf-8",
        )
        return maintenance

    def _write_verification_report(
        self,
        root: Path,
        check_codes: tuple[str, ...] = ("unittest_discovery", "compileall"),
        generated_at: str = "2026-07-30T00:00:00+00:00",
    ) -> Path:
        """Input: vault root, check codes, timestamp. Output: verification report path. Write local test evidence."""
        commands = {
            "unittest_discovery": [
                "python",
                "-c",
                "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')",
                "discover",
                "-s",
                "tests",
                "-q",
            ],
            "compileall": ["python", "-m", "compileall", "-q", "wqb", "tests"],
        }
        directory = root / "raw" / "maintenance" / "delivery_checks"
        directory.mkdir(parents=True, exist_ok=True)
        report_path = directory / "20260730T000000Z.json"
        report = {
            "report_type": "delivery_verification",
            "generated_at": generated_at,
            "status": "passed",
            "checks": [
                {
                    "code": code,
                    "status": "passed",
                    "returncode": 0,
                    "command": commands[code],
                }
                for code in check_codes
            ],
            "report_path": str(report_path),
        }
        report_path.write_text(json.dumps(report), encoding="utf-8")
        (directory / "latest.json").write_text(json.dumps(report), encoding="utf-8")
        return report_path

    def _passing_readiness(self) -> ReadinessReport:
        """Input: none. Output: ReadinessReport. Build a non-live readiness pass for delivery tests."""
        return ReadinessReport("plan-only", "2026-07-30T00:00:00+00:00", True, False, [])

    def _write_run_state(
        self,
        runs: Path,
        run_id: str,
        status: str,
        current_stage: str,
        updated_at: str,
        pause_reason: str = "",
        waiting_for_user: bool = False,
    ) -> Path:
        """Input: workflow state fields. Output: run directory. Write one durable real-schema workflow state."""
        run_dir = runs / run_id
        run_dir.mkdir(parents=True)
        state = create_initial_state(run_id, run_dir, "Delivery test", "2026-07-30T00:00:00+00:00")
        write_run_state(
            run_dir / "run_state.json",
            replace(
                state,
                status=status,
                current_stage=current_stage,
                pause_reason=pause_reason,
                waiting_for_user=waiting_for_user,
                updated_at=updated_at,
            ),
        )
        append_workflow_event(
            run_dir,
            "delivery_boundary_reached",
            {"status": status, "current_stage": current_stage},
            updated_at,
        )
        return run_dir

    def test_delivery_gate_accepts_expected_durable_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_verification_report(knowledge)
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "passed")
            self.assertIn("expected_pause", {check["code"] for check in report["checks"]})

    def test_delivery_gate_accepts_waiting_for_user_approval_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_verification_report(knowledge)
            self._write_run_state(
                runs,
                "20260730T000000-approval",
                "waiting_for_user",
                "user_approval",
                "2026-07-30T00:00:00+00:00",
                waiting_for_user=True,
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "passed")
            self.assertEqual(
                "passed",
                next(check["status"] for check in report["checks"] if check["code"] == "expected_pause"),
            )

    def test_delivery_gate_fails_for_plan_only_readiness_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_verification_report(knowledge)
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )
            readiness = ReadinessReport(
                "plan-only",
                "2026-07-30T00:00:00+00:00",
                True,
                False,
                [ReadinessIssue("warn", "stale_artifact", "Required artifact is stale.")],
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=readiness):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "failed")
            self.assertEqual(
                "failed",
                next(check["status"] for check in report["checks"] if check["code"] == "run_readiness"),
            )

    def test_delivery_gate_uses_latest_valid_state_updated_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_verification_report(knowledge)
            self._write_run_state(
                runs,
                "20260731T000000-failed",
                "failed",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
            )
            self._write_run_state(
                runs,
                "20260730T000000-resumed",
                "waiting_for_user",
                "user_approval",
                "2026-07-31T00:00:00+00:00",
                waiting_for_user=True,
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "passed")

    def test_delivery_gate_fails_when_local_verification_evidence_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            "failed",
            next(check["status"] for check in report["checks"] if check["code"] == "local_verification_evidence"),
        )

    def test_delivery_gate_requires_both_local_verification_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_verification_report(knowledge, ("unittest_discovery",))
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            "failed",
            next(check["status"] for check in report["checks"] if check["code"] == "local_verification_evidence"),
        )

    def test_delivery_gate_accepts_fresh_successful_local_verification_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            verification_path = self._write_verification_report(knowledge)
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

        check = next(check for check in report["checks"] if check["code"] == "local_verification_evidence")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(check["status"], "passed")
        self.assertEqual(check["evidence_path"], str(verification_path))

    def test_delivery_gate_rejects_raw_source_missing_from_machine_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_verification_report(knowledge)
            extra_source = knowledge / "raw" / "community" / "forum" / "thread.md"
            extra_source.parent.mkdir(parents=True)
            extra_source.write_text(
                "---\n"
                "source_type: community_note\n"
                "source_family: raw/community/forum\n"
                "source_path: /forum/thread\n"
                "captured_at: 2026-07-30T00:00:00+00:00\n"
                "capture_tool: delivery_test\n"
                "record_count: 1\n"
                "content_hash: def\n"
                "update_check: compare source\n"
                "compiled_targets:\n"
                "  - wiki/50_engineering_lessons.md\n"
                "---\n"
                "# Thread\n",
                encoding="utf-8",
            )
            markdown_index = knowledge / "raw" / "source_index.md"
            markdown_index.write_text(
                markdown_index.read_text(encoding="utf-8")
                + "\n## `raw/community/forum/thread.md`\n",
                encoding="utf-8",
            )
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

        self.assertEqual(report["status"], "failed")
        source_check = next(check for check in report["checks"] if check["code"] == "source_index_evidence")
        self.assertEqual(source_check["status"], "failed")
        self.assertIn("raw/community/forum/thread.md", source_check["message"])

    def test_delivery_gate_fails_when_machine_ledger_is_inside_wiki(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            (knowledge / "wiki" / "20_semantics").mkdir(parents=True)
            (knowledge / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text("{}\n", encoding="utf-8")

            report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "failed")
            self.assertIn(
                "clean_knowledge_structure",
                {check["code"] for check in report["checks"] if check["status"] == "failed"},
            )

    def test_delivery_gate_requires_fresh_successful_maintenance_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            maintenance = self._write_minimal_clean_knowledge(knowledge)
            payload = json.loads(maintenance.read_text(encoding="utf-8"))
            payload["status"] = "blocked"
            maintenance.write_text(json.dumps(payload), encoding="utf-8")
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            "failed",
            next(check["status"] for check in report["checks"] if check["code"] == "maintenance_evidence"),
        )

    def test_delivery_gate_rejects_cleanup_log_from_different_maintenance_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            maintenance = self._write_minimal_clean_knowledge(knowledge)
            payload = json.loads(maintenance.read_text(encoding="utf-8"))
            cleanup_log = Path(payload["cleanup"]["cleanup_log_path"])
            cleanup_row = json.loads(cleanup_log.read_text(encoding="utf-8"))
            cleanup_row["generated_at"] = "2026-07-29T00:00:00+00:00"
            cleanup_log.write_text(json.dumps(cleanup_row) + "\n", encoding="utf-8")
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            "failed",
            next(check["status"] for check in report["checks"] if check["code"] == "maintenance_evidence"),
        )

    def test_delivery_gate_rejects_broken_wiki_compiled_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            page = knowledge / "wiki" / "00_start_here.md"
            page.write_text(
                page.read_text(encoding="utf-8").replace(
                    "raw/platform/learn/doc.md",
                    "raw/platform/learn/missing.md",
                ),
                encoding="utf-8",
            )
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            "failed",
            next(check["status"] for check in report["checks"] if check["code"] == "knowledge_contract_health"),
        )

    def test_delivery_gate_rejects_empty_machine_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            (knowledge / "machine" / "scope_matrix.jsonl").write_text("", encoding="utf-8")
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            "failed",
            next(check["status"] for check in report["checks"] if check["code"] == "machine_resource_scope_matrix"),
        )

    def test_delivery_gate_requires_workflow_timeline_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            run_dir = self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )
            (run_dir / "workflow_events.jsonl").unlink()

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            "failed",
            next(check["status"] for check in report["checks"] if check["code"] == "workflow_timeline_evidence"),
        )

    def test_delivery_gate_checks_console_endpoints_when_url_is_provided(self):
        class FakeResponse:
            def __init__(self, body: bytes):
                self.status = 200
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return self.body

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_verification_report(knowledge)
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )
            responses = [
                FakeResponse(b"<html></html>"),
                FakeResponse(b'{"status":"ok"}'),
                FakeResponse(b'{"timeline":"ok"}'),
            ]

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()), patch(
                "urllib.request.urlopen",
                side_effect=responses,
            ) as request:
                report = run_delivery_gate(
                    knowledge,
                    runs,
                    "2026-07-30T00:00:00+00:00",
                    console_base_url="http://127.0.0.1:8765",
                )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(request.call_count, 3)
        self.assertEqual(
            {call.args[0] for call in request.call_args_list},
            {
                "http://127.0.0.1:8765/",
                "http://127.0.0.1:8765/api/state",
                "http://127.0.0.1:8765/api/fragments",
            },
        )

    def test_delivery_reports_are_immutable_with_latest_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            self._write_run_state(
                runs,
                "20260730T000000-paused",
                "paused",
                "scout_seed",
                "2026-07-30T00:00:00+00:00",
                pause_reason="missing candidates.csv",
            )

            with patch("wqb.delivery_gate.evaluate_run_readiness", return_value=self._passing_readiness()):
                first = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")
                second = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            latest = knowledge / "raw" / "maintenance" / "delivery_gates" / "latest.json"
            self.assertNotEqual(first["report_path"], second["report_path"])
            self.assertTrue(Path(first["report_path"]).exists())
            self.assertTrue(Path(second["report_path"]).exists())
            self.assertTrue(latest.exists())


if __name__ == "__main__":
    unittest.main()
