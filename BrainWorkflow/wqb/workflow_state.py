from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
from typing import Any

from wqb.workflow_contract import LEGAL_RUN_TRANSITIONS, RUN_STATUSES, STAGE_NAMES


STATE_FILENAME = "run_state.json"
ACTIVE_RUN_FILENAME = "active_run.json"


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
    stages = {
        name: WorkflowStageState(**dict(stage_row))
        for name, stage_row in dict(row.get("stages", {})).items()
        if name in STAGE_NAMES and isinstance(stage_row, dict)
    }
    for name in STAGE_NAMES:
        stages.setdefault(name, WorkflowStageState(name=name))
    return WorkflowRunState(
        run_id=str(row["run_id"]),
        run_dir=str(row["run_dir"]),
        objective=str(row.get("objective", "")),
        status=str(row["status"]),
        current_stage=str(row.get("current_stage", "objective_selected")),
        last_completed_stage=str(row.get("last_completed_stage", "")),
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
    if (root / "approved_candidates.jsonl").exists() and not (root / "approval.jsonl").exists():
        issues.append("candidate_queue_without_approval")
    if (root / STATE_FILENAME).exists():
        state = load_run_state(root / STATE_FILENAME)
        if state.status == "completed" and not (root / "research_record.json").exists():
            issues.append("completed_without_research_record")
    return issues
