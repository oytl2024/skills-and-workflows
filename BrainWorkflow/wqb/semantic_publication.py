"""Immutable semantic generations selected by one atomic machine pointer.

Rows are already validated by the semantic compiler; this layer checks storage
structure and provenance, not operator meaning. Wiki replacement is file-atomic,
not a multi-page transaction. Each rendered page visibly names its generation;
retrying publication repairs an interrupted wiki update without rewriting raw.
Legacy receipts bind both mutable paths and their observed bytes (None means
absent). They are invalidated by replacement or publication, not filesystem
snapshots: callers must verify the bytes they consumed and revalidate the same
receipt after paired reads before using the result.
"""

import hashlib
from datetime import datetime
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
import uuid
from typing import BinaryIO

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

from wqb.knowledge_paths import MACHINE_RESOURCE_FILES, LEGACY_MACHINE_RESOURCE_PATHS
from wqb.resource_evidence import resource_contract_version


SCHEMA_VERSION = 1
LOCK_TIMEOUT_SECONDS = 2.0
LOCK_POLL_SECONDS = 0.02
ATOMIC_REPLACE_MAX_ATTEMPTS = 10
ATOMIC_REPLACE_RETRY_SECONDS = 0.02
RESOURCE_NAMES = ('operator_ledger', 'template_library')
WIKI_TARGETS = {'wiki/20_data_semantics.md', 'wiki/30_template_and_operator_patterns.md'}
SENSITIVE_FRAGMENTS = ('.env', 'credential', 'secret', 'token', 'password', 'private', 'key', '.ssh', '.aws', '.git', 'auth', 'session', 'cookie', 'config')
DIGEST_PATTERN = re.compile(r'[0-9a-f]{64}\Z')


def _json_bytes(value: object) -> bytes:
    """Input: JSON-compatible object. Output: bytes. Encode deterministic strict JSON."""
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')


