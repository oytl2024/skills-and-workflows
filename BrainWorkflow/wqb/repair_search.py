"""Pure finite Repair search; no IO, AI receipt, dispatch or new authority.

Policy v1 supplies rules, traits and (for transforms) typed binding resources.
Like template_binding, this module consumes caller-verified frozen sources; an
EvidenceRef is a structural contract, not proof that this module read raw files.
The integrating caller must bind this output to that verified snapshot and still
enforce durable Stop, reservations, time, recovery and unknown-POST fences.

Policy: {schema_version: 1, rules: [...], traits: {name: {basis: source|
measured|hypothesis, value: scalar, evidence_refs: [...]}}, stop?: bool,
resources?: {template, field_rows, operator_rows, scope,
resource_contract_version, evidence_context?}}. Rules contain RULE_KEYS; transform
rules also contain TRANSFORM_KEYS under ``transform``. A source-backed rule, not
an operator name/type, authorizes the declared semantic effect and parameter
bounds. Window frequency facts explicitly use positive integer trading sessions.
The typed template must reproduce the current accepted incumbent, including any
previously accepted transformations. Hypotheses never authorize a trait.
"""

import ast
import copy
import hashlib
import json
import math
from pathlib import Path

from wqb.cli import simulation_identity_hash
from wqb.repair_identity import identity_hash_scheme
from wqb.repair_planning import DECAY_LIMIT, TRUNCATION_LIMIT, NEUTRALIZATIONS
from wqb.repair_trace import TARGET_DIRECTIONS
from wqb.semantic_contracts import evidence_ref_from_dict
from wqb.template_binding import IDENTIFIER, UNKNOWN_METADATA, TemplateBindingError, bind_template


PLANNER_VERSION = 1
MAX_VARIANTS = 8
MAX_RULES = 32
MAX_GRID = 32
SETTING_EFFECTS = {'decay': 'smoothing', 'truncation': 'bounded_weights',
                   'neutralization': 'nuisance_exposure'}
RULE_KEYS = {'rule_id', 'edit', 'effect', 'priority', 'target_metric', 'target_direction',
             'grid', 'requires', 'evidence_refs'}
TRANSFORM_KEYS = {'operator', 'parameter', 'parameter_kind', 'bounds', 'frequency_trait',
                  'preserves_direction'}
ECONOMIC_CONTEXT_KEYS = ('core_fields', 'economic_roles', 'conditions', 'direction',
                         'intended_direction', 'hypothesis', 'mechanism',
                         'prediction_direction', 'orientation', 'condition_filter_applied',
                         'measurement_scope', 'test_period', 'lane_id')
APPLICABILITY_LIMIT = 1600


