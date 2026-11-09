from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time
from threading import Lock
from typing import Any

from wqb.knowledge_paths import (
    ACTIVE_TOP_LEVELS,
    DECISION_ARTIFACTS_ROOT,
    LEGACY_DECISION_ARTIFACTS_ROOT,
    MACHINE_RESOURCE_FILES,
    active_top_level_names,
)


COORDINATION_FILES = {'.data_capture_compile.lock', '.data_capture_compile.lock.guard'}
SENSITIVE_NAME_FRAGMENTS = (
    ".env",
    "credential",
    "secret",
    "token",
    "password",
    "key",
    "private",
)
OBSOLETE_ACTIVE_PREFIXES = (
    Path("raw") / "learn",
    Path("raw") / "research" / "stage1",
    Path("wiki") / "00_principles",
    Path("wiki") / "10_foundations",
    Path("wiki") / "20_semantics",
    Path("wiki") / "30_templates",
    Path("wiki") / "40_experiments",
    Path("wiki") / "50_benchmarks",
    Path("wiki") / "60_workflows",
    Path("wiki") / "70_decisions",
    Path("wiki") / "80_maintenance",
    Path("wiki") / "90_index",
)
WIKI_MACHINE_EXTENSIONS = {".json", ".jsonl", ".csv"}
REFERENCE_FILE_LIMIT = 16 * 1024 * 1024
REFERENCE_TOTAL_LIMIT = 64 * 1024 * 1024
REFERENCE_ENTRY_LIMIT = 10000
REFERENCE_LINE_LIMIT = 16 * 1024 * 1024
REFERENCE_TIME_LIMIT = 30.0
REFERENCE_VALUE_CACHE_LIMIT = 10000
REFERENCE_PROOF_CACHE_CONTEXTS = 4
REFERENCE_HASH_CHUNK_BYTES = 1024 * 1024
_REFERENCE_PROOF_CACHE = OrderedDict()
_REFERENCE_PROOF_CACHE_LOCK = Lock()
RAW_REFERENCE_MANIFESTS = {'manifest.json', 'capture_manifest.json', 'learn_capture_manifest.json'}


@dataclass(frozen=True)
class KnowledgeCleanIssue:
    code: str
    path: str
    message: str
    action: str


@dataclass(frozen=True)
class CleanupCandidate:
    path: str
    reason: str
    action: str
    sha256: str


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for clean compile logs."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str:
    """Input: file path. Output: SHA-256 hex digest. Hash cleanup candidates before removal."""
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_local_path(root: Path, path: Path) -> str:
    """Input: root/path (Path). Output: reason (str); reject escapes, links and special files."""
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(root):
        return 'outside knowledge root'
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return 'unreadable path'
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            return 'link or reparse point'
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            return 'special file'
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            return 'hard-linked file'
    return ''


def _walk_local(root: Path, base: Path, *, deadline: float | None = None, diagnostics=None):
    """Input: Paths, deadline float, optional diagnostic dict. Output: safe bounded Path iterator."""
    if diagnostics is not None:
        diagnostics.update(phase='traversal', current_owner=str(base))
    if deadline is not None and time.monotonic() > deadline:
        raise TimeoutError('evidence reference scan limit')
    if not os.path.lexists(base):
        return
    if _safe_local_path(root, base) or not base.is_dir():
        yield base
        return
    paths = sorted(base.iterdir()) if deadline is None else base.iterdir()
    for path in paths:
        if diagnostics is not None:
            diagnostics.update(phase='traversal', current_owner=str(path))
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError('evidence reference scan limit')
        if not _safe_local_path(root, path) and path.is_dir():
            yield from _walk_local(root, path, deadline=deadline, diagnostics=diagnostics)
        else:
            yield path


def _reference_path_context(root: Path, target: Path, owner: Path) -> tuple:
    """Input: absolute root/target/owner Paths. Output: tuple; precompute lexical reference comparisons per owner."""
    ancestors = (target, *target.parents)
    return (tuple(str(path) for path in (root, root.parent, owner.parent)),
            {os.path.normcase(str(path)) for path in ancestors},
            {os.path.normcase(str(root)), os.path.normcase(str(root.parent))},
            {os.path.normcase(path.name) for path in ancestors} | {'.', '..'}, {})


