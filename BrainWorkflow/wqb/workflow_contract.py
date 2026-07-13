from __future__ import annotations

from pathlib import Path


RUN_STATUSES = (
    "created",
    "running",
    "waiting_for_user",
    "paused",
    "completed",
    "completed_with_warnings",
    "failed",
    "aborted",
)

STAGE_NAMES = (
    "objective_selected",
    "schedule",
    "scout_seed",
    "batch_generation",
    "backtest",
    "triage",
    "repair",
    "candidate_gate",
    "user_approval",
    "approved_queue",
    "research_record_sync",
    "complete",
)

STAGE_STATUSES = (
    "not_started",
    "running",
    "completed",
    "paused",
    "failed",
    "skipped",
)

LEGAL_RUN_TRANSITIONS = {
    "created": ("running", "aborted"),
    "running": ("waiting_for_user", "paused", "completed", "completed_with_warnings", "failed", "aborted"),
    "waiting_for_user": ("running", "aborted"),
    "paused": ("running", "failed", "aborted"),
    "failed": ("aborted",),
    "completed": (),
    "completed_with_warnings": (),
    "aborted": (),
}

APPROVAL_REQUIRED_FIELDS = (
    "candidate_id",
    "platform_alpha_id",
    "version",
    "expression_hash",
    "approved_at",
    "approved_by",
    "source_run_id",
)

RESEARCH_RECORD_SECTIONS = (
    "backtest",
    "triage",
    "repair",
    "candidate_gate",
    "user_approval",
    "approved_queue",
    "manual_submission_status",
)


def render_workflow_contract_pages() -> dict[str, str]:
    """Input: none. Output: Markdown pages. Render durable workflow contract text."""
    workflow = "\n".join(
        [
            "# Long Term Workflow Contract",
            "",
            "Research flow: Knowledge Maintenance -> Research Planner -> Option Cards -> User Selects Objective -> Schedule Research -> Scout / Seed -> 30 Alpha Batch -> Multisim / Backtest -> Triage -> Repair Near-Miss -> Candidate Gate -> User Approval -> Approved Candidate Queue -> Research Record.",
            "",
            "Codex chat context is never a source of truth. A new session must recover from run files and the knowledge wiki.",
            "",
        ]
    )
    state = "\n".join(
        [
            "# Workflow State Machine",
            "",
            "Only the Orchestrator may write official run_state.json.",
            "",
            "Run statuses: " + ", ".join(RUN_STATUSES),
            "",
            "Stage names: " + ", ".join(STAGE_NAMES),
            "",
            "Stage statuses: " + ", ".join(STAGE_STATUSES),
            "",
            "Legal run transitions:",
            *[
                f"- {source} -> {target}"
                for source, targets in LEGAL_RUN_TRANSITIONS.items()
                for target in targets
            ],
            "",
        ]
    )
    record = "\n".join(
        [
            "# Research Record Schema",
            "",
            "The Research Record stores backtest, triage, repair, candidate gate, user approval, approved queue, and manual submission status.",
            "",
            "Obvious failures are compact summaries. near-miss and repair branches keep original expression, repair hypothesis, version history, checks, and final judgment.",
            "",
        ]
    )
    approval = "\n".join(
        [
            "# Candidate Approval Policy",
            "",
            "Approval binds an exact candidate_id, platform_alpha_id, version, and expression_hash.",
            "",
            "A changed expression hash invalidates the old approval.",
            "",
            "Required fields: " + ", ".join(APPROVAL_REQUIRED_FIELDS),
            "",
        ]
    )
    return {
        "long_term_workflow_contract.md": workflow,
        "workflow_state_machine.md": state,
        "research_record_schema.md": record,
        "candidate_approval_policy.md": approval,
    }


def write_workflow_contract_pages(output_root: str | Path) -> list[Path]:
    """Input: output root. Output: written paths. Write workflow contract Markdown pages."""
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, content in render_workflow_contract_pages().items():
        path = root / filename
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
