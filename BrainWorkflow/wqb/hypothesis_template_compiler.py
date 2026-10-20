"""Task3 pure lowering; Task5 caller contract (no files, network or worker here).

resources has keys field_rows, operator_rows (lists of existing snapshot
dicts), source_index (path -> SourceIndexRow dict), source_texts (path -> COMPLETE
UTF-8 text), settings and evidence_pack, plus optional producer-owned
resource_contract_version (absent=1, exact int 1/2). Envelope and pack must agree.
No verified boolean is accepted. Every indexed source must have text. Extracts
require the IO producer's original receipt verification before model/cache use;
this pure compiler cannot grant filesystem verification. Task2 _pack owns Markdown normalized
body/header/index and optional file_sha256 checks. Source rows must have matching
canonical paths; field facts/tags/required metadata and operator definitions are
checked with Task1 pure coverage helpers, never inferred from IDs or prose.
Field rows require canonical field_id (id-only rows reject); an optional id alias
must equal field_id. Every bound identity must resolve to exactly one scoped row
with verified source_paths, never an empty lookup silently skipped by an audit.
Binding checks the original snapshot first to retain ambiguity detection, then
uses Task1 helpers to filter unverified, unused producer tags and binds again.
Both binding audits must agree exactly. Required semantic_tags metadata remains
an exact source fact; only verified descriptions/tags may satisfy role semantics.
evidence_pack is the original Task2 input (same scope, index, allowed semantics/
intents and histories). Its source_texts, if supplied, must agree with the outer
texts. It is required to revalidate both content and derived design_id. Task5
must retain this pack, not reconstruct authorization from model output.

settings is the complete existing build_settings output, with EXACT keys:
instrumentType, region, universe, delay, decay, neutralization, truncation,
pasteurization, unitHandling, nanHandling, language, visualization. Strings are
explicit nonblank; language=FASTEXPR; delay/decay nonnegative ints (not bool);
truncation finite numeric in [0,1]; visualization bool; ON/OFF toggles and
VERIFY/IGNORE unitHandling. No defaults/grids/coercion. region/universe/delay and
instrumentType must match scope.region/universe/delay/instrument_type. scope is
the Task2 scalar scope including timezone-aware as_of; optional dataset_id and
other scope facts remain fixed and identity-bound. Resource JSON is capped by
Task2's byte/depth limits; source count is capped by Task2.

Successful result: status='compiled', drafts=[TemplateRecord-compatible dicts],
experiment={experiment_id, design_id, compiler_version, compilation_digest,
 baseline_template_id, arms, changed_dimension:'feature', controls,
 rejection_criteria, inconclusive_criteria, conditions,
 condition_filter_applied:False, prediction_direction, orientation:1|-1,
 context_bindings, context_bindings_digest}.
arms=[{arm_id:'baseline'|'treatment', template_id, feature, rationale, settings,
 scope, binding:{bound_expression,bindings,operator_provenance,operator_call_count}}].
One baseline, zero/one treatment; identical complete settings/scope and shared
role bindings; only declared feature differs. Each arm declares only consumed
slots. Grouping auxiliaries may occur in only one arm. context_bindings freezes
the UNION of all arm roles as {role: existing binding audit plus source_paths and
documented evidence_refs}; context_bindings_digest is SHA256 of its canonical
JSON. All declared roles must be consumed across the experiment. Receipts are
returned JSON, not published state; Task5 must preserve/check these digests.
Negation orients BOTH arms for negative direction;
unknown direction rejects. Observable conditions are proxy-only, never filters,
and their roles must be actual inputs in every arm. Unidentifiable conditions,
VECTOR (schema has no reduction intent), unused roles and unsupported meanings
reject. Interpretive conditions remain interpretive in the attachment.

Operators require exact documented signatures without optional hidden arguments.
Version 1 accepted meanings are the sentences in OPERATOR_CONTRACTS (case,
whitespace and terminal period insensitive); unfamiliar descriptions reject,
even with familiar operator IDs. Version 2 requires the finite source-backed
resolver's operation rule and actual meaning premises, preserving raw wording.
No NLP meaning inference or silent substitution.
All lowering uses role leaves, typed calls and optional unary minus, then existing
parse_kernel/bind_template. Dedup is bound AST + settings, NOT math equivalence.
IDs bind compiler version, normalized design, all supplied evidence/resource
facts, complete settings/scope and emitted arm construction; not candidate IDs.

Failure result: status='rejected', drafts=[], experiment=None,
rejections=[{code,path,message}], compilation_digest=None. Stable first failure
is retained with original validator/binder diagnostics; no partial experiments.
No publication, reviewed/measured promotion, scheduling or simulation authority.
"""

