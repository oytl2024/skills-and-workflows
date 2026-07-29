from __future__ import annotations

from datetime import datetime, timezone
import json
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
