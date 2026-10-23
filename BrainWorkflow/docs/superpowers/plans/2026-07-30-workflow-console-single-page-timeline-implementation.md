# Workflow Console Single-Page Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-page BrainWorkflow Console with an event-backed runtime timeline, asynchronous long-job progress, inline decisions, and visible GPT/Codex judgment checkpoints.

**Architecture:** Keep the Orchestrator as the owner of research workflow state. Add small read-model helpers around Console jobs, progress probes, timeline rows, and AI checkpoints, then render them through the existing standard-library HTTP server. Preserve existing CLI commands and Console job files so old jobs remain readable.

**Tech Stack:** Python standard library, `http.server`, `subprocess`, `threading`, JSON/JSONL files, Markdown docs, standard-library `unittest`.

## Global Constraints

- No frontend framework migration.
- No multi-page app redesign for normal use.
- No change to Scout, Seed, Discovery, Repair, or Submit logic.
- No live simulation execution in this implementation.
- No automatic Alpha submission.
- No direct model API integration inside the local HTTP server.
- No deletion of legacy or stage1 archive material.
- Existing job records must remain readable.
- Deterministic actions must not be labeled as GPT/Codex work.
- GPT/Codex intervention points must be durable checkpoint records for a later agent runner.
- Long actions must not block the browser request.
- Use `unittest`, not `pytest`.
- For Windows Codex shell verification, set `SystemRoot` and `windir` before socket or Git commands when needed.

---

## File Structure

- Modify `wqb/console_jobs.py`
  - Keep `create_job`, `run_job`, `finish_job`, `load_job_history`, and `build_cli_command`.
  - Add asynchronous start/watch/reconcile behavior while preserving synchronous `run_job` for tests and short internal actions.

- Create `wqb/console_progress.py`
  - Own file-size, JSONL-row-count, capture-directory, process-liveness, and action-specific progress probes.
  - Keep these helpers independent from HTTP rendering.

- Create `wqb/ai_checkpoints.py`
  - Own durable `ai_checkpoints.jsonl` records under `knowledge/wiki/70_decisions/`.
  - No model calls in this module.

- Create `wqb/console_timeline.py`
  - Convert the aggregated Console state into stable timeline rows and one current-work panel.
  - Keep UI rendering separate from timeline state construction.

- Modify `wqb/console_state.py`
  - Reconcile running jobs and include `ai_checkpoints`, `timeline`, and `current_work` in `load_console_state`.

- Modify `wqb/console_server.py`
  - Render the single-page Control Center.
  - Add `/api/state`.
  - Start long actions asynchronously and redirect immediately.
  - Keep `/proposals` as a compatibility route.

- Modify `wqb/console_context.py`
  - Record context only when a job reaches a terminal or refused state.
  - Avoid writing a finished-job milestone entry for a still-running async job.

- Modify tests:
  - `tests/test_console_jobs.py`
  - `tests/test_console_state.py`
  - `tests/test_console_server.py`
  - Add `tests/test_console_progress.py`
  - Add `tests/test_ai_checkpoints.py`
  - Add `tests/test_console_timeline.py`

- Modify docs:
  - `docs/operations/operating_guide.md`
  - `docs/operations/maintainer_handoff.md`

---

### Task 1: Progress Probe Helpers

**Files:**
- Create: `wqb/console_progress.py`
- Test: `tests/test_console_progress.py`

**Interfaces:**
- Produces:
  - `count_jsonl_rows(path: str | Path) -> int`
  - `file_snapshot(path: str | Path) -> dict[str, object]`
  - `latest_data_capture_dir(knowledge_root: str | Path) -> Path | None`
  - `probe_data_capture_progress(knowledge_root: str | Path, capture_dir: str | Path | None = None) -> dict[str, object]`
  - `process_is_alive(pid: int | None) -> bool`
- Consumes:
  - `knowledge/raw/platform/data_fields/<date>/` raw capture files.

- [ ] **Step 1: Write failing tests for JSONL row counts and file snapshots**

Add to `tests/test_console_progress.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.console_progress import count_jsonl_rows, file_snapshot


class ConsoleProgressTests(unittest.TestCase):
    def test_count_jsonl_rows_skips_blank_lines_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "rows.jsonl"
            path.write_text('{"a":1}\n\n{"b":2}\n', encoding="utf-8")

            count = count_jsonl_rows(path)
            missing = count_jsonl_rows(root / "missing.jsonl")

        self.assertEqual(count, 2)
        self.assertEqual(missing, 0)

    def test_file_snapshot_reports_size_and_write_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data_fields.jsonl"
            path.write_text('{"field":"x"}\n', encoding="utf-8")

            snapshot = file_snapshot(path)
            missing = file_snapshot(root / "missing.jsonl")

        self.assertEqual(snapshot["exists"], True)
        self.assertGreater(snapshot["bytes"], 0)
        self.assertIn("last_write_at", snapshot)
        self.assertEqual(missing["exists"], False)
        self.assertEqual(missing["bytes"], 0)
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run:

```powershell
python -m unittest tests.test_console_progress -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.console_progress'`.

- [ ] **Step 3: Implement the minimal helper functions**

Create `wqb/console_progress.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any


def _iso_from_mtime(path: Path) -> str:
    """Input: file path. Output: UTC timestamp string. Convert file modified time for UI progress."""
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()


def count_jsonl_rows(path: str | Path) -> int:
    """Input: JSONL path. Output: non-empty row count. Count persisted progress rows safely."""
    target = Path(path)
    if not target.exists():
        return 0
    count = 0
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def file_snapshot(path: str | Path) -> dict[str, Any]:
    """Input: file path. Output: JSON-safe file snapshot. Report existence, size, and write time."""
    target = Path(path)
    if not target.exists():
        return {"exists": False, "bytes": 0, "last_write_at": ""}
    return {"exists": True, "bytes": target.stat().st_size, "last_write_at": _iso_from_mtime(target)}


def latest_data_capture_dir(knowledge_root: str | Path) -> Path | None:
    """Input: knowledge root. Output: latest capture directory or none. Locate raw data-field captures."""
    root = Path(knowledge_root) / "raw" / "platform" / "data_fields"
    if not root.exists():
        return None
    captures = sorted(path for path in root.iterdir() if path.is_dir())
    return captures[-1] if captures else None


def process_is_alive(pid: int | None) -> bool:
    """Input: process id or none. Output: bool. Check whether a child process still exists."""
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError, OverflowError):
        return False
    return True
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_console_progress -v
```