import ast
from copy import deepcopy
import hashlib

from wqb import hypothesis_design as contract
from wqb.resource_evidence import (resource_contract_version, resolve_operator_definition,
                                   OPERATOR_RULES, OPERATOR_MEANING_SUFFIXES)
from wqb.knowledge_compile import _coverage_field_supported, _coverage_operator_supported
from wqb.semantic_contracts import (SemanticPolicy, _indexed_source, _path,
    input_slot_from_dict, operator_definition_from_dict, validate_semantic_record)
from wqb.template_binding import (bind_template, parse_kernel, TemplateBindingError,
    _scope_matches, _select_field)
from wqb.template_library import (TemplateRecord, template_record_from_dict,
    template_record_to_dict)


SETTINGS_KEYS = {'instrumentType', 'region', 'universe', 'delay', 'decay',
    'neutralization', 'truncation', 'pasteurization', 'unitHandling', 'nanHandling',
    'language', 'visualization'}
OPERATOR_CONTRACTS = {
    'ts_delta': (['MATRIX'], ['MATRIX', 'INTEGER'],
        {'returns x - ts_delay(x, d)', 'returns the difference between x and its value d days ago'}),
    'group_rank': (['MATRIX', 'GROUP'], ['MATRIX', 'GROUP'],
        {'ranks x within each group', 'ranks each element within its group'}),
    'group_neutralize': (['MATRIX', 'GROUP'], ['MATRIX', 'GROUP'],
        {'subtracts the group mean from x', 'subtracts the mean of each group from x'}),
}


class CompilationError(ValueError):
    """Explicit proposal rejection preserving a code/path and underlying diagnostic."""

    def __init__(self, code: str, path: str, message: str):
        """Input: diagnostic strings. Output: exception carrying JSON-safe rejection."""
        super().__init__(message)
        self.diagnostic = dict(code=code, path=path, message=message)


def _fail(code: str, path: str, message: str) -> None:
    """Input: diagnostic strings. Output: never; reject atomically with explicit reason."""
    raise CompilationError(code, path, message)


def _digest(value: object) -> str:
    """Input: bounded JSON object. Output: canonical SHA256 str, not candidate identity."""
    return hashlib.sha256(contract._canonical(value).encode('utf-8')).hexdigest()


def _settings(settings: dict, scope: dict) -> None:
    """Input: complete settings/scope dicts. Output: None; reject defaults/coercion/grids."""
    if not isinstance(settings, dict) or set(settings) != SETTINGS_KEYS:
        _fail('invalid_settings', 'settings', 'expected exact complete build_settings keys')
    for key in sorted(SETTINGS_KEYS - {'delay', 'decay', 'truncation', 'visualization'}):
        if type(settings[key]) is not str or not settings[key].strip():
            _fail('invalid_settings', 'settings.' + key, 'expected explicit text setting')
    if any(type(settings[k]) is not int or settings[k] < 0 for k in ('delay', 'decay')):
        _fail('invalid_settings', 'settings', 'delay/decay require nonnegative integers')
    if (type(settings['truncation']) not in (float, int) or not 0 <= settings['truncation'] <= 1
            or type(settings['visualization']) is not bool or settings['language'] != 'FASTEXPR'
            or any(settings[k] not in ('ON', 'OFF') for k in ('pasteurization', 'nanHandling'))
            or settings['unitHandling'] not in ('VERIFY', 'IGNORE')):
        _fail('invalid_settings', 'settings', 'invalid explicit platform setting value')
    for setting, key in [('region', 'region'), ('universe', 'universe'),
                         ('delay', 'delay'), ('instrumentType', 'instrument_type')]:
        if type(settings[setting]) is not type(scope.get(key)) or settings[setting] != scope.get(key):
            _fail('invalid_settings', 'settings.' + setting, 'setting must match explicit scope.' + key)


