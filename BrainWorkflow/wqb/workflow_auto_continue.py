from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
from wqb.source_bridge import SourceBridgeDecision, active_run_needs_scout_seed_candidates, inspect_scout_seed_source_bridge
from wqb.source_run_lock import acquire_source_run_lock, release_source_run_lock
from wqb.research_planning import ResearchPlanningBlocked, ResearchVariantsExhausted


def _release_lock(run_dir: str, action: str, now: str, lock: dict[str, Any]) -> None:
    """Input: source run, action, timestamp, acquired lock. Output: none. Release only the matching source-run lock."""
    release_source_run_lock(run_dir, action, now, owner_id=str(lock.get("owner_id", "")))


def _local_construction_blocker(decision: SourceBridgeDecision) -> SourceBridgeDecision | None:
    """Input: source bridge decision. Output: blocker decision or none. Enforce local-only source construction."""
    if decision.action != "start_source_batch":
        return None
    metadata = dict(decision.metadata or {})
    if metadata.get("local_construction_ready") is True and metadata.get("allow_live_fallback") is False:
        return None
    blockers = metadata.get("local_construction_blockers")
    if not isinstance(blockers, list):
        blockers = ["local_construction_provenance_missing"]
    return SourceBridgeDecision(
        "maintenance_blocker",
        "local construction provenance is required before starting source batch",
        decision.source_run_id,
        decision.source_run_dir,
        decision.evidence_paths,
        {**metadata, "local_construction_blockers": blockers},
    )


