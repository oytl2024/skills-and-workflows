from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from uuid import uuid4

from wqb.candidate_queue import approve_candidate, queue_approved_candidate
from wqb.research_record import (
    empty_research_record,
    load_research_record,
    record_approval,
    record_candidate_gate,
    record_queue_update,
    write_research_record,
)
from wqb.workflow_events import append_workflow_event, read_workflow_events
from wqb.workflow_stage_adapters import schedule_research_stage
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

    def continue_once(self, now: str) -> dict[str, object]:
        """Input: timestamp. Output: status summary. Advance exactly one legal workflow stage."""
        state = self._active_state()
        if state is None:
            return {"active": False, "status": "none", "next_action": "workflow-start"}
        run_dir = Path(state.run_dir)
        if state.status == "created" and state.current_stage == "objective_selected":
            state = transition_run_state(state, "running", "")
            state = replace(state, current_stage="schedule", next_action="workflow-continue")
            write_run_state(run_dir / STATE_FILENAME, state)
            append_workflow_event(run_dir, "stage_started", {"stage": "schedule"}, now)
            return self._summary(state)
        if state.status == "running" and state.current_stage == "schedule":
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            result = schedule_research_stage(
                self.paths.knowledge_root, run_dir, str(manifest.get("selected_option_id", ""))
            )
            state = replace(state, current_stage="scout_seed", last_completed_stage="schedule")
            write_run_state(run_dir / STATE_FILENAME, state)
            append_workflow_event(
                run_dir, "stage_completed", {"stage": "schedule", "result": result}, now
            )
            return self._summary(state)
        return self._summary(state)

    def request_candidate_approval(
        self, candidates: list[dict[str, object]], now: str
    ) -> dict[str, object]:
        """Input: candidates and timestamp. Output: status summary. Pause run for user candidate approval."""
        state = self._active_state()
        if state is None:
            return {"active": False, "status": "none"}
        run_dir = Path(state.run_dir)
        record = self._load_or_create_research_record(state)
        for candidate in candidates:
            record = record_candidate_gate(
                record, candidate, "ready_for_approval", ["hard checks passed"]
            )
        write_research_record(run_dir / "research_record.json", record)
        (run_dir / "candidate_gate.json").write_text(
            json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if state.status == "created":
            state = transition_run_state(state, "running", "")
        state = transition_run_state(state, "waiting_for_user", "candidate approval required")
        write_run_state(run_dir / STATE_FILENAME, state)
        append_workflow_event(
            run_dir, "user_approval_requested", {"candidate_count": len(candidates)}, now
        )
        return self._summary(state)

    def approve_candidates(
        self, candidate_ids: list[str], approved_at: str, approved_by: str
    ) -> dict[str, object]:
        """Input: candidate ids and approval metadata. Output: queue summary. Approve and queue exact candidates."""
        state = self._active_state()
        if state is None:
            return {"active": False, "queued_count": 0}
        run_dir = Path(state.run_dir)
        candidates = json.loads((run_dir / "candidate_gate.json").read_text(encoding="utf-8"))
        wanted = {str(item) for item in candidate_ids}
        record = self._load_or_create_research_record(state)
        queued_count = 0
        for candidate in candidates:
            if str(candidate.get("candidate_id", "")) not in wanted:
                continue
            approval = approve_candidate(run_dir, candidate, approved_at, approved_by)
            queue_row = queue_approved_candidate(run_dir, approval)
            record = record_approval(record, approval)
            record = record_queue_update(record, queue_row)
            queued_count += 1
        write_research_record(run_dir / "research_record.json", record)
        append_workflow_event(
            run_dir, "candidates_approved", {"queued_count": queued_count}, approved_at
        )
        state = transition_run_state(state, "running", "")
        write_run_state(run_dir / STATE_FILENAME, state)
        return {"run_id": state.run_id, "queued_count": queued_count, "status": state.status}

    def _load_or_create_research_record(self, state: WorkflowRunState):
        """Input: state. Output: ResearchRecord. Load or create the run research record."""
        path = Path(state.run_dir) / "research_record.json"
        if path.exists():
            return load_research_record(path)
        return empty_research_record(state.run_id, state.objective)

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
