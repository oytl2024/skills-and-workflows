"""Deterministic, IO-free selection of frozen v2 executable hypotheses.

Snapshot contract: selected_scope, template_rows, data_ledger_rows (RAW rows,
including units/vector_grain/available_at), operator_rows. Provenance/release
integrity is checked by the snapshot owner before calling this helper.

Candidate contract: candidate_id, template_id, hypothesis_id/version,
binding_version=2, scope (exact selected_scope), settings (already bounded by
the planner), and the four bind_template outputs: bound_expression, bindings,
operator_provenance, operator_call_count. Optional window is a LOOKBACKS value
and requires an explicit template window slot. No model-authored kernels/cards.
Candidates are rebound against frozen rows; claimed binding receipts alone do
not establish eligibility. Template metadata, never candidate narratives,
supplies diversity. Nonempty template_family is the controlled canonical
mechanism key; normalized card text is a legacy fallback, not synonym inference.
Compilation owns grouping synonymous narratives under that stable family.

Return selected/rejected candidate copies and per-input reasons containing
index, candidate_id, code, detail, and (when selected) diversity novelty flags.
The caller passes maximum=min(original batch authority, remaining authority).
This helper additionally applies the existing Scout cap; it neither reserves
quota nor authorizes POST. AST-equivalent syntax plus exact complete settings
deduplicates narratives, without claiming general algebraic equivalence.
"""

import ast
import copy
import json
import hashlib
from collections import Counter
from datetime import date

from wqb.generator import LOOKBACKS
from wqb.research_workflow import cap_simulation_count, precheck_expression
from wqb.semantic_contracts import semantic_fields_from_dict
from wqb.template_binding import bind_template
from wqb.resource_evidence import resource_contract_version


BINDING_KEYS = ('bound_expression', 'bindings', 'operator_provenance', 'operator_call_count')
CANDIDATE_KEYS = {'candidate_id', 'template_id', 'hypothesis_id', 'hypothesis_version',
                  'binding_version', 'scope', 'settings', 'window', *BINDING_KEYS}
DIVERSITY_KEYS = ('mechanism', 'data_semantics', 'conditions', 'operator_roles')
MAX_BINDING_GROUPS_PER_TEMPLATE = 30
MAX_REJECTION_SAMPLES = 12
OPERATIONAL_CONTEXT_VERSION = 1


def paired_scout_enabled(research_policy: dict | None) -> bool:
    """Input: optional policy dict. Output: bool. Default off; reject coercion of explicit paired_scout values."""
    if research_policy is None:
        return False
    if not isinstance(research_policy, dict) or type(research_policy.get('paired_scout', False)) is not bool:
        raise ValueError('paired_scout must be a bool in research_policy')
    return research_policy.get('paired_scout', False)


def validate_operational_resource_context(snapshot: dict) -> dict:
    """Input: frozen snapshot dict. Output: verified context dict (legacy: {}). No filesystem or authority changes.

    Opt-in attachments use existing template experiment_paths and immutable
    manifest source_refs. Each UTF-8 attachment contains resource_contract_version,
    versions (the existing design contract), compiler_input {design,resources,scope}
    and the exact compiler experiment. Original sources and release files are
    frozen whole, never previews. Recompile under that contract, not a trust flag.
    """
    if not isinstance(snapshot, dict):
        raise ValueError('operational snapshot must be a dict')
    if not paired_scout_enabled(snapshot.get('research_policy')):
        require_legacy_resource_snapshot(snapshot)
        if 'operational_resource_context' in snapshot:
            raise ValueError('operational context requires explicit paired_scout mode')
        return {}
    try:
        return _validate_paired_context(snapshot)
    except (KeyError, TypeError, AttributeError, UnicodeError, RecursionError) as error:
        raise ValueError('paired_scout missing or invalid frozen operational context') from error


