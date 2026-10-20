"""Human-approved repair verification; never starts research or changes run intent."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from wqb.lockfile import json_lock_transition_guard
from wqb.recovery_cases import RECOVERY_LOCK_SECONDS, read_current_recovery_case
from wqb.runtime_control import _read, _write, read_runtime_control, update_runtime_status, utc_now
from wqb.source_run_lock import acquire_source_run_lock, release_source_run_lock


VERIFICATION_TIMEOUT_SECONDS = 600
MAX_CONFIRMATION_LENGTH = 256


def _case_path(run_dir: Path, case_id: str) -> Path:
    """Input: run Path/case ID str. Output: Path. Reject identity traversal before local access."""
    if len(case_id) != 24 or any(character not in "0123456789abcdef" for character in case_id):
        raise ValueError("invalid recovery identity")
    return Path(run_dir) / "runtime" / "recovery" / (case_id + ".json")


def _code_digest(project: Path) -> str:
    """Input: project Path. Output: SHA256 str. Bind verification to production and test source."""
    digest = hashlib.sha256()
    paths = [*project.glob("wqb/**/*.py"), *project.glob("tests/**/*.py"), *project.glob("scripts/**/*.py")]
    paths.extend(path for path in (project / "pyproject.toml", project / "requirements.txt") if path.exists())
    for path in sorted(paths):
        digest.update(str(path.relative_to(project)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def approve_repair(run_dir: Path, case_id: str, confirmation_reference: str) -> dict:
    """Input: run Path, case ID and human-confirmation reference str. Output: approved dict. Record scoped manual approval."""
    if not confirmation_reference.strip() or len(confirmation_reference) > MAX_CONFIRMATION_LENGTH:
        raise ValueError("explicit human confirmation reference required")
    path = _case_path(run_dir, case_id)
    with json_lock_transition_guard(path.parent / "cases", RECOVERY_LOCK_SECONDS, 0.01, "recovery cases busy"):
        if (read_runtime_control(run_dir).get("recovery_case") or {}).get("case_id") != case_id:
            raise ValueError("approval must match the current blocking case")
        row = _read(path)
        if row.get("status") == "resolved" and read_current_recovery_case(run_dir).get("status") == "awaiting_maintenance_confirmation":
            previous_id = case_id
            while path.exists():
                existing = _read(path)
                if existing.get("case_id") != case_id or existing.get("status") != "resolved":
                    raise ValueError("another unresolved occurrence already exists; preserve evidence")
                case_id = hashlib.sha256((case_id + ":next-occurrence").encode()).hexdigest()[:24]
                path = _case_path(run_dir, case_id)
            row = {key: row[key] for key in ("schema_version", "action", "stage", "category", "fault_fingerprint")}
            row.update(case_id=case_id, created_at=utc_now(), status="awaiting_maintenance_confirmation", reopened_from=previous_id)
        if row.get("case_id") != case_id or row.get("category") != "code_or_contract" or row.get("status") not in {
                "awaiting_maintenance_confirmation", "maintenance_approved", "paused", "classified"}:
            raise ValueError("case is not awaiting a human-approved code repair")
        if row.get("status") != "maintenance_approved":
            row.update(status="maintenance_approved", updated_at=utc_now(), patch_execution_allowed=False,
                       repair_approval={"approval_id": uuid4().hex, "reference": confirmation_reference,
                                        "approved_at": utc_now()})
            _write(path, row)
        update_runtime_status(run_dir, recovery_case=row)
        return row


def _finish_verified_release(run_dir: Path, case: dict) -> None:
    """Input: run Path and source-verified resolved case dict. Output: None. Finish local release while retaining true resource limits and Stop."""
    from wqb.runtime_boundaries import RESOURCE_ACTIONS
    case_id = case['case_id']
    control = read_runtime_control(run_dir)
    if (control.get('recovery_case') or {}).get('case_id') != case_id:
        return
    if case.get('action') == 'research-loop-blocked' and case.get('stage') == 'scout_seed':
        from wqb.research_planning import release_verified_planning_stop
        release_verified_planning_stop(run_dir, case_id, utc_now())
    released = False
    if case.get('stage') in {'triage', 'repair'}:
        from wqb.research_rounds import release_verified_partial_budget_stop
        released = release_verified_partial_budget_stop(run_dir, case_id, utc_now())
    control = read_runtime_control(run_dir)
    state = _read(Path(run_dir) / 'run_state.json')
    boundary_reason = control.get('reason') if control.get('reason') in RESOURCE_ACTIONS else state.get('pause_reason', '')
    if boundary_reason not in RESOURCE_ACTIONS or released and boundary_reason == 'research_simulation_budget_exhausted':
        boundary_reason = ''
    if float(control.get('elapsed_seconds', 0)) >= float(control.get('max_runtime_seconds', 21600)):
        boundary_reason = 'runtime_budget_exhausted'
    update_runtime_status(run_dir, recovery_case=case,
        status='blocked' if boundary_reason else ('paused' if control.get('desired_state') == 'paused' else 'ready'),
        reason=boundary_reason or 'human_approved_repair_verified')


def verify_and_resolve(run_dir: Path, case_id: str, approval_id: str) -> dict:
    """Input: run Path/case ID/approval ID str. Output: resolved dict. Run fixed offline checks, preserve Pause and budgets."""
    path = _case_path(run_dir, case_id)
    row = _read(path)
    if (row.get('status') == 'resolved' and approval_id
            and (row.get('repair_approval') or {}).get('approval_id') == approval_id):
        replay_root = Path(run_dir) / 'runtime'
        replay_lock = acquire_source_run_lock(replay_root, 'maintenance-verification', utc_now())
        if replay_lock.get('status') != 'acquired':
            raise ValueError('workflow worker still owns run; repair release refused')
        try:
            verified = read_current_recovery_case(run_dir)
            if verified.get('case_id') != case_id or verified.get('status') != 'resolved':
                raise ValueError('resolved repair proof is no longer valid')
            _finish_verified_release(run_dir, row)
            return row
        finally:
            release_source_run_lock(replay_root, 'maintenance-verification', utc_now(),
                                    owner_id=str(replay_lock.get('owner_id', '')))
    if row.get("status") != "maintenance_approved" or not approval_id or (row.get("repair_approval") or {}).get("approval_id") != approval_id:
        raise ValueError("matching human repair approval required before verification")
    lock_root = Path(run_dir) / "runtime"
    lock = acquire_source_run_lock(lock_root, "maintenance-verification", utc_now())
    if lock.get("status") != "acquired":
        raise ValueError("workflow worker still owns run; verification refused")
    project = Path(__file__).resolve().parents[1]
    evidence_path = lock_root / "maintenance_verification" / (case_id + ".json")
    evidence = {"case_id": case_id, "approval_id": approval_id, "status": "failed", "created_at": utc_now()}
    try:
        before = _code_digest(project)
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]
        environment = {key: value for key, value in os.environ.items()
                       if not any(word in key.upper() for word in ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "WQB_"))}
        completed = subprocess.run(command, cwd=project, env=environment, capture_output=True,
                                   text=True, timeout=VERIFICATION_TIMEOUT_SECONDS, check=False, shell=False)
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        counts = re.findall(r"^Ran (\d+) tests? in ", output, re.MULTILINE)
        test_count = int(counts[-1]) if counts else 0
        after = _code_digest(project)
        evidence.update(command=command, returncode=completed.returncode, tests_run=test_count,
                        code_digest=before, code_unchanged=before == after, finished_at=utc_now(),
                        test_failures=re.findall(r'^(?:FAIL|ERROR): ([^\n]+)', output, re.MULTILINE)[:20])
        if completed.returncode != 0 or test_count <= 0 or before != after or not re.search(r"^OK(?: \([^\n]*\))?\s*$", output, re.MULTILINE):
            raise ValueError("verification failed, empty, or source changed; repair case remains blocked")
        with json_lock_transition_guard(path.parent / "cases", RECOVERY_LOCK_SECONDS, 0.01, "recovery cases busy"):
            fresh = _read(path)
            if fresh.get("status") != "maintenance_approved" or (fresh.get("repair_approval") or {}).get("approval_id") != approval_id:
                raise ValueError("repair approval changed during verification")
            evidence["status"] = "passed"
            _write(evidence_path, evidence)
            fresh.update(status="resolved", resolved_at=utc_now(), verification_path=str(evidence_path),
                         patch_execution_allowed=False, reason="human_approved_repair_verified")
            _write(path, fresh)
            _finish_verified_release(run_dir, fresh)
            return fresh
    except Exception as error:
        evidence["error_type"] = type(error).__name__
        raise
    finally:
        try:
            if evidence.get("status") != "passed":
                _write(evidence_path, evidence)
        finally:
            release_source_run_lock(lock_root, "maintenance-verification", utc_now(), owner_id=str(lock.get("owner_id", "")))


def main() -> int:
    """Input: maintenance CLI args. Output: JSON/exit int. Record approval or verify, never resume research."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("approve", "verify-and-resolve"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--confirmation-reference", default="")
    parser.add_argument("--approval-id", default="")
    args = parser.parse_args()
    result = (approve_repair(args.run_dir, args.case_id, args.confirmation_reference) if args.action == "approve"
              else verify_and_resolve(args.run_dir, args.case_id, args.approval_id))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
