from __future__ import annotations

from typing import Any


WORKFLOW_STAGE_LABELS = {
    "knowledge_health": "Knowledge health",
    "knowledge_compile": "Knowledge maintenance",
    "platform_data_capture": "Platform data capture",
    "data_ledger_compile": "Data ledger compile",
    "research_options": "Research options",
    "user_research_decision": "Research decision",
    "objective_selected": "Research decision",
    "schedule": "Schedule research",
    "scout_seed": "Scout and Seed",
    "batch_generation": "30 alpha batch",
    "backtest": "Multisim and backtest",
    "triage": "Triage",
    "repair": "Repair",
    "candidate_gate": "Candidate gate",
    "user_approval": "User approval",
    "approved_queue": "Approved candidate queue",
    "research_record_sync": "Research record sync",
    "complete": "Workflow complete",
}


def _row(stage_id: str, status: str, source: str, explanation: str, evidence_path: str = "") -> dict[str, Any]:
    """Input: timeline fields. Output: JSON-safe row. Build one stable workflow timeline row."""
    return {
        "stage_id": stage_id,
        "label": WORKFLOW_STAGE_LABELS.get(stage_id, stage_id.replace("_", " ").title()),
        "status": status,
        "source": source,
        "explanation": explanation,
        "evidence_path": evidence_path,
    }


def _running_job_for_action(state: dict[str, Any], action: str) -> dict[str, Any] | None:
    """Input: console state and action. Output: running job or none. Find active durable job."""
    for job in state.get("jobs", []):
        if isinstance(job, dict) and job.get("action") == action and job.get("status") in {"running", "detached"}:
            return job
    return None


def _stage_status_from_workflow(state: dict[str, Any], stage_id: str) -> str:
    """Input: console state and stage id. Output: timeline status. Map Orchestrator stage to row status."""
    workflow = state.get("active_workflow", {})
    if not isinstance(workflow, dict) or not workflow.get("exists"):
        return "not_started"
    current = str(workflow.get("current_stage", "")).lower()
    stages = workflow.get("stages", {})
    stage = stages.get(stage_id, {}) if isinstance(stages, dict) else {}
    stage_status = str(stage.get("status", "")) if isinstance(stage, dict) else ""
    if current == stage_id:
        if stage_id == "complete":
            return "completed"
        if stage_status in {"completed", "failed", "paused", "skipped"}:
            return stage_status
        return "waiting" if workflow.get("waiting_for_user") else "running"
    if stage_status:
        return stage_status
    return "ready"


