from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from wqb.benchmark_rules import (
    BenchmarkRule,
    default_benchmark_rules,
    load_benchmark_rules,
    write_benchmark_rules_jsonl,
    write_benchmark_rules_markdown,
)
from wqb.data_ledger_compile import compile_data_ledger_from_raw, latest_capture_dir
from wqb.knowledge_bootstrap import ACTIVITY_SNAPSHOT
from wqb.knowledge_compile import compile_research_records
from wqb.knowledge_contracts import (
    SourceIndexRow,
    canonical_source_family,
    parse_markdown_front_matter,
    render_front_matter,
    update_source_index,
)
from wqb.knowledge_paths import (
    LEGACY_MACHINE_RESOURCE_PATHS,
    ensure_knowledge_dirs,
    machine_resource_path,
    relative_to_knowledge_root,
)
from wqb.operator_semantics import compile_operator_semantics
from wqb.template_library import (
    load_template_library,
    template_record_to_dict,
    write_template_library_markdown,
)


MIGRATION_REPORT_DIR = Path("raw") / "maintenance" / "migration_reports"
DEFAULT_FRESHNESS_DAYS = 30
RAW_ROOT_MARKDOWN_RE = re.compile(r"^raw_root_(?P<stem>.+)$")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SENSITIVE_NAME_FRAGMENTS = (
    ".env",
    "credential",
    "secret",
    "token",
    "password",
    "key",
    "private",
)
CANONICAL_WIKI_MARKDOWN_FILES = {
    "00_start_here.md",
    "10_factor_principles.md",
    "20_data_semantics.md",
    "30_template_and_operator_patterns.md",
    "40_benchmark_and_repair_rules.md",
    "50_engineering_lessons.md",
}
RETIRED_WIKI_PREFIXES = (
    "wiki/00_principles",
    "wiki/10_foundations",
    "wiki/20_semantics",
    "wiki/30_templates",
    "wiki/40_experiments",
    "wiki/50_benchmarks",
    "wiki/60_workflows",
    "wiki/70_decisions",
    "wiki/80_maintenance",
    "wiki/90_index",
)
LEGACY_MACHINE_REFERENCE_MAP = {
    "wiki/20_semantics/data_ledger.jsonl": "machine/data_ledger.jsonl",
    "wiki/20_semantics/operator_semantics.jsonl": "machine/operator_ledger.jsonl",
    "wiki/30_templates/template_library.jsonl": "machine/template_library.jsonl",
    "wiki/40_experiments/research_record_compile.json": "raw/research/runs/legacy_wiki_experiments/research_record_compile.md",
    "wiki/50_benchmarks/benchmark_rules.jsonl": "machine/benchmark_rules.jsonl",
    "wiki/80_maintenance/freshness_manifest.json": "machine/freshness_manifest.json",
}
PATH_LIST_KEYS = {"source_paths", "evidence_paths", "experiment_paths", "case_report_paths"}
LEGACY_RESEARCH_COMPILE_RAW_PATH = Path("raw") / "research" / "runs" / "legacy_wiki_experiments" / "research_record_compile.md"
DEFAULT_ACTIVITY_BODY = "# Activity Snapshot\n\nNo platform activity snapshot has been captured in this vault yet.\n"


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for vault migration."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> Any:
    """Input: JSON path. Output: decoded JSON or none. Read optional migration inputs."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _read_jsonl_rows(path: Path, max_rows: int = 0) -> list[dict[str, Any]]:
    """Input: JSONL path and row limit. Output: object rows. Load machine or raw resource rows."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
                    if max_rows > 0 and len(rows) >= max_rows:
                        break
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Input: JSONL path and rows. Output: path. Write deterministic JSONL machine resources."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _has_jsonl_rows(path: Path) -> bool:
    """Input: JSONL path. Output: bool. Check non-empty parseable JSONL without loading every row."""
    return bool(_read_jsonl_rows(path, max_rows=1))


def _legacy_reference_relative_path(value: str, root: Path) -> str:
    """Input: path-like string. Output: vault-relative path when it points at a legacy vault area."""
    normalized = str(value).replace("\\", "/").strip()
    if not normalized:
        return ""
    root_posix = root.resolve().as_posix().rstrip("/")
    if normalized.lower().startswith((root_posix + "/").lower()):
        candidate = normalized[len(root_posix) + 1 :]
        return candidate if candidate.startswith(("wiki/", "raw/learn/", "raw/research/stage1/")) else ""
    if normalized.startswith("knowledge/"):
        candidate = normalized.removeprefix("knowledge/")
        if candidate.startswith(("wiki/", "raw/learn/", "raw/research/stage1/", "machine/")):
            return candidate
    if normalized.startswith(("wiki/", "raw/learn/", "raw/research/stage1/")):
        return normalized
    return ""


def _legacy_wiki_markdown_target(root: Path, relative_path: str, generated_at: str) -> str:
    """Input: root, legacy wiki markdown path, timestamp. Output: canonical raw source path."""
    relative = PurePosixPath(relative_path)
    stem_parts = relative.with_suffix("").parts
    if stem_parts and stem_parts[0] == "wiki":
        stem_parts = stem_parts[1:]
    slug = "__".join(stem_parts)
    if relative.parts and relative.parts[1:2] == ("40_experiments",):
        return (Path("raw") / "research" / "runs" / "legacy_wiki_experiments" / f"{slug}.md").as_posix()
    search_root = root / "raw" / "community" / "user_messages"
    if search_root.exists():
        for existing in sorted(search_root.glob(f"*/legacy_wiki/{slug}.md")):
            return relative_to_knowledge_root(existing, root)
    return (Path("raw") / "community" / "user_messages" / generated_at[:10] / "legacy_wiki" / f"{slug}.md").as_posix()


