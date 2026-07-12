from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from uuid import uuid4

from wqb.workflow_events import append_workflow_event, read_workflow_events
from wqb.workflow_state import (
    STATE_FILENAME,
    WorkflowRunState,
    clear_active_run,
    create_initial_state,
    load_active_run,
    load_run_state,
    transition_run_state,
    write_active_run,
    write_run_state,
)


@dataclass(frozen=True)
class OrchestratorPaths:
    project_root: Path
    workflow_root: Path
    knowledge_root: Path
    run_root: Path


class WorkflowOrchestrator:
    def __init__(self, paths: OrchestratorPaths) -> None:
        """Input: OrchestratorPaths. Output: instance. Create a workflow controller over durable files."""
        self.paths = paths

    def start(self, objective: str, selected_option_id: str, created_at: str) -> dict[str, object]:
        """Input: objective, option id, timestamp. Output: start summary. Create a formal workflow run."""
        self.paths.run_root.mkdir(parents=True, exist_ok=True)
        run_id = f"{created_at.replace(':', '').replace('-', '').replace('+', 'plus')}-{uuid4().hex[:8]}"
        run_dir = self.paths.run_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        manifest = {
            "run_id": run_id,
            "objective": str(objective),
            "selected_option_id": str(selected_option_id),
            "created_at": str(created_at),
            "knowledge_root": str(self.paths.knowledge_root),
        }
        (run_dir / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        state = create_initial_state(run_id, run_dir, objective, created_at)
        write_run_state(run_dir / STATE_FILENAME, state)
        append_workflow_event(run_dir, "workflow_created", manifest, created_at)
        write_active_run(self.paths.run_root, run_id, run_dir)
        return self._summary(state)

    def status(self) -> dict[str, object]:
        """Input: none. Output: status summary. Read active run state without chat context."""
        state = self._active_state()
        if state is None:
            return {"active": False, "run_id": "", "status": "none", "next_action": "workflow-start"}
        summary = self._summary(state)
        summary["active"] = True
        summary["event_count"] = len(read_workflow_events(state.run_dir))
        return summary

    def resume(self, resumed_at: str) -> dict[str, object]:
        """Input: timestamp. Output: status summary. Resume a paused run without repeating completed work."""
        state = self._active_state()
        if state is None:
            return {"active": False, "status": "none", "next_action": "workflow-start"}
        if state.status == "paused":
            state = transition_run_state(state, "running", "")
            write_run_state(Path(state.run_dir) / STATE_FILENAME, state)
            append_workflow_event(state.run_dir, "workflow_resumed", {"run_id": state.run_id}, resumed_at)
        return self._summary(state)

    def abort(self, reason: str, aborted_at: str) -> dict[str, object]:
        """Input: reason and timestamp. Output: status summary. Abort active run and release pointer."""
        state = self._active_state()
        if state is None:
            return {"active": False, "status": "none"}
        if state.status != "aborted":
            state = transition_run_state(state, "aborted", reason)
            write_run_state(Path(state.run_dir) / STATE_FILENAME, state)
            append_workflow_event(
                state.run_dir,
                "workflow_aborted",
                {"run_id": state.run_id, "reason": reason},
                aborted_at,
            )
        clear_active_run(self.paths.run_root)
        return self._summary(state)

    def _active_state(self) -> WorkflowRunState | None:
        """Input: none. Output: active state or none. Recover the current resumable run from durable files."""
        try:
            active = load_active_run(self.paths.run_root)
        except (OSError, ValueError, TypeError):
            active = {}
        run_dir = Path(active.get("run_dir", "")) if active.get("run_dir") else None
        state = self._load_resumable_state(run_dir) if run_dir else None
        if state is not None and state.run_id == active.get("run_id"):
            return state

        recovered = self._find_resumable_state()
        if recovered is None:
            return None
        state, run_dir = recovered
        write_active_run(self.paths.run_root, state.run_id, run_dir)
        return state

    def _find_resumable_state(self) -> tuple[WorkflowRunState, Path] | None:
        """Input: none. Output: state and directory or none. Select the newest durable resumable run."""
        if not self.paths.run_root.exists():
            return None
        candidates: list[tuple[WorkflowRunState, Path]] = []
        for run_dir in self.paths.run_root.iterdir():
            if not run_dir.is_dir():
                continue
            state = self._load_resumable_state(run_dir)
            if state is not None:
                candidates.append((state, run_dir))
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda candidate: (
                candidate[0].updated_at or candidate[0].created_at,
                candidate[0].created_at,
                candidate[1].name,
            ),
        )

    def _load_resumable_state(self, run_dir: Path) -> WorkflowRunState | None:
        """Input: run directory. Output: state or none. Load a valid non-terminal durable run state."""
        try:
            state = load_run_state(run_dir / STATE_FILENAME)
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if state.status in {"completed", "completed_with_warnings", "failed", "aborted"}:
            return None
        return state

    def _summary(self, state: WorkflowRunState) -> dict[str, object]:
        """Input: state. Output: summary dict. Present stable Orchestrator status."""
        return {
            "run_id": state.run_id,
            "run_dir": state.run_dir,
            "objective": state.objective,
            "status": state.status,
            "current_stage": state.current_stage,
            "next_action": state.next_action,
            "waiting_for_user": state.waiting_for_user,
        }
