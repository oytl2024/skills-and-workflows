from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
from typing import Any, Mapping

from wqb.runtime_control import _write, RuntimePaused
from wqb.source_run_lock import acquire_source_run_lock, release_source_run_lock


BASE_COOLDOWN_SECONDS = 60
MAX_COOLDOWN_SECONDS = 900
MAX_CONSECUTIVE_429 = 3
MAX_BACKOFF_ATTEMPT_COUNT = 32
BOUNDED_RETRY_LEASE_SECONDS = 90


class RateLimitRecoveryRequired(RuntimePaused):
    """Input: source Path/state dict. Output: typed local stop. Request bounded recovery without submitting."""

    def __init__(self, source: Path, state: dict) -> None:
        super().__init__("rate_limit_recovery_authorization_required")
        self.source_run_dir = str(source)
        self.retry_at = str(state.get("retry_at", ""))


def check_source_retry_authorization(source: Path, now: str | None = None) -> None:
    """Input: source Path/optional ISO time. Output: none or local stop. Recheck cooldown/lease immediately before POST."""
    state = read_rate_limit_state(Path(source) / "rate_limit_state.json")
    current = now or datetime.now(timezone.utc).isoformat()
    if state.get("status") == "invalid":
        raise ValueError("invalid rate-limit evidence; submission refused")
    count = _normalized_counter(state.get("consecutive_429_count"), MAX_CONSECUTIVE_429)
    if cooldown_is_active(state, current) or (count >= MAX_CONSECUTIVE_429 - 1 and not bounded_retry_is_authorized(state, current)):
        raise RateLimitRecoveryRequired(Path(source), state)


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


def compute_backoff_seconds(
    attempt_count: int,
    base_seconds: int = BASE_COOLDOWN_SECONDS,
    max_seconds: int = MAX_COOLDOWN_SECONDS,
) -> int:
    """Input: attempt count and bounds. Output: cooldown seconds. Use deterministic bounded backoff."""
    attempt = max(1, int(attempt_count))
    raw = int(base_seconds) * (2 ** (attempt - 1))
    jitter = min(30, attempt * 3)
    return min(int(max_seconds), raw + jitter)


def _normalized_counter(value: Any, maximum: int) -> int:
    """Input: persisted counter and upper bound. Output: bounded int. Normalize malformed durable state safely."""
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(parsed, int(maximum)))


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


def bounded_retry_is_authorized(state: dict[str, Any], now: str) -> bool:
    """Input: rate-limit dict/time str. Output: bool. Match an unexpired retry lease to unchanged platform evidence."""
    permit = state.get("bounded_retry")
    if not isinstance(permit, dict) or state.get("status") != "cooldown":
        return False
    if any(permit.get(key) != state.get(key) for key in ("updated_at", "retry_at", "consecutive_429_count", "attempt_count")):
        return False
    try:
        return _parse_time(permit["authorized_at"]) <= _parse_time(now) < _parse_time(permit["expires_at"]) and not cooldown_is_active(state, now)
    except (KeyError, TypeError, ValueError):
        return False


def authorize_bounded_retry(run_dir: str | Path, now: str) -> dict[str, Any]:
    """Input: source Path/time str. Output: dict. Lease one bounded recovery window without claiming platform recovery."""
    root = Path(run_dir)
    path = root / "rate_limit_state.json"
    lock = acquire_source_run_lock(root, "bounded-rate-recovery", now)
    if lock.get("status") != "acquired":
        raise ValueError("source worker owns rate-limit state")
    try:
        state = read_rate_limit_state(path)
        retry_at = state.get("retry_at")
        if state.get("status") != "cooldown" or not retry_at or _parse_time(now) < _parse_time(str(retry_at)):
            raise ValueError("valid expired platform cooldown required")
        state["bounded_retry"] = {key: state.get(key) for key in ("updated_at", "retry_at", "consecutive_429_count", "attempt_count")}
        state["bounded_retry"].update(authorized_at=now,
            expires_at=(_parse_time(now) + timedelta(seconds=BOUNDED_RETRY_LEASE_SECONDS)).isoformat(),
            reason="bounded_runtime_retry_not_platform_recovery_evidence")
        _write(path, state)
        return state
    finally:
        release_source_run_lock(root, "bounded-rate-recovery", now, owner_id=str(lock.get("owner_id", "")))


def rate_limit_requires_maintenance(state: dict[str, Any], now: str | None = None) -> bool:
    """Input: rate-limit state dict. Output: bool. Stop automatic recovery at the consecutive-429 threshold."""
    count = _normalized_counter(
        state.get("consecutive_429_count", 0), MAX_CONSECUTIVE_429
    )
    current = now or datetime.now(timezone.utc).isoformat()
    return count >= MAX_CONSECUTIVE_429 and not bounded_retry_is_authorized(state, current)


def reset_rate_limit(
    run_dir: str | Path,
    reason: str,
    now: str,
) -> dict[str, Any]:
    """Input: source run, reset reason, timestamp. Output: ready state dict. Clear cooldown after platform progress."""
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "rate_limit_state.json"
    previous = read_rate_limit_state(path)
    state = {
        **(previous if isinstance(previous, dict) else {}),
        "status": "ready",
        "updated_at": now,
        "retry_after_seconds": 0,
        "retry_at": "",
        "attempt_count": 0,
        "consecutive_429_count": 0,
        "max_consecutive_429": MAX_CONSECUTIVE_429,
        "reset_reason": str(reason),
        "reset_at": now,
    }
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def acknowledge_rate_limit_recovery(
    run_dir: str | Path,
    reason: str,
    now: str,
) -> dict[str, Any]:
    """Input: source run, operator reason, timestamp. Output: ready state dict. Clear a 429 threshold after local acknowledgement."""
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "rate_limit_state.json"
    previous = read_rate_limit_state(path)
    state = {
        **(previous if isinstance(previous, dict) else {}),
        "status": "ready",
        "updated_at": now,
        "retry_after_seconds": 0,
        "retry_at": "",
        "attempt_count": 0,
        "consecutive_429_count": 0,
        "max_consecutive_429": MAX_CONSECUTIVE_429,
        "reset_reason": "operator_acknowledged_rate_limit_recovery",
        "reset_at": now,
        "acknowledged_reason": str(reason),
        "acknowledged_at": now,
    }
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def record_rate_limit(
    run_dir: str | Path,
    stage: str,
    error: BaseException,
    context: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    """Input: run dir, stage, error, context, timestamp. Output: cooldown state. Persist rate-limit recovery state."""
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "rate_limit_state.json"
    previous = read_rate_limit_state(path)
    attempt_count = min(
        MAX_BACKOFF_ATTEMPT_COUNT,
        _normalized_counter(
            previous.get("attempt_count", 0), MAX_BACKOFF_ATTEMPT_COUNT - 1
        )
        + 1,
    )
    consecutive_count = min(
        MAX_CONSECUTIVE_429,
        _normalized_counter(
            previous.get("consecutive_429_count", 0), MAX_CONSECUTIVE_429 - 1
        )
        + 1,
    )
    current_time = _parse_time(now)
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    retry_after = parse_retry_after_seconds(headers, current_time)
    wait_seconds = (
        retry_after
        if retry_after is not None
        else compute_backoff_seconds(attempt_count)
    )
    retry_at = current_time + timedelta(seconds=wait_seconds)
    state = {
        "status": "cooldown",
        "updated_at": now,
        "retry_after_seconds": wait_seconds,
        "retry_at": retry_at.isoformat(),
        "attempt_count": attempt_count,
        "consecutive_429_count": consecutive_count,
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
