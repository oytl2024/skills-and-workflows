from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
    options = _read_jsonl(options_path)
    selected = next(
        (row for row in options if str(row.get("option_id", "")) == str(selected_option_id)), None
    )
    if selected is None and options:
        selected = options[0]
    if selected is None:
        raise ValueError("no research option cards found")
    stage_dir = Path(run_dir) / "stages" / "schedule"
    stage_dir.mkdir(parents=True, exist_ok=True)
    schedule = {
        "stage": "schedule",
        "selected_option_id": str(selected_option_id),
        "title": str(selected.get("title", "")),
        "scope": str(selected.get("scope", "")),
    }
    (stage_dir / "research_schedule.json").write_text(
        json.dumps(schedule, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return schedule


def summarize_stage_artifacts(run_dir: str | Path) -> dict[str, object]:
    """Input: run dir. Output: artifact summary. Read existing run artifacts without changing state."""
    root = Path(run_dir)
    alpha_results = _read_jsonl(root / "all_alphas.jsonl")
    return {
        "alpha_result_count": len(alpha_results),
        "candidate_file_exists": (root / "candidates.csv").exists(),
        "simulation_event_count": len(_read_jsonl(root / "simulation_events.jsonl")),
    }
