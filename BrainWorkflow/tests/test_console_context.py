import sys
import tempfile
import unittest
from pathlib import Path

from wqb.console_context import record_console_job_context
from wqb.console_jobs import create_job, run_job
from wqb.console_state import ConsolePaths


class ConsoleContextTests(unittest.TestCase):
    def test_record_console_job_context_updates_milestone_todo_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            milestone = root / "milestone.md"
            todo = root / "todo.md"
            paths = ConsolePaths(root, root / "BrainWorkflow", root / "knowledge", runs, milestone, todo, runs / "console_jobs")
            job = create_job(paths.job_root, "readiness-check", [sys.executable, "-c", "print('ok')"], root, {}, now="2026-07-16T00:00:00Z")
            completed = run_job(job, timeout_seconds=10)

            record_console_job_context(paths, completed, next_command="python -m wqb.cli workflow-status")

            milestone_text = milestone.read_text(encoding="utf-8")
            todo_text = todo.read_text(encoding="utf-8")
            summary_text = Path(completed.summary_path).read_text(encoding="utf-8")

        self.assertIn("Console Job Context", milestone_text)
        self.assertIn("readiness-check", todo_text)
        self.assertIn("Next Command", summary_text)


if __name__ == "__main__":
    unittest.main()
