import csv
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from wqb.recorder import RunRecorder


TESTS_DIR = Path(__file__).resolve().parent


def make_run_dir() -> Path:
    """Input: none. Output: Path. Create a unique workspace-local recorder test directory."""
    run_dir = TESTS_DIR / f"_tmp_recorder_{uuid4().hex}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def cleanup_run_dir(run_dir: Path) -> None:
    """Input: Path. Output: none. Remove only verified workspace-local recorder test directories."""
    resolved = run_dir.resolve()
    if resolved.parent != TESTS_DIR or not resolved.name.startswith("_tmp_recorder_"):
        raise RuntimeError(f"refusing to clean unexpected test path: {resolved}")
    shutil.rmtree(resolved)


class RecorderTests(unittest.TestCase):
    def test_jsonl_append_and_seen_hashes(self):
        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            recorder.append_jsonl("all_alphas.jsonl", {"expression_hash": "abc", "status": "SIMULATED"})
            recorder.append_jsonl("all_alphas.jsonl", {"expression_hash": "def", "status": "FAILED"})

            self.assertEqual(recorder.seen_expression_hashes(), {"abc", "def"})
        finally:
            cleanup_run_dir(run_dir)

    def test_candidates_csv_written_with_headers(self):
        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)
            recorder.write_candidates(
                [
                    {
                        "alpha_id": "abc123",
                        "expression_hash": "hash1",
                        "sharpe": 1.8,
                        "fitness": 1.2,
                        "turnover": 0.22,
                    }
                ]
            )
            with (run_dir / "candidates.csv").open("r", encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))

            self.assertEqual(rows[0]["alpha_id"], "abc123")
            self.assertEqual(rows[0]["expression_hash"], "hash1")
        finally:
            cleanup_run_dir(run_dir)

    def test_write_markdown_saves_content(self):
        run_dir = make_run_dir()
        try:
            recorder = RunRecorder(run_dir)

            recorder.write_markdown("run_summary.md", "# Summary\n\nDone.\n")

            self.assertEqual((run_dir / "run_summary.md").read_text(encoding="utf-8"), "# Summary\n\nDone.\n")
        finally:
            cleanup_run_dir(run_dir)


if __name__ == "__main__":
    unittest.main()
