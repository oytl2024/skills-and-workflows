# Console Auto-Recovery And Knowledge-First Source Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make daily BrainWorkflow operation recoverable from one Console path: Start, option card selection, Continue, Stop, and explicit final Alpha submission approval.

**Architecture:** Add small workflow-support modules for stage-budget display, durable rate-limit cooldown, source-run locking, knowledge-first source selection, and smart workflow continuation. Keep Orchestrator as the owner of active workflow state; keep source runs as implementation details managed by a source bridge; keep the Console server as a thin view/action layer.

**Tech Stack:** Python standard library, server-rendered HTML in `wqb.console_server`, durable JSON/JSONL/CSV artifacts, `unittest`, existing WQB CLI and Orchestrator modules.

## Global Constraints

- Normal Console operation exposes only `Start workflow`, option card selection, `Continue workflow`, `Stop workflow`, and explicit final Alpha submission approval.
- Scout cap is 30, Seed cap is 8, Discovery cap is 50, Repair cap is 8, Submit cap is 0.
- `Continue workflow` must be idempotent and must not duplicate simulation submissions or artifact imports.
- No live platform calls are allowed in tests.
- No Alpha can be submitted automatically.
- Live API fallback must be explicitly labeled as `live_api`; knowledge-backed selection must be labeled as `knowledge`.
- 429 recovery MVP is local durable state plus Console-driven recovery, not a background daemon.
- Keep root `todo.md` and `milestone.md` out of repository commits unless the user explicitly requests otherwise.

---

## File Structure

- Modify `wqb/research_workflow.py`: expose stage-budget copy for UI/docs/tests.
- Modify `wqb/cli.py`: add `workflow-auto-continue`, connect cooldown state to submit 429, and record source provenance in `run_field_batch`.
- Modify `wqb/console_jobs.py`: map simplified Console actions to CLI commands.
- Modify `wqb/console_server.py`: simplify primary controls and move manual commands into diagnostics.
- Modify `wqb/console_state.py`: expose source bridge, cooldown, and provenance summaries.
- Modify `wqb/console_timeline.py`: show source recovery and rate-limit wait as first-class timeline/current-work states.
- Create `wqb/rate_limit_state.py`: own durable cooldown read/write/decision logic.
- Create `wqb/source_run_lock.py`: own source-run mutation lock lifecycle.
- Create `wqb/knowledge_source_resolver.py`: resolve fields/templates/operators from machine ledgers before live fallback.
- Create `wqb/source_bridge.py`: inspect and recover Scout/Seed source artifacts for the active workflow.
- Create `wqb/workflow_auto_continue.py`: implement the high-level Continue dispatcher used by CLI and Console; the CLI injects existing live source-run functions as runner callbacks.
- Modify `docs/operations/user_workflow_manual.md`: replace manual resume/import instructions with the one-button path.
- Modify `docs/operations/operating_guide.md`: move low-level recovery commands into maintenance-only guidance.
- Modify tests under `tests/`: add focused tests for every module and update Console expectations.

---

### Task 1: Stage Budget Contract

**Files:**
- Modify: `wqb/research_workflow.py`
- Modify: `tests/test_research_workflow.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: existing `STAGE_MAX_SIMULATIONS` and `cap_simulation_count(stage: str, requested_count: int) -> int`.
- Produces: `stage_budget_summary() -> dict[str, int]`.

- [ ] **Step 1: Write the failing stage-budget summary test**

Add this test to `tests/test_research_workflow.py`:

```python
def test_stage_budget_summary_keeps_scout_and_seed_distinct(self):
    from wqb.research_workflow import stage_budget_summary

    summary = stage_budget_summary()

    self.assertEqual(summary["scout"], 30)
    self.assertEqual(summary["seed"], 8)
    self.assertEqual(summary["discovery"], 50)
    self.assertEqual(summary["repair"], 8)
    self.assertEqual(summary["submit"], 0)
    self.assertIsNot(summary, __import__("wqb.research_workflow", fromlist=["STAGE_MAX_SIMULATIONS"]).STAGE_MAX_SIMULATIONS)
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_research_workflow.ResearchWorkflowTests.test_stage_budget_summary_keeps_scout_and_seed_distinct -v
```

Expected: FAIL because `stage_budget_summary` does not exist.

- [ ] **Step 3: Add the summary helper**

Add this function near `cap_simulation_count` in `wqb/research_workflow.py`:

```python
def stage_budget_summary() -> dict[str, int]:
    """Input: none. Output: stage cap mapping. Expose immutable simulation caps for UI and docs."""
    return dict(STAGE_MAX_SIMULATIONS)
```

- [ ] **Step 4: Add run metadata assertion coverage**

Add or extend a `run_field_batch` test in `tests/test_cli.py` using patched fake field fetch and fake submit/check functions:

```python
def test_run_field_batch_records_scout_stage_budget_metadata(self):
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        recorder = RunRecorder(run_dir)
        config = {
            "instrument_type": "EQUITY",
            "region": "USA",
            "delay": 1,
            "universe": "TOP3000",
            "max_alphas_per_round": 2,
            "neutralization": "SUBINDUSTRY",
            "decay": 4,
            "truncation": 0.08,
            "pasteurization": "ON",
            "nan_handling": "OFF",
            "unit_handling": "VERIFY",
            "language": "FASTEXPR",
            "visualization": False,
            "run_root": str(run_dir.parent),
        }
        fields = [{"id": "fresh_signal", "type": "MATRIX", "coverage": 0.9}]

        with patch("wqb.cli.fetch_data_fields", return_value=fields), patch(
            "wqb.cli.submit_candidate_payloads", return_value=[]
        ):
            run_field_batch(FakeClient(), recorder, config, field_search="fresh", workflow_stage="scout")

        meta = recorder.read_jsonl("run_meta.jsonl")[0]
        self.assertEqual(meta["workflow_stage"], "scout")
        self.assertEqual(meta["requested_max_alphas"], 2)
        self.assertEqual(meta["effective_max_alphas"], 30)
        self.assertEqual(meta["candidate_generation_limit"], 90)
```

If `FakeClient` or imports differ in the existing test module, reuse the local test fixtures already defined in `tests/test_cli.py`.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest tests.test_research_workflow tests.test_cli -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add BrainWorkflow\wqb\research_workflow.py BrainWorkflow\tests\test_research_workflow.py BrainWorkflow\tests\test_cli.py
git commit -m "clarify workflow stage budget contract"
```

---

### Task 2: Durable Rate-Limit Cooldown

**Files:**
- Create: `wqb/rate_limit_state.py`
- Create: `tests/test_rate_limit_state.py`
- Modify: `wqb/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `parse_retry_after_seconds(headers: Mapping[str, str], now: datetime) -> int | None`.
- Produces: `compute_backoff_seconds(attempt_count: int, base_seconds: int = 60, max_seconds: int = 900) -> int`.
- Produces: `record_rate_limit(run_dir: str | Path, stage: str, error: BaseException, context: dict[str, Any], now: str) -> dict[str, Any]`.
- Produces: `read_rate_limit_state(path: str | Path) -> dict[str, Any]`.
- Produces: `cooldown_is_active(state: dict[str, Any], now: str) -> bool`.
- Consumes: existing `record_recoverable_network_error`, `is_http_status_error`, and `submit_candidate_payloads`.

- [ ] **Step 1: Write failing tests for Retry-After parsing and backoff**

Create `tests/test_rate_limit_state.py`:

```python
from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path

from wqb.rate_limit_state import (
    compute_backoff_seconds,
    cooldown_is_active,
    parse_retry_after_seconds,
    read_rate_limit_state,
    record_rate_limit,
)


