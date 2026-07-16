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
from wqb.console_jobs import create_job, finish_job, run_job
from wqb.console_proposals import create_proposal_from_form
from wqb.console_state import ConsolePaths, default_console_paths, load_console_state


def _fallback_option_id(index: int) -> str:
    """Input: valid option order. Output: fallback option ID. Normalize cards without durable IDs."""
    return f"option-{index}"


def _html_page(title: str, body: str) -> str:
    """Input: title and body HTML. Output: full HTML page. Render the local console shell."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title>"
        "<style>"
        "body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#F6F7F9;color:#18202A}"
        "header{background:#18202A;color:white;padding:14px 24px;display:flex;justify-content:space-between;align-items:center}"
        "main{display:grid;grid-template-columns:220px minmax(0,1fr);gap:0;min-height:calc(100vh - 56px)}"
        "nav{border-right:1px solid #D9E0E8;background:#fff;padding:16px}nav a{display:block;color:#18202A;margin-top:10px;text-decoration:none}"
        ".workspace{padding:18px 22px;display:grid;gap:14px}"
        "section{background:white;border:1px solid #D9E0E8;border-radius:8px;padding:14px}"
        ".ledger-strip{display:flex;gap:8px;flex-wrap:wrap}"
        ".badge{border:1px solid #D9E0E8;border-radius:999px;padding:4px 8px;font-size:12px;background:#fff}"
        ".badge-ready{border-color:#167C80;color:#167C80}.badge-warn{border-color:#B7791F;color:#B7791F}.badge-blocked{border-color:#B42318;color:#B42318}"
        ".option-card{display:block;border:1px solid #D9E0E8;border-radius:8px;padding:10px;margin:8px 0;cursor:pointer}"
        ".option-card:has(input:checked){border-color:#167C80;box-shadow:inset 3px 0 0 #167C80}"
        ".option-title{display:block;font-weight:600}.option-meta{display:block;font-size:12px;color:#4B5563;margin-top:3px}"
        "button,input,select,textarea{font:inherit;margin:4px 0;padding:7px 9px}button{cursor:pointer}textarea{width:100%;min-height:90px}"
        "code,pre{font-family:Consolas,monospace}.wide{grid-column:1/-1}.empty{color:#6B7280}"
        "</style></head><body>"
        f"<header><h1>{escape(title)}</h1></header><main>{body}</main></body></html>"
    )


def _badge(label: str, value: Any, state: str = "neutral") -> str:
    """Input: label, value, state. Output: HTML badge. Render one compact status marker."""
    return f"<span class='badge badge-{escape(state)}'><strong>{escape(label)}</strong> {escape(str(value))}</span>"


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
            f"<input type=\"radio\" name=\"selected_option_id\" value=\"{escape(option_id)}\" {'checked' if index == 1 else ''}>"
            f"<span class='option-title'>{escape(title)}</span>"
            f"<span class='option-meta'>{escape(incentive)} | {escape(scope)} | score {escape(str(total))}</span>"
            "</label>"
        )
    return "".join(rows)


def render_dashboard(state: dict[str, Any]) -> str:
    """Input: console state dict. Output: HTML. Render dashboard, controls, and progress summary."""
    readiness = state.get("readiness", {})
    freshness = state.get("freshness", {})
    data_coverage = state.get("data_coverage", {})
    cards = [card for card in state.get("option_cards", []) if isinstance(card, dict)]
    jobs = state.get("jobs", [])
    active = state.get("active_workflow", {})
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
<button>Start selected workflow</button>
</form>
"""
    workflow_progress = f"""
<p>Active run: <code>{escape(str(active.get('run_id', 'none')))}</code></p>
<form method="post" action="/actions/run"><input type="hidden" name="action" value="workflow-continue"><button>Continue workflow</button></form>
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
<nav>
<strong>Operations</strong>
<a href="/">Research start</a>
<a href="/proposals">Proposals</a>
</nav>
<div class="workspace">
<section class="wide"><h2>Ledger Strip</h2><div class="ledger-strip">{ledger_strip}</div></section>
<section><h2>Research Start</h2>{research_start_form}</section>
<section><h2>Workflow Progress</h2>{workflow_progress}</section>
<section><h2>Knowledge Maintenance</h2>{knowledge_forms}</section>
<section><h2>Data Coverage</h2>{data_coverage_panel}</section>
<section class="wide"><h2>Recent Jobs</h2><ul>{job_items}</ul></section>
</div>
"""
    return _html_page("Workflow Console", body)


def render_proposals(proposals: list[dict[str, Any]]) -> str:
    """Input: proposal rows. Output: HTML. Render proposal inbox and creation form."""
    rows = "".join(
        f"<li><code>{escape(str(row.get('proposal_id', '')))}</code> {escape(str(row.get('status', '')))} {escape(str(row.get('title', '')))}</li>"
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
    valid_index = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            valid_index += 1
            normalized = dict(row)
            normalized.setdefault("option_id", _fallback_option_id(valid_index))
            rows.append(normalized)
    return rows


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


def build_action_command(action: str, paths: ConsolePaths, form: dict[str, Any] | None = None) -> list[str]:
    """Input: console action, paths, form. Output: CLI command. Enforce UI safety gates."""
    data = dict(form or {})
    if action == "plan-research-options" and not _truthy(data.get("enable_live_api")):
        raise ValueError("enable_live_api is required before refreshing platform option cards")
    if action == "capture-platform-data-fields" and not _truthy(data.get("enable_live_api")):
        raise ValueError("enable_live_api is required before capturing platform data fields")
    if action == "workflow-start-from-option":
        if not _freshness_clean(paths):
            raise ValueError("knowledge maintenance is required before starting research workflow")
        option = _selected_option(paths, str(data.get("selected_option_id", "")))
        normalized = {
            "objective": _option_objective(option),
            "selected_option_id": str(option.get("option_id")),
        }
        return build_raw_cli_command("workflow-start", paths, normalized)
    if action == "workflow-start" and not _freshness_clean(paths):
        raise ValueError("knowledge maintenance is required before starting research workflow")
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


class ConsoleRequestHandler(BaseHTTPRequestHandler):
    def _send_html(self, html: str, status: int = 200) -> None:
        """Input: HTML and status. Output: none. Send one HTML response."""
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

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
            if parsed.path == "/actions/run":
                completed = run_console_action(paths, form)
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
