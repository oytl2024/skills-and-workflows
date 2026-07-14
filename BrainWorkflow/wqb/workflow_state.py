from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
from typing import Any

from wqb.workflow_contract import LEGAL_RUN_TRANSITIONS, RUN_STATUSES, STAGE_NAMES, STAGE_STATUSES


STATE_FILENAME = "run_state.json"
STATE_CHECKPOINT_FILENAME = "run_state_checkpoint.json"
ACTIVE_RUN_FILENAME = "active_run.json"
TERMINAL_RUN_STATUSES = {"completed", "completed_with_warnings", "aborted"}
STAGES_REQUIRING_EVIDENCE = {
    "schedule",
    "scout_seed",
    "batch_generation",
    "backtest",
    "triage",
    "repair",
    "candidate_gate",
    "user_approval",
    "approved_queue",
    "research_record_sync",
}


class WorkflowStateError(ValueError):
    """Input: invalid state action. Output: exception. Signal illegal workflow state use."""


@dataclass(frozen=True)
class WorkflowStageState:
    name: str
    status: str = "not_started"
    started_at: str = ""
    completed_at: str = ""
    evidence_paths: list[str] = field(default_factory=list)
    blocker: str = ""


@dataclass(frozen=True)
class WorkflowRunState:
    run_id: str
    run_dir: str
    objective: str
    status: str
    current_stage: str
    last_completed_stage: str
    next_action: str
    pause_reason: str
    waiting_for_user: bool
    created_at: str
    updated_at: str
    budget_used: int
    research_record_synced: bool
    stages: dict[str, WorkflowStageState]


@dataclass(frozen=True)
class WorkflowStateDiscovery:
    state: WorkflowRunState | None
    run_dir: Path | None
    run_id: str
    diagnostics: list[str]
    recovered: bool = False


def create_initial_state(run_id: str, run_dir: str | Path, objective: str, created_at: str) -> WorkflowRunState:
    """Input: run id, run dir, objective, timestamp. Output: initial state. Create a formal run state."""
    stages = {name: WorkflowStageState(name=name) for name in STAGE_NAMES}
    return WorkflowRunState(
        run_id=str(run_id),
        run_dir=str(run_dir),
        objective=str(objective),
        status="created",
        current_stage="objective_selected",
        last_completed_stage="",
        next_action="workflow-start",
        pause_reason="",
        waiting_for_user=False,
        created_at=str(created_at),
        updated_at=str(created_at),
        budget_used=0,
        research_record_synced=False,
        stages=stages,
    )


def transition_run_state(state: WorkflowRunState, new_status: str, reason: str = "") -> WorkflowRunState:
    """Input: state and target status. Output: new state. Enforce legal run status transitions."""
    if new_status not in RUN_STATUSES:
        raise WorkflowStateError(f"unsupported run status: {new_status}")
    allowed = LEGAL_RUN_TRANSITIONS[state.status]
    if new_status not in allowed:
        raise WorkflowStateError(f"illegal run status transition: {state.status} -> {new_status}")
    return replace(
        state,
        status=new_status,
        pause_reason=reason if new_status in {"paused", "failed", "aborted"} else "",
        waiting_for_user=(new_status == "waiting_for_user"),
        next_action=_next_action_for_status(new_status),
    )


def _next_action_for_status(status: str) -> str:
    """Input: run status. Output: next action name. Map status to safe user command."""
    return {
        "created": "workflow-start",
        "running": "workflow-continue",
        "waiting_for_user": "workflow-approve-candidates",
        "paused": "workflow-resume",
        "failed": "workflow-abort",
        "completed": "",
        "completed_with_warnings": "",
        "aborted": "",
    }[status]


def _state_to_dict(state: WorkflowRunState) -> dict[str, Any]:
    """Input: state. Output: JSON-safe dict. Convert nested dataclasses."""
    row = asdict(state)
    row["stages"] = {name: asdict(stage) for name, stage in state.stages.items()}
    return row


