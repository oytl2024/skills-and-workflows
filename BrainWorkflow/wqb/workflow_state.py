from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
from typing import Any

from wqb.workflow_contract import LEGAL_RUN_TRANSITIONS, RUN_STATUSES, STAGE_NAMES, STAGE_STATUSES


STATE_FILENAME = "run_state.json"
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
    """Input: path and state. Output: written path. Atomically write official run state."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(_state_to_dict(state), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(target)
    return target


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
    return {"run_id": str(row.get("run_id", "")), "run_dir": str(row.get("run_dir", ""))}


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
    if queue_path.exists() and not approval_path.exists():
        issues.append("candidate_queue_without_approval")
    elif queue_path.exists():
        approvals = _read_jsonl_rows(approval_path)
        approval_identities = {_candidate_identity(row) for row in approvals}
        for queued in _read_jsonl_rows(queue_path):
            if _candidate_identity(queued) not in approval_identities:
                issues.append(
                    "candidate_queue_approval_identity_mismatch:"
                    f"{queued.get('candidate_id', '')}:{queued.get('version', '')}:"
                    f"{queued.get('expression_hash', '')}"
                )
    if (root / STATE_FILENAME).exists():
        state = load_run_state(root / STATE_FILENAME)
        if state.status == "completed" and not (root / "research_record.json").exists():
            issues.append("completed_without_research_record")
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


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: object rows. Read artifact identities for consistency diagnostics."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


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
    if pointer_dir is not None:
        state, issue = _load_discovery_state(pointer_dir)
        if issue == "run_state_invalid":
            return WorkflowStateDiscovery(None, pointer_dir, pointer.get("run_id", ""), [issue])
        if state is not None and state.status not in TERMINAL_RUN_STATUSES and state.run_id == pointer.get("run_id"):
            return WorkflowStateDiscovery(state, pointer_dir, state.run_id, [])
        pointer_issue = "active_run_stale"

    candidates: list[tuple[WorkflowRunState, Path]] = []
    invalid_dirs: list[Path] = []
    if root.exists():
        for run_dir in root.iterdir():
            if not run_dir.is_dir():
                continue
            state, issue = _load_discovery_state(run_dir)
            if issue == "run_state_invalid":
                invalid_dirs.append(run_dir)
            if state is not None and state.status not in TERMINAL_RUN_STATUSES:
                candidates.append((state, run_dir))
    if candidates:
        state, run_dir = max(
            candidates,
            key=lambda candidate: (
                candidate[0].updated_at or candidate[0].created_at,
                candidate[0].created_at,
                candidate[1].name,
            ),
        )
        return WorkflowStateDiscovery(state, run_dir, state.run_id, [pointer_issue] if pointer_issue else [], True)
    if invalid_dirs and pointer_issue == "active_run_missing":
        run_dir = max(invalid_dirs, key=lambda path: path.name)
        return WorkflowStateDiscovery(None, run_dir, run_dir.name, ["run_state_invalid"])
    return WorkflowStateDiscovery(None, pointer_dir, pointer.get("run_id", ""), [pointer_issue] if pointer_issue else [])


def _load_discovery_state(run_dir: Path) -> tuple[WorkflowRunState | None, str]:
    """Input: run directory. Output: state and issue code. Load one state for read-only discovery."""
    path = run_dir / STATE_FILENAME
    if not path.exists():
        return None, "run_state_missing"
    try:
        return load_run_state(path), ""
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None, "run_state_invalid"
