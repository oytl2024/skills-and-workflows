import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import asdict, fields as dataclass_fields
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from wqb.benchmark import benchmark_alpha_record
from wqb.candidate_queue import QUEUE_STATUSES
from wqb.checker import fetch_check_summary
from wqb.client import WQBClient
from wqb.config import load_config
from wqb.data_catalog import (
    build_metadata_cache,
    cached_fields,
    fetch_data_fields,
    field_ids,
    filter_fields_by_suffix,
    select_seed_fields,
)
from wqb.data_ledger import load_data_ledger
from wqb.decision_log import write_option_cards
from wqb.expression import expression_hash, is_power_pool_complexity_ok, replace_operator_names
from wqb.generator import build_settings, generate_seed_candidates, simulation_payload
from wqb.knowledge import fetch_knowledge_snapshot
from wqb.knowledge_bootstrap import bootstrap_knowledge, bootstrap_summary_to_dict
from wqb.knowledge_freshness import evaluate_freshness, load_freshness_manifest, write_freshness_report
from wqb.novelty import score_expression_novelty
from wqb.optimizer import actions_for_check_summary
from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
from wqb.principle_model import OptionCard, ScoreBreakdown, SourceEvidence
from wqb.recorder import RunRecorder
from wqb.research_planner import generate_research_options
from wqb.research_scheduler import build_research_schedule, research_schedule_to_dict, write_research_schedule
from wqb.research_workflow import build_parallel_stage_plan, cap_simulation_count, precheck_expression
from wqb.rule_refresh import refresh_incentive_snapshot
from wqb.run_readiness import evaluate_run_readiness, write_readiness_reports
from wqb.simulator import extract_alpha_id, poll_simulation, resolve_multisimulation_alpha_ids, submit_multisimulation, submit_simulation
from wqb.subagent_handoff import build_handoff_packets, write_handoff_packets
from wqb.template_library import load_template_library
from wqb.workflow_launcher import create_run_manifest, load_workflow_launch_config, write_run_manifest
from wqb.workflow_paths import resolve_project_root, resolve_run_root


FIELD_BATCH_MULTI_CHUNK_SIZE = 5
FIELD_BATCH_API_MAX_RECORDS = 80
FIELD_BATCH_SEED_FIELD_LIMIT = 40
FIELD_BATCH_CANDIDATE_BUFFER_MULTIPLIER = 3
DEFAULT_MULTI_CHUNK_SLEEP_SECONDS = 0.0
KNOWLEDGE_ROOT_ENV = "BRAIN_KNOWLEDGE_ROOT"


class ReadinessGateError(RuntimeError):
    """Input: gate message and report paths. Output: exception. Carry blocked readiness report locations."""

    def __init__(self, message: str, json_path: Path, markdown_path: Path):
        super().__init__(message)
        self.json_path = json_path
        self.markdown_path = markdown_path


