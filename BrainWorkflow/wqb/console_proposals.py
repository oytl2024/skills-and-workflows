from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wqb.workflow_proposals import WorkflowChangeProposal, proposal_from_issue, write_workflow_proposals


def _split_lines_or_commas(value: Any) -> list[str]:
    """Input: form value. Output: string list. Split textarea or comma-separated fields."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "")
    raw_items: list[str] = []
    for line in text.splitlines():
        raw_items.extend(line.split(","))
    return [item.strip() for item in raw_items if item.strip()]


def create_proposal_from_form(
    output_dir: str | Path,
    form: dict[str, Any],
    generated_at: str | None = None,
) -> WorkflowChangeProposal:
    """Input: proposal output dir and form fields. Output: proposal. Persist a workflow-change proposal."""
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    issue = {
        "issue_type": str(form.get("issue_type", "manual_review") or "manual_review"),
        "summary": str(form.get("summary", "Manual workflow review.") or "Manual workflow review."),
        "evidence_paths": _split_lines_or_commas(form.get("evidence_paths", "")),
        "affected_modules": _split_lines_or_commas(form.get("affected_modules", "")),
    }
    proposal = proposal_from_issue(issue, generated)
    write_workflow_proposals(Path(output_dir), [proposal])
    return proposal
