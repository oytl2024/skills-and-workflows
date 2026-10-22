"""Run-local validated research judgments; never platform requests or code changes."""

import hashlib
import json
import copy
from pathlib import Path

from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
from wqb.generator import SCHEDULED_DECAYS
from wqb.runtime_control import _write


HYPOTHESIS_BRIEF_MAX_BYTES = 9000


class ResearchPlanningBlocked(RuntimeError):
    """Input: explanation str. Output: exception. Stop when a required research judgment is unavailable."""


class ResearchVariantsExhausted(ResearchPlanningBlocked):
    """Input: explanation str. Output: exception. No novel bounded variants remain; no simulation was submitted."""


def release_verified_planning_stop(run: Path, case_id: str, now: str) -> bool:
    """Input: run Path, resolved case ID/time str. Output: bool. Release only a verified planning handoff, never Start or change intent."""
    from dataclasses import replace
    from wqb.lockfile import json_lock_transition_guard
    from wqb.recovery_cases import read_current_recovery_case
    from wqb.runtime_control import _read
    from wqb.workflow_state import load_run_state, write_run_state
    run = Path(run)
    with json_lock_transition_guard(run / 'runtime/control_intent', 5.0, 0.05, 'planning release busy'):
        case = read_current_recovery_case(run)
        if (case.get('case_id') != case_id or case.get('status') != 'resolved'
                or case.get('action') != 'research-loop-blocked' or case.get('stage') != 'scout_seed'):
            return False
        path = run / 'runtime/research_handoff.json'
        handoff = _read(path)
        if handoff.get('stop_reason') != 'research_planning_blocked' or handoff.get('status') != 'blocked':
            return False
        state_path = run / 'run_state.json'
        state = load_run_state(state_path)
        if state.current_stage != 'scout_seed' or state.status != 'paused':
            return False
        if state.pause_reason.startswith('research_planning_blocked:'):
            reason = 'checked research results required: all_alphas.jsonl (candidates.csv alone is insufficient)'
            stages = dict(state.stages)
            stages['scout_seed'] = replace(stages['scout_seed'], blocker=reason)
            write_run_state(state_path, replace(state, stages=stages, pause_reason=reason))
        _write(path, {**handoff, 'status': 'maintenance_verified', 'resolved_case_id': case_id,
                      'next_action': 'workflow-auto-continue', 'verified_at': now})
        return True


