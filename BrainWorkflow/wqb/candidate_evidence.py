import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from wqb.lockfile import json_lock_transition_guard


DEFAULT_CANDIDATE_EVIDENCE_MAX_AGE_SECONDS = 24 * 60 * 60
MAX_CANDIDATE_EVIDENCE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
EVIDENCE_SCHEMA_VERSION = 1
EVIDENCE_LOCK_TIMEOUT_SECONDS = 5
EVIDENCE_LOCK_SLEEP_SECONDS = 0.01
REQUIRED_BASELINE_CHECKS = {"LOW_SHARPE", "LOW_FITNESS"}
REQUIRED_CORRELATION_CHECKS = {"SELF_CORRELATION", "PROD_CORRELATION"}
SUBMISSION_CHECKS = REQUIRED_CORRELATION_CHECKS | {"DATA_DIVERSITY", "REGULAR_SUBMISSION"}
SELF_POOL_REVISION_FILENAME = 'self_pool_revision'


def _canonical(value: Any) -> str:
    """Input: JSON-compatible value. Output: str; canonical strict JSON for integrity and identity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _identity(alpha_id: str, detail: dict) -> dict | None:
    """Input: str ID, dict detail. Output: dict or None; verify identity from first platform detail only."""
    if not isinstance(detail, dict) or detail.get("id") != alpha_id or detail.get("status") != "UNSUBMITTED":
        return None
    regular = detail.get("regular")
    expression = regular.get("code") if isinstance(regular, dict) else None
    settings = detail.get("settings")
    if not isinstance(expression, str) or not expression.strip() or not isinstance(settings, dict) or not settings:
        return None
    identity = {"alpha_id": alpha_id, "expression": expression, "settings": settings}
    _canonical(identity)
    return identity


def _checks(payload: dict) -> list | None:
    """Input: dict platform payload. Output: list[dict] or None; reject absent or malformed checks."""
    metrics = payload.get("is") if isinstance(payload, dict) else None
    checks = metrics.get("checks") if isinstance(metrics, dict) else None
    if not isinstance(checks, list) or not checks:
        return None
    if any(not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"]
           or not isinstance(item.get("result"), str) for item in checks):
        return None
    if len({item["name"] for item in checks}) != len(checks):
        return None
    return checks


def _verified_payload(alpha_id: str, detail: dict, response: dict) -> tuple[dict, dict] | None:
    """Input: str ID, raw dicts. Output: (check payload, metrics) or None; require complete hard-pass evidence."""
    identity = _identity(alpha_id, detail)
    if identity is None or not isinstance(response, dict):
        return None
    # A full-check response may echo identity, but must never contradict the first detail.
    if "id" in response and response["id"] != alpha_id:
        return None
    if "settings" in response and _canonical(response["settings"]) != _canonical(identity["settings"]):
        return None
    if "regular" in response and response["regular"] != detail["regular"]:
        return None
    if "status" in response and response["status"] != "UNSUBMITTED":
        return None
    baseline = _checks(detail)
    full = _checks(response)
    if baseline is None or full is None:
        return None
    baseline_only = [item for item in baseline if item["name"] not in SUBMISSION_CHECKS]
    if not REQUIRED_BASELINE_CHECKS.issubset({item["name"] for item in baseline_only}):
        return None
    if any(item["result"].upper() not in {"PASS", "WARNING"} for item in baseline_only):
        return None
    correlations = {item["name"] for item in full if item["result"].upper() == "PASS"}
    if not REQUIRED_CORRELATION_CHECKS.issubset(correlations):
        return None
    merged = {item["name"]: item for item in baseline}
    merged.update({item["name"]: item for item in full})
    if any(item["result"].upper() not in {"PASS", "WARNING"} for item in merged.values()):
        return None
    return {"is": {"checks": list(merged.values())}}, detail["is"]


def _cache_path(client, alpha_id: str) -> Path | None:
    """Input: client, str ID. Output: Path or None; opt in only with an explicit real knowledge root."""
    root = vars(client).get("knowledge_root")
    if not isinstance(root, (str, Path)) or not Path(root).is_absolute() or not Path(root).is_dir():
        return None
    key = hashlib.sha256(alpha_id.encode("utf-8")).hexdigest()
    return Path(root) / "machine" / "candidate_evidence" / f"{key}.json"


def _cache_options(client, alpha_id: str) -> tuple[Path, float] | None:
    """Input: client, str ID. Output: (Path, validity seconds) or None; bound reuse independently of invalidation."""
    path = _cache_path(client, alpha_id)
    if path is None:
        return None
    validity = vars(client).get("candidate_evidence_max_age_seconds", DEFAULT_CANDIDATE_EVIDENCE_MAX_AGE_SECONDS)
    if (type(validity) not in (int, float) or not math.isfinite(validity)
            or not 0 < validity <= MAX_CANDIDATE_EVIDENCE_MAX_AGE_SECONDS):
        return None
    return path, float(validity)


def _write_record(path: Path, record: dict) -> None:
    """Input: Path, dict. Output: None; atomically publish JSON, cleaning only our temporary file."""
    encoded = _canonical(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _self_pool_path(path: Path) -> Path:
    """Input: evidence Path. Output: Path. Locate the shared eligibility revision, not a success ledger."""
    return path.parent / SELF_POOL_REVISION_FILENAME


def _evidence_revision(path: Path) -> str:
    """Input: evidence Path. Output: str. Bind both entry and account SELF comparison-set revisions."""
    return hashlib.sha256(_canonical([_file_revision(path), _file_revision(_self_pool_path(path))]).encode()).hexdigest()


def invalidate_self_pool(knowledge_root: Path, cause: str) -> None:
    """Input: vault Path, stable cause str. Output: None. Invalidate all prior SELF eligibility once per cause."""
    if not isinstance(cause, str) or not cause.strip():
        raise ValueError('SELF pool invalidation requires a cause')
    path = Path(knowledge_root) / 'machine/candidate_evidence' / SELF_POOL_REVISION_FILENAME
    with json_lock_transition_guard(path, EVIDENCE_LOCK_TIMEOUT_SECONDS, EVIDENCE_LOCK_SLEEP_SECONDS,
                                    'candidate SELF pool is busy'):
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            state = {'causes': []}
        if (not isinstance(state, dict) or not isinstance(state.get('causes'), list)
                or any(not isinstance(item, str) for item in state['causes'])):
            raise ValueError('Malformed SELF pool revision')
        if cause in state['causes']:
            return
        _write_record(path, {'revision': uuid4().hex, 'causes': [*state['causes'], cause]})


def load_candidate_evidence(client, alpha_id: str) -> tuple[dict, dict] | None:
    """Input: client, Alpha str. Output: cached tuple or None. Serialize reuse with SELF pool invalidation."""
    path = _cache_path(client, alpha_id)
    if path is None:
        return None
    try:
        with json_lock_transition_guard(_self_pool_path(path), EVIDENCE_LOCK_TIMEOUT_SECONDS,
                                        EVIDENCE_LOCK_SLEEP_SECONDS, 'candidate SELF pool is busy'):
            return _load_candidate_evidence(client, alpha_id)
    except (OSError, ValueError):
        return None


def _load_candidate_evidence(client, alpha_id: str) -> tuple[dict, dict] | None:
    """Input: client, str ID. Output: raw-derived (check payload, metrics) or None; never request the platform."""
    try:
        options = _cache_options(client, alpha_id)
        if options is None:
            return None
        path, validity = options
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
            return None
        if record.get("invalidated") is not False or record.get("alpha_id") != alpha_id:
            return None
        if record.get('self_pool_revision', 'missing') != _file_revision(_self_pool_path(path)):
            return None
        digest = record.pop("integrity_sha256", None)
        if digest != hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest():
            return None
        checked_at = record.get("checked_at")
        expires_at = record.get("expires_at")
        if type(checked_at) not in (int, float) or type(expires_at) not in (int, float):
            return None
        now = time.time()
        if not (math.isfinite(checked_at) and math.isfinite(expires_at)
                and 0 <= now - checked_at < validity and checked_at < expires_at
                and expires_at - checked_at <= MAX_CANDIDATE_EVIDENCE_MAX_AGE_SECONDS and now < expires_at):
            return None
        detail = record.get("alpha_detail")
        if _canonical(record.get("identity")) != _canonical(_identity(alpha_id, detail)):
            return None
        verified = _verified_payload(alpha_id, detail, record.get("check_response"))
        if verified is None:
            return None
        payload, metrics = verified
        audit = {"evidence_source": "cached", "checked_at": checked_at,
                 "expires_at": min(expires_at, checked_at + validity), "persistence_status": "persisted"}
        return payload, {**metrics, "candidate_evidence": audit}
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        return None


def _file_revision(path: Path) -> str:
    """Input: evidence Path. Output: digest str. Identify the complete prior state, including invalidation."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return 'missing'


