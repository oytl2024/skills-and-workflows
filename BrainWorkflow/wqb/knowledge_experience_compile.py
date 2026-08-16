from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_contracts import canonical_source_family, render_front_matter
from wqb.knowledge_paths import (
    existing_machine_resource_path,
    machine_resource_path,
    relative_to_knowledge_root,
)
from wqb.research_record import load_research_record_ledger


HUMAN_WIKI_FILES = {
    "start_here": Path("wiki") / "00_start_here.md",
    "factor_principles": Path("wiki") / "10_factor_principles.md",
    "data_semantics": Path("wiki") / "20_data_semantics.md",
    "template_operator_patterns": Path("wiki") / "30_template_and_operator_patterns.md",
    "benchmark_repair_rules": Path("wiki") / "40_benchmark_and_repair_rules.md",
    "engineering_lessons": Path("wiki") / "50_engineering_lessons.md",
}

MAX_COMPILED_FROM = 24
CASE_REPORT_DIR = Path("wiki") / "60_research_cases"
CASE_REASON_PRIORITY = {
    "submitted_or_approved": 0,
    "near_miss": 1,
    "repair_loop": 2,
    "representative_failure": 3,
}


def _front_matter(generated_at: str, compiled_from: list[str], consumed_by: list[str]) -> str:
    """Input: timestamp, sources, consumers. Output: Markdown front matter."""
    return render_front_matter(
        {
            "compiled_at": generated_at,
            "compiled_from": sorted(set(compiled_from))[:MAX_COMPILED_FROM],
            "consumed_by": consumed_by,
            "stale_after_days": 14,
            "trust_level": "compiled_experience",
            "update_trigger": "compile-knowledge",
        }
    )


