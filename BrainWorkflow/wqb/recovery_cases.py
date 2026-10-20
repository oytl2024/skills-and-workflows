"""Durable recovery identity; case creation never launches a process or calls WQB."""

import hashlib
import json
from pathlib import Path
import sys

from wqb.lockfile import json_lock_transition_guard
from wqb.runtime_control import _read, _write, read_runtime_control


RECOVERY_SCHEMA_VERSION = 1
RECOVERY_LOCK_SECONDS = 2.0
MAINTENANCE_BLOCKING_STATUSES = {"awaiting_maintenance_confirmation", "maintenance_approved"}


def read_current_recovery_case(run_dir: Path) -> dict:
    """Input: run Path. Output: dict. Read fresh case state, keeping corrupt resolution evidence blocked."""
    snapshot = read_runtime_control(run_dir).get("recovery_case") or {}
    case_id = str(snapshot.get("case_id", ""))
    if not snapshot:
        return {}
    valid_id = len(case_id) == 24 and all(character in "0123456789abcdef" for character in case_id)
    fresh = _read(Path(run_dir) / "runtime" / "recovery" / (case_id + ".json")) if valid_id else {}
    valid = fresh.get("case_id") == case_id and fresh.get("status") in {
        "classified", "paused", "waiting_external", "unsafe_to_recover", "awaiting_maintenance_confirmation",
        "maintenance_approved", "resolved"}
    valid = valid and fresh.get("category") in {"code_or_contract", "waiting_external", "reconciliation_required", "protected_prerequisite"}
    if valid and fresh.get("status") == "awaiting_maintenance_confirmation":
        valid = isinstance(fresh.get("notification"), dict)
    if valid and fresh.get("category") == "code_or_contract" and fresh.get("status") in {"classified", "paused"}:
        return {**fresh, "status": "awaiting_maintenance_confirmation",
                "notification": fresh.get("notification") or {"status": "pending"}}
    if valid and fresh.get("status") == "resolved":
        from wqb.maintenance_resolution import _code_digest
        receipt = _read(Path(run_dir) / "runtime" / "maintenance_verification" / (case_id + ".json"))
        count = receipt.get("tests_run")
        approval = (fresh.get("repair_approval") or {}).get("approval_id")
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]
        valid = (receipt.get("status") == "passed" and receipt.get("case_id") == case_id
                 and isinstance(approval, str) and len(approval) == 32 and all(character in '0123456789abcdef' for character in approval)
                 and receipt.get("approval_id") == approval and receipt.get("command") == command
                 and type(receipt.get("returncode")) is int and receipt["returncode"] == 0
                 and receipt.get("code_digest") == _code_digest(Path(__file__).resolve().parents[1])
                 and receipt.get("code_unchanged") is True and isinstance(count, int) and not isinstance(count, bool) and count > 0)
    if valid:
        return fresh
    if snapshot.get("category") == "code_or_contract" or snapshot.get("status") in MAINTENANCE_BLOCKING_STATUSES:
        return {**snapshot, "status": "awaiting_maintenance_confirmation",
                "notification": {"status": "failed", "error": "invalid_case_evidence_preserved"}}
    return snapshot


def classify_blocker(result: dict) -> dict:
    """Input: workflow result dict. Output: sanitized blocker dict. Classify without keeping raw error strings."""
    action = str(result.get("next_action", ""))
    stage = str(result.get("current_stage", ""))
    bridge = result.get("source_bridge") or {}
    metadata = bridge.get("metadata") or {}
    fault = {"source": bridge.get("source_run_id") or bridge.get("source_run_dir", ""),
             "uncertain": sorted(str(value) for value in (metadata.get("uncertain_expression_hashes")
                 or metadata.get("uncertain_submission_hashes") or []))}
    fingerprint = hashlib.sha256(json.dumps(fault, sort_keys=True).encode()).hexdigest()
    category = "code_or_contract"
    planning_fault = (result.get('stop_reason') in {'research_planning_blocked', 'research_plan_unavailable'} or
                      result.get('pause_reason') == 'research_plan_unavailable' or
                      str(result.get('pause_reason', '')).startswith('research_planning_blocked:'))
    if planning_fault:
        fault['planning_reason'] = str(result.get('message') or result.get('pause_reason', ''))
        fingerprint = hashlib.sha256(json.dumps(fault, sort_keys=True).encode()).hexdigest()
    if metadata.get("uncertain_submission_hashes") or metadata.get("uncertain_submission_count") or metadata.get("uncertain_expression_hashes"):
        category = "reconciliation_required"
    elif action in {"rate-limit-wait", "source-lock-wait"} or metadata.get("operator_acknowledgement_required") is True:
        category = "waiting_external"
    elif action in {"readiness-blocked", "enable-live-api-required", "research-loop-blocked", "research-mission-authority-required"} and not planning_fault:
        category = "protected_prerequisite"
    known_actions = {"maintenance-blocker", "source-batch-runner-missing", "rate-limit-wait", "source-lock-wait",
                     "readiness-blocked", "enable-live-api-required", "no_progress_detected", "stage_failed",
                     "research-loop-blocked", "research-mission-authority-required"}
    return {"action": action if action in known_actions else "stage_failed",
            "stage": stage if stage.replace("_", "").isalnum() and len(stage) < 64 else "unknown",
            "category": category, "fault_fingerprint": fingerprint,
            "retry_at": str(metadata.get("retry_at", ""))[:64]}


