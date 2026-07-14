from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResearchRecord:
    run_id: str
    objective: str
    backtest: list[dict[str, Any]] = field(default_factory=list)
    triage: list[dict[str, Any]] = field(default_factory=list)
    repair: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    candidate_gate: list[dict[str, Any]] = field(default_factory=list)
    user_approval: list[dict[str, Any]] = field(default_factory=list)
    approved_queue: list[dict[str, Any]] = field(default_factory=list)
    manual_submission_status: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failures(self) -> list[dict[str, Any]]:
        """Input: record. Output: triage rows. Preserve the legacy failures accessor."""
        return self.triage

    @property
    def alpha_results(self) -> list[dict[str, Any]]:
        """Input: record. Output: backtest rows. Preserve the legacy alpha-results accessor."""
        return self.backtest

    @property
    def repairs(self) -> dict[str, list[dict[str, Any]]]:
        """Input: record. Output: repair map. Preserve the legacy repairs accessor."""
        return self.repair

    @property
    def approvals(self) -> list[dict[str, Any]]:
        """Input: record. Output: approval rows. Preserve the legacy approvals accessor."""
        return self.user_approval

    @property
    def queue_updates(self) -> list[dict[str, Any]]:
        """Input: record. Output: queue rows. Preserve the legacy queue accessor."""
        return self.approved_queue


def empty_research_record(run_id: str, objective: str) -> ResearchRecord:
    """Input: run id and objective. Output: ResearchRecord. Create an empty research record."""
    return ResearchRecord(run_id=str(run_id), objective=str(objective))


def record_alpha_result(record: ResearchRecord, alpha_row: dict[str, object]) -> ResearchRecord:
    """Input: record and alpha row. Output: updated record. Store alpha result with compact failure summaries."""
    row = dict(alpha_row)
    results = [*record.backtest, row]
    triage = list(record.triage)
    if not bool(row.get("hard_pass", False)):
        triage.append(
            {
                "alpha_id": row.get("alpha_id", ""),
                "expression_hash": row.get("expression_hash", ""),
                "benchmark_label": row.get("benchmark_label", ""),
                "metrics": row.get("metrics", {}),
                "failed": row.get("failed", []),
            }
        )
    return replace(record, backtest=results, triage=triage)


def record_repair_version(
    record: ResearchRecord,
    candidate_id: str,
    version: int,
    expression_hash: str,
    hypothesis: str,
    result: dict[str, object],
) -> ResearchRecord:
    """Input: record and repair version. Output: updated record. Store one unique repair version."""
    repairs = {key: list(value) for key, value in record.repair.items()}
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
    return replace(record, repair=repairs)


def record_candidate_gate(record: ResearchRecord, candidate: dict[str, object], decision: str, reasons: list[str]) -> ResearchRecord:
    """Input: record, candidate, decision, reasons. Output: updated record. Store one gate decision."""
    row = dict(candidate)
    row["decision"] = str(decision)
    row["reasons"] = [str(item) for item in reasons]
    identity = _candidate_gate_identity(row)
    if any(_candidate_gate_identity(existing) == identity for existing in record.candidate_gate):
        return record
    return replace(record, candidate_gate=[*record.candidate_gate, row])


def record_approval(record: ResearchRecord, approval: dict[str, object]) -> ResearchRecord:
    """Input: record and approval. Output: updated record. Store user approval evidence."""
    identity = _candidate_identity(approval)
    if any(_candidate_identity(row) == identity for row in record.user_approval):
        return record
    return replace(record, user_approval=[*record.user_approval, dict(approval)])


def record_queue_update(record: ResearchRecord, queue_row: dict[str, object]) -> ResearchRecord:
    """Input: record and queue row. Output: updated record. Store approved queue update."""
    candidate_identity = _candidate_identity(queue_row)
    latest = next(
        (
            row
            for row in reversed(record.approved_queue)
            if _candidate_identity(row) == candidate_identity
        ),
        None,
    )
    if latest is not None and str(latest.get("status", "")) == str(queue_row.get("status", "")):
        return record
    return replace(record, approved_queue=[*record.approved_queue, dict(queue_row)])


