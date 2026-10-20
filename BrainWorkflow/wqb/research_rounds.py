"""Orchestrator-owned bounded rounds; no platform calls or authority creation."""

from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from uuid import uuid4

from wqb.data_ledger import data_ledger_record_from_dict, is_authoritative_data_record
from wqb.lockfile import json_lock_transition_guard
from wqb.runtime_control import runtime_authority_is_complete, RuntimePaused
from wqb.source_bridge import SOURCE_BINDING_RELATIVE_PATH, _has_in_flight_simulation
from wqb.stage_outcomes import checked_research_rows, research_outcome
from wqb.submission_attempts import uncertain_submission_hashes
from wqb.template_library import select_templates_for_data, template_record_from_dict
from wqb.workflow_state import (
    STATE_FILENAME, WorkflowStageState, load_run_state, transition_run_state, write_run_state,
)


SCOUT_CANDIDATE_COUNT = 30
ROUND_STATE_FILENAME = 'research_rounds.json'
ROUND_SCHEMA_VERSION = 1
ROUND_LOCK_TIMEOUT_SECONDS = 5.0
ROUND_LOCK_SLEEP_SECONDS = 0.05
ROUND_ARTIFACTS = (
    'all_alphas.jsonl', 'candidates.csv', 'simulation_events.jsonl', 'run_errors.jsonl',
    'run_summary.md', 'candidate_gate.json',
    'stages/scout_seed', 'stages/batch_generation', 'stages/backtest', 'stages/triage',
    'stages/repair', 'stages/candidate_gate', 'stages/user_approval', 'stages/approved_queue',
    'stages/research_record_sync',
)


def _read(path: Path) -> dict:
    """Input: JSON Path. Output: dict. Reject malformed durable state without replacing evidence."""
    if not path.exists():
        return {}
    row = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(row, dict):
        raise ValueError(f'expected JSON object: {path.name}')
    return row


