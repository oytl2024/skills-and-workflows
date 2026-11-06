"""Sanitized diagnostic HTTP attempt records; never authoritative quota state."""

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from wqb.lockfile import json_lock_transition_guard


DEFAULT_MAX_EVENTS = 10000
MAX_LINE_BYTES = 2048
METRICS_LOCK_SECONDS = 0.1


def endpoint_class(method: str, path: str) -> str:
    """Input: HTTP method/path strings. Output: str. Classify without preserving private identifiers."""
    parts = urlsplit(path).path.strip("/").split("/")
    if parts[0] == "authentication":
        return "authentication"
    if parts[0] == "simulations":
        return "simulation_submit" if method.upper() == "POST" and len(parts) == 1 else "simulation_progress"
    if parts[0] == "alphas":
        if "check" in parts:
            return "alpha_check"
        if "correlations" in parts:
            return "alpha_correlation"
        return "alpha_result"
    if parts[0] in {"data-fields", "data-sets", "operators"}:
        return "catalog"
    return "other"


def _number(value, default=0):
    """Input: untrusted numeric value. Output: finite nonnegative number. Drop malformed metadata."""
    try:
        result = float(value)
        return result if 0 <= result < 1e12 else default
    except (TypeError, ValueError, OverflowError):
        return default


def record_request(run_dir: Path, event: dict) -> None:
    """Input: run Path and raw event dict. Output: None. Append allowlisted diagnostic fields under an OS lock."""
    headers = {str(key).lower(): value for key, value in event.get("headers", {}).items()}
    row = {"timestamp": datetime.now(timezone.utc).isoformat(),
           "method": str(event.get("method", "")).upper() if event.get("method", "").upper() in {"GET", "POST", "OPTIONS", "PATCH", "DELETE", "PUT"} else "OTHER",
           "endpoint": endpoint_class(str(event.get("method", "")), str(event.get("path", ""))),
           "status": int(_number(event.get("status"))),
           "duration_seconds": round(_number(event.get("duration_seconds")), 6),
           "payload_count": int(_number(event.get("payload_count"))),
           "transport_error": event.get("transport_error") is True}
    for header, target in (("retry-after", "retry_after_seconds"), ("x-ratelimit-reset", "reset_seconds"),
                           ("x-ratelimit-remaining", "quota_remaining")):
        value = _number(headers.get(header), None)
        if value is not None:
            row[target] = value
    path = Path(run_dir) / "runtime" / "request_metrics.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with json_lock_transition_guard(path, METRICS_LOCK_SECONDS, 0.01, "metrics writer busy"):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")


def summarize_requests(run_dir: Path, max_events: int = DEFAULT_MAX_EVENTS) -> dict:
    """Input: run Path and event cap int. Output: dict. Read a bounded prefix; mark truncation explicitly."""
    if max_events <= 0:
        raise ValueError("max_events must be positive")
    result = {"request_count": 0, "rate_limited": 0, "transport_errors": 0,
              "submitted_payload_count": 0, "by_endpoint": {}, "truncated": False}
    path = Path(run_dir) / "runtime" / "request_metrics.jsonl"
    if not path.exists():
        return result
    with path.open("rb") as stream:
        for _ in range(max_events):
            line = stream.readline(MAX_LINE_BYTES)
            if not line:
                break
            if not line.endswith(b"\n"):
                result["truncated"] = True
                break
            try:
                row = json.loads(line)
                endpoint = row["endpoint"]
                if not isinstance(endpoint, str):
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            result["request_count"] += 1
            counts = result["by_endpoint"]
            counts[endpoint] = counts.get(endpoint, 0) + 1
            result["rate_limited"] += row.get("status") == 429
            result["transport_errors"] += row.get("transport_error") is True
            if endpoint == "simulation_submit":
                result["submitted_payload_count"] += int(_number(row.get("payload_count")))
        result["truncated"] = result["truncated"] or bool(stream.read(1))
    return result
