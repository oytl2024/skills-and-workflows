from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any
import urllib.request

from wqb.knowledge_clean_compile import evaluate_clean_knowledge_structure
from wqb.delivery_verification import verification_commands
from wqb.knowledge_freshness import (
    evaluate_knowledge_contract_health,
    load_freshness_manifest,
)
from wqb.knowledge_contracts import canonical_source_family, parse_markdown_front_matter
from wqb.knowledge_paths import MACHINE_RESOURCE_FILES, machine_resource_path
from wqb.research_planner import plan_research_options
from wqb.run_readiness import evaluate_run_readiness
from wqb.workflow_events import WorkflowEventReadError, read_workflow_events_strict
from wqb.workflow_state import (
    WorkflowRunState,
    diagnose_state_consistency,
    load_run_state,
)


REQUIRED_HUMAN_WIKI_FILES = (
    "00_start_here.md",
    "10_factor_principles.md",
    "20_data_semantics.md",
    "30_template_and_operator_patterns.md",
    "40_benchmark_and_repair_rules.md",
    "50_engineering_lessons.md",
)
LOCAL_VERIFICATION_MAX_AGE_HOURS = 24
REQUIRED_LOCAL_VERIFICATION_CHECKS = (
    "unittest_discovery",
    "compileall",
)
RAW_SOURCE_INDEX_HEADING = re.compile(r"^## `([^`]+)`\s*$", re.MULTILINE)


@dataclass(frozen=True)
class DeliveryGateCheck:
    code: str
    status: str
    message: str
    evidence_path: str = ""


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for delivery gate reports."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _latest_run_state(runs_root: Path) -> WorkflowRunState | None:
    """Input: runs root. Output: newest valid WorkflowRunState or none. Select by durable state timestamps."""
    states: list[WorkflowRunState] = []
    for path in runs_root.glob("*/run_state.json"):
        try:
            states.append(load_run_state(path))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    if not states:
        return None
    return max(
        states,
        key=lambda state: (state.updated_at or state.created_at, state.created_at, state.run_id),
    )


def _check(status: bool, code: str, message: str, evidence_path: str = "") -> DeliveryGateCheck:
    """Input: pass flag and details. Output: DeliveryGateCheck."""
    return DeliveryGateCheck(code, "passed" if status else "failed", message, evidence_path)


