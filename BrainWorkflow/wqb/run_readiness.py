from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.data_ledger import (
    DataLedgerRecord,
    is_authoritative_data_record,
    load_data_ledger,
    select_data_for_research,
    summarize_data_ledger_authority,
)
from wqb.knowledge_freshness import evaluate_freshness, load_freshness_manifest
from wqb.template_library import load_template_library, select_templates_for_data


READINESS_MODES = {"maintenance", "plan-only", "research", "submit-candidate"}
STRICT_BLOCKING_MODES = {"research", "submit-candidate"}
FRESHNESS_MANIFEST_PATH = Path("wiki") / "80_maintenance" / "freshness_manifest.json"
DATA_LEDGER_PATH = Path("wiki") / "20_semantics" / "data_ledger.jsonl"
TEMPLATE_LIBRARY_PATH = Path("wiki") / "30_templates" / "template_library.jsonl"


@dataclass(frozen=True)
class ReadinessIssue:
    level: str
    code: str
    message: str
    path: str = ""
    action: str = ""


@dataclass(frozen=True)
class ReadinessReport:
    mode: str
    generated_at: str
    passed: bool
    blocked: bool
    issues: list[ReadinessIssue]


def _issue(level: str, code: str, message: str, path: Path | str = "", action: str = "") -> ReadinessIssue:
    """Input: issue fields. Output: ReadinessIssue. Create one actionable readiness issue."""
    return ReadinessIssue(level=level, code=code, message=message, path=str(path), action=action)


def readiness_report_to_dict(report: ReadinessReport) -> dict[str, Any]:
    """Input: ReadinessReport. Output: dict. Convert readiness report to JSON-safe data."""
    row = asdict(report)
    row["issues"] = [asdict(issue) for issue in report.issues]
    return row


def _jsonl_row_count(path: Path) -> tuple[int, str]:
    """Input: JSONL path. Output: row count and error. Validate JSONL parseability."""
    count = 0
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip():
                json.loads(line)
                count += 1
    except json.JSONDecodeError as error:
        return count, f"{path}:{line_number}: {error.msg}"
    return count, ""


def _check_jsonl_artifact(path: Path, code_name: str, issues: list[ReadinessIssue], mode: str) -> None:
    """Input: path, artifact name, issues, mode. Output: none. Add JSONL parse and empty-file issues."""
    if not path.exists():
        return
    row_count, error = _jsonl_row_count(path)
    if error:
        issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "parse_error", f"Cannot parse {code_name}.", error, "Fix JSONL before running research."))
    elif row_count == 0:
        issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "empty_artifact", f"{code_name} has no records.", path, "Run bootstrap-knowledge or refresh knowledge."))


def _level_for_mode(mode: str) -> str:
    """Input: readiness mode. Output: issue level. Convert strict modes into blocking issues."""
    return "block" if mode in STRICT_BLOCKING_MODES else "warn"


def _data_ledger_max_age_days(records: list[Any]) -> int | None:
    """Input: freshness records. Output: optional max age. Find the data-ledger freshness policy."""
    for record in records:
        if getattr(record, "name", "") == "data_ledger":
            return int(getattr(record, "max_age_days", 0))
    return None


def _record_source_date(record: DataLedgerRecord) -> date | None:
    """Input: ledger record. Output: optional date. Parse per-record raw source freshness."""
    try:
        return date.fromisoformat(str(record.source_updated_at))
    except ValueError:
        return None


