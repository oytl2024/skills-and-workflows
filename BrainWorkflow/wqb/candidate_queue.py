from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wqb.workflow_contract import APPROVAL_REQUIRED_FIELDS


APPROVAL_FILENAME = "approval.jsonl"
QUEUE_FILENAME = "approved_candidates.jsonl"
QUEUE_STATUSES = {"queued", "manually_submitted", "api_submitted", "skipped", "invalidated"}


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """Input: path and row. Output: none. Append one JSONL row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: path. Output: rows. Read valid JSONL rows."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def approve_candidate(run_dir: str | Path, candidate: dict[str, object], approved_at: str, approved_by: str) -> dict[str, object]:
    """Input: run dir, candidate, approval metadata. Output: approval row. Persist exact candidate approval."""
    approval = {
        "candidate_id": str(candidate["candidate_id"]),
        "platform_alpha_id": str(candidate["platform_alpha_id"]),
        "version": int(candidate["version"]),
        "expression_hash": str(candidate["expression_hash"]),
        "approved_at": str(approved_at),
        "approved_by": str(approved_by),
        "source_run_id": str(candidate.get("source_run_id", "")),
    }
    approval = {field: approval[field] for field in APPROVAL_REQUIRED_FIELDS}
    _append_jsonl(Path(run_dir) / APPROVAL_FILENAME, approval)
    return approval


def load_approvals(run_dir: str | Path) -> list[dict[str, object]]:
    """Input: run dir. Output: approvals. Load candidate approval rows."""
    return _read_jsonl(Path(run_dir) / APPROVAL_FILENAME)


def approval_matches_candidate(approval: dict[str, object], candidate: dict[str, object]) -> bool:
    """Input: approval and candidate. Output: bool. Check exact version and hash binding."""
    return (
        str(approval.get("candidate_id", "")) == str(candidate.get("candidate_id", ""))
        and int(approval.get("version", -1)) == int(candidate.get("version", -2))
        and str(approval.get("expression_hash", "")) == str(candidate.get("expression_hash", ""))
    )


def _queue_identity(row: dict[str, object]) -> tuple[str, int, str]:
    """Input: queue-like row. Output: identity tuple. Build dedupe key."""
    return (str(row.get("candidate_id", "")), int(row.get("version", 0)), str(row.get("expression_hash", "")))


def queue_approved_candidate(run_dir: str | Path, approval: dict[str, object]) -> dict[str, object]:
    """Input: run dir and approval. Output: queue row. Add one approved candidate if not already queued."""
    path = Path(run_dir) / QUEUE_FILENAME
    rows = _read_jsonl(path)
    identity = _queue_identity(approval)
    for row in rows:
        if _queue_identity(row) == identity:
            return row
    queued = dict(approval)
    queued["status"] = "queued"
    _append_jsonl(path, queued)
    return queued


def load_approved_queue(run_root_or_run_dir: str | Path) -> list[dict[str, object]]:
    """Input: run root or run dir. Output: queue rows. Load approved candidate queue."""
    root = Path(run_root_or_run_dir)
    direct = root / QUEUE_FILENAME
    if direct.exists():
        return _read_jsonl(direct)
    rows: list[dict[str, object]] = []
    for path in root.glob(f"*/{QUEUE_FILENAME}"):
        rows.extend(_read_jsonl(path))
    return rows


def update_candidate_queue_status(
    run_dir: str | Path,
    candidate_id: str,
    version: int,
    expression_hash: str,
    status: str,
    updated_at: str,
) -> dict[str, object]:
    """Input: identity and status. Output: updated row. Rewrite queue with one status update."""
    if status not in QUEUE_STATUSES:
        raise ValueError(f"unsupported queue status: {status}")
    path = Path(run_dir) / QUEUE_FILENAME
    rows = _read_jsonl(path)
    target = (str(candidate_id), int(version), str(expression_hash))
    updated: dict[str, object] | None = None
    for row in rows:
        if _queue_identity(row) == target:
            row["status"] = status
            row["updated_at"] = str(updated_at)
            updated = row
            break
    if updated is None:
        raise ValueError("candidate queue entry not found")
    path.write_text("", encoding="utf-8")
    for row in rows:
        _append_jsonl(path, row)
    return updated
