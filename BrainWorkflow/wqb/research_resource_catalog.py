"""Read-only, bounded catalog admission; visibility is not executable certification."""

from copy import deepcopy
from datetime import date, datetime, timezone
import json
from io import StringIO
from pathlib import Path
import re

from wqb.knowledge_age_policy import KNOWLEDGE_MAX_AGE_DAYS
from wqb.knowledge_contracts import parse_markdown_front_matter
from wqb.knowledge_compile import _coverage_json_objects
from wqb.knowledge_paths import machine_resource_path
from wqb.hypothesis_design import INTENTS, MAX_JSON_BYTES
from wqb.resource_evidence import KNOWLEDGE_CATALOG_POLICY, catalog_operator_definition
from wqb.semantic_compilation import _material, _safe, _markdown_definitions, MAX_SOURCE_BYTES
from wqb.template_binding import _scope_matches


MAX_LINE_BYTES = 1_000_000
MAX_CATALOG_ROWS = 500_000
MAX_INDEX_ROWS = 4096
MAX_OPERATORS = 4096
MAX_LANES = 64
MAX_FIELDS_PER_LANE = 30
MAX_CONTEXT_BYTES = 16_000_000
MAX_DIAGNOSTICS = 2048
SCOPE_KEYS = ('instrument_type', 'region', 'delay', 'universe')
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
UNKNOWN_WARNING = ('Economic semantics, availability/timing and grain are unknown unless explicitly '
                   'provided; catalog identity tokens are binding labels, not economic meaning.')


def _size(value: object) -> int:
    """Input: JSON-compatible object. Output: serialized UTF-8 byte count, including repeated references."""
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    return sum(len(piece.encode('utf-8')) for piece in encoder.iterencode(value))


def _diagnostic(diagnostics: list, code: str, reason: str, **identity) -> None:
    """Input: diagnostics list/code/reason strings and identity. Output: None; append bounded diagnostics."""
    critical = ('unreadable_catalog', 'catalog_limit', 'context_limit',
                'technical_context_limit', 'technical_selection_gap')
    if len(diagnostics) < MAX_DIAGNOSTICS:
        diagnostics.append(dict(code=code, reason=reason, **identity))
    elif code in critical:
        diagnostics[-1] = dict(code=code, reason=reason, **identity)
    elif diagnostics[-1].get('code') in critical:
        return
    elif diagnostics[-1].get('code') != 'diagnostic_limit':
        diagnostics[-1] = dict(code='diagnostic_limit', severity='warning',
                               reason='Further diagnostics omitted by the bounded reader.')


def _rows(root: Path, name: str, diagnostics: list, *, scan_state: dict, report_rows: bool = True):
    """Input: vault Path/resource str/diagnostics list. Output: iterator[dict]; bounded canonical JSONL only."""
    path = machine_resource_path(root, name)
    scan_state[name] = False
    try:
        path = _safe(root, path.relative_to(root).as_posix())
        with path.open('rb') as stream:
            number = 0
            while True:
                line = stream.readline(MAX_LINE_BYTES + 1)
                if not line:
                    break
                number += 1
                if number > MAX_CATALOG_ROWS or len(line) > MAX_LINE_BYTES:
                    raise ValueError('catalog exceeds bounded row/line limit')
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if type(row) is not dict:
                        raise ValueError('catalog row must be an object')
                    yield row
                except (ValueError, UnicodeError, RecursionError) as error:
                    if report_rows:
                        _diagnostic(diagnostics, 'malformed_catalog_row', str(error),
                                    severity='excluded', path=path.relative_to(root).as_posix(), line=number)
        scan_state[name] = True
    except (OSError, ValueError) as error:
        _diagnostic(diagnostics, 'unreadable_catalog', str(error), severity='excluded', resource=name)


def _fresh(value: str, now: datetime, *, day: bool = False) -> None:
    """Input: original date str/current aware datetime/day flag. Output: None; reject unknown, future or expired dates."""
    if not isinstance(value, str):
        raise ValueError('missing real source date')
    if day:
        age = (now.date() - date.fromisoformat(value)).days
    else:
        captured = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if captured.tzinfo is None:
            raise ValueError('source date requires timezone')
        age = (now - captured).total_seconds() / 86400
    if not 0 <= age <= KNOWLEDGE_MAX_AGE_DAYS:
        raise ValueError('source date outside knowledge age policy')


