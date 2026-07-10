from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_freshness import evaluate_freshness, load_freshness_manifest


READINESS_MODES = {"maintenance", "plan-only", "research", "submit-candidate"}
STRICT_BLOCKING_MODES = {"research", "submit-candidate"}
FRESHNESS_MANIFEST_PATH = Path("wiki") / "80_maintenance" / "freshness_manifest.json"


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


def evaluate_run_readiness(
    knowledge_root: str | Path,
    mode: str,
    batch_size: int = 30,
    live_api_enabled: bool = False,
    submit_confirmed: bool = False,
    today_value: str | None = None,
) -> ReadinessReport:
    """Input: root, mode, safety flags. Output: report. Check whether a run may start."""
    if mode not in READINESS_MODES:
        raise ValueError(f"unsupported readiness mode: {mode}")
    root = Path(knowledge_root)
    current = date.fromisoformat(today_value) if today_value else date.today()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    issues: list[ReadinessIssue] = []
    manifest = root / FRESHNESS_MANIFEST_PATH
    if not manifest.exists():
        issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "missing_manifest", "Freshness manifest is missing.", manifest, "Run bootstrap-knowledge."))
    else:
        try:
            records = load_freshness_manifest(manifest, strict=True)
            statuses = evaluate_freshness(records, current, artifact_root=root)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "parse_error", f"Cannot load freshness manifest: {error}", manifest, "Fix the freshness manifest before running."))
        else:
            for status in statuses:
                if not status.artifact_exists:
                    issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "missing_artifact", f"Required artifact is missing: {status.name}", status.path, "Run bootstrap-knowledge."))
                elif status.stale:
                    issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "stale_artifact", f"Required artifact is stale: {status.name}", status.path, "Run knowledge maintenance."))
    _check_jsonl_artifact(root / "wiki" / "20_semantics" / "data_ledger.jsonl", "data_ledger", issues, mode)
    _check_jsonl_artifact(root / "wiki" / "30_templates" / "template_library.jsonl", "template_library", issues, mode)
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