def _state_from_dict(row: dict[str, Any]) -> WorkflowRunState:
    """Input: JSON row. Output: WorkflowRunState. Rebuild nested dataclasses."""
    if not isinstance(row, dict):
        raise WorkflowStateError("workflow state must be a JSON object")
    status = str(row["status"])
    current_stage = str(row.get("current_stage", "objective_selected"))
    last_completed_stage = str(row.get("last_completed_stage", ""))
    if status not in RUN_STATUSES:
        raise WorkflowStateError(f"unsupported run status: {status}")
    if current_stage not in STAGE_NAMES:
        raise WorkflowStateError(f"unsupported current stage: {current_stage}")
    if last_completed_stage and last_completed_stage not in STAGE_NAMES:
        raise WorkflowStateError(f"unsupported last completed stage: {last_completed_stage}")
    raw_stages = row.get("stages", {})
    if not isinstance(raw_stages, dict):
        raise WorkflowStateError("workflow stages must be a JSON object")
    stages: dict[str, WorkflowStageState] = {}
    for name, stage_row in raw_stages.items():
        if name not in STAGE_NAMES or not isinstance(stage_row, dict):
            raise WorkflowStateError(f"unsupported stage name: {name}")
        stored_name = str(stage_row.get("name", name))
        stage_status = str(stage_row.get("status", "not_started"))
        if stored_name != name:
            raise WorkflowStateError(f"stage name mismatch: {name} != {stored_name}")
        if stage_status not in STAGE_STATUSES:
            raise WorkflowStateError(f"unsupported stage status: {stage_status}")
        stages[name] = WorkflowStageState(
            name=name,
            status=stage_status,
            started_at=str(stage_row.get("started_at", "")),
            completed_at=str(stage_row.get("completed_at", "")),
            evidence_paths=[str(item) for item in stage_row.get("evidence_paths", [])],
            blocker=str(stage_row.get("blocker", "")),
        )
    for name in STAGE_NAMES:
        stages.setdefault(name, WorkflowStageState(name=name))
    return WorkflowRunState(
        run_id=str(row["run_id"]),
        run_dir=str(row["run_dir"]),
        objective=str(row.get("objective", "")),
        status=status,
        current_stage=current_stage,
        last_completed_stage=last_completed_stage,
        next_action=str(row.get("next_action", "")),
        pause_reason=str(row.get("pause_reason", "")),
        waiting_for_user=bool(row.get("waiting_for_user", False)),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
        budget_used=int(row.get("budget_used", 0)),
        research_record_synced=bool(row.get("research_record_synced", False)),
        stages=stages,
    )


