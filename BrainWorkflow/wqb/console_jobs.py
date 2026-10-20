from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from wqb.console_progress import probe_data_capture_progress, process_is_alive
from wqb.console_state import ConsolePaths
from wqb.knowledge_paths import decision_artifacts_root
from wqb.runtime_control import DEFAULT_MAX_RUNTIME_SECONDS


DEFAULT_TIMEOUT_SECONDS = 3600
WORKFLOW_TIMEOUT_GRACE_SECONDS = 60
JOB_REPLACE_ATTEMPTS = 3
JOB_REPLACE_RETRY_SECONDS = 0.02
TERMINAL_JOB_STATUSES = {"completed", "failed", "refused", "timed_out", "blocked", "paused", "waiting_for_user", 'cancelled'}


def cancel_semantic_job(knowledge_root: Path, job_id: str) -> dict:
    """Input: vault Path/knowledge job ID str. Output: cancellation dict. Persist Stop without changing research intent."""
    from wqb.runtime_control import _write
    from wqb.semantic_publication import _safe_path, read_semantic_release
    from wqb.lockfile import json_lock_transition_guard
    if not job_id or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for char in job_id):
        raise ValueError('invalid semantic job ID')
    job = _safe_path(knowledge_root, 'machine/semantic_jobs/' + job_id)
    if not job.is_dir() or job.is_symlink() or job.is_junction():
        raise ValueError('unknown semantic job')
    with json_lock_transition_guard(job/'publication_guard', 2.0, 0.02, 'semantic publication busy'):
        path = job/'command_result.json'
        result = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if result.get('status') == 'completed':
            return dict(cancelled=False, status='completed', reason='publication already completed')
        intent = job/'publication_intent.json'
        if intent.exists():
            result = json.loads(intent.read_text(encoding='utf-8'))
        if result.get('status') == 'publishing':
            active = read_semantic_release(knowledge_root)
            if active['release_id'] == (result.get('release') or {}).get('release_id'):
                return dict(cancelled=False, status='completed', reason='publication already committed; wiki recovery may remain')
        control = dict(cancelled=True, updated_at=_now())
        _write(job / 'control.json', control)
        return control


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
    started_at: str = ""
    finished_at: str = ""
    pid: int | None = None
    duration_seconds: float | None = None
    last_progress_at: str = ""
    progress_kind: str = ""
    progress: dict[str, Any] | None = None
    status_message: str = ""


def console_job_to_dict(job: ConsoleJob) -> dict[str, Any]:
    """Input: ConsoleJob. Output: dict. Convert a console job to JSON-safe data."""
    return asdict(job)