Expected: PASS.

- [ ] **Step 5: Add capture progress tests**

Append to `tests/test_console_progress.py`:

```python
from wqb.console_progress import latest_data_capture_dir, probe_data_capture_progress


class ConsoleCaptureProgressTests(unittest.TestCase):
    def test_probe_data_capture_progress_counts_raw_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge = Path(tmp) / "knowledge"
            capture = knowledge / "raw" / "platform" / "data_fields" / "2026-07-30"
            capture.mkdir(parents=True)
            (capture / "scopes.jsonl").write_text('{"scope":"usa"}\n', encoding="utf-8")
            (capture / "data_sets.jsonl").write_text('{"id":"ds1"}\n{"id":"ds2"}\n', encoding="utf-8")
            (capture / "data_fields.jsonl").write_text('{"id":"f1"}\n{"id":"f2"}\n{"id":"f3"}\n', encoding="utf-8")
            (capture / "errors.jsonl").write_text('{"error":"rate"}\n', encoding="utf-8")
            (capture / "manifest.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")

            latest = latest_data_capture_dir(knowledge)
            progress = probe_data_capture_progress(knowledge)

        self.assertEqual(latest, capture)
        self.assertEqual(progress["capture_dir"], str(capture))
        self.assertEqual(progress["scope_rows"], 1)
        self.assertEqual(progress["data_set_rows"], 2)
        self.assertEqual(progress["data_field_rows"], 3)
        self.assertEqual(progress["error_rows"], 1)
        self.assertGreater(progress["data_fields_bytes"], 0)
        self.assertEqual(progress["manifest_status"], "completed")
```

- [ ] **Step 6: Run capture progress test and verify it fails**

Run:

```powershell
python -m unittest tests.test_console_progress.ConsoleCaptureProgressTests -v
```

Expected: FAIL with `ImportError` or `AttributeError` for `probe_data_capture_progress`.

- [ ] **Step 7: Implement capture progress probing**

Append to `wqb/console_progress.py`:

```python
import json


def _read_manifest_status(capture_dir: Path) -> str:
    """Input: capture directory. Output: manifest status string. Read terminal capture state when present."""
    manifest = capture_dir / "manifest.json"
    if not manifest.exists():
        return ""
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "malformed"
    if not isinstance(payload, dict):
        return "malformed"
    return str(payload.get("status", ""))


def _max_write_time(*paths: Path) -> str:
    """Input: paths. Output: latest write timestamp. Summarize progress freshness."""
    existing = [path for path in paths if path.exists()]
    if not existing:
        return ""
    latest = max(existing, key=lambda item: item.stat().st_mtime)
    return _iso_from_mtime(latest)


def probe_data_capture_progress(
    knowledge_root: str | Path,
    capture_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Input: knowledge root and optional capture dir. Output: JSON-safe progress. Count raw platform capture files."""
    capture = Path(capture_dir) if capture_dir is not None else latest_data_capture_dir(knowledge_root)
    if capture is None:
        return {
            "capture_dir": "",
            "scope_rows": 0,
            "data_set_rows": 0,
            "data_field_rows": 0,
            "error_rows": 0,
            "data_fields_bytes": 0,
            "last_write_at": "",
            "manifest_status": "",
        }
    scopes = capture / "scopes.jsonl"
    data_sets = capture / "data_sets.jsonl"
    data_fields = capture / "data_fields.jsonl"
    errors = capture / "errors.jsonl"
    return {
        "capture_dir": str(capture),
        "scope_rows": count_jsonl_rows(scopes),
        "data_set_rows": count_jsonl_rows(data_sets),
        "data_field_rows": count_jsonl_rows(data_fields),
        "error_rows": count_jsonl_rows(errors),
        "data_fields_bytes": file_snapshot(data_fields)["bytes"],
        "last_write_at": _max_write_time(scopes, data_sets, data_fields, errors),
        "manifest_status": _read_manifest_status(capture),
    }
```

- [ ] **Step 8: Run focused tests**

Run:

```powershell
python -m unittest tests.test_console_progress -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add BrainWorkflow/wqb/console_progress.py BrainWorkflow/tests/test_console_progress.py
git commit -m "add console progress probes"
```

---

### Task 2: Asynchronous Console Jobs

**Files:**
- Modify: `wqb/console_jobs.py`
- Modify: `tests/test_console_jobs.py`

**Interfaces:**
- Consumes:
  - `probe_data_capture_progress(knowledge_root, capture_dir=None) -> dict[str, object]`
  - `process_is_alive(pid) -> bool`
- Produces:
  - New optional `ConsoleJob` fields: `started_at`, `finished_at`, `pid`, `duration_seconds`, `last_progress_at`, `progress_kind`, `progress`, `status_message`
  - `start_job_async(job: ConsoleJob, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> ConsoleJob`
  - `watch_job(job: ConsoleJob, process: subprocess.Popen[object], timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> ConsoleJob`
  - `reconcile_job_dict(row: dict[str, object], knowledge_root: str | Path | None = None) -> dict[str, object]`

- [ ] **Step 1: Write failing tests for async return and PID persistence**

Append to `tests/test_console_jobs.py`:

```python
import time

from wqb.console_jobs import reconcile_job_dict, start_job_async


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
            time.sleep(0.8)
            final_payload = json.loads((Path(job.job_dir) / "job.json").read_text(encoding="utf-8"))
            stdout = Path(job.stdout_path).read_text(encoding="utf-8")

        self.assertEqual(final_payload["status"], "completed")
        self.assertEqual(final_payload["exit_code"], 0)
        self.assertIn("done", stdout)
        self.assertTrue(Path(final_payload["summary_path"]).exists())
```

- [ ] **Step 2: Run async test and verify missing function failure**

Run:

```powershell
python -m unittest tests.test_console_jobs.AsyncConsoleJobsTests.test_start_job_async_returns_running_job_with_pid_before_command_finishes -v
```

Expected: FAIL with `ImportError` for `start_job_async`.