def _unique_object(pairs: list) -> dict:
    """Input: JSON key/value pairs list. Output: dict. Reject ambiguous duplicate keys."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    """Input: nonfinite JSON constant str. Output: none. Reject non-standard JSON."""
    raise ValueError(f'invalid JSON constant: {value}')


def _load(data: bytes) -> object:
    """Input: UTF-8 JSON bytes. Output: parsed object. Normalize corrupt input errors."""
    try:
        return json.loads(data, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('invalid semantic JSON') from error


def _digest(data: bytes) -> str:
    """Input: bytes. Output: SHA-256 str. Hash exact stored bytes."""
    return hashlib.sha256(data).hexdigest()


def _require_digest(value: object) -> str:
    """Input: object. Output: hex str. Require a canonical SHA-256 or release ID."""
    if not isinstance(value, str) or not DIGEST_PATTERN.fullmatch(value):
        raise ValueError('invalid semantic digest or release ID')
    return value


def _require_timestamp(value: object) -> str:
    """Input: object. Output: ISO timestamp str. Reject unusable generation dates."""
    if not isinstance(value, str) or not re.match(r'^\d{4}-\d{2}-\d{2}(?:$|T)', value):
        raise ValueError('invalid generation timestamp')
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('invalid generation timestamp') from error
    return value


def _safe_path(root: Path, relative: str) -> Path:
    """Input: root Path, POSIX relative str. Output: Path. Refuse escape, links and sensitive names."""
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('invalid relative semantic path')
    parts = relative.split('/')
    if any(part in ('', '.', '..') or part.endswith(('.', ' ')) or any(ord(char) < 32 for char in part) for part in parts) or PurePosixPath(relative).is_absolute():
        raise ValueError('semantic path traversal')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
    if any(part.split('.')[0].upper() in reserved for part in parts):
        raise ValueError('reserved semantic path')
    if any(fragment in part.lower() for part in parts for fragment in SENSITIVE_FRAGMENTS):
        raise ValueError('sensitive semantic path')
    base = Path(os.path.abspath(root))
    # Check ancestors before resolve: resolving first would conceal a link.
    for candidate in (*reversed(base.parents), base):
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError('linked semantic root')
    candidate = base
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError('linked semantic path')
    if not candidate.resolve().is_relative_to(base):
        raise ValueError('semantic path outside root')
    return candidate


def _read(path: Path) -> bytes:
    """Input: file Path. Output: bytes. Fail closed on missing or unreadable release files."""
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValueError(f'unreadable semantic file: {path.name}') from error


def _verify_sources(root: Path, refs: object) -> None:
    """Input: root Path/source-ref list. Output: None. Verify consumed bytes and original extract receipts readonly."""
    if not isinstance(refs, list):
        raise ValueError('source_refs must be a list')
    from wqb.knowledge_contracts import parse_markdown_front_matter, verify_field_source_extract, verify_source_repair
    indexed_extracts = set()
    index_path = _safe_path(root, 'machine/source_index.jsonl')
    if index_path.exists() and any(isinstance(ref, dict) and isinstance(ref.get('path'), str)
                                   and ref['path'].lower().endswith('.md') for ref in refs):
        with index_path.open('rb') as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = _load(line)
                if not isinstance(row, dict):
                    raise ValueError('source index requires object rows')
                if row.get('content_status') == 'verified_raw_extract':
                    if not isinstance(row.get('path'), str):
                        raise ValueError('indexed field extract requires canonical path')
                    indexed_extracts.add(row['path'])
    seen = set()
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
            raise ValueError('source ref requires path and sha256')
        path = _safe_path(root, ref['path'])
        if ref['path'].split('/')[0] not in ('raw', 'machine') or ref['path'] in seen:
            raise ValueError('invalid or duplicate source authority')
        seen.add(ref['path'])
        raw = _read(path)
        digest = _digest(raw)
        if digest != _require_digest(ref['sha256']):
            raise ValueError('semantic source digest changed')
        metadata = {}
        if path.suffix.lower() == '.md':
            metadata, _ = parse_markdown_front_matter(raw.decode('utf-8').replace('\r\n', '\n'))
            repair = verify_source_repair(root, ref['path'])
            if repair.get('status') not in ('verified', 'not_repaired') or repair.get('source_sha256') != digest:
                raise ValueError('source repair receipt does not match publication source bytes')
        if (ref['path'] in indexed_extracts or metadata.get('content_status') == 'verified_raw_extract'
                or (ref['path'].startswith('raw/platform/data_fields/')
                    and path.name.startswith('semantic-subset-'))):
            receipt = verify_field_source_extract(root, ref['path'])
            if receipt.get('status') != 'verified' or receipt.get('excerpt_sha256') != digest:
                raise ValueError('field extract receipt does not match publication source bytes')


def _acquire_lock(root: Path) -> BinaryIO:
    """Input: root Path. Output: owned binary lock handle. Bound waiting; OS releases locks on crash."""
    lock = _safe_path(root, 'machine/.semantic_publish.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    handle = lock.open('a+b')
    while True:
        try:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                raise TimeoutError('semantic writer lock busy')
            time.sleep(LOCK_POLL_SECONDS)


def _release_lock(handle: BinaryIO) -> None:
    """Input: owned binary lock handle. Output: none. Release without unlinking the shared lock inode."""
    try:
        handle.seek(0)
        if os.name == 'nt':
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _write_new(path: Path, data: bytes) -> None:
    """Input: new file Path, bytes. Output: none. Exclusively create and flush one staged file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_write(root: Path, relative: str, data: bytes) -> None:
    """Input: root Path, relative str, bytes. Output: none. Replace one file atomically."""
    target = _safe_path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = _safe_path(root, relative + '.tmp-' + uuid.uuid4().hex)
    _write_new(temporary, data)
    for attempt in range(ATOMIC_REPLACE_MAX_ATTEMPTS):
        try:
            os.replace(temporary, target)
            return
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in {5, 32, 33} or attempt + 1 == ATOMIC_REPLACE_MAX_ATTEMPTS:
                raise
            time.sleep(ATOMIC_REPLACE_RETRY_SECONDS)