def default_knowledge_root() -> Path:
    """Input: none. Output: Path. Resolve the shared Obsidian knowledge vault root."""
    configured = os.environ.get(KNOWLEDGE_ROOT_ENV, "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "knowledge"


def default_option_output_dir() -> str:
    """Input: none. Output: str path. Return the default research option card directory."""
    return str(default_knowledge_root() / "wiki" / "70_decisions")


def default_orchestrator_paths(config: dict[str, Any]) -> OrchestratorPaths:
    """Input: run config. Output: OrchestratorPaths. Resolve local workflow state roots."""
    workflow_root = Path(__file__).resolve().parents[1]
    project_root = resolve_project_root(workflow_root)
    knowledge_root = Path(config.get("knowledge_root", default_knowledge_root()))
    run_root = resolve_run_root(workflow_root, config.get("run_root", "runs"))
    return OrchestratorPaths(
        project_root=project_root,
        workflow_root=workflow_root,
        knowledge_root=knowledge_root,
        run_root=run_root,
    )


def make_run_dir(config: dict[str, Any]) -> Path:
    """Input: run config. Output: run directory path. Create a timestamped run location."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(config["run_root"]) / run_id


def build_client(config: dict[str, Any]) -> WQBClient:
    """Input: run config. Output: WQB client. Centralize client construction."""
    return WQBClient(
        timeout_seconds=int(config["request_timeout_seconds"]),
        max_retries=int(config["max_retries"]),
        base_backoff_seconds=int(config["base_backoff_seconds"]),
    )


def plan_research_options(config: dict[str, Any], max_options: int, output_dir: str) -> dict[str, Any]:
    """Input: config, option limit, output dir. Output: summary dict. Generate read-only research option cards."""
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    client = build_client(config)
    snapshot = refresh_incentive_snapshot(client, generated_at=generated_at)
    cards = generate_research_options(snapshot, max_options=max_options)
    jsonl_path, markdown_path = write_option_cards(Path(output_dir), cards, generated_at)
    return {
        "generated_at": generated_at,
        "option_count": len(cards),
        "jsonl_path": str(jsonl_path),
        "markdown_path": str(markdown_path),
        "refresh_error_count": len(snapshot.refresh_errors),
        "options": [card.title for card in cards],
    }


def _option_card_from_dict(row: dict[str, Any]) -> OptionCard:
    """Input: dict row. Output: OptionCard. Rebuild an option card from JSON for scheduling."""
    evidence = [SourceEvidence(**item) for item in row.get("evidence", [])]
    score = ScoreBreakdown(**row["score"])
    allowed = {field.name for field in dataclass_fields(OptionCard)}
    data = {key: value for key, value in row.items() if key in allowed}
    data["evidence"] = evidence
    data["score"] = score
    return OptionCard(**data)


def knowledge_health_check(
    knowledge_root: str | Path,
    manifest_path: str | Path,
    output_path: str | Path,
    today_value: str | None = None,
) -> dict[str, Any]:
    """Input: knowledge root, manifest path, output path, date string. Output: summary dict. Check compiled knowledge freshness."""
    root = Path(knowledge_root)
    manifest = Path(manifest_path)
    if not manifest.is_absolute():
        manifest = root / manifest
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    current = date.fromisoformat(today_value) if today_value else date.today()
    records = load_freshness_manifest(manifest, strict=True)
    statuses = evaluate_freshness(records, current, artifact_root=root)
    report = write_freshness_report(output, statuses, datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    return {
        "record_count": len(statuses),
        "stale_count": len([status for status in statuses if status.stale]),
        "missing_count": len([status for status in statuses if not status.artifact_exists]),
        "report_path": str(report),
    }


def bootstrap_knowledge_command(knowledge_root: str | Path, seed_root: str | Path) -> dict[str, Any]:
    """Input: knowledge root and seed root. Output: summary dict. Materialize formal knowledge artifacts."""
    summary = bootstrap_knowledge(knowledge_root, seed_root)
    return bootstrap_summary_to_dict(summary)


def readiness_check(
    knowledge_root: str | Path,
    output_dir: str | Path,
    mode: str,
    batch_size: int,
    live_api_enabled: bool,
    submit_confirmed: bool,
    today_value: str | None = None,
    region: str | None = None,
    universe: str | None = None,
    delay: int | None = None,
) -> dict[str, Any]:
    """Input: root, output dir, mode, safety flags. Output: summary dict. Run startup readiness checks."""
    report = evaluate_run_readiness(
        knowledge_root,
        mode=mode,
        batch_size=batch_size,
        live_api_enabled=live_api_enabled,
        submit_confirmed=submit_confirmed,
        today_value=today_value,
        region=region,
        universe=universe,
        delay=delay,
    )
    json_path, markdown_path = write_readiness_reports(Path(output_dir), report)
    return {
        "mode": report.mode,
        "passed": report.passed,
        "blocked": report.blocked,
        "issue_count": len(report.issues),
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }


def launch_workflow(
    defaults_path: str | Path,
    local_path: str | Path | None,
    overrides: dict[str, Any],
    write_handoffs: bool = True,
    submit_confirmed: bool = False,
    today_value: str | None = None,
) -> dict[str, Any]:
    """Input: config paths and overrides. Output: launch summary. Write manifest, readiness reports, and handoffs."""
    local = Path(local_path) if local_path else None
    config = load_workflow_launch_config(Path(defaults_path), local, overrides=overrides)
    readiness_report = evaluate_run_readiness(
        config.knowledge_root,
        mode=config.mode,
        batch_size=config.batch_size,
        live_api_enabled=config.live_api_enabled,
        submit_confirmed=submit_confirmed,
        today_value=today_value,
        region=config.region,
        universe=config.universe,
        delay=config.delay,
    )
    if readiness_report.blocked:
        blocked_dir = Path(config.run_root) / "readiness_blocked" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        readiness_json, readiness_md = write_readiness_reports(blocked_dir, readiness_report)
        return {
            "run_id": "",
            "mode": config.mode,
            "manifest_path": "",
            "readiness_json_path": str(readiness_json),
            "readiness_markdown_path": str(readiness_md),
            "readiness_passed": readiness_report.passed,
            "readiness_blocked": True,
            "error": f"Readiness blocked for {config.mode}; see {readiness_md}",
            "handoffs": [],
        }
    manifest = create_run_manifest(config)
    manifest_path = write_run_manifest(Path(manifest.run_dir) / "run_manifest.json", manifest)
    readiness_json, readiness_md = write_readiness_reports(Path(manifest.run_dir), readiness_report)
    handoff_outputs = []
    if write_handoffs:
        handoff_outputs = write_handoff_packets(Path(manifest.handoff_dir), build_handoff_packets(manifest))
    return {
        "run_id": manifest.run_id,
        "mode": manifest.mode,
        "manifest_path": str(manifest_path),
        "readiness_json_path": str(readiness_json),
        "readiness_markdown_path": str(readiness_md),
        "readiness_passed": readiness_report.passed,
        "readiness_blocked": False,
        "handoffs": handoff_outputs,
    }


def require_readiness_gate(
    knowledge_root: str | Path,
    output_dir: str | Path,
    mode: str,
    batch_size: int,
    live_api_enabled: bool,
    submit_confirmed: bool = False,
    region: str | None = None,
    universe: str | None = None,
    delay: int | None = None,
) -> None:
    """Input: readiness inputs and output dir. Output: none. Raise with report paths when execution is blocked."""
    report = evaluate_run_readiness(
        knowledge_root,
        mode=mode,
        batch_size=batch_size,
        live_api_enabled=live_api_enabled,
        submit_confirmed=submit_confirmed,
        region=region,
        universe=universe,
        delay=delay,
    )
    json_path, markdown_path = write_readiness_reports(Path(output_dir), report)
    if report.blocked:
        raise ReadinessGateError(f"Readiness blocked for {mode}; see {markdown_path}", json_path, markdown_path)


def _live_gate_kwargs(config: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Input: run config and run dir. Output: readiness kwargs. Build live execution readiness gate inputs."""
    return {
        "knowledge_root": config.get("knowledge_root") or default_knowledge_root(),
        "output_dir": run_dir,
        "mode": "research",
        "batch_size": int(config.get("max_alphas_per_round", 30)),
        "live_api_enabled": True,
        "region": str(config.get("region", "USA")),
        "universe": str(config.get("universe", "TOP3000")),
        "delay": int(config.get("delay", 1)),
    }


def _print_readiness_blocked(run_dir: Path, error: ReadinessGateError, extra: dict[str, Any] | None = None) -> None:
    """Input: run dir, readiness error, extra fields. Output: terminal JSON. Report a blocked live command."""
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "status": "readiness_blocked",
                "error": str(error),
                "readiness_json_path": str(error.json_path),
                "readiness_markdown_path": str(error.markdown_path),
                **dict(extra or {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def schedule_research_from_option(
    option_json: str | Path,
    knowledge_root: str | Path,
    output_path: str | Path,
    region: str,
    delay: int,
    option_index: int | None = None,
    universe: str = "TOP3000",
) -> dict[str, Any]:
    """Input: option path, knowledge root, output path, region, delay. Output: summary dict. Build schedule from compiled knowledge."""
    root = Path(knowledge_root)
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    require_readiness_gate(
        root,
        output.parent / "readiness",
        mode="research",
        batch_size=30,
        live_api_enabled=True,
        region=region,
        universe=universe,
        delay=delay,
    )
    if option_index is not None and option_index < 1:
        raise ValueError("option_index must be 1 or greater")
    option_text = Path(option_json).read_text(encoding="utf-8")
    try:
        payload = json.loads(option_text)
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in option_text.splitlines() if line.strip()]
    else:
        if not isinstance(payload, dict):
            raise ValueError("option file must contain one JSON object or JSONL option-card records")
        rows = [payload]
    if len(rows) > 1 and option_index is None:
        raise ValueError("option_index is required for multi-record JSONL option files")
    selected_index = option_index or 1
    if selected_index > len(rows):
        raise ValueError(f"option_index {selected_index} is outside the {len(rows)} available option records")
    option = _option_card_from_dict(rows[selected_index - 1])
    ledger = load_data_ledger(root / "wiki" / "20_semantics" / "data_ledger.jsonl")
    templates = load_template_library(root / "wiki" / "30_templates" / "template_library.jsonl")
    schedule = build_research_schedule(option, ledger, templates, region=region, delay=delay, universe=universe)
    schedule_path = write_research_schedule(output, schedule, datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    row = research_schedule_to_dict(schedule)
    return {
        "schedule_path": str(schedule_path),
        "selected_data_count": len(row["selected_data"]),
        "template_match_count": len(row["template_matches"]),
        "local_gates": row["local_gates"],
        "option_index": selected_index,
    }


def is_http_status_error(err: Exception, status_code: int) -> bool:
    """Input: exception and status code. Output: bool. Detect requests HTTPError response status."""
    response = getattr(err, "response", None)
    return isinstance(err, requests.exceptions.HTTPError) and getattr(response, "status_code", None) == status_code


def parse_operator_replacements(items: list[str] | None) -> dict[str, str]:
    """Input: CLI OLD=NEW strings. Output: replacement dict. Validate operator rewrite arguments."""
    replacements: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"operator replacement must use OLD=NEW: {item}")
        old, new = item.split("=", 1)
        old = old.strip()
        new = new.strip()
        if not old or not new:
            raise ValueError(f"operator replacement must use non-empty OLD=NEW: {item}")
        replacements[old] = new
    return replacements


def coerce_setting_value(value: str) -> Any:
    """Input: CLI setting value. Output: typed value. Convert simple numeric values for settings overrides."""
    stripped = value.strip()
    try:
        if "." not in stripped:
            return int(stripped)
        return float(stripped)
    except ValueError:
        return stripped


def parse_setting_overrides(items: list[str] | None) -> dict[str, Any]:
    """Input: CLI KEY=VALUE strings. Output: settings override dict. Validate tuning arguments."""
    overrides: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"setting override must use KEY=VALUE: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError(f"setting override must use non-empty KEY=VALUE: {item}")
        overrides[key] = coerce_setting_value(value)
    return overrides


def parse_setting_variations(items: list[str] | None) -> list[dict[str, Any]]:
    """Input: CLI KEY=A,B strings. Output: setting variant dicts. Build a small cartesian grid."""
    variants: list[dict[str, Any]] = [{}]
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"setting variation must use KEY=VALUE1,VALUE2: {item}")
        key, values = item.split("=", 1)
        key = key.strip()
        raw_values = [value.strip() for value in values.split(",") if value.strip()]
        if not key or not raw_values:
            raise ValueError(f"setting variation must use non-empty KEY=VALUE1,VALUE2: {item}")
        next_variants: list[dict[str, Any]] = []
        for variant in variants:
            for raw_value in raw_values:
                new_variant = dict(variant)
                new_variant[key] = coerce_setting_value(raw_value)
                next_variants.append(new_variant)
        variants = next_variants
    return variants


def parse_blend_weights(value: str) -> list[float]:
    """Input: comma-separated weights. Output: float list. Parse Repair blend weights."""
    weights: list[float] = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            weights.append(float(raw))
        except ValueError as err:
            raise ValueError(f"blend weight must be numeric: {raw}") from err
    if not weights:
        raise ValueError("at least one blend weight is required")
    return weights


def simulation_identity_hash(expression: str, settings: dict[str, Any]) -> str:
    """Input: expression and settings. Output: stable simulation hash. Distinguish setting variants."""
    settings_json = json.dumps(settings, ensure_ascii=False, sort_keys=True)
    return expression_hash(f"{expression}\n{settings_json}")


def record_recoverable_network_error(
    recorder: RunRecorder,
    stage: str,
    err: requests.exceptions.RequestException,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Input: recorder, stage, exception, metadata. Output: none. Persist retryable API/network failure."""
    response = getattr(err, "response", None)
    status_code = getattr(response, "status_code", None) or "NETWORK_ERROR"
    headers = getattr(response, "headers", {}) or {}
    rate_limit_fields = {
        "retry_after": headers.get("Retry-After"),
        "x_ratelimit_limit": headers.get("X-Ratelimit-Limit"),
        "x_ratelimit_remaining": headers.get("X-Ratelimit-Remaining"),
        "x_ratelimit_reset": headers.get("X-Ratelimit-Reset"),
    }
    recorder.append_jsonl(
        "run_errors.jsonl",
        {
            "stage": stage,
            "status": "RECOVERABLE",
            "status_code": status_code,
            "recoverable": True,
            "message": str(err),
            **{key: value for key, value in rate_limit_fields.items() if value is not None},
            **dict(metadata or {}),
        },
    )


def authenticate_for_run(client, recorder: RunRecorder, stage: str) -> bool:
    """Input: client, recorder, stage. Output: bool. Authenticate and record recoverable network failure."""
    try:
        client.authenticate()
    except requests.exceptions.RequestException as err:
        record_recoverable_network_error(recorder, stage, err)
        return False
    return True


def settings_for_generation(
    base_settings: dict[str, Any],
    generation: int,
    action_types: list[str],
) -> dict[str, Any]:
    """Input: base settings, generation, action types. Output: tuned settings for the next search round."""
    settings = dict(base_settings)
    if generation <= 0:
        return settings

    decay = int(settings.get("decay", 0))
    truncation = float(settings.get("truncation", 0.08))
    action_set = set(action_types)

    if {"increase_decay", "smooth_signal", "add_trade_when"} & action_set:
        settings["decay"] = min(decay + 2 * generation, 20)
    elif {"decrease_decay", "shorten_window"} & action_set:
        settings["decay"] = max(decay - generation, 0)
    else:
        settings["decay"] = min(decay + generation, 12)

    if {"rank_or_scale", "adjust_truncation", "add_backfill"} & action_set:
        settings["truncation"] = max(min(truncation * 0.75, 0.1), 0.01)
    return settings


def dry_run(config: dict[str, Any]) -> None:
    """Input: run config. Output: terminal summary. Generate payloads without hitting simulation endpoints."""
    settings = build_settings(config)
    sample_fields = [{"id": "close"}, {"id": "volume"}, {"id": "returns"}]
    candidates = generate_seed_candidates(sample_fields, settings, int(config["max_alphas_per_round"]), generation=0)
    known_fields = field_ids(sample_fields)
    payloads = []
    for candidate in candidates:
        complexity = is_power_pool_complexity_ok(
            candidate.expression,
            known_fields,
            int(config["power_pool_operator_limit"]),
            int(config["power_pool_field_limit"]),
        )
        payloads.append(
            {
                "expression_hash": expression_hash(candidate.expression),
                "expression": candidate.expression,
                "complexity_ok": complexity.ok,
                "payload": simulation_payload(candidate.settings, candidate.expression),
            }
        )
    print(json.dumps({"payload_count": len(payloads), "payloads": payloads[:5]}, ensure_ascii=False, indent=2))


def format_parallel_stage_plan(stage: str, dataset_ids: list[str]) -> str:
    """Input: workflow stage and dataset ids. Output: JSON string. Serialize assignable workflow tasks."""
    clean_datasets = [dataset.strip() for dataset in dataset_ids if dataset and dataset.strip()]
    tasks = [asdict(task) for task in build_parallel_stage_plan(stage, clean_datasets)]
    return json.dumps(
        {
            "stage": stage.strip().lower(),
            "dataset_ids": clean_datasets,
            "tasks": tasks,
        },
        ensure_ascii=False,
        indent=2,
    )


def plan_stage(stage: str, dataset_id_arg: str) -> None:
    """Input: stage and comma-separated dataset ids. Output: terminal JSON. Print parallel task plan."""
    dataset_ids = [item.strip() for item in dataset_id_arg.split(",") if item.strip()]
    print(format_parallel_stage_plan(stage, dataset_ids))


def list_fields_summary(
    client,
    config: dict[str, Any],
    dataset_id: str = "",
    field_search: str = "",
    field_suffix: str = "",
    max_fields: int = 50,
) -> dict[str, Any]:
    """Input: client, config, filters. Output: field summary dict. List data fields without simulation."""
    fields = fetch_data_fields(
        client,
        config["instrument_type"],
        config["region"],
        int(config["delay"]),
        config["universe"],
        dataset_id=dataset_id,
        search=field_search,
        max_records=max(int(max_fields), 1),
    )
    fields = filter_fields_by_suffix(fields, field_suffix)
    rows: list[dict[str, Any]] = []
    for field in fields[: int(max_fields)]:
        dataset = field.get("dataset") if isinstance(field.get("dataset"), dict) else {}
        rows.append(
            {
                "id": field.get("id"),
                "type": field.get("type"),
                "coverage": field.get("coverage"),
                "alphaCount": field.get("alphaCount"),
                "dataset_id": dataset.get("id", dataset_id),
            }
        )
    return {
        "dataset_id": dataset_id,
        "field_search": field_search,
        "field_suffix": field_suffix,
        "field_count": len(rows),
        "fields": rows,
    }


def list_fields(config: dict[str, Any], dataset_id: str, field_search: str, field_suffix: str, max_fields: int) -> None:
    """Input: config and field filters. Output: terminal JSON. Fetch and print data fields only."""
    client = build_client(config)
    client.authenticate()
    summary = list_fields_summary(
        client,
        config,
        dataset_id=dataset_id,
        field_search=field_search,
        field_suffix=field_suffix,
        max_fields=max_fields,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_csv_arg(value: str) -> list[str]:
    """Input: comma-separated string. Output: cleaned string list. Parse compact CLI lists."""
    return [item.strip() for item in value.split(",") if item.strip()]


def cache_metadata(
    config: dict[str, Any],
    dataset_id_arg: str,
    field_search_arg: str,
    field_suffix: str,
    max_fields: int,
    cache_dir: str,
    include_data_sets: bool = True,
) -> Path:
    """Input: config and metadata filters. Output: cache path. Fetch platform metadata for local reuse."""
    client = build_client(config)
    client.authenticate()
    dataset_ids = parse_csv_arg(dataset_id_arg)
    field_searches = parse_csv_arg(field_search_arg)
    cache = build_metadata_cache(
        client,
        config,
        dataset_ids=dataset_ids,
        field_searches=field_searches,
        field_suffix=field_suffix,
        max_fields_per_query=max_fields,
        include_data_sets=include_data_sets,
    )
    output_dir = Path(cache_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"platform_metadata_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "cache_path": str(output_path),
                "operator_count": len(cache.get("operators", [])),
                "data_set_count": len(cache.get("data_sets", [])),
                "field_query_count": len(cache.get("field_queries", [])),
                "field_count": sum(len(query.get("fields", [])) for query in cache.get("field_queries", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return output_path


def semantic_preview(
    config: dict[str, Any],
    cache_path: str,
    dataset_id: str,
    field_search: str,
    field_suffix: str,
    template_mode: str,
    max_count: int,
) -> dict[str, Any]:
    """Input: config, cache path, filters. Output: preview dict. Generate candidate payloads locally."""
    cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    all_cached_fields = cached_fields(
        cache,
        dataset_id=dataset_id,
        field_search=field_search,
        field_suffix="",
    )
    fields = cached_fields(
        cache,
        dataset_id=dataset_id,
        field_search=field_search,
        field_suffix=field_suffix,
    )
    fields, regular_peer_missing_ids = annotate_regular_peer_availability(
        fields,
        field_suffix,
        peer_field_ids={str(field.get("id")) for field in all_cached_fields if field.get("id")},
    )
    settings = build_settings(config)
    candidates = generate_seed_candidates(
        select_seed_fields(fields, max_fields=max(FIELD_BATCH_SEED_FIELD_LIMIT, int(max_count), 1)),
        settings,
        max_count=max(int(max_count), 1),
        generation=0,
        template_mode=template_mode,
    )
    known_fields = field_ids(fields)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        complexity = is_power_pool_complexity_ok(
            candidate.expression,
            known_fields,
            int(config["power_pool_operator_limit"]),
            int(config["power_pool_field_limit"]),
        )
        rows.append(
            {
                "expression_hash": expression_hash(candidate.expression),
                "expression": candidate.expression,
                "tags": candidate.tags,
                "complexity_ok": complexity.ok,
                "operator_count": complexity.operator_count,
                "field_count": complexity.field_count,
                "reasons": complexity.reasons,
            }
        )
    preview = {
        "cache_path": cache_path,
        "dataset_id": dataset_id,
        "field_search": field_search,
        "field_suffix": field_suffix,
        "template_mode": template_mode,
        "field_count": len(fields),
        "candidate_count": len(rows),
        "regular_peer_missing_ids": regular_peer_missing_ids,
        "candidates": rows,
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    return preview


def annotate_regular_peer_availability(
    fields: list[dict[str, Any]],
    field_suffix: str,
    peer_field_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Input: field records and suffix. Output: annotated fields and missing peer ids. Mark Fast D1 peer availability."""
    all_field_ids = peer_field_ids or {str(field.get("id")) for field in fields if field.get("id")}
    missing_ids: list[str] = []
    annotated_fields: list[dict[str, Any]] = []
    for field in fields:
        field_copy = dict(field)
        field_id = str(field_copy.get("id", ""))
        if field_suffix and field_id.endswith(field_suffix):
            regular_peer = field_id[: -len(field_suffix)]
            has_regular_peer = regular_peer in all_field_ids
            field_copy["regular_peer_available"] = has_regular_peer
            if not has_regular_peer:
                missing_ids.append(field_id)
        annotated_fields.append(field_copy)
    return annotated_fields, missing_ids


def run_root_expression_hashes(run_root: str | Path) -> set[str]:
    """Input: run root path. Output: expression hashes. Collect hashes already submitted or checked."""
    root = Path(run_root)
    hashes: set[str] = set()
    if not root.exists():
        return hashes
    for run_dir in root.iterdir():
        if not run_dir.is_dir():
            continue
        recorder = RunRecorder(run_dir)
        for filename in ["simulation_events.jsonl", "all_alphas.jsonl"]:
            for record in recorder.read_jsonl(filename):
                expr_hash = record.get("expression_hash")
                if expr_hash:
                    hashes.add(str(expr_hash))
    return hashes


def latest_run_dir(run_root: str | Path) -> Path | None:
    """Input: run root path. Output: latest run directory or None. Locate recent local run artifacts."""
    root = Path(run_root)
    if not root.exists():
        return None
    run_dirs = [path for path in root.iterdir() if path.is_dir()]
    if not run_dirs:
        return None
    return max(run_dirs, key=lambda path: path.stat().st_mtime)


def summarize_run_dir(run_dir: str | Path) -> dict[str, Any]:
    """Input: run directory path. Output: status summary dict. Summarize local run artifacts."""
    recorder = RunRecorder(run_dir)
    alpha_records = recorder.read_jsonl("all_alphas.jsonl")
    action_records = recorder.read_jsonl("optimization_trace.jsonl")
    error_records = recorder.read_jsonl("run_errors.jsonl")
    simulation_records = recorder.read_jsonl("simulation_events.jsonl")
    existing_scan_records = recorder.read_jsonl("existing_alpha_scan.jsonl")
    failed_counts: Counter[str] = Counter()
    pending_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    error_counts: Counter[str] = Counter()
    existing_scan_failed_counts: Counter[str] = Counter()
    existing_scan_benchmark_counts: Counter[str] = Counter()
    existing_repair_queue: list[dict[str, Any]] = []
    benchmark_counts: Counter[str] = Counter()
    repair_queue: list[dict[str, Any]] = []
    submitted_by_hash: dict[str, dict[str, Any]] = {}
    terminal_hashes: set[str] = set()

    for record in alpha_records:
        failed_counts.update(str(item) for item in record.get("failed", []))
        pending_counts.update(str(item) for item in record.get("pending", []))
        warning_counts.update(str(item) for item in record.get("warnings", []))
        benchmark = benchmark_alpha_record(record)
        benchmark_counts[benchmark.label] += 1
        if benchmark.label == "repairable_signal":
            repair_queue.append(
                {
                    "alpha_id": record.get("alpha_id"),
                    "expression_hash": record.get("expression_hash", ""),
                    "signal_score": benchmark.score,
                    "repair_priority": benchmark.repair_priority,
                    "reasons": benchmark.reasons,
                    "failed": record.get("failed", []),
                    "pending": record.get("pending", []),
                    "metrics": record.get("metrics", {}),
                }
            )
    for record in action_records:
        action_type = record.get("action_type")
        if action_type:
            action_counts[str(action_type)] += 1
    for record in error_records:
        status_code = record.get("status_code", "UNKNOWN")
        error_counts[str(status_code)] += 1
    for record in simulation_records:
        expression_hash = record.get("expression_hash")
        if not expression_hash:
            continue
        if record.get("event") == "SUBMITTED":
            submitted_by_hash[str(expression_hash)] = record
        elif record.get("event") in {"CHECKED", "ERROR"}:
            terminal_hashes.add(str(expression_hash))
    for record in existing_scan_records:
        existing_scan_failed_counts.update(str(item) for item in record.get("failed", []))
        existing_benchmark = benchmark_alpha_record(record)
        existing_scan_benchmark_counts[existing_benchmark.label] += 1
        if existing_benchmark.label == "repairable_signal":
            existing_repair_queue.append(
                {
                    "alpha_id": record.get("alpha_id"),
                    "expression_hash": record.get("expression_hash", ""),
                    "signal_score": existing_benchmark.score,
                    "repair_priority": existing_benchmark.repair_priority,
                    "reasons": existing_benchmark.reasons,
                    "failed": record.get("failed", []),
                    "pending": record.get("pending", []),
                    "metrics": record.get("metrics", {}),
                }
            )

    in_flight = [
        record
        for expression_hash, record in submitted_by_hash.items()
        if expression_hash not in terminal_hashes
    ]
    in_flight_progress_urls = []
    seen_progress_urls: set[str] = set()
    for record in in_flight:
        progress_url = record.get("progress_url")
        if not progress_url:
            continue
        progress_url = str(progress_url)
        if progress_url in seen_progress_urls:
            continue
        seen_progress_urls.add(progress_url)
        in_flight_progress_urls.append(progress_url)

    return {
        "run_dir": str(Path(run_dir)),
        "checked_count": len(alpha_records),
        "hard_pass_count": sum(1 for record in alpha_records if record.get("hard_pass")),
        "submitted_count": len(submitted_by_hash),
        "in_flight_count": len(in_flight),
        "in_flight_progress_urls": in_flight_progress_urls,
        "alpha_ids": [record.get("alpha_id") for record in alpha_records if record.get("alpha_id")],
        "failed_counts": dict(failed_counts),
        "pending_counts": dict(pending_counts),
        "warning_counts": dict(warning_counts),
        "benchmark_counts": dict(benchmark_counts),
        "repair_queue": sorted(
            repair_queue,
            key=lambda item: (item["repair_priority"], -float(item["signal_score"] or 0)),
        ),
        "action_counts": dict(action_counts),
        "error_counts": dict(error_counts),
        "existing_scan_count": len(existing_scan_records),
        "existing_scan_hard_pass_count": sum(1 for record in existing_scan_records if record.get("hard_pass")),
        "existing_scan_failed_counts": dict(existing_scan_failed_counts),
        "existing_scan_benchmark_counts": dict(existing_scan_benchmark_counts),
        "existing_repair_queue": sorted(
            existing_repair_queue,
            key=lambda item: (item["repair_priority"], -float(item["signal_score"] or 0)),
        ),
    }


def field_batch_status_label(run_status: dict[str, Any], summaries: list[Any]) -> str:
    """Input: run status dict and check summaries list. Output: status label string. Classify batch outcome."""
    if run_status["in_flight_count"] and not summaries:
        return "pending_recovery"
    if not summaries and not run_status["submitted_count"] and run_status["error_counts"]:
        return "submit_recoverable_error"
    return "completed"


def status(config: dict[str, Any], run_dir: str | None = None) -> None:
    """Input: run config and optional run dir. Output: terminal JSON summary. Report local workflow status."""
    selected_run_dir = Path(run_dir) if run_dir else latest_run_dir(config["run_root"])
    if selected_run_dir is None:
        print(json.dumps({"run_dir": None, "message": "no run directories found"}, ensure_ascii=False, indent=2))
        return
    print(json.dumps(summarize_run_dir(selected_run_dir), ensure_ascii=False, indent=2, sort_keys=True))


def scan_existing_alpha_candidates(
    client,
    recorder: RunRecorder,
    max_scan: int,
    page_limit: int = 50,
) -> list[dict[str, Any]]:
    """Input: WQB client, recorder, limits. Output: hard-pass candidate rows from existing IS Alphas."""
    candidates: list[dict[str, Any]] = []
    scanned = 0
    offset = 0
    while scanned < max_scan:
        limit = min(page_limit, max_scan - scanned)
        page = client.get_json(f"/users/self/alphas?stage=IS&limit={limit}&offset={offset}")
        rows = page.get("results", []) if isinstance(page, dict) else []
        if not rows:
            break
        for row in rows:
            alpha_id = row.get("id")
            if not alpha_id:
                continue
            try:
                summary = fetch_check_summary(client, str(alpha_id))
            except requests.exceptions.RequestException as err:
                record_recoverable_network_error(
                    recorder,
                    "scan_existing_check",
                    err,
                    {"alpha_id": str(alpha_id)},
                )
                scanned += 1
                if scanned >= max_scan:
                    break
                continue
            scan_record = {
                "alpha_id": str(alpha_id),
                "hard_pass": summary.hard_pass,
                "metrics": summary.metrics,
                "failed": [item.name for item in summary.failed],
                "pending": [item.name for item in summary.pending],
                "warnings": [item.name for item in summary.warnings],
            }
            scan_record.update(benchmark_fields_for_record(scan_record))
            recorder.append_jsonl("existing_alpha_scan.jsonl", scan_record)
            if summary.hard_pass:
                candidate = {
                    "alpha_id": str(alpha_id),
                    "expression_hash": "",
                    "sharpe": summary.metrics.get("sharpe"),
                    "fitness": summary.metrics.get("fitness"),
                    "turnover": summary.metrics.get("turnover"),
                    "returns": summary.metrics.get("returns"),
                    "warnings": ",".join(item.name for item in summary.warnings),
                }
                candidates.append(candidate)
                recorder.write_candidates(candidates)
            scanned += 1
            if scanned >= max_scan:
                break
        if len(rows) < limit:
            break
        offset += limit
    return candidates


def benchmark_fields_for_record(alpha_record: dict[str, Any]) -> dict[str, Any]:
    """Input: alpha record. Output: benchmark fields. Attach workflow classification to a record."""
    benchmark = benchmark_alpha_record(alpha_record)
    return {
        "benchmark_label": benchmark.label,
        "signal_score": benchmark.score,
        "repair_priority": benchmark.repair_priority,
        "benchmark_reasons": benchmark.reasons,
        "next_stage": benchmark.next_stage,
    }


def inspect_existing_alpha(
    client,
    recorder: RunRecorder,
    alpha_id: str,
    signal_note: str = "",
):
    """Input: client, recorder, alpha id, note. Output: check summary. Inspect an existing Alpha without resim."""
    summary = fetch_check_summary(client, alpha_id)
    record = {
        "alpha_id": alpha_id,
        "expression_hash": "",
        "status": "INSPECTED",
        "hard_pass": summary.hard_pass,
        "metrics": summary.metrics,
        "failed": [item.name for item in summary.failed],
        "pending": [item.name for item in summary.pending],
        "warnings": [item.name for item in summary.warnings],
    }
    if signal_note:
        record["signal_note"] = signal_note
    record.update(benchmark_fields_for_record(record))
    recorder.append_jsonl("all_alphas.jsonl", record)
    if summary.hard_pass:
        recorder.write_candidates(
            [
                {
                    "alpha_id": alpha_id,
                    "expression_hash": "",
                    "sharpe": summary.metrics.get("sharpe"),
                    "fitness": summary.metrics.get("fitness"),
                    "turnover": summary.metrics.get("turnover"),
                    "returns": summary.metrics.get("returns"),
                    "warnings": ",".join(item.name for item in summary.warnings),
                }
            ]
        )
    return summary


def inspect_alpha(config: dict[str, Any], alpha_id: str, run_dir: str | None = None, signal_note: str = "") -> None:
    """Input: config, alpha id, run dir, note. Output: terminal JSON. Inspect and benchmark one Alpha."""
    selected_run_dir = Path(run_dir) if run_dir else make_run_dir(config)
    recorder = RunRecorder(selected_run_dir)
    client = build_client(config)
    if not authenticate_for_run(client, recorder, "inspect_alpha_auth"):
        print(json.dumps({"run_dir": str(selected_run_dir), "status": "auth_recoverable_error"}, ensure_ascii=False))
        return
    try:
        summary = inspect_existing_alpha(client, recorder, alpha_id, signal_note=signal_note)
    except requests.exceptions.RequestException as err:
        record_recoverable_network_error(recorder, "inspect_alpha", err, {"alpha_id": alpha_id})
        print(json.dumps({"run_dir": str(selected_run_dir), "status": "recoverable_error"}, ensure_ascii=False))
        return
    record = recorder.read_jsonl("all_alphas.jsonl")[-1]
    print(
        json.dumps(
            {
                "run_dir": str(selected_run_dir),
                "alpha_id": alpha_id,
                "hard_pass": summary.hard_pass,
                "failed": record["failed"],
                "pending": record["pending"],
                "warnings": record["warnings"],
                "metrics": record["metrics"],
                "benchmark_label": record["benchmark_label"],
                "signal_score": record["signal_score"],
                "repair_priority": record["repair_priority"],
                "benchmark_reasons": record["benchmark_reasons"],
                "next_stage": record["next_stage"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def extract_existing_alpha_expression(alpha: dict[str, Any], alpha_id: str) -> str:
    """Input: alpha detail dict and alpha id. Output: expression string. Extract REGULAR code safely."""
    regular = alpha.get("regular")
    expression = regular.get("code") if isinstance(regular, dict) else regular
    if not isinstance(expression, str) or not expression.strip():
        raise RuntimeError(f"alpha {alpha_id} missing regular expression")
    return expression


def refresh_existing_alpha(
    client,
    recorder: RunRecorder,
    alpha_id: str,
    operator_replacements: dict[str, str] | None = None,
    setting_overrides: dict[str, Any] | None = None,
):
    """Input: WQB client, run recorder, alpha id. Output: check summary. Re-simulate and check an old Alpha."""
    alpha = client.get_json(f"/alphas/{alpha_id}")
    if not isinstance(alpha, dict):
        raise RuntimeError(f"alpha {alpha_id} detail response is not an object")
    settings = alpha.get("settings")
    if not isinstance(settings, dict):
        raise RuntimeError(f"alpha {alpha_id} missing settings")
    settings = dict(settings)
    overrides = setting_overrides or {}
    if overrides:
        settings.update(overrides)
    expression = extract_existing_alpha_expression(alpha, alpha_id)
    replacements = operator_replacements or {}
    if replacements:
        expression = replace_operator_names(expression, replacements)
    expr_hash = expression_hash(expression)
    try:
        progress_url = submit_simulation(client, simulation_payload(settings, expression))
    except requests.exceptions.RequestException as err:
        record_recoverable_network_error(
            recorder,
            "refresh_alpha_submit",
            err,
            {
                "parent_alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "operator_replacements": replacements,
                "setting_overrides": overrides,
            },
        )
        return None
    recorder.append_jsonl(
        "simulation_events.jsonl",
        {
            "event": "SUBMITTED",
            "parent_alpha_id": alpha_id,
            "expression_hash": expr_hash,
            "operator_replacements": replacements,
            "setting_overrides": overrides,
            "progress_url": progress_url,
        },
    )

    try:
        progress = poll_simulation(client, progress_url)
    except requests.exceptions.RequestException as err:
        record_recoverable_network_error(
            recorder,
            "refresh_alpha_poll",
            err,
            {
                "parent_alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "progress_url": progress_url,
                "operator_replacements": replacements,
                "setting_overrides": overrides,
            },
        )
        return None
    if str(progress.get("status", "")).upper() == "ERROR":
        message = str(progress.get("message", "simulation returned ERROR"))
        recorder.append_jsonl(
            "simulation_events.jsonl",
            {
                "event": "ERROR",
                "parent_alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "simulation_id": progress.get("id"),
                "message": message,
                "operator_replacements": replacements,
                "setting_overrides": overrides,
            },
        )
        recorder.append_jsonl(
            "run_errors.jsonl",
            {
                "stage": "refresh_alpha",
                "status": "ERROR",
                "status_code": "SIMULATION_ERROR",
                "parent_alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "message": message,
                "operator_replacements": replacements,
                "setting_overrides": overrides,
            },
        )
        return None

    refreshed_alpha_id = extract_alpha_id(progress)
    try:
        summary = fetch_check_summary(client, refreshed_alpha_id)
    except requests.exceptions.RequestException as err:
        record_recoverable_network_error(
            recorder,
            "refresh_alpha_check",
            err,
            {
                "parent_alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "progress_url": progress_url,
                "alpha_id": refreshed_alpha_id,
                "operator_replacements": replacements,
                "setting_overrides": overrides,
            },
        )
        return None
    recorder.append_jsonl(
        "simulation_events.jsonl",
        {
            "event": "CHECKED",
            "parent_alpha_id": alpha_id,
            "expression_hash": expr_hash,
            "alpha_id": refreshed_alpha_id,
            "operator_replacements": replacements,
            "setting_overrides": overrides,
        },
    )
    recorder.append_jsonl(
        "all_alphas.jsonl",
        {
            "alpha_id": refreshed_alpha_id,
            "parent_alpha_id": alpha_id,
            "expression_hash": expr_hash,
            "status": "CHECKED",
            "hard_pass": summary.hard_pass,
            "metrics": summary.metrics,
            "failed": [item.name for item in summary.failed],
            "pending": [item.name for item in summary.pending],
            "warnings": [item.name for item in summary.warnings],
            "operator_replacements": replacements,
            "setting_overrides": overrides,
        },
    )

    candidate_rows: list[dict[str, Any]] = []
    if summary.hard_pass:
        candidate_rows.append(
            {
                "alpha_id": refreshed_alpha_id,
                "expression_hash": expr_hash,
                "sharpe": summary.metrics.get("sharpe"),
                "fitness": summary.metrics.get("fitness"),
                "turnover": summary.metrics.get("turnover"),
                "returns": summary.metrics.get("returns"),
                "warnings": ",".join(item.name for item in summary.warnings),
            }
        )
    recorder.write_candidates(candidate_rows)
    return summary


def refresh_existing_alpha_batch(
    client,
    recorder: RunRecorder,
    alpha_id: str,
    setting_variants: list[dict[str, Any]],
    operator_replacements: dict[str, str] | None = None,
    base_setting_overrides: dict[str, Any] | None = None,
    submit_mode: str = "multi",
):
    """Input: WQB client, recorder, alpha id, variants. Output: check summaries. Batch refresh old Alpha."""
    if submit_mode not in {"multi", "serial"}:
        raise ValueError("submit_mode must be 'multi' or 'serial'")
    alpha = client.get_json(f"/alphas/{alpha_id}")
    if not isinstance(alpha, dict):
        raise RuntimeError(f"alpha {alpha_id} detail response is not an object")
    base_settings = alpha.get("settings")
    if not isinstance(base_settings, dict):
        raise RuntimeError(f"alpha {alpha_id} missing settings")
    expression = extract_existing_alpha_expression(alpha, alpha_id)
    replacements = operator_replacements or {}
    if replacements:
        expression = replace_operator_names(expression, replacements)
    fixed_overrides = base_setting_overrides or {}
    variants = setting_variants or [{}]
    payloads: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    for variant in variants:
        settings = dict(base_settings)
        settings.update(fixed_overrides)
        settings.update(variant)
        sim_hash = simulation_identity_hash(expression, settings)
        payloads.append(simulation_payload(settings, expression))
        metadata.append(
            {
                "parent_alpha_id": alpha_id,
                "expression_hash": sim_hash,
                "operator_replacements": replacements,
                "setting_overrides": dict(fixed_overrides),
                "setting_variant": dict(variant),
            }
        )

    if submit_mode == "serial":
        summaries = []
        candidate_rows: list[dict[str, Any]] = []
        for payload, item in zip(payloads, metadata):
            try:
                progress_url = submit_simulation(client, payload)
            except requests.exceptions.RequestException as err:
                record_recoverable_network_error(recorder, "refresh_alpha_batch_serial_submit", err, item)
                continue
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "SUBMITTED",
                    "progress_url": progress_url,
                    **item,
                },
            )
            try:
                progress = poll_simulation(client, progress_url)
            except requests.exceptions.RequestException as err:
                record_recoverable_network_error(
                    recorder,
                    "refresh_alpha_batch_serial_poll",
                    err,
                    {"progress_url": progress_url, **item},
                )
                continue
            if str(progress.get("status", "")).upper() == "ERROR":
                message = str(progress.get("message", "simulation returned ERROR"))
                recorder.append_jsonl(
                    "simulation_events.jsonl",
                    {
                        "event": "ERROR",
                        "simulation_id": progress.get("id"),
                        "message": message,
                        **item,
                    },
                )
                recorder.append_jsonl(
                    "run_errors.jsonl",
                    {
                        "stage": "refresh_alpha_batch_serial",
                        "status": "ERROR",
                        "status_code": "SIMULATION_ERROR",
                        "message": message,
                        **item,
                    },
                )
                continue
            refreshed_alpha_id = extract_alpha_id(progress)
            try:
                summary = fetch_check_summary(client, refreshed_alpha_id)
            except requests.exceptions.RequestException as err:
                record_recoverable_network_error(
                    recorder,
                    "refresh_alpha_batch_serial_check",
                    err,
                    {"progress_url": progress_url, "alpha_id": refreshed_alpha_id, **item},
                )
                continue
            summaries.append(summary)
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "CHECKED",
                    "alpha_id": refreshed_alpha_id,
                    **item,
                },
            )
            recorder.append_jsonl(
                "all_alphas.jsonl",
                {
                    "alpha_id": refreshed_alpha_id,
                    "status": "CHECKED",
                    "hard_pass": summary.hard_pass,
                    "metrics": summary.metrics,
                    "failed": [check.name for check in summary.failed],
                    "pending": [check.name for check in summary.pending],
                    "warnings": [check.name for check in summary.warnings],
                    **item,
                },
            )
            if summary.hard_pass:
                candidate_rows.append(
                    {
                        "alpha_id": refreshed_alpha_id,
                        "expression_hash": item["expression_hash"],
                        "sharpe": summary.metrics.get("sharpe"),
                        "fitness": summary.metrics.get("fitness"),
                        "turnover": summary.metrics.get("turnover"),
                        "returns": summary.metrics.get("returns"),
                        "warnings": ",".join(check.name for check in summary.warnings),
                    }
                )
        if candidate_rows:
            recorder.write_candidates(candidate_rows)
        return summaries

    try:
        progress_url = submit_multisimulation(client, payloads)
    except requests.exceptions.RequestException as err:
        record_recoverable_network_error(
            recorder,
            "refresh_alpha_batch_submit",
            err,
            {
                "parent_alpha_id": alpha_id,
                "operator_replacements": replacements,
                "setting_overrides": dict(fixed_overrides),
                "variant_count": len(metadata),
            },
        )
        return []
    for item in metadata:
        recorder.append_jsonl(
            "simulation_events.jsonl",
            {
                "event": "SUBMITTED",
                "progress_url": progress_url,
                **item,
            },
        )

    try:
        progress = poll_simulation(client, progress_url)
    except requests.exceptions.RequestException as err:
        for item in metadata:
            record_recoverable_network_error(
                recorder,
                "refresh_alpha_batch_poll",
                err,
                {"progress_url": progress_url, **item},
            )
        return []
    if str(progress.get("status", "")).upper() == "ERROR":
        message = str(progress.get("message", "multisimulation returned ERROR"))
        for item in metadata:
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "ERROR",
                    "simulation_id": progress.get("id"),
                    "message": message,
                    **item,
                },
            )
            recorder.append_jsonl(
                "run_errors.jsonl",
                {
                    "stage": "refresh_alpha_batch",
                    "status": "ERROR",
                    "status_code": "SIMULATION_ERROR",
                    "message": message,
                    **item,
                },
            )
        return []

    alpha_ids = resolve_multisimulation_alpha_ids(client, progress)
    summaries = []
    candidate_rows: list[dict[str, Any]] = []
    for item, refreshed_alpha_id in zip(metadata, alpha_ids):
        try:
            summary = fetch_check_summary(client, refreshed_alpha_id)
        except requests.exceptions.RequestException as err:
            record_recoverable_network_error(
                recorder,
                "refresh_alpha_batch_check",
                err,
                {"progress_url": progress_url, "alpha_id": refreshed_alpha_id, **item},
            )
            continue
        summaries.append(summary)
        recorder.append_jsonl(
            "simulation_events.jsonl",
            {
                "event": "CHECKED",
                "alpha_id": refreshed_alpha_id,
                **item,
            },
        )
        recorder.append_jsonl(
            "all_alphas.jsonl",
            {
                "alpha_id": refreshed_alpha_id,
                "status": "CHECKED",
                "hard_pass": summary.hard_pass,
                "metrics": summary.metrics,
                "failed": [check.name for check in summary.failed],
                "pending": [check.name for check in summary.pending],
                "warnings": [check.name for check in summary.warnings],
                **item,
            },
        )
        if summary.hard_pass:
            candidate_rows.append(
                {
                    "alpha_id": refreshed_alpha_id,
                    "expression_hash": item["expression_hash"],
                    "sharpe": summary.metrics.get("sharpe"),
                    "fitness": summary.metrics.get("fitness"),
                    "turnover": summary.metrics.get("turnover"),
                    "returns": summary.metrics.get("returns"),
                    "warnings": ",".join(check.name for check in summary.warnings),
                }
            )
    if candidate_rows:
        recorder.write_candidates(candidate_rows)
    return summaries


