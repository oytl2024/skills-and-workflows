from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from wqb.data_ledger import DataLedgerRecord
from wqb.knowledge_paths import existing_machine_resource_path


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
    compatible_regions: list[str] = field(default_factory=list)
    compatible_delays: list[int] = field(default_factory=list)
    compatible_universes: list[str] = field(default_factory=list)
    suitable_horizons: list[str] = field(default_factory=list)
    neutralization_styles: list[str] = field(default_factory=list)
    turnover_bucket: str = ""
    local_gates: list[str] = field(default_factory=list)
    experiment_paths: list[str] = field(default_factory=list)
    intended_direction: str = ""
    interpretation: str = ""
    decay: str = ""
    known_antipatterns: list[str] = field(default_factory=list)
    crowded_variants: list[str] = field(default_factory=list)
    data_semantics: list[str] = field(default_factory=list)
    economic_hypothesis: str = ""
    operator_composition: list[str] = field(default_factory=list)
    abandon_conditions: list[str] = field(default_factory=list)
    benchmark_rule_ids: list[str] = field(default_factory=list)
    template_family: str = ""


def template_record_to_dict(record: TemplateRecord) -> dict[str, Any]:
    """Input: TemplateRecord. Output: dict[str, Any]. Convert template record to JSON-safe data."""
    return asdict(record)


def template_record_from_dict(row: dict[str, Any]) -> TemplateRecord:
    """Input: dict row. Output: TemplateRecord. Normalize one JSON-safe template row."""
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
        compatible_regions=[str(item) for item in row.get("compatible_regions", []) if str(item)],
        compatible_delays=[int(item) for item in row.get("compatible_delays", [])],
        compatible_universes=[str(item) for item in row.get("compatible_universes", []) if str(item)],
        suitable_horizons=[str(item) for item in row.get("suitable_horizons", []) if str(item)],
        neutralization_styles=[str(item) for item in row.get("neutralization_styles", []) if str(item)],
        turnover_bucket=str(row.get("turnover_bucket", "")),
        local_gates=[str(item) for item in row.get("local_gates", []) if str(item)],
        experiment_paths=[str(item) for item in row.get("experiment_paths", []) if str(item)],
        intended_direction=str(row.get("intended_direction", "")),
        interpretation=str(row.get("interpretation", "")),
        decay=str(row.get("decay", "")),
        known_antipatterns=[str(item) for item in row.get("known_antipatterns", []) if str(item)],
        crowded_variants=[str(item) for item in row.get("crowded_variants", []) if str(item)],
        data_semantics=[str(item) for item in row.get("data_semantics", []) if str(item)],
        economic_hypothesis=str(row.get("economic_hypothesis", row.get("hypothesis", ""))),
        operator_composition=[str(item) for item in row.get("operator_composition", []) if str(item)],
        abandon_conditions=[str(item) for item in row.get("abandon_conditions", []) if str(item)],
        benchmark_rule_ids=[str(item) for item in row.get("benchmark_rule_ids", []) if str(item)],
        template_family=str(row.get("template_family", "")),
    )


def _template_from_dict(row: dict[str, Any]) -> TemplateRecord:
    """Input: dict row. Output: TemplateRecord. Keep the legacy private loader adapter."""
    return template_record_from_dict(row)


def load_template_library(path: Path) -> list[TemplateRecord]:
    """Input: JSONL path. Output: TemplateRecord list. Load strategy template memory from disk."""
    if not path.exists():
        return []
    records: list[TemplateRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(_template_from_dict(json.loads(line)))
    return records


def template_library_path_for_knowledge(knowledge_root: str | Path) -> Path:
    """Input: knowledge root. Output: Path. Return the current template-library authority path."""
    return existing_machine_resource_path(knowledge_root, "template_library")


def load_template_library_from_knowledge(knowledge_root: str | Path) -> list[TemplateRecord]:
    """Input: knowledge root. Output: TemplateRecord list. Load canonical template records with legacy fallback."""
    return load_template_library(template_library_path_for_knowledge(knowledge_root))


def template_matrix_ready(template: TemplateRecord) -> bool:
    """Input: template record. Output: bool. Check whether template has the full matrix fields."""
    correlation_risk = template.correlation_risk.strip().lower()
    return all(
        [
            bool(template.data_semantics),
            bool(template.economic_hypothesis),
            bool(template.required_field_types),
            bool(template.compatible_semantic_tags),
            bool(template.operator_tags),
            bool(template.compatible_regions),
            bool(template.compatible_delays),
            bool(template.compatible_universes),
            bool(template.suitable_horizons),
            bool(template.neutralization_styles),
            bool(template.turnover_bucket),
            bool(template.local_gates),
            bool(template.experiment_paths),
            bool(template.intended_direction),
            bool(template.interpretation),
            bool(template.decay),
            bool(template.operator_composition),
            bool(template.source_paths),
            bool(template.repair_levers),
            bool(template.abandon_conditions),
            bool(template.template_family),
            correlation_risk not in {"", "unknown", "unclassified", "none", "n/a", "not_applicable"},
        ]
    )


def template_matrix_summary(templates: list[TemplateRecord]) -> dict[str, Any]:
    """Input: templates. Output: summary dict. Count matrix readiness."""
    ready = [template for template in templates if template_matrix_ready(template)]
    return {
        "template_count": len(templates),
        "matrix_ready_count": len(ready),
        "seed_only_count": len(templates) - len(ready),
    }


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
    if template_matrix_ready(template):
        score += 1.0
    return round(score, 4)


def select_templates_for_data(
    templates: list[TemplateRecord],
    data_record: DataLedgerRecord,
    incentive: str,
    limit: int,
    region: str | None = None,
    delay: int | None = None,
    universe: str | None = None,
) -> list[TemplateRecord]:
    """Input: templates, data record, incentive, limit. Output: ranked templates. Select template candidates."""
    field_type = data_record.field_type.upper()
    selected_region = region if region is not None else data_record.region
    selected_delay = delay if delay is not None else data_record.delay
    selected_universe = universe if universe is not None else data_record.universe
    eligible = [
        template
        for template in templates
        if template.status.lower() != "deprecated"
        and (not template.required_field_types or field_type in {item.upper() for item in template.required_field_types})
        and (not template.compatible_regions or selected_region.upper() in {item.upper() for item in template.compatible_regions})
        and (not template.compatible_delays or int(selected_delay) in set(template.compatible_delays))
        and (not template.compatible_universes or selected_universe.upper() in {item.upper() for item in template.compatible_universes})
    ]
    scored = sorted(
        eligible,
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
        "| Template | Family | Status | Matrix Ready | Hypothesis | Field Types | Tags | Risk |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for template in templates:
        field_types = ", ".join(template.required_field_types)
        tags = ", ".join(template.compatible_semantic_tags)
        ready = "yes" if template_matrix_ready(template) else "no"
        lines.append(
            f"| `{template.template_id}` | {template.template_family} | {template.status} | {ready} | {template.hypothesis} | {field_types} | {tags} | {template.correlation_risk} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
