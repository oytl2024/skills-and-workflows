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

Policy v2 adds METRIC_RULE_KEYS and an optional bounded rulebook_id. Documented
references establish actual parent-field/trait facts; project_hypothesis labels
the unproven setting effect. Completed failure names OR a measured metric
predicate activate a rule. Normalized gap and matching failure count rank it
before declared priority/ID. Pending checks never become failed checks. V1
canonicalization, fixed ordering and persisted receipt rebuilding stay unchanged.

Explicit knowledge_catalog_v1 resources use sourced identity/type/coverage/date
and technical signatures without semantic publication or timing/grain proof.
Finite mathematical mappings and source-established traits remain mandatory;
absence of the marker preserves strict historical validation.
"""

import ast
import copy
import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from wqb.cli import simulation_identity_hash
from wqb.repair_identity import identity_hash_scheme
from wqb.repair_policy import DECAY_LIMIT, TRUNCATION_LIMIT, NEUTRALIZATIONS
from wqb.repair_trace import TARGET_DIRECTIONS
from wqb.benchmark import REPAIRABLE_CHECKS
from wqb.semantic_contracts import evidence_ref_from_dict
from wqb.resource_evidence import knowledge_catalog_admission
from wqb.template_binding import IDENTIFIER, UNKNOWN_METADATA, TemplateBindingError, bind_template


PLANNER_VERSION = 1
MAX_VARIANTS = 8
MAX_RULES = 32
MAX_GRID = 32
SETTING_EFFECTS = {'decay': 'smoothing', 'truncation': 'bounded_weights',
                   'neutralization': 'nuisance_exposure'}
RULE_KEYS = {'rule_id', 'edit', 'effect', 'priority', 'target_metric', 'target_direction',
             'grid', 'requires', 'evidence_refs'}
METRIC_RULE_KEYS = {'trigger', 'basis', 'rationale', 'parameter_direction'}
BASELINE_FAILURES = REPAIRABLE_CHECKS - {'SELF_CORRELATION', 'PROD_CORRELATION'}
MAX_POLICY_TEXT = 1600
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


def _catalog_admission(resources: dict) -> bool:
    """Input: resource dict. Output: bool or ValueError; validate explicit admission and projection agreement."""
    catalog = knowledge_catalog_admission(resources)
    for key in ('evidence_pack', 'evidence_context'):
        context = resources.get(key, {})
        if (isinstance(context, dict)
                and (key == 'evidence_pack' and key in resources or 'resource_admission_policy' in context)
                and knowledge_catalog_admission(context) != catalog):
            raise ValueError('Repair resource admission policy differs from ' + key)
    if catalog and (type(resources.get('resource_contract_version')) is not int
                    or resources['resource_contract_version'] != 2):
        raise ValueError('catalog admission requires resource contract version 2')
    return catalog


def _repair_capture_date_supported(value: object, source_date: str, now: datetime) -> bool:
    """Input: raw timestamp object/ledger date str/current aware datetime. Output: bool; no date inference or renewal."""
    from wqb.knowledge_age_policy import KNOWLEDGE_MAX_AGE_DAYS
    try:
        captured_at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        return False
    return (captured_at.tzinfo is not None and captured_at.date().isoformat() == source_date
            and timedelta(0) <= now - captured_at <= timedelta(days=KNOWLEDGE_MAX_AGE_DAYS))


def _repair_capture_contexts(text: str) -> list[tuple[dict, tuple]]:
    """Input: raw text str. Output: (object dict, ancestor dates tuple) list; retain branch-local capture dates."""
    from wqb.knowledge_compile import _coverage_json_objects
    objects = _coverage_json_objects(text)
    children = set()
    # The shared reader returns roots and flattened descendants; recover each tree once.
    for item in objects:
        pending = list(item.values())
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                children.add(id(value))
            elif isinstance(value, list):
                pending.extend(value)
    pending = [(item, ()) for item in objects if id(item) not in children]
    contexts = []
    while pending:
        value, dates = pending.pop()
        if isinstance(value, dict):
            if 'generated_at' in value:
                dates = dates + (value['generated_at'],)
            contexts.append((value, dates))
            pending.extend((child, dates) for child in value.values() if isinstance(child, (dict, list)))
        elif isinstance(value, list):
            pending.extend((child, dates) for child in value if isinstance(child, (dict, list)))
    return contexts


def _field_source_paths(row: dict, index: dict, texts: dict, scope: dict, catalog: bool) -> list[str]:
    """Input: canonical field/frozen sources/scope and mode. Output: evidence paths; keep legacy paths unchanged."""
    if not catalog:
        return row['source_paths']
    from wqb.resource_evidence import catalog_field_source_paths
    return catalog_field_source_paths(row, index, texts, scope)


def _repair_field_supported(row: dict, texts: dict, index: dict, scope: dict, catalog: bool) -> bool:
    """Input: field/raw/index/scope dicts and catalog bool. Output: bool; preserve technical and measured facts, not semantic proof."""
    from wqb.knowledge_compile import _coverage_field_supported, _coverage_source_fields
    from wqb.knowledge_age_policy import KNOWLEDGE_MAX_AGE_DAYS
    from wqb.template_binding import _known, _scope_matches
    from wqb.workflow_stage_adapters import (_row_has_measured_platform_coverage,
        _row_has_positive_coverage, _row_has_source_date)
    if not catalog:
        return _coverage_field_supported(dict(row, semantic_tags=[]), texts, index, scope,
                                         resource_contract_version=2)
    if (not isinstance(row.get('field_id'), str) or not IDENTIFIER.fullmatch(row['field_id'])
            or 'id' in row and row['id'] != row['field_id']
            or not isinstance(row.get('dataset_id'), str) or not _known(row['dataset_id'])
            or row.get('field_type') not in ('MATRIX', 'VECTOR', 'GROUP') or not _scope_matches(row, scope)
            or not _row_has_measured_platform_coverage(row) or not _row_has_positive_coverage(row)
            or not _row_has_source_date(row) or not _number(row.get('coverage'))):
        return False
    now = datetime.now(timezone.utc)
    age = (now.date() - date.fromisoformat(row['source_updated_at'])).days
    if not 0 <= age <= KNOWLEDGE_MAX_AGE_DAYS:
        return False
    try:
        paths = _field_source_paths(row, index, texts, scope, catalog)
    except (ValueError, KeyError, TypeError):
        return False
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) or p not in texts for p in paths):
        return False
    measured = []
    for path in paths:
        source = index.get(path, {})
        if (source.get('source_type') != 'platform_data_field_capture'
                or source.get('source_family') != 'raw/platform/data_fields'
                or not path.startswith('raw/platform/data_fields/')):
            return False
        if not _repair_capture_date_supported(source.get('captured_at'), row['source_updated_at'], now):
            return False
        for capture, capture_dates in _repair_capture_contexts(texts[path]):
            if not capture_dates:
                continue
            field = capture.get('field', capture)
            if not isinstance(field, dict):
                continue
            dataset = capture.get('data_set', field.get('dataset', {}))
            captured_scope = capture.get('scope', capture)
            if (isinstance(dataset, dict) and isinstance(captured_scope, dict)
                    and field.get('id') == row['field_id'] and dataset.get('id') == row['dataset_id']
                    and _scope_matches(dict(captured_scope, dataset_id=dataset['id']), scope)
                    and any(not _repair_capture_date_supported(stamp, row['source_updated_at'], now)
                            for stamp in capture_dates)):
                return False
        for field, dataset, captured in _coverage_source_fields(texts[path]):
            if (field.get('id') != row['field_id'] or dataset.get('id') != row['dataset_id']
                    or not _scope_matches(dict(captured, dataset_id=dataset['id']), scope)):
                continue
            facts = dict(dataset_id=dataset['id'], field_type=field.get('type'),
                         **{key: captured[key] for key in ('instrument_type', 'region', 'delay', 'universe')
                            if key in captured})
            if (field.get('type') != row['field_type'] or any(key in field and
                    (type(field[key]) is not type(value) or field[key] != value) for key, value in facts.items())):
                return False
            value = field.get('coverage')
            if _number(value) and value > 0:
                measured.append(value)
    return bool(measured) and row['coverage'] == max(measured)


def _repair_operator_supported(row: dict, context: dict, catalog: bool) -> bool:
    """Input: operator/source-context dicts and catalog bool. Output: bool; require explicit technical signature and provenance."""
    from wqb.resource_evidence import catalog_operator_definition, resolve_operator_definition
    if not catalog:
        return resolve_operator_definition(row, context['source_index'], context['source_texts'],
                                           resource_contract_version=2)['status'] == 'supported'
    if not isinstance(row.get('operator'), str) or not IDENTIFIER.fullmatch(row['operator']):
        return False
    try:
        catalog_operator_definition(row, context['source_index'], context['source_texts'])
    except (ValueError, TypeError, KeyError):
        return False
    return True


def _parent_resources(resources: dict, selected: list) -> dict:
    """Input: frozen resource dict/selected field list. Output: compiler resource dict retaining explicit admission."""
    catalog = _catalog_admission(resources)
    result = dict(resource_contract_version=2, field_rows=selected, operator_rows=resources['operator_rows'],
                  evidence_pack=dict(scope=resources['scope']), **resources['evidence_context'])
    if catalog:
        result['resource_admission_policy'] = resources['resource_admission_policy']
        result['evidence_pack']['resource_admission_policy'] = resources['resource_admission_policy']
    return result


def compile_repair_search_policy(resources: dict, project_policy: dict) -> dict:
    """Input: frozen source resources/project finite policy dicts. Output: strict policy dict.

    Source facts authorize prerequisites, not platform parameter domains or
    measured improvements. Parent binding is deferred until Repair acceptance.
    """
    from wqb.resource_evidence import _source, verify_premise
    from wqb.knowledge_compile import _coverage_source_fields
    catalog = _catalog_admission(resources)
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
        _source(ref, index, texts, _technical_catalog=catalog)
        refs[path] = ref
    fields = resources['field_rows']
    if not fields or any(not _repair_field_supported(row, texts, index, scope, catalog) for row in fields):
        if catalog:
            raise ValueError('Repair field facts differ from sourced identity/scope/type/coverage/date')
        raise ValueError('Repair field facts differ from sourced scope/type/timing/grain')
    traits = {}
    field_refs = [refs[p] for p in sorted({p for row in fields
        for p in _field_source_paths(row, index, texts, scope, catalog)})]
    if all(row['field_type'] == 'MATRIX' for row in fields):
        traits['matrix_observation'] = dict(basis='source', value=True, evidence_refs=field_refs)
    frequencies = []
    for row in fields:
        values = [field.get('sampling_frequency_sessions')
            for path in _field_source_paths(row, index, texts, scope, catalog)
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
            supported = _repair_operator_supported(row, resources, catalog)
            if catalog and not supported:
                raise ValueError('Repair operator differs from captured technical signature')
            definition = row['definition']
            parameters = definition['parameters']
            if (not supported or not catalog and definition['description'] != meaning
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
    if catalog:
        policy['resources']['resource_admission_policy'] = resources['resource_admission_policy']
        policy['resources']['evidence_context']['resource_admission_policy'] = resources['resource_admission_policy']
    return policy


def _materialize_parent(policy: dict, parent: dict) -> dict:
    """Input: compiled policy/accepted parent dicts. Output: copied, revalidated parent-bound policy.

    Explicit traits require premises for every actual parent field. Uncovered
    traits and dependent rules are omitted; independent rules remain eligible.
    """
    metric_directed = policy.get('schema_version') == 2
    if not metric_directed and not policy.get('resources', {}).get('producer'):
        return policy
    result = copy.deepcopy(policy)
    resources = result['resources']
    catalog = _catalog_admission(resources)
    if catalog:
        resources['evidence_context']['resource_admission_policy'] = resources['resource_admission_policy']
    tree = ast.parse(parent['expression'], mode='eval')
    functions = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    leaves = sorted({node.id for node in ast.walk(tree)
                     if isinstance(node, ast.Name) and id(node) not in functions})
    if metric_directed and not leaves:
        raise ValueError('accepted parent requires frozen field leaves')
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
            if len(reducers) != 1 or not catalog and not row.get('vector_grain'):
                if catalog:
                    raise ValueError('VECTOR reducer missing or ambiguous')
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
        semantics = ['field:' + row['dataset_id'] + '/' + row['field_id']] if catalog else [row['field_description']]
        slots.append(dict(name=slot, role='signal', required_semantics=semantics,
                          field_type=row['field_type'], required_metadata=[], reduction=reduction))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in functions:
            node.id = tokens[node.id]
    skeleton = ast.unparse(tree)
    replacements = {tokens[name]: '{repair_field_' + str(i) + '}' for i, name in enumerate(leaves)}
    skeleton = re.sub(r'\b__repair_slot_\d+\b', lambda match: replacements[match.group()], skeleton)
    # A resource-pack fact cannot authorize unrelated fields in the accepted parent.
    if metric_directed:
        _validate_v2_sources(resources)
        from wqb.resource_evidence import _source
        context = resources['evidence_context']
        refs = [ref for rule in result['rules'] for ref in rule['evidence_refs']]
        refs.extend(ref for fact in result['traits'].values()
                    if isinstance(fact, dict) for ref in fact.get('evidence_refs', []))
        for ref in refs:
            _source(ref, context['source_index'], context['source_texts'], _technical_catalog=catalog)
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        for name in calls:
            rows = [row for row in resources['operator_rows'] if row.get('operator') == name]
            if len(rows) != 1 or not _repair_operator_supported(rows[0], context, catalog):
                raise ValueError('accepted parent operator differs from frozen source definition')
        scope = resources['scope']
        if (any(type(scope.get(key)) is not type(parent['settings'].get(key))
                or scope.get(key) != parent['settings'].get(key) for key in ('region', 'delay', 'universe'))
                or scope.get('instrument_type') != parent['settings'].get('instrumentType')):
            raise ValueError('frozen scope differs from accepted parent settings')
        result['traits'] = _parent_traits(result['traits'], selected, resources)
    else:
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
        result = compile_repair_search_policy(_parent_resources(resources, selected), project)
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


def _validate_v2_sources(resources: dict) -> None:
    """Input: v2 frozen resources dict. Output: None or ValueError; verify exact source bytes/fields."""
    from wqb.resource_evidence import _source
    catalog = _catalog_admission(resources)
    if resources.get('resource_contract_version') != 2:
        raise ValueError('metric-directed Repair requires v2 field sources')
    context, scope = resources['evidence_context'], resources['scope']
    fields = resources['field_rows']
    for path in sorted({path for row in fields for path in _field_source_paths(row,
            context['source_index'], context['source_texts'], scope, catalog)}):
        source = context['source_index'][path]
        _source(dict(source_path=path, sha256=source['content_hash'], kind='documented',
                     capture_date=source['captured_at'][:10], experiment_refs=[]),
                context['source_index'], context['source_texts'], _technical_catalog=catalog)
    if not fields or any(not _repair_field_supported(row, context['source_texts'], context['source_index'],
            scope, catalog) for row in fields):
        if catalog:
            raise ValueError('Repair fields differ from frozen source identity/scope/type/coverage/date')
        raise ValueError('Repair fields differ from frozen source scope/type/timing/grain')


def _parent_traits(traits: dict, selected: list, resources: dict) -> dict:
    """Input: declared traits/actual parent rows/resources. Output: only source-proven parent-local traits."""
    from wqb.knowledge_compile import _coverage_source_fields
    context, scope = resources['evidence_context'], resources['scope']
    compiled = compile_repair_search_policy(_parent_resources(resources, selected),
        dict(compile_version=1, rules=[], traits={}))
    established = compiled['traits']
    if all(row['field_type'] in ('MATRIX', 'VECTOR') for row in selected):
        established['numeric_observation'] = dict(value=True)
    for name, field_fact in COMPILED_TRAIT_FACTS.items():
        values = []
        for row in selected:
            facts = [field.get(field_fact) for path in _field_source_paths(row,
                context['source_index'], context['source_texts'], scope, _catalog_admission(resources))
                for field, dataset, captured in _coverage_source_fields(context['source_texts'][path])
                if field.get('id') == row['field_id'] and dataset.get('id') == row['dataset_id']
                and all(type(captured.get(k)) is type(scope[k]) and captured.get(k) == scope[k]
                        for k in ('instrument_type', 'region', 'delay', 'universe'))]
            if not facts or any(value is None or type(value) is not type(facts[0])
                                or value != facts[0] for value in facts):
                break
            values.append(facts[0])
        if len(values) == len(selected) and all(type(v) is type(values[0]) and v == values[0] for v in values):
            established[name] = dict(value=values[0])
    result = {}
    for name, fact in traits.items():
        proof = established.get(name)
        if (not isinstance(fact, dict) or not proof or fact.get('basis') != 'source'
                or type(fact.get('value')) is not type(proof['value']) or fact['value'] != proof['value']
                or _trait_reason(traits, name, fact['value'])):
            continue
        paths = {ref['source_path'] for ref in fact['evidence_refs']}
        if all(paths.intersection(_field_source_paths(row, context['source_index'],
                context['source_texts'], scope, _catalog_admission(resources))) for row in selected):
            result[name] = copy.deepcopy(fact)
    # Parent-local frequency is mandatory even when a heterogeneous batch omitted it.
    if 'sampling_frequency_sessions' in established:
        result['sampling_frequency_sessions'] = copy.deepcopy(established['sampling_frequency_sessions'])
    return result


def _digest(value: object) -> str:
    """Input: JSON-compatible object. Output: SHA256 str binding immutable planner inputs."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _number(value: object) -> bool:
    """Input: object. Output: bool; reject booleans and nonfinite numeric measurements."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


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
            or policy['schema_version'] not in (1, 2)
            or set(policy) - ({'schema_version', 'rules', 'traits', 'stop', 'resources'}
                              | ({'rulebook_id'} if policy['schema_version'] == 2 else set()))
            or type(policy.get('stop', False)) is not bool
            or not isinstance(policy.get('traits'), dict)):
        raise ValueError('Unsupported policy shape/version')
    metric_directed = policy['schema_version'] == 2
    if isinstance(policy.get('resources'), dict):
        _catalog_admission(policy['resources'])
    if metric_directed and 'rulebook_id' in policy and not _bounded_text(policy['rulebook_id']):
        raise ValueError('Expected bounded nonempty rulebook_id')
    rules = policy.get('rules')
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise ValueError('Expected bounded rules list')
    clean, identifiers = copy.deepcopy(policy), set()
    for rule in clean['rules']:
        if not isinstance(rule, dict) or set(rule) != (RULE_KEYS
                | (METRIC_RULE_KEYS if metric_directed else set())
                | ({'transform'} if rule.get('edit') == 'transform' else set())):
            raise ValueError('Unknown or missing rule properties')
        if metric_directed:
            _metric_rule(rule)
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


def _bounded_text(value: object) -> bool:
    """Input: object. Output: bool; require nonblank bounded policy explanation/identity strings."""
    return isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_POLICY_TEXT


def _metric_rule(rule: dict) -> None:
    """Input: v2 rule dict. Output: None or ValueError; validate hypothesis and exact finite trigger."""
    trigger = rule['trigger']
    if (rule['basis'] != 'project_hypothesis' or not _bounded_text(rule['rationale'])
            or rule['parameter_direction'] not in ('increase', 'decrease', 'any')
            or not isinstance(trigger, dict) or set(trigger) != {'checks', 'metric', 'operator', 'threshold'}):
        raise ValueError('Invalid metric-directed hypothesis/trigger')
    checks = trigger['checks']
    if (not isinstance(checks, list) or len(checks) > len(BASELINE_FAILURES)
            or any(not isinstance(name, str) or name not in BASELINE_FAILURES for name in checks)
            or len(set(checks)) != len(checks)):
        raise ValueError('Trigger checks must be known distinct baseline failures')
    metric = trigger['metric']
    if metric is None:
        valid = trigger['operator'] is None and trigger['threshold'] is None and bool(checks)
    else:
        valid = (isinstance(metric, str) and metric in TARGET_DIRECTIONS
                 and trigger['operator'] in ('gt', 'lt') and _number(trigger['threshold']))
    if not valid:
        raise ValueError('Trigger needs named failures or a complete finite metric predicate')
    trigger['checks'] = sorted(checks)


def _failure_evidence(parent: dict) -> set:
    """Input: observed parent dict. Output: completed failures set or ValueError; pending never fails."""
    if parent.get('status') != 'CHECKED':
        raise ValueError('Failure evidence requires a checked parent')
    groups = []
    for key, expected in (('failed', 'FAIL'), ('pending', 'PENDING')):
        items = parent.get(key)
        if not isinstance(items, list):
            raise ValueError('Expected explicit failed/pending lists')
        names = set()
        for item in items:
            name = item.get('name') if isinstance(item, dict) else item
            if (not isinstance(name, str) or name not in REPAIRABLE_CHECKS
                    or isinstance(item, dict) and item.get('result') != expected):
                raise ValueError('Malformed or unknown ' + key + ' check evidence')
            names.add(name)
        groups.append(names)
    if groups[0] & groups[1]:
        raise ValueError('Checks cannot be both failed and pending')
    return groups[0]


def _transform_source_reason(rule: dict, resources: dict) -> str:
    """Input: v2 rule/resources dicts. Output: reason str; retain only the existing sourced invariants."""
    transform = rule['transform']
    rows = [row for row in resources['operator_rows'] if row.get('operator') == transform['operator']]
    if len(rows) != 1:
        return 'unsupported_transform'
    row = rows[0]
    context = resources['evidence_context']
    try:
        catalog = _catalog_admission(resources)
        verified = _repair_operator_supported(row, context, catalog)
        definition = row['definition']
        parameters = definition['parameters']
        supported = any(transform['operator'] == name and rule['effect'] == effect
            and transform['parameter_kind'] == kind and (catalog or definition['description'] == meaning)
            and definition['input_types'] == ['MATRIX'] and definition['output_type'] == 'MATRIX'
            and len(parameters) == 2 and [p['type'] for p in parameters] == ['MATRIX', scalar]
            and all(p['required'] and 'default' not in p for p in parameters)
            and transform['parameter'] == parameters[1]['name']
            and (kind != 'window' or transform['frequency_trait'] == 'sampling_frequency_sessions')
            for name, effect, kind, scalar, meaning in COMPILED_INVARIANTS.values())
        return '' if supported and verified else 'unsupported_transform'
    except (ValueError, TypeError, KeyError):
        return 'unsupported_transform'


def _trigger_evidence(rule: dict, parent: dict, failures: set) -> dict:
    """Input: rule/observed parent dicts and actual failures set. Output: auditable activation/gap dict."""
    trigger = rule['trigger']
    checks = sorted(failures.intersection(trigger['checks']))
    value = (parent.get('metrics') or {}).get(trigger['metric']) if isinstance(parent.get('metrics'), dict) else None
    measured = _number(value)
    active, gap = False, 0.
    if trigger['metric'] is not None and measured:
        threshold = trigger['threshold']
        active = value > threshold if trigger['operator'] == 'gt' else value < threshold
        if active:
            gap = abs(value / (abs(threshold) or 1) - threshold / (abs(threshold) or 1))
            if not _number(gap):
                raise ValueError('Nonfinite normalized metric gap')
    return dict(trigger=copy.deepcopy(trigger), failed_checks=checks,
                observed_value=value if measured else None, metric_predicate=active,
                normalized_gap=gap, activated=bool(checks) or active)


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
    context = resources.get('evidence_context')
    if _catalog_admission(resources):
        context = dict(context or {}, resource_admission_policy=resources['resource_admission_policy'])
    kwargs = dict(resource_contract_version=resources.get('resource_contract_version', 1),
                  evidence_context=context)
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
    except (ValueError, TypeError, OverflowError) as exc:
        return result | dict(stop_reason='invalid_policy', reason=str(exc))
    metric_directed = frozen['schema_version'] == 2
    if metric_directed:
        result['planner_version'] = 2
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
    triggered, eligible, duplicate_candidates = 0, 0, []
    prerequisites_missing = False
    triggers = {}
    if metric_directed:
        try:
            failures = _failure_evidence(parent)
            triggers = {rule['rule_id']: _trigger_evidence(rule, parent, failures) for rule in frozen['rules']}
        except (ValueError, TypeError, OverflowError) as exc:
            return result | dict(stop_reason='invalid_check_evidence', reason=str(exc))
        result['trigger_evidence'] = copy.deepcopy(triggers)
        if not frozen['rules']:
            return result | dict(status='exhausted', stop_reason='no_rules_configured', remaining_candidates=0)
        if not any(evidence['activated'] for evidence in triggers.values()):
            result['skipped'] = [dict(rule_id=rule['rule_id'], reason='trigger_not_observed',
                trigger_evidence=triggers[rule['rule_id']]) for rule in frozen['rules']]
            return result | dict(status='exhausted', stop_reason='no_triggered_rules', remaining_candidates=0)
        try:
            frozen = _materialize_parent(frozen, parent)
        except (ValueError, TypeError, KeyError, AttributeError, SyntaxError) as exc:
            result['skipped'] = [dict(rule_id=rule['rule_id'], reason='parent_prerequisites', detail=str(exc))
                                 for rule in frozen['rules']]
            return result | dict(status='exhausted', stop_reason='missing_prerequisites', remaining_candidates=0)
        frozen['rules'].sort(key=lambda rule: (-triggers[rule['rule_id']]['normalized_gap'],
            -len(triggers[rule['rule_id']]['failed_checks']), rule['priority'], rule['rule_id']))
    for rule in frozen['rules']:
        if metric_directed:
            evidence = triggers[rule['rule_id']]
            if not evidence['activated']:
                result['skipped'].append(dict(rule_id=rule['rule_id'], reason='trigger_not_observed',
                                              trigger_evidence=evidence))
                continue
            triggered += 1
        reason = ''
        if not _sources(rule['evidence_refs'], 'documented'):
            reason = 'rule_source_missing'
        for name, expected in sorted(rule['requires'].items()):
            reason = reason or _trait_reason(frozen['traits'], name, expected)
        metrics = parent.get('metrics')
        if not isinstance(metrics, dict) or not _number(metrics.get(rule['target_metric'])):
            reason = reason or 'target_unmeasured'
        if metric_directed and rule['edit'] != 'transform':
            current = parent['settings'].get(rule['edit'])
            if (rule['edit'] in ('decay', 'truncation') and not _number(current)
                    or rule['edit'] == 'neutralization' and current not in NEUTRALIZATIONS
                    or rule['edit'] == 'neutralization' and rule['parameter_direction'] != 'any'):
                reason = reason or 'parent_parameter_unmeasured'
            if rule['edit'] == 'neutralization' and rule['requires'].get('nuisance_exposure') is not True:
                reason = reason or 'nuisance_exposure_not_established'
        elif metric_directed:
            reason = reason or _transform_source_reason(rule, frozen['resources'])
        if reason:
            prerequisites_missing = True
            result['skipped'].append(dict(rule_id=rule['rule_id'], reason=reason))
            continue
        eligible += 1
        for value in rule['grid']:
            expression, settings = parent['expression'], copy.deepcopy(parent['settings'])
            binding = None
            reason = _frequency_reason(rule, frozen['traits'], value)
            if metric_directed and rule['edit'] == 'decay':
                cadence = frozen['traits'].get('sampling_frequency_sessions', {})
                frequency = cadence.get('value')
                if type(frequency) is int and cadence.get('units') == 'sessions' and value < frequency:
                    reason = reason or 'frequency_constraint'
            if metric_directed and rule['parameter_direction'] != 'any':
                if rule['edit'] == 'transform':
                    reason = reason or 'parent_parameter_unmeasured'
                else:
                    current = parent['settings'][rule['edit']]
                    directed = value > current if rule['parameter_direction'] == 'increase' else value < current
                    if not directed:
                        reason = reason or 'parameter_direction'
            if reason:
                if reason not in ('parameter_direction', 'frequency_constraint'):
                    prerequisites_missing = True
                result['skipped'].append(dict(rule_id=rule['rule_id'], value=value, reason=reason))
                continue
            if rule['edit'] == 'transform':
                try:
                    binding = _typed_transform(parent, rule, value, frozen.get('resources'))
                    expression = binding['bound_expression']
                except (TemplateBindingError, ValueError, TypeError, SyntaxError) as exc:
                    prerequisites_missing = True
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
                if metric_directed:
                    duplicate_candidates.append((identity, rule, value))
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
            if metric_directed:
                decision.update(basis=rule['basis'], rationale=rule['rationale'],
                    parameter_direction=rule['parameter_direction'], trigger_evidence=copy.deepcopy(evidence))
                if 'rulebook_id' in frozen:
                    decision['rulebook_id'] = frozen['rulebook_id']
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
    if metric_directed:
        reason = ('no_triggered_rules' if not triggered else 'missing_prerequisites' if prerequisites_missing or not eligible
                  else 'no_novel_candidates')
        if duplicate_candidates and not prerequisites_missing:
            reason = ('tested_without_improvement' if _tested_without_improvement(
                parent, history, duplicate_candidates) else 'search_space_exhausted')
        return result | dict(status='exhausted', stop_reason=reason)
    return result | dict(status='exhausted', stop_reason='search_space_exhausted')


def _tested_without_improvement(parent: dict, history: list, candidates: list) -> bool:
    """Input: parent/history and duplicate (identity, rule, value) tuples. Output: bool; require checked rejections."""
    from wqb.seed_policy import compare_versions, DEFAULT_SEED_POLICY
    for identity, rule, value in candidates:
        rows = [row for row in history if row.get('expression_hash') == identity]
        if not rows or any(row != rows[0] for row in rows[1:]):
            return False
        child = rows[0]
        try:
            _failure_evidence(child)
            comparison = compare_versions(parent, child, dict(target_metric=rule['target_metric'],
                target_direction=rule['target_direction'], edit=rule['edit'], value=value,
                turnover_max=DEFAULT_SEED_POLICY['turnover_max']))
        except (ValueError, TypeError, KeyError):
            return False
        if comparison['outcome'] != 'rejected':
            return False
    return True


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
    resources = policy.get('resources', {})
    if _catalog_admission(resources) and not knowledge_catalog_admission(context):
        raise ValueError('Repair resource admission differs from owning frozen context')
    if policy['schema_version'] == 2:
        resources = policy.get('resources', {})
        _validate_v2_sources(resources)
        for key in ('source_index', 'source_texts'):
            if any(context[key].get(path) != value
                   for path, value in resources['evidence_context'][key].items()):
                raise ValueError('metric-directed Repair sources differ from frozen context')
    producer = policy.get('resources', {}).get('producer')
    if producer:
        resources = policy['resources']
        frozen_context = resources['evidence_context']
        for key in ('source_index', 'source_texts'):
            if any(context[key].get(path) != value for path, value in frozen_context[key].items()):
                raise ValueError('compiled Repair sources differ from frozen context')
        rebuilt = compile_repair_search_policy(_parent_resources(resources, resources['field_rows']),
                                               producer['project_policy'])
        if rebuilt != policy:
            raise ValueError('compiled Repair producer policy changed')
    if policy.get('resources'):
        resources = policy['resources']
        for key, snapshot_key in (('field_rows', 'data_ledger_rows'), ('operator_rows', 'operator_rows')):
            if any(row not in snapshot.get(snapshot_key, []) for row in resources.get(key, [])):
                raise ValueError('Repair transform resources differ from owning frozen snapshot')
        from wqb.hypothesis_template_compiler import _operator
        for rule in policy['rules']:
            if rule['edit'] == 'transform' and not producer and not _catalog_admission(resources):
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
