from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from wqb.benchmark_rules import default_benchmark_rules, rules_for_consumer, rules_for_issue_type


PROPOSAL_JSONL = "workflow_change_proposals.jsonl"
PROPOSAL_MARKDOWN = "workflow_change_proposals.md"
PROPOSAL_STATUSES = (
    "proposed",
    "rejected",
    "accepted_for_wiki",
    "accepted_for_implementation",
    "accepted_as_experiment",
    "applied",
    "deferred",
)


def normalize_proposal_status(status: str) -> str:
    """Input: status string. Output: normalized status. Validate proposal lifecycle status."""
    normalized = str(status).strip().lower()
    if normalized == "accepted":
        normalized = "accepted_for_implementation"
    if normalized not in PROPOSAL_STATUSES:
        raise ValueError(f"unsupported proposal status: {status}")
    return normalized


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
    user_decision: str = ""
    current_behavior: str = ""
    expected_impact: str = ""
    applied_at: str = ""
    supersedes: list[str] | None = None


def workflow_change_proposal_to_dict(proposal: WorkflowChangeProposal) -> dict[str, Any]:
    """Input: WorkflowChangeProposal. Output: dict[str, Any]. Convert proposal to JSON-safe data."""
    return asdict(proposal)


def _rule_text(
    issue_type: str,
    summary: str,
    benchmark_rules: list[Any] | None = None,
) -> tuple[str, str, str]:
    """Input: issue, summary, optional active rules. Output: rule, benefit, risk. Apply benchmark authority."""
    active_rules = default_benchmark_rules() if benchmark_rules is None else benchmark_rules
    proposal_rules = rules_for_consumer(active_rules, "workflow_proposals")
    matched_rules = rules_for_issue_type(proposal_rules, issue_type)
    if matched_rules:
        rule = matched_rules[0]
        return (
            rule.action,
            f"Applies active benchmark rule `{rule.rule_id}` before the issue recurs.",
            rule.risk,
        )
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


def proposal_from_issue(
    issue: dict[str, Any],
    generated_at: str,
    benchmark_rules: list[Any] | None = None,
) -> WorkflowChangeProposal:
    """Input: issue, timestamp, optional active rules. Output: proposal. Convert an issue using rule authority."""
    issue_type = str(issue.get("issue_type", "manual_review"))
    summary = str(issue.get("summary", "Unclassified workflow issue."))
    evidence_paths = [str(item) for item in issue.get("evidence_paths", []) if str(item)]
    affected_modules = [str(item) for item in issue.get("affected_modules", []) if str(item)]
    proposed_rule_change, expected_benefit, risk = _rule_text(issue_type, summary, benchmark_rules)
    identity = json.dumps(
        {"issue_type": issue_type, "summary": summary, "evidence_paths": evidence_paths},
        ensure_ascii=False,
        sort_keys=True,
    )
    proposal_id = f"{generated_at[:10]}-{issue_type.replace('_', '-')}-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]}"
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
        user_decision_options=["accepted_for_wiki", "accepted_for_implementation", "accepted_as_experiment", "rejected", "deferred"],
        status="proposed",
        current_behavior=summary,
        expected_impact=expected_benefit,
        applied_at="",
        supersedes=[],
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