def _resources(resources: dict, scope: dict) -> tuple[dict, dict]:
    """Input: resources/scope dicts. Output: copied resources/verified Task2 pack dicts."""
    keys = {'field_rows', 'operator_rows', 'source_index', 'source_texts', 'settings', 'evidence_pack'}
    if not isinstance(resources, dict) or set(resources) - {'resource_contract_version'} != keys:
        _fail('invalid_resources', 'resources', 'expected exact resource contract keys')
    data = {key: contract._json_copy(value, source_metadata=True,
            full_source=key in {'source_texts', 'evidence_pack'})
            for key, value in resources.items()}
    if len(contract._canonical(data).encode()) > contract.MAX_JSON_BYTES:
        _fail('invalid_resources', 'resources', 'oversized compiler resources')
    if any(not isinstance(data[k], list) or any(not isinstance(r, dict) for r in data[k])
           for k in ('field_rows', 'operator_rows')):
        _fail('invalid_resources', 'resources', 'expected snapshot object lists')
    for index, row in enumerate(data['field_rows']):
        if (not isinstance(row.get('field_id'), str) or not contract.IDENTIFIER.fullmatch(row['field_id'])
                or ('id' in row and row['id'] != row['field_id'])):
            _fail('invalid_resources', f'field_rows[{index}].field_id',
                  'canonical field_id required; id-only or conflicting aliases are not accepted')
    original = data['evidence_pack']
    if not isinstance(original, dict):
        _fail('invalid_resources', 'evidence_pack', 'expected original Task2 pack')
    if resource_contract_version(data) != resource_contract_version(original):
        _fail('invalid_resources', 'resource_contract_version', 'resource envelope and evidence pack disagree')
    if original.get('scope') != scope:
        _fail('incompatible_scope', 'scope', 'scope differs from validated design scope')
    if original.get('source_index') != data['source_index']:
        _fail('invalid_resources', 'source_index', 'outer and design source indexes disagree')
    texts = data['source_texts']
    if not isinstance(texts, dict) or set(texts) != set(data['source_index']):
        _fail('invalid_resources', 'source_texts', 'complete indexed source texts required')
    for path, text in original.get('source_texts', {}).items():
        if texts.get(path) != text:
            _fail('invalid_resources', 'source_texts.' + path, 'design and resource source bytes disagree')
    pack_input = dict(original, source_texts=texts)
    pack = contract._pack(pack_input)
    pack['source_texts'] = texts
    for path in pack['source_index']:
        _path(path)
        _indexed_source(path, pack['source_index'])
    _settings(data['settings'], scope)
    return data, pack


def _lower(feature: dict, orientation: int) -> tuple[str, set[str], str | None]:
    """Input: validated feature dict/sign int. Output: restricted skeleton/used roles/operator."""
    kind = feature['kind']
    role = feature['role'] if kind == 'role' else feature['input']['role']
    roles, operator = {role}, None
    node = ast.Name(id='__binding_slot_' + role, ctx=ast.Load())
    args = [node]
    if kind == 'change':
        operator = 'ts_delta'
        args.append(ast.Constant(value=feature['horizon']))
    elif kind == 'relative':
        operator = 'group_rank' if feature['comparison'] == 'group_rank' else 'group_neutralize'
        group = feature['group_role']['role']
        roles.add(group)
        args.append(ast.Name(id='__binding_slot_' + group, ctx=ast.Load()))
    if operator:
        node = ast.Call(func=ast.Name(id=operator, ctx=ast.Load()), args=args, keywords=[])
    if orientation == -1:
        node = ast.UnaryOp(op=ast.USub(), operand=node)
    skeleton = ast.unparse(ast.fix_missing_locations(node))
    for role in sorted(roles, key=len, reverse=True):
        skeleton = skeleton.replace('__binding_slot_' + role, '{' + role + '}')
    parse_kernel(skeleton, roles)
    return skeleton, roles, operator