def _reference_value_refusal(value: object, root: Path, target: Path, owner: Path,
                             digest: str, deadline: float, *, path_context=None) -> str:
    """Input: parsed object, Paths, digest str, deadline float. Output: str; inspect non-routing references."""
    origins, ancestors, routing_roots, simple_names, cache = path_context or _reference_path_context(root, target, owner)
    values = [(value, False)]
    while values:
        if time.monotonic() > deadline:
            return 'evidence reference scan limit'
        value, routing = values.pop()
        if isinstance(value, dict):
            values.extend((key, False) for key in value)
            values.extend((item, key in {'root', 'knowledge_root'}) for key, item in value.items())
        elif isinstance(value, list):
            values.extend((item, False) for item in value)
        elif isinstance(value, str):
            if digest and value == digest:
                return 'referenced evidence digest'
            cache_key = (value, routing)
            if cache_key in cache:
                if cache[cache_key]:
                    return 'referenced evidence path'
                continue
            name = value.replace('\\', '/')
            if not name or '\n' in name or '\x00' in name:
                continue
            if '/' not in name and ':' not in name and os.path.normcase(name) not in simple_names:
                if len(cache) < REFERENCE_VALUE_CACHE_LIMIT:
                    cache[cache_key] = False
                continue
            # Joining an origin cannot change a normalized terminal component
            # except '.'/'..', which remain in simple_names and take the full path.
            terminal = os.path.basename(os.path.normcase(os.path.normpath(name)))
            if terminal not in simple_names:
                if len(cache) < REFERENCE_VALUE_CACHE_LIMIT:
                    cache[cache_key] = False
                continue
            refs = [os.path.normcase(os.path.abspath(os.path.join(origin, name))) for origin in origins]
            # Only known routing fields at the vault/workspace boundary are metadata.
            if routing and any(ref in routing_roots for ref in refs):
                if len(cache) < REFERENCE_VALUE_CACHE_LIMIT:
                    cache[cache_key] = False
                continue
            if any(ref in ancestors for ref in refs):
                return 'referenced evidence path'
            if len(cache) < REFERENCE_VALUE_CACHE_LIMIT:
                cache[cache_key] = False
    return ''


