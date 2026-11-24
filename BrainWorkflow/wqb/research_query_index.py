"""One replaceable, rebuildable ledger-offset cache; never source or execution authority."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from wqb.field_source_catalog import CATALOG_ROOT, _hash_file, _json_bytes
from wqb.knowledge_contracts import _capture_timestamp, _source_contract_bytes, _source_contract_path
from wqb.lockfile import exclusive_json_lock
from wqb.semantic_contracts import resource_scope_from_dict


SCHEMA_VERSION = 2
MAX_LINE_BYTES = 1_000_000
MAX_ROWS = 500_000
MAX_PAGE_SIZE = 100
MAX_SELECTED_IDENTITIES = 256
MAX_SELECTED_BYTES = 2_000_000
MAX_QUERY_BYTES = 4096
MAX_MANIFEST_BYTES = 32_000
LOCK_SECONDS = 5.0
LOCK_SLEEP_SECONDS = 0.05
LOCK_STALE_SECONDS = 3600.0
POINTER_PATH = CATALOG_ROOT + '/research-query.json'
INDEX_PATH = CATALOG_ROOT + '/research-query.sqlite3'
LOCK_PATH = CATALOG_ROOT + '/research-query.lock'
INPUT_PATHS = {'data_ledger': 'machine/data_ledger.jsonl', 'source_index': 'machine/source_index.jsonl'}
SUPPORTING_PATHS = {'operator_ledger': 'machine/operator_ledger.jsonl',
                    'template_library': 'machine/template_library.jsonl',
                    'mechanism_evidence': 'machine/mechanism_evidence.json',
                    'semantic_release': 'machine/semantic_release.json'}
CARD_KEYS = ('dataset_id', 'dataset_name', 'field_id', 'field_type', 'field_description',
             'semantic_tags', 'source_paths', 'source_updated_at', 'source_quality', 'coverage',
             'coverage_status', 'date_coverage', 'units', 'vector_grain', 'available_at',
             'timing_contract', 'field_semantics_ref', 'simulation_usage_count',
             'submitted_usage_count', 'repair_usage_count', 'last_used_at', 'best_result_label',
             'correlation_risk', 'crowding_risk')
SEARCH_KEYS = ('dataset_id', 'dataset_name', 'field_id', 'field_type', 'field_description',
               'semantic_tags', 'data_category', 'units', 'vector_grain')


def _file_identity(path: Path) -> dict:
    """Input: checked file Path. Output: dict of size/timestamps/inode/device for change detection."""
    stat = path.stat()
    return dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns, ctime_ns=stat.st_ctime_ns,
                inode=stat.st_ino, device=stat.st_dev)


def _inputs(root: Path) -> dict:
    """Input: vault Path. Output: stat identities/optional None; reject links and missing required inputs."""
    identities = {name: _file_identity(_source_contract_path(root, path)) for name, path in INPUT_PATHS.items()}
    for name, relative in SUPPORTING_PATHS.items():
        path = _source_contract_path(root, relative)
        identities[name] = _file_identity(path) if path.exists() else None
    return identities


def _generation(manifest: dict) -> str:
    """Input: manifest dict. Output: SHA256 str binding required/optional hashes, absences and file identities."""
    identity = {key: manifest[key] for key in
                ('schema_version', 'ledger_sha256', 'source_index_sha256', 'supporting_sha256', 'inputs')}
    return hashlib.sha256(_json_bytes(identity)).hexdigest()


def _scope_key(scope: dict) -> str:
    """Input: exact scope dict with optional aware as_of str. Output: four-key JSON str; reject other extras.

    as_of is validated query metadata, not a geographic lookup key or permission
    to change evidence dates. Callers retain the original scope in response metadata.
    """
    if not isinstance(scope, dict):
        raise ValueError('query scope must be an object')
    if 'as_of' in scope:
        _capture_timestamp(scope['as_of'])
    geographic = {key: value for key, value in scope.items() if key != 'as_of'}
    return _json_bytes(resource_scope_from_dict(geographic)).decode('utf-8')


def _row_scopes(row: dict) -> set[str]:
    """Input: canonical ledger dict. Output: exact scope keys; never infer Cartesian scope products."""
    scopes = row.get('available_scopes')
    if scopes is None:
        scopes = [{key: row.get(key) for key in ('instrument_type', 'region', 'delay', 'universe')}]
    if not isinstance(scopes, list) or not scopes:
        raise ValueError('ledger row requires explicit exact scopes')
    return {_scope_key(scope) for scope in scopes}


def _row_identity(row: dict) -> tuple[str, str]:
    """Input: ledger dict. Output: dataset/field tuple[str,str]; reject blank or nontext identities."""
    if not isinstance(row, dict):
        raise ValueError('ledger row must be an object')
    identity = row.get('dataset_id'), row.get('field_id')
    if any(not isinstance(value, str) or not value.strip() for value in identity):
        raise ValueError('ledger row requires dataset_id and field_id')
    return identity


def _check_inputs(root: Path, manifest: dict) -> None:
    """Input: vault Path/manifest dict. Output: None; fail closed on any input change, appearance or removal."""
    if _inputs(root) != manifest['inputs']:
        raise ValueError('query generation inputs changed; explicit preparation required')


def _reusable_query_index(root: Path) -> dict | None:
    """Input: knowledge root Path. Output: verified existing manifest dict or None; never write or scan inputs."""
    try:
        pointer = json.loads(_source_contract_bytes(_source_contract_path(root, POINTER_PATH), MAX_MANIFEST_BYTES))
        manifest = validate_query_generation(root, pointer['generation'])
        connection = _open_index(root, manifest)
        connection.close()
        _check_inputs(root, manifest)
        return manifest
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return None


def prepare_query_index(root: Path) -> dict:
    """Input: canonical knowledge root Path. Output: manifest dict; sole writer of disposable SQL/receipt.

    The generation binds full input SHA256s and file identities. Fields store
    searchable tokens and byte locators only; original rows remain in the ledger.
    Optional query context is hashed once here, including the semantic release
    pointer; existing readers still verify its immutable manifest and resources.
    Missing optional context is None, not a knowledge-readiness failure.
    Unchanged verified inputs/cache return immediately without rewriting files.
    Rebuilds replace one active SQL slot. Historical generation-named caches are
    not source evidence, but their separately authorized cleanup is not done here.
    """
    root = Path(root).absolute()
    pointer = _source_contract_path(root, POINTER_PATH)
    cached = _reusable_query_index(root)
    if cached is not None:
        return cached
    lock = _source_contract_path(root, LOCK_PATH)
    _source_contract_path(root, LOCK_PATH + '.guard')
    pointer.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_json_lock(lock, LOCK_SECONDS, LOCK_SLEEP_SECONDS, LOCK_STALE_SECONDS,
                             'research query index preparation busy'):
        cached = _reusable_query_index(root)
        if cached is not None:
            return cached
        inputs = _inputs(root)
        ledger = _source_contract_path(root, INPUT_PATHS['data_ledger'])
        source_index = _source_contract_path(root, INPUT_PATHS['source_index'])
        manifest = dict(schema_version=SCHEMA_VERSION, inputs=inputs,
                        source_index_sha256=_hash_file(source_index),
                        supporting_sha256={name: _hash_file(_source_contract_path(root, relative))
                                           if inputs[name] is not None else None
                                           for name, relative in SUPPORTING_PATHS.items()})
        temporary = _source_contract_path(root, CATALOG_ROOT + '/.query-building-' + uuid4().hex + '.sqlite3')
        receipt = _source_contract_path(root, CATALOG_ROOT + '/.query-receipt-' + uuid4().hex + '.json')
        connection = None
        try:
            connection = sqlite3.connect(temporary)
            connection.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            connection.execute('CREATE TABLE fields (scope TEXT, dataset_id TEXT, field_id TEXT, '
                               'field_type TEXT, search_text TEXT, offset INTEGER, length INTEGER, '
                               'row_sha256 TEXT, PRIMARY KEY(scope, dataset_id, field_id))')
            digest, count, lines = hashlib.sha256(), 0, 0
            with ledger.open('rb') as stream:
                while True:
                    offset = stream.tell()
                    raw = stream.readline(MAX_LINE_BYTES + 1)
                    if not raw:
                        break
                    lines += 1
                    if len(raw) > MAX_LINE_BYTES or lines > MAX_ROWS:
                        raise ValueError('ledger exceeds query index line/row bound')
                    digest.update(raw)
                    if not raw.strip():
                        continue
                    row = json.loads(raw)
                    dataset, field = _row_identity(row)
                    field_type = row.get('field_type')
                    if not isinstance(field_type, str):
                        raise ValueError('ledger field_type must be text (unknown may be empty)')
                    search = ' '.join(json.dumps(row[key], ensure_ascii=False) if not isinstance(row[key], str)
                                      else row[key] for key in SEARCH_KEYS if key in row).casefold()
                    for scope in sorted(_row_scopes(row)):
                        try:
                            connection.execute('INSERT INTO fields VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                                               (scope, dataset, field, field_type, search, offset, len(raw),
                                                hashlib.sha256(raw).hexdigest()))
                        except sqlite3.IntegrityError as error:
                            raise ValueError('duplicate same-scope field identity is ambiguous') from error
                    count += 1
            manifest.update(ledger_sha256=digest.hexdigest(), row_count=count)
            manifest['generation'] = _generation(manifest)
            manifest['index_path'] = INDEX_PATH
            connection.execute('INSERT INTO metadata VALUES (?, ?)',
                               ('generation', manifest['generation']))
            connection.execute('CREATE INDEX field_types ON fields(scope, field_type, dataset_id, field_id)')
            connection.commit()
            connection.close()
            connection = None
            _check_inputs(root, manifest)
            destination = _source_contract_path(root, manifest['index_path'])
            manifest['index_sha256'] = _hash_file(temporary)
            # Publish the DB before its receipt: interrupted publication fails closed.
            os.replace(temporary, destination)
            receipt.write_bytes(_json_bytes(manifest))
            _check_inputs(root, manifest)
            os.replace(receipt, pointer)
            return manifest
        finally:
            if connection is not None:
                connection.close()
            for path in (temporary, receipt):
                if path.exists():
                    _source_contract_path(root, path.relative_to(root).as_posix()).unlink()


def validate_query_generation(root: Path, generation: str) -> dict:
    """Input: knowledge root Path/generation str. Output: current manifest dict; read-only, no ledger scan.

    Stat identities detect required/optional input publication or removal, and a full SQL hash detects cache
    corruption. Selected row SHA256s are independently checked on materialization.
    This does not certify raw evidence, freshness, eligibility or authorization.
    """
    root = Path(root).absolute()
    try:
        if not isinstance(generation, str) or len(generation) != 64:
            raise ValueError('invalid query generation')
        manifest = json.loads(_source_contract_bytes(_source_contract_path(root, POINTER_PATH), MAX_MANIFEST_BYTES))
        if (not isinstance(manifest, dict) or set(manifest) != {
                'schema_version', 'generation', 'index_path', 'index_sha256', 'ledger_sha256',
                'source_index_sha256', 'supporting_sha256', 'inputs', 'row_count'}
                or type(manifest['schema_version']) is not int or manifest['schema_version'] != SCHEMA_VERSION
                or not isinstance(manifest['supporting_sha256'], dict)
                or set(manifest['supporting_sha256']) != set(SUPPORTING_PATHS)
                or manifest['generation'] != generation or _generation(manifest) != generation
                or manifest['index_path'] != INDEX_PATH):
            raise ValueError('query generation receipt mismatch')
        _check_inputs(root, manifest)
        for name, digest in manifest['supporting_sha256'].items():
            if ((digest is None) != (manifest['inputs'][name] is None)
                    or digest is not None and (not isinstance(digest, str) or len(digest) != 64
                                               or any(char not in '0123456789abcdef' for char in digest))):
                raise ValueError('invalid supporting resource hash/absence receipt')
        database = _source_contract_path(root, manifest['index_path'])
        if _hash_file(database) != manifest['index_sha256']:
            raise ValueError('corrupt query index; explicit preparation required')
        _check_inputs(root, manifest)
        return manifest
    except (OSError, KeyError, TypeError, UnicodeError, ValueError) as error:
        raise ValueError('query generation unavailable; explicit preparation required: ' + str(error)) from error


def _open_index(root: Path, manifest: dict) -> sqlite3.Connection:
    """Input: root Path/verified manifest dict. Output: readonly SQL connection, never create or repair."""
    database = _source_contract_path(root, manifest['index_path'])
    connection = sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.execute('PRAGMA query_only=ON')
        if connection.execute('SELECT value FROM metadata WHERE key=?', ('generation',)).fetchone() != (manifest['generation'],):
            raise ValueError('query index generation mismatch')
        return connection
    except BaseException:
        connection.close()
        raise


def _materialize(root: Path, manifest: dict, scope: str, locators: list) -> list[dict]:
    """Input: root/manifest/exact scope key/list[SQL tuple]. Output: original dict rows with hash/identity checks."""
    if not locators:
        return []
    ledger = _source_contract_path(root, INPUT_PATHS['data_ledger'])
    rows, total_bytes = [], 0
    with ledger.open('rb') as stream:
        for dataset, field, field_type, offset, length, row_hash in locators:
            if (type(offset) is not int or offset < 0 or type(length) is not int or not 0 < length <= MAX_LINE_BYTES
                    or offset + length > manifest['inputs']['data_ledger']['size']):
                raise ValueError('invalid query index row locator')
            total_bytes += length
            if total_bytes > MAX_SELECTED_BYTES:
                raise ValueError('selected ledger rows exceed byte bound; request smaller pages')
            stream.seek(offset)
            raw = stream.read(length)
            if hashlib.sha256(raw).hexdigest() != row_hash:
                raise ValueError('selected ledger row hash changed; explicit preparation required')
            row = json.loads(raw)
            if (_row_identity(row) != (dataset, field) or scope not in _row_scopes(row)
                    or row.get('field_type') != field_type):
                raise ValueError('selected ledger row identity/scope/type mismatch')
            rows.append(row)
    return rows


def query_fields(root: Path, generation: str, scope: dict, query: str = '',
                 field_type: str | None = None, offset: int = 0, limit: int = 20) -> dict:
    """Input: Path/generation/exact scope, literal search/type and integer page. Output: bounded card-page dict.

    Empty search and no type enumerate every exact-scope identity, sorted by
    dataset_id/field_id. Follow next_offset until None; total is indexed visibility,
    not a claim of complete capture or executable eligibility.
    """
    root = Path(root).absolute()
    scope_key = _scope_key(scope)
    if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE
            or not isinstance(query, str) or len(query.encode('utf-8')) > MAX_QUERY_BYTES
            or field_type is not None and (not isinstance(field_type, str) or len(field_type) > MAX_QUERY_BYTES)):
        raise ValueError('invalid field query bounds/type')
    manifest = validate_query_generation(root, generation)
    connection = None
    try:
        connection = _open_index(root, manifest)
        where, parameters = 'scope=?', [scope_key]
        for token in query.casefold().split():
            where += ' AND instr(search_text, ?) > 0'
            parameters.append(token)
        if field_type is not None:
            where += ' AND field_type=?'
            parameters.append(field_type)
        total = connection.execute('SELECT COUNT(*) FROM fields WHERE ' + where, parameters).fetchone()[0]
        locators = connection.execute('SELECT dataset_id, field_id, field_type, offset, length, row_sha256 '
                                      'FROM fields WHERE ' + where + ' ORDER BY dataset_id, field_id LIMIT ? OFFSET ?',
                                      parameters + [limit, offset]).fetchall()
        rows = _materialize(root, manifest, scope_key, locators)
        items = [dict({key: row[key] for key in CARD_KEYS if key in row},
                      scope=dict(scope), row_sha256=locator[-1]) for row, locator in zip(rows, locators)]
        _check_inputs(root, manifest)
        return dict(generation=generation, scope=dict(scope), query=query, field_type=field_type,
                    offset=offset, limit=limit, total=total,
                    next_offset=offset + len(items) if offset + len(items) < total else None, items=items)
    except (OSError, sqlite3.Error) as error:
        raise ValueError('query index unavailable; explicit preparation required') from error
    finally:
        if connection is not None:
            connection.close()


def read_field_rows(root: Path, generation: str, scope: dict,
                    identities: list[tuple[str, str]]) -> list[dict]:
    """Input: Path/generation/exact scope/list[dataset,field tuples]. Output: canonical dict rows in input order.

    Resolve only requested original rows. Missing or duplicate selectors fail
    closed, with no fallback scan, shadowing, scope widening or inferred facts.
    """
    root = Path(root).absolute()
    scope_key = _scope_key(scope)
    if (not isinstance(identities, list) or len(identities) > MAX_SELECTED_IDENTITIES
            or any(not isinstance(item, tuple) or len(item) != 2
                   or any(not isinstance(value, str) or not value.strip() for value in item) for item in identities)):
        raise ValueError('invalid selected field identities')
    if len(set(identities)) != len(identities):
        raise ValueError('duplicate selected field identity is ambiguous')
    manifest = validate_query_generation(root, generation)
    connection = None
    try:
        connection = _open_index(root, manifest)
        locators = []
        for dataset, field in identities:
            matches = connection.execute('SELECT dataset_id, field_id, field_type, offset, length, row_sha256 '
                                         'FROM fields WHERE scope=? AND dataset_id=? AND field_id=?',
                                         (scope_key, dataset, field)).fetchall()
            if len(matches) != 1:
                raise ValueError('missing or ambiguous exact-scope field identity')
            locators.append(matches[0])
        rows = _materialize(root, manifest, scope_key, locators)
        _check_inputs(root, manifest)
        return rows
    except (OSError, sqlite3.Error) as error:
        raise ValueError('query index unavailable; explicit preparation required') from error
    finally:
        if connection is not None:
            connection.close()
