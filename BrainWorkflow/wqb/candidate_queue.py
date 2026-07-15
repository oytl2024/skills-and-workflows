from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any

from wqb.lockfile import (
    exclusive_json_lock,
    json_lock_snapshot_is_stale,
    read_json_lock_snapshot,
)
from wqb.workflow_contract import APPROVAL_REQUIRED_FIELDS


APPROVAL_FILENAME = "approval.jsonl"
QUEUE_FILENAME = "approved_candidates.jsonl"
API_SUBMISSION_CLAIMS_FILENAME = "api_submission_claims.jsonl"
API_SUBMISSION_CLAIMS_LOCK_FILENAME = "api_submission_claims.lock"
QUEUE_STATUSES = {"queued", "manually_submitted", "api_submitted", "skipped", "invalidated"}
DAILY_API_SUBMISSION_LIMIT = 1
API_SUBMISSION_LOCK_TIMEOUT_SECONDS = 5.0
API_SUBMISSION_LOCK_SLEEP_SECONDS = 0.05
API_SUBMISSION_LOCK_STALE_SECONDS = 300.0


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Input: path and rows. Output: none. Atomically replace JSONL after recovery."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temp.replace(path)


def _read_jsonl(path: Path, repair_trailing: bool = False) -> list[dict[str, Any]]:
    """Input: path and repair flag. Output: rows. Tolerate one incomplete trailing JSONL row."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    trailing_invalid = False
    lines = [
        (number, line)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if line.strip()
    ]
    for index, (line_number, line) in enumerate(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                trailing_invalid = True
                continue
            raise ValueError(f"malformed JSONL row {line_number} in {path.name}")
        if not isinstance(row, dict):
            raise ValueError(f"non-object JSONL row {line_number} in {path.name}")
        rows.append(row)
    if trailing_invalid and repair_trailing:
        _write_jsonl(path, rows)
    return rows


def approve_candidate(run_dir: str | Path, candidate: dict[str, object], approved_at: str, approved_by: str) -> dict[str, object]:
    """Input: run dir, candidate, approval metadata. Output: approval row. Persist exact candidate approval."""
    approval = validate_candidate_approval(candidate, approved_at, approved_by)
    path = Path(run_dir) / APPROVAL_FILENAME
    identity = _approval_identity(approval)
    rows = _read_jsonl(path, repair_trailing=True)
    for existing in rows:
        if _approval_identity(existing) == identity:
            return existing
    _write_jsonl(path, [*rows, approval])
    return approval


def validate_candidate_approval(
    candidate: dict[str, object], approved_at: str, approved_by: str
) -> dict[str, object]:
    """Input: candidate and approval metadata. Output: validated approval row. Reject blank required values."""
    raw_values = {
        "candidate_id": candidate.get("candidate_id"),
        "platform_alpha_id": candidate.get("platform_alpha_id"),
        "version": candidate.get("version"),
        "expression_hash": candidate.get("expression_hash"),
        "approved_at": approved_at,
        "approved_by": approved_by,
        "source_run_id": candidate.get("source_run_id"),
    }
    for field in APPROVAL_REQUIRED_FIELDS:
        value = raw_values.get(field)
        if value is None or not str(value).strip():
            raise ValueError(f"{field} is required for candidate approval")
    try:
        version = int(raw_values["version"])
    except (TypeError, ValueError) as exc:
        raise ValueError("version must be an integer for candidate approval") from exc
    approval = {
        "candidate_id": str(raw_values["candidate_id"]).strip(),
        "platform_alpha_id": str(raw_values["platform_alpha_id"]).strip(),
        "version": version,
        "expression_hash": str(raw_values["expression_hash"]).strip(),
        "approved_at": str(raw_values["approved_at"]).strip(),
        "approved_by": str(raw_values["approved_by"]).strip(),
        "source_run_id": str(raw_values["source_run_id"]).strip(),
    }
    return {field: approval[field] for field in APPROVAL_REQUIRED_FIELDS}


def load_approvals(run_dir: str | Path) -> list[dict[str, object]]:
    """Input: run dir. Output: approvals. Load candidate approval rows."""
    return _read_jsonl(Path(run_dir) / APPROVAL_FILENAME)


def approval_matches_candidate(approval: dict[str, object], candidate: dict[str, object]) -> bool:
    """Input: approval and candidate. Output: bool. Check exact candidate identity binding."""
    return _approval_identity(approval) == _approval_identity(candidate)


def _approval_identity(row: dict[str, object]) -> tuple[str, str, int, str, str]:
    """Input: approval-like row. Output: exact candidate identity. Build durable approval and queue key."""
    try:
        version = int(row.get("version", -1))
    except (TypeError, ValueError):
        version = -1
    return (
        str(row.get("candidate_id", "")),
        str(row.get("platform_alpha_id", "")),
        version,
        str(row.get("expression_hash", "")),
        str(row.get("source_run_id", "")),
    )


def _status_identity(row: dict[str, object]) -> tuple[str, int, str]:
    """Input: queue row. Output: CLI-compatible status identity. Match the existing status command surface."""
    try:
        version = int(row.get("version", -1))
    except (TypeError, ValueError):
        version = -1
    return (str(row.get("candidate_id", "")), version, str(row.get("expression_hash", "")))


def _timestamp_date(timestamp: object) -> str:
    """Input: timestamp value. Output: calendar-date string. Extract the durable daily-limit bucket."""
    return str(timestamp).strip().split("T", 1)[0]


def count_api_submissions_for_date(run_root: str | Path, updated_at: str) -> int:
    """Input: run root and timestamp string. Output: int. Count durable API submissions across all run queues for one date."""
    requested_date = _timestamp_date(updated_at)
    identities = {
        _approval_identity(row)
        for row in load_approved_queue(run_root)
        if row.get("status") == "api_submitted"
        and _timestamp_date(row.get("updated_at", "")) == requested_date
    }
    identities.update(
        _approval_identity(row)
        for row in _read_submission_claims(Path(run_root))
        if _timestamp_date(row.get("updated_at", "")) == requested_date
    )
    return len(identities)


def claim_api_submission_slot(
    run_root: str | Path, candidate: dict[str, object], updated_at: str
) -> dict[str, object]:
    """Input: run root, candidate row, timestamp. Output: claim row. Atomically reserve one daily API slot."""
    root = Path(run_root)
    root.mkdir(parents=True, exist_ok=True)
    requested_date = _timestamp_date(updated_at)
    identity = _approval_identity(candidate)
    with _api_submission_claim_lock(root):
        rows = _read_submission_claims(root, repair_trailing=True)
        queue_identities = {
            _approval_identity(row)
            for row in load_approved_queue(root)
            if row.get("status") == "api_submitted"
            and _timestamp_date(row.get("updated_at", "")) == requested_date
        }
        if identity in queue_identities:
            return {
                "candidate_id": str(candidate.get("candidate_id", "")).strip(),
                "platform_alpha_id": str(candidate.get("platform_alpha_id", "")).strip(),
                "version": int(candidate.get("version", -1)),
                "expression_hash": str(candidate.get("expression_hash", "")).strip(),
                "source_run_id": str(candidate.get("source_run_id", "")).strip(),
                "updated_at": str(updated_at),
                "_created": False,
            }
        for row in rows:
            if (
                _timestamp_date(row.get("updated_at", "")) == requested_date
                and _approval_identity(row) == identity
            ):
                return dict(row, _created=False)
        claim_identities = {
            _approval_identity(row)
            for row in rows
            if _timestamp_date(row.get("updated_at", "")) == requested_date
        }
        if len(queue_identities | claim_identities) >= DAILY_API_SUBMISSION_LIMIT:
            raise ValueError("daily API submission limit reached")
        claim = {
            "candidate_id": str(candidate.get("candidate_id", "")).strip(),
            "platform_alpha_id": str(candidate.get("platform_alpha_id", "")).strip(),
            "version": int(candidate.get("version", -1)),
            "expression_hash": str(candidate.get("expression_hash", "")).strip(),
            "source_run_id": str(candidate.get("source_run_id", "")).strip(),
            "updated_at": str(updated_at),
        }
        _write_jsonl(root / API_SUBMISSION_CLAIMS_FILENAME, [*rows, claim])
        return dict(claim, _created=True)


def release_api_submission_claim_slot(
    run_root: str | Path, candidate: dict[str, object], updated_at: str
) -> bool:
    """Input: run root, candidate row, timestamp. Output: bool. Remove a newly created API claim after failed queue mutation."""
    root = Path(run_root)
    requested_date = _timestamp_date(updated_at)
    identity = _approval_identity(candidate)
    with _api_submission_claim_lock(root):
        path = root / API_SUBMISSION_CLAIMS_FILENAME
        rows = _read_submission_claims(root, repair_trailing=True)
        kept = [
            row
            for row in rows
            if not (
                _timestamp_date(row.get("updated_at", "")) == requested_date
                and _approval_identity(row) == identity
            )
        ]
        if len(kept) == len(rows):
            return False
        if kept:
            _write_jsonl(path, kept)
        elif path.exists():
            path.unlink()
        return True


def _read_submission_claims(root: Path, repair_trailing: bool = False) -> list[dict[str, Any]]:
    """Input: run root Path. Output: claim rows. Load durable API submission claims."""
    return _read_jsonl(root / API_SUBMISSION_CLAIMS_FILENAME, repair_trailing=repair_trailing)


@contextmanager
def _api_submission_claim_lock(root: Path):
    """Input: run root Path. Output: context manager. Hold an exclusive run-root claim lock."""
    path = root / API_SUBMISSION_CLAIMS_LOCK_FILENAME
    with exclusive_json_lock(
        path,
        API_SUBMISSION_LOCK_TIMEOUT_SECONDS,
        API_SUBMISSION_LOCK_SLEEP_SECONDS,
        API_SUBMISSION_LOCK_STALE_SECONDS,
        "API submission claim lock is busy",
        stale_checker=_api_submission_lock_is_stale,
    ):
        yield


def _api_submission_lock_is_stale(path: Path, now_seconds: float) -> bool:
    """Input: lock path and epoch seconds. Output: bool. Decide whether a lock lease expired."""
    snapshot = read_json_lock_snapshot(path)
    if snapshot is None:
        return False
    return json_lock_snapshot_is_stale(
        snapshot, now_seconds, API_SUBMISSION_LOCK_STALE_SECONDS
    )


def queue_approved_candidate(run_dir: str | Path, approval: dict[str, object]) -> dict[str, object]:
    """Input: run dir and approval. Output: queue row. Add one approved candidate if not already queued."""
    if not str(approval.get("source_run_id", "")).strip():
        raise ValueError("source_run_id is required for approved queue entries")
    for field in APPROVAL_REQUIRED_FIELDS:
        value = approval.get(field)
        if value is None or not str(value).strip():
            raise ValueError(f"{field} is required for approved queue entries")
    path = Path(run_dir) / QUEUE_FILENAME
    rows = _read_jsonl(path, repair_trailing=True)
    identity = _approval_identity(approval)
    status_identity = _status_identity(approval)
    for row in rows:
        if _status_identity(row) != status_identity:
            continue
        if _approval_identity(row) != identity:
            raise ValueError("candidate queue contract key conflict")
        return row
    queued = dict(approval)
    queued["status"] = "queued"
    _write_jsonl(path, [*rows, queued])
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
    matches = [row for row in rows if _status_identity(row) == target]
    if not matches:
        raise ValueError("candidate queue entry not found")
    if len(matches) > 1:
        raise ValueError("candidate queue identity is ambiguous")
    updated = matches[0]
    current_status = str(updated.get("status", ""))
    if current_status == status:
        return updated
    if current_status == "invalidated":
        raise ValueError("invalidated candidate queue entry cannot be updated")
    if current_status == "api_submitted":
        raise ValueError("api_submitted status is immutable")
    if status == "api_submitted":
        requested_date = _timestamp_date(updated_at)
        submission_count = sum(
            1
            for row in rows
            if row.get("status") == "api_submitted"
            and _timestamp_date(row.get("updated_at", "")) == requested_date
        )
        if submission_count >= DAILY_API_SUBMISSION_LIMIT:
            raise ValueError("daily API submission limit reached")
    updated["status"] = status
    updated["updated_at"] = str(updated_at)
    _write_jsonl(path, rows)
    return updated


def invalidate_candidate_queue_entry(
    run_dir: str | Path,
    candidate_id: str,
    version: int,
    expression_hash: str,
    reason: str,
    invalidated_at: str,
) -> dict[str, object]:
    """Input: identity, reason, timestamp. Output: invalidated row. Mark a superseded candidate non-actionable."""
    path = Path(run_dir) / QUEUE_FILENAME
    rows = _read_jsonl(path)
    target = (str(candidate_id), int(version), str(expression_hash))
    matches = [row for row in rows if _status_identity(row) == target]
    if not matches:
        raise ValueError("candidate queue entry not found")
    if len(matches) > 1:
        raise ValueError("candidate queue identity is ambiguous")
    updated = matches[0]
    current_status = str(updated.get("status", ""))
    if current_status == "invalidated":
        return updated
    if current_status in {"manually_submitted", "api_submitted"}:
        raise ValueError("submitted candidate queue entry is immutable")
    updated["status"] = "invalidated"
    updated["updated_at"] = str(invalidated_at)
    updated["invalidation_reason"] = str(reason).strip() or "candidate approval invalidated"
    _write_jsonl(path, rows)
    return updated
