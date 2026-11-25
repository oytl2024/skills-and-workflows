"""Bounded local evidence queries. Retrieval never certifies execution or semantics.

All operations require a prepared, current research_query_index generation. This
module deliberately imports that dependency only when called, and never prepares
an index or opens the full field ledger itself.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import re


MAX_RESPONSE_BYTES = 64_000
MAX_RESOURCE_BYTES = 16_000_000
MAX_PAGE_SIZE = 50
MAX_EXCERPT_CHARS = 8_000
MAX_QUERY_CHARS = 512
MAX_SOURCE_INDEX_ROWS = 4096
SCOPE_KEYS = ('instrument_type', 'region', 'delay', 'universe')
UNKNOWN_WARNING = ('Economic meaning, availability/timing and grain remain unknown unless explicitly sourced; '
                   'retrieval visibility is not technical validation or reviewed evidence.')
TRANSFER_WARNING = ('Cross-scope observations are transfer-only hypotheses, not proof in the requested market; '
                    'original scope and measurement period remain authoritative, and execution scope is unchanged.')
OPERATIONS = {'fields', 'operators', 'templates', 'experience', 'source', 'resources'}
LOCAL_TEXT_SUFFIXES = {'.md', '.json', '.jsonl', '.txt', '.csv'}


def _vault_resource(root: Path, relative: str) -> Path:
    """Input: vault root and relative string. Output: safe raw/machine/wiki path, excluding secrets and links."""
    from wqb.semantic_compilation import _safe
    path = Path(relative)
    if (not path.parts or path.parts[0] not in ('raw', 'machine', 'wiki') or '\\' in relative
            or any(part.startswith('.') or part in ('..', 'credentials.json', 'auth.json', 'Cookies',
                'Login Data', 'Local State', 'browser', 'webview2') for part in path.parts)):
        raise ValueError('resource must be a safe local raw/machine/wiki path')
    return _safe(root, relative)


def _resources(root: Path, arguments: dict) -> dict:
    """Input: vault root/listing args. Output: one bounded directory page; no recursive inventory or file contents."""
    relative = arguments.get('path', 'raw')
    target = _vault_resource(root, relative)
    offset, limit = arguments.get('offset', 0), arguments.get('limit', 20)
    import heapq
    def entries():
        for item in target.iterdir():
            try:
                path = item.relative_to(root).as_posix()
                _vault_resource(root, path)
                if not item.is_dir() and item.suffix.lower() not in LOCAL_TEXT_SUFFIXES:
                    continue
                yield dict(path=path, directory=item.is_dir(), bytes=item.stat().st_size)
            except (ValueError, OSError):
                continue
    # Keep only the requested prefix in memory; never serialize the full catalog.
    selected = heapq.nsmallest(offset + limit + 1, entries(), key=lambda item: item['path'])
    page = selected[offset:offset + limit]
    return dict(items=page, total=None, offset=offset,
        next_offset=offset + limit if len(selected) > offset + limit else None)


def _json_bytes(value: object) -> bytes:
    """Input: JSON-compatible object. Output: bytes; canonical UTF-8 with nonfinite numbers rejected."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _integer(value: object, name: str, minimum: int, maximum: int | None = None) -> int:
    """Input: object/name str/int bounds. Output: exact int or ValueError; booleans are not numbers."""
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError('invalid ' + name + ' bound')
    return value


def _text(value: object, name: str, *, maximum: int = MAX_QUERY_CHARS) -> str:
    """Input: object/name str/character bound int. Output: str or ValueError, without identity truncation."""
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError('invalid ' + name)
    return value


def _read(root: Path, relative: str) -> bytes:
    """Input: vault Path/relative str. Output: bounded bytes; reject unsafe paths and large resources."""
    from wqb.semantic_compilation import _safe
    path = _safe(root, relative)
    if path.stat().st_size > MAX_RESOURCE_BYTES:
        raise ValueError('query resource exceeds read bound')
    with path.open('rb') as stream:
        raw = stream.read(MAX_RESOURCE_BYTES + 1)
    if len(raw) > MAX_RESOURCE_BYTES:
        raise ValueError('query resource exceeds read bound')
    return raw


