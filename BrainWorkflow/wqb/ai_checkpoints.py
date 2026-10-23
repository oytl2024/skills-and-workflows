from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import os
import signal
import time
from typing import Any, Callable
from uuid import uuid4

from wqb.runtime_control import check_submission_allowed, RuntimePaused


CHECKPOINTS_FILENAME = "ai_checkpoints.jsonl"
CHECKPOINT_EVENTS_FILENAME = "ai_checkpoint_events.jsonl"
DEFAULT_EXECUTOR_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class AICheckpoint:
    checkpoint_id: str
    checkpoint_type: str
    reason: str
    evidence_paths: list[str]
    created_at: str
    status: str = "pending"


def _checkpoint_path(decisions_dir: str | Path) -> Path:
    """Input: decisions directory. Output: checkpoint file path. Resolve durable AI checkpoint storage."""
    return Path(decisions_dir) / CHECKPOINTS_FILENAME


def append_ai_checkpoint(
    decisions_dir: str | Path,
    checkpoint_type: str,
    reason: str,
    evidence_paths: list[str],
    created_at: str,
    status: str = "pending",
) -> AICheckpoint:
    """Input: checkpoint fields. Output: persisted checkpoint. Record required GPT/Codex judgment."""
    path = _checkpoint_path(decisions_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = AICheckpoint(
        checkpoint_id=f"ai-{uuid4().hex[:10]}",
        checkpoint_type=str(checkpoint_type),
        reason=str(reason),
        evidence_paths=[str(item) for item in evidence_paths],
        created_at=str(created_at),
        status=str(status),
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(checkpoint), ensure_ascii=False, sort_keys=True) + "\n")
    return checkpoint


def load_ai_checkpoints(decisions_dir: str | Path) -> list[dict[str, Any]]:
    """Input: decisions directory. Output: checkpoint rows. Read pending GPT/Codex judgment records."""
    path = _checkpoint_path(decisions_dir)
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("checkpoint_id") and row.get("checkpoint_type"):
            rows.append(row)
    events_path = Path(decisions_dir) / CHECKPOINT_EVENTS_FILENAME
    if events_path.exists():
        by_id = {row["checkpoint_id"]: row for row in rows}
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("checkpoint_id") in by_id:
                by_id[event["checkpoint_id"]].update({key: value for key, value in event.items() if key != "checkpoint_id"})
    return rows


def _append_checkpoint_event(decisions_dir: str | Path, event: dict[str, Any]) -> None:
    """Input: decisions directory and event dict. Output: None. Append durable executor status."""
    path = Path(decisions_dir) / CHECKPOINT_EVENTS_FILENAME
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def stop_worker_tree(process: subprocess.Popen) -> None:
    """Input: owned worker Popen. Output: None. Stop its descendants before acknowledging Pause."""
    if os.name == 'nt':
        result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        if result.returncode and process.poll() is None:
            raise RuntimeError('AI worker tree cancellation failed')
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.communicate(timeout=10)


class AICheckpointCancelled(RuntimeError):
    """Knowledge job cancellation, without granting or consulting research authority."""


def _model_worker_environment() -> dict[str, str]:
    """Input: process environment. Output: str environment dict. Exclude platform and secret variables from every model worker."""
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith('WQB_') and not any(
                word in key.upper() for word in ('PASSWORD', 'SECRET', 'TOKEN', 'API_KEY'))}


def _run_cancellable(argv: list[str], timeout_seconds: int,
                     cancellation_check: Callable[[], bool] | None = None,
                     cancel_on_pause: bool = True) -> subprocess.CompletedProcess:
    """Input: argv list and bound int. Output: result. Check Stop while a read-only AI worker runs."""
    def check_cancel() -> None:
        """Input: none. Output: None. Preserve legacy Pause and optional independent cancellation."""
        if cancel_on_pause:
            check_submission_allowed()
        if cancellation_check is not None and cancellation_check():
            raise AICheckpointCancelled('knowledge_job_cancelled')
    check_cancel()
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               shell=False, start_new_session=os.name != 'nt', env=_model_worker_environment())
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            check_cancel()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout_seconds)
            try:
                stdout, stderr = process.communicate(timeout=min(1, remaining))
                check_cancel()
                return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise
    except BaseException:
        stop_worker_tree(process)
        raise