def prepare_source_plan(run: Path, config: dict, metadata: dict, now: str) -> dict:
    """Input: active run Path, config/metadata dicts, time str. Output: config patch bound to a validated planning receipt."""
    manifest_path = Path(run) / 'run_manifest.json'
    if manifest_path.exists():
        snapshot = json.loads(manifest_path.read_text(encoding='utf-8')).get('start_snapshot', {})
        from wqb.hypothesis_selection import paired_scout_enabled, validate_operational_resource_context
        discovery = metadata.get('workflow_stage') == 'discovery' or metadata.get('template_provenance', {}).get('seed_expression')
        if (paired_scout_enabled(snapshot.get('research_policy')) and not discovery
                and metadata.get('workflow_stage', 'scout') in ('scout', 'scout_seed')):
            try:
                validate_operational_resource_context(snapshot)
            except ValueError as error:
                raise ResearchPlanningBlocked(str(error)) from error
            return prepare_paired_hypothesis_plan(run, config, metadata, now)
        if snapshot.get('hypothesis_binding_version') == 2:
            if metadata.get('workflow_stage') == 'discovery' or metadata.get('template_provenance', {}).get('seed_expression'):
                return prepare_hypothesis_discovery_plan(run, config, metadata, now)
            return prepare_hypothesis_plan(run, config, metadata, now)
    template = metadata.get('template_provenance') or {}
    manifest_path = Path(run) / 'run_manifest.json'
    manifest_digest = ''
    if manifest_path.exists():
        raw_manifest = manifest_path.read_bytes()
        manifest_digest = hashlib.sha256(raw_manifest).hexdigest()
        manifest = json.loads(raw_manifest)
        snapshot = manifest.get('start_snapshot', {})
        templates = snapshot.get('template_rows', [])
        fields = snapshot.get('data_ledger_rows', [])
        base = next((row for row in templates if row.get('template_id') == template.get('template_id')
                     and row.get('hypothesis') == template.get('hypothesis')), None)
        if not base or not any(row.get('field_id') == metadata.get('exact_field_id') for row in fields):
            raise ResearchPlanningBlocked('research plan is not bound to the Start knowledge snapshot')
        if template.get('seed_expression'):
            seed_path = Path(run) / 'stages/batch_generation/seed.json'
            seed = json.loads(seed_path.read_text(encoding='utf-8')) if seed_path.exists() else {}
            if template['seed_expression'] != seed.get('parent', {}).get('expression'):
                raise ResearchPlanningBlocked('Discovery plan differs from measured immutable seed')
        elif template.get('skeleton') != base.get('skeleton'):
            raise ResearchPlanningBlocked('scheduled template differs from the Start snapshot')
    identity = {'round_id': metadata.get('research_round_id', 'round-0001'),
                'field_id': metadata.get('exact_field_id'), 'template': template,
                'mode': config.get('ai_executor', 'none'), 'manifest_digest': manifest_digest}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    receipt = Path(run) / 'runtime/research_plans' / (digest + '.json')
    if receipt.exists():
        saved = json.loads(receipt.read_text(encoding='utf-8'))
        if saved.get('identity') != identity or saved.get('status') != 'ready':
            raise ResearchPlanningBlocked('research plan evidence invalid')
        return saved['config_patch']
    if not template.get('template_id') or not template.get('skeleton') or not template.get('hypothesis'):
        raise ResearchPlanningBlocked('scheduled economic template unavailable')
    selected = dict(template)
    judgment = {'status': 'not_requested', 'summary': 'Deterministic knowledge-backed template; no AI decision claimed.'}
    if config.get('ai_executor') == 'codex' or config.get('ai_executor_argv'):
        from wqb.workflow_driver import resolve_ai_executor_argv
        directory = Path(run) / 'stages/ai'
        evidence = Path(run) / 'runtime/research_plans' / (digest + '.input.json')
        _write(evidence, {'identity': identity, 'allowed_decays': SCHEDULED_DECAYS})
        checkpoint = append_ai_checkpoint(directory, 'research_batch_plan',
            'Choose a holding decay for this exact economic hypothesis. Return decision with exact '
            'template_id, field_id and preferred_decay from allowed_decays. No authority or code changes.',
            [str(evidence)], now)
        judgment = run_ai_checkpoint(directory, checkpoint.checkpoint_id, resolve_ai_executor_argv(config))
        decision = judgment.get('decision') or {}
        if (judgment.get('status') != 'completed' or decision.get('template_id') != template['template_id']
                or decision.get('field_id') != identity['field_id']
                or type(decision.get('preferred_decay')) is not int
                or decision['preferred_decay'] not in SCHEDULED_DECAYS):
            _write(receipt, {'identity': identity, 'status': 'blocked', 'judgment': judgment})
            raise ResearchPlanningBlocked('AI research decision failed or differs from allowed plan')
        selected['preferred_decay'] = decision['preferred_decay']
    patch = {'scheduled_template': selected, 'ai_plan_receipt': str(receipt)}
    _write(receipt, {'identity': identity, 'status': 'ready', 'judgment': judgment, 'config_patch': patch})
    return patch