def _validate_paired_context(snapshot: dict) -> dict:
    """Input: explicitly paired snapshot dict. Output: verified sources/versions/experiments dict. Reuse compiler/binder rules."""
    from wqb.semantic_publication import _load, _require_digest
    from wqb.semantic_compilation import _design_versions
    from wqb.semantic_contracts import SemanticPolicy
    from wqb.hypothesis_design import compile_hypothesis_design
    context = snapshot['operational_resource_context']
    if (type(context['schema_version']) is not int or context['schema_version'] != OPERATIONAL_CONTEXT_VERSION
            or resource_contract_version(snapshot) != 2 or snapshot.get('hypothesis_binding_version') != 2):
        raise ValueError('paired_scout incompatible resource/context version')
    receipt = snapshot['semantic_release']
    if resource_contract_version(receipt) != 2 or not receipt.get('release_id'):
        raise ValueError('paired_scout requires reviewed immutable resource v2 release')
    files = context['release_files']
    if set(files) != {'manifest', 'operator_ledger', 'template_library'}:
        raise ValueError('paired_scout requires complete frozen release files')
    manifest_bytes = files['manifest'].encode('utf-8')
    if hashlib.sha256(manifest_bytes).hexdigest() != _require_digest(receipt['manifest_sha256']):
        raise ValueError('paired_scout frozen manifest bytes digest mismatch')
    manifest = _load(manifest_bytes)
    if (_json(manifest) != _json(receipt['manifest']) or manifest['release_id'] != receipt['release_id']
            or resource_contract_version(manifest) != 2):
        raise ValueError('paired_scout release/context versions disagree')
    rows = {}
    for name in ('operator_ledger', 'template_library'):
        raw = files[name].encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        if digest != receipt['digests'][name] or digest != manifest['resources'][name]['sha256']:
            raise ValueError('paired_scout frozen resource bytes digest mismatch')
        rows[name] = [_load(line) for line in raw.splitlines() if line.strip()]
    if (_json(snapshot['operator_rows']) != _json(rows['operator_ledger'])
            or _json(snapshot['template_rows']) != _json(rows['template_library'])):
        raise ValueError('paired_scout snapshot rows differ from immutable reviewed release')
    templates = snapshot['template_rows']
    if (not templates or any(row.get('semantic_status') != 'reviewed' or row.get('binding_version') != 2 for row in templates)
            or any(row.get('semantic_status') != 'reviewed' for row in snapshot['operator_rows'])):
        raise ValueError('paired_scout requires reviewed resources')
    sources = context['source_files']
    refs = manifest['source_refs']
    if len({ref['path'] for ref in refs}) != len(refs) or set(sources) != {ref['path'] for ref in refs}:
        raise ValueError('paired_scout missing or duplicate complete source bytes')
    for ref in refs:
        if hashlib.sha256(sources[ref['path']].encode('utf-8')).hexdigest() != _require_digest(ref['sha256']):
            raise ValueError('paired_scout frozen source/attachment bytes digest mismatch')
    paths = sorted({path for row in templates for path in row['experiment_paths']})
    if not paths or any(not row['experiment_paths'] for row in templates):
        raise ValueError('paired_scout requires exact experiment attachments')
    experiments, index, texts, versions, covered, fields = [], {}, {}, None, set(), []
    for path in paths:
        if not path.startswith('raw/research/') or path not in sources:
            raise ValueError('paired_scout attachment missing from immutable release source_refs')
        doc = _load(sources[path].encode('utf-8'))
        if set(doc) != {'resource_contract_version', 'versions', 'compiler_input', 'experiment'} or resource_contract_version(doc) != 2:
            raise ValueError('paired_scout incompatible experiment attachment contract')
        policy = SemanticPolicy(**doc['versions']['policy'])
        expected_versions = _design_versions(policy)
        if _json(doc['versions']) != _json(expected_versions) or (versions is not None and _json(versions) != _json(expected_versions)):
            raise ValueError('paired_scout incompatible source/rule/parameter/context versions')
        versions = expected_versions
        inputs = doc['compiler_input']
        if set(inputs) != {'design', 'resources', 'scope'} or _json(inputs['scope']) != _json(snapshot['selected_scope']):
            raise ValueError('paired_scout compiler scope differs from frozen context')
        resources = inputs['resources']
        if resource_contract_version(resources) != 2 or _json(resources['operator_rows']) != _json(snapshot['operator_rows']):
            raise ValueError('paired_scout compiler resources differ from reviewed release')
        if set(resources['source_index']) != set(resources['source_texts']):
            raise ValueError('paired_scout incomplete compiler source context')
        for relative, source in resources['source_index'].items():
            text = resources['source_texts'][relative]
            if relative not in sources or sources[relative] != text or source['path'] != relative:
                raise ValueError('paired_scout compiler source bytes differ from immutable release')
            if relative in index and _json(index[relative]) != _json(source):
                raise ValueError('paired_scout conflicting frozen source metadata')
            index[relative], texts[relative] = source, text
        for row in resources['field_rows']:
            if row not in fields:
                fields.append(row)
        compiled = compile_hypothesis_design(inputs['design'], resources, inputs['scope'])
        if compiled['status'] != 'compiled' or _json(compiled['experiment']) != _json(doc['experiment']):
            raise ValueError('paired_scout experiment differs from verified compiler/binder output')
        experiment = doc['experiment']
        if len(experiment['arms']) != 2 or {arm['arm_id'] for arm in experiment['arms']} != {'baseline', 'treatment'}:
            raise ValueError('paired_scout requires a complete baseline/treatment attachment')
        for draft in compiled['drafts']:
            matches = [row for row in templates if row['template_id'] == draft['template_id']]
            if len(matches) != 1 or matches[0]['experiment_paths'] != [path]:
                raise ValueError('paired_scout ambiguous experiment/template references')
            reviewed = dict(draft, semantic_status='reviewed', experiment_paths=[path])
            if _json(matches[0]) != _json(reviewed):
                raise ValueError('paired_scout reviewed template differs from exact experiment')
            covered.add(draft['template_id'])
        experiments.append(experiment)
    if len(covered) != len(templates) or _json(sorted(fields, key=_json)) != _json(sorted(snapshot['data_ledger_rows'], key=_json)):
        raise ValueError('paired_scout incomplete experiment/resource dependencies')
    if (len({row['experiment_id'] for row in experiments}) != len(experiments)
            or sorted(covered) != snapshot['compatible_template_ids']):
        raise ValueError('paired_scout duplicate experiment or incompatible template references')
    return copy.deepcopy(dict(resource_contract_version=2, versions=versions, source_index=index,
                              source_texts=texts, experiments=experiments))