def _identity(row: dict) -> str:
    """Input: actual operator dict. Output: explicit operator identifier str; reject conflicting aliases."""
    values = [row[k] for k in ('operator', 'name', 'id') if k in row]
    if (not values or any(not isinstance(v, str) or not IDENTIFIER.fullmatch(v) for v in values)
            or len(set(values)) != 1):
        raise ValueError('operator identity missing or conflicting')
    return values[0]


def _paths(row: dict) -> list[str]:
    """Input: catalog row dict. Output: explicit raw source paths list; optional enrichment never required."""
    paths = row.get('source_paths', [])
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
        raise ValueError('catalog row requires indexed source_paths')
    return paths


def _operator_facts(text: str, *, jsonl: bool = False) -> list[dict]:
    """Input: complete verified source str. Output: actual JSON or labelled Markdown operator facts list."""
    if jsonl:
        facts = []
        stream = StringIO(text)
        while line := stream.readline(MAX_LINE_BYTES + 1):
            if len(line.encode('utf-8')) > MAX_LINE_BYTES:
                raise ValueError('operator JSONL record exceeds byte bound')
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError('operator JSONL records must be objects')
            facts.extend(_operator_facts(line))
            if len(facts) > MAX_OPERATORS:
                raise ValueError('operator JSONL catalog exceeds record bound')
        return facts
    # Operator containers are not recursively walked: parameter names are not operators.
    facts = []
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = next((payload[k] for k in ('operators', 'results', 'rows', 'data')
                            if isinstance(payload.get(k), list)), [payload])
        if isinstance(payload, list):
            facts = [r for r in payload if isinstance(r, dict)]
    except (ValueError, RecursionError):
        pass
    headings = list(re.finditer(r'^###\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s*$', text, re.MULTILINE))
    definitions = _markdown_definitions(text, require_description=False)
    for number, heading in enumerate(headings):
        section = text[heading.end():headings[number + 1].start() if number + 1 < len(headings) else len(text)]
        labels = {}
        for label in ('Source id', 'Definition', 'Description'):
            values = re.findall(r'^- ' + label + r':[ \t]*(.*)$', section, re.MULTILINE)
            if len(values) == 1:
                labels[label] = values[0].strip().strip('`')
        if labels.get('Source id') == heading[1]:
            fact = dict(operator=heading[1])
            if labels.get('Definition'):
                fact['raw_definition'] = labels['Definition']
            if labels.get('Description'):
                fact['raw_description'] = labels['Description']
            if heading[1] in definitions:
                fact['definition'] = definitions[heading[1]]
            facts.append(fact)
    return facts


def _phrases(fact: dict) -> set[str]:
    """Input: actual raw field dict. Output: literal description/tag string set, never inferred meanings."""
    phrases = set()
    for key in ('description', 'field_description', 'semantic_tags', 'tags'):
        value = fact.get(key, [])
        values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        phrases.update(v for v in values if isinstance(v, str) and v.strip())
    return phrases


def _embedded_operator_rows(paths: set[str], texts: dict, index: dict, diagnostics: list) -> list[dict]:
    """Input: selected source paths/text/index/diagnostics. Output: explicitly embedded, source-bound operator dicts.

    Only a document's named operators collection is ingestion authority here;
    field IDs, nested parameter names and arbitrary JSON records are not operators.
    """
    rows = []
    for path in sorted(paths):
        try:
            payload = json.loads(texts[path])
        except (ValueError, RecursionError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get('operators'), list):
            continue
        for fact in payload['operators']:
            try:
                if not isinstance(fact, dict):
                    raise ValueError('embedded operator must be an explicit record')
                name = _identity(fact)
                row = dict(deepcopy(fact), operator=name, source_paths=[path])
                definition = row.get('definition')
                if isinstance(definition, dict):
                    # Bind the technical facts actually present in these bytes,
                    # rather than trusting any references copied into the payload.
                    definition['evidence_refs'] = [dict(source_path=path, sha256=index[path]['content_hash'],
                        capture_date=index[path]['captured_at'][:10], kind='documented', experiment_refs=[])]
                else:
                    if isinstance(definition, str):
                        row['raw_definition'] = row.pop('definition')
                    _diagnostic(diagnostics, 'missing_operator_signature',
                        'Embedded operator remains visible; typed technical signature is unknown.',
                        severity='warning', operator=name, path=path)
                if isinstance(row.get('description'), str) and 'raw_description' not in row:
                    row['raw_description'] = row['description']
                if len(rows) >= MAX_OPERATORS:
                    raise ValueError('embedded operator catalog exceeds bound')
                rows.append(row)
            except (ValueError, TypeError) as error:
                _diagnostic(diagnostics, 'invalid_operator', str(error), severity='excluded', path=path)
    return rows


