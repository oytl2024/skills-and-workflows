from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from wqb.runtime_control import CONTROL_ENV, RuntimePaused, _read, _write, utc_now
from wqb.lockfile import json_lock_transition_guard
from wqb.source_run_lock import acquire_source_run_lock, release_source_run_lock
from wqb.submission_attempts import uncertain_submission_hashes


MAX_RECOVERIES = 3
MAX_RUNTIME_SECONDS = 21600
SCOPE_FILE = 'runtime/original_batch_scope.json'


def _rows(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL Path. Output: dict list. Read original evidence without altering it."""
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []


def _digest(path: Path) -> str:
    """Input: file Path. Output: SHA256 str. Bind scope to immutable plan bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(run: Path) -> Path:
    """Input: parent run Path. Output: source Path. Resolve only its explicitly bound batch."""
    row = json.loads((run / 'stages/scout_seed/source_bridge_binding.json').read_text(encoding='utf-8'))
    return Path(row['source_run_dir']).resolve()


def _inventory(source: Path, require_reconciled: bool = True) -> tuple[list[dict], set[str], set[str]]:
    """Input: source Path. Output: plan, submitted and terminal hashes. Preserve uncertain outcomes."""
    events = _rows(source / 'simulation_events.jsonl')
    if require_reconciled and uncertain_submission_hashes(events):
        raise RuntimePaused('uncertain simulation submission requires reconciliation')
    done = {str(row.get('expression_hash', '')) for row in events if row.get('event') in {'CHECKED', 'ERROR'}}
    submitted = done | {str(row.get('expression_hash', '')) for row in events if row.get('event') == 'SUBMITTED'}
    done |= {str(row.get('expression_hash', '')) for row in _rows(source / 'all_alphas.jsonl')}
    return _rows(source / 'planned_candidates.jsonl'), submitted | done, done


def read_original_batch(run: Path) -> dict[str, Any]:
    """Input: parent run Path. Output: verified scope dict, or empty. Refuse source/plan drift."""
    path = Path(run) / SCOPE_FILE
    if not path.exists():
        return {}
    row = _read(path)
    try:
        source = _binding(Path(run))
        if (row.get('invalid') or str(source) != row['source_run_dir']
                or _digest(source / 'planned_candidates.jsonl') != row['plan_digest']):
            raise RuntimePaused('original batch source or plan changed; maintenance required')
        if (not isinstance(row.get('scope_id'), str) or not row['scope_id']
                or not isinstance(row.get('settings'), dict) or not row['settings']
                or not isinstance(row.get('allowed_expressions'), list) or not row['allowed_expressions']
                or any(not isinstance(item, str) or not item for item in row['allowed_expressions'])
                or type(row.get('max_recoveries')) is not int or not 0 < row['max_recoveries'] <= MAX_RECOVERIES
                or type(row.get('max_runtime_seconds')) is not int
                or not 0 < row['max_runtime_seconds'] <= MAX_RUNTIME_SECONDS):
            raise RuntimePaused('original batch scope invalid; maintenance required')
    except (KeyError, OSError, ValueError) as error:
        raise RuntimePaused('original batch scope invalid; maintenance required') from error
    return row


def approve_original_batch(run: Path, settings: dict[str, Any], authorization: str) -> dict[str, Any]:
    """Input: run Path, verified original settings dict, human reference str. Output: paused, frozen scope receipt."""
    run = Path(run)
    if not authorization.strip() or not settings:
        raise ValueError('explicit authorization and verified original settings required')
    with json_lock_transition_guard(run / 'runtime/control_intent', 10, .02, 'runtime intent busy'):
        existing = read_original_batch(run)
        if existing:
            if existing['settings'] != settings:
                raise ValueError('original settings cannot be changed')
            return existing
        if _read(run / 'runtime_control.json'):
            raise ValueError('existing intent requires explicit reconciliation; cannot overwrite it')
        source = _binding(run)
        lock = acquire_source_run_lock(source, 'original-batch-adoption', utc_now())
        if lock.get('status') != 'acquired':
            raise RuntimePaused('source worker is active')
        try:
            plan, submitted, done = _inventory(source)
            pending = [row for row in plan if row.get('expression_hash') not in submitted]
            expressions = sorted({row['expression'] for row in pending})
            if not expressions:
                raise ValueError('no original pending candidates')
            receipt = {'scope_id': uuid4().hex, 'created_at': utc_now(), 'authorization': authorization,
                       'source_run_dir': str(source), 'plan_digest': _digest(source / 'planned_candidates.jsonl'),
                       'settings': settings, 'allowed_expressions': expressions, 'original_count': len(plan),
                       'completed_before': len(done), 'historical_attempts': None,
                       'max_recoveries': MAX_RECOVERIES, 'max_runtime_seconds': MAX_RUNTIME_SECONDS,
                       'new_research_allowed': False}
            _write(run / SCOPE_FILE, receipt)
            # Attempts cover only these identities plus bounded definitive-rejection retries.
            _write(run / 'runtime_control.json', {'desired_state': 'paused', 'enable_live_api': True,
                   'request_revision': uuid4().hex, 'created_at': utc_now(), 'original_batch_scope_id': receipt['scope_id'],
                   'max_simulations': len(expressions) * (MAX_RECOVERIES + 1),
                   'max_recoveries': MAX_RECOVERIES, 'max_runtime_seconds': MAX_RUNTIME_SECONDS})
            from wqb.runtime_control import update_runtime_status
            update_runtime_status(run, status='paused', reason='Original batch authorized; waiting for Console Resume')
            return receipt
        finally:
            release_source_run_lock(source, 'original-batch-adoption', utc_now(), owner_id=str(lock.get('owner_id', '')))


def validate_original_payloads(payloads: Any) -> None:
    """Input: POST payload dict/list. Output: none or RuntimePaused. Enforce frozen expression/settings allowlist."""
    run = os.environ.get(CONTROL_ENV)
    if not run:
        return
    scope = read_original_batch(Path(run))
    if not scope:
        return
    rows = payloads if isinstance(payloads, list) else [payloads]
    if not rows or any(not isinstance(row, dict) or row.get('type') != 'REGULAR'
                       or row.get('regular') not in scope['allowed_expressions']
                       or row.get('settings') != scope['settings'] for row in rows):
        raise RuntimePaused('simulation outside authorized original batch')


def original_batch_step(run: Path, config: dict[str, Any], now: str) -> dict[str, Any]:
    """Input: parent run, config dict, UTC str. Output: driver result. Recover only frozen work, never generate variants."""
    from wqb.cli import build_client, retry_planned_candidates, complete_in_flight_simulations
    from wqb.recorder import RunRecorder
    from wqb.knowledge_recovery import recover_knowledge
    from wqb.rate_limit_state import read_rate_limit_state, cooldown_is_active, check_source_retry_authorization
    from wqb.runtime_control import update_runtime_status
    scope = read_original_batch(run)
    if not scope:
        raise RuntimePaused('original batch authority required')
    source = Path(scope['source_run_dir'])
    base = {'active': True, 'run_dir': str(run), 'current_stage': 'scout_seed', 'status': 'paused'}
    plan, submitted, done = _inventory(source)
    if all(row.get('expression_hash') in done for row in plan):
        return {**base, 'status': 'completed', 'next_action': 'original-batch-complete',
                'message': 'Original batch finished; no new research or Alpha submission authorized.'}
    from wqb.runtime_control import check_submission_allowed
    if not os.environ.get(CONTROL_ENV) or Path(os.environ[CONTROL_ENV]).resolve() != Path(run).resolve():
        raise RuntimePaused('original batch recovery requires the managed Console driver')
    check_submission_allowed()
    original_config = {**config, **scope['settings']}
    original_config.pop('scope', None)
    update_runtime_status(run, reason='Maintaining original-scope knowledge before recovery')
    knowledge = recover_knowledge(Path(config['knowledge_root']), original_config, now, run)
    update_runtime_status(run, knowledge_recovery=knowledge, reason='Recovering original batch')
    if knowledge.get('status') != 'completed':
        return {**base, 'next_action': 'readiness-blocked', 'knowledge_recovery': knowledge}
    lock = acquire_source_run_lock(source, 'original-batch-recovery', now)
    if lock.get('status') != 'acquired':
        from datetime import datetime, timedelta
        wake = (datetime.fromisoformat(now.replace('Z', '+00:00')) + timedelta(seconds=2)).isoformat()
        return {**base, 'next_action': 'source-lock-wait', 'source_bridge': {'metadata': {'retry_at': wake}}}
    try:
        state = read_rate_limit_state(source / 'rate_limit_state.json')
        if cooldown_is_active(state, now):
            return {**base, 'next_action': 'rate-limit-wait', 'source_bridge': {
                'source_run_dir': str(source), 'metadata': {'retry_at': state.get('retry_at', '')}}}
        check_source_retry_authorization(source)
        settings = scope['settings']
        frozen = {**config, **settings, 'instrument_type': settings.get('instrumentType'),
                  'unit_handling': settings.get('unitHandling'), 'nan_handling': settings.get('nanHandling'),
                  'knowledge_root': knowledge.get('knowledge_root', config['knowledge_root']),
                  'max_retries': 0, 'request_timeout_seconds': 20}
        client = build_client(frozen)
        recorder = RunRecorder(source)
        if submitted - done:
            complete_in_flight_simulations(client, recorder)
        else:
            retry_planned_candidates(client, recorder, frozen, submit_mode='multi',
                                     multi_chunk_size=5, multi_chunk_sleep_seconds=0)
        plan, _, done = _inventory(source)
        if all(row.get('expression_hash') in done for row in plan):
            return {**base, 'status': 'completed', 'next_action': 'original-batch-complete'}
        state = read_rate_limit_state(source / 'rate_limit_state.json')
        if state.get('status') == 'cooldown':
            return {**base, 'next_action': 'maintenance-blocker', 'source_bridge': {
                'source_run_dir': str(source), 'metadata': {'retry_at': state.get('retry_at', ''),
                'operator_acknowledgement_required': True}}}
        return {**base, 'next_action': 'original-batch-recover', 'checked': len(done), 'planned': len(plan)}
    finally:
        release_source_run_lock(source, 'original-batch-recovery', utc_now(), owner_id=str(lock.get('owner_id', '')))
