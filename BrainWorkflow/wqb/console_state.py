from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_freshness import evaluate_freshness, load_freshness_manifest
from wqb.research_record import load_research_record
from wqb.workflow_events import read_workflow_events
from wqb.workflow_paths import resolve_project_root, resolve_run_root
from wqb.workflow_state import diagnose_state_consistency, discover_active_workflow


@dataclass(frozen=True)
class ConsolePaths:
    project_root: Path
    workflow_root: Path
    knowledge_root: Path
    runs_root: Path
    milestone_path: Path
    todo_path: Path
    job_root: Path


def default_console_paths(
    knowledge_root: str | Path | None = None,
    runs_root: str | Path | None = None,
) -> ConsolePaths:
    """Input: optional roots. Output: ConsolePaths. Resolve default local console paths."""
    workflow_root = Path(__file__).resolve().parents[1]
    project_root = resolve_project_root(workflow_root)
    knowledge = Path(knowledge_root) if knowledge_root is not None else project_root / "knowledge"
    runs = resolve_run_root(workflow_root, runs_root)
    return ConsolePaths(
        project_root=project_root,
        workflow_root=workflow_root,
        knowledge_root=knowledge,
        runs_root=runs,
        milestone_path=project_root / "milestone.md",
        todo_path=project_root / "todo.md",
        job_root=runs / "console_jobs",
    )


def _read_json(path: Path) -> dict[str, Any]:
    """Input: JSON path. Output: dict. Return empty dict for absent or invalid files."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: rows. Skip blank and invalid lines."""
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
    return rows