def _parse_timestamp(value: str) -> datetime | None:
    """Input: timestamp string. Output: timezone-aware datetime or none. Parse report evidence safely."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _project_root() -> Path:
    """Input: none. Output: BrainWorkflow project root path. Locate where local checks must run."""
    return Path(__file__).resolve().parent.parent


def _path_value_resolves_to(value: Any, expected: Path) -> bool:
    """Input: path-like value and expected path. Output: bool. Require a non-empty absolute path match."""
    if not isinstance(value, str) or not value.strip():
        return False
    path = Path(value)
    return path.is_absolute() and path.resolve() == expected


def _latest_maintenance_report(knowledge_root: Path) -> tuple[dict[str, Any], Path | None]:
    """Input: knowledge root. Output: newest final maintenance payload and path."""
    directory = knowledge_root / "raw" / "maintenance" / "compile_reports"
    pointer = directory / "latest.json"
    if pointer.exists():
        try:
            latest = json.loads(pointer.read_text(encoding="utf-8"))
            if not isinstance(latest, dict):
                return {}, None
            report_path = Path(str(latest.get("report_path", "")))
            if not report_path.is_absolute():
                report_path = knowledge_root / report_path
            report_path = report_path.resolve()
            report_path.relative_to(directory.resolve())
            if report_path == pointer.resolve():
                return {}, None
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                return {}, None
            if report.get("report_type") != "knowledge_maintenance":
                return {}, None
            return report, report_path
        except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
            return {}, None
    reports: list[tuple[datetime, dict[str, Any], Path]] = []
    for path in directory.glob("*.json"):
        if ".pre_cleanup_evidence" in path.name:
            continue
        if path.name == "latest.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("report_type") != "knowledge_maintenance":
            continue
        generated = _parse_timestamp(str(payload.get("generated_at", "")))
        if generated is not None:
            reports.append((generated, payload, path))
    if not reports:
        return {}, None
    _, payload, path = max(reports, key=lambda row: (row[0], row[2].stat().st_mtime_ns))
    return payload, path


def _load_cleanup_log(path_value: str, knowledge_root: Path) -> list[dict[str, Any]]:
    """Input: cleanup log reference and knowledge root. Output: parsed JSONL rows."""
    path = Path(path_value)
    if not path.is_absolute():
        path = knowledge_root / path
    path = path.resolve()
    cleanup_root = (
        knowledge_root / "raw" / "maintenance" / "cleanup_logs"
    ).resolve()
    try:
        path.relative_to(cleanup_root)
    except ValueError as error:
        raise ValueError("cleanup log is outside the maintenance directory") from error
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("cleanup log row must be an object")
        rows.append(row)
    return rows


def _maintenance_evidence(
    knowledge_root: Path,
    gate_generated_at: str,
) -> tuple[bool, str, str]:
    """Input: knowledge root and gate time. Output: status, message, report path. Validate fresh applied maintenance."""
    report, report_path = _latest_maintenance_report(knowledge_root)
    if report_path is None:
        return False, "Fresh successful knowledge maintenance report is missing.", ""
    gate_time = _parse_timestamp(gate_generated_at)
    report_time = _parse_timestamp(str(report.get("generated_at", "")))
    fresh = (
        gate_time is not None
        and report_time is not None
        and timedelta(0) <= gate_time - report_time <= timedelta(hours=24)
    )
    cleanup = report.get("cleanup", {})
    health = report.get("health", {})
    cleanup_rows: list[dict[str, Any]] = []
    try:
        if isinstance(cleanup, dict):
            cleanup_rows = _load_cleanup_log(
                str(cleanup.get("cleanup_log_path", "")),
                knowledge_root,
            )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        cleanup_rows = []
    applied_cleanup = any(
        row.get("event") == "cleanup_run"
        and row.get("dry_run") is False
        and row.get("blocked") is False
        and row.get("generated_at") == report.get("generated_at")
        for row in cleanup_rows
    )
    passed = (
        fresh
        and _path_value_resolves_to(report.get("report_path"), report_path)
        and report.get("report_type") == "knowledge_maintenance"
        and report.get("status") == "completed"
        and isinstance(health, dict)
        and health.get("issue_count") == 0
        and isinstance(cleanup, dict)
        and cleanup.get("status") == "completed"
        and cleanup.get("dry_run") is False
        and cleanup.get("blocked") is False
        and applied_cleanup
    )
    message = (
        "Fresh successful maintenance report and applied cleanup evidence are present."
        if passed
        else "Maintenance must be fresh, completed, healthy, and backed by an applied cleanup log."
    )
    return passed, message, str(report_path)


def _load_latest_verification_report(
    knowledge_root: Path,
) -> tuple[dict[str, Any], Path | None]:
    """Input: knowledge root. Output: immutable verification payload and path. Resolve the latest pointer safely."""
    directory = knowledge_root / "raw" / "maintenance" / "delivery_checks"
    pointer = directory / "latest.json"
    try:
        latest = json.loads(pointer.read_text(encoding="utf-8"))
        if not isinstance(latest, dict):
            return {}, None
        report_path = Path(str(latest.get("report_path", "")))
        if not report_path.is_absolute():
            report_path = knowledge_root / report_path
        report_path = report_path.resolve()
        report_path.relative_to(directory.resolve())
        if report_path == pointer.resolve():
            return {}, None
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            return {}, None
        return report, report_path
    except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        return {}, None


def _local_verification_evidence(
    knowledge_root: Path,
    gate_generated_at: str,
) -> tuple[bool, str, str]:
    """Input: vault root and gate time. Output: status, message, report path. Validate fresh local checks."""
    report, report_path = _load_latest_verification_report(knowledge_root)
    if report_path is None:
        return False, "Fresh local unittest discovery and compileall evidence is missing.", ""
    gate_time = _parse_timestamp(gate_generated_at)
    report_time = _parse_timestamp(str(report.get("generated_at", "")))
    fresh = (
        gate_time is not None
        and report_time is not None
        and timedelta(0) <= gate_time - report_time <= timedelta(hours=LOCAL_VERIFICATION_MAX_AGE_HOURS)
    )
    checks = report.get("checks", [])
    check_codes: list[str] = []
    checks_have_exact_shape = False
    if isinstance(checks, list) and all(isinstance(check, dict) for check in checks):
        check_codes = [str(check.get("code", "")) for check in checks]
        checks_have_exact_shape = (
            len(checks) == len(REQUIRED_LOCAL_VERIFICATION_CHECKS)
            and set(check_codes) == set(REQUIRED_LOCAL_VERIFICATION_CHECKS)
            and len(check_codes) == len(set(check_codes))
        )
    checks_by_code = {
        str(check.get("code", "")): check
        for check in checks
        if isinstance(check, dict)
    } if isinstance(checks, list) else {}
    expected_commands = {code: command for code, command in verification_commands()}
    expected_project = _project_root().resolve()
    report_path_matches = _path_value_resolves_to(report.get("report_path"), report_path)
    required_checks_passed = all(
        isinstance(checks_by_code.get(code), dict)
        and checks_by_code[code].get("status") == "passed"
        and checks_by_code[code].get("returncode") == 0
        and checks_by_code[code].get("command") == expected_commands.get(code)
        and _path_value_resolves_to(checks_by_code[code].get("cwd"), expected_project)
        and isinstance(checks_by_code[code].get("stdout"), str)
        and isinstance(checks_by_code[code].get("stderr"), str)
        for code in REQUIRED_LOCAL_VERIFICATION_CHECKS
    )
    passed = (
        fresh
        and report.get("report_type") == "delivery_verification"
        and report.get("status") == "passed"
        and report_path_matches
        and checks_have_exact_shape
        and required_checks_passed
    )
    if passed:
        message = "Fresh successful unittest discovery and compileall evidence is present."
    else:
        missing = [
            code
            for code in REQUIRED_LOCAL_VERIFICATION_CHECKS
            if code not in checks_by_code
        ]
        suffix = f" Missing checks: {', '.join(missing)}." if missing else ""
        message = f"Local verification must be fresh, runner-generated, and contain successful controller-compatible checks.{suffix}"
    return passed, message, str(report_path)


def _parse_machine_resource(
    knowledge_root: Path,
    resource_name: str,
) -> tuple[bool, str, list[dict[str, Any]]]:
    """Input: vault root and resource name. Output: parse status, message, object rows."""
    path = machine_resource_path(knowledge_root, resource_name)
    try:
        if resource_name == "freshness_manifest":
            records = load_freshness_manifest(path, strict=True)
            if not records:
                raise ValueError("freshness manifest is empty")
            return True, f"Machine resource is non-empty and parseable: {resource_name}.", []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("JSONL row must be an object")
            rows.append(row)
        if not rows:
            raise ValueError("JSONL resource is empty")
        return True, f"Machine resource is non-empty and parseable: {resource_name}.", rows
    except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as error:
        return False, f"Machine resource is missing, empty, or malformed: {resource_name}: {error}", []


def _source_index_evidence(
    knowledge_root: Path,
    rows: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Input: knowledge root and source-index rows. Output: status and message. Validate complete source coverage."""
    markdown_index = knowledge_root / "raw" / "source_index.md"
    markdown_text = (
        markdown_index.read_text(encoding="utf-8")
        if markdown_index.is_file()
        else ""
    )
    indexed_paths = []
    rows_by_path: dict[str, dict[str, Any]] = {}
    duplicate_machine_paths: list[str] = []
    for row in rows:
        if not isinstance(row.get("path"), str):
            continue
        normalized = str(row.get("path", "")).replace("\\", "/").strip()
        indexed_paths.append(normalized)
        if normalized in rows_by_path:
            duplicate_machine_paths.append(normalized)
        rows_by_path[normalized] = row
    indexed_path_set = set(indexed_paths)
    markdown_paths = {
        match.group(1).replace("\\", "/").strip()
        for match in RAW_SOURCE_INDEX_HEADING.finditer(markdown_text)
    }
    valid_rows = bool(rows) and all(
        isinstance(row.get("path"), str)
        and bool(str(row.get("path", "")).strip())
        and (knowledge_root / str(row["path"])).is_file()
        for row in rows
    )
    canonical_sources = {
        path.relative_to(knowledge_root).as_posix()
        for path in (knowledge_root / "raw").rglob("*.md")
        if path != markdown_index
        and canonical_source_family(path, knowledge_root).startswith("raw/")
    } if (knowledge_root / "raw").exists() else set()
    missing_machine = sorted(canonical_sources - indexed_path_set)
    missing_markdown = sorted(canonical_sources - markdown_paths)
    extra_markdown = sorted(markdown_paths - canonical_sources)
    broken_markdown = sorted(
        path
        for path in markdown_paths
        if not path.startswith("raw/")
        or Path(path).is_absolute()
        or not (knowledge_root / path).is_file()
    )
    metadata_mismatches: list[str] = []
    for source_path in sorted(canonical_sources & indexed_path_set):
        row = rows_by_path[source_path]
        source_file = knowledge_root / source_path
        try:
            metadata, _ = parse_markdown_front_matter(source_file.read_text(encoding="utf-8"))
        except OSError:
            metadata = {}
        comparisons = {
            "source_family": str(metadata.get("source_family", "")),
            "source_type": str(metadata.get("source_type", "")),
            "captured_at": str(metadata.get("captured_at", "")),
            "record_count": str(metadata.get("record_count", "")),
            "content_hash": str(metadata.get("content_hash", "")),
            "content_status": str(metadata.get("content_status", "")),
        }
        for field_name, expected in comparisons.items():
            actual = str(row.get(field_name, ""))
            if actual != expected:
                metadata_mismatches.append(f"{source_path}:{field_name}")
    passed = (
        markdown_index.is_file()
        and bool(markdown_text.strip())
        and valid_rows
        and not missing_machine
        and not missing_markdown
        and not extra_markdown
        and not broken_markdown
        and not duplicate_machine_paths
        and not metadata_mismatches
    )
    missing_details = []
    if missing_machine:
        missing_details.append(f"missing from machine index: {', '.join(missing_machine)}")
    if missing_markdown:
        missing_details.append(f"missing from raw index: {', '.join(missing_markdown)}")
    if extra_markdown:
        missing_details.append(f"unexpected raw index paths: {', '.join(extra_markdown)}")
    if broken_markdown:
        missing_details.append(f"broken raw index paths: {', '.join(broken_markdown)}")
    if duplicate_machine_paths:
        missing_details.append(f"duplicate machine index paths: {', '.join(sorted(set(duplicate_machine_paths)))}")
    if metadata_mismatches:
        missing_details.append(f"metadata mismatch: {', '.join(metadata_mismatches)}")
    return (
        passed,
        "Raw and machine source indexes cover every canonical raw Markdown source."
        if passed
        else "Source indexes are missing, invalid, or incomplete"
        + (f": {'; '.join(missing_details)}." if missing_details else "."),
    )


