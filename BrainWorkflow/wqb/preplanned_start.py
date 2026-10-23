"""Local, durable Start composition. Execution and active pointers belong to the parent."""

from copy import deepcopy
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path

from wqb.exploration_eligibility import validate_exploration
from wqb.generator import build_settings
from wqb.group_preparation import prepare_group_lanes, complete_group_lanes
from wqb.hypothesis_template_compiler import _resources
from wqb.initial_research_planning import prepare_initial_research
from wqb.knowledge_age_policy import KNOWLEDGE_MAX_AGE_DAYS
from wqb.knowledge_compile import (_audit_resource_rows, _coverage_field_supported,
    _coverage_operator_supported, _coverage_source_fields, read_semantic_rows)
from wqb.knowledge_paths import machine_resource_path
from wqb.lockfile import json_lock_transition_guard
from wqb.research_group import MAX_LANES, read_group
from wqb.runtime_control import _write
from wqb.semantic_compilation import (_digest, _material, _safe,
    verify_design_materials)
from wqb.semantic_contracts import SemanticPolicy
from wqb.template_binding import _scope_matches
from wqb.workflow_stage_adapters import (_row_has_measured_platform_coverage,
    _row_has_positive_coverage, _row_has_source_date)


DEFAULT_LANES = 2
DEFAULT_DEPTH = 2
DEFAULT_HYPOTHESES = 4
MAX_POLICY_VALUE = 16
MAX_LOCAL_JOBS = 128
MAX_FIELDS_PER_LANE = 30
MAX_LOCAL_JSON_BYTES = 16_000_000
LOCK_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.05
INITIAL_MODEL_CALLBACK_CONTRACT = {
    'checkpoint_type': 'initial_research_planning',
    'input': 'One brief dict with worker_context, full source_texts/source_index, '
             'certified data_traits/operator_rows/evidence_pack and strict output_schema.',
    'output': 'Raw JSON object with exactly summary/designs/tree matching brief.output_schema; '
              'not an advisory summary, status wrapper, decision or precompiled expression.',
    'authority': 'Injected runner only; one invocation per owning lane/content key, medium or lower reasoning, '
                 'read-only/no network/no WQB/no publication/no automatic retries.',
    'binding': 'worker_context points to the owning manifest, durable planning task and resource certificate. '
               'Verify those before dispatch; freeze full source copies and hash-bound references before '
               'rendering a bounded prompt. Preserve complete output; timeouts are unknown, never replay.',
    'compatibility': 'A run-bound initial_model_worker factory expects the exact persisted task brief. '
                     'Its caller must validate and remove worker_context before comparing the brief; '
                     'the hypothesis_design checkpoint drops tree and is not a compatible fallback.',
}
REPAIR_DIAGNOSTICS = [
    'No certified setting-effect/parameter-bound rules in the current semantic resources; '
    'freeze an empty finite Repair search, not an official rule inferred from field/operator names.',
    'Cadence, nuisance exposure and direction-preserving parent-bound transforms remain unknown; '
    'initial Scout is allowed, deterministic Repair will report search_space_exhausted.',
]


def _json(root: Path, relative: str) -> dict:
    """Input: trusted root Path/relative str. Output: bounded safe JSON object dict."""
    path = _safe(root, relative)
    if path.stat().st_size > MAX_LOCAL_JSON_BYTES:
        raise ValueError('oversized local Start material: ' + relative)
    value = json.loads(path.read_text(encoding='utf-8'))
    if type(value) is not dict:
        raise ValueError('local Start material must be an object: ' + relative)
    _digest(value)
    return value


