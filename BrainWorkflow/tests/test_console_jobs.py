import json
import sys
import tempfile
import unittest
from pathlib import Path

from wqb.console_jobs import build_cli_command, create_job, load_job_history, run_job
from wqb.console_state import ConsolePaths


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


class ConsoleJobsTests(unittest.TestCase):
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
            option_refresh = build_cli_command("plan-research-options", paths, {"enable_live_api": True})

        self.assertIn("bootstrap-knowledge", platform_compile)
        self.assertIn("compile-research-records", research_compile)
        self.assertIn("--enable-live-api", option_refresh)
        self.assertNotEqual(platform_compile, research_compile)

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
        self.assertIn("--resume-capture", capture)
        self.assertIn("compile-data-ledger", compile_cmd)
        self.assertNotIn("--enable-live-api", compile_cmd)

    def test_workflow_commands_carry_console_run_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            command = build_cli_command("workflow-status", paths, {})

        self.assertIn("--run-dir", command)
        self.assertIn(str(paths.runs_root), command)

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


if __name__ == "__main__":
    unittest.main()
