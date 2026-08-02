import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from wqb.delivery_verification import run_delivery_verification


class DeliveryVerificationTests(unittest.TestCase):
    def test_runner_records_controller_compatible_checks_and_latest_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            project_root = base / "BrainWorkflow"
            project_root.mkdir()
            results = [
                subprocess.CompletedProcess(["unittest"], 0, "Ran 714 tests\nOK\n", ""),
                subprocess.CompletedProcess(["compileall"], 0, "", ""),
            ]

            with patch("wqb.delivery_verification.subprocess.run", side_effect=results) as run:
                report = run_delivery_verification(
                    knowledge,
                    project_root=project_root,
                    generated_at="2026-07-30T00:00:00+00:00",
                )

            report_path = Path(report["report_path"])
            latest_path = knowledge / "raw" / "maintenance" / "delivery_checks" / "latest.json"
            checks = {check["code"]: check for check in report["checks"]}

            self.assertEqual(report["status"], "passed")
            self.assertEqual(checks["unittest_discovery"]["returncode"], 0)
            self.assertEqual(checks["compileall"]["returncode"], 0)
            self.assertEqual(
                checks["unittest_discovery"]["command"][1:],
                [
                    "-c",
                    "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')",
                    "discover",
                    "-s",
                    "tests",
                    "-q",
                ],
            )
            self.assertEqual(
                checks["compileall"]["command"][1:],
                ["-m", "compileall", "-q", "wqb", "tests"],
            )
            self.assertEqual(run.call_count, 2)
            self.assertTrue(report_path.exists())
            self.assertEqual(json.loads(latest_path.read_text(encoding="utf-8"))["report_path"], str(report_path))

    def test_runner_persists_absolute_report_path_for_relative_knowledge_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project_root = base / "BrainWorkflow"
            project_root.mkdir()
            results = [
                subprocess.CompletedProcess(["unittest"], 0, "OK\n", ""),
                subprocess.CompletedProcess(["compileall"], 0, "", ""),
            ]
            original_cwd = Path.cwd()
            try:
                os.chdir(base)
                with patch("wqb.delivery_verification.subprocess.run", side_effect=results):
                    report = run_delivery_verification(
                        "knowledge",
                        project_root=project_root,
                        generated_at="2026-07-30T00:00:00+00:00",
                    )
            finally:
                os.chdir(original_cwd)

        self.assertTrue(Path(report["report_path"]).is_absolute())


if __name__ == "__main__":
    unittest.main()