def _parameters(config: dict) -> tuple[dict, dict, dict]:
    """Input: configuration dict. Output: exact scope, measurement period and bounded policy dicts."""
    if type(config) is not dict:
        raise ValueError('config must be a dict')
    supplied = config.get('research_policy', {})
    if type(supplied) is not dict:
        raise ValueError('research_policy must be a dict')
    policy = {}
    for key, default, maximum in [('parallel_workflows', DEFAULT_LANES, MAX_LANES),
            ('plan_depth', DEFAULT_DEPTH, MAX_POLICY_VALUE),
            ('initial_hypotheses', DEFAULT_HYPOTHESES, MAX_POLICY_VALUE)]:
        value = config.get(key, supplied.get(key, default))
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f'{key} requires an integer in 1..{maximum}')
        policy[key] = value
    scope = deepcopy(config.get('selected_scope', config.get('scope')))
    if (type(scope) is not dict or not {'instrument_type', 'region', 'delay', 'universe', 'as_of'} <= scope.keys()
            or any(type(scope[key]) is not str or not scope[key].strip()
                   for key in ('instrument_type', 'region', 'universe', 'as_of'))
            or type(scope['delay']) is not int or scope['delay'] < 0):
        raise ValueError('selected_scope requires exact instrument_type/region/delay/universe/as_of facts')
    as_of = datetime.fromisoformat(scope['as_of'].replace('Z', '+00:00'))
    if as_of.tzinfo is None:
        raise ValueError('scope.as_of requires an explicit timezone')
    for key in ('instrument_type', 'region', 'delay', 'universe'):
        if key in config and (type(config[key]) is not type(scope[key]) or config[key] != scope[key]):
            raise ValueError('simulation setting conflicts with selected_scope: ' + key)
    period = deepcopy(config.get('measurement_period'))
    if type(period) is not dict or set(period) != {'start', 'end'}:
        raise ValueError('measurement_period requires explicit start/end dates')
    if date.fromisoformat(period['start']) >= date.fromisoformat(period['end']):
        raise ValueError('measurement_period start must precede end')
    return scope, period, policy


def _source_context(root: Path, requested: dict, registered: dict) -> dict:
    """Input: vault Path/requested/canonical index dicts. Output: actual raw texts; never repair hashes."""
    texts = {}
    for path, row in requested.items():
        if _digest(row) != _digest(registered.get(path)):
            raise ValueError('source differs from canonical registration: ' + path)
        _, texts[path] = _material(root, row)
        captured = datetime.fromisoformat(row['captured_at'].replace('Z', '+00:00'))
        if captured.tzinfo is None:
            raise ValueError('source capture timezone missing: ' + path)
        age = (datetime.now(timezone.utc) - captured).total_seconds() / 86400
        if age < 0 or age > KNOWLEDGE_MAX_AGE_DAYS:
            raise ValueError('source capture outside knowledge age policy: ' + path)
    return texts


def _validate_resource(root: Path, resource: dict, scope: dict, ledger: list[dict], index: dict) -> dict:
    """Input: vault/resource/scope/canonical ledger/index. Output: validated copied compiler resources dict."""
    resource, _ = _resources(resource, scope)
    texts = _source_context(root, resource['source_index'], index)
    if texts != resource['source_texts'] or resource['evidence_pack'].get('source_texts') != texts:
        raise ValueError('compiler materials differ from actual indexed raw text')
    fields = resource['field_rows']
    if not 1 <= len(fields) <= MAX_FIELDS_PER_LANE:
        raise ValueError('lane requires 1..30 source-backed fields')
    version = resource.get('resource_contract_version', 1)
    for row in fields:
        identity = (row.get('dataset_id'), row.get('field_id'))
        matches = [item for item in ledger if (item.get('dataset_id'), item.get('field_id')) == identity
                   and _scope_matches(item, scope)]
        if len(matches) != 1 or _digest(matches[0]) != _digest(row):
            raise ValueError('missing, ambiguous or changed exact-scope ledger field: ' + str(identity))
        if (not _scope_matches(row, scope) or not _row_has_measured_platform_coverage(row)
                or not _row_has_positive_coverage(row) or not _row_has_source_date(row)):
            raise ValueError('missing measured positive dated exact-scope coverage: ' + str(identity))
        if not _coverage_field_supported(row, texts, resource['source_index'], scope,
                                         resource_contract_version=version):
            raise ValueError('missing source-backed description/type/timing/grain/metadata: ' + str(identity))
        measured = []
        for path in row['source_paths']:
            for field, dataset, captured in _coverage_source_fields(texts[path]):
                if (field.get('id') == identity[1] and dataset.get('id') == identity[0]
                        and _scope_matches(dict(captured, dataset_id=identity[0]), scope)):
                    value = field.get('coverage')
                    if type(value) in (int, float) and math.isfinite(value) and value > 0:
                        measured.append(value)
        if not measured or row['coverage'] != max(measured):
            raise ValueError('measured coverage missing or differs from raw field: ' + str(identity))
        age = (datetime.now(timezone.utc).date() - date.fromisoformat(row['source_updated_at'])).days
        if not 0 <= age <= KNOWLEDGE_MAX_AGE_DAYS:
            raise ValueError('field source date outside knowledge age policy: ' + str(identity))
    for row in resource['operator_rows']:
        if not _coverage_operator_supported(row, texts, source_index=resource['source_index'],
                                            resource_contract_version=version):
            raise ValueError('missing typed source-backed operator: ' + str(row.get('operator')))
    return resource


