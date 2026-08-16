from __future__ import annotations

from typing import Any, Callable

from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
from wqb.source_bridge import active_run_needs_scout_seed_candidates, inspect_scout_seed_source_bridge
from wqb.source_run_lock import acquire_source_run_lock, release_source_run_lock


def _release_lock(run_dir: str, action: str, now: str, lock: dict[str, Any]) -> None:
    """Input: source run, action, timestamp, acquired lock. Output: none. Release only the matching source-run lock."""
    release_source_run_lock(run_dir, action, now, owner_id=str(lock.get("owner_id", "")))


def decorate_workflow_status_with_source_bridge(
    paths: OrchestratorPaths,
    status: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    """Input: paths, workflow status, timestamp. Output: status with source bridge overlay. Expose local blockers safely."""
    if not active_run_needs_scout_seed_candidates(status):
        return status
    decision = inspect_scout_seed_source_bridge(paths.run_root, str(status["run_dir"]), now)
    decision_dict = decision.to_dict()
    next_action = {
        "maintenance_blocker": "maintenance-blocker",
        "rate_limit_wait": "rate-limit-wait",
        "import_existing": "workflow-auto-continue",
        "complete_in_flight": "workflow-auto-continue",
        "retry_planned": "workflow-auto-continue",
        "start_source_batch": "workflow-auto-continue",
    }.get(decision.action, decision.action)
    return {**status, "source_bridge": decision_dict, "next_action": next_action}


def auto_continue_workflow(
    paths: OrchestratorPaths,
    config: dict[str, Any],
    now: str,
    enable_live_api: bool = False,
    source_batch_runner: Callable[[dict[str, Any], dict[str, Any]], dict[str, object]] | None = None,
    complete_in_flight_runner: Callable[[str], dict[str, object]] | None = None,
    retry_planned_runner: Callable[[str], dict[str, object]] | None = None,
) -> dict[str, object]:
    """Input: paths, config, timestamp, live flag, optional runners. Output: workflow summary after the next safe action."""
    orchestrator = WorkflowOrchestrator(paths)
    status = orchestrator.status()
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
        decision = inspect_scout_seed_source_bridge(paths.run_root, str(status["run_dir"]), now)
        decision_dict = decision.to_dict()
        if decision.action == "import_existing":
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
            return {**status, "source_bridge": decision_dict, "source_recovery": recovery, "next_action": "workflow-auto-continue"}
        if decision.action == "retry_planned" and retry_planned_runner is not None:
            lock = acquire_source_run_lock(decision.source_run_dir, "retry-planned", now)
            if lock.get("status") != "acquired":
                return {**status, "source_bridge": decision_dict, "next_action": "source-lock-wait", "source_lock": lock}
            try:
                recovery = retry_planned_runner(decision.source_run_dir)
            finally:
                _release_lock(decision.source_run_dir, "retry-planned", now, lock)
            return {**status, "source_bridge": decision_dict, "source_recovery": recovery, "next_action": "workflow-auto-continue"}
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
            }
            try:
                recovery = source_batch_runner(source_config, decision.metadata or {})
            finally:
                _release_lock(run_dir, "start-source-batch", now, lock)
            return {**status, "source_bridge": decision_dict, "source_recovery": recovery, "next_action": "workflow-auto-continue"}
        if decision.action == "maintenance_blocker":
            return {**status, "source_bridge": decision_dict, "next_action": "maintenance-blocker"}
        return {**status, "source_bridge": decision_dict, "next_action": "source-batch-runner-missing", "message": "Source batch runner is not configured."}
    if status.get("status") == "paused":
        resumed = orchestrator.resume(now)
        if resumed.get("status") == "running":
            return orchestrator.continue_once(now)
        return resumed
    if status.get("next_action") == "workflow-continue" or status.get("status") == "running":
        return orchestrator.continue_once(now)
    return status
