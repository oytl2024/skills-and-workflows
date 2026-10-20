from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from wqb.knowledge_paths import MACHINE_RESOURCE_FILES, machine_resource_path
from wqb.lockfile import json_lock_transition_guard


SOURCE_INDEX_LOCK_SECONDS = 5.0
SOURCE_INDEX_LOCK_SLEEP_SECONDS = 0.05
MAX_FIELD_EXTRACT_ROWS = 30
MAX_FIELD_CAPTURE_LINE_BYTES = 1_000_000
MAX_FIELD_EXTRACT_BYTES = 512_000
MAX_CAPTURE_MANIFEST_BYTES = 2_000_000
MAX_SOURCE_REPAIR_BYTES = 2_000_000

RAW_CANONICAL_PREFIXES = (
    "raw/platform/learn",
    "raw/platform/data_fields",
    "raw/platform/activities",
    "raw/platform/account_rules",
    "raw/community/forum",
    "raw/community/advisor_notes",
    "raw/community/user_messages",
    "raw/research/daily",
    "raw/research/batches",
    "raw/research/near_misses",
    "raw/research/repairs",
    "raw/research/submissions",
    "raw/research/runs",
)

WIKI_CANONICAL_PREFIXES = (
    "wiki/00_start_here.md",
    "wiki/10_factor_principles.md",
    "wiki/20_data_semantics.md",
    "wiki/30_template_and_operator_patterns.md",
    "wiki/40_benchmark_and_repair_rules.md",
    "wiki/50_engineering_lessons.md",
    "wiki/60_research_cases",
)

RAW_REQUIRED_FIELDS = (
    "source_type",
    "source_family",
    "source_path",
    "captured_at",
    "capture_tool",
    "content_status",
    "record_count",
    "content_hash",
    "update_check",
    "compiled_targets",
)

WIKI_REQUIRED_FIELDS = (
    "compiled_from",
    "compiled_at",
    "trust_level",
    "stale_after_days",
    "update_trigger",
    "consumed_by",
)


@dataclass(frozen=True)
class RawSourceMetadata:
    source_type: str
    source_family: str
    source_path: str
    captured_at: str
    capture_tool: str
    record_count: int
    content_hash: str
    update_check: str
    compiled_targets: list[str]
    scope: str = ""
    content_status: str = "raw_markdown"


@dataclass(frozen=True)
class WikiPageMetadata:
    compiled_from: list[str]
    compiled_at: str
    trust_level: str
    stale_after_days: int
    update_trigger: str
    consumed_by: list[str]


@dataclass(frozen=True)
class SourceIndexRow:
    path: str
    source_family: str
    source_type: str
    contents: str
    update_check: str
    compiled_targets: list[str] = field(default_factory=list)
    captured_at: str = ""
    record_count: int = 0
    content_hash: str = ""
    content_status: str = ""


def _coerce_scalar(value: str) -> Any:
    """Input: front matter value. Output: Python scalar. Convert simple YAML-style scalars."""
    stripped = value.strip()
    if stripped.isdigit():
        return int(stripped)
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    return stripped.strip('"').strip("'")


def parse_markdown_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Input: Markdown text. Output: metadata and body. Parse a small YAML-style front matter block."""
    if not text.startswith("---\n"):
        return {}, text
    lines = text.splitlines(keepends=True)
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}, text
    metadata: dict[str, Any] = {}
    current_key = ""
    for line in lines[1:end_index]:
        if line.startswith("  - ") and current_key:
            metadata.setdefault(current_key, []).append(_coerce_scalar(line[4:]))
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            if value.strip():
                metadata[current_key] = _coerce_scalar(value)
            else:
                metadata[current_key] = []
    return metadata, "".join(lines[end_index + 1 :])


def render_front_matter(metadata: dict[str, Any]) -> str:
    """Input: metadata dict. Output: Markdown front matter. Render deterministic YAML-style metadata."""
    lines = ["---"]
    for key in sorted(metadata):
        value = metadata[key]
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _relative_posix(path: Path, root: Path) -> str:
    """Input: path and root. Output: posix string. Convert a vault path to relative form."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def canonical_source_family(path: str | Path, knowledge_root: str | Path) -> str:
    """Input: path and vault root. Output: source family label. Classify canonical and legacy vault paths."""
    root = Path(knowledge_root)
    relative = _relative_posix(Path(path), root)
    for prefix in RAW_CANONICAL_PREFIXES:
        if relative == prefix or relative.startswith(prefix + "/"):
            return prefix
    for prefix in WIKI_CANONICAL_PREFIXES:
        if relative == prefix or relative.startswith(prefix + "/"):
            return prefix
    if relative in {f"machine/{filename}" for filename in MACHINE_RESOURCE_FILES.values()}:
        return relative
    if relative.startswith("raw/") or relative.startswith("wiki/"):
        return "legacy"
    return "external"


