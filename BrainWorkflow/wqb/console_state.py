from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from itertools import product
import json
from pathlib import Path
import threading
from typing import Any

from wqb.ai_checkpoints import load_ai_checkpoints
from wqb.benchmark_rules import load_active_benchmark_rules
from wqb.data_ledger import load_data_ledger, summarize_data_ledger_authority
from wqb.knowledge_paths import (
    existing_decision_artifact_path,
    existing_machine_resource_path,
)
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
from wqb.strategy_progress import load_strategy_progress


COLD_SUMMARY_CACHE: dict[str, tuple[tuple, dict[str, Any]]] = {}
COLD_SUMMARY_LOCK = threading.Lock()
COLD_SUMMARY_CACHE_LIMIT = 8


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


def _latest_knowledge_maintenance(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: maintenance summary. Read the newest valid maintenance report."""
    directory = knowledge_root / "raw" / "maintenance" / "compile_reports"
    latest = directory / "latest.json"
    payload = _read_json(latest)
    if payload:
        evidence_path = Path(str(payload.get("report_path", latest)))
        return {
            **payload,
            "exists": True,
            "path": str(evidence_path if evidence_path.exists() else latest),
        }
    reports = sorted(
        (
            path
            for path in directory.glob("*.json")
            if ".pre_cleanup_evidence" not in path.name and path.name != "latest.json"
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not reports:
        return {"exists": False}
    payload = _read_json(reports[0])
    return {**payload, "exists": bool(payload), "path": str(reports[0])}


def _latest_delivery_gate(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: delivery summary. Read the newest valid delivery gate report."""
    directory = knowledge_root / "raw" / "maintenance" / "delivery_gates"
    latest = directory / "latest.json"
    payload = _read_json(latest)
    if payload:
        evidence_path = Path(str(payload.get("report_path", latest)))
        return {
            **payload,
            "exists": True,
            "path": str(evidence_path if evidence_path.exists() else latest),
        }
    reports = sorted(
        (path for path in directory.glob("*.json") if path.name != "latest.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not reports:
        return {"exists": False}
    payload = _read_json(reports[0])
    return {**payload, "exists": bool(payload), "path": str(reports[0])}


def _freshness_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: freshness counts. Evaluate the manifest when present."""
    manifest = existing_machine_resource_path(knowledge_root, "freshness_manifest")
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
    ledger_path = existing_machine_resource_path(knowledge_root, "data_ledger")
    try:
        return _data_authority_summary_from_rows(_read_jsonl(ledger_path))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {
            "record_count": 0,
            "authoritative_measured_count": 0,
            "seed_cache_count": 0,
            "unclassified_count": 0,
            "authoritative_ready": False,
        }


def _ledger_row_authority(row: dict[str, Any]) -> str:
    """Input: data-ledger JSON row. Output: authority label. Classify dashboard provenance without raw-file scans."""
    if (
        row.get("source_quality") == "platform_raw_capture"
        and row.get("coverage_status") == "measured_raw"
    ):
        try:
            date.fromisoformat(str(row.get("source_updated_at", "")))
        except (TypeError, ValueError):
            return "unclassified"
        return "authoritative_measured"
    if row.get("source_quality") in {"platform_metadata_cache", "schema_seed", "bootstrap_seed"}:
        return "seed_cache"
    if row.get("coverage_status") in {"measured_cache", "schema_seeded", "partial"}:
        return "seed_cache"
    return "unclassified"


def _data_authority_summary_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Input: data-ledger JSON rows. Output: authority summary. Count metadata classes for the dashboard."""
    counts = Counter(_ledger_row_authority(row) for row in rows if isinstance(row, dict))
    record_count = len([row for row in rows if isinstance(row, dict)])
    return {
        "record_count": record_count,
        "authoritative_measured_count": counts.get("authoritative_measured", 0),
        "seed_cache_count": counts.get("seed_cache", 0),
        "unclassified_count": counts.get("unclassified", 0),
        "authoritative_ready": record_count > 0 and counts.get("authoritative_measured", 0) == record_count,
    }


def _semantic_ledger_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: semantic summary. Count operator, matrix-ready template, and active rule records."""
    try:
        from wqb.knowledge_compile import read_semantic_rows
        from wqb.operator_semantics import operator_semantic_record_from_dict
        from wqb.template_library import template_record_from_dict
        receipt, operator_rows, template_rows = read_semantic_rows(knowledge_root)
        operators = [operator_semantic_record_from_dict(row) for row in operator_rows]
        templates = [template_record_from_dict(row) for row in template_rows]
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


def _latest_semantic_compile(knowledge_root: Path) -> dict:
    """Input: vault Path. Output: latest semantic job dict. Expose durable status/errors/notification without model polling."""
    candidates = list((knowledge_root / 'machine/semantic_jobs').glob('*/command_result.json'))
    candidates += list((knowledge_root / 'machine/semantic_jobs/requests').glob('*/command_result.json'))
    if not candidates:
        return {}
    path = max(candidates, key=lambda item: item.stat().st_mtime_ns)
    try:
        result = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(result, dict) or result.get('status') not in {'running', 'publishing', 'completed', 'blocked', 'cancelled'}:
            raise ValueError('invalid semantic command receipt')
        return dict(result, path=str(path), job_id=path.parent.name)
    except (OSError, ValueError, TypeError):
        return dict(status='blocked', error='semantic command result unreadable', path=str(path))


def _data_ledger_max_age_days(knowledge_root: Path) -> int | None:
    """Input: knowledge root. Output: optional max age. Read scoped data-ledger freshness policy."""
    manifest = existing_machine_resource_path(knowledge_root, "freshness_manifest")
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


def _startable_scopes_from_rows(knowledge_root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Input: knowledge root and ledger rows. Output: concrete scope rows. Select measured scopes for workflow start."""
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


def _startable_scopes(knowledge_root: Path) -> list[dict[str, Any]]:
    """Input: knowledge root. Output: concrete scope rows. Read measured ledger scopes suitable for console selection."""
    return _startable_scopes_from_rows(
        knowledge_root,
        _read_jsonl(existing_machine_resource_path(knowledge_root, "data_ledger")),
    )


def _schedule_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: schedule preview. Read current schedule Markdown."""
    path = existing_decision_artifact_path(knowledge_root, "research_schedule.md")
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


def _load_cold_console_state(paths: ConsolePaths) -> dict[str, Any]:
    """Input: ConsolePaths. Output: dict. Compile knowledge summaries outside the runtime path."""
    proposal_dir = existing_decision_artifact_path(
        paths.knowledge_root,
        "workflow_change_proposals.jsonl",
    ).parent
    checkpoint_dir = existing_decision_artifact_path(
        paths.knowledge_root,
        "ai_checkpoints.jsonl",
    ).parent
    data_ledger_rows = _read_jsonl(existing_machine_resource_path(paths.knowledge_root, "data_ledger"))
    proposals = load_workflow_proposals(proposal_dir)
    proposal_counts = Counter(str(row.get("status", "unclassified")) for row in proposals)
    ai_checkpoints = load_ai_checkpoints(checkpoint_dir)
    return {
        "knowledge_maintenance": _latest_knowledge_maintenance(paths.knowledge_root),
        "semantic_compile": _latest_semantic_compile(paths.knowledge_root),
        "delivery_gate": _latest_delivery_gate(paths.knowledge_root),
        "freshness": _freshness_summary(paths.knowledge_root),
        "knowledge_contracts": evaluate_knowledge_contract_health(paths.knowledge_root),
        "data_coverage": _data_coverage_summary(paths.knowledge_root),
        "data_authority": _data_authority_summary_from_rows(data_ledger_rows),
        "semantic_ledgers": _semantic_ledger_summary(paths.knowledge_root),
        "startable_scopes": _startable_scopes_from_rows(paths.knowledge_root, data_ledger_rows),
        "option_cards": _read_jsonl(
            existing_decision_artifact_path(
                paths.knowledge_root,
                "research_option_cards.jsonl",
            )
        ),
        "schedule": _schedule_summary(paths.knowledge_root),
        "proposals": proposals,
        "proposal_counts": dict(proposal_counts),
        "ai_checkpoints": ai_checkpoints,
        "milestone": _milestone_summary(paths.milestone_path),
    }


def _cold_signature(paths: ConsolePaths) -> tuple:
    """Input: ConsolePaths. Output: tuple. Track knowledge file metadata and day-sensitive freshness."""
    tokens = [date.today().isoformat()]
    candidates = [paths.milestone_path, *paths.knowledge_root.rglob('*')]
    for path in sorted(candidates):
        try:
            stat = path.stat()
            tokens.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            continue
    return tuple(tokens)


def load_cold_console_state(paths: ConsolePaths) -> dict[str, Any]:
    """Input: ConsolePaths. Output: dict. Cache cold summaries until relevant file mtimes change."""
    key = str(paths.knowledge_root.resolve()) + str(paths.milestone_path.resolve())
    signature = _cold_signature(paths)
    with COLD_SUMMARY_LOCK:
        cached = COLD_SUMMARY_CACHE.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        state = _load_cold_console_state(paths)
        if len(COLD_SUMMARY_CACHE) >= COLD_SUMMARY_CACHE_LIMIT:
            COLD_SUMMARY_CACHE.pop(next(iter(COLD_SUMMARY_CACHE)))
        COLD_SUMMARY_CACHE[key] = (signature, state)
        return state


def _source_readiness(paths: ConsolePaths, active: dict[str, Any], decision: Any) -> dict[str, Any]:
    """Input: ConsolePaths, active dict, SourceBridgeDecision. Output: dict. Share CLI readiness selection."""
    from wqb.orchestrator import OrchestratorPaths
    from wqb.workflow_auto_continue import _readiness_blocker_for_status, _readiness_report_paths

    workflow_paths = OrchestratorPaths(paths.project_root, paths.workflow_root, paths.knowledge_root, paths.runs_root)
    blocker = _readiness_blocker_for_status(workflow_paths, active, decision)
    if blocker:
        return {**blocker, 'exists': True}
    for path in _readiness_report_paths(active, decision):
        if path.is_file():
            return {**_read_json(path), 'exists': True, 'path': str(path)}
    return _latest_readiness(paths.runs_root)


def project_start_readiness(paths: ConsolePaths, state: dict[str, Any]) -> None:
    """Input: Console paths and mutable state dict. Output: none. Separate new Start evidence from active-run readiness."""
    from wqb.console_start import read_start_request

    request = read_start_request(paths.runs_root)
    state['start_request'] = request
    state['start_preparation'] = request
    scope = (state.get('runtime_control') or {}).get('original_batch_recovery') or {}
    active = state.get('active_workflow') or {}
    new_start = not active.get('exists') or active.get('status') == 'complete'
    if scope.get('authorized'):
        new_start = scope.get('planned', 0) > 0 and scope.get('remaining') == 0
    if not new_start:
        return
    state['run_readiness'] = state.get('readiness', {})
    receipt_root = paths.runs_root / 'start_preflight'
    receipts = sorted(receipt_root.glob('*.json'), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    receipt = _read_json(receipts[0]) if receipts and not request else {}
    if request.get('preflight_receipt_path'):
        bound_path = Path(request['preflight_receipt_path'])
        if bound_path.resolve().parent == receipt_root.resolve():
            bound = _read_json(bound_path)
            if bound.get('scope') == (request.get('selection') or {}).get('scope'):
                receipt = bound
    if request.get('status') == 'blocked':
        receipt = {**receipt, 'blocked': True, 'passed': False,
                   'scope': (request.get('selection') or {}).get('scope', {}),
                   'issues': request.get('issues') or [{'code': 'start_preflight_failed',
                                                       'message': request.get('error', 'Start blocked')}],
                   'notification': request.get('notification', {})}
    state['start_preflight'] = receipt
    # A receipt explains the last attempt, not a renewable authorization.
    # Every Start still runs strict scoped readiness before creating a mission.
    state['readiness'] = {**receipt, 'exists': bool(receipt), 'passed': False,
                          'context': 'new-mission-preflight',
                          'last_preflight_passed': receipt.get('passed', False)}


def load_runtime_state(paths: ConsolePaths) -> dict[str, Any]:
    """Input: ConsolePaths. Output: dict. Project local runtime evidence without scanning knowledge ledgers."""
    from wqb.source_bridge import SourceBridgeDecision, inspect_scout_seed_source_bridge

    active_workflow, active_run_dir = _active_workflow_summary(paths.runs_root)
    source_bridge = {'exists': False}
    decision = None
    runtime_control = {}
    source_dir = None
    if active_run_dir is not None:
        binding = _read_json(active_run_dir / 'stages/scout_seed/source_bridge_binding.json')
        if binding.get('source_run_dir'):
            source_dir = Path(binding['source_run_dir'])
            decision = SourceBridgeDecision('bound', '', source_dir.name, str(source_dir))
        if active_workflow.get('current_stage') == 'scout_seed':
            bridge_decision = inspect_scout_seed_source_bridge(
                paths.runs_root, active_run_dir, datetime.now(timezone.utc).isoformat()
            )
            source_bridge = bridge_decision.to_dict()
            if decision is None:
                decision = bridge_decision
                if decision.source_run_dir:
                    source_dir = Path(decision.source_run_dir)
        try:
            from wqb.runtime_control import read_runtime_control, has_runtime_authority
        except ImportError:
            runtime_control = {'status': 'unavailable', 'desired_state': 'paused'}
        else:
            runtime_control = read_runtime_control(active_run_dir)
            if runtime_control.get('original_batch_scope_id') and has_runtime_authority(active_run_dir):
                from wqb.original_batch_recovery import read_original_batch, _inventory
                scope = read_original_batch(active_run_dir)
                plan, _, checked = _inventory(Path(scope['source_run_dir']), require_reconciled=False)
                runtime_control['original_batch_recovery'] = {
                    'authorized': True, 'scope_id': scope['scope_id'], 'planned': len(plan),
                    'remaining': sum(row.get('expression_hash') not in checked for row in plan),
                    'checked': len(checked)}
            if not has_runtime_authority(active_run_dir):
                runtime_control = {**runtime_control, 'legacy_authority_required': True,
                                   'status': 'blocked', 'reason': 'runtime authority required; legacy run needs reconciliation'}
            from wqb.recovery_cases import read_current_recovery_case
            if runtime_control.get('recovery_case'):
                runtime_control['recovery_case'] = read_current_recovery_case(active_run_dir)
            from wqb.runtime_boundaries import project_runtime_boundary
            active_workflow = project_runtime_boundary(active_workflow, runtime_control)
    workflow_events = [] if active_run_dir is None else [event.__dict__ for event in read_workflow_events(active_run_dir)]
    approved_queue, queue_diagnostics = _approved_queue_with_diagnostics(paths.runs_root)
    base_state = {
        'semantic_compile': _latest_semantic_compile(paths.knowledge_root),
        'research_rounds': _read_json(active_run_dir / 'research_rounds.json') if active_run_dir else {},
        'research_handoff': _read_json(active_run_dir / 'runtime/research_handoff.json') if active_run_dir else {},
        'readiness': _source_readiness(paths, active_workflow, decision),
        'runtime_control': runtime_control,
        'strategy_progress': load_strategy_progress(source_dir),
        'jobs': _job_rows(paths.job_root, paths.knowledge_root),
        "active_workflow": active_workflow,
        "source_bridge": source_bridge,
        "workflow_events": workflow_events,
        "approved_queue": approved_queue,
        "queue_diagnostics": queue_diagnostics,
        "research_record": _research_record_summary(active_run_dir),
        "run_ai_checkpoints": load_ai_checkpoints(active_run_dir / "stages" / "ai") if active_run_dir is not None else [],
    }
    if active_run_dir is not None:
        repair = _read_json(active_run_dir / 'stages/repair/repair_execution.json')
        base_state['repair_progress'] = [{'parent_alpha_id': a.get('parent_alpha_id'),
            'phase': a.get('phase', a.get('status')), 'next_poll_at': a.get('next_poll_at'),
            'hypothesis': a.get('plan', {}).get('decision', {}).get('hypothesis', 'Frozen legacy plan'),
            'ai_status': a.get('plan', {}).get('status', 'not_ai_generated')}
            for a in repair.get('attempts', [])]
        decisions = []
        for receipt_path in sorted((active_run_dir / 'runtime/repair_decisions').glob('*.json')):
            if receipt_path.name.endswith('.input.json'):
                continue
            decision = _read_json(receipt_path)
            decisions.append({'checkpoint_type': 'Repair execution decision', 'status': decision.get('status'),
                              'reason': decision.get('decision', {}).get('hypothesis', decision.get('reason', ''))})
        base_state['run_ai_checkpoints'].extend(decisions[-8:])
    project_start_readiness(paths, base_state)
    timeline = build_timeline_rows(base_state)
    base_state["timeline"] = timeline
    base_state["current_work"] = select_current_work(base_state, timeline)
    if active_workflow.get('current_stage') == 'repair':
        base_state['current_work'].setdefault('details', []).extend(
            f"{row['parent_alpha_id']}: {row['phase']}; AI={row['ai_status']}; next={row['next_poll_at'] or 'ready'}; {row['hypothesis']}"
            for row in base_state.get('repair_progress', []))
    return base_state


def load_console_state(paths: ConsolePaths) -> dict[str, Any]:
    """Input: ConsolePaths. Output: dict. Combine cached knowledge and current local runtime evidence."""
    state = {**load_cold_console_state(paths), **load_runtime_state(paths)}
    state["ai_checkpoints"] = [*state["run_ai_checkpoints"], *state["ai_checkpoints"]]
    state['timeline'] = build_timeline_rows(state)
    state['current_work'] = select_current_work(state, state['timeline'])
    if (state.get('active_workflow') or {}).get('current_stage') == 'repair':
        state['current_work'].setdefault('details', []).extend(
            f"{row['parent_alpha_id']}: {row['phase']}; AI={row['ai_status']}; next={row['next_poll_at'] or 'ready'}; {row['hypothesis']}"
            for row in state.get('repair_progress', []))
    return state
