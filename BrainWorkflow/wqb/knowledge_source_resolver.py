from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_paths import existing_machine_resource_path


@dataclass(frozen=True)
class SourceSelection:
    """Input: selected source rows. Output: immutable source selection. Carry provenance into runs."""

    fields: list[dict[str, Any]]
    field_source: str
    operator_source: str
    template_source: str
    provenance: list[dict[str, Any]]
    blockers: list[str]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: object rows. Read machine ledger rows safely."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _matches_scope(row: dict[str, Any], config: dict[str, Any]) -> bool:
    """Input: ledger row and config. Output: bool. Match instrument, region, delay, and universe."""
    return (
        str(row.get("instrument_type", "")).upper() == str(config.get("instrument_type", "")).upper()
        and str(row.get("region", "")).upper() == str(config.get("region", "")).upper()
        and str(row.get("delay", "")) == str(config.get("delay", ""))
        and str(row.get("universe", "")).upper() == str(config.get("universe", "")).upper()
    )


def _field_from_ledger(row: dict[str, Any]) -> dict[str, Any]:
    """Input: data ledger row. Output: field row. Convert machine ledger data to field-batch shape."""
    return {
        "id": str(row.get("field_id", "")),
        "type": str(row.get("field_type", "")),
        "coverage": row.get("coverage", 0),
        "dataset": {"id": row.get("dataset_id", ""), "name": row.get("dataset_name", "")},
        "description": row.get("field_description", ""),
    }


def resolve_source_inputs(
    knowledge_root: str | Path,
    config: dict[str, Any],
    field_search: str = "",
    dataset_id: str = "",
    exact_field_id: str = "",
    allow_live_fallback: bool = True,
    max_fields: int = 50,
) -> SourceSelection:
    """Input: vault root, config, filters, fallback flag. Output: source selection. Prefer knowledge ledgers over live API."""
    root = Path(knowledge_root)
    rows = _read_jsonl(existing_machine_resource_path(root, "data_ledger"))
    operators = _read_jsonl(existing_machine_resource_path(root, "operator_ledger"))
    templates = _read_jsonl(existing_machine_resource_path(root, "template_library"))
    search = str(field_search).lower().strip()
    exact = str(exact_field_id).strip()
    dataset = str(dataset_id).strip()
    matching: list[dict[str, Any]] = []
    for row in rows:
        field_id = str(row.get("field_id", ""))
        if not field_id or not _matches_scope(row, config):
            continue
        if dataset and str(row.get("dataset_id", "")) != dataset:
            continue
        if exact and field_id != exact:
            continue
        if search and search not in field_id.lower() and search not in str(row.get("field_description", "")).lower():
            continue
        if str(row.get("source_quality", "")) != "platform_raw_capture":
            continue
        matching.append(row)
    matching.sort(key=lambda row: float(row.get("coverage", 0) or 0), reverse=True)
    selected = matching[: max(0, int(max_fields))]
    if not selected:
        source = "live_api" if allow_live_fallback else "missing"
        return SourceSelection(
            [],
            source,
            "knowledge" if operators else "missing",
            "template_library" if templates else "missing",
            [],
            ["knowledge_field_coverage_missing"],
        )
    provenance = [
        {
            "field_id": row.get("field_id", ""),
            "source_paths": list(row.get("source_paths", [])),
            "source_quality": row.get("source_quality", ""),
            "source_updated_at": row.get("source_updated_at", ""),
            "region": row.get("region", ""),
            "delay": row.get("delay", ""),
            "universe": row.get("universe", ""),
        }
        for row in selected
    ]
    return SourceSelection(
        [_field_from_ledger(row) for row in selected],
        "knowledge",
        "knowledge" if operators else "missing",
        "template_library" if templates else "missing",
        provenance,
        [],
    )