def _missing_fields(metadata: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    """Input: metadata and required fields. Output: issue strings. Find missing metadata keys."""
    issues: list[str] = []
    for field_name in required:
        value = metadata.get(field_name)
        if value in (None, "", []):
            issues.append(f"missing {field_name}")
    return issues


def validate_raw_metadata(path: Path) -> list[str]:
    """Input: raw Markdown path. Output: issue strings. Validate raw source metadata."""
    metadata, _ = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
    issues = _missing_fields(metadata, RAW_REQUIRED_FIELDS)
    content_status = metadata.get("content_status")
    if (content_status == 'verified_raw_extract' or path.name.startswith('semantic-subset-')
            or any(key in metadata for key in ('extraction_receipt', 'original_source_path', 'original_sha256'))
            or metadata.get('capture_tool') == 'knowledge_contracts.extract_field_source_subset'):
        try:
            absolute = path.absolute()
            if len(absolute.parents) < 5:
                raise ValueError('canonical field excerpt path required')
            root = absolute.parents[4]
            verify_field_source_extract(root, absolute.relative_to(root).as_posix())
        except (ValueError, OSError, UnicodeDecodeError) as error:
            issues.append('verified_raw_extract verification failed: ' + str(error))
    elif content_status not in (None, "", []) and str(content_status) != "raw_markdown":
        issues.append("content_status must be raw_markdown")
    targets = metadata.get("compiled_targets", [])
    if targets and not isinstance(targets, list):
        issues.append("compiled_targets must be a list")
    return issues


def validate_wiki_metadata(path: Path) -> list[str]:
    """Input: wiki Markdown path. Output: issue strings. Validate compiled wiki metadata."""
    metadata, _ = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
    issues = _missing_fields(metadata, WIKI_REQUIRED_FIELDS)
    for list_field in ("compiled_from", "consumed_by"):
        value = metadata.get(list_field, [])
        if value and not isinstance(value, list):
            issues.append(f"{list_field} must be a list")
    stale_after_days = metadata.get("stale_after_days")
    if stale_after_days not in (None, ""):
        try:
            if int(stale_after_days) <= 0:
                issues.append("stale_after_days must be positive")
        except (TypeError, ValueError):
            issues.append("stale_after_days must be a positive integer")
    return issues


def source_index_row_to_dict(row: SourceIndexRow) -> dict[str, Any]:
    """Input: SourceIndexRow. Output: dict. Convert one source index row."""
    return asdict(row)


def _source_index_guard(root: Path):
    """Input: vault Path. Output: existing lock context manager. Serialize all source-index writers."""
    _check_index_path(root / 'machine/source_index_write.guard')
    return json_lock_transition_guard(root / 'machine/source_index_write', SOURCE_INDEX_LOCK_SECONDS,
                                      SOURCE_INDEX_LOCK_SLEEP_SECONDS, 'source index writer is busy')


def _check_index_path(path: Path) -> None:
    """Input: target Path. Output: None. Refuse linked index files or parent directories before writing."""
    for current in (path.absolute(), *path.absolute().parents):
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('linked source index refused')


def _write_index_file(path: Path, content: str) -> None:
    """Input: target Path and UTF-8 text str. Output: None. Atomically replace one complete index file."""
    _check_index_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with staged.open('xb') as stream:
            stream.write(content.encode('utf-8'))
        _check_index_path(path)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def _write_machine_source_index_unlocked(knowledge_root: str | Path, rows: list[SourceIndexRow]) -> Path:
    """Input: vault root and source rows list. Output: Path. Write under the caller-owned index guard."""
    output = machine_resource_path(knowledge_root, "source_index")
    content = ''.join(json.dumps(source_index_row_to_dict(row), ensure_ascii=False, sort_keys=True) + '\n'
                      for row in sorted(rows, key=lambda item: item.path))
    _write_index_file(output, content)
    return output


def write_machine_source_index(knowledge_root: str | Path, rows: list[SourceIndexRow]) -> Path:
    """Input: vault root and source rows list. Output: Path. Publish the machine index under a shared guard."""
    root = Path(knowledge_root)
    with _source_index_guard(root):
        return _write_machine_source_index_unlocked(root, rows)


def _update_source_index_unlocked(knowledge_root: str | Path, rows: list[SourceIndexRow]) -> Path:
    """Input: vault root and rows list. Output: Path. Write both views under a caller-owned guard."""
    root = Path(knowledge_root)
    _write_machine_source_index_unlocked(root, rows)
    output = root / "raw" / "source_index.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Raw Source Index",
        "",
        "This file is generated from canonical raw source metadata and migration records.",
        "",
    ]
    for row in sorted(rows, key=lambda item: item.path):
        lines.extend(
            [
                f"## `{row.path}`",
                "",
                f"- Source Family: `{row.source_family}`",
                f"- Source Type: `{row.source_type}`",
                f"- Contents: {row.contents}",
                f"- Captured At: `{row.captured_at}`",
                f"- Record Count: `{row.record_count}`",
                f"- Content Hash: `{row.content_hash}`",
                f"- Content Status: `{row.content_status}`",
                f"- Update Check: {row.update_check}",
                "- Compiled Targets:",
                *[f"  - `{target}`" for target in row.compiled_targets],
                "",
            ]
        )
    _write_index_file(output, "\n".join(lines))
    return output


def update_source_index(knowledge_root: str | Path, rows: list[SourceIndexRow]) -> Path:
    """Input: vault root and rows list. Output: Path. Serialize a complete two-view index update."""
    root = Path(knowledge_root)
    with _source_index_guard(root):
        return _update_source_index_unlocked(root, rows)


def upsert_source_index_rows(
    knowledge_root: str | Path,
    rows: list[SourceIndexRow],
) -> Path:
    """Input: vault root and source rows. Output: source index path. Merge writer-owned rows by canonical path."""
    root = Path(knowledge_root)
    with _source_index_guard(root):
        return _upsert_source_index_rows_unlocked(root, rows)


def _upsert_source_index_rows_unlocked(root: Path, rows: list[SourceIndexRow]) -> Path:
    """Input: vault Path and rows list. Output: Path. Keep read/merge/write inside one index guard."""
    machine_index = _source_contract_path(root, 'machine/source_index.jsonl')
    _reject_unindexed_human_history(root)
    merged: dict[str, SourceIndexRow] = {}
    if machine_index.exists():
        for line_number, line in enumerate(
            machine_index.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                existing = _strict_source_index_row(_capture_json(line.encode('utf-8')))
                if existing.path in merged:
                    raise ValueError('duplicate source index identity')
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"invalid machine source index row {line_number}: {machine_index}"
                ) from error
            merged[existing.path] = existing
    incoming = set()
    for row in rows:
        if not isinstance(row, SourceIndexRow):
            raise ValueError('source index update requires SourceIndexRow values')
        row = _strict_source_index_row(asdict(row))
        if row.path in incoming:
            raise ValueError('duplicate incoming source index identity')
        incoming.add(row.path)
        merged[row.path] = row
    return _update_source_index_unlocked(root, list(merged.values()))


