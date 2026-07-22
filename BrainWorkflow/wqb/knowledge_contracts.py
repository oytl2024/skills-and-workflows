from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


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
)

WIKI_CANONICAL_PREFIXES = (
    "wiki/00_principles",
    "wiki/10_foundations",
    "wiki/20_semantics",
    "wiki/30_templates",
    "wiki/40_experiments",
    "wiki/50_benchmarks",
    "wiki/60_workflows",
    "wiki/70_decisions",
    "wiki/80_maintenance",
    "wiki/90_index",
)

RAW_REQUIRED_FIELDS = (
    "source_type",
    "source_family",
    "source_path",
    "captured_at",
    "capture_tool",
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
    compiled_targets: list[str]


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


def update_source_index(knowledge_root: str | Path, rows: list[SourceIndexRow]) -> Path:
    """Input: vault root and rows. Output: source index path. Write the raw source inventory."""
    root = Path(knowledge_root)
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
                f"- Update Check: {row.update_check}",
                "- Compiled Targets:",
                *[f"  - `{target}`" for target in row.compiled_targets],
                "",
            ]
        )
    output.write_text("\n".join(lines), encoding="utf-8")
    return output