def _proposal_from_dict(row: dict[str, Any]) -> WorkflowChangeProposal:
    """Input: persisted proposal dict. Output: WorkflowChangeProposal. Rebuild a proposal for Markdown rendering."""
    return WorkflowChangeProposal(
        proposal_id=str(row.get("proposal_id", "")),
        generated_at=str(row.get("generated_at", "")),
        issue_type=str(row.get("issue_type", "manual_review")),
        title=str(row.get("title", "")),
        trigger=str(row.get("trigger", "")),
        evidence_paths=[str(item) for item in row.get("evidence_paths", []) if str(item)],
        affected_modules=[str(item) for item in row.get("affected_modules", []) if str(item)],
        proposed_rule_change=str(row.get("proposed_rule_change", "")),
        expected_benefit=str(row.get("expected_benefit", "")),
        risk=str(row.get("risk", "")),
        required_code_changes=[str(item) for item in row.get("required_code_changes", []) if str(item)],
        required_knowledge_updates=[str(item) for item in row.get("required_knowledge_updates", []) if str(item)],
        user_decision_options=[str(item) for item in row.get("user_decision_options", []) if str(item)],
        status=(
            normalize_proposal_status(str(row.get("status", "proposed")))
            if str(row.get("status", "proposed")).strip().lower() in {*PROPOSAL_STATUSES, "accepted"}
            else str(row.get("status", "proposed"))
        ),
        user_decision=str(row.get("user_decision", "")),
        current_behavior=str(row.get("current_behavior", "")),
        expected_impact=str(row.get("expected_impact", "")),
        applied_at=str(row.get("applied_at", "")),
        supersedes=[str(item) for item in (row.get("supersedes") or []) if str(item)],
    )


def write_workflow_proposals(output_dir: Path, proposals: list[WorkflowChangeProposal]) -> tuple[Path, Path]:
    """Input: output dir and proposals. Output: JSONL and Markdown paths. Persist workflow proposal artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / PROPOSAL_JSONL
    markdown_path = output_dir / PROPOSAL_MARKDOWN
    rows: list[dict[str, Any]] = []
    row_indexes: dict[str, int] = {}
    if jsonl_path.exists():
        for row in load_workflow_proposals(output_dir):
            row_indexes[str(row.get("proposal_id", ""))] = len(rows)
            rows.append(row)
    for proposal in proposals:
        incoming = workflow_change_proposal_to_dict(proposal)
        proposal_id = proposal.proposal_id
        if proposal_id in row_indexes:
            existing = rows[row_indexes[proposal_id]]
            merged = dict(existing)
            merged.update(incoming)
            for field_name in ("status", "user_decision"):
                if field_name in existing:
                    merged[field_name] = existing[field_name]
            rows[row_indexes[proposal_id]] = merged
        else:
            row_indexes[proposal_id] = len(rows)
            rows.append(incoming)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    markdown = ["# Workflow Change Proposals", ""]
    for row in rows:
        markdown.append(_proposal_markdown(_proposal_from_dict(row)))
    markdown_path.write_text("\n\n".join(markdown), encoding="utf-8")
    return jsonl_path, markdown_path


def load_workflow_proposals(output_dir: str | Path) -> list[dict[str, Any]]:
    """Input: proposal output dir. Output: proposal rows. Load persisted workflow proposal JSONL."""
    jsonl_path = Path(output_dir) / PROPOSAL_JSONL
    if not jsonl_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            status = str(row.get("status", "proposed"))
            if status.strip().lower() in {*PROPOSAL_STATUSES, "accepted"}:
                row["status"] = normalize_proposal_status(status)
            rows.append(row)
    return rows


def update_workflow_proposal_decision(
    output_dir: str | Path,
    proposal_id: str,
    status: str,
    user_decision: str,
) -> tuple[Path, Path]:
    """Input: output dir, proposal id, status, decision. Output: artifact paths. Persist user decision."""
    normalized_status = normalize_proposal_status(status)
    rows = load_workflow_proposals(output_dir)
    matched = False
    for row in rows:
        if str(row.get("proposal_id", "")) == str(proposal_id):
            row["status"] = normalized_status
            row["user_decision"] = str(user_decision)
            matched = True
            break
    if not matched:
        raise ValueError(f"proposal not found: {proposal_id}")
    proposals = [_proposal_from_dict(row) for row in rows]
    jsonl_path = Path(output_dir) / PROPOSAL_JSONL
    markdown_path = Path(output_dir) / PROPOSAL_MARKDOWN
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    markdown = ["# Workflow Change Proposals", ""]
    for proposal in proposals:
        markdown.append(_proposal_markdown(proposal))
    markdown_path.write_text("\n\n".join(markdown), encoding="utf-8")
    return jsonl_path, markdown_path