def _capture_json_object(pairs: list[tuple]) -> dict:
    """Input: JSON key/value pair list. Output: dict. Reject duplicate captured keys."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate capture JSON key')
        result[key] = value
    return result


def _capture_json_constant(value: str) -> None:
    """Input: nonfinite constant str. Output: raises ValueError. Keep captured facts valid JSON."""
    raise ValueError('invalid capture JSON constant: ' + value)


def _capture_json(raw: bytes) -> dict:
    """Input: UTF-8 JSON bytes. Output: dict. Parse bounded captured objects without duplicate keys."""
    try:
        value = json.loads(raw, object_pairs_hook=_capture_json_object, parse_constant=_capture_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('malformed captured JSON') from error
    if not isinstance(value, dict):
        raise ValueError('captured JSON requires an object')
    return value


def _capture_timestamp(value: object) -> datetime:
    """Input: timestamp object. Output: aware datetime. Reject missing or naive source dates."""
    if not isinstance(value, str):
        raise ValueError('missing capture timestamp')
    try:
        timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('invalid capture timestamp') from error
    if timestamp.tzinfo is None:
        raise ValueError('naive capture timestamp')
    return timestamp


def _capture_manifest_outcome(manifest: dict, scope: dict) -> dict:
    """Input: capture manifest/exact scope dicts. Output: matching generation metadata, never an unrelated fallback."""
    from wqb.semantic_contracts import resource_scope_from_dict
    top_scope = None
    if 'scope' in manifest:
        top_scope = resource_scope_from_dict(manifest['scope'])
    if 'requested_matrix' in manifest:
        matrix = manifest['requested_matrix']
        if not isinstance(matrix, list) or not matrix:
            raise ValueError('invalid requested capture matrix')
        scopes = [resource_scope_from_dict(item) for item in matrix]
        if scope not in scopes:
            raise ValueError('selected scope is outside requested capture matrix')
    outcomes = manifest.get('latest_scope_outcomes', [])
    if not isinstance(outcomes, list) or any(not isinstance(item, dict) for item in outcomes):
        raise ValueError('invalid capture scope outcomes')
    matches = []
    for item in outcomes:
        captured_scope = resource_scope_from_dict(item.get('scope'))
        if captured_scope == scope:
            matches.append(item)
    if outcomes:
        if len(matches) != 1:
            raise ValueError('selected scope has missing or ambiguous capture outcome')
        outcome = matches[0]
        if outcome.get('status') not in ('completed', 'partial'):
            raise ValueError('selected capture scope is not completed or partial')
    else:
        if top_scope != scope:
            raise ValueError('manifest does not cover selected scope')
        if 'status' in manifest and manifest['status'] not in ('completed', 'partial'):
            raise ValueError('selected capture scope is not completed or partial')
        outcome = manifest
    generation = outcome.get('capture_generation_id')
    if not isinstance(generation, str) or not generation.strip():
        raise ValueError('invalid capture generation identity')
    _capture_timestamp(outcome.get('generated_at'))
    return outcome


def _scan_field_source(source: Path, identities: list[dict], manifest: dict) -> dict:
    """Input: source Path, exact identities list and manifest dict. Output: hashes/selected rows; stream raw bytes."""
    from wqb.semantic_contracts import resource_scope_from_dict
    expected = {json.dumps(identity, sort_keys=True): identity for identity in identities}
    selected = {}
    source_hash = hashlib.sha256()
    before = source.stat()
    count, selected_bytes, oldest = 0, 0, None
    original_captured_at = None
    with source.open('rb') as stream:
        while True:
            raw = stream.readline(MAX_FIELD_CAPTURE_LINE_BYTES + 1)
            if not raw:
                break
            if len(raw) > MAX_FIELD_CAPTURE_LINE_BYTES:
                raise ValueError('captured field line exceeds bound')
            source_hash.update(raw)
            if not raw.strip():
                continue
            count += 1
            row = _capture_json(raw)
            if any(not isinstance(row.get(key), dict) for key in ('field', 'data_set', 'scope')):
                raise ValueError('invalid field capture row')
            row_date = _capture_timestamp(row.get('generated_at'))
            if oldest is None or row_date < oldest:
                oldest, original_captured_at = row_date, row['generated_at']
            identity = dict(dataset_id=row['data_set'].get('id'), field_id=row['field'].get('id'), scope=row['scope'])
            key = json.dumps(identity, sort_keys=True)
            if key not in expected:
                continue
            resource_scope_from_dict(row['scope'])
            if row.get('endpoint') != '/data-fields':
                raise ValueError('unsupported field capture endpoint')
            nested_dataset = row['field'].get('dataset')
            if nested_dataset is not None and (not isinstance(nested_dataset, dict)
                    or nested_dataset.get('id') != identity['dataset_id']):
                raise ValueError('conflicting captured dataset identity')
            outcome = _capture_manifest_outcome(manifest, row['scope'])
            if (row.get('capture_generation_id') != outcome.get('capture_generation_id')
                    or row_date != _capture_timestamp(outcome.get('generated_at'))):
                raise ValueError('field capture generation/date mismatch')
            if key in selected:
                raise ValueError('duplicate captured field identity')
            selected_bytes += len(raw)
            if selected_bytes > MAX_FIELD_EXTRACT_BYTES:
                raise ValueError('selected field bytes exceed extract bound')
            selected[key] = dict(row=row, row_sha256=hashlib.sha256(raw).hexdigest(), record_number=count,
                                 captured_at=row['generated_at'], capture_generation_id=row['capture_generation_id'])
    after = source.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('field source changed during extraction')
    if selected.keys() != expected.keys():
        raise ValueError('missing exact field capture identities')
    epochs = {(_capture_timestamp(item['captured_at']), item['capture_generation_id']) for item in selected.values()}
    if len(epochs) != 1:
        raise ValueError('mixed capture epochs require separate source excerpts')
    return dict(original_sha256=source_hash.hexdigest(), original_rows=count,
                selected=[selected[key] for key in sorted(selected)], source_stat=after,
                original_captured_at=original_captured_at)


def _write_immutable_source(path: Path, content: bytes) -> None:
    """Input: artifact Path/bytes. Output: None. Keep existing source artifacts immutable on replay."""
    _check_index_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.stat().st_size != len(content) or path.read_bytes() != content:
            raise ValueError('existing source extraction artifact differs')
        return
    staged = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with staged.open('xb') as stream:
            stream.write(content)
        _check_index_path(path)
        if path.exists():
            if not path.is_file() or path.stat().st_size != len(content) or path.read_bytes() != content:
                raise ValueError('source extraction artifact changed during publication')
        else:
            staged.rename(path)
    finally:
        staged.unlink(missing_ok=True)


def extract_field_source_subset(root: Path, source_path: str, identities: list[dict],
                                *, max_rows: int = MAX_FIELD_EXTRACT_ROWS) -> dict:
    """Input: vault Path/raw JSONL path/exact identities list/row bound int. Output: immutable extract receipt dict.

    Stream original bytes, verify captured identities and dates, publish a small
    Markdown raw excerpt plus original/row digests. This grants no semantic or
    historical PIT authority and never changes original capture bytes/dates.
    """
    from wqb.semantic_contracts import resource_scope_from_dict
    root = Path(root)
    if (not isinstance(source_path, str) or '\\' in source_path or ':' in source_path
            or str(PurePosixPath(source_path)) != source_path):
        raise ValueError('invalid field source path')
    parts = PurePosixPath(source_path).parts
    if len(parts) != 5 or parts[:3] != ('raw', 'platform', 'data_fields') or parts[-1] != 'data_fields.jsonl':
        raise ValueError('field source must be a canonical captured JSONL')
    if (type(max_rows) is not int or not 1 <= max_rows <= MAX_FIELD_EXTRACT_ROWS
            or not isinstance(identities, list) or not 1 <= len(identities) <= max_rows):
        raise ValueError('invalid field extract row bound')
    for identity in identities:
        if not isinstance(identity, dict) or set(identity) != {'dataset_id', 'field_id', 'scope'}:
            raise ValueError('exact field identity required')
        if any(not isinstance(identity[key], str) or not identity[key].strip() for key in ('dataset_id', 'field_id')):
            raise ValueError('invalid field identity')
        resource_scope_from_dict(identity['scope'])
    identity_keys = sorted(json.dumps(identity, sort_keys=True) for identity in identities)
    if len(set(identity_keys)) != len(identity_keys):
        raise ValueError('duplicate requested field identity')
    source = _source_contract_path(root, source_path)
    manifest_path = _source_contract_path(root, '/'.join(parts[:-1]) + '/manifest.json')
    manifest_bytes = _source_contract_bytes(manifest_path, MAX_CAPTURE_MANIFEST_BYTES)
    manifest = _capture_json(manifest_bytes)
    captured_at = manifest.get('generated_at')
    timestamp = _capture_timestamp(captured_at)
    generation = manifest.get('capture_generation_id')
    if (timestamp.date().isoformat() != parts[3] or not isinstance(generation, str) or not generation.strip()
            or manifest.get('certification_status') not in ('complete', 'partial')):
        raise ValueError('unverified capture manifest')
    scanned = _scan_field_source(source, identities, manifest)
    captured_at = scanned['selected'][0]['captured_at']
    original_hash = scanned['original_sha256']
    identity = dict(kind='field_source_extract', version=1, source_path=source_path,
        original_sha256=original_hash, manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(), identities=identity_keys)
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode('utf-8')).hexdigest()
    excerpt_path = '/'.join(parts[:-1]) + '/semantic-subset-' + key + '.md'
    receipt_path = 'machine/semantic_jobs/' + key + '/field_source_extract.json'
    body = '# Verified Field Source Extract\n\n' + '```json\n' + json.dumps(
        dict(rows=[item['row'] for item in scanned['selected']]), ensure_ascii=False,
        sort_keys=True, allow_nan=False) + '\n```\n'
    body_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
    metadata = dict(source_type='platform_data_field_capture', source_family='raw/platform/data_fields',
        source_path=excerpt_path, captured_at=captured_at, capture_tool='knowledge_contracts.extract_field_source_subset',
        content_status='verified_raw_extract', record_count=len(identities), content_hash=body_hash,
        update_check='verify original capture, row digests and extraction receipt',
        compiled_targets=['machine/data_ledger.jsonl'], extraction_receipt=receipt_path,
        original_source_path=source_path, original_sha256=original_hash)
    excerpt = (render_front_matter(metadata) + body).encode('utf-8')
    if len(excerpt) > MAX_FIELD_EXTRACT_BYTES:
        raise ValueError('rendered field extract exceeds bound')
    result = dict(status='extracted', source_path=source_path, excerpt_path=excerpt_path,
                  receipt_path=receipt_path, original_sha256=original_hash, selected_rows=len(identities))
    expected_receipt = dict(identity=identity, result=result, captured_at=captured_at,
        original_rows=scanned['original_rows'], partial=True,
        excerpt_sha256=hashlib.sha256(excerpt).hexdigest(), body_sha256=body_hash,
        row_receipts=[{name: item[name] for name in ('row_sha256', 'record_number', 'captured_at', 'capture_generation_id')}
                      for item in scanned['selected']])
    with _source_index_guard(root):
        _reject_unindexed_human_history(root)
        existing = [asdict(row) for row in _repair_index_rows(root)]
        origins = [row for row in existing if row.get('path') == source_path]
        if len(origins) > 1:
            raise ValueError('duplicate original source index identity')
        if origins:
            origin = origins[0]
            if (not isinstance(origin.get('content_hash'), str) or origin['content_hash'].lower() != original_hash
                    or origin.get('source_type') != 'platform_data_field_capture'
                    or origin.get('source_family') != 'raw/platform/data_fields'
                    or type(origin.get('record_count')) is not int or origin['record_count'] != scanned['original_rows']
                    or origin.get('content_status') != 'raw_jsonl'
                    or _capture_timestamp(origin.get('captured_at')) != _capture_timestamp(scanned['original_captured_at'])):
                raise ValueError('original source index conflicts; explicit repair required')
        snapshot = scanned['source_stat']
        current = source.stat()
        if ((current.st_size, current.st_mtime_ns, current.st_ino) != (snapshot.st_size, snapshot.st_mtime_ns, snapshot.st_ino)
                or manifest_path.read_bytes() != manifest_bytes):
            raise ValueError('capture changed before extract publication')
        receipt_file = _source_contract_path(root, receipt_path)
        if receipt_file.exists():
            if receipt_file.stat().st_size > MAX_FIELD_EXTRACT_BYTES:
                raise ValueError('source extraction receipt exceeds bound')
            cached = _capture_json(receipt_file.read_bytes())
            _capture_timestamp(cached.get('extracted_at'))
            cached_body = {name: value for name, value in cached.items() if name != 'extracted_at'}
            if json.dumps(cached_body, sort_keys=True, allow_nan=False) != json.dumps(expected_receipt, sort_keys=True, allow_nan=False):
                raise ValueError('source extraction receipt mismatch')
            receipt = cached
        else:
            receipt = dict(expected_receipt, extracted_at=datetime.now(timezone.utc).isoformat())
        _write_immutable_source(_source_contract_path(root, excerpt_path), excerpt)
        rows = [SourceIndexRow(path=excerpt_path, source_family='raw/platform/data_fields',
            source_type='platform_data_field_capture', contents='Verified raw rows; derived semantics are not included.',
            update_check=metadata['update_check'], compiled_targets=metadata['compiled_targets'],
            captured_at=captured_at, record_count=len(identities), content_hash=body_hash, content_status='verified_raw_extract')]
        if not origins:
            rows.append(SourceIndexRow(path=source_path, source_family='raw/platform/data_fields',
                source_type='platform_data_field_capture', contents='Original captured rows; subset receipts do not certify global coverage.',
                update_check='verify complete original bytes and capture manifest', compiled_targets=['machine/data_ledger.jsonl'],
                captured_at=scanned['original_captured_at'], record_count=scanned['original_rows'],
                content_hash=original_hash, content_status='raw_jsonl'))
        _upsert_source_index_rows_unlocked(root, rows)
        _write_immutable_source(receipt_file, (json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8'))
        verify_field_source_extract(root, excerpt_path)
        if not _repair_human_index_agrees(root, _repair_index_rows(root)):
            raise ValueError('field extraction index publication incomplete; replay required')
    return result


def _resolved_source_path(path: Path) -> Path:
    """Input: Path. Output: resolved Path. Compare ordinary and extended Windows filesystem namespaces equally."""
    value = str(path.resolve())
    if os.name == 'nt':
        if value.startswith('\\\\?\\UNC\\'):
            value = '\\\\' + value[8:]
        elif (value.startswith('\\\\?\\') and len(value) >= 7
              and value[4] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' and value[5:7] == ':\\'):
            value = value[4:]
    return Path(value)


def _source_contract_path(root: Path, relative: str) -> Path:
    """Input: vault Path/relative str. Output: safe Path. Reject aliases, escapes, links and hardlinked files."""
    if (not isinstance(relative, str) or not relative or relative == '.' or '\\' in relative or ':' in relative
            or str(PurePosixPath(relative)) != relative or PurePosixPath(relative).is_absolute()
            or '..' in PurePosixPath(relative).parts):
        raise ValueError('invalid source contract path')
    path = root / relative
    _check_index_path(path)
    if not _resolved_source_path(path).is_relative_to(_resolved_source_path(root)):
        raise ValueError('source contract path outside root')
    if path.is_file() and path.stat().st_nlink != 1:
        raise ValueError('hardlinked source contract file refused')
    return path


def _source_contract_bytes(path: Path, limit: int) -> bytes:
    """Input: Path/int bound. Output: bytes. Bound small evidence reads; never load original JSONL here."""
    try:
        with path.open('rb') as stream:
            raw = stream.read(limit + 1)
    except OSError as error:
        raise ValueError('source contract evidence unavailable: ' + path.name) from error
    if len(raw) > limit:
        raise ValueError('source contract evidence exceeds bound')
    return raw


def verify_field_source_extract(root: Path, source_path: str) -> dict:
    """Input: vault Path/excerpt path str. Output: verified receipt/result dict. Read only, stream original once.

    Reconstruct the producer's exact content key, excerpt and receipt from original
    rows and manifest. A marker/header or a previously successful check is not trust.
    No persistent verification cache, publication or lock-file creation is performed.
    """
    from wqb.semantic_contracts import resource_scope_from_dict
    root = Path(root)
    excerpt_file = _source_contract_path(root, source_path)
    parts = PurePosixPath(source_path).parts
    name = parts[-1]
    key = name.removeprefix('semantic-subset-').removesuffix('.md')
    if (len(parts) != 5 or parts[:3] != ('raw', 'platform', 'data_fields')
            or name != 'semantic-subset-' + key + '.md' or len(key) != 64
            or any(c not in '0123456789abcdef' for c in key)):
        raise ValueError('canonical field excerpt required')
    original_path = '/'.join(parts[:-1]) + '/data_fields.jsonl'
    original = _source_contract_path(root, original_path)
    manifest_file = _source_contract_path(root, '/'.join(parts[:-1]) + '/manifest.json')
    receipt_path = 'machine/semantic_jobs/' + key + '/field_source_extract.json'
    receipt_file = _source_contract_path(root, receipt_path)
    manifest_bytes = _source_contract_bytes(manifest_file, MAX_CAPTURE_MANIFEST_BYTES)
    manifest = _capture_json(manifest_bytes)
    timestamp = _capture_timestamp(manifest.get('generated_at'))
    generation = manifest.get('capture_generation_id')
    if (timestamp.date().isoformat() != parts[3] or not isinstance(generation, str) or not generation.strip()
            or manifest.get('certification_status') not in ('complete', 'partial')):
        raise ValueError('unverified capture manifest')
    receipt_bytes = _source_contract_bytes(receipt_file, MAX_FIELD_EXTRACT_BYTES)
    receipt = _capture_json(receipt_bytes)
    identity = receipt.get('identity')
    if not isinstance(identity, dict) or not isinstance(identity.get('identities'), list):
        raise ValueError('invalid field extraction identity')
    keys = identity['identities']
    if not 1 <= len(keys) <= MAX_FIELD_EXTRACT_ROWS or any(not isinstance(item, str) for item in keys):
        raise ValueError('invalid field extraction identities')
    if keys != sorted(set(keys)):
        raise ValueError('duplicate or unordered field extraction identities')
    identities = []
    for item in keys:
        selected = _capture_json(item.encode('utf-8'))
        if (set(selected) != {'dataset_id', 'field_id', 'scope'}
                or any(not isinstance(selected[k], str) or not selected[k].strip() for k in ('dataset_id', 'field_id'))
                or json.dumps(selected, sort_keys=True) != item):
            raise ValueError('invalid exact extracted identity')
        resource_scope_from_dict(selected['scope'])
        identities.append(selected)
    scanned = _scan_field_source(original, identities, manifest)
    expected_identity = dict(kind='field_source_extract', version=1, source_path=original_path,
        original_sha256=scanned['original_sha256'], manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        identities=keys)
    expected_key = hashlib.sha256(json.dumps(expected_identity, sort_keys=True).encode('utf-8')).hexdigest()
    if expected_key != key:
        raise ValueError('field extraction content key mismatch')
    captured_at = scanned['selected'][0]['captured_at']
    body = '# Verified Field Source Extract\n\n' + '```json\n' + json.dumps(
        dict(rows=[item['row'] for item in scanned['selected']]), ensure_ascii=False,
        sort_keys=True, allow_nan=False) + '\n```\n'
    body_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
    metadata = dict(source_type='platform_data_field_capture', source_family='raw/platform/data_fields',
        source_path=source_path, captured_at=captured_at, capture_tool='knowledge_contracts.extract_field_source_subset',
        content_status='verified_raw_extract', record_count=len(identities), content_hash=body_hash,
        update_check='verify original capture, row digests and extraction receipt',
        compiled_targets=['machine/data_ledger.jsonl'], extraction_receipt=receipt_path,
        original_source_path=original_path, original_sha256=scanned['original_sha256'])
    excerpt = (render_front_matter(metadata) + body).encode('utf-8')
    result = dict(status='extracted', source_path=original_path, excerpt_path=source_path,
        receipt_path=receipt_path, original_sha256=scanned['original_sha256'], selected_rows=len(identities))
    expected_receipt = dict(identity=expected_identity, result=result, captured_at=captured_at,
        original_rows=scanned['original_rows'], partial=True,
        excerpt_sha256=hashlib.sha256(excerpt).hexdigest(), body_sha256=body_hash,
        row_receipts=[{name: item[name] for name in ('row_sha256', 'record_number', 'captured_at', 'capture_generation_id')}
                      for item in scanned['selected']])
    _capture_timestamp(receipt.get('extracted_at'))
    actual = {name: value for name, value in receipt.items() if name != 'extracted_at'}
    if (json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(expected_receipt, sort_keys=True, allow_nan=False)
            or _source_contract_bytes(excerpt_file, MAX_FIELD_EXTRACT_BYTES) != excerpt):
        raise ValueError('field extraction receipt or excerpt mismatch')
    index = _source_contract_path(root, 'machine/source_index.jsonl')
    # Only retain the two consumed identities; the original catalog is streamed above.
    indexed = {}
    try:
        with index.open('rb') as stream:
            for raw in stream:
                if not raw.strip():
                    continue
                row = _capture_json(raw)
                if row.get('path') in (source_path, original_path):
                    if row['path'] in indexed:
                        raise ValueError('duplicate field extraction index identity')
                    indexed[row['path']] = row
    except OSError as error:
        raise ValueError('field extraction index unavailable') from error
    for path, expected in ((source_path, dict(source_family='raw/platform/data_fields',
            source_type='platform_data_field_capture', captured_at=captured_at, record_count=len(identities),
            content_hash=body_hash, content_status='verified_raw_extract')),
            (original_path, dict(source_family='raw/platform/data_fields', source_type='platform_data_field_capture',
            captured_at=scanned['original_captured_at'], record_count=scanned['original_rows'],
            content_hash=scanned['original_sha256'], content_status='raw_jsonl'))):
        row = indexed.get(path, {})
        if (set(row) - {item.name for item in fields(SourceIndexRow)}
                or json.dumps({k: row.get(k) for k in expected}, sort_keys=True) != json.dumps(expected, sort_keys=True)):
            raise ValueError('field extraction index mismatch')
    current = original.stat()
    snapshot = scanned['source_stat']
    if ((current.st_size, current.st_mtime_ns, current.st_ino) != (snapshot.st_size, snapshot.st_mtime_ns, snapshot.st_ino)
            or _source_contract_bytes(manifest_file, MAX_CAPTURE_MANIFEST_BYTES) != manifest_bytes
            or _source_contract_bytes(receipt_file, MAX_FIELD_EXTRACT_BYTES) != receipt_bytes):
        raise ValueError('field extraction evidence changed during verification')
    return dict(result, status='verified', captured_at=captured_at, body_sha256=body_hash,
                excerpt_sha256=expected_receipt['excerpt_sha256'], partial=True)


def verified_field_extract_source(root: Path, source_path: str, dataset_id: str, field_id: str,
                                  scopes: set[tuple]) -> Path | None:
    """Input: vault Path, excerpt/field identity strings and exact scope tuples. Output: original Path or None after full provenance verification."""
    try:
        key = PurePosixPath(source_path).name.removeprefix('semantic-subset-').removesuffix('.md')
        receipt = _source_contract_path(root, 'machine/semantic_jobs/' + key + '/field_source_extract.json')
        before = _source_contract_bytes(receipt, MAX_FIELD_EXTRACT_BYTES)
        verified = verify_field_source_extract(root, source_path)
        if verified.get('status') != 'verified' or _source_contract_bytes(receipt, MAX_FIELD_EXTRACT_BYTES) != before:
            return None
        identities = [_capture_json(value.encode('utf-8')) for value in _capture_json(before)['identity']['identities']]
        selected = set()
        for item in identities:
            if item['dataset_id'] == dataset_id and item['field_id'] == field_id:
                scope = item['scope']
                selected.add((scope.get('instrument_type', 'EQUITY'), scope['region'], scope['delay'], scope['universe']))
        if not scopes or not scopes.issubset(selected):
            return None
        return _source_contract_path(root, verified['source_path'])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _learn_repair_body(section: str, rows: list[dict]) -> str:
    """Input: known Learn section str/original list. Output: str. Match legacy raw rendering, not inferred semantics."""
    from scripts.capture_learn_material import markdown_record_value
    title = 'Operators' if section == 'operators' else 'Documentation Pages'
    lines = ['', '# ' + title, '', f'Record count: {len(rows)}', '']
    if section == 'operators':
        categories = {}
        for row in rows:
            categories.setdefault(str(row.get('category') or 'Uncategorized'), []).append(row)
        for category in sorted(categories):
            lines.extend(['## ' + category, ''])
            for row in sorted(categories[category], key=lambda item: str(item.get('name', '')).lower()):
                name = row.get('name', '')
                lines.extend([f'### `{name}`', '', f'- Source id: `{name}`',
                    f"- Scope: {row.get('scope', 'unspecified')}", f"- Level: {row.get('level', 'unspecified')}",
                    f"- Documentation: {row.get('documentation', '')}",
                    f"- Definition: `{markdown_record_value(row.get('definition'))}`",
                    f"- Description: {markdown_record_value(row.get('description'))}", ''])
    else:
        for page in sorted(rows, key=lambda item: str(item.get('title', item.get('id', ''))).lower()):
            page_id = page.get('id', '')
            lines.extend([f"## {page.get('title') or page_id}", '', f'- Page id: `{page_id}`',
                          f"- Category: {page.get('category', '')}", '', markdown_record_value(page.get('content')), ''])
    return '\n'.join(lines).rstrip() + '\n'


def _repair_markdown_parts(raw: bytes) -> tuple[dict, bytes, bytes]:
    """Input: UTF-8 Markdown bytes. Output: metadata/header/body tuple. Reject ambiguous flat headers; retain body bytes."""
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != b'---':
        raise ValueError('source repair requires an original metadata header')
    seen = set()
    list_allowed = False
    for i, raw_line in enumerate(lines[1:], 1):
        line = raw_line.decode('utf-8').rstrip('\r\n')
        if line == '---':
            header = b''.join(lines[:i + 1])
            metadata, _ = parse_markdown_front_matter(header.decode('utf-8').replace('\r\n', '\n'))
            return metadata, header, b''.join(lines[i + 1:])
        if line.startswith('  - ') and list_allowed:
            continue
        key, separator, value = line.partition(':')
        if (not separator or not key or not all(c.isascii() and (c.isalnum() or c == '_') for c in key)
                or key in seen):
            raise ValueError('ambiguous source metadata header')
        seen.add(key)
        list_allowed = not value.strip()
    raise ValueError('unterminated source metadata header')


def _strict_source_index_row(row: dict) -> SourceIndexRow:
    """Input: row dict. Output: SourceIndexRow. Reject malformed metadata rather than coercing or dropping it."""
    if not isinstance(row, dict) or set(row) - {item.name for item in fields(SourceIndexRow)}:
        raise ValueError('unsupported source index metadata; explicit migration required')
    try:
        parsed = SourceIndexRow(**row)
    except TypeError as error:
        raise ValueError('invalid source index row') from error
    payload = asdict(parsed)
    if (type(parsed.record_count) is not int or parsed.record_count < 0
            or not isinstance(parsed.compiled_targets, list)
            or any(not isinstance(value, str) or '\n' in value or '\r' in value
                   for key, value in payload.items() if key not in ('record_count', 'compiled_targets'))
            or any(not isinstance(value, str) or '\n' in value or '\r' in value for value in parsed.compiled_targets)):
        raise ValueError('invalid source index metadata types')
    return parsed


def _reject_unindexed_human_history(root: Path) -> None:
    """Input: vault Path. Output: None. Require machine history before a merge may replace a surviving human view."""
    machine = _source_contract_path(root, 'machine/source_index.jsonl')
    human = _source_contract_path(root, 'raw/source_index.md')
    if not machine.exists() and human.exists() and not _repair_human_index_agrees(root, []):
        raise ValueError('missing machine source index; surviving human history requires verified recovery')


def _repair_index_rows(root: Path) -> list[SourceIndexRow]:
    """Input: vault Path. Output: typed rows list. Fail closed on duplicate identities, unsupported or malformed metadata."""
    index = _source_contract_path(root, 'machine/source_index.jsonl')
    rows, seen = [], set()
    if not index.exists():
        return rows
    with index.open('rb') as stream:
        for raw in stream:
            if not raw.strip():
                continue
            row = _capture_json(raw)
            parsed = _strict_source_index_row(row)
            if parsed.path in seen:
                raise ValueError('duplicate source index identity')
            seen.add(parsed.path)
            rows.append(parsed)
    return rows


def _repair_human_index_agrees(root: Path, rows: list[SourceIndexRow]) -> bool:
    """Input: vault Path/rows list. Output: bool. Compare the entire human view with the existing writer's format."""
    path = _source_contract_path(root, 'raw/source_index.md')
    lines = ['# Raw Source Index', '',
             'This file is generated from canonical raw source metadata and migration records.', '']
    for row in sorted(rows, key=lambda item: item.path):
        lines.extend([f'## `{row.path}`', '', f'- Source Family: `{row.source_family}`',
            f'- Source Type: `{row.source_type}`', f'- Contents: {row.contents}',
            f'- Captured At: `{row.captured_at}`', f'- Record Count: `{row.record_count}`',
            f'- Content Hash: `{row.content_hash}`', f'- Content Status: `{row.content_status}`',
            f'- Update Check: {row.update_check}', '- Compiled Targets:',
            *[f'  - `{target}`' for target in row.compiled_targets], ''])
    return path.exists() and path.read_bytes() == '\n'.join(lines).encode('utf-8')