def prepare_paired_hypothesis_plan(run: Path, config: dict, metadata: dict, now: str) -> dict:
    """Input: run Path/config/metadata dicts/time str. Output: durable paired generator patch and sidecar reference.

    Only frozen compiled arms are planned. No model, vault, POST or quota writes.
    Replays retain original funded inputs even after execution consumes quota;
    existing executors own reconciliation and durable Stop remains dominant.
    """
    from wqb.generator import build_settings
    from wqb.hypothesis_selection import validate_operational_resource_context, select_experiment_batch, binding_group_id
    from wqb.lockfile import json_lock_transition_guard
    from wqb.cli import run_root_expression_hashes, simulation_identity_hash
    run = Path(run)
    try:
        raw = (run / 'run_manifest.json').read_bytes()
        snapshot = json.loads(raw)['start_snapshot']
        context = validate_operational_resource_context(snapshot)
        maximum = hypothesis_authorized_maximum(run, config['max_alphas_per_round'])
        settings = build_settings(config)
        allowed = metadata.get('hypothesis_allowed_refs')
        if allowed is not None and (not isinstance(allowed, list) or any(not isinstance(row, dict)
                or not {'template_id', 'hypothesis_id', 'hypothesis_version'} <= set(row)
                or set(row) - {'template_id', 'hypothesis_id', 'hypothesis_version', 'binding_id'} for row in allowed)):
            raise ValueError('invalid paired allowed references')
        identity = dict(round_id=metadata.get('research_round_id', 'round-0001'),
            manifest_sha256=hashlib.sha256(raw).hexdigest(), settings=settings, allowed_refs=allowed,
            requested_maximum=metadata.get('scheduled_batch_maximum', config['max_alphas_per_round']))
        slot = hashlib.sha256(json.dumps([identity['round_id'], allowed], sort_keys=True).encode()).hexdigest()
        receipt = run / 'runtime/research_plans' / ('paired-' + slot + '.json')
        sidecar_path = receipt.with_suffix('.experiments.json')
        with json_lock_transition_guard(receipt, 5.0, 0.05, 'paired plan busy'):
            saved = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else None
            if saved is not None:
                if saved.get('identity') != identity or saved.get('status') not in ('ready', 'exhausted'):
                    raise ResearchPlanningBlocked('paired persisted plan inputs changed')
                excluded = saved['excluded_simulation_hashes']
                maximum = saved['maximum']
                measurements = saved['available_measurements']
            else:
                excluded = sorted(run_root_expression_hashes(config['run_root'])) if config.get('run_root') else []
                measurements = _paired_measurements(snapshot, context['experiments'], config.get('run_root'))
            experiments = []
            for experiment in context['experiments']:
                arms = experiment['arms']
                if allowed is not None:
                    matches = []
                    for arm in arms:
                        template = next(row for row in snapshot['template_rows'] if row['template_id'] == arm['template_id'])
                        matches.extend(ref for ref in allowed if all(ref[key] == template[key] for key in (
                            'template_id', 'hypothesis_id', 'hypothesis_version')) and (
                            'binding_id' not in ref or ref['binding_id'] == binding_group_id(arm['binding'])))
                    if not matches:
                        continue
                if any(settings != arm['settings'] for arm in arms):
                    raise ResearchPlanningBlocked('paired settings differ from frozen experiment controls')
                if any(simulation_identity_hash(arm['binding']['bound_expression'], arm['settings']) in set(excluded) - set(measurements) for arm in arms):
                    continue
                experiments.append(experiment)
            # Measurements are not inferred from correlation/check caches or unknown historical periods.
            selection = select_experiment_batch(snapshot, experiments, maximum, measurements)
            selected = selection['selected']
            if not selected and saved is None:
                from wqb.runtime_control import _read, DailyBudgetExhausted
                if _read(run / 'runtime_control.json').get('simulation_budget_mode') == 'daily':
                    larger = select_experiment_batch(snapshot, experiments, 30, measurements)
                    if larger['selected']:
                        from wqb.daily_simulation_budget import read_daily_budget
                        costs = [sum(simulation_identity_hash(arm['binding']['bound_expression'], arm['settings'])
                                     not in measurements for arm in experiment['arms']) for experiment in experiments]
                        required = min(cost for cost in costs if cost > 0)
                        raise DailyBudgetExhausted({**read_daily_budget(run, now), 'required_count': required})
            sidecar = dict(schema_version=1, manifest_sha256=identity['manifest_sha256'],
                experiments=selection['experiments'], arms=selection['sidecars'])
            if saved is None:
                _write(sidecar_path, sidecar)
            if not sidecar_path.is_file() or json.loads(sidecar_path.read_text(encoding='utf-8')) != sidecar:
                raise ResearchPlanningBlocked('paired sidecar differs from frozen replay')
            sidecar_bytes = sidecar_path.read_bytes()
            patch = dict(scheduled_hypotheses=selected, hypothesis_bindings=selected, hypothesis_snapshot=snapshot,
                hypothesis_binding_version=2, hypothesis_execution_kind='paired_scout', scheduled_template=None,
                max_alphas_per_round=maximum, ai_plan_receipt=str(receipt), research_round_id=identity['round_id'],
                experiment_sidecar_path=str(sidecar_path), experiment_sidecar_sha256=hashlib.sha256(sidecar_bytes).hexdigest(),
                hypothesis_plan_quality=dict(generated_count=selection['generated_count'], selected_count=len(selected),
                    experiment_count=len(selection['experiments']), model_status='not_requested_frozen_pairs'))
            payload = dict(identity=identity, status='ready' if selected else 'exhausted', maximum=maximum,
                excluded_simulation_hashes=excluded, available_measurements=measurements, selection=selection, config_patch=patch)
            if saved is not None:
                if {key: value for key, value in saved.items() if key != 'consumption_audit'} != payload:
                    raise ResearchPlanningBlocked('paired persisted plan differs from frozen replay')
            _write(receipt, {**payload, 'consumption_audit': dict(cache_status='replayed' if saved else 'created',
                replay_count=saved.get('consumption_audit', {}).get('replay_count', 0) + 1 if saved else 0, consumed_at=now)})
            if not selected:
                raise ResearchVariantsExhausted('insufficient original authority or no novel complete paired experiment')
            return copy.deepcopy(patch)
    except ResearchPlanningBlocked:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ResearchPlanningBlocked('invalid frozen paired planning inputs: ' + str(exc)) from exc


