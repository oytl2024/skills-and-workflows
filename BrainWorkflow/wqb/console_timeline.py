from __future__ import annotations

from typing import Any
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


RUNTIME_STALE_SECONDS = 30


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


def readiness_blocker_current_work(state: dict[str, Any]) -> dict[str, Any] | None:
    """Input: Console state. Output: current-work blocker or none. Give blocked readiness priority over source retry."""
    readiness = state.get("readiness", {})
    if not isinstance(readiness, dict):
        return None
    issues = readiness.get("issues", [])
    issue_rows = [issue for issue in issues if isinstance(issue, dict)]
    blocked = readiness.get("blocked") is True or (
        readiness.get("exists") is True and readiness.get("passed") is False and bool(issue_rows)
    )
    if not blocked:
        return None
    details: list[str] = []
    for issue in issue_rows:
        code = str(issue.get("code", "readiness_blocked") or "readiness_blocked")
        message = str(issue.get("message", "") or "Readiness is blocked.")
        details.append(f"{code}: {message}")
        action = str(issue.get("action", "") or "")
        if action:
            details.append(f"Action: {action}")
    if not details:
        details.append("Readiness is blocked.")
    path = str(readiness.get("path", "") or "")
    return {
        "title": "Readiness blocker",
        "status": "blocked",
        "next_action": "readiness-blocked",
        "details": details,
        "evidence_paths": [path] if path else [],
    }


def build_timeline_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Input: console state. Output: timeline rows. Build the one-page workflow run tape."""
    freshness = state.get("freshness", {}) if isinstance(state.get("freshness"), dict) else {}
    maintenance = state.get("knowledge_maintenance", {}) if isinstance(state.get("knowledge_maintenance"), dict) else {}
    semantic = state.get('semantic_compile') or {}
    semantic_job = _running_job_for_action(state, 'compile-semantic-knowledge')
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
            str(semantic_job.get('status')) if semantic_job else (str(semantic['status']) if semantic else ("completed" if maintenance.get("status") == "completed" else "waiting")),
            "knowledge maintenance",
            ('Semantic compile: ' + str(semantic.get('error') or semantic.get('rejections') or 'partial coverage') + '; notification: ' + str((semantic.get('notification') or {}).get('status', 'not_needed'))) if semantic else "Compile raw facts into machine resources and compact human wiki.",
            str(semantic.get('path') or maintenance.get("path", maintenance.get("report_path", ""))),
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
    return rows + paired_arm_timeline(state)


def paired_arm_timeline(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Input: existing Console state dict. Output: arm timeline rows list. Project durable plans/events without execution or new gates."""
    run_dir = state.get('active_workflow', {}).get('run_dir')
    if not run_dir:
        return []
    progress = {row.get('expression_hash'): row for row in state.get('strategy_progress', {}).get('rows', [])}
    source = state.get('strategy_progress', {}).get('source_run_dir')
    source_sidecar = None
    if source:
        try:
            source_sidecar = hashlib.sha256((Path(source) / 'experiment_sidecar.json').read_bytes()).hexdigest()
        except OSError:
            return []
    rows = []
    for receipt in sorted((Path(run_dir) / 'runtime/research_plans').glob('paired-*.json')):
        if receipt.name.endswith('.experiments.json'):
            continue
        try:
            plan = json.loads(receipt.read_text(encoding='utf-8'))
            patch = plan['config_patch']
            path = receipt.with_suffix('.experiments.json')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != patch['experiment_sidecar_sha256']:
                continue
            if source_sidecar is not None and source_sidecar != patch['experiment_sidecar_sha256']:
                continue
            sidecar = json.loads(raw)
            projected = []
            for arm in sidecar['arms']:
                event = progress.get(arm['expression_hash'], {})
                status = str(event.get('status') or event.get('event', '')).upper()
                phase = 'queued'
                if arm.get('reused') or (status in ('CHECKED', 'QUALIFIED', 'MEASURED') and event.get('metrics')):
                    phase = 'measured'
                elif status in ('FAILED', 'ERROR'):
                    phase = 'failed'
                elif status in ('POLLING', 'PENDING', 'WAITING', 'SIMULATION_COMPLETED'):
                    phase = 'polling'
                elif status in ('SUBMITTED', 'RUNNING'):
                    phase = 'submitted'
                elif status == 'SUBMISSION_STARTED':
                    phase = 'uncertain'
                row = _row('scout_seed', phase, 'paired Scout', arm['arm_id'], str(path))
                row.update(experiment_id=arm['experiment_id'], arm_id=arm['arm_id'],
                    expression_hash=arm['expression_hash'], baseline_expression_hash=arm['baseline_expression_hash'])
                row['label'] = 'Scout ' + arm['arm_id']
                projected.append(row)
            for row in projected:
                siblings = [item for item in projected if item['experiment_id'] == row['experiment_id']]
                row['comparison_complete'] = len(siblings) == 2 and all(item['status'] == 'measured' for item in siblings)
                row['explanation'] = row['arm_id'] + ': ' + row['status'] + ('; comparison measured' if row['comparison_complete'] else '; comparison incomplete')
            rows.extend(projected)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return rows


