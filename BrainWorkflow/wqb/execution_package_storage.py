"""Lossless local package objects; archival preparation alone never permits deletion."""
import gzip
import hashlib
import io
from pathlib import Path

from wqb.execution_package import (
    MAX_LOCAL_INPUT_BYTES, SEAL_PATH, TREE_PATH, SEAL_KEYS, _digest, _read, _root,
    load_execution_package, package_enabled,
)
from wqb.exploration_eligibility import _store_immutable
from wqb.knowledge_contracts import _write_immutable_source
from wqb.lockfile import json_lock_transition_guard
from wqb.semantic_compilation import _safe


ARCHIVE_INDEX = 'runtime/execution_package/payload_archive.json'
OBJECT_ROOT = 'runtime/execution_package/objects/'
MAX_COMPRESSED_BYTES = MAX_LOCAL_INPUT_BYTES + 1024 * 1024
MAX_ARCHIVED_INPUTS = 32
LOCK_SECONDS = 5.0
LOCK_POLL_SECONDS = .05


def _hash(value: bytes) -> str:
    """Input: bytes. Output: exact SHA256 string."""
    return hashlib.sha256(value).hexdigest()


def _hex(value: object) -> bool:
    """Input: object. Output: bool; accept only exact hexadecimal SHA256 strings."""
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _bytes(run: Path, relative: str, maximum: int) -> bytes:
    """Input: checked owner/relative path and byte bound. Output: stable ordinary single-link file bytes."""
    path = _safe(run, relative)
    before = path.stat()
    if not path.is_file() or before.st_nlink != 1 or before.st_size > maximum:
        raise ValueError('unsafe or oversized package archival input')
    with path.open('rb') as stream:
        value = stream.read(maximum + 1)
    after = _safe(run, relative).stat()
    identity = lambda stat: (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    if len(value) > maximum or identity(before) != identity(after):
        raise ValueError('package archival input changed')
    return value


def _owner_seal(run: Path) -> tuple[dict, str]:
    """Input: owner Path. Output: original seal and byte hash, without reopening archived payload or global catalogs."""
    manifest, manifest_hash = _read(run, 'run_manifest.json')
    seal, seal_hash = _read(run, SEAL_PATH)
    if (manifest.get('run_id') != run.name or not package_enabled(manifest['start_snapshot'])
            or set(seal) != SEAL_KEYS or seal['run_id'] != run.name
            or seal['manifest_sha256'] != manifest_hash
            or seal['snapshot_sha256'] != _digest(manifest['start_snapshot'])
            or seal['content_sha256'] != _digest({k: v for k, v in seal.items() if k != 'content_sha256'})):
        raise ValueError('package archive owner changed')
    return seal, seal_hash


def _inputs(seal: dict) -> dict:
    """Input: original seal dict. Output: exact sealed input map; no caller-controlled collection selectors."""
    references = [dict(path=TREE_PATH, sha256=seal['tree_sha256']),
                  seal['data_characteristics'], *seal['certificate_refs']]
    expected = {}
    for row in references:
        if set(row) != {'path', 'sha256'} or not _hex(row['sha256']):
            raise ValueError('invalid sealed archival reference')
        path = row['path']
        certificate = (type(path) is str and path.startswith('runtime/exploration/resources/')
                       and path.endswith('.json') and _hex(path.split('/')[-1][:-5])
                       and path == 'runtime/exploration/resources/' + path.split('/')[-1])
        if path not in {TREE_PATH, 'runtime/initial_research_planning/data_characteristics.json'} and not certificate:
            raise ValueError('unowned package archival path')
        if path in expected and expected[path] != row['sha256']:
            raise ValueError('conflicting package archival references')
        expected[path] = row['sha256']
    if not 1 <= len(expected) <= MAX_ARCHIVED_INPUTS:
        raise ValueError('package archival reference count exceeds bound')
    return expected


def load_package_archive(run: Path) -> dict:
    """Input: owning run Path. Output: owner-bound archival index; not retirement or execution permission."""
    run = _root(run)
    try:
        seal, seal_hash = _owner_seal(run)
        index, _ = _read(run, ARCHIVE_INDEX)
        if (set(index) != {'schema_version', 'run_id', 'seal_sha256', 'entries', 'content_sha256'}
                or type(index['schema_version']) is not int or index['schema_version'] != 1
                or index['run_id'] != run.name or index['seal_sha256'] != seal_hash
                or index['content_sha256'] != _digest({k: v for k, v in index.items() if k != 'content_sha256'})):
            raise ValueError('package archive index changed')
        expected, actual = _inputs(seal), {}
        if type(index['entries']) is not list or len(index['entries']) != len(expected):
            raise ValueError('package archive entries differ')
        for row in index['entries']:
            if (type(row) is not dict or set(row) != {'path', 'sha256', 'size', 'object_path', 'gzip_sha256', 'gzip_bytes'}
                    or row['path'] not in expected or row['path'] in actual
                    or row['sha256'] != expected[row['path']] or not _hex(row['gzip_sha256'])
                    or row['object_path'] != OBJECT_ROOT + row['sha256'] + '.json.gz'
                    or type(row['size']) is not int or not 0 <= row['size'] <= MAX_LOCAL_INPUT_BYTES
                    or type(row['gzip_bytes']) is not int or not 0 < row['gzip_bytes'] <= MAX_COMPRESSED_BYTES):
                raise ValueError('invalid package archive entry')
            actual[row['path']] = row
        return index
    except (OSError, KeyError, TypeError) as error:
        raise ValueError('package archive missing or malformed') from error


def read_archived_input(run: Path, relative: str) -> bytes:
    """Input: owner Path and exact sealed relative path. Output: verified original bytes; never extracts or resumes."""
    run = _root(run)
    index = load_package_archive(run)
    row = next((entry for entry in index['entries'] if entry['path'] == relative), None)
    if row is None:
        raise ValueError('requested input is not archived')
    try:
        compressed = _bytes(run, row['object_path'], MAX_COMPRESSED_BYTES)
        if len(compressed) != row['gzip_bytes'] or _hash(compressed) != row['gzip_sha256']:
            raise ValueError('compressed package object changed')
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode='rb') as stream:
            value = stream.read(row['size'] + 1)
        if len(value) != row['size'] or _hash(value) != row['sha256']:
            raise ValueError('archived package input changed')
        return value
    except (OSError, EOFError) as error:
        raise ValueError('unreadable package archive object') from error


