import re
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Iterable

from wqb.benchmark import REPAIRABLE_CHECKS, benchmark_alpha_record


STAGE_MAX_SIMULATIONS = {
    "scout": 30,
    "seed": 8,
    "discovery": 50,
    "repair": 8,
    "submit": 0,
}
SCOUT_MAX_LINES = 1
SCOUT_MAX_NESTING_DEPTH = 3
SCOUT_MAX_NUMERIC_PARAMS = 2
ISSUE_RULES = [
    (
        ("attempted to use unknown variable", "unknown variable"),
        "disable_regular_peer_templates",
        "Mark the field as missing its regular peer and skip fast-minus-regular templates.",
    ),
    (
        ("does not support event inputs", "does not support vector inputs"),
        "convert_event_or_vector_field",
        "Convert VECTOR/event fields with a supported reducer such as vec_avg before ranking.",
    ),
    (
        ("broad field search", "unintended field", "wrong field"),
        "use_exact_field_id",
        "Use --exact-field-id when a run must target one field instead of relying on text search.",
    ),
    (
        ("connectionreseterror", "network_error", "recoverable", "during poll"),
        "recover_in_flight_before_resubmit",
        "Run complete-in-flight for the existing run before submitting replacement simulations.",
    ),
    (
        ("http 429", "status_code 429", "rate limit", "rate_limited"),
        "cooldown_and_reduce_batch",
        "Stop the batch, keep submitted progress URLs, back off, and resume with a smaller batch.",
    ),
    (
        ("low_sharpe", "low_fitness"),
        "benchmark_signal_before_discard",
        "Run the stage benchmark first; repair stable PnL or near-threshold signals, discard only weak branches.",
    ),
]


@dataclass(frozen=True)
class WorkflowPrecheck:
    ok: bool
    reasons: list[str]
    line_count: int
    nesting_depth: int
    numeric_param_count: int


@dataclass(frozen=True)
class WorkflowTask:
    """Input: workflow fields. Output: immutable task record. Describe one assignable workflow unit."""

    task_id: str
    stage: str
    task_type: str
    owner: str
    description: str
    parallel_group: str
    depends_on: list[str]
    dataset_id: str = ""
    inputs: list[str] = dataclass_field(default_factory=list)
    outputs: list[str] = dataclass_field(default_factory=list)
    forbidden_actions: list[str] = dataclass_field(default_factory=list)
    promotion_gate: str = ""


def cap_simulation_count(stage: str, requested_count: int) -> int:
    """Input: workflow stage and requested count. Output: capped count. Enforce stage batch budgets."""
    normalized = stage.strip().lower()
    if normalized == "scout" and int(requested_count) > 0:
        return STAGE_MAX_SIMULATIONS["scout"]
    stage_cap = STAGE_MAX_SIMULATIONS.get(normalized, requested_count)
    return max(0, min(int(requested_count), stage_cap))


def stage_budget_summary() -> dict[str, int]:
    """Input: none. Output: stage cap mapping. Expose immutable simulation caps for UI and docs."""
    return dict(STAGE_MAX_SIMULATIONS)


def max_parenthesis_depth(expression: str) -> int:
    """Input: expression string. Output: int depth. Measure expression nesting by parentheses."""
    depth = 0
    max_depth = 0
    for char in expression:
        if char == "(":
            depth += 1
            max_depth = max(max_depth, depth)
        elif char == ")":
            depth = max(0, depth - 1)
    return max_depth


def numeric_param_count(expression: str) -> int:
    """Input: expression string. Output: unique numeric literal count. Estimate parameter complexity."""
    values = re.findall(r"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?(?![A-Za-z0-9_])", expression)
    return len(set(values))