def write_run_state(path: str | Path, state: WorkflowRunState) -> Path:
    """Input: path and state. Output: written path. Atomically write checkpoint then official run state."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_state_to_dict(state), ensure_ascii=False, indent=2, sort_keys=True)
    _write_state_payload(target.parent / STATE_CHECKPOINT_FILENAME, payload)
    _write_state_payload(target, payload)
    return target


def _write_state_payload(target: Path, payload: str) -> None:
    """Input: target Path and JSON payload. Output: none. Atomically persist one durable state artifact."""
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(payload, encoding="utf-8")
    temp.replace(target)


def load_run_state(path: str | Path) -> WorkflowRunState:
    """Input: path. Output: WorkflowRunState. Load official run state from JSON."""
    return _state_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def write_active_run(run_root: str | Path, run_id: str, run_dir: str | Path) -> Path:
    """Input: run root, run id, run dir. Output: pointer path. Write active run index."""
    root = Path(run_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / ACTIVE_RUN_FILENAME
    path.write_text(json.dumps({"run_id": str(run_id), "run_dir": str(run_dir)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_active_run(run_root: str | Path) -> dict[str, str]:
    """Input: run root. Output: active run pointer. Load active run index or empty dict."""
    path = Path(run_root) / ACTIVE_RUN_FILENAME
    if not path.exists():
        return {}
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise WorkflowStateError("active run pointer must be a JSON object")
    run_id = row.get("run_id")
    run_dir = row.get("run_dir")
    if not isinstance(run_id, str) or not run_id or not isinstance(run_dir, str) or not run_dir:
        raise WorkflowStateError("active run pointer requires non-empty run_id and run_dir strings")
    return {"run_id": run_id, "run_dir": run_dir}


def clear_active_run(run_root: str | Path) -> None:
    """Input: run root. Output: none. Remove active run pointer when a workflow ends."""
    path = Path(run_root) / ACTIVE_RUN_FILENAME
    if path.exists():
        path.unlink()


def diagnose_state_consistency(run_dir: str | Path) -> list[str]:
    """Input: run dir. Output: issue codes. Detect contradictions between state and artifacts."""
    root = Path(run_dir)
    issues: list[str] = []
    approval_path = root / "approval.jsonl"
    queue_path = root / "approved_candidates.jsonl"
    gate_path = root / "candidate_gate.json"
    approvals, approval_issues = _read_jsonl_rows(approval_path)
    queued_rows, queue_issues = _read_jsonl_rows(queue_path)
    issues.extend(approval_issues)
    issues.extend(queue_issues)
    if queue_path.exists() and not approval_path.exists():
        issues.append("candidate_queue_without_approval")
    elif queue_path.exists():
        approval_identities = {_candidate_identity(row) for row in approvals}
        for queued in queued_rows:
            if _candidate_identity(queued) not in approval_identities:
                issues.append(
                    "candidate_queue_approval_identity_mismatch:"
                    f"{queued.get('candidate_id', '')}:{queued.get('version', '')}:"
                    f"{queued.get('expression_hash', '')}"
                )

    gate_rows: list[dict[str, Any]] | None = None
    if gate_path.exists():
        gate_rows = _read_candidate_gate(gate_path, issues)
    if gate_rows is not None:
        gate_identities = {_candidate_identity(row) for row in gate_rows}
        for approval in approvals:
            if _candidate_identity(approval) not in gate_identities:
                issues.append(
                    "approval_candidate_gate_identity_mismatch:"
                    f"{approval.get('candidate_id', '')}:{approval.get('version', '')}:"
                    f"{approval.get('expression_hash', '')}"
                )
        for queued in queued_rows:
            if _candidate_identity(queued) not in gate_identities:
                issues.append(
                    "candidate_queue_gate_identity_mismatch:"
                    f"{queued.get('candidate_id', '')}:{queued.get('version', '')}:"
                    f"{queued.get('expression_hash', '')}"
                )

    research_record_path = root / "research_record.json"
    research_record = None
    if research_record_path.exists():
        research_record = _read_json_object(research_record_path, issues)

    state = None
    state_path = root / STATE_FILENAME
    if state_path.exists():
        try:
            state = load_run_state(state_path)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            issues.append(f"malformed_json:{STATE_FILENAME}")
    if state is not None:
        if state.status in {"completed", "completed_with_warnings"} and research_record is None:
            issues.append("completed_without_research_record")
        if research_record is not None and str(research_record.get("run_id", "")) != state.run_id:
            issues.append(
                "research_record_run_id_mismatch:"
                f"{research_record.get('run_id', '')}"
            )
        candidate_artifacts = (
            (gate_path.name, gate_rows or []),
            (approval_path.name, approvals),
            (queue_path.name, queued_rows),
        )
        for artifact_name, rows in candidate_artifacts:
            for row in rows:
                source_run_id = str(row.get("source_run_id", ""))
                if source_run_id != state.run_id:
                    issues.append(
                        "candidate_source_run_id_mismatch:"
                        f"{artifact_name}:{row.get('candidate_id', '')}:{source_run_id}"
                    )
        for stage in state.stages.values():
            if stage.status != "completed":
                continue
            if stage.name in STAGES_REQUIRING_EVIDENCE and not stage.evidence_paths:
                issues.append(f"completed_stage_without_evidence:{stage.name}")
            for evidence_path in stage.evidence_paths:
                evidence = Path(evidence_path)
                if not evidence.is_absolute():
                    evidence = root / evidence
                if not evidence.exists():
                    issues.append(f"missing_stage_evidence:{stage.name}:{evidence_path}")
        from wqb.workflow_events import read_workflow_events

        events = read_workflow_events(root)
        if events and events[-1].event_type == "workflow_aborted" and state.status != "aborted":
            issues.append("state_event_status_conflict")
    return issues


def _read_jsonl_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Input: JSONL path. Output: rows and diagnostics. Skip malformed rows without crashing status."""
    if not path.exists():
        return [], []
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            issues.append(f"malformed_jsonl:{path.name}:{line_number}")
            continue
        if not isinstance(row, dict):
            issues.append(f"malformed_jsonl:{path.name}:{line_number}")
            continue
        rows.append(row)
    return rows, issues


def _read_candidate_gate(path: Path, issues: list[str]) -> list[dict[str, Any]] | None:
    """Input: gate path and issues. Output: candidate rows or none. Diagnose malformed gate data."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        issues.append(f"malformed_json:{path.name}")
        return None
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        issues.append(f"malformed_json:{path.name}")
        return None
    return payload


def _read_json_object(path: Path, issues: list[str]) -> dict[str, Any] | None:
    """Input: JSON path and issues. Output: object or none. Diagnose malformed object artifacts."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        issues.append(f"malformed_json:{path.name}")
        return None
    if not isinstance(payload, dict):
        issues.append(f"malformed_json:{path.name}")
        return None
    return payload


