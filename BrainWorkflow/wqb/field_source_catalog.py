"""Rebuildable SQLite offsets; raw capture bytes, never this index, own facts."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
from uuid import uuid4


CATALOG_VERSION = 1
CATALOG_ROOT = 'machine/field_catalogs'
HASH_CHUNK_BYTES = 1_048_576
MAX_POINTER_BYTES = 32_000
CATALOG_LOCK_SECONDS = 60.0
CATALOG_LOCK_STALE_SECONDS = 3600.0
SQL_IDENTITY_PAGE_SIZE = 256


class _InvalidCatalog(ValueError):
    """A disposable cache failed validation; fall back to raw, not invented facts."""


def _json_bytes(value: dict) -> bytes:
    """Input: JSON object dict. Output: canonical UTF-8 bytes for mechanical identities."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')


def _hash_file(path: Path) -> str:
    """Input: checked file Path. Output: SHA256 str without loading a full capture/index."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(HASH_CHUNK_BYTES), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _source_identity(source: Path) -> tuple:
    """Input: canonical capture Path. Output: (vault Path, relative str), rejecting links and wrong namespaces."""
    from wqb.knowledge_contracts import _source_contract_path
    absolute = source.absolute()
    if len(absolute.parents) < 5:
        raise ValueError('canonical field capture required')
    root = absolute.parents[4]
    relative = absolute.relative_to(root).as_posix()
    parts = PurePosixPath(relative).parts
    if len(parts) != 5 or parts[:3] != ('raw', 'platform', 'data_fields') or parts[-1] != 'data_fields.jsonl':
        raise ValueError('canonical field capture required')
    return root, _source_contract_path(root, relative).relative_to(root).as_posix()


def _source_fingerprint(source: Path, manifest: dict) -> tuple:
    """Input: raw Path/manifest dict. Output: digest/count/stat/physical offsets/raw date, never cached claims.

    A uniform manifest epoch needs one raw date witness. Mixed epochs require
    a date-only raw pass to preserve the legacy earliest-date receipt exactly.
    """
    from wqb.knowledge_contracts import MAX_FIELD_CAPTURE_LINE_BYTES, _capture_json, _capture_timestamp
    before = source.stat()
    outcomes = manifest.get('latest_scope_outcomes') or [manifest]
    epochs = {_capture_timestamp(item['generated_at']) for item in outcomes if item.get('generated_at')}
    digest, count, offsets, oldest = hashlib.sha256(), 0, {}, None
    with source.open('rb') as stream:
        while True:
            offset = stream.tell()
            raw = stream.readline(MAX_FIELD_CAPTURE_LINE_BYTES + 1)
            if not raw:
                break
            if len(raw) > MAX_FIELD_CAPTURE_LINE_BYTES:
                raise ValueError('captured field line exceeds bound')
            digest.update(raw)
            if not raw.strip():
                continue
            count += 1
            offsets[offset] = (count, len(raw))
            if oldest is None or len(epochs) != 1:
                row = _capture_json(raw)
                _, captured = _row_identity(row, manifest)
                if oldest is None or captured < oldest[0]:
                    oldest = captured, row['generated_at']
    after = source.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('field source changed during indexing')
    return digest.hexdigest(), count, after, offsets, oldest[1] if oldest else None


def _row_identity(row: dict, manifest: dict) -> tuple:
    """Input: raw field row/manifest dicts. Output: (exact identity str, capture datetime); no semantic inference."""
    from wqb.knowledge_contracts import _capture_timestamp, _capture_manifest_outcome
    from wqb.semantic_contracts import resource_scope_from_dict
    if any(not isinstance(row.get(key), dict) for key in ('field', 'data_set', 'scope')):
        raise ValueError('invalid field capture row')
    identity = dict(dataset_id=row['data_set'].get('id'), field_id=row['field'].get('id'), scope=row['scope'])
    if any(not isinstance(identity[key], str) or not identity[key].strip() for key in ('dataset_id', 'field_id')):
        raise ValueError('invalid field identity')
    resource_scope_from_dict(row['scope'])
    captured = _capture_timestamp(row.get('generated_at'))
    outcome = _capture_manifest_outcome(manifest, row['scope'])
    nested = row['field'].get('dataset')
    if (row.get('endpoint') != '/data-fields'
            or nested is not None and (not isinstance(nested, dict) or nested.get('id') != identity['dataset_id'])
            or row.get('capture_generation_id') != outcome.get('capture_generation_id')
            or captured != _capture_timestamp(outcome.get('generated_at'))):
        raise ValueError('field capture endpoint, dataset or generation/date mismatch')
    return json.dumps(identity, sort_keys=True), captured


def _build(source: Path, manifest: dict, expected: dict, destination: Path) -> None:
    """Input: capture/manifest/expected identity/destination. Output: None; atomically build a derived offsets DB."""
    from wqb.knowledge_contracts import _capture_json, MAX_FIELD_CAPTURE_LINE_BYTES
    temporary = destination.with_name('.building-' + uuid4().hex + '.sqlite3')
    connection = None
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        connection = sqlite3.connect(temporary)
        connection.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        connection.execute('CREATE TABLE fields (identity TEXT PRIMARY KEY, ordinal INTEGER UNIQUE, offset INTEGER, '
                           'length INTEGER, row_sha256 TEXT, content_sha256 TEXT, captured_at TEXT, generation_id TEXT)')
        digest, count, oldest = hashlib.sha256(), 0, None
        with source.open('rb') as stream:
            while True:
                offset = stream.tell()
                raw = stream.readline(MAX_FIELD_CAPTURE_LINE_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_FIELD_CAPTURE_LINE_BYTES:
                    raise ValueError('captured field line exceeds bound')
                digest.update(raw)
                if not raw.strip():
                    continue
                count += 1
                row = _capture_json(raw)
                identity, captured = _row_identity(row, manifest)
                if oldest is None or captured < oldest[0]:
                    oldest = captured, row['generated_at']
                try:
                    connection.execute('INSERT INTO fields VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (identity, count, offset, len(raw), hashlib.sha256(raw).hexdigest(),
                         hashlib.sha256(_json_bytes(row)).hexdigest(), row['generated_at'], row['capture_generation_id']))
                except sqlite3.IntegrityError as error:
                    raise ValueError('duplicate captured field identity') from error
        if digest.hexdigest() != expected['source_sha256'] or count != expected['row_count']:
            raise ValueError('field source changed during indexing')
        metadata = dict(expected, original_captured_at=oldest[1] if oldest else None)
        connection.execute('INSERT INTO metadata VALUES (?, ?)', ('catalog', _json_bytes(metadata).decode('utf-8')))
        connection.commit()
        connection.close()
        connection = None
        os.replace(temporary, destination)
    finally:
        if connection is not None:
            connection.close()
        if temporary.exists() and not temporary.is_symlink() and not temporary.is_junction():
            temporary.unlink()


def _open_verified(path: Path, expected: dict, pointer: dict) -> sqlite3.Connection:
    """Input: checked DB Path/expected generation/pointer dicts. Output: read-only verified SQLite connection."""
    from wqb.knowledge_contracts import _capture_json
    if set(pointer) != {'generation', 'database_sha256'} or pointer['generation'] != expected['generation']:
        raise _InvalidCatalog('catalog pointer differs from source generation')
    if _hash_file(path) != pointer['database_sha256']:
        raise _InvalidCatalog('catalog bytes differ from build receipt')
    connection = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.execute('PRAGMA query_only=ON')
        stored = connection.execute('SELECT value FROM metadata WHERE key = ?', ('catalog',)).fetchone()
        if stored is None:
            raise _InvalidCatalog('missing catalog metadata')
        metadata = _capture_json(stored[0].encode('utf-8'))
        if any(metadata.get(key) != value or type(metadata.get(key)) is not type(value) for key, value in expected.items()):
            raise _InvalidCatalog('catalog metadata differs from capture')
        if connection.execute('SELECT COUNT(*) FROM fields').fetchone()[0] != expected['row_count']:
            raise _InvalidCatalog('catalog row count differs from source')
        return connection
    except BaseException:
        connection.close()
        raise


def _selected_locators(connection, wanted: set[str], bulk: bool):
    """Input: verified SQL connection/exact identity set/bulk flag. Output: bounded locator iterator, never facts."""
    columns = ('SELECT identity, ordinal, offset, length, row_sha256, content_sha256, captured_at, generation_id '
               'FROM fields')
    if bulk:
        yield from connection.execute(columns + ' ORDER BY ordinal')
        return
    keys = sorted(wanted)
    for start in range(0, len(keys), SQL_IDENTITY_PAGE_SIZE):
        page = keys[start:start + SQL_IDENTITY_PAGE_SIZE]
        yield from connection.execute(columns + ' WHERE identity IN (' + ','.join('?' for _ in page) + ')', page)


def _select(connection, source: Path, manifest: dict, expected: dict, identities: list,
            bulk_limits: dict | None, receipts_only: bool, stat, offsets: dict, original_date) -> dict:
    """Input: verified DB/raw/manifest/finite selectors. Output: existing scan schema, selected raw facts verified."""
    from wqb.knowledge_contracts import _capture_json, _source_contract_bytes, MAX_FIELD_CAPTURE_LINE_BYTES, MAX_FIELD_EXTRACT_BYTES, MAX_SOURCE_REPAIR_BYTES
    wanted = {json.dumps(identity, sort_keys=True) for identity in identities}
    selected, retained, used_bytes = {}, {}, 0
    with source.open('rb') as stream:
        for key, ordinal, offset, length, raw_hash, content_hash, captured, generation in _selected_locators(
                connection, wanted, bulk_limits is not None):
            keep = key in wanted
            if bulk_limits is not None:
                keep = (len(retained) < bulk_limits['max_fields']
                    and type(length) is int and used_bytes + length <= bulk_limits['max_bytes']
                    and key not in bulk_limits.get('excluded_keys', set())
                    and (bulk_limits.get('requested_keys') is None or key in bulk_limits['requested_keys']))
            if not keep and key not in wanted:
                continue
            if (type(offset) is not int or type(length) is not int or type(ordinal) is not int
                    or offset < 0 or not 0 < length <= MAX_FIELD_CAPTURE_LINE_BYTES
                    or offset + length > stat.st_size or offsets.get(offset) != (ordinal, length)):
                raise _InvalidCatalog('invalid catalog row locator')
            stream.seek(offset)
            raw = stream.read(length)
            if hashlib.sha256(raw).hexdigest() != raw_hash:
                raise _InvalidCatalog('catalog offset differs from original raw row')
            item = dict(row_sha256=raw_hash, record_number=ordinal, captured_at=captured, capture_generation_id=generation)
            if receipts_only or bulk_limits is not None:
                item.update(raw_bytes=length, row_content_sha256=content_hash)
            row = _capture_json(raw)
            actual, _ = _row_identity(row, manifest)
            if (actual != key or hashlib.sha256(_json_bytes(row)).hexdigest() != content_hash
                    or row['generated_at'] != captured or row['capture_generation_id'] != generation):
                raise _InvalidCatalog('catalog identity differs from original raw row')
            if not receipts_only and keep:
                item['row'] = row
            if keep:
                used_bytes += length
            if bulk_limits is None and not receipts_only and used_bytes > MAX_FIELD_EXTRACT_BYTES:
                raise ValueError('selected field bytes exceed extract bound')
            selected[key] = item
            if bulk_limits is not None and keep:
                retained[key] = item
    if not wanted <= selected.keys():
        raise ValueError('missing exact field capture identities')
    if bulk_limits is None and not receipts_only:
        from wqb.knowledge_contracts import _capture_timestamp
        epochs = {(_capture_timestamp(item['captured_at']), item['capture_generation_id']) for item in selected.values()}
        if len(epochs) != 1:
            raise ValueError('mixed capture epochs require separate source excerpts')
    output = retained if bulk_limits is not None else selected
    metadata = json.loads(connection.execute('SELECT value FROM metadata WHERE key = ?', ('catalog',)).fetchone()[0])
    if metadata.get('original_captured_at') != original_date:
        raise _InvalidCatalog('catalog capture date differs from original raw evidence')
    result = dict(original_sha256=expected['source_sha256'], original_rows=expected['row_count'],
                  selected=[output[key] for key in sorted(output)], source_stat=stat,
                  original_captured_at=original_date)
    if receipts_only or bulk_limits is not None:
        limit = MAX_SOURCE_REPAIR_BYTES if bulk_limits is None else bulk_limits.get('max_snapshot_bytes', MAX_SOURCE_REPAIR_BYTES)
        snapshot = _source_contract_bytes(source, limit) if stat.st_size <= limit else None
        if snapshot is not None and hashlib.sha256(snapshot).hexdigest() != expected['source_sha256']:
            raise ValueError('field source changed during selection')
        result.update(selected_by_identity=selected, source_bytes=snapshot)
    return result


def catalog_field_scan(source: Path, identities: list, manifest: dict, *, bulk_limits: dict | None = None,
                       create: bool = False, receipts_only: bool = False) -> dict | None:
    """Input: raw Path, exact identities/manifest and bounded flags. Output: compatible scan or optional cache miss.

    Only explicit maintenance creates/rebuilds this index. Callers still finalize
    the existing original/excerpt receipt session before treating it as evidence.
    """
    from wqb.knowledge_contracts import _source_contract_path, _source_contract_bytes, _capture_json, _capture_timestamp, MAX_CAPTURE_MANIFEST_BYTES
    from wqb.lockfile import exclusive_json_lock
    from wqb.runtime_control import _write
    if type(create) is not bool or type(receipts_only) is not bool:
        raise ValueError('catalog flags must be bool')
    root, relative = _source_identity(source)
    source = _source_contract_path(root, relative)
    reference = hashlib.sha256(relative.encode('utf-8')).hexdigest()
    pointer_path = _source_contract_path(root, CATALOG_ROOT + '/' + reference + '.json')
    if not create and not pointer_path.exists():
        return None
    manifest_bytes = _source_contract_bytes(source.with_name('manifest.json'), MAX_CAPTURE_MANIFEST_BYTES)
    if _capture_json(manifest_bytes) != manifest:
        raise ValueError('capture manifest differs from source')
    if (_capture_timestamp(manifest.get('generated_at')).date().isoformat() != source.parent.name
            or manifest.get('certification_status') not in {'complete', 'partial'}):
        raise ValueError('unverified capture manifest')
    digest, count, stat, offsets, original_date = _source_fingerprint(source, manifest)
    identity = dict(version=CATALOG_VERSION, source_path=relative, source_sha256=digest,
                    manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(), row_count=count)
    generation = hashlib.sha256(_json_bytes(identity)).hexdigest()
    expected = dict(identity, generation=generation)
    database = _source_contract_path(root, CATALOG_ROOT + '/' + generation + '.sqlite3')

    def open_cached():
        """Input: closed-over checked paths/identity. Output: verified read-only connection or None."""
        try:
            pointer = _capture_json(_source_contract_bytes(pointer_path, MAX_POINTER_BYTES))
            return _open_verified(database, expected, pointer)
        except (OSError, sqlite3.Error, _InvalidCatalog, ValueError, TypeError, KeyError):
            return None

    connection = open_cached()
    if connection is None and create:
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        lock = _source_contract_path(root, CATALOG_ROOT + '/build.lock')
        _source_contract_path(root, CATALOG_ROOT + '/build.lock.guard')
        with exclusive_json_lock(lock, CATALOG_LOCK_SECONDS, .05,
                                 CATALOG_LOCK_STALE_SECONDS, 'field catalog build busy'):
            connection = open_cached()
            if connection is None:
                _build(source, manifest, expected, database)
                _write(pointer_path, dict(generation=generation, database_sha256=_hash_file(database)))
                connection = open_cached()
    if connection is None:
        return None
    try:
        result = _select(connection, source, manifest, expected, identities, bulk_limits, receipts_only, stat,
                         offsets, original_date)
        after = source.stat()
        if (stat.st_size, stat.st_mtime_ns, stat.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('field source changed during selection')
        return result
    except (_InvalidCatalog, sqlite3.Error):
        return None
    finally:
        connection.close()