def _reference_refusal(root: Path, target: Path, digest: str, *, ignored_owners=(),
                       snapshots=None, max_file_bytes=None, max_total_bytes=None,
                       historical_reports: bool = False, max_seconds=None, diagnostics=None) -> str:
    """Input: Paths, digest str, exact owner paths, optional dict/byte limits/bool. Output: refusal str.

    Populate snapshots (dict[str, str]) with absolute owner names and SHA-256 of
    fully consumed, validated bytes. Callers must revalidate these before mutation.
    Exclusions are exact files inside the vault or its supported sibling runs.
    Optional diagnostics dict records only progress/limits, never owner payloads.
    """
    from wqb.semantic_publication import _load

    root = Path(os.path.abspath(root))
    target = Path(os.path.abspath(target))
    started = time.monotonic()
    total = entries = 0
    scan_key, verified, pending = None, {}, {}
    state = diagnostics if diagnostics is not None else {}
    state.clear()
    state.update(phase='validate_limits', current_owner='', elapsed=0.0,
                 bytes=0, entries=0, limiting_bound='')

    def finish(reason: str, bound: str = '') -> str:
        """Input: refusal/bound strings. Output: unchanged refusal; finalize compact diagnostic dict."""
        if diagnostics is not None:
            state.update(elapsed=max(0.0, time.monotonic() - started), bytes=total,
                         entries=entries, limiting_bound=bound)
        if scan_key is not None:
            with _REFERENCE_PROOF_CACHE_LOCK:
                _REFERENCE_PROOF_CACHE.pop(scan_key, None)
                if not reason and len(pending) <= REFERENCE_ENTRY_LIMIT:
                    _REFERENCE_PROOF_CACHE[scan_key] = dict(pending)
                    while len(_REFERENCE_PROOF_CACHE) > REFERENCE_PROOF_CACHE_CONTEXTS:
                        _REFERENCE_PROOF_CACHE.popitem(last=False)
        return reason

    file_limit = REFERENCE_FILE_LIMIT if max_file_bytes is None else max_file_bytes
    total_limit = REFERENCE_TOTAL_LIMIT if max_total_bytes is None else max_total_bytes
    if any(type(limit) is not int or limit <= 0 for limit in (file_limit, total_limit)):
        bound = 'file_bytes' if type(file_limit) is not int or file_limit <= 0 else 'total_bytes'
        return finish('evidence reference scan limit', bound)
    seconds = REFERENCE_TIME_LIMIT if max_seconds is None else max_seconds
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        return finish('evidence reference scan limit', 'time_seconds')
    deadline = time.monotonic() + seconds
    roots = [root / 'raw', root / 'machine', root / 'runs']
    if root.name == 'knowledge':
        roots.append(root.parent / 'runs')
    ignored = set()
    state['phase'] = 'validate_exclusions'
    try:
        for item in ignored_owners:
            path = Path(item)
            if any(char in str(path) for char in '*?[]'):
                return finish('unsafe reference owner exclusion')
            path = Path(os.path.abspath(root / path))
            boundary = root
            if root.name == 'knowledge' and path.is_relative_to(root.parent / 'runs'):
                boundary = root.parent
            if (_safe_local_path(boundary, path) or path == root
                    or (path.exists() and not path.is_file())):
                return finish('unsafe reference owner exclusion')
            ignored.add(path)
    except (OSError, TypeError, ValueError):
        return finish('unsafe reference owner exclusion')
    scan_key = (str(root), str(target), digest, historical_reports,
                tuple(sorted(str(path) for path in ignored)), REFERENCE_LINE_LIMIT, REFERENCE_ENTRY_LIMIT)
    with _REFERENCE_PROOF_CACHE_LOCK:
        verified = dict(_REFERENCE_PROOF_CACHE.get(scan_key, {}))
    try:
        for base in roots:
            boundary = root.parent if base == root.parent / 'runs' else root
            state.update(phase='traversal', current_owner=str(base))
            for owner in _walk_local(boundary, base, deadline=deadline, diagnostics=diagnostics):
                state.update(phase='traversal', current_owner=str(owner))
                if time.monotonic() > deadline:
                    return finish('evidence reference scan limit', 'time_seconds')
                if _safe_local_path(boundary, owner):
                    return finish('uncertain evidence references')
                if owner in ignored or not _is_reference_owner(root, owner, historical_reports=historical_reports):
                    continue
                entries += 1
                if entries > REFERENCE_ENTRY_LIMIT:
                    return finish('uncertain evidence references', 'entries')
                if owner.suffix.lower() not in {'.json', '.jsonl'} or not owner.is_file():
                    continue
                if any(owner.is_relative_to(root / 'raw/maintenance' / name)
                       for name in ('cleanup_logs', 'compile_reports', 'migration_reports')):
                    continue
                if snapshots is not None:
                    snapshots.pop(str(owner), None)
                state['phase'] = 'owner_metadata'
                before = owner.stat()
                if before.st_size > file_limit or total + before.st_size > total_limit:
                    bound = 'file_bytes' if before.st_size > file_limit else 'total_bytes'
                    return finish('evidence reference scan limit', bound)
                consumed = 0
                sha = hashlib.sha256()
                refusal = ''
                path_context = _reference_path_context(root, target, owner)
                state['phase'] = 'read_owner'
                with owner.open('rb') as handle:
                    if str(owner) in verified:
                        while data := handle.read(REFERENCE_HASH_CHUNK_BYTES):
                            consumed += len(data)
                            total += len(data)
                            bound = ('file_bytes' if consumed > file_limit else
                                     'total_bytes' if total > total_limit else
                                     'time_seconds' if time.monotonic() > deadline else '')
                            if bound:
                                return finish('evidence reference scan limit', bound)
                            sha.update(data)
                        after = owner.stat()
                        if (consumed != before.st_size or _safe_local_path(boundary, owner)
                                or any(getattr(before, field) != getattr(after, field) for field in
                                       ('st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_ino', 'st_dev'))):
                            return finish('evidence changed during scan')
                        if sha.hexdigest() == verified[str(owner)]:
                            pending[str(owner)] = sha.hexdigest()
                            if snapshots is not None:
                                snapshots[str(owner)] = sha.hexdigest()
                            continue
                        # Changed bytes receive the original full scan. Count
                        # both reads against the same time/total-byte limits.
                        handle.seek(0)
                        consumed, sha = 0, hashlib.sha256()
                    rows = (iter(lambda: handle.readline(REFERENCE_LINE_LIMIT + 1), b'')
                            if owner.suffix.lower() == '.jsonl' else (handle.read(file_limit + 1),))
                    for data in rows:
                        state['phase'] = 'read_owner'
                        consumed += len(data)
                        total += len(data)
                        bound = ('file_bytes' if consumed > file_limit else
                                 'total_bytes' if total > total_limit else
                                 'time_seconds' if time.monotonic() > deadline else
                                 'line_bytes' if owner.suffix.lower() == '.jsonl'
                                 and len(data) > REFERENCE_LINE_LIMIT else '')
                        if bound:
                            return finish('evidence reference scan limit', bound)
                        sha.update(data)
                        if data.strip() or owner.suffix.lower() == '.json':
                            state['phase'] = 'parse_owner'
                            value = _load(data)
                            state['phase'] = 'reference_values'
                            reason = _reference_value_refusal(value, root, target, owner, digest, deadline,
                                                              path_context=path_context)
                            refusal = refusal or reason
                after = owner.stat()
                if (consumed != before.st_size or _safe_local_path(boundary, owner)
                        or any(getattr(before, field) != getattr(after, field)
                               for field in ('st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_ino', 'st_dev'))):
                    return finish('evidence changed during scan')
                if snapshots is not None:
                    snapshots[str(owner)] = sha.hexdigest()
                if refusal:
                    return finish(refusal, 'time_seconds' if refusal == 'evidence reference scan limit' else '')
                pending[str(owner)] = sha.hexdigest()
    except TimeoutError:
        return finish('evidence reference scan limit', 'time_seconds')
    except (OSError, ValueError, RecursionError):
        return finish('uncertain evidence references')
    state['phase'] = 'complete'
    return finish('')


