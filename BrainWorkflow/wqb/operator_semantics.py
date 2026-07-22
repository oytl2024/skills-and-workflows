from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


FIELD_TYPE_BONUS = 3.0
TAG_MATCH_BONUS = 0.8
RISK_PENALTY = 0.4


@dataclass(frozen=True)
class OperatorSemanticRecord:
    operator: str
    family: str
    workflow_uses: list[str]
    compatible_field_types: list[str]
    template_tags: list[str]
    risk_tags: list[str]
    repair_levers: list[str]
    source_paths: list[str]


def normalize_string_list(value: Any, *, uppercase: bool = False) -> list[str]:
    """Input: None, string, or list value. Output: normalized string list. Preserve scalar strings as one item."""
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list):
        raise ValueError("operator semantic list fields must be lists, strings, or None")
    normalized = [str(item) for item in values if str(item)]
    return [item.upper() for item in normalized] if uppercase else normalized


def operator_semantic_record_from_dict(row: dict[str, Any]) -> OperatorSemanticRecord:
    """Input: dict row. Output: OperatorSemanticRecord. Normalize one operator semantic row."""
    return OperatorSemanticRecord(
        operator=str(row.get("operator", "")),
        family=str(row.get("family", "")),
        workflow_uses=normalize_string_list(row.get("workflow_uses")),
        compatible_field_types=normalize_string_list(row.get("compatible_field_types"), uppercase=True),
        template_tags=normalize_string_list(row.get("template_tags")),
        risk_tags=normalize_string_list(row.get("risk_tags")),
        repair_levers=normalize_string_list(row.get("repair_levers")),
        source_paths=normalize_string_list(row.get("source_paths")),
    )


def operator_semantic_record_to_dict(record: OperatorSemanticRecord) -> dict[str, Any]:
    """Input: OperatorSemanticRecord. Output: dict. Convert a record to JSON-safe data."""
    return asdict(record)


def load_operator_semantics(path: Path) -> list[OperatorSemanticRecord]:
    """Input: JSONL path. Output: operator semantic records. Load operator workflow meanings."""
    if not path.exists():
        return []
    records: list[OperatorSemanticRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(operator_semantic_record_from_dict(json.loads(line)))
    return records


def write_operator_semantics_jsonl(path: Path, records: list[OperatorSemanticRecord]) -> Path:
    """Input: path and records. Output: path. Write operator semantics as deterministic JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in sorted(records, key=lambda item: item.operator):
            handle.write(json.dumps(operator_semantic_record_to_dict(record), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def write_operator_semantics_markdown(path: Path, records: list[OperatorSemanticRecord], generated_at: str) -> Path:
    """Input: path, records, timestamp. Output: path. Write human-readable operator semantics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Operator Semantics",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "| Operator | Family | Workflow Uses | Field Types | Template Tags | Risks | Repair Levers | Sources |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in sorted(records, key=lambda item: item.operator):
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                record.operator,
                record.family,
                ", ".join(record.workflow_uses),
                ", ".join(record.compatible_field_types),
                ", ".join(record.template_tags),
                ", ".join(record.risk_tags),
                ", ".join(record.repair_levers),
                ", ".join(record.source_paths),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def score_operator_for_template(record: OperatorSemanticRecord, field_type: str, template_tags: list[str]) -> float:
    """Input: operator record, field type, template tags. Output: score. Rank operator fit for template work."""
    score = 0.0
    if field_type.upper() in {item.upper() for item in record.compatible_field_types}:
        score += FIELD_TYPE_BONUS
    else:
        score -= FIELD_TYPE_BONUS
    shared = {item.lower() for item in template_tags} & {item.lower() for item in record.template_tags}
    score += len(shared) * TAG_MATCH_BONUS
    score -= len(record.risk_tags) * RISK_PENALTY
    return round(score, 4)