def _read_jsonl_rows(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    """Input: JSONL path and limit. Output: row dictionaries. Read bounded machine rows for wiki summaries."""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
                if len(rows) >= limit:
                    break
    return rows


def _now() -> str:
    """Input: none. Output: UTC timestamp. Produce deterministic-format compile timestamps."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_text(value: Any) -> str:
    """Input: display value. Output: compact one-line Markdown-safe text."""
    text = " ".join(str(value or "").split())
    return text.replace('{"', "{").replace("|", "/")[:240]


def _count_list_values(rows: list[dict[str, Any]], field_name: str, limit: int = 12) -> list[str]:
    """Input: rows, list field, limit. Output: compact frequency labels for recurring resource values."""
    counts: Counter[str] = Counter()
    for row in rows:
        values = row.get(field_name, [])
        if isinstance(values, list):
            counts.update(_safe_text(value) for value in values if _safe_text(value))
    return [f"{name} ({count})" for name, count in counts.most_common(limit)]


def _count_scalar_values(rows: list[dict[str, Any]], field_name: str, limit: int = 12) -> list[str]:
    """Input: rows, scalar field, limit. Output: compact frequency labels for resource values."""
    counts = Counter(_safe_text(row.get(field_name)) for row in rows if _safe_text(row.get(field_name)))
    return [f"{name} ({count})" for name, count in counts.most_common(limit)]


def _bullets(values: list[str], empty_message: str) -> list[str]:
    """Input: display values and fallback. Output: Markdown bullet lines."""
    return [f"- {value}" for value in values] if values else [f"- {empty_message}"]


def _canonical_sources(
    knowledge_root: Path,
    resource_names: list[str],
    rows: list[dict[str, Any]],
    source_key: str,
) -> list[str]:
    """Input: root, resources, rows, source key. Output: canonical raw or machine provenance paths."""
    sources = {
        relative_to_knowledge_root(machine_resource_path(knowledge_root, name), knowledge_root)
        for name in resource_names
    }
    for row in rows:
        values = row.get(source_key, [])
        if not isinstance(values, list):
            continue
        for value in values[:MAX_COMPILED_FROM]:
            relative = str(value).replace("\\", "/").removeprefix("knowledge/")
            family = canonical_source_family(knowledge_root / relative, knowledge_root)
            if family.startswith("machine/") or (family.startswith("raw/") and Path(relative).suffix):
                sources.add(relative)
    return sorted(sources)[:MAX_COMPILED_FROM]


def _write_page(path: Path, front_matter: str, title: str, lines: list[str]) -> Path:
    """Input: output path, metadata, title, body lines. Output: written human wiki page path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(front_matter + "\n" + f"# {title}\n\n" + "\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def select_research_case_records(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Input: research ledger rows and limit. Output: selected rows. Pick learning-worthy research cases."""
    latest_by_run: dict[str, dict[str, Any]] = {}
    for row in rows:
        run_id = str(row.get("run_id", ""))
        existing = latest_by_run.get(run_id)
        if existing is None or _research_snapshot_key(row) > _research_snapshot_key(existing):
            latest_by_run[run_id] = row
    return sorted(
        [
            row
            for row in latest_by_run.values()
            if str(row.get("case_reason", "")) in CASE_REASON_PRIORITY
        ],
        key=lambda row: (
            CASE_REASON_PRIORITY[str(row.get("case_reason", ""))],
            -_research_synced_at_seconds(row),
            str(row.get("run_id", "")),
        ),
    )[:max(int(limit), 0)]


def _research_snapshot_key(row: dict[str, Any]) -> tuple[float, str]:
    """Input: ledger row. Output: sortable key. Pick a deterministic latest snapshot for one run."""
    return _research_synced_at_seconds(row), json.dumps(
        row, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
    )


def _research_synced_at_seconds(row: dict[str, Any]) -> float:
    """Input: ledger row. Output: UTC seconds. Normalize a sync timestamp for deterministic ordering."""
    value = str(row.get("synced_at", "")).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (OSError, ValueError):
        return float("-inf")


def _lesson_from_case_reason(reason: str, failed: list[str]) -> str:
    """Input: case reason and failed checks. Output: reusable lesson text. Convert one record outcome into bounded guidance."""
    failed_text = ", ".join(failed) if failed else "the recorded checks"
    if reason == "submitted_or_approved":
        return "Record the submitted or approved result so later work can distinguish validated ideas from untested variants."
    if reason == "near_miss":
        return f"Treat a stable near miss as a bounded repair candidate; address {failed_text} before expanding the family."
    if reason == "repair_loop":
        return "Change one repair lever at a time and retain every version so the next decision has comparable evidence."
    return f"Convert repeated failure on {failed_text} into a named workflow rule instead of recreating the same candidate."


def _case_report_text(row: dict[str, Any], generated_at: str) -> str:
    """Input: research row and timestamp. Output: compact Markdown case report."""
    run_id = str(row.get("run_id", ""))
    objective = str(row.get("objective", ""))
    reason = str(row.get("case_reason", ""))
    failed = sorted({
        str(item)
        for triage in row.get("triage", [])
        if isinstance(triage, dict)
        for item in triage.get("failed", [])
    })
    front = _front_matter(
        generated_at,
        ["machine/research_records.jsonl"],
        ["human_learning", "workflow_review"],
    )
    return "\n".join([
        front.rstrip(),
        f"# Research Case {run_id}",
        "",
        f"- Objective: {objective}",
        f"- Case Reason: {reason}",
        f"- Failed Checks: {', '.join(failed) if failed else 'none recorded'}",
        f"- Run ID: `{run_id}`",
        "",
        "## Reusable Lesson",
        "",
        _lesson_from_case_reason(reason, failed),
        "",
    ]) + "\n"


def compile_research_case_reports(
    knowledge_root: str | Path,
    generated_at: str,
    limit: int,
) -> list[Path]:
    """Input: knowledge root, timestamp, limit. Output: report paths. Compile selected research cases for humans."""
    root = Path(knowledge_root)
    rows = load_research_record_ledger(root)
    reports: list[Path] = []
    selected_paths: set[Path] = set()
    for row in select_research_case_records(rows, limit):
        run_id = str(row.get("run_id", "")).replace("/", "_").replace("\\", "_")
        path = root / CASE_REPORT_DIR / f"{run_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_case_report_text(row, generated_at), encoding="utf-8")
        reports.append(path)
        selected_paths.add(path)
    reports_dir = root / CASE_REPORT_DIR
    if reports_dir.exists():
        for path in reports_dir.rglob("*.md"):
            if path not in selected_paths:
                path.unlink()
    return reports


def compile_human_experience_wiki(
    knowledge_root: str | Path,
    generated_at: str | None = None,
    max_case_reports: int = 20,
) -> dict[str, Any]:
    """Input: knowledge root, timestamp, case limit. Output: compact human wiki compile summary."""
    root = Path(knowledge_root)
    generated = generated_at or _now()
    ledger_rows = _read_jsonl_rows(existing_machine_resource_path(root, "data_ledger"))
    template_rows = _read_jsonl_rows(existing_machine_resource_path(root, "template_library"))
    benchmark_rows = _read_jsonl_rows(existing_machine_resource_path(root, "benchmark_rules"))

    data_sources = _canonical_sources(root, ["data_ledger"], ledger_rows, "source_paths")
    template_sources = _canonical_sources(root, ["template_library"], template_rows, "source_paths")
    benchmark_sources = _canonical_sources(root, ["benchmark_rules"], benchmark_rows, "evidence_paths")
    workflow_sources = sorted(set(data_sources + template_sources + benchmark_sources))
    engineering_sources = workflow_sources

    underexplored = sorted(
        ledger_rows,
        key=lambda row: (
            int(row.get("submitted_usage_count", 0) or 0),
            int(row.get("simulation_usage_count", 0) or 0),
            _safe_text(row.get("data_category") or row.get("dataset_id")),
        ),
    )[:12]
    underexplored_labels = [
        _safe_text(row.get("data_category") or row.get("dataset_id")) for row in underexplored if _safe_text(row.get("data_category") or row.get("dataset_id"))
    ]
    benchmark_actions = [
        f"- **{_safe_text(row.get('rule_id'))}:** {_safe_text(row.get('action'))} "
        f"(issues: {', '.join(_safe_text(item) for item in row.get('issue_types', []) if _safe_text(item)) or 'unclassified'})"
        for row in benchmark_rows[:20]
    ]
    if not benchmark_actions:
        benchmark_actions = ["- No persisted benchmark rules are available yet."]

    page_paths = [
        _write_page(
            root / HUMAN_WIKI_FILES["start_here"],
            _front_matter(generated, workflow_sources, ["human_learning", "workflow_maintenance"]),
            "Start Here",
            [
                "This wiki keeps the research workflow understandable without duplicating machine ledgers.",
                "",
                "## Normal Operation",
                "- Use the Console to inspect readiness, choose a bounded research option, and resume the saved workflow state.",
                "- Treat readiness blockers as work items; do not bypass them with inferred coverage or live submissions.",
                "",
                "## Highest-Signal Principles",
                "- Prefer simple economic logic and distinct data-template combinations.",
                "- Promote stable near misses into a controlled repair loop instead of repeating the same batch.",
                "- Keep machine records complete and human pages limited to reusable decisions.",
            ],
        ),
        _write_page(
            root / HUMAN_WIKI_FILES["factor_principles"],
            _front_matter(generated, template_sources + benchmark_sources, ["research_planner", "candidate_gate"]),
            "Factor Principles",
            [
                "- Start from a plain economic claim that the selected field can express.",
                "- Require novelty against self-correlation and production correlation before scaling a family.",
                "- Promote stable PnL near misses to repair review; change one repair lever at a time.",
                "- Use batches of 30 candidates so outcomes are comparable while the search remains bounded.",
            ],
        ),
        _write_page(
            root / HUMAN_WIKI_FILES["data_semantics"],
            _front_matter(generated, data_sources, ["research_planner", "template_selection"]),
            "Data Semantics",
            [
                "## Recurring Semantic Tags",
                *_bullets(_count_list_values(ledger_rows, "semantic_tags"), "No ledger tags are available yet."),
                "",
                "## Field Type Mix",
                *_bullets(_count_scalar_values(ledger_rows, "field_type"), "No field types are available yet."),
                "",
                "## Underexplored Categories",
                *_bullets(underexplored_labels, "No underexplored categories are available yet."),
            ],
        ),
        _write_page(
            root / HUMAN_WIKI_FILES["template_operator_patterns"],
            _front_matter(generated, template_sources, ["research_planner", "repair_loop"]),
            "Template And Operator Patterns",
            [
                "## Template Families",
                *_bullets(_count_scalar_values(template_rows, "template_family"), "No template families are available yet."),
                "",
                "## Operator Compositions",
                *_bullets(_count_list_values(template_rows, "operator_tags"), "No operator patterns are available yet."),
                "",
                "## Repair Levers",
                *_bullets(_count_list_values(template_rows, "repair_levers"), "No repair levers are available yet."),
                "",
                "## Crowding Notes",
                *_bullets(_count_scalar_values(template_rows, "correlation_risk"), "Classify crowding risk before expanding a template family."),
            ],
        ),
        _write_page(
            root / HUMAN_WIKI_FILES["benchmark_repair_rules"],
            _front_matter(generated, benchmark_sources, ["triage", "repair_loop", "candidate_gate"]),
            "Benchmark And Repair Rules",
            [
                "Use the active rulebook to turn a named issue type into one bounded next action.",
                "",
                *benchmark_actions,
            ],
        ),
        _write_page(
            root / HUMAN_WIKI_FILES["engineering_lessons"],
            _front_matter(generated, engineering_sources, ["workflow_maintenance", "human_learning"]),
            "Engineering Lessons",
            [
                "- Recover context from durable task and milestone records before making workflow changes.",
                "- Keep milestone state current so the next operator has the last verification evidence and exact next command.",
                "- Convert useful corrections, repeated blockers, and workflow bugs into durable notes, rules, tests, or proposals.",
                "- Capture data breadth-first across scopes before deepening one dataset, and record partial coverage explicitly.",
            ],
        ),
    ]
    case_report_paths = compile_research_case_reports(root, generated, max_case_reports)
    return {
        "generated_at": generated,
        "page_count": len(page_paths),
        "page_paths": [str(path) for path in page_paths],
        "case_report_count": len(case_report_paths),
        "case_report_paths": [str(path) for path in case_report_paths],
    }