def repair_existing_alpha_with_field(
    client,
    recorder: RunRecorder,
    alpha_id: str,
    field_expression: str,
    blend_weights: list[float],
) -> list[Any]:
    """Input: client, recorder, alpha id, field expression, weights. Output: summaries. Blend near-miss Alpha with new data."""
    alpha = client.get_json(f"/alphas/{alpha_id}")
    if not isinstance(alpha, dict):
        raise RuntimeError(f"alpha {alpha_id} detail response is not an object")
    settings = alpha.get("settings")
    if not isinstance(settings, dict):
        raise RuntimeError(f"alpha {alpha_id} missing settings")
    base_expression = extract_existing_alpha_expression(alpha, alpha_id)
    summaries = []
    candidate_rows: list[dict[str, Any]] = []

    for weight in blend_weights:
        expression = blend_repair_expression(base_expression, field_expression, weight)
        expr_hash = simulation_identity_hash(expression, settings)
        try:
            progress_url = submit_simulation(client, simulation_payload(dict(settings), expression))
        except requests.exceptions.RequestException as err:
            record_recoverable_network_error(
                recorder,
                "repair_alpha_submit",
                err,
                {
                    "parent_alpha_id": alpha_id,
                    "expression_hash": expr_hash,
                    "expression": expression,
                    "field_expression": field_expression,
                    "blend_weight": weight,
                    "workflow_stage": "repair",
                },
            )
            if is_http_status_error(err, 429):
                break
            continue
        recorder.append_jsonl(
            "simulation_events.jsonl",
            {
                "event": "SUBMITTED",
                "parent_alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "expression": expression,
                "field_expression": field_expression,
                "blend_weight": weight,
                "workflow_stage": "repair",
                "progress_url": progress_url,
            },
        )
        try:
            progress = poll_simulation(client, progress_url)
        except requests.exceptions.RequestException as err:
            record_recoverable_network_error(
                recorder,
                "repair_alpha_poll",
                err,
                {
                    "parent_alpha_id": alpha_id,
                    "expression_hash": expr_hash,
                    "expression": expression,
                    "field_expression": field_expression,
                    "blend_weight": weight,
                    "workflow_stage": "repair",
                    "progress_url": progress_url,
                },
            )
            continue
        if str(progress.get("status", "")).upper() == "ERROR":
            message = str(progress.get("message", "simulation returned ERROR"))
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "ERROR",
                    "parent_alpha_id": alpha_id,
                    "expression_hash": expr_hash,
                    "expression": expression,
                    "field_expression": field_expression,
                    "blend_weight": weight,
                    "workflow_stage": "repair",
                    "message": message,
                },
            )
            continue
        repaired_alpha_id = extract_alpha_id(progress)
        try:
            summary = fetch_check_summary(client, repaired_alpha_id)
        except requests.exceptions.RequestException as err:
            record_recoverable_network_error(
                recorder,
                "repair_alpha_check",
                err,
                {
                    "parent_alpha_id": alpha_id,
                    "alpha_id": repaired_alpha_id,
                    "expression_hash": expr_hash,
                    "expression": expression,
                    "field_expression": field_expression,
                    "blend_weight": weight,
                    "workflow_stage": "repair",
                    "progress_url": progress_url,
                },
            )
            continue
        summaries.append(summary)
        recorder.append_jsonl(
            "simulation_events.jsonl",
            {
                "event": "CHECKED",
                "parent_alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "alpha_id": repaired_alpha_id,
                "field_expression": field_expression,
                "blend_weight": weight,
                "workflow_stage": "repair",
            },
        )
        recorder.append_jsonl(
            "all_alphas.jsonl",
            {
                "alpha_id": repaired_alpha_id,
                "parent_alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "status": "CHECKED",
                "hard_pass": summary.hard_pass,
                "metrics": summary.metrics,
                "failed": [item.name for item in summary.failed],
                "pending": [item.name for item in summary.pending],
                "warnings": [item.name for item in summary.warnings],
                "expression": expression,
                "field_expression": field_expression,
                "blend_weight": weight,
                "workflow_stage": "repair",
            },
        )
        if summary.hard_pass:
            candidate_rows.append(
                {
                    "alpha_id": repaired_alpha_id,
                    "expression_hash": expr_hash,
                    "sharpe": summary.metrics.get("sharpe"),
                    "fitness": summary.metrics.get("fitness"),
                    "turnover": summary.metrics.get("turnover"),
                    "returns": summary.metrics.get("returns"),
                    "warnings": ",".join(item.name for item in summary.warnings),
                }
            )
            recorder.write_candidates(candidate_rows)
    return summaries


