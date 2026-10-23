from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable

from wqb.runtime_control import CONTROL_ENV, DEADLINE_ENV, DAILY_RECONCILE_ENV, RuntimePaused, RuntimeBudgetExhausted, DailyBudgetExhausted, read_runtime_control, has_runtime_authority, update_runtime_status, utc_now, _read, _write
from wqb.source_run_lock import acquire_source_run_lock, release_source_run_lock
from wqb.ai_checkpoints import schedule_run_checkpoint
from wqb.recovery_cases import classify_blocker, ensure_recovery_case, advance_scripted_recovery, read_current_recovery_case, MAINTENANCE_BLOCKING_STATUSES
from wqb.maintenance_notifications import dispatch_notification
from wqb.rate_limit_state import RateLimitRecoveryRequired
from wqb.runtime_boundaries import RESOURCE_ACTIONS


DEFAULT_NO_PROGRESS_LIMIT = 5
DEFAULT_MAX_STEPS = 1000
WAIT_SLICE_SECONDS = 1.0
DAILY_RECONCILE_SECONDS = 60.0


def resolve_ai_executor_argv(config: dict[str, Any]) -> list[str]:
    """Input: runtime config dict. Output: explicit worker argv. Select a bounded run-local AI adapter."""
    if config.get("ai_executor") == "codex":
        return [sys.executable, "-m", "wqb.codex_ai_worker", "{input}", "{output}"]
    configured = config.get("ai_executor_argv", [])
    return configured if isinstance(configured, list) and all(isinstance(item, str) for item in configured) else []


def _repair_cooldown_result(run: Path, result: dict[str, Any], now: str) -> dict[str, Any]:
    """Input: active run and step result. Output: result. Surface durable Repair cooldown to the driver."""
    if result.get('next_action') == 'daily-budget-wait':
        return result
    if result.get("current_stage") not in {"repair", "batch_generation", "backtest"} or result.get("status") != "paused":
        return result
    if result.get('pause_reason') in {'checked research differs from its import receipt',
            'research import receipt belongs to another run', 'checked research import evidence is missing'}:
        return {**result, 'next_action': 'maintenance-blocker'}
    stage = str(result['current_stage'])
    receipt_name = {'repair': 'repair_execution.json', 'batch_generation': 'discovery_execution.json',
                    'backtest': 'check_recovery.json'}[stage]
    receipt_path = run / "stages" / stage / receipt_name
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return result
    if (receipt.get('status') == 'paused' and receipt.get('recovery_eligible') is False
            and receipt.get('blocker') and result.get('pause_reason') == receipt['blocker']):
        return {**result, 'next_action': 'maintenance-blocker'}
    progress_wake = str(receipt.get('progress_retry_at', ''))
    progress_source = str(receipt.get('progress_source_run_dir', ''))
    if (receipt.get('status') == 'paused' and receipt.get('recovery_eligible') is True
            and progress_wake and progress_source and receipt.get('blocker')
            and result.get('pause_reason') == receipt.get('blocker')):
        return {**result, 'next_action': 'simulation-progress-wait',
                'source_bridge': {'source_run_dir': progress_source, 'metadata': {'retry_at': progress_wake}}}
    wake = str(receipt.get("rate_limit_retry_at", ""))
    source = str(receipt.get("rate_limit_source_run_dir", ""))
    if receipt.get("status") != "paused" or receipt.get("recovery_eligible") is not True or not wake or not source:
        return result
    from wqb.rate_limit_state import rate_limit_requires_maintenance, read_rate_limit_state

    count_state = read_rate_limit_state(Path(source) / "rate_limit_state.json")
    threshold = rate_limit_requires_maintenance(count_state, now)
    return {**result, "next_action": "maintenance-blocker" if threshold else "rate-limit-wait",
            "source_bridge": {"source_run_dir": source, "metadata": {
                "retry_at": wake, "operator_acknowledgement_required": threshold}}}


