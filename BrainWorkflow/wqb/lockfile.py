from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
from typing import Callable

if os.name == "nt":
    import msvcrt
else:
    import fcntl


LockSnapshot = dict[str, object]
StaleChecker = Callable[[Path, float], bool]


@contextmanager
def exclusive_json_lock(
    lock_path: str | Path,
    timeout_seconds: float,
    sleep_seconds: float,
    stale_seconds: float,
    busy_message: str,
    stale_checker: StaleChecker | None = None,
):
    """Input: lock path and timing policy. Output: context manager. Hold one JSON lock file."""
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}-{time.time_ns()}"
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    with json_lock_transition_guard(path, timeout_seconds, sleep_seconds, busy_message):
        while not acquired:
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if _recover_stale_json_lock_unlocked(
                    path, time.time(), stale_seconds, stale_checker
                ):
                    continue
                if time.monotonic() >= deadline:
                    raise ValueError(busy_message) from None
            else:
                try:
                    write_json_lock_payload(fd, token)
                except Exception:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                    raise
                acquired = True
            if not acquired:
                time.sleep(sleep_seconds)
        try:
            yield
        finally:
            release_json_lock_unlocked(path, token)


@contextmanager
def json_lock_transition_guard(
    lock_path: str | Path,
    timeout_seconds: float,
    sleep_seconds: float,
    busy_message: str,
):
    """Input: lock path and timing policy. Output: context manager. Serialize lock transitions."""
    guard_path = Path(str(lock_path) + ".guard")
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    with guard_path.open("a+b") as handle:
        _ensure_guard_byte(handle)
        acquired = False
        while not acquired:
            try:
                _try_lock_guard(handle)
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError(busy_message) from None
                time.sleep(sleep_seconds)
            else:
                acquired = True
        try:
            yield
        finally:
            _unlock_guard(handle)


def _ensure_guard_byte(handle) -> None:
    """Input: binary file handle. Output: none. Ensure byte-range locks have one byte."""
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)


def _try_lock_guard(handle) -> None:
    """Input: binary file handle. Output: none. Acquire a non-blocking OS advisory lock."""
    handle.seek(0)
    if os.name == "nt":
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError from exc
    else:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BlockingIOError from exc


def _unlock_guard(handle) -> None:
    """Input: binary file handle. Output: none. Release the OS advisory transition lock."""
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_json_lock_payload(fd: int, token: str) -> None:
    """Input: OS file descriptor and token. Output: none. Persist lock owner metadata."""
    payload = {
        "token": token,
        "pid": os.getpid(),
        "created_at": time.time(),
    }
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)


def read_json_lock_snapshot(path: str | Path) -> LockSnapshot | None:
    """Input: lock path. Output: snapshot or none. Capture lock file bytes and file identity hints."""
    lock_path = Path(path)
    try:
        raw = lock_path.read_text(encoding="utf-8")
        stat = lock_path.stat()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    return {
        "raw": raw,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def json_lock_snapshot_is_stale(
    snapshot: LockSnapshot, now_seconds: float, stale_seconds: float
) -> bool:
    """Input: lock snapshot and timing policy. Output: bool. Decide whether a JSON lock expired."""
    raw = str(snapshot.get("raw", ""))
    mtime_ns = int(snapshot.get("mtime_ns", 0))
    ages = [now_seconds - (mtime_ns / 1_000_000_000)]
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            created_at = float(payload.get("created_at", mtime_ns / 1_000_000_000))
            ages.append(now_seconds - created_at)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return max(ages) >= stale_seconds


def recover_stale_json_lock(
    path: str | Path,
    now_seconds: float,
    stale_seconds: float,
    stale_checker: StaleChecker | None = None,
) -> bool:
    """Input: lock path and stale policy. Output: bool. Remove only the stale lock snapshot observed."""
    lock_path = Path(path)
    with json_lock_transition_guard(
        lock_path, 5.0, 0.05, f"{lock_path.name} transition guard is busy"
    ):
        return _recover_stale_json_lock_unlocked(
            lock_path, now_seconds, stale_seconds, stale_checker
        )


def _recover_stale_json_lock_unlocked(
    path: str | Path,
    now_seconds: float,
    stale_seconds: float,
    stale_checker: StaleChecker | None = None,
) -> bool:
    """Input: lock path and stale policy. Output: bool. Recover a stale lock while transition guard is held."""
    lock_path = Path(path)
    snapshot = read_json_lock_snapshot(lock_path)
    if snapshot is None:
        return False
    is_stale = (
        stale_checker(lock_path, now_seconds)
        if stale_checker is not None
        else json_lock_snapshot_is_stale(snapshot, now_seconds, stale_seconds)
    )
    if not is_stale:
        return False
    if read_json_lock_snapshot(lock_path) != snapshot:
        return False
    tombstone = lock_path.with_name(
        f"{lock_path.name}.stale.{os.getpid()}.{time.time_ns()}"
    )
    try:
        lock_path.rename(tombstone)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    tombstone_snapshot = read_json_lock_snapshot(tombstone)
    if tombstone_snapshot != snapshot:
        try:
            if not lock_path.exists():
                tombstone.rename(lock_path)
        except OSError as exc:
            raise ValueError(f"{lock_path.name} changed during stale lock recovery") from exc
        return False
    try:
        tombstone.unlink()
    except FileNotFoundError:
        pass
    return True


def release_json_lock(
    path: str | Path,
    token: str,
    timeout_seconds: float = 5.0,
    sleep_seconds: float = 0.05,
    busy_message: str = "JSON lock transition guard is busy",
) -> None:
    """Input: lock path and owner token. Output: none. Remove only the caller-owned lock file."""
    lock_path = Path(path)
    with json_lock_transition_guard(
        lock_path, timeout_seconds, sleep_seconds, busy_message
    ):
        release_json_lock_unlocked(lock_path, token)


def release_json_lock_unlocked(path: str | Path, token: str) -> None:
    """Input: lock path and owner token. Output: none. Release lock while transition guard is held."""
    lock_path = Path(path)
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict) or str(payload.get("token", "")) != token:
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
