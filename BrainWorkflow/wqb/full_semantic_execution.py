"""Authenticated K4 explanation execution; no platform, publication or ledger updates.

Executor protocol: executor(job=loaded_job, output_schema=schema, deadline=unix_time)
returns the complete {summary, targets} answer. Adapters must enforce the supplied
deadline on transport: a synchronous Python callback cannot be forcibly preempted.
Reservations precede callbacks; an uncertain or interrupted attempt is never replayed.
"""

from copy import deepcopy
import math
from pathlib import Path
import re
import secrets
import time

from wqb.full_semantic_compile import (
    BRIEF, OUTPUT_CONTRACT, _bytes, _contracts, _digest, _freeze, _hash,
    _json, _parse, _rows,
)
from wqb.knowledge_paths import machine_resource_path
from wqb.lockfile import json_lock_transition_guard
from wqb.semantic_compilation import (
    MAX_MATERIAL_BYTES, MAX_OUTPUT_BYTES, MAX_PACK_BYTES, MAX_SELECTED_SOURCES,
    MAX_SOURCE_BYTES, _material, _safe, _write, semantic_output_schema,
)
from wqb.semantic_contracts import (
    CARD_FIELDS, evidence_ref_from_dict, hypothesis_card_from_dict,
    operator_definition_from_dict, semantic_fields_from_dict, validate_semantic_record,
)


EXECUTION_VERSION = 'full-semantic-execution-1'
LOCK_TIMEOUT_SECONDS = 1.0
LOCK_SLEEP_SECONDS = 0.02
HASH = re.compile(r'[a-f0-9]{64}\Z')
FIELD_FACTS = {'units', 'vector_grain', 'available_at', 'timing_contract'}
TERMINAL_STATES = {'running', 'reserved', 'outcome_unknown', 'rejected', 'failed', 'cancelled', 'deadline_exceeded'}


def _root(path: Path) -> Path:
    """Input: vault Path. Output: resolved Path; reject linked ancestors before normalization."""
    path = Path(path).absolute()
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or hasattr(ancestor, 'is_junction') and ancestor.is_junction():
            raise ValueError('symlink/junction execution root denied')
    return path.resolve(strict=True)


def _read(path: Path, limit: int = MAX_OUTPUT_BYTES, *, canonical: bool = False):
    """Input: safe Path/int limit/canonical flag. Output: parsed JSON, bounded and optionally canonical."""
    if path.stat().st_size > limit:
        raise ValueError('execution artifact exceeds read bound')
    raw = path.read_bytes()
    value = _json(raw.decode('utf-8'))
    if canonical and _bytes(value) != raw:
        raise ValueError('immutable artifact is not canonical bytes')
    return value


def _ref(root: Path, ref: dict, limit: int, base: str) -> bytes:
    """Input: vault/ref/limit/expected directory. Output: authenticated complete referenced bytes."""
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'} or not HASH.fullmatch(str(ref.get('sha256', ''))):
        raise ValueError('invalid immutable reference')
    if not isinstance(ref['path'], str) or not ref['path'].startswith(base + '/'):
        raise ValueError('reference outside bound job')
    path = _safe(root, ref['path'])
    if path.stat().st_size > limit:
        raise ValueError('referenced material exceeds bound')
    raw = path.read_bytes()
    if _hash(raw) != ref['sha256']:
        raise ValueError('immutable reference digest mismatch')
    return raw