def _now() -> str:
    """Input: none. Output: UTC timestamp string. Provide a stable timestamp format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _duration_seconds(started_at: str, finished_at: str) -> float | None:
    """Input: start and finish timestamps. Output: elapsed seconds or none. Compute job duration."""
    if not started_at or not finished_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (finish - start).total_seconds())


def _write_job(job: ConsoleJob) -> ConsoleJob:
    """Input: ConsoleJob. Output: same job. Atomically publish complete records for concurrent readers."""
    path = Path(job.job_dir) / "job.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(console_job_to_dict(job), ensure_ascii=False, indent=2), encoding="utf-8")
        for attempt in range(JOB_REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == JOB_REPLACE_ATTEMPTS-1:
                    raise
                time.sleep(JOB_REPLACE_RETRY_SECONDS)
    finally:
        temporary.unlink(missing_ok=True)
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
        completed = replace(running, status="timed_out", updated_at=_now(), exit_code=-1, error=f"timed out after {timeout_seconds}s")
    except Exception as error:
        Path(running.stdout_path).write_text("", encoding="utf-8")
        error_text = f"{running.command[0] if running.command else 'command'}: {error}"
        Path(running.stderr_path).write_text(error_text, encoding="utf-8")
        completed = replace(running, status="failed", updated_at=_now(), exit_code=-1, error=error_text)
    _write_summary(completed)
    return _write_job(completed)


def _finalize_process_result(job: ConsoleJob, returncode: int, error: str = "", status: str = "") -> ConsoleJob:
    """Input: running job and return code. Output: terminal job. Persist process result."""
    finished = _now()
    terminal_status = status or ("completed" if returncode == 0 else "failed")
    runtime_reason = ""
    if job.action == 'compile-semantic-knowledge' and not status:
        try:
            receipt = json.loads(Path(job.stdout_path).read_text(encoding='utf-8'))
            if not isinstance(receipt, dict):
                raise ValueError('semantic command result must be an object')
            if receipt.get('status') in {'completed', 'blocked', 'cancelled'}:
                terminal_status = receipt['status']
                runtime_reason = receipt.get('error', '') or json.dumps(receipt.get('rejections', []))
            else:
                terminal_status, runtime_reason = 'failed', 'semantic command result missing or invalid'
        except (OSError, ValueError):
            terminal_status, runtime_reason = 'failed', 'semantic command result missing or invalid'
    run_dir = job.metadata.get("run_dir") if isinstance(job.metadata, dict) else None
    if job.action == "workflow-auto-continue" and returncode == 0 and not status and run_dir:
        try:
            runtime = json.loads((Path(run_dir) / "runtime_status.json").read_text(encoding="utf-8"))
            business_status = str(runtime.get("status", ""))
            runtime_reason = str(runtime.get("reason", ""))
            if business_status in {"blocked", "paused", "waiting_for_user"}:
                terminal_status = business_status
            elif business_status == "error":
                terminal_status = "failed"
            elif business_status not in {"completed", "completed_with_warnings", "aborted"}:
                terminal_status, runtime_reason = "failed", "runtime result missing or nonterminal"
        except (OSError, ValueError):
            terminal_status, runtime_reason = "failed", "runtime result missing or invalid"
    completed = replace(
        job,
        status=terminal_status,
        updated_at=finished,
        finished_at=finished,
        duration_seconds=_duration_seconds(job.started_at, finished),
        exit_code=returncode,
        error=error,
        status_message=f"{terminal_status}: {runtime_reason}" if runtime_reason else terminal_status,
    )
    _write_summary(completed)
    return _write_job(completed)


def _notify_completion(callback: Callable[[ConsoleJob], None] | None, job: ConsoleJob) -> None:
    """Input: optional completion callback and terminal job. Output: none. Notify recovery hooks without breaking a watcher."""
    if callback is None:
        return
    try:
        callback(job)
    except Exception:
        return


def watch_job(
    job: ConsoleJob,
    process: subprocess.Popen[Any],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    on_complete: Callable[[ConsoleJob], None] | None = None,
) -> ConsoleJob:
    """Input: running job, process, timeout. Output: terminal job. Wait for async process and persist result."""
    try:
        returncode = process.wait(timeout=timeout_seconds)
        completed = _finalize_process_result(job, int(returncode))
    except subprocess.TimeoutExpired:
        process.kill()
        returncode = process.wait()
        completed = _finalize_process_result(job, int(returncode), f"timed out after {timeout_seconds}s", status="timed_out")
    _notify_completion(on_complete, completed)
    return completed


def timeout_for_job(job: ConsoleJob, requested_timeout: int) -> int:
    """Input: job and requested seconds. Output: int. Keep managed runs alive through their runtime budget."""
    if job.action == "workflow-auto-continue" and requested_timeout == DEFAULT_TIMEOUT_SECONDS:
        if job.metadata.get('run_dir'):
            import math
            from wqb.runtime_control import read_runtime_control
            control = read_runtime_control(job.metadata['run_dir'])
            remaining = float(control.get('max_runtime_seconds', DEFAULT_MAX_RUNTIME_SECONDS)) - float(control.get('elapsed_seconds', 0))
            return max(1, math.ceil(remaining)) + WORKFLOW_TIMEOUT_GRACE_SECONDS
        return DEFAULT_MAX_RUNTIME_SECONDS + WORKFLOW_TIMEOUT_GRACE_SECONDS
    return requested_timeout


def start_job_async(
    job: ConsoleJob,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    on_complete: Callable[[ConsoleJob], None] | None = None,
) -> ConsoleJob:
    """Input: created job and timeout. Output: running job. Start a CLI command without blocking the caller."""
    started_at = _now()
    stdout_path = Path(job.stdout_path)
    stderr_path = Path(job.stderr_path)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            job.command,
            cwd=job.cwd,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )
    except Exception as error:
        stdout_handle.close()
        stderr_handle.close()
        completed = finish_job(job, "failed", exit_code=-1, error=f"{job.command[0] if job.command else 'command'}: {error}")
        _notify_completion(on_complete, completed)
        return completed
    stdout_handle.close()
    stderr_handle.close()
    running = replace(
        job,
        status="running",
        updated_at=started_at,
        started_at=started_at,
        pid=process.pid,
        status_message="running",
    )
    _write_job(running)
    thread = threading.Thread(target=watch_job, args=(running, process, timeout_for_job(job, timeout_seconds), on_complete), daemon=True)
    thread.start()
    return running


def _progress_for_action(
    action: str,
    knowledge_root: str | Path | None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Input: action and knowledge root. Output: progress kind and payload. Compute action-specific progress."""
    if action == "capture-platform-data-fields" and knowledge_root is not None:
        capture_dir = (metadata or {}).get("capture_dir")
        return "data_capture", probe_data_capture_progress(knowledge_root, capture_dir=capture_dir)
    if action == 'compile-semantic-knowledge' and knowledge_root is not None:
        from wqb.console_state import _latest_semantic_compile
        return 'semantic_compile', _latest_semantic_compile(Path(knowledge_root))
    return "", {}