def load_expression_file_items(expression_file: str | Path) -> list[dict[str, Any]]:
    """Input: JSONL path (str|Path). Output: items (list[dict]). Read custom expression batch items."""
    path = Path(expression_file)
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"expression file line {line_number} must be a JSON object")
            if not isinstance(item.get("base_alpha_id"), str) or not item["base_alpha_id"].strip():
                raise ValueError(f"expression file line {line_number} missing base_alpha_id")
            if not isinstance(item.get("expression"), str) or not item["expression"].strip():
                raise ValueError(f"expression file line {line_number} missing expression")
            items.append(item)
    return items


def load_novelty_reference_records(reference_files: list[str] | None) -> list[dict[str, Any]]:
    """Input: JSONL paths list[str]|None. Output: records list[dict]. Read novelty reference ledgers."""
    records: list[dict[str, Any]] = []
    for reference_file in reference_files or []:
        path = Path(reference_file)
        with path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"novelty reference line {line_number} in {path} must be a JSON object")
                records.append(record)
    return records


def run_expression_file_batch(
    client,
    recorder: RunRecorder,
    expression_file: str | Path,
    submit_mode: str = "serial",
    defer_poll: bool = False,
    seen_hashes: set[str] | None = None,
    multi_chunk_sleep_seconds: float = DEFAULT_MULTI_CHUNK_SLEEP_SECONDS,
    novelty_reference_records: list[dict[str, Any]] | None = None,
    min_novelty_score: int | None = None,
) -> list[Any]:
    """Input: client, recorder, JSONL path. Output: check summaries. Run custom expressions with cloned settings."""
    items = load_expression_file_items(expression_file)
    detail_cache: dict[str, dict[str, Any]] = {}
    seen_hashes = set(seen_hashes or set())
    seen_hashes.update(recorder.seen_expression_hashes())
    for event in recorder.read_jsonl("simulation_events.jsonl"):
        event_hash = event.get("expression_hash")
        if event_hash and event.get("event") in {"SUBMITTED", "CHECKED", "ERROR"}:
            seen_hashes.add(str(event_hash))
    payloads: list[dict[str, Any]] = []
    metadata_items: list[dict[str, Any]] = []
    for item in items:
        base_alpha_id = str(item["base_alpha_id"])
        if base_alpha_id not in detail_cache:
            detail = client.get_json(f"/alphas/{base_alpha_id}")
            if not isinstance(detail, dict):
                raise RuntimeError(f"alpha {base_alpha_id} detail response is not an object")
            detail_cache[base_alpha_id] = detail
        settings = detail_cache[base_alpha_id].get("settings")
        if not isinstance(settings, dict):
            raise RuntimeError(f"alpha {base_alpha_id} missing settings")
        settings = dict(settings)
        setting_overrides = item.get("setting_overrides") or {}
        if not isinstance(setting_overrides, dict):
            raise ValueError(f"setting_overrides for {base_alpha_id} must be an object")
        settings.update(setting_overrides)
        expression = str(item["expression"])
        tag = item.get("tag")
        workflow_stage = str(item.get("workflow_stage", "repair"))
        expr_hash = simulation_identity_hash(expression, settings)
        if expr_hash in seen_hashes:
            continue
        metadata = {
            "base_alpha_id": base_alpha_id,
            "tag": tag,
            "expression_hash": expr_hash,
            "expression": expression,
            "workflow_stage": workflow_stage,
            "setting_overrides": setting_overrides,
        }
        if min_novelty_score is not None:
            novelty = score_expression_novelty(expression, settings, novelty_reference_records or [])
            metadata["novelty_score"] = novelty.score
            metadata["novelty_label"] = novelty.label
            metadata["novelty_reasons"] = novelty.reasons
            if novelty.score < min_novelty_score:
                recorder.append_jsonl(
                    "novelty_rejections.jsonl",
                    {
                        "base_alpha_id": base_alpha_id,
                        "tag": tag,
                        "expression_hash": expr_hash,
                        "expression": expression,
                        "novelty_score": novelty.score,
                        "novelty_label": novelty.label,
                        "novelty_reasons": novelty.reasons,
                        "novelty_profile": novelty.profile,
                    },
                )
                continue
        seen_hashes.add(expr_hash)
        metadata_items.append(metadata)
        payloads.append(simulation_payload(settings, expression))
    return submit_candidate_payloads(
        client,
        recorder,
        payloads,
        metadata_items,
        submit_mode,
        "run_expression_file",
        defer_poll=defer_poll,
        multi_chunk_sleep_seconds=multi_chunk_sleep_seconds,
    )


def split_top_level_args(argument_text: str) -> list[str]:
    """Input: argument text (str). Output: top-level args (list[str]). Split WQB call args without breaking nested calls."""
    args: list[str] = []
    current: list[str] = []
    depth = 0
    for char in argument_text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        args.append("".join(current).strip())
    return args


def trade_when_blend_expression(final_expression: str, field_expression: str, weight: float) -> str:
    """Input: final expression/field/weight (str,str,float). Output: trade_when-aware blend or empty str."""
    stripped = final_expression.strip()
    prefix = "trade_when("
    if not stripped.startswith(prefix) or not stripped.endswith(")"):
        return ""
    args = split_top_level_args(stripped[len(prefix) : -1])
    if len(args) != 3:
        return ""
    condition, signal, exit_condition = args
    blended_signal = f"rank(({signal})) + {weight:g} * rank({field_expression})"
    return f"trade_when({condition}, {blended_signal}, {exit_condition})"


def blend_repair_expression(base_expression: str, field_expression: str, weight: float) -> str:
    """Input: base expression/field/weight (str,str,float). Output: blended expression (str). Preserve assignments."""
    parts = [part.strip() for part in base_expression.replace("\r\n", "\n").split(";") if part.strip()]
    if not parts:
        raise ValueError("base expression is empty")
    final_expression = parts[-1]
    blend = trade_when_blend_expression(final_expression, field_expression, weight)
    if not blend:
        blend = f"rank(({final_expression})) + {weight:g} * rank({field_expression})"
    if len(parts) == 1:
        return blend
    assignments = ";\n".join(parts[:-1])
    return f"{assignments};\n{blend}"