def _is_reference_owner(root: Path, path: Path, *, historical_reports: bool = False) -> bool:
    """Input: root/path (Path). Output: bool; select declared contracts, not capture/inventory payloads."""
    if path.is_relative_to(root / 'runs') or (root.name == 'knowledge' and path.is_relative_to(root.parent / 'runs')):
        return path.suffix.lower() in {'.json', '.jsonl'} or path.suffix == ''
    relative = path.relative_to(root)
    if historical_reports and relative.is_relative_to(Path('machine/reports')):
        return path.suffix.lower() in {'.json', '.jsonl'} or path.suffix == ''
    if (relative.parts[:2] in {('machine', 'semantic_jobs'), ('machine', 'semantic_inventories')}
            and len(relative.parts) == 4 and relative.name == 'inventory.jsonl'
            and len(relative.parts[2]) == 64 and all(c in '0123456789abcdef' for c in relative.parts[2])):
        return False
    if relative.is_relative_to(Path('raw/research')):
        return path.suffix.lower() in {'.json', '.jsonl'} or path.suffix == ''
    if relative.parts[0] == 'raw':
        return path.name in RAW_REFERENCE_MANIFESTS
    if relative.parent == Path('machine'):
        return path.name in {*MACHINE_RESOURCE_FILES.values(), 'semantic_release.json'}
    for prefix in ('machine/semantic_jobs', 'machine/decisions', 'machine/candidate_evidence'):
        if relative.is_relative_to(Path(prefix)):
            return path.suffix.lower() in {'.json', '.jsonl'} or path.suffix == ''
    if relative.is_relative_to(Path('machine/semantic_releases')):
        return path.name in {'manifest.json', *MACHINE_RESOURCE_FILES.values()} or path.suffix == ''
    return False


def _candidate_refusal(root: Path, path: Path, digest: str) -> str:
    """Input: root/path (Path), planned digest (str). Output: concise refusal reason or empty str."""
    reason = _safe_local_path(root, path)
    if reason:
        return reason
    path = Path(os.path.abspath(path))
    relative = path.relative_to(root)
    if not ((len(relative.parts) == 1 and path.name not in COORDINATION_FILES)
            or any(relative.is_relative_to(prefix) for prefix in OBSOLETE_ACTIVE_PREFIXES)):
        return 'outside obsolete allowlist'
    if _is_sensitive(path, root):
        return 'sensitive path'
    if relative.is_relative_to(Path('raw')):
        return 'protected raw evidence'
    try:
        if not path.is_file() or not digest or _sha256(path) != digest:
            return 'candidate changed or missing'
        if relative.is_relative_to(LEGACY_DECISION_ARTIFACTS_ROOT):
            canonical = root / DECISION_ARTIFACTS_ROOT / relative.relative_to(LEGACY_DECISION_ARTIFACTS_ROOT)
            if _safe_local_path(root, canonical) or not canonical.is_file() or _sha256(canonical) != digest:
                return 'canonical migration changed or missing'
        return _reference_refusal(root, path, digest)
    except OSError:
        return 'candidate unreadable'


