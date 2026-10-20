"""Pure proposal contract and Task3 compiler entry; no IO or lifecycle authority.

Public API: design_output_schema() -> dict and
validate_hypothesis_design(answer: dict, evidence_pack: dict,
                           policy: SemanticPolicy) -> dict; failures raise ValueError.
The returned envelope is a fresh normalized copy with validator-derived design_id
on each design. It is NOT model output and must not be fed back as model input.

Exact model envelope is {summary: str, designs: [design, ...]}. The schema below
enumerates every mandatory design member; unknown keys are rejected recursively.
Each design is one (trigger_id, mechanism_family, condition_id) branch. trigger_id
is an indexed source path, not a guessed field ID. Seven card-compatible sentences
are data_meaning, economic_rationale, prediction, conditions.description,
alternative_explanation, operator_rationale and falsification, respectively.

Feature JSON is {kind: 'role', role: slot_name} or {kind: 'level', input: leaf},
{kind: 'change', input: leaf, horizon: int}, {kind: 'relative', input: leaf,
group_role: leaf, comparison: 'group_rank'|'group_demean'}. Only leaves may be
arguments: maximum depth is two, counting the root. Slot semantics are exact bounded
phrases from allowed_role_semantics, and requirements
selected from the pack, not field IDs. No operator signature is asserted here.

conditions is {mode: observable|interpretive|unidentifiable, description: sentence,
observable_roles: [slot_name]}; only observable may have proxy roles (and must).
Proxy declarations are NOT executable predicates or filters. experiment_plan is
{baseline: feature, treatments: [{feature: feature, rationale: sentence}],
controls: [sentence], rejection_criteria: sentence, inconclusive_criteria: sentence}.
The baseline equals feature_plan, at most one treatment changes the feature only;
controls declare fixed scope/non-treatment settings. Task3 owns settings/binding
verification, including rejecting infeasible proxies or unsupported signatures.

Minimal evidence_pack fixture (see tests/test_hypothesis_design.py for full JSON):
{source_index: {path: existing SourceIndexRow dict}, scope: nonempty scalar dict,
 allowed_role_semantics: [exact_sourced_semantic_phrase],
 allowed_operator_intents: ['level','change','group_rank','group_demean'],
 source_texts?: {path: full UTF-8 source text},
 histories?: [{statement: sentence, evidence_refs: [existing EvidenceRef dict]}]}.
Sources use existing path/content_hash/captured_at/source_type/source_family, not
a parallel evidence grade. EvidenceRef uses source_path/sha256/capture_date/kind/
experiment_refs. Existing provenance checks constrain documented/measured kinds.
Source text, when supplied, is complete, never truncated. Markdown with frontmatter
uses the existing LF-normalized BODY content_hash and header/index agreement;
other sources use the full UTF-8 bytes. An indexed file_sha256, if present, checks
the full bytes separately. Short prose is capped at 7000 characters; full source
texts may exceed that within the unchanged 1MB total JSON pack byte cap.
Histories are bounded upstream-verified statements, never model-created results;
measured histories also require their verbatim statement in supplied source_texts.
Generated empirical-claim markers require an exact history sentence with measured
grade references and a matching statement in the hash-verified source body; mere
membership in histories cannot promote hypothesis evidence to measured evidence.
Digits and quarter labels alone are not empirical-claim markers.
Prospective criteria beginning 'Reject if', 'Inconclusive if' or 'Inconclusive when'
may contain numeric metric thresholds; those criteria are not measured outcomes.
Every measured design reference must already occur in a supplied history.

IMPORTANT: indexed metadata alone does not verify actual source bytes, role meaning,
measurement validity or completeness. The caller MUST build this pack from verified
upstream evidence (Task1/5). This parser checks internal consistency, not semantic
truth of arbitrary prose; its conservative empirical-marker guard is not an NLP
proof. Natural prose remains data, never an executable feature. Structural slots
admit no measured output fields, executable formula or lifecycle status.
Identity binds normalized design, referenced index metadata, scope, allowed intents/
semantics, used histories and COMPILER_VERSION; batch summary/order are irrelevant.
Task3 must bump COMPILER_VERSION when lowering semantics change.
"""