def _planning_exercise(knowledge_root: Path, generated_at: str) -> tuple[bool, str]:
    """Input: knowledge root and timestamp. Output: status and message. Exercise deterministic non-live planning."""
    try:
        result = plan_research_options(
            knowledge_root,
            generated_at,
            max_options=1,
            live_api_enabled=False,
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        return False, f"Non-live planning exercise failed: {error}"
    options = result.get("options", [])
    passed = int(result.get("option_count", 0)) > 0 and isinstance(options, list) and bool(options)
    return passed, "Non-live research option planning produced a valid option." if passed else "Non-live planning produced no options."


def _workflow_timeline_evidence(state: WorkflowRunState | None) -> tuple[bool, str, str]:
    """Input: latest workflow state. Output: status, message, run path. Validate timeline and stage evidence."""
    if state is None:
        return False, "Latest workflow state is missing.", ""
    run_dir = Path(state.run_dir)
    try:
        events = read_workflow_events_strict(run_dir)
        diagnostics = diagnose_state_consistency(run_dir, state)
    except (OSError, ValueError, TypeError, WorkflowEventReadError) as error:
        return False, f"Workflow timeline or evidence is malformed: {error}", str(run_dir)
    passed = run_dir.is_dir() and bool(events) and not diagnostics
    message = (
        "Workflow event timeline and referenced stage evidence are durable and consistent."
        if passed
        else f"Workflow timeline/evidence is incomplete: {', '.join(diagnostics) or 'event log is empty'}."
    )
    return passed, message, str(run_dir)


def _stage_has_existing_evidence(state: WorkflowRunState, stage_name: str) -> bool:
    """Input: workflow state and stage name. Output: bool. Require durable evidence files for accepted boundaries."""
    stage = state.stages.get(stage_name)
    if stage is None or not stage.evidence_paths:
        return False
    if stage.status not in {"paused", "completed"}:
        return False
    run_dir = Path(state.run_dir)
    for evidence_path in stage.evidence_paths:
        path = Path(evidence_path)
        if not path.is_absolute():
            path = run_dir / path
        if path.exists():
            return True
    return False


def _stage_evidence_lists_missing_artifact(
    state: WorkflowRunState,
    stage_name: str,
    artifact_filename: str,
) -> bool:
    """Input: workflow state, stage, artifact filename. Output: bool. Read structured handoff blockers."""
    stage = state.stages.get(stage_name)
    if stage is None or stage.status not in {"paused", "completed"}:
        return False
    run_dir = Path(state.run_dir)
    expected_artifact = (run_dir / artifact_filename).resolve()
    for evidence_path in stage.evidence_paths:
        path = Path(evidence_path)
        if not path.is_absolute():
            path = run_dir / path
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("stage", "")) != stage_name:
            continue
        if str(payload.get("mode", "")) != "plan_only":
            continue
        blocker = str(payload.get("blocker", "")).lower()
        if "local artifacts required" not in blocker:
            continue
        missing = payload.get("missing_artifacts")
        if not isinstance(missing, list):
            continue
        for item in missing:
            candidate = Path(str(item))
            if not candidate.is_absolute():
                candidate = run_dir / candidate
            if candidate.resolve() == expected_artifact and not candidate.exists():
                return True
    return False