def run_ai_checkpoint(
    decisions_dir: str | Path,
    checkpoint_id: str,
    executor_argv: list[str],
    timeout_seconds: int = DEFAULT_EXECUTOR_TIMEOUT_SECONDS,
    *, cancel_on_pause: bool = False,
    cancellation_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Input: checkpoint ID, explicit argv, timeout. Output: status dict. Run an auditable local AI worker."""
    checkpoint = next((row for row in load_ai_checkpoints(decisions_dir) if row["checkpoint_id"] == checkpoint_id), None)
    if checkpoint is None:
        raise ValueError(f"Unknown AI checkpoint: {checkpoint_id}")
    if checkpoint.get('status') in {'unknown', 'running'} or (
            checkpoint['checkpoint_type'] == 'initial_research_plan' and checkpoint.get('status') != 'pending'):
        return checkpoint
    if not executor_argv:
        return {"checkpoint_id": checkpoint_id, "status": "pending", "reason": "executor-not-configured"}
    if checkpoint["status"] == "completed":
        return checkpoint
    if "{input}" not in executor_argv or "{output}" not in executor_argv:
        raise ValueError("AI executor argv must include {input} and {output} placeholders")
    if timeout_seconds <= 0:
        raise ValueError("AI executor timeout must be positive")
    attempt_dir = Path(decisions_dir) / "ai_checkpoint_runs" / checkpoint_id / uuid4().hex
    attempt_dir.mkdir(parents=True, exist_ok=False)
    input_path = attempt_dir / "input.json"
    output_path = attempt_dir / "output.json"
    input_path.write_text(json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    running = {"checkpoint_id": checkpoint_id, "status": "running", "input_path": str(input_path), "output_path": str(output_path)}
    _append_checkpoint_event(decisions_dir, running)
    argv = [str(input_path) if arg == "{input}" else str(output_path) if arg == "{output}" else arg for arg in executor_argv]
    try:
        if checkpoint['checkpoint_type'] == 'initial_research_plan':
            from wqb.initial_model_worker import _authenticated_task
            from wqb.initial_research_planning import TASK_PATH
            from wqb.semantic_compilation import _check_schema
            run = Path(decisions_dir).resolve().parent.parent
            initial_task = _authenticated_task(run)
            if checkpoint['evidence_paths'] != [TASK_PATH]:
                raise ValueError('initial planning checkpoint evidence mismatch')
        if cancellation_check is not None:
            result = _run_cancellable(argv, timeout_seconds, cancellation_check, cancel_on_pause)
        else:
            result = (_run_cancellable(argv, timeout_seconds) if cancel_on_pause else
                      subprocess.run(argv, capture_output=True, text=True, timeout=timeout_seconds, check=False,
                                     shell=False, env=_model_worker_environment()))
        if result.returncode != 0:
            raise RuntimeError(f"executor exit {result.returncode}: {result.stderr[-500:]}")
        output = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(output, dict) or not output.get("summary"):
            raise ValueError("AI executor output must be JSON with nonempty summary")
        final = {**running, "status": "completed", "summary": str(output["summary"])}
        if checkpoint['checkpoint_type'] == 'initial_research_plan':
            task = _authenticated_task(run)
            if task != initial_task:
                raise ValueError('initial planning task changed during executor run')
            _check_schema(task['brief']['output_schema'], output)
            final.update(output)
        if checkpoint['checkpoint_type'] == 'semantic_compile':
            from wqb.semantic_compilation import validate_semantic_output
            validate_semantic_output(output)
            final['proposals'] = output['proposals']
        if checkpoint['checkpoint_type'] == 'hypothesis_design':
            from wqb.hypothesis_design import design_output_schema
            from wqb.semantic_compilation import _check_schema
            _check_schema(design_output_schema(), output)
            final['designs'] = output['designs']
        if isinstance(output.get("decision"), dict):
            final["decision"] = output["decision"]
        if cancellation_check is not None and cancellation_check():
            raise AICheckpointCancelled('knowledge_job_cancelled')
    except AICheckpointCancelled as exc:
        final = {**running, 'status': 'cancelled', 'error': str(exc)}
    except RuntimePaused:
        _append_checkpoint_event(decisions_dir, {**running, 'status': 'cancelled', 'error': 'user_paused'})
        raise
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        final = {**running, "status": "failed", "error": str(exc)[:500]}
    _append_checkpoint_event(decisions_dir, final)
    return final


def schedule_run_checkpoint(
    run_dir: str | Path,
    result: dict[str, Any],
    now: str,
    executor_argv: list[str],
) -> dict[str, Any] | None:
    """Input: run, stage result, time and worker argv. Output: checkpoint or None. Schedule selected judgments once per run."""
    run = Path(run_dir)
    stage = str(result.get("current_stage", ""))
    status = str(result.get("status", ""))
    specs = {
        "scout_seed": ("research_option_reasoning", "Review the selected scope and economic hypothesis before source exploration.",
                       run / "stages" / "schedule" / "research_schedule.json"),
        "repair": ("near_miss_interpretation", "Explain the checked near miss and propose one bounded repair hypothesis.",
                   run / "all_alphas.jsonl"),
        "user_approval": ("candidate_risk_review", "Summarize remaining risks in checked candidate evidence for human approval.",
                          run / "candidate_gate.json"),
        "complete": ("research_reflection", "Extract reusable research lessons; do not change benchmark rules automatically.",
                     run / "research_record.json"),
    }
    key = "complete" if status in {"completed", "completed_with_warnings"} else stage
    if key not in specs:
        return None
    checkpoint_type, reason, evidence = specs[key]
    if not evidence.is_file():
        return None
    directory = run / "stages" / "ai"
    existing = next((row for row in load_ai_checkpoints(directory)
                     if row.get("checkpoint_type") == checkpoint_type), None)
    if existing is not None:
        if existing.get("status") == "pending" and executor_argv:
            return run_ai_checkpoint(directory, str(existing["checkpoint_id"]), executor_argv, cancel_on_pause=True)
        return existing
    checkpoint = append_ai_checkpoint(directory, checkpoint_type, reason, [str(evidence)], now)
    if not executor_argv:
        return asdict(checkpoint)
    return run_ai_checkpoint(directory, checkpoint.checkpoint_id, executor_argv, cancel_on_pause=True)
