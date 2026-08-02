from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.benchmark_rules import BENCHMARK_RULES_PATH, load_benchmark_rules
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


def _check_benchmark_rulebook(path: Path, issues: list[ReadinessIssue], mode: str) -> None:
    """Input: rulebook path, issues, mode. Output: none. Enforce runtime benchmark rule readiness."""
    level = _level_for_mode(mode)
    if not path.exists():
        issues.append(
            _issue(
                level,
                "missing_artifact",
                "Required artifact is missing: benchmark_rules",
                path,
                "Compile or restore the runtime benchmark rulebook.",
            )
        )
        return
    try:
        rules = load_benchmark_rules(path)
    except json.JSONDecodeError as error:
        issues.append(
            _issue(
                level,
                "parse_error",
                "Cannot parse benchmark_rules.",
                f"{path}:{error.lineno}: {error.msg}",
                "Fix benchmark_rules.jsonl before running research.",
            )
        )
        return
    except (OSError, TypeError, ValueError) as error:
        issues.append(
            _issue(
                level,
                "invalid_benchmark_rule",
                f"Runtime benchmark rule is invalid: {error}",
                path,
                "Add every required benchmark rule field before running research.",
            )
        )
        return
    if not rules:
        issues.append(
            _issue(
                level,
                "empty_artifact",
                "benchmark_rules has no records.",
                path,
                "Compile or restore at least one active benchmark rule.",
            )
        )


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


def _scope_key(scope: dict[str, Any]) -> tuple[str, str, int, str] | None:
    """Input: scope dict. Output: normalized key or none. Match raw capture and ledger scope rows."""
    try:
        key = (
            str(scope.get("instrument_type", "EQUITY") or "EQUITY").strip().upper(),
            str(scope.get("region", "")).strip().upper(),
            int(scope.get("delay")),
            str(scope.get("universe", "")).strip().upper(),
        )
    except (TypeError, ValueError):
        return None
    return key if key[0] and key[1] and key[2] >= 0 and key[3] else None


def _record_scope_keys(record: DataLedgerRecord) -> set[tuple[str, str, int, str]]:
    """Input: data-ledger record. Output: exact scope keys. Prefer captured exact scopes over legacy fields."""
    keys = {
        key
        for scope in record.available_scopes or []
        if isinstance(scope, dict) and (key := _scope_key(scope)) is not None
    }
    if keys:
        return keys
    fallback = _scope_key(
        {
            "instrument_type": record.instrument_type or "EQUITY",
            "region": record.region,
            "delay": record.delay,
            "universe": record.universe,
        }
    )
    return {fallback} if fallback is not None else set()


def _canonical_raw_fields_path(root: Path, source_path: str) -> Path | None:
    """Input: vault root and source path. Output: raw data_fields path or none. Resolve safe capture evidence."""
    candidate = Path(str(source_path).replace("\\", "/"))
    resolved = candidate if candidate.is_absolute() else root / candidate
    try:
        relative = resolved.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    if tuple(part.lower() for part in relative.parts[:3]) != ("raw", "platform", "data_fields"):
        return None
    if resolved.name != "data_fields.jsonl":
        return None
    return resolved


def _latest_scope_outcomes(capture_dir: Path) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    """Input: capture directory. Output: latest outcome by scope key. Read append-only scope certification rows."""
    outcomes: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    path = capture_dir / "scopes.jsonl"
    if not path.exists():
        return outcomes
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        scope = row.get("scope") if isinstance(row, dict) else None
        if isinstance(scope, dict) and (key := _scope_key(scope)) is not None:
            outcomes[key] = row
    return outcomes