def _validate_scope_artifacts(
    root: Path,
    mode: str,
    issues: list[ReadinessIssue],
    region: str | None,
    universe: str | None,
    delay: int | None,
    current: date,
    data_ledger_max_age_days: int | None,
) -> None:
    """Input: root, mode, issues, scope. Output: none. Validate ledger/template fit for a selected run scope."""
    if region is None or universe is None or delay is None:
        return
    level = _level_for_mode(mode)
    ledger_path = root / DATA_LEDGER_PATH
    template_path = root / TEMPLATE_LIBRARY_PATH
    try:
        ledger_records = load_data_ledger(ledger_path)
        template_records = load_template_library(template_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        issues.append(_issue(level, "parse_error", f"Cannot load scoped knowledge artifacts: {error}", root, "Fix JSONL before running research."))
        return
    selected_data = select_data_for_research(
        ledger_records,
        incentive="power_pool",
        region=region,
        delay=int(delay),
        limit=max(len(ledger_records), 1),
        universe=universe,
    )
    if not selected_data:
        issues.append(
            _issue(
                level,
                "no_compatible_data",
                f"No data ledger records match selected scope {region} D{int(delay)} {universe}.",
                ledger_path,
                "Bootstrap or refresh data ledger records for the selected region/universe/delay.",
            )
        )
        return
    if mode in STRICT_BLOCKING_MODES:
        zero_coverage = [record for record in selected_data if float(record.coverage) <= 0.0]
        if zero_coverage:
            issues.append(
                _issue(
                    level,
                    "insufficient_data_coverage",
                    f"Compatible data ledger records for {region} D{int(delay)} {universe} include zero coverage.",
                    ledger_path,
                    "Replace schema-only seeds with measured data ledger records before research.",
                )
            )
            return
        if data_ledger_max_age_days is None or data_ledger_max_age_days <= 0:
            issues.append(
                _issue(
                    level,
                    "invalid_scope_data_freshness",
                    "Data ledger freshness policy is missing for scoped readiness.",
                    root / FRESHNESS_MANIFEST_PATH,
                    "Fix freshness_manifest.json before running research.",
                )
            )
            return
        invalid_freshness = [
            record for record in selected_data if _record_source_date(record) is None
        ]
        if invalid_freshness:
            authority = summarize_data_ledger_authority(selected_data, root)
            issues.append(
                _issue(
                    level,
                    "cache_only_data_ledger",
                    f"Selected scope {region} D{int(delay)} {universe} has {authority['seed_cache_count']} seed/cache records and {authority['authoritative_measured_count']} authoritative measured records; source dates are invalid.",
                    ledger_path,
                    "Refresh platform raw data fields and compile ledger rows with source_updated_at.",
                )
            )
            return
        stale = [
            record
            for record in selected_data
            if (current - _record_source_date(record)).days > data_ledger_max_age_days  # type: ignore[arg-type]
        ]
        if stale:
            issues.append(
                _issue(
                    level,
                    "stale_scope_data",
                    f"Compatible data ledger records for {region} D{int(delay)} {universe} are stale for the selected exact scope.",
                    ledger_path,
                    "Refresh platform raw data fields for this exact scope before research.",
                )
            )
            return
        uncertified = [record for record in selected_data if not is_authoritative_data_record(record, root)]
        if uncertified:
            authority = summarize_data_ledger_authority(selected_data, root)
            issues.append(
                _issue(
                    level,
                    "cache_only_data_ledger",
                    f"Selected scope {region} D{int(delay)} {universe} has {authority['seed_cache_count']} seed/cache records and {authority['authoritative_measured_count']} authoritative measured records.",
                    ledger_path,
                    "Run capture-platform-data-fields and compile-data-ledger before research scheduling.",
                )
            )
            return
        covered_data = selected_data
    else:
        covered_data = [record for record in selected_data if float(record.coverage) > 0.0]
    if not covered_data:
        issues.append(
            _issue(
                level,
                "insufficient_data_coverage",
                f"Compatible data ledger records for {region} D{int(delay)} {universe} have zero coverage.",
                ledger_path,
                "Replace schema-only seeds with measured data ledger records before research.",
            )
        )
        return
    has_template_match = any(
        select_templates_for_data(
            template_records,
            record,
            incentive="power_pool",
            limit=1,
            region=region,
            delay=int(delay),
            universe=universe,
        )
        for record in covered_data
    )
    if not has_template_match:
        issues.append(
            _issue(
                level,
                "no_compatible_template",
                f"No template library records match selected scope {region} D{int(delay)} {universe}.",
                template_path,
                "Add or refresh templates compatible with the selected data scope.",
            )
        )


def evaluate_run_readiness(
    knowledge_root: str | Path,
    mode: str,
    batch_size: int = 30,
    live_api_enabled: bool = False,
    submit_confirmed: bool = False,
    today_value: str | None = None,
    region: str | None = None,
    universe: str | None = None,
    delay: int | None = None,
) -> ReadinessReport:
    """Input: root, mode, safety flags. Output: report. Check whether a run may start."""
    if mode not in READINESS_MODES:
        raise ValueError(f"unsupported readiness mode: {mode}")
    root = Path(knowledge_root)
    current = date.fromisoformat(today_value) if today_value else date.today()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    issues: list[ReadinessIssue] = []
    freshness_records: list[Any] = []
    manifest = root / FRESHNESS_MANIFEST_PATH
    if not manifest.exists():
        issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "missing_manifest", "Freshness manifest is missing.", manifest, "Run bootstrap-knowledge."))
    else:
        try:
            freshness_records = load_freshness_manifest(manifest, strict=True)
            statuses = evaluate_freshness(freshness_records, current, artifact_root=root)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "parse_error", f"Cannot load freshness manifest: {error}", manifest, "Fix the freshness manifest before running."))
        else:
            for status in statuses:
                if not status.artifact_exists:
                    issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "missing_artifact", f"Required artifact is missing: {status.name}", status.path, "Run bootstrap-knowledge."))
                elif status.stale:
                    issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "stale_artifact", f"Required artifact is stale: {status.name}", status.path, "Run knowledge maintenance."))
    _check_jsonl_artifact(root / DATA_LEDGER_PATH, "data_ledger", issues, mode)
    _check_jsonl_artifact(root / TEMPLATE_LIBRARY_PATH, "template_library", issues, mode)
    _validate_scope_artifacts(
        root,
        mode,
        issues,
        region,
        universe,
        delay,
        current,
        _data_ledger_max_age_days(freshness_records),
    )
    if mode == "research" and batch_size < 30:
        issues.append(_issue("block", "batch_size_too_small", "Research discovery batch size must be at least 30.", "", "Set batch_size to 30 or higher."))
    if mode == "research" and not live_api_enabled:
        issues.append(_issue("block", "live_api_disabled", "Research mode requires explicit live API enablement.", "", "Pass live_api_enabled=True or use plan-only mode."))
    if mode == "submit-candidate" and not submit_confirmed:
        issues.append(_issue("block", "submit_not_confirmed", "Submit-candidate mode requires explicit user confirmation.", "", "Collect user confirmation before submit."))
    blocked = any(issue.level == "block" for issue in issues)
    return ReadinessReport(mode=mode, generated_at=generated_at, passed=not blocked, blocked=blocked, issues=issues)


def write_readiness_reports(output_dir: Path, report: ReadinessReport) -> tuple[Path, Path]:
    """Input: output dir and report. Output: JSON and Markdown paths. Persist readiness reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "readiness_report.json"
    md_path = output_dir / "readiness_report.md"
    json_path.write_text(json.dumps(readiness_report_to_dict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Run Readiness Report", "", f"Generated at: `{report.generated_at}`", f"Mode: `{report.mode}`", f"Passed: `{report.passed}`", ""]
    lines.extend(["| Level | Code | Message | Path | Action |", "| --- | --- | --- | --- | --- |"])
    for issue in report.issues:
        lines.append(f"| {issue.level} | {issue.code} | {issue.message} | `{issue.path}` | {issue.action} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
