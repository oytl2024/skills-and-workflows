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
        """Input: none. Output: active state or none. Load current active run state."""
        active = load_active_run(self.paths.run_root)
        if not active:
            return None
        return load_run_state(Path(active["run_dir"]) / STATE_FILENAME)

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
