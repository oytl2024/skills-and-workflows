"""Offline, content-addressed semantic proposals; this module never publishes.

Input source_refs are existing SourceIndexRow dictionaries, not invented file
registrations. Evidence hashes refer to indexed content (Markdown body); output
source_refs bind full file bytes for the publisher. Group envelopes are separate
from Task 1 records: trigger_id/mechanism_id/condition_id/record.

Lifecycle experiments additionally require template_id, hypothesis_version,
bindings (slot -> field_id object), scope (region/delay/universe matching settings),
and optional numeric parameters. Exact bound AST identity is required; unsupported
implicit reductions remain gaps, not successful lifecycle evidence. Cached job
receipts are reconstructed from source-scoped unit outputs before reuse.
"""

from copy import deepcopy
from dataclasses import asdict, fields
from datetime import datetime, timezone
import ast
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
from uuid import uuid4

from wqb.ai_checkpoints import append_ai_checkpoint, load_ai_checkpoints, run_ai_checkpoint
from wqb.knowledge_contracts import parse_markdown_front_matter
from wqb.operator_semantics import (OperatorSemanticRecord, operator_semantic_record_from_dict,
                                    operator_semantic_record_to_dict)
from wqb.semantic_contracts import SemanticPolicy, validate_semantic_record, CARD_FIELDS
from wqb.template_library import TemplateRecord, template_record_from_dict, template_record_to_dict
from wqb.resource_evidence import resource_contract_version
from wqb.mechanism_evidence import MAX_CONTEXT as MAX_MECHANISM_CONTEXT


SCHEMA_VERSION = 2
TASK_VERSION = 'semantic-compile-4'
DESIGN_CONTEXT_VERSION = 'hypothesis-context-3'
DESIGN_TASK_VERSION = 'hypothesis-proposal-2'
DESIGN_EVIDENCE_VERSION = 2
MAX_MATERIAL_BYTES = 7000
MAX_SELECTED_SOURCES = 24
MAX_SOURCE_BYTES = 2_000_000
MAX_OUTPUT_BYTES = 1_000_000
MAX_INPUT_SOURCES = 128
MAX_PACK_BYTES = 11000
MAX_RESEARCH_INDEX_HEADINGS = 24
MAX_NUMERIC_MAGNITUDE = sys.float_info.max
SENSITIVE_NAMES = {'config', 'configs', 'configuration', 'credentials', 'credential', 'secrets',
                   'secret', 'token', 'tokens', 'auth', 'settings', 'id_rsa', 'id_ed25519'}
SUCCESS_STATUSES = {'seed', 'discovery_ready', 'submit_proven'}
GROUP_KEYS = {'trigger_id', 'mechanism_id', 'condition_id', 'record'}


def _hash(raw: bytes) -> str:
    """Input: bytes. Output: hex str. Hash complete bytes, never a sliced preview."""
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object) -> str:
    """Input: JSON-compatible object. Output: str. Compute a stable cache identity."""
    return _hash(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))