def _candidate_identity(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Input: approval or queue row. Output: exact identity tuple. Normalize identity fields for comparison."""
    return (
        str(row.get("candidate_id", "")),
        str(row.get("platform_alpha_id", "")),
        str(row.get("version", "")),
        str(row.get("expression_hash", "")),
        str(row.get("source_run_id", "")),
    )


def discover_active_workflow(run_root: str | Path) -> WorkflowStateDiscovery:
    """Input: run root. Output: read-only discovery. Recover active state without writing pointer or state files."""
    root = Path(run_root)
    pointer_path = root / ACTIVE_RUN_FILENAME
    pointer: dict[str, str] = {}
    pointer_issue = ""
    if pointer_path.exists():
        try:
            pointer = load_active_run(root)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pointer_issue = "active_run_invalid"
    else:
        pointer_issue = "active_run_missing"

    pointer_dir = Path(pointer.get("run_dir", "")) if pointer.get("run_dir") else None
    pointer_state_issue = ""
    if pointer_dir is not None:
        pointer_directory_issue = _active_pointer_directory_issue(
            root, pointer.get("run_id", ""), pointer_dir
        )
        if pointer_directory_issue:
            pointer_issue = pointer_directory_issue
        else:
            state, issue, _ = _load_discovery_state(root, pointer_dir)
            if issue and issue != "run_state_recovered_from_checkpoint":
                pointer_state_issue = issue
            elif state is not None and state.status in TERMINAL_RUN_STATUSES:
                pointer_issue = "active_run_terminal"

    if pointer_state_issue:
        return WorkflowStateDiscovery(
            None, pointer_dir, pointer.get("run_id", ""), [pointer_state_issue]
        )

    candidates: list[tuple[WorkflowRunState, Path, str, bool]] = []
    invalid_dirs: list[tuple[Path, str]] = []
    if root.exists():
        for run_dir in root.iterdir():
            if not run_dir.is_dir():
                continue
            state, issue, recovered_from_checkpoint = _load_discovery_state(root, run_dir)
            if issue and issue not in {
                "run_state_missing", "run_state_recovered_from_checkpoint"
            }:
                invalid_dirs.append((run_dir, issue))
            if state is not None and state.status not in TERMINAL_RUN_STATUSES:
                candidates.append((state, run_dir, issue, recovered_from_checkpoint))
    if len(candidates) > 1:
        return WorkflowStateDiscovery(None, None, "", ["multiple_active_runs"])
    if candidates:
        state, run_dir, state_issue, recovered_from_checkpoint = max(
            candidates,
            key=lambda candidate: (
                candidate[0].updated_at or candidate[0].created_at,
                candidate[0].created_at,
                candidate[1].name,
            ),
        )
        pointer_matches_state = (
            not pointer_issue
            and pointer_dir is not None
            and pointer_dir.resolve() == run_dir.resolve()
            and pointer.get("run_id", "") == state.run_id
        )
        diagnostics: list[str] = []
        if not pointer_matches_state and pointer_issue:
            diagnostics.append(pointer_issue)
        if state_issue:
            diagnostics.append(state_issue)
        return WorkflowStateDiscovery(
            state,
            run_dir,
            state.run_id,
            diagnostics,
            recovered_from_checkpoint or not pointer_matches_state,
        )
    if invalid_dirs and pointer_issue == "active_run_missing":
        run_dir, issue = max(invalid_dirs, key=lambda item: item[0].name)
        return WorkflowStateDiscovery(None, run_dir, run_dir.name, [issue])
    return WorkflowStateDiscovery(
        None, pointer_dir, pointer.get("run_id", ""), [pointer_issue] if pointer_issue else []
    )


def _active_pointer_directory_issue(root: Path, run_id: str, run_dir: Path) -> str:
    """Input: run root, pointer id and directory. Output: issue code. Validate pointer containment and identity."""
    root_path = root.resolve()
    run_path = run_dir.resolve()
    try:
        run_path.relative_to(root_path)
    except ValueError:
        return "active_run_outside_run_root"
    if run_path != (root_path / run_id).resolve():
        return "active_run_directory_mismatch"
    return ""


def _load_discovery_state(root: Path, run_dir: Path) -> tuple[WorkflowRunState | None, str, bool]:
    """Input: run directory. Output: state and issue code. Load one state for read-only discovery."""
    root_path = root.resolve()
    run_path = run_dir.resolve()
    try:
        run_path.relative_to(root_path)
    except ValueError:
        return None, "run_directory_outside_run_root", False
    path = run_dir / STATE_FILENAME
    if not path.exists():
        return None, "run_state_missing", False
    recovered_from_checkpoint = False
    try:
        state = load_run_state(path)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        try:
            state = load_run_state(run_dir / STATE_CHECKPOINT_FILENAME)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None, "run_state_invalid", False
        recovered_from_checkpoint = True
    if state.run_id != run_dir.name:
        return None, "run_state_run_id_mismatch", False
    if Path(state.run_dir).resolve() != run_path:
        return None, "run_state_run_dir_mismatch", False
    if recovered_from_checkpoint:
        return state, "run_state_recovered_from_checkpoint", True
    return state, "", False