def _read_json(path: Path) -> dict[str, Any]:
    """Input: JSON path. Output: dict. Read local JSON and return empty dict when unavailable."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _readiness_blocker_from_report(report: dict[str, Any], path: Path) -> dict[str, Any] | None:
    """Input: readiness report and path. Output: blocker summary or none. Normalize blocked readiness evidence."""
    issues = report.get("issues", [])
    issue_rows = [issue for issue in issues if isinstance(issue, dict)]
    blocked = report.get("blocked") is True or (
        report.get("exists") is True and report.get("passed") is False and bool(issue_rows)
    )
    if not blocked:
        return None
    return {
        "blocked": True,
        "passed": False,
        "path": str(path),
        "codes": [str(issue.get("code", "")) for issue in issue_rows if str(issue.get("code", ""))],
        "issues": issue_rows,
    }


def _latest_readiness_blocker(runs_root: Path) -> dict[str, Any] | None:
    """Input: runs root. Output: latest readiness blocker or none. Use newest report as read-only gate evidence."""
    reports = sorted(runs_root.glob("**/readiness_report.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not reports:
        return None
    return _readiness_blocker_from_report(_read_json(reports[0]), reports[0])


def _readiness_report_paths(status: dict[str, Any], decision: SourceBridgeDecision | None = None) -> list[Path]:
    """Input: workflow status and source decision. Output: report paths. Prefer active or bound run evidence."""
    paths: list[Path] = []
    if decision is not None and decision.source_run_dir:
        paths.append(Path(decision.source_run_dir) / "readiness_report.json")
    run_dir = str(status.get("run_dir", "") or "")
    if run_dir:
        paths.append(Path(run_dir) / "readiness_report.json")
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _readiness_blocker_for_status(
    paths: OrchestratorPaths,
    status: dict[str, Any],
    decision: SourceBridgeDecision | None = None,
) -> dict[str, Any] | None:
    """Input: paths, workflow status, source decision. Output: blocker or none. Avoid unrelated readiness reports."""
    saw_relevant_report = False
    report_paths = _readiness_report_paths(status, decision)
    for report_path in report_paths:
        if not report_path.is_file():
            continue
        saw_relevant_report = True
        blocker = _readiness_blocker_from_report(_read_json(report_path), report_path)
        if blocker is not None:
            return blocker
    if saw_relevant_report or report_paths:
        return None
    return _latest_readiness_blocker(paths.run_root)


def _apply_readiness_blocker(status: dict[str, Any], blocker: dict[str, Any] | None) -> dict[str, Any]:
    """Input: workflow status and optional blocker. Output: status. Make readiness the top-level next-action gate."""
    if not blocker:
        return status
    return {
        **status,
        "readiness_blocker": blocker,
        "next_action": "readiness-blocked",
        "message": "Readiness is blocked; refresh the required knowledge/data artifacts before continuing research.",
    }


def decorate_workflow_status_with_source_bridge(
    paths: OrchestratorPaths,
    status: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    """Input: paths, workflow status, timestamp. Output: status with source bridge overlay. Expose local blockers safely."""
    if not active_run_needs_scout_seed_candidates(status):
        return _apply_readiness_blocker(status, _readiness_blocker_for_status(paths, status))
    decision = inspect_scout_seed_source_bridge(paths.run_root, str(status["run_dir"]), now)
    decision_dict = decision.to_dict()
    next_action = {
        "maintenance_blocker": "maintenance-blocker",
        "rate_limit_wait": "rate-limit-wait",
        "import_existing": "workflow-auto-continue",
        "import_research_outcome": "workflow-auto-continue",
        "complete_in_flight": "workflow-auto-continue",
        "retry_planned": "workflow-auto-continue",
        "start_source_batch": "workflow-auto-continue",
    }.get(decision.action, decision.action)
    return _apply_readiness_blocker(
        {**status, "source_bridge": decision_dict, "next_action": next_action},
        _readiness_blocker_for_status(paths, status, decision),
    )


def _readiness_blocked_auto_continue(status: dict[str, Any], blocker: dict[str, Any] | None) -> dict[str, Any] | None:
    """Input: workflow status and optional blocker. Output: auto-continue stop payload or none. Stop before live work."""
    if not blocker:
        return None
    return {
        **status,
        "readiness_blocker": blocker,
        "next_action": "readiness-blocked",
        "message": "Readiness is blocked; refresh exact-scope knowledge/data artifacts before live source recovery.",
    }


def _planning_blocked_result(orchestrator: WorkflowOrchestrator, run: Path, now: str, message: str) -> dict:
    """Input: controller, run Path, timestamp/message str. Output: blocked dict. Persist planning faults for event-routed maintenance."""
    from dataclasses import replace
    from wqb.workflow_state import load_run_state, transition_run_state, write_run_state
    from wqb.runtime_control import _write
    state_path = run / 'run_state.json'
    state = load_run_state(state_path)
    reason = 'research_planning_blocked: ' + message
    if state.status == 'running':
        state = transition_run_state(state, 'paused', reason)
    stages = dict(state.stages)
    stages[state.current_stage] = replace(stages[state.current_stage], status='paused', blocker=reason)
    write_run_state(state_path, replace(state, stages=stages, pause_reason=reason))
    _write(run / 'runtime/research_handoff.json', {
        'status': 'blocked', 'stop_reason': 'research_planning_blocked',
        'next_action': 'research-loop-blocked', 'message': message, 'recorded_at': now})
    return {**orchestrator.status(), 'next_action': 'research-loop-blocked',
            'stop_reason': 'research_planning_blocked', 'message': message}


def _source_recovery_result(status: dict, decision: dict, recovery: dict) -> dict:
    """Input: workflow/bridge/source result dicts. Output: next-action dict. Stop on source readiness failure instead of looping."""
    result = {**status, 'source_bridge': decision, 'source_recovery': recovery,
              'next_action': 'workflow-auto-continue'}
    if recovery.get('status') != 'readiness_blocked':
        return result
    path = Path(str(recovery.get('readiness_json_path', '')))
    blocker = _readiness_blocker_from_report(_read_json(path), path) if path.is_file() else None
    if blocker is None:
        return {**result, 'next_action': 'maintenance-blocker',
                'message': 'Source readiness failed without a valid blocking report; preserve evidence.'}
    return {**result, 'next_action': 'readiness-blocked', 'readiness_blocker': blocker,
            'message': 'Source readiness blocked; no further source batches or platform requests are allowed.'}


def auto_continue_workflow(
    paths: OrchestratorPaths,
    config: dict[str, Any],
    now: str,
    enable_live_api: bool = False,
    source_batch_runner: Callable[[dict[str, Any], dict[str, Any]], dict[str, object]] | None = None,
    complete_in_flight_runner: Callable[[str], dict[str, object]] | None = None,
    retry_planned_runner: Callable[[str], dict[str, object]] | None = None,
    repair_executor: Callable[[Path, dict[str, Any], list[dict[str, Any]], int], list[dict[str, Any]]] | None = None,
    discovery_executor: Callable | None = None,
) -> dict[str, object]:
    """Input: paths, config, timestamp, live flag, optional runners. Output: workflow summary after the next safe action."""
    from wqb.discovery_runtime import DiscoveryRuntimeExecutor
    orchestrator = WorkflowOrchestrator(paths, repair_executor=repair_executor if enable_live_api else None,
        discovery_executor=(discovery_executor or (DiscoveryRuntimeExecutor(config)
                            if config.get('managed_research_execution') else None)) if enable_live_api else None,
        **({'bound_run_dir': Path(config['bound_group_lane'])} if config.get('bound_group_lane') else {}))
    status = orchestrator.status()
    if status.get('active') and status.get('run_dir'):
        from wqb.research_rounds import reconcile_research_budget_wait
        reconciled = reconcile_research_budget_wait(Path(status['run_dir']), now)
        if reconciled['status'] == 'daily-budget-wait':
            return {**status, 'next_action': 'daily-budget-wait',
                    'daily_simulation_budget': reconciled['daily_simulation_budget']}
        if reconciled['status'] == 'ready':
            status = orchestrator.status()
    if status.get("status") == "paused" and str(status.get("pause_reason", "")).startswith("research_"):
        planning = str(status['pause_reason']).startswith('research_planning_blocked:')
        return {**status, "next_action": "research-loop-blocked", "message": status["pause_reason"],
                **({'stop_reason': 'research_planning_blocked'} if planning else {})}
    if not status.get("active"):
        return {
            "active": False,
            "status": "none",
            "next_action": "workflow-start",
            "message": "Select an option card and start a workflow.",
        }
    if status.get("waiting_for_user") or status.get("status") == "waiting_for_user":
        return {**status, "message": "User approval is required before automatic progress."}
    if active_run_needs_scout_seed_candidates(status):
        from wqb.research_seed_stage import preplanned_research_enabled
        if preplanned_research_enabled(Path(status['run_dir'])):
            from wqb.tree_runtime import continue_tree
            try:
                progress = continue_tree(Path(status['run_dir']), config, now,
                    enable_live_api=enable_live_api, source_batch_runner=source_batch_runner,
                    complete_in_flight_runner=complete_in_flight_runner,
                    retry_planned_runner=retry_planned_runner)
            except (OSError, ValueError, KeyError, TypeError) as error:
                return _planning_blocked_result(orchestrator, Path(status['run_dir']), now,
                                                'Preplanned tree evidence invalid: ' + str(error))
            if progress.get('tree_complete'):
                resumed = orchestrator.resume(now)
                if resumed.get('status') == 'running':
                    return {**orchestrator.continue_once(now), 'tree': progress['tree']}
                return {**resumed, 'tree': progress['tree']}
            return {**status, **progress}
        from wqb.research_rounds import rotate_exhausted_scout_plan
        try:
            rotate_exhausted_scout_plan(Path(status['run_dir']), now)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return _planning_blocked_result(orchestrator, Path(status['run_dir']), now,
                                            'Scout selection evidence invalid: ' + str(exc))
        decision = inspect_scout_seed_source_bridge(paths.run_root, str(status["run_dir"]), now)
        readiness_stop = _readiness_blocked_auto_continue(status, _readiness_blocker_for_status(paths, status, decision))
        if readiness_stop is not None:
            return readiness_stop
        local_blocker = _local_construction_blocker(decision)
        if local_blocker is not None:
            decision = local_blocker
        decision_dict = decision.to_dict()
        if decision.action in {"import_existing", "import_research_outcome"}:
            imported = orchestrator.import_scout_seed_bridge_decision(decision_dict, now)
            return {**imported, "source_bridge": decision_dict, "next_action": "workflow-auto-continue"}
        if decision.action == "rate_limit_wait":
            return {
                **status,
                "source_bridge": decision_dict,
                "next_action": "rate-limit-wait",
                "message": "Platform cooldown is active; Continue will not contact the platform yet.",
            }
        if decision.action in {
            "complete_in_flight",
            "retry_planned",
            "start_source_batch",
        } and not enable_live_api:
            return {
                **status,
                "source_bridge": decision_dict,
                "next_action": "enable-live-api-required",
                "message": "Live API authorization is required before source recovery can contact the platform.",
            }
        if decision.action == "complete_in_flight" and complete_in_flight_runner is not None:
            lock = acquire_source_run_lock(decision.source_run_dir, "complete-in-flight", now)
            if lock.get("status") != "acquired":
                return {**status, "source_bridge": decision_dict, "next_action": "source-lock-wait", "source_lock": lock}
            try:
                recovery = complete_in_flight_runner(decision.source_run_dir)
            finally:
                _release_lock(decision.source_run_dir, "complete-in-flight", now, lock)
            return _source_recovery_result(status, decision_dict, recovery)
        if decision.action == "retry_planned" and retry_planned_runner is not None:
            lock = acquire_source_run_lock(decision.source_run_dir, "retry-planned", now)
            if lock.get("status") != "acquired":
                return {**status, "source_bridge": decision_dict, "next_action": "source-lock-wait", "source_lock": lock}
            try:
                recovery = retry_planned_runner(decision.source_run_dir)
            finally:
                _release_lock(decision.source_run_dir, "retry-planned", now, lock)
            return _source_recovery_result(status, decision_dict, recovery)
        if decision.action in {"complete_in_flight", "retry_planned"}:
            return {**status, "source_bridge": decision_dict, "next_action": decision.action, "message": "Source recovery runner is not configured."}
        if decision.action == "start_source_batch" and source_batch_runner is not None:
            run_dir = str(status["run_dir"])
            lock = acquire_source_run_lock(run_dir, "start-source-batch", now)
            if lock.get("status") != "acquired":
                return {**status, "source_bridge": decision_dict, "next_action": "source-lock-wait", "source_lock": lock}
            metadata = decision.metadata or {}
            source_config = {
                **config,
                **{
                    key: metadata[key]
                    for key in ("instrument_type", "region", "delay", "universe")
                    if key in metadata
                },
                "max_alphas_per_round": int(metadata.get("max_alphas_per_round", 30)),
                "allow_live_source_fallback": False,
                "scheduled_template": metadata.get("template_provenance"),
                "research_round_id": metadata.get("research_round_id", "round-0001"),
                "active_workflow_run_dir": run_dir,
            }
            try:
                from wqb.daily_simulation_budget import read_daily_budget
                from wqb.runtime_control import read_runtime_control, DailyBudgetExhausted, DAILY_RECONCILE_ENV
                if read_runtime_control(run_dir).get('simulation_budget_mode') == 'daily':
                    budget = read_daily_budget(Path(run_dir), now)
                    import os
                    if not budget['remaining'] or os.environ.get(DAILY_RECONCILE_ENV) == '1':
                        raise DailyBudgetExhausted(budget)
                if metadata.get('hypothesis_binding_version') == 2:
                    from wqb.research_planning import prepare_source_plan
                    source_config['max_alphas_per_round'] = metadata.get('scheduled_batch_maximum', source_config['max_alphas_per_round'])
                    source_config.update(prepare_source_plan(Path(run_dir), source_config, metadata, now))
                    metadata = {**metadata, 'hypothesis_bindings': source_config['hypothesis_bindings'],
                                'ai_plan_receipt': source_config['ai_plan_receipt']}
                recovery = source_batch_runner(source_config, metadata)
            except ResearchPlanningBlocked as exc:
                if isinstance(exc, ResearchVariantsExhausted):
                    try:
                        if rotate_exhausted_scout_plan(Path(run_dir), now, exhausted=True):
                            return {**status, 'next_action': 'workflow-auto-continue',
                                    'message': 'Empty Scout plan exhausted; selected another snapshot-backed hypothesis.'}
                    except (ValueError, OSError, KeyError, TypeError) as error:
                        exc = ResearchPlanningBlocked('Scout selection evidence invalid: ' + str(error))
                return _planning_blocked_result(orchestrator, Path(run_dir), now, str(exc))
            finally:
                _release_lock(run_dir, "start-source-batch", now, lock)
            return _source_recovery_result(status, decision_dict, recovery)
        if decision.action == "maintenance_blocker":
            return {**status, "source_bridge": decision_dict, "next_action": "maintenance-blocker"}
        return {**status, "source_bridge": decision_dict, "next_action": "source-batch-runner-missing", "message": "Source batch runner is not configured."}
    readiness_stop = _readiness_blocked_auto_continue(status, _readiness_blocker_for_status(paths, status))
    if readiness_stop is not None:
        return readiness_stop
    if status.get("current_stage") == "candidate_gate":
        return orchestrator.request_candidate_approval_from_checked_results(now)
    if status.get("status") == "paused":
        resumed = orchestrator.resume(now)
        if resumed.get("status") == "running":
            return orchestrator.continue_once(now)
        return resumed
    if status.get("next_action") == "workflow-continue" or status.get("status") in {"running", "created"}:
        return orchestrator.continue_once(now)
    return status
