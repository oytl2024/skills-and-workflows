from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from wqb.knowledge_experience_compile import compile_research_case_reports
from wqb.knowledge_contracts import parse_markdown_front_matter
from wqb.knowledge_paths import machine_resource_path
from wqb.semantic_contracts import SemanticPolicy
from wqb.resource_evidence import resource_contract_version


RAW_RESEARCH_RECORD_PATTERN = Path("raw") / "research" / "runs" / "*" / "research_record.md"
RESEARCH_COMPILE_JSON = Path("machine") / "reports" / "research_record_compile.json"
DEFAULT_MAX_MECHANISMS = 3
DEFAULT_MAX_CONDITIONS_PER_MECHANISM = 2
DEFAULT_SEMANTIC_TARGETS = 3
DEFAULT_SEMANTIC_SOURCES = 2
MAX_INDEXED_SOURCE_BYTES = 1024 * 1024
DESIGN_AUDIT_MAX_FIELDS = 30
DESIGN_AUDIT_MAX_SOURCES = 8


def _write_semantic_command_receipt(path: Path, row: dict) -> None:
    """Input: receipt Path/dict. Output: None; use existing bounded atomic Windows replacement."""
    from wqb.semantic_publication import _atomic_write
    _atomic_write(path.parent, path.name, json.dumps(row, ensure_ascii=False, indent=2).encode('utf-8'))


def _audit_resource_rows(path: Path, root: Path):
    """Input: resource/root Paths. Output: iterator[dict]. Read bounded lines without linked or missing resources."""
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('missing or outside audit resource: ' + path.name)
    for component in (path, *path.parents):
        if component == root.parent:
            break
        if component.is_symlink() or component.is_junction():
            raise ValueError('linked audit resource refused: ' + path.name)
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if not line.strip():
                continue
            if len(line.encode('utf-8')) > MAX_INDEXED_SOURCE_BYTES:
                raise ValueError('oversized audit resource row')
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('audit resource rows must be objects')
            yield row


def audit_hypothesis_resources(root: Path, scope: dict, template_requirements: list[dict]) -> dict:
    """Input: vault Path, scope dict, explicit V2 template dict list. Output: partial coverage dict; read-only, no research authority."""
    from wqb.knowledge_paths import existing_machine_resource_path
    from wqb.semantic_publication import validate_semantic_receipt
    from wqb.template_binding import _scope_matches
    if (not isinstance(scope, dict) or not isinstance(template_requirements, list)
            or any(not isinstance(row, dict) for row in template_requirements)):
        raise ValueError('audit requires scope and explicit template objects')
    root = Path(root)
    fields = []
    sampled_ids, conflicting_ids = set(), set()
    for row in _audit_resource_rows(existing_machine_resource_path(root, 'data_ledger'), root):
        if _scope_matches(row, scope):
            identity = row.get('field_id')
            if not isinstance(identity, str):
                raise ValueError('audit fields require string identities')
            if len(fields) < DESIGN_AUDIT_MAX_FIELDS:
                fields.append(row)
                sampled_ids.add(identity)
            elif identity in sampled_ids:
                conflicting_ids.add(identity)
    # Scan past the context cap so a later shadow identity cannot certify a sampled field.
    fields = [row for row in fields if row['field_id'] not in conflicting_ids]
    receipt, operators, _ = read_semantic_rows(root)
    needed = {path for row in fields for path in row.get('source_paths', []) if isinstance(path, str)}
    needed.update(ref['source_path'] for row in operators for ref in (row.get('definition') or {}).get('evidence_refs', [])
                  if isinstance(ref, dict) and isinstance(ref.get('source_path'), str))
    sources = list(_audit_resource_rows(existing_machine_resource_path(root, 'source_index'), root))
    by_path = {}
    for source in sources:
        path = source.get('path')
        if not isinstance(path, str):
            raise ValueError('audit source index requires string paths')
        if path in by_path and by_path[path] != source:
            raise ValueError('conflicting source index rows: ' + path)
        by_path[path] = source
    sources = list(by_path.values())
    sources.sort(key=lambda row: (row.get('path') not in needed,
                                 'operator' not in str(row.get('path', '')).lower(), str(row.get('path', ''))))
    selected = [row for row in sources if row.get('path') in needed or
                str(row.get('path', '')).startswith('raw/platform/') and
                'operator' in str(row.get('path', '')).lower()][:DESIGN_AUDIT_MAX_SOURCES]
    coverage = semantic_resource_coverage(dict(knowledge_root=root, field_rows=fields, operator_rows=operators,
        template_rows=template_requirements, source_index=selected,
        **({'resource_contract_version': 2} if resource_contract_version(receipt) == 2 else {})), scope)
    for identity in sorted(conflicting_ids):
        coverage['reasons'].append(dict(kind='field', identity=identity, code='conflicting_field_identity',
                                       reason='sampled expression identity also occurs beyond audit context limit'))
    selected_paths = {row.get('path') for row in selected}
    for path in sorted(needed - selected_paths):
        coverage['reasons'].append(dict(kind='source', identity=path, reason='unindexed or outside bounded audit context'))
    validate_semantic_receipt(root, receipt)
    return dict(status='usable_subset' if coverage['executable_bindings'] else 'blocked',
                partial=True, research_authorized=False, coverage=coverage,
                limits=dict(field_rows=DESIGN_AUDIT_MAX_FIELDS, source_rows=DESIGN_AUDIT_MAX_SOURCES),
                source_fingerprints=[dict(path=row.get('path'), content_hash=row.get('content_hash')) for row in selected],
                semantic_release_id=receipt['release_id'])


def _coverage_json_objects(text: str) -> list[dict]:
    """Input: source text str. Output: dict list. Read structured JSON/JSONL facts without interpreting prose."""
    _, body = parse_markdown_front_matter(text.replace('\r\n', '\n'))
    candidates = [body, *body.splitlines(), *re.findall(r'```json\s*\n(.*?)\n```', body, re.DOTALL)]
    objects = []
    for candidate in candidates:
        try:
            pending = [json.loads(candidate)]
        except ValueError:
            continue
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                objects.append(value)
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
    return objects


