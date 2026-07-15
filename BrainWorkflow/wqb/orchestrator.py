from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
from uuid import uuid4

from wqb.candidate_queue import (
    approve_candidate,
    claim_api_submission_slot,
    invalidate_candidate_queue_entry,
    load_approved_queue,
    queue_approved_candidate,
    release_api_submission_claim_slot,
    update_candidate_queue_status,
    validate_candidate_approval,
)
from wqb.lockfile import exclusive_json_lock
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
from wqb.workflow_stage_adapters import POST_SCHEDULE_STAGES, advance_post_schedule_stage, schedule_research_stage
from wqb.workflow_state import (
    STATE_FILENAME,
    WorkflowRunState,
    WorkflowStageState,
    WorkflowStateDiscovery,
    blocking_terminal_issues,
    clear_active_run,
    create_initial_state,
    diagnose_state_consistency,
    discover_active_workflow,
    load_run_state,
    transition_run_state,
    write_active_run,
    write_run_state,
)


CANDIDATE_GATE_PREREQUISITES = (
    "objective_selected",
    "schedule",
    "scout_seed",
    "batch_generation",
    "backtest",
    "triage",
    "repair",
)
WORKFLOW_START_LOCK_FILENAME = "workflow_start.lock"
WORKFLOW_START_LOCK_TIMEOUT_SECONDS = 5.0
WORKFLOW_START_LOCK_SLEEP_SECONDS = 0.05
WORKFLOW_START_LOCK_STALE_SECONDS = 300.0
WORKFLOW_MUTATION_LOCK_FILENAME = "workflow_mutation.lock"
WORKFLOW_MUTATION_LOCK_TIMEOUT_SECONDS = 5.0
WORKFLOW_MUTATION_LOCK_SLEEP_SECONDS = 0.05
WORKFLOW_MUTATION_LOCK_STALE_SECONDS = 300.0


@contextmanager
def _workflow_start_lock(run_root: Path):
    """Input: run root Path. Output: context manager. Serialize workflow creation under run_root."""
    with exclusive_json_lock(
        run_root / WORKFLOW_START_LOCK_FILENAME,
        WORKFLOW_START_LOCK_TIMEOUT_SECONDS,
        WORKFLOW_START_LOCK_SLEEP_SECONDS,
        WORKFLOW_START_LOCK_STALE_SECONDS,
        "workflow start lock is busy",
    ):
        yield


