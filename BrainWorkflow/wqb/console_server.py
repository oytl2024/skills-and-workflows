from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import webbrowser

from wqb.console_context import record_console_job_context
from wqb.console_jobs import build_cli_command as build_raw_cli_command
from wqb.console_jobs import create_job, finish_job, run_job, start_job_async
from wqb.console_proposals import create_proposal_from_form
from wqb.console_state import ConsolePaths, default_console_paths, load_console_state
from wqb.data_ledger import DataLedgerRecord
from wqb.option_cards import fallback_option_id, normalize_option_card_row, normalize_option_card_rows
from wqb.run_readiness import evaluate_run_readiness
from wqb.template_library import load_template_library, select_templates_for_data
from wqb.workflow_proposals import update_workflow_proposal_decision


PROPOSAL_DECISION_STATUSES = (
    "accepted_for_wiki",
    "accepted_for_implementation",
    "accepted_as_experiment",
    "rejected",
    "deferred",
)

ASYNC_CONSOLE_ACTIONS = {"capture-platform-data-fields"}


def _fallback_option_id(index: int) -> str:
    """Input: valid option order. Output: fallback option ID. Normalize cards without durable IDs."""
    return fallback_option_id(index)


def _html_page(title: str, body: str) -> str:
    """Input: title and body HTML. Output: full HTML page. Render the local console shell."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title>"
        "<style>"
        "body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#F6F7F9;color:#18202A}"
        "header{background:#18202A;color:white;padding:14px 24px;display:flex;justify-content:space-between;align-items:center}"
        "main{min-height:calc(100vh - 56px)}"
        ".workspace,.control-center{padding:18px 22px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}"
        "section{background:white;border:1px solid #D9E0E8;border-radius:8px;padding:14px}"
        ".ledger-strip{display:flex;gap:8px;flex-wrap:wrap}"
        ".badge{border:1px solid #D9E0E8;border-radius:999px;padding:4px 8px;font-size:12px;background:#fff}"
        ".badge-ready{border-color:#167C80;color:#167C80}.badge-warn{border-color:#B7791F;color:#B7791F}.badge-blocked{border-color:#B42318;color:#B42318}"
        ".option-card{display:block;border:1px solid #D9E0E8;border-radius:8px;padding:10px;margin:8px 0;cursor:pointer}"
        ".option-card:has(input:checked){border-color:#167C80;box-shadow:inset 3px 0 0 #167C80}"
        ".option-title{display:block;font-weight:600}.option-meta{display:block;font-size:12px;color:#4B5563;margin-top:3px}"
        "button,input,select,textarea{font:inherit;margin:4px 0;padding:7px 9px}button{cursor:pointer}textarea{width:100%;min-height:90px}"
        "code,pre{font-family:Consolas,monospace}.wide{grid-column:1/-1}.empty{color:#6B7280}"
        ".timeline{list-style:none;margin:0;padding:0}.timeline-row{display:grid;grid-template-columns:14px minmax(0,1fr);gap:10px;padding:10px 0;border-top:1px solid #D9E0E8}.timeline-row:first-child{border-top:0}.timeline-dot{width:9px;height:9px;margin-top:6px;border-radius:50%;background:#6B7280}.state-running .timeline-dot,.state-completed .timeline-dot{background:#167C80}.state-blocked .timeline-dot,.state-failed .timeline-dot{background:#B42318}.state-waiting .timeline-dot,.state-paused .timeline-dot{background:#B7791F}.timeline-row span{display:block;color:#4B5563;font-size:12px;margin-top:2px}.timeline-row p{margin:5px 0}.timeline-row code{font-size:12px;overflow-wrap:anywhere}"
        "@media(max-width:760px){.workspace,.control-center{grid-template-columns:1fr;padding:14px}.wide{grid-column:auto}}"
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
        return "<div class='empty'>No research options. Refresh option cards with live API authorization.</div>"
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
            f"<input type=\"radio\" name=\"selected_option_id\" value=\"{escape(option_id)}\">"
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


def render_dashboard(state: dict[str, Any]) -> str:
    """Input: console state dict. Output: HTML. Render dashboard, controls, and progress summary."""
    readiness = state.get("readiness", {})
    freshness = state.get("freshness", {})
    data_coverage = state.get("data_coverage", {})
    option_rows = [card for card in state.get("option_cards", []) if isinstance(card, dict)]
    cards = _normalized_option_rows(option_rows)
    scopes = [scope for scope in state.get("startable_scopes", []) if isinstance(scope, dict)]
    jobs = state.get("jobs", [])
    job_items = "".join(
        f"<li><code>{escape(str(job.get('job_id', '')))}</code> {escape(str(job.get('action', '')))} {escape(str(job.get('status', '')))}</li>"
        for job in jobs[:8] if isinstance(job, dict)
    ) or "<li>No console jobs.</li>"
    readiness_state = "ready" if readiness.get("passed", readiness.get("exists", False)) else "blocked"
    freshness_state = "ready" if freshness.get("valid") and not freshness.get("stale_count") and not freshness.get("missing_count") else "warn"
    coverage_state = "ready" if data_coverage.get("status") == "completed" and not data_coverage.get("error_count") else "warn"
    ledger_strip = "".join(
        [
            _badge("Readiness", readiness.get("passed", readiness.get("exists", False)), readiness_state),
            _badge("Freshness", f"stale {freshness.get('stale_count', 0)} / missing {freshness.get('missing_count', 0)}", freshness_state),
            _badge("Data fields", data_coverage.get("field_count", 0), coverage_state),
        ]
    )
    research_start_form = f"""
