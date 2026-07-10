from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


PROPOSAL_JSONL = "workflow_change_proposals.jsonl"
PROPOSAL_MARKDOWN = "workflow_change_proposals.md"


@dataclass(frozen=True)
class WorkflowChangeProposal:
    proposal_id: str
    generated_at: str
    issue_type: str
    title: str
    trigger: str
    evidence_paths: list[str]
    affected_modules: list[str]
    proposed_rule_change: str
    expected_benefit: str
    risk: str
    required_code_changes: list[str]
    required_knowledge_updates: list[str]
    user_decision_options: list[str]
    status: str


def workflow_change_proposal_to_dict(proposal: WorkflowChangeProposal) -> dict[str, Any]:
    """Input: WorkflowChangeProposal. Output: dict[str, Any]. Convert proposal to JSON-safe data."""
    return asdict(proposal)


def _rule_text(issue_type: str, summary: str) -> tuple[str, str, str]:
    """Input: issue type and summary. Output: rule, benefit, risk. Map repeated issue to proposal text."""
    normalized = issue_type.lower()
    if "prod_correlation" in normalized:
        return (
            "Down-rank data-template pairs that repeatedly fail production correlation, and require a distinct data source, operator skeleton, or economic hypothesis before reusing them.",
            "Reduces wasted production-correlation checks and pushes novelty upstream.",
            "May suppress a repairable family if the evidence window is too small.",
        )
    if "self_correlation" in normalized:
        return (
            "Require local self-correlation proxy review before scheduling data or templates overlapping with submitted alpha families.",
            "Reduces candidate loss from avoidable self-correlation failures.",
            "May over-penalize fields that can pass with a materially better Sharpe.",
        )
    if "pnl_signal" in normalized:
        return (
            "Increase repair priority when stable PnL evidence exists even if a single metric is below threshold.",
            "Prevents discarding signal-bearing near-miss alphas.",
            "May spend repair budget on visually appealing but fragile in-sample signals.",
        )
    return (
        f"Review this issue and add a workflow rule if it repeats: {summary}",
        "Captures new workflow knowledge before the same issue recurs.",
        "Manual review is needed because the issue class is not yet mapped.",
    )


def proposal_from_issue(issue: dict[str, Any], generated_at: str) -> WorkflowChangeProposal:
    """Input: issue dict and timestamp. Output: proposal. Convert one research issue into a reviewable rule proposal."""
    issue_type = str(issue.get("issue_type", "manual_review"))
    summary = str(issue.get("summary", "Unclassified workflow issue."))
    evidence_paths = [str(item) for item in issue.get("evidence_paths", []) if str(item)]
    affected_modules = [str(item) for item in issue.get("affected_modules", []) if str(item)]
    proposed_rule_change, expected_benefit, risk = _rule_text(issue_type, summary)
    proposal_id = f"{generated_at[:10]}-{issue_type.replace('_', '-')}"
    return WorkflowChangeProposal(
        proposal_id=proposal_id,
        generated_at=generated_at,
        issue_type=issue_type,
        title=summary,
        trigger=summary,
        evidence_paths=evidence_paths,
        affected_modules=affected_modules,
        proposed_rule_change=proposed_rule_change,
        expected_benefit=expected_benefit,
        risk=risk,
        required_code_changes=affected_modules,
        required_knowledge_updates=["knowledge/wiki/50_benchmarks", "knowledge/wiki/60_workflows"],
        user_decision_options=["accept", "reject", "revise", "defer"],
        status="proposed",
    )


def _proposal_markdown(proposal: WorkflowChangeProposal) -> str:
    """Input: proposal. Output: Markdown string. Render one workflow-change proposal for review."""
    evidence = "\n".join(f"- `{path}`" for path in proposal.evidence_paths) or "- none recorded"
    modules = ", ".join(proposal.affected_modules) or "manual_review"
    options = ", ".join(proposal.user_decision_options)
    return (
        f"## {proposal.title}\n\n"
        f"- Proposal ID: `{proposal.proposal_id}`\n"
        f"- Status: `{proposal.status}`\n"
        f"- Issue Type: `{proposal.issue_type}`\n"
        f"- Affected Modules: {modules}\n\n"
        f"### Trigger\n{proposal.trigger}\n\n"
        f"### Evidence\n{evidence}\n\n"
        f"### Proposed Rule Change\n{proposal.proposed_rule_change}\n\n"
        f"### Expected Benefit\n{proposal.expected_benefit}\n\n"
        f"### Risk\n{proposal.risk}\n\n"
        f"### User Decision Options\n{options}\n"
    )


def write_workflow_proposals(output_dir: Path, proposals: list[WorkflowChangeProposal]) -> tuple[Path, Path]:
    """Input: output dir and proposals. Output: JSONL and Markdown paths. Persist workflow proposal artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / PROPOSAL_JSONL
    markdown_path = output_dir / PROPOSAL_MARKDOWN
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for proposal in proposals:
            handle.write(json.dumps(workflow_change_proposal_to_dict(proposal), ensure_ascii=False, sort_keys=True) + "\n")
    markdown = ["# Workflow Change Proposals", ""]
    for proposal in proposals:
        markdown.append(_proposal_markdown(proposal))
    markdown_path.write_text("\n\n".join(markdown), encoding="utf-8")
    return jsonl_path, markdown_path