def record_manual_submission_status(record: ResearchRecord, status_row: dict[str, object]) -> ResearchRecord:
    """Input: record and status row. Output: updated record. Store manual or API submission queue status."""
    candidate_identity = _candidate_identity(status_row)
    latest = next(
        (
            row
            for row in reversed(record.manual_submission_status)
            if _candidate_identity(row) == candidate_identity
        ),
        None,
    )
    if latest is not None and str(latest.get("status", "")) == str(status_row.get("status", "")):
        return record
    return replace(
        record,
        manual_submission_status=[*record.manual_submission_status, dict(status_row)],
    )


def _candidate_identity(row: dict[str, object]) -> tuple[str, str, str, str, str]:
    """Input: approval or queue row. Output: exact candidate identity. Normalize durable record keys."""
    return (
        str(row.get("candidate_id", "")),
        str(row.get("platform_alpha_id", "")),
        str(row.get("version", "")),
        str(row.get("expression_hash", "")),
        str(row.get("source_run_id", "")),
    )


def _candidate_gate_identity(row: dict[str, object]) -> tuple[str, str, str, str, str, str]:
    """Input: candidate-gate row. Output: full gate identity. Include decision for idempotent gate records."""
    return (*_candidate_identity(row), str(row.get("decision", "")))


def write_research_record(path: str | Path, record: ResearchRecord) -> Path:
    """Input: path and record. Output: written path. Persist machine-readable research record."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(
        json.dumps(asdict(record), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp.replace(target)
    return target


def load_research_record(path: str | Path) -> ResearchRecord:
    """Input: path. Output: ResearchRecord. Load a machine-readable research record."""
    row = json.loads(Path(path).read_text(encoding="utf-8"))
    return ResearchRecord(
        run_id=str(row["run_id"]),
        objective=str(row.get("objective", "")),
        backtest=list(row.get("backtest", row.get("alpha_results", []))),
        triage=list(row.get("triage", row.get("failures", []))),
        repair=dict(row.get("repair", row.get("repairs", {}))),
        candidate_gate=list(row.get("candidate_gate", [])),
        user_approval=list(row.get("user_approval", row.get("approvals", []))),
        approved_queue=list(row.get("approved_queue", row.get("queue_updates", []))),
        manual_submission_status=list(row.get("manual_submission_status", [])),
    )


def render_research_record_markdown(record: ResearchRecord) -> str:
    """Input: record. Output: Markdown. Render research findings for raw knowledge sync."""
    lines = [
        "# Research Record",
        "",
        f"- Run ID: `{record.run_id}`",
        f"- Objective: {record.objective}",
        "",
        "## Backtest",
    ]
    for row in record.backtest:
        lines.append(f"- `{row.get('alpha_id', '')}` `{row.get('expression_hash', '')}`")
    lines.extend(["", "## Triage", ""])
    for row in record.triage:
        lines.append(f"- `{row.get('alpha_id', '')}` {row.get('decision', row.get('benchmark_label', ''))}")
    lines.extend(["", "## Repair", ""])
    for candidate_id, rows in record.repair.items():
        lines.append(f"### {candidate_id}")
        for row in rows:
            lines.append(
                f"- version `{row.get('version', '')}` hash `{row.get('expression_hash', '')}` "
                f"hypothesis: {row.get('hypothesis', '')}"
            )
    lines.extend(["", "## Candidate Gate", ""])
    for row in record.candidate_gate:
        lines.append(f"- `{row.get('candidate_id', '')}` {row.get('decision', '')}: {', '.join(row.get('reasons', []))}")
    lines.extend(["", "## User Approval", ""])
    for row in record.user_approval:
        lines.append(f"- `{row.get('candidate_id', '')}` hash `{row.get('expression_hash', '')}`")
    lines.extend(["", "## Approved Queue", ""])
    for row in record.approved_queue:
        lines.append(f"- `{row.get('candidate_id', '')}` status `{row.get('status', '')}`")
    lines.extend(["", "## Manual Submission Status", ""])
    for row in record.manual_submission_status:
        lines.append(f"- `{row.get('candidate_id', '')}` status `{row.get('status', '')}`")
    return "\n".join(lines) + "\n"


def sync_research_record_to_raw(record: ResearchRecord, raw_root: str | Path) -> Path:
    """Input: record and raw root. Output: Markdown path. Write raw research record into knowledge raw."""
    path = Path(raw_root) / "research" / "runs" / record.run_id / "research_record.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_research_record_markdown(record), encoding="utf-8")
    return path