from copy import deepcopy
import hashlib
import json
import math
import re

from wqb.semantic_contracts import (SemanticPolicy, CARD_FIELDS, IDENTIFIER,
    hypothesis_card_from_dict, input_slot_from_dict, validate_semantic_record)
from wqb.semantic_compilation import _check_schema
from wqb.knowledge_contracts import parse_markdown_front_matter
from wqb.resource_evidence import PROJECT_WINDOW_POLICY, resource_contract_version
from wqb.mechanism_evidence import MAX_CONTEXT as MAX_MECHANISM_CONTEXT


COMPILER_VERSION = 'hypothesis-design-v4'
MAX_JSON_BYTES = 1_000_000
DESIGN_WORKER_CONTRACT = dict(version=3, instructions=(
    'Every prose value, including summary, each explanation, criterion and control, must be exactly one sentence, '
    'with no newline or sentence-separating punctuation followed by more prose. '
    'trigger_id must equal a referenced indexed source_path, not an invented identifier; '
    'mechanism_family and condition_id must be ASCII identifiers matching [A-Za-z_][A-Za-z0-9_]*, '
    'such as adverse_information_diffusion and gradual_pricing, not prose or sentences. '
    'include an evidence_ref with kind=hypothesis for economic inference and never claim measured evidence without histories. '
    'required_semantics must be a subset of evidence_pack.allowed_role_semantics, without extra descriptive phrases. '
    'required_metadata must name only schema-permitted metadata actually present on the selected frozen field_rows; '
    'for version2 a verified timing_contract can replace available_at, so do not require an absent timestamp or units. '
    'feature_plan must equal experiment_plan.baseline exactly; choose Level as the baseline and one distinct Change '
    'treatment when comparing Level/Change, not Change in feature_plan with Level in baseline. '
    'Unknown source facts stay explicitly unknown; an indexed user-authorized polarity assumption may support '
    'a falsifiable directional prediction and interpretive condition, but remains hypothesis evidence, '
    'never a documented encoding fact or measured conclusion. Without such evidence unknown polarity or '
    'unidentifiable conditions must remain explicit and cannot produce oriented drafts. '
    'mechanism_context contains selected-only scoped derived observations, not causal or statistical proof, '
    'not measured EvidenceRefs and not lifecycle or candidate approval; omissions are not evidence of completeness. '
    'Read the complete hashed supporting_ref records, including failed and inconclusive cases; never edit factual records. '
    'An exhausted idea requires an explicit new experiment with a changed falsifiable mechanism or condition, '
    'not a repeated claim or a parameter-only relabeling. Empty context supplies no empirical support. '
))
MAX_JSON_DEPTH = 24
MAX_TEXT_LENGTH = 7000
MAX_HORIZON = PROJECT_WINDOW_POLICY['maximum']
DEFAULT_HORIZONS = tuple(PROJECT_WINDOW_POLICY['default_horizons'])
MAX_HISTORIES = 32
MAX_SOURCES = 128
MAX_ROLES = 16
MAX_DESIGNS = 128
METADATA_KEYS = ('available_at', 'units', 'vector_grain', 'dataset_id', 'region',
                 'universe', 'delay', 'description', 'semantic_tags', 'field_type')
INTENTS = ('level', 'change', 'group_rank', 'group_demean')
EMPIRICAL = re.compile(r'\b(?:measured|backtest\w*|sharpe|fitness|correlation|'
                       r'proven|proved|outperform\w*|empirically|significant|'
                       r'realized|observed returns|achieved|demonstrated)\b|'
                       r'实测|回测|相关性|夏普|已证明|显著', re.IGNORECASE)