def _source_index(root: Path) -> dict:
    """Input: vault Path. Output: path->source dict; reject malformed or ambiguous indexed identities."""
    rows = {}
    for line in _read(root, 'machine/source_index.jsonl').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get('path'), str) or row['path'] in rows:
            raise ValueError('invalid or duplicate source index identity')
        rows[row['path']] = row
        if len(rows) > MAX_SOURCE_INDEX_ROWS:
            raise ValueError('source index exceeds row bound')
    return rows


def _material(root: Path, row: dict, *, direct: bool = False) -> tuple[dict, str]:
    """Input: vault Path/indexed source dict. Output: verified metadata/text tuple with original age and hashes."""
    if direct:
        from wqb.direct_knowledge import read_direct_source
        return read_direct_source(root, row)
    from wqb.research_resource_catalog import _fresh
    from wqb.semantic_compilation import _material as read_material
    _fresh(row.get('captured_at'), datetime.now(timezone.utc))
    source, text = read_material(root, row)
    if row.get('file_sha256', source['file_sha256']).lower() != source['file_sha256']:
        raise ValueError('indexed full-file hash mismatch')
    return source, text


def _lexical(row: dict, query: str) -> bool:
    """Input: record dict/query str. Output: bool; require every lexical token without semantic inference."""
    terms = re.findall(r'\w+', query.casefold())
    haystack = _json_bytes(row).decode('utf-8').casefold()
    return all(term in haystack for term in terms)


def _matches_scope(row: dict, scope: dict) -> bool:
    """Input: facts/exact scope dicts. Output: bool; match only explicitly declared scope restrictions."""
    from wqb.template_binding import _scope_matches
    if 'available_scopes' in row:
        return _scope_matches(row, scope)
    for key in SCOPE_KEYS:
        if key in row and (type(row[key]) is not type(scope[key]) or row[key] != scope[key]):
            return False
    for key, plural in (('region', 'regions'), ('delay', 'delays'), ('universe', 'universes')):
        values = row.get('compatible_' + plural, [])
        if not isinstance(values, list):
            raise ValueError('invalid compatible scope list')
        if values and not any(type(value) is type(scope[key]) and value == scope[key] for value in values):
            return False
    return True


def _page(rows: list[dict], offset: int, limit: int) -> dict:
    """Input: ordered dict rows/offset/limit ints. Output: complete pagination metadata and selected rows."""
    end = offset + limit
    return dict(items=rows[offset:end], total=len(rows), offset=offset,
                next_offset=end if end < len(rows) else None)