def _write(path: Path, value: dict, *, compact: bool = False) -> None:
    """Input: Path/dict/compact bool. Output: None. Atomically preserve a complete JSON receipt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False,
                        indent=None if compact else 2, separators=(',', ':') if compact else None), encoding='utf-8')
    temporary.replace(path)


def _read(path: Path) -> dict:
    """Input: Path. Output: dict. Bound JSON receipt reads and reject nonobjects."""
    if path.stat().st_size > MAX_OUTPUT_BYTES:
        raise ValueError('oversized JSON receipt')
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise ValueError('expected JSON object')
    return result


def _safe(root: Path, relative: str, *, source: bool = False) -> Path:
    """Input: root Path/relative str/source bool. Output: Path. Deny escapes, links and secrets."""
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('invalid relative material path')
    parts = relative.split('/')
    if PurePosixPath(relative).is_absolute() or any(p in {'', '.', '..'} for p in parts):
        raise ValueError('material path escape')
    if source and not (relative.startswith('raw/platform/') or relative.startswith('raw/research/')
                       or relative.startswith('raw/user/') or relative.startswith('raw/community/user_messages/')):
        raise ValueError('material must be an explicitly indexed raw source')
    current = root
    for part in parts:
        lowered = part.lower()
        if lowered.startswith('.') or Path(lowered).stem in SENSITIVE_NAMES or lowered.endswith(('.pem', '.key', '.pfx')):
            raise ValueError('sensitive material path denied')
        current = current / part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('symlink/junction material denied')
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError('material path escape')
    return current


def _policy(policy: SemanticPolicy) -> dict:
    """Input: SemanticPolicy. Output: dict. Require positive explicit limits."""
    values = asdict(policy)
    if any(type(value) is not int or value < 1 for value in values.values()):
        raise ValueError('semantic limits must be positive integers')
    return values


def _material(root: Path, row: dict) -> tuple[dict, str]:
    """Input: root/SourceIndexRow dict. Output: enriched index/text. Verify body and full hashes."""
    required = {'path', 'content_hash', 'captured_at', 'source_type', 'source_family'}
    if not isinstance(row, dict) or not required <= set(row) or any(not isinstance(row[k], str) or not row[k] for k in required):
        raise ValueError('source_refs require existing source index metadata')
    datetime.fromisoformat(row['captured_at'].replace('Z', '+00:00'))
    path = _safe(root, row['path'], source=True)
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('source exceeds safe read bound; compile a smaller indexed source')
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    content = raw
    metadata = {}
    if path.suffix.lower() == '.md':
        metadata, body = parse_markdown_front_matter(text.replace('\r\n', '\n'))
        if metadata:
            content = body.encode('utf-8')
            for key in ('content_hash', 'captured_at', 'source_type', 'source_family'):
                if key in metadata and str(metadata[key]) != row[key]:
                    raise ValueError(f'frontmatter/index mismatch: {key}')
    if _hash(content) != row['content_hash'].lower():
        raise ValueError('indexed source content_hash mismatch')
    if path.suffix.lower() == '.md':
        from wqb.knowledge_contracts import verify_source_repair
        repair = verify_source_repair(root, row['path'])
        if repair.get('status') not in ('verified', 'not_repaired') or repair.get('source_sha256') != _hash(raw):
            raise ValueError('source repair receipt does not match consumed bytes')
    if (row.get('content_status') == 'verified_raw_extract'
            or metadata.get('content_status') == 'verified_raw_extract'
            or (row['path'].startswith('raw/platform/data_fields/')
                and path.name.startswith('semantic-subset-'))):
        from wqb.knowledge_contracts import verify_field_source_extract
        receipt = verify_field_source_extract(root, row['path'])
        if receipt.get('status') != 'verified' or receipt.get('excerpt_sha256') != _hash(raw):
            raise ValueError('field extract receipt does not match consumed bytes')
    normalized = dict(row, file_sha256=_hash(raw))
    if 'target_ids' in row:
        targets = row['target_ids']
        if not isinstance(targets, list) or not targets or any(not isinstance(t, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', t) for t in targets):
            raise ValueError('target_ids require nonempty explicit identifiers')
        normalized['target_ids'] = sorted(set(targets))
    return normalized, text


def _target_material(text: str, target_ids: list[str]) -> str:
    """Input: complete source text/target IDs. Output: complete Markdown sections, never byte slices.

    Official capture writes each operator as a level-3 heading with its Source id
    and complete definition/description. Unknown layouts remain explicit gaps;
    source headings, not guessed operator names or unindexed JSON, select scope.
    """
    if not target_ids:
        return text
    _, body = parse_markdown_front_matter(text.replace('\r\n', '\n'))
    headings = list(re.finditer(r'^###\s+`?([A-Za-z_][A-Za-z0-9_.-]*)`?\s*$', body, re.MULTILINE))
    sections = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        section = body[heading.start():end]
        # A new category belongs to the next section, not the preceding operator.
        category = re.search(r'^##\s+', section, re.MULTILINE)
        if category:
            section = section[:category.start()]
        if heading[1] in sections:
            raise ValueError('duplicate operator heading; target scope ambiguous')
        sections[heading[1]] = section
    missing = sorted(set(target_ids) - set(sections))
    if missing:
        raise ValueError('missing structured target sections: ' + ', '.join(missing))
    return '\n'.join(sections[target] for target in target_ids)


def _semantic_versions(policy: SemanticPolicy, resource_version: int) -> dict:
    """Input: SemanticPolicy/int resource version. Output: dict; bind current schema/rules/project policy without upgrading v1."""
    resource_contract_version({'resource_contract_version': resource_version})
    version = dict(schema_version=SCHEMA_VERSION, task_version=TASK_VERSION, policy=_policy(policy),
                   material_limits=dict(max_material_bytes=MAX_MATERIAL_BYTES, max_sources=MAX_SELECTED_SOURCES))
    if resource_version == 2:
        contracts = _design_versions(policy)
        version.update(resource_contract_version=2, resource_rules_digest=contracts['resource_rules_digest'],
                       resource_schema_digest=_digest(semantic_output_schema(2)),
                       parameter_policy=contracts['parameter_policy'])
    return version


def prepare_semantic_job(root: Path, source_refs: list[dict], policy: SemanticPolicy, *, resource_version: int = 1) -> Path:
    """Input: vault Path/index rows/SemanticPolicy. Output: job Path. Freeze bounded read-only copies.

    One complete source per unit; large sources are explicit gaps, never cut at a
    byte boundary. Only provided index entries grant provenance. Source selection
    is partial by construction, not a claim to cover the entire operator registry.
    """
    root = Path(root).resolve()
    resource_contract_version({'resource_contract_version': resource_version})
    if not isinstance(source_refs, list) or len(source_refs) > MAX_INPUT_SOURCES or any(not isinstance(row, dict) for row in source_refs):
        raise ValueError('source index selection exceeds bounded job scope')
    version = _semantic_versions(policy, resource_version)
    rows, texts = [], {}
    for ref in sorted(source_refs, key=lambda row: row.get('path', '')):
        row, text = _material(root, ref)
        if row['path'] in texts:
            raise ValueError('duplicate indexed source')
        rows.append(row)
        texts[row['path']] = text
    identity = dict(**version, sources=rows)
    digest = _digest(identity)
    jobs = _safe(root, 'machine/semantic_jobs')
    job = _safe(jobs, digest)
    if (job / 'run_manifest.json').exists():
        return job
    gaps, units = [], []
    for row in rows:
        try:
            selected_text = _target_material(texts[row['path']], row.get('target_ids', []))
        except ValueError as exc:
            gaps.append(dict(code='material_gap', path=row['path'], message=str(exc)))
            continue
        supporting = None
        if len(selected_text.encode('utf-8')) > MAX_MATERIAL_BYTES and row['path'].startswith('raw/research/'):
            supporting = dict(path='materials/sources/' + row['file_sha256'] + '.md', sha256=row['file_sha256'])
            headings = re.findall(r'^#{1,6}\s+(.+)$', selected_text, re.MULTILINE)
            selected_text = json.dumps(dict(kind='complete_research_record_reference',
                source_path=row['path'], supporting_evidence=supporting,
                section_titles=[heading for heading in headings if len(heading) <= 160][:MAX_RESEARCH_INDEX_HEADINGS],
                section_count=len(headings), section_index_partial=True,
                instruction='Consult relevant sections of the complete bound local record; incomplete results are not measurements.'), ensure_ascii=False)
        if len(units) >= MAX_SELECTED_SOURCES or len(selected_text.encode('utf-8')) > MAX_MATERIAL_BYTES:
            gaps.append(dict(code='material_gap', path=row['path'], message='Complete source omitted by material bound'))
            continue
        # Each source is independently cached; declared experiments are dependencies
        # only when supplied in the source's index metadata by the coordinator.
        dependencies = row.get('experiment_refs', [])
        if not isinstance(dependencies, list) or any(dep not in texts for dep in dependencies):
            raise ValueError('missing indexed experiment dependency')
        selected = [row] + [item for item in rows if item['path'] in dependencies and item['path'] != row['path']]
        pack = dict(source_index={item['path']: {k: v for k, v in item.items() if k != 'file_sha256'} for item in selected},
                    materials=[dict(path=item['path'], indexed_content_hash=item['content_hash'],
                                    file_sha256=item['file_sha256'], target_ids=item.get('target_ids', []),
                                    partial=bool(item.get('target_ids')),
                                    content=selected_text if item['path'] == row['path'] else texts[item['path']]) for item in selected],
                    target_ids=row.get('target_ids', []),
                    grouping_contract=sorted(GROUP_KEYS), coverage='partial', **version)
        if supporting is not None:
            pack['materials'][0]['supporting_evidence'] = supporting
        if len(json.dumps(pack, ensure_ascii=False).encode('utf-8')) > MAX_PACK_BYTES:
            gaps.append(dict(code='material_gap', path=row['path'], message='Complete dependency pack exceeds bound'))
            continue
        unit_identity = dict(**version, sources=selected, role='unit')
        unit_id = _digest(unit_identity)
        unit = _safe(jobs, unit_id)
        material_path = _safe(unit, 'materials/pack.json')
        if not (unit / 'run_manifest.json').exists():
            if supporting is not None:
                copy_path = _safe(unit, supporting['path'])
                raw = _safe(root, row['path'], source=True).read_bytes()
                if copy_path.exists():
                    if _hash(copy_path.read_bytes()) != supporting['sha256']:
                        raise ValueError('research supporting copy changed')
                else:
                    copy_path.parent.mkdir(parents=True, exist_ok=True)
                    with copy_path.open('xb') as handle:
                        handle.write(raw)
                    copy_path.chmod(0o444)
            _write(material_path, pack)
            material_path.chmod(0o444)
            _write(unit / 'run_manifest.json', dict(kind='knowledge_compile', unit_id=unit_id,
                identity=unit_identity,
                **version, target_ids=row.get('target_ids', []), source_refs=[dict(path=item['path'], sha256=item['file_sha256']) for item in selected],
                source_index=pack['source_index'], material_refs=[dict(path='materials/pack.json', sha256=_hash(material_path.read_bytes()))],
                supporting_material_refs=[dict(supporting, source_path=row['path'])] if supporting is not None else []))
        units.append(unit_id)
    _write(job / 'run_manifest.json', dict(kind='knowledge_compile', identity=identity,
        root=str(root), **version, units=units, source_index={row['path']: row for row in rows},
        source_refs=[dict(path=row['path'], sha256=row['file_sha256']) for row in rows],
        coverage=dict(partial=True, selected_sources=len(units), provided_sources=len(rows),
                      omitted_sources=len(gaps), registry_coverage='unknown',
                      target_ids=sorted({target for row in rows for target in row.get('target_ids', [])})), gaps=gaps))
    return job


def verify_semantic_material_copies(unit: Path, manifest: dict) -> None:
    """Input: unit Path/manifest dict. Output: None. Bind full research copies to indexed sources before model execution or replay."""
    material_refs = manifest.get('material_refs', [])
    if len(material_refs) != 1:
        raise ValueError('semantic job requires one bound material index')
    pack = _read(_safe(unit, material_refs[0]['path']))
    if (resource_contract_version(pack) != resource_contract_version(manifest)
            or resource_contract_version(manifest) != resource_contract_version(manifest.get('identity', {}))):
        raise ValueError('semantic material/manifest resource version mismatch')
    if resource_contract_version(manifest) == 2:
        version = _semantic_versions(SemanticPolicy(**manifest['policy']), 2)
        identity = manifest['identity']
        if any(_digest(value.get(key)) != _digest(expected)
               for value in (manifest, identity, pack) for key, expected in version.items()):
            raise ValueError('stale semantic schema/rules/parameter policy')
        if unit.name != _digest(identity):
            raise ValueError('semantic material content key mismatch')
    expected = []
    if not any(item.get('supporting_evidence') for item in pack.get('materials', [])):
        if manifest.get('supporting_material_refs', []):
            raise ValueError('research supporting manifest mismatch')
        return
    sources = {row['path']: row for row in manifest['identity']['sources']}
    for item in pack['materials']:
        reference = item.get('supporting_evidence')
        if reference is None:
            continue
        source = sources[item['path']]
        canonical = dict(path='materials/sources/' + source['file_sha256'] + '.md', sha256=source['file_sha256'])
        if not source['path'].startswith('raw/research/') or reference != canonical:
            raise ValueError('research supporting reference is outside indexed source identity')
        if _hash(_safe(unit, reference['path']).read_bytes()) != reference['sha256']:
            raise ValueError('research supporting copy hash mismatch')
        expected.append(dict(reference, source_path=item['path']))
    if manifest.get('supporting_material_refs', []) != expected:
        raise ValueError('research supporting manifest mismatch')


def _object(properties: dict, required: list | None = None) -> dict:
    """Input: property schemas/required names. Output: strict object schema dict."""
    return dict(type='object', properties=properties, required=list(properties) if required is None else required,
                additionalProperties=False)


def semantic_output_schema(resource_version: int = 2) -> dict:
    """Input: none. Output: strict JSON schema dict. Describe records plus external grouping metadata."""
    string = dict(type='string')
    strings = dict(type='array', items=string)
    evidence = _object(dict(source_path=string, sha256=string, capture_date=string,
                            kind=dict(type='string', enum=['documented', 'hypothesis', 'measured']), experiment_refs=strings))
    refs = dict(type='array', items=evidence)
    premise = _object(dict(evidence_ref=evidence, locator=_object(dict(
        kind=dict(type='string', enum=['markdown_quote']), heading=string, quote=string))))
    basis = _object(dict(operator=string, signature_premise=premise,
        type_premises=dict(type='array', items=premise), rule_id=string,
        rule_version=dict(type='integer', minimum=1), definition_digest=string))
    scalar = dict(anyOf=[dict(type=kind) for kind in ('string', 'number', 'boolean')])
    # Parameter names are a closed signature in a typed definition; arbitrary
    # reduction dictionaries are validated by the Task 1 parser after generation.
    role = _object(dict(operator=string, role=string, purpose=string))
    parameter = _object(dict(name=string, type=string, required=dict(type='boolean'), default=scalar), ['name', 'type', 'required'])
    definition = _object(dict(description=string, input_types=strings, output_type=string,
                              parameters=dict(type='array', items=parameter), evidence_refs=refs))
    slot = _object(dict(name=string, role=string, required_semantics=strings, field_type=string,
                        required_metadata=strings, reduction=dict(anyOf=[dict(type='null'), _object(dict(
                            operator=string, parameters=dict(type='object', properties={}, required=[],
                                additionalProperties=scalar)))])), ['name', 'role', 'required_semantics', 'field_type'])
    common = dict(evidence_refs=refs, hypothesis_card=_object({key: string for key in CARD_FIELDS}),
                  input_slots=dict(type='array', items=slot), operator_roles=dict(type='array', items=role))
    lists = {'workflow_uses', 'compatible_field_types', 'template_tags', 'risk_tags', 'repair_levers', 'source_paths',
             'required_field_types', 'compatible_semantic_tags', 'operator_tags', 'compatible_regions',
             'compatible_universes', 'suitable_horizons', 'neutralization_styles', 'local_gates', 'experiment_paths',
             'known_antipatterns', 'crowded_variants', 'data_semantics', 'operator_composition', 'abandon_conditions', 'benchmark_rule_ids'}
    properties = {}
    for name, cls in (('operators', OperatorSemanticRecord), ('templates', TemplateRecord)):
        record = {}
        for field in fields(cls):
            key = field.name
            record[key] = common.get(key, strings if key in lists else string)
            if key in {'semantic_version', 'binding_version', 'hypothesis_version'}:
                record[key] = dict(type='integer', minimum=1)
            if key == 'compatible_delays':
                record[key] = dict(type='array', items=dict(type='integer'))
            if key == 'definition':
                record[key] = definition
            if key == 'definition_basis' and resource_version == 2:
                record[key] = basis
            if key == 'conditional_uses':
                record[key] = dict(type='array', items=_object(dict(conditions=string, purpose=string, failure_risks=strings, evidence_refs=refs)))
        required = ['operator', 'family', 'semantic_version', 'evidence_refs'] if name == 'operators' else ['template_id', 'skeleton', 'status', 'semantic_version', 'evidence_refs']
        envelope = _object(dict(trigger_id=string, mechanism_id=string, condition_id=string,
                                record=_object(record, required)))
        properties[name] = dict(type='array', items=envelope)
    return _object(dict(summary=string, proposals=_object(properties)))


def semantic_worker_schema(materials: dict) -> dict:
    """Input: complete material pack dict. Output: Codex-compatible strict schema.

    All object fields are required on the wire; optional record fields use null
    and are omitted before Task 1 parsing. Named reduction parameters can only
    come from complete JSON or source-labelled Markdown signatures in material.
    """
    parameter_names = set()
    for material in materials.get('materials', []):
        text = material.get('content', '')
        for definition in _markdown_definitions(text).values():
            parameter_names.update(parameter['name'] for parameter in definition['parameters'])
        candidates = [text] + re.findall(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
        for candidate in candidates:
            try:
                pending = [json.loads(candidate)]
            except ValueError:
                continue
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    if isinstance(value.get('parameters'), list):
                        for parameter in value['parameters']:
                            if isinstance(parameter, dict) and isinstance(parameter.get('name'), str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', parameter['name']):
                                parameter_names.add(parameter['name'])
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)

    def strict(schema: dict) -> dict:
        """Input: schema dict. Output: strict schema dict. Close maps and nullable optional fields."""
        if 'anyOf' in schema:
            return dict(anyOf=[strict(branch) for branch in schema['anyOf']])
        result = dict(schema)
        if schema['type'] == 'object':
            properties = schema['properties']
            if isinstance(schema.get('additionalProperties'), dict):
                properties = {name: schema['additionalProperties'] for name in sorted(parameter_names)}
            result['properties'] = {key: strict(value) if key in schema['required'] else
                dict(anyOf=[strict(value), dict(type='null')]) for key, value in properties.items()}
            result['required'] = list(properties)
            result['additionalProperties'] = False
        elif schema['type'] == 'array':
            result['items'] = strict(schema['items'])
        return result
    return strict(semantic_output_schema(resource_contract_version(materials)))


def normalize_semantic_output(value: object) -> object:
    """Input: strict-wire JSON value. Output: JSON value. Omit nullable optionals for Task 1 compatibility."""
    def nullable(schema: dict) -> dict:
        """Input: schema dict. Output: schema dict. Allow null only for known optional wire fields."""
        if 'anyOf' in schema:
            return dict(anyOf=[nullable(branch) for branch in schema['anyOf']])
        result = dict(schema)
        if schema['type'] == 'object':
            result['properties'] = {key: nullable(item) if key in schema['required'] else
                dict(anyOf=[nullable(item), dict(type='null')]) for key, item in schema['properties'].items()}
            if isinstance(schema.get('additionalProperties'), dict):
                result['additionalProperties'] = dict(anyOf=[schema['additionalProperties'], dict(type='null')])
        elif schema['type'] == 'array':
            result['items'] = nullable(schema['items'])
        return result

    def omit(item: object) -> object:
        """Input: validated JSON value. Output: JSON value. Remove optional nulls after shape validation."""
        if isinstance(item, dict):
            return {key: omit(child) for key, child in item.items() if child is not None}
        if isinstance(item, list):
            return [omit(child) for child in item]
        return item

    _check_schema(nullable(semantic_output_schema()), value)
    return omit(value)


def _finite_number(value: object) -> bool:
    """Input: JSON value object. Output: bool. Reject nonnumbers and overflow-sized ints without float conversion."""
    if type(value) is int:
        return -MAX_NUMERIC_MAGNITUDE <= value <= MAX_NUMERIC_MAGNITUDE
    return type(value) is float and math.isfinite(value)


def _check_schema(schema: dict, value: object) -> None:
    """Input: schema/value. Output: None. Validate the schema subset without a new dependency."""
    if 'anyOf' in schema:
        for branch in schema['anyOf']:
            try:
                _check_schema(branch, value)
                return
            except ValueError:
                pass
        raise ValueError('invalid union value')
    kind = schema['type']
    if kind == 'object':
        extra = schema.get('additionalProperties', False)
        if not isinstance(value, dict) or not set(schema['required']) <= set(value) or (extra is False and set(value) - set(schema['properties'])):
            raise ValueError('unknown or missing object fields')
        for key, item in value.items():
            _check_schema(schema['properties'].get(key, extra), item)
    elif kind == 'array':
        if not isinstance(value, list):
            raise ValueError('expected array')
        for item in value:
            _check_schema(schema['items'], item)
    elif kind == 'string':
        if not isinstance(value, str):
            raise ValueError('expected string')
    elif kind == 'null':
        if value is not None:
            raise ValueError('expected null')
    elif kind == 'boolean':
        if type(value) is not bool:
            raise ValueError('expected boolean')
    elif kind in {'integer', 'number'}:
        if type(value) not in ((int,) if kind == 'integer' else (int, float)) or not _finite_number(value) or value < schema.get('minimum', -math.inf):
            raise ValueError('invalid number')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('unknown enum value')


def validate_semantic_output(answer: dict) -> dict:
    """Input: model dict. Output: same dict. Reject extra keys and malformed grouped records."""
    if len(json.dumps(answer, ensure_ascii=False).encode('utf-8')) > MAX_OUTPUT_BYTES:
        raise ValueError('oversized semantic output')
    _check_schema(semantic_output_schema(), answer)
    if not answer['summary'].strip():
        raise ValueError('expected nonempty summary')
    for kind in ('operators', 'templates'):
        for item in answer['proposals'][kind]:
            if any(not item[key].strip() for key in ('trigger_id', 'mechanism_id', 'condition_id')):
                raise ValueError('expected nonempty grouping IDs')
    return answer


def _references(row: dict) -> list[dict]:
    """Input: record dict. Output: evidence dict list. Collect each independently graded claim."""
    refs = list(row.get('evidence_refs', []))
    refs.extend(row.get('definition', {}).get('evidence_refs', []))
    for use in row.get('conditional_uses', []):
        refs.extend(use.get('evidence_refs', []))
    return refs


def _measurement(root: Path, path: str, source_index: dict) -> dict:
    """Input: vault/path/index. Output: payload dict. Inspect actual measured identity/settings/results.

    Unsupported aggregate research formats fail closed; the coordinator must
    supply a separately indexed experiment with these auditable fields. A filename
    or success label alone is never measurement or final-submission evidence.
    """
    _material(root, source_index[path])
    payload = _read(_safe(root, path, source=True))
    if not isinstance(payload.get('expression'), str) or not payload['expression'].strip():
        raise ValueError('measurement missing expression')
    if not isinstance(payload.get('settings'), dict) or not payload['settings']:
        raise ValueError('measurement missing settings')
    metrics = payload.get('metrics')
    if not isinstance(metrics, dict) or not metrics or any(not _finite_number(v) for v in metrics.values()):
        raise ValueError('measurement missing finite results')
    if not isinstance(payload.get('checks'), list) or not payload['checks'] or not payload.get('tested_at'):
        raise ValueError('measurement missing test records')
    timestamp = payload['tested_at']
    if not isinstance(timestamp, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', timestamp):
        raise ValueError('measurement tested_at requires an explicit timezone-aware timestamp')
    tested = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    if tested.utcoffset() is None:
        raise ValueError('measurement tested_at requires timezone')
    if any(not isinstance(check, dict) or not isinstance(check.get('name'), str) or
           check.get('result') not in {'PASS', 'FAIL', 'WARNING'} for check in payload['checks']):
        raise ValueError('measurement has malformed check records')
    return payload


def _measurement_matches(row: dict, payload: dict) -> bool:
    """Input: template/verified experiment dicts. Output: bool. Verify lifecycle identity, scope and bound kernel."""
    if payload.get('template_id') != row['template_id'] or type(payload.get('hypothesis_version')) is not int or payload['hypothesis_version'] != row.get('hypothesis_version', 1):
        return False
    if row.get('hypothesis_id') and payload.get('hypothesis_id') != row['hypothesis_id']:
        return False
    scope = payload.get('scope')
    if not isinstance(scope, dict):
        return False
    for name, compatibility in (('region', 'compatible_regions'), ('delay', 'compatible_delays'), ('universe', 'compatible_universes')):
        value = scope.get(name)
        if value is None or type(value) is not type(payload['settings'].get(name)) or value != payload['settings'][name]:
            return False
        if row.get(compatibility) and value not in row[compatibility]:
            return False
    bindings = payload.get('bindings')
    slots = {slot['name'] for slot in row.get('input_slots', [])}
    if row.get('binding_version', 1) == 1:
        slots = {'field'}
    if not isinstance(bindings, dict) or set(bindings) != slots or not slots:
        return False
    atoms = {}
    for name, binding in bindings.items():
        if not isinstance(binding, dict) or not isinstance(binding.get('field_id'), str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', binding['field_id']):
            return False
        atoms[name] = binding['field_id']
    # Implicit reductions cannot be certified by a simple field substitution.
    # Keep such evidence pending a full verified binding receipt importer.
    if any(slot.get('reduction') for slot in row.get('input_slots', [])):
        return False
    parameters = payload.get('parameters', {})
    if not isinstance(parameters, dict):
        return False
    for name, value in parameters.items():
        if name in atoms or not _finite_number(value):
            return False
        atoms[name] = repr(value)
    skeleton = row['skeleton']
    placeholders = re.findall(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', skeleton)
    if set(placeholders) != set(atoms):
        return False
    expression = re.sub(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', lambda match: atoms[match[1]], skeleton)
    try:
        return ast.dump(ast.parse(expression, mode='eval')) == ast.dump(ast.parse(payload['expression'], mode='eval'))
    except (SyntaxError, ValueError):
        return False


def _markdown_definitions(text: str) -> dict:
    """Input: Markdown str. Output: operator->definition dict. Parse only complete source-labelled typed facts."""
    definitions = {}
    headings = list(re.finditer(r'^###\s+`?([A-Za-z_][A-Za-z0-9_.-]*)`?\s*$', text, re.MULTILINE))
    for number, heading in enumerate(headings):
        if sum(item[1] == heading[1] for item in headings) != 1:
            continue
        section = text[heading.end():headings[number + 1].start() if number + 1 < len(headings) else len(text)]
        def label(name: str) -> str:
            """Input: exact label str. Output: str. Require one unambiguous labelled Markdown line."""
            values = re.findall(r'^- ' + re.escape(name) + r':\s*(.+)$', section, re.MULTILINE)
            return values[0].strip() if len(values) == 1 else ''
        if label('Source id') != '`' + heading[1] + '`' or not label('Description'):
            continue
        inputs = label('Input types')
        output = label('Output type')
        if not re.fullmatch(r'`[A-Z]+`(?:,\s*`[A-Z]+`)*', inputs) or not re.fullmatch(r'`[A-Z]+`', output):
            continue
        parameter_section = re.search(r'^- Parameters:\s*\n((?:[ \t]+[^\n]+\n?)*)', section, re.MULTILINE)
        if not parameter_section:
            continue
        parameters = []
        for line in parameter_section[1].splitlines():
            match = re.fullmatch(r'  - `([A-Za-z_][A-Za-z0-9_]*)`: type=`([A-Z]+)`, required=`(true|false)`(?:, default=`([^`]+)`)?', line)
            if not match:
                break
            parameter = dict(name=match[1], type=match[2], required=match[3] == 'true')
            if match[4] is not None:
                try:
                    parameter['default'] = json.loads(match[4])
                except ValueError:
                    break
            parameters.append(parameter)
        else:
            if parameters and len({p['name'] for p in parameters}) == len(parameters) and heading[1] not in definitions:
                definitions[heading[1]] = dict(description=label('Description'), input_types=re.findall(r'`([A-Z]+)`', inputs),
                    output_type=output.strip('`'), parameters=parameters)
    return definitions


def _definition_supported(row: dict, root: Path, index: dict, *, resource_contract_version: int = 1) -> bool:
    """Input: record/root/index. Output: bool. Accept types only as explicit existing source data.

    Syntax is not a typed definition. Complete structured JSON or exact labelled
    Markdown facts are accepted; absent types/parameters remain unknown.
    """
    if type(resource_contract_version) is not int or resource_contract_version not in (1, 2):
        return False
    if resource_contract_version == 2:
        from wqb.resource_evidence import resolve_operator_definition
        basis = row.get('definition_basis') or {}
        refs = list(row['definition']['evidence_refs'])
        refs.extend(premise['evidence_ref'] for premise in
                    ([basis['signature_premise'], *basis['type_premises']] if basis else []))
        texts = {path: _material(root, index[path])[1] for path in {ref['source_path'] for ref in refs}}
        return resolve_operator_definition(row, index, texts, resource_contract_version=2)['status'] == 'supported'
    definition = row['definition']
    expected = {key: value for key, value in definition.items() if key != 'evidence_refs'}
    for ref in definition['evidence_refs']:
        _, text = _material(root, index[ref['source_path']])
        _, body = parse_markdown_front_matter(text.replace('\r\n', '\n'))
        if _markdown_definitions(body).get(row['operator']) == expected:
            return True
        candidates = [body] + re.findall(r'```json\s*\n(.*?)\n```', body, re.DOTALL)
        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except ValueError:
                continue
            pending = [payload]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    if {key: item for key, item in value.items() if key != 'evidence_refs'} == expected:
                        return True
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
    return False


def _validate_proposals(proposals: dict, root: Path, index: dict, policy: SemanticPolicy,
                        target_ids: list[str] | None = None, *, resource_version: int = 1) -> dict:
    """Input: grouped proposals/root/index/policy. Output: validated lists, grouping and rejections."""
    result = dict(validated_operators=[], validated_templates=[], rejections=[], grouping=[])
    groups = {}
    for kind in ('operators', 'templates'):
        for envelope in proposals[kind]:
            groups.setdefault(envelope['trigger_id'], {}).setdefault(envelope['mechanism_id'], set()).add(envelope['condition_id'])
    rejected = {trigger for trigger, mechanisms in groups.items() if len(mechanisms) > policy.max_mechanisms or
                any(len(conditions) > policy.max_conditions_per_mechanism for conditions in mechanisms.values())}
    seen = {}
    for kind, parser, serializer, identity in (
            ('operators', operator_semantic_record_from_dict, operator_semantic_record_to_dict, 'operator'),
            ('templates', template_record_from_dict, template_record_to_dict, 'template_id')):
        for envelope in proposals[kind]:
            row = envelope['record']
            errors = validate_semantic_record(row, index)
            if target_ids and ((kind == 'operators' and row.get('operator') not in target_ids) or
                               (kind == 'templates' and envelope['trigger_id'] not in target_ids)):
                errors.append(dict(code='outside_target_scope', path='$', message='Proposal outside requested target IDs'))
            if envelope['trigger_id'] in rejected:
                errors.append(dict(code='policy_limit', path='$', message='Entire trigger exceeds mechanism/condition limit'))
            if row.get('semantic_version') != SCHEMA_VERSION or not row.get('evidence_refs'):
                errors.append(dict(code='missing_provenance', path='$', message='Versioned proposals require evidence'))
            if len(row.get('conditional_uses', [])) > policy.max_conditions_per_mechanism:
                errors.append(dict(code='policy_limit', path='conditional_uses', message='Too many conditions in one mechanism'))
            try:
                if row.get('definition') and not _definition_supported(row, root, index, resource_contract_version=resource_version):
                    errors.append(dict(code='unsupported_definition', path='definition', message='Typed definition absent from indexed material; retain raw syntax and unknown types'))
                if row.get('raw_definition'):
                    documented = [ref for ref in row.get('evidence_refs', []) if ref['kind'] == 'documented']
                    if not documented or not any(row['raw_definition'] in _material(root, index[ref['source_path']])[1] for ref in documented):
                        errors.append(dict(code='unsupported_definition', path='raw_definition', message='Syntax requires exact documented source text'))
            except (ValueError, KeyError, TypeError, OSError) as exc:
                errors.append(dict(code='unsupported_definition', path='definition', message=str(exc)))
            try:
                measured = []
                for ref in _references(row):
                    if ref['kind'] == 'measured':
                        measured.extend(_measurement(root, path, index) for path in ref['experiment_refs'])
                if row.get('status') in SUCCESS_STATUSES:
                    if not measured:
                        raise ValueError('Successful template lifecycle requires actual measurements')
                    if not any(_measurement_matches(row, payload) and all(check['result'] == 'PASS' for check in payload['checks']) for payload in measured):
                        raise ValueError('Successful lifecycle requires passing measurements with matching template, binding, expression and scope lineage')
                    if row['status'] == 'submit_proven':
                        # Final submission proof is not derivable from a model claim
                        # or baseline checks. Leave it to the qualification importer.
                        raise ValueError('submit_proven requires independent qualification import, not semantic model output')
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append(dict(code='unverified_measurement', path='$', message=str(exc)))
            try:
                parsed = serializer(parser(row))
                if not parsed[identity] or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', parsed[identity]):
                    raise ValueError('invalid record identity')
                key = (kind, parsed[identity])
                if key in seen and seen[key] != parsed:
                    merge_fields = {'conditional_uses', 'evidence_refs', 'source_paths'}
                    if kind != 'operators' or any(seen[key][field] != value for field, value in parsed.items() if field not in merge_fields):
                        raise ValueError('conflicting record identity; create immutable IDs')
                if kind == 'templates' and not parsed['skeleton']:
                    raise ValueError('template missing skeleton')
            except (ValueError, TypeError, KeyError) as exc:
                errors.append(dict(code='invalid_record', path='$', message=str(exc)))
            if errors:
                result['rejections'].extend(dict(error, record_id=row.get(identity, ''), trigger_id=envelope['trigger_id']) for error in errors)
                continue
            if key not in seen:
                result['validated_' + kind].append(parsed)
                seen[key] = parsed
            elif kind == 'operators':
                for field in ('conditional_uses', 'evidence_refs', 'source_paths'):
                    for value in parsed[field]:
                        if value not in seen[key][field]:
                            seen[key][field].append(value)
            group = dict(kind=kind, record_id=parsed[identity],
                         **{name: envelope[name] for name in ('trigger_id', 'mechanism_id', 'condition_id')})
            if kind == 'operators':
                group['conditional_use_indices'] = [seen[key]['conditional_uses'].index(use) for use in row.get('conditional_uses', [])]
            result['grouping'].append(group)
    return result


def _cancelled(job: Path) -> bool:
    """Input: job Path. Output: bool. Read knowledge-job cancellation, independent of WQB Pause."""
    control = _safe(job, 'control.json')
    return control.exists() and _read(control).get('cancelled') is True


def _design_versions(policy: SemanticPolicy) -> dict:
    """Input: SemanticPolicy. Output: dict. Bind schema, compiler, policy and context contracts."""
    from wqb.hypothesis_design import COMPILER_VERSION, DESIGN_WORKER_CONTRACT, design_output_schema
    from wqb import resource_evidence as rules
    rule_contract = {name: getattr(rules, name) for name in (
        'REGULAR_DELAY_RULE', 'OPERATOR_RULES', 'OPERATOR_MEANING_SUFFIXES',
        'MATRIX_FACTS', 'GROUP_FACT', 'OPERATOR_RECEIPT_POLICY',
        'OPERATOR_CONTEXT_POLICY_VERSION', 'PROJECT_WINDOW_POLICY')}
    rule_contract['type_sections'] = {key: sorted(values) for key, values in rules.OPERATOR_TYPE_SECTION_HASHES.items()}
    rule_contract['type_ancestors'] = sorted(rules.OPERATOR_TYPE_ANCESTORS)
    rule_contract['document_headings'] = rules.OPERATOR_DOCUMENT_HEADINGS
    rule_contract['documentation_pages'] = rules.page_rule_contract()
    rule_contract['patterns'] = {name: getattr(rules, name).pattern for name in (
        'INTEGER_WINDOW_PATTERN', 'OPERATOR_CONTAINER_INTRO', 'OPERATOR_WINDOW_HEADING',
        'OPERATOR_WINDOW_CANDIDATE', 'OPERATOR_WINDOW_SUBJECT', 'OPERATOR_WINDOW_RELATION',
        'OPERATOR_CAPTURE_LINE')}
    return dict(schema_version=_digest([design_output_schema(1), design_output_schema(2)]), compiler_version=COMPILER_VERSION,
                task_version=DESIGN_TASK_VERSION, context_version=DESIGN_CONTEXT_VERSION,
                evidence_version=DESIGN_EVIDENCE_VERSION, resource_rules_digest=_digest(rule_contract),
                parameter_policy=deepcopy(rules.PROJECT_WINDOW_POLICY),
                worker_contract=deepcopy(DESIGN_WORKER_CONTRACT), policy=_policy(policy))


def _mechanism_summary(group: dict) -> dict:
    """Input: full selected derived group dict. Output: bounded observation summary with exact local byte reference."""
    from wqb.hypothesis_design import _canonical
    raw = _canonical(group).encode('utf-8')
    if len(raw) > min(MAX_SOURCE_BYTES, MAX_OUTPUT_BYTES):
        raise ValueError('oversized complete mechanism supporting record')
    digest = _hash(raw)
    return dict(group_id=group['group_id'], label=group['label'],
                observed_differences=deepcopy(group['observed_differences']), limitations=deepcopy(group['limitations']),
                supporting_ref=dict(path='materials/mechanisms/' + digest + '.json', sha256=digest))


def prepare_design_job(root: Path, evidence_pack: dict, policy: SemanticPolicy,
                       resources: dict | None = None, *, mechanism_feedback: list[dict] | None = None) -> Path:
    """Input: vault Path/pack/policy/resources dict/optional selected feedback dict list. Output: frozen job Path.

    Complete source copies stay local; the model receives a compact reference
    pack. Context-bearing commands use a distinct key from proposal-only jobs.
    """
    from wqb.hypothesis_design import _pack, _json_copy
    root = Path(root).resolve()
    original = _json_copy(evidence_pack, source_metadata=True, full_source=True)
    if 'mechanism_context' in original:
        raise ValueError('mechanism context must come from selected complete records')
    if mechanism_feedback is not None and (not isinstance(mechanism_feedback, list)
            or len(mechanism_feedback) > MAX_MECHANISM_CONTEXT):
        raise ValueError('expected bounded complete mechanism records')
    if mechanism_feedback:
        original['mechanism_context'] = [_mechanism_summary(group) for group in mechanism_feedback]
        if resources is not None:
            resources = deepcopy(resources)
            resources['evidence_pack']['mechanism_context'] = deepcopy(original['mechanism_context'])
    _pack(original)
    rows, texts = [], {}
    for path, ref in sorted(original['source_index'].items()):
        if ref.get('path') != path:
            raise ValueError('source index path mismatch')
        row, text = _material(root, ref)
        if path in original.get('source_texts', {}) and original['source_texts'][path] != text:
            raise ValueError('provided source_texts differ from actual full bytes')
        rows.append(row)
        texts[path] = text
    _pack(dict(original, source_texts=texts))
    if resources is not None:
        from wqb.hypothesis_template_compiler import _resources
        _resources(resources, original['scope'])
        if (resources['evidence_pack'] != original or resources['source_index'] != original['source_index']
                or resources['source_texts'] != texts):
            raise ValueError('compiler context differs from original evidence/full sources')
    version = _design_versions(policy)
    compact = {key: value for key, value in original.items() if key != 'source_texts'}
    identity = dict(**version, sources=rows, evidence_pack=compact,
                    context_digest=_digest(resources) if resources is not None else None)
    key = _digest(identity)
    # Only fixed local components are created; inspect links before each mkdir
    # and verify containment after it returns, when that directory is established.
    for relative in ('machine', 'machine/semantic_jobs'):
        jobs = root / relative
        if jobs.is_symlink() or (hasattr(jobs, 'is_junction') and jobs.is_junction()):
            raise ValueError('symlink/junction material denied')
        jobs.mkdir(exist_ok=True)
        jobs = _safe(root, relative)
    supporting = [dict(path='materials/sources/' + row['file_sha256'] + '.txt',
                       sha256=row['file_sha256'], source_path=row['path']) for row in rows]
    context_refs = ([dict(path='materials/compiler_context.json', sha256=_digest(resources))]
                    if resources is not None else [])
    pack = dict(evidence_pack=compact, policy=version['policy'],
                parameter_policy=version['parameter_policy'],
                supporting_material_refs=supporting, context_refs=context_refs,
                coverage='partial', task_kind='hypothesis_design')
    if len(json.dumps(pack, ensure_ascii=False).encode('utf-8')) > MAX_PACK_BYTES:
        raise ValueError('complete design reference pack exceeds bounded model context')
    from wqb.lockfile import json_lock_transition_guard
    # Anchor the key lock to an established parent, not a concurrently appearing
    # job root whose Windows resolve() can transiently retain the extended prefix.
    guard = _safe(jobs, key + '.preparation_guard')
    with json_lock_transition_guard(guard, 2.0, 0.02, 'design preparation busy'):
        job = _safe(jobs, key)
        job.mkdir(exist_ok=True)
        job = _safe(jobs, key)
        manifest_path = _safe(job, 'run_manifest.json')
        if manifest_path.exists():
            manifest = _read(manifest_path)
            if manifest.get('identity') != identity or manifest.get('root') != str(root):
                raise ValueError('existing design manifest identity mismatch')
            verify_design_materials(job, manifest, policy, check_sources=True)
            return job
        for ref in supporting:
            target = _safe(job, ref['path'])
            raw = texts[ref['source_path']].encode('utf-8')
            if target.exists() and target.read_bytes() != raw:
                raise ValueError('existing full source copy mismatch')
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                with target.open('xb') as handle:
                    handle.write(raw)
        from wqb.hypothesis_design import _canonical
        for group, summary in zip(mechanism_feedback or [], original.get('mechanism_context', [])):
            target = _safe(job, summary['supporting_ref']['path'])
            raw = _canonical(group).encode('utf-8')
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != raw:
                raise ValueError('existing mechanism supporting record mismatch')
            if not target.exists():
                with target.open('xb') as handle:
                    handle.write(raw)
        if resources is not None:
            _write(_safe(job, context_refs[0]['path']), resources, compact=True)
        material = _safe(job, 'materials/pack.json')
        _write(material, pack, compact=True)
        manifest = dict(kind='knowledge_compile', task_kind='hypothesis_design', root=str(root),
            identity=identity, **version, source_index={row['path']: row for row in rows},
            source_refs=[dict(path=row['path'], sha256=row['file_sha256']) for row in rows],
            material_refs=[dict(path='materials/pack.json', sha256=_hash(material.read_bytes()))],
            supporting_material_refs=supporting, context_refs=context_refs)
        if resource_contract_version(original) == 2:
            manifest['resource_contract_version'] = 2
        _write(manifest_path, manifest)
        verify_design_materials(job, manifest, policy, check_sources=True)
        return job


def _design_references(value: object, name: str, keys: set[str], count: int) -> list[dict]:
    """Input: reference JSON/name str/exact key set/count int. Output: strict reference dict list."""
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(name + ' requires exact reference cardinality')
    for ref in value:
        if not isinstance(ref, dict) or set(ref) != keys:
            raise ValueError(name + ' requires exact reference object keys')
        if any(not isinstance(ref[key], str) or not ref[key].strip() for key in keys):
            raise ValueError(name + ' requires nonempty string reference values')
        if not re.fullmatch(r'[0-9a-f]{64}', ref['sha256']):
            raise ValueError(name + ' requires a canonical SHA256 reference')
    return value


def verify_design_materials(job: Path, manifest: dict, policy: SemanticPolicy,
                            *, check_sources: bool = False) -> tuple[dict, dict | None]:
    """Input: job Path/manifest/policy/check_sources bool. Output: original full pack/resources.

    Workers verify only frozen local copies. Coordinators additionally verify
    original sources before cache reuse and after compilation, never rehash them.
    """
    from wqb.hypothesis_design import _pack
    if (not isinstance(manifest, dict) or manifest.get('kind') != 'knowledge_compile'
            or manifest.get('task_kind') != 'hypothesis_design'):
        raise ValueError('hypothesis_design requires a bound knowledge_compile manifest')
    identity = manifest['identity']
    if not isinstance(identity, dict):
        raise ValueError('design identity requires an object')
    version = _design_versions(policy)
    if any(_digest(manifest.get(key)) != _digest(value) or _digest(identity.get(key)) != _digest(value)
           for key, value in version.items()):
        raise ValueError('stale design contract/policy version')
    if job.name != _digest(identity) or set(identity) != set(version) | {'sources', 'evidence_pack', 'context_digest'}:
        raise ValueError('design content key mismatch')
    if job.parent != _safe(Path(manifest['root']), 'machine/semantic_jobs'):
        raise ValueError('design job location mismatch')
    rows = identity['sources']
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError('design sources require a nonempty object list')
    _design_references(manifest.get('source_refs'), 'source_refs', {'path', 'sha256'}, len(rows))
    _design_references(manifest.get('supporting_material_refs'), 'supporting_material_refs',
                       {'path', 'sha256', 'source_path'}, len(rows))
    _design_references(manifest.get('context_refs'), 'context_refs', {'path', 'sha256'},
                       int(identity['context_digest'] is not None))
    refs = _design_references(manifest.get('material_refs'), 'material_refs', {'path', 'sha256'}, 1)
    expected_index = {row['path']: row for row in rows}
    if (manifest['source_index'] != expected_index or
            manifest['source_refs'] != [dict(path=row['path'], sha256=row['file_sha256']) for row in rows]):
        raise ValueError('design source manifest mismatch')
    compact = identity['evidence_pack']
    if resource_contract_version(compact) != resource_contract_version(manifest):
        raise ValueError('design manifest/evidence pack resource version mismatch')
    original_index = {}
    for row in rows:
        original_row = dict(row)
        if 'file_sha256' not in compact['source_index'].get(row['path'], {}):
            original_row.pop('file_sha256')
        original_index[row['path']] = original_row
    if compact['source_index'] != original_index:
        raise ValueError('design original index mismatch')
    supporting = [dict(path='materials/sources/' + row['file_sha256'] + '.txt',
                       sha256=row['file_sha256'], source_path=row['path']) for row in rows]
    if manifest.get('supporting_material_refs') != supporting:
        raise ValueError('design full copy references mismatch')
    texts = {}
    for ref in supporting:
        path = _safe(job, ref['path'])
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError('oversized design full source copy')
        raw = path.read_bytes()
        if _hash(raw) != ref['sha256']:
            raise ValueError('design full source copy hash mismatch')
        texts[ref['source_path']] = raw.decode('utf-8')
    pack = dict(compact, source_texts=texts)
    _pack(pack)
    for summary in compact.get('mechanism_context', []):
        ref = summary['supporting_ref']
        path = _safe(job, ref['path'])
        if path.stat().st_size > min(MAX_SOURCE_BYTES, MAX_OUTPUT_BYTES):
            raise ValueError('oversized mechanism supporting record')
        raw = path.read_bytes()
        if _hash(raw) != ref['sha256']:
            raise ValueError('mechanism supporting record hash mismatch')
        if _mechanism_summary(json.loads(raw)) != summary:
            raise ValueError('mechanism summary differs from complete supporting record')
    context_refs = manifest.get('context_refs')
    expected_context = ([dict(path='materials/compiler_context.json', sha256=identity['context_digest'])]
                        if identity['context_digest'] is not None else [])
    if context_refs != expected_context:
        raise ValueError('design compiler context reference mismatch')
    resources = None
    if context_refs:
        context_path = _safe(job, context_refs[0]['path'])
        if context_path.stat().st_size > MAX_OUTPUT_BYTES:
            raise ValueError('oversized design compiler context')
        if _hash(context_path.read_bytes()) != context_refs[0]['sha256']:
            raise ValueError('design compiler context file hash mismatch')
        resources = _read(context_path)
        if _digest(resources) != identity['context_digest']:
            raise ValueError('design compiler context hash mismatch')
        if (resources.get('source_index') != compact['source_index'] or resources.get('source_texts') != texts
                or {k: v for k, v in resources.get('evidence_pack', {}).items() if k != 'source_texts'} != compact
                or any(texts.get(k) != v for k, v in resources['evidence_pack'].get('source_texts', {}).items())):
            raise ValueError('design compiler context/evidence mismatch')
    if refs[0]['path'] != 'materials/pack.json':
        raise ValueError('design requires one bounded reference pack')
    material = _safe(job, refs[0]['path'])
    if material.stat().st_size > MAX_PACK_BYTES:
        raise ValueError('oversized design reference pack')
    if _hash(material.read_bytes()) != refs[0]['sha256']:
        raise ValueError('design reference pack hash mismatch')
    if _digest(_read(material)) != _digest(dict(evidence_pack=compact, policy=version['policy'],
            parameter_policy=version['parameter_policy'],
            supporting_material_refs=supporting, context_refs=context_refs,
            coverage='partial', task_kind='hypothesis_design')):
        raise ValueError('design reference pack identity mismatch')
    if check_sources:
        _verify_sources(Path(manifest['root']), manifest)
    return pack, resources


def _design_empty(status: str, message: str) -> dict:
    """Input: status/message str. Output: dict. A failed proposal grants no drafts or authority."""
    return dict(designs=[], drafts=[], attachments=[], rejections=[dict(code=status, message=message)],
                cache_status=status, research_authorized=False)


def compile_design_proposals(job: Path, executor_argv: list[str], policy: SemanticPolicy) -> dict:
    """Input: prepared job Path/explicit executor argv/policy. Output: validated proposal dict.

    Reuse checkpoint attempts and terminal receipts. No publication, implicit
    retry, new research authority, or fallback to the legacy skeleton worker.
    Caller holds the existing command transition guard for concurrent requests.
    """
    from wqb.hypothesis_design import validate_hypothesis_design, compile_hypothesis_design
    job = Path(job).resolve()
    try:
        manifest = _read(_safe(job, 'run_manifest.json'))
        pack, resources = verify_design_materials(job, manifest, policy, check_sources=True)
        if resources is None:
            raise ValueError('compilation requires explicit complete compiler resources')
        result_path, state_path = _safe(job, 'result.json'), _safe(job, 'unit_result.json')
        if _cancelled(job):
            result = _design_empty('cancelled', 'Knowledge design job cancelled')
            _write(result_path, result)
            return result
        cached = _read(result_path) if result_path.exists() else None
        if cached is not None:
            if cached.get('cache_status') not in {'ready', 'hit', 'failed', 'invalid', 'cancelled'}:
                raise ValueError('unknown cached design verdict')
            if cached['cache_status'] in {'failed', 'invalid', 'cancelled'}:
                return _design_empty(cached['cache_status'], 'Terminal design content key; no automatic retry')
            if not state_path.exists():
                raise ValueError('cached design missing durable checkpoint output')
        if state_path.exists():
            state = _read(state_path)
        else:
            directory = _safe(job, 'stages/ai')
            if load_ai_checkpoints(directory):
                state = dict(status='failed', error='interrupted design checkpoint; no automatic retry')
            elif not executor_argv:
                return _design_empty('pending', 'executor-not-configured')
            else:
                checkpoint = append_ai_checkpoint(directory, 'hypothesis_design',
                    'Propose bounded economic mechanisms, never formulas or publication.',
                    [manifest['material_refs'][0]['path']], datetime.now(timezone.utc).isoformat())
                _write(state_path, dict(status='failed', error='interrupted design worker'))
                state = run_ai_checkpoint(directory, checkpoint.checkpoint_id, executor_argv,
                                          cancellation_check=lambda: _cancelled(job))
            _write(state_path, state)
        if _cancelled(job) or state.get('status') == 'cancelled':
            result = _design_empty('cancelled', 'Knowledge design job cancelled before completion')
        elif state.get('status') != 'completed':
            result = _design_empty('failed', state.get('error', 'Unknown checkpoint verdict'))
        else:
            answer = dict(summary=state['summary'], designs=state['designs'])
            checked = validate_hypothesis_design(answer, pack, policy)
            drafts, attachments, rejections = [], [], []
            for design in checked['designs']:
                verify_design_materials(job, manifest, policy, check_sources=True)
                compilation = compile_hypothesis_design(design, resources, pack['scope'])
                if compilation['status'] != 'compiled':
                    rejections.extend(compilation['rejections'])
                else:
                    drafts.extend(compilation['drafts'])
                    attachments.append(compilation['experiment'])
            result = dict(designs=checked['designs'], drafts=drafts, attachments=attachments,
                          rejections=rejections, cache_status='invalid' if rejections else 'ready',
                          research_authorized=False)
            if resource_contract_version(pack) == 2:
                result['resource_contract_version'] = 2
            verify_design_materials(job, manifest, policy, check_sources=True)
            if _cancelled(job):
                result = _design_empty('cancelled', 'Knowledge design job cancelled after compilation')
            elif cached is not None:
                if dict(cached, cache_status='ready') != result:
                    raise ValueError('cached design validation receipt mismatch')
                return dict(result, cache_status='hit')
        _write(result_path, result)
        return result
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        result = _design_empty('invalid', str(exc))
        # Malformed/failed unchanged keys stay terminal even after control clears.
        _write(_safe(job, 'result.json'), result)
        return result


def _empty(status: str, message: str) -> dict:
    """Input: status/message strings. Output: safe result dict. Preserve a visible non-success blocker."""
    return dict(validated_operators=[], validated_templates=[], rejections=[dict(code=status, path='$', message=message)],
                cache_status=status, source_refs=[], wiki_materials={}, grouping=[], coverage=dict(partial=True))


def design_review_identity(job: Path, policy: SemanticPolicy) -> dict:
    """Input: frozen job Path/policy. Output: exact review target dict; reconstruct without model execution or approval."""
    job = Path(job).resolve()
    result = compile_design_proposals(job, [], policy)
    if result['cache_status'] not in {'ready', 'hit'} or not result['drafts'] or result['rejections']:
        raise ValueError('review requires a successful verified design compilation')
    return dict(job_key=job.name, result_digest=_digest(dict(result, cache_status='ready')))


def _immutable_design_export(root: Path, relative: str, value: dict) -> dict:
    """Input: vault Path/relative str/JSON dict. Output: full-file reference; never overwrite differing evidence."""
    from wqb.hypothesis_design import _canonical
    path = _safe(root, relative)
    raw = _canonical(value).encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as stream:
            stream.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError('immutable design export differs from existing bytes')
    return dict(path=relative, sha256=_hash(raw))


def export_reviewed_design_proposals(job: Path, policy: SemanticPolicy, review: dict) -> dict:
    """Input: frozen job Path/policy/explicit exact review dict. Output: existing publication inputs, never active release.

    Review keys are job_key/result_digest/reviewer/reviewed_at. Operators must
    already be reviewed in the compiler input; this API never promotes them.
    The separate caller authorizes only these exact drafts/compilation. Export
    retains scout_only and grants no simulation, candidate or submit authority.
    """
    from wqb.hypothesis_design import compile_hypothesis_design
    from wqb.semantic_publication import _require_timestamp
    job = Path(job).resolve()
    target = design_review_identity(job, policy)
    if (not isinstance(review, dict) or set(review) != set(target) | {'reviewer', 'reviewed_at'}
            or any(review.get(key) != value for key, value in target.items())
            or not isinstance(review['reviewer'], str) or not review['reviewer'].strip()):
        raise ValueError('separate review must authorize exact job and compilation')
    _require_timestamp(review['reviewed_at'])
    manifest = _read(_safe(job, 'run_manifest.json'))
    pack, resources = verify_design_materials(job, manifest, policy, check_sources=True)
    if (resources is None or resource_contract_version(resources) != 2
            or any(row.get('semantic_status') != 'reviewed' for row in resources['operator_rows'])):
        raise ValueError('paired export requires already reviewed resource v2 operators')
    result = compile_design_proposals(job, [], policy)
    if target != dict(job_key=job.name, result_digest=_digest(dict(result, cache_status='ready'))):
        raise ValueError('review compilation changed during export')
    root = Path(manifest['root']).resolve()
    documents, templates = [], []
    for design in result['designs']:
        compiled = compile_hypothesis_design(design, resources, pack['scope'])
        if compiled['status'] != 'compiled' or compiled['experiment'] not in result['attachments']:
            raise ValueError('reviewed experiment reconstruction mismatch')
        document = dict(resource_contract_version=2, versions=_design_versions(policy),
                        compiler_input=dict(design=design, resources=resources, scope=pack['scope']),
                        experiment=compiled['experiment'])
        relative = 'raw/research/experiments/' + _digest(document) + '.json'
        documents.append((relative, document))
        templates.extend(dict(row, semantic_status='reviewed', experiment_paths=[relative]) for row in compiled['drafts'])
    refs = deepcopy(manifest['source_refs'])
    for item in pack.get('mechanism_context', []):
        ref = item['supporting_ref']
        refs.append(dict(path=job.relative_to(root).as_posix() + '/' + ref['path'], sha256=ref['sha256']))
    for relative, document in documents:
        refs.append(_immutable_design_export(root, relative, document))
    refs.append(_immutable_design_export(root, 'raw/research/experiments/review-' + _digest(review) + '.json', review))
    verify_design_materials(job, manifest, policy, check_sources=True)
    return dict(resource_contract_version=2, validated_operators=deepcopy(resources['operator_rows']),
                validated_templates=templates, source_refs=refs, wiki_materials={}, research_authorized=False)


def _verify_sources(root: Path, manifest: dict) -> None:
    """Input: vault Path/manifest. Output: None. Bind index metadata and full file bytes to the job key."""
    rows = manifest['identity']['sources']
    if manifest['source_index'] != {row['path']: row for row in rows}:
        raise ValueError('manifest source index differs from content identity')
    if manifest['source_refs'] != [dict(path=row['path'], sha256=row['file_sha256']) for row in rows]:
        raise ValueError('manifest publication references differ from identity')
    for row in rows:
        checked, _ = _material(root, row)
        if checked != row:
            raise ValueError('source file changed since preparation')


def compile_semantic_proposals(job: Path, executor_argv: list[str], policy: SemanticPolicy) -> dict:
    """Input: prepared Path/explicit argv/SemanticPolicy. Output: validated publication inputs, never a release.

    Failed/cancelled/invalid/interrupted units are terminal for this content key.
    Source or policy changes create new keys; no automatic model repeat. Output
    includes source_refs full-file hashes, empty wiki_materials, partial coverage,
    and stable grouping metadata for downstream selection and audit.
    """
    job = Path(job).resolve()
    try:
        manifest = _read(_safe(job, 'run_manifest.json'))
        if manifest.get('kind') != 'knowledge_compile' or manifest.get('policy') != _policy(policy):
            raise ValueError('knowledge manifest/policy mismatch')
        if manifest.get('schema_version') != SCHEMA_VERSION or manifest.get('task_version') != TASK_VERSION:
            raise ValueError('stale semantic contract version')
        resource_version = resource_contract_version(manifest)
        if resource_contract_version(manifest['identity']) != resource_version:
            raise ValueError('semantic identity resource version mismatch')
        if resource_version == 2:
            version = _semantic_versions(policy, 2)
            if any(_digest(value.get(key)) != _digest(expected)
                   for value in (manifest, manifest['identity']) for key, expected in version.items()):
                raise ValueError('stale semantic schema/rules/parameter policy')
        root = Path(manifest['root']).resolve()
        if job.parent != _safe(root, 'machine/semantic_jobs') or job.name != _digest(manifest['identity']):
            raise ValueError('job identity/location mismatch')
        _verify_sources(root, manifest)
        if _cancelled(job):
            result = _empty('cancelled', 'Knowledge job cancelled')
            _write(job / 'result.json', result)
            return result
        receipt = _safe(job, 'result.json')
        cached = None
        if receipt.exists():
            cached = _read(receipt)
            if cached.get('cache_status') not in {'ready', 'hit', 'failed', 'invalid', 'cancelled', 'pending'}:
                raise ValueError('invalid cached result status')
            if cached.get('cache_status') == 'cancelled':
                return _empty('cancelled', 'Knowledge job cancellation is durable for this content key')
            # Reconstruct from each unit's bounded, source-scoped output below.
            # A cached aggregate never grants permission to execute missing work.
        expected_coverage = dict(partial=True, selected_sources=len(manifest['units']),
            provided_sources=len(manifest['identity']['sources']), omitted_sources=len(manifest['gaps']),
            registry_coverage='unknown', target_ids=sorted({target for row in manifest['identity']['sources'] for target in row.get('target_ids', [])}))
        if manifest['coverage'] != expected_coverage:
            raise ValueError('manifest coverage mismatch')
        proposals = dict(operators=[], templates=[])
        failures = list(manifest['gaps'])
        hits, executed = 0, 0
        terminal = ''
        for unit_id in manifest['units']:
            if _cancelled(job):
                terminal = 'cancelled'
                break
            unit = _safe(job.parent, unit_id)
            unit_manifest = _read(_safe(unit, 'run_manifest.json'))
            if unit_manifest.get('kind') != 'knowledge_compile' or unit_manifest.get('policy') != _policy(policy):
                raise ValueError('unit manifest mismatch')
            if resource_contract_version(unit_manifest) != resource_version:
                raise ValueError('unit resource version mismatch')
            if _digest(unit_manifest['identity']) != unit_id:
                raise ValueError('unit identity mismatch')
            expected_index = {item['path']: {k: v for k, v in item.items() if k != 'file_sha256'}
                              for item in unit_manifest['identity']['sources']}
            if unit_manifest['source_index'] != expected_index:
                raise ValueError('unit source index mismatch')
            if unit_manifest.get('target_ids', []) != unit_manifest['identity']['sources'][0].get('target_ids', []):
                raise ValueError('unit target identity mismatch')
            if any(item not in manifest['identity']['sources'] for item in unit_manifest['identity']['sources']):
                raise ValueError('unit source is outside prepared inputs')
            for material in unit_manifest['material_refs']:
                path = _safe(unit, material['path'])
                if _hash(path.read_bytes()) != material['sha256']:
                    raise ValueError('run-local material hash mismatch')
            verify_semantic_material_copies(unit, unit_manifest)
            state_path = _safe(unit, 'unit_result.json')
            if state_path.exists():
                state = _read(state_path)
                hits += 1
            else:
                if cached is not None:
                    raise ValueError('cached job missing durable unit result')
                directory = unit / 'stages/ai'
                checkpoints = load_ai_checkpoints(directory)
                if checkpoints:
                    # A checkpoint without its unit receipt indicates interrupted
                    # work, not permission to repeat a model call.
                    state = dict(status='failed', error='interrupted semantic checkpoint')
                elif not executor_argv:
                    state = dict(status='pending', error='executor-not-configured')
                else:
                    try:
                        with _safe(unit, 'execution.lock').open('x', encoding='utf-8') as lock:
                            lock.write('Content key reserved; never repeat automatically.\n')
                    except FileExistsError:
                        state = dict(status='failed', error='semantic unit already reserved or interrupted')
                    else:
                        checkpoint = append_ai_checkpoint(directory, 'semantic_compile',
                            'Compile bounded untrusted material into unverified hypotheses; no network, authority or publication.',
                            ['materials/pack.json'], datetime.now(timezone.utc).isoformat())
                        _write(state_path, dict(status='failed', error='interrupted semantic worker'))
                        state = run_ai_checkpoint(directory, checkpoint.checkpoint_id, executor_argv,
                                                  cancellation_check=lambda: _cancelled(job))
                        executed += 1
                if state.get('status') != 'pending':
                    _write(state_path, state)
            if state.get('status') != 'completed':
                terminal = state.get('status', 'failed')
                failures.extend(state.get('rejections') or [dict(code=terminal, path=unit_id, message=state.get('error', 'Semantic worker not completed'))])
                continue
            try:
                output = validate_semantic_output(dict(summary=state['summary'], proposals=state['proposals']))
                # Only a unit's own indexed inputs can support its claims; adding
                # a source elsewhere in the job cannot retroactively legitimize it.
                checked = _validate_proposals(output['proposals'], root, unit_manifest['source_index'], policy,
                                              unit_manifest.get('target_ids'), resource_version=resource_version)
                if checked['rejections']:
                    failures.extend(checked['rejections'])
                    terminal = 'invalid'
                    _write(state_path, dict(status='invalid', error='semantic validation rejected proposals', rejections=checked['rejections']))
                    continue
                for kind in proposals:
                    proposals[kind].extend(output['proposals'][kind])
            except (ValueError, TypeError, KeyError) as exc:
                terminal = 'invalid'
                rejection = dict(code='invalid_output', path=unit_id, message=str(exc))
                failures.append(rejection)
                _write(state_path, dict(status='invalid', error=str(exc), rejections=[rejection]))
        checked = _validate_proposals(proposals, root, manifest['source_index'], policy, resource_version=resource_version)
        checked['rejections'].extend(failures)
        _verify_sources(root, manifest)
        if _cancelled(job) or terminal == 'cancelled':
            result = _empty('cancelled', 'Knowledge job cancelled before completion')
        else:
            status = terminal or ('invalid' if checked['rejections'] else ('hit' if hits and not executed else 'ready'))
            result = dict(checked, cache_status=status, source_refs=manifest['source_refs'], wiki_materials={},
                          coverage=manifest['coverage'])
            if resource_version == 2:
                result['resource_contract_version'] = 2
        if cached is not None:
            saved_proposals = _read(_safe(job, 'proposals.json'))
            normalized_cache = dict(cached, cache_status='ready' if cached['cache_status'] == 'hit' else cached['cache_status'])
            normalized_result = dict(result, cache_status='ready' if result['cache_status'] == 'hit' else result['cache_status'])
            if saved_proposals != proposals or normalized_cache != normalized_result:
                raise ValueError('cached validation/provenance/coverage/status receipt mismatch')
            return result
        _write(job / 'proposals.json', proposals)
        if result['cache_status'] != 'pending':
            _write(job / 'result.json', result)
        return result
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return _empty('invalid', str(exc))
