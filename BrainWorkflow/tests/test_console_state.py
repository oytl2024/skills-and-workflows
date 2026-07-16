import json
import tempfile
import unittest
from pathlib import Path

from wqb.console_state import ConsolePaths, _active_workflow_summary, load_console_state


class ConsoleStateTests(unittest.TestCase):
    def test_active_workflow_discovery_recovers_missing_pointer_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            run_dir = runs / "run1"
            run_dir.mkdir(parents=True)
            from wqb.workflow_state import create_initial_state, write_run_state

            write_run_state(
                run_dir / "run_state.json",
                create_initial_state("run1", run_dir, "Power Pool", "2026-07-12T00:00:00Z"),
            )
            summary, recovered_dir = _active_workflow_summary(runs)

            self.assertEqual(recovered_dir, run_dir)
            self.assertEqual(summary["run_id"], "run1")
            self.assertFalse((runs / "active_run.json").exists())
    def test_load_console_state_aggregates_readiness_options_schedule_jobs_and_proposals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            runs = root / "runs"
            decisions = knowledge / "wiki" / "70_decisions"
            maintenance = knowledge / "wiki" / "80_maintenance"
            decisions.mkdir(parents=True)
            maintenance.mkdir(parents=True)
            readiness_dir = runs / "readiness_latest"
            readiness_dir.mkdir(parents=True)
            job_dir = runs / "console_jobs" / "job-1"
            job_dir.mkdir(parents=True)

            (readiness_dir / "readiness_report.json").write_text(
                json.dumps({"mode": "plan-only", "passed": True, "blocked": False, "issues": []}),
                encoding="utf-8",
            )
            for relative in [
                "wiki/20_semantics/data_ledger.jsonl",
                "wiki/30_templates/template_library.jsonl",
                "wiki/50_benchmarks/correlation_and_novelty.md",
                "wiki/10_foundations/activity_snapshot.md",
            ]:
                artifact = knowledge / relative
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text("{}", encoding="utf-8")
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps(
                    [
                        {"name": "data_ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-12", "max_age_days": 7},
                        {"name": "template_library", "path": "wiki/30_templates/template_library.jsonl", "updated_at": "2026-07-12", "max_age_days": 7},
                        {"name": "benchmark_rules", "path": "wiki/50_benchmarks/correlation_and_novelty.md", "updated_at": "2026-07-12", "max_age_days": 7},
                        {"name": "activity_snapshot", "path": "wiki/10_foundations/activity_snapshot.md", "updated_at": "2026-07-12", "max_age_days": 7},
                    ]
                ),
                encoding="utf-8",
            )
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps({"title": "Explore current Power Pool boards", "score": {"total": 10.5}}) + "\n",
                encoding="utf-8",
            )
            (decisions / "research_schedule.md").write_text("# Research Schedule\n\n- Option: Power Pool\n", encoding="utf-8")
            (decisions / "workflow_change_proposals.jsonl").write_text(
                json.dumps({"proposal_id": "p1", "status": "proposed", "title": "Down-rank crowded templates"}) + "\n",
                encoding="utf-8",
            )
            (job_dir / "job.json").write_text(
                json.dumps({"job_id": "job-1", "status": "completed", "action": "readiness-check"}),
                encoding="utf-8",
            )
            milestone = root / "milestone.md"
            milestone.write_text("## Active Loop\n\nLoop name: `workflow-console`\n", encoding="utf-8")
            todo = root / "todo.md"
            todo.write_text("# todo\n", encoding="utf-8")

            state = load_console_state(
                ConsolePaths(
                    project_root=root,
                    workflow_root=root / "BrainWorkflow",
                    knowledge_root=knowledge,
                    runs_root=runs,
                    milestone_path=milestone,
                    todo_path=todo,
                    job_root=runs / "console_jobs",
                )
            )

        self.assertTrue(state["readiness"]["passed"])
        self.assertEqual(state["freshness"]["record_count"], 4)
        self.assertEqual(state["option_cards"][0]["title"], "Explore current Power Pool boards")
        self.assertIn("Research Schedule", state["schedule"]["preview"])
        self.assertEqual(state["jobs"][0]["job_id"], "job-1")
        self.assertEqual(state["proposal_counts"]["proposed"], 1)
        self.assertEqual(state["milestone"]["active_loop"], "workflow-console")

    def test_load_console_state_handles_missing_optional_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            runs = root / "runs"
            knowledge.mkdir()
            runs.mkdir()
            state = load_console_state(
                ConsolePaths(
                    project_root=root,
                    workflow_root=root / "BrainWorkflow",
                    knowledge_root=knowledge,
                    runs_root=runs,
                    milestone_path=root / "milestone.md",
                    todo_path=root / "todo.md",
                    job_root=runs / "console_jobs",
                )
            )

        self.assertFalse(state["readiness"]["exists"])
        self.assertEqual(state["option_cards"], [])
        self.assertEqual(state["jobs"], [])
        self.assertEqual(state["proposal_counts"], {})
        self.assertEqual(state["active_workflow"], {"exists": False})
        self.assertEqual(state["workflow_events"], [])
        self.assertEqual(state["approved_queue"], [])
        self.assertEqual(state["research_record"], {"exists": False})

    def test_console_state_reports_latest_data_coverage_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = ConsolePaths(
                root,
                root / "BrainWorkflow",
                root / "knowledge",
                root / "runs",
                root / "milestone.md",
                root / "todo.md",
                root / "runs" / "console_jobs",
            )
            capture = paths.knowledge_root / "raw" / "platform" / "data_fields" / "2026-07-16"
            capture.mkdir(parents=True)
            (capture / "manifest.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-16T08:00:00+00:00",
                        "capture_dir": str(capture),
                        "scope_count": 4,
                        "data_set_count": 8,
                        "field_count": 120,
                        "error_count": 1,
                        "status": "completed_with_warnings",
                    }
                ),
                encoding="utf-8",
            )

            state = load_console_state(paths)

        self.assertTrue(state["data_coverage"]["exists"])
        self.assertEqual(state["data_coverage"]["field_count"], 120)
        self.assertEqual(state["data_coverage"]["error_count"], 1)

    def test_console_state_ignores_newer_capture_without_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = ConsolePaths(
                root,
                root / "BrainWorkflow",
                root / "knowledge",
                root / "runs",
                root / "milestone.md",
                root / "todo.md",
                root / "runs" / "console_jobs",
            )
            older_capture = paths.knowledge_root / "raw" / "platform" / "data_fields" / "2026-07-15"
            older_capture.mkdir(parents=True)
            (older_capture / "manifest.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-15T08:00:00+00:00",
                        "capture_dir": str(older_capture),
                        "scope_count": 2,
                        "data_set_count": 3,
                        "field_count": 40,
                        "error_count": 0,
                        "status": "completed",
                    }
                ),
                encoding="utf-8",
            )
            (paths.knowledge_root / "raw" / "platform" / "data_fields" / "2026-07-16").mkdir()

            state = load_console_state(paths)

        self.assertTrue(state["data_coverage"]["exists"])
        self.assertEqual(state["data_coverage"]["latest_capture_dir"], str(older_capture))
        self.assertEqual(state["data_coverage"]["field_count"], 40)
        self.assertEqual(state["data_coverage"]["scope_count"], 2)
        self.assertEqual(state["data_coverage"]["data_set_count"], 3)
        self.assertEqual(state["data_coverage"]["status"], "completed")

    def test_console_state_ignores_newer_partial_and_malformed_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = ConsolePaths(
                root,
                root / "BrainWorkflow",
                root / "knowledge",
                root / "runs",
                root / "milestone.md",
                root / "todo.md",
                root / "runs" / "console_jobs",
            )
            older_capture = paths.knowledge_root / "raw" / "platform" / "data_fields" / "2026-07-15"
            older_capture.mkdir(parents=True)
            (older_capture / "manifest.json").write_text(
                json.dumps({"scope_count": 2, "data_set_count": 3, "field_count": 40, "error_count": 0, "status": "completed"}),
                encoding="utf-8",
            )
            partial_capture = paths.knowledge_root / "raw" / "platform" / "data_fields" / "2026-07-16"
            partial_capture.mkdir(parents=True)
            (partial_capture / "manifest.json").write_text(json.dumps({"status": "in_progress"}), encoding="utf-8")
            malformed_capture = paths.knowledge_root / "raw" / "platform" / "data_fields" / "2026-07-17"
            malformed_capture.mkdir(parents=True)
            (malformed_capture / "manifest.json").write_text(
                json.dumps({"scope_count": 2, "data_set_count": 3, "field_count": "unknown", "error_count": 0}),
                encoding="utf-8",
            )

            state = load_console_state(paths)

        self.assertEqual(state["data_coverage"]["latest_capture_dir"], str(older_capture))
        self.assertEqual(state["data_coverage"]["field_count"], 40)
        self.assertEqual(state["data_coverage"]["status"], "completed")

    def test_load_console_state_includes_active_workflow_state_events_and_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            runs = root / "runs"
            run_dir = runs / "run1"
            run_dir.mkdir(parents=True)
            knowledge.mkdir()
            (runs / "active_run.json").write_text(
                json.dumps({"run_id": "run1", "run_dir": str(run_dir)}), encoding="utf-8"
            )
            from wqb.workflow_events import append_workflow_event
            from wqb.workflow_state import create_initial_state, write_run_state

            write_run_state(
                run_dir / "run_state.json",
                create_initial_state("run1", run_dir, "Power Pool", "2026-07-12T00:00:00Z"),
            )
            append_workflow_event(run_dir, "workflow_created", {"run_id": "run1"}, "2026-07-12T00:00:00Z")
            (run_dir / "approved_candidates.jsonl").write_text(
                '{"candidate_id":"c1","status":"queued"}\n', encoding="utf-8"
            )

            state = load_console_state(
                ConsolePaths(
                    root,
                    root / "BrainWorkflow",
                    knowledge,
                    runs,
                    root / "milestone.md",
                    root / "worklog.md",
                    runs / "console_jobs",
                )
            )

        self.assertEqual(state["active_workflow"]["run_id"], "run1")
        self.assertEqual(state["workflow_events"][0]["event_type"], "workflow_created")
        self.assertEqual(state["approved_queue"][0]["candidate_id"], "c1")

    def test_active_workflow_summary_includes_nonterminal_consistency_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            run_dir = runs / "run1"
            run_dir.mkdir(parents=True)
            (runs / "active_run.json").write_text(
                json.dumps({"run_id": "run1", "run_dir": str(run_dir)}), encoding="utf-8"
            )
            from wqb.workflow_state import create_initial_state, write_run_state

            write_run_state(
                run_dir / "run_state.json",
                create_initial_state("run1", run_dir, "Power Pool", "2026-07-12T00:00:00Z"),
            )
            (run_dir / "approved_candidates.jsonl").write_text(
                '{"candidate_id":"c1","version":1,"expression_hash":"h1","status":"queued"}\n',
                encoding="utf-8",
            )

            summary, recovered_dir = _active_workflow_summary(runs)

        self.assertEqual(recovered_dir, run_dir)
        self.assertFalse(summary.get("consistent", True))
        self.assertIn("candidate_queue_without_approval", summary.get("diagnostics", []))

    def test_load_console_state_reports_malformed_global_queue_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            runs = root / "runs"
            run_dir = runs / "run1"
            knowledge.mkdir()
            run_dir.mkdir(parents=True)
            (run_dir / "approved_candidates.jsonl").write_text("{not-json}\n", encoding="utf-8")

            state = load_console_state(
                ConsolePaths(
                    root,
                    root / "BrainWorkflow",
                    knowledge,
                    runs,
                    root / "milestone.md",
                    root / "worklog.md",
                    runs / "console_jobs",
                )
            )

        self.assertEqual(state["approved_queue"], [])
        self.assertIn("malformed_json:approved_candidates.jsonl", state.get("queue_diagnostics", []))

    def test_load_console_state_reads_approved_queue_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            runs = root / "runs"
            active_run = runs / "run1"
            queued_run = runs / "run2"
            knowledge.mkdir()
            active_run.mkdir(parents=True)
            queued_run.mkdir(parents=True)
            (runs / "active_run.json").write_text(
                json.dumps({"run_id": "run1", "run_dir": str(active_run)}), encoding="utf-8"
            )
            (queued_run / "approved_candidates.jsonl").write_text(
                '{"candidate_id":"c2","status":"queued"}\n', encoding="utf-8"
            )

            state = load_console_state(
                ConsolePaths(
                    root,
                    root / "BrainWorkflow",
                    knowledge,
                    runs,
                    root / "milestone.md",
                    root / "worklog.md",
                    runs / "console_jobs",
                )
            )

        self.assertEqual(state["approved_queue"], [{"candidate_id": "c2", "status": "queued"}])