def _prepare_source_repair(root: Path, relative: str, rows: list[SourceIndexRow]) -> tuple[dict | None, str]:
    """Input: vault Path/source str/index rows. Output: (immutable correction dict or None, reason str). Verify original cache."""
    source = _source_contract_path(root, relative)
    parts = PurePosixPath(relative).parts
    section = source.stem
    if section not in ('operators', 'documentation_pages'):
        return None, 'unknown source family; need fresh bounded capture'
    cache_dir = 'docs/knowledge/cache/learn/' + parts[3] + '/'
    payload_file = _source_contract_path(root, cache_dir + section + '.json')
    manifest_file = _source_contract_path(root, cache_dir + 'learn_capture_manifest.json')
    try:
        raw = _source_contract_bytes(source, MAX_SOURCE_REPAIR_BYTES)
        metadata, header, body = _repair_markdown_parts(raw)
        payload_bytes = _source_contract_bytes(payload_file, MAX_SOURCE_REPAIR_BYTES)
        manifest_bytes = _source_contract_bytes(manifest_file, MAX_CAPTURE_MANIFEST_BYTES)
        payload = json.loads(payload_bytes, object_pairs_hook=_capture_json_object,
                             parse_constant=_capture_json_constant)
        manifest = _capture_json(manifest_bytes)
        date = metadata.get('captured_at')
        if (not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload)
                or manifest.get('generated_at') != date
                or _capture_timestamp(date).date().isoformat() != parts[3]
                or not isinstance(manifest.get('counts'), dict)
                or type(manifest['counts'].get(section)) is not int
                or manifest['counts'][section] != len(payload)
                or manifest.get('excluded') != ['courses']
                or metadata.get('capture_tool') != 'scripts/capture_learn_material.py'):
            raise ValueError('original capture provenance mismatch')
        identity_name = 'name' if section == 'operators' else 'id'
        ids = [row.get(identity_name) for row in payload]
        if (any(not isinstance(value, str) or not value.strip() for value in ids)
                or len(set(ids)) != len(ids) or any({'error', 'errors', 'detail'} & row.keys() for row in payload)
                or {'error', 'errors', 'detail'} & manifest.keys()):
            raise ValueError('invalid original source records')
        body_text = body.decode('utf-8').replace('\r\n', '\n')
        if body_text != _learn_repair_body(section, payload):
            raise ValueError('retained original does not reproduce the complete raw body')
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        return None, str(error)
    payload_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
    corrected = dict(metadata, source_path=relative, source_type='platform_learn_material',
        source_family='raw/platform/learn', content_hash=hashlib.sha256(body_text.encode('utf-8')).hexdigest(),
        payload_hash=payload_hash, record_count=len(payload), content_status='raw_markdown')
    corrected.pop('source_repair_receipt', None)
    old_row = next((asdict(row) for row in rows if row.path == relative), None)
    targets = corrected.get('compiled_targets')
    if (not isinstance(targets, list) or any(not isinstance(target, str) or '\n' in target or '\r' in target
            or PurePosixPath(target).is_absolute() or '..' in PurePosixPath(target).parts
            or not target.startswith(('wiki/', 'machine/')) for target in targets)
            or not isinstance(corrected.get('update_check'), str) or '\n' in corrected['update_check']):
        raise ValueError('unsafe source index projection')
    new_row = dict(path=relative, source_family=corrected['source_family'], source_type=corrected['source_type'],
        contents=old_row['contents'] if old_row else 'Verified original Learn capture file ' + source.name,
        update_check=corrected['update_check'], compiled_targets=targets, captured_at=date, record_count=len(payload),
        content_hash=corrected['content_hash'], content_status='raw_markdown')
    proof = dict(payload_path=cache_dir + section + '.json', payload_file_sha256=hashlib.sha256(payload_bytes).hexdigest(),
        manifest_path=cache_dir + 'learn_capture_manifest.json', manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        renderer='scripts/capture_learn_material.py:' + section, payload_hash=payload_hash)
    previous = metadata.get('source_repair_receipt')
    if previous is None:
        _reject_unindexed_human_history(root)
    if previous is not None:
        if (not isinstance(previous, str) or len(PurePosixPath(previous).parts) != 4
                or PurePosixPath(previous).parts[:2] != ('machine', 'semantic_jobs')
                or PurePosixPath(previous).name != 'source_repair.json'
                or len(PurePosixPath(previous).parts[2]) != 64
                or any(c not in '0123456789abcdef' for c in PurePosixPath(previous).parts[2])):
            raise ValueError('invalid source repair receipt reference')
        receipt_file = _source_contract_path(root, previous)
        receipt = _capture_json(_source_contract_bytes(receipt_file, MAX_SOURCE_REPAIR_BYTES))
        key = hashlib.sha256(json.dumps(receipt, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        if previous != 'machine/semantic_jobs/' + key + '/source_repair.json':
            raise ValueError('source repair receipt content key mismatch')
        before_header = receipt.get('before_header')
        if not isinstance(before_header, str):
            raise ValueError('invalid source repair original header')
        before_raw = before_header.encode('utf-8') + body
        before_metadata, _, _ = _repair_markdown_parts(before_raw)
        if old_row is None:
            retained = receipt.get('index_after')
            if not isinstance(retained, dict) or not isinstance(retained.get('contents'), str):
                raise ValueError('invalid retained repair index projection')
            new_row['contents'] = retained['contents']
            # A missing target row is recoverable. A lost whole machine index
            # must not silently discard unrelated rows still in the human view.
            if not (root / 'machine/source_index.jsonl').exists():
                views = [retained, receipt.get('index_before')]
                if not any(isinstance(view, dict) and _repair_human_index_agrees(root, [SourceIndexRow(**view)])
                           for view in views):
                    raise ValueError('missing machine index has unverified unrelated history')
        if (receipt.get('kind') != 'source_repair' or receipt.get('version') != 1
                or receipt.get('source_path') != relative or receipt.get('before_metadata') != before_metadata
                or receipt.get('before_sha256') != hashlib.sha256(before_raw).hexdigest()
                or receipt.get('after_metadata') != corrected or receipt.get('proof') != proof
                or receipt.get('body_sha256') != hashlib.sha256(body).hexdigest()
                or receipt.get('index_after') != new_row
                or (old_row is not None and old_row not in (receipt.get('index_before'), receipt.get('index_after')))):
            raise ValueError('source repair replay evidence conflict')
        return dict(receipt=receipt, receipt_path=previous, raw=raw, body=body, metadata=corrected,
                    index_row=SourceIndexRow(**new_row)), ''
    receipt = dict(kind='source_repair', version=1, source_path=relative, before_metadata=metadata,
        before_header=header.decode('utf-8'), before_sha256=hashlib.sha256(raw).hexdigest(),
        after_metadata=corrected, body_sha256=hashlib.sha256(body).hexdigest(), proof=proof,
        index_before=old_row, index_after=new_row,
        reason='retained original payload and legacy rendering verify body, hashes, family and index; no date renewal')
    key = hashlib.sha256(json.dumps(receipt, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return dict(receipt=receipt, receipt_path='machine/semantic_jobs/' + key + '/source_repair.json', raw=raw,
                body=body, metadata=corrected, index_row=SourceIndexRow(**new_row)), ''


def verify_source_repair(root: Path, source_path: str) -> dict:
    """Input: vault Path/canonical source str. Output: status/source_sha256 dict or ValueError.

    Verify completed repair publication without writes or locks. Ordinary sources
    do not require paired index agreement. Callers must compare source_sha256 to
    the bytes they consume and revalidate at each consumption/publication boundary.
    """
    root = Path(root)
    source = _source_contract_path(root, source_path)
    raw = _source_contract_bytes(source, MAX_SOURCE_REPAIR_BYTES)
    metadata, _ = parse_markdown_front_matter(raw.decode('utf-8').replace('\r\n', '\n'))
    markers = {key for key in metadata if key.startswith('source_repair')}
    index = _source_contract_path(root, 'machine/source_index.jsonl')
    if index.exists():
        with index.open('rb') as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = _capture_json(line)
                if row.get('path') == source_path:
                    markers.update(key for key in row if key.startswith('source_repair'))
    # The old index schema has no repair marker. Retained receipts prevent a
    # removed header from turning a repaired Learn source back into legacy raw.
    if not markers and source.stem in ('operators', 'documentation_pages'):
        for receipt_file in (root / 'machine/semantic_jobs').glob('*/source_repair.json'):
            relative = receipt_file.relative_to(root).as_posix()
            receipt = _capture_json(_source_contract_bytes(_source_contract_path(root, relative), MAX_SOURCE_REPAIR_BYTES))
            if receipt.get('source_path') == source_path:
                raise ValueError('source repair receipt exists without its source marker; replay required')
    if not markers:
        return dict(status='not_repaired', source_sha256=hashlib.sha256(raw).hexdigest())
    if markers != {'source_repair_receipt'} or not metadata.get('source_repair_receipt'):
        raise ValueError('unknown or missing source repair receipt marker')
    parts = PurePosixPath(source_path).parts
    if (len(parts) != 5 or parts[:3] != ('raw', 'platform', 'learn')
            or source.name not in ('operators.md', 'documentation_pages.md')):
        raise ValueError('unsupported repaired source path')
    rows = _repair_index_rows(root)
    prepared, reason = _prepare_source_repair(root, source_path, rows)
    if prepared is None:
        raise ValueError('source repair evidence invalid: ' + reason)
    receipt_file = _source_contract_path(root, prepared['receipt_path'])
    receipt_bytes = (json.dumps(prepared['receipt'], sort_keys=True, indent=2, ensure_ascii=False,
                               allow_nan=False) + '\n').encode('utf-8')
    expected = render_front_matter(dict(prepared['metadata'],
        source_repair_receipt=prepared['receipt_path'])).encode('utf-8') + prepared['body']
    if (raw != expected or prepared['raw'] != raw
            or next((row for row in rows if row.path == source_path), None) != prepared['index_row']
            or not _repair_human_index_agrees(root, rows)
            or _source_contract_bytes(receipt_file, MAX_SOURCE_REPAIR_BYTES) != receipt_bytes):
        raise ValueError('source repair publication incomplete or conflicting; replay required')
    final_rows = _repair_index_rows(root)
    final, _ = _prepare_source_repair(root, source_path, final_rows)
    if (final != prepared or final_rows != rows or not _repair_human_index_agrees(root, final_rows)
            or _source_contract_bytes(source, MAX_SOURCE_REPAIR_BYTES) != raw
            or _source_contract_bytes(receipt_file, MAX_SOURCE_REPAIR_BYTES) != receipt_bytes):
        raise ValueError('source repair evidence changed during readonly verification')
    return dict(status='verified', source_sha256=hashlib.sha256(raw).hexdigest(),
                receipt_path=prepared['receipt_path'])


def repair_source_metadata(root: Path, paths: list[str], *, dry_run: bool = True) -> dict:
    """Input: vault Path/relative raw Markdown list/dry_run bool. Output: per-source audit/correction report dict.

    Default dry run writes nothing. Legacy operators/documentation pages require
    retained array caches and learn_capture_manifest.json at root/docs/knowledge/
    cache/learn/<date>/ (the existing capture-cache layout, scoped to this root).
    External caches, unknown families or unverifiable bodies need fresh capture;
    this API never reads credentials, renews dates or adds derived raw semantics.
    Each receipt is immutable before publication. Raw and each index file publish
    atomically under the existing guard, NOT as a multi-file transaction. Replay
    re-verifies originals and repairs partial publication before acknowledging it.
    """
    root = Path(root)
    if type(dry_run) is not bool or not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        raise ValueError('invalid source repair arguments')
    if len(set(paths)) != len(paths):
        raise ValueError('duplicate source repair paths')
    for relative in paths:
        _source_contract_path(root, relative)
        parts = PurePosixPath(relative).parts
        if (len(parts) != 5 or parts[:3] != ('raw', 'platform', 'learn') or not parts[-1].endswith('.md')
                or not all(c.isascii() and (c.isalnum() or c in '_-') for c in parts[-1][:-3])):
            raise ValueError('source repair requires canonical nonsensitive Learn Markdown')
        try:
            datetime.strptime(parts[3], '%Y-%m-%d')
        except ValueError as error:
            raise ValueError('invalid source repair date directory') from error
    _source_contract_path(root, 'raw/source_index.md')
    _source_contract_path(root, 'machine/source_index_write.guard')
    results = []
    for relative in paths:
        rows = _repair_index_rows(root)
        prepared, reason = _prepare_source_repair(root, relative, rows)
        if prepared is None:
            results.append(dict(source_path=relative, status='need_fresh_capture', reason=reason))
            continue
        result = dict(source_path=relative, status='planned' if dry_run else 'repaired',
                      receipt_path=prepared['receipt_path'], captured_at=prepared['metadata']['captured_at'])
        receipt_file = _source_contract_path(root, prepared['receipt_path'])
        receipt_bytes = (json.dumps(prepared['receipt'], sort_keys=True, indent=2, ensure_ascii=False,
                                    allow_nan=False) + '\n').encode('utf-8')
        if len(receipt_bytes) > MAX_SOURCE_REPAIR_BYTES:
            raise ValueError('source repair receipt exceeds bound')
        if receipt_file.exists() and _source_contract_bytes(receipt_file, MAX_SOURCE_REPAIR_BYTES) != receipt_bytes:
            raise ValueError('immutable source repair receipt conflict')
        if not dry_run:
            with _source_index_guard(root):
                current_rows = _repair_index_rows(root)
                current, _ = _prepare_source_repair(root, relative, current_rows)
                if current is None or current != prepared:
                    raise ValueError('source repair inputs changed before publication')
                _source_contract_path(root, 'raw/source_index.md')
                _write_immutable_source(receipt_file, receipt_bytes)
                metadata = dict(prepared['metadata'], source_repair_receipt=prepared['receipt_path'])
                corrected = render_front_matter(metadata).encode('utf-8') + prepared['body']
                _write_index_file(_source_contract_path(root, relative), corrected.decode('utf-8'))
                if not (root / 'machine/source_index.jsonl').exists() and (root / 'raw/source_index.md').exists():
                    # Only _prepare_source_repair's verified receipt/history path
                    # can reach this recovery; first repairs fail before writing.
                    _write_machine_source_index_unlocked(root, [prepared['index_row']])
                _upsert_source_index_rows_unlocked(root, [prepared['index_row']])
                final_rows = _repair_index_rows(root)
                verified, _ = _prepare_source_repair(root, relative, final_rows)
                if (next((row for row in final_rows if row.path == relative), None) != prepared['index_row']
                        or verified is None or verified['receipt'] != prepared['receipt']
                        or not _repair_human_index_agrees(root, final_rows)
                        or _source_contract_bytes(_source_contract_path(root, relative), MAX_SOURCE_REPAIR_BYTES) != corrected):
                    raise ValueError('source repair publication incomplete; replay required')
        results.append(result)
    return dict(dry_run=dry_run, results=results,
                status='need_fresh_capture' if any(item['status'] == 'need_fresh_capture' for item in results)
                else 'dry_run' if dry_run else 'repaired')