def _legacy_wiki_non_markdown_target(root: Path, relative_path: str, generated_at: str) -> str:
    """Input: root, legacy wiki file path, timestamp. Output: canonical raw wrapper path."""
    if relative_path == "wiki/40_experiments/research_record_compile.json":
        return LEGACY_RESEARCH_COMPILE_RAW_PATH.as_posix()
    relative = PurePosixPath(relative_path)
    stem_parts = relative.with_suffix("").parts
    if stem_parts and stem_parts[0] == "wiki":
        stem_parts = stem_parts[1:]
    suffix = relative.suffix.lower().lstrip(".") or "file"
    name = f"{'__'.join(stem_parts)}_{suffix}.md"
    if relative.parts and relative.parts[1:2] == ("40_experiments",):
        return (Path("raw") / "research" / "runs" / "legacy_wiki_experiments" / name).as_posix()
    search_root = root / "raw" / "community" / "user_messages"
    if search_root.exists():
        for existing in sorted(search_root.glob(f"*/legacy_wiki/{name}")):
            return relative_to_knowledge_root(existing, root)
    return (Path("raw") / "community" / "user_messages" / generated_at[:10] / "legacy_wiki" / name).as_posix()


def _legacy_raw_learn_target(root: Path, relative_path: str, generated_at: str) -> str:
    """Input: root, old raw/learn path, timestamp. Output: canonical platform Learn raw path."""
    filename = PurePosixPath(relative_path).name
    learn_root = root / "raw" / "platform" / "learn"
    if learn_root.exists():
        for existing in sorted(learn_root.glob(f"*/{filename}")):
            return relative_to_knowledge_root(existing, root)
    return (Path("raw") / "platform" / "learn" / generated_at[:10] / filename).as_posix()


def _legacy_raw_non_markdown_target(relative_path: str, generated_at: str) -> str:
    """Input: retired raw file path and timestamp. Output: canonical Markdown wrapper target."""
    relative = PurePosixPath(relative_path)
    suffix = relative.suffix.lower().lstrip(".") or "file"
    if relative.parts[:2] == ("raw", "learn"):
        stem_parts = relative.with_suffix("").parts[2:]
        return (Path("raw") / "platform" / "learn" / generated_at[:10] / f"{'__'.join(stem_parts)}_{suffix}.md").as_posix()
    if relative.parts[:3] == ("raw", "research", "stage1"):
        stem_parts = relative.with_suffix("").parts[3:]
        return (Path("raw") / "research" / "runs" / f"{'__'.join(stem_parts)}_{suffix}.md").as_posix()
    stem_parts = relative.with_suffix("").parts
    return (Path("raw") / "community" / "user_messages" / generated_at[:10] / f"{'__'.join(stem_parts)}_{suffix}.md").as_posix()


def _migration_path_map(root: Path, *groups: list[dict[str, Any]]) -> dict[str, str]:
    """Input: root and migration summaries. Output: old relative path to actual new relative path map."""
    mapping: dict[str, str] = {}
    for group in groups:
        for row in group:
            source = str(row.get("source_path", "")).strip()
            target = str(row.get("target_path", "")).strip()
            if not source or not target:
                continue
            mapping[relative_to_knowledge_root(source, root)] = relative_to_knowledge_root(target, root)
    return mapping


def _legacy_raw_stage1_target(
    root: Path,
    relative_path: str,
    migration_map: dict[str, str] | None = None,
) -> str:
    """Input: root and old raw stage1 path. Output: canonical raw research run path."""
    if migration_map and relative_path in migration_map:
        return migration_map[relative_path]
    filename = PurePosixPath(relative_path).name
    runs_root = root / "raw" / "research" / "runs"
    if runs_root.exists():
        existing = runs_root / filename
        if existing.exists():
            return relative_to_knowledge_root(existing, root)
    return (Path("raw") / "research" / "runs" / filename).as_posix()


def _normalize_legacy_reference(
    value: str,
    root: Path,
    generated_at: str,
    migration_map: dict[str, str] | None = None,
) -> str:
    """Input: possible path, vault root, timestamp. Output: canonical path when value references retired locations."""
    relative = _legacy_reference_relative_path(value, root)
    if not relative:
        return str(value).replace("\\", "/").strip()
    if migration_map and relative == "wiki/40_experiments/research_record_compile.json" and relative in migration_map:
        return migration_map[relative]
    if relative in LEGACY_MACHINE_REFERENCE_MAP:
        return LEGACY_MACHINE_REFERENCE_MAP[relative]
    if migration_map and relative in migration_map:
        return migration_map[relative]
    if relative.startswith("raw/learn/"):
        return _legacy_raw_learn_target(root, relative, generated_at)
    if relative.startswith("raw/research/stage1/"):
        return _legacy_raw_stage1_target(root, relative, migration_map)
    if any(relative == prefix or relative.startswith(prefix + "/") for prefix in RETIRED_WIKI_PREFIXES):
        if PurePosixPath(relative).suffix.lower() == ".md":
            return _legacy_wiki_markdown_target(root, relative, generated_at)
        return _legacy_wiki_non_markdown_target(root, relative, generated_at)
    return str(value).replace("\\", "/").strip()