def build_timeline_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Input: console state. Output: timeline rows. Build the one-page workflow run tape."""
    freshness = state.get("freshness", {}) if isinstance(state.get("freshness"), dict) else {}
    maintenance = state.get("knowledge_maintenance", {}) if isinstance(state.get("knowledge_maintenance"), dict) else {}
    delivery_gate = state.get("delivery_gate", {}) if isinstance(state.get("delivery_gate"), dict) else {}
    data_coverage = state.get("data_coverage", {}) if isinstance(state.get("data_coverage"), dict) else {}
    capture_job = _running_job_for_action(state, "capture-platform-data-fields")
    compile_job = _running_job_for_action(state, "compile-data-ledger")
    rows = [
        _row(
            "knowledge_health",
            "blocked" if int(freshness.get("stale_count", 0) or 0) or int(freshness.get("missing_count", 0) or 0) else "completed",
            "deterministic",
            "Checks raw/wiki freshness and maintenance contract state.",
        ),
        _row(
            "knowledge_compile",
            "completed" if maintenance.get("status") == "completed" else "waiting",
            "knowledge maintenance",
            "Compile raw facts into machine resources and compact human wiki.",
            str(maintenance.get("path", maintenance.get("report_path", ""))),
        ),
        _row(
            "platform_data_capture",
            str(capture_job.get("status")) if capture_job else ("completed" if data_coverage.get("exists") else "not_started"),
            "deterministic",
            "Captures platform data fields into the raw vault.",
            str(data_coverage.get("latest_capture_dir", "")),
        ),
        _row(
            "data_ledger_compile",
            str(compile_job.get("status")) if compile_job else "ready",
            "deterministic",
            "Compiles measured raw platform data into the semantic data ledger.",
        ),
        _row(
            "research_options",
            "completed" if state.get("option_cards") else "ready",
            "deterministic",
            "Chooses research options from incentives, data coverage, and template novelty.",
        ),
        _row("user_research_decision", "waiting" if state.get("option_cards") else "not_started", "user_approval", "User selects one research direction and measured scope."),
        _row("objective_selected", _stage_status_from_workflow(state, "objective_selected"), "user_approval", "Records the selected research objective and measured scope."),
        _row("schedule", _stage_status_from_workflow(state, "schedule"), "deterministic", "Builds the Orchestrator-owned research schedule."),
        _row("scout_seed", _stage_status_from_workflow(state, "scout_seed"), "deterministic", "Tests signal and records the template kernel."),
        _row("batch_generation", _stage_status_from_workflow(state, "batch_generation"), "deterministic", "Builds a 30 alpha batch before simulation."),
        _row("backtest", _stage_status_from_workflow(state, "backtest"), "deterministic", "Runs multisim or backtest and records results."),
        _row("triage", _stage_status_from_workflow(state, "triage"), "deterministic", "Classifies results and near misses."),
        _row("repair", _stage_status_from_workflow(state, "repair"), "deterministic", "Applies narrow repair levers to promising alphas."),
        _row("candidate_gate", _stage_status_from_workflow(state, "candidate_gate"), "deterministic", "Checks candidate readiness and writes approval requests."),
        _row("user_approval", _stage_status_from_workflow(state, "user_approval"), "user_approval", "User approves a submit-ready Alpha before API submission."),
        _row("approved_queue", _stage_status_from_workflow(state, "approved_queue"), "deterministic", "Writes approved candidates to the durable queue."),
        _row("research_record_sync", _stage_status_from_workflow(state, "research_record_sync"), "deterministic", "Compiles workflow evidence into the research record."),
        _row("complete", _stage_status_from_workflow(state, "complete"), "deterministic", "Marks the durable workflow run complete."),
        _row(
            "delivery_gate",
            str(delivery_gate.get("status", "waiting")),
            "delivery gate",
            "Verify fixed automation before handoff.",
            str(delivery_gate.get("path", delivery_gate.get("report_path", ""))),
        ),
    ]
    for checkpoint in state.get("ai_checkpoints", []):
        if isinstance(checkpoint, dict) and checkpoint.get("status") == "pending":
            rows.append(_row("ai_checkpoint", "waiting", "ai_judgment", str(checkpoint.get("reason", "")), ",".join(str(item) for item in checkpoint.get("evidence_paths", []))))
    return rows


def select_current_work(state: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    """Input: console state and timeline. Output: current work summary. Explain the active row for the UI."""
    source_bridge = state.get("source_bridge", {})
    if isinstance(source_bridge, dict):
        action = str(source_bridge.get("action", ""))
        source_run_id = str(source_bridge.get("source_run_id", ""))
        details = [str(source_bridge.get("reason", "")), f"Source run: {source_run_id}"]
        evidence_paths = list(source_bridge.get("evidence_paths", []))
        auto_continue_job = _running_job_for_action(state, "workflow-auto-continue")
        if auto_continue_job is not None:
            details.append(f"Job ID: {auto_continue_job.get('job_id', '')}")
            summary_path = str(auto_continue_job.get("summary_path", ""))
            if summary_path:
                evidence_paths.append(summary_path)
        source_work = {
            "rate_limit_wait": ("Rate limited", "waiting", "Continue workflow after retry time"),
            "import_existing": ("Import existing source", "paused", "Continue workflow to import source artifacts"),
            "complete_in_flight": ("Complete in-flight source", "waiting", "Continue workflow to recover source results"),
            "retry_planned": ("Retry planned source", "waiting", "Continue workflow to retry planned source work"),
        }
        if action in source_work:
            title, status, next_action = source_work[action]
            return {
                "title": title,
                "status": status,
                "next_action": next_action,
                "details": details,
                "evidence_paths": evidence_paths,
            }
    for job in state.get("jobs", []):
        if isinstance(job, dict) and job.get("status") in {"running", "detached"}:
            if job.get("action") == "capture-platform-data-fields":
                progress = job.get("progress", {}) if isinstance(job.get("progress"), dict) else {}
                return {
                    "title": "Platform data capture",
                    "status": job.get("status"),
                    "next_action": "wait for capture to finish",
                    "details": [
                        f"Fields captured: {progress.get('data_field_rows', 0)}",
                        f"Data sets captured: {progress.get('data_set_rows', 0)}",
                        f"Raw directory: {progress.get('capture_dir', '')}",
                    ],
                    "evidence_paths": [str(progress.get("capture_dir", ""))],
                }
            return {
                "title": str(job.get("action", "Console job")).replace("-", " ").title(),
                "status": job.get("status"),
                "next_action": "watch job evidence files",
                "details": [f"Job ID: {job.get('job_id', '')}"],
                "evidence_paths": [str(job.get("summary_path", ""))],
            }
    workflow = state.get("active_workflow", {})
    if isinstance(workflow, dict) and workflow.get("exists"):
        stage = str(workflow.get("current_stage", "workflow_start"))
        label = WORKFLOW_STAGE_LABELS.get(stage, stage.replace("_", " ").title())
        return {
            "title": label,
            "status": workflow.get("status", ""),
            "next_action": workflow.get("next_action", ""),
            "details": [f"Run ID: {workflow.get('run_id', '')}", f"Current stage: {stage}"],
            "evidence_paths": [str(workflow.get("run_dir", ""))],
        }
    waiting_rows = [row for row in timeline if row.get("status") in {"blocked", "waiting", "running"}]
    row = waiting_rows[0] if waiting_rows else timeline[0]
    return {
        "title": str(row.get("label", "Workflow")),
        "status": row.get("status", ""),
        "next_action": "choose the next safe action",
        "details": [str(row.get("explanation", ""))],
        "evidence_paths": [str(row.get("evidence_path", ""))],
    }