def _is_sensitive(path: Path, root: Path) -> bool:
    """Input: candidate path and knowledge root. Output: bool. Refuse sensitive relative path components."""
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return True
    return any(fragment in part.lower() for part in parts for fragment in SENSITIVE_NAME_FRAGMENTS)


def evaluate_clean_knowledge_structure(knowledge_root: str | Path) -> dict[str, Any]:
    """Input: knowledge root. Output: dict. Check the simplified active knowledge contract."""
    root = Path(knowledge_root)
    issues: list[KnowledgeCleanIssue] = []
    top_levels = active_top_level_names(root)
    for name in sorted(ACTIVE_TOP_LEVELS - top_levels):
        issues.append(
            KnowledgeCleanIssue(
                "missing_required_layer",
                str(root / name),
                "Required active knowledge layer is missing.",
                "Create the raw, machine, and wiki active knowledge layers before compile.",
            )
        )
    for name in sorted(top_levels - ACTIVE_TOP_LEVELS):
        issues.append(
            KnowledgeCleanIssue(
                "extra_active_layer",
                str(root / name),
                "Top-level active knowledge layer is not allowed.",
                "Move compiled content under raw, machine, or wiki.",
            )
        )
    if root.exists():
        for path in sorted(item for item in root.iterdir() if item.is_file() and item.name not in COORDINATION_FILES):
            issues.append(
                KnowledgeCleanIssue(
                    "root_level_file",
                    str(path),
                    "Files are not allowed at the knowledge root.",
                    "Move the file under raw, machine, or wiki, or remove it through guarded cleanup.",
                )
            )
    for prefix in OBSOLETE_ACTIVE_PREFIXES:
        path = root / prefix
        if path.exists():
            issues.append(
                KnowledgeCleanIssue(
                    "legacy_active_path",
                    str(path),
                    "Legacy mixed active path remains after compile.",
                    "Run clean compile cleanup after successful compile verification.",
                )
            )
    wiki_root = root / "wiki"
    from wqb.semantic_publication import read_semantic_release, _safe_path

    try:
        receipt = read_semantic_release(root)
        if receipt['release_id'] is not None:
            for target, entry in receipt['manifest']['wiki'].items():
                path = _safe_path(root, target)
                if not path.is_file() or _sha256(path) != entry['sha256']:
                    issues.append(KnowledgeCleanIssue(
                        "semantic_wiki_version_mismatch", str(path),
                        "Human wiki does not match the active semantic release; page updates are file-atomic, not simultaneous.",
                        "Retry publication of the active receipt to restore its version-labelled wiki materials.",
                    ))
    except ValueError as error:
        issues.append(KnowledgeCleanIssue(
            "semantic_release_invalid", str(root / "machine" / "semantic_release.json"),
            str(error), "Repair the release pointer or immutable generation; do not silently use legacy resources.",
        ))
    if wiki_root.exists():
        for path in sorted(wiki_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in WIKI_MACHINE_EXTENSIONS:
                issues.append(
                    KnowledgeCleanIssue(
                        "machine_resource_inside_wiki",
                        str(path),
                        "Machine-readable artifact is inside the human wiki.",
                        "Move machine artifacts under knowledge/machine.",
                    )
                )
    return {
        "clean": not issues,
        "issue_count": len(issues),
        "top_levels": sorted(top_levels),
        "issues": [asdict(issue) for issue in issues],
    }


def plan_obsolete_active_cleanup(knowledge_root: str | Path) -> list[CleanupCandidate]:
    """Input: knowledge root. Output: cleanup candidates. Plan ordinary removals and sensitive refusals."""
    root = Path(knowledge_root)
    rows: list[CleanupCandidate] = []
    def candidate(path: Path, reason: str) -> CleanupCandidate:
        """Input: path (Path), reason (str). Output: guarded CleanupCandidate without following links."""
        refusal = _safe_local_path(root, path)
        digest = ''
        if not refusal:
            try:
                digest = _sha256(path)
            except OSError:
                refusal = 'candidate unreadable'
        if not refusal:
            refusal = _candidate_refusal(Path(os.path.abspath(root)), path, digest)
        return CleanupCandidate(str(path), refusal or reason, 'refuse' if refusal else 'remove', digest)

    if root.exists():
        for path in sorted(root.iterdir()):
            if path.name not in COORDINATION_FILES and (_safe_local_path(root, path) or path.is_file()):
                rows.append(candidate(path, 'file at knowledge root'))
    for prefix in OBSOLETE_ACTIVE_PREFIXES:
        base = root / prefix
        for path in _walk_local(root, base):
            rows.append(candidate(path, f'obsolete active prefix {prefix.as_posix()}'))
    return rows


def migrate_legacy_decision_artifacts(knowledge_root: str | Path) -> dict[str, Any]:
    """Input: knowledge root. Output: migration evidence. Copy legacy decisions without overwriting conflicts."""
    root = Path(knowledge_root)
    legacy = root / LEGACY_DECISION_ARTIFACTS_ROOT
    canonical = root / DECISION_ARTIFACTS_ROOT
    artifacts: list[dict[str, Any]] = []
    if legacy.exists():
        for source in sorted(path for path in legacy.rglob("*") if path.is_file()):
            relative = source.relative_to(legacy)
            target = canonical / relative
            source_hash = _sha256(source)
            target_hash = _sha256(target) if target.is_file() else ""
            if _is_sensitive(source, root):
                status = "refused_sensitive"
            elif target.is_file() and target_hash != source_hash:
                status = "conflict"
            elif target.is_file():
                status = "verified_existing"
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
                target_hash = _sha256(target)
                status = "migrated"
            artifacts.append(
                {
                    "source_path": str(source),
                    "target_path": str(target),
                    "source_sha256": source_hash,
                    "target_sha256": target_hash,
                    "status": status,
                }
            )
    return {
        "status": "completed"
        if all(row["status"] != "conflict" for row in artifacts)
        else "blocked",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def write_cleanup_log(knowledge_root: str | Path, rows: list[dict[str, Any]], generated_at: str) -> Path:
    """Input: knowledge root, cleanup rows, timestamp. Output: log path. Persist cleanup evidence."""
    root = Path(os.path.abspath(knowledge_root))
    path = _cleanup_log_path(root, generated_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


def _cleanup_log_path(root: Path, generated_at: str) -> Path:
    """Input: root (Path), timestamp (str). Output: Path; reject unsafe audit destinations before deletion."""
    day = generated_at[:10]
    try:
        datetime.strptime(day, '%Y-%m-%d')
    except ValueError as error:
        raise ValueError('unsafe cleanup log date') from error
    path = root / 'raw/maintenance/cleanup_logs' / f'{day}.jsonl'
    if _safe_local_path(root, path):
        raise ValueError('unsafe cleanup log path')
    return path


def _remove_empty_obsolete_directories(root: Path) -> None:
    """Input: knowledge root. Output: none. Remove empty directories under obsolete active prefixes."""
    for prefix in OBSOLETE_ACTIVE_PREFIXES:
        base = root / prefix
        if _safe_local_path(root, base) or not base.is_dir():
            continue
        for directory in sorted((path for path in base.rglob("*") if path.is_dir()), reverse=True):
            if not _safe_local_path(root, directory) and not any(directory.iterdir()):
                directory.rmdir()
        if not _safe_local_path(root, base) and not any(base.iterdir()):
            base.rmdir()


def _compile_verification_evidence(
    root: Path,
    verification_report_path: str | Path | None,
    dry_run: bool,
) -> dict[str, Any]:
    """Input: root, report path, dry-run flag. Output: evidence dict. Validate compile report before deletion."""
    if dry_run:
        return {"verification_report_path": None, "verification_status": "not_required", "verified": True}
    if verification_report_path is None:
        return {"verification_report_path": None, "verification_status": "missing", "verified": False}

    report_path = Path(os.path.abspath(verification_report_path))
    if _safe_local_path(root, report_path):
        return {'verification_report_path': str(report_path), 'verification_status': 'unsafe', 'verified': False}
    report_root = (root / "raw" / "maintenance" / "compile_reports").resolve()
    try:
        report_path.relative_to(report_root)
    except ValueError:
        return {
            "verification_report_path": str(report_path),
            "verification_status": "outside_maintenance_directory",
            "verified": False,
        }
    if not report_path.is_file():
        return {"verification_report_path": str(report_path), "verification_status": "missing", "verified": False}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"verification_report_path": str(report_path), "verification_status": "invalid", "verified": False}
    if not isinstance(report, dict):
        return {"verification_report_path": str(report_path), "verification_status": "invalid", "verified": False}

    status = report.get("status")
    compile_summary = report.get("compile")
    pre_cleanup_health = report.get("pre_cleanup_health")
    verified = (
        report.get("report_type") == "knowledge_maintenance_pre_cleanup_evidence"
        and status == "completed"
        and isinstance(compile_summary, dict)
        and compile_summary.get("status") == "completed"
        and isinstance(pre_cleanup_health, dict)
        and pre_cleanup_health.get("blocking_issue_count") == 0
    )
    if verified:
        verification_status = "completed"
    elif isinstance(status, str) and status not in {"completed", "passed"}:
        verification_status = status
    else:
        verification_status = "invalid"
    return {
        "verification_report_path": str(report_path),
        "verification_status": verification_status,
        "verified": verified,
    }


def apply_obsolete_active_cleanup(
    knowledge_root: str | Path,
    generated_at: str | None = None,
    dry_run: bool = True,
    verification_report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Input: root/path, timestamp str, dry-run bool, report/path. Output: dict; serialize cleanup with publication."""
    from wqb.semantic_publication import _acquire_lock, _release_lock

    root = Path(os.path.abspath(knowledge_root))
    if _safe_local_path(root, root):
        raise ValueError('unsafe knowledge root')
    generated = generated_at or _now()
    _cleanup_log_path(root, generated)
    handle = _acquire_lock(root)
    try:
        return _apply_obsolete_active_cleanup_locked(root, generated, dry_run, verification_report_path)
    finally:
        _release_lock(handle)


def _apply_obsolete_active_cleanup_locked(
    knowledge_root: Path,
    generated_at: str,
    dry_run: bool,
    verification_report_path: str | Path | None,
) -> dict[str, Any]:
    """Input: root, timestamp, dry run, compile report path. Output: cleanup summary with audit log."""
    generated = generated_at or _now()
    root = Path(os.path.abspath(knowledge_root))
    if _safe_local_path(root, root):
        raise ValueError('unsafe knowledge root')
    _cleanup_log_path(root, generated)
    candidates = plan_obsolete_active_cleanup(root)
    evidence = _compile_verification_evidence(root, verification_report_path, dry_run)
    blocked = not evidence["verified"]
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        path = Path(candidate.path)
        row = asdict(candidate) | {
            "generated_at": generated,
            "dry_run": dry_run,
            "blocked": blocked,
            "verification_report_path": evidence["verification_report_path"],
            "verification_status": evidence["verification_status"],
        }
        if candidate.action == "remove" and not dry_run and not blocked:
            refusal = _candidate_refusal(root, path, candidate.sha256)
            if not refusal:
                write_cleanup_log(root, [row | {'event': 'cleanup_intent', 'applied': False}], generated)
                try:
                    # Recheck after the reference scan, immediately before unlink.
                    refusal = _safe_local_path(root, path)
                    if not refusal and _sha256(path) != candidate.sha256:
                        refusal = 'candidate changed'
                    if not refusal:
                        path.unlink()
                except OSError:
                    refusal = 'candidate removal failed'
            row['applied'] = not refusal
            if refusal:
                row.update(action='refuse', reason=refusal)
        else:
            row["applied"] = False
        rows.append(row)
    if not dry_run and not blocked:
        _remove_empty_obsolete_directories(root)
    summary_row = {
        "event": "cleanup_run",
        "generated_at": generated,
        "dry_run": dry_run,
        "blocked": blocked,
        "verification_report_path": evidence["verification_report_path"],
        "verification_status": evidence["verification_status"],
        "candidate_count": len(rows),
        "removed_count": sum(1 for row in rows if row.get("applied")),
        "refused_count": sum(1 for row in rows if row["action"] == "refuse"),
    }
    log_path = write_cleanup_log(root, [*rows, summary_row], generated)
    return {
        "generated_at": generated,
        "dry_run": dry_run,
        "blocked": blocked,
        "verification_report_path": evidence["verification_report_path"],
        "verification_status": evidence["verification_status"],
        "removed_count": summary_row["removed_count"],
        "refused_count": summary_row["refused_count"],
        "candidate_count": summary_row["candidate_count"],
        "refusals": [{'path': row['path'], 'reason': row['reason']}
                     for row in rows if row['action'] == 'refuse'],
        "cleanup_log_path": str(log_path),
    }
