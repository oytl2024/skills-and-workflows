from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
import hashlib
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse
import webbrowser

from wqb.console_context import record_console_job_context
from wqb.console_jobs import build_cli_command as build_raw_cli_command
from wqb.console_jobs import (
    ConsoleJob,
    create_job,
    finish_job,
    load_job_history,
    run_job,
    start_job_async,
)
from wqb.console_proposals import create_proposal_from_form
from wqb.console_state import ConsolePaths, default_console_paths, load_console_state, load_runtime_state
from wqb.runtime_revision import LOADED_CODE_REVISION
from wqb.recovery_cases import MAINTENANCE_BLOCKING_STATUSES
from wqb.console_timeline import readiness_blocker_current_work, build_timeline_rows, select_current_work
from wqb.data_ledger import DataLedgerRecord, data_ledger_path_for_knowledge
from wqb.knowledge_paths import (
    decision_artifacts_root,
    existing_decision_artifact_path,
)
from wqb.template_library import load_template_library_from_knowledge
from wqb.option_cards import fallback_option_id, normalize_option_card_row, normalize_option_card_rows
from wqb.run_readiness import evaluate_run_readiness
from wqb.template_library import select_templates_for_data
from wqb.workflow_proposals import update_workflow_proposal_decision


PROPOSAL_DECISION_STATUSES = (
    "accepted_for_wiki",
    "accepted_for_implementation",
    "accepted_as_experiment",
    "rejected",
    "deferred",
)

ASYNC_CONSOLE_ACTIONS = {
    "workflow-start-from-option",
    "bootstrap-knowledge",
    "capture-platform-data-fields",
    "compile-data-ledger",
    "compile-knowledge",
    "compile-research-records",
    'compile-semantic-knowledge',
    "delivery-gate",
    "plan-research-options",
    "workflow-auto-continue",
}

CONSOLE_STATE_CACHE_TTL_SECONDS = 3.0
CONSOLE_REFRESH_INTERVAL_MS = 3000
CONSOLE_SERVER_REVISION = "console-autonomous-v3"
CONSOLE_EVENT_INTERVAL_SECONDS = 1.0
CONSOLE_STREAM_SECONDS = 60.0
AUTO_CONTINUE_JOB_LOCK = threading.Lock()
START_JOB_LOCK = threading.Lock()
CODE_COMMIT_CACHE = ""


def _fallback_option_id(index: int) -> str:
    """Input: valid option order. Output: fallback option ID. Normalize cards without durable IDs."""
    return fallback_option_id(index)


def _html_page(title: str, body: str) -> str:
    """Input: title and body HTML. Output: full HTML page. Render the local console shell."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title>"
        "<style>"
        "body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#fff;color:#263238;letter-spacing:0}"
        "header{background:#fff;color:#263238;padding:14px 24px;border-bottom:2px solid #157d72;display:flex;justify-content:space-between;align-items:center}"
        "header h1{font-size:19px;line-height:1.25;margin:0;font-weight:650}main{min-height:calc(100vh - 56px)}"
        ".workspace,.control-center{max-width:1600px;margin:auto;display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,38%)}"
        "section{background:#fff;border-bottom:1px solid #dce4e1;padding:18px 24px;min-width:0}section h2{font-size:16px;line-height:1.3;margin:0 0 12px}section h3{font-size:14px;margin:8px 0}"
        ".hero{background:#f4f8f6}.timeline-panel{grid-column:1}.current-work{grid-column:2;border-left:1px solid #dce4e1}"
        ".ledger-strip{display:flex;gap:8px;flex-wrap:wrap}"
        ".badge{border:1px solid #D9E0E8;border-radius:3px;padding:4px 8px;font-size:12px;background:#fff}"
        ".badge-ready{border-color:#167C80;color:#167C80}.badge-warn{border-color:#B7791F;color:#B7791F}.badge-blocked{border-color:#B42318;color:#B42318}"
        ".option-card{display:block;border:1px solid #D9E0E8;border-radius:8px;padding:10px;margin:8px 0;cursor:pointer}"
        ".option-card:has(input:checked){border-color:#167C80;box-shadow:inset 3px 0 0 #167C80}"
        ".option-title{display:block;font-weight:600}.option-meta{display:block;font-size:12px;color:#4B5563;margin-top:3px}"
        "button,input,select,textarea{font:inherit;margin:4px 0;padding:7px 9px}button{cursor:pointer;background:#fff;border:1px solid #a8bbb5;border-radius:4px;color:#1f514b}button:hover,button:focus-visible{border-color:#157d72;outline:2px solid #c0e1d9}button:disabled{cursor:not-allowed;color:#697a78;border-color:#d3dcda}textarea{width:100%;min-height:90px}"
        "code,pre{font-family:Consolas,monospace}.wide{grid-column:1/-1}.empty{color:#6B7280}"
        ".timeline{list-style:none;margin:0;padding:0}.timeline-row{display:grid;grid-template-columns:14px minmax(0,1fr);gap:10px;padding:10px 0;border-top:1px solid #D9E0E8}.timeline-row:first-child{border-top:0}.timeline-dot{width:9px;height:9px;margin-top:6px;border-radius:50%;background:#6B7280}.state-running .timeline-dot,.state-completed .timeline-dot{background:#167C80}.state-blocked .timeline-dot,.state-failed .timeline-dot{background:#B42318}.state-waiting .timeline-dot,.state-paused .timeline-dot{background:#B7791F}.timeline-row span{display:block;color:#4B5563;font-size:12px;margin-top:2px}.timeline-row p{margin:5px 0}.timeline-row code{font-size:12px;overflow-wrap:anywhere}"
        "@media(max-width:760px){.workspace,.control-center{grid-template-columns:1fr}.wide,.timeline-panel,.current-work{grid-column:1}.current-work{border-left:0}section{padding:15px}}"
        "</style></head><body>"
        f"<header><h1>{escape(title)}</h1></header><main>{body}</main></body></html>"
    )


def _badge(label: str, value: Any, state: str = "neutral") -> str:
    """Input: label, value, state. Output: HTML badge. Render one compact status marker."""
    return f"<span class='badge badge-{escape(state)}'><strong>{escape(label)}</strong> {escape(str(value))}</span>"


def _render_data_authority(authority: dict[str, Any]) -> str:
    """Input: authority summary. Output: HTML. Render data ledger provenance."""
    ready = "yes" if authority.get("authoritative_ready") else "no"
    return (
        "<div class='ledger-strip'>"
        + _badge("authoritative measured", authority.get("authoritative_measured_count", 0), "ready" if ready == "yes" else "warn")
        + _badge("seed/cache", authority.get("seed_cache_count", 0), "warn")
        + _badge("unclassified", authority.get("unclassified_count", 0), "warn")
        + _badge("ready", ready, "ready" if ready == "yes" else "blocked")
        + "</div>"
    )


def _render_knowledge_contracts(contracts: dict[str, Any]) -> str:
    """Input: contract health summary. Output: HTML. Render vault contract health."""
    return (
        "<div class='ledger-strip'>"
        + _badge("issues", contracts.get("issue_count", 0), "warn" if contracts.get("issue_count") else "ready")
        + _badge("legacy paths", contracts.get("legacy_count", 0), "warn" if contracts.get("legacy_count") else "ready")
        + "</div>"
    )


def _option_blockers(cards: list[dict[str, Any]]) -> str:
    """Input: option cards. Output: HTML. Render maintenance blockers attached to options."""
    blockers = []
    for card in cards:
        blockers.extend(str(item) for item in card.get("maintenance_blockers", []) if str(item))
    if not blockers:
        return "<div class='empty'>No option maintenance blockers.</div>"
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in blockers[:6]) + "</ul>"


def _render_semantic_ledgers(summary: dict[str, Any]) -> str:
    """Input: semantic summary. Output: HTML. Render operator, template, and benchmark authority."""
    ready = bool(summary.get("ready"))
    return (
        "<div class='ledger-strip'>"
        + _badge("operator semantics", summary.get("operator_semantic_count", 0), "ready" if ready else "warn")
        + _badge("matrix-ready templates", summary.get("matrix_ready_template_count", 0), "ready" if ready else "warn")
        + _badge("active benchmark rules", summary.get("active_benchmark_rule_count", 0), "ready" if ready else "warn")
        + _badge("ready", "yes" if ready else "no", "ready" if ready else "blocked")
        + "</div>"
    )


def _render_proposal_lifecycle(counts: dict[str, Any]) -> str:
    """Input: proposal-status counts. Output: HTML. Render persisted proposal lifecycle counts."""
    if not counts:
        return "<div class='empty'>No workflow proposals.</div>"
    return "<div class='ledger-strip'>" + "".join(
        _badge(str(status), count) for status, count in sorted(counts.items())
    ) + "</div>"


def _render_option_controls(cards: list[dict[str, Any]]) -> str:
    """Input: option card rows. Output: HTML. Render selectable research option cards."""
    if not cards:
        return "<div class='empty'>No research options are available.</div>"
    rows = []
    for index, card in enumerate(cards, start=1):
        option_id = str(card.get("option_id") or _fallback_option_id(index))
        title = str(card.get("title", "Research option"))
        incentive = str(card.get("primary_incentive", ""))
        scope = str(card.get("candidate_scope", ""))
        score = card.get("score", {})
        total = score.get("total", "") if isinstance(score, dict) else ""
        rows.append(
            "<label class='option-card'>"
            f"<input type=\"radio\" name=\"selected_option_id\" value=\"{escape(option_id)}\" required>"
            f"<span class='option-title'>{escape(title)}</span>"
            f"<span class='option-meta'>{escape(incentive)} | {escape(scope)} | score {escape(str(total))}</span>"
            "</label>"
        )
    return "".join(rows)


def _normalized_option_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Input: option-card rows. Output: validated normalized rows. Skip malformed durable option cards."""
    return normalize_option_card_rows(rows)


