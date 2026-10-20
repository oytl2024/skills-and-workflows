import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb.console_jobs import build_cli_command, create_job, load_job_history, reconcile_job_dict, run_job, start_job_async, timeout_for_job, _finalize_process_result
from wqb.console_state import ConsolePaths


TERMINAL_STATUSES = {"completed", "failed", "refused", "timed_out"}
POLL_INTERVAL_SECONDS = 0.02


def make_paths(root: Path) -> ConsolePaths:
    """Input: temp root. Output: ConsolePaths. Create a minimal console path fixture."""
    return ConsolePaths(
        project_root=root,
        workflow_root=root / "BrainWorkflow",
        knowledge_root=root / "knowledge",
        runs_root=root / "runs",
        milestone_path=root / "milestone.md",
        todo_path=root / "todo.md",
        job_root=root / "runs" / "console_jobs",
    )


def wait_for_terminal_payload(job_dir: str | Path, timeout_seconds: float = 5) -> dict[str, object]:
    """Input: job directory and timeout seconds. Output: terminal job payload. Poll durable job state until terminal."""
    deadline = time.monotonic() + timeout_seconds
    path = Path(job_dir) / "job.json"
    while time.monotonic() < deadline:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") in TERMINAL_STATUSES:
            return payload
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(f"job did not reach a terminal state within {timeout_seconds}s")