class RateLimitStateTests(unittest.TestCase):
    def test_parse_retry_after_seconds_accepts_delta_seconds(self):
        now = datetime(2026, 8, 12, 0, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(parse_retry_after_seconds({"Retry-After": "120"}, now), 120)

    def test_parse_retry_after_seconds_accepts_http_date(self):
        now = datetime(2026, 8, 12, 0, 0, 0, tzinfo=timezone.utc)

        seconds = parse_retry_after_seconds({"Retry-After": "Wed, 12 Aug 2026 00:02:00 GMT"}, now)

        self.assertEqual(seconds, 120)

    def test_compute_backoff_is_bounded_and_deterministic(self):
        self.assertEqual(compute_backoff_seconds(1), 63)
        self.assertEqual(compute_backoff_seconds(2), 126)
        self.assertEqual(compute_backoff_seconds(20), 900)

    def test_record_rate_limit_writes_durable_state(self):
        class Error(Exception):
            response = type("Response", (), {"status_code": 429, "headers": {"Retry-After": "60"}})()

        with tempfile.TemporaryDirectory() as tmp:
            state = record_rate_limit(
                Path(tmp),
                "retry_planned_submit",
                Error("HTTP 429"),
                {"expression_hash": "h1", "progress_url": "progress/1"},
                "2026-08-12T00:00:00+00:00",
            )
            loaded = read_rate_limit_state(Path(tmp) / "rate_limit_state.json")

        self.assertEqual(state["status"], "cooldown")
        self.assertEqual(loaded["last_status_code"], 429)
        self.assertEqual(loaded["last_candidate_hash"], "h1")
        self.assertTrue(cooldown_is_active(loaded, "2026-08-12T00:00:30+00:00"))
        self.assertFalse(cooldown_is_active(loaded, "2026-08-12T00:01:01+00:00"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run:

```powershell
python -m unittest tests.test_rate_limit_state -v
```

Expected: FAIL because `wqb.rate_limit_state` does not exist.

- [ ] **Step 3: Implement `wqb/rate_limit_state.py`**

Create the module with constants near imports:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
from typing import Any, Mapping


BASE_COOLDOWN_SECONDS = 60
MAX_COOLDOWN_SECONDS = 900
MAX_CONSECUTIVE_429 = 3


def _parse_time(value: str) -> datetime:
    """Input: timestamp string. Output: timezone-aware datetime. Normalize JSON timestamps."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_retry_after_seconds(headers: Mapping[str, str], now: datetime) -> int | None:
    """Input: response headers and current time. Output: wait seconds or none. Parse platform Retry-After."""
    value = ""
    for key, candidate in headers.items():
        if str(key).lower() == "retry-after":
            value = str(candidate).strip()
            break
    if not value:
        return None
    if value.isdigit():
        return max(0, int(value))
    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return max(0, int((target.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()))


def compute_backoff_seconds(attempt_count: int, base_seconds: int = BASE_COOLDOWN_SECONDS, max_seconds: int = MAX_COOLDOWN_SECONDS) -> int:
    """Input: attempt count and bounds. Output: cooldown seconds. Use deterministic bounded backoff."""
    attempt = max(1, int(attempt_count))
    raw = int(base_seconds) * (2 ** (attempt - 1))
    jitter = min(30, attempt * 3)
    return min(int(max_seconds), raw + jitter)


def read_rate_limit_state(path: str | Path) -> dict[str, Any]:
    """Input: state path. Output: state dict. Read missing or malformed cooldown state safely."""
    state_path = Path(path)
    if not state_path.exists():
        return {"status": "none"}
    try:
        row = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "invalid", "path": str(state_path)}
    return row if isinstance(row, dict) else {"status": "invalid", "path": str(state_path)}


def cooldown_is_active(state: dict[str, Any], now: str) -> bool:
    """Input: cooldown state and timestamp. Output: bool. Decide whether live calls must wait."""
    if state.get("status") != "cooldown":
        return False
    retry_at = str(state.get("retry_at", ""))
    if not retry_at:
        return False
    try:
        return _parse_time(now) < _parse_time(retry_at)
    except ValueError:
        return False


def record_rate_limit(run_dir: str | Path, stage: str, error: BaseException, context: dict[str, Any], now: str) -> dict[str, Any]:
    """Input: run dir, stage, error, context, timestamp. Output: cooldown state. Persist rate-limit recovery state."""
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "rate_limit_state.json"
    previous = read_rate_limit_state(path)
    attempt_count = int(previous.get("attempt_count", 0) or 0) + 1
    current_time = _parse_time(now)
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    retry_after = parse_retry_after_seconds(headers, current_time)
    wait_seconds = retry_after if retry_after is not None else compute_backoff_seconds(attempt_count)
    retry_at = current_time + timedelta(seconds=wait_seconds)
    state = {
        "status": "cooldown",
        "updated_at": now,
        "retry_after_seconds": wait_seconds,
        "retry_at": retry_at.isoformat(),
        "attempt_count": attempt_count,
        "consecutive_429_count": int(previous.get("consecutive_429_count", 0) or 0) + 1,
        "max_consecutive_429": MAX_CONSECUTIVE_429,
        "last_status_code": getattr(response, "status_code", 429),
        "last_error_type": type(error).__name__,
        "last_command": stage,
        "last_run_id": root.name,
        "last_candidate_hash": str(context.get("expression_hash", "")),
        "last_progress_url": str(context.get("progress_url", "")),
        "evidence_path": str(root / "run_errors.jsonl"),
    }
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state
```

- [ ] **Step 4: Connect submit 429 to cooldown state**

In `wqb/cli.py`, import `record_rate_limit`, `read_rate_limit_state`, and `cooldown_is_active`. In `submit_candidate_payloads`, before each live submit loop, read `recorder.run_dir / "rate_limit_state.json"` and stop if cooldown is active:

```python
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
cooldown_state = read_rate_limit_state(recorder.run_dir / "rate_limit_state.json")
if cooldown_is_active(cooldown_state, now):
    recorder.append_jsonl(
        "run_errors.jsonl",
        {
            "stage": f"{stage_prefix}_cooldown",
            "error_type": "RATE_LIMIT_COOLDOWN_ACTIVE",
            "retry_at": cooldown_state.get("retry_at", ""),
            "status": "rate_limit_wait",
        },
    )
    return summaries
```

In each `except requests.exceptions.RequestException as err` block that checks `is_http_status_error(err, 429)`, call:

```python
if is_http_status_error(err, 429):
    record_rate_limit(
        recorder.run_dir,
        f"{stage_prefix}_submit",
        err,
        item if isinstance(item, dict) else {"payload_count": len(chunk_payloads), "progress_url": progress_url if "progress_url" in locals() else ""},
        datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    break
```

For multi-submit blocks, pass the first metadata item plus `payload_count` and `chunk_start`.

- [ ] **Step 5: Add CLI tests for cooldown guards**

Add tests to `tests/test_cli.py`:

```python
def test_retry_planned_candidates_respects_active_cooldown(self):
    with tempfile.TemporaryDirectory() as tmp:
        recorder = RunRecorder(Path(tmp))
        recorder.append_jsonl("planned_candidates.jsonl", {"expression_hash": "h1", "expression": "rank(field_a)"})
        (Path(tmp) / "rate_limit_state.json").write_text(
            json.dumps({"status": "cooldown", "retry_at": "2099-01-01T00:00:00+00:00"}),
            encoding="utf-8",
        )

        summaries = retry_planned_candidates(FakeClient(), recorder, minimal_config(), submit_mode="serial")

        self.assertEqual(summaries, [])
        errors = recorder.read_jsonl("run_errors.jsonl")
        self.assertEqual(errors[0]["status"], "rate_limit_wait")
```

Also update existing 429 tests so they assert `(run_dir / "rate_limit_state.json").exists()`.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
python -m unittest tests.test_rate_limit_state tests.test_cli -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add BrainWorkflow\wqb\rate_limit_state.py BrainWorkflow\wqb\cli.py BrainWorkflow\tests\test_rate_limit_state.py BrainWorkflow\tests\test_cli.py
git commit -m "persist rate limit cooldown state"
```

---

### Task 3: Source-Run Mutation Lock

**Files:**
- Create: `wqb/source_run_lock.py`
- Create: `tests/test_source_run_lock.py`

**Interfaces:**
- Produces: `acquire_source_run_lock(run_dir: str | Path, action: str, now: str, ttl_seconds: int = 3600, process_alive: Callable[[int], bool] | None = None, pid: int | None = None, command_hash: str = "", candidate_hash: str = "", progress_url: str = "") -> dict[str, Any]`.
- Produces: `release_source_run_lock(run_dir: str | Path, action: str, now: str) -> dict[str, Any]`.
- Produces: `read_source_run_lock(run_dir: str | Path) -> dict[str, Any]`.
- Consumes: `wqb.console_progress.process_is_alive`.

- [ ] **Step 1: Write failing lock tests**

Create `tests/test_source_run_lock.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.source_run_lock import acquire_source_run_lock, read_source_run_lock, release_source_run_lock


class SourceRunLockTests(unittest.TestCase):
    def test_acquire_lock_creates_running_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = acquire_source_run_lock(Path(tmp), "retry-planned", "2026-08-12T00:00:00+00:00", pid=123)

        self.assertEqual(lock["status"], "acquired")
        self.assertEqual(lock["action"], "retry-planned")
        self.assertEqual(lock["pid"], 123)

    def test_active_lock_refuses_second_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquire_source_run_lock(root, "retry-planned", "2026-08-12T00:00:00+00:00", pid=123, process_alive=lambda pid: True)
            second = acquire_source_run_lock(root, "complete-in-flight", "2026-08-12T00:00:01+00:00", pid=124, process_alive=lambda pid: True)

        self.assertEqual(second["status"], "locked")
        self.assertEqual(second["active_action"], "retry-planned")

    def test_stale_lock_is_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquire_source_run_lock(root, "retry-planned", "2026-08-12T00:00:00+00:00", pid=123, process_alive=lambda pid: True)
            second = acquire_source_run_lock(root, "complete-in-flight", "2026-08-12T02:00:00+00:00", pid=124, ttl_seconds=60, process_alive=lambda pid: False)
            loaded = read_source_run_lock(root)

        self.assertEqual(second["status"], "acquired")
        self.assertEqual(loaded["action"], "complete-in-flight")

    def test_release_marks_lock_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquire_source_run_lock(root, "retry-planned", "2026-08-12T00:00:00+00:00", pid=123)
            released = release_source_run_lock(root, "retry-planned", "2026-08-12T00:05:00+00:00")

        self.assertEqual(released["status"], "released")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run new tests and confirm failure**

Run:

```powershell
python -m unittest tests.test_source_run_lock -v
```

Expected: FAIL because `wqb.source_run_lock` does not exist.

- [ ] **Step 3: Implement `wqb/source_run_lock.py`**

Use only standard library and `process_is_alive`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any, Callable

from wqb.console_progress import process_is_alive as default_process_is_alive


DEFAULT_LOCK_TTL_SECONDS = 3600


def _parse_time(value: str) -> datetime:
    """Input: timestamp. Output: timezone-aware datetime. Parse source lock times."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _lock_path(run_dir: str | Path) -> Path:
    """Input: run dir. Output: lock path. Locate source-run mutation lock."""
    return Path(run_dir) / "source_run_lock.json"


def read_source_run_lock(run_dir: str | Path) -> dict[str, Any]:
    """Input: run dir. Output: lock dict. Read source mutation lock safely."""
    path = _lock_path(run_dir)
    if not path.exists():
        return {"status": "none"}
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "invalid", "path": str(path)}
    return row if isinstance(row, dict) else {"status": "invalid", "path": str(path)}


def acquire_source_run_lock(
    run_dir: str | Path,
    action: str,
    now: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    process_alive: Callable[[int], bool] | None = None,
    pid: int | None = None,
    command_hash: str = "",
    candidate_hash: str = "",
    progress_url: str = "",
) -> dict[str, Any]:
    """Input: run dir, action, timestamp, process probe. Output: lock decision. Prevent duplicate source mutations."""
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = _lock_path(root)
    probe = process_alive or default_process_is_alive
    existing = read_source_run_lock(root)
    current = _parse_time(now)
    if existing.get("status") == "running":
        existing_pid = existing.get("pid")
        expires_at = str(existing.get("expires_at", ""))
        alive = isinstance(existing_pid, int) and probe(existing_pid)
        expired = bool(expires_at) and current >= _parse_time(expires_at)
        if alive and not expired:
            return {"status": "locked", "active_action": existing.get("action", ""), "pid": existing_pid, "path": str(path)}
    lock = {
        "status": "running",
        "run_id": root.name,
        "action": str(action),
        "pid": int(pid if pid is not None else os.getpid()),
        "created_at": now,
        "expires_at": (current + timedelta(seconds=int(ttl_seconds))).isoformat(),
        "command_hash": str(command_hash),
        "candidate_hash": str(candidate_hash),
        "progress_url": str(progress_url),
    }
    path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "acquired", **lock, "path": str(path)}


def release_source_run_lock(run_dir: str | Path, action: str, now: str) -> dict[str, Any]:
    """Input: run dir, action, timestamp. Output: release state. Mark a source mutation as finished."""
    path = _lock_path(run_dir)
    current = read_source_run_lock(run_dir)
    released = {**current, "status": "released", "released_at": now, "released_by": str(action)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(released, ensure_ascii=False, indent=2), encoding="utf-8")
    return released
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m unittest tests.test_source_run_lock -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add BrainWorkflow\wqb\source_run_lock.py BrainWorkflow\tests\test_source_run_lock.py
git commit -m "add source run mutation lock"
```

---

### Task 4: Knowledge-First Source Resolver

**Files:**
- Create: `wqb/knowledge_source_resolver.py`
- Create: `tests/test_knowledge_source_resolver.py`
- Modify: `wqb/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `SourceSelection` dataclass with `fields`, `field_source`, `operator_source`, `template_source`, `provenance`, and `blockers`.
- Produces: `resolve_source_inputs(knowledge_root: str | Path, config: dict[str, Any], field_search: str = "", dataset_id: str = "", exact_field_id: str = "", allow_live_fallback: bool = True, max_fields: int = 50) -> SourceSelection`.
- Consumes: `existing_machine_resource_path`, `data_ledger.jsonl`, `operator_ledger.jsonl`, and `template_library.jsonl`.

- [ ] **Step 1: Write resolver tests**

Create `tests/test_knowledge_source_resolver.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.knowledge_source_resolver import resolve_source_inputs


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class KnowledgeSourceResolverTests(unittest.TestCase):
    def test_resolver_prefers_matching_knowledge_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_jsonl(
                root / "machine" / "data_ledger.jsonl",
                [
                    {
                        "field_id": "buzz_intensity_score_15",
                        "field_type": "VECTOR",
                        "dataset_id": "analyst_buzz",
                        "coverage": 0.93,
                        "region": "USA",
                        "delay": 1,
                        "universe": "TOP3000",
                        "instrument_type": "EQUITY",
                        "source_quality": "platform_raw_capture",
                        "source_updated_at": "2026-08-12",
                        "source_paths": ["raw/platform/data_fields/2026-08-12/data_fields.md"],
                        "compatible_template_ids": ["vector_event_count_surprise"],
                    }
                ],
            )
            write_jsonl(root / "machine" / "operator_ledger.jsonl", [{"operator": "vec_count", "source_paths": ["raw/platform/operators.md"]}])
            write_jsonl(root / "machine" / "template_library.jsonl", [{"template_id": "vector_event_count_surprise", "skeleton": "rank(ts_delta(vec_count({field}), 1))"}])

            selection = resolve_source_inputs(
                root,
                {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                field_search="buzz",
                allow_live_fallback=False,
            )

        self.assertEqual(selection.field_source, "knowledge")
        self.assertEqual(selection.operator_source, "knowledge")
        self.assertEqual(selection.template_source, "template_library")
        self.assertEqual(selection.fields[0]["id"], "buzz_intensity_score_15")
        self.assertEqual(selection.provenance[0]["source_quality"], "platform_raw_capture")
        self.assertEqual(selection.blockers, [])

    def test_resolver_blocks_when_knowledge_missing_and_live_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            selection = resolve_source_inputs(
                Path(tmp),
                {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                field_search="buzz",
                allow_live_fallback=False,
            )

        self.assertEqual(selection.field_source, "missing")
        self.assertIn("knowledge_field_coverage_missing", selection.blockers)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run resolver tests and confirm failure**

Run:

```powershell
python -m unittest tests.test_knowledge_source_resolver -v
```

Expected: FAIL because `wqb.knowledge_source_resolver` does not exist.

- [ ] **Step 3: Implement resolver module**

Create `wqb/knowledge_source_resolver.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_paths import existing_machine_resource_path


@dataclass(frozen=True)
class SourceSelection:
    """Input: selected source rows. Output: immutable source selection. Carry provenance into runs."""

    fields: list[dict[str, Any]]
    field_source: str
    operator_source: str
    template_source: str
    provenance: list[dict[str, Any]]
    blockers: list[str]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: object rows. Read machine ledger rows safely."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _matches_scope(row: dict[str, Any], config: dict[str, Any]) -> bool:
    """Input: ledger row and config. Output: bool. Match instrument, region, delay, and universe."""
    return (
        str(row.get("instrument_type", "")).upper() == str(config.get("instrument_type", "")).upper()
        and str(row.get("region", "")).upper() == str(config.get("region", "")).upper()
        and str(row.get("delay", "")) == str(config.get("delay", ""))
        and str(row.get("universe", "")).upper() == str(config.get("universe", "")).upper()
    )


def _field_from_ledger(row: dict[str, Any]) -> dict[str, Any]:
    """Input: data ledger row. Output: field row. Convert machine data ledger shape to run_field_batch field shape."""
    return {
        "id": str(row.get("field_id", "")),
        "type": str(row.get("field_type", "")),
        "coverage": row.get("coverage", 0),
        "dataset": {"id": row.get("dataset_id", ""), "name": row.get("dataset_name", "")},
        "description": row.get("field_description", ""),
    }


def resolve_source_inputs(
    knowledge_root: str | Path,
    config: dict[str, Any],
    field_search: str = "",
    dataset_id: str = "",
    exact_field_id: str = "",
    allow_live_fallback: bool = True,
    max_fields: int = 50,
) -> SourceSelection:
    """Input: vault root, run config, filters, fallback flag. Output: source selection. Prefer knowledge ledgers over live API."""
    root = Path(knowledge_root)
    rows = _read_jsonl(existing_machine_resource_path(root, "data_ledger"))
    operators = _read_jsonl(existing_machine_resource_path(root, "operator_ledger"))
    templates = _read_jsonl(existing_machine_resource_path(root, "template_library"))
    search = str(field_search).lower().strip()
    exact = str(exact_field_id).strip()
    dataset = str(dataset_id).strip()
    matching: list[dict[str, Any]] = []
    for row in rows:
        field_id = str(row.get("field_id", ""))
        if not field_id or not _matches_scope(row, config):
            continue
        if dataset and str(row.get("dataset_id", "")) != dataset:
            continue
        if exact and field_id != exact:
            continue
        if search and search not in field_id.lower() and search not in str(row.get("field_description", "")).lower():
            continue
        if str(row.get("source_quality", "")) != "platform_raw_capture":
            continue
        matching.append(row)
    matching.sort(key=lambda row: float(row.get("coverage", 0) or 0), reverse=True)
    selected = matching[: max(0, int(max_fields))]
    if not selected:
        source = "live_api" if allow_live_fallback else "missing"
        return SourceSelection([], source, "knowledge" if operators else "missing", "template_library" if templates else "missing", [], ["knowledge_field_coverage_missing"])
    provenance = [
        {
            "field_id": row.get("field_id", ""),
            "source_paths": list(row.get("source_paths", [])),
            "source_quality": row.get("source_quality", ""),
            "source_updated_at": row.get("source_updated_at", ""),
            "region": row.get("region", ""),
            "delay": row.get("delay", ""),
            "universe": row.get("universe", ""),
        }
        for row in selected
    ]
    return SourceSelection(
        [_field_from_ledger(row) for row in selected],
        "knowledge",
        "knowledge" if operators else "missing",
        "template_library" if templates else "missing",
        provenance,
        [],
    )
```

- [ ] **Step 4: Integrate resolver into `run_field_batch`**

In `wqb/cli.py`:

```python
from wqb.knowledge_source_resolver import resolve_source_inputs
```

At the start of `run_field_batch`, before live `fetch_data_fields`, use:

```python
selection = resolve_source_inputs(
    config.get("knowledge_root", default_knowledge_root()),
    config,
    field_search=field_search,
    dataset_id=dataset_id,
    exact_field_id=exact_field_id,
    allow_live_fallback=True,
    max_fields=FIELD_BATCH_API_MAX_RECORDS,
)
source_provenance = selection.provenance
operator_source = selection.operator_source
template_source = selection.template_source
if field_cache_path:
    ...
elif selection.fields:
    fields = selection.fields
    field_source = selection.field_source
else:
    fields = fetch_data_fields(...)
    field_source = "live_api"
```

Add these keys to `run_meta.jsonl`:

```python
"field_source": field_source,
"operator_source": operator_source,
"template_source": template_source,
"source_provenance": source_provenance,
```

Keep `field_cache_path` behavior as `field_source="cache"` because an explicit cache is a stronger caller choice.

- [ ] **Step 5: Add CLI provenance tests**

Extend the `run_field_batch` metadata test so a temp knowledge root with one matching data ledger row is passed through `config["knowledge_root"]`; assert:

```python
self.assertEqual(meta["field_source"], "knowledge")
self.assertEqual(meta["operator_source"], "knowledge")
self.assertEqual(meta["template_source"], "template_library")
self.assertEqual(meta["source_provenance"][0]["field_id"], "buzz_intensity_score_15")
```

Add a separate fallback test with no ledger rows and patched `fetch_data_fields`; assert:

```python
self.assertEqual(meta["field_source"], "live_api")
self.assertEqual(meta["source_provenance"], [])
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
python -m unittest tests.test_knowledge_source_resolver tests.test_cli -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add BrainWorkflow\wqb\knowledge_source_resolver.py BrainWorkflow\wqb\cli.py BrainWorkflow\tests\test_knowledge_source_resolver.py BrainWorkflow\tests\test_cli.py
git commit -m "prefer knowledge source provenance for field batches"
```

---

### Task 5: Scout/Seed Source Bridge

**Files:**
- Create: `wqb/source_bridge.py`
- Create: `tests/test_source_bridge.py`
- Modify: `wqb/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Produces: `SourceBridgeDecision` dataclass with `action`, `reason`, `source_run_id`, `source_run_dir`, `evidence_paths`, and `metadata`.
- Produces: `inspect_scout_seed_source_bridge(runs_root: str | Path, active_run_dir: str | Path, now: str) -> SourceBridgeDecision`.
- Produces: `active_run_needs_scout_seed_candidates(summary: dict[str, Any]) -> bool`.
- Consumes: `import_scout_seed_artifacts_from_run`, `rate_limit_state`, `source_run_lock`, and source run artifacts.

- [ ] **Step 1: Write bridge tests**

Create `tests/test_source_bridge.py`:

```python
import csv
import json
import tempfile
import unittest
from pathlib import Path

from wqb.source_bridge import active_run_needs_scout_seed_candidates, inspect_scout_seed_source_bridge


def write_candidates(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["alpha_id", "expression_hash"])
        writer.writeheader()
        writer.writerow({"alpha_id": "a1", "expression_hash": "h1"})


class SourceBridgeTests(unittest.TestCase):
    def test_active_run_needs_candidates_only_for_scout_seed_pause(self):
        summary = {"active": True, "status": "paused", "current_stage": "scout_seed", "pause_reason": "missing candidates.csv"}

        self.assertTrue(active_run_needs_scout_seed_candidates(summary))
        self.assertFalse(active_run_needs_scout_seed_candidates({**summary, "current_stage": "repair"}))

    def test_bridge_imports_existing_valid_source_candidate_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            active.mkdir()
            write_candidates(source / "candidates.csv")

            decision = inspect_scout_seed_source_bridge(runs, active, "2026-08-12T00:00:00+00:00")

        self.assertEqual(decision.action, "import_existing")
        self.assertEqual(decision.source_run_id, "source1")

    def test_bridge_waits_when_cooldown_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            active.mkdir()
            source.mkdir()
            (source / "rate_limit_state.json").write_text(
                json.dumps({"status": "cooldown", "retry_at": "2099-01-01T00:00:00+00:00"}),
                encoding="utf-8",
            )

            decision = inspect_scout_seed_source_bridge(runs, active, "2026-08-12T00:00:00+00:00")

        self.assertEqual(decision.action, "rate_limit_wait")
        self.assertEqual(decision.source_run_id, "source1")

    def test_bridge_builds_source_batch_metadata_from_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            schedule = active / "stages" / "schedule" / "research_schedule.json"
            schedule.parent.mkdir(parents=True)
            schedule.write_text(
                json.dumps(
                    {
                        "template_matches": [
                            {
                                "field_id": "buzz_intensity_score_15",
                                "dataset_id": "analyst_buzz",
                                "template_id": "vector_event_count_surprise",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            decision = inspect_scout_seed_source_bridge(runs, active, "2026-08-12T00:00:00+00:00")

        self.assertEqual(decision.action, "start_source_batch")
        self.assertEqual(decision.metadata["field_search"], "buzz_intensity_score_15")
        self.assertEqual(decision.metadata["exact_field_id"], "buzz_intensity_score_15")
        self.assertEqual(decision.metadata["dataset_id"], "analyst_buzz")
        self.assertEqual(decision.metadata["workflow_stage"], "scout")
        self.assertEqual(decision.metadata["max_alphas_per_round"], 30)
```

- [ ] **Step 2: Run bridge tests and confirm failure**

Run:

```powershell
python -m unittest tests.test_source_bridge -v
```

Expected: FAIL because `wqb.source_bridge` does not exist.

- [ ] **Step 3: Implement `wqb/source_bridge.py`**

Create the module:

```python
from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any

from wqb.rate_limit_state import cooldown_is_active, read_rate_limit_state
from wqb.workflow_stage_adapters import import_scout_seed_artifacts


@dataclass(frozen=True)
class SourceBridgeDecision:
    """Input: source bridge fields. Output: immutable decision. Explain the next source recovery action."""

    action: str
    reason: str
    source_run_id: str = ""
    source_run_dir: str = ""
    evidence_paths: list[str] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Input: decision. Output: dict. Serialize source bridge decision for CLI and Console."""
        row = asdict(self)
        row["evidence_paths"] = list(self.evidence_paths or [])
        row["metadata"] = dict(self.metadata or {})
        return row


def active_run_needs_scout_seed_candidates(summary: dict[str, Any]) -> bool:
    """Input: workflow summary. Output: bool. Detect the paused missing-candidate bridge state."""
    return (
        bool(summary.get("active"))
        and str(summary.get("status", "")) == "paused"
        and str(summary.get("current_stage", "")) == "scout_seed"
        and "candidates.csv" in str(summary.get("pause_reason", ""))
    )


def _candidate_file_valid(source: Path) -> bool:
    """Input: source run dir. Output: bool. Check candidate file existence before audited import."""
    path = source / "candidates.csv"
    return path.exists() and path.is_file() and path.stat().st_size > len("alpha_id,expression_hash\n")


def _source_runs(runs_root: Path, active_run_dir: Path) -> list[Path]:
    """Input: runs root and active dir. Output: candidate source dirs. List newest source dirs first."""
    active_resolved = active_run_dir.resolve()
    rows = [path for path in runs_root.iterdir() if path.is_dir() and path.resolve() != active_resolved]
    return sorted(rows, key=lambda path: path.stat().st_mtime, reverse=True)


def _source_batch_metadata(active_run_dir: Path) -> dict[str, Any]:
    """Input: active run dir. Output: source batch args. Read first scheduled Scout field/template."""
    schedule_path = active_run_dir / "stages" / "schedule" / "research_schedule.json"
    if not schedule_path.exists():
        return {}
    try:
        schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    matches = schedule.get("template_matches", [])
    if not isinstance(matches, list) or not matches or not isinstance(matches[0], dict):
        return {}
    first = matches[0]
    field_id = str(first.get("field_id", "")).strip()
    return {
        "field_search": field_id,
        "exact_field_id": field_id,
        "dataset_id": str(first.get("dataset_id", "")).strip(),
        "template_mode": "economic",
        "workflow_stage": "scout",
        "submit_mode": "multi",
        "max_alphas_per_round": 30,
    }


def inspect_scout_seed_source_bridge(runs_root: str | Path, active_run_dir: str | Path, now: str) -> SourceBridgeDecision:
    """Input: runs root, active run dir, timestamp. Output: bridge decision. Choose source artifact recovery action."""
    root = Path(runs_root)
    active = Path(active_run_dir)
    for source in _source_runs(root, active):
        if _candidate_file_valid(source):
            return SourceBridgeDecision("import_existing", "valid source candidates found", source.name, str(source), [str(source / "candidates.csv")])
    for source in _source_runs(root, active):
        cooldown = read_rate_limit_state(source / "rate_limit_state.json")
        if cooldown_is_active(cooldown, now):
            return SourceBridgeDecision("rate_limit_wait", "platform cooldown active", source.name, str(source), [str(source / "rate_limit_state.json")], cooldown)
    for source in _source_runs(root, active):
        if (source / "simulation_events.jsonl").exists():
            text = (source / "simulation_events.jsonl").read_text(encoding="utf-8")
            if "SUBMITTED" in text and "CHECKED" not in text:
                return SourceBridgeDecision("complete_in_flight", "submitted simulation needs recovery", source.name, str(source), [str(source / "simulation_events.jsonl")])
    for source in _source_runs(root, active):
        if (source / "planned_candidates.jsonl").exists():
            return SourceBridgeDecision("retry_planned", "planned source candidates remain", source.name, str(source), [str(source / "planned_candidates.jsonl")])
    metadata = _source_batch_metadata(active)
    if metadata.get("field_search"):
        return SourceBridgeDecision("start_source_batch", "no recoverable source run exists", "", "", [str(active / "stages" / "schedule" / "research_schedule.json")], metadata)
    return SourceBridgeDecision("maintenance_blocker", "research schedule has no source batch metadata", "", "", [str(active / "stages" / "schedule" / "research_schedule.json")], {})


def import_existing_source_artifacts(active_run_dir: str | Path, decision: SourceBridgeDecision, imported_at: str) -> dict[str, object]:
    """Input: active run dir, bridge decision, timestamp. Output: import summary. Import valid source candidates once."""
    if decision.action != "import_existing" or not decision.source_run_dir:
        raise ValueError("source bridge decision is not importable")
    return import_scout_seed_artifacts(active_run_dir, decision.source_run_dir, imported_at)
```

- [ ] **Step 4: Add Orchestrator wrapper for bridge import**

In `wqb/orchestrator.py`, add a method that receives a `SourceBridgeDecision` and imports only when action is `import_existing`. It should call the existing `_import_scout_seed_artifacts_unlocked` path, so all current artifact validation remains centralized.

```python
def import_scout_seed_bridge_decision(self, decision: dict[str, object], imported_at: str) -> dict[str, object]:
    """Input: source bridge decision and timestamp. Output: workflow summary. Import source artifacts selected by the bridge."""
    action = str(decision.get("action", ""))
    source_run_id = str(decision.get("source_run_id", ""))
    if action != "import_existing":
        raise ValueError("source bridge decision is not an import decision")
    return self.import_scout_seed_artifacts(source_run_id, imported_at)
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest tests.test_source_bridge tests.test_orchestrator -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add BrainWorkflow\wqb\source_bridge.py BrainWorkflow\wqb\orchestrator.py BrainWorkflow\tests\test_source_bridge.py BrainWorkflow\tests\test_orchestrator.py
git commit -m "add scout seed source bridge"
```

---

### Task 6: Smart Workflow Auto-Continue

**Files:**
- Create: `wqb/workflow_auto_continue.py`
- Create: `tests/test_workflow_auto_continue.py`
- Modify: `wqb/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `wqb/console_jobs.py`
- Modify: `tests/test_console_jobs.py`

**Interfaces:**
- Produces: `auto_continue_workflow(paths: OrchestratorPaths, config: dict[str, Any], now: str, enable_live_api: bool = False, source_batch_runner: Callable[[dict[str, Any], dict[str, Any]], dict[str, object]] | None = None, complete_in_flight_runner: Callable[[str], dict[str, object]] | None = None, retry_planned_runner: Callable[[str], dict[str, object]] | None = None) -> dict[str, object]`.
- Produces CLI command `workflow-auto-continue`.
- Consumes: `WorkflowOrchestrator`, `active_run_needs_scout_seed_candidates`, `inspect_scout_seed_source_bridge`, `source_run_lock`, cooldown state.

- [ ] **Step 1: Write auto-continue tests**

Create `tests/test_workflow_auto_continue.py`:

```python
import csv
import tempfile
import unittest
from pathlib import Path

from wqb.orchestrator import WorkflowOrchestrator, default_orchestrator_paths
from wqb.workflow_auto_continue import auto_continue_workflow


def write_candidate_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["alpha_id", "expression_hash"])
        writer.writeheader()
        writer.writerow({"alpha_id": "a1", "expression_hash": "h1"})