def _paired_measurements(snapshot: dict, experiments: list[dict], run_root: str | None) -> dict:
    """Input: frozen snapshot/experiment list and optional source-root str. Output: exact compatible local measurements dict.

    Only existing all_alphas records with a measured Alpha and known period can
    be reused; never check/correlation caches, unknown POSTs or inferred dates.
    Conflicting measurements of one identity are conservatively excluded.
    """
    from wqb.hypothesis_selection import _experiment_candidate, _compatible_measurement
    from wqb.cli import simulation_identity_hash
    if not run_root or not snapshot.get('measurement_period'):
        return {}
    candidates = {}
    for experiment in experiments:
        for arm in experiment['arms']:
            candidate = _experiment_candidate(snapshot, arm)
            candidates[simulation_identity_hash(candidate['bound_expression'], candidate['settings'])] = candidate
    measurements, conflicts = {}, set()
    for path in sorted(Path(run_root).rglob('all_alphas.jsonl')):
        try:
            records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        except (OSError, ValueError):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            identity = record.get('expression_hash')
            if (identity not in candidates or not record.get('alpha_id')
                    or str(record.get('status', '')).lower() in ('failed', 'error', 'pending')
                    or not (type(record.get('hard_pass')) is bool or record.get('status') in ('measured', 'CHECKED'))):
                continue
            measurement = copy.deepcopy(record)
            measurement.update(scope=record.get('scope', record.get('hypothesis_binding', {}).get('scope')),
                               status='measured')
            if not _compatible_measurement(snapshot, candidates[identity], identity, measurement):
                continue
            if identity in measurements and measurements[identity] != measurement:
                conflicts.add(identity)
            measurements[identity] = measurement
    return {identity: measurement for identity, measurement in measurements.items() if identity not in conflicts}


def _hypothesis_pool(snapshot: dict, settings: dict, allowed: list | None, *, report: dict | None = None) -> list[dict]:
    """Input: frozen raw snapshot, complete settings dict, optional allowed template refs list. Output: bounded candidate list.

    Only existing scheduled decay/neutralization/window choices are expanded;
    bind_template owns typed data availability and operator validation.
    """
    from wqb.generator import LOOKBACKS, SCHEDULED_NEUTRALIZATIONS
    from wqb.template_binding import bind_template, TemplateBindingError
    from wqb.research_workflow import precheck_expression
    from wqb.hypothesis_selection import (enumerate_hypothesis_bindings, binding_field_rows,
                                         binding_group_id, require_legacy_resource_snapshot)
    require_legacy_resource_snapshot(snapshot)
    pool = []
    if report is None:
        report = {}
    report.update(binding_attempt_count=0, binding_pass_count=0, rejections=[])
    templates = snapshot.get('template_rows', [])
    if allowed is not None:
        keys = {'template_id', 'hypothesis_id', 'hypothesis_version'}
        if not isinstance(allowed, list) or any(not isinstance(row, dict) or not keys <= set(row)
                or set(row) - keys - {'binding_id'} for row in allowed):
            raise ResearchPlanningBlocked('invalid allowed hypothesis references')
        known = [{key: row.get(key) for key in ('template_id', 'hypothesis_id', 'hypothesis_version')} for row in templates]
        if any({key: row[key] for key in keys} not in known for row in allowed):
            raise ResearchPlanningBlocked('allowed hypothesis is outside frozen snapshot')
        templates = [row for row in templates if {key: row.get(key) for key in (
            'template_id', 'hypothesis_id', 'hypothesis_version')} in [
                {key: row[key] for key in keys} for row in allowed]]
    for template in templates:
        if template.get('binding_version') != 2 or template.get('semantic_status') != 'reviewed':
            continue
        windows = LOOKBACKS if '{window}' in template.get('skeleton', '') else [None]
        group_report = {}
        groups = enumerate_hypothesis_bindings(template, snapshot['data_ledger_rows'], snapshot['operator_rows'], snapshot['selected_scope'], report=group_report)
        for key in ('binding_attempt_count', 'binding_pass_count'):
            report[key] += group_report[key]
        from wqb.hypothesis_selection import MAX_REJECTION_SAMPLES
        report['rejections'].extend(group_report['rejections'][:max(0, MAX_REJECTION_SAMPLES - len(report['rejections']))])
        if allowed is not None:
            refs = [row for row in allowed if row['template_id'] == template['template_id']
                    and row['hypothesis_id'] == template['hypothesis_id'] and row['hypothesis_version'] == template['hypothesis_version']]
            permitted = {row.get('binding_id') for row in refs}
            groups = [group for group in groups if None in permitted or binding_group_id(group) in permitted]
        for group, window in [(group, window) for group in groups for window in windows]:
            scope = copy.deepcopy(snapshot['selected_scope'])
            binding_scope = dict(scope, window=window) if window is not None else scope
            try:
                binding = bind_template(template, binding_field_rows(snapshot, group), snapshot['operator_rows'], binding_scope)
            except TemplateBindingError:
                continue
            if not precheck_expression(binding['bound_expression'], 'scout').ok:
                continue
            for decay in SCHEDULED_DECAYS:
                for neutralization in SCHEDULED_NEUTRALIZATIONS:
                    row = dict(template_id=template['template_id'], hypothesis_id=template['hypothesis_id'],
                               hypothesis_version=template['hypothesis_version'], binding_version=2, scope=scope,
                               settings={**settings, 'decay': decay, 'neutralization': neutralization}, **copy.deepcopy(binding))
                    if window is not None:
                        row['window'] = window
                    row['candidate_id'] = hashlib.sha256(json.dumps(row, sort_keys=True, allow_nan=False).encode()).hexdigest()
                    pool.append(row)
    return pool