def _console_checks(console_base_url: str) -> list[DeliveryGateCheck]:
    """Input: Console base URL. Output: endpoint checks. Probe documented read-only Console endpoints."""
    checks: list[DeliveryGateCheck] = []
    base = console_base_url.rstrip("/")
    for code, endpoint, expect_json in (
        ("console_root", "/", False),
        ("console_api_state", "/api/state", True),
        ("console_api_fragments", "/api/fragments", True),
    ):
        url = f"{base}{endpoint}"
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                body = response.read()
                passed = int(response.status) == 200
                if expect_json:
                    passed = passed and isinstance(json.loads(body.decode("utf-8")), dict)
            message = f"Console endpoint responded successfully: {endpoint}."
        except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as error:
            passed = False
            message = f"Console endpoint failed: {endpoint}: {error}"
        checks.append(_check(passed, code, message, url))
    return checks


def _write_delivery_report(
    knowledge_root: Path,
    generated_at: str,
    report: dict[str, Any],
) -> Path:
    """Input: knowledge root, timestamp, report. Output: immutable report path and latest pointer."""
    generated = _parse_timestamp(generated_at)
    if generated is None:
        raise ValueError(f"invalid delivery report timestamp: {generated_at}")
    directory = knowledge_root / "raw" / "maintenance" / "delivery_gates"
    directory.mkdir(parents=True, exist_ok=True)
    stem = generated.strftime("%Y%m%dT%H%M%SZ")
    index = 0
    while True:
        suffix = "" if index == 0 else f".{index}"
        path = directory / f"{stem}{suffix}.json"
        payload = {**report, "report_path": str(path)}
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            (directory / "latest.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            report["report_path"] = str(path)
            return path
        except FileExistsError:
            index += 1


def run_delivery_gate(
    knowledge_root: str | Path,
    runs_root: str | Path,
    generated_at: str | None = None,
    console_base_url: str = "",
) -> dict[str, Any]:
    """Input: knowledge root, runs root, timestamp, Console URL. Output: delivery gate report."""
    generated = generated_at or _now()
    knowledge = Path(knowledge_root)
    runs = Path(runs_root)
    checks: list[DeliveryGateCheck] = []
    maintenance_ok, maintenance_message, maintenance_path = _maintenance_evidence(
        knowledge,
        generated,
    )
    checks.append(
        _check(
            maintenance_ok,
            "maintenance_evidence",
            maintenance_message,
            maintenance_path,
        )
    )
    verification_ok, verification_message, verification_path = _local_verification_evidence(
        knowledge,
        generated,
    )
    checks.append(
        _check(
            verification_ok,
            "local_verification_evidence",
            verification_message,
            verification_path,
        )
    )
    clean = evaluate_clean_knowledge_structure(knowledge)
    checks.append(
        _check(
            bool(clean.get("clean")),
            "clean_knowledge_structure",
            "Knowledge active tree follows raw/machine/wiki.",
            str(knowledge),
        )
    )
    health = evaluate_knowledge_contract_health(knowledge)
    checks.append(
        _check(
            health.get("issue_count") == 0,
            "knowledge_contract_health",
            "Full knowledge contract health has no issues."
            if health.get("issue_count") == 0
            else f"Knowledge contract health has {health.get('issue_count', 0)} issue(s).",
            str(knowledge),
        )
    )
    readiness = evaluate_run_readiness(
        knowledge,
        mode="plan-only",
        batch_size=30,
        live_api_enabled=False,
        today_value=generated[:10],
    )
    readiness_codes = ", ".join(issue.code for issue in readiness.issues)
    readiness_ok = readiness.passed and not readiness.blocked and not readiness.issues
    checks.append(
        _check(
            readiness_ok,
            "run_readiness",
            "Plan-only readiness has no issues."
            if readiness_ok
            else f"Plan-only readiness requires attention: {readiness_codes or 'readiness failed'}.",
            str(knowledge),
        )
    )
    machine_rows: dict[str, list[dict[str, Any]]] = {}
    for resource_name in MACHINE_RESOURCE_FILES:
        path = machine_resource_path(knowledge, resource_name)
        parsed, message, rows = _parse_machine_resource(knowledge, resource_name)
        machine_rows[resource_name] = rows
        checks.append(
            _check(
                parsed,
                f"machine_resource_{resource_name}",
                message,
                str(path),
            )
        )
    source_index_ok, source_index_message = _source_index_evidence(
        knowledge,
        machine_rows.get("source_index", []),
    )
    checks.append(
        _check(
            source_index_ok,
            "source_index_evidence",
            source_index_message,
            str(knowledge / "raw" / "source_index.md"),
        )
    )
    for page_name in REQUIRED_HUMAN_WIKI_FILES:
        path = knowledge / "wiki" / page_name
        compact = path.exists() and path.stat().st_size <= 12000
        checks.append(
            _check(
                compact,
                f"human_wiki_{page_name}",
                f"Compact human wiki page exists: {page_name}.",
                str(path),
            )
        )
    planning_ok, planning_message = _planning_exercise(knowledge, generated)
    checks.append(
        _check(
            planning_ok,
            "planning_exercise",
            planning_message,
            str(knowledge),
        )
    )
    state = _latest_run_state(runs)
    expected_pause = (
        state is not None
        and state.status == "paused"
        and state.current_stage == "scout_seed"
        and _stage_evidence_lists_missing_artifact(state, "scout_seed", "candidates.csv")
        and _stage_has_existing_evidence(state, "scout_seed")
    )
    expected_approval = (
        state is not None
        and state.status == "waiting_for_user"
        and state.current_stage == "user_approval"
        and state.waiting_for_user
        and _stage_has_existing_evidence(state, "user_approval")
    )
    expected_terminal = (
        state is not None
        and state.status in {"completed", "completed_with_warnings"}
        and _stage_has_existing_evidence(state, "research_record_sync")
    )
    evidence_path = state.run_dir if state is not None else str(runs)
    checks.append(_check(state is not None, "workflow_state_exists", "Latest workflow state is durable.", evidence_path))
    timeline_ok, timeline_message, timeline_path = _workflow_timeline_evidence(state)
    checks.append(
        _check(
            timeline_ok,
            "workflow_timeline_evidence",
            timeline_message,
            timeline_path,
        )
    )
    checks.append(
        _check(
            expected_pause
            or expected_approval
            or expected_terminal,
            "expected_pause",
            "Workflow reached a durable accepted boundary.",
            evidence_path,
        )
    )
    if console_base_url.strip():
        checks.extend(_console_checks(console_base_url.strip()))
    report = {
        "report_type": "delivery_gate",
        "generated_at": generated,
        "status": "passed" if all(check.status == "passed" for check in checks) else "failed",
        "checks": [asdict(check) for check in checks],
    }
    _write_delivery_report(knowledge, generated, report)
    return report