def _normalize_option_row(row: dict[str, Any], fallback_index: int) -> dict[str, Any] | None:
    """Input: one option row and valid-row index. Output: normalized row or none. Validate persisted option-card structure."""
    return normalize_option_card_row(row, fallback_index)


def _render_scope_controls(scopes: list[dict[str, Any]]) -> str:
    """Input: ledger-backed scope rows. Output: HTML. Render required concrete scope selectors."""
    if not scopes:
        return "<div class='empty'>No measured ledger scopes are available for workflow start.</div>"
    options = "".join(
        f'<option value="{escape(json.dumps(scope, sort_keys=True))}">{escape("{} D{} {}".format(scope["region"], scope["delay"], scope["universe"]))}</option>'
        for scope in scopes
    )
    return f'<label>Scope <select name="selected_scope">{options}</select></label>'


def _state_label(status: Any) -> str:
    """Input: status value. Output: CSS-safe state label. Normalize timeline state styling."""
    value = str(status or "not_started").replace("_", "-")
    return "".join(ch for ch in value if ch.isalnum() or ch == "-")


def _render_timeline(rows: list[dict[str, Any]]) -> str:
    """Input: timeline rows. Output: HTML. Render the durable workflow run tape."""
    if not rows:
        return "<div class='empty'>No timeline rows available.</div>"
    items = []
    for row in rows:
        state = _state_label(row.get("status"))
        items.append(
            "<li class='timeline-row state-{state}'>"
            "<span class='timeline-dot'></span>"
            "<div><strong>{label}</strong><span>{status} · {source}</span><p>{explanation}</p><code>{evidence}</code></div>"
            "</li>".format(
                state=escape(state),
                label=escape(str(row.get("label", ""))),
                status=escape(str(row.get("status", ""))),
                source=escape(str(row.get("source", ""))),
                explanation=escape(str(row.get("explanation", ""))),
                evidence=escape(str(row.get("evidence_path", ""))),
            )
        )
    return "<ol class='timeline'>" + "".join(items) + "</ol>"


def _render_current_work(work: dict[str, Any]) -> str:
    """Input: current work row. Output: HTML. Render active job or workflow stage details."""
    details = "".join(f"<li>{escape(str(item))}</li>" for item in work.get("details", []) if str(item))
    evidence = "".join(f"<li><code>{escape(str(item))}</code></li>" for item in work.get("evidence_paths", []) if str(item))
    return (
        f"<h3>{escape(str(work.get('title', 'No active work')))}</h3>"
        f"<p>Status: <strong>{escape(str(work.get('status', '')))}</strong></p>"
        f"<p>Next action: {escape(str(work.get('next_action', '')))}</p>"
        f"<ul>{details}</ul>"
        f"<details><summary>Evidence paths</summary><ul>{evidence}</ul></details>"
    )


def _render_objective_summary(state: dict[str, Any]) -> str:
    """Input: Console state. Output: HTML. Render polling-safe gate badges and current work title."""
    readiness = state.get("readiness", {})
    freshness = state.get("freshness", {})
    data_coverage = state.get("data_coverage", {})
    readiness_state = "ready" if readiness.get("passed", readiness.get("exists", False)) else "blocked"
    readiness_value = readiness.get("passed", readiness.get("exists", False))
    if readiness.get("context") == "new-mission-preflight" and not readiness.get("blocked"):
        readiness_state, readiness_value = "neutral", "Checked on Start"
    freshness_state = "ready" if freshness.get("valid") and not freshness.get("stale_count") and not freshness.get("missing_count") else "warn"
    coverage_state = "ready" if data_coverage.get("status") == "completed" and not data_coverage.get("error_count") else "warn"
    badges = "".join(
        [
            _badge("Readiness", readiness_value, readiness_state),
            _badge("Freshness", f"stale {freshness.get('stale_count', 0)} / missing {freshness.get('missing_count', 0)}", freshness_state),
            _badge("Data fields", data_coverage.get("field_count", 0), coverage_state),
        ]
    )
    return (
        "<p>Workflow Console</p>"
        f"<div class='ledger-strip'>{badges}</div>"
        f"<p>Current work: <strong>{escape(str(state.get('current_work', {}).get('title', 'No active workflow')))}</strong></p>"
    )


def _render_recent_jobs(jobs: list[dict[str, Any]]) -> str:
    """Input: Console job rows. Output: HTML. Render recent durable job statuses for polling replacement."""
    items = "".join(
        f"<li><code>{escape(str(job.get('job_id', '')))}</code> {escape(str(job.get('action', '')))} {escape(str(job.get('status', '')))}</li>"
        for job in jobs[:8]
        if isinstance(job, dict)
    )
    return f"<ul>{items or '<li>No console jobs.</li>'}</ul>"


def _workflow_action_state(state: dict[str, Any]) -> dict[str, bool]:
    """Input: Console state. Output: action permission booleans. Centralize button authority."""
    active = state.get("active_workflow", {}) if isinstance(state.get("active_workflow"), dict) else {}
    source_bridge = state.get("source_bridge", {}) if isinstance(state.get("source_bridge"), dict) else {}
    current_work = state.get("current_work", {}) if isinstance(state.get("current_work"), dict) else {}
    readiness_blocked = readiness_blocker_current_work(state) is not None
    blocked_source_actions = {"maintenance_blocker", "rate_limit_wait"}
    maintenance_blocked = (
        readiness_blocked
        or str(source_bridge.get("action", "")) in blocked_source_actions
        or str(current_work.get("next_action", "")) == "maintenance-blocker"
        or str(current_work.get("next_action", "")) == "rate-limit-wait"
        or str(current_work.get("next_action", "")) == "readiness-blocked"
    )
    active_exists = bool(active.get("exists"))
    control = state.get("runtime_control", {})
    scope = control.get('original_batch_recovery') or {}
    scripted_source = (str(source_bridge.get('action', '')) != 'maintenance_blocker'
                       or (source_bridge.get('metadata') or {}).get('operator_acknowledgement_required') is True)
    if scope.get('authorized') and scripted_source:
        maintenance_blocked = False
    if str(current_work.get('next_action', '')) in {'research-loop-blocked', 'research-mission-authority-required'}:
        maintenance_blocked = True
    from wqb.runtime_boundaries import RESOURCE_ACTIONS
    if control.get('reason') in RESOURCE_ACTIONS and control.get('status') == 'blocked':
        maintenance_blocked = True
    confirmation_required = ((control.get("recovery_case") or {}).get("status") in MAINTENANCE_BLOCKING_STATUSES
                             or bool(control.get("legacy_authority_required")))
    worker_running = control.get("desired_state") == "running" and control.get("status") in {"running", "waiting"}
    original_finished = (scope.get('authorized') is True and type(scope.get('planned')) is int
                         and scope['planned'] > 0 and scope.get('remaining') == 0
                         and scope.get('checked', 0) >= scope['planned'] and not worker_running)
    preparing = (state.get("start_preparation") or {}).get("status") in {"preparing", "validating", "committing"}
    return {
        "continue_workflow": active_exists and not preparing and not maintenance_blocked and not worker_running and not confirmation_required,
        "stop_workflow": active_exists or preparing,
        "start_workflow": (not active_exists or original_finished) and not preparing,
    }


def _maintenance_blocker_reason(state: dict[str, Any]) -> str:
    """Input: Console state. Output: blocker reason. Explain disabled Continue consistently."""
    readiness_work = readiness_blocker_current_work(state)
    if readiness_work is not None:
        return "; ".join(str(item) for item in readiness_work.get("details", []) if str(item))
    source_bridge = state.get("source_bridge", {}) if isinstance(state.get("source_bridge"), dict) else {}
    current_work = state.get("current_work", {}) if isinstance(state.get("current_work"), dict) else {}
    details = "; ".join(str(item) for item in current_work.get("details", []) if str(item))
    return str(source_bridge.get("reason", "")) or details