def _documented_refs(root: Path, sources: list[dict]) -> list[dict]:
    """Input: vault Path/indexed source dicts. Output: standard evidence refs only where path/hash/date are explicit."""
    from wqb.semantic_compilation import _safe
    refs = []
    for source in sources:
        path, digest, captured = source.get('path'), source.get('content_hash'), source.get('captured_at')
        if not isinstance(path, str) or not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', digest):
            continue
        if not isinstance(captured, str):
            continue
        try:
            stamp = datetime.fromisoformat(captured.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                continue
            _safe(root, path, source=True)
        except ValueError:
            continue
        refs.append(dict(source_path=path, sha256=digest, capture_date=captured[:10],
                         kind='documented', experiment_refs=[]))
    return refs


def _field_card(root: Path, row: dict, index: dict) -> dict:
    """Input: vault Path/indexed field row/source index dicts. Output: exact catalog-role card and indexed evidence refs."""
    identity = (row.get('dataset_id'), row.get('field_id'))
    if any(not isinstance(value, str) or not value.strip() for value in identity):
        raise ValueError('field role selector requires exact dataset_id and field_id')
    paths = row.get('source_paths', [])
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
        raise ValueError('field source_paths must be a string list')
    refs = _documented_refs(root, [index[path] for path in sorted(set(paths)) if path in index])
    return dict(deepcopy(row), role_selector='field:' + identity[0] + '/' + identity[1], evidence_refs=refs)


def _operators(root: Path, scope: dict, arguments: dict, *, direct: bool = False) -> tuple[list[dict], list]:
    """Input: vault Path/scope/arguments dicts. Output: current official operator cards/warnings lists."""
    from wqb.research_resource_catalog import _operator_facts, _identity, MAX_OPERATORS
    index = _source_index(root)
    if direct:
        from wqb.research_resource_catalog import _rows
        notes, state = [], {}
        cards = [deepcopy(row) for row in _rows(root, 'operator_ledger', notes, scan_state=state)
                 if arguments.get('operator', row.get('operator')) == row.get('operator')
                 and _matches_scope(row, scope) and _lexical(row, arguments.get('query', ''))]
        return cards, notes
    candidates = [(datetime.fromisoformat(row['captured_at'].replace('Z', '+00:00')), path, row)
                  for path, row in index.items() if path.startswith('raw/platform/')
                  and Path(path).stem.lower() == 'operators' and Path(path).suffix.lower() in ('.json', '.jsonl', '.md')]
    if not candidates:
        return [], ['operator_catalog_unavailable: no indexed official operator inventory']
    newest = max(item[0] for item in candidates)
    cards = {}
    for captured, path, row in sorted(candidates, key=lambda item: item[1]):
        if captured != newest:
            continue
        source, text = _material(root, row)
        facts = _operator_facts(text, jsonl=Path(path).suffix.lower() == '.jsonl')
        if not facts or len(facts) > MAX_OPERATORS:
            raise ValueError('invalid current official operator inventory bound')
        seen = set()
        for fact in facts:
            name = _identity(fact)
            if name in seen:
                raise ValueError('duplicate current operator identity: ' + name)
            seen.add(name)
            # Authority is the consumed catalog, not embedded source_paths/refs.
            payload = {key: deepcopy(value) for key, value in fact.items()
                       if key not in ('id', 'name', 'operator', 'source_paths', 'source_refs',
                                      'source_path', 'content_hash', 'captured_at', 'evidence_refs')}
            if name not in cards:
                cards[name] = dict(payload, operator=name, source_paths=[], source_refs=[])
            else:
                previous = cards[name]
                for key, value in payload.items():
                    if key in previous and previous[key] != value:
                        raise ValueError('conflicting current operator fact: ' + name + '/' + key)
                    previous[key] = value
            cards[name]['source_paths'].append(path)
            cards[name]['source_refs'].append(source)
            if len(cards) > MAX_OPERATORS:
                raise ValueError('current operator inventory exceeds bound')
    warnings, selected = [], []
    for name, card in sorted(cards.items()):
        if arguments.get('operator', name) != name or not _matches_scope(card, scope) or not _lexical(card, arguments.get('query', '')):
            continue
        definition = card.get('definition')
        typed = (isinstance(definition, dict) and isinstance(definition.get('input_types'), list)
                 and isinstance(definition.get('output_type'), str)
                 and isinstance(definition.get('parameters'), list))
        primary = card['source_refs'][0]
        card.update(source_path=primary['path'], content_hash=primary['content_hash'], captured_at=primary['captured_at'])
        card['evidence_refs'] = _documented_refs(root, card['source_refs'])
        card['signature_status'] = 'documented' if typed else 'unknown'
        if card['signature_status'] == 'unknown':
            warnings = ['unknown_signature: some matching operators lack typed signatures; inspect signature_status']
        if isinstance(definition, dict):
            definition['evidence_refs'] = deepcopy(card['evidence_refs'])
        selected.append(card)
    return selected, warnings


def _templates(root: Path, scope: dict, arguments: dict, *, direct: bool = False) -> tuple[list[dict], list]:
    """Input: vault Path/scope/arguments dicts. Output: canonical template cards/warnings, without status promotion."""
    from wqb.knowledge_compile import read_semantic_rows
    if direct:
        from wqb.research_resource_catalog import _rows
        notes, state = [], {}
        templates = list(_rows(root, 'template_library', notes, scan_state=state))
        receipt = None
    else:
        receipt, _, templates = read_semantic_rows(root)
    rows, seen = [], set()
    for template in templates:
        identity = template.get('template_id')
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError('missing or duplicate template identity')
        seen.add(identity)
        if (arguments.get('template_id', identity) != identity or not _matches_scope(template, scope)
                or not _lexical(template, arguments.get('query', ''))):
            continue
        card = deepcopy(template)
        if receipt is not None:
            card['resource_ref'] = dict(resource='template_library', release_id=receipt.get('release_id'),
                                        sha256=receipt['digests']['template_library'])
        rows.append(card)
    return sorted(rows, key=lambda row: row['template_id']), []


def _experience(root: Path, scope: dict, arguments: dict) -> tuple[list[dict], list]:
    """Input: vault Path/scope/arguments dicts. Output: observations/warnings; cross-scope transfer requires explicit opt-in."""
    from wqb.mechanism_evidence import select_mechanism_context
    try:
        raw = _read(root, 'machine/mechanism_evidence.json')
    except FileNotFoundError:
        return [], ['experience_unavailable: no current compiled mechanism evidence']
    view = json.loads(raw)
    if (not isinstance(view, dict) or not isinstance(view.get('groups'), list)
            or not isinstance(view.get('input_digest'), str)):
        raise ValueError('invalid compiled mechanism evidence')
    ref = dict(path='machine/mechanism_evidence.json', sha256=hashlib.sha256(raw).hexdigest(),
               input_digest=view['input_digest'])
    rows, seen = [], set()
    for group in view['groups']:
        identity = group.get('group_id')
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError('missing or duplicate experience identity')
        seen.add(identity)
        experiment = group['experiment']
        first_arm = next(iter(experiment.get('arms', [])), {})
        cohort = group.get('cohort', {})
        captured = cohort.get('scope', cohort.get('settings', first_arm.get('scope', first_arm.get('settings', {}))))
        if not isinstance(captured, dict) or any(key not in captured for key in ('region', 'delay', 'universe')):
            continue
        exact = _matches_scope(captured, scope)
        if (not exact and not arguments.get('include_other_scopes', False)) or not _lexical(group, arguments.get('query', '')):
            continue
        filters = {key: arguments[key] for key in ('mechanism_family', 'experiment_id') if key in arguments}
        if 'group_id' in arguments and identity != arguments['group_id']:
            continue
        # The existing reader owns mechanism matching/order. Process one eligible
        # group at a time so its twelve-context prompt cap never hides query pages.
        result = select_mechanism_context(dict(view, groups=[group]), filters, maximum=1)
        if result['items']:
            card = result['items'][0]
            card['evidence_view_ref'] = ref
            card['scope'] = deepcopy(captured)
            card['scope_relation'] = 'exact' if exact else 'transfer_only'
            if not exact:
                card['scope_warning'] = TRANSFER_WARNING
            rows.append(card)
    rows.sort(key=lambda row: (row['label'] == 'supports_prediction_in_scope', row['group_id']))
    warnings = [] if rows else ['experience_no_matches: no scoped observations match this query']
    if any(row['scope_relation'] == 'transfer_only' for row in rows):
        warnings.append(TRANSFER_WARNING)
    return rows, warnings


def _source(root: Path, arguments: dict, *, direct: bool = False) -> dict:
    """Input: vault Path/arguments dict. Output: one bounded indexed source excerpt plus full provenance."""
    path = arguments.get('path')
    if direct and isinstance(path, str) and path.startswith(('raw/', 'machine/', 'wiki/')):
        target = _vault_resource(root, path)
        if target.suffix.lower() not in LOCAL_TEXT_SUFFIXES:
            raise ValueError('resource is not readable text; use catalog query tools for binary indexes')
        start, length = arguments.get('start', 0), arguments.get('length', 2000)
        _integer(start, 'start', 0, MAX_RESOURCE_BYTES)
        before = target.stat()
        with target.open('r', encoding='utf-8-sig') as stream:
            prefix = stream.read(start)
            if len(prefix) != start:
                raise ValueError('source start exceeds text length')
            excerpt = stream.read(length)
            more = bool(stream.read(1))
        after = target.stat()
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise ValueError('resource changed during read; query again')
        end = start + len(excerpt)
        return dict(items=[dict(source_paths=[path], source_refs=[dict(path=path,
            source_type='local_resource', knowledge_status='unreviewed', captured_at=None,
            platform_capture=False, excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest())],
            excerpt=excerpt, start=start, end=end, total_chars=None,
            next_start=end if more else None)], total=1, offset=0, next_offset=None)
    index = _source_index(root)
    if not isinstance(path, str) or not path.startswith('raw/') or path not in index:
        raise ValueError('source path must reference an indexed raw source')
    source, text = _material(root, index[path], direct=direct)
    start, length = arguments.get('start', 0), arguments.get('length', 2000)
    if start > len(text):
        raise ValueError('source start exceeds text length')
    end = min(start + length, len(text))
    item = dict(source_paths=[path], source_refs=[source], excerpt=text[start:end],
                start=start, end=end, total_chars=len(text), next_start=end if end < len(text) else None)
    return dict(items=[item], total=1, offset=0, next_offset=None)


def query_knowledge(root: Path, generation: str, scope: dict, operation: str, arguments: dict,
                    *, direct_knowledge_version: int | None = None) -> dict:
    """Input: vault Path/generation str/exact scope dict/operation str/arguments dict.

    Scope permits only instrument_type,region,delay,universe and optional as_of.
    Output: deterministic JSON dict with operation,generation,items,total,offset,
    next_offset,warnings. All operations recheck generation before/after reads.
    Common search args: query:str='',offset:int=0,limit:int=20 (1..50).
    fields additionally accepts field_type or exact identities:[[dataset,field]];
    exact identities exclude query/field_type. Every field card has the literal
    role_selector='field:'+dataset_id+'/'+field_id (identity, not economic meaning)
    plus evidence_refs from explicit indexed source metadata, without raw validation.
    operators accepts operator:str and exposes primary source_path/content_hash/
    captured_at plus evidence_refs in the documented design-schema shape; refs
    document consumed facts, never manufacture missing technical types.
    templates template_id:str; experience mechanism_family/experiment_id/group_id.
    experience alone accepts include_other_scopes:bool=False. Opt-in preserves
    original scope/measurement_period and marks scope_relation exact/transfer_only;
    transfer-only cards carry an explicit warning, never wider execution authority.
    source accepts path:str,start:int=0,length:int=2000 (1..8000 characters),
    and no search args. Errors raise ValueError/OSError; never return partial or
    silently shortened identity data. No validate, preparation, writes or network.
    """
    backend = importlib.import_module('wqb.research_query_index')
    from wqb.direct_knowledge import direct_knowledge_enabled, WARNING
    direct = (direct_knowledge_enabled(dict(direct_knowledge_version=direct_knowledge_version))
              if direct_knowledge_version is not None else False)
    root = Path(root)
    if not isinstance(generation, str) or not generation:
        raise ValueError('generation must be a nonempty string')
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ValueError('unsupported read-only query operation')
    if (type(scope) is not dict or any(key not in scope for key in SCOPE_KEYS)
            or set(scope) - (set(SCOPE_KEYS) | {'as_of'})):
        raise ValueError('queries require exact scope')
    if (type(scope['delay']) is not int or scope['delay'] < 0
            or any(not isinstance(scope[key], str) or not scope[key].strip()
                   for key in ('instrument_type', 'region', 'universe'))):
        raise ValueError('invalid exact scope')
    if 'as_of' in scope:
        stamp = _text(scope['as_of'], 'scope.as_of')
        if datetime.fromisoformat(stamp.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('scope.as_of requires timezone')
    if type(arguments) is not dict:
        raise ValueError('query arguments must be an object')
    backend.validate_query_generation(root, generation)
    common = {'query', 'offset', 'limit'}
    extras = dict(fields={'field_type', 'identities'}, operators={'operator'}, templates={'template_id'},
                  experience={'mechanism_family', 'experiment_id', 'group_id', 'include_other_scopes'},
                  source={'path', 'start', 'length'}, resources={'path'})
    allowed = extras[operation] | (common if operation != 'source' else set())
    if set(arguments) - allowed:
        raise ValueError('unknown query arguments: ' + ','.join(sorted(set(arguments) - allowed))
            + '; allowed: ' + ','.join(sorted(allowed)))
    if 'include_other_scopes' in arguments and type(arguments['include_other_scopes']) is not bool:
        raise ValueError('include_other_scopes must be a boolean')
    for key in ('query', 'operator', 'template_id', 'mechanism_family', 'experiment_id', 'group_id', 'path'):
        if key in arguments:
            _text(arguments[key], key)
            if key != 'query' and not arguments[key]:
                raise ValueError('empty ' + key)
    offset = _integer(arguments.get('offset', 0), 'offset', 0)
    limit = _integer(arguments.get('limit', 20), 'limit', 1, MAX_PAGE_SIZE)
    warnings = [UNKNOWN_WARNING]
    if direct:
        warnings.append(WARNING)
    if operation == 'fields':
        field_type = arguments.get('field_type')
        if field_type is not None and field_type not in ('MATRIX', 'VECTOR', 'GROUP'):
            raise ValueError('invalid field_type')
        if 'identities' in arguments:
            if 'query' in arguments or 'field_type' in arguments:
                raise ValueError('exact identities exclude query and field_type')
            identities = arguments['identities']
            if not isinstance(identities, list) or not 1 <= len(identities) <= MAX_PAGE_SIZE:
                raise ValueError('invalid exact field identities bound')
            pairs = []
            for pair in identities:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ValueError('field identity requires dataset_id and field_id')
                if any(not _text(value, 'field identity') for value in pair):
                    raise ValueError('empty field identity')
                pairs.append(tuple(pair))
            if len(set(pairs)) != len(pairs):
                raise ValueError('duplicate exact field identity')
            rows = backend.read_field_rows(root, generation, scope, pairs)
            page = _page(rows, offset, limit)
        else:
            result = backend.query_fields(root, generation, scope, query=arguments.get('query', ''),
                                          field_type=field_type, offset=offset, limit=limit)
            page = {key: result[key] for key in ('items', 'total', 'offset', 'next_offset')}
            warnings.extend(result.get('warnings', []))
        index = _source_index(root)
        page['items'] = [_field_card(root, row, index) for row in page['items']]
        if any(not row['evidence_refs'] or len(row['evidence_refs']) < len(set(row.get('source_paths', [])))
               for row in page['items']):
            warnings.append('field_source_evidence_unavailable: some cards lack complete indexed raw path/hash/date refs')
    elif operation == 'resources':
        if not direct:
            raise ValueError('resource discovery requires direct knowledge mode')
        page = _resources(root, arguments)
    elif operation == 'source':
        _integer(arguments.get('start', 0), 'start', 0)
        _integer(arguments.get('length', 2000), 'length', 1, MAX_EXCERPT_CHARS)
        page = _source(root, arguments, direct=direct)
    else:
        readers = dict(operators=_operators, templates=_templates, experience=_experience)
        options = dict(direct=direct) if operation in ('operators', 'templates') else {}
        rows, notes = readers[operation](root, scope, arguments, **options)
        page = _page(rows, offset, limit)
        warnings.extend(notes)
    unique_warnings = {_json_bytes(warning): warning for warning in warnings}
    response = dict(operation=operation, generation=generation, **page,
                    warnings=[unique_warnings[key] for key in sorted(unique_warnings)])
    if len(_json_bytes(response)) > MAX_RESPONSE_BYTES:
        raise ValueError('query response exceeds byte bound; request a smaller page or source excerpt')
    backend.validate_query_generation(root, generation)
    return response
