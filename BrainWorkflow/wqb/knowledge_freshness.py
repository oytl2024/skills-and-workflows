from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_clean_compile import evaluate_clean_knowledge_structure
from wqb.knowledge_contracts import (
    RAW_REQUIRED_FIELDS,
    canonical_source_family,
    parse_markdown_front_matter,
    validate_raw_metadata,
    validate_wiki_metadata,
    verify_field_source_extracts,
)


REQUIRED_RESEARCH_RUN_MANIFEST_NAMES = {
    "data_ledger",
    "template_library",
    "benchmark_rules",
    "activity_snapshot",
}
USER_NOTE_HOUSEKEEPING_MESSAGES = {f"missing {field}" for field in RAW_REQUIRED_FIELDS}


@dataclass(frozen=True)
class KnowledgeFreshnessRecord:
    name: str
    path: str
    updated_at: str
    max_age_days: int


@dataclass(frozen=True)
class KnowledgeFreshnessStatus:
    name: str
    path: str
    updated_at: str
    max_age_days: int
    age_days: int
    stale: bool
    artifact_exists: bool = True


@dataclass(frozen=True)
class KnowledgeHealthIssue:
    code: str
    path: str
    message: str
    action: str


def _vault_relative(path: Path, root: Path) -> str:
    """Input: vault path and root. Output: POSIX relative path. Normalize contract references."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def _resolve_vault_reference(root: Path, value: str) -> Path | None:
    """Input: vault root and metadata reference. Output: resolved vault path or none. Reject external backlinks."""
    candidate = Path(str(value).replace("\\", "/"))
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        parts = candidate.parts
        if parts and parts[0].lower() == root.name.lower():
            candidate = Path(*parts[1:])
        resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def _is_local_design_note(path: Path, root: Path, metadata: dict[str, Any]) -> bool:
    """Input: safe file/root Paths and metadata dict. Output: bool. Classify only canonical local design notes."""
    relative = path.absolute().relative_to(root.absolute())
    return (
        relative.parts[:3] == ("raw", "community", "user_messages")
        and len(relative.parts) > 3
        and metadata.get("source_type") == "user_design_input"
        and metadata.get("status") == "design_discussion_not_implemented"
    )


def _user_note_provenance_issues(metadata: dict[str, Any], root: Path) -> list[str]:
    """Input: note metadata dict and vault Path. Output: list[str]. Reject invalid declared dates and local references."""
    issues = []
    if "captured_at" in metadata:
        value = metadata["captured_at"]
        try:
            if not isinstance(value, str) or len(value) < 10 or date.fromisoformat(value[:10]).isoformat() != value[:10]:
                raise ValueError("invalid captured_at")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            issues.append("Declared captured_at is invalid; preserve the original date precision.")
    references = []
    if "source_path" in metadata:
        references.append(metadata["source_path"])
    targets = metadata.get("compiled_targets", [])
    if isinstance(targets, list):
        references.extend(targets)
    for value in references:
        if (not isinstance(value, str) or not value
                or ".." in Path(value.replace("\\", "/")).parts
                or _resolve_vault_reference(root, value) is None):
            issues.append(f"Declared local provenance path is unsafe: {value}")
            continue
        candidate = Path(value.replace("\\", "/"))
        if not candidate.is_absolute():
            if candidate.parts and candidate.parts[0].lower() == root.name.lower():
                candidate = Path(*candidate.parts[1:])
            candidate = root / candidate
        if any(part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction())
               for part in (candidate.absolute(), *candidate.absolute().parents)):
            issues.append(f"Declared local provenance path is linked: {value}")
    return issues


def _record_from_dict(row: dict[str, Any]) -> KnowledgeFreshnessRecord:
    """Input: dict row. Output: KnowledgeFreshnessRecord. Normalize one manifest entry."""
    return KnowledgeFreshnessRecord(
        name=str(row.get("name", "")),
        path=str(row.get("path", "")),
        updated_at=str(row.get("updated_at", "")),
        max_age_days=int(row.get("max_age_days", 0)),
    )


def _validate_required_record(record: KnowledgeFreshnessRecord, raw_path: Any) -> None:
    """Input: record and raw path value. Output: None. Validate required manifest fields."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"freshness manifest required entry has empty path: {record.name}")
    try:
        date.fromisoformat(record.updated_at)
    except ValueError as error:
        raise ValueError(f"freshness manifest required entry has invalid updated_at: {record.name}") from error
    if record.max_age_days <= 0:
        raise ValueError(f"freshness manifest required entry has non-positive max_age_days: {record.name}")