def load_bound_explanation_job(job_dir: Path) -> dict:
    """Input: canonical machine/semantic_jobs/<hex> Path. Output: authenticated worker job dict.

    Returned keys: manifest,input,brief,job_dir,root,source_index,source_texts.
    Only source bytes are validated here, not freshness or compiler eligibility.
    Every selected material must reconstruct completely from current indexed raw.
    """
    job_dir = _root(job_dir)
    if not HASH.fullmatch(job_dir.name) or job_dir.parent.name != 'semantic_jobs' or job_dir.parent.parent.name != 'machine':
        raise ValueError('explanation job must use canonical content-addressed directory')
    root = _root(job_dir.parents[2])
    base = job_dir.relative_to(root).as_posix()
    manifest_path = _safe(root, base + '/run_manifest.json')
    manifest = _read(manifest_path, canonical=True)
    if (manifest.get('kind') != 'full_semantic_explanation' or manifest.get('schema_version') != 1
            or manifest.get('root') != str(root) or manifest.get('content_key') != job_dir.name):
        raise ValueError('job kind/root/key mismatch')
    contracts = manifest['contracts']
    expected = _contracts(dict(max_targets_per_job=contracts['bounds']['max_targets_per_job'],
                               rules_version=contracts.get('rules_version', '')))
    if contracts != expected:
        raise ValueError('job contracts differ from current code/schema/bounds')
    limit = contracts['bounds']['max_targets_per_job']
    if type(limit) is not int or not 1 <= limit <= MAX_SELECTED_SOURCES:
        raise ValueError('invalid target batch bound')
    input_raw = _ref(root, manifest['input_ref'], MAX_PACK_BYTES, base)
    value = _json(input_raw.decode('utf-8'))
    if _bytes(value) != input_raw:
        raise ValueError('input bytes are not canonical')
    expected_key = _digest(dict(input_sha256=_hash(input_raw), contracts=contracts, root=str(root)))
    if expected_key != job_dir.name or manifest['input_bytes'] != len(input_raw):
        raise ValueError('job content key/input length mismatch')
    brief = _ref(root, manifest['brief_ref'], MAX_MATERIAL_BYTES, base).decode('utf-8')
    if brief != BRIEF or _hash(brief.encode()) != contracts['brief_sha256']:
        raise ValueError('brief does not match current contract')
    ids = manifest['target_ids']
    if not isinstance(ids, list) or not ids or len(ids) > limit or len(set(ids)) != len(ids):
        raise ValueError('duplicate/invalid job target IDs')
    if (value.get('root') != str(root) or value.get('contracts') != contracts
            or manifest['targets'] != value.get('targets') or manifest['materials'] != value.get('materials')
            or manifest['output_contract'] != dict(OUTPUT_CONTRACT, exact_target_ids=ids)
            or value.get('output_contract') != manifest['output_contract']
            or [t['target_id'] for t in value['targets']] != ids):
        raise ValueError('manifest/input target or contract mismatch')
    expected_manifest = dict(kind='full_semantic_explanation', schema_version=1, root=str(root),
        content_key=job_dir.name, contracts=contracts, target_ids=ids, targets=value['targets'],
        group=value['group'], materials=value['materials'],
        input_ref=dict(path=base + '/input.json', sha256=_hash(input_raw)),
        brief_ref=dict(path=base + '/brief.txt', sha256=_hash(brief.encode())),
        input_bytes=len(input_raw), output_contract=value['output_contract'], gaps=[], model_calls=0)
    if manifest != expected_manifest:
        raise ValueError('manifest differs from reconstructed immutable job')
    for target in value['targets']:
        kind, identity = target['kind'], target['identity']
        expected_identity_keys = {'dataset_id', 'field_id'} if kind == 'field' else {'operator'}
        if (kind not in {'field', 'operator'} or not isinstance(identity, dict)
                or set(identity) != expected_identity_keys or any(not isinstance(v, str) or not v for v in identity.values())
                or target['target_id'] != kind + ':' + _digest(identity)):
            raise ValueError('invalid resource target identity')
    materials = value['materials']
    if (not isinstance(materials, list) or not materials
            or sum(len(m['content'].encode('utf-8')) for m in materials) > MAX_MATERIAL_BYTES
            or len({m['source_index']['path'] for m in materials}) > MAX_SELECTED_SOURCES):
        raise ValueError('material bounds exceeded')
    diagnostics, registered = [], {}
    for row in _rows(_safe(root, 'machine/source_index.jsonl'), diagnostics):
        path = row.get('path')
        if path in registered and registered[path] != row:
            raise ValueError('conflicting current source registration')
        registered[path] = row
    if diagnostics:
        raise ValueError('invalid current source index')
    index, texts, parsed = {}, {}, {}
    for material in materials:
        source = material['source_index']
        path = source['path']
        if material['target_id'] not in ids or _hash(material['content'].encode()) != material['sha256']:
            raise ValueError('material target/hash mismatch')
        current = registered.get(path)
        if not isinstance(current, dict) or ({k: v for k, v in current.items() if k != 'file_sha256'}
                                             != {k: v for k, v in source.items() if k != 'file_sha256'}):
            raise ValueError('source registration differs from bound job')
        if path not in index:
            checked, text = _material(root, current)
            for claim in (current, source):
                if 'file_sha256' in claim and claim['file_sha256'] != checked['file_sha256']:
                    raise ValueError('asserted source digest mismatch')
            index[path], texts[path] = checked, text
            parse_diagnostics = []
            parsed[path] = list(_parse(text, path, parse_diagnostics))
            if parse_diagnostics:
                raise ValueError('source material cannot reconstruct completely')
        target = next(t for t in value['targets'] if t['target_id'] == material['target_id'])
        from wqb.full_semantic_compile import _identity, _scope_rows
        if not any(content == material['content'] and _identity(row, 'operator' in path.lower()) == (target['kind'], target['identity'])
                   and _scope_rows(row) == material['scopes'] and not row.get('ambiguous', False)
                   for row, content in parsed[path]):
            raise ValueError('selected material does not reconstruct from exact source identity/scope')
        if any(scope not in target['source_validated_scopes'] for scope in material['scopes']):
            raise ValueError('material scope not declared source-validated')
    if set(m['target_id'] for m in materials) != set(ids):
        raise ValueError('job lacks material for one or more targets')
    return dict(manifest=manifest, input=value, brief=brief, job_dir=str(job_dir), root=str(root),
                source_index=index, source_texts=texts)


def _object(properties: dict, required: list | None = None) -> dict:
    """Input: schema properties/optional required keys. Output: closed JSON Schema object."""
    return dict(type='object', properties=properties,
                required=list(properties) if required is None else required, additionalProperties=False)


def full_semantic_output_schema(job: dict) -> dict:
    """Input: loaded job dict. Output: closed answer schema; null summaries and empty factual maps allowed."""
    string = dict(type='string', minLength=1)
    strings = dict(type='array', items=string)
    ref = _object(dict(source_path=string, sha256=string, capture_date=string,
                       kind=dict(type='string', enum=['documented', 'hypothesis']), experiment_refs=strings))
    refs = dict(type='array', items=ref)
    card = _object(dict(hypothesis_card=_object({key: string for key in CARD_FIELDS}), evidence_refs=refs))
    use = _object(dict(conditions=string, purpose=string, failure_risks=strings, evidence_refs=refs))
    operator_schema = semantic_output_schema(2)['properties']['proposals']['properties']['operators']['items']['properties']['record']['properties']
    scope = _object(dict(instrument_type=string, region=string, delay=dict(type='integer', minimum=0), universe=string))
    locator = dict(anyOf=[_object(dict(kind=dict(type='string', enum=['json_value']),
        row_identity=_object(dict(dataset_id=string, field_id=string, scope=scope)),
        value_path=strings, expected_value={})), _object(dict(kind=dict(type='string', enum=['markdown_quote']),
        heading=string, quote=string))])
    claim = _object(dict(value={}, premises=dict(type='array', minItems=1,
                        items=_object(dict(evidence_ref=ref, locator=locator)))))
    facts = {key: claim for key in sorted(FIELD_FACTS)}
    facts.update(definition=operator_schema['definition'], definition_basis=operator_schema['definition_basis'])
    target = _object(dict(target_id=dict(type='string', enum=job['manifest']['target_ids']),
        identity=dict(anyOf=[_object(dict(operator=string)), _object(dict(dataset_id=string, field_id=string))]),
        literal_fact_summary=dict(anyOf=[string, dict(type='null')]), typed_facts=_object(facts, []),
        hypothesis_cards=dict(type='array', items=card), conditional_uses=dict(type='array', items=use),
        missing_facts=strings, conflicting_facts=strings, evidence_refs=refs))
    count = len(job['manifest']['target_ids'])
    return _object(dict(summary=string, targets=dict(type='array', items=target, minItems=count, maxItems=count)))