def capture_evidence_revision(client, alpha_id: str) -> str | None:
    """Input: client and Alpha ID str. Output: revision str or None. Bind a check before any platform request."""
    path = _cache_path(client, alpha_id)
    if path is None:
        return None
    try:
        with json_lock_transition_guard(_self_pool_path(path), EVIDENCE_LOCK_TIMEOUT_SECONDS,
                                        EVIDENCE_LOCK_SLEEP_SECONDS, 'candidate SELF pool is busy'):
            return _evidence_revision(path)
    except (OSError, ValueError):
        return 'unreadable'


def save_candidate_evidence(client, alpha_id: str, detail: dict, response: dict,
                            expected_revision: str | None = None) -> dict:
    """Input: client, str ID, raw dicts. Output: audit dict; report retention only after successful atomic write."""
    checked_at = time.time()
    audit = {"evidence_source": "fresh", "checked_at": checked_at,
             "expires_at": None, "persistence_status": "disabled"}
    try:
        options = _cache_options(client, alpha_id)
        if options is None:
            return audit
        if _verified_payload(alpha_id, detail, response) is None:
            return {**audit, "persistence_status": "ineligible"}
        path, validity = options
        expected = expected_revision if expected_revision is not None else _evidence_revision(path)
        record = {"schema_version": EVIDENCE_SCHEMA_VERSION, "alpha_id": alpha_id,
                  "identity": _identity(alpha_id, detail), "alpha_detail": detail,
                  "check_response": response, "checked_at": checked_at,
                  "expires_at": checked_at + validity, "invalidated": False}
        with json_lock_transition_guard(_self_pool_path(path), EVIDENCE_LOCK_TIMEOUT_SECONDS,
                                        EVIDENCE_LOCK_SLEEP_SECONDS, 'candidate SELF pool is busy'):
            with json_lock_transition_guard(path, EVIDENCE_LOCK_TIMEOUT_SECONDS, EVIDENCE_LOCK_SLEEP_SECONDS,
                                            'candidate evidence is busy'):
                if _evidence_revision(path) != expected:
                    return {**audit, 'persistence_status': 'superseded'}
                record['self_pool_revision'] = _file_revision(_self_pool_path(path))
                record["integrity_sha256"] = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
                _write_record(path, record)
        return {**audit, "expires_at": record["expires_at"], "persistence_status": "persisted"}
    except (OSError, ValueError, TypeError, OverflowError, RecursionError) as error:
        # Report only the error class; filesystem paths or platform content need not leak into diagnostics.
        return {**audit, "persistence_status": "failed", "persistence_error": type(error).__name__}


def invalidate_candidate_evidence(client, alpha_id: str, reason: str = "explicit_invalidation") -> None:
    """Input: client, str ID/reason. Output: None; retain raw evidence while invalidating; errors propagate."""
    path = _cache_path(client, alpha_id)
    if path is not None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Invalidation requires a nonempty reason")
        with json_lock_transition_guard(path, EVIDENCE_LOCK_TIMEOUT_SECONDS, EVIDENCE_LOCK_SLEEP_SECONDS,
                                        'candidate evidence is busy'):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                record = {"schema_version": EVIDENCE_SCHEMA_VERSION, "alpha_id": alpha_id}
            if not isinstance(record, dict):
                raise ValueError("Cannot invalidate malformed evidence without erasing it")
            record.update({"invalidated": True, "invalidation_reason": reason,
                           "invalidated_at": time.time(), "invalidation_revision": uuid4().hex})
            record.pop("integrity_sha256", None)
            record["integrity_sha256"] = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
            _write_record(path, record)
