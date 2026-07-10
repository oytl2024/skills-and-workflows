from dataclasses import asdict, dataclass, field
from math import ceil
from pathlib import Path
from typing import Any

from wqb.data_ledger import DataLedgerRecord, data_ledger_record_to_dict, select_data_for_research
from wqb.principle_model import OptionCard
from wqb.research_workflow import build_parallel_stage_plan
from wqb.template_library import TemplateRecord, select_templates_for_data


DEFAULT_LOCAL_GATES = [
    "syntax_gate",
    "field_availability_gate",
    "field_type_gate",
    "template_complexity_gate",
    "local_novelty_gate",
    "self_correlation_proxy_gate",
    "production_correlation_risk_gate",
]


@dataclass(frozen=True)
class ResearchSchedule:
    option_title: str
    primary_incentive: str
    region: str
    delay: int
    batch_size: int
    selected_data: list[DataLedgerRecord]
    template_matches: list[dict[str, Any]]
    local_gates: list[str]
    stop_rules: list[str]
    activity: str = ""
    universe: str = ""
    batch_count: int = 0
    simulation_budget: int = 0
    api_budget: int = 0
    parallel_task_plan: list[dict[str, Any]] = field(default_factory=list)


def research_schedule_to_dict(schedule: ResearchSchedule) -> dict[str, Any]:
    """Input: ResearchSchedule. Output: dict[str, Any]. Convert schedule to JSON-safe data."""
    row = asdict(schedule)
    row["selected_data"] = [data_ledger_record_to_dict(record) for record in schedule.selected_data]
    return row


def build_research_schedule(
    option: OptionCard,
    data_records: list[DataLedgerRecord],
    templates: list[TemplateRecord],
    region: str,
    delay: int,
    universe: str,
    max_data: int = 5,
    templates_per_data: int = 2,
    batch_size: int = 30,
) -> ResearchSchedule:
    """Input: option, ledger, templates, scope. Output: ResearchSchedule. Create a concrete research schedule."""
    selected_data = select_data_for_research(
        data_records,
        option.primary_incentive,
        region,
        delay,
        max_data,
        universe=universe,
    )
    template_matches: list[dict[str, Any]] = []
    for record in selected_data:
        matched = select_templates_for_data(templates, record, option.primary_incentive, templates_per_data)
        for template in matched:
            template_matches.append(
                {
                    "field_id": record.field_id,
                    "dataset_id": record.dataset_id,
                    "template_id": template.template_id,
                    "skeleton": template.skeleton,
                    "hypothesis": template.hypothesis,
                    "correlation_risk": template.correlation_risk,
                }
            )
    unit_ids = [f"{match['dataset_id']}:{match['field_id']}:{match['template_id']}" for match in template_matches]
    parallel_task_plan = [
        asdict(task)
        for task in build_parallel_stage_plan("scout", unit_ids)
        if task.task_type == "data_scout"
    ]
    unit_count = len(template_matches)
    normalized_batch_size = max(int(batch_size), 1)
    batch_count = ceil(unit_count / normalized_batch_size) if unit_count else 0
    simulation_budget = min(unit_count, normalized_batch_size * batch_count)
    return ResearchSchedule(
        option_title=option.title,
        primary_incentive=option.primary_incentive,
        region=region,
        delay=int(delay),
        batch_size=normalized_batch_size,
        selected_data=selected_data,
        template_matches=template_matches,
        local_gates=list(DEFAULT_LOCAL_GATES),
        stop_rules=[
            "stop_after_one_30_alpha_scout_batch_without_signal",
            "stop_repair_after_8_variants_without_metric_or_check_improvement",
            "promote_only_latest_hard_check_passes",
        ],
        activity=option.primary_incentive,
        universe=universe,
        batch_count=batch_count,
        simulation_budget=simulation_budget,
        api_budget=max(simulation_budget, len(parallel_task_plan)),
        parallel_task_plan=parallel_task_plan,
    )


def write_research_schedule(path: Path, schedule: ResearchSchedule, generated_at: str) -> Path:
    """Input: output path, schedule, timestamp. Output: path. Write Markdown research schedule."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Research Schedule",
        "",
        f"Generated at: `{generated_at}`",
        "",
        f"- Option: {schedule.option_title}",
        f"- Primary Incentive: `{schedule.primary_incentive}`",
        f"- Scope: {schedule.region} D{schedule.delay}",
        f"- Activity: `{schedule.activity}`",
        f"- Universe: `{schedule.universe}`",
        f"- Batch Size: {schedule.batch_size}",
        f"- Batch Count: {schedule.batch_count}",
        f"- Simulation Budget: {schedule.simulation_budget}",
        f"- API Budget: {schedule.api_budget}",
        "",
        "## Selected Data",
    ]
    for record in schedule.selected_data:
        lines.append(f"- `{record.field_id}` from `{record.dataset_id}`; tags: {', '.join(record.semantic_tags)}; risk: {record.correlation_risk}")
    lines.extend(["", "## Template Matches"])
    for match in schedule.template_matches:
        lines.append(f"- `{match['template_id']}` on `{match['field_id']}`: {match['hypothesis']}")
    lines.extend(["", "## Parallel Task Plan"])
    for task in schedule.parallel_task_plan:
        lines.append(f"- `{task['task_id']}`: {task['description']}")
    lines.extend(["", "## Local Gates"])
    for gate in schedule.local_gates:
        lines.append(f"- {gate}")
    lines.extend(["", "## Stop Rules"])
    for rule in schedule.stop_rules:
        lines.append(f"- {rule}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