def _render_workflow_progress(state: dict[str, Any]) -> str:
    """Input: Console state. Output: HTML. Render active workflow controls from authoritative permissions."""
    active = state.get("active_workflow", {}) if isinstance(state.get("active_workflow"), dict) else {}
    if (state.get("start_preparation") or {}).get("status") in {"preparing", "validating", "committing"}:
        return ('<p role="status">Local Start preflight is preparing knowledge. No live work has started.</p>'
                '<form method="post" action="/actions/run"><input type="hidden" name="action" '
                'value="workflow-stop"><button>Stop workflow</button></form>')
    if not active.get("exists"):
        return ""
    allowed = _workflow_action_state(state)
    blocker_reason = _maintenance_blocker_reason(state)
    control = state.get("runtime_control", {})
    scope = control.get('original_batch_recovery') or {}
    scope_text = (f"<p>Original batch: {int(scope.get('checked', 0))}/{int(scope.get('planned', 0))} checked; "
                  f"{int(scope.get('remaining', 0))} remaining. Resume automatically maintains knowledge, "
                  "waits for cooldown and recovers existing work. No new research or Alpha submission.</p>"
                  if scope.get('authorized') else '')
    if control.get("legacy_authority_required"):
        blocker_reason = "Runtime authority required; legacy run needs reconciliation. Defaults cannot authorize Resume."
    case = control.get("recovery_case") or {}
    notification_text = ""
    if (control.get('status') == 'blocked' and control.get('reason') == 'runtime_budget_exhausted'
            and not control.get('original_batch_scope_id') and not control.get('legacy_authority_required')
            and case.get('status') not in MAINTENANCE_BLOCKING_STATUSES):
        notification_text += f"""
<form method="post" action="/actions/run">
<input type="hidden" name="action" value="workflow-renew-runtime">
<input type="hidden" name="run_id" value="{escape(str(active.get('run_id', '')))}">
<input type="hidden" name="expected_runtime_revision" value="{escape(str(control.get('request_revision', '')))}">
<label>Additional runtime <select name="additional_seconds"><option value="21600">6 hours</option><option value="43200">12 hours</option></select></label>
<p>Elapsed time and simulation usage are preserved. Only the runtime limit increases.</p>
<button>Authorize extension and resume</button>
</form>
"""
    if case.get("status") == "maintenance_approved":
        notification_text = "<p role='status'>Repair approved; waiting for successful verification. Workflow remains blocked.</p>"
    if case.get("status") == "awaiting_maintenance_confirmation":
        labels = {"not_requested": "No maintenance-chat delivery attempted",
                  "pending": "Waiting for maintenance-chat delivery (event-triggered)",
                  "claimed": "Delivery uncertain; automatic duplicate delivery disabled",
                  "failed": "Maintenance-chat delivery failed; request preserved locally",
                  "delivery_uncertain": "Delivery uncertain; automatic duplicate delivery disabled",
                  "queued": "Request queued to Codex; awaiting receipt and human confirmation",
                  "notified": "Maintenance chat notified; waiting for human confirmation"}
        label = labels.get((case.get("notification") or {}).get("status"), "Notification state unavailable")
        verification = {"maintenance_verification_stale": "Maintenance verification is outdated for current source",
                        "maintenance_verification_invalid": "Maintenance verification evidence is incomplete or invalid",
                        "maintenance_evidence_invalid": "Maintenance case evidence is invalid"}.get(case.get("verification_error"), "")
        error = str((case.get("notification") or {}).get("error", ""))
        detail = ". ".join(value for value in (verification, label, error) if value)
        notification_text = f"<p role='status'>{escape(detail)}. Code repair requires human confirmation.</p>"
    if control.get("desired_state") == "running" and control.get("status") in {"running", "waiting"}:
        return scope_text + '<p>Workflow is running automatically.</p><form method="post" action="/actions/run"><input type="hidden" name="action" value="workflow-stop"><button>Stop workflow</button></form>'
    if allowed["continue_workflow"]:
        continue_control = f"""
<form method="post" action="/actions/run">
<input type="hidden" name="action" value="workflow-auto-continue">
<input type="hidden" name="state_hash" value="{_workflow_action_hash(state)}">
<input type="hidden" name="expected_runtime_revision" value="{escape(str(control.get('request_revision', '')))}">
<button>Resume workflow</button>
</form>
"""
    else:
        readiness_blocked = readiness_blocker_current_work(state) is not None
        continue_control = f"""
<div class="blocked-action">
<p>{escape("Readiness blocker" if readiness_blocked else "Maintenance blocker")}: {escape(blocker_reason)}</p>
<button disabled>Resume workflow</button>
</div>
"""
    return f"""
{scope_text}<p>Active run: <code>{escape(str(active.get('run_id', 'none')))}</code></p>
{notification_text}
{continue_control}
<form method="post" action="/actions/run">
<input type="hidden" name="action" value="workflow-stop">
<button>Stop workflow</button>
</form>
"""