def _local_resources(root: Path, scope: dict, config: dict, count: int) -> tuple[list, list, list]:
    """Input: vault Path, exact scope/config dicts, requested count int. Output: resources/receipts/diagnostics lists.

    Reuse verified semantic job compiler_context materials and experiment receipts
    first. Otherwise assemble dataset lanes from canonical machine rows, actual
    raw text and the existing settings/compiler/coverage helpers. Never compile
    the vault, publish a release, capture data or load an arbitrary Python builder.
    """
    index = {}
    for row in _audit_resource_rows(machine_resource_path(root, 'source_index'), root):
        if row['path'] in index:
            raise ValueError('duplicate canonical source index path: ' + row['path'])
        index[row['path']] = row
    ledger = list(_audit_resource_rows(machine_resource_path(root, 'data_ledger'), root))
    resources, receipts, diagnostics, seen = [], [], [], set()

    def accept(resource: dict) -> None:
        """Input: local compiler resource dict. Output: None; retain only distinct verified selections."""
        if resource.get('evidence_pack', {}).get('scope') != scope:
            return
        checked = _validate_resource(root, resource, scope, ledger, index)
        identity = tuple(sorted((r['dataset_id'], r['field_id']) for r in checked['field_rows']))
        if identity not in seen:
            seen.add(identity)
            resources.append(checked)

    # Library attachments carry compiler inputs, not a reviewed-status shortcut.
    _, operators, templates = read_semantic_rows(root)
    for relative in sorted({path for row in templates for path in row.get('experiment_paths', [])}):
        try:
            document = _json(root, relative)
            inputs = document['compiler_input']
            if inputs['scope'] != scope:
                continue
            receipt = validate_exploration(**inputs)
            if document.get('experiment') != receipt['compiled']['experiment']:
                raise ValueError('template experiment differs from reconstructed compiler receipt')
            accept(inputs['resources'])
            receipts.append(receipt)
        except (OSError, ValueError, TypeError, KeyError) as error:
            diagnostics.append(dict(path=relative, reason=str(error)))
    jobs_root = _safe(root, 'machine/semantic_jobs')
    jobs = sorted(jobs_root.glob('*/run_manifest.json')) if jobs_root.exists() else []
    if len(jobs) > MAX_LOCAL_JOBS:
        raise ValueError('semantic job lookup exceeds bounded local index; maintenance required')
    for path in jobs:
        try:
            job = _safe(root, path.parent.relative_to(root).as_posix())
            manifest = _json(job, 'run_manifest.json')
            if manifest.get('task_kind') != 'hypothesis_design':
                continue
            policy = SemanticPolicy(**manifest['identity']['policy'])
            pack, resource = verify_design_materials(job, manifest, policy, check_sources=True)
            if resource is None or pack['scope'] != scope:
                continue
            accept(resource)
            # Reconstruct completed designs locally; no call to a checkpoint executor.
            if _safe(job, 'result.json').exists():
                result = _json(job, 'result.json')
                if result.get('cache_status') in ('ready', 'hit'):
                    for design in result['designs']:
                        receipt = validate_exploration(design, resource, scope)
                        if receipt['compiled']['experiment'] not in result['attachments']:
                            raise ValueError('cached experiment differs from source-recompiled receipt')
                        receipts.append(receipt)
        except (OSError, ValueError, TypeError, KeyError) as error:
            diagnostics.append(dict(path=str(path.relative_to(root)), reason=str(error)))
    if len(resources) < count:
        grouped = {}
        for row in ledger:
            if _scope_matches(row, scope):
                grouped.setdefault(row.get('dataset_id'), []).append(row)
        for dataset, fields in sorted(grouped.items(), key=lambda item: str(item[0])):
            try:
                paths = {p for row in fields for p in row.get('source_paths', [])}
                paths.update(ref['source_path'] for row in operators
                             for ref in (row.get('definition') or {}).get('evidence_refs', []))
                selected = {path: index[path] for path in sorted(paths)}
                texts = _source_context(root, selected, index)
                # These are literal sourced descriptions/tags, not inferred meanings.
                semantics = sorted({text for row in fields for text in
                    [row.get('field_description', row.get('description')), *row.get('semantic_tags', [])]
                    if isinstance(text, str) and text.strip()})
                pack = dict(resource_contract_version=2, scope=deepcopy(scope), source_index=selected,
                    source_texts=texts, allowed_role_semantics=semantics,
                    allowed_operator_intents=['level', 'change'], histories=[])
                resource = dict(resource_contract_version=2, field_rows=deepcopy(fields),
                    operator_rows=deepcopy(operators), source_index=selected, source_texts=texts,
                    evidence_pack=pack, settings=build_settings({**config,
                        **{key: scope[key] for key in ('instrument_type', 'region', 'delay', 'universe')}}))
                accept(resource)
            except (OSError, ValueError, TypeError, KeyError) as error:
                diagnostics.append(dict(dataset_id=dataset, reason=str(error)))
    receipts = list({row['content_sha256']: row for row in receipts}.values())
    return resources[:count], receipts, diagnostics