def run_field_batch(
    client,
    recorder: RunRecorder,
    config: dict[str, Any],
    field_search: str = "",
    dataset_id: str = "",
    field_suffix: str = "",
    template_mode: str = "basic",
    workflow_stage: str = "discovery",
    human_idea: str = "",
    exact_field_id: str = "",
    submit_mode: str = "serial",
    field_cache_path: str = "",
    defer_poll: bool = False,
    multi_chunk_sleep_seconds: float = DEFAULT_MULTI_CHUNK_SLEEP_SECONDS,
) -> list[Any]:
    """Input: WQB client, recorder, config, field filters, mode. Output: check summaries. Run seed fields."""
    field_source = "api"
    if field_cache_path:
        field_cache = json.loads(Path(field_cache_path).read_text(encoding="utf-8"))
        fields = cached_fields(
            field_cache,
            dataset_id=dataset_id,
            field_search=field_search,
            field_suffix=field_suffix,
        )
        field_source = "cache"
    else:
        fields = fetch_data_fields(
            client,
            config["instrument_type"],
            config["region"],
            int(config["delay"]),
            config["universe"],
            dataset_id=dataset_id,
            search=field_search,
            max_records=FIELD_BATCH_API_MAX_RECORDS,
        )
    all_field_ids = {str(field.get("id")) for field in fields if field.get("id")}
    if not field_cache_path:
        fields = filter_fields_by_suffix(fields, field_suffix)
    if exact_field_id:
        fields = [field for field in fields if str(field.get("id", "")) == exact_field_id]
    fields, regular_peer_missing_ids = annotate_regular_peer_availability(
        fields,
        field_suffix,
        peer_field_ids=all_field_ids,
    )
    requested_max_alphas = int(config["max_alphas_per_round"])
    effective_max_alphas = cap_simulation_count(workflow_stage, requested_max_alphas)
    candidate_generation_limit = max(
        effective_max_alphas * FIELD_BATCH_CANDIDATE_BUFFER_MULTIPLIER,
        effective_max_alphas,
    )
    seed_fields = select_seed_fields(fields, max_fields=FIELD_BATCH_SEED_FIELD_LIMIT)
    recorder.append_jsonl(
        "run_meta.jsonl",
        {
            "data_fields_path": (
                f"/data-fields?instrumentType={config['instrument_type']}&region={config['region']}"
                f"&delay={int(config['delay'])}&universe={config['universe']}"
                f"&dataset.id={dataset_id}&search={field_search}"
            ),
            "field_count": len(fields),
            "field_search": field_search,
            "dataset_id": dataset_id,
            "field_suffix": field_suffix,
            "template_mode": template_mode,
            "workflow_stage": workflow_stage,
            "human_idea": human_idea,
            "exact_field_id": exact_field_id,
            "submit_mode": submit_mode,
            "field_source": field_source,
            "field_cache_path": field_cache_path,
            "defer_poll": defer_poll,
            "multi_chunk_sleep_seconds": multi_chunk_sleep_seconds,
            "requested_max_alphas": requested_max_alphas,
            "effective_max_alphas": effective_max_alphas,
            "candidate_generation_limit": candidate_generation_limit,
            "seed_field_ids": [str(field.get("id")) for field in seed_fields],
            "regular_peer_missing_ids": regular_peer_missing_ids,
        },
    )
    settings = build_settings(config)
    candidates = generate_seed_candidates(
        seed_fields,
        settings,
        candidate_generation_limit,
        generation=0,
        template_mode=template_mode,
    )
    filtered_candidates = []
    for candidate in candidates:
        precheck = precheck_expression(candidate.expression, workflow_stage)
        if precheck.ok:
            filtered_candidates.append(candidate)
            continue
        recorder.append_jsonl(
            "precheck_rejections.jsonl",
            {
                "workflow_stage": workflow_stage,
                "expression": candidate.expression,
                "reasons": precheck.reasons,
                "line_count": precheck.line_count,
                "nesting_depth": precheck.nesting_depth,
                "numeric_param_count": precheck.numeric_param_count,
            },
        )
    candidates = filtered_candidates
    metadata: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    seen_expression_hashes = run_root_expression_hashes(config.get("run_root", "runs"))
    for candidate in candidates:
        expr_hash = expression_hash(candidate.expression)
        if expr_hash in seen_expression_hashes:
            recorder.append_jsonl(
                "duplicate_rejections.jsonl",
                {
                    "expression_hash": expr_hash,
                    "expression": candidate.expression,
                    "reason": "seen_in_run_root",
                },
            )
            continue
        seen_expression_hashes.add(expr_hash)
        metadata.append(
            {
                "expression_hash": expr_hash,
                "expression": candidate.expression,
                "field_search": field_search,
                "dataset_id": dataset_id,
                "field_suffix": field_suffix,
                "template_mode": template_mode,
                "workflow_stage": workflow_stage,
                "human_idea": human_idea,
            }
        )
        payloads.append(simulation_payload(candidate.settings, candidate.expression))
        if len(metadata) >= effective_max_alphas:
            break
    for item in metadata:
        recorder.append_jsonl("planned_candidates.jsonl", item)

    summaries = []
    candidate_rows: list[dict[str, Any]] = []

    if submit_mode not in {"multi", "serial"}:
        raise ValueError("submit_mode must be 'multi' or 'serial'")

    if submit_mode == "multi":
        if not payloads:
            return []
        fallback_payloads: list[dict[str, Any]] = []
        fallback_metadata: list[dict[str, Any]] = []
        for start in range(0, len(payloads), FIELD_BATCH_MULTI_CHUNK_SIZE):
            if start > 0 and multi_chunk_sleep_seconds > 0:
                time.sleep(multi_chunk_sleep_seconds)
            chunk_payloads = payloads[start : start + FIELD_BATCH_MULTI_CHUNK_SIZE]
            chunk_metadata = metadata[start : start + FIELD_BATCH_MULTI_CHUNK_SIZE]
            try:
                progress_url = submit_multisimulation(client, chunk_payloads)
            except requests.exceptions.RequestException as err:
                record_recoverable_network_error(
                    recorder,
                    "run_field_batch_multi_submit",
                    err,
                    {
                        "payload_count": len(chunk_payloads),
                        "dataset_id": dataset_id,
                        "template_mode": template_mode,
                        "chunk_start": start,
                    },
                )
                if is_http_status_error(err, 400):
                    fallback_payloads.extend(chunk_payloads)
                    fallback_metadata.extend(chunk_metadata)
                if is_http_status_error(err, 429):
                    break
                continue
            for item in chunk_metadata:
                recorder.append_jsonl(
                    "simulation_events.jsonl",
                    {
                        "event": "SUBMITTED",
                        "progress_url": progress_url,
                        **item,
                    },
                )
            if defer_poll:
                continue
            try:
                progress = poll_simulation(client, progress_url)
            except requests.exceptions.RequestException as err:
                for item in chunk_metadata:
                    record_recoverable_network_error(
                        recorder,
                        "run_field_batch_multi_poll",
                        err,
                        {"progress_url": progress_url, **item},
                    )
                continue
            if str(progress.get("status", "")).upper() == "ERROR":
                message = str(progress.get("message", "multisimulation returned ERROR"))
                for item in chunk_metadata:
                    recorder.append_jsonl(
                        "simulation_events.jsonl",
                        {"event": "ERROR", "message": message, "progress_url": progress_url, **item},
                    )
                    recorder.append_jsonl(
                        "run_errors.jsonl",
                        {
                            "stage": "run_field_batch_multi",
                            "status": "ERROR",
                            "status_code": "SIMULATION_ERROR",
                            "message": message,
                            **item,
                        },
                    )
                continue
            alpha_ids = resolve_multisimulation_alpha_ids(client, progress)
            for item, alpha_id in zip(chunk_metadata, alpha_ids):
                try:
                    summary = fetch_check_summary(client, alpha_id)
                except requests.exceptions.RequestException as err:
                    record_recoverable_network_error(
                        recorder,
                        "run_field_batch_multi_check",
                        err,
                        {"alpha_id": alpha_id, "progress_url": progress_url, **item},
                    )
                    continue
                summaries.append(summary)
                recorder.append_jsonl(
                    "simulation_events.jsonl",
                    {"event": "CHECKED", "alpha_id": alpha_id, **item},
                )
                recorder.append_jsonl(
                    "all_alphas.jsonl",
                    {
                        "alpha_id": alpha_id,
                        "status": "CHECKED",
                        "hard_pass": summary.hard_pass,
                        "metrics": summary.metrics,
                        "failed": [check.name for check in summary.failed],
                        "pending": [check.name for check in summary.pending],
                        "warnings": [check.name for check in summary.warnings],
                        **item,
                    },
                )
                if summary.hard_pass:
                    candidate_rows.append(
                        {
                            "alpha_id": alpha_id,
                            "expression_hash": item["expression_hash"],
                            "sharpe": summary.metrics.get("sharpe"),
                            "fitness": summary.metrics.get("fitness"),
                            "turnover": summary.metrics.get("turnover"),
                            "returns": summary.metrics.get("returns"),
                            "warnings": ",".join(check.name for check in summary.warnings),
                        }
                    )
        if not fallback_payloads:
            if candidate_rows:
                recorder.write_candidates(candidate_rows)
            return summaries
        payloads = fallback_payloads
        metadata = fallback_metadata

    for payload, item in zip(payloads, metadata):
        try:
            progress_url = submit_simulation(client, payload)
        except requests.exceptions.RequestException as err:
            record_recoverable_network_error(
                recorder,
                "run_field_batch_submit",
                err,
                item,
            )
            if is_http_status_error(err, 429):
                break
            continue
        recorder.append_jsonl(
            "simulation_events.jsonl",
            {
                "event": "SUBMITTED",
                "progress_url": progress_url,
                **item,
            },
        )
        try:
            progress = poll_simulation(client, progress_url)
        except requests.exceptions.RequestException as err:
            record_recoverable_network_error(
                recorder,
                "run_field_batch_poll",
                err,
                {"progress_url": progress_url, **item},
            )
            continue
        if str(progress.get("status", "")).upper() == "ERROR":
            message = str(progress.get("message", "simulation returned ERROR"))
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "ERROR",
                    "message": message,
                    "progress_url": progress_url,
                    **item,
                },
            )
            recorder.append_jsonl(
                "run_errors.jsonl",
                {
                    "stage": "run_field_batch",
                    "status": "ERROR",
                    "status_code": "SIMULATION_ERROR",
                    "message": message,
                    **item,
                },
            )
            continue
        alpha_id = extract_alpha_id(progress)
        try:
            summary = fetch_check_summary(client, alpha_id)
        except requests.exceptions.RequestException as err:
            record_recoverable_network_error(
                recorder,
                "run_field_batch_check",
                err,
                {
                    "alpha_id": alpha_id,
                    "progress_url": progress_url,
                    **item,
                },
            )
            continue
        summaries.append(summary)
        recorder.append_jsonl(
            "simulation_events.jsonl",
            {
                "event": "CHECKED",
                "alpha_id": alpha_id,
                **item,
            },
        )
        recorder.append_jsonl(
            "all_alphas.jsonl",
            {
                "alpha_id": alpha_id,
                "expression_hash": item["expression_hash"],
                "status": "CHECKED",
                "hard_pass": summary.hard_pass,
                "metrics": summary.metrics,
                "failed": [item.name for item in summary.failed],
                "pending": [item.name for item in summary.pending],
                "warnings": [item.name for item in summary.warnings],
                **item,
            },
        )
        if summary.hard_pass:
            candidate_rows.append(
                {
                    "alpha_id": alpha_id,
                    "expression_hash": item["expression_hash"],
                    "sharpe": summary.metrics.get("sharpe"),
                    "fitness": summary.metrics.get("fitness"),
                    "turnover": summary.metrics.get("turnover"),
                    "returns": summary.metrics.get("returns"),
                    "warnings": ",".join(item.name for item in summary.warnings),
                }
            )
            recorder.write_candidates(candidate_rows)
    if candidate_rows:
        recorder.write_candidates(candidate_rows)
    return summaries


def candidate_row_from_summary(alpha_id: str, item: dict[str, Any], summary: Any) -> dict[str, Any]:
    """Input: alpha id, metadata, summary. Output: CSV candidate row. Format a hard-pass Alpha."""
    return {
        "alpha_id": alpha_id,
        "expression_hash": item["expression_hash"],
        "sharpe": summary.metrics.get("sharpe"),
        "fitness": summary.metrics.get("fitness"),
        "turnover": summary.metrics.get("turnover"),
        "returns": summary.metrics.get("returns"),
        "warnings": ",".join(check.name for check in summary.warnings),
    }


def submitted_or_terminal_hashes(recorder: RunRecorder) -> set[str]:
    """Input: run recorder. Output: expression hashes set. Find planned items already sent or terminal."""
    hashes: set[str] = set()
    for record in recorder.read_jsonl("simulation_events.jsonl"):
        if record.get("event") in {"SUBMITTED", "CHECKED", "ERROR"} and record.get("expression_hash"):
            hashes.add(str(record["expression_hash"]))
    for record in recorder.read_jsonl("all_alphas.jsonl"):
        if record.get("expression_hash"):
            hashes.add(str(record["expression_hash"]))
    return hashes


def retry_planned_candidates(
    client,
    recorder: RunRecorder,
    config: dict[str, Any],
    submit_mode: str = "multi",
    defer_poll: bool = False,
) -> list[Any]:
    """Input: WQB client, run recorder, config, submit mode. Output: check summaries. Retry unsubmitted planned items."""
    planned = recorder.read_jsonl("planned_candidates.jsonl")
    skipped_hashes = submitted_or_terminal_hashes(recorder)
    settings = build_settings(config)
    payloads: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    for item in planned:
        expr_hash = str(item.get("expression_hash", ""))
        expression = str(item.get("expression", ""))
        if not expr_hash or not expression:
            continue
        if expr_hash in skipped_hashes:
            recorder.append_jsonl(
                "retry_planned_skips.jsonl",
                {"expression_hash": expr_hash, "expression": expression, "reason": "already_submitted_or_terminal"},
            )
            continue
        metadata.append(dict(item))
        payloads.append(simulation_payload(settings, expression))
    return submit_candidate_payloads(
        client,
        recorder,
        payloads,
        metadata,
        submit_mode,
        "retry_planned",
        defer_poll=defer_poll,
    )


