from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from wqb.candidate_queue import approve_candidate, queue_approved_candidate, update_candidate_queue_status
from wqb.research_record import (
    empty_research_record,
    load_research_record,
    record_approval,
    record_candidate_gate,
    record_manual_submission_status,
    record_queue_update,
    sync_research_record_to_raw,
    write_research_record,
)
from wqb.workflow_events import append_workflow_event, read_workflow_events
from wqb.workflow_stage_adapters import schedule_research_stage
from wqb.workflow_state import (
    STATE_FILENAME,
    WorkflowRunState,
    WorkflowStageState,
    WorkflowStateDiscovery,
    clear_active_run,
    create_initial_state,
    diagnose_state_consistency,
    discover_active_workflow,
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
        discovery = discover_active_workflow(self.paths.run_root)
        if discovery.state is not None or (
            discovery.run_dir is not None and "run_state_invalid" in discovery.diagnostics
        ):
            raise ValueError("an active workflow run already exists")
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
        state = self._set_stage(
            state,
            "objective_selected",
            "completed",
            created_at,
            current_stage="objective_selected",
            last_completed_stage="objective_selected",
        )
        state = replace(state, next_action="workflow-continue")
        write_run_state(run_dir / STATE_FILENAME, state)
        append_workflow_event(run_dir, "workflow_created", manifest, created_at)
        write_active_run(self.paths.run_root, run_id, run_dir)
        return self._summary(state)

    def status(self) -> dict[str, object]:
        """Input: none. Output: status summary. Read active run state without chat context."""
        discovery = self._active_discovery()
        state = discovery.state
        if state is None:
            return {
                "active": discovery.run_dir is not None,
                "run_id": discovery.run_id,
                "status": "damaged" if discovery.run_dir is not None else "none",
                "next_action": "workflow-start" if discovery.run_dir is None else "",
                "diagnostics": discovery.diagnostics,
                "consistent": not discovery.diagnostics,
            }
        diagnostics = diagnose_state_consistency(state.run_dir)
        state = self._pause_for_diagnostics(
            state, diagnostics, datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )
        summary = self._summary(state, diagnostics)
        summary["active"] = True
        summary["event_count"] = len(read_workflow_events(state.run_dir))
        return summary

    def resume(self, resumed_at: str) -> dict[str, object]:
        """Input: timestamp. Output: status summary. Resume a paused run without repeating completed work."""
        discovery = self._active_discovery()
        state = discovery.state
        if state is None:
            return self._missing_state_summary(discovery)
        diagnostics = diagnose_state_consistency(state.run_dir)
        state = self._pause_for_diagnostics(state, diagnostics, resumed_at)
        if diagnostics:
            return self._summary(state, diagnostics)
        if state.status == "paused":
            state = transition_run_state(state, "running", "")
            state = self._set_stage(state, state.current_stage, "running", resumed_at)
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
        discovery = self._active_discovery()
        state = discovery.state
        if state is None:
            return self._missing_state_summary(discovery)
        diagnostics = diagnose_state_consistency(state.run_dir)
        state = self._pause_for_diagnostics(state, diagnostics, now)
        if diagnostics:
            return self._summary(state, diagnostics)
        run_dir = Path(state.run_dir)
        if state.status == "created" and state.current_stage == "objective_selected":
            state = transition_run_state(state, "running", "")
            state = self._set_stage(
                state,
                "schedule",
                "running",
                now,
                current_stage="schedule",
                last_completed_stage="objective_selected",
            )
            write_run_state(run_dir / STATE_FILENAME, state)
            append_workflow_event(run_dir, "stage_started", {"stage": "schedule"}, now)
            return self._summary(state)
        if state.status == "running" and state.current_stage == "schedule":
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            result = schedule_research_stage(
                self.paths.knowledge_root, run_dir, str(manifest.get("selected_option_id", ""))
            )
            state = self._set_stage(
                state,
                "schedule",
                "completed",
                now,
                evidence_paths=[str(item) for item in result.get("evidence_paths", [])],
                current_stage="scout_seed",
                last_completed_stage="schedule",
            )
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
        if not candidates:
            raise ValueError("at least one candidate is required for approval request")
        for candidate in candidates:
            if str(candidate.get("source_run_id", "")) != state.run_id:
                raise ValueError("candidate source_run_id must match the active workflow run")
            if not self._candidate_has_verified_hard_pass(candidate):
                raise ValueError("candidate must carry verified hard-pass evidence")
        run_dir = Path(state.run_dir)
        record = self._load_or_create_research_record(state)
        for candidate in candidates:
            record = record_candidate_gate(
                record, candidate, "ready_for_approval", ["hard checks passed"]
            )
        write_research_record(run_dir / "research_record.json", record)
        gate_path = run_dir / "candidate_gate.json"
        gate_path.write_text(
            json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if state.status == "created":
            state = transition_run_state(state, "running", "")
        state = transition_run_state(state, "waiting_for_user", "candidate approval required")
        state = self._set_stage(
            state,
            "candidate_gate",
            "completed",
            now,
            evidence_paths=[str(gate_path)],
            current_stage="user_approval",
            last_completed_stage="candidate_gate",
        )
        state = self._set_stage(
            state,
            "user_approval",
            "paused",
            now,
            blocker="candidate approval required",
            current_stage="user_approval",
            last_completed_stage="candidate_gate",
        )
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
        if not candidate_ids:
            raise ValueError("at least one candidate must be selected for approval")
        if state.status != "waiting_for_user":
            summary = self._summary(state)
            summary["queued_count"] = 0
            return summary
        run_dir = Path(state.run_dir)
        candidates = json.loads((run_dir / "candidate_gate.json").read_text(encoding="utf-8"))
        wanted = {str(item) for item in candidate_ids}
        available = {str(candidate.get("candidate_id", "")) for candidate in candidates}
        unknown = sorted(wanted - available)
        if unknown:
            raise ValueError(f"unknown candidate IDs: {', '.join(unknown)}")
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
        if queued_count < 1:
            raise ValueError("at least one exact candidate must be approved")
        state = transition_run_state(state, "running", "")
        state = self._set_stage(
            state,
            "user_approval",
            "completed",
            approved_at,
            evidence_paths=[str(run_dir / "approval.jsonl")],
            current_stage="approved_queue",
            last_completed_stage="user_approval",
        )
        state = self._set_stage(
            state,
            "approved_queue",
            "completed",
            approved_at,
            evidence_paths=[str(run_dir / "approved_candidates.jsonl")],
            current_stage="research_record_sync",
            last_completed_stage="approved_queue",
        )
        write_run_state(run_dir / STATE_FILENAME, state)
        return {"run_id": state.run_id, "queued_count": queued_count, "status": state.status}

    def update_candidate_status(
        self,
        candidate_id: str,
        version: int,
        expression_hash: str,
        status: str,
        updated_at: str,
    ) -> dict[str, object]:
        """Input: exact queue identity, status, timestamp. Output: updated row. Own queue status workflow updates."""
        state = self._active_state()
        if state is None:
            raise ValueError("an active workflow run is required for candidate status updates")
        run_dir = Path(state.run_dir)
        updated = update_candidate_queue_status(
            run_dir, candidate_id, version, expression_hash, status, updated_at
        )
        record = self._load_or_create_research_record(state)
        record = record_queue_update(record, updated)
        if status != "queued":
            record = record_manual_submission_status(record, updated)
        write_research_record(run_dir / "research_record.json", record)
        append_workflow_event(
            run_dir,
            "candidate_status_updated",
            {
                "candidate_id": candidate_id,
                "version": version,
                "expression_hash": expression_hash,
                "status": status,
            },
            updated_at,
        )
        write_run_state(run_dir / STATE_FILENAME, replace(state, updated_at=updated_at))
        return updated

    def sync_research_record(self, now: str) -> dict[str, object]:
        """Input: timestamp. Output: sync summary. Sync the active Research Record to knowledge raw."""
        state = self._active_state()
        if state is None:
            return {"active": False, "synced": False, "raw_path": ""}
        run_dir = Path(state.run_dir)
        record = self._load_or_create_research_record(state)
        write_research_record(run_dir / "research_record.json", record)
        raw_path = sync_research_record_to_raw(record, self.paths.knowledge_root / "raw")
        state = replace(state, research_record_synced=True, updated_at=now)
        write_run_state(run_dir / STATE_FILENAME, state)
        append_workflow_event(
            run_dir,
            "research_record_synced",
            {"raw_path": str(raw_path), "synced": True},
            now,
        )
        summary = self._summary(state)
        summary.update({"synced": True, "raw_path": str(raw_path)})
        return summary

    def _load_or_create_research_record(self, state: WorkflowRunState):
        """Input: state. Output: ResearchRecord. Load or create the run research record."""
        path = Path(state.run_dir) / "research_record.json"
        if path.exists():
            return load_research_record(path)
        return empty_research_record(state.run_id, state.objective)

    def _active_state(self) -> WorkflowRunState | None:
        """Input: none. Output: active state or none. Recover the current resumable run from durable files."""
        return self._active_discovery().state

    def _active_discovery(self) -> WorkflowStateDiscovery:
        """Input: none. Output: discovery result. Durably repair only the active pointer when recovery succeeds."""
        discovery = discover_active_workflow(self.paths.run_root)
        if discovery.state is not None and discovery.run_dir is not None and discovery.recovered:
            write_active_run(self.paths.run_root, discovery.state.run_id, discovery.run_dir)
            return WorkflowStateDiscovery(
                discovery.state,
                discovery.run_dir,
                discovery.run_id,
                [],
                False,
            )
        return discovery

    def _set_stage(
        self,
        state: WorkflowRunState,
        stage_name: str,
        status: str,
        now: str,
        evidence_paths: list[str] | None = None,
        blocker: str = "",
        current_stage: str | None = None,
        last_completed_stage: str | None = None,
    ) -> WorkflowRunState:
        """Input: state, stage transition, evidence, timestamp. Output: updated state. Keep stage metadata coherent."""
        stages = dict(state.stages)
        previous = stages[stage_name]
        started_at = previous.started_at
        completed_at = previous.completed_at
        if status in {"running", "paused"} and not started_at:
            started_at = now
        if status == "completed":
            started_at = started_at or now
            completed_at = now
        stages[stage_name] = WorkflowStageState(
            name=stage_name,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            evidence_paths=list(evidence_paths) if evidence_paths is not None else list(previous.evidence_paths),
            blocker=blocker,
        )
        return replace(
            state,
            stages=stages,
            current_stage=current_stage if current_stage is not None else state.current_stage,
            last_completed_stage=(
                last_completed_stage if last_completed_stage is not None else state.last_completed_stage
            ),
            updated_at=now,
        )

    def _pause_for_diagnostics(
        self, state: WorkflowRunState, diagnostics: list[str], now: str
    ) -> WorkflowRunState:
        """Input: state, diagnostics, timestamp. Output: safe state. Pause running work on contradictions."""
        if not diagnostics or state.status != "running":
            return state
        reason = "workflow consistency diagnostics: " + ", ".join(diagnostics)
        state = transition_run_state(state, "paused", reason)
        state = self._set_stage(
            state,
            state.current_stage,
            "paused",
            now,
            blocker=reason,
        )
        write_run_state(Path(state.run_dir) / STATE_FILENAME, state)
        append_workflow_event(
            state.run_dir,
            "workflow_paused",
            {"reason": reason, "diagnostics": diagnostics},
            now,
        )
        return state

    def _candidate_has_verified_hard_pass(self, candidate: dict[str, object]) -> bool:
        """Input: candidate row. Output: bool. Accept explicit verified hard-pass evidence only."""
        if candidate.get("hard_pass") is True:
            return True
        for field_name in ("check_result", "benchmark_result", "hard_check_result"):
            evidence = candidate.get(field_name)
            if isinstance(evidence, dict) and evidence.get("hard_pass") is True:
                return True
        return False

    def _summary(
        self, state: WorkflowRunState, diagnostics: list[str] | None = None
    ) -> dict[str, object]:
        """Input: state. Output: summary dict. Present stable Orchestrator status."""
        issues = list(diagnostics or [])
        return {
            "run_id": state.run_id,
            "run_dir": state.run_dir,
            "objective": state.objective,
            "status": state.status,
            "current_stage": state.current_stage,
            "next_action": state.next_action,
            "waiting_for_user": state.waiting_for_user,
            "diagnostics": issues,
            "consistent": not issues,
        }

    def _missing_state_summary(self, discovery: WorkflowStateDiscovery) -> dict[str, object]:
        """Input: discovery without state. Output: status summary. Expose damaged active state instead of hiding it."""
        return {
            "active": discovery.run_dir is not None,
            "run_id": discovery.run_id,
            "status": "damaged" if discovery.run_dir is not None else "none",
            "next_action": "workflow-start" if discovery.run_dir is None else "",
            "diagnostics": discovery.diagnostics,
            "consistent": not discovery.diagnostics,
        }
