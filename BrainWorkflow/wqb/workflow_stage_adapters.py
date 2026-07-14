from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from wqb.data_ledger import load_data_ledger
from wqb.principle_model import OptionCard, ScoreBreakdown, SourceEvidence
from wqb.research_scheduler import build_research_schedule, research_schedule_to_dict, write_research_schedule
from wqb.template_library import load_template_library


POST_SCHEDULE_STAGES = (
    "scout_seed",
    "batch_generation",
    "backtest",
    "triage",
    "repair",
)


def advance_post_schedule_stage(run_dir: str | Path, stage_name: str) -> dict[str, object]:
    """Input: run directory and post-schedule stage name. Output: stage summary. Complete from local artifacts or write a plan-only handoff."""
    if stage_name not in POST_SCHEDULE_STAGES:
        raise ValueError(f"unsupported post-schedule stage: {stage_name}")
    root = Path(run_dir)
    artifacts = summarize_stage_artifacts(root)
    required_paths = {
        "scout_seed": [root / "candidates.csv"],
        "batch_generation": [root / "all_alphas.jsonl"],
        "backtest": [root / "all_alphas.jsonl"],
        "triage": [root / "candidates.csv"],
        "repair": [root / "all_alphas.jsonl"],
    }[stage_name]
    stage_dir = root / "stages" / stage_name
    stage_dir.mkdir(parents=True, exist_ok=True)
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        blocker = "local artifacts required before plan-only stage completion"
        handoff_path = stage_dir / f"{stage_name}_handoff.json"
        handoff_path.write_text(
            json.dumps(
                {
                    "stage": stage_name,
                    "mode": "plan_only",
                    "blocker": blocker,
                    "missing_artifacts": missing,
                    "artifact_summary": artifacts,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "stage": stage_name,
            "status": "paused",
            "blocker": blocker,
            "evidence_paths": [str(handoff_path)],
        }
    summary_path = stage_dir / f"{stage_name}_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "stage": stage_name,
                "mode": "local_artifacts",
                "artifact_summary": artifacts,
                "source_artifacts": [str(path) for path in required_paths],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "stage": stage_name,
        "status": "completed",
        "evidence_paths": [str(summary_path), *[str(path) for path in required_paths]],
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: rows. Read valid JSONL rows."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def schedule_research_stage(
    knowledge_root: str | Path, run_dir: str | Path, selected_option_id: str
) -> dict[str, object]:
    """Input: knowledge root, run dir, option id. Output: schedule summary. Write a plan-only schedule artifact."""
    knowledge = Path(knowledge_root)
    options_path = knowledge / "wiki" / "70_decisions" / "research_option_cards.jsonl"
    options = []
    for index, row in enumerate(_read_jsonl(options_path), start=1):
        normalized = dict(row)
        normalized.setdefault("option_id", f"option-{index}")
        options.append(normalized)
    selected = next(
        (row for row in options if str(row.get("option_id", "")) == str(selected_option_id)), None
    )
    if not options:
        raise ValueError("no research option cards found")
    if selected is None:
        raise ValueError(f"selected research option not found: {selected_option_id}")
    stage_dir = Path(run_dir) / "stages" / "schedule"
    stage_dir.mkdir(parents=True, exist_ok=True)
    option = _option_card_from_row(selected)
    region, delay, universe = _scope_from_option(selected)
    ledger = load_data_ledger(knowledge / "wiki" / "20_semantics" / "data_ledger.jsonl")
    templates = load_template_library(knowledge / "wiki" / "30_templates" / "template_library.jsonl")
    schedule = build_research_schedule(option, ledger, templates, region, delay, universe)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    markdown_path = write_research_schedule(stage_dir / "research_schedule.md", schedule, generated_at)
    schedule_row = research_schedule_to_dict(schedule)
    schedule_row.update(
        {
            "stage": "schedule",
            "selected_option_id": str(selected_option_id),
            "selected_option": dict(selected),
            "schedule_path": str(markdown_path),
        }
    )
    json_path = stage_dir / "research_schedule.json"
    json_path.write_text(json.dumps(schedule_row, ensure_ascii=False, indent=2), encoding="utf-8")
    schedule_row["evidence_paths"] = [str(json_path), str(markdown_path)]
    return schedule_row


def _option_card_from_row(row: dict[str, Any]) -> OptionCard:
    """Input: option-card row. Output: OptionCard. Normalize stored option evidence for pure scheduling."""
    score_row = row.get("score", {}) if isinstance(row.get("score", {}), dict) else {}
    evidence = [SourceEvidence(**item) for item in row.get("evidence", []) if isinstance(item, dict)]
    score = ScoreBreakdown(
        total=float(score_row.get("total", 0.0)),
        components=dict(score_row.get("components", {})),
        penalties=dict(score_row.get("penalties", {})),
        reasons=[str(item) for item in score_row.get("reasons", [])],
    )
    return OptionCard(
        title=str(row.get("title", "")),
        primary_incentive=str(row.get("primary_incentive", row.get("activity", ""))),
        secondary_incentives=[str(item) for item in row.get("secondary_incentives", [])],
        why_now=str(row.get("why_now", "")),
        candidate_scope=str(row.get("candidate_scope", row.get("scope", ""))),
        expected_asset_value=str(row.get("expected_asset_value", "")),
        correlation_risk=str(row.get("correlation_risk", "unknown")),
        resource_cost=str(row.get("resource_cost", "")),
        evidence=evidence,
        failure_modes=[str(item) for item in row.get("failure_modes", [])],
        decision_needed=str(row.get("decision_needed", "")),
        score=score,
    )


def _scope_from_option(row: dict[str, Any]) -> tuple[str, int, str]:
    """Input: option-card row. Output: region, delay, universe. Derive scheduler scope without live API use."""
    scope = str(row.get("candidate_scope", row.get("scope", "")))
    tokens = scope.replace(",", " ").split()
    region = str(row.get("region", tokens[0] if tokens else "USA"))
    delay_match = re.search(r"\bD(\d+)\b", scope, re.IGNORECASE)
    delay = int(row.get("delay", delay_match.group(1) if delay_match else 1))
    universe = str(
        row.get("universe", next((item for item in tokens if item.upper().startswith("TOP")), "TOP3000"))
    )
    return region, delay, universe


def summarize_stage_artifacts(run_dir: str | Path) -> dict[str, object]:
    """Input: run dir. Output: artifact summary. Read existing run artifacts without changing state."""
    root = Path(run_dir)
    alpha_results = _read_jsonl(root / "all_alphas.jsonl")
    return {
        "alpha_result_count": len(alpha_results),
        "candidate_file_exists": (root / "candidates.csv").exists(),
        "simulation_event_count": len(_read_jsonl(root / "simulation_events.jsonl")),
    }
