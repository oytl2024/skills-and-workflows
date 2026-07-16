from __future__ import annotations

from pathlib import Path

from wqb.console_jobs import ConsoleJob
from wqb.console_state import ConsolePaths


def _append(path: Path, text: str) -> None:
    """Input: path and text. Output: none. Append text after creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def record_console_job_context(paths: ConsolePaths, job: ConsoleJob, next_command: str = "") -> None:
    """Input: console paths and job. Output: none. Update durable context anchors after a UI job."""
    milestone_text = (
        "\n## Console Job Context\n\n"
        f"- Job ID: `{job.job_id}`\n"
        f"- Action: `{job.action}`\n"
        f"- Status: `{job.status}`\n"
        f"- Summary: `{job.summary_path}`\n"
        f"- Next command: `{next_command}`\n"
    )
    todo_text = (
        "\n### Console Job\n"
        f"- `{job.action}` finished with status `{job.status}`.\n"
        f"- Summary: `{job.summary_path}`\n"
    )
    _append(paths.milestone_path, milestone_text)
    _append(paths.todo_path, todo_text)
    summary = Path(job.summary_path)
    existing = summary.read_text(encoding="utf-8") if summary.exists() else "# Console Job Summary\n"
    if "## Next Command" not in existing:
        summary.write_text(existing + f"\n## Next Command\n\n`{next_command}`\n", encoding="utf-8")