def require_legacy_resource_snapshot(snapshot: dict) -> None:
    """Input: frozen snapshot dict. Output: None or ValueError; no silent v2 downgrade.

    Source-backed resources are M1 proposal artifacts. Operational consumption
    needs a separately approved frozen evidence-context contract, not activation
    by the presence of optional metadata or a producer version alone.
    """
    if (resource_contract_version(snapshot) != 1
            or resource_contract_version(snapshot.get('semantic_release', {})) != 1
            or any('timing_contract' in row for row in snapshot.get('data_ledger_rows', []))
            or any('definition_basis' in row for row in snapshot.get('operator_rows', []))):
        raise ValueError('source-backed resource contract requires approved operational evidence context')


def rejection_reason(code: str, detail: str) -> dict:
    """Input: code/detail str. Output: bounded reason dict with stable ID. Preserve diagnostics without copying whole catalogs."""
    return dict(reason_id=hashlib.sha256((code + '\n' + detail).encode()).hexdigest(), code=code, detail=detail[:500])


def binding_group_id(binding: dict) -> str:
    """Input: binding receipt dict. Output: stable str. Identify exact slot fields/metadata independently of a window variant."""
    return hashlib.sha256(_json(binding['bindings']).encode()).hexdigest()


def binding_field_rows(snapshot: dict, binding: dict) -> list[dict]:
    """Input: snapshot and claimed binding dicts. Output: exact frozen raw rows. Reject missing/ambiguous dataset+field identities."""
    selected = []
    for slot in binding['bindings'].values():
        matches = [row for row in snapshot['data_ledger_rows'] if row.get('dataset_id') == slot['dataset_id']
                   and row.get('field_id', row.get('id')) == slot['field_id']]
        if len(matches) != 1:
            raise ValueError('missing or ambiguous exact frozen field identity')
        if matches[0] not in selected:
            selected.append(matches[0])
    return selected