def submit_candidate_payloads(
    client,
    recorder: RunRecorder,
    payloads: list[dict[str, Any]],
    metadata: list[dict[str, Any]],
    submit_mode: str,
    stage_prefix: str,
    defer_poll: bool = False,
    multi_chunk_sleep_seconds: float = DEFAULT_MULTI_CHUNK_SLEEP_SECONDS,
    sleep_func=time.sleep,
) -> list[Any]:
    """Input: client, payloads, metadata, mode, stage prefix. Output: summaries. Submit and check payloads."""
    summaries = []
    candidate_rows: list[dict[str, Any]] = []
    if submit_mode not in {"multi", "serial"}:
        raise ValueError("submit_mode must be 'multi' or 'serial'")
    if submit_mode == "multi":
        fallback_payloads: list[dict[str, Any]] = []
        fallback_metadata: list[dict[str, Any]] = []
        for start in range(0, len(payloads), FIELD_BATCH_MULTI_CHUNK_SIZE):
            chunk_payloads = payloads[start : start + FIELD_BATCH_MULTI_CHUNK_SIZE]
            chunk_metadata = metadata[start : start + FIELD_BATCH_MULTI_CHUNK_SIZE]
            if start > 0 and multi_chunk_sleep_seconds > 0:
                sleep_func(multi_chunk_sleep_seconds)
            try:
                progress_url = submit_multisimulation(client, chunk_payloads)
            except requests.exceptions.RequestException as err:
                record_recoverable_network_error(
                    recorder,
                    f"{stage_prefix}_multi_submit",
                    err,
                    {"payload_count": len(chunk_payloads), "chunk_start": start},
                )
                if is_http_status_error(err, 400):
                    fallback_payloads.extend(chunk_payloads)
                    fallback_metadata.extend(chunk_metadata)
                if is_http_status_error(err, 429):
                    break
                continue
            for item in chunk_metadata:
                recorder.append_jsonl("simulation_events.jsonl", {"event": "SUBMITTED", "progress_url": progress_url, **item})
            if defer_poll:
                continue
            try:
                progress = poll_simulation(client, progress_url)
            except requests.exceptions.RequestException as err:
                for item in chunk_metadata:
                    record_recoverable_network_error(
                        recorder,
                        f"{stage_prefix}_multi_poll",
                        err,
                        {"progress_url": progress_url, **item},
                    )
                continue
            if str(progress.get("status", "")).upper() == "ERROR":
                message = str(progress.get("message", "multisimulation returned ERROR"))
                for item in chunk_metadata:
                    recorder.append_jsonl(
                        "simulation_events.jsonl",
                        {"event": "ERROR", "message": message, "progress_url": progress_url, **item},
                    )
                continue
            alpha_ids = resolve_multisimulation_alpha_ids(client, progress)
            for item, alpha_id in zip(chunk_metadata, alpha_ids):
                try:
                    summary = fetch_check_summary(client, alpha_id)
                except requests.exceptions.RequestException as err:
                    record_recoverable_network_error(
                        recorder,
                        f"{stage_prefix}_multi_check",
                        err,
                        {"alpha_id": alpha_id, "progress_url": progress_url, **item},
                    )
                    continue
                summaries.append(summary)
                recorder.append_jsonl("simulation_events.jsonl", {"event": "CHECKED", "alpha_id": alpha_id, **item})
                record = {
                    "alpha_id": alpha_id,
                    "status": "CHECKED",
                    "hard_pass": summary.hard_pass,
                    "metrics": summary.metrics,
                    "failed": [check.name for check in summary.failed],
                    "pending": [check.name for check in summary.pending],
                    "warnings": [check.name for check in summary.warnings],
                    **item,
                }
                record.update(benchmark_fields_for_record(record))
                recorder.append_jsonl("all_alphas.jsonl", record)
                if summary.hard_pass:
                    candidate_rows.append(candidate_row_from_summary(alpha_id, item, summary))
        if not fallback_payloads:
            if candidate_rows:
                recorder.write_candidates(candidate_rows)
            return summaries
        payloads = fallback_payloads
        metadata = fallback_metadata
    for payload, item in zip(payloads, metadata):
        try:
            progress_url = submit_simulation(client, payload)
        except requests.exceptions.RequestException as err:
            record_recoverable_network_error(recorder, f"{stage_prefix}_submit", err, item)
            if is_http_status_error(err, 429):
                break
            continue
        recorder.append_jsonl("simulation_events.jsonl", {"event": "SUBMITTED", "progress_url": progress_url, **item})
        if defer_poll:
            continue
        try:
            progress = poll_simulation(client, progress_url)
        except requests.exceptions.RequestException as err:
            record_recoverable_network_error(recorder, f"{stage_prefix}_poll", err, {"progress_url": progress_url, **item})
            continue
        if str(progress.get("status", "")).upper() == "ERROR":
            message = str(progress.get("message", "simulation returned ERROR"))
            recorder.append_jsonl("simulation_events.jsonl", {"event": "ERROR", "message": message, "progress_url": progress_url, **item})
            continue
        alpha_id = extract_alpha_id(progress)
        try:
            summary = fetch_check_summary(client, alpha_id)
        except requests.exceptions.RequestException as err:
            record_recoverable_network_error(
                recorder,
                f"{stage_prefix}_check",
                err,
                {"alpha_id": alpha_id, "progress_url": progress_url, **item},
            )
            continue
        summaries.append(summary)
        recorder.append_jsonl("simulation_events.jsonl", {"event": "CHECKED", "alpha_id": alpha_id, **item})
        record = {
            "alpha_id": alpha_id,
            "status": "CHECKED",
            "hard_pass": summary.hard_pass,
            "metrics": summary.metrics,
            "failed": [check.name for check in summary.failed],
            "pending": [check.name for check in summary.pending],
            "warnings": [check.name for check in summary.warnings],
            **item,
        }
        record.update(benchmark_fields_for_record(record))
        recorder.append_jsonl("all_alphas.jsonl", record)
        if summary.hard_pass:
            candidate_rows.append(candidate_row_from_summary(alpha_id, item, summary))
    if candidate_rows:
        recorder.write_candidates(candidate_rows)
    return summaries


def complete_in_flight_simulations(client, recorder: RunRecorder) -> list[str]:
    """Input: WQB client and recorder. Output: completed alpha ids. Finish submitted simulations in a run."""
    events = recorder.read_jsonl("simulation_events.jsonl")
    terminal_hashes = {
        str(record.get("expression_hash"))
        for record in events
        if record.get("expression_hash") and record.get("event") in {"CHECKED", "ERROR"}
    }
    completed_alpha_ids: list[str] = []
    candidate_rows: list[dict[str, Any]] = []

    events_by_progress_url: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        expression_hash = event.get("expression_hash")
        progress_url = event.get("progress_url")
        if event.get("event") != "SUBMITTED" or not expression_hash or not progress_url:
            continue
        if str(expression_hash) in terminal_hashes:
            continue
        events_by_progress_url.setdefault(str(progress_url), []).append(event)

    for progress_url, pending_events in events_by_progress_url.items():
        try:
            progress = poll_simulation(client, progress_url)
        except requests.exceptions.RequestException as err:
            for event in pending_events:
                record_recoverable_network_error(
                    recorder,
                    "complete_in_flight",
                    err,
                    {
                        "parent_alpha_id": event.get("parent_alpha_id"),
                        "expression_hash": event.get("expression_hash"),
                        "progress_url": progress_url,
                        "operator_replacements": event.get("operator_replacements", {}),
                        "setting_overrides": event.get("setting_overrides", {}),
                        "setting_variant": event.get("setting_variant", {}),
                    },
                )
            continue
        if str(progress.get("status", "")).upper() == "ERROR":
            message = str(progress.get("message", "simulation returned ERROR"))
            for event in pending_events:
                expression_hash = event.get("expression_hash")
                recorder.append_jsonl(
                    "simulation_events.jsonl",
                    {
                        "event": "ERROR",
                        "parent_alpha_id": event.get("parent_alpha_id"),
                        "expression_hash": expression_hash,
                        "simulation_id": progress.get("id"),
                        "message": message,
                        "operator_replacements": event.get("operator_replacements", {}),
                        "setting_overrides": event.get("setting_overrides", {}),
                        "setting_variant": event.get("setting_variant", {}),
                    },
                )
                recorder.append_jsonl(
                    "run_errors.jsonl",
                    {
                        "stage": "complete_in_flight",
                        "status": "ERROR",
                        "status_code": "SIMULATION_ERROR",
                        "parent_alpha_id": event.get("parent_alpha_id"),
                        "expression_hash": expression_hash,
                        "message": message,
                        "operator_replacements": event.get("operator_replacements", {}),
                        "setting_overrides": event.get("setting_overrides", {}),
                        "setting_variant": event.get("setting_variant", {}),
                    },
                )
                terminal_hashes.add(str(expression_hash))
            continue

        if len(pending_events) == 1 and progress.get("alpha"):
            alpha_ids = [extract_alpha_id(progress)]
        else:
            alpha_ids = resolve_multisimulation_alpha_ids(client, progress)
        for event, alpha_id in zip(pending_events, alpha_ids):
            expression_hash = event.get("expression_hash")
            try:
                summary = fetch_check_summary(client, alpha_id)
            except requests.exceptions.RequestException as err:
                record_recoverable_network_error(
                    recorder,
                    "complete_in_flight_check",
                    err,
                    {
                        "parent_alpha_id": event.get("parent_alpha_id"),
                        "expression_hash": expression_hash,
                        "progress_url": progress_url,
                        "alpha_id": alpha_id,
                        "operator_replacements": event.get("operator_replacements", {}),
                        "setting_overrides": event.get("setting_overrides", {}),
                        "setting_variant": event.get("setting_variant", {}),
                    },
                )
                continue
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "CHECKED",
                    "parent_alpha_id": event.get("parent_alpha_id"),
                    "expression_hash": expression_hash,
                    "alpha_id": alpha_id,
                    "operator_replacements": event.get("operator_replacements", {}),
                    "setting_overrides": event.get("setting_overrides", {}),
                    "setting_variant": event.get("setting_variant", {}),
                },
            )
            recorder.append_jsonl(
                "all_alphas.jsonl",
                {
                    "alpha_id": alpha_id,
                    "parent_alpha_id": event.get("parent_alpha_id"),
                    "expression_hash": expression_hash,
                    "status": "CHECKED",
                    "hard_pass": summary.hard_pass,
                    "metrics": summary.metrics,
                    "failed": [item.name for item in summary.failed],
                    "pending": [item.name for item in summary.pending],
                    "warnings": [item.name for item in summary.warnings],
                    "expression": event.get("expression"),
                    "field_search": event.get("field_search"),
                    "dataset_id": event.get("dataset_id"),
                    "operator_replacements": event.get("operator_replacements", {}),
                    "setting_overrides": event.get("setting_overrides", {}),
                    "setting_variant": event.get("setting_variant", {}),
                },
            )
            completed_alpha_ids.append(alpha_id)
            terminal_hashes.add(str(expression_hash))
            if summary.hard_pass:
                candidate_rows.append(
                    {
                        "alpha_id": alpha_id,
                        "expression_hash": expression_hash,
                        "sharpe": summary.metrics.get("sharpe"),
                        "fitness": summary.metrics.get("fitness"),
                        "turnover": summary.metrics.get("turnover"),
                        "returns": summary.metrics.get("returns"),
                        "warnings": ",".join(item.name for item in summary.warnings),
                    }
                )

    if candidate_rows:
        recorder.write_candidates(candidate_rows)
    return completed_alpha_ids