<form method="post" action="/actions/run">
<input type="hidden" name="action" value="workflow-start-from-option">
{_render_option_controls(cards)}
{_render_scope_controls(scopes)}
<button>Start selected workflow</button>
</form>
"""
    knowledge_forms = """
<form method="post" action="/actions/run"><input type="hidden" name="action" value="readiness-check"><button>Run readiness check</button></form>
<form method="post" action="/actions/run"><input type="hidden" name="action" value="compile-research-records"><button>Compile research records</button></form>
<form method="post" action="/actions/run"><input type="hidden" name="action" value="plan-research-options"><label><input type="checkbox" name="enable_live_api"> Enable live API</label><button>Refresh research options</button></form>
<form method="post" action="/actions/run"><input type="hidden" name="action" value="knowledge-health-check"><button>Check knowledge health</button></form>
"""
    data_coverage_panel = (
        "<form method=\"post\" action=\"/actions/run\">"
        "<input type=\"hidden\" name=\"action\" value=\"capture-platform-data-fields\">"
        "<label><input type=\"checkbox\" name=\"enable_live_api\"> enable_live_api</label>"
        "<select name=\"max_scopes\">"
        "<option value=\"0\">All configured scopes</option>"
        "<option value=\"4\">First 4 scopes</option>"
        "<option value=\"10\">First 10 scopes</option>"
        "</select>"
        "<button>Capture platform data fields</button></form>"
        "<form method=\"post\" action=\"/actions/run\">"
        "<input type=\"hidden\" name=\"action\" value=\"compile-data-ledger\">"
        "<button>Compile data ledger from raw</button></form>"
        f"<p>Fields: <code>{escape(str(data_coverage.get('field_count', 0)))}</code></p>"
        f"<p>Scopes: <code>{escape(str(data_coverage.get('scope_count', 0)))}</code></p>"
        f"<p>Data sets: <code>{escape(str(data_coverage.get('data_set_count', 0)))}</code></p>"
        f"<p>Errors: <code>{escape(str(data_coverage.get('error_count', 0)))}</code></p>"
    )
    body = f"""
<div class="control-center">
<section class="wide hero"><h2>Objective and Gate Summary</h2><div class="ledger-strip">{ledger_strip}</div><p>Current work: <strong data-current-work-title>{escape(str(state.get("current_work", {}).get("title", "No active workflow")))}</strong></p></section>
<section class="timeline-panel"><h2>Runtime Timeline</h2>{_render_timeline(state.get("timeline", []))}</section>
<section class="current-work"><h2>Current Work</h2>{_render_current_work(state.get("current_work", {}))}</section>
<section class="wide"><h2>Decisions and Approvals</h2>{research_start_form}{_render_inline_proposals(state.get("proposals", []))}</section>
<section class="wide"><h2>AI Checkpoints</h2>{_render_ai_checkpoints(state.get("ai_checkpoints", []))}</section>
<section><h2>Maintain Knowledge</h2>{knowledge_forms}</section>
<section><h2>Platform Data</h2>{data_coverage_panel}</section>
<section class="wide"><h2>Recent Jobs</h2><ul>{job_items}</ul></section>
</div>
<script>
async function refreshState(){{
  const response = await fetch('/api/state');
  if (!response.ok) return;
  const state = await response.json();
  const marker = document.querySelector('[data-current-work-title]');
  if (marker && state.current_work) marker.textContent = state.current_work.title || 'No active work';
}}
setInterval(refreshState, 5000);
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
    path = paths.knowledge_root / "wiki" / "70_decisions" / "research_option_cards.jsonl"
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