def _optional_published_operators(root: Path, diagnostics: list, max_bytes: int) -> list[dict]:
    """Input: vault Path/diagnostics list/remaining byte budget int. Output: optional published operator dicts.

    Preflight the selected immutable generation before the existing paired-byte
    reader. Publication is an enrichment source, never a catalog selector.
    """
    from wqb.knowledge_compile import read_semantic_rows
    try:
        pointer = _safe(root, 'machine/semantic_release.json')
        if not pointer.exists():
            return []
        if pointer.stat().st_size > min(MAX_LINE_BYTES, max_bytes):
            raise ValueError('optional semantic pointer exceeds byte bound')
        with pointer.open('rb') as stream:
            raw = stream.read(min(MAX_LINE_BYTES, max_bytes) + 1)
        if len(raw) > min(MAX_LINE_BYTES, max_bytes):
            raise ValueError('optional semantic pointer changed beyond byte bound')
        payload = json.loads(raw)
        release_id = payload.get('release_id')
        if not isinstance(release_id, str) or not re.fullmatch('[a-f0-9]{64}', release_id):
            raise ValueError('invalid optional semantic release identity')
        generation = _safe(root, 'machine/semantic_releases/' + release_id)
        total, entries = len(raw), 0
        for candidate in generation.rglob('*'):
            entries += 1
            path = _safe(root, candidate.relative_to(root).as_posix())
            if entries > MAX_INDEX_ROWS:
                raise ValueError('optional semantic generation exceeds entry bound')
            if path.is_file():
                size = path.stat().st_size
                total += size
                if size > MAX_SOURCE_BYTES or total > max_bytes:
                    raise ValueError('optional semantic generation exceeds byte bound')
        receipt, operators, templates = read_semantic_rows(root)
        if (receipt.get('release_id') != release_id or pointer.read_bytes() != raw
                or len(operators) > MAX_OPERATORS or _size([receipt, operators, templates]) > max_bytes):
            raise ValueError('optional semantic generation changed or exceeds context bound')
        return operators
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as error:
        _diagnostic(diagnostics, 'operator_enrichment_unavailable', str(error), severity='warning')
        return []