def _consume_hypothesis_decision(pool: list[dict], judgment: dict) -> list[dict]:
    """Input: frozen candidates list[dict], checkpoint dict. Output: exact recommended candidates. Reject arbitrary parameters/code."""
    if judgment.get('status') == 'not_requested':
        return pool
    decision = judgment.get('decision')
    if judgment.get('status') != 'completed' or not isinstance(decision, dict) or set(decision) != {'selected_bindings'}:
        raise ResearchPlanningBlocked('AI hypothesis decision failed or has unknown schema')
    choices = decision['selected_bindings']
    if not isinstance(choices, list):
        raise ResearchPlanningBlocked('selected_bindings must be a list')
    by_id = {row['candidate_id']: row for row in pool}
    selected, seen = [], set()
    for choice in choices:
        if not isinstance(choice, dict) or set(choice) != {'binding_id', 'hypothesis_id', 'hypothesis_version'}:
            raise ResearchPlanningBlocked('unknown selected binding schema')
        identifier = choice['binding_id']
        if not isinstance(identifier, str) or identifier in seen or identifier not in by_id:
            raise ResearchPlanningBlocked('duplicate or unknown frozen binding ID')
        row = by_id[identifier]
        if (choice['hypothesis_id'] != row['hypothesis_id'] or type(choice['hypothesis_version']) is not int
                or choice['hypothesis_version'] != row['hypothesis_version']):
            raise ResearchPlanningBlocked('hypothesis identity/version differs from frozen binding')
        selected.append(row)
        seen.add(identifier)
    return selected


def hypothesis_worker_projection(brief: dict, run: Path) -> dict:
    """Input: short brief dict/run Path. Output: verified brief dict. Bind full read-only pack and manifest before worker invocation."""
    run = Path(run).resolve()
    for key in ('supporting_evidence', 'run_manifest'):
        ref = brief[key]
        if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
            raise ValueError('invalid hypothesis material reference')
        path = run / ref['path']
        if path.is_symlink() or not path.resolve().is_relative_to(run):
            raise ValueError('hypothesis material outside bound run')
        if hashlib.sha256(path.read_bytes()).hexdigest() != ref['sha256']:
            raise ValueError('hypothesis material digest mismatch')
    if len(json.dumps(brief, ensure_ascii=False).encode('utf-8')) > HYPOTHESIS_BRIEF_MAX_BYTES:
        raise ValueError('hypothesis brief exceeds bounded evidence input; no truncation permitted')
    return brief


def _write_hypothesis_brief(run: Path, evidence: Path, snapshot: dict, identity: dict, pool: list[dict]) -> Path:
    """Input: run/evidence Paths, frozen snapshot/identity dicts, candidate list. Output: brief Path. Index full pack without prompt dumping."""
    _write(evidence, dict(identity=identity, allowed_bindings=pool,
                         material_index=['run_manifest.json#start_snapshot', 'allowed_bindings']))
    hypotheses = []
    for template in snapshot['template_rows']:
        rows = [row for row in pool if row['template_id'] == template['template_id']
                and row['hypothesis_id'] == template['hypothesis_id']
                and row['hypothesis_version'] == template['hypothesis_version']]
        if not rows:
            continue
        hypotheses.append(dict(template_id=template['template_id'], hypothesis_id=template['hypothesis_id'],
            hypothesis_version=template['hypothesis_version'], hypothesis_card=template['hypothesis_card'],
            binding_count=len(rows), example_binding_id=rows[0]['candidate_id'],
            binding_index='allowed_bindings: exact candidate_id, settings, bindings, operator_provenance',
            allowed_parameters=dict(decay=sorted({row['settings']['decay'] for row in rows}),
                neutralization=sorted({row['settings']['neutralization'] for row in rows}),
                window=sorted({row['window'] for row in rows if 'window' in row}))))
    brief = dict(hypotheses=hypotheses, maximum=identity['maximum'], scope=snapshot['selected_scope'],
                 fixed_settings=identity['settings'],
                 supporting_evidence=dict(path=evidence.relative_to(run).as_posix(),
                     sha256=hashlib.sha256(evidence.read_bytes()).hexdigest()),
                 run_manifest=dict(path='run_manifest.json', sha256=identity['manifest_sha256']))
    hypothesis_worker_projection(brief, run)
    path = evidence.with_suffix('.brief.json')
    _write(path, brief)
    return path


