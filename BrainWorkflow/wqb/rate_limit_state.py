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