def precheck_expression(expression: str, stage: str) -> WorkflowPrecheck:
    """Input: expression and workflow stage. Output: precheck result. Reject over-complex scout ideas."""
    line_count = len([line for line in expression.splitlines() if line.strip()])
    nesting_depth = max_parenthesis_depth(expression)
    param_count = numeric_param_count(expression)
    reasons: list[str] = []
    if stage.strip().lower() in {"scout", "seed"}:
        if line_count > SCOUT_MAX_LINES:
            reasons.append(f"line_count {line_count} exceeds {SCOUT_MAX_LINES}")
        if nesting_depth > SCOUT_MAX_NESTING_DEPTH:
            reasons.append(f"nesting_depth {nesting_depth} exceeds {SCOUT_MAX_NESTING_DEPTH}")
        if param_count > SCOUT_MAX_NUMERIC_PARAMS:
            reasons.append(f"numeric_param_count {param_count} exceeds {SCOUT_MAX_NUMERIC_PARAMS}")
    return WorkflowPrecheck(
        ok=not reasons,
        reasons=reasons,
        line_count=line_count,
        nesting_depth=nesting_depth,
        numeric_param_count=param_count,
    )


def build_parallel_stage_plan(stage: str, dataset_ids: Iterable[str]) -> list[WorkflowTask]:
    """Input: stage string and dataset ids. Output: task list. Split workflow work into parallel lanes."""
    normalized_stage = stage.strip().lower()
    clean_datasets = [dataset.strip() for dataset in dataset_ids if dataset and dataset.strip()]
    tasks: list[WorkflowTask] = []

    if normalized_stage == "scout":
        for index, dataset_id in enumerate(clean_datasets, start=1):
            task_id = f"scout:{index}:{dataset_id}"
            tasks.append(
                WorkflowTask(
                    task_id=task_id,
                    stage="scout",
                    task_type="data_scout",
                    owner="data-scout-agent",
                    description=(
                        "Run simple economic templates on a new dataset and save all run artifacts."
                    ),
                    parallel_group="new_data_scout",
                    depends_on=[],
                    dataset_id=dataset_id,
                    inputs=["dataset_id", "field_suffix", "template_mode", "human_idea"],
                    outputs=["run_dir", "field_ids", "progress_urls", "alpha_ids", "check_results"],
                    forbidden_actions=["submit_alpha", "promote_seed_without_diagnosis"],
                    promotion_gate="diagnosis-agent must confirm signal before Seed or Repair.",
                )
            )

        diagnosis_id = "scout:diagnosis"
        tasks.append(
            WorkflowTask(
                task_id=diagnosis_id,
                stage="scout",
                task_type="diagnosis",
                owner="diagnosis-agent",
                description="Compare Scout results, discard weak branches, and promote only signal-bearing seeds.",
                parallel_group="post_scout",
                depends_on=[task.task_id for task in tasks if task.task_type == "data_scout"],
                inputs=["scout_run_dirs", "all_alphas.jsonl", "run_errors.jsonl"],
                outputs=["promoted_seed_ids", "discarded_branches", "next_actions"],
                forbidden_actions=["submit_alpha", "run_new_simulation"],
                promotion_gate="Promote only hard-pass candidates or near-miss records with good core metrics.",
            )
        )
        tasks.append(
            WorkflowTask(
                task_id="scout:knowledge_update",
                stage="scout",
                task_type="knowledge_update",
                owner="knowledge-agent",
                description="Record platform issues, field lessons, and next-run workflow rule changes.",
                parallel_group="post_scout",
                depends_on=[diagnosis_id],
                inputs=["diagnosis_summary", "platform_errors", "field_lessons"],
                outputs=["docs_knowledge_updates", "todo_update"],
                forbidden_actions=["submit_simulation", "submit_alpha"],
                promotion_gate="All repeated issues must become a documented rule or a manual diagnosis item.",
            )
        )
        return tasks

    if normalized_stage == "result_recovery":
        run_ref = clean_datasets[0] if clean_datasets else "latest"
        recovery_id = f"result_recovery:{run_ref}"
        return [
            WorkflowTask(
                task_id=recovery_id,
                stage="result_recovery",
                task_type="result_recovery",
                owner="result-recovery-agent",
                description="Recover in-flight simulations for an existing run before any resubmission.",
                parallel_group="result_recovery",
                depends_on=[],
                dataset_id=run_ref,
                inputs=["run_dir", "simulation_events.jsonl"],
                outputs=["recovered_alpha_ids", "check_results", "recoverable_errors"],
                forbidden_actions=["submit_simulation", "submit_alpha", "change_expression"],
                promotion_gate="Recovery must finish or record a recoverable error before replacement submissions.",
            ),
            WorkflowTask(
                task_id="result_recovery:diagnosis",
                stage="result_recovery",
                task_type="diagnosis",
                owner="diagnosis-agent",
                description="Decide whether recovered alphas are candidates, near-misses, or discarded branches.",
                parallel_group="post_recovery",
                depends_on=[recovery_id],
                inputs=["recovered_alpha_ids", "check_results"],
                outputs=["candidate_rows", "near_miss_ids", "discarded_branches"],
                forbidden_actions=["submit_alpha", "run_new_simulation"],
                promotion_gate="Only clean hard-check results enter candidates.csv.",
            ),
        ]

    if normalized_stage == "repair":
        return [
            WorkflowTask(
                task_id="repair:variant_design",
                stage="repair",
                task_type="repair",
                owner="repair-agent",
                description="Create 4-8 targeted variants for a near-miss alpha only.",
                parallel_group="repair",
                depends_on=[],
                inputs=["near_miss_alpha_id", "failed_checks", "human_repair_hypothesis"],
                outputs=["repair_run_dir", "progress_urls", "check_results"],
                forbidden_actions=["submit_alpha", "repair_weak_scout_branch"],
                promotion_gate="is_near_miss(alpha_record) must be true before Repair starts.",
            ),
            WorkflowTask(
                task_id="repair:submit_check",
                stage="repair",
                task_type="submit_check",
                owner="submit-check-agent",
                description="Check repaired alphas and write candidates only when all hard checks pass.",
                parallel_group="post_repair",
                depends_on=["repair:variant_design"],
                inputs=["repair_check_results"],
                outputs=["candidates.csv", "rejected_repairs"],
                forbidden_actions=["submit_alpha", "run_new_simulation"],
                promotion_gate="No failed or pending hard checks.",
            ),
        ]

    return [
        WorkflowTask(
            task_id=f"{normalized_stage}:diagnosis",
            stage=normalized_stage,
            task_type="diagnosis",
            owner="diagnosis-agent",
            description="Inspect stage artifacts and choose the next workflow action.",
            parallel_group=normalized_stage,
            depends_on=[],
            inputs=["run_artifacts"],
            outputs=["next_actions"],
            forbidden_actions=["submit_alpha"],
            promotion_gate="Manual diagnosis required for stages without a specialized plan.",
        )
    ]


def workflow_action_for_platform_issue(message: str) -> dict[str, str]:
    """Input: platform issue text. Output: action dict. Convert repeated failures into workflow rules."""
    normalized = message.strip().lower()
    for patterns, rule, action in ISSUE_RULES:
        if any(pattern in normalized for pattern in patterns):
            return {"rule": rule, "action": action}
    return {
        "rule": "manual_diagnosis",
        "action": "Record the issue, inspect run artifacts, and add a new workflow rule if it repeats.",
    }


def is_near_miss(
    alpha_record: dict[str, Any],
    benchmark_rules: list[Any] | None = None,
    knowledge_root: str | Path | None = None,
    run_dir: str | Path | None = None,
    consumer: str = "repair_loop",
) -> bool:
    """Input: alpha, rules, roots, consumer. Output: bool. Apply scoped authority to Repair promotion."""
    return benchmark_alpha_record(
        alpha_record,
        benchmark_rules=benchmark_rules,
        knowledge_root=knowledge_root,
        run_dir=run_dir,
        consumer=consumer,
    ).label == "repairable_signal"