def scan_existing(config: dict[str, Any], max_scan: int, run_dir: str | None = None) -> None:
    """Input: config, scan limit, run dir. Output: run artifacts. Scan existing IS Alphas for candidates."""
    run_dir = Path(run_dir) if run_dir else make_run_dir(config)
    recorder = RunRecorder(run_dir)
    client = build_client(config)
    if not authenticate_for_run(client, recorder, "scan_existing_auth"):
        print(
            json.dumps(
                {
                    "run_dir": str(run_dir),
                    "candidate_count": 0,
                    "candidates": [],
                    "status": "auth_recoverable_error",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    candidates = scan_existing_alpha_candidates(client, recorder, max_scan=max_scan)
    recorder.write_markdown(
        "run_summary.md",
        f"# Existing Alpha Scan\n\nScanned up to {max_scan} IS Alphas. Candidates found: {len(candidates)}.\n",
    )
    print(json.dumps({"run_dir": str(run_dir), "candidate_count": len(candidates), "candidates": candidates}, ensure_ascii=False, indent=2))


def complete_in_flight(config: dict[str, Any], run_dir: str | None = None) -> None:
    """Input: run config and optional run dir. Output: run artifacts. Complete pending simulation events."""
    selected_run_dir = Path(run_dir) if run_dir else latest_run_dir(config["run_root"])
    if selected_run_dir is None:
        print(json.dumps({"run_dir": None, "completed_alpha_ids": []}, ensure_ascii=False, indent=2))
        return
    recorder = RunRecorder(selected_run_dir)
    client = build_client(config)
    if not authenticate_for_run(client, recorder, "complete_in_flight_auth"):
        print(
            json.dumps(
                {
                    "run_dir": str(selected_run_dir),
                    "completed_alpha_ids": [],
                    "status": summarize_run_dir(selected_run_dir),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    completed_alpha_ids = complete_in_flight_simulations(client, recorder)
    print(
        json.dumps(
            {
                "run_dir": str(selected_run_dir),
                "completed_alpha_ids": completed_alpha_ids,
                "status": summarize_run_dir(selected_run_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def retry_planned(
    config: dict[str, Any],
    run_dir: str,
    submit_mode: str = "multi",
    defer_poll: bool = False,
) -> None:
    """Input: run config, run dir, submit mode. Output: run artifacts. Retry unsubmitted planned candidates."""
    selected_run_dir = Path(run_dir)
    recorder = RunRecorder(selected_run_dir)
    try:
        require_readiness_gate(**_live_gate_kwargs(config, selected_run_dir))
    except ReadinessGateError as err:
        _print_readiness_blocked(selected_run_dir, err, {"submit_mode": submit_mode, "defer_poll": defer_poll})
        return
    client = build_client(config)
    if not authenticate_for_run(client, recorder, "retry_planned_auth"):
        print(json.dumps({"run_dir": str(selected_run_dir), "status": "auth_recoverable_error"}, ensure_ascii=False, indent=2))
        return
    summaries = retry_planned_candidates(client, recorder, config, submit_mode=submit_mode, defer_poll=defer_poll)
    run_status = summarize_run_dir(selected_run_dir)
    status_label = field_batch_status_label(run_status, summaries)
    print(
        json.dumps(
            {
                "run_dir": str(selected_run_dir),
                "status": status_label,
                "submit_mode": submit_mode,
                "defer_poll": defer_poll,
                "checked_count": len(summaries),
                "hard_pass_alpha_ids": [summary.alpha_id for summary in summaries if summary.hard_pass],
                "failed": {summary.alpha_id: [check.name for check in summary.failed] for summary in summaries},
                "pending": {summary.alpha_id: [check.name for check in summary.pending] for summary in summaries},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def run_expression_file(
    config: dict[str, Any],
    expression_file: str,
    run_dir: str | None = None,
    submit_mode: str = "serial",
    defer_poll: bool = False,
    multi_chunk_sleep_seconds: float = DEFAULT_MULTI_CHUNK_SLEEP_SECONDS,
    novelty_reference_files: list[str] | None = None,
    min_novelty_score: int | None = None,
) -> None:
    """Input: config, JSONL file, run dir. Output: terminal JSON and run artifacts. Submit custom expression batch."""
    selected_run_dir = Path(run_dir) if run_dir else make_run_dir(config)
    recorder = RunRecorder(selected_run_dir)
    try:
        require_readiness_gate(**_live_gate_kwargs(config, selected_run_dir))
    except ReadinessGateError as err:
        _print_readiness_blocked(selected_run_dir, err, {"expression_file": expression_file, "submit_mode": submit_mode})
        return
    client = build_client(config)
    if not authenticate_for_run(client, recorder, "run_expression_file_auth"):
        print(json.dumps({"run_dir": str(selected_run_dir), "status": "auth_recoverable_error"}, ensure_ascii=False, indent=2))
        return
    novelty_reference_records = load_novelty_reference_records(novelty_reference_files)
    summaries = run_expression_file_batch(
        client,
        recorder,
        expression_file,
        submit_mode=submit_mode,
        defer_poll=defer_poll,
        seen_hashes=run_root_expression_hashes(config.get("run_root", "runs")),
        multi_chunk_sleep_seconds=multi_chunk_sleep_seconds,
        novelty_reference_records=novelty_reference_records,
        min_novelty_score=min_novelty_score,
    )
    run_status = summarize_run_dir(selected_run_dir)
    print(
        json.dumps(
            {
                "run_dir": str(selected_run_dir),
                "expression_file": expression_file,
                "submit_mode": submit_mode,
                "defer_poll": defer_poll,
                "multi_chunk_sleep_seconds": multi_chunk_sleep_seconds,
                "min_novelty_score": min_novelty_score,
                "novelty_reference_file_count": len(novelty_reference_files or []),
                "checked_count": len(summaries),
                "hard_pass_alpha_ids": [summary.alpha_id for summary in summaries if summary.hard_pass],
                "failed": {summary.alpha_id: [check.name for check in summary.failed] for summary in summaries},
                "pending": {summary.alpha_id: [check.name for check in summary.pending] for summary in summaries},
                "status": run_status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def refresh_alpha(
    config: dict[str, Any],
    alpha_id: str,
    operator_replacements: dict[str, str] | None = None,
    setting_overrides: dict[str, Any] | None = None,
) -> None:
    """Input: run config and alpha id. Output: run artifacts. Refresh one existing Alpha by re-simulation."""
    run_dir = make_run_dir(config)
    recorder = RunRecorder(run_dir)
    try:
        require_readiness_gate(**_live_gate_kwargs(config, run_dir))
    except ReadinessGateError as err:
        _print_readiness_blocked(run_dir, err, {"alpha_id": alpha_id})
        return
    client = build_client(config)
    client.authenticate()
    try:
        summary = refresh_existing_alpha(
            client,
            recorder,
            alpha_id,
            operator_replacements=operator_replacements,
            setting_overrides=setting_overrides,
        )
    except requests.exceptions.HTTPError as err:
        if is_http_status_error(err, 429):
            recorder.append_jsonl(
                "run_errors.jsonl",
                {
                    "stage": "refresh_alpha",
                    "status_code": 429,
                    "parent_alpha_id": alpha_id,
                    "operator_replacements": operator_replacements or {},
                    "setting_overrides": setting_overrides or {},
                },
            )
            recorder.write_markdown(
                "run_summary.md",
                "# Refresh Alpha Summary\n\nStopped early: platform returned HTTP 429 while refreshing Alpha.\n",
            )
            print(json.dumps({"run_dir": str(run_dir), "alpha_id": alpha_id, "status": "rate_limited"}, ensure_ascii=False, indent=2))
            return
        raise

    if summary is None:
        run_status = summarize_run_dir(run_dir)
        status_label = "pending_recovery" if run_status["in_flight_count"] else "simulation_error"
        recorder.write_markdown(
            "run_summary.md",
            f"# Refresh Alpha Summary\n\nParent Alpha: `{alpha_id}`\n\nStatus: `{status_label}`\n",
        )
        print(json.dumps({"run_dir": str(run_dir), "alpha_id": alpha_id, "status": status_label}, ensure_ascii=False, indent=2))
        return

    recorder.write_markdown(
        "run_summary.md",
        f"# Refresh Alpha Summary\n\nParent Alpha: `{alpha_id}`\n\nRefreshed Alpha: `{summary.alpha_id}`\n\nHard pass: `{summary.hard_pass}`\n",
    )
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "parent_alpha_id": alpha_id,
                "alpha_id": summary.alpha_id,
                "hard_pass": summary.hard_pass,
                "operator_replacements": operator_replacements or {},
                "setting_overrides": setting_overrides or {},
                "failed": [item.name for item in summary.failed],
                "pending": [item.name for item in summary.pending],
                "warnings": [item.name for item in summary.warnings],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def refresh_alpha_batch(
    config: dict[str, Any],
    alpha_id: str,
    setting_variants: list[dict[str, Any]],
    operator_replacements: dict[str, str] | None = None,
    base_setting_overrides: dict[str, Any] | None = None,
    submit_mode: str = "multi",
) -> None:
    """Input: run config, alpha id, variants. Output: run artifacts. Batch refresh setting variants."""
    run_dir = make_run_dir(config)
    recorder = RunRecorder(run_dir)
    try:
        require_readiness_gate(**_live_gate_kwargs(config, run_dir))
    except ReadinessGateError as err:
        _print_readiness_blocked(run_dir, err, {"alpha_id": alpha_id, "submit_mode": submit_mode})
        return
    client = build_client(config)
    client.authenticate()
    try:
        summaries = refresh_existing_alpha_batch(
            client,
            recorder,
            alpha_id,
            setting_variants=setting_variants,
            operator_replacements=operator_replacements,
            base_setting_overrides=base_setting_overrides,
            submit_mode=submit_mode,
        )
    except requests.exceptions.HTTPError as err:
        if is_http_status_error(err, 429):
            recorder.append_jsonl(
                "run_errors.jsonl",
                {
                    "stage": "refresh_alpha_batch",
                    "status_code": 429,
                    "parent_alpha_id": alpha_id,
                    "operator_replacements": operator_replacements or {},
                    "base_setting_overrides": base_setting_overrides or {},
                    "setting_variants": setting_variants,
                },
            )
            print(json.dumps({"run_dir": str(run_dir), "alpha_id": alpha_id, "status": "rate_limited"}, ensure_ascii=False, indent=2))
            return
        raise

    run_status = summarize_run_dir(run_dir)
    status_label = "pending_recovery" if run_status["in_flight_count"] and not summaries else "completed"
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "parent_alpha_id": alpha_id,
                "status": status_label,
                "checked_count": len(summaries),
                "hard_pass_alpha_ids": [summary.alpha_id for summary in summaries if summary.hard_pass],
                "failed": {summary.alpha_id: [check.name for check in summary.failed] for summary in summaries},
                "pending": {summary.alpha_id: [check.name for check in summary.pending] for summary in summaries},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def repair_alpha_with_field(
    config: dict[str, Any],
    alpha_id: str,
    field_expression: str,
    blend_weights: list[float],
) -> None:
    """Input: run config, alpha id, field expression, weights. Output: run artifacts. Repair near-miss Alpha."""
    run_dir = make_run_dir(config)
    recorder = RunRecorder(run_dir)
    try:
        require_readiness_gate(**_live_gate_kwargs(config, run_dir))
    except ReadinessGateError as err:
        _print_readiness_blocked(run_dir, err, {"alpha_id": alpha_id, "field_expression": field_expression})
        return
    client = build_client(config)
    if not authenticate_for_run(client, recorder, "repair_alpha_auth"):
        print(json.dumps({"run_dir": str(run_dir), "alpha_id": alpha_id, "status": "auth_recoverable_error"}, ensure_ascii=False, indent=2))
        return
    summaries = repair_existing_alpha_with_field(
        client,
        recorder,
        alpha_id,
        field_expression,
        blend_weights,
    )
    run_status = summarize_run_dir(run_dir)
    status_label = field_batch_status_label(run_status, summaries)
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "parent_alpha_id": alpha_id,
                "status": status_label,
                "field_expression": field_expression,
                "blend_weights": blend_weights,
                "checked_count": len(summaries),
                "hard_pass_alpha_ids": [summary.alpha_id for summary in summaries if summary.hard_pass],
                "failed": {summary.alpha_id: [check.name for check in summary.failed] for summary in summaries},
                "pending": {summary.alpha_id: [check.name for check in summary.pending] for summary in summaries},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def field_batch(
    config: dict[str, Any],
    field_search: str = "",
    dataset_id: str = "",
    field_suffix: str = "",
    template_mode: str = "basic",
    workflow_stage: str = "scout",
    human_idea: str = "",
    exact_field_id: str = "",
    submit_mode: str = "multi",
    field_cache_path: str = "",
    defer_poll: bool = False,
    multi_chunk_sleep_seconds: float = DEFAULT_MULTI_CHUNK_SLEEP_SECONDS,
) -> None:
    """Input: run config and field filters. Output: run artifacts. Run seed batch from selected fields."""
    run_dir = make_run_dir(config)
    recorder = RunRecorder(run_dir)
    try:
        require_readiness_gate(**_live_gate_kwargs(config, run_dir))
    except ReadinessGateError as err:
        _print_readiness_blocked(
            run_dir,
            err,
            {
                "field_search": field_search,
                "dataset_id": dataset_id,
                "field_suffix": field_suffix,
                "template_mode": template_mode,
                "workflow_stage": workflow_stage,
            },
        )
        return
    client = build_client(config)
    if not authenticate_for_run(client, recorder, "field_batch_auth"):
        print(
            json.dumps(
                {
                    "run_dir": str(run_dir),
                    "status": "auth_recoverable_error",
                    "field_search": field_search,
                    "dataset_id": dataset_id,
                    "field_suffix": field_suffix,
                    "template_mode": template_mode,
                    "workflow_stage": workflow_stage,
                    "exact_field_id": exact_field_id,
                    "field_cache_path": field_cache_path,
                    "defer_poll": defer_poll,
                    "multi_chunk_sleep_seconds": multi_chunk_sleep_seconds,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    summaries = run_field_batch(
        client,
        recorder,
        config,
        field_search=field_search,
        dataset_id=dataset_id,
        field_suffix=field_suffix,
        template_mode=template_mode,
        workflow_stage=workflow_stage,
        human_idea=human_idea,
        exact_field_id=exact_field_id,
        submit_mode=submit_mode,
        field_cache_path=field_cache_path,
        defer_poll=defer_poll,
        multi_chunk_sleep_seconds=multi_chunk_sleep_seconds,
    )
    run_status = summarize_run_dir(run_dir)
    status_label = field_batch_status_label(run_status, summaries)
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "status": status_label,
                "field_search": field_search,
                "dataset_id": dataset_id,
                "field_suffix": field_suffix,
                "template_mode": template_mode,
                "workflow_stage": workflow_stage,
                "human_idea": human_idea,
                "exact_field_id": exact_field_id,
                "field_cache_path": field_cache_path,
                "defer_poll": defer_poll,
                "multi_chunk_sleep_seconds": multi_chunk_sleep_seconds,
                "checked_count": len(summaries),
                "hard_pass_alpha_ids": [summary.alpha_id for summary in summaries if summary.hard_pass],
                "failed": {summary.alpha_id: [check.name for check in summary.failed] for summary in summaries},
                "pending": {summary.alpha_id: [check.name for check in summary.pending] for summary in summaries},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def smoke(config: dict[str, Any]) -> None:
    """Input: run config. Output: run artifacts. Execute a tiny live simulation/check cycle."""
    run_dir = make_run_dir(config)
    recorder = RunRecorder(run_dir)
    try:
        require_readiness_gate(**_live_gate_kwargs(config, run_dir))
    except ReadinessGateError as err:
        _print_readiness_blocked(run_dir, err, {"command": "smoke"})
        return
    client = build_client(config)
    client.authenticate()
    snapshot = fetch_knowledge_snapshot(client, list(config.get("knowledge_queries", []))[:3])
    recorder.write_markdown("run_summary.md", "# Smoke Test\n\nKnowledge snapshot fetched.\n")
    (run_dir / "knowledge_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = fetch_data_fields(
        client,
        config["instrument_type"],
        config["region"],
        int(config["delay"]),
        config["universe"],
        max_records=20,
    )
    seed_fields = select_seed_fields(fields, max_fields=5)
    settings = build_settings(config)
    max_count = min(int(config["max_alphas_per_round"]), 3)
    candidates = generate_seed_candidates(seed_fields, settings, max_count, generation=0)
    for candidate in candidates:
        expr_hash = expression_hash(candidate.expression)
        payload = simulation_payload(candidate.settings, candidate.expression)
        progress_url = submit_simulation(client, payload)
        progress = poll_simulation(client, progress_url)
        alpha_id = extract_alpha_id(progress)
        summary = fetch_check_summary(client, alpha_id)
        recorder.append_jsonl(
            "all_alphas.jsonl",
            {
                "alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "status": "CHECKED",
                "hard_pass": summary.hard_pass,
                "failed": [item.name for item in summary.failed],
                "pending": [item.name for item in summary.pending],
                "warnings": [item.name for item in summary.warnings],
            },
        )
        print(f"checked alpha_id={alpha_id} hard_pass={summary.hard_pass}")
        break


def run_stage1(config: dict[str, Any]) -> None:
    """Input: run config. Output: run artifacts. Run Stage 1 search and optimization workflow."""
    run_dir = make_run_dir(config)
    recorder = RunRecorder(run_dir)
    try:
        require_readiness_gate(**_live_gate_kwargs(config, run_dir))
    except ReadinessGateError as err:
        _print_readiness_blocked(run_dir, err, {"command": "run-stage1"})
        return
    client = build_client(config)
    client.authenticate()
    snapshot = fetch_knowledge_snapshot(client, list(config.get("knowledge_queries", [])))
    (run_dir / "knowledge_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = fetch_data_fields(
        client,
        config["instrument_type"],
        config["region"],
        int(config["delay"]),
        config["universe"],
        max_records=300,
    )
    seed_fields = select_seed_fields(fields, max_fields=40)
    base_settings = build_settings(config)
    candidates_rows: list[dict[str, Any]] = []
    seen = recorder.seen_expression_hashes()
    previous_action_types: list[str] = []

    for generation in range(int(config["max_rounds"])):
        settings = settings_for_generation(base_settings, generation, previous_action_types)
        candidates = generate_seed_candidates(
            seed_fields,
            settings,
            int(config["max_alphas_per_round"]),
            generation=generation,
        )
        round_action_types: list[str] = []
        for candidate in candidates:
            expr_hash = expression_hash(candidate.expression)
            if expr_hash in seen:
                continue
            seen.add(expr_hash)
            payload = simulation_payload(candidate.settings, candidate.expression)
            try:
                progress_url = submit_simulation(client, payload)
                recorder.append_jsonl(
                    "simulation_events.jsonl",
                    {
                        "event": "SUBMITTED",
                        "generation": generation,
                        "expression_hash": expr_hash,
                        "expression": candidate.expression,
                        "progress_url": progress_url,
                    },
                )
            except requests.exceptions.HTTPError as err:
                if is_http_status_error(err, 429):
                    recorder.append_jsonl(
                        "run_errors.jsonl",
                        {
                            "stage": "submit_simulation",
                            "status_code": 429,
                            "generation": generation,
                            "expression_hash": expr_hash,
                            "expression": candidate.expression,
                        },
                    )
                    recorder.write_candidates(candidates_rows)
                    recorder.write_markdown(
                        "run_summary.md",
                        "# Stage 1 Summary\n\nStopped early: platform returned HTTP 429 while submitting simulation.\n",
                    )
                    print(f"stage1 stopped rate_limited run_dir={run_dir}")
                    return
                raise
            progress = poll_simulation(client, progress_url)
            alpha_id = extract_alpha_id(progress)
            summary = fetch_check_summary(client, alpha_id)
            recorder.append_jsonl(
                "simulation_events.jsonl",
                {
                    "event": "CHECKED",
                    "generation": generation,
                    "expression_hash": expr_hash,
                    "alpha_id": alpha_id,
                },
            )
            record = {
                "alpha_id": alpha_id,
                "expression_hash": expr_hash,
                "generation": generation,
                "status": "CHECKED",
                "hard_pass": summary.hard_pass,
                "metrics": summary.metrics,
                "failed": [item.name for item in summary.failed],
                "pending": [item.name for item in summary.pending],
                "warnings": [item.name for item in summary.warnings],
                "expression": candidate.expression,
            }
            recorder.append_jsonl("all_alphas.jsonl", record)
            if summary.hard_pass:
                row = {
                    "alpha_id": alpha_id,
                    "expression_hash": expr_hash,
                    "sharpe": summary.metrics.get("sharpe"),
                    "fitness": summary.metrics.get("fitness"),
                    "turnover": summary.metrics.get("turnover"),
                    "returns": summary.metrics.get("returns"),
                    "warnings": ",".join(item.name for item in summary.warnings),
                }
                candidates_rows.append(row)
                recorder.write_candidates(candidates_rows)
                if config["stop_after_first_candidate"]:
                    recorder.write_markdown("run_summary.md", f"# Stage 1 Summary\n\nCandidate found: `{alpha_id}`\n")
                    print(f"candidate found alpha_id={alpha_id}")
                    return
            for action in actions_for_check_summary(expr_hash, summary):
                round_action_types.append(action.action_type)
                recorder.append_jsonl(
                    "optimization_trace.jsonl",
                    {
                        "parent_hash": action.parent_hash,
                        "reason": action.reason,
                        "action_type": action.action_type,
                        "details": action.details,
                    },
                )
        if round_action_types:
            previous_action_types = round_action_types

    recorder.write_candidates(candidates_rows)
    recorder.write_markdown("run_summary.md", "# Stage 1 Summary\n\nNo hard-check-passing candidate found within budget.\n")
    print(f"stage1 complete run_dir={run_dir}")


def parse_args() -> argparse.Namespace:
    """Input: command line. Output: parsed args. Define Stage 1 CLI commands."""
    parser = argparse.ArgumentParser(description="WorldQuant Brain Stage 1 workflow")
    parser.add_argument(
        "command",
        choices=[
            "dry-run",
            "smoke",
            "run-stage1",
            "status",
            "scan-existing",
            "inspect-alpha",
            "refresh-alpha",
            "refresh-alpha-batch",
            "repair-alpha-with-field",
            "run-field-batch",
            "list-fields",
            "cache-metadata",
            "semantic-preview",
            "plan-stage",
            "complete-in-flight",
            "retry-planned",
            "run-expression-file",
            "plan-research-options",
            "knowledge-health-check",
            "readiness-check",
            "launch-workflow",
            "bootstrap-knowledge",
            "schedule-research",
            "workflow-start",
            "workflow-continue",
            "workflow-status",
            "workflow-resume",
            "workflow-abort",
            "workflow-approve-candidates",
            "workflow-update-candidate-status",
        ],
    )
    parser.add_argument("--config", default="configs/stage1_usa_d1.yaml")
    parser.add_argument("--max-alphas-per-round", type=int, default=None)
    parser.add_argument("--max-rounds", type=int, default=None)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--max-scan", type=int, default=25)
    parser.add_argument("--alpha-id", default=None)
    parser.add_argument("--signal-note", default="")
    parser.add_argument("--replace-operator", action="append", default=[])
    parser.add_argument("--set-setting", action="append", default=[])
    parser.add_argument("--vary-setting", action="append", default=[])
    parser.add_argument("--submit-mode", choices=["multi", "serial"], default="multi")
    parser.add_argument("--multi-chunk-sleep-seconds", type=float, default=DEFAULT_MULTI_CHUNK_SLEEP_SECONDS)
    parser.add_argument("--field-search", default="")
    parser.add_argument("--dataset-id", default="")
    parser.add_argument("--field-suffix", default="")
    parser.add_argument("--template-mode", choices=["basic", "economic", "relational", "semantic"], default="basic")
    parser.add_argument("--workflow-stage", choices=["scout", "seed", "discovery", "repair", "submit"], default="scout")
    parser.add_argument("--human-idea", default="")
    parser.add_argument("--exact-field-id", default="")
    parser.add_argument("--field-cache-path", default="")
    parser.add_argument("--cache-dir", default="docs/knowledge/cache")
    parser.add_argument("--cache-path", default="")
    parser.add_argument("--skip-data-sets", action="store_true", default=False)
    parser.add_argument("--defer-poll", action="store_true", default=False)
    parser.add_argument("--field-expression", default="")
    parser.add_argument("--expression-file", default="")
    parser.add_argument("--novelty-reference-file", action="append", default=[])
    parser.add_argument("--min-novelty-score", type=int, default=None)
    parser.add_argument("--blend-weights", default="0.25,0.5")
    parser.add_argument("--max-fields", type=int, default=50)
    parser.add_argument("--request-timeout-seconds", type=int, default=None)
    parser.add_argument("--request-max-retries", type=int, default=None)
    parser.add_argument("--request-base-backoff-seconds", type=int, default=None)
    parser.add_argument("--max-options", type=int, default=5)
    parser.add_argument("--option-output-dir", default=default_option_output_dir())
    parser.add_argument("--freshness-manifest", default="wiki/80_maintenance/freshness_manifest.json")
    parser.add_argument("--freshness-report", default="wiki/80_maintenance/freshness_report.md")
    parser.add_argument("--knowledge-root", default=str(default_knowledge_root()))
    parser.add_argument("--knowledge-seed-root", default="docs/knowledge")
    parser.add_argument("--readiness-output-dir", default="")
    parser.add_argument("--readiness-mode", choices=["maintenance", "plan-only", "research", "submit-candidate"], default="plan-only")
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--enable-live-api", action="store_true", default=False)
    parser.add_argument("--confirm-submit", action="store_true", default=False)
    parser.add_argument("--today", default="")
    parser.add_argument("--workflow-defaults", default="configs/workflow_defaults.example.json")
    parser.add_argument("--workflow-local", default="")
    parser.add_argument("--workflow-objective", default="")
    parser.add_argument("--workflow-mode", choices=["maintenance", "plan-only", "research", "submit-candidate"], default="")
    parser.add_argument("--workflow-region", default="")
    parser.add_argument("--workflow-universe", default="")
    parser.add_argument("--workflow-delay", type=int, default=None)
    parser.add_argument("--skip-handoffs", action="store_true", default=False)
    parser.add_argument("--option-json", default="")
    parser.add_argument("--option-index", type=int, default=None)
    parser.add_argument("--schedule-output", default="wiki/70_decisions/research_schedule.md")
    parser.add_argument("--schedule-region", default="USA")
    parser.add_argument("--schedule-delay", type=int, default=1)
    parser.add_argument("--schedule-universe", default="TOP3000")
    parser.add_argument("--objective", default="")
    parser.add_argument("--selected-option-id", default="")
    parser.add_argument("--now", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--approved-by", default="user")
    parser.add_argument("--candidate-version", type=int, default=None)
    parser.add_argument("--candidate-expression-hash", default="")
    parser.add_argument("--candidate-status", choices=sorted(QUEUE_STATUSES), default="")
    parser.add_argument("--source-run-id", default="")
    return parser.parse_args()


def config_overrides_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Input: parsed CLI args. Output: config overrides dict. Collect optional run hyperparameters."""
    return {
        "max_alphas_per_round": args.max_alphas_per_round,
        "max_rounds": args.max_rounds,
        "request_timeout_seconds": args.request_timeout_seconds,
        "max_retries": args.request_max_retries,
        "base_backoff_seconds": args.request_base_backoff_seconds,
    }


def cli_flag_present(argv: list[str], flag: str) -> bool:
    """Input: argv tokens and a flag. Output: bool. Detect whether a CLI flag was explicitly provided."""
    return any(item == flag or item.startswith(f"{flag}=") for item in argv)


def launch_overrides_from_args(args: argparse.Namespace, argv: list[str]) -> dict[str, Any]:
    """Input: parsed args and argv. Output: workflow overrides. Preserve config layering for omitted CLI flags."""
    overrides: dict[str, Any] = {
        "objective": args.workflow_objective or None,
        "mode": args.workflow_mode or None,
        "region": args.workflow_region or None,
        "universe": args.workflow_universe or None,
        "delay": args.workflow_delay,
    }
    if cli_flag_present(argv, "--knowledge-root"):
        overrides["knowledge_root"] = args.knowledge_root
    if cli_flag_present(argv, "--batch-size"):
        overrides["batch_size"] = args.batch_size
    if cli_flag_present(argv, "--enable-live-api"):
        overrides["live_api_enabled"] = args.enable_live_api
    return overrides


def main() -> None:
    """Input: CLI args. Output: command side effects. Dispatch Stage 1 commands."""
    args = parse_args()
    overrides = config_overrides_from_args(args)
    if args.command == "launch-workflow":
        launch_overrides = launch_overrides_from_args(args, sys.argv[1:])
        result = launch_workflow(
            args.workflow_defaults,
            args.workflow_local or None,
            overrides=launch_overrides,
            write_handoffs=not args.skip_handoffs,
            submit_confirmed=args.confirm_submit,
            today_value=args.today or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command.startswith("workflow-"):
        orchestrator = WorkflowOrchestrator(
            default_orchestrator_paths({"knowledge_root": args.knowledge_root})
        )
        now = args.now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if args.command == "workflow-start":
            if not args.objective or not args.selected_option_id:
                raise SystemExit("--objective and --selected-option-id are required for workflow-start")
            result = orchestrator.start(args.objective, args.selected_option_id, now)
        elif args.command == "workflow-continue":
            result = orchestrator.continue_once(now)
        elif args.command == "workflow-status":
            result = orchestrator.status()
        elif args.command == "workflow-resume":
            result = orchestrator.resume(now)
        elif args.command == "workflow-abort":
            if not args.reason:
                raise SystemExit("--reason is required for workflow-abort")
            result = orchestrator.abort(args.reason, now)
        elif args.command == "workflow-approve-candidates":
            result = orchestrator.approve_candidates(args.candidate_id, now, args.approved_by)
        else:
            if (
                len(args.candidate_id) != 1
                or args.candidate_version is None
                or not args.candidate_expression_hash
                or not args.candidate_status
            ):
                raise SystemExit(
                    "--candidate-id, --candidate-version, --candidate-expression-hash, and --candidate-status "
                    "are required for workflow-update-candidate-status"
                )
            status_args = (
                args.candidate_id[0],
                args.candidate_version,
                args.candidate_expression_hash,
                args.candidate_status,
                now,
            )
            if args.source_run_id:
                result = orchestrator.update_candidate_status(
                    *status_args, source_run_id=args.source_run_id
                )
            else:
                result = orchestrator.update_candidate_status(*status_args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    config = load_config(args.config, overrides=overrides)
    if args.command == "dry-run":
        dry_run(config)
    elif args.command == "smoke":
        smoke(config)
    elif args.command == "run-stage1":
        run_stage1(config)
    elif args.command == "status":
        status(config, args.run_dir)
    elif args.command == "scan-existing":
        scan_existing(config, args.max_scan, run_dir=args.run_dir)
    elif args.command == "inspect-alpha":
        if not args.alpha_id:
            raise SystemExit("--alpha-id is required for inspect-alpha")
        inspect_alpha(config, args.alpha_id, run_dir=args.run_dir, signal_note=args.signal_note)
    elif args.command == "complete-in-flight":
        complete_in_flight(config, args.run_dir)
    elif args.command == "retry-planned":
        if not args.run_dir:
            raise SystemExit("--run-dir is required for retry-planned")
        retry_planned(config, args.run_dir, submit_mode=args.submit_mode, defer_poll=args.defer_poll)
    elif args.command == "run-expression-file":
        if not args.expression_file:
            raise SystemExit("--expression-file is required for run-expression-file")
        run_expression_file(
            config,
            args.expression_file,
            run_dir=args.run_dir,
            submit_mode=args.submit_mode,
            defer_poll=args.defer_poll,
            multi_chunk_sleep_seconds=args.multi_chunk_sleep_seconds,
            novelty_reference_files=args.novelty_reference_file,
            min_novelty_score=args.min_novelty_score,
        )
    elif args.command == "refresh-alpha":
        if not args.alpha_id:
            raise SystemExit("--alpha-id is required for refresh-alpha")
        try:
            replacements = parse_operator_replacements(args.replace_operator)
            setting_overrides = parse_setting_overrides(args.set_setting)
        except ValueError as err:
            raise SystemExit(str(err)) from err
        refresh_alpha(config, args.alpha_id, operator_replacements=replacements, setting_overrides=setting_overrides)
    elif args.command == "refresh-alpha-batch":
        if not args.alpha_id:
            raise SystemExit("--alpha-id is required for refresh-alpha-batch")
        try:
            replacements = parse_operator_replacements(args.replace_operator)
            setting_overrides = parse_setting_overrides(args.set_setting)
            setting_variants = parse_setting_variations(args.vary_setting)
        except ValueError as err:
            raise SystemExit(str(err)) from err
        refresh_alpha_batch(
            config,
            args.alpha_id,
            setting_variants=setting_variants,
            operator_replacements=replacements,
            base_setting_overrides=setting_overrides,
            submit_mode=args.submit_mode,
        )
    elif args.command == "repair-alpha-with-field":
        if not args.alpha_id:
            raise SystemExit("--alpha-id is required for repair-alpha-with-field")
        if not args.field_expression:
            raise SystemExit("--field-expression is required for repair-alpha-with-field")
        try:
            blend_weights = parse_blend_weights(args.blend_weights)
        except ValueError as err:
            raise SystemExit(str(err)) from err
        repair_alpha_with_field(
            config,
            args.alpha_id,
            args.field_expression,
            blend_weights,
        )
    elif args.command == "run-field-batch":
        field_batch(
            config,
            field_search=args.field_search,
            dataset_id=args.dataset_id,
            field_suffix=args.field_suffix,
            template_mode=args.template_mode,
            workflow_stage=args.workflow_stage,
            human_idea=args.human_idea,
            exact_field_id=args.exact_field_id,
            submit_mode=args.submit_mode,
            field_cache_path=args.field_cache_path,
            defer_poll=args.defer_poll,
            multi_chunk_sleep_seconds=args.multi_chunk_sleep_seconds,
        )
    elif args.command == "list-fields":
        list_fields(
            config,
            dataset_id=args.dataset_id,
            field_search=args.field_search,
            field_suffix=args.field_suffix,
            max_fields=args.max_fields,
        )
    elif args.command == "cache-metadata":
        cache_metadata(
            config,
            dataset_id_arg=args.dataset_id,
            field_search_arg=args.field_search,
            field_suffix=args.field_suffix,
            max_fields=args.max_fields,
            cache_dir=args.cache_dir,
            include_data_sets=not args.skip_data_sets,
        )
    elif args.command == "semantic-preview":
        if not args.cache_path:
            raise SystemExit("--cache-path is required for semantic-preview")
        semantic_preview(
            config,
            cache_path=args.cache_path,
            dataset_id=args.dataset_id,
            field_search=args.field_search,
            field_suffix=args.field_suffix,
            template_mode=args.template_mode,
            max_count=args.max_alphas_per_round or int(config["max_alphas_per_round"]),
        )
    elif args.command == "plan-stage":
        plan_stage(args.workflow_stage, args.dataset_id)
    elif args.command == "plan-research-options":
        result = plan_research_options(config, args.max_options, args.option_output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "knowledge-health-check":
        result = knowledge_health_check(
            default_knowledge_root(),
            args.freshness_manifest,
            args.freshness_report,
            today_value=args.today or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "readiness-check":
        output_dir = args.readiness_output_dir or str(Path(config["run_root"]) / "readiness")
        result = readiness_check(
            args.knowledge_root,
            output_dir,
            args.readiness_mode,
            args.batch_size,
            args.enable_live_api,
            args.confirm_submit,
            today_value=args.today or None,
            region=str(config.get("region", "")) or None,
            universe=str(config.get("universe", "")) or None,
            delay=int(config["delay"]) if "delay" in config else None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "bootstrap-knowledge":
        result = bootstrap_knowledge_command(args.knowledge_root, args.knowledge_seed_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "schedule-research":
        if not args.option_json:
            raise SystemExit("--option-json is required for schedule-research")
        result = schedule_research_from_option(
            args.option_json,
            args.knowledge_root,
            args.schedule_output,
            args.schedule_region,
            args.schedule_delay,
            option_index=args.option_index,
            universe=args.schedule_universe,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