def _daily_replay_maximum(run: Path, saved: dict | None, maximum: int, ceiling: int) -> int:
    """Input: run/receipt/current max/frozen ceiling. Output: int. Retain an existing plan's reservation across daily balance changes."""
    from wqb.runtime_control import _read
    if _read(run / 'runtime_control.json').get('simulation_budget_mode') != 'daily':
        return maximum
    if saved is None:
        from wqb.runtime_control import DAILY_RECONCILE_ENV
        import os
        if not maximum or os.environ.get(DAILY_RECONCILE_ENV) == '1':
            from wqb.daily_simulation_budget import read_daily_budget
            from wqb.runtime_control import DailyBudgetExhausted
            raise DailyBudgetExhausted(read_daily_budget(run))
        return maximum
    reserved = saved.get('identity', {}).get('maximum')
    if type(reserved) is not int or not 0 < reserved <= min(30, ceiling):
        raise ResearchPlanningBlocked('invalid frozen daily plan reservation')
    return reserved


def hypothesis_authorized_maximum(run: Path, requested: int) -> int:
    """Input: run Path/requested int. Output: capped int. Respect persisted remaining authority without reserving or modifying it."""
    from wqb.research_workflow import cap_simulation_count
    control_path = run / 'runtime_control.json'
    if type(requested) is not int or requested < 0:
        raise ResearchPlanningBlocked('invalid authorized batch maximum')
    maximum = cap_simulation_count('scout', requested)
    if control_path.exists():
        control = json.loads(control_path.read_text(encoding='utf-8'))
        if control.get('desired_state') != 'running':
            from wqb.runtime_control import RuntimePaused
            raise RuntimePaused('user_paused')
        if control.get('simulation_budget_mode') == 'daily':
            from wqb.daily_simulation_budget import remaining_submission_allowance
            return min(maximum, remaining_submission_allowance(run))
        status = json.loads((run / 'runtime_status.json').read_text(encoding='utf-8'))
        limit, used = control.get('max_simulations'), status.get('simulation_attempts')
        if type(limit) is not int or type(used) is not int or limit < 0 or used < 0:
            raise ResearchPlanningBlocked('research budget accounting required')
        usage = control.get('simulation_attempts', 0)
        if type(usage) is not int or usage < 0:
            raise ResearchPlanningBlocked('research budget accounting required')
        state_path = run / 'run_state.json'
        state_used = json.loads(state_path.read_text(encoding='utf-8')).get('budget_used', 0) if state_path.exists() else 0
        if type(state_used) is not int or state_used < 0:
            raise ResearchPlanningBlocked('research budget accounting required')
        maximum = min(maximum, max(0, limit - max(used, usage, state_used)))
    return maximum


