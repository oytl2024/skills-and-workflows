from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from itertools import product
import json
from pathlib import Path
from typing import Any

from wqb.ai_checkpoints import load_ai_checkpoints
from wqb.benchmark_rules import load_active_benchmark_rules
from wqb.data_ledger import load_data_ledger, summarize_data_ledger_authority
from wqb.knowledge_freshness import (
    evaluate_freshness,
    evaluate_knowledge_contract_health,
    load_freshness_manifest,
)
from wqb.research_record import load_research_record
from wqb.operator_semantics import load_operator_semantics
from wqb.template_library import load_template_library, template_matrix_summary
from wqb.workflow_proposals import load_workflow_proposals
from wqb.workflow_events import read_workflow_events
from wqb.workflow_paths import resolve_project_root, resolve_run_root
from wqb.workflow_state import diagnose_state_consistency, discover_active_workflow
from wqb.console_timeline import build_timeline_rows, select_current_work


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


def _valid_coverage_manifest(manifest: dict[str, Any]) -> bool:
    """Input: manifest dict. Output: bool. Check terminal status and numeric coverage counts."""
    required_counts = ("field_count", "scope_count", "data_set_count", "error_count")
    if manifest.get("status") not in {"completed", "completed_with_warnings"}:
        return False
    try:
        return all(
            key in manifest and not isinstance(manifest[key], bool)
            for key in required_counts
        ) and all(int(manifest[key]) >= 0 for key in required_counts)
    except (TypeError, ValueError, OverflowError):
        return False


def _data_coverage_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: data coverage summary. Read latest raw data-field capture manifest."""
    root = knowledge_root / "raw" / "platform" / "data_fields"
    captures = sorted([path for path in root.glob("*") if path.is_dir()])
    valid_captures = [(capture, _read_json(capture / "manifest.json")) for capture in captures]
    valid_captures = [(capture, manifest) for capture, manifest in valid_captures if _valid_coverage_manifest(manifest)]
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


def _data_authority_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: data authority summary. Summarize ledger provenance for dashboard."""
    ledger_path = knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl"
    try:
        return summarize_data_ledger_authority(load_data_ledger(ledger_path), knowledge_root)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {
            "record_count": 0,
            "authoritative_measured_count": 0,
            "seed_cache_count": 0,
            "unclassified_count": 0,
            "authoritative_ready": False,
        }