@contextmanager
def _workflow_mutation_lock(run_root: Path):
    """Input: run root Path. Output: context manager. Serialize workflow state mutations."""
    with exclusive_json_lock(
        run_root / WORKFLOW_MUTATION_LOCK_FILENAME,
        WORKFLOW_MUTATION_LOCK_TIMEOUT_SECONDS,
        WORKFLOW_MUTATION_LOCK_SLEEP_SECONDS,
        WORKFLOW_MUTATION_LOCK_STALE_SECONDS,
        "workflow mutation lock is busy",
    ):
        yield


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
        with _workflow_mutation_lock(self.paths.run_root):
            return self._start_unlocked(objective, selected_option_id, created_at)

    def _start_unlocked(self, objective: str, selected_option_id: str, created_at: str) -> dict[str, object]:
        """Input: objective, option id, timestamp. Output: start summary. Create run under mutation lock."""
        self.paths.run_root.mkdir(parents=True, exist_ok=True)
        discovery = self._active_discovery()
        if not self._start_is_allowed(discovery):
            raise ValueError("an active workflow run already exists")
        run_id = self._new_run_id(created_at)
        resolved_run_root = self.paths.run_root.resolve()
        run_dir = resolved_run_root / run_id
        if Path(run_id).name != run_id or run_dir.resolve().parent != resolved_run_root:
            raise ValueError("workflow run directory must be an immediate child of run_root")
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
        with _workflow_mutation_lock(self.paths.run_root):
            return self._status_unlocked()

    def _status_unlocked(self) -> dict[str, object]:
        """Input: none. Output: status summary. Read and repair status under mutation lock."""
        discovery = self._active_discovery()
        state = discovery.state
        if state is None:
            damaged = self._discovery_is_damaged(discovery)
            return {
                "active": discovery.run_dir is not None or damaged,
                "run_id": discovery.run_id,
                "status": "damaged" if damaged else "none",
                "next_action": "" if damaged else "workflow-start",
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
        with _workflow_mutation_lock(self.paths.run_root):
            return self._resume_unlocked(resumed_at)

    def _resume_unlocked(self, resumed_at: str) -> dict[str, object]:
        """Input: timestamp. Output: status summary. Resume while caller holds mutation lock."""
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
        with _workflow_mutation_lock(self.paths.run_root):
            return self._abort_unlocked(reason, aborted_at)

    def _abort_unlocked(self, reason: str, aborted_at: str) -> dict[str, object]:
        """Input: reason and timestamp. Output: status summary. Abort while caller holds mutation lock."""
        state = self._active_state()
        if state is None:
            return {"active": False, "status": "none"}
        warnings: list[str] = []
        raw_path = ""
        try:
            record = self._load_or_create_research_record(state)
            write_research_record(Path(state.run_dir) / "research_record.json", record)
            synced_path = sync_research_record_to_raw(record, self.paths.knowledge_root / "raw")
            raw_path = str(synced_path)
            state = replace(state, research_record_synced=True, updated_at=aborted_at)
            append_workflow_event(
                state.run_dir,
                "abort_research_record_synced",
                {"raw_path": raw_path, "synced": True},
                aborted_at,
            )
        except Exception as exc:
            warning = f"{type(exc).__name__}: {exc}"
            warnings.append(warning)
            append_workflow_event(
                state.run_dir,
                "abort_research_record_sync_warning",
                {"synced": False, "warning": warning},
                aborted_at,
            )
        if state.status != "aborted":
            state = transition_run_state(state, "aborted", reason)
            state = replace(state, updated_at=aborted_at)
            write_run_state(Path(state.run_dir) / STATE_FILENAME, state)
            append_workflow_event(
                state.run_dir,
                "workflow_aborted",
                {"run_id": state.run_id, "reason": reason},
                aborted_at,
            )
        clear_active_run(self.paths.run_root)
        summary = self._summary(state)
        summary.update({"warnings": warnings, "raw_path": raw_path})
        return summary

    def continue_once(self, now: str) -> dict[str, object]:
        """Input: timestamp. Output: status summary. Advance exactly one legal workflow stage."""
        with _workflow_mutation_lock(self.paths.run_root):
            return self._continue_once_unlocked(now)

    def _continue_once_unlocked(self, now: str) -> dict[str, object]:
        """Input: timestamp. Output: status summary. Advance one stage while mutation lock is held."""
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
            try:
                manifest = json.loads(
                    (run_dir / "run_manifest.json").read_text(encoding="utf-8")
                )
                result = schedule_research_stage(
                    self.paths.knowledge_root, run_dir, str(manifest.get("selected_option_id", ""))
                )
            except (OSError, ValueError, KeyError, TypeError) as exc:
                blocker = f"{type(exc).__name__}: {exc}"
                state = transition_run_state(state, "failed", blocker)
                state = self._set_stage(state, "schedule", "failed", now, blocker=blocker)
                write_run_state(run_dir / STATE_FILENAME, state)
                append_workflow_event(
                    run_dir,
                    "stage_failed",
                    {
                        "stage": "schedule",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    now,
                )
                return self._summary(state, [f"schedule_stage_failed:{blocker}"])
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
        if state.status == "running" and state.current_stage in POST_SCHEDULE_STAGES:
            stage_name = state.current_stage
            try:
                result = advance_post_schedule_stage(run_dir, stage_name)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                blocker = f"{type(exc).__name__}: {exc}"
                state = transition_run_state(state, "failed", blocker)
                state = self._set_stage(state, stage_name, "failed", now, blocker=blocker)
                write_run_state(run_dir / STATE_FILENAME, state)
                append_workflow_event(
                    run_dir,
                    "stage_failed",
                    {
                        "stage": stage_name,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    now,
                )
                return self._summary(state, [f"{stage_name}_stage_failed:{blocker}"])
            if result["status"] == "paused":
                blocker = str(result["blocker"])
                state = transition_run_state(state, "paused", blocker)
                state = self._set_stage(
                    state,
                    stage_name,
                    "paused",
                    now,
                    evidence_paths=[str(item) for item in result["evidence_paths"]],
                    blocker=blocker,
                )
                write_run_state(run_dir / STATE_FILENAME, state)
                append_workflow_event(
                    run_dir,
                    "stage_paused",
                    {"stage": stage_name, "blocker": blocker, "result": result},
                    now,
                )
                return self._summary(state)
            next_stage = POST_SCHEDULE_STAGES[POST_SCHEDULE_STAGES.index(stage_name) + 1] if stage_name != "repair" else "candidate_gate"
            state = self._set_stage(
                state,
                stage_name,
                "completed",
                now,
                evidence_paths=[str(item) for item in result["evidence_paths"]],
                current_stage=next_stage,
                last_completed_stage=stage_name,
            )
            write_run_state(run_dir / STATE_FILENAME, state)
            append_workflow_event(
                run_dir,
                "stage_completed",
                {"stage": stage_name, "result": result},
                now,
            )
            return self._summary(state)
        if state.status == "running" and state.current_stage == "candidate_gate":
            blocker = "candidate approval request required"
            handoff_path = run_dir / "stages" / "candidate_gate" / "candidate_approval_request.json"
            handoff_path.parent.mkdir(parents=True, exist_ok=True)
            handoff_path.write_text(
                json.dumps(
                    {"run_id": state.run_id, "blocker": blocker, "requested_at": now},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            state = transition_run_state(state, "paused", blocker)
            state = self._set_stage(
                state,
                "candidate_gate",
                "paused",
                now,
                evidence_paths=[str(handoff_path)],
                blocker=blocker,
            )
            state = replace(state, next_action="workflow-request-candidate-approval")
            write_run_state(run_dir / STATE_FILENAME, state)
            append_workflow_event(
                run_dir,
                "candidate_approval_request_required",
                {"stage": "candidate_gate", "blocker": blocker, "handoff_path": str(handoff_path)},
                now,
            )
            return self._summary(state)
        if state.status == "running" and state.current_stage == "research_record_sync":
            return self._sync_research_record_unlocked(now)
        return self._summary(state)

    def request_candidate_approval(
        self, candidates: list[dict[str, object]], now: str
    ) -> dict[str, object]:
        """Input: candidates and timestamp. Output: status summary. Pause run for user candidate approval."""
        with _workflow_mutation_lock(self.paths.run_root):
            return self._request_candidate_approval_unlocked(candidates, now)

    def _request_candidate_approval_unlocked(
        self, candidates: list[dict[str, object]], now: str
    ) -> dict[str, object]:
        """Input: candidates and timestamp. Output: status summary. Request approval under mutation lock."""
        state = self._active_state()
        if state is None:
            return {"active": False, "status": "none"}
        if state.current_stage != "candidate_gate" or state.status not in {"running", "paused"}:
            raise ValueError(
                "candidate approval request requires the running candidate gate stage"
            )
        if state.status == "paused" and state.stages["candidate_gate"].blocker != "candidate approval request required":
            raise ValueError(
                "candidate approval request requires the running candidate gate stage"
            )
        if state.status == "paused":
            state = transition_run_state(state, "running", "")
            state = self._set_stage(state, "candidate_gate", "running", now)
        state = self._reject_inconsistent_candidate_mutation(state, now)
        incomplete = [
            stage_name
            for stage_name in CANDIDATE_GATE_PREREQUISITES
            if state.stages[stage_name].status not in {"completed", "skipped"}
        ]
        if incomplete:
            raise ValueError(
                "candidate gate prerequisite stages are incomplete: " + ", ".join(incomplete)
            )
        if not candidates:
            raise ValueError("at least one candidate is required for approval request")
        for candidate in candidates:
            self._validate_candidate_gate_identity(candidate)
            if str(candidate.get("source_run_id", "")) != state.run_id:
                raise ValueError("candidate source_run_id must match the active workflow run")
            if not self._candidate_has_verified_hard_pass(state, candidate):
                raise ValueError("candidate must carry verified hard-pass evidence")
        seen_contract_keys: set[tuple[str, int, str]] = set()
        seen_candidate_ids: set[str] = set()
        for candidate in candidates:
            candidate_id = str(candidate.get("candidate_id", "")).strip()
            if candidate_id in seen_candidate_ids:
                raise ValueError("duplicate candidate ID")
            seen_candidate_ids.add(candidate_id)
            contract_key = self._candidate_contract_key(candidate)
            if contract_key in seen_contract_keys:
                raise ValueError("duplicate candidate contract key")
            seen_contract_keys.add(contract_key)
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
        with _workflow_mutation_lock(self.paths.run_root):
            return self._approve_candidates_unlocked(candidate_ids, approved_at, approved_by)

    def _approve_candidates_unlocked(
        self, candidate_ids: list[str], approved_at: str, approved_by: str
    ) -> dict[str, object]:
        """Input: candidate ids and metadata. Output: queue summary. Approve under mutation lock."""
        state = self._active_state()
        if state is None:
            return {"active": False, "queued_count": 0}
        if not candidate_ids:
            raise ValueError("at least one candidate must be selected for approval")
        if state.status != "waiting_for_user" or state.current_stage != "user_approval":
            raise ValueError(
                "candidate approval requires waiting_for_user at the user approval stage"
            )
        state = self._reject_inconsistent_candidate_mutation(state, approved_at)
        run_dir = Path(state.run_dir)
        candidates = json.loads((run_dir / "candidate_gate.json").read_text(encoding="utf-8"))
        if not isinstance(candidates, list):
            raise ValueError("candidate gate must contain a list of candidates")
        wanted = {str(item) for item in candidate_ids}
        candidates_by_id: dict[str, list[dict[str, object]]] = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError("candidate gate rows must be objects")
            candidate_id = str(candidate.get("candidate_id", ""))
            candidates_by_id.setdefault(candidate_id, []).append(candidate)
        available = set(candidates_by_id)
        unknown = sorted(wanted - available)
        if unknown:
            raise ValueError(f"unknown candidate IDs: {', '.join(unknown)}")
        ambiguous = sorted(
            candidate_id for candidate_id in wanted if len(candidates_by_id[candidate_id]) != 1
        )
        if ambiguous:
            raise ValueError(f"ambiguous candidate ID: {', '.join(ambiguous)}")
        selected = [candidates_by_id[candidate_id][0] for candidate_id in sorted(wanted)]
        for candidate in selected:
            self._validate_candidate_gate_identity(candidate)
            if str(candidate.get("source_run_id", "")) != state.run_id:
                raise ValueError("candidate source_run_id must match the active workflow run")
            if not self._candidate_has_verified_hard_pass(state, candidate):
                raise ValueError("candidate must carry verified hard-pass evidence")
            validate_candidate_approval(candidate, approved_at, approved_by)
        record = self._load_or_create_research_record(state)
        queued_count = 0
        for candidate in selected:
            approval = approve_candidate(run_dir, candidate, approved_at, approved_by)
            queue_row = queue_approved_candidate(run_dir, approval)
            record = record_approval(record, approval)
            record = record_queue_update(record, queue_row)
            queued_count += 1
        write_research_record(run_dir / "research_record.json", record)
        self._append_event_once(
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
        state = replace(state, research_record_synced=False)
        write_run_state(run_dir / STATE_FILENAME, state)
        return {"run_id": state.run_id, "queued_count": queued_count, "status": state.status}

    def update_candidate_status(
        self,
        candidate_id: str,
        version: int,
        expression_hash: str,
        status: str,
        updated_at: str,
        source_run_id: str = "",
    ) -> dict[str, object]:
        """Input: queue identity, status, timestamp, optional source run. Output: updated row. Own status updates."""
        with _workflow_mutation_lock(self.paths.run_root):
            return self._update_candidate_status_unlocked(
                candidate_id, version, expression_hash, status, updated_at, source_run_id
            )

    def invalidate_candidate_approval(
        self,
        candidate_id: str,
        version: int,
        expression_hash: str,
        reason: str,
        invalidated_at: str,
        source_run_id: str = "",
    ) -> dict[str, object]:
        """Input: queue identity and reason. Output: invalidated row. Invalidate a superseded approval."""
        with _workflow_mutation_lock(self.paths.run_root):
            return self._invalidate_candidate_approval_unlocked(
                candidate_id, version, expression_hash, reason, invalidated_at, source_run_id
            )

    def _invalidate_candidate_approval_unlocked(
        self,
        candidate_id: str,
        version: int,
        expression_hash: str,
        reason: str,
        invalidated_at: str,
        source_run_id: str = "",
    ) -> dict[str, object]:
        """Input: queue identity and reason. Output: invalidated row. Mark old approval non-actionable."""
        state = self._candidate_invalidation_state(source_run_id)
        if state is None:
            raise ValueError("an active workflow run is required for candidate invalidation")
        state = self._reject_inconsistent_candidate_mutation(state, invalidated_at)
        run_dir = Path(state.run_dir)
        invalidated = invalidate_candidate_queue_entry(
            run_dir, candidate_id, version, expression_hash, reason, invalidated_at
        )
        original_record = self._load_or_create_research_record(state)
        record = record_queue_update(original_record, invalidated)
        record_changed = record != original_record
        pending_state = state
        if record_changed or not state.research_record_synced:
            pending_state = replace(state, research_record_synced=False, updated_at=invalidated_at)
            write_run_state(run_dir / STATE_FILENAME, pending_state)
        if record_changed:
            write_research_record(run_dir / "research_record.json", record)
        self._append_event_once(
            run_dir,
            "candidate_approval_invalidated",
            {
                "candidate_id": invalidated.get("candidate_id", ""),
                "platform_alpha_id": invalidated.get("platform_alpha_id", ""),
                "version": invalidated.get("version", ""),
                "expression_hash": invalidated.get("expression_hash", ""),
                "source_run_id": invalidated.get("source_run_id", ""),
                "reason": invalidated.get("invalidation_reason", ""),
            },
            invalidated_at,
        )
        if state.status in {"completed", "completed_with_warnings"}:
            if record_changed or not state.research_record_synced:
                self._sync_terminal_research_record_or_warn(
                    pending_state, record, invalidated_at
                )
        return invalidated

    def _update_candidate_status_unlocked(
        self,
        candidate_id: str,
        version: int,
        expression_hash: str,
        status: str,
        updated_at: str,
        source_run_id: str = "",
    ) -> dict[str, object]:
        """Input: queue identity and status. Output: updated row. Update status under mutation lock."""
        state = self._candidate_status_state(source_run_id)
        if state is None:
            raise ValueError("an active workflow run is required for candidate status updates")
        state = self._reject_inconsistent_candidate_mutation(state, updated_at)
        run_dir = Path(state.run_dir)
        before_rows = load_approved_queue(run_dir)
        target = (str(candidate_id), str(version), str(expression_hash))
        before_matches = [
            row
            for row in before_rows
            if (
                str(row.get("candidate_id", "")),
                str(row.get("version", "")),
                str(row.get("expression_hash", "")),
            )
            == target
        ]
        if (
            status == "api_submitted"
            and len(before_matches) == 1
            and str(before_matches[0].get("status", "")) not in {"api_submitted", "invalidated"}
        ):
            claim = claim_api_submission_slot(self.paths.run_root, before_matches[0], updated_at)
        else:
            claim = None
        try:
            updated = update_candidate_queue_status(
                run_dir, candidate_id, version, expression_hash, status, updated_at
            )
        except Exception:
            if claim is not None and bool(claim.get("_created", False)):
                release_api_submission_claim_slot(self.paths.run_root, claim, updated_at)
            raise
        queue_changed = len(before_matches) == 1 and str(before_matches[0].get("status", "")) != status
        original_record = self._load_or_create_research_record(state)
        record = original_record
        record = record_queue_update(record, updated)
        if status != "queued":
            record = record_manual_submission_status(record, updated)
        record_changed = record != original_record
        mutation_recorded = queue_changed or record_changed
        pending_state = state
        if mutation_recorded:
            pending_state = replace(state, research_record_synced=False, updated_at=updated_at)
            write_run_state(run_dir / STATE_FILENAME, pending_state)
        if record_changed:
            write_research_record(run_dir / "research_record.json", record)
        self._append_event_once(
            run_dir,
            "candidate_status_updated",
            {
                "candidate_id": updated.get("candidate_id", ""),
                "platform_alpha_id": updated.get("platform_alpha_id", ""),
                "version": updated.get("version", ""),
                "expression_hash": updated.get("expression_hash", ""),
                "source_run_id": updated.get("source_run_id", ""),
                "status": status,
            },
            updated_at,
        )
        if state.status in {"completed", "completed_with_warnings"}:
            if mutation_recorded or not state.research_record_synced:
                self._sync_terminal_research_record_or_warn(pending_state, record, updated_at)
        return updated

    def sync_research_record(self, now: str) -> dict[str, object]:
        """Input: timestamp. Output: sync summary. Sync the active Research Record to knowledge raw."""
        with _workflow_mutation_lock(self.paths.run_root):
            return self._sync_research_record_unlocked(now)

    def _sync_research_record_unlocked(self, now: str) -> dict[str, object]:
        """Input: timestamp. Output: sync summary. Sync record while mutation lock is held."""
        state = self._active_state()
        if state is None:
            return {"active": False, "synced": False, "raw_path": ""}
        run_dir = Path(state.run_dir)
        record = self._load_or_create_research_record(state)
        write_research_record(run_dir / "research_record.json", record)
        advance_stage = state.current_stage == "research_record_sync"
        try:
            raw_path = sync_research_record_to_raw(record, self.paths.knowledge_root / "raw")
        except Exception as exc:
            if not advance_stage:
                raise
            warning = f"{type(exc).__name__}: {exc}"
            state = self._set_stage(
                state,
                "research_record_sync",
                "completed",
                now,
                evidence_paths=[str(run_dir / "research_record.json")],
                blocker=warning,
                current_stage="complete",
                last_completed_stage="research_record_sync",
            )
            state = replace(state, research_record_synced=False)
            state = transition_run_state(state, "completed_with_warnings", "")
            write_run_state(run_dir / STATE_FILENAME, state)
            append_workflow_event(
                run_dir,
                "research_record_sync_warning",
                {
                    "synced": False,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "local_record_path": str(run_dir / "research_record.json"),
                },
                now,
            )
            clear_active_run(self.paths.run_root)
            summary = self._summary(state)
            summary.update({"synced": False, "raw_path": "", "warnings": [warning]})
            return summary
        if advance_stage:
            state = self._set_stage(
                state,
                "research_record_sync",
                "completed",
                now,
                evidence_paths=[str(raw_path)],
                current_stage="complete",
                last_completed_stage="research_record_sync",
            )
            state = replace(state, research_record_synced=True)
        else:
            state = replace(state, research_record_synced=True, updated_at=now)
        if advance_stage:
            state = transition_run_state(state, "completed", "")
        write_run_state(run_dir / STATE_FILENAME, state)
        append_workflow_event(
            run_dir,
            "research_record_synced",
            {"raw_path": str(raw_path), "synced": True},
            now,
        )
        if advance_stage:
            append_workflow_event(
                run_dir,
                "workflow_completed",
                {"run_id": state.run_id, "status": state.status},
                now,
            )
            clear_active_run(self.paths.run_root)
        summary = self._summary(state)
        summary.update({"synced": True, "raw_path": str(raw_path), "warnings": []})
        return summary

    def _sync_terminal_research_record_or_warn(
        self, state: WorkflowRunState, record, now: str
    ) -> None:
        """Input: WorkflowRunState, ResearchRecord-like object, timestamp str. Output: None. Sync raw record or persist warning state."""
        run_dir = Path(state.run_dir)
        try:
            raw_path = sync_research_record_to_raw(record, self.paths.knowledge_root / "raw")
        except Exception as exc:
            warning = f"{type(exc).__name__}: {exc}"
            warning_state = self._set_stage(
                state,
                "research_record_sync",
                "completed",
                now,
                evidence_paths=[str(run_dir / "research_record.json")],
                blocker=warning,
                current_stage="complete",
                last_completed_stage="research_record_sync",
            )
            warning_state = replace(
                warning_state,
                status="completed_with_warnings",
                research_record_synced=False,
                waiting_for_user=False,
                next_action="",
                updated_at=now,
            )
            write_run_state(run_dir / STATE_FILENAME, warning_state)
            append_workflow_event(
                run_dir,
                "research_record_sync_warning",
                {
                    "synced": False,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "local_record_path": str(run_dir / "research_record.json"),
                },
                now,
            )
            return
        synced_state = self._set_stage(
            state,
            "research_record_sync",
            "completed",
            now,
            evidence_paths=[str(raw_path)],
            current_stage="complete",
            last_completed_stage="research_record_sync",
        )
        synced_state = replace(synced_state, research_record_synced=True, updated_at=now)
        write_run_state(
            run_dir / STATE_FILENAME,
            synced_state,
        )
        append_workflow_event(
            run_dir,
            "research_record_synced",
            {"raw_path": str(raw_path), "synced": True},
            now,
        )

    def _append_event_once(
        self,
        run_dir: str | Path,
        event_type: str,
        payload: dict[str, object],
        occurred_at: str,
    ) -> None:
        """Input: run dir and event data. Output: none. Skip retry events for the same identity."""
        events = read_workflow_events(run_dir)
        if event_type == "candidate_status_updated":
            identity_fields = (
                "candidate_id",
                "platform_alpha_id",
                "version",
                "expression_hash",
                "source_run_id",
            )
            identity = tuple(str(payload.get(field, "")) for field in identity_fields)
            latest = next(
                (
                    event
                    for event in reversed(events)
                    if event.event_type == event_type
                    and tuple(str(event.payload.get(field, "")) for field in identity_fields)
                    == identity
                ),
                None,
            )
            if latest is not None and str(latest.payload.get("status", "")) == str(
                payload.get("status", "")
            ):
                return
        if events and events[-1].event_type == event_type and events[-1].payload == payload:
            return
        append_workflow_event(run_dir, event_type, payload, occurred_at)

    def _load_or_create_research_record(self, state: WorkflowRunState):
        """Input: state. Output: ResearchRecord. Load or create the run research record."""
        path = Path(state.run_dir) / "research_record.json"
        if path.exists():
            return load_research_record(path)
        return empty_research_record(state.run_id, state.objective)

    def _active_state(self) -> WorkflowRunState | None:
        """Input: none. Output: active state or none. Recover the current resumable run from durable files."""
        return self._active_discovery().state

    def _candidate_status_state(self, source_run_id: str) -> WorkflowRunState | None:
        """Input: optional source run id. Output: selected state. Load completed runs without active discovery."""
        selector = str(source_run_id).strip()
        if not selector:
            return self._active_state()
        if selector in {".", ".."} or Path(selector).name != selector:
            raise ValueError("source_run_id must be a run identifier")
        state_path = self.paths.run_root / selector / STATE_FILENAME
        if not state_path.exists():
            raise ValueError(f"source workflow run not found: {selector}")
        resolved_run_root = self.paths.run_root.resolve()
        selected_run_dir = state_path.parent.resolve()
        if selected_run_dir != resolved_run_root / selector:
            raise ValueError("source_run_id resolves outside run_root")
        state = load_run_state(state_path)
        if state.run_id != selector:
            raise ValueError("source_run_id does not match the selected workflow state")
        if Path(state.run_dir).resolve() != selected_run_dir:
            raise ValueError("selected workflow state run_dir does not match its directory")
        if state.status not in {"completed", "completed_with_warnings"}:
            raise ValueError("source_run_id must select a completed workflow run")
        return state

    def _candidate_invalidation_state(self, source_run_id: str) -> WorkflowRunState | None:
        """Input: optional source run id. Output: state. Select active run or completed run for invalidation."""
        selector = str(source_run_id).strip()
        if not selector:
            return self._active_state()
        active = self._active_state()
        if active is not None and active.run_id == selector:
            return active
        return self._candidate_status_state(selector)

    def _active_discovery(self) -> WorkflowStateDiscovery:
        """Input: none. Output: discovery result. Repair official state and pointer only after read-only recovery."""
        discovery = discover_active_workflow(self.paths.run_root)
        if (
            discovery.state is None
            and discovery.run_dir is not None
            and discovery.diagnostics == ["active_run_terminal"]
        ):
            clear_active_run(self.paths.run_root)
            return WorkflowStateDiscovery(None, None, "", [])
        if discovery.state is not None and discovery.run_dir is not None and discovery.recovered:
            if any(
                diagnostic in {
                    "run_state_recovered_from_checkpoint",
                    "run_state_recovered_from_events",
                }
                for diagnostic in discovery.diagnostics
            ):
                write_run_state(discovery.run_dir / STATE_FILENAME, discovery.state)
            write_active_run(self.paths.run_root, discovery.state.run_id, discovery.run_dir)
            return WorkflowStateDiscovery(
                discovery.state,
                discovery.run_dir,
                discovery.run_id,
                [],
                False,
            )
        return discovery

    def _start_is_allowed(self, discovery: WorkflowStateDiscovery) -> bool:
        """Input: active discovery. Output: whether start is safe. Allow only a clean no-active-run result."""
        return discovery.state is None and discovery.diagnostics in ([], ["active_run_missing"])

    def _new_run_id(self, created_at: str) -> str:
        """Input: user timestamp. Output: single-segment run id. Format valid timestamps or use a safe fallback."""
        try:
            timestamp = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            prefix = timestamp.strftime("%Y%m%dT%H%M%S%f")
        except ValueError:
            prefix = "run"
        return f"{prefix}-{uuid4().hex[:8]}"

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

    def _reject_inconsistent_candidate_mutation(
        self, state: WorkflowRunState, now: str
    ) -> WorkflowRunState:
        """Input: state and timestamp. Output: consistent state. Pause or reject before candidate writes."""
        diagnostics = diagnose_state_consistency(state.run_dir)
        blocking_diagnostics = blocking_terminal_issues(state, diagnostics)
        state = self._pause_for_diagnostics(state, blocking_diagnostics, now)
        if blocking_diagnostics:
            raise ValueError("workflow consistency diagnostics: " + ", ".join(blocking_diagnostics))
        return state

    def _validate_candidate_gate_identity(self, candidate: dict[str, object]) -> None:
        """Input: candidate row. Output: none. Require approval identity fields before candidate-gate writes."""
        for field in ("candidate_id", "platform_alpha_id", "expression_hash", "source_run_id"):
            value = candidate.get(field)
            if value is None or not str(value).strip():
                if field == "candidate_id":
                    raise ValueError(
                        "candidate_id and version must be non-empty; candidate_id is required for candidate gate"
                    )
                raise ValueError(f"{field} is required for candidate gate")
        version_value = candidate.get("version")
        if version_value is None or not str(version_value).strip():
            raise ValueError(
                "candidate_id and version must be non-empty; version is required for candidate gate"
            )
        try:
            int(version_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("version must be an integer for candidate gate") from exc

    def _candidate_contract_key(self, candidate: dict[str, object]) -> tuple[str, int, str]:
        """Input: candidate row. Output: contract key tuple. Match queue status identity semantics."""
        return (
            str(candidate.get("candidate_id", "")).strip(),
            int(candidate.get("version", -1)),
            str(candidate.get("expression_hash", "")).strip(),
        )

    def _candidate_has_verified_hard_pass(
        self, state: WorkflowRunState, candidate: dict[str, object]
    ) -> bool:
        """Input: active state and candidate row. Output: bool. Bind hard-pass eligibility to local run artifacts."""
        if candidate.get("hard_pass") is not True:
            return False
        alpha_id = str(candidate.get("platform_alpha_id", "")).strip()
        expression_hash = str(candidate.get("expression_hash", "")).strip()
        if not alpha_id or not expression_hash:
            return False
        run_dir = Path(state.run_dir)
        csv_path = run_dir / "candidates.csv"
        all_alphas_path = run_dir / "all_alphas.jsonl"
        if csv_path.exists():
            csv_rows = self._read_candidate_csv(csv_path)
            if csv_rows is None or not any(
                self._artifact_identity_matches(row, alpha_id, expression_hash)
                for row in csv_rows
            ):
                return False
        if not all_alphas_path.exists():
            return False
        alpha_rows = self._read_jsonl_rows(all_alphas_path)
        matching_rows = [
            row
            for row in alpha_rows or []
            if self._artifact_identity_matches(row, alpha_id, expression_hash)
        ]
        if alpha_rows is None or not matching_rows:
            return False
        return all(
            row.get("hard_pass") is True
            and not bool(row.get("failed"))
            and not bool(row.get("pending"))
            for row in matching_rows
        )

    def _read_candidate_csv(self, path: Path) -> list[dict[str, str]] | None:
        """Input: candidates CSV path. Output: rows or none. Read local candidate evidence without mutation."""
        try:
            with path.open("r", encoding="utf-8", newline="") as file:
                return list(csv.DictReader(file))
        except (OSError, csv.Error, UnicodeError):
            return None

    def _read_jsonl_rows(self, path: Path) -> list[dict[str, object]] | None:
        """Input: JSONL artifact path. Output: object rows or none. Read durable alpha results without mutation."""
        try:
            rows: list[dict[str, object]] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    return None
                rows.append(row)
            return rows
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None

    def _artifact_identity_matches(
        self, row: dict[str, object], alpha_id: str, expression_hash: str
    ) -> bool:
        """Input: artifact row, alpha id, expression hash. Output: bool. Compare durable alpha identity exactly."""
        artifact_alpha_id = str(
            row.get("alpha_id", row.get("platform_alpha_id", ""))
        ).strip()
        return (
            artifact_alpha_id == alpha_id
            and str(row.get("expression_hash", "")).strip() == expression_hash
        )

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
        damaged = self._discovery_is_damaged(discovery)
        return {
            "active": discovery.run_dir is not None or damaged,
            "run_id": discovery.run_id,
            "status": "damaged" if damaged else "none",
            "next_action": "" if damaged else "workflow-start",
            "diagnostics": discovery.diagnostics,
            "consistent": not discovery.diagnostics,
        }

    def _discovery_is_damaged(self, discovery: WorkflowStateDiscovery) -> bool:
        """Input: discovery result. Output: bool. Distinguish absent pointers from damaged or ambiguous workflows."""
        return discovery.run_dir is not None or discovery.diagnostics not in ([], ["active_run_missing"])