def prepare_hypothesis_discovery_plan(run: Path, config: dict, metadata: dict, now: str) -> dict:
    """Input: run Path/config/metadata dicts/time str. Output: cached measured-seed plan patch. Vary only existing settings; never rerun a model or select a new hypothesis."""
    from wqb.generator import build_settings, SCHEDULED_NEUTRALIZATIONS
    from wqb.hypothesis_selection import select_hypothesis_batch, summarize_hypothesis_selection
    from wqb.cli import simulation_identity_hash, run_root_expression_hashes
    from wqb.lockfile import json_lock_transition_guard
    run = Path(run)
    manifest_bytes = (run / 'run_manifest.json').read_bytes()
    snapshot = json.loads(manifest_bytes)['start_snapshot']
    seed = json.loads((run / 'stages/batch_generation/seed.json').read_text(encoding='utf-8'))['parent']
    if seed != metadata.get('measured_seed'):
        raise ResearchPlanningBlocked('Discovery measured seed differs from durable immutable seed')
    binding = seed.get('hypothesis_binding')
    if (not isinstance(binding, dict) or seed.get('expression') != binding['bound_expression']
            or seed.get('settings') != binding['settings']
            or seed.get('expression_hash') != simulation_identity_hash(seed['expression'], seed['settings'])
            or len(select_hypothesis_batch(snapshot, [binding], 1)['selected']) != 1):
        raise ResearchPlanningBlocked('Discovery seed hypothesis identity/bindings are invalid')
    settings = build_settings(config)
    if settings != seed['settings']:
        raise ResearchPlanningBlocked('Discovery settings differ from measured parent')
    maximum = hypothesis_authorized_maximum(run, config['max_alphas_per_round'])
    identity = dict(kind='measured_seed_discovery', round_id=metadata['research_round_id'],
                    manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(), parent=seed, maximum=maximum)
    slot = hashlib.sha256(metadata['research_round_id'].encode()).hexdigest()
    receipt = run / 'runtime/research_plans' / ('discovery-' + slot + '.json')
    with json_lock_transition_guard(receipt, 5.0, 0.05, 'Discovery hypothesis plan busy'):
        saved = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else None
        maximum = _daily_replay_maximum(run, saved, maximum, metadata.get('scheduled_batch_maximum', 30))
        identity['maximum'] = maximum
        if saved is not None:
            if saved.get('identity') != identity or saved.get('status') not in ('ready', 'exhausted'):
                raise ResearchPlanningBlocked('Discovery frozen plan changed')
            excluded = saved['excluded_simulation_hashes']
        else:
            excluded = sorted({seed['expression_hash'], *(
                run_root_expression_hashes(config['run_root']) if config.get('run_root') else set())})
        pool = []
        for decay in SCHEDULED_DECAYS:
            for neutralization in SCHEDULED_NEUTRALIZATIONS:
                row = copy.deepcopy(binding)
                row['settings'] = {**settings, 'decay': decay, 'neutralization': neutralization}
                if simulation_identity_hash(row['bound_expression'], row['settings']) in excluded:
                    continue
                row.pop('candidate_id', None)
                row['candidate_id'] = hashlib.sha256(json.dumps(row, sort_keys=True, allow_nan=False).encode()).hexdigest()
                pool.append(row)
        selection = select_hypothesis_batch(snapshot, pool, maximum)
        selected = selection['selected']
        patch = dict(scheduled_hypotheses=selected, hypothesis_bindings=selected, hypothesis_snapshot=snapshot,
                     hypothesis_binding_version=2, hypothesis_execution_kind='discovery', scheduled_template=None,
                     max_alphas_per_round=maximum, ai_plan_receipt=str(receipt), research_round_id=identity['round_id'],
                     hypothesis_plan_quality=dict(binding_attempt_count=1, binding_pass_count=1,
                         selection=summarize_hypothesis_selection(snapshot, selection), rejections=[],
                         model_status='not_requested_measured_seed'))
        payload = dict(identity=identity, status='ready' if selected else 'exhausted',
                       excluded_simulation_hashes=excluded, config_patch=patch)
        if saved is not None and {key: value for key, value in saved.items() if key != 'consumption_audit'} != payload:
            raise ResearchPlanningBlocked('Discovery persisted plan content invalid')
        _write(receipt, {**payload, 'consumption_audit': dict(cache_status='replayed' if saved else 'created',
            replay_count=saved.get('consumption_audit', {}).get('replay_count', 0) + 1 if saved else 0, consumed_at=now)})
        if not selected:
            raise ResearchVariantsExhausted('no novel measured-seed Discovery variants within original authority')
        return copy.deepcopy(patch)


