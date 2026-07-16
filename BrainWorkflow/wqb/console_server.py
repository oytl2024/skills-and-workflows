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


def _html_page(title: str, body: str) -> str:
    """Input: title and body HTML. Output: full HTML page. Render the local console shell."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title>"
        "<style>"
        "body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f7f8fa;color:#20242a}"
        "header{background:#243447;color:white;padding:16px 24px}"
        "main{padding:20px;display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}"
        "section{background:white;border:1px solid #d8dde5;border-radius:8px;padding:16px}"
        "button,input,select,textarea{font:inherit;margin:4px 0;padding:8px} textarea{width:100%;min-height:90px}"
        "code{background:#edf1f5;padding:2px 4px;border-radius:4px} .wide{grid-column:1/-1}"
        "</style></head><body>"
        f"<header><h1>{escape(title)}</h1></header><main>{body}</main></body></html>"
    )


def render_dashboard(state: dict[str, Any]) -> str:
    """Input: console state dict. Output: HTML. Render dashboard, controls, and progress summary."""
    readiness = state.get("readiness", {})
    freshness = state.get("freshness", {})
    cards = state.get("option_cards", [])
    jobs = state.get("jobs", [])
    active = state.get("active_workflow", {})
    card_items = "".join(f"<li>{escape(str(card.get('title', 'untitled')))}</li>" for card in cards[:5]) or "<li>No option cards.</li>"
    job_items = "".join(
        f"<li><code>{escape(str(job.get('job_id', '')))}</code> {escape(str(job.get('action', '')))} {escape(str(job.get('status', '')))}</li>"
        for job in jobs[:8]
    ) or "<li>No console jobs.</li>"
    body = f"""
<section><h2>Readiness</h2><p>Passed: <code>{escape(str(readiness.get('passed', readiness.get('exists', False))))}</code></p><p>Blocked: <code>{escape(str(readiness.get('blocked', False)))}</code></p></section>
<section><h2>Knowledge Freshness</h2><p>Stale: <code>{escape(str(freshness.get('stale_count', 0)))}</code></p><p>Missing: <code>{escape(str(freshness.get('missing_count', 0)))}</code></p></section>
<section><h2>Research Control</h2>
<form method="post" action="/actions/run"><input type="hidden" name="action" value="readiness-check"><button>Run Readiness</button></form>
<form method="post" action="/actions/run"><input type="hidden" name="action" value="plan-research-options"><label><input type="checkbox" name="enable_live_api"> enable_live_api</label><button>Refresh Option Cards</button></form>
<form method="post" action="/actions/run"><input type="hidden" name="action" value="workflow-start"><input name="objective" placeholder="Objective"><input name="selected_option_id" placeholder="option-1"><button>Start Workflow</button></form>
<form method="post" action="/actions/run"><input type="hidden" name="action" value="workflow-continue"><button>Continue Workflow</button></form>
</section>
<section><h2>Knowledge Maintenance</h2>
<form method="post" action="/actions/run"><input type="hidden" name="action" value="compile-research-records"><button>Compile Research Records</button></form>
<form method="post" action="/actions/run"><input type="hidden" name="action" value="bootstrap-knowledge"><button>Compile Platform Materials</button></form>
<form method="post" action="/actions/run"><input type="hidden" name="action" value="knowledge-health-check"><button>Knowledge Health Check</button></form>
</section>
<section><h2>Research Options</h2><ul>{card_items}</ul></section>
<section><h2>Research Progress</h2><p>Active run: <code>{escape(str(active.get('run_id', 'none')))}</code></p><ul>{job_items}</ul></section>
<section class="wide"><h2>Schedule Preview</h2><pre>{escape(str(state.get('schedule', {}).get('preview', ''))[:2000])}</pre></section>
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
<input name="issue_type" placeholder="issue_type">
<textarea name="summary" placeholder="summary"></textarea>
<textarea name="evidence_paths" placeholder="evidence paths"></textarea>
<input name="affected_modules" placeholder="affected_modules">
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


def build_action_command(action: str, paths: ConsolePaths, form: dict[str, Any] | None = None) -> list[str]:
    """Input: console action, paths, form. Output: CLI command. Enforce UI safety gates."""
    data = dict(form or {})
    if action == "plan-research-options" and not _truthy(data.get("enable_live_api")):
        raise ValueError("enable_live_api is required before refreshing platform option cards")
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