def _operator(name: str, rows: list[dict], pack: dict) -> None:
    """Input: required operator name/snapshot/verified pack. Output: None; verify facts and intent."""
    matches = [row for row in rows if row.get('operator') == name]
    try:
        if len(matches) != 1:
            raise ValueError('missing or ambiguous documented definition')
        row = matches[0]
        issues = validate_semantic_record(row, pack['source_index'])
        if issues:
            raise ValueError(str(issues))
        definition = operator_definition_from_dict(row['definition'])
        version = resource_contract_version(pack)
        if not _coverage_operator_supported(row, pack['source_texts'], source_index=pack['source_index'],
                                            resource_contract_version=version):
            raise ValueError('definition differs from exact sourced operator facts')
        inputs, types, meanings = OPERATOR_CONTRACTS[name]
        meaning = ' '.join(definition['description'].lower().strip().rstrip('.').split())
        if (definition['input_types'] != inputs or definition['output_type'] != 'MATRIX'
                or [p['type'] for p in definition['parameters']] != types
                or any(not p['required'] or 'default' in p for p in definition['parameters'])
                or (version == 1 and meaning not in meanings)):
            raise ValueError('unsupported documented signature or meaning for ' + name)
        if version == 2:
            receipt = resolve_operator_definition(row, pack['source_index'], pack['source_texts'],
                                                 resource_contract_version=2)
            rule_meaning = OPERATOR_RULES[name]['meaning']
            direct_meanings = meanings | {' '.join(value.lower().strip().rstrip('.').split())
                for value in (rule_meaning, rule_meaning + OPERATOR_MEANING_SUFFIXES[name])}
            if (receipt['status'] != 'supported'
                    or (receipt['value'].get('kind') == 'source_backed_derivation'
                        and (receipt['value'].get('rule_id'), receipt['value'].get('rule_version')) not in
                        ({(name, 1), ('ts_delta_project_window', 2)} if name == 'ts_delta' else {(name, 1)}))
                    or (receipt['value'].get('kind') == 'direct_documentation' and meaning not in direct_meanings)):
                raise ValueError('feature requires source-backed operation meaning: ' + str(receipt['rejections']))
    except (ValueError, KeyError, TypeError) as exc:
        _fail('missing_operator_definition', 'operator_rows.' + name, str(exc))


def _selected_row(chosen: dict, data: dict, scope: dict) -> dict:
    """Input: bound identity/resources/scope dicts. Output: exactly one canonical scoped row."""
    selected = [row for row in data['field_rows'] if _scope_matches(row, scope)
        and (row['dataset_id'], row['field_id']) == (chosen['dataset_id'], chosen['field_id'])]
    if len(selected) != 1:
        _fail('ambiguous_field' if selected else 'missing_field_semantics', 'binding',
              f'bound identity must resolve to exactly one canonical source row ({len(selected)})')
    return selected[0]