class ConsoleJobsTests(unittest.TestCase):
    def test_job_record_is_never_overwritten_in_place(self):
        original = Path.write_text

        def reject_direct_write(path, *args, **kwargs):
            if path.name == "job.json":
                raise AssertionError("Readers can observe an empty job record")
            return original(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Path, "write_text", reject_direct_write):
                job = create_job(Path(tmp), "test", [], Path(tmp))
            payload = json.loads((Path(job.job_dir) / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "created")

    def test_zero_exit_preserves_blocked_runtime_business_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            run = Path(tmp) / 'active'
            run.mkdir()
            (run / 'runtime_status.json').write_text(json.dumps({'status': 'blocked',
                'reason': 'readiness-blocked'}), encoding='utf-8')
            job = create_job(paths.job_root, 'workflow-auto-continue', [], paths.workflow_root,
                             {'run_dir': str(run)})
            result = _finalize_process_result(job, 0)
            self.assertEqual(result.status, 'blocked')
            self.assertIn('readiness-blocked', result.status_message)

    def test_workflow_worker_outlives_default_one_hour_job_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            worker = create_job(paths.job_root, 'workflow-auto-continue', [], paths.workflow_root, {})
            routine = create_job(paths.job_root, 'compile-knowledge', [], paths.workflow_root, {})
            self.assertGreaterEqual(timeout_for_job(worker, 3600), 21660)
            self.assertEqual(timeout_for_job(routine, 3600), 3600)
            self.assertEqual(timeout_for_job(worker, 1), 1)

    def test_create_and_run_job_persists_outputs_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            command = [sys.executable, "-c", "print('ok')"]

            job = create_job(paths.job_root, "readiness-check", command, root, {"mode": "plan-only"}, now="2026-07-16T00:00:00Z")
            completed = run_job(job, timeout_seconds=10)
            history = load_job_history(paths.job_root)
            stdout_text = Path(completed.stdout_path).read_text(encoding="utf-8").strip()
            summary_exists = Path(completed.summary_path).exists()

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.exit_code, 0)
        self.assertEqual(history[0]["job_id"], job.job_id)
        self.assertEqual(stdout_text, "ok")
        self.assertTrue(summary_exists)

    def test_build_cli_command_has_separate_knowledge_maintenance_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            platform_compile = build_cli_command("bootstrap-knowledge", paths, {})
            research_compile = build_cli_command("compile-research-records", paths, {})
            knowledge_compile = build_cli_command("compile-knowledge", paths, {})
            delivery_gate = build_cli_command("delivery-gate", paths, {})
            option_refresh = build_cli_command("plan-research-options", paths, {"enable_live_api": True})

        self.assertIn("bootstrap-knowledge", platform_compile)
        self.assertIn("compile-research-records", research_compile)
        self.assertEqual(knowledge_compile[-3:], ["--knowledge-root", str(paths.knowledge_root), "--apply-cleanup"])
        self.assertEqual(delivery_gate[-5:], ["delivery-gate", "--knowledge-root", str(paths.knowledge_root), "--runs-root", str(paths.runs_root)])
        self.assertIn("--enable-live-api", option_refresh)
        self.assertEqual(
            option_refresh[option_refresh.index("--option-output-dir") + 1],
            str(paths.knowledge_root / "machine" / "decisions"),
        )
        self.assertNotEqual(platform_compile, research_compile)

    def test_build_cli_command_maps_interaction_capture_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            command = build_cli_command(
                "capture-interaction-note",
                paths,
                {
                    "summary": "Persist a repeated console blocker.",
                    "category": "engineering_lesson",
                    "tag": ["console", "blocker"],
                    "evidence_path": ["runs/console_jobs/job/summary.md"],
                },
            )

        self.assertEqual(command[3], "capture-interaction-note")
        self.assertIn("--summary", command)
        self.assertIn("Persist a repeated console blocker.", command)
        self.assertEqual(command.count("--tag"), 2)
        self.assertEqual(command.count("--evidence-path"), 1)

    def test_build_cli_command_maps_data_capture_and_compile(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            capture = build_cli_command(
                "capture-platform-data-fields",
                paths,
                {
                    "enable_live_api": True,
                    "max_scopes": "4",
                    "max_datasets_per_scope": "5",
                    "max_fields_per_dataset": "6",
                    "fields_per_scope": "100",
                    "capture_plan_path": "knowledge/raw/platform/data_fields/capture_plans/2026-07-30.jsonl",
                    "resume_capture": True,
                },
            )
            compile_cmd = build_cli_command("compile-data-ledger", paths, {})

        self.assertIn("capture-platform-data-fields", capture)
        self.assertIn("--enable-live-api", capture)
        self.assertIn("--max-scopes", capture)
        self.assertIn("4", capture)
        self.assertIn("--max-datasets-per-scope", capture)
        self.assertIn("5", capture)
        self.assertIn("--max-fields-per-dataset", capture)
        self.assertIn("6", capture)
        self.assertIn("--fields-per-scope", capture)
        self.assertIn("100", capture)
        self.assertIn("--capture-plan-path", capture)
        self.assertIn("--resume-capture", capture)
        self.assertIn("compile-data-ledger", compile_cmd)
        self.assertNotIn("--enable-live-api", compile_cmd)

    def test_workflow_commands_carry_console_run_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            command = build_cli_command("workflow-status", paths, {})

        self.assertIn("--run-dir", command)
        self.assertIn(str(paths.runs_root), command)

    def test_build_cli_command_maps_auto_continue_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            auto_continue = build_cli_command("workflow-auto-continue", paths, {"enable_live_api": True, "expected_runtime_revision": "rendered-revision"})
            stop = build_cli_command("workflow-stop", paths, {})
            acknowledge = build_cli_command(
                "workflow-acknowledge-source-rate-limit",
                paths,
                {"reason": "operator confirmed platform recovery"},
            )

        self.assertIn("workflow-run", auto_continue)
        self.assertNotIn("--enable-live-api", auto_continue)
        self.assertEqual(auto_continue[auto_continue.index("--expected-runtime-revision") + 1], "rendered-revision")
        self.assertIn("workflow-pause", stop)
        self.assertIn("workflow-acknowledge-source-rate-limit", acknowledge)
        self.assertIn("--reason", acknowledge)
        self.assertIn("operator confirmed platform recovery", acknowledge)
        self.assertNotIn("--enable-live-api", acknowledge)

    def test_workflow_start_command_carries_structured_selected_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            command = build_cli_command(
                "workflow-start",
                paths,
                {"objective": "Power Pool", "selected_option_id": "option-1", "selected_region": "USA", "selected_delay": 1, "selected_universe": "TOP3000", "enable_live_api": True},
            )

        self.assertEqual(command[command.index("--selected-region") + 1], "USA")
        self.assertEqual(command[command.index("--selected-delay") + 1], "1")
        self.assertEqual(command[command.index("--selected-universe") + 1], "TOP3000")
        self.assertIn("--enable-live-api", command)

    def test_job_json_contains_context_for_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            job = create_job(paths.job_root, "compile-research-records", [sys.executable, "-c", "print('compile')"], root, {"maintenance_kind": "research_record_compile"}, now="2026-07-16T00:00:00Z")

            payload = json.loads((Path(job.job_dir) / "job.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["metadata"]["maintenance_kind"], "research_record_compile")
        self.assertEqual(payload["status"], "created")

    def test_run_job_marks_spawn_error_failed_with_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            job = create_job(paths.job_root, "broken", ["definitely_missing_executable"], root, {}, now="2026-07-16T00:00:00Z")

            completed = run_job(job, timeout_seconds=10)
            payload = json.loads((Path(job.job_dir) / "job.json").read_text(encoding="utf-8"))
            summary = Path(completed.summary_path).read_text(encoding="utf-8")

        self.assertEqual(completed.status, "failed")
        self.assertEqual(payload["status"], "failed")
        self.assertIn("definitely_missing_executable", completed.error)
        self.assertIn("failed", summary)

    def test_run_job_marks_timeout_timed_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            job = create_job(paths.job_root, "timed", [sys.executable, "-c", "import time; time.sleep(5)"], root, {})

            completed = run_job(job, timeout_seconds=0.1)

        self.assertEqual(completed.status, "timed_out")
        self.assertEqual(completed.exit_code, -1)
        self.assertEqual(completed.error, "timed out after 0.1s")


class AsyncConsoleJobsTests(unittest.TestCase):
    def test_start_job_async_returns_running_job_with_pid_before_command_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            command = [sys.executable, "-c", "import time; time.sleep(0.4); print('done')"]
            job = create_job(paths.job_root, "slow-action", command, root, {}, now="2026-07-30T00:00:00+00:00")

            started = start_job_async(job, timeout_seconds=5)
            payload = json.loads((Path(job.job_dir) / "job.json").read_text(encoding="utf-8"))

            self.assertEqual(started.status, "running")
            self.assertIsInstance(started.pid, int)
            self.assertEqual(payload["status"], "running")
            self.assertEqual(payload["pid"], started.pid)
            final_payload = wait_for_terminal_payload(job.job_dir)
            stdout = Path(job.stdout_path).read_text(encoding="utf-8")
            summary_exists = Path(final_payload["summary_path"]).exists()

        self.assertEqual(final_payload["status"], "completed")
        self.assertEqual(final_payload["exit_code"], 0)
        self.assertIn("done", stdout)
        self.assertTrue(summary_exists)

    def test_start_job_async_persists_failed_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            command = [sys.executable, "-c", "import sys; print('bad'); sys.exit(7)"]
            job = create_job(paths.job_root, "failing-action", command, root, {})

            start_job_async(job, timeout_seconds=5)
            payload = wait_for_terminal_payload(job.job_dir)
            summary = Path(job.summary_path).read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["exit_code"], 7)
        self.assertTrue(payload["finished_at"])
        self.assertEqual(payload["status_message"], "failed")
        self.assertIn("failed", summary)

    def test_start_job_async_terminates_timed_out_process_and_persists_timed_out_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            command = [sys.executable, "-c", "import time; time.sleep(5)"]
            job = create_job(paths.job_root, "timed-action", command, root, {})

            start_job_async(job, timeout_seconds=0.1)
            payload = wait_for_terminal_payload(job.job_dir)

        self.assertEqual(payload["status"], "timed_out")
        self.assertIsNotNone(payload["exit_code"])
        self.assertTrue(payload["finished_at"])
        self.assertEqual(payload["status_message"], "timed_out")
        self.assertEqual(payload["error"], "timed out after 0.1s")

    def test_start_job_async_persists_spawn_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            job = create_job(paths.job_root, "broken", ["definitely_missing_executable"], root, {})

            failed = start_job_async(job, timeout_seconds=5)
            payload = json.loads((Path(job.job_dir) / "job.json").read_text(encoding="utf-8"))
            summary = Path(job.summary_path).read_text(encoding="utf-8")

        self.assertEqual(failed.status, "failed")
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["exit_code"], -1)
        self.assertIn("definitely_missing_executable", payload["error"])
        self.assertIn("failed", summary)

    def test_reconcile_running_capture_job_adds_progress_without_claiming_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            capture = knowledge / "raw" / "platform" / "data_fields" / "2026-07-30"
            capture.mkdir(parents=True)
            (capture / "data_fields.jsonl").write_text('{"id":"f1"}\n{"id":"f2"}\n', encoding="utf-8")
            row = {
                "job_id": "job-1",
                "status": "running",
                "action": "capture-platform-data-fields",
                "pid": None,
                "exit_code": None,
                "progress": {},
            }

            reconciled = reconcile_job_dict(row, knowledge)

        self.assertEqual(reconciled["status"], "detached")
        self.assertEqual(reconciled["progress_kind"], "data_capture")
        self.assertEqual(reconciled["progress"]["data_field_rows"], 2)
        self.assertNotEqual(reconciled["status"], "completed")

    def test_reconcile_capture_job_uses_its_persisted_capture_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            selected = knowledge / "raw" / "platform" / "data_fields" / "2026-07-29"
            newer = knowledge / "raw" / "platform" / "data_fields" / "2026-07-30"
            selected.mkdir(parents=True)
            newer.mkdir(parents=True)
            (selected / "data_fields.jsonl").write_text('{"id":"selected"}\n', encoding="utf-8")
            (newer / "data_fields.jsonl").write_text('{"id":"newer-1"}\n{"id":"newer-2"}\n', encoding="utf-8")
            row = {
                "job_id": "job-capture-29",
                "status": "running",
                "action": "capture-platform-data-fields",
                "pid": None,
                "exit_code": None,
                "metadata": {"capture_dir": str(selected)},
            }

            reconciled = reconcile_job_dict(row, knowledge)

        self.assertEqual(reconciled["progress"]["capture_dir"], str(selected))
        self.assertEqual(reconciled["progress"]["data_field_rows"], 1)

    def test_start_job_async_calls_completion_callback_after_terminal_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            job = create_job(paths.job_root, "callback-action", [sys.executable, "-c", "print('done')"], root, {})
            callbacks = []

            start_job_async(job, timeout_seconds=5, on_complete=callbacks.append)
            payload = wait_for_terminal_payload(job.job_dir)

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0].status, "completed")

    def test_reconcile_completed_job_keeps_terminal_state(self):
        row = {"job_id": "job-2", "status": "completed", "action": "readiness-check", "exit_code": 0}

        reconciled = reconcile_job_dict(row, None)

        self.assertEqual(reconciled["status"], "completed")
        self.assertEqual(reconciled["exit_code"], 0)

    def test_reconcile_terminal_capture_does_not_recount_raw_data(self):
        row = {
            "job_id": "job-capture-complete",
            "status": "completed",
            "action": "capture-platform-data-fields",
            "exit_code": 0,
            "progress": {"data_field_rows": 42},
        }

        with patch("wqb.console_jobs.probe_data_capture_progress", side_effect=AssertionError("unexpected recount")):
            reconciled = reconcile_job_dict(row, Path("knowledge"))

        self.assertEqual(reconciled["status"], "completed")
        self.assertEqual(reconciled["progress"]["data_field_rows"], 42)


if __name__ == "__main__":
    unittest.main()