def enumerate_hypothesis_bindings(template: dict, fields: list[dict], operators: list[dict], scope: dict,
                                  *, report: dict | None = None) -> list[dict]:
    """Input: template, raw fields/operators, scope dicts. Output: bounded explicit binding receipts. Never relax binder ambiguity.

    Prefer complete same-dataset groups. Pair sorted eligible slot rows by index
    (not a Cartesian product); only use cross-dataset groups when no dataset
    independently supplies all slots. This is deterministic selection, not a
    claim of exhaustive catalog search or inferred economic equivalence.
    """
    from wqb.template_binding import _select_field, TemplateBindingError
    require_legacy_resource_snapshot(dict(data_ledger_rows=fields, operator_rows=operators))
    if report is None:
        report = {}
    report.update(binding_attempt_count=0, binding_pass_count=0, rejections=[])
    semantic = semantic_fields_from_dict(template)
    slots = semantic['input_slots']
    if not slots:
        return []
    ordered = sorted(fields, key=lambda row: (str(row.get('dataset_id', '')), str(row.get('field_id', ''))))
    datasets = sorted({row.get('dataset_id') for row in ordered if isinstance(row.get('dataset_id'), str)})
    groups, seen = [], set()
    subsets = [[row for row in ordered if row.get('dataset_id') == dataset] for dataset in datasets]
    for subset in [*subsets, ordered]:
        if subset is ordered and groups:
            break
        choices = []
        for slot in slots:
            eligible = []
            for row in subset:
                try:
                    _select_field(slot, [row], scope)
                    eligible.append(row)
                except TemplateBindingError as exc:
                    if 'semantic/type/scope match' not in str(exc) and len(report['rejections']) < MAX_REJECTION_SAMPLES:
                        report['rejections'].append(rejection_reason('field_facts_unavailable',
                            str(template.get('template_id')) + ': ' + str(row.get('dataset_id')) + '.' +
                            str(row.get('field_id')) + ': ' + str(exc)))
                    continue
            choices.append(eligible)
        if any(not rows for rows in choices):
            if len(report['rejections']) < MAX_REJECTION_SAMPLES:
                report['rejections'].append(rejection_reason('missing_slot_facts',
                    str(template.get('template_id')) + ': no eligible facts for ' + ','.join(
                        slot.name for slot, rows in zip(slots, choices) if not rows)))
            continue
        for index in range(min(MAX_BINDING_GROUPS_PER_TEMPLATE, max(map(len, choices)))):
            selected = []
            for rows in choices:
                row = rows[index % len(rows)]
                if row not in selected:
                    selected.append(row)
            try:
                report['binding_attempt_count'] += 1
                binding = bind_template(template, selected, operators, scope)
            except TemplateBindingError as exc:
                if len(report['rejections']) < MAX_REJECTION_SAMPLES:
                    report['rejections'].append(rejection_reason('binding_invalid', str(template.get('template_id')) + ': ' + str(exc)))
                continue
            report['binding_pass_count'] += 1
            identifier = binding_group_id(binding)
            if identifier not in seen:
                groups.append(binding)
                seen.add(identifier)
            if len(groups) >= MAX_BINDING_GROUPS_PER_TEMPLATE:
                return groups
    return groups