class WorkflowAutoContinueTests(unittest.TestCase):
    def test_auto_continue_refuses_without_active_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = default_orchestrator_paths({"run_root": str(Path(tmp) / "runs"), "knowledge_root": str(Path(tmp) / "knowledge")})

            result = auto_continue_workflow(paths, {}, "2026-08-12T00:00:00+00:00")

        self.assertEqual(result["status"], "none")
        self.assertEqual(result["next_action"], "workflow-start")

    def test_auto_continue_imports_valid_source_candidates_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = default_orchestrator_paths({"run_root": str(root / "runs"), "knowledge_root": str(root / "knowledge")})
            orchestrator = WorkflowOrchestrator(paths)
            orchestrator.start("Power Pool", "option-1", "2026-08-12T00:00:00+00:00")
            orchestrator.continue_once("2026-08-12T00:01:00+00:00")
            orchestrator.continue_once("2026-08-12T00:02:00+00:00")
            source = paths.run_root / "source1"
            write_candidate_file(source / "candidates.csv")

            result = auto_continue_workflow(paths, {}, "2026-08-12T00:03:00+00:00")
            second = auto_continue_workflow(paths, {}, "2026-08-12T00:04:00+00:00")

        self.assertEqual(result["source_bridge"]["action"], "import_existing")
        self.assertIn(second["status"], {"running", "paused"})
        self.assertTrue((Path(result["run_dir"]) / "candidates.csv").exists())

    def test_auto_continue_reports_rate_limit_wait_without_live_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = default_orchestrator_paths({"run_root": str(root / "runs"), "knowledge_root": str(root / "knowledge")})
            orchestrator = WorkflowOrchestrator(paths)
            orchestrator.start("Power Pool", "option-1", "2026-08-12T00:00:00+00:00")
            orchestrator.continue_once("2026-08-12T00:01:00+00:00")
            orchestrator.continue_once("2026-08-12T00:02:00+00:00")
            source = paths.run_root / "source1"
            source.mkdir()
            (source / "rate_limit_state.json").write_text('{"status":"cooldown","retry_at":"2099-01-01T00:00:00+00:00"}', encoding="utf-8")

            result = auto_continue_workflow(paths, {}, "2026-08-12T00:03:00+00:00")

        self.assertEqual(result["next_action"], "rate-limit-wait")
        self.assertEqual(result["source_bridge"]["action"], "rate_limit_wait")

    def test_auto_continue_starts_bounded_source_batch_when_live_enabled(self):
        calls = []

        def source_batch_runner(config, metadata):
            calls.append((dict(config), dict(metadata)))
            return {"status": "source_batch_completed", "run_dir": "runs/source1"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = default_orchestrator_paths({"run_root": str(root / "runs"), "knowledge_root": str(root / "knowledge")})
            orchestrator = WorkflowOrchestrator(paths)
            orchestrator.start("Power Pool", "option-1", "2026-08-12T00:00:00+00:00")
            orchestrator.continue_once("2026-08-12T00:01:00+00:00")
            orchestrator.continue_once("2026-08-12T00:02:00+00:00")
            schedule = paths.run_root / "20260812T000000000000-option-1" / "stages" / "schedule" / "research_schedule.json"
            if not schedule.exists():
                schedule = next(paths.run_root.glob("*/stages/schedule/research_schedule.json"))
            schedule.write_text(
                '{"template_matches":[{"field_id":"buzz_intensity_score_15","dataset_id":"analyst_buzz","template_id":"vector_event_count_surprise"}]}',
                encoding="utf-8",
            )

            result = auto_continue_workflow(
                paths,
                {"max_alphas_per_round": 2},
                "2026-08-12T00:03:00+00:00",
                enable_live_api=True,
                source_batch_runner=source_batch_runner,
            )

        self.assertEqual(result["next_action"], "workflow-auto-continue")
        self.assertEqual(result["source_bridge"]["action"], "start_source_batch")
        self.assertEqual(calls[0][0]["max_alphas_per_round"], 30)
        self.assertEqual(calls[0][1]["field_search"], "buzz_intensity_score_15")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
python -m unittest tests.test_workflow_auto_continue -v
```

Expected: FAIL because `wqb.workflow_auto_continue` does not exist.

- [ ] **Step 3: Implement auto-continue module**

Create `wqb/workflow_auto_continue.py`:

```python
from __future__ import annotations

from typing import Any, Callable

from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
from wqb.source_bridge import active_run_needs_scout_seed_candidates, inspect_scout_seed_source_bridge
from wqb.source_run_lock import acquire_source_run_lock, release_source_run_lock


def auto_continue_workflow(
    paths: OrchestratorPaths,
    config: dict[str, Any],
    now: str,
    enable_live_api: bool = False,
    source_batch_runner: Callable[[dict[str, Any], dict[str, Any]], dict[str, object]] | None = None,
    complete_in_flight_runner: Callable[[str], dict[str, object]] | None = None,
    retry_planned_runner: Callable[[str], dict[str, object]] | None = None,
) -> dict[str, object]:
    """Input: orchestrator paths, config, timestamp, live flag. Output: workflow summary. Run the next safe workflow action."""
    orchestrator = WorkflowOrchestrator(paths)
    status = orchestrator.status()
    if not status.get("active"):
        return {"active": False, "status": "none", "next_action": "workflow-start", "message": "Select an option card and start a workflow."}
    if status.get("waiting_for_user") or status.get("status") == "waiting_for_user":
        return {**status, "message": "User approval is required before automatic progress."}
    if active_run_needs_scout_seed_candidates(status):
        decision = inspect_scout_seed_source_bridge(paths.run_root, status["run_dir"], now)
        if decision.action == "import_existing":
            imported = orchestrator.import_scout_seed_bridge_decision(decision.to_dict(), now)
            return {**imported, "source_bridge": decision.to_dict(), "next_action": "workflow-auto-continue"}
        if decision.action == "rate_limit_wait":
            return {**status, "source_bridge": decision.to_dict(), "next_action": "rate-limit-wait", "message": "Platform cooldown is active; Continue will not contact the platform yet."}
        if decision.action == "complete_in_flight" and complete_in_flight_runner is not None:
            lock = acquire_source_run_lock(decision.source_run_dir, "complete-in-flight", now)
            if lock.get("status") != "acquired":
                return {**status, "source_bridge": decision.to_dict(), "next_action": "source-lock-wait", "source_lock": lock}
            try:
                recovery = complete_in_flight_runner(decision.source_run_dir)
            finally:
                release_source_run_lock(decision.source_run_dir, "complete-in-flight", now)
            return {**status, "source_bridge": decision.to_dict(), "source_recovery": recovery, "next_action": "workflow-auto-continue"}
        if decision.action == "retry_planned" and retry_planned_runner is not None:
            lock = acquire_source_run_lock(decision.source_run_dir, "retry-planned", now)
            if lock.get("status") != "acquired":
                return {**status, "source_bridge": decision.to_dict(), "next_action": "source-lock-wait", "source_lock": lock}
            try:
                recovery = retry_planned_runner(decision.source_run_dir)
            finally:
                release_source_run_lock(decision.source_run_dir, "retry-planned", now)
            return {**status, "source_bridge": decision.to_dict(), "source_recovery": recovery, "next_action": "workflow-auto-continue"}
        if decision.action in {"complete_in_flight", "retry_planned"}:
            return {**status, "source_bridge": decision.to_dict(), "next_action": decision.action, "message": "Source recovery runner is not configured."}
        if decision.action == "start_source_batch" and not enable_live_api:
            return {**status, "source_bridge": decision.to_dict(), "next_action": "enable-live-api-required", "message": "Live API authorization is required before starting a source batch."}
        if decision.action == "start_source_batch" and source_batch_runner is not None:
            lock = acquire_source_run_lock(status["run_dir"], "start-source-batch", now)
            if lock.get("status") != "acquired":
                return {**status, "source_bridge": decision.to_dict(), "next_action": "source-lock-wait", "source_lock": lock}
            source_config = {**config, "max_alphas_per_round": int(decision.metadata.get("max_alphas_per_round", 30))}
            try:
                recovery = source_batch_runner(source_config, decision.metadata or {})
            finally:
                release_source_run_lock(status["run_dir"], "start-source-batch", now)
            return {**status, "source_bridge": decision.to_dict(), "source_recovery": recovery, "next_action": "workflow-auto-continue"}
        if decision.action == "maintenance_blocker":
            return {**status, "source_bridge": decision.to_dict(), "next_action": "maintenance-blocker"}
        return {**status, "source_bridge": decision.to_dict(), "next_action": "source-batch-runner-missing", "message": "Source batch runner is not configured."}
    if status.get("status") == "paused":
        resumed = orchestrator.resume(now)
        if resumed.get("status") == "running":
            return orchestrator.continue_once(now)
        return resumed
    if status.get("next_action") == "workflow-continue" or status.get("status") == "running":
        return orchestrator.continue_once(now)
    return status
```

- [ ] **Step 4: Make `field_batch` return a summary while preserving CLI output**

In `wqb/cli.py`, change `field_batch(...) -> None` to `field_batch(...) -> dict[str, Any]`. Build the payload once, print it, and return it:

```python
payload = {
    "run_dir": str(run_dir),
    "status": status_label,
    "field_search": field_search,
    "dataset_id": dataset_id,
    "field_suffix": field_suffix,
    "template_mode": template_mode,
    "workflow_stage": workflow_stage,
    "human_idea": human_idea,
    "exact_field_id": exact_field_id,
    "field_cache_path": field_cache_path,
    "defer_poll": defer_poll,
    "multi_chunk_sleep_seconds": multi_chunk_sleep_seconds,
    "checked_count": len(summaries),
    "hard_pass_alpha_ids": [summary.alpha_id for summary in summaries if summary.hard_pass],
    "failed": {summary.alpha_id: [check.name for check in summary.failed] for summary in summaries},
    "pending": {summary.alpha_id: [check.name for check in summary.pending] for summary in summaries},
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
return payload
```

For readiness-blocked and auth-recoverable branches, build the printed JSON payload and return it the same way.

- [ ] **Step 5: Add CLI command**

In parser choices, add `workflow-auto-continue`. In workflow command handling:

```python
elif args.command == "workflow-auto-continue":
    from wqb.workflow_auto_continue import auto_continue_workflow

    def source_batch_runner(run_config, metadata):
        return field_batch(
            run_config,
            field_search=str(metadata.get("field_search", "")),
            dataset_id=str(metadata.get("dataset_id", "")),
            template_mode=str(metadata.get("template_mode", "economic")),
            workflow_stage=str(metadata.get("workflow_stage", "scout")),
            exact_field_id=str(metadata.get("exact_field_id", "")),
            submit_mode=str(metadata.get("submit_mode", "multi")),
        )

    def complete_runner(source_run_dir):
        complete_in_flight(config, source_run_dir)
        return summarize_run_dir(source_run_dir, config.get("knowledge_root", default_knowledge_root()))

    def retry_runner(source_run_dir):
        retry_planned(config, source_run_dir, submit_mode=args.submit_mode, defer_poll=args.defer_poll)
        return summarize_run_dir(source_run_dir, config.get("knowledge_root", default_knowledge_root()))

    result = auto_continue_workflow(
        default_orchestrator_paths(config),
        config,
        now,
        enable_live_api=args.enable_live_api,
        source_batch_runner=source_batch_runner,
        complete_in_flight_runner=complete_runner,
        retry_planned_runner=retry_runner,
    )
```

- [ ] **Step 6: Add Console command mapping**

In `wqb/console_jobs.py`, add:

```python
if action == "workflow-auto-continue":
    command = [*base, "workflow-auto-continue", "--knowledge-root", knowledge_root, "--run-dir", str(paths.runs_root)]
    if data.get("enable_live_api"):
        command.append("--enable-live-api")
    return command
if action == "workflow-stop":
    return [*base, "workflow-abort", "--knowledge-root", knowledge_root, "--run-dir", str(paths.runs_root), "--reason", "user stopped from console"]
```

- [ ] **Step 7: Update command mapping tests**

In `tests/test_console_jobs.py`, add:

```python
def test_build_cli_command_maps_auto_continue_and_stop(self):
    with tempfile.TemporaryDirectory() as tmp:
        paths = make_paths(Path(tmp))

        auto_continue = build_cli_command("workflow-auto-continue", paths, {"enable_live_api": True})
        stop = build_cli_command("workflow-stop", paths, {})

    self.assertIn("workflow-auto-continue", auto_continue)
    self.assertIn("--enable-live-api", auto_continue)
    self.assertIn("workflow-abort", stop)
    self.assertIn("user stopped from console", stop)
```

- [ ] **Step 8: Run focused tests**

Run:

```powershell
python -m unittest tests.test_workflow_auto_continue tests.test_console_jobs tests.test_cli -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add BrainWorkflow\wqb\workflow_auto_continue.py BrainWorkflow\wqb\cli.py BrainWorkflow\wqb\console_jobs.py BrainWorkflow\tests\test_workflow_auto_continue.py BrainWorkflow\tests\test_console_jobs.py BrainWorkflow\tests\test_cli.py
git commit -m "add smart workflow auto continue"
```

---

### Task 7: Simplified Console Primary Path

**Files:**
- Modify: `wqb/console_server.py`
- Modify: `wqb/console_state.py`
- Modify: `wqb/console_timeline.py`
- Modify: `tests/test_console_server.py`
- Modify: `tests/test_console_timeline.py`

**Interfaces:**
- Consumes: `active_workflow`, `source_bridge`, `rate_limit`, and `provenance` state.
- Produces: primary forms for `workflow-start-from-option`, `workflow-auto-continue`, and `workflow-stop`.

- [ ] **Step 1: Write failing Console render tests**

Replace the old tests that expect visible manual import/resume with:

```python
def test_render_dashboard_uses_single_primary_continue_and_stop(self):
    state = {
        "readiness": {"exists": True, "passed": True, "blocked": False},
        "freshness": {"exists": True, "valid": True, "record_count": 6, "stale_count": 0, "missing_count": 0},
        "data_coverage": {"exists": True, "field_count": 120, "scope_count": 4, "data_set_count": 8, "error_count": 0, "status": "completed"},
        "startable_scopes": [],
        "option_cards": [],
        "schedule": {"preview": "# Schedule"},
        "jobs": [],
        "proposal_counts": {},
        "active_workflow": {"exists": True, "run_id": "active", "current_stage": "scout_seed", "status": "paused", "next_action": "workflow-resume"},
        "approved_queue": [],
        "queue_diagnostics": [],
        "workflow_events": [],
        "source_bridge": {"action": "rate_limit_wait", "reason": "platform cooldown active"},
    }

    html = render_dashboard(state)

    self.assertIn('value="workflow-auto-continue"', html)
    self.assertIn("Continue workflow", html)
    self.assertIn('value="workflow-stop"', html)
    self.assertIn("Stop workflow", html)
    self.assertNotIn('name="source_run_id"', html)
    self.assertNotIn('value="workflow-resume"', html)
```

Add an option card selection test that expects each card to contain a radio input:

```python
def test_option_cards_are_directly_selectable(self):
    state = {
        "readiness": {"exists": True, "passed": True, "blocked": False},
        "freshness": {},
        "data_coverage": {},
        "startable_scopes": [{"region": "USA", "delay": 1, "universe": "TOP3000"}],
        "option_cards": [{"option_id": "power-pool", "title": "Power Pool", "objective": "Find Power Pool alpha"}],
        "schedule": {},
        "jobs": [],
        "proposal_counts": {},
        "active_workflow": {"exists": False},
        "approved_queue": [],
        "queue_diagnostics": [],
        "workflow_events": [],
    }

    html = render_dashboard(state)

    self.assertIn('type="radio"', html)
    self.assertIn('value="power-pool"', html)
    self.assertIn("Start workflow", html)
```

- [ ] **Step 2: Run Console render tests and confirm failure**

Run:

```powershell
python -m unittest tests.test_console_server -v
```

Expected: FAIL because old controls still render.

- [ ] **Step 3: Simplify `render_dashboard` controls**

In `wqb/console_server.py`, replace `workflow_progress` forms with:

```python
workflow_progress = f"""
<p>Active run: <code>{escape(str(active.get('run_id', 'none')))}</code></p>
<form method="post" action="/actions/run" class="action-row">
<input type="hidden" name="action" value="workflow-auto-continue">
<button>Continue workflow</button>
</form>
<form method="post" action="/actions/run" class="action-row">
<input type="hidden" name="action" value="workflow-stop">
<button>Stop workflow</button>
</form>
<details>
<summary>Maintenance diagnostics</summary>
<p>Manual resume/import commands are maintenance-only. Use them only when a recorded blocker says the automatic bridge is broken.</p>
</details>
"""
```

Change the start button text to `Start workflow`. Keep option controls inside the start form.

- [ ] **Step 4: Add source bridge and cooldown to Console state**

In `wqb/console_state.py`, after active workflow summary is loaded:

```python
source_bridge = {"exists": False}
if active_run_dir is not None and active_workflow.get("current_stage") == "scout_seed":
    from wqb.source_bridge import inspect_scout_seed_source_bridge

    source_bridge = inspect_scout_seed_source_bridge(paths.runs_root, active_run_dir, datetime.now(timezone.utc).replace(microsecond=0).isoformat()).to_dict()
```

Add `"source_bridge": source_bridge` to `base_state`.

- [ ] **Step 5: Update timeline current work**

In `wqb/console_timeline.py`, when `state["source_bridge"]["action"] == "rate_limit_wait"`, return a current work row:

```python
return {
    "title": "Rate limited",
    "status": "waiting",
    "next_action": "Continue workflow after retry time",
    "details": [str(source_bridge.get("reason", "")), f"Source run: {source_bridge.get('source_run_id', '')}"],
    "evidence_paths": list(source_bridge.get("evidence_paths", [])),
}
```

Add similar read-only details for `import_existing`, `complete_in_flight`, and `retry_planned`.

- [ ] **Step 6: Run focused Console tests**

Run:

```powershell
python -m unittest tests.test_console_server tests.test_console_timeline -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add BrainWorkflow\wqb\console_server.py BrainWorkflow\wqb\console_state.py BrainWorkflow\wqb\console_timeline.py BrainWorkflow\tests\test_console_server.py BrainWorkflow\tests\test_console_timeline.py
git commit -m "simplify console workflow controls"
```

---

### Task 8: Operation Docs, Verification, And Handoff

**Files:**
- Modify: `docs/operations/user_workflow_manual.md`
- Modify: `docs/operations/operating_guide.md`
- Modify: `docs/superpowers/specs/2026-08-12-console-auto-recovery-knowledge-first-design.md` only if implementation reveals a corrected contract.
- Modify: root `C:\Users\oytl\Desktop\pyproject\brain\todo.md`
- Modify: root `C:\Users\oytl\Desktop\pyproject\brain\milestone.md`

**Interfaces:**
- Consumes: implemented Console actions and tests from Tasks 1-7.
- Produces: user-facing operation guide and recovery handoff.

- [ ] **Step 1: Update user manual one-button path**

In `docs/operations/user_workflow_manual.md`, replace the Orchestrator table with:

```markdown
| State | User action | System behavior |
| --- | --- | --- |
| No active workflow | Select one option card, then click `Start workflow` | Creates a durable Orchestrator run. |
| Active workflow | Click `Continue workflow` | Runs the next safe deterministic step or recovery step. |
| Rate limited | Click `Continue workflow` after the displayed retry time | Resumes the persisted planned queue; it does not discard candidates. |
| Waiting for user | Review the approval shown by the Console | Automatic progress stops until the human decision is recorded. |
| User wants to stop | Click `Stop workflow` | Aborts the active workflow non-destructively and preserves evidence. |
```

Remove normal-path instructions that ask the user to type a source run ID or choose between Resume and Continue. Move the CLI versions into a maintenance section.

- [ ] **Step 2: Update operating guide maintenance path**

In `docs/operations/operating_guide.md`, add a maintenance section:

````markdown
## Maintenance-Only Recovery Commands

The normal Console path is `Continue workflow`. Use these CLI commands only when the Console records a maintenance blocker:

```powershell
python -m wqb.cli workflow-status --knowledge-root '<knowledge>' --run-dir '<runs>'
python -m wqb.cli complete-in-flight --run-dir '<source-run-dir>'
python -m wqb.cli retry-planned --run-dir '<source-run-dir>'
python -m wqb.cli workflow-import-scout-seed-artifacts --source-run-id '<source-run-id>' --knowledge-root '<knowledge>' --run-dir '<runs>'
```
````

Add explicit copy that Scout source batches use cap 30 and Seed refinement uses cap 8.

- [ ] **Step 3: Run focused docs/Console tests**

Run:

```powershell
python -m unittest tests.test_research_workflow tests.test_console_server tests.test_console_jobs tests.test_console_timeline tests.test_rate_limit_state tests.test_source_run_lock tests.test_source_bridge tests.test_workflow_auto_continue tests.test_knowledge_source_resolver -q
```

Expected: PASS.

- [ ] **Step 4: Run full non-live verification**

Run:

```powershell
python -m unittest discover -s tests -q
python -m compileall -q wqb tests scripts
git diff --check
```

Expected: PASS for tests and compileall. `git diff --check` should have no whitespace errors.

- [ ] **Step 5: Update local recovery files**

Append to root `todo.md`:

```markdown
- 2026-08-12 implementation result:
  - Console primary path simplified.
  - Smart Continue, source bridge, cooldown state, lock state, and knowledge provenance are implemented.
  - Verification commands passed.
```

Append to root `milestone.md`:

````markdown
## 2026-08-12 Console auto-recovery implementation handoff

- Current loop: ready to hand back to operations runner.
- Last successful command: `python -m unittest discover -s tests -q`.
- Verification evidence: full non-live tests, compileall, diff check.
- Exact next operation command:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m wqb.cli workflow-status --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --run-dir 'C:\Users\oytl\Desktop\pyproject\brain\runs'
```
````

- [ ] **Step 6: Commit docs and handoff**

```powershell
git add BrainWorkflow\docs\operations\user_workflow_manual.md BrainWorkflow\docs\operations\operating_guide.md
git commit -m "document simplified workflow operation"
```

- [ ] **Step 7: Push branch**

Run:

```powershell
git push origin agent/brainworkflow-phase2
```

Expected: remote branch includes all implementation commits.

---

## Review Checklist

- Spec coverage: Tasks 1-8 cover stage caps, Console primary path, source bridge, cooldown, source lock, knowledge provenance, AI intervention visibility through state, Stop behavior, docs, and verification.
- No open markers: this plan has concrete files, function names, test names, commands, and expected outcomes.
- Type consistency: `SourceSelection`, `SourceBridgeDecision`, and `auto_continue_workflow` signatures are introduced before later tasks consume them.
- Scope control: direct model API integration, background daemon scheduling, and automatic Alpha submission are excluded from this implementation slice.