def _semantic_ledger_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: semantic summary. Count operator, matrix-ready template, and active rule records."""
    try:
        operators = load_operator_semantics(
            knowledge_root / "wiki" / "20_semantics" / "operator_semantics.jsonl"
        )
        templates = load_template_library(
            knowledge_root / "wiki" / "30_templates" / "template_library.jsonl"
        )
        rules = load_active_benchmark_rules(knowledge_root, fallback_to_defaults=False)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        operators, templates, rules = [], [], []
    matrix_ready = template_matrix_summary(templates)["matrix_ready_count"]
    return {
        "operator_semantic_count": len(operators),
        "matrix_ready_template_count": matrix_ready,
        "active_benchmark_rule_count": len(rules),
        "ready": bool(operators) and matrix_ready > 0 and bool(rules),
    }


def _data_ledger_max_age_days(knowledge_root: Path) -> int | None:
    """Input: knowledge root. Output: optional max age. Read scoped data-ledger freshness policy."""
    manifest = knowledge_root / "wiki" / "80_maintenance" / "freshness_manifest.json"
    try:
        records = load_freshness_manifest(manifest, strict=True)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    for record in records:
        if record.name == "data_ledger":
            return int(record.max_age_days)
    return None


def _row_is_startable(row: dict[str, Any], current: date, max_age_days: int | None) -> bool:
    """Input: data ledger row and freshness policy. Output: bool. Filter selectable measured scopes."""
    if max_age_days is None or max_age_days <= 0:
        return False
    if row.get("source_quality") != "platform_raw_capture" or row.get("coverage_status") != "measured_raw":
        return False
    try:
        if float(row.get("coverage", 0.0)) <= 0.0:
            return False
        source_date = date.fromisoformat(str(row.get("source_updated_at", "")))
    except (TypeError, ValueError):
        return False
    return (current - source_date).days <= max_age_days


def _startable_scopes(knowledge_root: Path) -> list[dict[str, Any]]:
    """Input: knowledge root. Output: concrete scope rows. Read measured ledger scopes suitable for console selection."""
    rows = _read_jsonl(knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl")
    scopes: set[tuple[str, int, str]] = set()
    current = date.today()
    max_age_days = _data_ledger_max_age_days(knowledge_root)
    for row in rows:
        if not _row_is_startable(row, current, max_age_days):
            continue
        if "available_scopes" in row:
            exact_scopes = row.get("available_scopes")
            if not isinstance(exact_scopes, list):
                continue
            for scope in exact_scopes:
                if not isinstance(scope, dict):
                    continue
                try:
                    normalized = (
                        str(scope.get("region", "")).strip().upper(),
                        int(scope.get("delay")),
                        str(scope.get("universe", "")).strip().upper(),
                    )
                except (TypeError, ValueError):
                    continue
                if normalized[0] and normalized[2] and normalized[1] >= 0:
                    scopes.add(normalized)
            continue
        regions = row.get("available_regions") if isinstance(row.get("available_regions"), list) else [row.get("region")]
        delays = row.get("available_delays") if isinstance(row.get("available_delays"), list) else [row.get("delay")]
        universes = row.get("available_universes") if isinstance(row.get("available_universes"), list) else [row.get("universe")]
        for region, delay, universe in product(regions, delays, universes):
            try:
                normalized = (str(region).strip().upper(), int(delay), str(universe).strip().upper())
            except (TypeError, ValueError):
                continue
            if normalized[0] and normalized[2] and normalized[1] >= 0:
                scopes.add(normalized)
    return [
        {"region": region, "delay": delay, "universe": universe}
        for region, delay, universe in sorted(scopes)
    ]


def _schedule_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: schedule preview. Read current schedule Markdown."""
    path = knowledge_root / "wiki" / "70_decisions" / "research_schedule.md"
    if not path.exists():
        return {"exists": False, "path": str(path), "preview": ""}
    text = path.read_text(encoding="utf-8")
    return {"exists": True, "path": str(path), "preview": text[:2000]}


def _job_rows(job_root: Path, knowledge_root: Path) -> list[dict[str, Any]]:
    """Input: job root and knowledge root. Output: reconciled job rows. Read console jobs newest first."""
    from wqb.console_jobs import load_job_history

    return load_job_history(job_root, knowledge_root)


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
            "stages": {name: stage.__dict__ for name, stage in state.stages.items()},
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
    proposals = load_workflow_proposals(decisions)
    proposal_counts = Counter(str(row.get("status", "unclassified")) for row in proposals)
    active_workflow, active_run_dir = _active_workflow_summary(paths.runs_root)
    workflow_events = [] if active_run_dir is None else [event.__dict__ for event in read_workflow_events(active_run_dir)]
    approved_queue, queue_diagnostics = _approved_queue_with_diagnostics(paths.runs_root)
    ai_checkpoints = load_ai_checkpoints(decisions)
    base_state = {
        "readiness": _latest_readiness(paths.runs_root),
        "freshness": _freshness_summary(paths.knowledge_root),
        "knowledge_contracts": evaluate_knowledge_contract_health(paths.knowledge_root),
        "data_coverage": _data_coverage_summary(paths.knowledge_root),
        "data_authority": _data_authority_summary(paths.knowledge_root),
        "semantic_ledgers": _semantic_ledger_summary(paths.knowledge_root),
        "startable_scopes": _startable_scopes(paths.knowledge_root),
        "option_cards": _read_jsonl(decisions / "research_option_cards.jsonl"),
        "schedule": _schedule_summary(paths.knowledge_root),
        "jobs": _job_rows(paths.job_root, paths.knowledge_root),
        "proposals": proposals,
        "proposal_counts": dict(proposal_counts),
        "ai_checkpoints": ai_checkpoints,
        "milestone": _milestone_summary(paths.milestone_path),
        "active_workflow": active_workflow,
        "workflow_events": workflow_events,
        "approved_queue": approved_queue,
        "queue_diagnostics": queue_diagnostics,
        "research_record": _research_record_summary(active_run_dir),
    }
    timeline = build_timeline_rows(base_state)
    base_state["timeline"] = timeline
    base_state["current_work"] = select_current_work(base_state, timeline)
    return base_state