def _save(path: Path, state: dict) -> None:
    """Input: journal Path/state dict. Output: None; persist restart inputs and integrity before model IO."""
    state.pop('state_sha256', None)
    state['state_sha256'] = _digest(state)
    _write(path, state)


def _repair_policy(resource: dict, supplied: dict | None = None) -> dict:
    """Input: already raw-validated compiler resource dict. Output: finite Repair policy dict.

    Field types are source facts, not evidence of noise, cadence or exposure.
    The current semantic contract has no setting-effect/bounds records. Do not
    repurpose raw as a project policy store or invent documented rule references.
    Empty rules are a supported deterministic exhaustion, not a Scout blocker.
    """
    from wqb.repair_search import _policy
    traits = {}
    fields = resource['field_rows']
    if fields and all(row['field_type'] == 'MATRIX' for row in fields):
        paths = sorted({path for row in fields for path in row['source_paths']})
        refs = [dict(source_path=path, sha256=resource['source_index'][path]['content_hash'],
            capture_date=resource['source_index'][path]['captured_at'][:10],
            kind='documented', experiment_refs=[]) for path in paths]
        traits['matrix_observation'] = dict(basis='source', value=True, evidence_refs=refs)
    if supplied is None:
        return _policy(dict(schema_version=1, rules=[], traits=traits))
    policy = _policy(supplied)
    if policy.get('resources') or any(rule['edit'] == 'transform' for rule in policy['rules']):
        raise ValueError('Start transforms require a separately verified parent-bound rule producer')
    if any(name not in traits or trait != traits[name] for name, trait in policy['traits'].items()):
        raise ValueError('project Repair policy contains unknown or changed sourced data traits')
    for rule in policy['rules']:
        for name, value in rule['requires'].items():
            if name not in policy['traits'] or policy['traits'][name]['value'] != value:
                raise ValueError('project Repair rule requires unsupported data traits')
        for ref in rule['evidence_refs']:
            source = resource['source_index'].get(ref['source_path'])
            if (not source or ref['sha256'] != source['content_hash']
                    or ref['capture_date'] != source['captured_at'][:10]
                    or ref['source_path'] not in resource['source_texts']):
                raise ValueError('project Repair rule source differs from certified resources')
    # The finite grid/effect is an explicit project experiment, not an official
    # parameter domain or a claim that this data is noisy. Measurement decides.
    return policy


