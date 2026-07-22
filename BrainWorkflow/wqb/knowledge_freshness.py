from dataclasses import asdict, dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_contracts import (
    canonical_source_family,
    parse_markdown_front_matter,
    validate_raw_metadata,
    validate_wiki_metadata,
)


REQUIRED_RESEARCH_RUN_MANIFEST_NAMES = {
    "data_ledger",
    "template_library",
    "benchmark_rules",
    "activity_snapshot",
}


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
    for record in records:
        updated = date.fromisoformat(record.updated_at)
        age_days = (today - updated).days
        artifact_exists = True
        if artifact_root is not None:
            artifact_path = Path(record.path)
            if not artifact_path.is_absolute():
                if artifact_path.parts and artifact_path.parts[0].lower() == artifact_root.name.lower():
                    artifact_path = artifact_root.parent / artifact_path
                else:
                    artifact_path = artifact_root / artifact_path
            artifact_exists = artifact_path.exists()
        statuses.append(
            KnowledgeFreshnessStatus(
                name=record.name,
                path=record.path,
                updated_at=record.updated_at,
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
    legacy_count = 0
    raw_root = root / "raw"
    wiki_root = root / "wiki"
    source_index = raw_root / "source_index.md"
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
                relative = _vault_relative(resolved, root)
                if not canonical_source_family(resolved, root).startswith("raw/"):
                    issues.append(
                        KnowledgeHealthIssue(
                            code="wiki_backlink_not_raw",
                            path=str(path),
                            message=f"compiled_from target is not a canonical raw source: {value}",
                            action="Replace the backlink with direct provenance under raw/platform, raw/community, or raw/research.",
                        )
                    )
                    continue
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
    for path in raw_paths:
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
        for issue in validate_raw_metadata(path):
            issues.append(
                KnowledgeHealthIssue(
                    code="raw_metadata_missing",
                    path=str(path),
                    message=issue,
                    action="Add raw source metadata or mark the source as migration-only.",
                )
            )
        relative = _vault_relative(path, root)
        indexed = relative in index_text
        if not indexed:
            issues.append(
                KnowledgeHealthIssue(
                    code="source_index_coverage_missing",
                    path=str(path),
                    message="Canonical raw source is missing from raw/source_index.md.",
                    action="Regenerate the source index with this canonical raw source.",
                )
            )
        if not indexed and relative not in wiki_references:
            issues.append(
                KnowledgeHealthIssue(
                    code="orphan_raw_source",
                    path=str(path),
                    message="Canonical raw source is not referenced by wiki compiled_from metadata or the source index.",
                    action="Index the raw source and compile it into a wiki target, or mark it as migration-only.",
                )
            )
    return {
        "issue_count": len(issues),
        "legacy_count": legacy_count,
        "raw_source_count": len(raw_paths),
        "wiki_page_count": len(list(wiki_root.rglob("*.md"))) if wiki_root.exists() else 0,
        "issues": [asdict(issue) for issue in issues],
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