def _coverage_operator_supported(row: dict, texts: dict, *, source_index: dict | None = None,
                                 resource_contract_version: int = 1) -> bool:
    """Input: operator dict and verified source texts dict. Output: bool. Match typed facts to this exact source operator ID."""
    if type(resource_contract_version) is not int or resource_contract_version not in (1, 2):
        return False
    if resource_contract_version == 2:
        from wqb.resource_evidence import resolve_operator_definition
        return resolve_operator_definition(row, source_index, texts, resource_contract_version=2)['status'] == 'supported'
    from wqb.semantic_compilation import _markdown_definitions
    definition = row['definition']
    expected = {key: value for key, value in definition.items() if key != 'evidence_refs'}
    for ref in definition['evidence_refs']:
        text = texts[ref['source_path']]
        _, body = parse_markdown_front_matter(text.replace('\r\n', '\n'))
        if _markdown_definitions(body).get(row['operator']) == expected:
            continue
        supported = False
        for item in _coverage_json_objects(text):
            if item.get('operator', item.get('name', item.get('id'))) != row['operator']:
                continue
            fact = item.get('definition')
            if isinstance(fact, dict) and {key: value for key, value in fact.items() if key != 'evidence_refs'} == expected:
                supported = True
            elif fact is not None:
                return False
        if not supported:
            return False
    return bool(definition['evidence_refs'])


def _coverage_source_fields(text: str) -> list[tuple[dict, dict, dict]]:
    """Input: source text str. Output: (field, dataset, scope) dict tuples. Recognize wrapper and flat captures without inference."""
    facts = []
    for item in _coverage_json_objects(text):
        field, dataset, captured = item.get('field'), item.get('data_set'), item.get('scope')
        if all(isinstance(value, dict) for value in (field, dataset, captured)):
            facts.append((field, dataset, captured))
        elif {'id', 'description', 'type', 'dataset', 'region', 'delay', 'universe'} <= set(item):
            dataset = item['dataset']
            if isinstance(dataset, dict) and isinstance(dataset.get('id'), str):
                captured = {key: item[key] for key in ('instrument_type', 'region', 'delay', 'universe') if key in item}
                facts.append((item, dataset, captured))
    return facts


