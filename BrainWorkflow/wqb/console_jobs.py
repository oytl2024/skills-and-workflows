from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
from uuid import uuid4

from wqb.console_state import ConsolePaths


DEFAULT_TIMEOUT_SECONDS = 3600


@dataclass(frozen=True)
class ConsoleJob:
    job_id: str
    created_at: str
    updated_at: str
    status: str
    action: str
    command: list[str]
    cwd: str
    metadata: dict[str, Any]
    job_dir: str
    stdout_path: str
    stderr_path: str
    summary_path: str
    exit_code: int | None = None
    error: str = ""


def console_job_to_dict(job: ConsoleJob) -> dict[str, Any]:
    """Input: ConsoleJob. Output: dict. Convert a console job to JSON-safe data."""
    return asdict(job)


def _now() -> str:
    """Input: none. Output: UTC timestamp string. Provide a stable timestamp format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_job(job: ConsoleJob) -> ConsoleJob:
    """Input: ConsoleJob. Output: same job. Persist the job record atomically enough for local use."""
    path = Path(job.job_dir) / "job.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(console_job_to_dict(job), ensure_ascii=False, indent=2), encoding="utf-8")
    return job


def create_job(
    job_root: str | Path,
    action: str,
    command: list[str],
    cwd: str | Path,
    metadata: dict[str, Any] | None = None,
    now: str | None = None,
) -> ConsoleJob:
    """Input: job root, action, command, cwd, metadata. Output: ConsoleJob. Create a durable queued job."""
    created = now or _now()
    job_id = f"{created[:10].replace('-', '')}-{str(action).replace('_', '-')}-{uuid4().hex[:8]}"
    job_dir = Path(job_root) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    job = ConsoleJob(
        job_id=job_id,
        created_at=created,
        updated_at=created,
        status="created",
        action=str(action),
        command=[str(item) for item in command],
        cwd=str(cwd),
        metadata=dict(metadata or {}),
        job_dir=str(job_dir),
        stdout_path=str(job_dir / "stdout.txt"),
        stderr_path=str(job_dir / "stderr.txt"),
        summary_path=str(job_dir / "summary.md"),
    )
    return _write_job(job)


def _write_summary(job: ConsoleJob) -> None:
    """Input: ConsoleJob. Output: none. Write a compact job summary for recovery."""
    lines = [
        "# Console Job Summary",
        "",
        f"- Job ID: `{job.job_id}`",
        f"- Action: `{job.action}`",
        f"- Status: `{job.status}`",
        f"- Exit Code: `{job.exit_code}`",
        f"- Command: `{' '.join(job.command)}`",
        f"- Stdout: `{job.stdout_path}`",
        f"- Stderr: `{job.stderr_path}`",
    ]
    if job.error:
        lines.append(f"- Error: {job.error}")
    Path(job.summary_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def finish_job(job: ConsoleJob, status: str, exit_code: int = 0, error: str = "") -> ConsoleJob:
    """Input: job and final state. Output: finalized job. Persist internal or refused console actions."""
    completed = replace(job, status=status, updated_at=_now(), exit_code=exit_code, error=str(error))
    stdout = Path(completed.stdout_path)
    stderr = Path(completed.stderr_path)
    stdout.parent.mkdir(parents=True, exist_ok=True)
    if not stdout.exists():
        stdout.write_text("", encoding="utf-8")
    if not stderr.exists():
        stderr.write_text(str(error), encoding="utf-8")
    _write_summary(completed)
    return _write_job(completed)


def run_job(job: ConsoleJob, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> ConsoleJob:
    """Input: ConsoleJob and timeout. Output: completed job. Run the command and persist outputs."""
    running = replace(job, status="running", updated_at=_now())
    _write_job(running)
    try:
        result = subprocess.run(
            running.command,
            cwd=running.cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        Path(running.stdout_path).write_text(result.stdout or "", encoding="utf-8")
        Path(running.stderr_path).write_text(result.stderr or "", encoding="utf-8")
        status = "completed" if result.returncode == 0 else "failed"
        completed = replace(running, status=status, updated_at=_now(), exit_code=result.returncode)
    except subprocess.TimeoutExpired as error:
        Path(running.stdout_path).write_text(error.stdout or "", encoding="utf-8")
        Path(running.stderr_path).write_text(error.stderr or "", encoding="utf-8")
        completed = replace(running, status="failed", updated_at=_now(), exit_code=-1, error=f"timed out after {timeout_seconds}s")
    except Exception as error:
        Path(running.stdout_path).write_text("", encoding="utf-8")
        error_text = f"{running.command[0] if running.command else 'command'}: {error}"
        Path(running.stderr_path).write_text(error_text, encoding="utf-8")
        completed = replace(running, status="failed", updated_at=_now(), exit_code=-1, error=error_text)
    _write_summary(completed)
    return _write_job(completed)


def load_job_history(job_root: str | Path) -> list[dict[str, Any]]:
    """Input: job root. Output: job rows newest first. Load persisted console job records."""
    root = Path(job_root)
    rows: list[dict[str, Any]] = []
    for path in root.glob("*/job.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return sorted(rows, key=lambda row: str(row.get("updated_at", row.get("created_at", ""))), reverse=True)


def build_cli_command(action: str, paths: ConsolePaths, form: dict[str, Any] | None = None) -> list[str]:
    """Input: action, paths, form. Output: CLI command tokens. Map console actions to safe local commands."""
    data = dict(form or {})
    base = [sys.executable, "-m", "wqb.cli"]
    knowledge_root = str(paths.knowledge_root)
    if action == "readiness-check":
        mode = str(data.get("readiness_mode", "plan-only"))
        command = [
            *base,
            "readiness-check",
            "--knowledge-root",
            knowledge_root,
            "--readiness-mode",
            mode,
            "--batch-size",
            str(data.get("batch_size", 30)),
            "--readiness-output-dir",
            str(paths.runs_root / "readiness"),
        ]
        if data.get("enable_live_api"):
            command.append("--enable-live-api")
        if data.get("confirm_submit"):
            command.append("--confirm-submit")
        return command
    if action == "knowledge-health-check":
        return [*base, "knowledge-health-check", "--knowledge-root", knowledge_root]
    if action == "bootstrap-knowledge":
        return [*base, "bootstrap-knowledge", "--knowledge-root", knowledge_root, "--knowledge-seed-root", str(paths.workflow_root / "docs" / "knowledge")]
    if action == "compile-research-records":
        return [*base, "compile-research-records", "--knowledge-root", knowledge_root]
    if action == "plan-research-options":
        command = [
            *base,
            "plan-research-options",
            "--knowledge-root",
            knowledge_root,
            "--option-output-dir",
            str(paths.knowledge_root / "wiki" / "70_decisions"),
            "--max-options",
            str(data.get("max_options", 5)),
        ]
        if data.get("enable_live_api"):
            command.append("--enable-live-api")
        return command
    if action == "workflow-start":
        return [
            *base,
            "workflow-start",
            "--knowledge-root",
            knowledge_root,
            "--run-dir",
            str(paths.runs_root),
            "--objective",
            str(data.get("objective", "")),
            "--selected-option-id",
            str(data.get("selected_option_id", "")),
        ]
    if action == "workflow-continue":
        return [*base, "workflow-continue", "--knowledge-root", knowledge_root, "--run-dir", str(paths.runs_root)]
    if action == "workflow-status":
        return [*base, "workflow-status", "--knowledge-root", knowledge_root, "--run-dir", str(paths.runs_root)]
    raise ValueError(f"unsupported console action: {action}")
