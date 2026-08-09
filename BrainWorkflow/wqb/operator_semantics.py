from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_paths import existing_machine_resource_path, machine_resource_path


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


def default_operator_semantics() -> list[OperatorSemanticRecord]:
    """Input: none. Output: default records. Seed missing workflow semantics without replacing reviewed rows."""
    return [
        OperatorSemanticRecord(
            operator="rank",
            family="cross_sectional_normalizer",
            workflow_uses=["normalize_cross_section", "reduce_scale_dependency"],
            compatible_field_types=["MATRIX"],
            template_tags=["cross_sectional_normalizer"],
            risk_tags=["crowded_when_used_on_price_volume_only"],
            repair_levers=["group_rank", "group_neutralize"],
            source_paths=["wiki/20_semantics/operator_catalog_official.md"],
        ),
        OperatorSemanticRecord(
            operator="ts_delta",
            family="time_series_change",
            workflow_uses=["capture_recent_change", "event_surprise"],
            compatible_field_types=["MATRIX"],
            template_tags=["time_series_surprise", "event"],
            risk_tags=["turnover_inflation"],
            repair_levers=["increase_window", "add_decay"],
            source_paths=["wiki/20_semantics/operator_catalog_official.md"],
        ),
        OperatorSemanticRecord(
            operator="vec_avg",
            family="vector_to_matrix",
            workflow_uses=["summarize_vector_values"],
            compatible_field_types=["VECTOR"],
            template_tags=["event_value", "vector_to_matrix"],
            risk_tags=["invalid_raw_vector_use"],
            repair_levers=["replace_vec_count_with_vec_avg"],
            source_paths=["wiki/20_semantics/operators.md"],
        ),
    ]


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


def _canonical_operator_rows(knowledge_root: Path) -> list[tuple[dict[str, Any], str]]:
    """Input: vault root. Output: operator rows and source paths. Read canonical structured operator captures."""
    capture_root = knowledge_root / "raw" / "platform" / "data_fields"
    rows: list[tuple[dict[str, Any], str]] = []
    for path in sorted(capture_root.glob("*/operators.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        operators = payload.get("operators", []) if isinstance(payload, dict) else []
        if not isinstance(operators, list):
            continue
        source_path = path.relative_to(knowledge_root).as_posix()
        rows.extend((row, source_path) for row in operators if isinstance(row, dict))
    return rows


def _record_from_canonical_operator(row: dict[str, Any], source_path: str) -> OperatorSemanticRecord | None:
    """Input: canonical operator row and path. Output: semantic record or none. Compile conservative source semantics."""
    operator = str(row.get("name", row.get("operator", row.get("id", "")))).strip()
    if not operator:
        return None
    return OperatorSemanticRecord(
        operator=operator,
        family=str(row.get("category", row.get("family", "unclassified"))) or "unclassified",
        workflow_uses=normalize_string_list(row.get("workflow_uses")),
        compatible_field_types=normalize_string_list(row.get("compatible_field_types"), uppercase=True),
        template_tags=normalize_string_list(row.get("template_tags")),
        risk_tags=normalize_string_list(row.get("risk_tags")),
        repair_levers=normalize_string_list(row.get("repair_levers")),
        source_paths=[source_path],
    )


def compile_operator_semantics(
    knowledge_root: str | Path, generated_at: str
) -> dict[str, Any]:
    """Input: vault root and timestamp. Output: compile summary. Merge canonical operators, seeds, and reviewed records."""
    root = Path(knowledge_root)
    jsonl_path = machine_resource_path(root, "operator_ledger")
    markdown_path = root / "machine" / "previews" / "operator_semantics.md"
    by_operator = {record.operator: record for record in default_operator_semantics()}
    for row, source_path in _canonical_operator_rows(root):
        record = _record_from_canonical_operator(row, source_path)
        if record is not None and record.operator not in by_operator:
            by_operator[record.operator] = record
    reviewed = load_operator_semantics(existing_machine_resource_path(root, "operator_ledger"))
    for record in reviewed:
        by_operator[record.operator] = record
    records = list(by_operator.values())
    write_operator_semantics_jsonl(jsonl_path, records)
    write_operator_semantics_markdown(markdown_path, records, generated_at)
    return {
        "record_count": len(records),
        "reviewed_record_count": len(reviewed),
        "jsonl_path": str(jsonl_path),
        "markdown_path": str(markdown_path),
    }
