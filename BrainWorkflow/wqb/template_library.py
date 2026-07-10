from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from wqb.data_ledger import DataLedgerRecord


FIELD_TYPE_MATCH_BONUS = 3.0
TAG_MATCH_BONUS = 0.8
INCENTIVE_TAG_BONUS = 1.5
LOW_RISK_BONUS = 1.5
MEDIUM_RISK_BONUS = 0.3
HIGH_RISK_PENALTY = 2.0
STATUS_SCORES = {
    "submit_proven": 2.0,
    "discovery_ready": 1.5,
    "seed": 1.0,
    "scout_only": 0.2,
    "repair_only": -0.5,
    "deprecated": -4.0,
}


@dataclass(frozen=True)
class TemplateRecord:
    template_id: str
    hypothesis: str
    skeleton: str
    required_field_types: list[str]
    compatible_semantic_tags: list[str]
    operator_tags: list[str]
    status: str
    correlation_risk: str
    repair_levers: list[str]
    source_paths: list[str]


def template_record_to_dict(record: TemplateRecord) -> dict[str, Any]:
    """Input: TemplateRecord. Output: dict[str, Any]. Convert template record to JSON-safe data."""
    return asdict(record)


def _template_from_dict(row: dict[str, Any]) -> TemplateRecord:
    """Input: dict row. Output: TemplateRecord. Normalize one JSONL row from the template library."""
    return TemplateRecord(
        template_id=str(row.get("template_id", "")),
        hypothesis=str(row.get("hypothesis", "")),
        skeleton=str(row.get("skeleton", "")),
        required_field_types=[str(item).upper() for item in row.get("required_field_types", []) if str(item)],
        compatible_semantic_tags=[str(item) for item in row.get("compatible_semantic_tags", []) if str(item)],
        operator_tags=[str(item) for item in row.get("operator_tags", []) if str(item)],
        status=str(row.get("status", "scout_only")),
        correlation_risk=str(row.get("correlation_risk", "unknown")),
        repair_levers=[str(item) for item in row.get("repair_levers", []) if str(item)],
        source_paths=[str(item) for item in row.get("source_paths", []) if str(item)],
    )


def load_template_library(path: Path) -> list[TemplateRecord]:
    """Input: JSONL path. Output: TemplateRecord list. Load strategy template memory from disk."""
    if not path.exists():
        return []
    records: list[TemplateRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(_template_from_dict(json.loads(line)))
    return records


def score_template_for_data(template: TemplateRecord, data_record: DataLedgerRecord, incentive: str) -> float:
    """Input: template, data record, incentive. Output: float score. Rank template fit for a field."""
    score = STATUS_SCORES.get(template.status, 0.0)
    if data_record.field_type.upper() in {item.upper() for item in template.required_field_types}:
        score += FIELD_TYPE_MATCH_BONUS
    else:
        score -= FIELD_TYPE_MATCH_BONUS
    data_tags = {tag.lower() for tag in data_record.semantic_tags}
    template_tags = {tag.lower() for tag in template.compatible_semantic_tags}
    score += len(data_tags & template_tags) * TAG_MATCH_BONUS
    if incentive.lower() in template_tags or incentive.lower() in data_tags:
        score += INCENTIVE_TAG_BONUS
    risk = template.correlation_risk.lower()
    if risk == "low":
        score += LOW_RISK_BONUS
    elif risk == "medium":
        score += MEDIUM_RISK_BONUS
    elif risk == "high":
        score -= HIGH_RISK_PENALTY
    return round(score, 4)


def select_templates_for_data(
    templates: list[TemplateRecord],
    data_record: DataLedgerRecord,
    incentive: str,
    limit: int,
) -> list[TemplateRecord]:
    """Input: templates, data record, incentive, limit. Output: ranked templates. Select template candidates."""
    scored = sorted(
        templates,
        key=lambda item: (score_template_for_data(item, data_record, incentive), item.template_id),
        reverse=True,
    )
    return scored[: max(int(limit), 0)]


def write_template_library_markdown(path: Path, templates: list[TemplateRecord], generated_at: str) -> Path:
    """Input: output path, templates, timestamp. Output: path. Write reviewable Markdown template library."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Template Library",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "| Template | Status | Hypothesis | Field Types | Tags | Risk |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for template in templates:
        field_types = ", ".join(template.required_field_types)
        tags = ", ".join(template.compatible_semantic_tags)
        lines.append(
            f"| `{template.template_id}` | {template.status} | {template.hypothesis} | {field_types} | {tags} | {template.correlation_risk} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
