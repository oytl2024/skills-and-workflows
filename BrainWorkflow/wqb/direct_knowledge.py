"""Small new-start DIRECT reader: integrity, not knowledge confidence admission."""
from copy import deepcopy
import hashlib
from pathlib import Path

from wqb.knowledge_contracts import parse_markdown_front_matter
from wqb.semantic_compilation import _safe


DIRECT_POLICY = 'direct_knowledge_v1'
MAX_SOURCE_BYTES = 4_000_000
MAX_CONTEXT_BYTES = 16_000_000
MAX_INDEX_ROWS = 4096
MAX_OPERATORS = 4096
WARNING = ('DIRECT knowledge: source age, semantics, timing and coverage may be old, unknown or incomplete; '
           'these are warnings, not verified facts. Technical compilation remains mandatory.')


def direct_knowledge_enabled(value: dict) -> bool:
    """Input: config/resource dict. Output: bool; reject malformed explicit new-start versions."""
    if 'direct_knowledge_version' in value:
        version = value['direct_knowledge_version']
        if type(version) is not int or version != 1:
            raise ValueError('direct_knowledge_version requires integer 1')
        return True
    return value.get('resource_admission_policy') == DIRECT_POLICY


def read_direct_source(root: Path, row: dict) -> tuple[dict, str]:
    """Input: vault Path/indexed source dict. Output: original metadata/text with verified input hashes, no receipts."""
    path = _safe(root, row['path'])
    if not row['path'].startswith(('raw/', 'wiki/')):
        raise ValueError('DIRECT source outside knowledge boundaries')
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('DIRECT source exceeds byte bound')
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError('DIRECT source exceeds byte bound')
    text, content = raw.decode('utf-8'), raw
    if path.suffix.lower() == '.md':
        metadata, body = parse_markdown_front_matter(text.replace('\r\n', '\n'))
        if metadata:
            content = body.encode('utf-8')
            for key in ('content_hash', 'captured_at', 'source_type', 'source_family'):
                if key in metadata and str(metadata[key]) != row.get(key):
                    raise ValueError('DIRECT source header/index mismatch: ' + key)
    digest = hashlib.sha256(raw).hexdigest()
    if (hashlib.sha256(content).hexdigest() != row.get('content_hash', '').lower()
            or row.get('file_sha256', digest).lower() != digest):
        raise ValueError('DIRECT source bytes changed')
    return dict(row, file_sha256=digest), text


def read_direct_resources(root: Path, scope: dict, count: int, *, settings: dict,
                          max_fields_per_lane: int, selected_rows=None) -> tuple[list, list]:
    """Input: vault/scope/settings and bounded selection. Output: compiler resource/warning lists; no history reads."""
    from wqb.hypothesis_design import INTENTS
    from wqb.research_resource_catalog import (_rows, _identity, _scope_matches, _phrases, _size,
        _optional_published_operators, _operator_facts)
    diagnostics, state = [], {}
    index = {}
    for row in _rows(root, 'source_index', diagnostics, scan_state=state):
        if row['path'] in index:
            raise ValueError('duplicate DIRECT source identity')
        index[row['path']] = row
        if len(index) > MAX_INDEX_ROWS:
            raise ValueError('DIRECT source index exceeds row bound')
    fields = list(selected_rows) if selected_rows is not None else list(
        _rows(root, 'data_ledger', diagnostics, scan_state=state))
    fields = [deepcopy(row) for row in fields if _scope_matches(row, scope)]
    operators = list(_rows(root, 'operator_ledger', diagnostics, scan_state=state))
    captures = []
    candidates = [(str(source.get('captured_at') or ''), path, source) for path, source in index.items()
        if path.startswith('raw/platform/') and Path(path).stem.lower() == 'operators']
    for captured, path, source in sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True):
        try:
            _, text = read_direct_source(root, source)
            facts = _operator_facts(text, jsonl=Path(path).suffix.lower() == '.jsonl')
        except (OSError, ValueError, UnicodeError) as error:
            diagnostics.append(dict(code='operator_capture_unavailable', path=path, severity='warning', reason=str(error)))
            continue
        if facts:
            captures.append((captured, path, facts))
            break
    if captures:
        _, path, facts = max(captures, key=lambda item: (item[0], item[1]))
        operators = [dict(deepcopy(row), source_paths=[path]) for row in facts]
        for row in operators:
            if isinstance(row.get('definition'), str):
                row['raw_definition'] = row.pop('definition')
            if isinstance(row.get('description'), str):
                row.setdefault('raw_description', row['description'])
    current = {_identity(row): row for row in _optional_published_operators(root, diagnostics, MAX_CONTEXT_BYTES)}
    operators = [deepcopy(current.pop(_identity(row), row)) for row in operators]
    operators.extend(deepcopy(list(current.values())))
    if len(operators) > MAX_OPERATORS:
        raise ValueError('DIRECT operator list exceeds row bound')
    if _size([index, fields, operators]) > MAX_CONTEXT_BYTES:
        raise ValueError('DIRECT resource metadata exceeds byte bound')
    seen = set()
    for row in fields:
        identity = (row.get('dataset_id'), row.get('field_id'))
        if identity in seen:
            raise ValueError('duplicate DIRECT field identity')
        seen.add(identity)
        row['direct_knowledge_version'] = 1
    for row in operators:
        row['operator'] = _identity(row)
        row['direct_knowledge_version'] = 1
    if len({row['operator'] for row in operators}) != len(operators):
        raise ValueError('duplicate DIRECT operator identity')
    resources = []
    for start in range(0, min(len(fields), count * max_fields_per_lane), max_fields_per_lane):
        batch = fields[start:start + max_fields_per_lane]
        paths = {path for row in [*batch, *operators] for path in row.get('source_paths', [])}
        paths.update(ref['source_path'] for row in operators
                     if isinstance(row.get('definition'), dict)
                     for ref in row['definition'].get('evidence_refs', []))
        sources, texts = {}, {}
        for path in sorted(paths):
            if path not in index:
                diagnostics.append(dict(code='missing_source_reference', path=path, severity='warning'))
                continue
            sources[path], texts[path] = read_direct_source(root, index[path])
            if _size([sources, texts]) > MAX_CONTEXT_BYTES:
                raise ValueError('DIRECT selected input bytes exceed context bound')
        semantics = {'field:' + row['dataset_id'] + '/' + row['field_id'] for row in batch}
        semantics.update(term for row in batch for term in _phrases(row))
        pack = dict(resource_contract_version=2, resource_admission_policy=DIRECT_POLICY,
            scope=deepcopy(scope), source_index=sources, source_texts=texts,
            allowed_role_semantics=sorted(semantics), allowed_operator_intents=list(INTENTS), histories=[])
        resources.append(dict(resource_contract_version=2, resource_admission_policy=DIRECT_POLICY,
            field_rows=batch, operator_rows=deepcopy(operators), source_index=sources,
            source_texts=texts, evidence_pack=pack, settings=deepcopy(settings)))
    diagnostics.append(dict(code='direct_knowledge_uncertainty', severity='warning', reason=WARNING))
    return resources, diagnostics