def _binding(template: dict, data: dict, pack: dict, scope: dict) -> dict:
    """Input: template/resources/verified pack/scope dicts. Output: source-checked binding dict."""
    version = resource_contract_version(data)
    options = dict(resource_contract_version=version, evidence_context=dict(
        source_index=pack['source_index'], source_texts=pack['source_texts'])) if version == 2 else {}
    try:
        binding = bind_template(template, data['field_rows'], data['operator_rows'], scope, **options)
    except TemplateBindingError as exc:
        message = str(exc)
        code = 'missing_field_semantics'
        if 'ambiguous' in message and '(0)' not in message:
            code = 'ambiguous_field'
        elif 'availability' in message or 'available_at' in message or 'as_of' in message:
            code = 'lookahead_risk'
        elif 'units' in message:
            code = 'invalid_units'
        elif '(0)' in message:
            for slot in template['input_slots']:
                try:
                    _select_field(input_slot_from_dict(slot), data['field_rows'],
                                  {'as_of': scope.get('as_of')})
                except TemplateBindingError:
                    continue
                if message.startswith(slot['name'] + ':'):
                    code = 'incompatible_scope'
        _fail(code, 'binding', message)
    verified_rows = []
    for slot in template['input_slots']:
        chosen = binding['bindings'][slot['name']]
        row = _selected_row(chosen, data, scope)
        clean = dict(row, semantic_tags=[])
        facts = row if 'semantic_tags' in slot['required_metadata'] else clean
        if not _coverage_field_supported(facts, pack['source_texts'], pack['source_index'],
                                         scope, slot['required_metadata'], resource_contract_version=version):
            _fail('missing_field_semantics', 'input_slots.' + slot['name'],
                  'selected field description/type/tags/required metadata lack exact source support')
        tags = row.get('semantic_tags', [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            _fail('missing_field_semantics', 'input_slots.' + slot['name'], 'expected snapshot text tags')
        metadata = [key for key in slot['required_metadata'] if key != 'semantic_tags']
        clean['semantic_tags'] = [tag for tag in tags if _coverage_field_supported(
            dict(clean, semantic_tags=[tag]), pack['source_texts'], pack['source_index'], scope, metadata,
            resource_contract_version=version)]
        verified_rows.append(clean)
    # Multiple roles may consume the same canonical field; keep one snapshot row.
    unique_rows = {(row['dataset_id'], row['field_id']): row for row in verified_rows}
    try:
        verified_binding = bind_template(template, list(unique_rows.values()), data['operator_rows'], scope, **options)
    except TemplateBindingError as exc:
        _fail('missing_field_semantics', 'binding', 'source-verified rebind failed: ' + str(exc))
    if verified_binding != binding:
        _fail('missing_field_semantics', 'binding', 'source-verified rebind differs from original snapshot binding')
    if version == 2:
        for item in verified_binding['operator_provenance']:
            row = next(row for row in data['operator_rows'] if row['operator'] == item['operator'])
            resolution = resolve_operator_definition(row, pack['source_index'], pack['source_texts'],
                                                     resource_contract_version=2)
            if resolution['status'] != 'supported':
                _fail('missing_operator_definition', 'binding', str(resolution['rejections']))
            item['definition_receipt'] = resolution['value']
            if 'definition_basis' in row:
                item['definition_basis'] = deepcopy(row['definition_basis'])
    return verified_binding


def _evidence(design: dict, binding: dict, data: dict, pack: dict, scope: dict) -> list[dict]:
    """Input: design/binding/resources/pack/scope dicts. Output: all consumed provenance refs."""
    refs = deepcopy(design['evidence_refs'])
    paths = {path for chosen in binding['bindings'].values()
             for path in _selected_row(chosen, data, scope)['source_paths']}
    paths.update(source['source_path'] for chosen in binding['bindings'].values()
                 for source in chosen.get('timing_receipt', {}).get('sources', []))
    for path in sorted(paths):
        source = pack['source_index'][path]
        refs.append(dict(source_path=path, sha256=source['content_hash'].lower(),
            capture_date=source['captured_at'][:10], kind='documented', experiment_refs=[]))
    for operator in binding['operator_provenance']:
        refs.extend(deepcopy(operator['evidence_refs']))
    for ref in refs:
        ref['sha256'] = ref['sha256'].lower()
    unique = {contract._canonical(ref): ref for ref in refs}
    return contract._refs(list(unique.values()), pack)


def compile_design(design: dict, resources: dict, scope: dict) -> dict:
    """Input: normalized individual design/resources/scope dicts. Output: atomic compiler result."""
    phase = 'invalid_resources'
    try:
        data, pack = _resources(resources, scope)
        phase = 'invalid_design'
        raw = contract._json_copy(design)
        supplied_id = raw.pop('design_id', None)
        normalized = contract.validate_hypothesis_design(
            dict(summary='A compiler input proposal.', designs=[raw]),
            dict(data['evidence_pack'], source_texts=data['source_texts']), SemanticPolicy())['designs'][0]
        if normalized != design or supplied_id != normalized['design_id']:
            _fail('invalid_design', 'design_id', 'normalized content or derived identity differs')
        direction = normalized['prediction_direction']
        if direction == 'unknown' or normalized['conditions']['mode'] == 'unidentifiable':
            _fail('unsupported_feature', 'conditions/prediction_direction',
                  'unknown direction or unidentifiable condition cannot produce oriented trading drafts')
        if any(r['field_type'] == 'VECTOR' for r in normalized['field_roles']):
            _fail('unsupported_feature', 'field_roles', 'VECTOR has no structured reduction intent in design v1')
        orientation = -1 if direction == 'negative' else 1
        exp = normalized['experiment_plan']
        features = [dict(feature=exp['baseline'], rationale=normalized['operator_rationale'])] + exp['treatments']
        drafts, arms, fingerprints, union_bindings = [], [], set(), {}
        context = dict(design=normalized, resources=data, scope=scope, compiler_version=contract.COMPILER_VERSION)
        digest = _digest(context)
        for index, construction in enumerate(features):
            skeleton, used, operator = _lower(construction['feature'], orientation)
            if not set(normalized['conditions']['observable_roles']) <= used:
                _fail('unsupported_feature', 'conditions.observable_roles',
                      'condition proxies must be consumed in every arm; proxies are not predicates')
            if operator:
                _operator(operator, data['operator_rows'], pack)
            slots = [dict(r, role=r['name'], reduction=None) for r in normalized['field_roles'] if r['name'] in used]
            card = dict(data_meaning=normalized['data_meaning'], mechanism=normalized['economic_rationale'],
                conditions=normalized['conditions']['description'], alternative=normalized['alternative_explanation'],
                prediction=normalized['prediction'], operator_roles=normalized['operator_rationale'],
                falsification=normalized['falsification'])
            template = template_record_to_dict(TemplateRecord(
                template_id='template_' + _digest(dict(context=digest, skeleton=skeleton)),
                hypothesis=normalized['economic_rationale'], skeleton=skeleton,
                required_field_types=sorted({r['field_type'] for r in slots}),
                compatible_semantic_tags=sorted({s for r in slots for s in r['required_semantics']}),
                operator_tags=[operator] if operator else [], status='scout_only', correlation_risk='unknown',
                repair_levers=[], source_paths=sorted(pack['source_index']),
                compatible_regions=[scope['region']], compatible_delays=[scope['delay']],
                compatible_universes=[scope['universe']], intended_direction=direction,
                template_family=normalized['mechanism_family'], semantic_version=2, semantic_status='unreviewed',
                hypothesis_id=normalized['design_id'], hypothesis_version=normalized['design_version'], binding_version=2))
            template.update(input_slots=slots, hypothesis_card=card, evidence_refs=deepcopy(normalized['evidence_refs']),
                operator_roles=[dict(operator=operator, role=construction['feature']['kind'],
                    purpose=normalized['operator_rationale'])] if operator else [])
            template = template_record_to_dict(template_record_from_dict(template))
            binding = _binding(template, data, pack, scope)
            template['evidence_refs'] = _evidence(normalized, binding, data, pack, scope)
            template['source_paths'] = sorted({ref['source_path'] for ref in template['evidence_refs']}
                | {path for ref in template['evidence_refs'] for path in ref['experiment_refs']})
            key = contract._canonical(dict(ast=ast.dump(ast.parse(binding['bound_expression'], mode='eval')),
                                           settings=data['settings']))
            if key in fingerprints:
                _fail('duplicate_template', 'experiment_plan', 'bound AST/settings duplicates another arm')
            fingerprints.add(key)
            for name, chosen in binding['bindings'].items():
                if name in union_bindings and chosen != union_bindings[name]:
                    _fail('unsupported_feature', 'experiment_plan', 'treatment changes shared field binding, not only feature')
                union_bindings[name] = deepcopy(chosen)
            drafts.append(template)
            arms.append(dict(arm_id='baseline' if index == 0 else 'treatment', template_id=template['template_id'],
                **deepcopy(construction), settings=deepcopy(data['settings']), scope=deepcopy(scope), binding=binding))
        if set(union_bindings) != {r['name'] for r in normalized['field_roles']}:
            _fail('unsupported_feature', 'experiment_plan', 'all declared roles must be consumed across the experiment')
        context_bindings = {}
        for name, chosen in sorted(union_bindings.items()):
            row = _selected_row(chosen, data, scope)
            refs = _evidence(dict(evidence_refs=[]), dict(bindings={name: chosen}, operator_provenance=[]),
                             data, pack, scope)
            context_bindings[name] = dict(deepcopy(chosen), source_paths=sorted(row['source_paths']), evidence_refs=refs)
        experiment = dict(experiment_id='experiment_' + digest, design_id=normalized['design_id'],
            compiler_version=contract.COMPILER_VERSION, compilation_digest=digest,
            baseline_template_id=drafts[0]['template_id'], arms=arms, changed_dimension='feature',
            controls=deepcopy(exp['controls']), rejection_criteria=exp['rejection_criteria'],
            inconclusive_criteria=exp['inconclusive_criteria'], conditions=deepcopy(normalized['conditions']),
            condition_filter_applied=False, prediction_direction=direction, orientation=orientation,
            context_bindings=context_bindings, context_bindings_digest=_digest(context_bindings))
        if resource_contract_version(data) == 2:
            experiment['resource_contract_version'] = 2
        return dict(status='compiled', drafts=drafts, experiment=experiment, rejections=[], compilation_digest=digest)
    except CompilationError as exc:
        diagnostic = exc.diagnostic
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        diagnostic = dict(code=phase, path='$', message=str(exc))
    return dict(status='rejected', drafts=[], experiment=None, rejections=[diagnostic], compilation_digest=None)