def runtime_current_work(state: dict[str, Any]) -> dict[str, Any] | None:
    """Input: state dict. Output: work dict or None. Separate worker evidence from requested intent."""
    control = state.get('runtime_control', {})
    if not control:
        return None
    status = str(control.get('status', 'unknown'))
    reason = str(control.get('reason', ''))
    stamp = control.get('heartbeat_at') or control.get('updated_at')
    if control.get('invalid'):
        status, reason = 'error', 'Invalid runtime state; maintenance required'
    elif control.get('desired_state') == 'paused' and status not in {'paused', 'error', 'blocked', 'completed'}:
        status, reason = 'pausing', 'Pause requested; awaiting worker acknowledgement'
    elif status in {'running', 'waiting', 'unknown'}:
        try:
            observed = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - observed).total_seconds()
        except (ValueError, TypeError):
            status, reason = 'unknown', 'Worker heartbeat missing; execution is not confirmed'
        else:
            if age > RUNTIME_STALE_SECONDS or age < -RUNTIME_STALE_SECONDS:
                status, reason = 'stale', 'Worker heartbeat is stale; inspect or resume the durable driver'
    details = [reason] if reason else []
    from wqb.runtime_boundaries import RESOURCE_ACTIONS
    if reason in RESOURCE_ACTIONS and status == 'blocked':
        boundary = control.get('runtime_boundary') or {}
        return {'title': 'Runtime limit reached', 'status': 'blocked',
                'next_action': RESOURCE_ACTIONS[reason],
                'details': [reason, f"Elapsed: {control.get('elapsed_seconds', 0)} / {control.get('max_runtime_seconds', 'unknown')} seconds",
                            f"Resource usage: {boundary.get('used', 'unknown')} / {boundary.get('limit', 'unknown')}",
                            'Existing limits are preserved; Resume cannot enlarge resource authority.',
                            'Notice: ' + str(boundary.get('notification', {}).get('status', 'not_recorded'))],
                'evidence_paths': [boundary['evidence_path']] if boundary.get('evidence_path') else []}
    details.append(f"Desired state: {control.get('desired_state', 'unknown')}")
    if stamp:
        details.append(f'Last worker update: {stamp}')
    if control.get('next_wake_at'):
        details.append(f"Next wake: {control['next_wake_at']}")
    return {'title': 'Workflow driver', 'status': status, 'details': details,
            'next_action': 'workflow-auto-continue' if status in {'paused', 'stale', 'unknown'} else reason or status,
            'evidence_paths': []}


