from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any


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


def _record_from_dict(row: dict[str, Any]) -> KnowledgeFreshnessRecord:
    """Input: dict row. Output: KnowledgeFreshnessRecord. Normalize one manifest entry."""
    return KnowledgeFreshnessRecord(
        name=str(row.get("name", "")),
        path=str(row.get("path", "")),
        updated_at=str(row.get("updated_at", "")),
        max_age_days=int(row.get("max_age_days", 0)),
    )


def load_freshness_manifest(path: Path) -> list[KnowledgeFreshnessRecord]:
    """Input: manifest path. Output: freshness records. Load knowledge freshness settings."""
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [_record_from_dict(row) for row in payload if isinstance(row, dict)]


def evaluate_freshness(records: list[KnowledgeFreshnessRecord], today: date) -> list[KnowledgeFreshnessStatus]:
    """Input: records and current date. Output: statuses. Mark stale knowledge artifacts."""
    statuses: list[KnowledgeFreshnessStatus] = []
    for record in records:
        updated = date.fromisoformat(record.updated_at)
        age_days = (today - updated).days
        statuses.append(
            KnowledgeFreshnessStatus(
                name=record.name,
                path=record.path,
                updated_at=record.updated_at,
                max_age_days=record.max_age_days,
                age_days=age_days,
                stale=age_days > record.max_age_days,
            )
        )
    return statuses


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
        label = "stale" if status.stale else "fresh"
        lines.append(f"| {status.name} | {label} | {status.age_days} | {status.max_age_days} | `{status.path}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