def _coverage_field_supported(row: dict, texts: dict, index: dict, scope: dict,
                              required_metadata: list[str] | tuple = (), *, resource_contract_version: int = 1) -> bool:
    """Input: field/source/index/scope dicts and required keys. Output: bool. Verify every consumed fact against exact raw identity/scope."""
    from wqb.semantic_contracts import PLATFORM_SOURCE_TYPES
    from wqb.template_binding import _known, _scope_matches
    from wqb.resource_evidence import resolve_timing_contract
    if type(resource_contract_version) is not int or resource_contract_version not in (1, 2):
        return False
    metadata = set(required_metadata) | ({'available_at'} if resource_contract_version == 1 else set())
    if 'available_at' in row:
        metadata.add('available_at')
    if resource_contract_version == 2:
        from wqb.template_binding import _available
        try:
            if 'available_at' in row:
                if not _available(row['available_at'], scope.get('as_of')):
                    return False
            if 'timing_contract' in row:
                if resolve_timing_contract(row['timing_contract'], row, scope, index, texts)['status'] != 'supported':
                    return False
                metadata.discard('timing_contract')
            elif 'available_at' not in row:
                return False
        except (ValueError, TypeError, KeyError):
            return False
    if row.get('field_type') == 'VECTOR':
        metadata.add('vector_grain')
    description = row.get('field_description', row.get('description'))
    if not _known(description) or row.get('field_type') not in ('MATRIX', 'VECTOR', 'GROUP'):
        return False
    if any(not _known(row.get(key)) for key in metadata):
        return False
    if any(not isinstance(row[key], str) for key in metadata & {'units', 'available_at', 'vector_grain'}):
        return False
    tags = row.get('semantic_tags', [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        return False
    paths = row.get('source_paths', [])
    if not isinstance(paths, list) or not paths or any(not isinstance(path, str) or path not in texts for path in paths):
        return False
    supported = False
    for path in paths:
        source = index.get(path, {})
        family = source.get('source_family', '')
        if (path not in texts or source.get('source_type') not in PLATFORM_SOURCE_TYPES
                or not family.startswith('raw/platform/') or not path.startswith(family + '/')):
            return False
        for field, dataset, captured in _coverage_source_fields(texts[path]):
            if (field.get('id') != row.get('field_id') or dataset.get('id') != row.get('dataset_id')
                    or not _scope_matches(dict(captured, dataset_id=dataset['id']), scope)):
                continue
            facts = dict(field)
            normalized = dict(dataset_id=dataset['id'], field_type=field.get('type'))
            normalized.update({key: captured[key] for key in ('instrument_type', 'region', 'universe', 'delay') if key in captured})
            for key, value in normalized.items():
                if key in field and (type(field[key]) is not type(value) or field[key] != value):
                    return False
                facts[key] = value
            if (field.get('type') != row.get('field_type') or field.get('description') != description
                    or any(type(facts.get(key)) is not type(row[key]) or facts.get(key) != row[key] for key in metadata)):
                return False
            source_tags = field.get('semantic_tags', [])
            if tags and (not isinstance(source_tags, list) or any(
                    tag.casefold() not in [value.casefold() for value in source_tags if isinstance(value, str)] for tag in tags)):
                return False
            supported = True
    return supported


def semantic_resource_coverage(resources: dict, scope: dict) -> dict:
    """Input: resource/scope dicts. Output: coverage dict; no mutation or writes.

    resources uses field_rows/operator_rows/source_index and optional template_rows,
    knowledge_root. Counts require verified bytes via existing body/full-hash rules,
    exact source facts and successful V2 binder calls, not freshness or row presence.
    Field inventory requires available_at (and VECTOR grain); bindings additionally
    verify every slot-required metadata key. Only source-verified tags reach binding.
    Without knowledge_root, byte verification is unavailable and counts fail closed.
    This is scoped compiler evidence, never reviewed/measured or live readiness.
    """
    from wqb.semantic_compilation import _material
    from wqb.semantic_contracts import validate_semantic_record
    from wqb.template_binding import bind_template, TemplateBindingError, _scope_matches
    if not isinstance(resources, dict) or not isinstance(scope, dict):
        raise ValueError('coverage requires resource and scope objects')
    version = resource_contract_version(resources)
    if 'evidence_pack' in resources and resource_contract_version(resources['evidence_pack']) != version:
        raise ValueError('coverage resource envelope and pack versions disagree')
    fields = resources.get('field_rows', [])
    operators = resources.get('operator_rows', [])
    templates = resources.get('template_rows', [])
    if any(not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
           for rows in (fields, operators, templates)):
        raise ValueError('coverage requires object row lists')
    sources = resources.get('source_index', {})
    if isinstance(sources, dict):
        sources = list(sources.values())
    if not isinstance(sources, list) or any(not isinstance(row, dict) for row in sources):
        raise ValueError('coverage requires source index objects')
    index, texts, reasons, conflicts = {}, {}, [], set()
    for source in sources:
        path = source.get('path')
        if not isinstance(path, str):
            reasons.append(dict(kind='source', identity='', reason='missing source path'))
            continue
        if path in index and index[path] != source:
            conflicts.add(path)
        index[path] = source
    root = resources.get('knowledge_root')
    for path, source in sorted(index.items()):
        try:
            if path in conflicts:
                raise ValueError('conflicting source index rows')
            if root is None:
                raise ValueError('source bytes unverified: knowledge_root required')
            _, texts[path] = _material(Path(root), source)
        except (OSError, ValueError, TypeError) as exc:
            reasons.append(dict(kind='source', identity=path, reason=str(exc)))
    verified_index = {path: index[path] for path in texts}
    scoped_fields = [row for row in fields if _scope_matches(row, scope)]
    verified_fields, verified_operators, verified_by_row = [], [], {}
    for row in scoped_fields:
        clean = dict(row, semantic_tags=[])
        if _coverage_field_supported(clean, texts, verified_index, scope, resource_contract_version=version):
            tags = row.get('semantic_tags', [])
            if isinstance(tags, list):
                clean['semantic_tags'] = [tag for tag in tags if isinstance(tag, str) and
                    _coverage_field_supported(dict(clean, semantic_tags=[tag]), texts, verified_index, scope,
                                              resource_contract_version=version)]
            verified_fields.append(clean)
            verified_by_row[id(row)] = clean
        else:
            reasons.append(dict(kind='field', identity=[row.get('dataset_id'), row.get('field_id')],
                                reason='missing source-bound description/type/grain/available_at or exact dataset/scope'))
        for path in row.get('source_paths', []) if isinstance(row.get('source_paths'), list) else []:
            if isinstance(path, str) and path in texts and not _coverage_source_fields(texts[path]):
                reason = dict(kind='source', identity=path, code='unsupported_source_format',
                              reason='field source is neither wrapper nor flat dataset/scope capture')
                if reason not in reasons:
                    reasons.append(reason)
    for row in operators:
        issues = validate_semantic_record(row, verified_index)
        if not issues and isinstance(row.get('definition'), dict):
            try:
                if _coverage_operator_supported(row, texts, source_index=verified_index, resource_contract_version=version):
                    verified_operators.append(row)
                    continue
            except (ValueError, KeyError, TypeError):
                pass
        reasons.append(dict(kind='operator', identity=row.get('operator'),
                            reason='missing or unsupported source-bound typed definition', issues=issues))
    executable = 0
    options = dict(resource_contract_version=version, evidence_context=dict(source_index=verified_index,
        source_texts=texts)) if version == 2 else {}
    for template in templates:
        try:
            if template.get('binding_version') != 2:
                raise TemplateBindingError('coverage requires explicit V2 binding')
            # Bind against all rows first, so unverified duplicates cannot disappear.
            binding = bind_template(template, fields, operators, scope, **options)
            verified_binding = bind_template(template, verified_fields, verified_operators, scope, **options)
            if verified_binding['bindings'] != binding['bindings']:
                raise TemplateBindingError('source-verified semantics select different bindings')
            selected = {(item['dataset_id'], item['field_id']) for item in binding['bindings'].values()}
            if any(id(row) not in verified_by_row for row in scoped_fields
                   if (row.get('dataset_id'), row.get('field_id')) in selected):
                raise TemplateBindingError('selected field has conflicting or unverified snapshot rows')
            for slot in template['input_slots']:
                chosen = binding['bindings'][slot['name']]
                for row in scoped_fields:
                    if (row.get('dataset_id'), row.get('field_id')) != (chosen['dataset_id'], chosen['field_id']):
                        continue
                    if not _coverage_field_supported(verified_by_row[id(row)], texts, verified_index, scope,
                                                     slot.get('required_metadata', []), resource_contract_version=version):
                        raise TemplateBindingError(slot['name'] + ': required metadata absent or conflicting in exact source')
            executable += 1
        except TemplateBindingError as exc:
            reasons.append(dict(kind='template', identity=template.get('template_id'), reason=str(exc)))
    if not templates:
        reasons.append(dict(kind='binding', identity='', reason='no explicit template_rows supplied; no executable bindings tested'))
    return dict(indexed_material=len(texts), verified_semantics=len(verified_fields)+len(verified_operators),
                executable_bindings=executable, scope_row_count=len(scoped_fields),
                unique_field_count=len({(row.get('dataset_id'), row.get('field_id')) for row in scoped_fields}),
                verified_field_rows=len(verified_fields), verified_operator_rows=len(verified_operators), reasons=reasons,
                evidence_boundary='verified source bytes, exact ID/scope-bound facts and V2 binder only; not review, measurement or live readiness')


def _published_semantic_provenance(root: Path) -> tuple[dict, list[dict]]:
    """Input: vault Path. Output: operator/source provenance tuple. Count only current rows backed by verified immutable publications."""
    from wqb.semantic_publication import validate_semantic_receipt
    current, operators, templates = read_semantic_rows(root)
    active = {'operator_ledger': {row['operator']: row for row in operators},
              'template_library': {row['template_id']: row for row in templates}}
    receipts = [current] if current['release_id'] else []
    for path in sorted((root/'machine/semantic_jobs').glob('*/command_result.json')):
        if path.is_symlink() or path.parent.is_symlink() or path.parent.is_junction():
            continue
        try:
            result = json.loads(path.read_bytes())
            receipt = result.get('release')
            if result.get('status') == 'completed' and isinstance(receipt, dict) and receipt.get('release_id'):
                receipts.append(validate_semantic_receipt(root, receipt))
        except (OSError, ValueError, TypeError):
            continue
    provenance = {}
    sources = []
    seen = set()
    for receipt in receipts:
        if receipt['release_id'] in seen:
            continue
        seen.add(receipt['release_id'])
        refs = {ref['path']: ref['sha256'] for ref in receipt['manifest']['source_refs']}
        for resource, identity in (('operator_ledger', 'operator'), ('template_library', 'template_id')):
            raw = Path(receipt['paths'][resource]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != receipt['digests'][resource]:
                raise ValueError('published semantic bytes changed during selection')
            for row in [json.loads(line) for line in raw.splitlines() if line.strip()]:
                name = row.get(identity)
                if row.get('semantic_version') != 2 or active[resource].get(name) != row:
                    continue
                for ref in row.get('evidence_refs', []):
                    if ref.get('source_path') in refs:
                        verified = dict(ref, file_sha256=refs[ref['source_path']])
                        sources.append(verified)
                        if resource == 'operator_ledger':
                            provenance.setdefault(name, []).append(verified)
        validate_semantic_receipt(root, receipt)
    return provenance, sources


def _select_semantic_sources(root: Path, rows: list[dict], coverage: dict | None = None) -> list[dict]:
    """Input: vault Path/index list/optional coverage dict. Output: bounded next missing/stale selection. Never auto-loop compilation."""
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('source index requires object rows')
    provenance, source_provenance = _published_semantic_provenance(root)
    inventory = []
    gaps = []
    for row in sorted(rows, key=lambda item: (str(item.get('captured_at', '')), str(item.get('path', ''))), reverse=True):
        relative = row.get('path', '')
        if not isinstance(relative, str):
            continue
        research = relative.startswith('raw/research/')
        if not research and not (relative.startswith('raw/platform/') and 'operator' in relative.lower()):
            continue
        parts = relative.split('/')
        if '\\' in relative or ':' in relative or any(part in ('', '.', '..') for part in parts):
            raise ValueError('unsafe indexed source path')
        if any(fragment in part.lower() for part in parts for fragment in ('.env', 'credential', 'secret', 'token', 'password', 'private', 'key', '.ssh', '.git', 'auth', 'session', 'cookie', 'config')):
            raise ValueError('sensitive indexed source path')
        path = root
        for part in parts:
            path = path / part
            if path.is_symlink() or path.is_junction():
                raise ValueError('linked indexed source path')
        if path.suffix.lower() != '.md' or not path.is_file() or path.stat().st_size > MAX_INDEXED_SOURCE_BYTES:
            if research:
                gaps.append(dict(path=relative, reason='Unselected research aggregate or unavailable/oversized Markdown remains unmeasured; compatible indexed experiment dependency required for measurement.'))
            continue
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        text = raw.decode('utf-8')
        _, body = parse_markdown_front_matter(text.replace('\r\n', '\n'))
        headings = re.findall(r'^###\s+`?([A-Za-z_][A-Za-z0-9_.-]*)`?\s*$', body, re.MULTILINE)
        if not headings and not research:
            continue
        targets = [] if research else (row.get('target_ids') or sorted(set(headings)))
        def matches(ref):
            """Input: published evidence dict. Output: bool. Match indexed content, real capture date and actual full bytes."""
            return (ref.get('source_path') == relative and ref.get('sha256') == row.get('content_hash')
                    and ref.get('capture_date') == str(row.get('captured_at', ''))[:10] and ref.get('file_sha256') == digest)
        covered = {target for target in targets if any(matches(ref) for ref in provenance.get(target, []))}
        research_covered = research and any(matches(ref) for ref in source_provenance)
        inventory.append((row, targets, covered, research, research_covered))
    missing = [(row, [target for target in targets if target not in covered])
               for row, targets, covered, research, research_covered in inventory
               if (research and not research_covered) or (not research and len(covered) < len(targets))]
    choices = missing or [(row, targets) for row, targets, _, _, _ in inventory]
    selected = [dict(row, target_ids=targets[:DEFAULT_SEMANTIC_TARGETS]) if targets else dict(row)
                for row, targets in choices[:DEFAULT_SEMANTIC_SOURCES]]
    if coverage is not None:
        total = sum(len(targets) for _, targets, _, _, _ in inventory)
        count = sum(len(covered) for _, _, covered, _, _ in inventory)
        coverage.update(partial=True, indexed_target_count=total, covered_target_count=count,
                        remaining_target_count=total-count, selected_target_count=sum(len(row.get('target_ids', [])) for row in selected),
                        indexed_research_source_count=sum(research for _, _, _, research, _ in inventory),
                        remaining_research_source_count=len(gaps)+sum(research and not covered for _, _, _, research, covered in inventory),
                        unsupported_research_source_count=len(gaps), source_gaps=gaps,
                        target_scope='indexed operator headings only; definitions and research coverage remain separately incomplete')
    return selected


def _persist_template_families(templates: list[dict], grouping: list[dict]) -> list[dict]:
    """Input: validated template/group dict lists. Output: copied records. Preserve canonical family beyond transient group envelopes."""
    families = {}
    for group in grouping:
        if group.get('kind') == 'templates':
            families.setdefault(group['record_id'], set()).add(group['mechanism_id'])
    output = []
    for row in templates:
        family = row.get('template_family')
        if not family and row.get('template_id') in families:
            choices = families[row['template_id']]
            if len(choices) != 1:
                raise ValueError('ambiguous canonical mechanism for template')
            family = next(iter(choices))
        output.append(dict(row, template_family=family) if family else dict(row))
    return output


def _semantic_row_source_paths(row: dict) -> set[str]:
    """Input: semantic row dict. Output: source path set. Include definitions, conditional uses and measured dependencies."""
    refs = list(row.get('evidence_refs', []))
    refs.extend((row.get('definition') or {}).get('evidence_refs', []))
    for use in row.get('conditional_uses', []):
        refs.extend(use.get('evidence_refs', []))
    return {path for ref in refs for path in [ref['source_path'], *ref.get('experiment_refs', [])]}


def _merge_publication_sources(current: dict, retained: list[dict], new_refs: list[dict]) -> list[dict]:
    """Input: active receipt/retained rows/new full-byte refs. Output: closed ref list. Reject changed dependencies of retained facts."""
    needed = set().union(*(_semantic_row_source_paths(row) for row in retained)) if retained else set()
    old = {ref['path']: ref['sha256'] for ref in current.get('manifest', {}).get('source_refs', []) if ref['path'] in needed}
    for ref in new_refs:
        if ref['path'] in old and old[ref['path']] != ref['sha256']:
            raise ValueError('retained semantic source changed: ' + ref['path'] + '; recompile affected records before publication')
        old[ref['path']] = ref['sha256']
    if current.get('release_id') and needed - set(old):
        raise ValueError('retained semantic source provenance missing: ' + ', '.join(sorted(needed-set(old))))
    return [dict(path=path, sha256=old[path]) for path in sorted(old)]


def _validate_semantic_publish_health(root: Path, wiki: dict[str, str]) -> None:
    """Input: vault Path/replacement wiki texts. Output: None. Reject mixed authority and unsafe or broken local inline wiki links without cleanup."""
    from wqb.knowledge_clean_compile import evaluate_clean_knowledge_structure
    issues = [issue for issue in evaluate_clean_knowledge_structure(root)['issues']
              if issue['code'] != 'semantic_wiki_version_mismatch']
    if issues:
        raise ValueError('unclean semantic publication: ' + json.dumps(issues, ensure_ascii=False))
    pages = {path.relative_to(root).as_posix(): path.read_text(encoding='utf-8')
             for path in (root/'wiki').rglob('*.md') if path.relative_to(root).as_posix() not in wiki}
    pages.update(wiki)
    for relative, text in pages.items():
        for target in re.findall(r'(?<!\\)\[[^\]\n]*\]\(([^)\n]+)\)', text):
            url = urlsplit(target.strip().strip('<>'))
            if url.scheme in {'https', 'http', 'mailto'}:
                continue
            if url.scheme or url.netloc or '\\' in url.path:
                raise ValueError('invalid wiki link in ' + relative)
            if not url.path:
                continue
            path = (root/relative).parent/unquote(url.path)
            if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError('broken or outside wiki link in ' + relative + ': ' + target)


def read_semantic_rows(root: Path) -> tuple[dict, list[dict], list[dict]]:
    """Input: vault Path. Output: receipt/operator/template tuple. Verify paired bytes before and after parsing."""
    from wqb.semantic_publication import read_semantic_release, validate_semantic_receipt
    receipt = read_semantic_release(root)
    rows = []
    for name in ('operator_ledger', 'template_library'):
        path = Path(receipt['paths'][name])
        exists = path.exists()
        data = path.read_bytes() if exists else b''
        digest = hashlib.sha256(data).hexdigest() if exists else None
        if digest != receipt['digests'][name]:
            raise ValueError('semantic resource bytes changed during read')
        parsed = [json.loads(line) for line in data.splitlines() if line.strip()]
        if any(not isinstance(row, dict) for row in parsed):
            raise ValueError('semantic resource requires object rows')
        rows.append(parsed)
    validate_semantic_receipt(root, receipt)
    return receipt, rows[0], rows[1]


def _merge_semantic_rows(old: list[dict], new: list[dict], key: str) -> list[dict]:
    """Input: old/new object lists, identity str. Output: merged list. Preserve unrelated rows and immutable template IDs."""
    merged = {}
    lineage = {}
    for row in [*old, *new]:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity:
            raise ValueError(f'missing semantic identity: {key}')
        existing = merged.get(identity)
        if existing is not None and existing != row and key == 'template_id':
            raise ValueError('changed template content requires a unique template_id and hypothesis_id/version lineage')
        if existing is not None and key == 'operator':
            row = _merge_operator_row(existing, row)
        if key == 'template_id' and row.get('hypothesis_id'):
            version = row.get('hypothesis_version', 1)
            if type(version) is not int or version < 1:
                raise ValueError('hypothesis_version must be a positive integer')
            parent = (row['hypothesis_id'], version)
            if parent in lineage and lineage[parent] != row:
                raise ValueError('changed hypothesis content requires a new hypothesis_version and unique template_id')
            lineage[parent] = row
        merged[identity] = row
    return [merged[identity] for identity in sorted(merged)]


def _merge_operator_row(old: dict, new: dict) -> dict:
    """Input: compatible old/new operator dicts. Output: merged dict. Accumulate uses/provenance without erasing documented metadata."""
    merged = dict(old)
    if old.get('definition_basis') and new.get('definition_basis') and old['definition_basis'] != new['definition_basis']:
        raise ValueError('conflicting operator definition basis; explicit reviewed migration required')
    for key, value in new.items():
        previous = old.get(key)
        if key == 'definition' and previous and value:
            if {name: item for name, item in previous.items() if name != 'evidence_refs'} != {
                    name: item for name, item in value.items() if name != 'evidence_refs'}:
                raise ValueError('conflicting operator typed definitions; explicit reviewed migration required')
            refs = list(previous.get('evidence_refs', []))
            refs.extend(ref for ref in value.get('evidence_refs', []) if ref not in refs)
            merged[key] = dict(previous, evidence_refs=refs)
        elif key == 'raw_definition' and previous and value and previous != value:
            raise ValueError('conflicting operator raw definitions; explicit reviewed migration required')
        elif isinstance(value, list) and isinstance(previous, list):
            merged[key] = list(previous)
            merged[key].extend(item for item in value if item not in merged[key])
        elif key in {'semantic_version', 'binding_version'}:
            merged[key] = max(previous or 1, value)
        elif key == 'semantic_status' and previous in {None, '', 'legacy/unreviewed', 'unreviewed'}:
            merged[key] = value
        elif previous is None or previous == '' or previous == {}:
            merged[key] = value
    if merged.get('definition_basis'):
        digest = hashlib.sha256(json.dumps(merged.get('definition'), sort_keys=True,
            separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')).hexdigest()
        if merged['definition_basis']['definition_digest'] != digest:
            raise ValueError('merged operator definition no longer matches its source-backed basis')
    return merged


def _repair_active_semantic_wiki(root: Path, expected: dict) -> dict:
    """Input: vault Path/expected active receipt dict. Output: active receipt. Restore exact active wiki bytes under publication lock, never its pointer."""
    from wqb.semantic_publication import (_acquire_lock, _release_lock, _atomic_write,
                                          read_semantic_release, _verify_sources)
    lock = _acquire_lock(root)
    try:
        active = read_semantic_release(root)
        if active != expected:
            raise ValueError('active semantic release changed before wiki repair; retry explicit maintenance')
        if active['release_id'] is None:
            return active
        pages = {}
        for target, entry in active['manifest']['wiki'].items():
            raw = (Path(active['manifest_path']).parent/entry['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise ValueError('active immutable wiki bytes changed during repair')
            pages[target] = raw
        _validate_semantic_publish_health(root, {target: raw.decode('utf-8') for target, raw in pages.items()})
        _verify_sources(root, active['manifest']['source_refs'])
        for target, raw in pages.items():
            if not (root/target).is_file() or (root/target).read_bytes() != raw:
                _atomic_write(root, target, raw)
        from wqb.knowledge_clean_compile import evaluate_clean_knowledge_structure
        if not evaluate_clean_knowledge_structure(root)['clean']:
            raise ValueError('active semantic wiki repair did not restore clean publication health')
        return active
    finally:
        _release_lock(lock)


def _require_semantic_merge_version(active: dict, requested: int) -> None:
    """Input: active receipt dict/requested int. Output: None or ValueError; reject implicit resource downgrade."""
    if resource_contract_version(active) > requested:
        raise ValueError('resource contract downgrade blocked: requested v1 cannot merge active v2; '
                         'use explicit v2 compilation or a separately reviewed migration')


def _compile_prepared_semantic_job(root: Path, job: Path, config: dict, policy: Any, result: dict) -> dict:
    """Input: vault/job Paths, config/policy/result. Output: command dict. Journal publication and preserve completed replay evidence."""
    from wqb.semantic_compilation import compile_semantic_proposals
    from wqb.semantic_publication import stage_semantic_release, publish_semantic_release, read_semantic_release, validate_semantic_receipt
    from wqb.knowledge_experience_compile import render_semantic_wiki_materials
    _write = _write_semantic_command_receipt
    from wqb.lockfile import json_lock_transition_guard
    previous = {}
    try:
        version = resource_contract_version(config)
        _require_semantic_merge_version(read_semantic_release(root), version)
        previous = json.loads((job/'command_result.json').read_text()) if (job/'command_result.json').exists() else {}
        if not isinstance(previous, dict):
            raise ValueError('semantic command receipt must be an object')
        if isinstance(previous.get('completed_publication'), dict):
            previous = previous['completed_publication']
        if previous.get('status') != 'completed' and (job/'publication_intent.json').exists():
            previous = json.loads((job/'publication_intent.json').read_text(encoding='utf-8'))
        if previous.get('status') not in {'completed', 'publishing', 'cancelled'} and previous.get('terminal_content_key') != 'cancelled':
            _write(job / 'command_result.json', dict(result, status='running'))
        compiled = compile_semantic_proposals(job, config.get('executor_argv', []), policy)
        if compiled.get('cache_status') in {'ready', 'hit'} and resource_contract_version(compiled) != version:
            raise ValueError('compiled resource contract version differs from requested producer version')
        result.update(rejections=compiled.get('rejections', []), cache_status=compiled.get('cache_status'),
                      coverage={**(compiled.get('coverage') or {}), **result['coverage'], 'partial': True})
        if compiled.get('cache_status') == 'cancelled':
            result.update(status='cancelled', error='Knowledge compile cancelled; its content key remains terminal.')
            if previous.get('status') == 'cancelled' or previous.get('terminal_content_key') == 'cancelled':
                result.update(status='blocked', terminal_content_key='cancelled',
                              error='Previously cancelled content key remains stopped; no automatic retry or publication.',
                              next_action='Preserve Stop. Request approved maintenance to inspect the cancelled content key, or explicitly compile genuinely changed indexed material/policy. Do not clear cancellation or cache automatically.')
        elif compiled.get('cache_status') not in {'ready', 'hit'}:
            raise ValueError('semantic compiler did not produce a validated ready result: ' + json.dumps(result['rejections']))
        elif not compiled['validated_operators'] and not compiled['validated_templates']:
            raise ValueError('no validated semantic proposals; source coverage remains incomplete')
        else:
            with json_lock_transition_guard(root / 'machine/semantic_command', 2.0, 0.02, 'semantic command busy'):
                current, operators, templates = read_semantic_rows(root)
                _require_semantic_merge_version(current, version)
                if previous.get('status') == 'completed':
                    validate_semantic_receipt(root, previous['release'])
                    current = _repair_active_semantic_wiki(root, current)
                    return dict(previous, cache_status='hit', active_release=current, coverage=result['coverage'])
                if previous.get('status') == 'publishing':
                    staged = validate_semantic_receipt(root, previous['release'])
                    if current != staged and current != previous.get('base_release'):
                        raise ValueError('interrupted semantic publication superseded; preserve current release')
                    control = json.loads((job/'control.json').read_text()) if (job/'control.json').exists() else {}
                    if current != staged and control.get('cancelled') is True:
                        return dict(result, status='cancelled')
                    # Reuse the journaled generation, including its original wiki,
                    # to finish a pointer/wiki interruption without a new release.
                    wiki = {path: (Path(staged['manifest_path']).parent/entry['path']).read_text(encoding='utf-8')
                            for path, entry in staged['manifest']['wiki'].items()}
                    _validate_semantic_publish_health(root, wiki)
                    with json_lock_transition_guard(job/'publication_guard', 2.0, 0.02, 'semantic publication busy'):
                        control = json.loads((job/'control.json').read_text()) if (job/'control.json').exists() else {}
                        if current != staged and control.get('cancelled') is True:
                            return dict(result, status='cancelled')
                        receipt = publish_semantic_release(root, staged)
                        result.update(status='completed', release=receipt)
                        _write(job/'command_result.json', result)
                        return result
                proposals = dict(compiled)
                proposals['validated_operators'] = _merge_semantic_rows(operators, compiled['validated_operators'], 'operator')
                new_templates = _persist_template_families(compiled['validated_templates'], compiled.get('grouping', []))
                proposals['validated_templates'] = _merge_semantic_rows(templates, new_templates, 'template_id')
                all_rows = proposals['validated_operators'] + proposals['validated_templates']
                proposals['source_refs'] = _merge_publication_sources(current, all_rows, compiled['source_refs'])
                proposals['wiki_materials'] = render_semantic_wiki_materials(proposals, config['generated_at'])
                _validate_semantic_publish_health(root, proposals['wiki_materials'])
                staged = stage_semantic_release(root, proposals, config['generated_at'])
                with json_lock_transition_guard(job/'publication_guard', 2.0, 0.02, 'semantic publication busy'):
                    control = json.loads((job/'control.json').read_text()) if (job/'control.json').exists() else {}
                    if control.get('cancelled') is True:
                        result['status'] = 'cancelled'
                    else:
                        if read_semantic_release(root) != current:
                            raise ValueError('active semantic release changed; retry explicit compile against current pair')
                        intent = dict(result, status='publishing', release=staged, base_release=current)
                        _write(job/'publication_intent.json', intent)
                        _write(job / 'command_result.json', intent)
                        receipt = publish_semantic_release(root, staged)
                        result.update(status='completed', release=receipt)
                        _write(job/'command_result.json', result)
    except (OSError, ValueError, TypeError, RuntimeError, TimeoutError) as error:
        result.update(status='blocked', error=str(error))
        if isinstance(previous, dict) and previous.get('status') == 'completed':
            result['completed_publication'] = previous
    return result


def compile_semantic_knowledge_command(root: Path, config: dict) -> dict:
    """Input: vault Path/config dict. Output: durable job/release/coverage dict. Run one explicit bounded maintenance request."""
    from wqb.semantic_contracts import SemanticPolicy
    from wqb.semantic_compilation import prepare_semantic_job
    from wqb.semantic_publication import read_semantic_release
    from wqb.maintenance_notifications import dispatch_knowledge_notification
    _write = _write_semantic_command_receipt
    from wqb.lockfile import json_lock_transition_guard
    root = Path(root)
    now = config.get('generated_at') or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    config = dict(config, generated_at=now)
    job = root / 'machine/semantic_jobs/requests'
    result = dict(status='blocked', job=str(job), release=None, coverage=dict(partial=True),
                  rejections=[], notification=dict(status='not_needed'), error='')
    try:
        limits = dict(max_mechanisms=config.get('max_mechanisms', DEFAULT_MAX_MECHANISMS),
                      max_conditions_per_mechanism=config.get('max_conditions_per_mechanism', DEFAULT_MAX_CONDITIONS_PER_MECHANISM))
        if any(type(value) is not int or value < 1 for value in limits.values()):
            raise ValueError('semantic policy limits require positive integers')
        policy = SemanticPolicy(**limits)
        version = resource_contract_version(config)
        _require_semantic_merge_version(read_semantic_release(root), version)
        refs = config.get('source_refs')
        indexed = None
        if refs is None:
            indexed = _read_existing_research_rows(machine_resource_path(root, 'source_index'))
            refs = _select_semantic_sources(root, indexed, result['coverage'])
        if not refs and config.get('source_refs') is None:
            raise ValueError('source index has no supported captured operator sections or research records; source coverage remains incomplete')
        prepared = prepare_semantic_job(root, refs, policy, **({'resource_version': 2} if version == 2 else {}))
        with json_lock_transition_guard(prepared/'command_guard', 2.0, 0.02, 'semantic job busy'):
            result['job'] = str(prepared)
            result = _compile_prepared_semantic_job(root, prepared, config, policy, result)
            _write(prepared/'command_result.json', result)
            if indexed is not None and result['status'] == 'completed':
                coverage = {}
                _select_semantic_sources(root, indexed, coverage)
                coverage['selected_target_count'] = sum(len(row.get('target_ids', [])) for row in refs)
                result['coverage'].update(coverage)
                _write(prepared/'command_result.json', result)
            if result['status'] == 'blocked':
                result['notification'] = dispatch_knowledge_notification(prepared, now)
                _write(prepared/'command_result.json', result)
            return result
    except (OSError, ValueError, TypeError, RuntimeError, TimeoutError) as error:
        # Preparation/lock errors have their own request evidence; they must not
        # overwrite another running job or its completed publication journal.
        identity = dict(error=str(error), policy={key: config.get(key) for key in ('max_mechanisms', 'max_conditions_per_mechanism')},
                        source_refs=config.get('source_refs'))
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
        job = root/'machine/semantic_jobs/requests'/key
        result.update(status='blocked', job=str(job), error=str(error))
    _write(job/'command_result.json', result)
    result['notification'] = dispatch_knowledge_notification(job, now)
    _write(job/'command_result.json', result)
    return result


def prepare_hypothesis_design_job(root: Path, evidence_pack: dict, policy: SemanticPolicy) -> Path:
    """Input: vault Path/original evidence dict/SemanticPolicy. Output: frozen proposal job Path."""
    from wqb.semantic_compilation import prepare_design_job
    return prepare_design_job(root, evidence_pack, policy)


def compile_hypothesis_design_command(root: Path, config: dict) -> dict:
    """Input: vault Path/config dict. Output: bounded proposal/attachment/diagnostic dict.

    Required config keys: evidence_pack (the original Task2 pack), resources
    (exact field_rows/operator_rows/source_index/source_texts/evidence_pack/settings).
    Scope is taken only from evidence_pack; resources must match it and include
    complete build_settings output and actual full source strings. Optional keys:
    executor_argv (default []), max_mechanisms (3), max_conditions_per_mechanism (2).
    No executor means pending without an attempt, never a default model call.
    Optional nonempty mechanism_query selects relevant maintenance-view observations;
    mechanism_maximum is an exact int0..12. Only complete selected records enter
    the frozen key/support files, never the global view digest or omitted count.
    Empty selection preserves the original input contract. Oversize context fails
    closed without truncation, a larger cap, or empirical/lifecycle promotion.

    Results contain status/job/cache_status/designs/drafts/attachments/rejections/
    research_authorized=False. ready or hit maps to completed; pending/cancelled
    retain their names; failed/invalid maps to blocked. Successful replay verifies
    sources, frozen copies and reconstruction, with no new checkpoint/model call.
    Failed, malformed, interrupted and cancelled unchanged keys are terminal;
    clearing control.json is not retry authority. Genuinely changed evidence,
    schema/compiler/context versions, policy or resources creates a new key.
    Preparation errors return blocked with job=None. Only job artifacts are written;
    completed means proposed, not reviewed/published/measured or research-ready.
    """
    from wqb.semantic_contracts import SemanticPolicy
    from wqb.semantic_compilation import prepare_design_job, compile_design_proposals, _design_empty, _write
    from wqb.lockfile import json_lock_transition_guard
    result = dict(_design_empty('invalid', 'Design job not prepared'), status='blocked', job=None)
    try:
        policy = SemanticPolicy(max_mechanisms=config.get('max_mechanisms', DEFAULT_MAX_MECHANISMS),
            max_conditions_per_mechanism=config.get('max_conditions_per_mechanism', DEFAULT_MAX_CONDITIONS_PER_MECHANISM))
        if 'resources' not in config:
            raise ValueError('explicit complete Task3 resources required')
        feedback = None
        if 'mechanism_query' in config:
            from wqb.mechanism_evidence import select_mechanism_context, MAX_CONTEXT
            from wqb.semantic_compilation import _read, _safe
            query = config['mechanism_query']
            if not isinstance(query, dict) or not query:
                raise ValueError('mechanism_query requires explicit relevant constraints')
            view_path = _safe(Path(root).resolve(), 'machine/mechanism_evidence.json')
            view = _read(view_path) if view_path.exists() else dict(groups=[], input_digest='absent')
            feedback = select_mechanism_context(view, query, config.get('mechanism_maximum', MAX_CONTEXT))['items']
        job = prepare_design_job(root, config['evidence_pack'], policy, config['resources'], mechanism_feedback=feedback)
        result['job'] = str(job)
        with json_lock_transition_guard(job / 'command_guard', 2.0, 0.02, 'design job busy'):
            compiled = compile_design_proposals(job, config.get('executor_argv', []), policy)
            status = {'ready': 'completed', 'hit': 'completed', 'pending': 'pending',
                      'cancelled': 'cancelled'}.get(compiled['cache_status'], 'blocked')
            result = dict(compiled, job=str(job), status=status)
            _write(job / 'command_result.json', result)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, TimeoutError) as exc:
        result = dict(_design_empty('invalid', str(exc)), status='blocked', job=result['job'])
    return result


def _extract_line_value(text: str, label: str) -> str:
    """Input: markdown text and label. Output: value string. Extract a simple bullet field."""
    prefix = f"- {label}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip().strip("`")
    return ""


def _record_summary(path: Path) -> dict[str, Any]:
    """Input: raw research record path. Output: summary dict. Extract compact compile metadata."""
    text = path.read_text(encoding="utf-8")
    metadata, body = parse_markdown_front_matter(text)
    benchmark_label = "near_miss" if "near_miss" in body else ""
    return {
        "run_id": _extract_line_value(body, "Run ID") or path.parent.name,
        "objective": _extract_line_value(body, "Objective"),
        "path": str(path),
        "preview": "\n".join(body.splitlines()[:12]),
        "case_reason": "near_miss" if benchmark_label else "representative_failure",
        "triage": [{"benchmark_label": benchmark_label, "failed": []}] if benchmark_label else [],
        "content_hash": str(metadata.get("content_hash", "")),
    }


def _read_existing_research_rows(path: Path) -> list[dict[str, Any]]:
    """Input: machine ledger path. Output: existing row dicts. Preserve richer synced rows when present."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_research_rows(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Input: machine ledger path and rows. Output: path. Write deterministic research record JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    from wqb.semantic_publication import _atomic_write
    content = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows).encode('utf-8')
    if not path.exists() or path.read_text(encoding='utf-8') != content.decode('utf-8'):
        _atomic_write(path.parent, path.name, content)
    return path


def _compiled_row_from_raw_summary(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    """Input: raw summary and timestamp. Output: machine ledger row. Convert one raw record snapshot."""
    return {
        "run_id": str(row["run_id"]),
        "objective": str(row["objective"]),
        "backtest": [],
        "triage": row["triage"],
        "repair": {},
        "candidate_gate": [],
        "user_approval": [],
        "approved_queue": [],
        "manual_submission_status": [],
        "synced_at": generated_at,
        "final_state": "compiled_from_raw",
        "case_reason": str(row["case_reason"]),
        "raw_source_path": str(row["path"]),
        "content_hash": str(row.get("content_hash", "")),
    }


def compile_research_records(
    knowledge_root: str | Path,
    generated_at: str | None = None,
    max_records: int = 100,
) -> dict[str, Any]:
    """Input: knowledge root and limit. Output: summary dict. Compile raw research records into canonical ledgers."""
    from wqb.lockfile import json_lock_transition_guard
    from wqb.research_record import RECORD_LOCK_TIMEOUT_SECONDS, RECORD_LOCK_SLEEP_SECONDS
    path = machine_resource_path(knowledge_root, 'research_records')
    path.parent.mkdir(parents=True, exist_ok=True)
    with json_lock_transition_guard(path, RECORD_LOCK_TIMEOUT_SECONDS, RECORD_LOCK_SLEEP_SECONDS, 'research ledger is busy'):
        return _compile_research_records_locked(knowledge_root, generated_at, max_records)


def _compile_research_records_locked(knowledge_root: str | Path, generated_at: str | None, max_records: int) -> dict:
    """Input: root Path/string, optional timestamp, limit int. Output: maintenance summary under ledger guard."""
    root = Path(knowledge_root)
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for name in ("raw", "machine", "wiki"):
        (root / name).mkdir(parents=True, exist_ok=True)
    raw_paths = sorted(
        root.glob(str(RAW_RESEARCH_RECORD_PATTERN).replace("\\", "/")),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:max_records]
    rows = [_record_summary(path) for path in raw_paths]
    ledger_path = machine_resource_path(root, "research_records")
    existing_rows = _read_existing_research_rows(ledger_path)
    # A raw Markdown summary cannot replace structured workflow evidence, even a Repair-only record.
    structured_runs = {
        str(row.get('run_id', ''))
        for row in existing_rows
        if row.get('final_state') != 'compiled_from_raw'
        and not row.get('raw_source_path')
        and any(key in row for key in ('backtest', 'triage', 'repair', 'candidate_gate',
                                       'user_approval', 'approved_queue', 'manual_submission_status'))
    }
    compiled_snapshots = {
        (str(row.get("raw_source_path", "")), str(row.get("content_hash", "")))
        for row in existing_rows
        if str(row.get("raw_source_path", ""))
    }
    output_rows = list(existing_rows)
    for row in rows:
        if str(row['run_id']) in structured_runs:
            continue
        identity = (str(row["path"]), str(row.get("content_hash", "")))
        if identity not in compiled_snapshots:
            output_rows.append(_compiled_row_from_raw_summary(row, generated))
            compiled_snapshots.add(identity)
    _write_research_rows(ledger_path, output_rows)
    from wqb.mechanism_evidence import build_mechanism_evidence
    mechanism_path = machine_resource_path(root, 'mechanism_evidence')
    _write_semantic_command_receipt(mechanism_path, build_mechanism_evidence(output_rows, []))
    case_report_paths = compile_research_case_reports(root, generated, max_records)
    output_json = root / RESEARCH_COMPILE_JSON
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(
            {
                "report_type": "research_record_compile",
                "generated_at": generated,
                "record_count": len(rows),
                "ledger_path": str(ledger_path),
                "case_report_paths": [str(path) for path in case_report_paths],
                "source_paths": [row["path"] for row in rows],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "generated_at": generated,
        "record_count": len(rows),
        "markdown_path": str(case_report_paths[0]) if case_report_paths else "",
        "case_report_paths": [str(path) for path in case_report_paths],
        "json_path": str(output_json),
        "mechanism_evidence_path": str(mechanism_path),
        "source_paths": [row["path"] for row in rows],
    }
