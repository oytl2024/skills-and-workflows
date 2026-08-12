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
    """Input: run dir. Output: guard directory. Locate the atomic acquisition guard."""
    return Path(run_dir) / "source_run_lock.acquire"


def _guard_entry_path(guard_path: Path, owner_id: str) -> Path:
    """Input: guard directory and owner token. Output: owner entry path. Locate one owner's guard entry."""
    return guard_path / owner_id


def _read_guard_entry(guard_path: Path) -> tuple[Path, dict[str, Any]] | None:
    """Input: guard directory. Output: owner entry and metadata or none. Read the active guard owner safely."""
    try:
        entries = [entry for entry in guard_path.iterdir() if entry.is_file()]
    except OSError:
        return None
    if len(entries) != 1:
        return None
    entry = entries[0]
    try:
        metadata = json.loads(entry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (entry, metadata) if isinstance(metadata, dict) else None


def _remove_guard_entry(guard_path: Path, entry_path: Path) -> bool:
    """Input: guard directory and owner entry. Output: removal result. Remove only the observed owner entry."""
    try:
        entry_path.unlink()
    except FileNotFoundError:
        return False
    try:
        guard_path.rmdir()
    except OSError:
        pass
    return True


def _acquire_guard(path: Path, process_alive: Callable[[int], bool] | None = None) -> tuple[int, str] | None:
    """Input: guard directory and process probe. Output: descriptor/token or none. Acquire or safely recover a guard."""
    deadline = time.monotonic() + DEFAULT_GUARD_WAIT_SECONDS
    while True:
        try:
            path.mkdir()
        except FileExistsError:
            try:
                stale = time.time() - path.stat().st_mtime >= DEFAULT_GUARD_STALE_SECONDS
            except FileNotFoundError:
                continue
            if stale:
                guard_entry = _read_guard_entry(path)
                if guard_entry is None:
                    try:
                        path.rmdir()
                    except FileNotFoundError:
                        continue
                    except OSError:
                        pass
                    else:
                        continue
                else:
                    entry_path, guard = guard_entry
                    owner_pid = guard.get("pid")
                    probe = process_alive or default_process_is_alive
                    try:
                        owner_dead = isinstance(owner_pid, int) and probe(owner_pid) is False
                    except Exception:
                        owner_dead = False
                    if owner_dead:
                        _remove_guard_entry(path, entry_path)
                        continue
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.001)
        else:
            owner_id = uuid.uuid4().hex
            entry_path = _guard_entry_path(path, owner_id)
            descriptor: int | None = None
            try:
                descriptor = os.open(entry_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                metadata = {"pid": os.getpid(), "owner_id": owner_id, "created_at": time.time()}
                os.write(descriptor, json.dumps(metadata).encode("utf-8"))
                return descriptor, owner_id
            except Exception:
                if descriptor is not None:
                    os.close(descriptor)
                _remove_guard_entry(path, entry_path)
                raise


def _release_guard(path: Path, descriptor: int, owner_id: str) -> None:
    """Input: guard directory, descriptor, owner token. Output: none. Release only this owner's guard entry."""
    try:
        os.close(descriptor)
    except OSError:
        pass
    _remove_guard_entry(path, _guard_entry_path(path, owner_id))


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