def _receipt(root: Path, release_id: str, manifest_sha256: str) -> dict:
    """Input: root Path, ID/digest strs. Output: dict receipt. Verify one immutable generation."""
    release_id = _require_digest(release_id)
    prefix = f'machine/semantic_releases/{release_id}/'
    manifest_path = _safe_path(root, prefix + 'manifest.json')
    data = _read(manifest_path)
    if _digest(data) != _require_digest(manifest_sha256):
        raise ValueError('semantic manifest digest mismatch')
    manifest = _load(data)
    if not isinstance(manifest, dict) or set(manifest) - {'resource_contract_version'} != {'schema_version', 'release_id', 'generated_at', 'source_refs', 'resources', 'wiki'}:
        raise ValueError('invalid semantic manifest structure')
    resource_contract_version(manifest)
    if type(manifest['schema_version']) is not int or manifest['schema_version'] != SCHEMA_VERSION or manifest['release_id'] != release_id:
        raise ValueError('invalid semantic manifest identity')
    _require_timestamp(manifest['generated_at'])
    if not isinstance(manifest['source_refs'], list):
        raise ValueError('invalid source refs')
    # Validate source shapes/paths without requiring old source bytes to stay unchanged.
    for ref in manifest['source_refs']:
        if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
            raise ValueError('invalid manifest source ref')
        _safe_path(root, ref['path'])
        _require_digest(ref['sha256'])
        if ref['path'].split('/')[0] not in ('raw', 'machine'):
            raise ValueError('invalid source authority')
    if not isinstance(manifest['resources'], dict) or set(manifest['resources']) != set(RESOURCE_NAMES):
        raise ValueError('missing semantic resource pair')
    if not isinstance(manifest['wiki'], dict) or not set(manifest['wiki']).issubset(WIKI_TARGETS):
        raise ValueError('invalid wiki targets')
    generation = manifest_path.parent
    expected_files = {'manifest.json', *(MACHINE_RESOURCE_FILES[name] for name in RESOURCE_NAMES), *manifest['wiki']}
    actual_files = set()
    for item in generation.rglob('*'):
        relative = item.relative_to(generation).as_posix()
        _safe_path(root, prefix + relative)
        if item.is_file():
            actual_files.add(relative)
    if actual_files != expected_files:
        raise ValueError('unlisted or missing semantic release files')
    paths, digests = {}, {}
    for name, entry in {**manifest['resources'], **manifest['wiki']}.items():
        expected = MACHINE_RESOURCE_FILES[name] if name in RESOURCE_NAMES else name
        if not isinstance(entry, dict) or set(entry) != {'path', 'sha256'} or entry['path'] != expected:
            raise ValueError('invalid release resource path')
        path = _safe_path(root, prefix + entry['path'])
        content = _read(path)
        if _digest(content) != _require_digest(entry['sha256']):
            raise ValueError('semantic resource digest mismatch')
        if name in RESOURCE_NAMES:
            for line in content.splitlines():
                if not line.strip() or not isinstance(_load(line), dict):
                    raise ValueError('semantic resource requires JSONL objects')
            paths[name], digests[name] = str(path), entry['sha256']
        elif f'Semantic release: `{release_id}`' not in content.decode('utf-8'):
            raise ValueError('wiki release label missing')
    return {**({'resource_contract_version': manifest['resource_contract_version']} if 'resource_contract_version' in manifest else {}),
            'schema_version': SCHEMA_VERSION, 'release_id': release_id, 'manifest_path': str(manifest_path),
            'manifest_sha256': manifest_sha256, 'generated_at': manifest['generated_at'],
            'paths': paths, 'digests': digests, 'manifest': manifest}


