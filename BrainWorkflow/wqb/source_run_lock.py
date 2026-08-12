from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Callable
import uuid

from wqb.console_progress import process_is_alive as default_process_is_alive


DEFAULT_LOCK_TTL_SECONDS = 3600
DEFAULT_GUARD_STALE_SECONDS = 300
DEFAULT_GUARD_WAIT_SECONDS = 0.1


def _parse_time(value: str) -> datetime:
    """Input: timestamp. Output: timezone-aware datetime. Parse source lock times."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _lock_path(run_dir: str | Path) -> Path:
    """Input: run dir. Output: lock path. Locate source-run mutation lock."""
    return Path(run_dir) / "source_run_lock.json"


def _acquisition_guard_path(run_dir: str | Path) -> Path:
    """Input: run dir. Output: guard path. Locate the atomic acquisition guard."""
    return Path(run_dir) / "source_run_lock.acquire"


def _acquire_guard(path: Path, process_alive: Callable[[int], bool] | None = None) -> tuple[int, str] | None:
    """Input: guard path and process probe. Output: descriptor/token or None. Acquire or safely recover a guard."""
    deadline = time.monotonic() + DEFAULT_GUARD_WAIT_SECONDS
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            owner_id = uuid.uuid4().hex
            os.write(descriptor, json.dumps({"pid": os.getpid(), "owner_id": owner_id, "created_at": time.time()}).encode("utf-8"))
            return descriptor, owner_id
        except FileExistsError:
            try:
                stale = time.time() - path.stat().st_mtime >= DEFAULT_GUARD_STALE_SECONDS
            except FileNotFoundError:
                stale = False
            if stale:
                try:
                    guard = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    guard = {}
                owner_pid = guard.get("pid") if isinstance(guard, dict) else None
                probe = process_alive or default_process_is_alive
                try:
                    owner_dead = isinstance(owner_pid, int) and probe(owner_pid) is False
                except Exception:
                    owner_dead = False
                if owner_dead:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.001)


def _release_guard(path: Path, descriptor: int, owner_id: str) -> None:
    """Input: guard path, descriptor, owner token. Output: none. Release only this guard's file."""
    os.close(descriptor)
    try:
        guard = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(guard, dict) and guard.get("owner_id") == owner_id:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


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
    guard_path = _acquisition_guard_path(root)
    guard_state = _acquire_guard(guard_path, process_alive)
    if guard_state is None:
        return {"status": "busy", "reason": "active_guard", "path": str(path)}
    guard, guard_owner = guard_state
    try:
        return _acquire_source_run_lock_locked(
            root,
            path,
            action,
            now,
            ttl_seconds,
            process_alive,
            pid,
            command_hash,
            candidate_hash,
            progress_url,
        )
    finally:
        _release_guard(guard_path, guard, guard_owner)


def _acquire_source_run_lock_locked(
    root: Path,
    path: Path,
    action: str,
    now: str,
    ttl_seconds: int,
    process_alive: Callable[[int], bool] | None,
    pid: int | None,
    command_hash: str,
    candidate_hash: str,
    progress_url: str,
) -> dict[str, Any]:
    """Input: guarded lock inputs. Output: lock decision. Read and write one source lock atomically."""
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
        "owner_id": uuid.uuid4().hex,
    }
    path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**lock, "status": "acquired", "path": str(path)}


def release_source_run_lock(
    run_dir: str | Path,
    action: str,
    now: str,
    pid: int | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """Input: run dir, action, timestamp. Output: release state. Mark a source mutation as finished."""
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = _lock_path(root)
    guard_path = _acquisition_guard_path(root)
    guard_state = _acquire_guard(guard_path)
    if guard_state is None:
        return {"status": "busy", "reason": "active_guard", "path": str(path)}
    guard, guard_owner = guard_state
    try:
        current = read_source_run_lock(root)
        if current.get("status") == "running":
            if not owner_id:
                return {**current, "status": "ownership_required", "path": str(path)}
            action_matches = current.get("action") == str(action)
            pid_matches = pid is None or current.get("pid") == int(pid)
            owner_matches = current.get("owner_id") == str(owner_id)
            if not (action_matches and pid_matches and owner_matches):
                return {**current, "status": "ownership_mismatch", "path": str(path)}
        released = {**current, "status": "released", "released_at": now, "released_by": str(action)}
        path.write_text(json.dumps(released, ensure_ascii=False, indent=2), encoding="utf-8")
        return released
    finally:
        _release_guard(guard_path, guard, guard_owner)