def _seconds_until(target: str, now: str) -> float:
    """Input: ISO timestamps str. Output: float seconds. Compute bounded wait to a recorded wake time."""
    try:
        end = datetime.fromisoformat(target.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return max(0.0, (end - current).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def _daily_wait_result(run: Path, result: dict, now: str) -> dict | None:
    """Input: owning run/result/time. Output: wait dict or None. Recheck persisted waits without model/platform work."""
    from wqb.daily_simulation_budget import read_daily_budget
    path = run / 'runtime/daily_budget_wait.json'
    saved = _read(path)
    if saved.get('status') != 'waiting':
        return None
    budget = read_daily_budget(run, now)
    required = saved.get('required_count', 1)
    if type(required) is not int or required < 1 or saved.get('policy_id') != budget['policy_id']:
        raise ValueError('invalid daily budget wait evidence')
    if budget['remaining'] >= required:
        _write(path, {**saved, 'status': 'ready', 'ready_at': now})
        return None
    return {**result, 'next_action': 'daily-budget-wait',
            'daily_simulation_budget': {**budget, 'required_count': required}}


def _daily_reconciliation_due(run: Path, stage: str, now: str) -> bool:
    """Input: run/stage/time. Output: bool. Permit paced recovery of existing identities only, never a fresh research plan."""
    saved = _read(run / 'runtime/daily_budget_wait.json')
    if saved.get('last_reconciled_at') and _seconds_until(now, saved['last_reconciled_at']) < DAILY_RECONCILE_SECONDS:
        return False
    if stage == 'repair':
        receipt = _read(run / 'stages/repair/repair_execution.json')
        return any(attempt.get('phase') == 'waiting' and attempt.get('next_poll_at')
                   and _seconds_until(attempt['next_poll_at'], now) == 0 for attempt in receipt.get('attempts', []))
    if stage in {'batch_generation', 'backtest'}:
        name = 'discovery_execution.json' if stage == 'batch_generation' else 'check_recovery.json'
        receipt = _read(run / 'stages' / stage / name)
        wake = receipt.get('progress_retry_at') or receipt.get('rate_limit_retry_at')
        return bool(receipt.get('recovery_eligible') is True and wake and _seconds_until(wake, now) == 0)
    if stage == 'scout_seed':
        from wqb.source_bridge import inspect_scout_seed_source_bridge
        decision = inspect_scout_seed_source_bridge(run.parent, str(run), now)
        return decision.action in {'complete_in_flight', 'import_existing', 'import_research_outcome'}
    return False


def run_workflow_driver(
    paths: Any,
    config: dict[str, Any],
    *,
    step: Callable[[], dict[str, Any]],
    status_reader: Callable[[], dict[str, Any]] | None = None,
    now_func: Callable[[], str] = utc_now,
    sleep_func: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Input: paths/config, one-step runner, optional clock/status. Output: result dict. Drive durably to a real boundary."""
    if status_reader is None:
        from wqb.orchestrator import WorkflowOrchestrator
        lane = config.get('bound_group_lane')
        status_reader = WorkflowOrchestrator(paths, bound_run_dir=Path(lane) if lane else None).status
    initial = status_reader()
    if not initial.get("active") or not initial.get("run_dir"):
        return {**initial, "runtime_status": "idle"}
    run = Path(initial["run_dir"])
    from wqb.research_group import require_group_running, group_for_run
    grouped = group_for_run(run) is not None
    lane = config.get('bound_group_lane')
    if lane and Path(lane).resolve() != run.resolve():
        raise ValueError('driver lane run identity mismatch')
    existing_case = read_current_recovery_case(run)
    if existing_case.get("status") in MAINTENANCE_BLOCKING_STATUSES:
        return {**initial, "runtime_status": "blocked", "runtime_reason": "maintenance_confirmation_required"}
    if not has_runtime_authority(run):
        return {**initial, "runtime_status": "blocked", "runtime_reason": "runtime_authority_required"}
    lock_dir = run / "runtime"
    lock_dir.mkdir(exist_ok=True)
    lock = acquire_source_run_lock(lock_dir, "workflow-driver", now_func())
    if lock.get("status") != "acquired":
        return {**initial, "runtime_status": "running", "runtime_reason": "existing_worker"}
    prior_env = os.environ.get(CONTROL_ENV)
    os.environ[CONTROL_ENV] = str(run)
    from wqb.runtime_control import start_runtime_heartbeat
    heartbeat_stop, heartbeat_worker = start_runtime_heartbeat(run)
    previous = ""
    no_progress = 0
    result = initial
    runtime_status, reason = "blocked", "step_budget_exhausted"
    start = now_func()
    stored = read_runtime_control(run)
    elapsed_before = float(stored.get("elapsed_seconds", 0))
    prior_deadline = os.environ.get(DEADLINE_ENV)
    os.environ[DEADLINE_ENV] = str(time.monotonic() + max(0, float(stored.get('max_runtime_seconds', 21600)) - elapsed_before))
    try:
        for _ in range(int(config.get("runtime_max_steps", DEFAULT_MAX_STEPS))):
            try:
                require_group_running(run)
            except RuntimePaused as error:
                runtime_status = 'paused' if str(error) == 'research group is paused' else 'blocked'
                reason = 'runtime_budget_exhausted' if isinstance(error, RuntimeBudgetExhausted) else str(error)
                break
            if read_current_recovery_case(run).get("status") in MAINTENANCE_BLOCKING_STATUSES:
                runtime_status, reason = "blocked", "maintenance_confirmation_required"
                break
            control = read_runtime_control(run)
            if control.get("desired_state") != "running":
                runtime_status, reason = "paused", "user_paused"
                break
            elapsed = elapsed_before + _seconds_until(now_func(), start)
            if elapsed >= float(control.get("max_runtime_seconds", 21600)):
                runtime_status, reason = "blocked", "runtime_budget_exhausted"
                break
            update_runtime_status(run, status="running", next_wake_at="", elapsed_seconds=elapsed)
            try:
                waiting = _daily_wait_result(run, result, now_func())
                reconciliation_only = waiting is not None and _daily_reconciliation_due(run, str(result.get('current_stage', '')), now_func())
                if reconciliation_only:
                    wait_path = run / 'runtime/daily_budget_wait.json'
                    _write(wait_path, {**_read(wait_path), 'last_reconciled_at': now_func()})
                    prior_reconcile = os.environ.get(DAILY_RECONCILE_ENV)
                    os.environ[DAILY_RECONCILE_ENV] = '1'
                    try:
                        result = step()
                    finally:
                        if prior_reconcile is None:
                            os.environ.pop(DAILY_RECONCILE_ENV, None)
                        else:
                            os.environ[DAILY_RECONCILE_ENV] = prior_reconcile
                else:
                    result = waiting if waiting is not None else step()
                if (grouped and not result.get('run_dir') or
                        result.get('run_dir') and Path(result['run_dir']).resolve() != run.resolve()):
                    raise ValueError('driver lane result run identity mismatch')
                require_group_running(run)
            except RateLimitRecoveryRequired as error:
                from wqb.rate_limit_state import read_rate_limit_state, MAX_CONSECUTIVE_429
                rate_state = read_rate_limit_state(Path(error.source_run_dir) / 'rate_limit_state.json')
                threshold = MAX_CONSECUTIVE_429 - int(getattr(error, 'simulation_submit', True))
                needs_lease = int(rate_state.get('consecutive_429_count', 0)) >= threshold
                result = {**result, "next_action": "maintenance-blocker" if needs_lease else 'rate-limit-wait', "source_bridge": {
                    "source_run_dir": error.source_run_dir, "metadata": {
                        "retry_at": error.retry_at, "operator_acknowledgement_required": needs_lease}}}
            except RuntimeBudgetExhausted:
                runtime_status, reason = 'blocked', 'runtime_budget_exhausted'
                break
            except DailyBudgetExhausted as error:
                budget = error.budget
                prior_wait = _read(run / 'runtime/daily_budget_wait.json')
                _write(run / 'runtime/daily_budget_wait.json', {
                    **prior_wait,
                    'status': 'waiting', 'policy_id': budget['policy_id'],
                    'budget_date': budget['budget_date'], 'next_reset_at': budget['next_reset_at'],
                    'required_count': max(prior_wait.get('required_count', 1), budget.get('required_count', 1)),
                    'created_at': prior_wait.get('created_at', now_func())})
                result = {**result, 'next_action': 'daily-budget-wait', 'daily_simulation_budget': budget}
            except RuntimePaused as error:
                runtime_status = "paused" if (read_runtime_control(run).get("desired_state") == "paused"
                                              or str(error) == 'research group is paused') else "blocked"
                reason = ('research_simulation_budget_exhausted'
                          if runtime_status == 'blocked' and str(error) == 'simulation attempt budget exhausted' else str(error))
                break
            result = _repair_cooldown_result(run, result, now_func())
            if (not reconciliation_only and result.get('next_action') not in {
                    'daily-budget-wait', 'rate-limit-wait', 'source-lock-wait', 'simulation-progress-wait'}
                    and not (result.get('source_bridge', {}).get('metadata', {}).get('operator_acknowledgement_required'))
                    and not (config.get('managed_research_execution') and result.get('current_stage') == 'scout_seed')):
                try:
                    schedule_run_checkpoint(run, result, now_func(), resolve_ai_executor_argv(config))
                except RuntimeBudgetExhausted:
                    runtime_status, reason = 'blocked', 'runtime_budget_exhausted'
                    break
                except RuntimePaused as error:
                    runtime_status = 'paused' if read_runtime_control(run).get('desired_state') == 'paused' else 'blocked'
                    reason = 'user_paused' if runtime_status == 'paused' else str(error)
                    break
            update_runtime_status(run, last_result=result)
            if result.get("waiting_for_user") or result.get("status") == "waiting_for_user":
                runtime_status, reason = "waiting_for_user", "approval_required"
                break
            if result.get("status") in {"completed", "completed_with_warnings", "aborted"}:
                runtime_status, reason = str(result["status"]), ""
                break
            bridge = result.get("source_bridge") or {}
            metadata = bridge.get("metadata") or {}
            action = str(result.get("next_action", ""))
            if action == 'daily-budget-wait':
                budget = result['daily_simulation_budget']
                wake = budget['next_reset_at']
                update_runtime_status(run, status='waiting', reason='daily_budget_exhausted', next_wake_at=wake)
                while _seconds_until(wake, now_func()) > 0:
                    try:
                        require_group_running(run)
                    except RuntimePaused:
                        break
                    current = read_runtime_control(run)
                    if current.get('invalid'):
                        raise ValueError('daily budget authority became invalid during wait')
                    if (current.get('desired_state') != 'running'
                            or read_current_recovery_case(run).get('status') in MAINTENANCE_BLOCKING_STATUSES
                            or elapsed_before + _seconds_until(now_func(), start) >= float(current['max_runtime_seconds'])):
                        break
                    if _daily_reconciliation_due(run, str(result.get('current_stage', '')), now_func()):
                        break
                    part = min(WAIT_SLICE_SECONDS, _seconds_until(wake, now_func()))
                    reserved_elapsed = elapsed_before + _seconds_until(now_func(), start) + part
                    update_runtime_status(run, elapsed_seconds=reserved_elapsed)
                    try:
                        sleep_func(part)
                    finally:
                        update_runtime_status(run, elapsed_seconds=max(reserved_elapsed,
                            elapsed_before + _seconds_until(now_func(), start)))
                continue
            recoverable_rate_limit = action == "maintenance-blocker" and metadata.get("operator_acknowledgement_required") is True
            if action in {"rate-limit-wait", "source-lock-wait", "simulation-progress-wait"} or recoverable_rate_limit:
                wake = str(metadata.get("retry_at", ""))
                update_runtime_status(run, status="waiting", next_wake_at=wake,
                                      reason="simulation_processing" if action == 'simulation-progress-wait' else "platform_cooldown")
                while _seconds_until(wake, now_func()) > 0:
                    try:
                        require_group_running(run)
                    except RuntimePaused:
                        break
                    if read_runtime_control(run).get("desired_state") != "running":
                        break
                    if elapsed_before + _seconds_until(now_func(), start) >= float(control.get("max_runtime_seconds", 21600)):
                        break
                    sleep_func(min(WAIT_SLICE_SECONDS, _seconds_until(wake, now_func())))
                try:
                    require_group_running(run)
                except RuntimePaused:
                    continue
                if read_runtime_control(run).get("desired_state") != "running":
                    continue
                if elapsed_before + _seconds_until(now_func(), start) >= float(control.get("max_runtime_seconds", 21600)):
                    runtime_status, reason = "blocked", "runtime_budget_exhausted"
                    break
                if recoverable_rate_limit:
                    used = int(read_runtime_control(run).get("recovery_attempts", 0))
                    if used >= int(control.get("max_recoveries", 3)) or not control.get("enable_live_api"):
                        runtime_status, reason = "blocked", "automatic_recovery_budget_exhausted"
                        break
                    from wqb.research_group import authorize_group_retry
                    source = str(bridge.get("source_run_dir", ""))
                    if not source:
                        runtime_status, reason = "blocked", "missing_recovery_source"
                        break
                    try:
                        authorize_group_retry(run, Path(source), now_func())
                    except RuntimePaused as error:
                        runtime_status, reason = 'blocked', str(error)
                        break
                    update_runtime_status(run, recovery_attempts=used + 1, recovery_rate_limit_source=source)
                sleep_func(WAIT_SLICE_SECONDS)
                continue
            if action in {"maintenance-blocker", "readiness-blocked", "enable-live-api-required", "source-batch-runner-missing",
                          "research-loop-blocked", "research-mission-authority-required"} or result.get("status") == "failed":
                runtime_status, reason = "blocked", action or "stage_failed"
                if action == 'research-loop-blocked' and result.get('pause_reason') in RESOURCE_ACTIONS:
                    reason = result['pause_reason']
                break
            signature = json.dumps(result, sort_keys=True, default=str)
            no_progress = no_progress + 1 if signature == previous else 0
            previous = signature
            if no_progress >= int(config.get("runtime_no_progress_limit", DEFAULT_NO_PROGRESS_LIMIT)):
                runtime_status, reason = "blocked", "no_progress_detected"
                break
        if runtime_status == "blocked" and reason not in {*RESOURCE_ACTIONS, "maintenance_confirmation_required"}:
            blocker = classify_blocker({**result, "next_action": reason})
            case = ensure_recovery_case(run, blocker, now_func())
            case = advance_scripted_recovery(run, case, config, now_func())
            update_runtime_status(run, recovery_case=case, status="blocked", reason=reason)
            case = dispatch_notification(run, case, now_func())
            update_runtime_status(run, recovery_case=case)
        update_runtime_status(run, status=runtime_status, reason=reason, next_wake_at="", last_result=result,
                              elapsed_seconds=elapsed_before + _seconds_until(now_func(), start))
        from wqb.runtime_boundaries import record_runtime_boundary, dispatch_boundary_notice, project_runtime_boundary
        if runtime_status == 'blocked' and reason in RESOURCE_ACTIONS:
            boundary = record_runtime_boundary(run, reason, {'current_stage': result.get('current_stage'),
                'step_limit': int(config.get('runtime_max_steps', DEFAULT_MAX_STEPS)),
                'steps_used': int(config.get('runtime_max_steps', DEFAULT_MAX_STEPS)),
                'last_result': result}, now_func())
            boundary = dispatch_boundary_notice(run, boundary, now_func())
            update_runtime_status(run, runtime_boundary=boundary)
            result = project_runtime_boundary(result, read_runtime_control(run))
        return {**result, "runtime_status": runtime_status, "runtime_reason": reason}
    except Exception as error:
        update_runtime_status(run, status="error", reason=f"{type(error).__name__}: {error}")
        raise
    finally:
        if prior_deadline is None:
            os.environ.pop(DEADLINE_ENV, None)
        else:
            os.environ[DEADLINE_ENV] = prior_deadline
        heartbeat_stop.set()
        heartbeat_worker.join(2)
        if prior_env is None:
            os.environ.pop(CONTROL_ENV, None)
        else:
            os.environ[CONTROL_ENV] = prior_env
        release_source_run_lock(lock_dir, "workflow-driver", now_func(), owner_id=str(lock.get("owner_id", "")))