def validate_semantic_receipt(root: Path, receipt: dict) -> dict:
    """Input: root Path, receipt dict. Output: verified dict. Preserve generations; invalidate changed legacy pairs."""
    if not isinstance(receipt, dict) or 'release_id' not in receipt:
        raise ValueError('invalid semantic receipt')
    if receipt['release_id'] is not None:
        checked = _receipt(Path(root), receipt['release_id'], receipt.get('manifest_sha256'))
        if resource_contract_version(receipt) != resource_contract_version(checked):
            raise ValueError('semantic receipt resource contract version mismatch')
        return checked
    if set(receipt) != {'schema_version', 'release_id', 'paths', 'digests'} or type(receipt['schema_version']) is not int or receipt['schema_version'] != SCHEMA_VERSION:
        raise ValueError('invalid legacy receipt structure')
    pointer = _safe_path(Path(root), 'machine/semantic_release.json')
    if pointer.exists():
        raise ValueError('legacy receipt cannot bypass an existing semantic pointer')
    paths = receipt.get('paths')
    if not isinstance(paths, dict) or set(paths) != set(RESOURCE_NAMES):
        raise ValueError('invalid legacy receipt paths')
    base = Path(os.path.abspath(root))
    for name, value in paths.items():
        if not isinstance(value, str):
            raise ValueError('invalid legacy receipt path')
        candidate = Path(os.path.abspath(value))
        try:
            relative = candidate.relative_to(base).as_posix()
        except ValueError as error:
            raise ValueError('legacy receipt outside root') from error
        allowed = {'machine/' + MACHINE_RESOURCE_FILES[name], *(path.as_posix() for path in LEGACY_MACHINE_RESOURCE_PATHS.get(name, ()))}
        if relative not in allowed:
            raise ValueError('legacy receipt outside allowed resource paths')
        _safe_path(base, relative)
    digests = receipt.get('digests')
    if not isinstance(digests, dict) or set(digests) != set(RESOURCE_NAMES):
        raise ValueError('invalid legacy receipt digests')
    for digest in digests.values():
        if digest is not None:
            _require_digest(digest)
    current = read_semantic_release(base)
    if current['release_id'] is not None or current['paths'] != paths or current['digests'] != digests:
        raise ValueError('legacy semantic receipt invalidated by resource or authority change')
    return current


def stage_semantic_release(root: Path, proposals: dict, generated_at: str) -> dict:
    """Input: root Path, validated proposal dict, timestamp str. Output: inactive immutable receipt dict."""
    root = Path(root)
    if not isinstance(proposals, dict) or not isinstance(generated_at, str) or not generated_at.strip():
        raise ValueError('invalid semantic proposals or timestamp')
    version = resource_contract_version(proposals)
    if 'evidence_pack' in proposals and resource_contract_version(proposals['evidence_pack']) != version:
        raise ValueError('proposal and evidence pack resource versions disagree')
    _require_timestamp(generated_at)
    for key in ('validated_operators', 'validated_templates'):
        if not isinstance(proposals.get(key), list) or any(not isinstance(row, dict) for row in proposals[key]):
            raise ValueError(f'{key} requires a list of validated objects')
    refs = proposals.get('source_refs')
    _verify_sources(root, refs)
    wiki = proposals.get('wiki_materials', {})
    if not isinstance(wiki, dict) or not set(wiki).issubset(WIKI_TARGETS) or any(not isinstance(text, str) for text in wiki.values()):
        raise ValueError('wiki_materials requires allowed wiki path to Markdown string')
    identity = {'generated_at': generated_at, 'source_refs': refs, 'wiki_materials': wiki,
                'validated_operators': proposals['validated_operators'], 'validated_templates': proposals['validated_templates'], 'schema_version': SCHEMA_VERSION}
    version_metadata = {'resource_contract_version': version} if 'resource_contract_version' in proposals else {}
    identity.update(version_metadata)
    release_id = _digest(_json_bytes(identity))
    manifest = {'schema_version': SCHEMA_VERSION, 'release_id': release_id, 'generated_at': generated_at,
                'source_refs': refs, 'resources': {}, 'wiki': {}, **version_metadata}
    files = {}
    for name, key in zip(RESOURCE_NAMES, ('validated_operators', 'validated_templates')):
        relative = MACHINE_RESOURCE_FILES[name]
        files[relative] = b''.join(_json_bytes(row) for row in proposals[key])
        manifest['resources'][name] = {'path': relative, 'sha256': _digest(files[relative])}
    for relative, text in wiki.items():
        files[relative] = (text.rstrip() + f'\n\nSemantic release: `{release_id}`\n').encode('utf-8')
        manifest['wiki'][relative] = {'path': relative, 'sha256': _digest(files[relative])}
    files['manifest.json'] = _json_bytes(manifest)
    manifest_digest = _digest(files['manifest.json'])
    lock = _acquire_lock(root)
    try:
        generation = _safe_path(root, f'machine/semantic_releases/{release_id}')
        if not generation.exists():
            temporary = _safe_path(root, f'machine/semantic_releases/.staging-{uuid.uuid4().hex}')
            for relative, data in files.items():
                _write_new(temporary / relative, data)
            os.rename(temporary, generation)
        return _receipt(root, release_id, manifest_digest)
    finally:
        _release_lock(lock)