def validate_hypothesis_match(snapshot: dict, match: dict) -> dict:
    """Input: frozen snapshot/match dicts. Output: verified binding dict. Validate complete schedule dependencies without live reads."""
    if paired_scout_enabled(snapshot.get('research_policy')):
        context = validate_operational_resource_context(snapshot)
        for experiment in context['experiments']:
            for arm in experiment['arms']:
                candidate = _experiment_candidate(snapshot, arm)
                if (all(match.get(key) == candidate[key] for key in ('template_id', 'hypothesis_id', 'hypothesis_version'))
                        and match.get('binding_id') == binding_group_id(arm['binding'])
                        and _json(match.get('hypothesis_binding')) == _json(arm['binding'])):
                    template = next(row for row in snapshot['template_rows'] if row['template_id'] == arm['template_id'])
                    if any(key in match and match[key] != template[key] for key in ('skeleton', 'hypothesis')):
                        raise ValueError('paired schedule differs from frozen template')
                    return copy.deepcopy(arm['binding'])
        raise ValueError('paired schedule differs from frozen experiment')
    require_legacy_resource_snapshot(snapshot)
    keys = ('template_id', 'hypothesis_id', 'hypothesis_version')
    templates = [row for row in snapshot['template_rows'] if all(
        _json(row.get(key)) == _json(match.get(key)) for key in keys)]
    if len(templates) != 1 or templates[0].get('semantic_status') != 'reviewed':
        raise ValueError('unknown or unreviewed frozen hypothesis match')
    template = templates[0]
    for key, plural in [('region', 'regions'), ('delay', 'delays'), ('universe', 'universes')]:
        allowed = template.get('compatible_' + plural, [])
        if allowed and not any(_json(snapshot['selected_scope'][key]) == _json(value) for value in allowed):
            raise ValueError('hypothesis match excludes frozen scope')
    bound = bind_template(template, binding_field_rows(snapshot, match['hypothesis_binding']), snapshot['operator_rows'], snapshot['selected_scope'])
    if match.get('binding_id') is not None and match['binding_id'] != binding_group_id(bound):
        raise ValueError('hypothesis schedule binding group ID mismatch')
    if _json(match.get('hypothesis_binding')) != _json(bound):
        raise ValueError('hypothesis schedule binding differs from frozen dependencies')
    for key in ('skeleton', 'hypothesis'):
        if key in match and _json(match[key]) != _json(template.get(key)):
            raise ValueError('hypothesis schedule differs from frozen template')
    return bound