def prepare_package_archive(run: Path) -> dict:
    """Input: fully sealed owning run. Output: immutable lossless index; originals and authority remain untouched."""
    run = _root(run)
    with json_lock_transition_guard(_safe(run, 'runtime/execution_package/archive_guard'),
            LOCK_SECONDS, LOCK_POLL_SECONDS, 'package archival preparation busy'):
        package = load_execution_package(run)
        if _safe(run, ARCHIVE_INDEX).exists():
            index = load_package_archive(run)
            for row in index['entries']:
                read_archived_input(run, row['path'])
            return index
        _, seal_hash = _owner_seal(run)
        entries = []
        for path, digest in sorted(_inputs(package['seal']).items()):
            raw = _bytes(run, path, MAX_LOCAL_INPUT_BYTES)
            if _hash(raw) != digest:
                raise ValueError('package payload changed before archival preparation')
            compressed = gzip.compress(raw, mtime=0)
            object_path = OBJECT_ROOT + digest + '.json.gz'
            _write_immutable_source(_safe(run, object_path), compressed)
            entries.append(dict(path=path, sha256=digest, size=len(raw), object_path=object_path,
                gzip_sha256=_hash(compressed), gzip_bytes=len(compressed)))
        if load_execution_package(run)['seal'] != package['seal']:
            raise ValueError('package changed during archival preparation')
        index = dict(schema_version=1, run_id=run.name, seal_sha256=seal_hash, entries=entries)
        index['content_sha256'] = _digest(index)
        _store_immutable(run, ARCHIVE_INDEX, index)
        for row in entries:
            read_archived_input(run, row['path'])
        return index