def _certified_scope_keys(raw_path: Path, source_date: date) -> set[tuple[str, str, int, str]]:
    """Input: raw data_fields path and source date. Output: certified scope keys. Validate manifest-level authority once."""
    capture_dir = raw_path.parent
    try:
        manifest = json.loads((capture_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(manifest, dict) or manifest.get("certification_status") != "complete":
        return set()
    generated_at = str(manifest.get("generated_at", ""))
    if len(generated_at) < 10 or generated_at[:10] != source_date.isoformat():
        return set()
    requested = manifest.get("requested_matrix")
    if not isinstance(requested, list):
        return set()
    requested_keys = {
        key
        for item in requested
        if isinstance(item, dict) and (key := _scope_key(item)) is not None
    }
    outcomes = _latest_scope_outcomes(capture_dir)
    return {
        key
        for key in requested_keys
        if (outcome := outcomes.get(key)) is not None
        and outcome.get("status") == "completed"
        and outcome.get("certification_status") == "complete"
    }


def _raw_field_key(scope: dict[str, Any], dataset_id: str, field_id: str) -> tuple[tuple[str, str, int, str], str, str] | None:
    """Input: raw scope, dataset id, field id. Output: comparable raw key or none. Normalize field evidence keys."""
    scope_key = _scope_key(scope)
    if scope_key is None or not dataset_id or not field_id:
        return None
    return scope_key, dataset_id, field_id


def _batch_uncertified_records(records: list[DataLedgerRecord], root: Path) -> list[DataLedgerRecord]:
    """Input: candidate records and vault root. Output: records missing batch raw evidence. Scan each raw file once."""
    source_scope_cache: dict[tuple[Path, date], set[tuple[str, str, int, str]]] = {}
    grouped: dict[Path, list[tuple[int, DataLedgerRecord, set[tuple[str, str, int, str]]]]] = {}
    for index, record in enumerate(records):
        source_date = _record_source_date(record)
        record_scopes = _record_scope_keys(record)
        if source_date is None or not record_scopes:
            continue
        for source_path in record.source_paths:
            raw_path = _canonical_raw_fields_path(root, source_path)
            if raw_path is None or not raw_path.exists():
                continue
            cache_key = (raw_path, source_date)
            if cache_key not in source_scope_cache:
                source_scope_cache[cache_key] = _certified_scope_keys(raw_path, source_date)
            if record_scopes.issubset(source_scope_cache[cache_key]):
                grouped.setdefault(raw_path, []).append((index, record, record_scopes))
                break

    certified_indexes: set[int] = set()
    for raw_path, items in grouped.items():
        required = {
            (scope, record.dataset_id, record.field_id)
            for _, record, scopes in items
            for scope in scopes
            if record.dataset_id and record.field_id
        }
        seen: set[tuple[tuple[str, str, int, str], str, str]] = set()
        try:
            with raw_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
                    data_set = row.get("data_set") if isinstance(row.get("data_set"), dict) else {}
                    field = row.get("field") if isinstance(row.get("field"), dict) else {}
                    key = _raw_field_key(scope, str(data_set.get("id", "")), str(field.get("id", "")))
                    if key in required:
                        seen.add(key)
        except OSError:
            continue
        for index, record, scopes in items:
            record_keys = {(scope, record.dataset_id, record.field_id) for scope in scopes}
            if record_keys and record_keys.issubset(seen):
                certified_indexes.add(index)
    return [record for index, record in enumerate(records) if index not in certified_indexes]


def _has_measured_platform_metadata(record: DataLedgerRecord) -> bool:
    """Input: ledger record. Output: bool. Check strict raw-platform metadata before raw evidence certification."""
    return record.source_quality == "platform_raw_capture" and record.coverage_status == "measured_raw"


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
        measured_platform_data = [record for record in covered_data if _has_measured_platform_metadata(record)]
        if not measured_platform_data:
            authority = summarize_data_ledger_authority(covered_data)
            issues.append(
                _issue(
                    level,
                    "cache_only_data_ledger",
                    f"Selected scope {region} D{int(delay)} {universe} has {authority['seed_cache_count']} seed/cache records and {authority['authoritative_measured_count']} measured-platform metadata records.",
                    ledger_path,
                    "Run capture-platform-data-fields and compile-data-ledger before research scheduling.",
                )
            )
            return
        covered_data = measured_platform_data
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
        invalid_freshness = [record for record in covered_data if _record_source_date(record) is None]
        if invalid_freshness:
            authority = summarize_data_ledger_authority(covered_data)
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
            for record in covered_data
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
        uncertified = _batch_uncertified_records(covered_data, root)
        if uncertified:
            authority = summarize_data_ledger_authority(covered_data)
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
            for record in freshness_records:
                if record.name == "benchmark_rules" and Path(record.path) != BENCHMARK_RULES_PATH:
                    issues.append(
                        _issue(
                            _level_for_mode(mode),
                            "invalid_benchmark_rule_path",
                            "Freshness manifest must track the runtime benchmark rulebook.",
                            record.path,
                            f"Set benchmark_rules path to {BENCHMARK_RULES_PATH.as_posix()}.",
                        )
                    )
            for status in statuses:
                if not status.artifact_exists:
                    issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "missing_artifact", f"Required artifact is missing: {status.name}", status.path, "Run bootstrap-knowledge."))
                elif status.stale:
                    issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "stale_artifact", f"Required artifact is stale: {status.name}", status.path, "Run knowledge maintenance."))
    _check_jsonl_artifact(root / DATA_LEDGER_PATH, "data_ledger", issues, mode)
    _check_jsonl_artifact(root / TEMPLATE_LIBRARY_PATH, "template_library", issues, mode)
    _check_benchmark_rulebook(root / BENCHMARK_RULES_PATH, issues, mode)
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