def prepare_hypothesis_plan(run: Path, config: dict, metadata: dict, now: str) -> dict:
    """Input: run Path, authorized config/metadata dicts, time str. Output: persisted consumed multi-hypothesis config patch.

    Bind only immutable Start rows, cache successful AND failed judgments per
    round/allowed selection, verify replay against regenerated frozen inputs,
    and publish before callers can generate or POST. Never read an active vault.
    """
    from wqb.generator import build_settings
    from wqb.hypothesis_selection import select_hypothesis_batch, summarize_hypothesis_selection
    from wqb.research_workflow import cap_simulation_count
    from wqb.lockfile import json_lock_transition_guard
    run = Path(run)
    try:
        raw_manifest = (run / 'run_manifest.json').read_bytes()
        snapshot = json.loads(raw_manifest)['start_snapshot']
        if snapshot.get('hypothesis_binding_version') != 2:
            raise ValueError('requires frozen v2 hypothesis snapshot')
        maximum = hypothesis_authorized_maximum(run, config['max_alphas_per_round'])
        settings = build_settings(config)
        for key in ('region', 'delay', 'universe'):
            if (type(settings[key]) is not type(snapshot['selected_scope'][key])
                    or settings[key] != snapshot['selected_scope'][key]):
                raise ValueError('settings scope differs from frozen hypothesis scope')
        allowed = metadata.get('hypothesis_allowed_refs')
        identity = dict(round_id=metadata.get('research_round_id', 'round-0001'),
                        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(), settings=settings,
                        maximum=maximum, allowed_refs=allowed,
                        executor=config.get('ai_executor', 'none'), executor_argv=config.get('ai_executor_argv'))
        slot = hashlib.sha256(json.dumps([identity['round_id'], allowed], sort_keys=True).encode()).hexdigest()
        receipt = run / 'runtime/research_plans' / ('hypothesis-' + slot + '.json')
        with json_lock_transition_guard(receipt, 5.0, 0.05, 'hypothesis plan busy'):
            saved = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else None
            maximum = _daily_replay_maximum(run, saved, maximum, metadata.get('scheduled_batch_maximum', config['max_alphas_per_round']))
            identity['maximum'] = maximum
            from wqb.cli import run_root_expression_hashes, simulation_identity_hash
            excluded = (saved.get('identity', {}).get('excluded_simulation_hashes', []) if saved is not None else
                        sorted(run_root_expression_hashes(config['run_root'])) if config.get('run_root') else [])
            identity['excluded_simulation_hashes'] = excluded
            quality = {}
            raw_pool = _hypothesis_pool(snapshot, settings, allowed, report=quality)
            pool = [row for row in raw_pool
                    if simulation_identity_hash(row['bound_expression'], row['settings']) not in excluded]
            quality['excluded_seen_identity_count'] = len(raw_pool) - len(pool)
            if saved is not None:
                if saved.get('identity') == identity and saved.get('reason_code') == 'variants_exhausted':
                    raise ResearchVariantsExhausted(saved['reason'])
                if saved.get('identity') != identity or saved.get('status') != 'ready':
                    raise ResearchPlanningBlocked('persisted hypothesis plan blocked or changed; no automatic model replay')
                judgment = saved['judgment']
            else:
                judgment = dict(status='not_requested', summary='Deterministic frozen hypothesis selection; no AI decision claimed.')
                if not pool or maximum == 0:
                    reason = 'no executable novel hypothesis bindings within original authority'
                    _write(receipt, dict(identity=identity, status='blocked', judgment=judgment,
                                         reason=reason, reason_code='variants_exhausted'))
                    raise ResearchVariantsExhausted(reason)
                if config.get('ai_executor') == 'codex' or config.get('ai_executor_argv'):
                    from wqb.workflow_driver import resolve_ai_executor_argv
                    _write(receipt, dict(identity=identity, status='planning'))
                    evidence = receipt.with_suffix('.input.json')
                    brief = _write_hypothesis_brief(run, evidence, snapshot, identity, pool)
                    checkpoint = append_ai_checkpoint(run / 'stages/ai', 'hypothesis_batch_plan',
                        'Select frozen binding IDs from allowed_bindings. Return decision.selected_bindings '
                        'with exact binding_id, hypothesis_id, hypothesis_version only. Read hash-backed supporting_evidence '
                        'for the full allowed binding index, settings and metadata; brief examples are not exhaustive. '
                        'No code, scope, budget or rule changes.', [str(brief)], now)
                    # Persist the attempt before invoking the worker: interruption is not permission to rerun it.
                    _write(receipt, dict(identity=identity, status='planning', checkpoint_id=checkpoint.checkpoint_id))
                    judgment = run_ai_checkpoint(run / 'stages/ai', checkpoint.checkpoint_id, resolve_ai_executor_argv(config),
                                                 cancel_on_pause=True)
            try:
                recommended = _consume_hypothesis_decision(pool, judgment)
                selection = select_hypothesis_batch(snapshot, recommended, maximum)
                invalid = [reason for reason in selection['reasons'] if reason['code'] == 'invalid_candidate']
                if invalid:
                    raise ResearchPlanningBlocked('frozen hypothesis binding validation failed: ' + str(invalid))
                if not selection['selected']:
                    raise ResearchVariantsExhausted('no executable novel hypothesis bindings within original authority')
                patch = dict(scheduled_hypotheses=selection['selected'], hypothesis_bindings=selection['selected'],
                             hypothesis_snapshot=snapshot, max_alphas_per_round=maximum,
                             ai_plan_receipt=str(receipt), hypothesis_binding_version=2,
                             research_round_id=identity['round_id'],
                             hypothesis_plan_quality={**quality, 'selection': summarize_hypothesis_selection(snapshot, selection),
                                                      'model_status': judgment['status']})
                payload = dict(identity=identity, status='ready', judgment=judgment, selection=selection, config_patch=patch)
                if saved is not None and {key: value for key, value in saved.items() if key != 'consumption_audit'} != payload:
                    raise ResearchPlanningBlocked('persisted hypothesis plan content differs from validated replay')
                _write(receipt, {**payload, 'consumption_audit': dict(cache_status='replayed' if saved else 'created',
                    replay_count=saved.get('consumption_audit', {}).get('replay_count', 0) + 1 if saved else 0, consumed_at=now)})
                return copy.deepcopy(patch)
            except ResearchPlanningBlocked as exc:
                if saved is None:
                    _write(receipt, dict(identity=identity, status='blocked', judgment=judgment, reason=str(exc),
                                         reason_code='variants_exhausted' if isinstance(exc, ResearchVariantsExhausted) else 'planning_blocked'))
                raise
    except ResearchPlanningBlocked:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ResearchPlanningBlocked('invalid frozen hypothesis planning inputs: ' + str(exc)) from exc