def _validate_option_data_coverage(paths: ConsolePaths, option: dict[str, Any], scope: dict[str, Any]) -> None:
    """Input: console paths, selected option, selected scope. Output: none. Require certified data and real templates."""
    ledger_path = paths.knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl"
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
    if any(row.get("source_quality") != "platform_raw_capture" or row.get("coverage_status") != "measured_raw" for row in matching_rows):
        raise ValueError("data coverage ledger for the selected scope is not certified measured platform coverage")
    template_path = paths.knowledge_root / "wiki" / "30_templates" / "template_library.jsonl"
    templates = load_template_library(template_path)
    incentive = str(option.get("primary_incentive", ""))
    for row in matching_rows:
        compatible_ids = row.get("compatible_template_ids")
        if not isinstance(compatible_ids, list) or not compatible_ids:
            raise ValueError("data coverage ledger for the selected scope has no compatible templates")
        selected = select_templates_for_data(templates, _ledger_record(row, scope), incentive, len(templates), **scope)
        if not set(str(item) for item in compatible_ids) & {template.template_id for template in selected}:
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
        if not _freshness_clean(paths):
            raise ValueError("knowledge maintenance is required before starting research workflow")
        _validate_option_data_coverage(paths, option, scope)
        normalized = {
            "objective": f"{_option_objective(option)} | scope: {scope['region']} D{scope['delay']} {scope['universe']}",
            "selected_option_id": str(option.get("option_id")),
            "selected_region": scope["region"],
            "selected_delay": scope["delay"],
            "selected_universe": scope["universe"],
        }
        return build_raw_cli_command("workflow-start", paths, normalized)
    normalized = {key: (_truthy(value) if key in {"enable_live_api", "confirm_submit"} else value) for key, value in data.items()}
    return build_raw_cli_command(action, paths, normalized)


def run_console_action(paths: ConsolePaths, form: dict[str, Any]) -> Any:
    """Input: console paths and action form. Output: ConsoleJob. Run or refuse one durable console action."""
    action = str(form.get("action", ""))
    try:
        command = build_action_command(action, paths, form)
    except Exception as error:
        job = create_job(paths.job_root, action or "unknown-action", [], paths.workflow_root, {"form": dict(form)})
        completed = finish_job(job, "refused", exit_code=2, error=str(error))
        record_console_job_context(paths, completed, next_command="python -m wqb.cli workflow-status")
        return completed
    job = create_job(paths.job_root, action, command, paths.workflow_root, {"form": dict(form)})
    try:
        if action in ASYNC_CONSOLE_ACTIONS:
            started = start_job_async(job)
            return started
        completed = run_job(job)
    except Exception as error:
        completed = finish_job(job, "failed", exit_code=1, error=str(error))
    record_console_job_context(paths, completed, next_command="python -m wqb.cli workflow-status")
    return completed


def create_console_proposal(paths: ConsolePaths, form: dict[str, Any]) -> Any:
    """Input: console paths and proposal form. Output: ConsoleJob. Persist proposal and context artifacts."""
    job = create_job(paths.job_root, "create-proposal", ["internal:create-proposal"], paths.workflow_root, {"form": dict(form)})
    try:
        proposal = create_proposal_from_form(paths.knowledge_root / "wiki" / "70_decisions", form)
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
        update_workflow_proposal_decision(paths.knowledge_root / "wiki" / "70_decisions", proposal_id, status, user_decision)
        completed = finish_job(job, "completed", exit_code=0, error="")
        record_console_job_context(paths, completed, next_command="open workflow proposal inbox")
        return completed
    except Exception as error:
        completed = finish_job(job, "failed", exit_code=1, error=str(error))
        record_console_job_context(paths, completed, next_command="open workflow proposal inbox")
        return completed


class ConsoleRequestHandler(BaseHTTPRequestHandler):
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
        state = load_console_state(paths)
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
        form = self._read_form()
        try:
            if parsed.path == "/proposals/create":
                completed = create_console_proposal(paths, form)
                self._send_html(f"<html><body>Proposal job {escape(completed.status)}. <a href='/proposals'>Back</a></body></html>")
                return
            if parsed.path == "/proposals/decision":
                completed = update_console_proposal_decision(paths, form)
                self._send_html(f"<html><body>Decision job {escape(completed.status)}. <a href='/proposals'>Back</a></body></html>")
                return
            if parsed.path == "/actions/run":
                completed = run_console_action(paths, form)
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
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}"
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return {"url": url, "host": actual_host, "port": actual_port}
