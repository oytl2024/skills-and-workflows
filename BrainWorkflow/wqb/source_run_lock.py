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
    return {**lock, "status": "acquired", "path": str(path)}


def release_source_run_lock(run_dir: str | Path, action: str, now: str) -> dict[str, Any]:
    """Input: run dir, action, timestamp. Output: release state. Mark a source mutation as finished."""
    path = _lock_path(run_dir)
    current = read_source_run_lock(run_dir)
    released = {**current, "status": "released", "released_at": now, "released_by": str(action)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(released, ensure_ascii=False, indent=2), encoding="utf-8")
    return released