def reconcile_job_dict(row: dict[str, Any], knowledge_root: str | Path | None = None) -> dict[str, Any]:
    """Input: persisted job row and knowledge root. Output: reconciled row. Refresh running job state for the Console."""
    result = dict(row)
    status = str(result.get("status", ""))
    if status in TERMINAL_JOB_STATUSES:
        return result
    action = str(result.get("action", ""))
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    progress_kind, progress = _progress_for_action(action, knowledge_root, metadata)
    if progress_kind:
        result["progress_kind"] = progress_kind
        result["progress"] = progress
        result["last_progress_at"] = str(progress.get("last_write_at", ""))
    if status == "running":
        pid = result.get("pid")
        if process_is_alive(int(pid)) if isinstance(pid, int) else False:
            result["status_message"] = "running"
            return result
        if result.get("exit_code") is None:
            result["status"] = "detached"
            result["status_message"] = "process handle is no longer attached"
    return result


def load_job_history(job_root: str | Path, knowledge_root: str | Path | None = None) -> list[dict[str, Any]]:
    """Input: job root and optional knowledge root. Output: job rows newest first. Load and reconcile console jobs."""
    root = Path(job_root)
    rows: list[dict[str, Any]] = []
    for path in root.glob("*/job.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            rows.append(reconcile_job_dict(row, knowledge_root))
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
    if action == 'compile-semantic-knowledge':
        return [*base, action, '--knowledge-root', knowledge_root,
                '--max-mechanisms', str(data.get('max_mechanisms', 3)),
                '--max-conditions-per-mechanism', str(data.get('max_conditions_per_mechanism', 2))]
    if action == "capture-interaction-note":
        command = [
            *base,
            "capture-interaction-note",
            "--knowledge-root",
            knowledge_root,
            "--summary",
            str(data.get("summary", "")),
            "--category",
            str(data.get("category", "")),
        ]
        for flag, key in (("--tag", "tag"), ("--evidence-path", "evidence_path")):
            values = data.get(key, [])
            if not isinstance(values, list):
                values = [values]
            for value in values:
                if str(value).strip():
                    command.extend([flag, str(value)])
        return command
    if action == "capture-platform-data-fields":
        command = [
            *base,
            "capture-platform-data-fields",
            "--knowledge-root",
            knowledge_root,
        ]
        if data.get("enable_live_api"):
            command.append("--enable-live-api")
        if data.get("max_scopes"):
            command.extend(["--max-scopes", str(data.get("max_scopes"))])
        if data.get("max_datasets_per_scope"):
            command.extend(["--max-datasets-per-scope", str(data.get("max_datasets_per_scope"))])
        if data.get("max_fields_per_dataset"):
            command.extend(["--max-fields-per-dataset", str(data.get("max_fields_per_dataset"))])
        if data.get("fields_per_scope"):
            command.extend(["--fields-per-scope", str(data.get("fields_per_scope"))])
        if data.get("capture_plan_path"):
            command.extend(["--capture-plan-path", str(data.get("capture_plan_path"))])
        if data.get("resume_capture"):
            command.append("--resume-capture")
        if data.get("data_capture_date"):
            command.extend(["--data-capture-date", str(data.get("data_capture_date"))])
        return command
    if action == "compile-data-ledger":
        return [*base, "compile-data-ledger", "--knowledge-root", knowledge_root]
    if action == "compile-knowledge":
        return [*base, "compile-knowledge", "--knowledge-root", knowledge_root, "--apply-cleanup"]
    if action == "delivery-gate":
        return [*base, "delivery-gate", "--knowledge-root", knowledge_root, "--runs-root", str(paths.runs_root)]
    if action == "plan-research-options":
        command = [
            *base,
            "plan-research-options",
            "--knowledge-root",
            knowledge_root,
            "--option-output-dir",
            str(decision_artifacts_root(paths.knowledge_root)),
            "--max-options",
            str(data.get("max_options", 5)),
        ]
        if data.get("enable_live_api"):
            command.append("--enable-live-api")
        return command
    if action == "workflow-start":
        command = [
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
        for flag, key in (
            ("--selected-region", "selected_region"),
            ("--selected-delay", "selected_delay"),
            ("--selected-universe", "selected_universe"),
        ):
            if data.get(key) not in (None, ""):
                command.extend([flag, str(data[key])])
        if data.get("enable_live_api"):
            command.append("--enable-live-api")
        return command
    if action == "workflow-continue":
        return [*base, "workflow-continue", "--knowledge-root", knowledge_root, "--run-dir", str(paths.runs_root)]
    if action == "workflow-auto-continue":
        command = [*base, "workflow-run", "--knowledge-root", knowledge_root, "--run-dir", str(paths.runs_root),
                   "--ai-executor", "codex", "--expected-runtime-revision", str(data.get("expected_runtime_revision", ""))]
        return command
    if action == "workflow-acknowledge-source-rate-limit":
        reason = str(data.get("reason", "")).strip() or "operator confirmed platform recovery"
        return [
            *base,
            "workflow-acknowledge-source-rate-limit",
            "--knowledge-root",
            knowledge_root,
            "--run-dir",
            str(paths.runs_root),
            "--reason",
            reason,
        ]
    if action == "workflow-stop":
        return [*base, "workflow-pause", "--knowledge-root", knowledge_root, "--run-dir", str(paths.runs_root)]
    if action == "workflow-resume":
        return [*base, "workflow-resume", "--knowledge-root", knowledge_root, "--run-dir", str(paths.runs_root)]
    if action == "workflow-import-scout-seed-artifacts":
        source_run_id = str(data.get("source_run_id", "")).strip()
        if not source_run_id:
            raise ValueError("source_run_id is required")
        return [
            *base,
            "workflow-import-scout-seed-artifacts",
            "--knowledge-root",
            knowledge_root,
            "--run-dir",
            str(paths.runs_root),
            "--source-run-id",
            source_run_id,
        ]
    if action == "workflow-status":
        return [*base, "workflow-status", "--knowledge-root", knowledge_root, "--run-dir", str(paths.runs_root)]
    raise ValueError(f"unsupported console action: {action}")