def _state_hash(state: dict[str, Any]) -> str:
    """Input: Console state. Output: short digest. Detect stale client/server state snapshots."""
    payload = json.dumps(state, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _workflow_action_hash(state: dict[str, Any]) -> str:
    """Input: Console state. Output: stable digest. Version only fields that authorize Start/Resume."""
    active = state.get("active_workflow") if isinstance(state.get("active_workflow"), dict) else {}
    control = state.get("runtime_control") if isinstance(state.get("runtime_control"), dict) else {}
    bridge = state.get("source_bridge") if isinstance(state.get("source_bridge"), dict) else {}
    payload = {
        "active_run_id": active.get("run_id"),
        "active_exists": active.get("exists"),
        "active_status": active.get("status"),
        "active_stage": active.get("current_stage"),
        "request_revision": control.get("request_revision"),
        "desired_state": control.get("desired_state"),
        "runtime_boundary_reason": control.get('reason') if control.get('status') == 'blocked' else '',
        "legacy_authority_required": control.get("legacy_authority_required"),
        "original_batch_scope_id": control.get("original_batch_scope_id"),
        "maintenance_case": {key: (control.get("recovery_case") or {}).get(key) for key in ("case_id", "status")},
        "source_action": bridge.get("action"),
        "research_round": {key: (state.get("research_rounds") or {}).get(key)
                           for key in ("current_round_id", "status", "stop_reason")},
        "research_handoff": {key: (state.get("research_handoff") or {}).get(key)
                             for key in ("status", "stop_reason", "next_action")},
        "option_ids": [row.get("option_id") for row in state.get("option_cards", []) if isinstance(row, dict)],
        "start_preparation": {key: (state.get("start_preparation") or {}).get(key)
                              for key in ("request_id", "status")},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def assert_workflow_action_current(form: dict[str, Any], state: dict[str, Any]) -> None:
    """Input: posted form and current state. Output: None or ValueError. Refuse stale Start/Resume actions."""
    if form.get("action") not in {"workflow-start-from-option", "workflow-auto-continue"}:
        return
    preparation = state.get("start_preparation") or {}
    if form.get("action") == "workflow-start-from-option" and preparation.get("status") in {"preparing", "validating"}:
        from wqb.console_start import _selection
        if preparation.get("selection") == _selection(form):
            return
    if str(form.get("state_hash", "")) != _workflow_action_hash(state):
        raise ValueError("stale workflow state; refresh before starting or resuming")
    if form.get("action") == "workflow-start-from-option":
        control = state.get("runtime_control") or {}
        revision = control.get("request_revision", "")
        if "expected_runtime_revision" in form and form["expected_runtime_revision"] != revision:
            raise ValueError("stale runtime intent; refresh before resuming")
        form["expected_runtime_revision"] = revision
    if form.get("action") == "workflow-auto-continue":
        control = state.get("runtime_control") if isinstance(state.get("runtime_control"), dict) else {}
        if control.get('status') == 'blocked' and control.get('reason') in {'runtime_budget_exhausted', 'step_budget_exhausted'}:
            raise ValueError('runtime limit reached; Resume cannot renew authority')
        if control.get("legacy_authority_required"):
            raise ValueError("runtime authority required; legacy run needs reconciliation")
        if (control.get("recovery_case") or {}).get("status") in MAINTENANCE_BLOCKING_STATUSES:
            raise ValueError("maintenance repair requires human confirmation and verified resolution")
        if str(form.get("expected_runtime_revision", "")) != str(control.get("request_revision", "")):
            raise ValueError("stale runtime intent; refresh before resuming")


def _code_commit() -> str:
    """Input: none. Output: git commit or unknown. Expose local code revision without requiring network."""
    global CODE_COMMIT_CACHE
    if CODE_COMMIT_CACHE:
        return CODE_COMMIT_CACHE
    try:
        CODE_COMMIT_CACHE = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
    except Exception:
        CODE_COMMIT_CACHE = "unknown"
    return CODE_COMMIT_CACHE


def _render_data_coverage_panel(data_coverage: dict[str, Any]) -> str:
    """Input: data coverage summary. Output: HTML. Render capture controls and live persisted progress counts."""
    semantic = data_coverage.get('semantic_compile') or {}
    coverage = semantic.get('coverage') or {}
    cancel = ''
    if semantic.get('status') in {'running', 'publishing'} and semantic.get('job_id'):
        cancel = ('<form method="post" action="/actions/run">'
                  '<input type="hidden" name="action" value="cancel-semantic-knowledge">'
                  f'<input type="hidden" name="semantic_job_id" value="{escape(str(semantic["job_id"]), quote=True)}">'
                  '<button>Cancel knowledge compile</button></form>')
    return (
        '<form method="post" action="/actions/run">'
        '<input type="hidden" name="action" value="capture-platform-data-fields">'
        '<label><input type="checkbox" name="enable_live_api"> enable_live_api</label>'
        '<input name="fields_per_scope" type="number" min="0" value="100">'
        '<input name="max_scopes" type="number" min="0" value="40">'
        '<button>Capture platform data fields</button></form>'
        '<form method="post" action="/actions/run">'
        '<input type="hidden" name="action" value="compile-data-ledger">'
        '<button>Compile data ledger from raw</button></form>'
        '<form method="post" action="/actions/run">'
        '<input type="hidden" name="action" value="compile-semantic-knowledge">'
        '<button>Compile semantic knowledge</button></form>'
        '<form method="post" action="/actions/run">'
        '<input type="hidden" name="action" value="compile-research-records">'
        '<button>Summarize research records</button></form>'
        f'{cancel}<p>Semantic knowledge: {escape(str(semantic.get("status", "not_started")))}; '
        f'{escape(str(semantic.get("error", "")))}; notification: '
        f'{escape(str((semantic.get("notification") or {}).get("status", "not_needed")))}</p>'
        f'<p>Indexed operator targets: {escape(str(coverage.get("indexed_target_count", "unknown")))}; '
        f'covered: {escape(str(coverage.get("covered_target_count", "unknown")))}; '
        f'remaining: {escape(str(coverage.get("remaining_target_count", "unknown")))}. '
        f'Research sources remaining: {escape(str(coverage.get("remaining_research_source_count", "unknown")))}</p>'
        f'<p>{escape(str(coverage.get("source_gaps") or "Coverage remains partial; no measured promotion without validated experiments."))}</p>'
        f"<p>Fields: <code>{escape(str(data_coverage.get('field_count', 0)))}</code></p>"
        f"<p>Scopes: <code>{escape(str(data_coverage.get('scope_count', 0)))}</code></p>"
        f"<p>Data sets: <code>{escape(str(data_coverage.get('data_set_count', 0)))}</code></p>"
        f"<p>Errors: <code>{escape(str(data_coverage.get('error_count', 0)))}</code></p>"
    )


def render_runtime_fragments(state: dict[str, Any]) -> dict[str, Any]:
    """Input: Console state. Output: named HTML fragments. Render all runtime regions refreshed by browser polling."""
    return {
        "objective": _render_objective_summary(state),
        "timeline": _render_timeline(state.get("timeline", [])),
        "current_work": _render_current_work(state.get("current_work", {})),
        "workflow_progress": _render_workflow_controls(state),
        "platform_data": _render_data_coverage_panel({**state.get("data_coverage", {}), 'semantic_compile': state.get('semantic_compile', {})}),
        "recent_jobs": _render_recent_jobs(state.get("jobs", [])),
        "ai_checkpoints": _render_ai_checkpoints(state.get("ai_checkpoints", [])),
        "allowed_actions": _workflow_action_state(state),
        "strategy_progress": state.get("strategy_progress", {"rows": [], "counts": {}}),
        "runtime_control": state.get("runtime_control", {}),
        "server_revision": CONSOLE_SERVER_REVISION,
        "code_revision": LOADED_CODE_REVISION,
        "code_commit": _code_commit(),
        "state_hash": _state_hash(state),
        "action_revision": _workflow_action_hash(state),
        "last_refreshed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "refresh_interval_ms": CONSOLE_REFRESH_INTERVAL_MS,
    }


def _render_ai_checkpoints(rows: list[dict[str, Any]]) -> str:
    """Input: checkpoint rows. Output: HTML. Render GPT/Codex judgment queue."""
    if not rows:
        return "<div class='empty'>No AI judgment checkpoints.</div>"
    items = []
    for row in rows:
        items.append(
            "<li><strong>{kind}</strong> <span>{status}</span><p>{reason}</p></li>".format(
                kind=escape(str(row.get("checkpoint_type", "ai_checkpoint"))),
                status=escape(str(row.get("status", ""))),
                reason=escape(str(row.get("reason", ""))),
            )
        )
    return "<ul>" + "".join(items) + "</ul>"


def _render_workflow_controls(state: dict[str, Any]) -> str:
    """Input: Console state dict. Output: HTML str. Keep Start, preparation Stop and Resume controls live across polling."""
    option_rows = [card for card in state.get("option_cards", []) if isinstance(card, dict)]
    cards = _normalized_option_rows(option_rows)
    scopes = [scope for scope in state.get("startable_scopes", []) if isinstance(scope, dict)]
    if not _workflow_action_state(state)["start_workflow"]:
        return "<h3>Workflow Progress</h3>" + _render_workflow_progress(state)
    return f"""
<h3>Research Start</h3>
<form method="post" action="/actions/run">
<input type="hidden" name="action" value="workflow-start-from-option">
<input type="hidden" name="state_hash" value="{_workflow_action_hash(state)}">
{_render_option_controls(cards)}
{_render_scope_controls(scopes)}
<input type="hidden" name="enable_live_api" value="on">
<button>Start workflow</button><span>Local Start preflight runs before mission creation.</span>
</form>
"""


def render_dashboard(state: dict[str, Any]) -> str:
    """Input: console state dict. Output: HTML. Render dashboard, controls, and progress summary."""
    fragments = render_runtime_fragments(state)
    decision_controls = f"<div data-runtime-fragment='workflow_progress'>{fragments['workflow_progress']}</div>"
    body = f"""
<div class="control-center">
<div id="stale-console-banner" class="wide" hidden>Console state changed; actions are temporarily disabled while the page refreshes.</div>
<section class="wide hero"><h2>Objective and Gate Summary</h2><div data-runtime-fragment='objective'>{fragments["objective"]}</div></section>
<section class="timeline-panel"><h2>Runtime Timeline</h2><div data-runtime-fragment='timeline'>{fragments["timeline"]}</div></section>
<section class="current-work"><h2>Current Work</h2><div data-runtime-fragment='current_work'>{fragments["current_work"]}</div></section>
<section class="wide"><h2>Decisions and Approvals</h2>{decision_controls}</section>
<section class="wide"><h2>Strategy Progress</h2><p id="runtime-connection" role="status">Connecting</p><div style="overflow:auto"><table style="width:100%;text-align:left;table-layout:fixed"><thead><tr><th>Alpha / expression</th><th>Status</th><th>Checks</th><th>Next action</th></tr></thead><tbody id="strategy-progress-body"></tbody></table></div></section>
<section class="wide"><h2>AI judgments</h2><div data-runtime-fragment='ai_checkpoints'>{fragments["ai_checkpoints"]}</div></section>
<section class="wide"><h2>Recent Jobs</h2><div data-runtime-fragment='recent_jobs'>{fragments["recent_jobs"]}</div></section>
</div>
<script>
let refreshInFlight = false;
let streamConnected = false;
const initialServerRevision = {json.dumps(fragments["server_revision"])};
const initialCodeRevision = {json.dumps(fragments["code_revision"])};
let lastStateHash = {json.dumps(fragments["state_hash"])};
function disableWorkflowButtons(){{
  for (const button of document.querySelectorAll('button')) {{
    button.disabled = true;
  }}
}}
function applySnapshot(fragments){{
    if ((fragments.server_revision && fragments.server_revision !== initialServerRevision) ||
        (fragments.code_revision && fragments.code_revision !== initialCodeRevision)) {{
      const banner = document.getElementById('stale-console-banner');
      if (banner) banner.hidden = false;
      disableWorkflowButtons();
      window.location.reload();
      return;
    }}
    lastStateHash = fragments.state_hash || lastStateHash;
    for (const [name, html] of Object.entries(fragments)) {{
      if (typeof html !== 'string') continue;
      const target = document.querySelector('[data-runtime-fragment="' + name + '"]');
      if (target && target.dataset.lastHtml !== html) {{
        const preservedInputs = Array.from(target.querySelectorAll('input, select, textarea')).filter(el => el.type !== 'hidden').map(el => ({{name:el.name, value:el.value, checked:el.checked}}));
        target.innerHTML = html;
        target.dataset.lastHtml = html;
        for (const saved of preservedInputs) {{
          for (const el of target.querySelectorAll('input, select, textarea')) {{
            if (el.name !== saved.name || el.type === 'hidden') continue;
            if (el.type === 'checkbox' || el.type === 'radio') {{
              if (el.value === saved.value) el.checked = saved.checked;
            }} else el.value = saved.value;
          }}
        }}
      }}
    }}
    const body = document.getElementById('strategy-progress-body');
    const rows = fragments.strategy_progress?.rows || [];
    body.replaceChildren();
    for (const row of rows) {{
      const tr = document.createElement('tr');
      for (const value of [row.alpha_id || row.expression || row.expression_hash || row.key, row.status, (row.failures || []).join(', ') || (row.hard_pass ? 'Passed' : ''), row.next_action]) {{
        const td = document.createElement('td');
        td.textContent = String(value || '');
        td.style.overflowWrap = 'anywhere';
        td.style.padding = '8px 4px';
        tr.appendChild(td);
      }}
      body.appendChild(tr);
    }}
    document.getElementById('runtime-connection').textContent = (streamConnected ? 'Live' : 'Polling fallback') + ' | ' + (fragments.last_refreshed_at || '') + ' | ' + rows.length + ' strategies';
}}
async function refreshState(){{
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {{
    const response = await fetch('/api/fragments', {{cache:'no-store'}});
    if (!response.ok) throw new Error('Snapshot unavailable');
    applySnapshot(await response.json());
  }} catch (error) {{
    document.getElementById('runtime-connection').textContent = 'Disconnected; retrying';
  }} finally {{
    refreshInFlight = false;
  }}
}}
if (window.EventSource) {{
  const stream = new EventSource('/api/events');
  stream.addEventListener('snapshot', event => {{streamConnected = true; applySnapshot(JSON.parse(event.data));}});
  stream.addEventListener('heartbeat', () => {{streamConnected = true;}});
  stream.onerror = () => {{streamConnected = false; refreshState();}};
}}
refreshState();
setInterval(() => {{if (!streamConnected) refreshState();}}, {CONSOLE_REFRESH_INTERVAL_MS});
</script>
"""
    return _html_page("BrainWorkflow Control Center", body)


def _render_proposal_decision_form(proposal: dict[str, Any]) -> str:
    """Input: proposal row. Output: HTML form. Render lifecycle controls for one persisted proposal."""
    proposal_id = escape(str(proposal.get("proposal_id", "")))
    current_status = str(proposal.get("status", ""))
    options = "".join(
        f'<option value="{status}"{" selected" if status == current_status else ""}>{status}</option>'
        for status in PROPOSAL_DECISION_STATUSES
    )
    return (
        '<form method="post" action="/proposals/decision">'
        f'<input type="hidden" name="proposal_id" value="{proposal_id}">'
        f'<select name="status">{options}</select>'
        '<textarea name="user_decision" placeholder="decision rationale"></textarea>'
        '<button>Update decision</button></form>'
    )


def _render_inline_proposals(proposals: list[dict[str, Any]]) -> str:
    """Input: proposal rows. Output: HTML. Render proposal decisions in the Control Center."""
    rows = "".join(
        f"<li><strong>{escape(str(row.get('title', '')))}</strong> <span>{escape(str(row.get('status', '')))}</span>"
        f"{_render_proposal_decision_form(row)}</li>"
        for row in proposals
        if isinstance(row, dict)
    ) or "<li>No proposals.</li>"
    return "<ul>" + rows + "</ul>"


def render_proposals(proposals: list[dict[str, Any]]) -> str:
    """Input: proposal rows. Output: HTML. Render proposal inbox and creation form."""
    rows = "".join(
        f"<li><code>{escape(str(row.get('proposal_id', '')))}</code> {escape(str(row.get('status', '')))} {escape(str(row.get('title', '')))}"
        f"{_render_proposal_decision_form(row)}</li>"
        for row in proposals
    ) or "<li>No proposals.</li>"
    body = f"""
<section class="wide"><h2>Workflow Proposal Inbox</h2><ul>{rows}</ul></section>
<section class="wide"><h2>New Proposal</h2>
<form method="post" action="/proposals/create">
<select name="issue_type">
<option value="template_innovation">template_innovation</option>
<option value="data_coverage">data_coverage</option>
<option value="benchmark_rule">benchmark_rule</option>
<option value="workflow_gate">workflow_gate</option>
</select>
<textarea name="summary" placeholder="summary"></textarea>
<textarea name="evidence_paths" placeholder="evidence paths"></textarea>
<select name="affected_modules">
<option value="template_library">template_library</option>
<option value="data_coverage">data_coverage</option>
<option value="console">console</option>
<option value="orchestrator">orchestrator</option>
<option value="knowledge_compile">knowledge_compile</option>
</select>
<button>Create Proposal</button>
</form></section>
"""
    return _html_page("Workflow Proposal Inbox", body)


def _truthy(value: Any) -> bool:
    """Input: form value. Output: bool. Normalize checkbox values."""
    if isinstance(value, list):
        return any(_truthy(item) for item in value)
    return str(value).lower() in {"1", "true", "yes", "on"}


def _capture_date(form: dict[str, Any]) -> str:
    """Input: capture form values. Output: ISO date. Select the raw capture directory date before process launch."""
    value = str(form.get("data_capture_date", "")).strip()
    if not value:
        return datetime.now(timezone.utc).date().isoformat()
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        raise ValueError("data_capture_date must be an ISO date") from None


def _job_metadata(action: str, paths: ConsolePaths, form: dict[str, Any], command: list[str]) -> dict[str, Any]:
    """Input: action, paths, form, command. Output: durable metadata. Bind capture progress to its launched raw directory."""
    metadata = {"form": dict(form)}
    if action == "workflow-auto-continue":
        from wqb.workflow_state import discover_active_workflow

        active = discover_active_workflow(paths.runs_root)
        if active.run_dir is not None:
            metadata["run_dir"] = str(active.run_dir)
    if action == "capture-platform-data-fields":
        capture_date = command[command.index("--data-capture-date") + 1]
        metadata["capture_dir"] = str(paths.knowledge_root / "raw" / "platform" / "data_fields" / capture_date)
    return metadata


def _record_async_console_job_context(paths: ConsolePaths, job: Any) -> None:
    """Input: Console paths and terminal async job. Output: none. Record recovery context without breaking a job watcher."""
    if str(getattr(job, "status", "")) not in {"completed", "failed", "refused", "timed_out", "blocked", "paused", "waiting_for_user"}:
        return
    try:
        record_console_job_context(paths, job, next_command="python -m wqb.cli workflow-status")
    except Exception:
        return


def _freshness_clean(paths: ConsolePaths) -> bool:
    """Input: console paths. Output: bool. Check whether compiled knowledge is current enough for research start."""
    summary = load_console_state(paths).get("freshness", {})
    return (
        bool(summary.get("exists"))
        and bool(summary.get("valid"))
        and int(summary.get("record_count", 0)) > 0
        and int(summary.get("stale_count", 0)) == 0
        and int(summary.get("missing_count", 0)) == 0
    )


def _option_rows(paths: ConsolePaths) -> list[dict[str, Any]]:
    """Input: console paths. Output: normalized option rows. Load durable research options."""
    path = existing_decision_artifact_path(
        paths.knowledge_root,
        "research_option_cards.jsonl",
    )
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return _normalized_option_rows(rows)


def _selected_option(paths: ConsolePaths, selected_option_id: str) -> dict[str, Any]:
    """Input: paths and selected option id. Output: option row. Validate console research selection."""
    selected = str(selected_option_id).strip()
    if not selected:
        raise ValueError("select a research option card before starting workflow")
    for row in _option_rows(paths):
        if str(row.get("option_id", "")) == selected:
            return row
    raise ValueError(f"selected research option is not available: {selected}")


def _option_objective(row: dict[str, Any]) -> str:
    """Input: option row. Output: objective string. Derive workflow objective from the selected card."""
    return str(row.get("title") or row.get("primary_incentive") or "Research option").strip()


def _selected_scope(form: dict[str, Any]) -> dict[str, Any]:
    """Input: action form. Output: concrete scope dict. Validate the user-selected ledger scope fields."""
    try:
        selected = form.get("selected_scope")
        payload = json.loads(str(selected)) if selected else form
        if not isinstance(payload, dict):
            raise ValueError
        region = str(payload.get("region", payload.get("selected_region", ""))).strip().upper()
        delay = int(payload.get("delay", payload.get("selected_delay", "")))
        universe = str(payload.get("universe", payload.get("selected_universe", ""))).strip().upper()
    except (TypeError, ValueError):
        raise ValueError("select a concrete region, delay, and universe scope before starting workflow") from None
    if not region or delay < 0 or not universe:
        raise ValueError("select a concrete region, delay, and universe scope before starting workflow")
    return {"region": region, "delay": delay, "universe": universe}


def _matches_scope(record: dict[str, Any], scope: dict[str, Any]) -> bool:
    """Input: ledger row and requested scope. Output: bool. Match one ledger row using available scope fields first."""
    if "available_scopes" in record:
        return any(
            isinstance(item, dict)
            and str(item.get("region", "")).upper() == scope["region"]
            and item.get("delay") == scope["delay"]
            and str(item.get("universe", "")).upper() == scope["universe"]
            for item in record.get("available_scopes", [])
        )

    def values(available_key: str, fallback_key: str) -> list[Any]:
        if available_key in record:
            value = record.get(available_key)
            return value if isinstance(value, list) else []
        return [record.get(fallback_key)]

    return (
        scope["region"] in {str(value).upper() for value in values("available_regions", "region")}
        and scope["delay"] in {int(value) for value in values("available_delays", "delay") if str(value).strip()}
        and scope["universe"] in {str(value).upper() for value in values("available_universes", "universe")}
    )


def _ledger_record(row: dict[str, Any], scope: dict[str, Any]) -> DataLedgerRecord:
    """Input: ledger JSON row and selected scope. Output: data record. Adapt raw ledger metadata for template selection."""
    return DataLedgerRecord(
        dataset_id=str(row.get("dataset_id", "")), dataset_name=str(row.get("dataset_name", "")),
        field_id=str(row.get("field_id", "")), field_type=str(row.get("field_type", "")),
        region=scope["region"], delay=scope["delay"], universe=scope["universe"],
        semantic_tags=[str(tag) for tag in row.get("semantic_tags", []) if str(tag)] if isinstance(row.get("semantic_tags"), list) else [],
        coverage=0.0, alpha_count=0, user_count=0, simulation_usage_count=0, submitted_usage_count=0,
        last_used_at="", best_result_label="", correlation_risk="unknown", source_paths=[],
    )


def _require_scoped_readiness(paths: ConsolePaths, scope: dict[str, Any]) -> None:
    """Input: console paths and scope. Output: none. Reuse strict research readiness before starting."""
    report = evaluate_run_readiness(
        paths.knowledge_root,
        mode="research",
        batch_size=30,
        live_api_enabled=True,
        region=str(scope["region"]),
        delay=int(scope["delay"]),
        universe=str(scope["universe"]),
    )
    if report.blocked:
        codes = ", ".join(issue.code for issue in report.issues if issue.level == "block") or "blocked"
        raise ValueError(f"data coverage readiness blocked for selected scope: {codes}")


def _validate_option_data_coverage(paths: ConsolePaths, option: dict[str, Any], scope: dict[str, Any],
                                  *, research_policy: dict | None = None) -> None:
    """Input: console paths, selected option, selected scope. Output: none. Require certified data and real templates."""
    ledger_path = data_ledger_path_for_knowledge(paths.knowledge_root)
    matching_rows: list[dict[str, Any]] = []
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and _matches_scope(row, scope):
                matching_rows.append(row)
    if not matching_rows:
        raise ValueError("data coverage ledger has no records matching the selected option scope")
    research_rows = []
    for row in matching_rows:
        if row.get("source_quality") != "platform_raw_capture" or row.get("coverage_status") != "measured_raw":
            continue
        try:
            if float(row.get("coverage", 0.0)) <= 0.0:
                continue
        except (TypeError, ValueError):
            continue
        research_rows.append(row)
    if not research_rows:
        raise ValueError("data coverage ledger for the selected scope is not certified measured platform coverage")
    from wqb.hypothesis_selection import paired_scout_enabled
    if paired_scout_enabled(research_policy):
        from wqb.workflow_stage_adapters import create_start_snapshot
        create_start_snapshot(paths.knowledge_root, str(option['option_id']), scope, research_policy=research_policy)
        return
    templates = load_template_library_from_knowledge(paths.knowledge_root)
    incentive = str(option.get("primary_incentive", ""))
    has_template_match = False
    for row in research_rows:
        compatible_ids = row.get("compatible_template_ids")
        if not isinstance(compatible_ids, list) or not compatible_ids:
            continue
        selected = select_templates_for_data(templates, _ledger_record(row, scope), incentive, len(templates), **scope)
        if set(str(item) for item in compatible_ids) & {template.template_id for template in selected}:
            has_template_match = True
            break
    if not has_template_match:
        raise ValueError("data coverage ledger for the selected scope has no compatible templates in the template library")
    _require_scoped_readiness(paths, scope)


def build_action_command(action: str, paths: ConsolePaths, form: dict[str, Any] | None = None) -> list[str]:
    """Input: console action, paths, form. Output: CLI command. Enforce UI safety gates."""
    data = dict(form or {})
    if action == "workflow-start":
        raise ValueError("direct console workflow-start is disabled; select an option card and measured scope")
    if action == "plan-research-options" and not _truthy(data.get("enable_live_api")):
        raise ValueError("enable_live_api is required before refreshing platform option cards")
    if action == "capture-platform-data-fields" and not _truthy(data.get("enable_live_api")):
        raise ValueError("enable_live_api is required before capturing platform data fields")
    if action == "workflow-start-from-option":
        option = _selected_option(paths, str(data.get("selected_option_id", "")))
        scope = _selected_scope(data)
        normalized = {
            "objective": f"{_option_objective(option)} | scope: {scope['region']} D{scope['delay']} {scope['universe']}",
            "selected_option_id": str(option.get("option_id")),
            "selected_region": scope["region"],
            "selected_delay": scope["delay"],
            "selected_universe": scope["universe"],
            "enable_live_api": _truthy(data.get("enable_live_api")),
        }
        command = build_raw_cli_command("workflow-start", paths, normalized)
        command[2] = "wqb.console_start"
        return command
    normalized = {key: (_truthy(value) if key in {"enable_live_api", "confirm_submit"} else value) for key, value in data.items()}
    if action == "capture-platform-data-fields":
        normalized["data_capture_date"] = _capture_date(data)
    return build_raw_cli_command(action, paths, normalized)


def _active_auto_continue_job(paths: ConsolePaths) -> ConsoleJob | None:
    """Input: Console paths. Output: active ConsoleJob or none. Load the current durable auto-continue job."""
    for row in load_job_history(paths.job_root, paths.knowledge_root):
        if row.get("action") != "workflow-auto-continue" or row.get("status") != "running":
            continue
        fields = ConsoleJob.__dataclass_fields__
        return ConsoleJob(**{key: row[key] for key in fields if key in row})
    return None


def _active_start_job(paths: ConsolePaths) -> ConsoleJob | None:
    """Input: ConsolePaths. Output: ConsoleJob or None. Reuse the current durable local preparation job."""
    from wqb.console_start import read_start_request, PREPARING_STATUSES
    request = read_start_request(paths.runs_root)
    if request.get("status") not in PREPARING_STATUSES | {"committing"}:
        return None
    for row in load_job_history(paths.job_root, paths.knowledge_root):
        if row.get("job_id") == request.get("job_id") and row.get("status") in {"created", "running"}:
            fields = ConsoleJob.__dataclass_fields__
            return ConsoleJob(**{key: row[key] for key in fields if key in row})
    return None


def _complete_start_job(paths: ConsolePaths, completed: ConsoleJob) -> None:
    """Input: ConsolePaths and terminal job. Output: None. Continue only a successful, current Start receipt."""
    from wqb.console_start import (
        read_start_request, start_request_guard, _blocked_request, _notify_blocked_request, PREPARING_STATUSES,
    )
    from wqb.runtime_control import read_runtime_control
    _record_async_console_job_context(paths, completed)
    if completed.status != "completed" or completed.exit_code != 0:
        blocked = None
        with start_request_guard(paths.runs_root):
            current = read_start_request(paths.runs_root)
            if (current.get("job_id") == completed.job_id
                    and current.get("status") in PREPARING_STATUSES | {"committing"}):
                blocked = _blocked_request(paths, current, {
                    "issues": [{"code": "start_worker_failed", "level": "block",
                                "path": completed.stderr_path,
                                "message": completed.error or "Start worker failed or timed out"}]},
                    completed.error or "Start worker did not complete; inspect job output")
        if blocked is not None:
            _notify_blocked_request(paths, blocked)
        return
    try:
        receipt = json.loads(Path(completed.stdout_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    current = read_start_request(paths.runs_root)
    if not isinstance(receipt, dict) or receipt.get("passed") is not True or receipt.get("status") != "completed":
        return
    revision = receipt.get("runtime_request_revision")
    if (not isinstance(revision, str) or not revision or current.get("status") != "completed"
            or current.get("request_id") != receipt.get("request_id")
            or current.get("runtime_request_revision") != revision
            or not receipt.get("run_dir") or current.get("run_dir") != receipt["run_dir"]):
        return
    if read_runtime_control(receipt["run_dir"]).get("request_revision") != revision:
        return
    run_console_action(paths, {"action": "workflow-auto-continue", "expected_runtime_revision": revision})


def _run_console_action_unlocked(paths: ConsolePaths, form: dict[str, Any], action: str) -> Any:
    """Input: Console paths, form, and action. Output: ConsoleJob. Create and run one Console action without duplicate checks."""
    try:
        command = build_action_command(action, paths, form)
    except Exception as error:
        job = create_job(paths.job_root, action or "unknown-action", [], paths.workflow_root, {"form": dict(form)})
        completed = finish_job(job, "refused", exit_code=2, error=str(error))
        record_console_job_context(paths, completed, next_command="python -m wqb.cli workflow-status")
        return completed
    job = create_job(paths.job_root, action, command, paths.workflow_root, _job_metadata(action, paths, form, command))
    try:
        if action == "workflow-start-from-option":
            from wqb.console_start import register_start
            request = register_start(paths, form, job.job_id)
            if request["job_id"] != job.job_id:
                finish_job(job, "refused", exit_code=2, error="duplicate Start; existing preparation retained")
                active = _active_start_job(paths)
                if active is not None:
                    return active
                raise ValueError("Start preparation changed; inspect its durable request")
            job.command.extend(["--start-request-id", request["request_id"]])
            job.metadata["start_request_id"] = request["request_id"]
            return start_job_async(job, on_complete=lambda completed: _complete_start_job(paths, completed))
        if action in ASYNC_CONSOLE_ACTIONS:
            started = start_job_async(job, on_complete=lambda completed: _record_async_console_job_context(paths, completed))
            return started
        completed = run_job(job)
    except Exception as error:
        completed = finish_job(job, "failed", exit_code=1, error=str(error))
        if action == "workflow-start-from-option":
            _complete_start_job(paths, completed)
            return completed
    record_console_job_context(paths, completed, next_command="python -m wqb.cli workflow-status")
    return completed


def run_console_action(paths: ConsolePaths, form: dict[str, Any]) -> Any:
    """Input: console paths and action form. Output: ConsoleJob. Run or refuse one durable console action."""
    action = str(form.get("action", ""))
    if action == 'cancel-semantic-knowledge':
        from wqb.console_jobs import cancel_semantic_job
        job = create_job(paths.job_root, action, ['internal:cancel-semantic-knowledge'], paths.workflow_root)
        try:
            receipt = cancel_semantic_job(paths.knowledge_root, str(form.get('semantic_job_id', '')))
            Path(job.stdout_path).write_text(json.dumps(receipt), encoding='utf-8')
            job = replace(job, metadata=dict(job.metadata, cancellation=receipt),
                          status_message=receipt.get('reason') or 'Knowledge compile cancellation recorded')
            return finish_job(job, 'completed', exit_code=0)
        except (ValueError, OSError, TimeoutError) as error:
            return finish_job(job, 'refused', exit_code=2, error=str(error))
    if action == "workflow-start-from-option":
        with START_JOB_LOCK:
            active = _active_start_job(paths)
            if active is not None:
                from wqb.console_start import _selection, read_start_request
                if read_start_request(paths.runs_root).get("selection") != _selection(form):
                    raise ValueError("another Console Start preparation is active; Stop it before changing options")
                return active
            state = load_runtime_state(paths)
            allowed = _workflow_action_state(state)
            if (state.get("active_workflow") or {}).get("exists") and not allowed["start_workflow"]:
                if not allowed["continue_workflow"]:
                    active_worker = _active_auto_continue_job(paths)
                    if active_worker is not None:
                        return active_worker
                    raise ValueError("existing workflow cannot resume; inspect current blockers before Start")
                control = state.get("runtime_control") or {}
                revision = form.get("expected_runtime_revision")
                if not isinstance(revision, str) or not revision:
                    raise ValueError("existing workflow requires runtime authority before Resume")
                if revision != control.get("request_revision"):
                    raise ValueError("stale runtime intent; refresh before resuming")
                return run_console_action(paths, {"action": "workflow-auto-continue", "expected_runtime_revision": revision})
            return _run_console_action_unlocked(paths, form, action)
    if action == 'workflow-renew-runtime':
        from wqb.runtime_control import renew_runtime_budget
        from wqb.workflow_state import discover_active_workflow
        with AUTO_CONTINUE_JOB_LOCK:
            if _active_auto_continue_job(paths) is not None:
                raise ValueError('workflow worker is active; renewal refused')
            active = discover_active_workflow(paths.runs_root)
            if active.run_dir is None or str(active.run_dir.name) != str(form.get('run_id', '')):
                raise ValueError('active run changed; refresh before renewal')
            renewed = renew_runtime_budget(active.run_dir, int(form.get('additional_seconds', '0')),
                                           str(form.get('expected_runtime_revision', '')))
            return _run_console_action_unlocked(paths, {
                'action': 'workflow-auto-continue',
                'expected_runtime_revision': renewed['request_revision'],
            }, 'workflow-auto-continue')
    if action == "workflow-stop":
        from wqb.console_start import cancel_start
        cancelled = cancel_start(paths.runs_root)
        from wqb.workflow_state import discover_active_workflow
        if cancelled and discover_active_workflow(paths.runs_root).run_dir is None:
            job = create_job(paths.job_root, action, ["internal:cancel-start"], paths.workflow_root,
                             {"form": dict(form), "start_request_id": cancelled.get("request_id")})
            return finish_job(job, "completed", exit_code=0)
    if action == "workflow-auto-continue":
        with AUTO_CONTINUE_JOB_LOCK:
            active = _active_auto_continue_job(paths)
            if active is not None:
                return active
            return _run_console_action_unlocked(paths, form, action)
    return _run_console_action_unlocked(paths, form, action)


def create_console_proposal(paths: ConsolePaths, form: dict[str, Any]) -> Any:
    """Input: console paths and proposal form. Output: ConsoleJob. Persist proposal and context artifacts."""
    job = create_job(paths.job_root, "create-proposal", ["internal:create-proposal"], paths.workflow_root, {"form": dict(form)})
    try:
        proposal = create_proposal_from_form(decision_artifacts_root(paths.knowledge_root), form)
        completed = finish_job(job, "completed", exit_code=0, error="")
        record_console_job_context(paths, completed, next_command=f"review proposal {proposal.proposal_id}")
        return completed
    except Exception as error:
        completed = finish_job(job, "failed", exit_code=1, error=str(error))
        record_console_job_context(paths, completed, next_command="open workflow proposal inbox")
        return completed


def update_console_proposal_decision(paths: ConsolePaths, form: dict[str, Any]) -> Any:
    """Input: console paths and decision form. Output: ConsoleJob. Persist one proposal lifecycle decision."""
    proposal_id = str(form.get("proposal_id", "")).strip()
    status = str(form.get("status", "")).strip()
    user_decision = str(form.get("user_decision", ""))
    job = create_job(paths.job_root, "update-proposal-decision", ["internal:update-proposal-decision"], paths.workflow_root, {"form": dict(form)})
    try:
        proposal_dir = existing_decision_artifact_path(
            paths.knowledge_root,
            "workflow_change_proposals.jsonl",
        ).parent
        update_workflow_proposal_decision(proposal_dir, proposal_id, status, user_decision)
        completed = finish_job(job, "completed", exit_code=0, error="")
        record_console_job_context(paths, completed, next_command="open workflow proposal inbox")
        return completed
    except Exception as error:
        completed = finish_job(job, "failed", exit_code=1, error=str(error))
        record_console_job_context(paths, completed, next_command="open workflow proposal inbox")
        return completed


def _file_token(path: Path) -> str:
    """Input: path. Output: mtime token. Track local evidence changes for cache invalidation."""
    try:
        stat = path.stat()
    except OSError:
        return ""
    return f"{path}:{stat.st_mtime_ns}:{stat.st_size}"


def _console_state_signature(paths: ConsolePaths) -> str:
    """Input: Console paths. Output: digest. Invalidate state cache when local workflow evidence changes."""
    patterns = [
        "*/run_state.json",
        "*/run_state_checkpoint.json",
        "*/workflow_events.jsonl",
        "*/rate_limit_state.json",
        "*/source_run_lock.json",
        "*/stages/scout_seed/source_bridge_binding.json",
        "console_jobs/*/job.json",
        "start_preflight/*.json",
        "console_start/*.json",
        "start_preflight/notifications/*.json",
        "*/runtime/recovery/*.json",
        "*/runtime/maintenance_verification/notifications/*.json",
    ]
    tokens = [_file_token(paths.milestone_path), _file_token(paths.todo_path)]
    for pattern in patterns:
        tokens.extend(
            _file_token(path)
            for path in sorted(paths.runs_root.glob(pattern))
            if path.is_file()
        )
    return hashlib.sha256("\n".join(tokens).encode("utf-8")).hexdigest()


def _load_cached_console_state(server: Any, paths: ConsolePaths) -> dict[str, Any]:
    """Input: Console server and paths. Output: state dict. Reuse expensive state snapshots during poll bursts."""
    now = time.monotonic()
    lock = getattr(server, "console_state_cache_lock", None)
    cache = getattr(server, "console_state_cache", None)
    if lock is None or cache is None:
        return load_console_state(paths)
    signature = _console_state_signature(paths)
    with lock:
        cached_state = cache.get("state")
        loaded_at = float(cache.get("loaded_at", 0.0))
        cached_signature = str(cache.get("signature", ""))
        if (
            isinstance(cached_state, dict)
            and cached_signature == signature
            and now - loaded_at < CONSOLE_STATE_CACHE_TTL_SECONDS
        ):
            return cached_state
        fresh_state = load_console_state(paths)
        cache["state"] = fresh_state
        cache["loaded_at"] = time.monotonic()
        cache["signature"] = signature
        return fresh_state


def _invalidate_cached_console_state(server: Any) -> None:
    """Input: Console server. Output: none. Force the next poll to observe a posted action or proposal change."""
    lock = getattr(server, "console_state_cache_lock", None)
    cache = getattr(server, "console_state_cache", None)
    if lock is None or cache is None:
        return
    with lock:
        cache["state"] = None
        cache["loaded_at"] = 0.0
        cache["signature"] = ""


def _load_runtime_snapshot(server: Any, paths: ConsolePaths) -> dict[str, Any]:
    """Input: HTTP server and ConsolePaths. Output: dict. Refresh hot state without cold resource traversal."""
    with server.console_runtime_lock:
        now = time.monotonic()
        cached = server.console_runtime_cache
        if cached.get('state') is not None and now - cached['loaded_at'] < CONSOLE_EVENT_INTERVAL_SECONDS:
            return cached['state']
        # Reuse the last page's cold summary, never recompute knowledge for SSE or polling.
        with server.console_state_cache_lock:
            base = server.console_state_cache.get('state') or {}
        state = {**base, **load_runtime_state(paths)}
        state['timeline'] = build_timeline_rows(state)
        state['current_work'] = select_current_work(state, state['timeline'])
        cached.update(state=state, loaded_at=now)
        return state


class ConsoleRequestHandler(BaseHTTPRequestHandler):
    def _send_events(self, paths: ConsolePaths) -> None:
        """Input: ConsolePaths. Output: None. Stream local snapshots and heartbeats; reconnect periodically."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()
        started, last_hash = time.monotonic(), None
        try:
            while time.monotonic() - started < CONSOLE_STREAM_SECONDS:
                try:
                    payload = render_runtime_fragments(_load_runtime_snapshot(self.server, paths))
                    changed = payload['state_hash'] != last_hash
                    event = 'snapshot' if changed else 'heartbeat'
                    last_hash = payload['state_hash']
                    if not changed:
                        payload = {key: payload[key] for key in ('server_revision', 'last_refreshed_at', 'state_hash')}
                except Exception:
                    event, payload = 'runtime-error', {'message': 'Local runtime snapshot unavailable'}
                self.wfile.write(f'event: {event}\ndata: {json.dumps(payload)}\n\n'.encode('utf-8'))
                self.wfile.flush()
                time.sleep(CONSOLE_EVENT_INTERVAL_SECONDS)
        except (OSError, ConnectionError):
            pass

    def _send_html(self, html: str, status: int = 200) -> None:
        """Input: HTML and status. Output: none. Send one HTML response."""
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        """Input: JSON payload and status. Output: none. Send one JSON response."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_form(self) -> dict[str, Any]:
        """Input: request body. Output: parsed form dict. Decode URL-encoded POST data."""
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(data)
        return {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}

    def do_GET(self) -> None:
        """Input: HTTP GET. Output: response. Route read-only console pages."""
        parsed = urlparse(self.path)
        paths: ConsolePaths = self.server.console_paths  # type: ignore[attr-defined]
        if parsed.path == '/api/health':
            self._send_json({
                'app': 'BrainWorkflow',
                'workflow_root': str(paths.workflow_root.resolve()),
                'runs_root': str(paths.runs_root.resolve()),
                'knowledge_root': str(paths.knowledge_root.resolve()),
                'server_revision': CONSOLE_SERVER_REVISION,
                'code_revision': LOADED_CODE_REVISION,
            })
            return
        if parsed.path == '/api/events':
            self._send_events(paths)
            return
        if parsed.path == "/api/fragments":
            try:
                self._send_json(render_runtime_fragments(_load_runtime_snapshot(self.server, paths)))
            except ConnectionError:
                return
            except Exception:
                self._send_json({'error': 'Local runtime snapshot unavailable'}, status=503)
            return
        state = _load_cached_console_state(self.server, paths)
        if parsed.path == "/api/state":
            self._send_json(state)
            return
        if parsed.path == "/proposals":
            self._send_html(render_proposals(state.get("proposals", [])))
            return
        self._send_html(render_dashboard(state))

    def do_POST(self) -> None:
        """Input: HTTP POST. Output: response. Run approved local actions or create proposals."""
        paths: ConsolePaths = self.server.console_paths  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        expected_host = f"{self.server.server_address[0]}:{self.server.server_address[1]}"
        origin = urlparse(self.headers.get("Origin", ""))
        if (self.headers.get("Host") != expected_host or origin.scheme != "http"
                or origin.netloc != expected_host):
            self._send_html("<html><body>Foreign POST origin refused.</body></html>", status=403)
            return
        form = self._read_form()
        try:
            if parsed.path == "/proposals/create":
                completed = create_console_proposal(paths, form)
                _invalidate_cached_console_state(self.server)
                self._send_html(f"<html><body>Proposal job {escape(completed.status)}. <a href='/proposals'>Back</a></body></html>")
                return
            if parsed.path == "/proposals/decision":
                completed = update_console_proposal_decision(paths, form)
                _invalidate_cached_console_state(self.server)
                self._send_html(f"<html><body>Decision job {escape(completed.status)}. <a href='/proposals'>Back</a></body></html>")
                return
            if parsed.path == "/actions/run":
                if form.get("action") in {"workflow-start-from-option", "workflow-auto-continue"}:
                    assert_workflow_action_current(form, load_console_state(paths))
                completed = run_console_action(paths, form)
                _invalidate_cached_console_state(self.server)
                if completed.status == "running":
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                self._send_html(f"<html><body>Job {escape(completed.status)}: <code>{escape(completed.job_id)}</code> <a href='/'>Back</a></body></html>")
                return
        except Exception as error:  # local console should show recoverable errors instead of crashing.
            self._send_html(f"<html><body><h1>Action refused</h1><p>{escape(str(error))}</p><a href='/'>Back</a></body></html>", status=400)
            return
        self._send_html("<html><body>Not found</body></html>", status=404)

    def log_message(self, format: str, *args: Any) -> None:
        """Input: log message. Output: none. Silence default local request logging."""
        return


def make_console_server(host: str, port: int, paths: ConsolePaths) -> ThreadingHTTPServer:
    """Input: host, port, paths. Output: HTTP server. Construct a local Workflow Console server."""
    server = ThreadingHTTPServer((host, port), ConsoleRequestHandler)
    server.console_paths = paths  # type: ignore[attr-defined]
    server.console_state_cache = {"loaded_at": 0.0, "state": None, "signature": ""}  # type: ignore[attr-defined]
    server.console_state_cache_lock = threading.Lock()  # type: ignore[attr-defined]
    server.console_runtime_lock = threading.Lock()
    server.console_runtime_cache = {'state': None, 'loaded_at': 0.0}
    return server


def run_console(
    host: str = "127.0.0.1",
    port: int = 8765,
    knowledge_root: str | Path | None = None,
    runs_root: str | Path | None = None,
    open_browser: bool = True,
) -> dict[str, Any]:
    """Input: server config. Output: startup summary. Run the local console until interrupted."""
    paths = default_console_paths(knowledge_root, runs_root)
    server = make_console_server(host, port, paths)
    from wqb.maintenance_notifications import dispatch_startup_notifications
    threading.Thread(target=dispatch_startup_notifications, args=(paths.runs_root,),
                     name="maintenance-startup-notice", daemon=True).start()
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}"
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return {"url": url, "host": actual_host, "port": actual_port}
