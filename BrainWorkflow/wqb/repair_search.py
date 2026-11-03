"""Finite Repair producer/search; no AI receipt, dispatch or new authority.

Policy v1 supplies rules, traits and (for transforms) typed binding resources.
The opt-in compiler verifies supplied full source bytes and premises; persisted
planning additionally revalidates the owning operational snapshot. Legacy pure
search still treats EvidenceRef as a structural contract, not raw-file proof.
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
import re
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
COMPILED_INVARIANTS = {
    'positive_averaging': ('ts_mean', 'smoothing', 'window', 'INTEGER',
        'Returns the average value of x over the past d days.'),
    'positive_signed_power': ('signed_power', 'bounded_weights', 'scalar', 'FLOAT',
        'Raises the absolute value of x to the power y while preserving its sign.'),
}
COMPILED_TRAIT_FACTS = {'nuisance_exposure': 'nuisance_exposure', 'grain': 'vector_grain'}


def compile_repair_search_policy(resources: dict, project_policy: dict) -> dict:
    """Input: frozen source resources/project finite policy dicts. Output: strict policy dict.

    Source facts authorize prerequisites, not platform parameter domains or
    measured improvements. Parent binding is deferred until Repair acceptance.
    """
    from wqb.resource_evidence import _source, verify_premise, resolve_operator_definition
    from wqb.knowledge_compile import _coverage_field_supported, _coverage_source_fields
    if (type(project_policy.get('compile_version')) is not int or project_policy['compile_version'] != 1
            or set(project_policy) - {'compile_version', 'rules', 'traits'}):
        raise ValueError('unsupported Repair compiler input')
    if resources.get('resource_contract_version') != 2:
        raise ValueError('Repair compiler requires V2 sources')
    index, texts = resources['source_index'], resources['source_texts']
    scope = resources['evidence_pack']['scope']
    refs = {}
    for path, source in index.items():
        ref = dict(source_path=path, sha256=source['content_hash'],
                   capture_date=source['captured_at'][:10], kind='documented', experiment_refs=[])
        _source(ref, index, texts)
        refs[path] = ref
    fields = resources['field_rows']
    if not fields or any(not _coverage_field_supported(row, texts, index, scope,
            resource_contract_version=2) for row in fields):
        raise ValueError('Repair field facts differ from sourced scope/type/timing/grain')
    traits = {}
    field_refs = [refs[p] for p in sorted({p for row in fields for p in row['source_paths']})]
    if all(row['field_type'] == 'MATRIX' for row in fields):
        traits['matrix_observation'] = dict(basis='source', value=True, evidence_refs=field_refs)
    frequencies = []
    for row in fields:
        values = [field.get('sampling_frequency_sessions') for path in row['source_paths']
            for field, dataset, captured in _coverage_source_fields(texts[path])
            if field.get('id') == row['field_id'] and dataset.get('id') == row['dataset_id']
            and all(type(captured.get(k)) is type(scope[k]) and captured.get(k) == scope[k]
                    for k in ('instrument_type', 'region', 'delay', 'universe'))]
        if values and all(type(v) is int and v > 0 for v in values) and len(set(values)) == 1:
            frequencies.append(values[0])
    if len(frequencies) == len(fields) and len(set(frequencies)) == 1:
        traits['sampling_frequency_sessions'] = dict(basis='source', value=frequencies[0],
            units='sessions', evidence_refs=field_refs)
    for name, fact in project_policy.get('traits', {}).items():
        if (name not in COMPILED_TRAIT_FACTS or name in traits
                or set(fact) != {'value', 'premises'} or not fact['premises']):
            raise ValueError('explicit traits require exact source premises')
        if name == 'nuisance_exposure' and fact['value'] is not True:
            raise ValueError('nuisance exposure requires an explicit true fact')
        for premise in fact['premises']:
            locator = premise.get('locator', {})
            field_fact = COMPILED_TRAIT_FACTS[name]
            if (locator.get('kind') != 'json_value'
                    or locator.get('value_path') not in ([field_fact], ['field', field_fact])):
                raise ValueError('Repair trait premise has unsupported meaning')
            identity = locator.get('row_identity', {})
            if (identity.get('scope') != {k: scope[k] for k in ('instrument_type', 'region', 'delay', 'universe')}
                    or not any(identity.get('dataset_id') == row['dataset_id']
                               and identity.get('field_id') == row['field_id'] for row in fields)):
                raise ValueError('Repair trait requires an exact bound-field scope premise')
            value = verify_premise(premise, index, texts)
            if type(value) is not type(fact['value']) or value != fact['value']:
                raise ValueError('Repair trait premise mismatch')
        traits[name] = dict(basis='source', value=fact['value'],
            evidence_refs=[p['evidence_ref'] for p in fact['premises']])
    rules = copy.deepcopy(project_policy['rules'])
    for rule in rules:
        if any(name not in traits or type(traits[name]['value']) is not type(value)
               or traits[name]['value'] != value for name, value in rule['requires'].items()):
            raise ValueError('unsupported Repair trait prerequisite')
        if rule['edit'] == 'transform':
            invariant = rule.pop('invariant', None)
            if invariant not in COMPILED_INVARIANTS:
                raise ValueError('transform requires explicit supported mathematical invariant')
            name, effect, kind, scalar, meaning = COMPILED_INVARIANTS[invariant]
            transform = rule['transform']
            rows = [r for r in resources['operator_rows'] if r.get('operator') == name]
            if len(rows) != 1:
                raise ValueError('missing or ambiguous transform definition')
            row = rows[0]
            receipt = resolve_operator_definition(row, index, texts, resource_contract_version=2)
            definition = row['definition']
            parameters = definition['parameters']
            if (receipt['status'] != 'supported' or definition['description'] != meaning
                    or definition['input_types'] != ['MATRIX'] or definition['output_type'] != 'MATRIX'
                    or len(parameters) != 2 or [p['type'] for p in parameters] != ['MATRIX', scalar]
                    or any(not p['required'] or 'default' in p for p in parameters)
                    or transform['operator'] != name or transform['parameter'] != parameters[1]['name']
                    or transform['parameter_kind'] != kind or rule['effect'] != effect
                    or kind == 'window' and transform['frequency_trait'] != 'sampling_frequency_sessions'):
                raise ValueError('unsupported transform meaning/signature/invariant')
            rule['evidence_refs'] = copy.deepcopy(definition['evidence_refs'])
        else:
            if (rule['edit'] == 'neutralization'
                    and (rule['requires'].get('nuisance_exposure') is not True
                         or 'nuisance_exposure' not in project_policy.get('traits', {}))):
                raise ValueError('neutralization requires explicit sourced exposure')
            rule['evidence_refs'] = [ref for name in sorted(rule['requires'])
                                     for ref in traits[name]['evidence_refs']]
    policy = _policy(dict(schema_version=1, rules=rules, traits=traits))
    policy['resources'] = dict(resource_contract_version=2, field_rows=copy.deepcopy(fields),
        operator_rows=copy.deepcopy(resources['operator_rows']), scope=copy.deepcopy(scope),
        evidence_context=dict(source_index=copy.deepcopy(index), source_texts=copy.deepcopy(texts)),
        producer=dict(compile_version=1, project_policy=copy.deepcopy(project_policy)))
    return policy


def _materialize_parent(policy: dict, parent: dict) -> dict:
    """Input: compiled policy/accepted parent dicts. Output: copied, revalidated parent-bound policy.

    Explicit traits require premises for every actual parent field. Uncovered
    traits and dependent rules are omitted; independent rules remain eligible.
    """
    if not policy.get('resources', {}).get('producer'):
        return policy
    result = copy.deepcopy(policy)
    resources = result['resources']
    tree = ast.parse(parent['expression'], mode='eval')
    functions = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    leaves = sorted({node.id for node in ast.walk(tree)
                     if isinstance(node, ast.Name) and id(node) not in functions})
    selected, slots, tokens = [], [], {}
    for i, name in enumerate(leaves):
        rows = [r for r in resources['field_rows'] if r['field_id'] == name]
        if len(rows) != 1 or rows[0]['field_type'] not in ('MATRIX', 'VECTOR'):
            raise ValueError('parent field missing/ambiguous or unsupported type')
        row = rows[0]
        reduction = None
        if row['field_type'] == 'VECTOR':
            reducers = set()
            for leaf in ast.walk(tree):
                if not isinstance(leaf, ast.Name) or leaf.id != name or id(leaf) in functions:
                    continue
                call = parents.get(id(leaf))
                if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name)
                        or len(call.args) != 1 or call.args[0] is not leaf or call.keywords):
                    raise ValueError('VECTOR parent needs explicit unary sourced reducer')
                reducers.add(call.func.id)
            if len(reducers) != 1 or not row.get('vector_grain'):
                raise ValueError('VECTOR grain/reducer missing or ambiguous')
            reducer = next(iter(reducers))
            definitions = [r['definition'] for r in resources['operator_rows'] if r.get('operator') == reducer]
            if (len(definitions) != 1 or definitions[0]['input_types'] != ['VECTOR']
                    or definitions[0]['output_type'] != 'MATRIX' or len(definitions[0]['parameters']) != 1):
                raise ValueError('VECTOR reducer requires explicit VECTOR to MATRIX signature')
            reduction = dict(operator=reducer, parameters={})
        slot = 'repair_field_' + str(i)
        token = '__repair_slot_' + str(i)
        if token in parent['expression']:
            raise ValueError('parent placeholder collision')
        tokens[name] = token
        selected.append(row)
        slots.append(dict(name=slot, role='signal', required_semantics=[row['field_description']],
                          field_type=row['field_type'], required_metadata=[], reduction=reduction))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in functions:
            node.id = tokens[node.id]
    skeleton = ast.unparse(tree)
    replacements = {tokens[name]: '{repair_field_' + str(i) + '}' for i, name in enumerate(leaves)}
    skeleton = re.sub(r'\b__repair_slot_\d+\b', lambda match: replacements[match.group()], skeleton)
    # A resource-pack fact cannot authorize unrelated fields in the accepted parent.
    project = copy.deepcopy(resources['producer']['project_policy'])
    identities = {(row['dataset_id'], row['field_id']) for row in selected}
    applicable = {}
    for name, fact in project.get('traits', {}).items():
        premises = [premise for premise in fact['premises']
                    if (premise['locator']['row_identity']['dataset_id'],
                        premise['locator']['row_identity']['field_id']) in identities]
        covered = {(p['locator']['row_identity']['dataset_id'],
                    p['locator']['row_identity']['field_id']) for p in premises}
        if identities and covered == identities:
            applicable[name] = dict(fact, premises=premises)
    removed = set(project.get('traits', {})) - set(applicable)
    project['traits'] = applicable
    project['rules'] = [rule for rule in project['rules'] if not removed.intersection(rule['requires'])]
    result = compile_repair_search_policy(dict(resource_contract_version=2, field_rows=selected,
        operator_rows=resources['operator_rows'], evidence_pack=dict(scope=resources['scope']),
        **resources['evidence_context']), project)
    if 'stop' in policy:
        result['stop'] = policy['stop']
    resources = result['resources']
    resources['template'] = dict(template_id='repair-accepted-parent', binding_version=2,
        skeleton=skeleton, input_slots=slots)
    resources['field_rows'] = selected
    bound = bind_template(resources['template'], selected, resources['operator_rows'], resources['scope'],
        resource_contract_version=2, evidence_context=resources['evidence_context'])
    if ast.dump(ast.parse(bound['bound_expression'], mode='eval')) != ast.dump(ast.parse(parent['expression'], mode='eval')):
        raise ValueError('materialized template differs from accepted parent')
    return result


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
    producer = policy.get('resources', {}).get('producer')
    if producer:
        resources = policy['resources']
        frozen_context = resources['evidence_context']
        for key in ('source_index', 'source_texts'):
            if any(context[key].get(path) != value for path, value in frozen_context[key].items()):
                raise ValueError('compiled Repair sources differ from frozen context')
        rebuilt = compile_repair_search_policy(dict(resource_contract_version=2,
            field_rows=resources['field_rows'], operator_rows=resources['operator_rows'],
            evidence_pack=dict(scope=resources['scope']), **frozen_context), producer['project_policy'])
        if rebuilt != policy:
            raise ValueError('compiled Repair producer policy changed')
    if policy.get('resources'):
        resources = policy['resources']
        for key, snapshot_key in (('field_rows', 'data_ledger_rows'), ('operator_rows', 'operator_rows')):
            if any(row not in snapshot.get(snapshot_key, []) for row in resources.get(key, [])):
                raise ValueError('Repair transform resources differ from owning frozen snapshot')
        from wqb.hypothesis_template_compiler import _operator
        for rule in policy['rules']:
            if rule['edit'] == 'transform' and not producer:
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
    policy = _materialize_parent(policy, parent)
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
    policy = _materialize_parent(policy, evidence['parent'])
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
