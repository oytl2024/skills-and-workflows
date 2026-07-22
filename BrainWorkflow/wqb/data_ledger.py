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
    source_quality: str = ""
    coverage_status: str = ""
    source_updated_at: str = ""
    available_regions: list[str] = field(default_factory=list)
    available_delays: list[int] = field(default_factory=list)
    available_universes: list[str] = field(default_factory=list)
    available_scopes: list[dict[str, Any]] | None = None
    activity_tags: list[str] = field(default_factory=list)
    compatible_template_ids: list[str] = field(default_factory=list)
    gate_requirements: list[str] = field(default_factory=list)
    experiment_paths: list[str] = field(default_factory=list)
    instrument_type: str = ""
    date_coverage: str = ""
    data_category: str = ""
    crowding_risk: str = "unknown"
    known_operators: list[str] = field(default_factory=list)
    repair_usage_count: int = 0
    field_description: str = ""


def data_ledger_record_to_dict(record: DataLedgerRecord) -> dict[str, Any]:
    """Input: DataLedgerRecord. Output: dict[str, Any]. Convert ledger record to JSON-safe data."""
    row = asdict(record)
    if row["available_scopes"] is None:
        row.pop("available_scopes")
    return row


def data_ledger_record_from_dict(row: dict[str, Any]) -> DataLedgerRecord:
    """Input: dict row. Output: DataLedgerRecord. Normalize one JSON-safe data ledger row."""
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
        source_quality=str(row.get("source_quality", "")),
        coverage_status=str(row.get("coverage_status", "")),
        source_updated_at=str(row.get("source_updated_at", "")),
        available_regions=[str(item) for item in row.get("available_regions", []) if str(item)],
        available_delays=[int(item) for item in row.get("available_delays", [])],
        available_universes=[str(item) for item in row.get("available_universes", []) if str(item)],
        available_scopes=(
            [dict(item) for item in row.get("available_scopes", []) if isinstance(item, dict)]
            if "available_scopes" in row
            else None
        ),
        activity_tags=[str(item) for item in row.get("activity_tags", []) if str(item)],
        compatible_template_ids=[str(item) for item in row.get("compatible_template_ids", []) if str(item)],
        gate_requirements=[str(item) for item in row.get("gate_requirements", []) if str(item)],
        experiment_paths=[str(item) for item in row.get("experiment_paths", []) if str(item)],
        instrument_type=str(row.get("instrument_type", "")),
        date_coverage=str(row.get("date_coverage", "")),
        data_category=str(row.get("data_category", "")),
        crowding_risk=str(row.get("crowding_risk", "unknown")),
        known_operators=[str(item) for item in row.get("known_operators", []) if str(item)],
        repair_usage_count=int(row.get("repair_usage_count", 0)),
        field_description=str(row.get("field_description", "")),
    )


def data_record_authority(record: DataLedgerRecord) -> str:
    """Input: data ledger record. Output: authority label. Classify seed/cache versus measured platform rows."""
    if (
        record.source_quality == "platform_raw_capture"
        and record.coverage_status == "measured_raw"
        and bool(record.source_updated_at)
    ):
        return "authoritative_measured"
    if record.source_quality in {"platform_metadata_cache", "schema_seed", "bootstrap_seed"}:
        return "seed_cache"
    if record.coverage_status in {"measured_cache", "schema_seeded", "partial"}:
        return "seed_cache"
    return "unclassified"


def is_authoritative_data_record(record: DataLedgerRecord) -> bool:
    """Input: data ledger record. Output: bool. Test whether the row is measured platform evidence."""
    return data_record_authority(record) == "authoritative_measured"


def summarize_data_ledger_authority(records: list[DataLedgerRecord]) -> dict[str, Any]:
    """Input: data ledger records. Output: summary dict. Count authority classes for UI and readiness."""
    counts = {"authoritative_measured": 0, "seed_cache": 0, "unclassified": 0}
    for record in records:
        authority = data_record_authority(record)
        counts[authority] = counts.get(authority, 0) + 1
    return {
        "record_count": len(records),
        "authoritative_measured_count": counts.get("authoritative_measured", 0),
        "seed_cache_count": counts.get("seed_cache", 0),
        "unclassified_count": counts.get("unclassified", 0),
        "authoritative_ready": bool(records) and counts.get("authoritative_measured", 0) == len(records),
    }


def _record_from_dict(row: dict[str, Any]) -> DataLedgerRecord:
    """Input: dict row. Output: DataLedgerRecord. Keep the legacy private loader adapter."""
    return data_ledger_record_from_dict(row)


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
    universe: str | None = None,
) -> list[DataLedgerRecord]:
    """Input: records and scheduling filters. Output: ranked records. Select data candidates for a run."""
    eligible = [
        record
        for record in records
        if _record_matches_scope(record, region, delay, universe)
    ]
    scored = sorted(
        eligible,
        key=lambda item: (score_data_for_research(item, incentive, region, delay), item.field_id),
        reverse=True,
    )
    return scored[: max(int(limit), 0)]


def _record_matches_scope(
    record: DataLedgerRecord, region: str, delay: int, universe: str | None
) -> bool:
    """Input: ledger record and requested scope. Output: bool. Prefer exact captured scope tuples over legacy scope lists."""
    if record.available_scopes is not None:
        return any(
            str(scope.get("region", "")).upper() == region.upper()
            and int(scope.get("delay", -1)) == int(delay)
            and (universe is None or str(scope.get("universe", "")).upper() == universe.upper())
            for scope in record.available_scopes
            if isinstance(scope, dict)
        )
    return (
        region.upper() in {item.upper() for item in (record.available_regions or [record.region])}
        and int(delay) in set(record.available_delays or [record.delay])
        and (
            universe is None
            or universe.upper() in {item.upper() for item in (record.available_universes or [record.universe])}
        )
    )


def write_data_ledger_markdown(path: Path, records: list[DataLedgerRecord], generated_at: str) -> Path:
    """Input: output path, records, timestamp. Output: path. Write reviewable Markdown data ledger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Data Ledger",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "| Dataset | Field | Scope | Authority | Tags | Usage | Best Result | Risk |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        scope = f"{record.region} D{record.delay} {record.universe}"
        authority = data_record_authority(record)
        tags = ", ".join(record.semantic_tags)
        usage = f"sim={record.simulation_usage_count}; submitted={record.submitted_usage_count}"
        lines.append(
            f"| {record.dataset_id} | `{record.field_id}` | {scope} | {authority} | {tags} | {usage} | {record.best_result_label} | {record.correlation_risk} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