def _latest_readiness(runs_root: Path) -> dict[str, Any]:
    """Input: runs root. Output: readiness summary. Read newest readiness report."""
    reports = sorted(runs_root.glob("**/readiness_report.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not reports:
        return {"exists": False}
    payload = _read_json(reports[0])
    payload["exists"] = True
    payload["path"] = str(reports[0])
    return payload


def _freshness_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: freshness counts. Evaluate the manifest when present."""
    manifest = knowledge_root / "wiki" / "80_maintenance" / "freshness_manifest.json"
    if not manifest.exists():
        return {"exists": False, "valid": False, "record_count": 0, "stale_count": 0, "missing_count": 0, "records": []}
    try:
        records = load_freshness_manifest(manifest, strict=True)
        statuses = evaluate_freshness(records, date.today(), artifact_root=knowledge_root)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"exists": True, "valid": False, "record_count": 0, "stale_count": 0, "missing_count": 0, "records": []}
    return {
        "exists": True,
        "valid": True,
        "record_count": len(statuses),
        "stale_count": len([status for status in statuses if status.stale]),
        "missing_count": len([status for status in statuses if not status.artifact_exists]),
        "records": [status.__dict__ for status in statuses],
    }


def _data_coverage_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: data coverage summary. Read latest raw data-field capture manifest."""
    root = knowledge_root / "raw" / "platform" / "data_fields"
    captures = sorted([path for path in root.glob("*") if path.is_dir()])
    valid_captures = [(capture, _read_json(capture / "manifest.json")) for capture in captures]
    valid_captures = [(capture, manifest) for capture, manifest in valid_captures if manifest]
    if not valid_captures:
        return {"exists": False, "latest_capture_dir": "", "field_count": 0, "scope_count": 0, "data_set_count": 0, "error_count": 0, "status": ""}
    latest, manifest = valid_captures[-1]
    return {
        "exists": bool(manifest),
        "latest_capture_dir": str(latest),
        "generated_at": str(manifest.get("generated_at", "")),
        "field_count": int(manifest.get("field_count", 0)),
        "scope_count": int(manifest.get("scope_count", 0)),
        "data_set_count": int(manifest.get("data_set_count", 0)),
        "error_count": int(manifest.get("error_count", 0)),
        "status": str(manifest.get("status", "")),
    }


def _schedule_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: schedule preview. Read current schedule Markdown."""
    path = knowledge_root / "wiki" / "70_decisions" / "research_schedule.md"
    if not path.exists():
        return {"exists": False, "path": str(path), "preview": ""}
    text = path.read_text(encoding="utf-8")
    return {"exists": True, "path": str(path), "preview": text[:2000]}


def _job_rows(job_root: Path) -> list[dict[str, Any]]:
    """Input: job root. Output: job rows. Read job records newest first."""
    rows = [_read_json(path) for path in job_root.glob("*/job.json")]
    rows = [row for row in rows if row]
    return sorted(rows, key=lambda row: str(row.get("updated_at", row.get("created_at", ""))), reverse=True)


def _milestone_summary(path: Path) -> dict[str, str]:
    """Input: milestone path. Output: active loop summary. Extract a readable recovery anchor."""
    if not path.exists():
        return {"exists": "false", "active_loop": "", "path": str(path)}
    text = path.read_text(encoding="utf-8")
    active_loop = ""
    for line in text.splitlines():
        if line.startswith("Loop name:"):
            active_loop = line.split("`")[1] if "`" in line else line.replace("Loop name:", "").strip()
            break
    return {"exists": "true", "active_loop": active_loop, "path": str(path)}


def _active_workflow_summary(runs_root: Path) -> tuple[dict[str, Any], Path | None]:
    """Input: runs root. Output: workflow summary and run dir. Read active Orchestrator state once."""
    discovery = discover_active_workflow(runs_root)
    if discovery.state is None and discovery.run_dir is None:
        return {"exists": False}, None
    if discovery.state is None:
        return {
            "exists": True,
            "run_id": discovery.run_id,
            "state_exists": False,
            "diagnostics": discovery.diagnostics,
        }, discovery.run_dir
    state = discovery.state
    consistency_diagnostics = (
        diagnose_state_consistency(discovery.run_dir, state)
        if discovery.run_dir is not None
        else []
    )
    diagnostics = list(dict.fromkeys([*discovery.diagnostics, *consistency_diagnostics]))
    return (
        {
            "exists": True,
            "state_exists": True,
            "run_id": state.run_id,
            "run_dir": state.run_dir,
            "status": state.status,
            "current_stage": state.current_stage,
            "next_action": state.next_action,
            "waiting_for_user": state.waiting_for_user,
            "consistent": not diagnostics,
            "diagnostics": diagnostics,
            "recovered_read_only": discovery.recovered,
        },
        discovery.run_dir,
    )


def _approved_queue_with_diagnostics(runs_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Input: runs root. Output: queue rows and diagnostics. Read approved queue without crashing dashboard."""
    direct = runs_root / "approved_candidates.jsonl"
    paths = [direct] if direct.exists() else sorted(runs_root.glob("*/approved_candidates.jsonl"))
    rows: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            diagnostics.append(f"unreadable_file:{path.name}")
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                diagnostics.append(f"malformed_json:{path.name}")
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows, list(dict.fromkeys(diagnostics))


def _research_record_summary(run_dir: Path | None) -> dict[str, Any]:
    """Input: active run dir or None. Output: research record summary. Read optional record safely."""
    if run_dir is None:
        return {"exists": False}
    path = run_dir / "research_record.json"
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        record = load_research_record(path)
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError):
        return {"exists": False, "path": str(path)}
    return {"exists": True, "path": str(path), **record.__dict__}


def load_console_state(paths: ConsolePaths) -> dict[str, Any]:
    """Input: console paths. Output: JSON-safe state dict. Aggregate dashboard data."""
    decisions = paths.knowledge_root / "wiki" / "70_decisions"
    proposals = _read_jsonl(decisions / "workflow_change_proposals.jsonl")
    proposal_counts = Counter(str(row.get("status", "unclassified")) for row in proposals)
    active_workflow, active_run_dir = _active_workflow_summary(paths.runs_root)
    workflow_events = [] if active_run_dir is None else [event.__dict__ for event in read_workflow_events(active_run_dir)]
    approved_queue, queue_diagnostics = _approved_queue_with_diagnostics(paths.runs_root)
    return {
        "readiness": _latest_readiness(paths.runs_root),
        "freshness": _freshness_summary(paths.knowledge_root),
        "data_coverage": _data_coverage_summary(paths.knowledge_root),
        "option_cards": _read_jsonl(decisions / "research_option_cards.jsonl"),
        "schedule": _schedule_summary(paths.knowledge_root),
        "jobs": _job_rows(paths.job_root),
        "proposals": proposals,
        "proposal_counts": dict(proposal_counts),
        "milestone": _milestone_summary(paths.milestone_path),
        "active_workflow": active_workflow,
        "workflow_events": workflow_events,
        "approved_queue": approved_queue,
        "queue_diagnostics": queue_diagnostics,
        "research_record": _research_record_summary(active_run_dir),
    }