def normalize_horizon_defaults(values: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    """Input: nonempty list/tuple of int horizons. Output: tuple[int, ...]; reject invalid bounded defaults.

    These are research choices, not a platform domain, whitelist or Scout grid.
    """
    if (not isinstance(values, (list, tuple)) or not values
            or any(type(value) is not int or not 1 <= value <= MAX_HORIZON for value in values)):
        raise ValueError('horizon defaults require positive integers within MAX_HORIZON')
    return tuple(values)


def _object(properties: dict) -> dict:
    """Input: property schemas dict. Output: strict all-required object schema."""
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def _array(items: dict) -> dict:
    """Input: item schema dict. Output: array schema for the existing validator."""
    return dict(type='array', items=items)


def _string(values: tuple | None = None) -> dict:
    """Input: optional enum tuple. Output: JSON string schema."""
    return dict(type='string', **({'enum': list(values)} if values is not None else {}))


def _feature_schema() -> dict:
    """Input: none. Output: finite depth-two feature union dict, no recursion."""
    leaf = _object(dict(kind=_string(('role',)), role=_string()))
    return dict(anyOf=[leaf,
        _object(dict(kind=_string(('level',)), input=leaf)),
        _object(dict(kind=_string(('change',)), input=leaf,
                     horizon=dict(type='integer', minimum=1, maximum=MAX_HORIZON))),
        _object(dict(kind=_string(('relative',)), input=leaf, group_role=leaf,
                     comparison=_string(('group_rank', 'group_demean'))))])


def design_output_schema(resource_version: int | None = None) -> dict:
    """Input: producer int or None (syntax-only union). Output: strict schema, never trust.

    The checkpoint transport checks syntax without producer context. Workers and
    the semantic validator always pass the verified version explicitly.
    """
    if resource_version is None:
        resource_version = 2
    resource_contract_version({'resource_contract_version': resource_version})
    text = _string()
    ref = _object(dict(source_path=text, sha256=text, capture_date=text,
                       kind=_string(('documented', 'hypothesis', 'measured')),
                       experiment_refs=_array(text)))
    feature = _feature_schema()
    role = _object(dict(name=text, required_semantics=_array(text),
                        field_type=_string(('MATRIX', 'VECTOR', 'GROUP')),
                        required_metadata=_array(_string(METADATA_KEYS + (('timing_contract',) if resource_version == 2 else ())))))
    design = _object(dict(design_version=dict(type='integer', enum=[1]),
        trigger_id=text, mechanism_family=text, condition_id=text, data_meaning=text,
        economic_rationale=text, prediction=text,
        prediction_direction=_string(('positive', 'negative', 'unknown')),
        conditions=_object(dict(mode=_string(('observable', 'interpretive', 'unidentifiable')),
                                description=text, observable_roles=_array(text))),
        alternative_explanation=text, falsification=text, operator_rationale=text,
        field_roles=_array(role), feature_plan=feature,
        experiment_plan=_object(dict(baseline=feature,
            treatments=_array(_object(dict(feature=feature, rationale=text))),
            controls=_array(text), rejection_criteria=text, inconclusive_criteria=text)),
        evidence_refs=_array(ref)))
    return _object(dict(summary=text, designs=_array(design)))


def _json_copy(value: object, depth: int = 0, source_metadata: bool = False, full_source: bool = False) -> object:
    """Input: JSON value/depth int/metadata/source bools. Output: bounded copy preserving sources."""
    if depth > MAX_JSON_DEPTH:
        raise ValueError('excessive JSON nesting')
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ValueError('JSON keys must be strings')
        return {key: _json_copy(item, depth + 1, source_metadata,
                full_source or (source_metadata and depth == 0 and key == 'source_texts'))
                for key, item in value.items()}
    if isinstance(value, list):
        return [_json_copy(item, depth + 1, source_metadata, full_source) for item in value]
    if type(value) is str:
        limit = MAX_JSON_BYTES if full_source else MAX_TEXT_LENGTH
        if (not source_metadata and not value.strip()) or len(value) > limit or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
            raise ValueError('expected bounded nonblank text')
        return value if source_metadata else value.strip()
    if value is None or type(value) is bool:
        return value
    if type(value) in (float, int):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite or abs(value) > 1e308:
            raise ValueError('nonfinite or overflow number')
        return value
    raise ValueError('expected JSON-compatible value')


def _canonical(value: object) -> str:
    """Input: JSON value. Output: stable canonical JSON str for comparisons/digests."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _strings(values: object, nonempty: bool = True) -> list[str]:
    """Input: object and nonempty bool. Output: sorted unique text list or ValueError."""
    if not isinstance(values, list) or (nonempty and not values) or any(type(v) is not str or not v.strip() for v in values):
        raise ValueError('expected text list')
    if len(values) != len(set(values)):
        raise ValueError('duplicate list entries')
    return sorted(values)


def _refs(refs: list, pack: dict) -> list[dict]:
    """Input: EvidenceRef dict list/pack dict. Output: normalized metadata-bound refs."""
    if not refs:
        raise ValueError('evidence references are required')
    issues = validate_semantic_record({'evidence_refs': refs}, pack['source_index'])
    if issues:
        raise ValueError('invalid evidence: ' + str(issues))
    result = deepcopy(refs)
    for ref in result:
        ref['sha256'] = ref['sha256'].lower()
        ref['experiment_refs'] = _strings(ref['experiment_refs'], nonempty=False)
        if ref['kind'] != 'measured' and ref['experiment_refs']:
            raise ValueError('non-measured reference cannot assert experiment evidence')
    keys = [_canonical(ref) for ref in result]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate evidence references')
    return sorted(result, key=_canonical)


def _pack(evidence_pack: dict) -> dict:
    """Input: upstream-verified pack dict. Output: copied consistency-checked pack dict."""
    required = {'source_index', 'scope', 'allowed_role_semantics', 'allowed_operator_intents'}
    if not isinstance(evidence_pack, dict) or not required <= evidence_pack.keys() or evidence_pack.keys() - required - {'source_texts', 'histories', 'resource_contract_version', 'mechanism_context'}:
        raise ValueError('unknown or missing evidence pack fields')
    resource_contract_version(evidence_pack)
    pack = _json_copy(evidence_pack, source_metadata=True)
    if len(_canonical(pack).encode()) > MAX_JSON_BYTES:
        raise ValueError('oversized evidence pack')
    if not isinstance(pack['scope'], dict) or not pack['scope'] or any(isinstance(v, (dict, list)) or v is None or (isinstance(v, str) and not v.strip()) for v in pack['scope'].values()):
        raise ValueError('scope requires explicit scalar facts')
    index = pack['source_index']
    if not isinstance(index, dict) or not index or len(index) > MAX_SOURCES:
        raise ValueError('expected bounded source index')
    if any(not isinstance(row, dict) or not isinstance(row.get('content_hash'), str) for row in index.values()):
        raise ValueError('malformed source index row')
    pack['allowed_role_semantics'] = _strings(pack['allowed_role_semantics'])
    pack['allowed_operator_intents'] = _strings(pack['allowed_operator_intents'])
    if set(pack['allowed_operator_intents']) - set(INTENTS):
        raise ValueError('unsupported allowed operator intent')
    texts = pack.setdefault('source_texts', {})
    if not isinstance(texts, dict):
        raise ValueError('source_texts must map paths to full source texts')
    # Match _material's Markdown body hash without filesystem IO.
    for path, text in evidence_pack.get('source_texts', {}).items():
        if type(text) is not str or path not in index:
            raise ValueError('source_texts requires indexed full UTF-8 text')
        row = index[path]
        content = text
        if path.lower().endswith('.md'):
            metadata, body = parse_markdown_front_matter(text.replace('\r\n', '\n'))
            if metadata:
                content = body
                for key in ('content_hash', 'captured_at', 'source_type', 'source_family'):
                    if key in metadata and str(metadata[key]) != row.get(key):
                        raise ValueError('frontmatter/index mismatch: ' + key)
        if hashlib.sha256(content.encode('utf-8')).hexdigest() != row['content_hash'].lower():
            raise ValueError('source content does not match indexed hash')
        if 'file_sha256' in row and (not isinstance(row['file_sha256'], str) or
                hashlib.sha256(text.encode('utf-8')).hexdigest() != row['file_sha256'].lower()):
            raise ValueError('source full bytes do not match indexed file_sha256')
        texts[path] = content
    context = pack.get('mechanism_context', [])
    if not isinstance(context, list) or len(context) > MAX_MECHANISM_CONTEXT:
        raise ValueError('expected bounded mechanism context')
    for item in context:
        if (not isinstance(item, dict) or set(item) != {'group_id', 'label', 'observed_differences', 'limitations', 'supporting_ref'}
                or not isinstance(item['group_id'], str) or not item['group_id']
                or item['label'] not in {'inconclusive', 'operational_failure', 'supports_prediction_in_scope', 'contradicts_prediction_in_scope'}
                or not isinstance(item['observed_differences'], dict) or not isinstance(item['limitations'], list)):
            raise ValueError('invalid mechanism observation context')
        ref = item['supporting_ref']
        if (not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}
                or not isinstance(ref['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', ref['sha256'])
                or ref['path'] != 'materials/mechanisms/' + ref['sha256'] + '.json'):
            raise ValueError('invalid mechanism supporting reference')
    histories = pack.setdefault('histories', [])
    if not isinstance(histories, list) or len(histories) > MAX_HISTORIES:
        raise ValueError('expected bounded histories')
    for history in histories:
        _check_schema(_object(dict(statement=_string(), evidence_refs=_array(design_output_schema()['properties']['designs']['items']['properties']['evidence_refs']['items']))), history)
        history['evidence_refs'] = _refs(history['evidence_refs'], pack)
        _sentence(history['statement'], [history], history['evidence_refs'])
        if any(ref['kind'] == 'measured' for ref in history['evidence_refs']) and not any(
                history['statement'] in texts.get(ref['source_path'], '') for ref in history['evidence_refs'] if ref['kind'] == 'measured'):
            raise ValueError('measured history requires supplied source statement')
    return pack


def _sentence(text: str, histories: list[dict], refs: list[dict], criterion: bool = False) -> None:
    """Input: prose str/histories/refs, criterion bool. Output: None; guard sentences/claims."""
    hypothesis_card_from_dict(dict.fromkeys(CARD_FIELDS, text))
    prospective = criterion and re.match(r'^(?:Reject if|Inconclusive if|Inconclusive when)\b', text)
    if EMPIRICAL.search(text) and not prospective and not any(text == h['statement'] and
            any(ref['kind'] == 'measured' for ref in h['evidence_refs']) and
            all(ref in refs for ref in h['evidence_refs']) for h in histories):
        raise ValueError('empirical claim absent from supplied evidence histories')


def _feature(feature: dict, roles: dict, pack: dict) -> None:
    """Input: schema-checked feature/roles/pack dicts. Output: None; validate role intents."""
    kind = feature['kind']
    leaf = feature if kind == 'role' else feature['input']
    if leaf['role'] not in roles or roles[leaf['role']]['field_type'] == 'GROUP':
        raise ValueError('feature needs a declared value role')
    intent = 'level' if kind == 'role' else feature.get('comparison', kind)
    if intent not in pack['allowed_operator_intents']:
        raise ValueError('feature intent is not supplied by evidence pack')
    if kind == 'change' and not 1 <= feature['horizon'] <= MAX_HORIZON:
        raise ValueError('horizon is out of bounds')
    if kind == 'relative':
        name = feature['group_role']['role']
        if name not in roles or roles[name]['field_type'] != 'GROUP':
            raise ValueError('relative requires a declared GROUP role')


def _feature_identity(feature: dict, roles: dict, omit_horizon: bool = False) -> dict:
    """Input: feature/roles dicts, omit_horizon bool. Output: alias-free semantic intent dict."""
    result = deepcopy(feature)
    if result['kind'] == 'level':
        result = result['input']
    if result['kind'] == 'role':
        result['role'] = {k: v for k, v in roles[result['role']].items() if k != 'name'}
    else:
        result['input'] = _feature_identity(result['input'], roles)
        if result['kind'] == 'relative':
            result['group_role'] = _feature_identity(result['group_role'], roles)
        if omit_horizon:
            result.pop('horizon', None)
    return result


def compile_hypothesis_design(design: dict, resources: dict, scope: dict) -> dict:
    """Input: normalized design/resources/scope dicts. Output: deterministic proposal result.

    Exact resource/experiment contracts live in hypothesis_template_compiler's
    module docstring. Compilation grants no review, measurement or publication.
    """
    from wqb.hypothesis_template_compiler import compile_design
    return compile_design(design, resources, scope)


def _branch_signature(design: dict, roles: dict) -> str:
    """Input: normalized design dict. Output: structured conditional distinction str."""
    treatments = [_feature_identity(t['feature'], roles, omit_horizon=True)
                  for t in design['experiment_plan']['treatments']]
    requirements = sorted([{k: v for k, v in role.items() if k != 'name'}
                           for role in roles.values()], key=_canonical)
    return _canonical(dict(prediction_direction=design['prediction_direction'],
                           field_roles=requirements, treatments=treatments))


def validate_hypothesis_design(answer: dict, evidence_pack: dict, policy: SemanticPolicy) -> dict:
    """Input: model answer/verified pack dicts, SemanticPolicy. Output: normalized design envelope.

    Raise ValueError on unsupported structure, source inconsistency or padded
    branches. This function has no IO or mutation of either input and grants no
    review, measurement, executable binding or platform authority.
    """
    if not isinstance(policy, SemanticPolicy) or any(type(v) is not int or v < 1 for v in (policy.max_mechanisms, policy.max_conditions_per_mechanism)):
        raise ValueError('expected positive SemanticPolicy limits')
    result = _json_copy(answer)
    if len(_canonical(result).encode()) > MAX_JSON_BYTES:
        raise ValueError('oversized design output')
    pack = _pack(evidence_pack)
    version = resource_contract_version(pack)
    _check_schema(design_output_schema(version), result)
    _sentence(result['summary'], [], [])
    if not result['designs'] or len(result['designs']) > MAX_DESIGNS:
        raise ValueError('expected a nonempty bounded design batch')
    branches = {}
    mechanisms = {}
    for design in result['designs']:
        trigger = design['trigger_id']
        for key in ('mechanism_family', 'condition_id'):
            if not IDENTIFIER.fullmatch(design[key]):
                raise ValueError('expected semantic branch identifier')
        refs = _refs(design['evidence_refs'], pack)
        design['evidence_refs'] = refs
        history_refs = [ref for h in pack['histories'] for ref in h['evidence_refs']]
        if any(ref['kind'] == 'measured' and ref not in history_refs for ref in refs):
            raise ValueError('measured reference absent from verified pack histories')
        if trigger not in {ref['source_path'] for ref in refs}:
            raise ValueError('trigger must be a referenced indexed source path')
        if not any(ref['kind'] in {'hypothesis', 'measured'} for ref in refs):
            raise ValueError('economic inference requires hypothesis evidence')
        condition = design['conditions']
        roles = {}
        if not 1 <= len(design['field_roles']) <= MAX_ROLES:
            raise ValueError('expected bounded field roles')
        for role in design['field_roles']:
            input_slot_from_dict(dict(role, role=role['name']))
            role['required_semantics'] = _strings(role['required_semantics'])
            role['required_metadata'] = _strings(role['required_metadata'])
            if set(role['required_semantics']) - set(pack['allowed_role_semantics']):
                raise ValueError('role semantics absent from supplied evidence')
            if (not ({'available_at'} | ({'timing_contract'} if version == 2 else set())) & set(role['required_metadata']) or (role['field_type'] == 'VECTOR' and 'vector_grain' not in role['required_metadata'])):
                raise ValueError('explicit availability/vector grain requirement missing')
            if role['name'] in roles:
                raise ValueError('duplicate role names')
            roles[role['name']] = role
        design['field_roles'] = sorted(roles.values(), key=lambda r: r['name'])
        condition['observable_roles'] = _strings(condition['observable_roles'], nonempty=False)
        if set(condition['observable_roles']) - roles.keys() or bool(condition['observable_roles']) != (condition['mode'] == 'observable'):
            raise ValueError('condition mode and observable proxy roles disagree')
        exp = design['experiment_plan']
        _feature(design['feature_plan'], roles, pack)
        _feature(exp['baseline'], roles, pack)
        if exp['baseline'] != design['feature_plan'] or len(exp['treatments']) > 1:
            raise ValueError('baseline mismatch or excessive treatments')
        exp['controls'] = _strings(exp['controls'])
        features = [design['feature_plan'], exp['baseline']]
        for treatment in exp['treatments']:
            _feature(treatment['feature'], roles, pack)
            features.append(treatment['feature'])
            if _feature_identity(treatment['feature'], roles) == _feature_identity(exp['baseline'], roles):
                raise ValueError('treatment duplicates baseline')
        used_roles = set(condition['observable_roles'])
        for feature in features:
            used_roles.add(feature['role'] if feature['kind'] == 'role' else feature['input']['role'])
            if feature['kind'] == 'relative':
                used_roles.add(feature['group_role']['role'])
        if used_roles != roles.keys():
            raise ValueError('unused role requirements cannot pad a design')
        prose = [design[key] for key in ('data_meaning', 'economic_rationale', 'prediction',
                 'alternative_explanation', 'operator_rationale', 'falsification')]
        prose += [condition['description']]
        prose += exp['controls'] + [t['rationale'] for t in exp['treatments']]
        for text in prose:
            _sentence(text, pack['histories'], refs)
        for text in (exp['rejection_criteria'], exp['inconclusive_criteria']):
            _sentence(text, pack['histories'], refs, criterion=True)
            prose.append(text)
        family = design['mechanism_family']
        mechanisms.setdefault(trigger, set()).add(family)
        group = branches.setdefault((trigger, family), {})
        signature = _branch_signature(design, roles)
        if design['condition_id'] in group or signature in group.values():
            raise ValueError('duplicate or narrative/window-only conditional branch')
        group[design['condition_id']] = signature
        if len(mechanisms[trigger]) > policy.max_mechanisms or len(group) > policy.max_conditions_per_mechanism:
            raise ValueError('SemanticPolicy mechanism/condition maximum exceeded')
        paths = {ref['source_path'] for ref in refs}
        paths.update(path for ref in refs for path in ref['experiment_refs'])
        sources = {path: deepcopy(pack['source_index'][path]) for path in sorted(paths)}
        for source in sources.values():
            source['content_hash'] = source['content_hash'].lower()
        used_histories = sorted([h for h in pack['histories'] if h['statement'] in prose], key=_canonical)
        identity = dict(design=design, compiler_version=COMPILER_VERSION, scope=pack['scope'],
                        sources=sources, histories=used_histories,
                        allowed_role_semantics=pack['allowed_role_semantics'],
                        allowed_operator_intents=pack['allowed_operator_intents'])
        if version == 2:
            identity['resource_contract_version'] = version
        design['design_id'] = 'design_' + hashlib.sha256(_canonical(identity).encode('utf-8')).hexdigest()
    return result
