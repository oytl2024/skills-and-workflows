from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
import re
from typing import Any

from wqb.benchmark_rules import (
    BENCHMARK_RULES_PATH,
    benchmark_rule_to_dict,
    benchmark_rulebook_digest,
    benchmark_rules_from_start_snapshot,
    load_benchmark_rules,
    load_run_benchmark_rules,
)
from wqb.data_ledger import data_ledger_record_from_dict, load_data_ledger
from wqb.option_cards import option_card_from_row, read_option_card_jsonl
from wqb.principle_model import OptionCard
from wqb.research_scheduler import build_research_schedule, research_schedule_to_dict, write_research_schedule
from wqb.run_readiness import evaluate_run_readiness
from wqb.template_library import load_template_library, select_templates_for_data, template_record_from_dict


POST_SCHEDULE_STAGES = (
    "scout_seed",
    "batch_generation",
    "backtest",
    "triage",
    "repair",
)
START_SNAPSHOT_VERSION = 2


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


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: dict rows list. Read JSONL and reject non-object rows."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path} line {line_number} must be a JSON object")
        rows.append(row)
    return rows


def _validate_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    """Input: optional scope dict. Output: normalized scope dict. Validate concrete workflow scheduling scope."""
    if not isinstance(scope, dict):
        raise ValueError("selected workflow scope must include region, delay, and universe")
    try:
        normalized = {
            "region": str(scope["region"]).strip().upper(),
            "delay": int(scope["delay"]),
            "universe": str(scope["universe"]).strip().upper(),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("selected workflow scope must include region, delay, and universe") from exc
    if not normalized["region"] or normalized["delay"] < 0 or not normalized["universe"]:
        raise ValueError("selected workflow scope must include region, delay, and universe")
    return normalized


def _row_matches_scope(row: dict[str, Any], scope: dict[str, Any]) -> bool:
    """Input: ledger row and scope dict. Output: bool. Match exact available scopes before legacy fields."""
    if "available_scopes" in row:
        return any(
            isinstance(item, dict)
            and str(item.get("region", "")).upper() == scope["region"]
            and int(item.get("delay", -1)) == scope["delay"]
            and str(item.get("universe", "")).upper() == scope["universe"]
            for item in row.get("available_scopes", [])
        )
    try:
        return (
            str(row.get("region", "")).upper() == scope["region"]
            and int(row.get("delay", -1)) == scope["delay"]
            and str(row.get("universe", "")).upper() == scope["universe"]
        )
    except (TypeError, ValueError):
        return False


def _require_start_snapshot_readiness(knowledge: Path, scope: dict[str, Any]) -> None:
    """Input: knowledge root and scope. Output: none. Enforce strict readiness before binding a snapshot."""
    report = evaluate_run_readiness(
        knowledge,
        mode="research",
        batch_size=30,
        live_api_enabled=True,
        region=str(scope["region"]),
        delay=int(scope["delay"]),
        universe=str(scope["universe"]),
    )
    if report.blocked:
        codes = ", ".join(issue.code for issue in report.issues if issue.level == "block") or "blocked"
        raise ValueError(f"start snapshot readiness blocked: {codes}")


def _row_has_positive_coverage(row: dict[str, Any]) -> bool:
    """Input: ledger row. Output: bool. Validate measured row coverage is positive."""
    try:
        return float(row.get("coverage", 0.0)) > 0.0
    except (TypeError, ValueError):
        return False


def _row_has_source_date(row: dict[str, Any]) -> bool:
    """Input: ledger row. Output: bool. Validate raw-source date shape for immutable snapshots."""
    try:
        date.fromisoformat(str(row.get("source_updated_at", "")))
    except ValueError:
        return False
    return True


def _validate_start_artifact_rows(
    option: dict[str, Any],
    scope: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    template_rows: list[dict[str, Any]],
) -> list[str]:
    """Input: option, scope, ledger rows, template rows. Output: compatible template IDs. Revalidate start gates."""
    if not ledger_rows:
        raise ValueError("start snapshot data ledger rows are required")
    if not template_rows:
        raise ValueError("start snapshot template rows are required")
    templates = [template_record_from_dict(row) for row in template_rows]
    incentive = str(option.get("primary_incentive", ""))
    compatible_ids: set[str] = set()
    for row in ledger_rows:
        if not _row_matches_scope(row, scope):
            raise ValueError("start snapshot data ledger row does not match selected scope")
        if row.get("source_quality") != "platform_raw_capture" or row.get("coverage_status") != "measured_raw":
            raise ValueError("start snapshot data ledger rows must be measured platform coverage")
        if not _row_has_positive_coverage(row):
            raise ValueError("start snapshot data ledger rows must have positive measured coverage")
        if not _row_has_source_date(row):
            raise ValueError("start snapshot data ledger rows must include source_updated_at")
        row_template_ids = row.get("compatible_template_ids")
        if not isinstance(row_template_ids, list) or not row_template_ids:
            raise ValueError("start snapshot data ledger rows must include compatible template IDs")
        selected = select_templates_for_data(
            templates,
            data_ledger_record_from_dict(row),
            incentive,
            len(templates),
            region=scope["region"],
            delay=scope["delay"],
            universe=scope["universe"],
        )
        matching = {str(item) for item in row_template_ids} & {template.template_id for template in selected}
        if not matching:
            raise ValueError("start snapshot has no compatible templates for a measured ledger row")
        compatible_ids.update(matching)
    return sorted(compatible_ids)


def create_start_snapshot(
    knowledge_root: str | Path,
    selected_option_id: str,
    selected_scope: dict[str, Any] | None,
) -> dict[str, Any]:
    """Input: knowledge root, option id, scope. Output: snapshot dict. Bind validated start artifacts immutably."""
    knowledge = Path(knowledge_root)
    options_path = knowledge / "wiki" / "70_decisions" / "research_option_cards.jsonl"
    options = read_option_card_jsonl(options_path)
    selected = next((row for row in options if str(row.get("option_id", "")) == str(selected_option_id)), None)
    if not options:
        raise ValueError("no research option cards found")
    if selected is None:
        raise ValueError(f"selected research option not found: {selected_option_id}")
    if selected_scope is None:
        region, delay, universe = _scope_from_option(selected)
        scope = _validate_scope({"region": region, "delay": delay, "universe": universe})
    else:
        scope = _validate_scope(selected_scope)
    _require_start_snapshot_readiness(knowledge, scope)
    ledger_rows = [
        row
        for row in _read_jsonl_objects(knowledge / "wiki" / "20_semantics" / "data_ledger.jsonl")
        if _row_matches_scope(row, scope)
    ]
    template_rows = _read_jsonl_objects(knowledge / "wiki" / "30_templates" / "template_library.jsonl")
    compatible_ids = _validate_start_artifact_rows(selected, scope, ledger_rows, template_rows)
    selected_template_rows = [row for row in template_rows if str(row.get("template_id", "")) in set(compatible_ids)]
    benchmark_rules = load_benchmark_rules(knowledge / BENCHMARK_RULES_PATH)
    if not benchmark_rules:
        raise ValueError("start snapshot benchmark rule rows are required")
    return {
        "artifact_binding_version": START_SNAPSHOT_VERSION,
        "selected_option": dict(selected),
        "selected_scope": dict(scope),
        "data_ledger_rows": [dict(row) for row in ledger_rows],
        "compatible_template_ids": compatible_ids,
        "template_rows": selected_template_rows,
        "benchmark_rulebook": {
            "path": BENCHMARK_RULES_PATH.as_posix(),
            "sha256": benchmark_rulebook_digest(benchmark_rules),
            "rules": [benchmark_rule_to_dict(rule) for rule in benchmark_rules],
        },
        "gate_metadata": {
            "required_source_quality": "platform_raw_capture",
            "required_coverage_status": "measured_raw",
            "required_positive_coverage": True,
            "required_source_updated_at": True,
        },
    }


def _snapshot_schedule_inputs(
    snapshot: Any,
    selected_option_id: str,
    selected_scope: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[Any], list[Any], list[Any]]:
    """Input: snapshot payload, option id, scope. Output: option, scope, ledger, templates, rules."""
    if not isinstance(snapshot, dict):
        raise ValueError("start snapshot is required for this workflow")
    if int(snapshot.get("artifact_binding_version", 0) or 0) != START_SNAPSHOT_VERSION:
        raise ValueError("start snapshot version is unsupported")
    selected_option = snapshot.get("selected_option")
    if not isinstance(selected_option, dict):
        raise ValueError("start snapshot selected option is missing")
    selected_option = dict(selected_option)
    if str(selected_option.get("option_id", "")) != str(selected_option_id):
        raise ValueError("start snapshot selected option mismatch")
    option_card_from_row(selected_option)
    scope = _validate_scope(snapshot.get("selected_scope") if isinstance(snapshot.get("selected_scope"), dict) else None)
    if selected_scope is not None and _validate_scope(selected_scope) != scope:
        raise ValueError("start snapshot selected scope mismatch")
    ledger_rows = snapshot.get("data_ledger_rows")
    template_rows = snapshot.get("template_rows")
    if not isinstance(ledger_rows, list) or not all(isinstance(row, dict) for row in ledger_rows):
        raise ValueError("start snapshot data ledger rows are required")
    if not isinstance(template_rows, list) or not all(isinstance(row, dict) for row in template_rows):
        raise ValueError("start snapshot template rows are required")
    benchmark_rules = benchmark_rules_from_start_snapshot(snapshot)
    compatible_ids = _validate_start_artifact_rows(selected_option, scope, [dict(row) for row in ledger_rows], [dict(row) for row in template_rows])
    stored_compatible_ids = snapshot.get("compatible_template_ids")
    if not isinstance(stored_compatible_ids, list) or not set(compatible_ids).issubset({str(item) for item in stored_compatible_ids}):
        raise ValueError("start snapshot compatible template IDs are incomplete")
    return (
        selected_option,
        scope,
        [data_ledger_record_from_dict(dict(row)) for row in ledger_rows],
        [template_record_from_dict(dict(row)) for row in template_rows],
        benchmark_rules,
    )


def schedule_research_stage(
    knowledge_root: str | Path,
    run_dir: str | Path,
    selected_option_id: str,
    selected_scope: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Input: knowledge root, run dir, option id. Output: schedule summary. Write a plan-only schedule artifact."""
    knowledge = Path(knowledge_root)
    manifest_path = Path(run_dir) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    if isinstance(manifest, dict) and "start_snapshot" in manifest:
        selected, scope, ledger, templates, benchmark_rules = _snapshot_schedule_inputs(
            manifest.get("start_snapshot"), selected_option_id, selected_scope
        )
        region, delay, universe = scope["region"], scope["delay"], scope["universe"]
    elif manifest_path.exists():
        raise ValueError("start snapshot is required for workflow schedule authority")
    else:
        options_path = knowledge / "wiki" / "70_decisions" / "research_option_cards.jsonl"
        options = read_option_card_jsonl(options_path)
        selected = next(
            (row for row in options if str(row.get("option_id", "")) == str(selected_option_id)), None
        )
        if not options:
            raise ValueError("no research option cards found")
        if selected is None:
            raise ValueError(f"selected research option not found: {selected_option_id}")
        region, delay, universe = _scope_from_selected_or_option(selected_scope, selected)
        ledger = load_data_ledger(knowledge / "wiki" / "20_semantics" / "data_ledger.jsonl")
        templates = load_template_library(knowledge / "wiki" / "30_templates" / "template_library.jsonl")
        benchmark_rules = []
    stage_dir = Path(run_dir) / "stages" / "schedule"
    stage_dir.mkdir(parents=True, exist_ok=True)
    option = _option_card_from_row(selected)
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
            "benchmark_rule_ids": [rule.rule_id for rule in benchmark_rules],
        }
    )
    json_path = stage_dir / "research_schedule.json"
    json_path.write_text(json.dumps(schedule_row, ensure_ascii=False, indent=2), encoding="utf-8")
    schedule_row["evidence_paths"] = [str(json_path), str(markdown_path)]
    return schedule_row


def _option_card_from_row(row: dict[str, Any]) -> OptionCard:
    """Input: option-card row. Output: OptionCard. Normalize stored option evidence for pure scheduling."""
    return option_card_from_row(row)


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


def _scope_from_selected_or_option(
    selected_scope: dict[str, Any] | None, option: dict[str, Any]
) -> tuple[str, int, str]:
    """Input: optional selected scope and option card. Output: region, delay, universe. Prefer persisted concrete scope over planner prose."""
    if selected_scope is None:
        return _scope_from_option(option)
    try:
        region = str(selected_scope["region"]).strip().upper()
        delay = int(selected_scope["delay"])
        universe = str(selected_scope["universe"]).strip().upper()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("selected workflow scope must include region, delay, and universe") from exc
    if not region or delay < 0 or not universe:
        raise ValueError("selected workflow scope must include region, delay, and universe")
    return region, delay, universe


def summarize_stage_artifacts(run_dir: str | Path) -> dict[str, object]:
    """Input: run dir. Output: artifact summary. Read existing run artifacts without changing state."""
    root = Path(run_dir)
    alpha_results = _read_jsonl(root / "all_alphas.jsonl")
    benchmark_rules = load_run_benchmark_rules(root)
    return {
        "alpha_result_count": len(alpha_results),
        "candidate_file_exists": (root / "candidates.csv").exists(),
        "simulation_event_count": len(_read_jsonl(root / "simulation_events.jsonl")),
        "benchmark_rule_ids": [rule.rule_id for rule in benchmark_rules or []],
    }