def read_catalog_resources(root: Path, scope: dict, count: int, *, settings: dict,
                           max_fields_per_lane: int = 30) -> tuple[list[dict], list[dict]]:
    """Input: vault Path/exact scope dict/count int/settings dict/field cap int.

    Output: (compiler resource dict list, diagnostic dict list). Read canonical
    catalogs without publishing, creating extracts, invoking models or granting
    technical/economic certification. Large originals need existing verified extracts.
    """
    if (type(count) is not int or not 1 <= count <= MAX_LANES
            or type(max_fields_per_lane) is not int or not 1 <= max_fields_per_lane <= MAX_FIELDS_PER_LANE):
        raise ValueError('invalid catalog lane/field bounds')
    if (type(scope) is not dict or type(settings) is not dict
            or any(k not in scope for k in (*SCOPE_KEYS, 'as_of'))
            or type(scope['delay']) is not int or scope['delay'] < 0
            or any(not isinstance(scope[k], str) or not scope[k].strip()
                   for k in ('instrument_type', 'region', 'universe', 'as_of'))):
        raise ValueError('catalog requires exact scope and settings')
    as_of = datetime.fromisoformat(scope['as_of'].replace('Z', '+00:00'))
    if as_of.tzinfo is None:
        raise ValueError('scope.as_of requires timezone')
    root, now = Path(root), datetime.now(timezone.utc)
    diagnostics, index, bad_paths, scan_state = [], {}, set(), {}
    metadata_bytes = 0
    for source in _rows(root, 'source_index', diagnostics, scan_state=scan_state):
        path = source.get('path')
        if not isinstance(path, str) or path in index:
            if isinstance(path, str):
                bad_paths.add(path)
            _diagnostic(diagnostics, 'invalid_source_index', 'missing or duplicate source path', severity='excluded')
            continue
        if len(index) >= MAX_INDEX_ROWS:
            _diagnostic(diagnostics, 'catalog_limit', 'source index exceeds row bound', severity='excluded')
            return [], diagnostics
        metadata_bytes += _size(source)
        if metadata_bytes > MAX_CONTEXT_BYTES:
            _diagnostic(diagnostics, 'context_limit', 'source index metadata exceeds byte bound', severity='excluded')
            return [], diagnostics
        index[path] = source
    for path in bad_paths:
        index.pop(path, None)
    if not scan_state['source_index']:
        return [], diagnostics

    cache, cache_costs, cache_bytes, pinned_paths = {}, {}, 0, set()

    def material(path: str) -> tuple[dict, str]:
        """Input: indexed source path str. Output: verified source/text tuple; bounded invocation cache."""
        nonlocal cache_bytes
        if path not in index:
            raise ValueError('unindexed source: ' + path)
        if path not in cache:
            _fresh(index[path].get('captured_at'), now)
            if _safe(root, path, source=True).stat().st_size > MAX_SOURCE_BYTES:
                raise ValueError('oversized source requires existing verified indexed field extract: ' + path)
            source, text = _material(root, index[path])
            if index[path].get('file_sha256', source['file_sha256']).lower() != source['file_sha256']:
                raise ValueError('asserted full-file hash mismatch')
            cost = _size(text) + _size(source)
            for previous in list(cache):
                if metadata_bytes + cache_bytes + cost <= MAX_CONTEXT_BYTES:
                    break
                if previous not in pinned_paths:
                    cache.pop(previous)
                    cache_bytes -= cache_costs.pop(previous)
            if metadata_bytes + cache_bytes + cost > MAX_CONTEXT_BYTES:
                raise ValueError('catalog source context exceeds byte bound')
            cache_bytes += cost
            cache_costs[path] = cost
            cache[path] = source, text
        return cache[path]

    # The ledger may lag the latest authenticated catalog. Read indexed captures
    # directly, without selecting an active semantic release or unindexed files.
    ledger_rows = []
    for row in _rows(root, 'operator_ledger', diagnostics, scan_state=scan_state):
        if len(ledger_rows) >= MAX_OPERATORS:
            _diagnostic(diagnostics, 'catalog_limit', 'operator ledger exceeds row bound', severity='excluded')
            return [], diagnostics
        metadata_bytes += _size(row)
        if metadata_bytes + cache_bytes > MAX_CONTEXT_BYTES:
            _diagnostic(diagnostics, 'context_limit', 'operator metadata exceeds byte bound', severity='excluded')
            return [], diagnostics
        ledger_rows.append(row)
    inventories = []
    for path, source in index.items():
        if not (path.startswith('raw/platform/') and Path(path).stem.lower() == 'operators'
                and Path(path).suffix.lower() in ('.json', '.md', '.jsonl')):
            continue
        try:
            _, text = material(path)
            facts = _operator_facts(text, jsonl=Path(path).suffix.lower() == '.jsonl')
            if not facts:
                raise ValueError('indexed operator catalog contains no readable rows')
            if len(facts) > MAX_OPERATORS:
                raise ValueError('operator source catalog exceeds bound')
            metadata_bytes += _size(facts)
            if metadata_bytes + cache_bytes > MAX_CONTEXT_BYTES:
                _diagnostic(diagnostics, 'context_limit', 'operator inventory metadata exceeds byte bound', severity='excluded')
                return [], diagnostics
            inventories.append((datetime.fromisoformat(source['captured_at'].replace('Z', '+00:00')), path, facts))
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
            _diagnostic(diagnostics, 'invalid_operator_source', str(error), severity='excluded', path=path)
    if inventories:
        # A fresh catalog is a current inventory, not a union with retired old IDs.
        newest = max(item[0] for item in inventories)
        catalog = {}
        for captured, path, facts in sorted(inventories, key=lambda item: item[1]):
            if captured != newest:
                continue
            for fact in facts:
                try:
                    name = _identity(fact)
                    if name not in catalog:
                        catalog[name] = dict(deepcopy(fact), source_paths=[path])
                    else:
                        # Equal-date JSON/Markdown copies can contribute actual
                        # technical facts; conflicting facts remain explicit errors.
                        previous = catalog[name]
                        for key, value in fact.items():
                            if key in ('operator', 'name', 'id'):
                                continue
                            if key in previous and previous[key] != value:
                                raise ValueError('conflicting current operator fact: ' + name + '/' + key)
                            previous[key] = deepcopy(value)
                        previous['source_paths'].append(path)
                except (ValueError, TypeError) as error:
                    _diagnostic(diagnostics, 'invalid_operator', str(error), severity='excluded', path=path)
        for row in ledger_rows:
            try:
                _identity(row)
            except ValueError as error:
                _diagnostic(diagnostics, 'invalid_operator', str(error), severity='excluded')
        operator_candidates = list(catalog.values())
    else:
        # Missing optional ledger permits embedded operators, not a failed scan
        # of an existing fallback authority. Independent inventories above win.
        if not scan_state['operator_ledger'] and (ledger_rows or machine_resource_path(root, 'operator_ledger').exists()):
            return [], diagnostics
        operator_candidates = ledger_rows

    operators, operator_paths, seen_operators, duplicate_operators = [], set(), set(), set()
    for row in operator_candidates:
        try:
            name = _identity(row)
            if name in seen_operators:
                duplicate_operators.add(name)
                raise ValueError('duplicate operator identity: ' + name)
            seen_operators.add(name)
            if len(seen_operators) > MAX_OPERATORS:
                raise ValueError('operator catalog exceeds bound')
            paths, facts, typed_paths = _paths(row), [], []
            for path in paths:
                _, text = material(path)
                for fact in _operator_facts(text, jsonl=Path(path).suffix.lower() == '.jsonl'):
                    try:
                        if _identity(fact) == name:
                            facts.append(fact)
                            if isinstance(fact.get('definition'), dict):
                                typed_paths.append(path)
                    except ValueError:
                        continue
            if not facts:
                raise ValueError('operator identity absent from authentic raw source: ' + name)
            selected = deepcopy(row)
            selected['operator'] = name
            if 'definition' in selected and not any(f.get('definition') == selected['definition'] for f in facts):
                selected.pop('definition')
                _diagnostic(diagnostics, 'unverified_operator_signature',
                            'Ledger technical claim is absent from actual source; retained identity only.',
                            severity='warning', operator=name)
            for fact in facts:
                for key in ('definition', 'raw_definition', 'raw_description', 'description'):
                    if key in fact:
                        if key in selected and selected[key] not in (None, '', fact[key]):
                            raise ValueError('conflicting operator technical/raw fact: ' + name + '/' + key)
                        selected[key] = deepcopy(fact[key])
            if isinstance(selected.get('definition'), str):
                selected['raw_definition'] = selected.pop('definition')
            if 'raw_description' not in selected and isinstance(selected.get('description'), str):
                selected['raw_description'] = selected['description']
            if (typed_paths and isinstance(selected.get('definition'), dict)
                    and {'input_types', 'output_type', 'parameters'}.issubset(selected['definition'])):
                selected['definition'].setdefault('description',
                    'Economic description unavailable; technical declaration only.')
            if typed_paths and isinstance(selected.get('definition'), dict) and 'evidence_refs' not in selected['definition']:
                selected['definition']['evidence_refs'] = [dict(source_path=path,
                    sha256=index[path]['content_hash'], capture_date=index[path]['captured_at'][:10],
                    kind='documented', experiment_refs=[]) for path in sorted(set(typed_paths))]
            if not isinstance(selected.get('definition'), dict):
                _diagnostic(diagnostics, 'missing_operator_signature',
                            'Typed technical signature unknown; operator remains visible, unsupported calls must reject.',
                            severity='warning', operator=name)
            operators.append(selected)
            metadata_bytes += _size(selected)
            if metadata_bytes + cache_bytes > MAX_CONTEXT_BYTES:
                _diagnostic(diagnostics, 'context_limit', 'operator context metadata exceeds byte bound', severity='excluded')
                return [], diagnostics
            operator_paths.update(paths)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
            _diagnostic(diagnostics, 'invalid_operator', str(error), severity='excluded', operator=row.get('operator', row.get('id')))
    operators = [row for row in operators if row['operator'] not in duplicate_operators]

    published_rows = _optional_published_operators(root, diagnostics, MAX_CONTEXT_BYTES - metadata_bytes - cache_bytes)
    published = {}
    for row in published_rows:
        name = row.get('operator')
        if name in published:
            published[name] = None
        elif isinstance(name, str):
            published[name] = row
    for number, current in enumerate(operators):
        candidate = published.get(current['operator'])
        if isinstance(current.get('definition'), dict) or not isinstance(candidate, dict):
            continue
        previously_pinned = set(pinned_paths)
        try:
            definition = candidate.get('definition')
            if not isinstance(definition, dict):
                continue
            refs = list(definition.get('evidence_refs', []))
            basis = candidate.get('definition_basis')
            if isinstance(basis, dict):
                refs.extend(premise['evidence_ref'] for premise in
                            [basis['signature_premise'], *basis['type_premises']])
            if not refs:
                raise ValueError('published technical definition lacks evidence refs')
            paths = {ref['source_path'] for ref in refs}
            for path in sorted(paths):
                material(path)
                pinned_paths.add(path)
            enriched = deepcopy(current)
            enriched['definition'] = deepcopy(definition)
            if basis is not None:
                enriched['definition_basis'] = deepcopy(basis)
            enriched['source_paths'] = sorted(set(current['source_paths']) | paths)
            selected_index = {path: index[path] for path in enriched['source_paths']}
            source_texts = {path: material(path)[1] for path in enriched['source_paths']}
            catalog_operator_definition(enriched, selected_index, source_texts)
            extra = _size(enriched) - _size(current)
            if metadata_bytes + cache_bytes + _size(published_rows) + extra > MAX_CONTEXT_BYTES:
                raise ValueError('optional operator enrichment exceeds context byte bound')
            metadata_bytes += extra
            operators[number] = enriched
        except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as error:
            _diagnostic(diagnostics, 'operator_enrichment_rejected', str(error),
                        severity='warning', operator=current['operator'])
            pinned_paths = previously_pinned
    del published_rows, published
    operator_paths = {p for row in operators for p in row['source_paths']}
    pinned_paths.update(operator_paths)
    try:
        for path in sorted(operator_paths):
            material(path)
    except (OSError, ValueError, TypeError, KeyError) as error:
        _diagnostic(diagnostics, 'context_limit', str(error), severity='excluded')
        return [], diagnostics

    def lane_resource(batch: list, lane_diagnostics: list) -> dict:
        """Input: verified (canonical row, phrases, evidence paths) tuples/diagnostics list. Output: full resource dict."""
        rows = [row for row, _, _ in batch]
        field_paths = {p for _, _, paths in batch for p in paths}
        paths = operator_paths | field_paths
        selected_index = {p: index[p] for p in sorted(paths)}
        texts = {p: cache[p][1] for p in sorted(paths)}
        lane_operators = {row['operator']: row for row in operators}
        for row in _embedded_operator_rows(field_paths, texts, selected_index, lane_diagnostics):
            previous = lane_operators.get(row['operator'])
            if previous is None or not isinstance(previous.get('definition'), dict):
                lane_operators[row['operator']] = row
            elif isinstance(row.get('definition'), dict):
                prior = {k: v for k, v in previous['definition'].items() if k != 'evidence_refs'}
                current = {k: v for k, v in row['definition'].items() if k != 'evidence_refs'}
                if prior != current:
                    _diagnostic(lane_diagnostics, 'invalid_operator', 'Conflicting embedded technical definition.',
                                severity='excluded', operator=row['operator'], path=row['source_paths'][0])
        pack = dict(resource_contract_version=2, resource_admission_policy=KNOWLEDGE_CATALOG_POLICY,
                    scope=scope, source_index=selected_index, source_texts=texts,
                    allowed_role_semantics=sorted(set().union(*(phrases for _, phrases, _ in batch))),
                    allowed_operator_intents=list(INTENTS), histories=[])
        return dict(resource_contract_version=2, resource_admission_policy=KNOWLEDGE_CATALOG_POLICY,
                    field_rows=rows, operator_rows=list(lane_operators.values()),
                    source_index=selected_index, source_texts=texts, evidence_pack=pack, settings=settings)

    def verify_field(row: dict, *, prefer_extracts: bool = False) -> tuple | None:
        """Input: exact-scope ledger row dict/extract preference bool. Output: (canonical row, phrases, paths) tuple or None."""
        identity = (row.get('dataset_id'), row.get('field_id'))
        try:
            if any(not isinstance(v, str) or not v.strip() for v in identity):
                raise ValueError('missing field/dataset identity')
            if not IDENTIFIER.fullmatch(row['field_id']) or row.get('field_type') not in ('MATRIX', 'VECTOR', 'GROUP'):
                raise ValueError('invalid field identity or explicit type')
            _fresh(row.get('source_updated_at'), now, day=True)
            paths, matched, actual_paths = _paths(row), [], []
            for path in paths:
                choices = [path]
                if path in index and (prefer_extracts or _safe(root, path, source=True).stat().st_size > MAX_SOURCE_BYTES):
                    _fresh(index[path].get('captured_at'), now)
                    # Only existing indexed excerpts: _material verifies their original receipts.
                    choices = [p for p, item in index.items() if item.get('content_status') == 'verified_raw_extract'
                               and Path(p).parent == Path(path).parent]
                    if not choices:
                        if prefer_extracts and _safe(root, path, source=True).stat().st_size <= MAX_SOURCE_BYTES:
                            choices = [path]
                        else:
                            raise ValueError('oversized source has no existing verified indexed extract')
                found = False
                for chosen in choices:
                    source, text = material(chosen)
                    if chosen != path:
                        metadata, _ = parse_markdown_front_matter(text.replace('\r\n', '\n'))
                        if (metadata.get('original_source_path') != path
                                or metadata.get('original_sha256') != index[path]['content_hash']):
                            continue
                    for item in _coverage_json_objects(text):
                        field, dataset, captured = item.get('field'), item.get('data_set'), item.get('scope')
                        if not all(isinstance(v, dict) for v in (field, dataset, captured)):
                            field, dataset, captured = item, item.get('dataset'), item
                        if not isinstance(dataset, dict) or not isinstance(captured, dict):
                            continue
                        if (field.get('id'), dataset.get('id')) != (identity[1], identity[0]):
                            continue
                        if not _scope_matches(captured, scope):
                            continue
                        if field.get('type') != row['field_type']:
                            raise ValueError('raw field type conflicts with catalog')
                        if 'generated_at' in item:
                            _fresh(item['generated_at'], now)
                            if item['generated_at'][:10] != row['source_updated_at']:
                                raise ValueError('raw capture date conflicts with ledger source date')
                        if 'dataset' in field and field['dataset'].get('id') != identity[0]:
                            raise ValueError('raw nested dataset identity conflicts')
                        matched.append(field)
                        found = True
                        actual_paths.append(chosen)
                        pinned_paths.add(chosen)
                if not found:
                    raise ValueError('missing exact raw field identity/type/scope in source: ' + path)
            semantics = {'field:' + identity[0] + '/' + identity[1]}
            for fact in matched:
                semantics.update(_phrases(fact))
            # Evidence substitution is proven by the existing extract receipt;
            # it must never mutate the ledger identity frozen by Start.
            return deepcopy(row), sorted(semantics), list(dict.fromkeys(actual_paths))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as error:
            _diagnostic(diagnostics, 'invalid_field', str(error), severity='excluded',
                        dataset_id=identity[0], field_id=identity[1])
            return None

    # Only verified fields occupy bounded slots. A complete identity-only audit
    # detects shadows even before the selected occurrence, then refills from the
    # deterministic stream without retaining an unbounded candidate queue.
    selected_fields, duplicate_ids, selected_bytes = {}, set(), 0
    target = count * max_fields_per_lane
    while True:
        for row in _rows(root, 'data_ledger', diagnostics, scan_state=scan_state):
            if not _scope_matches(row, scope):
                continue
            identity = (row.get('dataset_id'), row.get('field_id'))
            if any(not isinstance(v, str) for v in identity):
                _diagnostic(diagnostics, 'invalid_field', 'missing field/dataset identity', severity='excluded')
                continue
            if identity in selected_fields or identity in duplicate_ids:
                continue
            if len(selected_fields) >= target:
                # Audit the whole pool for scarce known DSL-compatible fields;
                # retain only a bounded view, not an unbounded candidate queue.
                matrices = sum(item[0]['field_type'] == 'MATRIX' for item in selected_fields.values())
                if row.get('field_type') != 'MATRIX' or matrices >= count:
                    continue
            previously_pinned = set(pinned_paths)
            verified = verify_field(row)
            single_bytes = _size(lane_resource([verified], [])) if verified is not None else 0
            if verified is not None and single_bytes > MAX_JSON_BYTES:
                # Existing extracts may fit even when the original is below the
                # IO cap. Never manufacture an excerpt or shorten source text.
                pinned_paths = previously_pinned
                extracted = verify_field(row, prefer_extracts=True)
                if extracted is not None and _size(lane_resource([extracted], [])) <= MAX_JSON_BYTES:
                    verified = extracted
                else:
                    _diagnostic(diagnostics, 'technical_context_limit',
                        'Single-field indispensable evidence cannot fit serialized compiler resource limit '
                        + str(MAX_JSON_BYTES) + ' bytes including duplicate source pack; no fitting existing verified extract.',
                        severity='excluded', dataset_id=identity[0], field_id=identity[1], resource_bytes=single_bytes)
                    verified = None
            if verified is not None:
                if len(selected_fields) >= target:
                    displaced = next(key for key in reversed(selected_fields)
                                     if selected_fields[key][0]['field_type'] != 'MATRIX')
                    selected_bytes -= _size(selected_fields.pop(displaced))
                    pinned_paths = operator_paths | {p for _, _, paths in selected_fields.values()
                                                     for p in paths} | set(verified[2])
                cost = _size(verified)
                if metadata_bytes + cache_bytes + selected_bytes + cost > MAX_CONTEXT_BYTES:
                    _diagnostic(diagnostics, 'context_limit', 'verified field metadata exceeds byte bound', severity='excluded')
                    return [], diagnostics
                selected_fields[identity] = verified
                selected_bytes += cost
                pinned_paths.update(verified[2])
                _diagnostic(diagnostics, 'unknown_optional_metadata', UNKNOWN_WARNING, severity='warning',
                            dataset_id=identity[0], field_id=identity[1])
            else:
                pinned_paths = previously_pinned
        if not scan_state['data_ledger']:
            return [], diagnostics
        occurrences = dict.fromkeys(selected_fields, 0)
        for row in _rows(root, 'data_ledger', diagnostics, scan_state=scan_state, report_rows=False):
            if _scope_matches(row, scope):
                identity = (row.get('dataset_id'), row.get('field_id'))
                if all(isinstance(v, str) for v in identity) and identity in occurrences:
                    occurrences[identity] += 1
        if not scan_state['data_ledger']:
            return [], diagnostics
        ambiguous = {identity for identity, number in occurrences.items() if number != 1}
        if not ambiguous:
            break
        for dataset, field in sorted(ambiguous):
            selected_bytes -= _size(selected_fields.pop((dataset, field)))
            duplicate_ids.add((dataset, field))
            _diagnostic(diagnostics, 'invalid_field', 'duplicate exact-scope field identity',
                        severity='excluded', dataset_id=dataset, field_id=field)
        if metadata_bytes + cache_bytes + selected_bytes + _size(sorted(duplicate_ids)) > MAX_CONTEXT_BYTES:
            _diagnostic(diagnostics, 'context_limit', 'duplicate identity audit exceeds byte bound', severity='excluded')
            return [], diagnostics
        pinned_paths = operator_paths | {p for _, _, paths in selected_fields.values() for p in paths}

    resources, output_bytes = [], 2
    # Seed each view with an actual MATRIX when possible, then stably pack all
    # types without coercion. Count is a cap, not a demand to invent DSL inputs.
    matrix_fields = [item for item in selected_fields.values() if item[0]['field_type'] == 'MATRIX']
    seeds = matrix_fields[:count]
    seeded_ids = {(item[0]['dataset_id'], item[0]['field_id']) for item in seeds}
    batches = [[item] for item in seeds]
    lane_limit = len(seeds) if seeds else count
    if len(seeds) < count:
        _diagnostic(diagnostics, 'technical_selection_gap',
                    'Current feature DSL requires MATRIX inputs; available verified MATRIX fields cannot seed '
                    'every requested lane. VECTOR/GROUP remain visible and unchanged; no implicit reduction or semantic gate.',
                    severity='warning', requested_lanes=count, available_matrix_fields=len(matrix_fields))
    for identity, field in selected_fields.items():
        if identity in seeded_ids:
            continue
        for batch in batches:
            if len(batch) < max_fields_per_lane and _size(lane_resource([*batch, field], [])) <= MAX_JSON_BYTES:
                batch.append(field)
                break
        else:
            if len(batches) < lane_limit:
                batches.append([field])
    for batch in batches:
        resource = lane_resource(batch, diagnostics)
        cost = _size(resource) + bool(resources)
        if output_bytes + cost > MAX_CONTEXT_BYTES:
            _diagnostic(diagnostics, 'context_limit', 'full resource output exceeds byte bound; requested lanes remain incomplete.',
                        severity='excluded')
            return resources, diagnostics
        output_bytes += cost
        resources.append(deepcopy(resource))
        if len(resources) == count:
            return resources, diagnostics
    return resources, diagnostics