def _strings(value, name: str) -> None:
    """Input: value/field name. Output: None; require explicit nonempty strings in a list."""
    if not isinstance(value, list) or any(not isinstance(s, str) or not s.strip() for s in value):
        raise ValueError(name + ' requires a string list')


def _evidence(refs, job: dict, *, hypothesis: bool = False) -> None:
    """Input: evidence list/loaded job/hypothesis flag. Output: None; verify existing EvidenceRef and bytes."""
    from wqb.resource_evidence import _source, verify_hypothesis_source
    if not isinstance(refs, list) or hypothesis and not refs:
        raise ValueError('classified evidence list required')
    for ref in refs:
        evidence = evidence_ref_from_dict(ref)
        if evidence.kind == 'measured':
            raise ValueError('unsupported measured claims in explanation output')
        if hypothesis and evidence.kind != 'hypothesis':
            raise ValueError('economic explanations must remain hypotheses')
        issues = validate_semantic_record(dict(evidence_refs=[ref]), job['source_index'])
        if issues:
            raise ValueError('invalid evidence: ' + str(issues))
        if evidence.kind == 'hypothesis':
            verify_hypothesis_source(ref, job['source_index'], job['source_texts'])
        else:
            _source(ref, job['source_index'], job['source_texts'])


def _formula_strings(value):
    """Input: explanation JSON value. Output: prose strings, excluding original identity/evidence metadata."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _formula_strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in {'identity', 'target_id', 'evidence_refs', 'premises', 'definition_basis'}:
                yield from _formula_strings(item)


def _field_result(root: Path, job: dict, target: dict, bound: dict, canonical_fields: dict,
                  *, persist_field_results: bool = True) -> tuple:
    """Input: root/job/target/bound/canonical dicts and persistence bool. Output: proof tuple and K3 ref.

    Only K3's resolver can select factual enrichment. Missing measured capture
    remains a compiler gap for explanation-only answers, never forged coverage.
    """
    from wqb.knowledge_compile import resolve_field_semantics
    identity, facts = bound['identity'], target['typed_facts']
    if set(facts) - FIELD_FACTS:
        raise ValueError('unsupported field factual type/polarity/key')
    candidates = canonical_fields.get((identity['dataset_id'], identity['field_id']), [])
    materials = [m for m in job['input']['materials'] if m['target_id'] == target['target_id']]
    field_types = set()
    descriptions = set()
    from wqb.full_semantic_compile import _objects
    for material in materials:
        try:
            for raw in _objects(_json(material['content'])):
                field = raw.get('field', raw)
                if field.get('type'):
                    field_types.add(field['type'])
                if isinstance(field.get('description'), str):
                    descriptions.add(field['description'])
        except ValueError:
            pass
    literal = target['literal_fact_summary']
    if literal is not None and literal not in descriptions:
        raise ValueError('field literal summary must retain a sourced original description')
    if not candidates or len(field_types) != 1 or literal is None:
        if facts:
            raise ValueError('field facts require current canonical K3 proof and exact literal/type')
        return dict(status='hypothesis_only', research_eligible=False,
                    reason='No current canonical compiler proof selected'), None
    scopes = bound['source_validated_scopes']
    result = dict(schema_version=1, status='validated', source_index=job['source_index'], fields=[dict(
        **identity, field_type=next(iter(field_types)), allowed_scopes=scopes,
        literal_fact_explanation=literal, facts=facts, hypothesis_cards=target['hypothesis_cards'],
        missing_facts=target['missing_facts'])])
    raw = _bytes(result)
    base = Path(job['job_dir']).relative_to(root).as_posix()
    path = base + '/field_explanations_' + _hash(raw) + '.json'
    if persist_field_results:
        ref = _freeze(root, path, raw)
    else:
        artifact = _safe(root, path)
        if not artifact.is_file() or artifact.stat().st_size != len(raw) or artifact.read_bytes() != raw:
            raise ValueError('readonly field result artifact missing or changed')
        ref = dict(path=path, sha256=_hash(raw))
    checked = []
    for row in candidates:
        selected = dict(row, field_semantics_ref=dict(schema_version=1, **ref, **identity))
        checked.append(resolve_field_semantics(root, selected))
    failures = [item for item in checked if item['status'] != 'supported']
    if failures and facts:
        raise ValueError('K3 rejected field facts: ' + str(failures))
    return dict(status='supported' if not failures else 'hypothesis_only', research_eligible=False,
                resolver_results=checked), ref


def validate_full_semantic_output(root: Path, job: dict, answer: dict,
                                  *, persist_field_results: bool = True) -> dict:
    """Input: root/job/answer dicts and persistence bool. Output: validated envelope with per-target proofs/K3 refs.

    Raising ValueError rejects the whole job; no target is silently dropped. A
    validated explanation is never automatically compiler-eligible or published.
    Readonly mode verifies existing deterministic field artifacts without writes.
    """
    root = _root(root)
    job = load_bound_explanation_job(Path(job['job_dir']))
    if job['root'] != str(root):
        raise ValueError('validation root mismatch')
    if not isinstance(answer, dict) or set(answer) != {'summary', 'targets'} or len(_bytes(answer)) > MAX_OUTPUT_BYTES:
        raise ValueError('unknown/missing answer fields or oversized answer')
    if not isinstance(answer['summary'], str) or not answer['summary'].strip() or not isinstance(answer['targets'], list):
        raise ValueError('full summary and targets required')
    wanted = {target['target_id']: target for target in job['input']['targets']}
    field_keys = {(t['identity']['dataset_id'], t['identity']['field_id'])
                  for t in wanted.values() if t['kind'] == 'field'}
    canonical_fields, diagnostics = {}, []
    if field_keys:
        for row in _rows(_safe(root, machine_resource_path(root, 'data_ledger').relative_to(root).as_posix()), diagnostics):
            key = (row.get('dataset_id'), row.get('field_id'))
            if key in field_keys:
                canonical_fields.setdefault(key, []).append(row)
        if diagnostics:
            raise ValueError('invalid canonical field ledger')
    seen, proofs, field_refs = set(), {}, {}
    known = {t['identity']['operator'] for t in job['input']['targets'] if t['kind'] == 'operator'}
    for text in _formula_strings(answer):
        if set(re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(', text)) - known:
            raise ValueError('unsupported formula/operator in output')
    for target in answer['targets']:
        if not isinstance(target, dict) or set(target) != set(OUTPUT_CONTRACT['required_target_fields']):
            raise ValueError('unknown/missing target fields')
        target_id = target['target_id']
        if target_id not in wanted or target_id in seen or target['identity'] != wanted[target_id]['identity']:
            raise ValueError('duplicate/extra/mismatched target identity')
        seen.add(target_id)
        bound = wanted[target_id]
        if not isinstance(target['typed_facts'], dict):
            raise ValueError('typed_facts must be an object')
        for name in ('missing_facts', 'conflicting_facts'):
            _strings(target[name], name)
        literal = target['literal_fact_summary']
        if literal is None:
            if not target['missing_facts']:
                raise ValueError('null literal summary requires explicit missing reason')
        elif not isinstance(literal, str) or not literal.strip():
            raise ValueError('literal summary must be nonblank or null')
        _evidence(target['evidence_refs'], job)
        if literal is not None and not target['evidence_refs']:
            raise ValueError('literal summary requires source evidence')
        cards = target['hypothesis_cards']
        if not isinstance(cards, list):
            raise ValueError('hypothesis cards require a list')
        for card in cards:
            if not isinstance(card, dict) or set(card) != {'hypothesis_card', 'evidence_refs'}:
                raise ValueError('unknown/missing hypothesis card fields')
            hypothesis_card_from_dict(card['hypothesis_card'])
            _evidence(card['evidence_refs'], job, hypothesis=True)
        semantic_fields_from_dict(dict(conditional_uses=target['conditional_uses']))
        for use in target['conditional_uses']:
            _evidence(use['evidence_refs'], job, hypothesis=True)
        if bound['kind'] == 'field':
            proofs[target_id], ref = _field_result(root, job, target, bound, canonical_fields,
                                                 persist_field_results=persist_field_results)
            if ref:
                field_refs[target_id] = ref
        else:
            facts = target['typed_facts']
            if set(facts) - {'definition', 'definition_basis'} or 'definition_basis' in facts and 'definition' not in facts:
                raise ValueError('unsupported operator factual type/polarity/key')
            if facts:
                from wqb.resource_evidence import resolve_operator_definition
                operator_definition_from_dict(facts['definition'])
                for ref in facts['definition']['evidence_refs']:
                    _evidence([ref], job)
                record = dict(operator=bound['identity']['operator'], **facts)
                issues = validate_semantic_record(record, job['source_index'])
                proof = resolve_operator_definition(record, job['source_index'], job['source_texts'], resource_contract_version=2)
                if issues or proof['status'] != 'supported':
                    raise ValueError('unsupported source-bound operator definition: ' + str(issues or proof))
                proofs[target_id] = dict(status='supported', definition=proof, research_eligible=False)
            else:
                proofs[target_id] = dict(status='hypothesis_only', research_eligible=False)
            if literal is not None:
                materials = [m['content'] for m in job['input']['materials'] if m['target_id'] == target_id]
                if not any(literal in text for text in materials):
                    raise ValueError('operator literal summary not present in exact source material')
    if seen != set(wanted):
        raise ValueError('omitted output target IDs')
    return dict(schema_version=1, status='validated', summary=answer['summary'], targets=deepcopy(answer['targets']),
                target_validation=proofs, field_result_refs=field_refs,
                compiler_eligibility='per_target_proof_only', research_authorized=False,
                publication_authorized=False)


def _load_plan(root: Path, plan: dict) -> tuple:
    """Input: resolved root/supplied plan. Output: saved plan/inventory; authenticate, ignoring only cache counters."""
    if not isinstance(plan, dict) or plan.get('root') != str(root) or not HASH.fullmatch(str(plan.get('content_key', ''))):
        raise ValueError('plan root/key mismatch')
    base = 'machine/semantic_jobs/' + plan['content_key']
    if plan.get('plan_path') != base + '/plan.json':
        raise ValueError('plan path mismatch')
    # Plans/inventories can be much larger than a bounded model result; they are
    # local machine manifests, not model material. Raw source limits are unchanged.
    path = _safe(root, plan['plan_path'])
    saved = _read(path, max(path.stat().st_size, 1), canonical=True)
    supplied = deepcopy(plan)
    for value in (saved, supplied):
        for field in ('cached_jobs', 'changed_jobs'):
            value['estimates'].pop(field, None)
    if supplied != saved or _digest(saved['identity']) != saved['content_key']:
        raise ValueError('saved plan identity/authority differs from supplied plan')
    if saved['identity']['root'] != str(root) or saved['identity']['jobs'] != saved['jobs']:
        raise ValueError('plan identity root/job mismatch')
    config = saved['identity']['config']
    budget = config['model_call_budget']
    if (type(budget) is not int or budget < 0 or saved['budget']['model_call_budget'] != budget
            or type(config['max_runtime_seconds']) is not int or config['max_runtime_seconds'] < 1):
        raise ValueError('invalid finite plan budget/runtime')
    inventory_path = _safe(root, saved['inventory_ref']['path'])
    inventory_raw = _ref(root, saved['inventory_ref'], max(inventory_path.stat().st_size, 1), base)
    if _hash(inventory_raw) != saved['identity']['inventory_sha256']:
        raise ValueError('inventory identity mismatch')
    inventory = [_json(line.decode()) for line in inventory_raw.splitlines() if line.strip()]
    ids = [row['target_id'] for row in inventory]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate inventory target')
    assigned = [target for job in saved['jobs'] for target in job['target_ids']]
    if len(assigned) != len(set(assigned)) or set(assigned) != {row['target_id'] for row in inventory if row['status'] == 'prepared'}:
        raise ValueError('job target coverage differs from inventory')
    return saved, inventory


def _cancelled(root: Path, base: str) -> bool:
    """Input: vault Path/job or plan base. Output: bool; malformed controls fail closed."""
    path = _safe(root, base + '/control.json')
    if not path.exists():
        return False
    control = _read(path)
    if not isinstance(control, dict) or type(control.get('cancelled', False)) is not bool:
        raise ValueError('invalid cancellation control')
    return control.get('cancelled', False)


def _reservations(root: Path, base: str, plan: dict) -> dict:
    """Input: vault/plan base/saved plan. Output: authenticated durable reservations, never refunded."""
    folder = _safe(root, base + '/reservations')
    reservations = {}
    if folder.exists():
        allowed = {job['job_id'] for job in plan['jobs']}
        for path in folder.iterdir():
            relative = path.relative_to(root).as_posix()
            row = _read(_safe(root, relative), canonical=True)
            if (path.suffix != '.json' or path.stem not in allowed or row.get('job_id') != path.stem
                    or row.get('plan_key') != plan['content_key'] or row.get('calls') != 1):
                raise ValueError('invalid durable reservation')
            reservations[path.stem] = row
    if len(reservations) > plan['budget']['model_call_budget']:
        raise ValueError('durable reservations exceed original allowance')
    return reservations


def _verify_state(root: Path, state: dict, ref: dict, *, _plan_loader=None) -> dict | None:
    """Input: vault/state/job ref. Output: original authority dict or None; bind durable charged reservation."""
    if not state:
        return
    if state.get('status') not in TERMINAL_STATES | {'completed'}:
        raise ValueError('unknown execution state; no retry authority')
    if state.get('job_id') != ref['job_id'] or state.get('input_sha256') != ref['input_sha256']:
        raise ValueError('job execution state identity mismatch')
    owner = state.get('owner_plan')
    if not isinstance(owner, str) or not HASH.fullmatch(owner) or 'reservation_ref' not in state:
        raise ValueError('job state lacks original reservation authority')
    attempt = _read(_safe(root, 'machine/semantic_jobs/' + ref['job_id'] + '/attempt_reservation.json'), canonical=True)
    if attempt != dict(job_id=ref['job_id'], input_sha256=ref['input_sha256'], owner_plan=owner, deadline=state['deadline']):
        raise ValueError('independent job reservation differs from state')
    base = 'machine/semantic_jobs/' + owner
    reservation_ref = state['reservation_ref']
    if reservation_ref.get('path') != base + '/reservations/' + ref['job_id'] + '.json':
        raise ValueError('job reservation path mismatch')
    reservation = _json(_ref(root, reservation_ref, MAX_OUTPUT_BYTES, base).decode())
    authority = _read(_safe(root, base + '/execution_authority.json'), canonical=True)
    plan_path = _safe(root, base + '/plan.json')
    plan = _read(plan_path, max(plan_path.stat().st_size, 1), canonical=True)
    plan, _ = (_load_plan if _plan_loader is None else _plan_loader)(root, plan)
    if (plan.get('content_key') != owner or _digest(plan['identity']) != owner or plan['root'] != str(root)
            or authority['plan_key'] != owner or authority['root'] != str(root)
            or authority['model_call_budget'] != plan['budget']['model_call_budget']
            or authority['deadline'] != authority['started_at'] + plan['identity']['config']['max_runtime_seconds']
            or state['reservation_id'] != reservation_ref['sha256']
            or reservation['plan_key'] != owner or reservation['job_id'] != ref['job_id']
            or reservation['calls'] != 1 or reservation['deadline'] != authority['deadline']
            or state['deadline'] != authority['deadline']
            or not any(job['job_id'] == ref['job_id'] for job in plan['jobs'])):
        raise ValueError('job reservation/owner/deadline mismatch')
    reservations = _reservations(root, base, plan)
    if ref['job_id'] not in reservations or authority['model_call_budget'] < 1:
        raise ValueError('job reservation is not charged to original authority')
    return dict(authority, owner_plan=owner, job_id=ref['job_id'], calls_reserved=len(reservations),
                reservation_ref=deepcopy(reservation_ref), reservation_id=state['reservation_id'])


def require_full_semantic_reservation(job: dict) -> dict:
    """Input: loaded job dict. Output: authenticated running authority including owner_plan/deadline.

    Read-only dispatch gate for worker/checkpoint boundaries. Prepared input alone
    grants no model call. Reject absent/nonrunning/uncharged, cancelled or expired
    authority; do not acquire the runner-held job lock or create any reservation.
    """
    try:
        loaded = load_bound_explanation_job(Path(job['job_dir']))
        if any(key in job and job[key] != loaded[key] for key in ('root', 'manifest', 'input')):
            raise ValueError('supplied job differs from authenticated reservation input')
        root = Path(loaded['root'])
        manifest = loaded['manifest']
        base = Path(loaded['job_dir']).relative_to(root).as_posix()
        state_path = _safe(root, base + '/execution_state.json')
        state = _read(state_path)
        if not isinstance(state, dict) or state.get('status') != 'running':
            raise ValueError('model dispatch requires an already running reservation')
        authority = _verify_state(root, state, dict(job_id=manifest['content_key'],
                                                   input_sha256=manifest['input_ref']['sha256']))
        owner_base = 'machine/semantic_jobs/' + authority['owner_plan']
        owner_state = _safe(root, owner_base + '/execution_state.json')
        cancelled = owner_state.exists() and _read(owner_state).get('status') == 'cancelled'
        if cancelled or _cancelled(root, base) or _cancelled(root, owner_base):
            raise ValueError('model reservation cancelled')
        now = time.time()
        if (type(authority['deadline']) not in (int, float) or not math.isfinite(authority['deadline'])
                or type(authority['started_at']) not in (int, float) or not math.isfinite(authority['started_at'])
                or not math.isfinite(now) or now >= authority['deadline']):
            raise ValueError('model reservation original deadline expired or invalid')
        if _read(state_path) != state:
            raise ValueError('model reservation state changed during authentication')
        return authority
    except (OSError, KeyError, TypeError, AttributeError, UnicodeError) as exc:
        raise ValueError('missing or invalid full semantic reservation: ' + str(exc)) from exc


def claim_full_semantic_dispatch(job: dict, input_path: Path, *, worker: bool = False) -> dict:
    """Input: loaded job, checkpoint input Path, worker bool. Output: authenticated authority.

    One reservation owns one dispatch. A checkpoint delegates only to the exact
    token-bearing input bytes; its worker atomically consumes that delegation.
    A direct worker instead acquires and consumes the same reservation claim.
    Partial writes and uncertain launches remain spent, never retry authority.
    """
    authority = require_full_semantic_reservation(job)
    root = Path(job['root'])
    base = Path(job['job_dir']).relative_to(root).as_posix()
    source = _safe(root, Path(input_path).absolute().relative_to(root).as_posix())
    if (not source.is_relative_to(Path(job['job_dir']) / 'stages/ai/ai_checkpoint_runs')
            or source.name != 'input.json'):
        raise ValueError('dispatch input outside job checkpoint attempts')
    guard = _safe(root, base + '/dispatch_claim_guard')
    claim_path = _safe(root, base + '/dispatch_claim.json')
    worker_path = _safe(root, base + '/worker_transport_claim.json')
    with json_lock_transition_guard(guard, LOCK_TIMEOUT_SECONDS, LOCK_SLEEP_SECONDS, 'dispatch claim busy'):
        authority = require_full_semantic_reservation(job)
        payload = _read(source)
        token = payload.get('full_semantic_dispatch_token')
        binding = dict(job_id=authority['job_id'], reservation_id=authority['reservation_id'],
                       owner_plan=authority['owner_plan'], deadline=authority['deadline'])
        if worker and token is not None:
            if not isinstance(token, str) or not HASH.fullmatch(token):
                raise ValueError('invalid explanation dispatch token')
            claim = _read(claim_path, canonical=True)
            expected = dict(binding, kind='checkpoint', input_path=source.relative_to(root).as_posix(),
                            input_sha256=_hash(source.read_bytes()), token_sha256=_hash(token.encode()))
            if claim != expected:
                raise ValueError('explanation dispatch lineage mismatch')
            if worker_path.exists():
                raise ValueError('explanation worker transport already claimed; no replay')
            from wqb.ai_checkpoints import load_ai_checkpoints
            checkpoints = load_ai_checkpoints(Path(job['job_dir']) / 'stages/ai')
            checkpoint = next((row for row in checkpoints if row['checkpoint_id'] == payload.get('checkpoint_id')), {})
            if (checkpoint.get('status') != 'running' or checkpoint.get('input_path') != str(source)
                    or checkpoint.get('checkpoint_type') != 'full_semantic_explanation'):
                raise ValueError('explanation checkpoint delegation is no longer running')
        else:
            if claim_path.exists() or worker_path.exists():
                raise ValueError('explanation dispatch already claimed; no replay')
            if token is not None:
                raise ValueError('unexpected explanation dispatch token')
            if not worker:
                token = secrets.token_hex(32)
                payload['full_semantic_dispatch_token'] = token
                _write(source, payload)
            claim = dict(binding, kind='worker' if worker else 'checkpoint',
                         input_path=source.relative_to(root).as_posix(), input_sha256=_hash(source.read_bytes()),
                         token_sha256=_hash(token.encode()) if token is not None else None)
            _freeze(root, base + '/dispatch_claim.json', _bytes(claim))
        if worker:
            if worker_path.exists():
                raise ValueError('explanation worker transport already claimed; no replay')
            _freeze(root, base + '/worker_transport_claim.json', _bytes(dict(
                binding, dispatch_sha256=_digest(claim))))
    return authority


def full_semantic_transport_controls(job: dict, timeout_seconds: float) -> tuple:
    """Input: loaded job and timeout number. Output: bounded seconds and mandatory cancellation callback.

    Authenticate once, then poll original deadline and durable plan/job Stop
    without repeatedly parsing all frozen source material during transport.
    """
    authority = require_full_semantic_reservation(job)
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('invalid explanation transport timeout')
    root = Path(job['root'])
    job_base = Path(job['job_dir']).relative_to(root).as_posix()
    plan_base = 'machine/semantic_jobs/' + authority['owner_plan']

    def cancelled() -> bool:
        """Input: none. Output: bool; original deadline and durable cancellation dominate transport."""
        if time.time() >= authority['deadline']:
            return True
        if _cancelled(root, job_base) or _cancelled(root, plan_base):
            return True
        job_state = _read(_safe(root, job_base + '/execution_state.json'))
        if (not isinstance(job_state, dict) or job_state.get('status') != 'running'
                or any(job_state.get(key) != authority[key] for key in
                       ('job_id', 'owner_plan', 'reservation_id', 'deadline'))):
            return True
        state_path = _safe(root, plan_base + '/execution_state.json')
        if state_path.exists():
            state = _read(state_path)
            if not isinstance(state, dict):
                raise ValueError('invalid durable plan state')
            if state.get('status') == 'cancelled':
                return True
        return False

    if cancelled():
        raise ValueError('explanation transport cancelled')
    return min(timeout_seconds, max(0.0, authority['deadline'] - time.time())), cancelled


def run_full_semantic_compile(root: Path, plan: dict, *, executor) -> dict:
    """Input: vault Path/prepared plan/callback. Output: complete per-target results, blockers and finite accounting.

    Budget is authenticated against immutable prep, never supplied overrides.
    Independent job state survives new plans; prepared input is not completed
    cache. Valid completed cache is reusable at budget0 after current-source and
    full output revalidation. No retry, publication or canonical reference update.
    """
    result = dict(status='blocked', plan_key=plan.get('content_key') if isinstance(plan, dict) else None,
                  targets=[], jobs=[], blockers=[], calls_reserved=0, budget_remaining=0,
                  model_calls=0, deadline=None, research_authorized=False, publication_authorized=False,
                  research_ready=False)
    try:
        root = _root(root)
        saved, inventory = _load_plan(root, plan)
        base = 'machine/semantic_jobs/' + saved['content_key']
        guard = _safe(root, base + '/execution_guard')
        _safe(root, base + '/execution_guard.guard')
        with json_lock_transition_guard(guard, LOCK_TIMEOUT_SECONDS, LOCK_SLEEP_SECONDS, 'plan execution busy'):
            authority_path = _safe(root, base + '/execution_authority.json')
            if authority_path.exists():
                authority = _read(authority_path, canonical=True)
            else:
                started = time.time()
                authority = dict(plan_key=saved['content_key'], root=str(root), started_at=started,
                                 deadline=started + saved['identity']['config']['max_runtime_seconds'],
                                 model_call_budget=saved['budget']['model_call_budget'])
                _freeze(root, base + '/execution_authority.json', _bytes(authority))
            if (authority['plan_key'] != saved['content_key'] or authority['root'] != str(root)
                    or authority['model_call_budget'] != saved['budget']['model_call_budget']
                    or not all(type(authority[k]) in (int, float) and math.isfinite(authority[k]) for k in ('started_at', 'deadline'))
                    or authority['deadline'] != authority['started_at'] + saved['identity']['config']['max_runtime_seconds']):
                raise ValueError('execution authority/deadline mismatch')
            result['deadline'] = authority['deadline']
            reservations = _reservations(root, base, saved)
            result.update(calls_reserved=len(reservations), budget_remaining=saved['budget']['model_call_budget'] - len(reservations))
            plan_state_path = _safe(root, base + '/execution_state.json')
            plan_state = _read(plan_state_path) if plan_state_path.exists() else {}
            cancelled = plan_state.get('status') == 'cancelled' or _cancelled(root, base)
            if cancelled:
                _write(plan_state_path, dict(status='cancelled', plan_key=saved['content_key']))
            outputs = {row['target_id']: dict(target_id=row['target_id'], identity=row['identity'], status='blocked',
                       result=None, blockers=row.get('gaps', [])) for row in inventory}
            for ref in saved['jobs']:
                job_status, explanation, error = 'blocked', None, ''
                state = {}
                job_base = 'machine/semantic_jobs/' + ref['job_id']
                try:
                    manifest_raw = _ref(root, dict(path=ref['path'], sha256=ref['sha256']), MAX_OUTPUT_BYTES, job_base)
                    job_dir = _safe(root, job_base)
                    job = load_bound_explanation_job(job_dir)
                    if (job['manifest']['target_ids'] != ref['target_ids'] or _hash(manifest_raw) != ref['sha256']
                            or ref['input_sha256'] != job['manifest']['input_ref']['sha256']
                            or ref['brief_sha256'] != job['manifest']['brief_ref']['sha256']):
                        raise ValueError('plan job reference differs from authenticated input')
                    job_guard = _safe(root, job_base + '/execution_guard')
                    _safe(root, job_base + '/execution_guard.guard')
                    with json_lock_transition_guard(job_guard, LOCK_TIMEOUT_SECONDS, LOCK_SLEEP_SECONDS, 'job execution busy'):
                        state_path = _safe(root, job_base + '/execution_state.json')
                        state = _read(state_path) if state_path.exists() else {}
                        _verify_state(root, state, ref)
                        attempt_path = _safe(root, job_base + '/attempt_reservation.json')
                        if cancelled or _cancelled(root, base) or _cancelled(root, job_base):
                            cancelled = True
                            _write(plan_state_path, dict(status='cancelled', plan_key=saved['content_key']))
                            job_status = 'cancelled'
                        elif state.get('status') == 'completed':
                            raw = _ref(root, state['result_ref'], MAX_OUTPUT_BYTES, job_base)
                            cached = _json(raw.decode('utf-8'))
                            explanation = validate_full_semantic_output(root, job, dict(summary=cached['summary'], targets=cached['targets']))
                            if _bytes(explanation) != raw:
                                raise ValueError('completed explanation proof differs from current validation')
                            job_status = 'cached'
                        elif state.get('status') in TERMINAL_STATES or ref['job_id'] in reservations or attempt_path.exists():
                            job_status = state.get('status', 'outcome_unknown')
                            if job_status in {'running', 'reserved'}:
                                job_status = 'outcome_unknown'
                            error = 'Attempt is terminal or uncertain; automatic replay is forbidden'
                        elif state:
                            raise ValueError('unknown execution state')
                        elif time.time() >= authority['deadline']:
                            job_status, error = 'deadline_exceeded', 'Original plan deadline expired'
                        elif result['budget_remaining'] <= 0:
                            job_status, error = 'budget_blocked', 'Finite model-call allowance exhausted'
                        elif not callable(executor):
                            job_status, error = 'blocked', 'A callable explicit executor is required'
                        else:
                            # This independent immutable intent closes the crash gap
                            # before plan accounting/state writes, including new plans.
                            _freeze(root, job_base + '/attempt_reservation.json', _bytes(dict(
                                job_id=ref['job_id'], input_sha256=ref['input_sha256'],
                                owner_plan=saved['content_key'], deadline=authority['deadline'])))
                            reservation = dict(plan_key=saved['content_key'], job_id=ref['job_id'], calls=1,
                                               deadline=authority['deadline'], reserved_at=time.time())
                            reservation_ref = _freeze(root, base + '/reservations/' + ref['job_id'] + '.json', _bytes(reservation))
                            reservations[ref['job_id']] = reservation
                            result.update(calls_reserved=len(reservations), budget_remaining=saved['budget']['model_call_budget'] - len(reservations))
                            state = dict(status='reserved', job_id=ref['job_id'], input_sha256=ref['input_sha256'],
                                         owner_plan=saved['content_key'], deadline=authority['deadline'],
                                         reservation_id=reservation_ref['sha256'], reservation_ref=reservation_ref,
                                         execution_version=EXECUTION_VERSION)
                            _write(state_path, state)
                            state['status'] = 'running'
                            _write(state_path, state)
                            try:
                                result['model_calls'] += 1
                                answer = executor(job=deepcopy(job), output_schema=full_semantic_output_schema(job), deadline=authority['deadline'])
                            except (Exception, KeyboardInterrupt) as exc:
                                state.update(status='outcome_unknown', error=type(exc).__name__)
                                _write(state_path, state)
                                job_status, error = 'outcome_unknown', 'Executor did not return a certain complete outcome'
                            else:
                                try:
                                    explanation = validate_full_semantic_output(root, job, answer)
                                    result_ref = _freeze(root, job_base + '/explanation_result.json', _bytes(explanation))
                                    if _cancelled(root, base) or _cancelled(root, job_base):
                                        job_status, cancelled = 'cancelled', True
                                        _write(plan_state_path, dict(status='cancelled', plan_key=saved['content_key']))
                                    elif time.time() >= authority['deadline']:
                                        job_status, error = 'deadline_exceeded', 'Executor returned after original deadline'
                                    else:
                                        job_status = 'completed'
                                    state.update(status=job_status, result_ref=result_ref)
                                except (OSError, ValueError, TypeError, KeyError) as exc:
                                    state.update(status='rejected', error=str(exc))
                                    job_status, explanation, error = 'rejected', None, str(exc)
                                _write(state_path, state)
                except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                    job_status, error = 'blocked', str(exc)
                returned = {target['target_id']: target for target in explanation['targets']} if explanation else {}
                for target_id in ref['target_ids']:
                    outputs[target_id].update(status=job_status, result=returned.get(target_id),
                        validation=explanation['target_validation'].get(target_id) if explanation else None)
                    if error:
                        outputs[target_id]['blockers'] = [error]
                result['jobs'].append(dict(job_id=ref['job_id'], status=job_status, error=error,
                                           result_ref=state.get('result_ref')))
                if job_status not in {'completed', 'cached'}:
                    result['blockers'].append(dict(job_id=ref['job_id'], status=job_status, reason=error or job_status))
            result['targets'] = list(outputs.values())
            for target in result['targets']:
                if target['status'] == 'blocked' and target['blockers']:
                    result['blockers'].append(dict(target_id=target['target_id'], status='blocked', reason=target['blockers']))
            complete = all(t['status'] in {'completed', 'cached'} for t in result['targets'])
            result['status'] = 'cancelled' if cancelled else 'completed' if complete else 'blocked'
            result['inventory_complete'] = saved['coverage'].get('inventory_complete', False)
            result['full_processing_coverage'] = complete and result['inventory_complete']
            processed = [t for t in result['targets'] if t['status'] in {'completed', 'cached'}]
            explained = [t for t in processed if t['result'] and (
                t['result']['literal_fact_summary'] is not None or t['result']['hypothesis_cards']
                or t['result']['conditional_uses'])]
            verified = [t for t in explained if t.get('validation', {}).get('status') == 'supported']
            resolved = [t for t in verified if not t['result']['missing_facts'] and not t['result']['conflicting_facts']]
            result['coverage'] = dict(target_count=len(inventory), processed_targets=len(processed),
                explained_targets=len(explained), verified_targets=len(verified), eligible_targets=0,
                source_verified_targets=sum(bool(t.get('source_validated')) for t in inventory),
                unresolved_targets=len(inventory) - len(resolved),
                compiler_eligibility='not_evaluated', actual_start_consumption='not_evaluated')
            result['full_coverage'] = bool(inventory) and result['full_processing_coverage'] and len(resolved) == len(inventory)
            _write(_safe(root, base + '/execution_result.json'), result)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        result['blockers'].append(dict(status='blocked', reason=str(exc)))
    return result