def publish_semantic_release(root: Path, release: dict) -> dict:
    """Input: root Path, staged receipt dict. Output: verified active receipt dict. Atomically publish pair."""
    root = Path(root)
    if not isinstance(release, dict):
        raise ValueError('invalid release receipt')
    lock = _acquire_lock(root)
    try:
        receipt = _receipt(root, release.get('release_id'), release.get('manifest_sha256'))
        # A corrupt active pointer is an error, never a request to overwrite evidence.
        read_semantic_release(root)
        from wqb.knowledge_clean_compile import evaluate_clean_knowledge_structure

        clean = evaluate_clean_knowledge_structure(root)
        blocking = [row for row in clean['issues'] if row['code'] != 'semantic_wiki_version_mismatch']
        if blocking:
            raise ValueError('unclean knowledge structure blocks semantic publication')
        for target in receipt['manifest']['wiki']:
            path = _safe_path(root, target)
            if path.exists() and not path.is_file():
                raise ValueError('wiki target must be an ordinary file')
        _verify_sources(root, receipt['manifest']['source_refs'])
        pointer = {'schema_version': SCHEMA_VERSION, 'release_id': receipt['release_id'], 'manifest_sha256': receipt['manifest_sha256']}
        _atomic_write(root, 'machine/semantic_release.json', _json_bytes(pointer))
        for target, entry in receipt['manifest']['wiki'].items():
            source = _safe_path(root, f"machine/semantic_releases/{receipt['release_id']}/{entry['path']}")
            _atomic_write(root, target, _read(source))
        return receipt
    finally:
        _release_lock(lock)


def read_semantic_release(root: Path) -> dict:
    """Input: root Path. Output: fixed receipt dict. Select once; only absent pointers allow legacy reads."""
    root = Path(root)
    pointer = _safe_path(root, 'machine/semantic_release.json')
    if not pointer.exists():
        paths, digests = {}, {}
        for name in RESOURCE_NAMES:
            canonical = _safe_path(root, 'machine/' + MACHINE_RESOURCE_FILES[name])
            selected = canonical
            if not canonical.exists():
                for relative in LEGACY_MACHINE_RESOURCE_PATHS.get(name, ()):
                    candidate = _safe_path(root, relative.as_posix())
                    if candidate.exists():
                        selected = candidate
                        break
            paths[name] = str(selected)
            digests[name] = _digest(_read(selected)) if selected.exists() else None
        if _safe_path(root, 'machine/semantic_release.json').exists():
            raise ValueError('legacy semantic receipt invalidated during acquisition')
        return {'schema_version': SCHEMA_VERSION, 'release_id': None, 'paths': paths, 'digests': digests}
    payload = _load(_read(pointer))
    if not isinstance(payload, dict) or set(payload) != {'schema_version', 'release_id', 'manifest_sha256'}:
        raise ValueError('invalid semantic pointer structure')
    if type(payload['schema_version']) is not int or payload['schema_version'] != SCHEMA_VERSION:
        raise ValueError('invalid semantic pointer version')
    return _receipt(root, payload['release_id'], payload['manifest_sha256'])