def _unchanged_group(state: dict) -> dict:
    """Input: durable preparation state dict. Output: current paused group or fail closed after Stop/intent change."""
    group = read_group(Path(state['group_dir']))
    if group['request_revision'] != state['request_revision'] or group['desired_state'] != 'paused':
        raise ValueError('group Stop or intent changed; preparation cannot resume or replace authority')
    return group


def prepare_preplanned_start(paths, selected_option: dict, authority: dict, config: dict, *, model_runner) -> dict:
    """Input: paths with knowledge_root/run_root Paths, option/authority/config dicts, injected callable.

    config requires selected_scope (instrument_type/region/delay/universe/as_of)
    and measurement_period (start/end ISO dates). N/depth/initial_hypotheses
    default to 2/2/4; exact integer bounds are 1..32/1..16/1..16. Flat simulation
    settings use existing build_settings when no verified compiler context exists.
    A research_policy dict may supply the three planning parameters instead.
    Repair retains certified traits only; absent sourced effect/bounds produce
    an explicit empty finite search and diagnostic, not a Scout readiness failure.
    model_runner receives INITIAL_MODEL_CALLBACK_CONTRACT's source-bound brief;
    legacy codex_ai_worker hypothesis_design is deliberately not a fallback.

    Output: dict with status completed|blocked, reason, missing_facts, warnings,
    requested_lanes/prepared_lanes and group when allocated. Fewer genuinely
    available lanes are explicit. Complete means locally prepared and PAUSED:
    no worker, active pointer, runtime authority, live fallback or publication.
    Identical input reuses the durable group and per-lane model tasks. Unknown
    outcomes never replay. Stop revision changes remain blocked on later calls.
    """
    result = dict(status='blocked', reason='', missing_facts=[], warnings=[], prepared_lanes=0)
    try:
        scope, period, policy = _parameters(config)
        result['requested_lanes'] = policy['parallel_workflows']
        if type(selected_option) is not dict or not selected_option.get('option_id'):
            raise ValueError('selected_option requires an option_id')
        from wqb.workflow_stage_adapters import option_card_from_row
        option_card_from_row(selected_option)
        root = Path(paths.knowledge_root).absolute()
        runs = Path(paths.run_root).absolute()
        if any(p.is_symlink() or p.is_junction() for base in (root, runs) for p in (base, *base.parents)):
            raise ValueError('Start roots cannot traverse links')
        # Only non-secret executable settings participate in this local content key.
        settings = {k: config[k] for k in ('instrument_type', 'region', 'delay', 'universe', 'decay',
            'neutralization', 'truncation', 'pasteurization', 'unit_handling', 'nan_handling', 'language') if k in config}
        supplied_repair = deepcopy(config.get('repair_search_policy'))
        identity = dict(knowledge_root=str(root), selected_option=selected_option, authority=authority,
                        scope=scope, measurement_period=period, policy=policy, settings=settings,
                        repair_search_policy=supplied_repair)
        directory = _safe(runs, 'start_preflight/preplanned/' + _digest(identity))
        directory.mkdir(parents=True, exist_ok=True)
        path = _safe(directory, 'preparation.json')
        with json_lock_transition_guard(directory / 'guard', LOCK_SECONDS, LOCK_POLL_SECONDS, 'Start composer busy'):
            if path.exists():
                state = _json(directory, path.name)
                if (state.get('state_sha256') != _digest({k: v for k, v in state.items() if k != 'state_sha256'})
                        or state.get('identity') != identity):
                    raise ValueError('durable Start preparation integrity or input mismatch')
            else:
                resources, receipts, diagnostics = _local_resources(root, scope, config, policy['parallel_workflows'])
                result['missing_facts'] = diagnostics
                if not resources:
                    raise ValueError('no source-backed exact-scope lane resources; local maintenance required')
                repair_policies = [_repair_policy(resource, supplied_repair) for resource in resources]
                prepared = prepare_group_lanes(paths, resources, scope, selected_option, authority,
                    plan_depth=policy['plan_depth'], initial_hypotheses=policy['initial_hypotheses'])
                group = prepared['group']
                state = dict(identity=identity, resources=resources, receipts=receipts,
                    diagnostics=diagnostics, group_dir=group['group_dir'], request_revision=group['request_revision'],
                    repair_policies=repair_policies, planning_results=[])
                # Freeze comparison period before the initial model or its task key exists.
                for lane, repair in zip(group['lanes'], repair_policies):
                    run = runs / lane['run_id']
                    manifest = _json(run, 'run_manifest.json')
                    manifest['start_snapshot']['measurement_period'] = deepcopy(period)
                    manifest['start_snapshot']['repair_search_policy'] = repair
                    manifest['start_snapshot']['repair_search_diagnostics'] = deepcopy(REPAIR_DIAGNOSTICS)
                    _write(run / 'run_manifest.json', manifest)
                _save(path, state)
            group = _unchanged_group(state)
            result.update(group=group, prepared_lanes=len(group['lanes']), missing_facts=state['diagnostics'])
            if len(group['lanes']) < policy['parallel_workflows']:
                result['warnings'].append('insufficient distinct sourced selections: '
                    f"requested {policy['parallel_workflows']}, prepared {len(group['lanes'])}")
            snapshots = []
            for lane_index, (lane, resource) in enumerate(zip(group['lanes'], state['resources'])):
                _unchanged_group(state)
                _validate_resource(root, resource, scope,
                    list(_audit_resource_rows(machine_resource_path(root, 'data_ledger'), root)),
                    {r['path']: r for r in _audit_resource_rows(machine_resource_path(root, 'source_index'), root)})
                run = runs / lane['run_id']
                if _repair_policy(resource, supplied_repair) != state['repair_policies'][lane_index]:
                    raise ValueError('frozen initial Repair rules or traits changed')

                def bound_runner(brief: dict) -> dict:
                    """Input: certified planning brief dict. Output: raw injected-worker answer dict, never a launch here."""
                    from wqb.initial_research_planning import TASK_PATH
                    _unchanged_group(state)
                    supplied = deepcopy(brief)
                    supplied['worker_context'] = dict(checkpoint_type='initial_research_planning',
                        run_dir=str(run), knowledge_root=str(root), task_path=TASK_PATH,
                        manifest_path='run_manifest.json',
                        certificate_path='runtime/exploration/resources/'
                            + brief['resource_certificate_sha256'] + '.json')
                    return model_runner(supplied)

                if lane_index < len(state['planning_results']):
                    from wqb.exploration_eligibility import validate_operational_exploration
                    planning = state['planning_results'][lane_index]
                    manifest = _json(run, 'run_manifest.json')
                    if manifest['start_snapshot'] != planning['snapshot']:
                        raise ValueError('completed initial lane manifest changed')
                    validate_operational_exploration(run, root, manifest['start_snapshot'])
                else:
                    planning = prepare_initial_research(run, root, resource,
                        model_runner=bound_runner, template_receipts=state['receipts'],
                        tree_policy=dict(schema_version=1, plan_depth=policy['plan_depth'],
                                         initial_hypotheses=policy['initial_hypotheses']))
                    if planning['status'] == 'completed':
                        state['planning_results'].append(planning)
                        _save(path, state)
                _unchanged_group(state)
                if planning['status'] != 'completed':
                    result.update(reason=planning.get('reason', 'initial planning blocked'),
                                  blocked_lane=lane['run_id'])
                    return result
                snapshots.append(planning['snapshot'])
            _unchanged_group(state)
            completed = complete_group_lanes(paths, Path(group['group_dir']), snapshots)
            _unchanged_group(state)
            from wqb.research_tree import _load
            for lane in completed['lanes']:
                _load(runs / lane['run_id'])
            result['warnings'].extend(REPAIR_DIAGNOSTICS)
            result.update(status='completed', reason='', group=completed)
            return result
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, TimeoutError) as error:
        result['reason'] = 'preplanned_start_blocked:' + str(error)
        if not result['missing_facts']:
            result['missing_facts'] = [dict(reason=str(error))]
        return result