def _json(value: object) -> str:
    """Input: JSON-compatible object. Output: canonical str. Preserve scalar types and reject nonfinite values."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _text(value: str) -> str:
    """Input: str. Output: str. Normalize case/spacing without inventing semantic equivalence."""
    return ' '.join(value.casefold().split())


def _expression(value: str) -> str:
    """Input: bound expression str. Output: AST identity str. Ignore only syntactic spacing/parentheses."""
    return ast.dump(ast.parse(value.strip(), mode='eval'), include_attributes=False)


def _validate_candidate(snapshot: dict, candidate: dict, *, operational_context: dict | None = None) -> tuple:
    """Input: frozen snapshot and candidate dicts. Output: identity/features/count tuple. Reject untrusted claims."""
    if not isinstance(candidate, dict) or set(candidate) - CANDIDATE_KEYS:
        raise ValueError('unknown candidate schema')
    for key in ('candidate_id', 'template_id', 'hypothesis_id'):
        if not isinstance(candidate.get(key), str) or not candidate[key].strip():
            raise ValueError(f'missing {key}')
    if type(candidate.get('binding_version')) is not int or candidate['binding_version'] != 2:
        raise ValueError('requires v2 binding')
    if type(candidate.get('hypothesis_version')) is not int or candidate['hypothesis_version'] < 1:
        raise ValueError('invalid hypothesis version')
    matches = [row for row in snapshot['template_rows'] if row.get('template_id') == candidate['template_id']
               and row.get('hypothesis_id') == candidate['hypothesis_id']
               and type(row.get('hypothesis_version')) is int
               and row['hypothesis_version'] == candidate['hypothesis_version']]
    if len(matches) != 1:
        raise ValueError('unknown or ambiguous frozen hypothesis/template/version')
    template = matches[0]
    semantic = semantic_fields_from_dict(template)
    if (semantic.get('binding_version') != 2 or semantic.get('semantic_status') != 'reviewed'
            or not semantic.get('hypothesis_card') or not semantic.get('input_slots')
            or (not semantic.get('operator_roles') and not paired_scout_enabled(snapshot.get('research_policy')))):
        raise ValueError('requires reviewed v2 card, slots and operator roles')
    scope = snapshot['selected_scope']
    if _json(candidate.get('scope')) != _json(scope):
        raise ValueError('candidate scope differs from frozen scope')
    settings = candidate.get('settings')
    if not isinstance(settings, dict):
        raise ValueError('settings must be a complete planner-validated dict')
    for key, plural in [('region', 'regions'), ('delay', 'delays'), ('universe', 'universes')]:
        if key not in scope or _json(settings.get(key)) != _json(scope[key]):
            raise ValueError(f'settings.{key} differs from frozen scope')
        allowed = template.get('compatible_' + plural, [])
        if allowed and not any(_json(scope[key]) == _json(value) for value in allowed):
            raise ValueError(f'template excludes frozen {key}')
    binding_scope = dict(scope)
    if 'window' in candidate:
        window = candidate['window']
        if type(window) is not int or window not in LOOKBACKS or '{window}' not in template.get('skeleton', ''):
            raise ValueError('window is not an explicit bounded template parameter')
        binding_scope['window'] = window
    if paired_scout_enabled(snapshot.get('research_policy')):
        context = operational_context if operational_context is not None else validate_operational_resource_context(snapshot)
        arms = [arm for experiment in context['experiments'] for arm in experiment['arms']
                if arm['template_id'] == template['template_id']]
        if len(arms) != 1 or 'window' in candidate:
            raise ValueError('candidate differs from frozen experiment arm')
        # Context validation recompiles and source-rebinds both complete arms.
        expected = arms[0]['binding']
    else:
        expected = bind_template(template, binding_field_rows(snapshot, candidate), snapshot['operator_rows'], binding_scope)
    if _expression(candidate.get('bound_expression', '')) != _expression(expected['bound_expression']):
        raise ValueError('expression differs from frozen binding')
    for key in BINDING_KEYS[1:]:
        if key not in candidate or _json(candidate[key]) != _json(expected[key]):
            raise ValueError(f'{key} differs from frozen binding')
    used = {row['operator'] for row in expected['operator_provenance']}
    declared = {role.operator for role in semantic['operator_roles']}
    if used != declared:
        raise ValueError('operator roles must cover precisely the bound operators')
    card = semantic['hypothesis_card']
    family = template.get('template_family', '')
    if not isinstance(family, str):
        raise ValueError('template_family must be text')
    features = (_text(family) if family.strip() else _text(card.mechanism),
                tuple(sorted({_text(term) for slot in semantic['input_slots'] for term in slot.required_semantics})),
                _text(card.conditions), tuple(sorted({_text(role.role) for role in semantic['operator_roles']})))
    return (_expression(expected['bound_expression']), _json(settings)), features, expected['operator_call_count']


def select_hypothesis_batch(snapshot: dict, candidates: list[dict], maximum: int) -> dict:
    """Input: frozen snapshot dict, bound candidates list[dict], authorized maximum int. Output: selection dict.

    Validate/rebind first, deduplicate simulation identities, greedily cover new
    mechanisms then semantics/conditions/roles, prefer fewer actual calls, and
    break ties by candidate ID. Invalid snapshot/max raises ValueError; invalid
    candidates remain in rejected with diagnostics. No IO or input mutation.
    """
    if type(maximum) is not int or maximum < 0:
        raise ValueError('maximum must be a nonnegative authorized integer')
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('selected_scope'), dict):
        raise ValueError('missing frozen selected_scope')
    context = validate_operational_resource_context(snapshot)
    for key in ('template_rows', 'data_ledger_rows', 'operator_rows'):
        if not isinstance(snapshot.get(key), list) or any(not isinstance(row, dict) for row in snapshot[key]):
            raise ValueError(f'missing or invalid frozen {key}')
    if not isinstance(candidates, list):
        raise ValueError('candidates must be a list')
    counts = Counter(row.get('candidate_id') for row in candidates
                     if isinstance(row, dict) and isinstance(row.get('candidate_id'), str))
    reasons, eligible = {}, []
    for index, candidate in enumerate(candidates):
        identifier = candidate.get('candidate_id') if isinstance(candidate, dict) else None
        reasons[index] = dict(index=index, candidate_id=identifier)
        try:
            if isinstance(identifier, str) and counts[identifier] != 1:
                raise ValueError('duplicate candidate_id')
            identity, features, calls = _validate_candidate(snapshot, candidate, operational_context=context)
            check = precheck_expression(candidate['bound_expression'], 'scout')
            if not check.ok:
                reasons[index].update(code='scout_complexity', detail='; '.join(check.reasons))
                continue
            eligible.append(dict(index=index, candidate=candidate, identity=identity, features=features, calls=calls))
        except (ValueError, TypeError, KeyError, AttributeError, SyntaxError, RecursionError) as exc:
            reasons[index].update(code='invalid_candidate', detail=str(exc))
    # Narrative diversity cannot justify duplicate simulations. Choose a stable representative first.
    unique, seen = [], set()
    for row in sorted(eligible, key=lambda row: (row['calls'], row['candidate']['candidate_id'])):
        if row['identity'] in seen:
            reasons[row['index']].update(code='duplicate_simulation', detail='Equivalent expression and complete settings.')
        else:
            seen.add(row['identity'])
            unique.append(row)
    covered = [set() for _ in DIVERSITY_KEYS]
    selected = []
    while unique and len(selected) < cap_simulation_count('scout', maximum):
        row = min(unique, key=lambda row: (*(feature in used for feature, used in zip(row['features'], covered)),
                                          row['calls'], row['candidate']['candidate_id']))
        novelty = {key: feature not in used for key, feature, used in zip(DIVERSITY_KEYS, row['features'], covered)}
        reasons[row['index']].update(code='selected', detail='Frozen binding selected within authorized Scout cap.',
                                     diversity=novelty)
        for used, feature in zip(covered, row['features']):
            used.add(feature)
        selected.append(row['index'])
        unique.remove(row)
    for row in unique:
        reasons[row['index']].update(code='batch_limit', detail='Authorized maximum or existing Scout cap reached.')
    selected_set = set(selected)
    for reason in reasons.values():
        reason['reason_id'] = rejection_reason(reason['code'], str(reason['candidate_id']) + ': ' + reason['detail'])['reason_id']
    return dict(selected=[copy.deepcopy(candidates[index]) for index in selected],
                rejected=[copy.deepcopy(row) for index, row in enumerate(candidates) if index not in selected_set],
                reasons=[reasons[index] for index in range(len(candidates))])


def _experiment_candidate(snapshot: dict, arm: dict) -> dict:
    """Input: verified frozen snapshot/arm dicts. Output: existing candidate-schema dict, no identity extensions."""
    template = next(row for row in snapshot['template_rows'] if row['template_id'] == arm['template_id'])
    row = dict(template_id=template['template_id'], hypothesis_id=template['hypothesis_id'],
               hypothesis_version=template['hypothesis_version'], binding_version=2,
               scope=copy.deepcopy(arm['scope']), settings=copy.deepcopy(arm['settings']), **copy.deepcopy(arm['binding']))
    row['candidate_id'] = hashlib.sha256(_json(row).encode()).hexdigest()
    return row


def _compatible_measurement(snapshot: dict, candidate: dict, identity: str, measurement: object) -> bool:
    """Input: frozen snapshot/candidate, identity str, claimed measurement object. Output: bool. Require exact dated simulation evidence."""
    period = snapshot.get('measurement_period')
    try:
        if (not isinstance(period, dict) or set(period) != {'start', 'end'}
                or date.fromisoformat(period['start']) > date.fromisoformat(period['end'])):
            return False
        if not isinstance(measurement, dict):
            return False
        metrics = measurement.get('metrics')
        _json(metrics)
        return (measurement.get('status') == 'measured' and measurement.get('expression_hash') == identity
            and measurement.get('expression') == candidate['bound_expression']
            and _json(measurement.get('settings')) == _json(candidate['settings'])
            and _json(measurement.get('scope')) == _json(candidate['scope'])
            and _json(measurement.get('measurement_period')) == _json(period)
            and isinstance(metrics, dict) and any(type(value) in (int, float) for value in metrics.values()))
    except (ValueError, TypeError, KeyError):
        return False


def select_experiment_batch(snapshot: dict, experiments: list[dict], maximum: int,
                            available_measurements: dict | None = None) -> dict:
    """Input: frozen snapshot, experiment list, quota int, optional identity->measurement dict. Output: selection dict.

    Recompile complete groups before dedup/cap. Sidecars retain every arm link;
    selected contains unique missing simulations only. Reuse requires measured
    metrics and exact simulation/settings/scope plus an explicit known period
    in snapshot.measurement_period. A correlation cache never funds an arm.
    """
    from wqb.cli import simulation_identity_hash
    if type(maximum) is not int or maximum < 0 or not isinstance(experiments, list):
        raise ValueError('invalid experiment list or authorized maximum')
    context = validate_operational_resource_context(snapshot)
    if not context:
        raise ValueError('paired Scout requires frozen operational context')
    if available_measurements is not None and not isinstance(available_measurements, dict):
        raise ValueError('available_measurements must be an identity mapping')
    measurements = available_measurements or {}
    known = {row['experiment_id']: row for row in context['experiments']}
    groups, reasons, seen = [], [], set()
    for index, experiment in enumerate(experiments):
        identifier = experiment.get('experiment_id') if isinstance(experiment, dict) else None
        reason = dict(index=index, experiment_id=identifier)
        reasons.append(reason)
        if identifier not in known or _json(experiment) != _json(known[identifier]):
            reason.update(code='invalid_experiment', detail='Experiment differs from verified frozen compiler output.')
            continue
        if identifier in seen:
            reason.update(code='duplicate_experiment', detail='Repeated complete experiment.')
            continue
        seen.add(identifier)
        arms = [_experiment_candidate(snapshot, arm) for arm in experiment['arms']]
        identities = [simulation_identity_hash(row['bound_expression'], row['settings']) for row in arms]
        ast_identities = [(_expression(row['bound_expression']), _json(row['settings'])) for row in arms]
        if (len(set(ast_identities)) != 2 or any(not precheck_expression(row['bound_expression'], 'scout').ok for row in arms)):
            reason.update(code='invalid_experiment', detail='Identical arms or Scout complexity rejection.')
            continue
        reusable = set()
        for row, identity in zip(arms, identities):
            measurement = measurements.get(identity)
            if _compatible_measurement(snapshot, row, identity, measurement):
                reusable.add(identity)
        groups.append((experiment, arms, identities, reusable, reason))
    selected, accepted, sidecars, funded = [], [], [], set()
    cap = cap_simulation_count('scout', maximum)
    for experiment, arms, identities, reusable, reason in groups:
        missing = set(identities) - funded - reusable
        if len(selected) + len(missing) > cap:
            reason.update(code='insufficient_pair_budget', detail='Original authority cannot fund a complete comparison.')
            continue
        if not missing and not (set(identities) & funded):
            reason.update(code='already_measured', detail='No novel simulation required.')
            continue
        baseline = identities[0]
        accepted.append(copy.deepcopy(experiment))
        for arm, row, identity in zip(experiment['arms'], arms, identities):
            sidecars.append(dict(experiment_id=experiment['experiment_id'], arm_id=arm['arm_id'],
                candidate_id=row['candidate_id'], expression_hash=identity, baseline_expression_hash=baseline,
                baseline_template_id=experiment['baseline_template_id'], reused=identity in reusable,
                measurement=copy.deepcopy(measurements[identity]) if identity in reusable else None))
            if identity in missing and identity not in funded:
                selected.append(row)
                funded.add(identity)
        reason.update(code='selected', detail='Complete group funded within original authority.')
    for reason in reasons:
        reason['reason_id'] = rejection_reason(reason['code'], str(reason['experiment_id']) + ': ' + reason['detail'])['reason_id']
    return dict(selected=selected, experiments=accepted, sidecars=sidecars, reasons=reasons,
                generated_count=sum(len(group[1]) for group in groups))


def summarize_hypothesis_selection(snapshot: dict, selection: dict) -> dict:
    """Input: frozen snapshot/selection dicts. Output: aggregate report dict. Preserve the selector's original three-key API."""
    context = validate_operational_resource_context(snapshot)
    families = sorted({_validate_candidate(snapshot, row, operational_context=context)[1][0] for row in selection['selected']})
    return dict(candidate_count=len(selection['reasons']), selected_count=len(selection['selected']),
                mechanism_families=families, mechanism_family_count=len(families),
                reason_counts=dict(Counter(row['code'] for row in selection['reasons'])))