- [ ] **Step 3: Extend `ConsoleJob` with backward-compatible optional fields**

Modify the `ConsoleJob` dataclass in `wqb/console_jobs.py`:

```python
    started_at: str = ""
    finished_at: str = ""
    pid: int | None = None
    duration_seconds: float | None = None
    last_progress_at: str = ""
    progress_kind: str = ""
    progress: dict[str, Any] | None = None
    status_message: str = ""
```

Add helper functions near `_now()`:

```python
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
```

- [ ] **Step 4: Implement async start and watcher**

Add imports:

```python
import threading
```

Add to `wqb/console_jobs.py`:

```python
def _finalize_process_result(job: ConsoleJob, returncode: int, error: str = "") -> ConsoleJob:
    """Input: running job and return code. Output: terminal job. Persist process result."""
    finished = _now()
    status = "completed" if returncode == 0 else "failed"
    completed = replace(
        job,
        status=status,
        updated_at=finished,
        finished_at=finished,
        duration_seconds=_duration_seconds(job.started_at, finished),
        exit_code=returncode,
        error=error,
        status_message=status,
    )
    _write_summary(completed)
    return _write_job(completed)


def watch_job(
    job: ConsoleJob,
    process: subprocess.Popen[Any],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> ConsoleJob:
    """Input: running job, process, timeout. Output: terminal job. Wait for async process and persist result."""
    try:
        returncode = process.wait(timeout=timeout_seconds)
        return _finalize_process_result(job, int(returncode))
    except subprocess.TimeoutExpired:
        process.kill()
        returncode = process.wait()
        return _finalize_process_result(job, int(returncode), f"timed out after {timeout_seconds}s")


def start_job_async(job: ConsoleJob, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> ConsoleJob:
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
        return finish_job(job, "failed", exit_code=-1, error=f"{job.command[0] if job.command else 'command'}: {error}")
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
    thread = threading.Thread(target=watch_job, args=(running, process, timeout_seconds), daemon=True)
    thread.start()
    return running
```

- [ ] **Step 5: Run async persistence test**

Run:

```powershell
python -m unittest tests.test_console_jobs.AsyncConsoleJobsTests.test_start_job_async_returns_running_job_with_pid_before_command_finishes -v
```

Expected: PASS.

- [ ] **Step 6: Write failing reconciliation tests**

Append to `AsyncConsoleJobsTests`:

```python
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

    def test_reconcile_completed_job_keeps_terminal_state(self):
        row = {"job_id": "job-2", "status": "completed", "action": "readiness-check", "exit_code": 0}

        reconciled = reconcile_job_dict(row, None)

        self.assertEqual(reconciled["status"], "completed")
        self.assertEqual(reconciled["exit_code"], 0)
```

- [ ] **Step 7: Run reconciliation tests and verify missing function failure**

Run:

```powershell
python -m unittest tests.test_console_jobs.AsyncConsoleJobsTests.test_reconcile_running_capture_job_adds_progress_without_claiming_completion tests.test_console_jobs.AsyncConsoleJobsTests.test_reconcile_completed_job_keeps_terminal_state -v
```

Expected: FAIL with `ImportError` or `NameError` for `reconcile_job_dict`.

- [ ] **Step 8: Implement job reconciliation**

Add imports:

```python
from wqb.console_progress import probe_data_capture_progress, process_is_alive
```

Add to `wqb/console_jobs.py`:

```python
TERMINAL_JOB_STATUSES = {"completed", "failed", "refused", "timed_out"}


def _progress_for_action(action: str, knowledge_root: str | Path | None) -> tuple[str, dict[str, Any]]:
    """Input: action and knowledge root. Output: progress kind and payload. Compute action-specific progress."""
    if action == "capture-platform-data-fields" and knowledge_root is not None:
        return "data_capture", probe_data_capture_progress(knowledge_root)
    return "", {}


def reconcile_job_dict(row: dict[str, Any], knowledge_root: str | Path | None = None) -> dict[str, Any]:
    """Input: persisted job row and knowledge root. Output: reconciled row. Refresh running job state for the Console."""
    result = dict(row)
    status = str(result.get("status", ""))
    action = str(result.get("action", ""))
    progress_kind, progress = _progress_for_action(action, knowledge_root)
    if progress_kind:
        result["progress_kind"] = progress_kind
        result["progress"] = progress
        result["last_progress_at"] = str(progress.get("last_write_at", ""))
    if status in TERMINAL_JOB_STATUSES:
        return result
    if status == "running":
        pid = result.get("pid")
        if process_is_alive(int(pid)) if isinstance(pid, int) else False:
            result["status_message"] = "running"
            return result
        if result.get("exit_code") is None:
            result["status"] = "detached"
            result["status_message"] = "process handle is no longer attached"
    return result
```

- [ ] **Step 9: Apply reconciliation in job history**

Modify `load_job_history`:

```python
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
```

- [ ] **Step 10: Run console job tests**

Run:

```powershell
python -m unittest tests.test_console_jobs -v
```

Expected: PASS.

- [ ] **Step 11: Commit**

```powershell
git add BrainWorkflow/wqb/console_jobs.py BrainWorkflow/tests/test_console_jobs.py
git commit -m "add async console jobs"
```

---

### Task 3: AI Checkpoint Store

**Files:**
- Create: `wqb/ai_checkpoints.py`
- Test: `tests/test_ai_checkpoints.py`

**Interfaces:**
- Produces:
  - `AICheckpoint`
  - `append_ai_checkpoint(decisions_dir: str | Path, checkpoint_type: str, reason: str, evidence_paths: list[str], created_at: str, status: str = "pending") -> AICheckpoint`
  - `load_ai_checkpoints(decisions_dir: str | Path) -> list[dict[str, object]]`
- Consumes:
  - `knowledge/wiki/70_decisions/ai_checkpoints.jsonl`

- [ ] **Step 1: Write failing checkpoint store tests**