def select_current_work(state: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    """Input: console state and timeline. Output: current work summary. Explain the active row for the UI."""
    if ((state.get('start_request') or {}).get('status') == 'cancelled'
            and (state.get('readiness') or {}).get('context') == 'new-mission-preflight'):
        return {'title': 'Research preparation stopped', 'status': 'paused',
                'next_action': 'start-preflight-paused',
                'details': ['Stop is recorded. No new research mission will be created by this request.',
                            'Start can begin a new local preparation request.'], 'evidence_paths': []}
    preparing = _running_job_for_action(state, 'workflow-start-from-option')
    if preparing is not None:
        return {'title': 'Preparing research locally', 'status': 'running',
                'next_action': 'start-preflight-running',
                'details': ['Checking the selected scope and repairing local compiled resources.',
                            'No online knowledge capture is authorized by Start.'],
                'evidence_paths': [str(preparing.get('summary_path', ''))]}
    preflight = state.get('start_preflight') or {}
    if preflight.get('blocked'):
        issues = [issue for issue in preflight.get('issues', []) if isinstance(issue, dict)]
        details = [f"{issue.get('code', '')}: {issue.get('message', '')} | "
                   f"{issue.get('path', '')} | {issue.get('action', '')}" for issue in issues]
        notification = preflight.get('notification') or {}
        if notification:
            details.append(f"Maintenance delivery: {notification.get('status', 'unknown')} "
                           f"{notification.get('error', '')}; no capture or repair authorization.")
        return {'title': 'Research preparation blocked', 'status': 'blocked',
                'next_action': 'start-preflight-blocked',
                'details': details,
                'evidence_paths': [str(preflight.get('receipt_path', ''))]}
    rounds = state.get('research_rounds') or {}
    handoff = state.get('research_handoff') or {}
    from wqb.runtime_boundaries import RESOURCE_ACTIONS
    runtime = state.get('runtime_control') or {}
    if runtime.get('status') == 'blocked' and runtime.get('reason') in RESOURCE_ACTIONS:
        return runtime_current_work(state)
    if (rounds.get('status') == 'blocked' and rounds.get('stop_reason') != 'user_paused') or handoff.get('status') == 'blocked':
        reason = rounds.get('stop_reason') or handoff.get('stop_reason')
        return {'title': 'Research loop paused', 'status': 'blocked',
                'next_action': 'research-loop-blocked',
                'details': [f"Round: {rounds.get('current_round_id', 'original batch')}", str(reason),
                            str(handoff.get('message', '')),
                            'No new simulations started; evidence and authorized limits are preserved.'],
                'evidence_paths': []}
    control = state.get('runtime_control') or {}
    case = control.get('recovery_case') or {}
    if case.get('status') in {'awaiting_maintenance_confirmation', 'maintenance_approved'}:
        delivery = (case.get('notification') or {}).get('status', 'unknown')
        approval = ('Human confirmation recorded; verification required before resume.'
                    if case['status'] == 'maintenance_approved'
                    else 'Waiting for human repair confirmation in the maintenance chat.')
        return {'title': 'Maintenance blocker', 'status': 'blocked', 'next_action': 'maintenance-blocker',
                'details': [f"Case: {case.get('case_id', 'unknown')}",
                            f"Maintenance message delivery: {delivery}", approval,
                            'Runtime renewal does not resolve this fault.',
                            str((control.get('last_result') or {}).get('pause_reason', control.get('reason', '')))],
                'evidence_paths': []}
    scope = control.get('original_batch_recovery') or {}
    if scope.get('authorized'):
        if scope.get('planned', 0) > 0 and scope.get('remaining') == 0:
            return {'title': 'Original batch completed', 'status': 'blocked',
                    'next_action': 'research-mission-authority-required',
                    'details': [f"{scope.get('checked')}/{scope.get('planned')} checked. Original-only permission finished.",
                                'Choose an option card and Start a new bounded mission; Resume cannot extend the old scope.'],
                    'evidence_paths': []}
        work = runtime_current_work(state) or {}
        return {**work, 'title': 'Original batch recovery', 'details': [
            *work.get('details', []),
            f"Checked: {scope.get('checked', 0)}/{scope.get('planned', 0)}; remaining: {scope.get('remaining', 0)}",
            'Resume handles knowledge maintenance, cooldown and existing work; no new research.']}
    readiness_work = readiness_blocker_current_work(state)
    if readiness_work is not None:
        return readiness_work
    runtime_work = runtime_current_work(state)
    if runtime_work is not None:
        return runtime_work
    source_bridge = state.get("source_bridge", {})
    if isinstance(source_bridge, dict):
        action = str(source_bridge.get("action", ""))
        source_run_id = str(source_bridge.get("source_run_id", ""))
        details = [str(source_bridge.get("reason", "")), f"Source run: {source_run_id}"]
        metadata = source_bridge.get("metadata", {})
        if isinstance(metadata, dict):
            retry_at = str(metadata.get("retry_at", ""))
            next_check_at = str(metadata.get("next_check_at", ""))
            operator_message = str(metadata.get("operator_message", ""))
            consecutive = metadata.get("consecutive_429_count", "")
            maximum = metadata.get("max_consecutive_429", "")
            if retry_at:
                details.append(f"Retry at: {retry_at}")
            if next_check_at:
                details.append(f"Next check: {next_check_at}")
            if operator_message:
                details.append(operator_message)
            if str(consecutive) and str(maximum):
                details.append(f"429 count: {consecutive}/{maximum}")
        evidence_paths = list(source_bridge.get("evidence_paths", []))
        auto_continue_job = _running_job_for_action(state, "workflow-auto-continue")
        if auto_continue_job is not None:
            details.append(f"Job ID: {auto_continue_job.get('job_id', '')}")
            summary_path = str(auto_continue_job.get("summary_path", ""))
            if summary_path:
                evidence_paths.append(summary_path)
        source_work = {
            "rate_limit_wait": ("Rate limited", "waiting", "Continue workflow after retry time"),
            "maintenance_blocker": ("Maintenance blocker", "blocked", "maintenance-blocker"),
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