def _normalize_machine_value(
    value: Any,
    root: Path,
    generated_at: str,
    key: str = "",
    migration_map: dict[str, str] | None = None,
) -> Any:
    """Input: JSON value and key. Output: normalized value. Rewrite retired path references recursively."""
    if isinstance(value, dict):
        return {
            str(child_key): _normalize_machine_value(child_value, root, generated_at, str(child_key), migration_map)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        normalized = [_normalize_machine_value(item, root, generated_at, key, migration_map) for item in value]
        if key in PATH_LIST_KEYS:
            deduped: list[Any] = []
            for item in normalized:
                if item not in deduped:
                    deduped.append(item)
            return deduped
        return normalized
    if isinstance(value, str) and (key in PATH_LIST_KEYS or key.endswith("_path")):
        return _normalize_legacy_reference(value, root, generated_at, migration_map)
    return value


def _normalize_machine_rows(
    rows: list[dict[str, Any]],
    root: Path,
    generated_at: str,
    migration_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Input: machine rows. Output: rows with retired legacy path references rewritten."""
    return [
        _normalize_machine_value(row, root, generated_at, migration_map=migration_map)
        for row in rows
        if isinstance(row, dict)
    ]


def _legacy_resource_candidates(root: Path, resource_name: str) -> list[Path]:
    """Input: root and resource name. Output: legacy paths. Locate old machine resources explicitly."""
    return [root / path for path in LEGACY_MACHINE_RESOURCE_PATHS.get(resource_name, ())]


def _first_nonempty_legacy_jsonl(root: Path, resource_name: str) -> Path | None:
    """Input: root and resource name. Output: path or none. Find a non-empty legacy JSONL resource."""
    for candidate in _legacy_resource_candidates(root, resource_name):
        if _has_jsonl_rows(candidate):
            return candidate
    return None


def _copy_legacy_jsonl_if_needed(
    root: Path,
    resource_name: str,
    generated_at: str,
    migration_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Input: root and resource name. Output: copy summary. Materialize a canonical machine JSONL from legacy fallback."""
    target = machine_resource_path(root, resource_name)
    if _has_jsonl_rows(target):
        rows = _read_jsonl_rows(target)
        normalized = _normalize_machine_rows(rows, root, generated_at, migration_map)
        if normalized != rows:
            _write_jsonl(target, normalized)
        return {"status": "preserved_existing", "path": str(target), "source_path": "", "normalized": normalized != rows}
    source = _first_nonempty_legacy_jsonl(root, resource_name)
    if source is None:
        return {"status": "missing_legacy", "path": str(target), "source_path": ""}
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = _normalize_machine_rows(_read_jsonl_rows(source), root, generated_at, migration_map)
    _write_jsonl(target, rows)
    return {"status": "copied_legacy", "path": str(target), "source_path": str(source), "normalized": True}


def _compile_or_copy_data_ledger(
    root: Path,
    generated_at: str,
    migration_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Input: vault root and timestamp. Output: summary. Build canonical data ledger from raw captures with legacy fallback."""
    capture_root = root / "raw" / "platform" / "data_fields"
    has_raw_capture = any(capture_root.glob("*/data_fields.jsonl")) if capture_root.exists() else False
    copy_summary = _copy_legacy_jsonl_if_needed(root, "data_ledger", generated_at, migration_map)
    if not has_raw_capture:
        target = machine_resource_path(root, "data_ledger")
        if _has_jsonl_rows(target):
            return {"status": "completed_with_legacy_only", "legacy_copy": copy_summary, "ledger_path": str(target)}
        return {
            "status": "skipped_no_source",
            "legacy_copy": copy_summary,
            "ledger_path": str(target),
            "message": "No raw platform data-field capture or legacy data ledger is available.",
        }
    try:
        capture = latest_capture_dir(root)
        compiled = compile_data_ledger_from_raw(root, capture_dir=capture, generated_at=generated_at)
        return {"status": "completed", "legacy_copy": copy_summary, "compile": compiled}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        target = machine_resource_path(root, "data_ledger")
        if _has_jsonl_rows(target):
            return {
                "status": "completed_with_legacy_only",
                "legacy_copy": copy_summary,
                "compile_error": str(error),
                "ledger_path": str(target),
            }
        return {"status": "blocked", "legacy_copy": copy_summary, "compile_error": str(error), "ledger_path": str(target)}


def _seed_template_rows() -> list[dict[str, Any]]:
    """Input: none. Output: template rows. Load bundled seed templates as last-resort migration content."""
    seed = Path(__file__).resolve().parents[1] / "docs" / "knowledge" / "template_library.example.jsonl"
    return _read_jsonl_rows(seed)


def _materialize_template_library(
    root: Path,
    generated_at: str,
    migration_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Input: vault root and timestamp. Output: summary. Write canonical template library and machine preview."""
    target = machine_resource_path(root, "template_library")
    source = target if _has_jsonl_rows(target) else _first_nonempty_legacy_jsonl(root, "template_library")
    rows = _read_jsonl_rows(source) if source is not None else _seed_template_rows()
    rows = _normalize_machine_rows(rows, root, generated_at, migration_map)
    source_status = "preserved_existing" if source == target else "copied_legacy" if source is not None else "seeded"
    if not rows:
        source_status = "blocked"
    _write_jsonl(target, rows)
    templates = load_template_library(target)
    preview = root / "machine" / "previews" / "template_library.md"
    write_template_library_markdown(preview, templates, generated_at)
    return {
        "status": "completed" if rows else "blocked",
        "source_status": source_status,
        "source_path": str(source or ""),
        "path": str(target),
        "markdown_path": str(preview),
        "record_count": len(rows),
    }


def _normalize_benchmark_rules(
    rules: list[BenchmarkRule],
    root: Path,
    generated_at: str,
    migration_map: dict[str, str] | None = None,
) -> list[BenchmarkRule]:
    """Input: benchmark rules. Output: normalized rules. Keep rule text while removing active legacy evidence paths."""
    normalized: list[BenchmarkRule] = []
    canonical_evidence = [
        "knowledge/machine/benchmark_rules.jsonl",
        "knowledge/wiki/40_benchmark_and_repair_rules.md",
        "knowledge/wiki/50_engineering_lessons.md",
    ]
    for rule in rules:
        evidence_paths = _normalize_machine_value(
                rule.evidence_paths,
                root,
                generated_at,
                "evidence_paths",
                migration_map,
            )
        normalized.append(replace(rule, evidence_paths=evidence_paths or canonical_evidence))
    return normalized


def _materialize_benchmark_rules(
    root: Path,
    generated_at: str,
    migration_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Input: vault root and timestamp. Output: summary. Write canonical benchmark rules and preview."""
    target = machine_resource_path(root, "benchmark_rules")
    source = target if _has_jsonl_rows(target) else _first_nonempty_legacy_jsonl(root, "benchmark_rules")
    try:
        rules = load_benchmark_rules(source) if source is not None else []
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        rules = []
    if not rules:
        rules = default_benchmark_rules()
        source_status = "seeded_defaults"
    else:
        source_status = "preserved_existing" if source == target else "copied_legacy"
    rules = _normalize_benchmark_rules(rules, root, generated_at, migration_map)
    write_benchmark_rules_jsonl(target, rules)
    preview = root / "machine" / "previews" / "benchmark_rules.md"
    write_benchmark_rules_markdown(preview, rules, generated_at)
    return {
        "status": "completed" if rules else "blocked",
        "source_status": source_status,
        "source_path": str(source or ""),
        "path": str(target),
        "markdown_path": str(preview),
        "record_count": len(rules),
    }


def _scope_key(scope: dict[str, Any]) -> tuple[str, str, int, str] | None:
    """Input: scope dict. Output: normalized key or none. Normalize captured platform scope rows."""
    try:
        key = (
            str(scope.get("instrument_type", "EQUITY") or "EQUITY").strip().upper(),
            str(scope.get("region", "")).strip().upper(),
            int(scope.get("delay")),
            str(scope.get("universe", "")).strip().upper(),
        )
    except (TypeError, ValueError):
        return None
    return key if key[0] and key[1] and key[2] >= 0 and key[3] else None


def _scope_rows_from_raw_captures(root: Path, generated_at: str) -> list[dict[str, Any]]:
    """Input: vault root and timestamp. Output: scope rows. Compile breadth-first capture coverage from raw scope logs."""
    by_key: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    capture_root = root / "raw" / "platform" / "data_fields"
    for path in sorted(capture_root.glob("*/scopes.jsonl")):
        for row in _read_jsonl_rows(path):
            scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
            key = _scope_key(scope)
            if key is None:
                continue
            by_key[key] = {
                "generated_at": generated_at,
                "instrument_type": key[0],
                "region": key[1],
                "delay": key[2],
                "universe": key[3],
                "status": str(row.get("status", "unknown")),
                "dataset_count": int(row.get("data_set_count", 0) or 0),
                "truncated": bool(row.get("truncated", False)),
                "message": str(row.get("message", "")),
            }
    return [by_key[key] for key in sorted(by_key)]


def _scope_rows_from_ledger(root: Path, generated_at: str) -> list[dict[str, Any]]:
    """Input: vault root and timestamp. Output: scope rows. Derive fallback scope coverage from compiled data rows."""
    ledger = machine_resource_path(root, "data_ledger")
    by_key: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for row in _read_jsonl_rows(ledger):
        scopes = row.get("available_scopes") if isinstance(row.get("available_scopes"), list) else []
        if not scopes:
            scopes = [
                {
                    "instrument_type": row.get("instrument_type", "EQUITY"),
                    "region": row.get("region"),
                    "delay": row.get("delay"),
                    "universe": row.get("universe"),
                }
            ]
        for scope in scopes:
            if not isinstance(scope, dict):
                continue
            key = _scope_key(scope)
            if key is None:
                continue
            by_key[key] = {
                "generated_at": generated_at,
                "instrument_type": key[0],
                "region": key[1],
                "delay": key[2],
                "universe": key[3],
                "status": "available_from_data_ledger",
                "dataset_count": 0,
                "truncated": False,
                "message": "Derived from machine/data_ledger.jsonl during vault migration.",
            }
    return [by_key[key] for key in sorted(by_key)]


def _materialize_scope_matrix(root: Path, generated_at: str) -> dict[str, Any]:
    """Input: vault root and timestamp. Output: summary. Write the canonical scope matrix from raw capture breadth."""
    target = machine_resource_path(root, "scope_matrix")
    rows = _scope_rows_from_raw_captures(root, generated_at) or _scope_rows_from_ledger(root, generated_at)
    _write_jsonl(target, rows)
    return {
        "status": "completed" if rows else "skipped_no_source",
        "path": str(target),
        "record_count": len(rows),
    }


def _write_activity_snapshot(root: Path, generated_at: str) -> dict[str, Any]:
    """Input: vault root and timestamp. Output: summary. Preserve the platform activity note as a canonical raw source."""
    target = root / ACTIVITY_SNAPSHOT
    legacy = root / "wiki" / "10_foundations" / "activity_snapshot.md"
    moved_sources = sorted(
        (root / "raw" / "community" / "user_messages").glob("*/legacy_wiki/10_foundations__activity_snapshot.md")
    )
    source = legacy if legacy.exists() else moved_sources[-1] if moved_sources else None
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if "No platform activity snapshot has been captured" not in existing or source is None:
            return {
                "status": "preserved_existing",
                "path": str(target),
                "source_path": "",
            }
        body = source.read_text(encoding="utf-8")
        status = "restored_from_legacy"
    else:
        body = source.read_text(encoding="utf-8") if source is not None else DEFAULT_ACTIVITY_BODY
        status = "completed"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return {
        "status": status,
        "path": str(target),
        "source_path": str(source) if source is not None else "",
    }


def _preserve_legacy_research_compile_report(root: Path, generated_at: str) -> dict[str, Any]:
    """Input: vault root and timestamp. Output: preserved report summary. Archive old research compile JSON as raw evidence."""
    legacy = root / "wiki" / "40_experiments" / "research_record_compile.json"
    payload = _read_json(legacy)
    if not isinstance(payload, dict):
        return {"status": "skipped_no_source", "source_path": str(legacy), "raw_path": "", "target_path": ""}
    target = root / LEGACY_RESEARCH_COMPILE_RAW_PATH
    body = (
        "# Legacy Research Record Compile Report\n\n"
        "This raw note preserves the old `wiki/40_experiments/research_record_compile.json` "
        "before retired wiki cleanup.\n\n"
        "```json\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}\n"
        "```\n"
    )
    actual_target = _unique_text_target(target, body)
    actual_target.parent.mkdir(parents=True, exist_ok=True)
    write_status = "preserved_existing"
    if not actual_target.exists():
        actual_target.write_text(body, encoding="utf-8")
        write_status = "preserved_collision" if actual_target != target else "preserved"
    return {
        "status": "completed",
        "write_status": write_status,
        "source_path": str(legacy),
        "target_path": str(actual_target),
        "raw_path": str(actual_target),
        "record_count": int(payload.get("record_count", 0) or 0),
        "payload": payload,
    }


def _legacy_research_compile_row(
    preserved: dict[str, Any],
    root: Path,
    generated_at: str,
    migration_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Input: preserved legacy report summary. Output: research ledger row. Convert old compile JSON to machine history."""
    payload = preserved.get("payload") if isinstance(preserved.get("payload"), dict) else {}
    raw_path = Path(str(preserved.get("raw_path", "")))
    source_paths = [
        _normalize_legacy_reference(str(path), root, generated_at, migration_map)
        for path in payload.get("source_paths", [])
        if str(path)
    ]
    case_report_paths = [
        _normalize_legacy_reference(str(path), root, generated_at, migration_map)
        for path in payload.get("case_report_paths", [])
        if str(path)
    ]
    return {
        "run_id": "legacy_research_record_compile",
        "objective": "Preserve legacy research record compile evidence before retired wiki cleanup",
        "backtest": [],
        "triage": [
            {
                "benchmark_label": "legacy_research_compile",
                "failed": [],
                "source_paths": source_paths,
                "case_report_paths": case_report_paths,
            }
        ],
        "repair": {},
        "candidate_gate": [],
        "user_approval": [],
        "approved_queue": [],
        "manual_submission_status": [],
        "synced_at": generated_at,
        "final_state": "compiled_from_legacy_research_compile_report",
        "case_reason": "legacy_import",
        "legacy_compile_report_path": relative_to_knowledge_root(raw_path, root),
        "legacy_record_count": int(payload.get("record_count", 0) or 0),
    }


def _append_unique_research_row(target: Path, row: dict[str, Any]) -> list[dict[str, Any]]:
    """Input: research ledger path and row. Output: rows written. Append one row when run_id is not already present."""
    rows = _read_jsonl_rows(target)
    if not any(str(existing.get("run_id", "")) == str(row.get("run_id", "")) for existing in rows):
        rows.append(row)
        _write_jsonl(target, rows)
    return rows


def _legacy_stage1_source_paths(root: Path) -> list[str]:
    """Input: vault root. Output: raw source paths. Locate migrated Stage 1 lesson notes."""
    paths = sorted((root / "wiki" / "40_experiments").glob("*.md"))
    paths.extend(sorted((root / "raw" / "research" / "runs" / "legacy_wiki_experiments").glob("*.md")))
    return [
        relative_to_knowledge_root(path, root)
        for path in paths
        if path.name != LEGACY_RESEARCH_COMPILE_RAW_PATH.name
    ]


def _repair_existing_legacy_stage1_rows(target: Path, root: Path) -> dict[str, Any]:
    """Input: research ledger and root. Output: repair summary. Backfill old Stage 1 provenance when it is empty."""
    rows = _read_jsonl_rows(target)
    source_paths = _legacy_stage1_source_paths(root)
    changed = False
    if not source_paths:
        return {"status": "skipped_no_source", "updated_count": 0}
    for row in rows:
        if str(row.get("run_id", "")) != "legacy_stage1_import":
            continue
        triage = row.get("triage")
        if not isinstance(triage, list) or not triage:
            row["triage"] = [{"benchmark_label": "legacy_stage1_lesson", "failed": [], "source_paths": source_paths}]
            changed = True
            continue
        first = triage[0]
        if isinstance(first, dict) and not first.get("source_paths"):
            first["source_paths"] = source_paths
            changed = True
    if changed:
        _write_jsonl(target, rows)
    return {"status": "completed", "updated_count": 1 if changed else 0, "source_count": len(source_paths)}


def _normalize_research_records_file(
    target: Path,
    root: Path,
    generated_at: str,
    migration_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Input: research ledger path. Output: normalization summary. Rewrite retired references in existing rows."""
    rows = _read_jsonl_rows(target)
    normalized = _normalize_machine_rows(rows, root, generated_at, migration_map)
    if normalized != rows:
        _write_jsonl(target, normalized)
    return {
        "status": "completed" if rows else "skipped_no_rows",
        "record_count": len(rows),
        "updated": normalized != rows,
    }


def _ensure_research_records(
    root: Path,
    generated_at: str,
    migration_map: dict[str, str] | None = None,
    preserved_compile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Input: vault root and timestamp. Output: summary. Keep research history machine-readable even before new runs exist."""
    preserved_compile = preserved_compile or _preserve_legacy_research_compile_report(root, generated_at)
    compile_summary = compile_research_records(root, generated_at=generated_at)
    target = machine_resource_path(root, "research_records")
    if preserved_compile["status"] == "completed":
        rows = _append_unique_research_row(
            target,
            _legacy_research_compile_row(preserved_compile, root, generated_at, migration_map),
        )
        stage1_repair = _repair_existing_legacy_stage1_rows(target, root)
        normalization = _normalize_research_records_file(target, root, generated_at, migration_map)
        return {
            "status": "completed",
            "path": str(target),
            "compile": compile_summary,
            "legacy_compile": {key: value for key, value in preserved_compile.items() if key != "payload"},
            "record_count": len(rows),
            "stage1_repair": stage1_repair,
            "normalization": normalization,
        }
    if _has_jsonl_rows(target):
        stage1_repair = _repair_existing_legacy_stage1_rows(target, root)
        normalization = _normalize_research_records_file(target, root, generated_at, migration_map)
        return {
            "status": "completed",
            "path": str(target),
            "compile": compile_summary,
            "stage1_repair": stage1_repair,
            "normalization": normalization,
        }
    legacy_experiments = _legacy_stage1_source_paths(root)
    row = {
        "run_id": "legacy_stage1_import",
        "objective": "Preserve migrated Stage 1 research lessons",
        "backtest": [],
        "triage": [
            {
                "benchmark_label": "legacy_stage1_lesson",
                "failed": [],
                "source_paths": legacy_experiments[:20],
            }
        ],
        "repair": {},
        "candidate_gate": [],
        "user_approval": [],
        "approved_queue": [],
        "manual_submission_status": [],
        "synced_at": generated_at,
        "final_state": "compiled_from_legacy_wiki",
        "case_reason": "legacy_import",
    }
    _write_jsonl(target, [row])
    normalization = _normalize_research_records_file(target, root, generated_at, migration_map)
    return {
        "status": "completed",
        "path": str(target),
        "compile": compile_summary,
        "source_status": "legacy_summary_seed",
        "normalization": normalization,
    }


def _unique_target(target: Path, source: Path) -> Path:
    """Input: target and source. Output: safe target path. Avoid overwriting different migrated raw files."""
    if not target.exists():
        return target
    if hashlib.sha256(target.read_bytes()).hexdigest() == hashlib.sha256(source.read_bytes()).hexdigest():
        return target
    index = 1
    while True:
        candidate = target.with_name(f"{target.stem}.{index}{target.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _unique_text_target(target: Path, body: str) -> Path:
    """Input: target and text body. Output: safe target path. Avoid overwriting different raw wrapper notes."""
    if not target.exists():
        return target
    existing_text = target.read_text(encoding="utf-8")
    _, existing_body = parse_markdown_front_matter(existing_text)
    if existing_text == body or existing_body == body:
        return target
    index = 1
    while True:
        candidate = target.with_name(f"{target.stem}.{index}{target.suffix}")
        if not candidate.exists():
            return candidate
        candidate_text = candidate.read_text(encoding="utf-8")
        _, candidate_body = parse_markdown_front_matter(candidate_text)
        if candidate_text == body or candidate_body == body:
            return candidate
        index += 1


def _is_sensitive_legacy_source(path: Path, root: Path) -> bool:
    """Input: source path and root. Output: bool. Avoid migrating and deleting sensitive retired raw files."""
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return True
    return any(fragment in part.lower() for part in parts for fragment in SENSITIVE_NAME_FRAGMENTS)


def _raw_non_markdown_wrapper_body(source: Path, relative_path: str) -> str:
    """Input: source file and relative path. Output: Markdown wrapper body preserving text or bytes."""
    data = source.read_bytes()
    suffix = source.suffix.lower().lstrip(".") or "text"
    try:
        content = data.decode("utf-8")
        fence = suffix
        note = "This raw note preserves a retired raw artifact before cleanup."
    except UnicodeDecodeError:
        content = base64.b64encode(data).decode("ascii")
        fence = "base64"
        note = f"This raw note preserves a retired binary raw artifact before cleanup. Original extension: .{suffix}."
    return (
        f"# Legacy {relative_path}\n\n"
        f"{note}\n\n"
        f"```{fence}\n"
        f"{content}\n"
        "```\n"
    )


def _wrap_retired_raw_non_markdown_file(source: Path, target: Path, root: Path) -> dict[str, Any]:
    """Input: retired source, target, root. Output: preservation row. Wrap non-Markdown raw evidence safely."""
    if _is_sensitive_legacy_source(source, root):
        return {"status": "refused_sensitive", "source_path": str(source), "target_path": ""}
    relative = source.relative_to(root).as_posix()
    body = _raw_non_markdown_wrapper_body(source, relative)
    actual_target = _unique_text_target(target, body)
    actual_target.parent.mkdir(parents=True, exist_ok=True)
    if actual_target.exists():
        source.unlink()
        status = "removed_duplicate"
    else:
        actual_target.write_text(body, encoding="utf-8")
        source.unlink()
        status = "preserved_collision" if actual_target != target else "preserved"
    return {"status": status, "source_path": str(source), "target_path": str(actual_target)}


def _move_markdown_file(source: Path, target: Path, root: Path) -> dict[str, Any]:
    """Input: source, target, and root path. Output: move summary. Move non-sensitive Markdown without overwrite."""
    if _is_sensitive_legacy_source(source, root):
        return {"status": "refused_sensitive", "source_path": str(source), "target_path": ""}
    actual_target = _unique_target(target, source)
    actual_target.parent.mkdir(parents=True, exist_ok=True)
    if actual_target.exists():
        source.unlink()
        status = "removed_duplicate"
    else:
        shutil.move(str(source), str(actual_target))
        status = "migrated"
    return {"status": status, "source_path": str(source), "target_path": str(actual_target)}


def _migrate_raw_markdown_locations(root: Path, generated_at: str) -> list[dict[str, Any]]:
    """Input: vault root and timestamp. Output: move summaries. Move legacy raw Markdown into canonical families."""
    moves: list[dict[str, Any]] = []
    for source in sorted(path for path in root.iterdir() if path.is_file() and path.suffix.lower() == ".md"):
        target_name = f"legacy_knowledge_root_{source.stem}.md"
        target = root / "raw" / "community" / "user_messages" / generated_at[:10] / target_name
        moves.append(_move_markdown_file(source, target, root))
    raw_root = root / "raw"
    if not raw_root.exists():
        return moves
    for source in sorted(path for path in raw_root.iterdir() if path.is_file() and path.suffix.lower() == ".md"):
        if source.name == "source_index.md":
            continue
        day_match = DATE_RE.search(source.name)
        day = day_match.group(0) if day_match else generated_at[:10]
        stem = source.stem
        if stem == "karpathy_llm_knowledge_bases_20260702":
            stem = "karpathy_llm_knowledge_bases"
            day = "2026-07-02"
        moves.append(_move_markdown_file(source, raw_root / "community" / "user_messages" / day / f"{stem}.md", root))
    stage1 = raw_root / "research" / "stage1"
    if stage1.exists():
        for source in sorted(path for path in stage1.rglob("*") if path.is_file() and path.suffix.lower() == ".md"):
            relative = source.relative_to(stage1)
            target_name = "__".join(relative.with_suffix("").parts) + ".md"
            moves.append(_move_markdown_file(source, raw_root / "research" / "runs" / target_name, root))
        for source in sorted(path for path in stage1.rglob("*") if path.is_file() and path.suffix.lower() != ".md"):
            relative = source.relative_to(root).as_posix()
            moves.append(
                _wrap_retired_raw_non_markdown_file(
                    source,
                    root / _legacy_raw_non_markdown_target(relative, generated_at),
                    root,
                )
            )
    learn = raw_root / "learn"
    if learn.exists():
        for source in sorted(path for path in learn.rglob("*") if path.is_file() and path.suffix.lower() == ".md"):
            target_name = source.with_suffix(".md").name
            moves.append(_move_markdown_file(source, raw_root / "platform" / "learn" / generated_at[:10] / target_name, root))
        for source in sorted(path for path in learn.rglob("*") if path.is_file() and path.suffix.lower() != ".md"):
            relative = source.relative_to(root).as_posix()
            moves.append(
                _wrap_retired_raw_non_markdown_file(
                    source,
                    root / _legacy_raw_non_markdown_target(relative, generated_at),
                    root,
                )
            )
    return moves


def _migrate_legacy_wiki_markdown_sources(root: Path, generated_at: str) -> list[dict[str, Any]]:
    """Input: vault root and timestamp. Output: move summaries. Preserve old wiki notes as raw migration sources."""
    moves: list[dict[str, Any]] = []
    wiki_root = root / "wiki"
    if not wiki_root.exists():
        return moves
    for source in sorted(path for path in wiki_root.rglob("*") if path.is_file() and path.suffix.lower() == ".md"):
        relative = source.relative_to(wiki_root)
        if len(relative.parts) == 1 and source.name in CANONICAL_WIKI_MARKDOWN_FILES:
            continue
        if relative.parts and relative.parts[0] == "60_research_cases":
            continue
        if relative.parts and relative.parts[0] == "70_decisions":
            continue
        slug = "__".join(relative.with_suffix("").parts)
        if relative.parts and relative.parts[0] == "40_experiments":
            target = root / "raw" / "research" / "runs" / "legacy_wiki_experiments" / f"{slug}.md"
        else:
            target = root / "raw" / "community" / "user_messages" / generated_at[:10] / "legacy_wiki" / f"{slug}.md"
        moves.append(_move_markdown_file(source, target, root))
    return moves


def _migrate_legacy_wiki_non_markdown_sources(root: Path, generated_at: str) -> list[dict[str, Any]]:
    """Input: vault root and timestamp. Output: preservation summaries. Wrap old wiki data files as raw Markdown."""
    wiki_root = root / "wiki"
    if not wiki_root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for source in sorted(path for path in wiki_root.rglob("*") if path.is_file() and path.suffix.lower() != ".md"):
        relative = source.relative_to(root).as_posix()
        if not any(relative == prefix or relative.startswith(prefix + "/") for prefix in RETIRED_WIKI_PREFIXES):
            continue
        if relative == "wiki/40_experiments/research_record_compile.json":
            continue
        if _is_sensitive_legacy_source(source, root):
            rows.append({"status": "refused_sensitive", "source_path": str(source), "target_path": ""})
            continue
        target = root / _legacy_wiki_non_markdown_target(root, relative, generated_at)
        suffix = source.suffix.lower().lstrip(".") or "text"
        body = (
            f"# Legacy {relative}\n\n"
            "This raw note preserves a retired wiki machine artifact before cleanup.\n\n"
            f"```{suffix}\n"
            f"{source.read_text(encoding='utf-8')}\n"
            "```\n"
        )
        actual_target = _unique_text_target(target, body)
        actual_target.parent.mkdir(parents=True, exist_ok=True)
        if actual_target.exists():
            status = "preserved_existing"
        else:
            actual_target.write_text(body, encoding="utf-8")
            status = "preserved_collision" if actual_target != target else "preserved"
        rows.append({"status": status, "source_path": str(source), "target_path": str(actual_target)})
    return rows


def _captured_at_for_path(path: Path, generated_at: str, metadata: dict[str, Any]) -> str:
    """Input: path, timestamp, metadata. Output: captured timestamp. Preserve explicit metadata or infer from path."""
    existing = str(metadata.get("captured_at", "")).strip()
    if existing:
        return existing
    for part in path.parts:
        if DATE_RE.fullmatch(part):
            return f"{part}T00:00:00+00:00"
    match = DATE_RE.search(path.name)
    if match:
        return f"{match.group(0)}T00:00:00+00:00"
    return generated_at


def _source_profile(relative_path: str) -> tuple[str, str, str, list[str]]:
    """Input: vault-relative raw path. Output: type, contents, update rule, compile targets. Classify raw sources."""
    if relative_path.startswith("raw/platform/data_fields/"):
        return (
            "platform_data_field_capture",
            "Platform data-field capture summary and provenance.",
            "rerun stratified platform data capture and compare scope/data-field counts",
            ["machine/data_ledger.jsonl", "machine/scope_matrix.jsonl", "machine/operator_ledger.jsonl", "wiki/20_data_semantics.md"],
        )
    if relative_path.startswith("raw/platform/learn/"):
        return (
            "platform_learn_material",
            "Platform Learn, documentation, operator, FAQ, or reading material captured as raw Markdown.",
            "refresh platform Learn raw material and compare source index rows",
            ["wiki/00_start_here.md", "wiki/10_factor_principles.md", "wiki/20_data_semantics.md", "wiki/30_template_and_operator_patterns.md"],
        )
    if relative_path.startswith("raw/platform/activities/"):
        return (
            "platform_activity_snapshot",
            "Platform activity or incentive snapshot used by planning.",
            "refresh platform activities and consultant incentive rules",
            ["machine/freshness_manifest.json", "wiki/00_start_here.md"],
        )
    if relative_path.startswith("raw/research/"):
        return (
            "research_record_source",
            "Raw research history, stage output, or migrated Stage 1 source note.",
            "compile research records after completed workflow runs",
            ["machine/research_records.jsonl", "wiki/60_research_cases"],
        )
    if relative_path.startswith("raw/community/user_messages/"):
        return (
            "user_provided_reference",
            "User-provided workflow principle or project-memory source.",
            "compile interaction lessons and engineering principles",
            ["wiki/50_engineering_lessons.md"],
        )
    if relative_path.startswith("raw/community/forum/"):
        return (
            "community_forum_source",
            "Forum experience or advisor discussion captured for workflow learning.",
            "refresh forum source and compile human experience wiki",
            ["wiki/10_factor_principles.md", "wiki/30_template_and_operator_patterns.md", "wiki/40_benchmark_and_repair_rules.md"],
        )
    return (
        "raw_markdown_source",
        "Canonical raw Markdown source.",
        "review source family and compiled targets during knowledge maintenance",
        ["wiki/50_engineering_lessons.md"],
    )


def _record_count_for_raw(path: Path, relative_path: str) -> int:
    """Input: raw Markdown path and relative path. Output: count. Estimate raw record count for source indexing."""
    if relative_path.startswith("raw/platform/data_fields/"):
        manifest = _read_json(path.parent / "manifest.json")
        if isinstance(manifest, dict):
            try:
                return int(manifest.get("field_count", 1) or 1)
            except (TypeError, ValueError):
                return 1
    text = path.read_text(encoding="utf-8")
    heading_count = sum(1 for line in text.splitlines() if line.startswith("#"))
    return max(1, heading_count)


def _repair_raw_markdown_metadata(root: Path, generated_at: str) -> dict[str, Any]:
    """Input: vault root and timestamp. Output: metadata summary. Add required front matter to every canonical raw note."""
    rows: list[SourceIndexRow] = []
    updated_paths: list[str] = []
    raw_root = root / "raw"
    for path in sorted(raw_root.rglob("*.md")) if raw_root.exists() else []:
        if path == raw_root / "source_index.md":
            continue
        if _is_sensitive_legacy_source(path, root):
            continue
        family = canonical_source_family(path, root)
        if not family.startswith("raw/"):
            continue
        text = path.read_text(encoding="utf-8")
        existing, body = parse_markdown_front_matter(text)
        if not body.strip():
            body = f"# {path.stem.replace('_', ' ').title()}\n"
        relative = relative_to_knowledge_root(path, root)
        source_type, contents, update_check, targets = _source_profile(relative)
        metadata = {
            "source_type": source_type,
            "source_family": family,
            "source_path": relative,
            "captured_at": _captured_at_for_path(path, generated_at, existing),
            "capture_tool": str(existing.get("capture_tool", "wqb.knowledge_vault_migration")) or "wqb.knowledge_vault_migration",
            "content_status": "raw_markdown",
            "record_count": _record_count_for_raw(path, relative),
            "content_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "update_check": update_check,
            "compiled_targets": targets,
        }
        if body and not body.startswith("\n"):
            body = body if body.startswith("#") else body
        path.write_text(render_front_matter(metadata) + body, encoding="utf-8")
        updated_paths.append(relative)
        rows.append(
            SourceIndexRow(
                path=relative,
                source_family=family,
                source_type=source_type,
                contents=contents,
                update_check=update_check,
                captured_at=str(metadata["captured_at"]),
                record_count=int(metadata["record_count"]),
                content_hash=str(metadata["content_hash"]),
                content_status="raw_markdown",
                compiled_targets=targets,
            )
        )
    index_path = update_source_index(root, rows)
    return {"status": "completed", "updated_count": len(updated_paths), "source_index_path": str(index_path), "updated_paths": updated_paths}


def _write_freshness_manifest(root: Path, generated_at: str) -> dict[str, Any]:
    """Input: vault root and timestamp. Output: summary. Normalize manifest paths to canonical active authorities."""
    day = generated_at[:10]
    rows = [
        {"name": "data_ledger", "path": "machine/data_ledger.jsonl", "updated_at": day, "max_age_days": DEFAULT_FRESHNESS_DAYS, "status": "compiled", "source_note": "Compiled or migrated into canonical machine authority."},
        {"name": "template_library", "path": "machine/template_library.jsonl", "updated_at": day, "max_age_days": DEFAULT_FRESHNESS_DAYS, "status": "compiled", "source_note": "Compiled or migrated into canonical machine authority."},
        {"name": "benchmark_rules", "path": "machine/benchmark_rules.jsonl", "updated_at": day, "max_age_days": DEFAULT_FRESHNESS_DAYS, "status": "compiled", "source_note": "Compiled or migrated into canonical machine authority."},
        {"name": "activity_snapshot", "path": ACTIVITY_SNAPSHOT.as_posix(), "updated_at": day, "max_age_days": DEFAULT_FRESHNESS_DAYS, "status": "compiled", "source_note": "Canonical raw platform activity snapshot."},
        {"name": "operator_catalog", "path": "machine/operator_ledger.jsonl", "updated_at": day, "max_age_days": DEFAULT_FRESHNESS_DAYS, "status": "compiled", "source_note": "Compiled from raw operators plus reviewed/default semantics."},
        {"name": "scope_matrix", "path": "machine/scope_matrix.jsonl", "updated_at": day, "max_age_days": DEFAULT_FRESHNESS_DAYS, "status": "compiled", "source_note": "Compiled from raw platform scope outcomes."},
        {"name": "research_records", "path": "machine/research_records.jsonl", "updated_at": day, "max_age_days": DEFAULT_FRESHNESS_DAYS, "status": "compiled", "source_note": "Compiled from raw workflow records or migration summaries."},
        {"name": "source_index", "path": "machine/source_index.jsonl", "updated_at": day, "max_age_days": DEFAULT_FRESHNESS_DAYS, "status": "compiled", "source_note": "Generated from raw Markdown source metadata."},
    ]
    path = machine_resource_path(root, "freshness_manifest")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {"status": "completed", "path": str(path), "record_count": len(rows)}


def _write_report(root: Path, report: dict[str, Any]) -> Path:
    """Input: vault root and report. Output: path. Persist immutable migration evidence plus latest pointer."""
    generated = datetime.fromisoformat(str(report["generated_at"]).replace("Z", "+00:00"))
    stem = generated.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = root / MIGRATION_REPORT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    index = 0
    while True:
        suffix = "" if index == 0 else f".{index}"
        path = directory / f"{stem}{suffix}.json"
        payload = {**report, "report_path": str(path)}
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            (directory / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            report["report_path"] = str(path)
            return path
        except FileExistsError:
            index += 1


def run_knowledge_vault_migration(
    knowledge_root: str | Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Input: knowledge root and optional timestamp. Output: migration report. Materialize the canonical vault before cleanup."""
    generated = generated_at or _now()
    paths = ensure_knowledge_dirs(knowledge_root)
    root = paths.root
    raw_moves = _migrate_raw_markdown_locations(root, generated)
    wiki_moves = _migrate_legacy_wiki_markdown_sources(root, generated)
    wiki_data_preserved = _migrate_legacy_wiki_non_markdown_sources(root, generated)
    research_compile_preserved = _preserve_legacy_research_compile_report(root, generated)
    research_compile_moves = [research_compile_preserved] if research_compile_preserved["status"] == "completed" else []
    move_map = _migration_path_map(root, raw_moves, wiki_moves, wiki_data_preserved, research_compile_moves)
    activity = _write_activity_snapshot(root, generated)
    data_ledger = _compile_or_copy_data_ledger(root, generated, move_map)
    templates = _materialize_template_library(root, generated, move_map)
    benchmarks = _materialize_benchmark_rules(root, generated, move_map)
    operators = compile_operator_semantics(root, generated)
    scope_matrix = _materialize_scope_matrix(root, generated)
    research_records = _ensure_research_records(root, generated, move_map, research_compile_preserved)
    freshness_manifest = _write_freshness_manifest(root, generated)
    raw_metadata = _repair_raw_markdown_metadata(root, generated)
    components = {
        "activity_snapshot": activity,
        "data_ledger": data_ledger,
        "template_library": templates,
        "benchmark_rules": benchmarks,
        "operator_ledger": operators,
        "scope_matrix": scope_matrix,
        "research_records": research_records,
        "freshness_manifest": freshness_manifest,
        "raw_metadata": raw_metadata,
    }
    blocked = [
        name
        for name, component in components.items()
        if isinstance(component, dict) and str(component.get("status", "")) == "blocked"
    ]
    report = {
        "report_type": "knowledge_vault_migration",
        "generated_at": generated,
        "status": "blocked" if blocked else "completed",
        "blocked_components": blocked,
        "raw_moves": raw_moves,
        "wiki_moves": wiki_moves,
        "wiki_data_preserved": wiki_data_preserved,
        "components": components,
    }
    _write_report(root, report)
    return report