Create `tests/test_ai_checkpoints.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.ai_checkpoints import append_ai_checkpoint, load_ai_checkpoints


class AICheckpointTests(unittest.TestCase):
    def test_append_and_load_ai_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            decisions = Path(tmp) / "knowledge" / "wiki" / "70_decisions"

            checkpoint = append_ai_checkpoint(
                decisions,
                "blocker_explanation",
                "Research readiness is blocked by stale data ledger.",
                ["runs/readiness/report.md"],
                "2026-07-30T00:00:00+00:00",
            )
            rows = load_ai_checkpoints(decisions)

        self.assertTrue(checkpoint.checkpoint_id.startswith("ai-"))
        self.assertEqual(rows[0]["checkpoint_type"], "blocker_explanation")
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["evidence_paths"], ["runs/readiness/report.md"])

    def test_load_ai_checkpoints_skips_malformed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            decisions = Path(tmp)
            decisions.mkdir()
            (decisions / "ai_checkpoints.jsonl").write_text(
                "not-json\n"
                '{"checkpoint_id":"ai-good","checkpoint_type":"template_innovation","reason":"Need a novel template.","evidence_paths":[],"created_at":"2026-07-30T00:00:00+00:00","status":"pending"}\n',
                encoding="utf-8",
            )

            rows = load_ai_checkpoints(decisions)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["checkpoint_id"], "ai-good")
```

- [ ] **Step 2: Run tests and verify missing module failure**

Run:

```powershell
python -m unittest tests.test_ai_checkpoints -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement checkpoint store**

Create `wqb/ai_checkpoints.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


CHECKPOINTS_FILENAME = "ai_checkpoints.jsonl"


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
    return rows
```

- [ ] **Step 4: Run checkpoint tests**

Run:

```powershell
python -m unittest tests.test_ai_checkpoints -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add BrainWorkflow/wqb/ai_checkpoints.py BrainWorkflow/tests/test_ai_checkpoints.py
git commit -m "add ai checkpoint store"
```

---

### Task 4: Timeline Read Model

**Files:**
- Create: `wqb/console_timeline.py`
- Modify: `wqb/console_state.py`
- Test: `tests/test_console_timeline.py`
- Modify: `tests/test_console_state.py`

**Interfaces:**
- Consumes:
  - Console state dict from `load_console_state`
  - AI checkpoint rows
  - reconciled job rows
- Produces:
  - `build_timeline_rows(state: dict[str, object]) -> list[dict[str, object]]`
  - `select_current_work(state: dict[str, object], timeline: list[dict[str, object]]) -> dict[str, object]`
  - `load_console_state(paths)` includes `timeline`, `current_work`, and `ai_checkpoints`.

- [ ] **Step 1: Write failing timeline tests**

Create `tests/test_console_timeline.py`:

```python
import unittest

from wqb.console_timeline import build_timeline_rows, select_current_work