def ensure_recovery_case(run_dir: Path, blocker: dict, now: str) -> dict:
    """Input: run Path, classified blocker dict, timestamp str. Output: dict. Create exactly one case per fault fingerprint."""
    root = Path(run_dir) / "runtime" / "recovery"
    identity = {key: blocker.get(key, "") for key in ("action", "stage", "category", "fault_fingerprint")}
    case_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    path = root / (case_id + ".json")
    with json_lock_transition_guard(root / "cases", RECOVERY_LOCK_SECONDS, 0.01, "recovery cases busy"):
        while path.exists():
            row = _read(path)
            if row.get("invalid") or row.get("case_id") != case_id:
                raise ValueError("invalid recovery case; preserve evidence")
            if row.get("status") != "resolved":
                return row
            case_id = hashlib.sha256((case_id + ":next-occurrence").encode()).hexdigest()[:24]
            path = root / (case_id + ".json")
        row = {"schema_version": RECOVERY_SCHEMA_VERSION, "case_id": case_id,
               **identity, "created_at": now, "updated_at": now, "status": "classified",
               "intent_revision": read_runtime_control(run_dir).get("request_revision", ""),
               "attempts": 0, "next_wake": blocker.get("retry_at", ""),
               "patch_execution_allowed": False, "reason": ""}
        _write(path, row)
        return row


def advance_scripted_recovery(run_dir: Path, case: dict, policy: dict, now: str) -> dict:
    """Input: run Path, case/policy dicts and timestamp str. Output: dict. Route recovery without unsafe writes or live probes."""
    case_id = str(case.get("case_id", ""))
    if len(case_id) != 24 or any(character not in "0123456789abcdef" for character in case_id):
        raise ValueError("invalid recovery identity")
    root = Path(run_dir) / "runtime" / "recovery"
    path = root / (case_id + ".json")
    with json_lock_transition_guard(root / "cases", RECOVERY_LOCK_SECONDS, 0.01, "recovery cases busy"):
        row = _read(path)
        if row.get("invalid") or row.get("case_id") != case_id:
            raise ValueError("invalid recovery case; preserve evidence")
        control = read_runtime_control(run_dir)
        if row.get("status") in {"maintenance_approved", "resolved"}:
            return row
        if control.get("desired_state") != "running":
            status, reason = "paused", "user_paused"
        elif row["category"] == "waiting_external":
            status, reason = "waiting_external", "platform_or_lock_evidence_required"
        elif row["category"] == "reconciliation_required":
            status, reason = "unsafe_to_recover", "unknown_submission_requires_authoritative_reconciliation"
        elif row["category"] == "protected_prerequisite":
            status, reason = "waiting_external", "protected_authority_or_knowledge_prerequisite"
        else:
            status, reason = "awaiting_maintenance_confirmation", "human_confirmation_required_before_code_repair"
            if "notification" not in row:
                row["notification"] = {"status": "pending", "created_at": now,
                                       "target": "maintenance_chat", "repair_authorized": False}
            elif not isinstance(row["notification"], dict) or row["notification"].get("status") not in {
                    "pending", "claimed", "queued", "failed", "delivery_uncertain", "notified"}:
                raise ValueError("invalid maintenance notification; preserve evidence")
        row.update(status=status, reason=reason, updated_at=now, patch_execution_allowed=False)
        _write(path, row)
        return row
