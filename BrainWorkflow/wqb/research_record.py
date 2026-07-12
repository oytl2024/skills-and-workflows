from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResearchRecord:
    run_id: str
    objective: str
    failures: list[dict[str, Any]] = field(default_factory=list)
    alpha_results: list[dict[str, Any]] = field(default_factory=list)
    repairs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    candidate_gate: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    queue_updates: list[dict[str, Any]] = field(default_factory=list)


def empty_research_record(run_id: str, objective: str) -> ResearchRecord:
    """Input: run id and objective. Output: ResearchRecord. Create an empty research record."""
    return ResearchRecord(run_id=str(run_id), objective=str(objective))


def record_alpha_result(record: ResearchRecord, alpha_row: dict[str, object]) -> ResearchRecord:
    """Input: record and alpha row. Output: updated record. Store alpha result with compact failure summaries."""
    row = dict(alpha_row)
    results = [*record.alpha_results, row]
    failures = list(record.failures)
    if not bool(row.get("hard_pass", False)):
        failures.append(
            {
                "alpha_id": row.get("alpha_id", ""),
                "expression_hash": row.get("expression_hash", ""),
                "benchmark_label": row.get("benchmark_label", ""),
                "metrics": row.get("metrics", {}),
                "failed": row.get("failed", []),
            }
        )
    return replace(record, alpha_results=results, failures=failures)


def record_repair_version(
    record: ResearchRecord,
    candidate_id: str,
    version: int,
    expression_hash: str,
    hypothesis: str,
    result: dict[str, object],
) -> ResearchRecord:
    """Input: record and repair version. Output: updated record. Store one unique repair version."""
    repairs = {key: list(value) for key, value in record.repairs.items()}
    rows = repairs.setdefault(str(candidate_id), [])
    identity = (int(version), str(expression_hash))
    if not any((int(row["version"]), str(row["expression_hash"])) == identity for row in rows):
        rows.append(
            {
                "candidate_id": str(candidate_id),
                "version": int(version),
                "expression_hash": str(expression_hash),
                "hypothesis": str(hypothesis),
                "result": dict(result),
            }
        )
    return replace(record, repairs=repairs)


def record_candidate_gate(record: ResearchRecord, candidate: dict[str, object], decision: str, reasons: list[str]) -> ResearchRecord:
    """Input: record, candidate, decision, reasons. Output: updated record. Store one gate decision."""
    row = dict(candidate)
    row["decision"] = str(decision)
    row["reasons"] = [str(item) for item in reasons]
    return replace(record, candidate_gate=[*record.candidate_gate, row])


def record_approval(record: ResearchRecord, approval: dict[str, object]) -> ResearchRecord:
    """Input: record and approval. Output: updated record. Store user approval evidence."""
    return replace(record, approvals=[*record.approvals, dict(approval)])


def record_queue_update(record: ResearchRecord, queue_row: dict[str, object]) -> ResearchRecord:
    """Input: record and queue row. Output: updated record. Store approved queue update."""
    return replace(record, queue_updates=[*record.queue_updates, dict(queue_row)])


def write_research_record(path: str | Path, record: ResearchRecord) -> Path:
    """Input: path and record. Output: written path. Persist machine-readable research record."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target


def load_research_record(path: str | Path) -> ResearchRecord:
    """Input: path. Output: ResearchRecord. Load a machine-readable research record."""
    row = json.loads(Path(path).read_text(encoding="utf-8"))
    return ResearchRecord(**row)


def render_research_record_markdown(record: ResearchRecord) -> str:
    """Input: record. Output: Markdown. Render research findings for raw knowledge sync."""
    lines = [
        "# Research Record",
        "",
        f"- Run ID: `{record.run_id}`",
        f"- Objective: {record.objective}",
        "",
        "## Failures",
    ]
    for failure in record.failures:
        lines.append(f"- `{failure.get('alpha_id', '')}` `{failure.get('expression_hash', '')}` {failure.get('benchmark_label', '')}")
    lines.extend(["", "## Repair", ""])
    for candidate_id, rows in record.repairs.items():
        lines.append(f"### {candidate_id}")
        for row in rows:
            lines.append(f"- version `{row['version']}` hash `{row['expression_hash']}` hypothesis: {row['hypothesis']}")
    lines.extend(["", "## Candidate Gate", ""])
    for row in record.candidate_gate:
        lines.append(f"- `{row.get('candidate_id', '')}` {row.get('decision', '')}: {', '.join(row.get('reasons', []))}")
    lines.extend(["", "## User Approval", ""])
    for row in record.approvals:
        lines.append(f"- `{row.get('candidate_id', '')}` hash `{row.get('expression_hash', '')}`")
    lines.extend(["", "## Approved Queue", ""])
    for row in record.queue_updates:
        lines.append(f"- `{row.get('candidate_id', '')}` status `{row.get('status', '')}`")
    return "\n".join(lines) + "\n"


def sync_research_record_to_raw(record: ResearchRecord, raw_root: str | Path) -> Path:
    """Input: record and raw root. Output: Markdown path. Write raw research record into knowledge raw."""
    path = Path(raw_root) / "research" / "runs" / record.run_id / "research_record.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_research_record_markdown(record), encoding="utf-8")
    return path
