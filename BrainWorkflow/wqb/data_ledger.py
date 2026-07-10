from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


LOW_RISK_BONUS = 1.5
MEDIUM_RISK_BONUS = 0.3
HIGH_RISK_PENALTY = 2.5
MATCHING_SCOPE_BONUS = 2.0
INCENTIVE_TAG_BONUS = 2.0
UNDERUSED_BONUS = 2.0
SUBMITTED_USAGE_PENALTY = 1.5
SIM_USAGE_PENALTY = 0.08
REPAIRABLE_SIGNAL_BONUS = 1.0
PROD_CORR_PENALTY = 2.0


@dataclass(frozen=True)
class DataLedgerRecord:
    dataset_id: str
    dataset_name: str
    field_id: str
    field_type: str
    region: str
    delay: int
    universe: str
    semantic_tags: list[str]
    coverage: float
    alpha_count: int
    user_count: int
    simulation_usage_count: int
    submitted_usage_count: int
    last_used_at: str
    best_result_label: str
    correlation_risk: str
    source_paths: list[str]
    available_regions: list[str] = field(default_factory=list)
    available_delays: list[int] = field(default_factory=list)
    available_universes: list[str] = field(default_factory=list)
    activity_tags: list[str] = field(default_factory=list)
    compatible_template_ids: list[str] = field(default_factory=list)
    gate_requirements: list[str] = field(default_factory=list)
    experiment_paths: list[str] = field(default_factory=list)


def data_ledger_record_to_dict(record: DataLedgerRecord) -> dict[str, Any]:
    """Input: DataLedgerRecord. Output: dict[str, Any]. Convert ledger record to JSON-safe data."""
    return asdict(record)


def _record_from_dict(row: dict[str, Any]) -> DataLedgerRecord:
    """Input: dict row. Output: DataLedgerRecord. Normalize one JSONL row from the data ledger."""
    return DataLedgerRecord(
        dataset_id=str(row.get("dataset_id", "")),
        dataset_name=str(row.get("dataset_name", "")),
        field_id=str(row.get("field_id", "")),
        field_type=str(row.get("field_type", "")),
        region=str(row.get("region", "")),
        delay=int(row.get("delay", 0)),
        universe=str(row.get("universe", "")),
        semantic_tags=[str(item) for item in row.get("semantic_tags", []) if str(item)],
        coverage=float(row.get("coverage", 0.0)),
        alpha_count=int(row.get("alpha_count", 0)),
        user_count=int(row.get("user_count", 0)),
        simulation_usage_count=int(row.get("simulation_usage_count", 0)),
        submitted_usage_count=int(row.get("submitted_usage_count", 0)),
        last_used_at=str(row.get("last_used_at", "")),
        best_result_label=str(row.get("best_result_label", "")),
        correlation_risk=str(row.get("correlation_risk", "unknown")),
        source_paths=[str(item) for item in row.get("source_paths", []) if str(item)],
        available_regions=[str(item) for item in row.get("available_regions", []) if str(item)],
        available_delays=[int(item) for item in row.get("available_delays", [])],
        available_universes=[str(item) for item in row.get("available_universes", []) if str(item)],
        activity_tags=[str(item) for item in row.get("activity_tags", []) if str(item)],
        compatible_template_ids=[str(item) for item in row.get("compatible_template_ids", []) if str(item)],
        gate_requirements=[str(item) for item in row.get("gate_requirements", []) if str(item)],
        experiment_paths=[str(item) for item in row.get("experiment_paths", []) if str(item)],
    )


def load_data_ledger(path: Path) -> list[DataLedgerRecord]:
    """Input: JSONL path. Output: DataLedgerRecord list. Load data scheduling memory from disk."""
    if not path.exists():
        return []
    records: list[DataLedgerRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(_record_from_dict(json.loads(line)))
    return records


def score_data_for_research(record: DataLedgerRecord, incentive: str, region: str, delay: int) -> float:
    """Input: data record, incentive, region, delay. Output: float score. Rank fields for research scheduling."""
    score = float(record.coverage) * 2.0
    if record.region.upper() == region.upper() and int(record.delay) == int(delay):
        score += MATCHING_SCOPE_BONUS
    tags = {tag.lower() for tag in record.semantic_tags}
    if incentive.lower() in tags:
        score += INCENTIVE_TAG_BONUS
    if record.simulation_usage_count == 0 and record.submitted_usage_count == 0:
        score += UNDERUSED_BONUS
    score -= record.submitted_usage_count * SUBMITTED_USAGE_PENALTY
    score -= record.simulation_usage_count * SIM_USAGE_PENALTY
    risk = record.correlation_risk.lower()
    if risk == "low":
        score += LOW_RISK_BONUS
    elif risk == "medium":
        score += MEDIUM_RISK_BONUS
    elif risk == "high":
        score -= HIGH_RISK_PENALTY
    if record.best_result_label == "repairable_signal":
        score += REPAIRABLE_SIGNAL_BONUS
    if record.best_result_label == "prod_correlation_fail":
        score -= PROD_CORR_PENALTY
    return round(score, 4)


def select_data_for_research(
    records: list[DataLedgerRecord],
    incentive: str,
    region: str,
    delay: int,
    limit: int,
) -> list[DataLedgerRecord]:
    """Input: records and scheduling filters. Output: ranked records. Select data candidates for a run."""
    eligible = [
        record
        for record in records
        if region.upper() in {item.upper() for item in (record.available_regions or [record.region])}
        and int(delay) in set(record.available_delays or [record.delay])
    ]
    scored = sorted(
        eligible,
        key=lambda item: (score_data_for_research(item, incentive, region, delay), item.field_id),
        reverse=True,
    )
    return scored[: max(int(limit), 0)]


def write_data_ledger_markdown(path: Path, records: list[DataLedgerRecord], generated_at: str) -> Path:
    """Input: output path, records, timestamp. Output: path. Write reviewable Markdown data ledger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Data Ledger",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "| Dataset | Field | Scope | Tags | Usage | Best Result | Risk |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        scope = f"{record.region} D{record.delay} {record.universe}"
        tags = ", ".join(record.semantic_tags)
        usage = f"sim={record.simulation_usage_count}; submitted={record.submitted_usage_count}"
        lines.append(
            f"| {record.dataset_id} | `{record.field_id}` | {scope} | {tags} | {usage} | {record.best_result_label} | {record.correlation_risk} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