def _write(path: Path, row: dict) -> None:
    """Input: JSON Path, dict. Output: None. Atomically publish a round receipt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def mission_round_authorized(run: Path) -> bool:
    """Input: run Path. Output: bool. Accept validated Start limits, never original-only authority/defaults."""
    try:
        control = _read(Path(run) / 'runtime_control.json')
        return (runtime_authority_is_complete(control)
                and not control.get('original_batch_scope_id')
                and (not (Path(run) / 'runtime/original_batch_scope.json').exists())
                and ('max_rounds' not in control or
                     type(control['max_rounds']) is int and control['max_rounds'] > 0))
    except (OSError, ValueError, TypeError):
        return False


def research_round_limit(control: dict) -> int:
    """Input: validated runtime control dict. Output: int. Share derived round ceiling without enlarging explicit limits."""
    maximum = control['max_simulations']
    ceiling = max(1, (maximum + SCOUT_CANDIDATE_COUNT - 1) // SCOUT_CANDIDATE_COUNT)
    return min(control.get('max_rounds', ceiling), ceiling)


def completed_original_batch(run: Path) -> bool:
    """Input: run Path. Output: bool. Verify finished protected scope and stopped worker before a NEW Start may supersede it."""
    from wqb.original_batch_recovery import read_original_batch, _inventory
    try:
        if _read(run / 'runtime_status.json').get('status') not in {'completed', 'blocked', 'paused'}:
            return False
        scope = read_original_batch(run)
        if not scope:
            return False
        plan, _, checked = _inventory(Path(scope['source_run_dir']))
        return bool(plan) and all(row.get('expression_hash') in checked for row in plan)
    except (OSError, ValueError, RuntimeError, KeyError):
        return False


def finish_original_batch_handoff(run: Path, now: str) -> dict:
    """Input: run Path, timestamp str. Output: decision dict. Record controller handoff without widening scope."""
    run = Path(run)
    try:
        control = _read(run / 'runtime_control.json')
    except (OSError, ValueError):
        control = {}
    reason = ('research_mission_authority_required' if not mission_round_authorized(run) else
              'user_paused' if control.get('desired_state') != 'running' else '')
    result = {'status': 'blocked' if reason else 'continue_research', 'stop_reason': reason,
              'next_action': 'workflow-auto-continue' if not reason else 'research-mission-authority-required'
              if reason == 'research_mission_authority_required' else 'workflow-resume',
              'run_id': run.name, 'recorded_at': now}
    _write(run / 'runtime/research_handoff.json', result)
    return result


def _identity(match: dict) -> list:
    """Input: scheduled match dict. Output: identity list[str]. Deduplicate hypotheses by data/template unit."""
    if match.get('hypothesis_id'):
        return ['hypothesis_v2', *[match.get(key) for key in ('template_id', 'hypothesis_id', 'hypothesis_version', 'binding_id')]]
    return [match.get(key, '') for key in ('dataset_id', 'field_id', 'template_id')]


def _select_next_match(schedule: dict, manifest: dict, tried: list) -> dict:
    """Input: schedule, immutable manifest dicts, tried identities list. Output: measured compatible match or {}."""
    snapshot = manifest.get('start_snapshot', {})
    if snapshot.get('hypothesis_binding_version') == 2:
        from wqb.hypothesis_selection import validate_hypothesis_match
        scope = snapshot['selected_scope']
        if any(schedule.get(key) != scope.get(key) for key in ('region', 'delay', 'universe')):
            return {}
        for match in schedule.get('template_matches', []):
            if not isinstance(match, dict) or _identity(match) in tried:
                continue
            try:
                validate_hypothesis_match(snapshot, match)
            except (ValueError, TypeError, KeyError):
                continue
            return dict(match)
        return {}
    scope = manifest.get('selected_scope', {})
    templates = [template_record_from_dict(row) for row in snapshot.get('template_rows', [])]
    incentive = snapshot.get('selected_option', {}).get('primary_incentive', '')
    if any(schedule.get(key) != scope.get(key) for key in ('region', 'delay', 'universe')):
        return {}
    for match in schedule.get('template_matches', []):
        if not isinstance(match, dict) or _identity(match) in tried:
            continue
        for row in schedule.get('selected_data', []):
            if (row.get('dataset_id') != match.get('dataset_id')
                    or row.get('field_id') != match.get('field_id')):
                continue
            snapshot_row = next((item for item in snapshot.get('data_ledger_rows', [])
                if all(item.get(key) == row.get(key) for key in
                       ('dataset_id', 'field_id', 'field_type', 'region', 'delay', 'universe'))), None)
            if snapshot_row is None:
                continue
            record = data_ledger_record_from_dict(snapshot_row)
            scheduled_record = data_ledger_record_from_dict(row)
            if (not is_authoritative_data_record(scheduled_record, Path(manifest['knowledge_root']))
                    or not record.source_paths or record.coverage <= 0
                    or not is_authoritative_data_record(record, Path(manifest['knowledge_root']))):
                continue
            compatible = select_templates_for_data(
                templates, record, incentive, len(templates), region=scope['region'],
                delay=scope['delay'], universe=scope['universe'])
            if any(template.template_id == match.get('template_id')
                   and template.skeleton == match.get('skeleton')
                   and template.hypothesis == match.get('hypothesis')
                   and template.hypothesis.strip() for template in compatible):
                return dict(match)
    return {}


def _source_reconciliation_required(run: Path) -> bool:
    """Input: run Path. Output: bool. Refuse to detach unknown or in-flight source evidence."""
    binding = _read(run / SOURCE_BINDING_RELATIVE_PATH)
    roots = [run, run / 'stages/batch_generation/source', run / 'stages/repair/source']
    if binding:
        source_id = binding.get('source_run_id', '')
        source = run.parent / str(source_id)
        if (not source_id or source.resolve().parent != run.parent.resolve()
                or not source.is_dir()
                or str(source.resolve()) != str(Path(binding.get('source_run_dir', '')).resolve())):
            return True
        roots.append(source)
    for root in roots:
        path = root / 'simulation_events.jsonl'
        rows = ([json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
                if path.exists() else [])
        if uncertain_submission_hashes(rows) or path.exists() and _has_in_flight_simulation(path):
            return True
        planned = root / 'planned_candidates.jsonl'
        if planned.exists():
            hashes = {row['expression_hash'] for row in checked_research_rows(root)}
            hashes.update(row.get('expression_hash') for row in rows if row.get('event') == 'ERROR')
            candidates = [json.loads(line) for line in planned.read_text(encoding='utf-8').splitlines()
                          if line.strip()]
            if any(not row.get('expression_hash') or row['expression_hash'] not in hashes for row in candidates):
                return True
    return False


def rotate_exhausted_scout_plan(run: Path, now: str, *, exhausted: bool = False) -> bool:
    """Input: run Path, timestamp str, zero-candidate flag bool. Output: bool. Journal a safe same-round alternate without POST or quota changes."""
    run = Path(run)
    with json_lock_transition_guard(run / 'runtime/research_rounds', ROUND_LOCK_TIMEOUT_SECONDS,
                                    ROUND_LOCK_SLEEP_SECONDS, 'research selection busy'):
        with json_lock_transition_guard(run / 'runtime/control_intent', ROUND_LOCK_TIMEOUT_SECONDS,
                                        ROUND_LOCK_SLEEP_SECONDS, 'runtime intent busy during selection'):
            ledger = _read(run / ROUND_STATE_FILENAME)
            pending = ledger.get('pending_scout_selection')
            if not exhausted and not pending:
                return False
            control = _read(run / 'runtime_control.json')
            state = load_run_state(run / STATE_FILENAME)
            if (not mission_round_authorized(run) or control.get('desired_state') != 'running'
                    or state.current_stage != 'scout_seed'):
                raise RuntimePaused('Scout selection requires a running mission')
            if (run / 'all_alphas.jsonl').exists() or _source_reconciliation_required(run):
                raise ValueError('Scout selection requires reconciled unsubmitted work')
            schedule_path = run / 'stages/schedule/research_schedule.json'
            schedule = _read(schedule_path)
            manifest = _read(run / 'run_manifest.json')
            if not ledger:
                ledger = {'schema_version': ROUND_SCHEMA_VERSION, 'run_id': run.name,
                          'current_round_id': schedule.get('research_round_id', 'round-0001'), 'rounds': []}
            if ledger.get('schema_version') != ROUND_SCHEMA_VERSION or ledger.get('run_id') != run.name:
                raise ValueError('research selection ledger mismatch')
            rejected = ledger.setdefault('exhausted_scout_selections', [])
            if pending:
                if not isinstance(pending, dict) or not isinstance(pending.get('selection'), dict):
                    raise ValueError('invalid prepared Scout selection')
                selected = pending['selection']
            else:
                matches = schedule.get('template_matches', [])
                if not matches:
                    return False
                entry = {'round_id': ledger['current_round_id'], 'selection_identity': _identity(matches[0]),
                         'selection': matches[0], 'reason': 'zero_valid_novel_candidates'}
                if not any(row['round_id'] == entry['round_id'] and
                           row['selection_identity'] == entry['selection_identity'] for row in rejected):
                    rejected.append(entry)
                tried = [row['selection_identity'] for row in ledger['rounds']
                         if row['round_id'] != ledger['current_round_id']]
                tried += [row['selection_identity'] for row in rejected]
                selected = _select_next_match(schedule, manifest, tried)
                if not selected:
                    _write(run / ROUND_STATE_FILENAME, ledger)
                    return False
                ledger['pending_scout_selection'] = {'selection': selected, 'recorded_at': now}
                _write(run / ROUND_STATE_FILENAME, ledger)
            # Validate replay too; the prepared journal is not authority to alter the snapshot.
            verified = _select_next_match({**schedule, 'template_matches': [selected]}, manifest, [])
            if verified != selected:
                raise ValueError('Scout alternate differs from authoritative snapshot')
            matches = schedule.get('template_matches', [])
            next_schedule = {**schedule, 'template_matches': [selected, *[
                row for row in matches if _identity(row) != _identity(selected)]]}
            if manifest.get('start_snapshot', {}).get('hypothesis_binding_version') == 2:
                next_schedule['hypothesis_allowed_refs'] = [{key: selected[key] for key in (
                    'template_id', 'hypothesis_id', 'hypothesis_version', 'binding_id') if key in selected}]
            _write(schedule_path, next_schedule)
            for row in ledger['rounds']:
                if row['round_id'] == ledger['current_round_id']:
                    row.update(selection=selected, selection_identity=_identity(selected))
            ledger.pop('pending_scout_selection', None)
            _write(run / ROUND_STATE_FILENAME, ledger)
            return True


def _stop(run: Path, ledger: dict, reason: str, now: str) -> dict:
    """Input: run Path, ledger dict, reason/timestamp str. Output: blocked dict. Persist a nonterminal stop."""
    ledger.update(status='blocked', stop_reason=reason, next_transition='blocked', updated_at=now)
    _write(run / ROUND_STATE_FILENAME, ledger)
    state = load_run_state(run / STATE_FILENAME)
    if state.status == 'running':
        state = transition_run_state(state, 'paused', reason)
        stages = dict(state.stages)
        stages[state.current_stage] = replace(stages[state.current_stage], status='paused', blocker=reason)
        state = replace(state, stages=stages, updated_at=now)
        write_run_state(run / STATE_FILENAME, state)
    return {'status': 'blocked', 'stop_reason': reason, 'round_id': ledger.get('current_round_id', '')}


def _apply_transition(run: Path, ledger: dict, now: str) -> dict:
    """Input: run Path, prepared ledger dict, timestamp str. Output: advanced dict. Replay an interrupted reset safely."""
    transition = ledger['pending_transition']
    parent_id = transition.get('parent_round_id')
    round_ids = [row.get('round_id') for row in ledger.get('rounds', [])]
    if (parent_id not in round_ids or ledger.get('current_round_id') not in round_ids
            or not isinstance(parent_id, str) or Path(parent_id).name != parent_id
            or parent_id in {'.', '..'}
            or any(name not in ROUND_ARTIFACTS for name in transition.get('artifacts', []))):
        raise ValueError('invalid round transition identity/artifact paths')
    archive = run / 'rounds' / transition['parent_round_id']
    if archive.resolve().parent != (run / 'rounds').resolve() or (run / 'rounds').is_symlink():
        raise ValueError('invalid round transition archive path')
    archive.mkdir(parents=True, exist_ok=True)
    for relative in transition['artifacts']:
        source, target = run / relative, archive / relative
        if source.exists() and target.exists():
            raise ValueError('round archive conflict requires maintenance')
        if source.exists():
            if source.is_symlink():
                raise ValueError('round artifact must not be a symlink')
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
    schedule = transition['schedule']
    _write(run / 'stages/schedule/research_schedule.json', schedule)
    state = load_run_state(run / STATE_FILENAME)
    stages = dict(state.stages)
    for name in stages:
        if name not in {'objective_selected', 'schedule', 'complete'}:
            stages[name] = WorkflowStageState(name=name)
    state = replace(state, stages=stages, current_stage='scout_seed', last_completed_stage='schedule',
                    next_action='workflow-continue', waiting_for_user=False, research_record_synced=False,
                    updated_at=now)
    write_run_state(run / STATE_FILENAME, state)
    ledger.update(status='running', stop_reason='', next_transition='scout_seed', updated_at=now)
    ledger.pop('pending_transition')
    _write(run / ROUND_STATE_FILENAME, ledger)
    return {'status': 'advanced', 'round_id': ledger['current_round_id'], 'next_stage': 'scout_seed'}


def recover_pending_research_round(run: Path, now: str) -> dict | None:
    """Input: run Path, timestamp str. Output: transition dict or None. Recover before normal stage diagnostics."""
    ledger = _read(Path(run) / ROUND_STATE_FILENAME)
    if not ledger.get('pending_transition'):
        return None
    return advance_research_round(Path(run), now, {})


def release_verified_partial_budget_stop(run: Path, case_id: str, now: str) -> bool:
    """Input: run Path, verified case/time str. Output: bool. Release an obsolete full-batch stop locally without Start or quota changes."""
    from wqb.recovery_cases import read_current_recovery_case
    from wqb.runtime_control import read_runtime_control
    run = Path(run)
    with json_lock_transition_guard(run / 'runtime/research_rounds', ROUND_LOCK_TIMEOUT_SECONDS,
                                    ROUND_LOCK_SLEEP_SECONDS, 'budget release busy'):
        with json_lock_transition_guard(run / 'runtime/control_intent', ROUND_LOCK_TIMEOUT_SECONDS,
                                        ROUND_LOCK_SLEEP_SECONDS, 'budget release intent busy'):
            case = read_current_recovery_case(run)
            if case.get('case_id') != case_id or case.get('status') != 'resolved':
                return False
            state = load_run_state(run / STATE_FILENAME)
            ledger = _read(run / ROUND_STATE_FILENAME)
            already_released = (ledger.get('resolved_case_id') == case_id and ledger.get('status') == 'ready'
                                and state.pause_reason == 'Verified remaining simulation budget is available')
            if (state.status != 'paused' or not (already_released or state.pause_reason == 'research_simulation_budget_exhausted')
                    or case.get('stage') != state.current_stage
                    or ledger.get('run_id') != run.name or not mission_round_authorized(run)):
                return False
            control = read_runtime_control(run)
            usage = control.get('simulation_attempts')
            if type(usage) is not int or usage < 0:
                return False
            used = max(usage, state.budget_used, sum(row['budget_reserved'] for row in ledger['rounds']))
            if (used >= control['max_simulations']
                    or max(1, len(ledger['rounds'])) >= research_round_limit(control)
                    or _source_reconciliation_required(run)):
                return False
            schedule = _read(run / 'stages/schedule/research_schedule.json')
            tried = [row['selection_identity'] for row in ledger['rounds']]
            if not tried and schedule.get('template_matches'):
                tried = [_identity(schedule['template_matches'][0])]
            tried += [row['selection_identity'] for row in ledger.get('exhausted_scout_selections', [])]
            if not _select_next_match(schedule, _read(run / 'run_manifest.json'), tried):
                return False
            if already_released:
                return True
            ledger.update(status='ready', stop_reason='', next_transition='round_recheck',
                          resolved_case_id=case_id, updated_at=now)
            _write(run / ROUND_STATE_FILENAME, ledger)
            stages = dict(state.stages)
            stages[state.current_stage] = replace(stages[state.current_stage], blocker='')
            write_run_state(run / STATE_FILENAME, replace(state, stages=stages,
                pause_reason='Verified remaining simulation budget is available', updated_at=now))
            return True


def advance_research_round(run: Path, now: str, result: dict) -> dict:
    """Input: run Path, timestamp str, stage result dict. Output: decision dict. Rotate bounded measured rounds locally."""
    run = Path(run)
    with json_lock_transition_guard(run / 'runtime/research_rounds', ROUND_LOCK_TIMEOUT_SECONDS,
                                    ROUND_LOCK_SLEEP_SECONDS, 'research round transition busy'):
        with json_lock_transition_guard(run / 'runtime/control_intent', ROUND_LOCK_TIMEOUT_SECONDS,
                                        ROUND_LOCK_SLEEP_SECONDS, 'runtime intent busy during round transition'):
            return _advance_unlocked(run, now, result)


def _advance_unlocked(run: Path, now: str, result: dict) -> dict:
    """Input: run Path, timestamp str, result dict. Output: decision dict. Validate then journal under round lock."""
    ledger = _read(run / ROUND_STATE_FILENAME) or {
        'schema_version': ROUND_SCHEMA_VERSION, 'run_id': run.name, 'rounds': [],
        'current_round_id': 'round-0001',
    }
    if ledger.get('schema_version') != ROUND_SCHEMA_VERSION or ledger.get('run_id') != run.name:
        raise ValueError('research round state identity/version mismatch')
    if not mission_round_authorized(run):
        return _stop(run, ledger, 'research_mission_authority_required', now)
    control = _read(run / 'runtime_control.json')
    state = load_run_state(run / STATE_FILENAME)
    if control.get('desired_state') != 'running' or state.status != 'running':
        return _stop(run, ledger, 'user_paused', now)
    if ledger.get('pending_transition'):
        return _apply_transition(run, ledger, now)
    if ledger['rounds'] and state.current_stage == 'scout_seed' and not (run / 'all_alphas.jsonl').exists():
        return {'status': 'advanced', 'round_id': ledger['current_round_id'], 'next_stage': 'scout_seed'}
    if state.current_stage not in {'triage', 'repair'}:
        return {'status': 'not_applicable', 'round_id': ledger['current_round_id']}
    outcome = research_outcome(run)
    if outcome['outcome'] in {'pending_review', 'missing_results'}:
        return _stop(run, ledger, 'research_evidence_reconciliation_required', now)
    if not (outcome['outcome'] == 'no_signal' or
            state.current_stage == 'repair' and result.get('next_stage') == 'research_record_sync'
            and result.get('status') == 'completed' and not outcome['counts']['hard_pass']):
        return {'status': 'not_applicable', 'round_id': ledger['current_round_id']}
    if _source_reconciliation_required(run):
        return _stop(run, ledger, 'research_source_reconciliation_required', now)
    usage = _read(run / 'runtime_status.json').get('simulation_attempts')
    if type(usage) is not int or usage < 0:
        return _stop(run, ledger, 'research_budget_accounting_required', now)
    maximum = control['max_simulations']
    max_rounds = research_round_limit(control)
    used = max(usage, state.budget_used, sum(row['budget_reserved'] for row in ledger['rounds']))
    next_batch_cap = min(SCOUT_CANDIDATE_COUNT, maximum - used)
    if next_batch_cap <= 0:
        return _stop(run, ledger, 'research_simulation_budget_exhausted', now)
    if max(1, len(ledger['rounds'])) >= max_rounds:
        return _stop(run, ledger, 'research_round_budget_exhausted', now)
    schedule = _read(run / 'stages/schedule/research_schedule.json')
    manifest = _read(run / 'run_manifest.json')
    matches = schedule.get('template_matches', [])
    if not matches:
        return _stop(run, ledger, 'research_plan_unavailable', now)
    tried = [row['selection_identity'] for row in ledger['rounds']] or [_identity(matches[0])]
    tried += [row['selection_identity'] for row in ledger.get('exhausted_scout_selections', [])]
    selected = _select_next_match(schedule, manifest, tried)
    if not selected:
        return _stop(run, ledger, 'research_plan_unavailable', now)
    binding = _read(run / SOURCE_BINDING_RELATIVE_PATH)
    parent_id = ledger['current_round_id']
    archive = run / 'rounds' / parent_id
    archive.mkdir(parents=True, exist_ok=True)
    if not ledger['rounds']:
        ledger['rounds'].append({'round_id': parent_id, 'selection_identity': _identity(matches[0]),
                                 'selection': matches[0], 'budget_reserved': used})
    parent = ledger['rounds'][-1]
    parent.update(source_run_id=binding.get('source_run_id', ''), outcome=outcome['outcome'],
                  classification_version=ROUND_SCHEMA_VERSION,
                  candidate_hashes=[row['expression_hash'] for row in outcome['rows']],
                  budget_used=usage, closed_at=now, next_transition='scout_seed')
    _write(archive / 'round.json', parent)
    _write(archive / 'run_state.json', asdict(state))
    _write(archive / 'research_schedule.json', schedule)
    if (run / 'research_record.json').exists():
        _write(archive / 'research_record.json', _read(run / 'research_record.json'))
    next_id = f'round-{len(ledger["rounds"]) + 1:04d}'
    ledger['rounds'].append({'round_id': next_id, 'parent_round_id': parent_id,
                             'parent_source_run_id': binding.get('source_run_id', ''),
                             'selection_identity': _identity(selected), 'selection': selected,
                             'budget_reserved': next_batch_cap, 'created_at': now})
    next_schedule = {**schedule, 'template_matches': [selected, *[
        match for match in matches if _identity(match) != _identity(selected)]],
        'batch_size': next_batch_cap, 'research_round_id': next_id,
        'parent_source_run_id': binding.get('source_run_id', ''),
        'excluded_source_run_ids': [row.get('source_run_id') for row in ledger['rounds'] if row.get('source_run_id')]}
    if manifest.get('start_snapshot', {}).get('hypothesis_binding_version') == 2:
        next_schedule['hypothesis_allowed_refs'] = [{key: selected[key] for key in (
            'template_id', 'hypothesis_id', 'hypothesis_version', 'binding_id') if key in selected}]
    ledger.update(current_round_id=next_id, max_rounds=max_rounds, max_simulations=maximum,
                  pending_transition={'parent_round_id': parent_id, 'schedule': next_schedule,
                                      'artifacts': [name for name in ROUND_ARTIFACTS if (run / name).exists()]})
    _write(run / ROUND_STATE_FILENAME, ledger)
    return _apply_transition(run, ledger, now)