def _digest(value: object) -> str:
    """Input: JSON-compatible object. Output: SHA256 str binding immutable planner inputs."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _number(value: object) -> bool:
    """Input: object. Output: bool; reject booleans and nonfinite numeric measurements."""
    return type(value) in (int, float) and math.isfinite(value)


def _sources(refs: object, kind: str) -> bool:
    """Input: references object/required kind str. Output: bool; never promote hypotheses."""
    if not isinstance(refs, list) or not refs:
        return False
    try:
        return all(evidence_ref_from_dict(ref).kind == kind for ref in refs)
    except (ValueError, TypeError, AttributeError):
        return False


def _policy(policy: dict) -> dict:
    """Input: policy dict. Output: canonical copy or ValueError; validate finite rules before planning."""
    if (not isinstance(policy, dict) or type(policy.get('schema_version')) is not int
            or policy['schema_version'] != PLANNER_VERSION
            or set(policy) - {'schema_version', 'rules', 'traits', 'stop', 'resources'}
            or type(policy.get('stop', False)) is not bool
            or not isinstance(policy.get('traits'), dict)):
        raise ValueError('Unsupported policy shape/version')
    rules = policy.get('rules')
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise ValueError('Expected bounded rules list')
    clean, identifiers = copy.deepcopy(policy), set()
    for rule in clean['rules']:
        if not isinstance(rule, dict) or set(rule) != RULE_KEYS | ({'transform'} if rule.get('edit') == 'transform' else set()):
            raise ValueError('Unknown or missing rule properties')
        name, edit = rule['rule_id'], rule['edit']
        if not isinstance(name, str) or not name.strip() or name in identifiers:
            raise ValueError('Expected distinct rule IDs')
        identifiers.add(name)
        if (not isinstance(edit, str) or edit not in SETTING_EFFECTS and edit != 'transform'
                or edit in SETTING_EFFECTS and rule['effect'] != SETTING_EFFECTS[edit]
                or edit == 'transform' and rule['effect'] not in ('smoothing', 'bounded_weights')):
            raise ValueError('Unsupported single-property edit/effect')
        if edit == 'transform':
            _transform_policy(rule['transform'])
        metric = rule['target_metric']
        if not isinstance(metric, str) or metric not in TARGET_DIRECTIONS or rule['target_direction'] != TARGET_DIRECTIONS[metric]:
            raise ValueError('Conflicting or unsupported target')
        if type(rule['priority']) is not int or rule['priority'] < 0:
            raise ValueError('Expected fixed nonnegative priority')
        if not isinstance(rule['requires'], dict) or not rule['requires']:
            raise ValueError('Rules require explicit eligible data traits')
        if any(not isinstance(key, str) or not key or type(value) not in (str, bool, int, float)
               or type(value) is float and not math.isfinite(value)
               for key, value in rule['requires'].items()):
            raise ValueError('Invalid trait predicate')
        if len(json.dumps(rule['requires'], sort_keys=True)) > APPLICABILITY_LIMIT:
            raise ValueError('Oversized trait predicate')
        grid = rule['grid']
        if not isinstance(grid, list) or not 1 <= len(grid) <= MAX_GRID:
            raise ValueError('Expected finite nonempty grid')
        for value in grid:
            valid = (edit == 'decay' and type(value) is int and 0 <= value <= DECAY_LIMIT
                     or edit == 'truncation' and _number(value) and 0 < value <= TRUNCATION_LIMIT
                     or edit == 'neutralization' and isinstance(value, str) and value in NEUTRALIZATIONS
                     or edit == 'transform' and _number(value) and
                     rule['transform']['bounds'][0] <= value <= rule['transform']['bounds'][1] and
                     (rule['transform']['parameter_kind'] != 'window' or type(value) is int))
            if not valid:
                raise ValueError('Grid value outside supported type/bounds')
        rule['grid'] = sorted(set(grid))
    clean['rules'].sort(key=lambda rule: (rule['priority'], rule['rule_id']))
    return clean


def _transform_policy(transform: dict) -> None:
    """Input: transform declaration dict. Output: None or ValueError; no operator facts inferred."""
    if (not isinstance(transform, dict) or set(transform) != TRANSFORM_KEYS
            or transform['preserves_direction'] is not True
            or transform['parameter_kind'] not in ('window', 'scalar')
            or any(not isinstance(transform[key], str) or not IDENTIFIER.fullmatch(transform[key])
                   for key in ('operator', 'parameter'))):
        raise ValueError('Transform requires a sourced direction-preserving typed declaration')
    bounds = transform['bounds']
    if (not isinstance(bounds, list) or len(bounds) != 2 or not all(_number(v) for v in bounds)
            or bounds[0] <= 0 or bounds[0] > bounds[1]):
        raise ValueError('Transform requires finite positive parameter bounds')
    if transform['parameter_kind'] == 'window':
        if (not all(type(v) is int for v in bounds) or not isinstance(transform['frequency_trait'], str)
                or not transform['frequency_trait']):
            raise ValueError('Window requires integer bounds and an explicit frequency trait')
    elif transform['frequency_trait'] is not None:
        raise ValueError('Scalar parameters cannot imply a frequency conversion')


def _frequency_reason(rule: dict, traits: dict, value: object) -> str:
    """Input: rule/traits dicts and grid scalar. Output: reason str; sessions are never guessed."""
    transform = rule.get('transform', {})
    if transform.get('parameter_kind') != 'window':
        return ''
    name = transform['frequency_trait']
    fact = traits.get(name, {})
    frequency = fact.get('value') if isinstance(fact, dict) else None
    if (not isinstance(fact, dict) or type(frequency) is not int or frequency < 1
            or fact.get('units') != 'sessions' or _trait_reason(traits, name, frequency)):
        return 'frequency_unknown_or_unestablished'
    return 'frequency_constraint' if value < frequency else ''


def _typed_transform(parent: dict, rule: dict, value: object, resources: dict) -> dict:
    """Input: parent/rule/resources dicts, parameter scalar. Output: binding dict or TemplateBindingError.

    Only wrap the complete verified parent subtree; never substitute fields,
    conditions, roles, sign or a new mechanism. Source-backed rule authorization
    supplies the semantic effect; the binder supplies mathematical type checking.
    """
    if not isinstance(resources, dict) or not isinstance(resources.get('template'), dict):
        raise TemplateBindingError('Missing frozen typed binding resources')
    template = copy.deepcopy(resources['template'])
    if type(template.get('binding_version')) is not int or template['binding_version'] != 2:
        raise TemplateBindingError('Transforms cannot use the untyped legacy binder')
    scope = resources.get('scope')
    if (not isinstance(scope, dict) or any(key not in scope or key not in parent['settings']
            or type(scope[key]) is not type(parent['settings'][key])
            or scope[key] != parent['settings'][key] for key in ('region', 'delay', 'universe'))):
        raise TemplateBindingError('Binding scope differs from parent simulation settings')
    if 'instrument_type' in scope and scope['instrument_type'] != parent['settings'].get('instrumentType'):
        raise TemplateBindingError('Binding instrument type differs from parent settings')
    args = (resources.get('field_rows', []), resources.get('operator_rows', []), resources.get('scope', {}))
    kwargs = dict(resource_contract_version=resources.get('resource_contract_version', 1),
                  evidence_context=resources.get('evidence_context'))
    baseline = bind_template(template, *args, **kwargs)
    parent_ast = ast.dump(ast.parse(parent['expression'], mode='eval').body)
    if ast.dump(ast.parse(baseline['bound_expression'], mode='eval').body) != parent_ast:
        raise TemplateBindingError('Frozen binding does not reproduce the complete parent')
    transform = rule['transform']
    template['skeleton'] = (transform['operator'] + '((' + template['skeleton'] + '), ' +
                            transform['parameter'] + '=' + repr(value) + ')')
    bound = bind_template(template, *args, **kwargs)
    node = ast.parse(bound['bound_expression'], mode='eval').body
    if not isinstance(node, ast.Call) or ast.dump(node.args[0]) != parent_ast:
        raise TemplateBindingError('Transform changed the parent subtree')
    return bound


def _trait_reason(traits: dict, name: str, expected: object) -> str:
    """Input: frozen traits dict/name str/expected scalar. Output: skip reason str or empty."""
    fact = traits.get(name)
    if not isinstance(fact, dict):
        return 'trait_unknown:' + name
    basis = fact.get('basis')
    if basis not in ('source', 'measured'):
        return 'trait_not_established:' + name
    kind = 'documented' if basis == 'source' else 'measured'
    if not _sources(fact.get('evidence_refs'), kind):
        return 'trait_source_missing:' + name
    value = fact.get('value')
    if value is None or isinstance(value, str) and value.strip().casefold() in UNKNOWN_METADATA | {''}:
        return 'trait_unknown:' + name
    if type(value) is not type(expected) or value != expected:
        return 'trait_mismatch_or_unknown:' + name
    return ''


def _used_identities(parent: dict, history: list) -> set[str]:
    """Input: parent dict/history list. Output: hashes set covering payloads, aliases and unknown POSTs."""
    used = set()
    for row in [parent] + history:
        if not isinstance(row, dict):
            raise ValueError('History must contain identity objects')
        identity = row.get('expression_hash')
        payload = isinstance(row.get('expression'), str) and isinstance(row.get('settings'), dict) and row['settings']
        if not payload and not (isinstance(identity, str) and len(identity) == 64
                                and all(c in '0123456789abcdef' for c in identity)):
            raise ValueError('History identity unavailable')
        if isinstance(identity, str):
            used.add(identity)
        if payload:
            json.dumps(row['settings'], allow_nan=False)
            used.add(simulation_identity_hash(row['expression'], row['settings']))
    return used


def prepare_search(run: Path, parent: dict, history: list, allowance: int, policy: dict) -> dict:
    """Input: run Path (context only), measured parent dict, history list, allowance int, policy dict.

    Output: deterministic plan dict: status validated|stopped|exhausted|blocked,
    planner_kind/version, evidence_digest, variants[], skipped[], stop_reason.
    Variants retain expression/settings/CLI identity/parent lineage plus a sourced
    decision. No files are read/written and no receipt or authority is invented.
    """
    result = dict(schema_version=1, planner_kind='deterministic', planner_version=PLANNER_VERSION,
                  status='blocked', variants=[], skipped=[], stop_reason='')
    if type(allowance) is not int or not 0 <= allowance <= MAX_VARIANTS:
        return result | dict(stop_reason='invalid_allowance')
    try:
        frozen = _policy(policy)
    except (ValueError, TypeError) as exc:
        return result | dict(stop_reason='invalid_policy', reason=str(exc))
    try:
        if (not isinstance(parent, dict) or not parent.get('alpha_id')
                or not identity_hash_scheme(parent) or not parent['expression'].strip()):
            raise ValueError('Parent identity must verify against expression and settings')
        json.dumps(parent['settings'], allow_nan=False)
    except (ValueError, TypeError, AttributeError) as exc:
        return result | dict(stop_reason='invalid_parent', reason=str(exc))
    if not isinstance(history, list):
        return result | dict(stop_reason='invalid_history')
    try:
        used = _used_identities(parent, history)
        result['evidence_digest'] = _digest(dict(parent=parent, policy=frozen,
            history=sorted(history, key=lambda row: json.dumps(row, sort_keys=True)), allowance=allowance))
    except (ValueError, TypeError) as exc:
        return result | dict(stop_reason='invalid_history', reason=str(exc))
    if frozen.get('stop') or parent.get('hard_pass') is True or allowance == 0:
        reason = 'stopped' if frozen.get('stop') else 'already_qualified' if parent.get('hard_pass') is True else 'allowance_exhausted'
        return result | dict(status='stopped', stop_reason=reason)
    for rule in frozen['rules']:
        reason = ''
        if not _sources(rule['evidence_refs'], 'documented'):
            reason = 'rule_source_missing'
        for name, expected in sorted(rule['requires'].items()):
            reason = reason or _trait_reason(frozen['traits'], name, expected)
        metrics = parent.get('metrics')
        if not isinstance(metrics, dict) or not _number(metrics.get(rule['target_metric'])):
            reason = reason or 'target_unmeasured'
        if reason:
            result['skipped'].append(dict(rule_id=rule['rule_id'], reason=reason))
            continue
        for value in rule['grid']:
            expression, settings = parent['expression'], copy.deepcopy(parent['settings'])
            binding = None
            reason = _frequency_reason(rule, frozen['traits'], value)
            if reason:
                result['skipped'].append(dict(rule_id=rule['rule_id'], value=value, reason=reason))
                continue
            if rule['edit'] == 'transform':
                try:
                    binding = _typed_transform(parent, rule, value, frozen.get('resources'))
                    expression = binding['bound_expression']
                except (TemplateBindingError, ValueError, TypeError, SyntaxError) as exc:
                    result['skipped'].append(dict(rule_id=rule['rule_id'], value=value,
                        reason='unsupported_transform', detail=str(exc)))
                    continue
            else:
                settings[rule['edit']] = value
            if expression == parent['expression'] and settings == parent['settings']:
                result['skipped'].append(dict(rule_id=rule['rule_id'], value=value, reason='no_change'))
                continue
            identity = simulation_identity_hash(expression, settings)
            if identity in used:
                result['skipped'].append(dict(rule_id=rule['rule_id'], value=value, reason='duplicate_identity'))
                continue
            used.add(identity)
            decision = dict(action='test', edit=rule['edit'], value=value,
                parent_alpha_id=parent['alpha_id'], parent_expression_hash=parent['expression_hash'],
                target_metric=rule['target_metric'], target_direction=rule['target_direction'],
                rule_id=rule['rule_id'], effect=rule['effect'], evidence_refs=copy.deepcopy(rule['evidence_refs']),
                applicability=json.dumps(rule['requires'], sort_keys=True),
                eligible_traits=copy.deepcopy(rule['requires']),
                falsification='Reject unless measured ' + rule['target_metric'] + ' improves in the declared '
                              'direction without Sharpe/Fitness regression or new baseline failures.',
                trait_evidence={name: copy.deepcopy(frozen['traits'][name]) for name in sorted(rule['requires'])})
            variant = dict(expression=expression, settings=settings, expression_hash=identity,
                simulation_identity=identity,
                parent_alpha_id=parent['alpha_id'], parent_expression_hash=parent['expression_hash'],
                repair_action='deterministic_' + rule['edit'], decision=decision)
            variant.update({key: copy.deepcopy(parent[key]) for key in ECONOMIC_CONTEXT_KEYS if key in parent})
            if binding is not None:
                variant['binding'] = binding
                decision['transform'] = copy.deepcopy(rule['transform'])
                if rule['transform']['frequency_trait'] is not None:
                    name = rule['transform']['frequency_trait']
                    decision['trait_evidence'][name] = copy.deepcopy(frozen['traits'][name])
            result['variants'].append(variant)
    result['remaining_candidates'] = max(0, len(result['variants']) - allowance)
    result['variants'] = result['variants'][:allowance]
    if result['variants']:
        return result | dict(status='validated')
    return result | dict(status='exhausted', stop_reason='search_space_exhausted')


def _frozen_policy(run: Path) -> tuple[dict, str]:
    """Input: owning run Path. Output: policy dict/manifest digest str; validate explicit frozen provenance."""
    from wqb.hypothesis_selection import validate_operational_resource_context
    raw = (Path(run) / 'run_manifest.json').read_bytes()
    manifest = json.loads(raw)
    snapshot = manifest['start_snapshot']
    if snapshot.get('research_policy', {}).get('deterministic_repair') is not True:
        raise ValueError('deterministic Repair requires explicit frozen run policy')
    context = validate_operational_resource_context(snapshot)
    if snapshot.get('research_policy', {}).get('exploration_scout') is True:
        from wqb.exploration_eligibility import validate_operational_exploration
        context = validate_operational_exploration(run, Path(manifest['knowledge_root']), snapshot)
    if not context:
        raise ValueError('deterministic Repair requires verified operational resources')
    policy = _policy(snapshot['repair_search_policy'])
    if policy.get('resources'):
        resources = policy['resources']
        for key, snapshot_key in (('field_rows', 'data_ledger_rows'), ('operator_rows', 'operator_rows')):
            if any(row not in snapshot.get(snapshot_key, []) for row in resources.get(key, [])):
                raise ValueError('Repair transform resources differ from owning frozen snapshot')
        from wqb.hypothesis_template_compiler import _operator
        for rule in policy['rules']:
            if rule['edit'] == 'transform':
                _operator(rule['transform']['operator'], resources['operator_rows'], context)
    refs = [ref for rule in policy['rules'] for ref in rule['evidence_refs']]
    refs.extend(ref for trait in policy['traits'].values() for ref in trait.get('evidence_refs', []))
    for ref in refs:
        source = context['source_index'].get(ref.get('source_path'))
        if (not source or source['content_hash'] != ref.get('sha256')
                or source['captured_at'][:10] != ref.get('capture_date')
                or ref['source_path'] not in context['source_texts']):
            raise ValueError('Repair rule or trait source differs from frozen operational evidence')
    return policy, hashlib.sha256(raw).hexdigest()


def prepare_persisted_search(run: Path, parent: dict, history: list, allowance: int) -> dict:
    """Input: owning Path, measured parent/history and allowance int. Output: immutable single-change plan dict."""
    from wqb.runtime_control import _write
    from wqb.lockfile import json_lock_transition_guard
    if type(allowance) is not int or not 1 <= allowance <= MAX_VARIANTS:
        raise ValueError('Repair allowance must be 1..8')
    policy, manifest_digest = _frozen_policy(run)
    evidence = dict(parent=parent, history=history, allowance=1, policy=policy,
                    manifest_sha256=manifest_digest)
    digest = _digest(evidence)
    directory = Path(run) / 'runtime/repair_decisions'
    path = directory / ('deterministic-' + digest + '.json')
    with json_lock_transition_guard(directory / ('deterministic-' + digest), 5.0, 0.05,
                                    'deterministic Repair planning busy'):
        if path.exists():
            return verify_persisted_search(run, json.loads(path.read_text(encoding='utf-8')))
        result = prepare_search(run, parent, history, 1, policy)
        if result['status'] == 'blocked':
            raise ValueError('deterministic Repair blocked: ' + result['stop_reason'])
        variants = result['variants']
        receipt = dict(result, evidence_digest=digest, status='validated', receipt_path=str(path),
                       decision=variants[0]['decision'] if variants else dict(action='stop', edit='none', value=0))
        _write(path.with_suffix('.input.json'), evidence)
        _write(path, receipt)
        return receipt


def verify_persisted_search(run: Path, plan: dict) -> dict:
    """Input: owning run Path and claimed plan dict. Output: verified receipt; no AI or live work."""
    if not isinstance(plan, dict) or plan.get('planner_kind') != 'deterministic':
        raise ValueError('unsupported deterministic receipt')
    digest = str(plan.get('evidence_digest', ''))
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('invalid deterministic evidence digest')
    path = Path(run) / 'runtime/repair_decisions' / ('deterministic-' + digest + '.json')
    if Path(plan.get('receipt_path', '')).resolve() != path.resolve() or path.is_symlink() or path.is_junction():
        raise ValueError('deterministic receipt path differs from owning run')
    saved = json.loads(path.read_text(encoding='utf-8'))
    evidence = json.loads(path.with_suffix('.input.json').read_text(encoding='utf-8'))
    policy, manifest_digest = _frozen_policy(run)
    if (_digest(evidence) != digest or policy != evidence['policy']
            or manifest_digest != evidence['manifest_sha256']):
        raise ValueError('deterministic Repair frozen evidence changed')
    rebuilt = prepare_search(run, evidence['parent'], evidence['history'], 1, policy)
    variants = rebuilt['variants']
    expected = dict(rebuilt, evidence_digest=digest, status='validated', receipt_path=str(path),
                    decision=variants[0]['decision'] if variants else dict(action='stop', edit='none', value=0))
    clean = lambda row: {k: v for k, v in row.items() if k != 'status'}
    if (clean(saved) != clean(expected) or clean(plan) != clean(saved)
            or saved.get('status') not in {'validated', 'consumed'}
            or plan.get('status') not in {'validated', 'consumed'}):
        raise ValueError('deterministic Repair plan differs from frozen search')
    return saved