class ConsoleTimelineTests(unittest.TestCase):
    def test_timeline_marks_running_capture_and_ai_checkpoint(self):
        state = {
            "jobs": [
                {
                    "job_id": "job-capture",
                    "action": "capture-platform-data-fields",
                    "status": "running",
                    "progress_kind": "data_capture",
                    "progress": {"data_field_rows": 12, "capture_dir": "knowledge/raw/platform/data_fields/2026-07-30"},
                }
            ],
            "active_workflow": {"exists": False},
            "workflow_events": [],
            "ai_checkpoints": [
                {
                    "checkpoint_id": "ai-1",
                    "checkpoint_type": "blocker_explanation",
                    "reason": "Explain stale data ledger.",
                    "status": "pending",
                    "evidence_paths": ["runs/readiness/report.md"],
                }
            ],
            "freshness": {"stale_count": 1, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120},
            "option_cards": [],
        }

        rows = build_timeline_rows(state)
        current = select_current_work(state, rows)

        capture_rows = [row for row in rows if row["stage_id"] == "platform_data_capture"]
        ai_rows = [row for row in rows if row["source"] == "ai_judgment"]
        self.assertEqual(capture_rows[0]["status"], "running")
        self.assertEqual(ai_rows[0]["status"], "waiting")
        self.assertEqual(current["title"], "Platform data capture")
        self.assertIn("12", current["details"][0])

    def test_timeline_uses_active_workflow_stage_as_current_work(self):
        state = {
            "jobs": [],
            "active_workflow": {"exists": True, "run_id": "run1", "current_stage": "repair", "next_action": "workflow-continue", "waiting_for_user": False},
            "workflow_events": [{"event_type": "repair_started", "occurred_at": "2026-07-30T00:00:00+00:00", "payload": {}}],
            "ai_checkpoints": [],
            "freshness": {"stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120},
            "option_cards": [{"title": "Power Pool"}],
        }

        rows = build_timeline_rows(state)
        current = select_current_work(state, rows)

        repair_rows = [row for row in rows if row["stage_id"] == "repair"]
        self.assertEqual(repair_rows[0]["status"], "running")
        self.assertEqual(current["title"], "Repair")
        self.assertEqual(current["next_action"], "workflow-continue")
```

- [ ] **Step 2: Run timeline tests and verify missing module failure**

Run:

```powershell
python -m unittest tests.test_console_timeline -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement timeline module**

Create `wqb/console_timeline.py`:

```python
from __future__ import annotations

from typing import Any


WORKFLOW_STAGE_LABELS = {
    "knowledge_health": "Knowledge health",
    "platform_data_capture": "Platform data capture",
    "data_ledger_compile": "Data ledger compile",
    "research_options": "Research options",
    "user_research_decision": "Research decision",
    "workflow_start": "Workflow start",
    "scout": "Scout",
    "seed": "Seed",
    "batch": "30 alpha batch",
    "simulation": "Multisim and backtest",
    "triage": "Triage",
    "repair": "Repair",
    "submit_review": "Submit review",
    "submission_approval": "Submission approval",
    "knowledge_compile": "Knowledge compile",
}


def _row(stage_id: str, status: str, source: str, explanation: str, evidence_path: str = "") -> dict[str, Any]:
    """Input: timeline fields. Output: JSON-safe row. Build one stable workflow timeline row."""
    return {
        "stage_id": stage_id,
        "label": WORKFLOW_STAGE_LABELS.get(stage_id, stage_id.replace("_", " ").title()),
        "status": status,
        "source": source,
        "explanation": explanation,
        "evidence_path": evidence_path,
    }


def _running_job_for_action(state: dict[str, Any], action: str) -> dict[str, Any] | None:
    """Input: console state and action. Output: running job or none. Find active durable job."""
    for job in state.get("jobs", []):
        if isinstance(job, dict) and job.get("action") == action and job.get("status") in {"running", "detached"}:
            return job
    return None


def _stage_status_from_workflow(state: dict[str, Any], stage_id: str) -> str:
    """Input: console state and stage id. Output: timeline status. Map Orchestrator stage to row status."""
    workflow = state.get("active_workflow", {})
    if not isinstance(workflow, dict) or not workflow.get("exists"):
        return "not_started"
    current = str(workflow.get("current_stage", "")).lower()
    if current == stage_id:
        return "waiting" if workflow.get("waiting_for_user") else "running"
    return "ready"


def build_timeline_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Input: console state. Output: timeline rows. Build the one-page workflow run tape."""
    freshness = state.get("freshness", {}) if isinstance(state.get("freshness"), dict) else {}
    data_coverage = state.get("data_coverage", {}) if isinstance(state.get("data_coverage"), dict) else {}
    capture_job = _running_job_for_action(state, "capture-platform-data-fields")
    compile_job = _running_job_for_action(state, "compile-data-ledger")
    rows = [
        _row(
            "knowledge_health",
            "blocked" if int(freshness.get("stale_count", 0) or 0) or int(freshness.get("missing_count", 0) or 0) else "completed",
            "deterministic",
            "Checks raw/wiki freshness and maintenance contract state.",
        ),
        _row(
            "platform_data_capture",
            str(capture_job.get("status")) if capture_job else ("completed" if data_coverage.get("exists") else "not_started"),
            "deterministic",
            "Captures platform data fields into the raw vault.",
            str(data_coverage.get("latest_capture_dir", "")),
        ),
        _row(
            "data_ledger_compile",
            str(compile_job.get("status")) if compile_job else "ready",
            "deterministic",
            "Compiles measured raw platform data into the semantic data ledger.",
        ),
        _row(
            "research_options",
            "completed" if state.get("option_cards") else "ready",
            "ai_judgment",
            "Chooses research options from incentives, data coverage, and template novelty.",
        ),
        _row("user_research_decision", "waiting" if state.get("option_cards") else "not_started", "user_approval", "User selects one research direction and measured scope."),
        _row("workflow_start", _stage_status_from_workflow(state, "workflow_start"), "deterministic", "Creates an Orchestrator-owned workflow run."),
        _row("scout", _stage_status_from_workflow(state, "scout"), "deterministic", "Tests whether a data-template direction has signal."),
        _row("seed", _stage_status_from_workflow(state, "seed"), "ai_judgment", "Locks the economic template kernel for exploitation."),
        _row("batch", _stage_status_from_workflow(state, "batch"), "deterministic", "Builds a 30 alpha batch before simulation."),
        _row("simulation", _stage_status_from_workflow(state, "simulation"), "deterministic", "Runs multisim or backtest and records results."),
        _row("triage", _stage_status_from_workflow(state, "triage"), "ai_judgment", "Classifies results and near misses."),
        _row("repair", _stage_status_from_workflow(state, "repair"), "ai_judgment", "Applies narrow repair levers to promising alphas."),
        _row("submit_review", _stage_status_from_workflow(state, "submit_review"), "deterministic", "Checks submission readiness and candidate gates."),
        _row("submission_approval", "waiting", "user_approval", "User approves a submit-ready Alpha before API submission."),
        _row("knowledge_compile", "ready", "ai_judgment", "Compiles research records back into the knowledge vault."),
    ]
    for checkpoint in state.get("ai_checkpoints", []):
        if isinstance(checkpoint, dict) and checkpoint.get("status") == "pending":
            rows.append(_row("ai_checkpoint", "waiting", "ai_judgment", str(checkpoint.get("reason", "")), ",".join(str(item) for item in checkpoint.get("evidence_paths", []))))
    return rows


def select_current_work(state: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    """Input: console state and timeline. Output: current work summary. Explain the active row for the UI."""
    for job in state.get("jobs", []):
        if isinstance(job, dict) and job.get("status") in {"running", "detached"}:
            if job.get("action") == "capture-platform-data-fields":
                progress = job.get("progress", {}) if isinstance(job.get("progress"), dict) else {}
                return {
                    "title": "Platform data capture",
                    "status": job.get("status"),
                    "next_action": "wait for capture to finish",
                    "details": [
                        f"Fields captured: {progress.get('data_field_rows', 0)}",
                        f"Data sets captured: {progress.get('data_set_rows', 0)}",
                        f"Raw directory: {progress.get('capture_dir', '')}",
                    ],
                    "evidence_paths": [str(progress.get("capture_dir", ""))],
                }
            return {
                "title": str(job.get("action", "Console job")).replace("-", " ").title(),
                "status": job.get("status"),
                "next_action": "watch job evidence files",
                "details": [f"Job ID: {job.get('job_id', '')}"],
                "evidence_paths": [str(job.get("summary_path", ""))],
            }
    workflow = state.get("active_workflow", {})
    if isinstance(workflow, dict) and workflow.get("exists"):
        stage = str(workflow.get("current_stage", "workflow_start"))
        label = WORKFLOW_STAGE_LABELS.get(stage, stage.replace("_", " ").title())
        return {
            "title": label,
            "status": workflow.get("status", ""),
            "next_action": workflow.get("next_action", ""),
            "details": [f"Run ID: {workflow.get('run_id', '')}", f"Current stage: {stage}"],
            "evidence_paths": [str(workflow.get("run_dir", ""))],
        }
    waiting_rows = [row for row in timeline if row.get("status") in {"blocked", "waiting", "running"}]
    row = waiting_rows[0] if waiting_rows else timeline[0]
    return {
        "title": str(row.get("label", "Workflow")),
        "status": row.get("status", ""),
        "next_action": "choose the next safe action",
        "details": [str(row.get("explanation", ""))],
        "evidence_paths": [str(row.get("evidence_path", ""))],
    }
```

- [ ] **Step 4: Run timeline tests**

Run:

```powershell
python -m unittest tests.test_console_timeline -v
```

Expected: PASS.

- [ ] **Step 5: Wire timeline and checkpoints into console state**

Modify imports in `wqb/console_state.py`:

```python
from wqb.ai_checkpoints import load_ai_checkpoints
from wqb.console_timeline import build_timeline_rows, select_current_work
```

Modify `_job_rows`:

```python
from wqb.console_jobs import load_job_history


def _job_rows(job_root: Path, knowledge_root: Path) -> list[dict[str, Any]]:
    """Input: job root and knowledge root. Output: reconciled job rows. Read console jobs newest first."""
    return load_job_history(job_root, knowledge_root)
```

Modify `load_console_state` near the return block:

```python
    ai_checkpoints = load_ai_checkpoints(decisions)
    base_state = {
        "readiness": _latest_readiness(paths.runs_root),
        "freshness": _freshness_summary(paths.knowledge_root),
        "knowledge_contracts": evaluate_knowledge_contract_health(paths.knowledge_root),
        "data_coverage": _data_coverage_summary(paths.knowledge_root),
        "data_authority": _data_authority_summary(paths.knowledge_root),
        "semantic_ledgers": _semantic_ledger_summary(paths.knowledge_root),
        "startable_scopes": _startable_scopes(paths.knowledge_root),
        "option_cards": _read_jsonl(decisions / "research_option_cards.jsonl"),
        "schedule": _schedule_summary(paths.knowledge_root),
        "jobs": _job_rows(paths.job_root, paths.knowledge_root),
        "proposals": proposals,
        "proposal_counts": dict(proposal_counts),
        "ai_checkpoints": ai_checkpoints,
        "milestone": _milestone_summary(paths.milestone_path),
        "active_workflow": active_workflow,
        "workflow_events": workflow_events,
        "approved_queue": approved_queue,
        "queue_diagnostics": queue_diagnostics,
        "research_record": _research_record_summary(active_run_dir),
    }
    timeline = build_timeline_rows(base_state)
    base_state["timeline"] = timeline
    base_state["current_work"] = select_current_work(base_state, timeline)
    return base_state
```

- [ ] **Step 6: Add console state integration test**

Append to `tests/test_console_state.py`:

```python
    def test_load_console_state_includes_timeline_current_work_and_ai_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            decisions = paths.knowledge_root / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "ai_checkpoints.jsonl").write_text(
                json.dumps({
                    "checkpoint_id": "ai-1",
                    "checkpoint_type": "blocker_explanation",
                    "reason": "Explain stale data ledger.",
                    "evidence_paths": ["runs/readiness/report.md"],
                    "created_at": "2026-07-30T00:00:00+00:00",
                    "status": "pending",
                }) + "\n",
                encoding="utf-8",
            )

            state = load_console_state(paths)

        self.assertEqual(state["ai_checkpoints"][0]["checkpoint_id"], "ai-1")
        self.assertTrue(state["timeline"])
        self.assertIn("current_work", state)
```

- [ ] **Step 7: Run focused state and timeline tests**

Run:

```powershell
python -m unittest tests.test_console_timeline tests.test_console_state -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add BrainWorkflow/wqb/console_timeline.py BrainWorkflow/wqb/console_state.py BrainWorkflow/tests/test_console_timeline.py BrainWorkflow/tests/test_console_state.py
git commit -m "add console timeline state"
```

---

### Task 5: Single-Page Console Server And API

**Files:**
- Modify: `wqb/console_server.py`
- Modify: `wqb/console_context.py`
- Modify: `tests/test_console_server.py`

**Interfaces:**
- Consumes:
  - `state["timeline"]`
  - `state["current_work"]`
  - `state["ai_checkpoints"]`
  - `start_job_async(job)`
  - `run_job(job)`
- Produces:
  - `/` single-page Console HTML
  - `/api/state` JSON state endpoint
  - `run_console_action(paths, form)` returns `running` for async actions

- [ ] **Step 1: Write failing render tests for single-page sections**

Modify `tests/test_console_server.py` by adding:

```python
    def test_render_dashboard_has_single_page_timeline_control_center(self):
        state = {
            "readiness": {"exists": True, "passed": False},
            "freshness": {"exists": True, "valid": True, "stale_count": 1, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 60046, "scope_count": 7, "data_set_count": 453, "error_count": 0, "status": "completed"},
            "option_cards": [valid_option()],
            "startable_scopes": [{"region": "USA", "delay": 1, "universe": "TOP3000"}],
            "jobs": [{"job_id": "job-1", "action": "capture-platform-data-fields", "status": "completed"}],
            "active_workflow": {"exists": False},
            "workflow_events": [],
            "approved_queue": [],
            "queue_diagnostics": [],
            "proposal_counts": {"proposed": 1},
            "proposals": [{"proposal_id": "p1", "title": "Improve workflow", "status": "proposed"}],
            "ai_checkpoints": [{"checkpoint_id": "ai-1", "reason": "Explain blocker.", "status": "pending"}],
            "timeline": [
                {"stage_id": "platform_data_capture", "label": "Platform data capture", "status": "completed", "source": "deterministic", "explanation": "Captured raw fields.", "evidence_path": "raw/platform/data_fields/2026-07-30"},
                {"stage_id": "ai_checkpoint", "label": "AI checkpoint", "status": "waiting", "source": "ai_judgment", "explanation": "Explain blocker.", "evidence_path": "runs/readiness/report.md"},
            ],
            "current_work": {"title": "Knowledge health", "status": "blocked", "next_action": "Run knowledge health check", "details": ["Freshness has stale artifacts."], "evidence_paths": []},
        }

        html = render_dashboard(state)

        self.assertIn("BrainWorkflow Control Center", html)
        self.assertIn("Objective and Gate Summary", html)
        self.assertIn("Runtime Timeline", html)
        self.assertIn("Current Work", html)
        self.assertIn("Decisions and Approvals", html)
        self.assertIn("AI Checkpoints", html)
        self.assertIn("Platform data capture", html)
        self.assertIn("Explain blocker.", html)
```

- [ ] **Step 2: Run render test and verify missing section failure**

Run:

```powershell
python -m unittest tests.test_console_server.ConsoleServerTests.test_render_dashboard_has_single_page_timeline_control_center -v
```

Expected: FAIL because current HTML does not contain the new section names.

- [ ] **Step 3: Add HTML render helpers**

In `wqb/console_server.py`, add helpers:

```python
def _state_label(status: Any) -> str:
    """Input: status value. Output: CSS-safe state label. Normalize timeline state styling."""
    value = str(status or "not_started").replace("_", "-")
    return "".join(ch for ch in value if ch.isalnum() or ch == "-")


def _render_timeline(rows: list[dict[str, Any]]) -> str:
    """Input: timeline rows. Output: HTML. Render the durable workflow run tape."""
    if not rows:
        return "<div class='empty'>No timeline rows available.</div>"
    items = []
    for row in rows:
        state = _state_label(row.get("status"))
        items.append(
            "<li class='timeline-row state-{state}'>"
            "<span class='timeline-dot'></span>"
            "<div><strong>{label}</strong><span>{status} · {source}</span><p>{explanation}</p><code>{evidence}</code></div>"
            "</li>".format(
                state=escape(state),
                label=escape(str(row.get("label", ""))),
                status=escape(str(row.get("status", ""))),
                source=escape(str(row.get("source", ""))),
                explanation=escape(str(row.get("explanation", ""))),
                evidence=escape(str(row.get("evidence_path", ""))),
            )
        )
    return "<ol class='timeline'>" + "".join(items) + "</ol>"


def _render_current_work(work: dict[str, Any]) -> str:
    """Input: current work row. Output: HTML. Render active job or workflow stage details."""
    details = "".join(f"<li>{escape(str(item))}</li>" for item in work.get("details", []) if str(item))
    evidence = "".join(f"<li><code>{escape(str(item))}</code></li>" for item in work.get("evidence_paths", []) if str(item))
    return (
        f"<h3>{escape(str(work.get('title', 'No active work')))}</h3>"
        f"<p>Status: <strong>{escape(str(work.get('status', '')))}</strong></p>"
        f"<p>Next action: {escape(str(work.get('next_action', '')))}</p>"
        f"<ul>{details}</ul>"
        f"<details><summary>Evidence paths</summary><ul>{evidence}</ul></details>"
    )


def _render_ai_checkpoints(rows: list[dict[str, Any]]) -> str:
    """Input: checkpoint rows. Output: HTML. Render GPT/Codex judgment queue."""
    if not rows:
        return "<div class='empty'>No AI judgment checkpoints.</div>"
    items = []
    for row in rows:
        items.append(
            "<li><strong>{kind}</strong> <span>{status}</span><p>{reason}</p></li>".format(
                kind=escape(str(row.get("checkpoint_type", "ai_checkpoint"))),
                status=escape(str(row.get("status", ""))),
                reason=escape(str(row.get("reason", ""))),
            )
        )
    return "<ul>" + "".join(items) + "</ul>"
```

- [ ] **Step 4: Replace dashboard layout with the single-page control center**

Modify `render_dashboard` so the page title is `BrainWorkflow Control Center` and the body uses:

```python
    body = f"""
<div class="control-center">
<section class="wide hero"><h2>Objective and Gate Summary</h2><div class="ledger-strip">{ledger_strip}</div><p>Current work: <strong>{escape(str(state.get("current_work", {}).get("title", "No active workflow")))}</strong></p></section>
<section class="timeline-panel"><h2>Runtime Timeline</h2>{_render_timeline(state.get("timeline", []))}</section>
<section class="current-work"><h2>Current Work</h2>{_render_current_work(state.get("current_work", {}))}</section>
<section class="wide"><h2>Decisions and Approvals</h2>{research_start_form}{_render_inline_proposals(state.get("proposals", []))}</section>
<section class="wide"><h2>AI Checkpoints</h2>{_render_ai_checkpoints(state.get("ai_checkpoints", []))}</section>
<section><h2>Maintain Knowledge</h2>{knowledge_forms}</section>
<section><h2>Platform Data</h2>{data_coverage_panel}</section>
<section class="wide"><h2>Recent Jobs</h2><ul>{job_items}</ul></section>
</div>
<script>
async function refreshState(){{
  const response = await fetch('/api/state');
  if (!response.ok) return;
  const state = await response.json();
  const marker = document.querySelector('[data-current-work-title]');
  if (marker && state.current_work) marker.textContent = state.current_work.title || 'No active work';
}}
setInterval(refreshState, 5000);
</script>
"""
```

Add `_render_inline_proposals` by reusing `_render_proposal_decision_form`.

- [ ] **Step 5: Run render tests**

Run:

```powershell
python -m unittest tests.test_console_server.ConsoleServerTests.test_render_dashboard_has_single_page_timeline_control_center tests.test_console_server.ConsoleServerTests.test_render_dashboard_uses_selectable_option_cards_without_manual_option_id_input -v
```

Expected: PASS.

- [ ] **Step 6: Write failing tests for async action routing**

Append to `tests/test_console_server.py`:

```python
    def test_run_console_action_starts_data_capture_async(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            with patch("wqb.console_server.start_job_async") as start_async:
                start_async.side_effect = lambda job: job.__class__(**{**job.__dict__, "status": "running", "pid": 123})
                completed = run_console_action(paths, {"action": "capture-platform-data-fields", "enable_live_api": "on", "max_scopes": "4"})

        self.assertEqual(completed.status, "running")
        start_async.assert_called_once()

    def test_run_console_action_keeps_short_actions_synchronous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            with patch("wqb.console_server.run_job") as run_sync:
                run_sync.side_effect = lambda job: job.__class__(**{**job.__dict__, "status": "completed", "exit_code": 0})
                completed = run_console_action(paths, {"action": "knowledge-health-check"})

        self.assertEqual(completed.status, "completed")
        run_sync.assert_called_once()
```

- [ ] **Step 7: Run async routing test and verify missing import or synchronous behavior failure**

Run:

```powershell
python -m unittest tests.test_console_server.ConsoleServerTests.test_run_console_action_starts_data_capture_async -v
```

Expected: FAIL because `run_console_action` calls `run_job` synchronously.

- [ ] **Step 8: Implement async action routing**

Modify imports:

```python
from wqb.console_jobs import create_job, finish_job, run_job, start_job_async
```

Add constant:

```python
ASYNC_CONSOLE_ACTIONS = {"capture-platform-data-fields"}
```

Modify `run_console_action`:

```python
    job = create_job(paths.job_root, action, command, paths.workflow_root, {"form": dict(form)})
    try:
        if action in ASYNC_CONSOLE_ACTIONS:
            started = start_job_async(job)
            return started
        completed = run_job(job)
    except Exception as error:
        completed = finish_job(job, "failed", exit_code=1, error=str(error))
    record_console_job_context(paths, completed, next_command="python -m wqb.cli workflow-status")
    return completed
```

Leave refused actions synchronous because they already have terminal state.

- [ ] **Step 9: Add `/api/state` route**

In `ConsoleRequestHandler`, add:

```python
    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        """Input: JSON payload and status. Output: none. Send one JSON response."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
```

Modify `do_GET`:

```python
        if parsed.path == "/api/state":
            self._send_json(state)
            return
```

- [ ] **Step 10: Modify POST action response to redirect immediately for running jobs**

In `do_POST`, when action path is `/actions/run`:

```python
                completed = run_console_action(paths, form)
                if completed.status == "running":
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                self._send_html(f"<html><body>Job {escape(completed.status)}: <code>{escape(completed.job_id)}</code> <a href='/'>Back</a></body></html>")
                return
```

- [ ] **Step 11: Run server tests**

Run:

```powershell
python -m unittest tests.test_console_server -v
```

Expected: PASS.

- [ ] **Step 12: Commit**

```powershell
git add BrainWorkflow/wqb/console_server.py BrainWorkflow/wqb/console_context.py BrainWorkflow/tests/test_console_server.py
git commit -m "render single page console timeline"
```

---

### Task 6: Documentation, Verification, And Recovery Notes

**Files:**
- Modify: `docs/operations/operating_guide.md`
- Modify: `docs/operations/maintainer_handoff.md`
- Modify: root `todo.md`
- Modify: root `milestone.md`

**Interfaces:**
- Consumes:
  - implemented Console behavior from Tasks 1-5.
- Produces:
  - launch and use instructions for the single-page Console.
  - recovery record for the next Codex session.

- [ ] **Step 1: Update operating guide**

Add a section to `docs/operations/operating_guide.md`:

```markdown
## Single-Page Workflow Console

Launch from PowerShell:

```powershell
$env:SystemRoot='C:\Windows'
$env:windir='C:\Windows'
$env:WQB_USERNAME=[Environment]::GetEnvironmentVariable('WQB_USERNAME','User')
$env:WQB_PASSWORD=[Environment]::GetEnvironmentVariable('WQB_PASSWORD','User')
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m wqb.cli launch-console --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --run-dir 'C:\Users\oytl\Desktop\pyproject\brain\runs' --console-port 8765
```

Open `http://127.0.0.1:8765`.

Use the page from top to bottom:

1. Read `Objective and Gate Summary`.
2. Check `Runtime Timeline` for running, waiting, blocked, and completed stages.
3. Inspect `Current Work` for job progress and evidence paths.
4. Use `Decisions and Approvals` for research option choice and proposal review.
5. Use `AI Checkpoints` to see where Codex judgment is required.

Live API actions are gated by explicit checkboxes. Alpha submission still requires user approval.
```

- [ ] **Step 2: Update maintainer handoff**

Add to `docs/operations/maintainer_handoff.md`:

```markdown
## Console Timeline Maintenance Contract

The Console is a read and control layer. The Orchestrator owns research workflow state. Console jobs own command execution evidence. `console_timeline.py` maps durable state into UI rows.

Do not put model API calls in `console_server.py`. When GPT/Codex judgment is needed, write an `ai_checkpoints.jsonl` record through `ai_checkpoints.py` and let a Codex agent skill or automation runner consume it.

Long actions should use `start_job_async`. Short local checks may use `run_job`. Running jobs must be reconciled from `job.json`, PID state, and persisted raw/wiki/run artifacts.
```

- [ ] **Step 3: Run focused Console verification**

Run:

```powershell
python -m unittest tests.test_console_progress tests.test_ai_checkpoints tests.test_console_timeline tests.test_console_jobs tests.test_console_state tests.test_console_server -v
```

Expected: PASS.

- [ ] **Step 4: Run full non-live verification**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
python -m compileall -q wqb tests
git diff --check
```

Expected: all commands pass. `git diff --check` may report existing protected progress-file line-ending notices; record them if they are outside implementation files.

- [ ] **Step 5: Update root recovery files**

Append to root `todo.md` and root `milestone.md`:

```markdown
## 2026-07-30 Single-Page Console Implementation Complete

- Implemented async Console jobs, progress probes, timeline state, AI checkpoints, single-page rendering, and `/api/state`.
- Verification passed:
  - focused Console suite;
  - full non-live discovery;
  - compileall;
  - diff check.
- Next safe command:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m wqb.cli launch-console --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --run-dir 'C:\Users\oytl\Desktop\pyproject\brain\runs' --console-port 8765
```
```

- [ ] **Step 6: Commit documentation and recovery updates**

```powershell
git add BrainWorkflow/docs/operations/operating_guide.md BrainWorkflow/docs/operations/maintainer_handoff.md
git commit -m "document single page console workflow"
```

Do not add root `todo.md` or root `milestone.md` to the repository because they are outside the active git repository.

---

## Final Verification Gate

After all tasks are complete, run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_console_progress tests.test_ai_checkpoints tests.test_console_timeline tests.test_console_jobs tests.test_console_state tests.test_console_server -v
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
python -m compileall -q wqb tests
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git diff --check
git status --short --branch
```

Then launch the Console locally with the Windows environment patch and verify the main page returns HTTP 200:

```powershell
$env:SystemRoot='C:\Windows'
$env:windir='C:\Windows'
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m wqb.cli launch-console --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --run-dir 'C:\Users\oytl\Desktop\pyproject\brain\runs' --console-port 8765 --no-open-browser
```

If a server is already running on `8765`, use `8766` and record the actual URL.

---

## Plan Self-Review

- Spec coverage: Tasks 1-2 cover async long jobs and progress polling inputs; Task 3 covers durable AI checkpoints; Task 4 covers runtime timeline and current-work read models; Task 5 covers the single-page UI and `/api/state`; Task 6 covers documentation and recovery.
- Placeholder scan: clean.
- Type consistency: all new interfaces are defined before later tasks consume them.
- Scope check: research generation, simulation, repair, and submit logic stay unchanged.