def load_freshness_manifest(path: Path, strict: bool = False) -> list[KnowledgeFreshnessRecord]:
    """Input: manifest path. Output: freshness records. Load knowledge freshness settings."""
    if not path.exists():
        raise FileNotFoundError(f"freshness manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"freshness manifest must contain a JSON list: {path}")
    rows = [row for row in payload if isinstance(row, dict)]
    records = [_record_from_dict(row) for row in rows]
    if strict:
        names = {record.name for record in records}
        missing = sorted(REQUIRED_RESEARCH_RUN_MANIFEST_NAMES - names)
        if missing:
            raise ValueError(f"freshness manifest missing required entries: {', '.join(missing)}")
        for row, record in zip(rows, records):
            if record.name in REQUIRED_RESEARCH_RUN_MANIFEST_NAMES:
                _validate_required_record(record, row.get("path"))
    return records


def evaluate_freshness(
    records: list[KnowledgeFreshnessRecord],
    today: date,
    artifact_root: Path | None = None,
) -> list[KnowledgeFreshnessStatus]:
    """Input: records and current date. Output: statuses. Mark stale knowledge artifacts."""
    statuses: list[KnowledgeFreshnessStatus] = []
    receipt = None
    if artifact_root is not None and any(row.name in {"operator_ledger", "template_library"} for row in records):
        from wqb.semantic_publication import read_semantic_release

        receipt = read_semantic_release(artifact_root)
    for record in records:
        semantic = receipt is not None and receipt["release_id"] is not None and record.name in receipt["paths"]
        updated_at = receipt["generated_at"][:10] if semantic else record.updated_at
        updated = date.fromisoformat(updated_at)
        age_days = (today - updated).days
        artifact_exists = True
        if artifact_root is not None:
            artifact_path = Path(receipt["paths"][record.name] if semantic else record.path)
            if not artifact_path.is_absolute():
                if artifact_path.parts and artifact_path.parts[0].lower() == artifact_root.name.lower():
                    artifact_path = artifact_root.parent / artifact_path
                else:
                    artifact_path = artifact_root / artifact_path
            artifact_exists = artifact_path.exists()
        statuses.append(
            KnowledgeFreshnessStatus(
                name=record.name,
                path=receipt["paths"][record.name] if semantic else record.path,
                updated_at=updated_at,
                max_age_days=record.max_age_days,
                age_days=age_days,
                stale=age_days > record.max_age_days or not artifact_exists,
                artifact_exists=artifact_exists,
            )
        )
    return statuses


def evaluate_knowledge_contract_health(knowledge_root: str | Path) -> dict[str, Any]:
    """Input: vault root. Output: health dict. Validate canonical raw/wiki contracts."""
    root = Path(knowledge_root)
    issues: list[KnowledgeHealthIssue] = []
    warnings: list[KnowledgeHealthIssue] = []
    legacy_count = 0
    raw_root = root / "raw"
    wiki_root = root / "wiki"
    source_index = raw_root / "source_index.md"
    from wqb.semantic_publication import read_semantic_release

    selected_resources: set[Path] = set()
    try:
        receipt = read_semantic_release(root)
        if receipt["release_id"] is not None:
            selected_resources = {Path(path).resolve() for path in receipt["paths"].values()}
    except (OSError, ValueError):
        # The clean-structure evaluator below reports corrupt publication evidence.
        pass
    raw_paths = [
        path
        for path in (sorted(raw_root.rglob("*.md")) if raw_root.exists() else [])
        if path != source_index
    ]
    wiki_references: set[str] = set()
    for path in sorted(wiki_root.rglob("*.md")) if wiki_root.exists() else []:
        metadata, _ = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
        compiled_from = metadata.get("compiled_from", [])
        if isinstance(compiled_from, list):
            for value in compiled_from:
                resolved = _resolve_vault_reference(root, str(value))
                if resolved is None or not resolved.is_file():
                    issues.append(
                        KnowledgeHealthIssue(
                            code="wiki_backlink_missing",
                            path=str(path),
                            message=f"compiled_from target does not exist: {value}",
                            action="Restore the canonical raw source or correct the compiled_from backlink.",
                        )
                    )
                    continue
                family = canonical_source_family(resolved, root)
                if not (family.startswith("raw/") or family.startswith("machine/") or resolved in selected_resources):
                    issues.append(
                        KnowledgeHealthIssue(
                            code="wiki_backlink_not_source_authority",
                            path=str(path),
                            message=f"compiled_from target is not raw or machine source authority: {value}",
                            action="Replace the backlink with direct provenance under raw or machine.",
                        )
                    )
                    continue
                relative = _vault_relative(resolved, root)
                wiki_references.add(relative)
        for issue in validate_wiki_metadata(path):
            issues.append(
                KnowledgeHealthIssue(
                    code="wiki_metadata_missing",
                    path=str(path),
                    message=issue,
                    action="Add compiled_from, trust, stale policy, update trigger, and consumed_by metadata.",
                )
            )
    index_text = source_index.read_text(encoding="utf-8") if source_index.exists() else ""
    raw_metadata: dict[Path, dict[str, Any]] = {}
    excerpt_paths: list[str] = []
    for path in raw_paths:
        if (not path.resolve().is_relative_to(root.resolve())
                or any(part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction())
                       for part in (path.absolute(), *path.absolute().parents))):
            issues.append(KnowledgeHealthIssue(
                code="raw_source_path_unsafe", path=str(path),
                message="Raw source path escapes the vault or traverses a link.",
                action="Restore an unlinked canonical source path before using this source.",
            ))
            continue
        try:
            metadata, _ = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as error:
            issues.append(KnowledgeHealthIssue(
                code="raw_source_unreadable", path=str(path), message=str(error),
                action="Restore readable original source evidence before using this source.",
            ))
            continue
        raw_metadata[path] = metadata
        if (metadata.get("content_status") == "verified_raw_extract"
                or path.name.startswith("semantic-subset-")
                or any(key in metadata for key in ("extraction_receipt", "original_source_path", "original_sha256"))
                or metadata.get("capture_tool") == "knowledge_contracts.extract_field_source_subset"):
            excerpt_paths.append(path.relative_to(root).as_posix())
    verification_session = verify_field_source_extracts(root, excerpt_paths) if excerpt_paths else None
    for path, metadata in raw_metadata.items():
        local_note = _is_local_design_note(path, root, metadata)
        housekeeping = warnings if local_note else issues
        if local_note:
            captured_on = metadata.get("captured_on")
            try:
                if not isinstance(captured_on, str) or date.fromisoformat(captured_on).isoformat() != captured_on:
                    raise ValueError("invalid captured_on")
            except ValueError:
                issues.append(KnowledgeHealthIssue(
                    code="user_note_date_invalid", path=str(path),
                    message="Local design note requires a valid captured_on in YYYY-MM-DD precision.",
                    action="Recover the original note date; do not invent a capture timestamp.",
                ))
            for message in _user_note_provenance_issues(metadata, root):
                issues.append(KnowledgeHealthIssue(
                    code="user_note_provenance_invalid", path=str(path), message=message,
                    action="Correct declared provenance from original evidence; do not fabricate capture metadata.",
                ))
        family = canonical_source_family(path, root)
        if family == "legacy":
            legacy_count += 1
            issues.append(
                KnowledgeHealthIssue(
                    code="legacy_path",
                    path=str(path),
                    message="Raw source is outside the canonical raw tree.",
                    action="Migrate the file into raw/platform, raw/community, or raw/research before using it as an active source.",
                )
            )
        for issue in validate_raw_metadata(path, _verification_session=verification_session):
            target = housekeeping if issue in USER_NOTE_HOUSEKEEPING_MESSAGES else issues
            target.append(
                KnowledgeHealthIssue(
                    code="raw_metadata_missing",
                    path=str(path),
                    message=issue,
                    action=("Document local note housekeeping without inventing capture times or tools."
                            if local_note and target is warnings
                            else "Add raw source metadata or mark the source as migration-only."),
                )
            )
        relative = _vault_relative(path, root)
        indexed = relative in index_text
        if not indexed:
            housekeeping.append(
                KnowledgeHealthIssue(
                    code="source_index_coverage_missing",
                    path=str(path),
                    message="Canonical raw source is missing from raw/source_index.md.",
                    action="Regenerate the source index with this canonical raw source.",
                )
            )
        if not indexed and relative not in wiki_references:
            housekeeping.append(
                KnowledgeHealthIssue(
                    code="orphan_raw_source",
                    path=str(path),
                    message="Canonical raw source is not referenced by wiki compiled_from metadata or the source index.",
                    action="Index the raw source and compile it into a wiki target, or mark it as migration-only.",
                )
            )
    if verification_session is not None:
        try:
            verification_session.finalize()
        except (OSError, ValueError) as error:
            issues.append(KnowledgeHealthIssue(
                code="raw_extract_verification_changed", path=str(raw_root), message=str(error),
                action="Recheck unchanged original captures, excerpts, indexes and receipts before using their evidence.",
            ))
    clean_report = evaluate_clean_knowledge_structure(root)
    for issue in clean_report["issues"]:
        issues.append(
            KnowledgeHealthIssue(
                code=str(issue["code"]),
                path=str(issue["path"]),
                message=str(issue["message"]),
                action=str(issue["action"]),
            )
        )
    return {
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "legacy_count": legacy_count,
        "raw_source_count": len(raw_paths),
        "wiki_page_count": len(list(wiki_root.rglob("*.md"))) if wiki_root.exists() else 0,
        "clean_structure": clean_report["clean"],
        "clean_structure_issue_count": clean_report["issue_count"],
        "issues": [asdict(issue) for issue in issues],
        "warnings": [asdict(issue) for issue in warnings],
    }


def write_freshness_report(path: Path, statuses: list[KnowledgeFreshnessStatus], generated_at: str) -> Path:
    """Input: output path, statuses, timestamp. Output: path. Write a Markdown knowledge freshness report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Knowledge Freshness Report",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "| Name | Status | Age Days | Max Age Days | Path |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for status in statuses:
        label = "missing" if not status.artifact_exists else "stale" if status.stale else "fresh"
        lines.append(f"| {status.name} | {label} | {status.age_days} | {status.max_age_days} | `{status.path}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
