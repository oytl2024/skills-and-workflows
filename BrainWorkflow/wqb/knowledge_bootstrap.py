from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from wqb.benchmark_rules import BENCHMARK_RULES_PATH
from wqb.data_ledger import load_data_ledger, write_data_ledger_markdown
from wqb.knowledge_contracts import (
    RAW_REQUIRED_FIELDS,
    SourceIndexRow,
    parse_markdown_front_matter,
    render_front_matter,
    upsert_source_index_rows,
)
from wqb.knowledge_paths import machine_resource_path
from wqb.template_library import load_template_library, write_template_library_markdown


DATA_LEDGER_RESOURCE = "data_ledger"
TEMPLATE_LIBRARY_RESOURCE = "template_library"
FRESHNESS_MANIFEST_RESOURCE = "freshness_manifest"
DATA_LEDGER_JSONL = Path("machine") / "data_ledger.jsonl"
DATA_LEDGER_MD = Path("machine") / "previews" / "data_ledger.md"
TEMPLATE_LIBRARY_JSONL = Path("machine") / "template_library.jsonl"
TEMPLATE_LIBRARY_MD = Path("machine") / "previews" / "template_library.md"
FRESHNESS_MANIFEST = Path("machine") / "freshness_manifest.json"
OPERATOR_LEDGER = Path("machine") / "operator_ledger.jsonl"
BOOTSTRAP_REPORT_DIR = Path("raw") / "maintenance" / "bootstrap_reports"
ACTIVITY_SNAPSHOT = Path("raw") / "platform" / "activities" / "bootstrap_activity_snapshot.md"
NON_REFRESHED_BASELINE_DATE = "1970-01-01"


@dataclass(frozen=True)
class BootstrapSummary:
    generated_at: str
    knowledge_root: str
    data_ledger_count: int
    template_count: int
    artifact_paths: list[str]
    warnings: list[str]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: dict rows. Load seed records from disk."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Input: path and rows. Output: path. Write deterministic JSONL rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _stamp_rows(
    rows: list[dict[str, Any]],
    source_quality: str,
    coverage_status: str,
    normalize_coverage: bool = False,
) -> list[dict[str, Any]]:
    """Input: rows and labels. Output: copied rows with source labels and optional conservative coverage."""
    stamped = []
    for row in rows:
        copied = dict(row)
        copied["source_quality"] = source_quality
        copied["coverage_status"] = coverage_status
        if normalize_coverage:
            copied["coverage"] = 0.0
        stamped.append(copied)
    return stamped


def _activity_snapshot_body(generated_at: str) -> str:
    """Input: timestamp. Output: markdown body. Build the bootstrap activity note body."""
    return "".join(
        (
            "# Activity Snapshot\n\n"
            f"Generated at: `{generated_at}`\n\n"
            "No live platform activity refresh was executed by bootstrap. "
            "Run the research planner or maintenance refresh before activity-driven scheduling.\n",
        )
    )


def _activity_snapshot_metadata(path: Path, knowledge_root: Path, generated_at: str, body_text: str) -> dict[str, Any]:
    """Input: path, root, timestamp, body. Output: metadata dict. Build raw source metadata for bootstrap activity."""
    relative_path = path.relative_to(knowledge_root).as_posix()
    return {
        "source_type": "bootstrap_activity_snapshot",
        "source_family": "raw/platform/activities",
        "source_path": relative_path,
        "captured_at": generated_at,
        "capture_tool": "wqb.knowledge_bootstrap",
        "content_status": "raw_markdown",
        "record_count": 1,
        "content_hash": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
        "update_check": "rerun platform activity refresh or bootstrap",
        "compiled_targets": ["wiki/00_start_here.md"],
    }


def _upsert_activity_source_index(path: Path, knowledge_root: Path) -> Path:
    """Input: activity path and vault root. Output: index path. Ensure source-index coverage for activity raw note."""
    relative_path = path.relative_to(knowledge_root).as_posix()
    metadata = _activity_snapshot_metadata(
        path,
        knowledge_root,
        "1970-01-01T00:00:00+00:00",
        _activity_snapshot_body("1970-01-01T00:00:00+00:00"),
    )
    try:
        parsed, _ = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
        if parsed:
            metadata.update(parsed)
    except OSError:
        pass
    return upsert_source_index_rows(
        knowledge_root,
        [
            SourceIndexRow(
                path=relative_path,
                source_family="raw/platform/activities",
                source_type="bootstrap_activity_snapshot",
                contents="Bootstrap note certifying that no live activity refresh was executed.",
                update_check="rerun platform activity refresh or bootstrap",
                captured_at=str(metadata.get("captured_at", "")),
                record_count=int(metadata.get("record_count", 0) or 0),
                content_hash=str(metadata.get("content_hash", "")),
                content_status=str(metadata.get("content_status", "")),
                compiled_targets=["wiki/00_start_here.md"],
            )
        ],
    )


def _write_activity_snapshot(path: Path, knowledge_root: Path, generated_at: str) -> Path:
    """Input: output path, vault root, timestamp. Output: path. Write non-live activity raw note."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body_text = _activity_snapshot_body(generated_at)
    metadata = _activity_snapshot_metadata(path, knowledge_root, generated_at, body_text)
    path.write_text(
        render_front_matter(metadata) + body_text,
        encoding="utf-8",
    )
    _upsert_activity_source_index(path, knowledge_root)
    return path


def _ensure_activity_snapshot_contract(path: Path, knowledge_root: Path, generated_at: str) -> Path:
    """Input: activity path, root, timestamp. Output: path. Backfill raw metadata and source index."""
    if not path.exists():
        return _write_activity_snapshot(path, knowledge_root, generated_at)
    text = path.read_text(encoding="utf-8")
    metadata, body = parse_markdown_front_matter(text)
    body_text = body if metadata else text
    expected = _activity_snapshot_metadata(path, knowledge_root, generated_at, body_text)
    needs_metadata = any(metadata.get(field) in (None, "", []) for field in RAW_REQUIRED_FIELDS)
    managed_fields = (
        "source_type",
        "source_family",
        "source_path",
        "captured_at",
        "capture_tool",
        "content_status",
        "record_count",
        "content_hash",
        "update_check",
        "compiled_targets",
    )
    needs_managed_repair = any(metadata.get(field) != expected[field] for field in managed_fields)
    if needs_metadata or needs_managed_repair:
        path.write_text(render_front_matter(expected) + body_text, encoding="utf-8")
    _upsert_activity_source_index(path, knowledge_root)
    return path


def _bootstrap_report_path(root: Path, generated_at: str) -> Path:
    """Input: vault root and timestamp. Output: report path. Locate bootstrap maintenance evidence."""
    return root / BOOTSTRAP_REPORT_DIR / f"{generated_at[:10]}.json"


def _scaffold_manifest_row(
    name: str,
    artifact_path: Path,
    max_age_days: int,
    day: str,
    initialized_names: set[str],
) -> dict[str, Any]:
    """Input: artifact metadata and initialized names. Output: manifest row. Avoid certifying preserved artifacts."""
    if name in initialized_names:
        return {
            "name": name,
            "path": artifact_path.as_posix(),
            "updated_at": day,
            "max_age_days": max_age_days,
            "status": "refreshed",
        }
    return {
        "name": name,
        "path": artifact_path.as_posix(),
        "updated_at": NON_REFRESHED_BASELINE_DATE,
        "max_age_days": max_age_days,
        "status": "preserved",
        "source_note": "Bootstrap preserved the existing artifact and did not certify its freshness.",
    }


def _write_manifest(path: Path, generated_at: str, initialized_names: set[str]) -> Path:
    """Input: manifest path, timestamp, initialized names. Output: path. Write a conservative scaffold manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_manifest_rows(generated_at, initialized_names), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _manifest_rows(generated_at: str, initialized_names: set[str]) -> list[dict[str, Any]]:
    """Input: timestamp and initialized names. Output: manifest rows. Build canonical bootstrap manifest rows."""
    day = generated_at[:10]
    return [
        _scaffold_manifest_row("data_ledger", DATA_LEDGER_JSONL, 1, day, initialized_names),
        _scaffold_manifest_row("template_library", TEMPLATE_LIBRARY_JSONL, 7, day, initialized_names),
        {
            "name": "benchmark_rules",
            "path": BENCHMARK_RULES_PATH.as_posix(),
            "updated_at": NON_REFRESHED_BASELINE_DATE,
            "max_age_days": 7,
            "status": "not_refreshed",
            "source_note": "Bootstrap does not create or refresh benchmark rules.",
        },
        _scaffold_manifest_row("activity_snapshot", ACTIVITY_SNAPSHOT, 1, day, initialized_names),
        {
            "name": "operator_catalog",
            "path": OPERATOR_LEDGER.as_posix(),
            "updated_at": NON_REFRESHED_BASELINE_DATE,
            "max_age_days": 30,
            "status": "not_refreshed",
            "source_note": "Bootstrap does not create or refresh the official operator catalog.",
        },
        {
            "name": "research_option_cards",
            "path": "machine/decisions/research_option_cards.jsonl",
            "updated_at": NON_REFRESHED_BASELINE_DATE,
            "max_age_days": 7,
            "status": "not_refreshed",
            "source_note": "Bootstrap does not create or refresh research option cards.",
        },
    ]


def _normalize_existing_manifest(path: Path, generated_at: str, initialized_names: set[str]) -> Path:
    """Input: manifest path, timestamp, initialized names. Output: path. Normalize known artifact paths in place."""
    canonical_rows = _manifest_rows(generated_at, initialized_names)
    canonical_by_name = {row["name"]: row for row in canonical_rows}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = []
    existing_rows = payload if isinstance(payload, list) else []
    known_rows: dict[str, tuple[dict[str, Any], tuple[str, int]]] = {}
    unknown_rows: list[dict[str, Any]] = []
    for sequence, row in enumerate(existing_rows):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", ""))
        if name not in canonical_by_name:
            unknown_rows.append(dict(row))
            continue
        key = _manifest_preference_key(row, sequence)
        if key is not None and (name not in known_rows or key > known_rows[name][1]):
            known_rows[name] = (dict(row), key)
    normalized: list[dict[str, Any]] = []
    for canonical in canonical_rows:
        name = str(canonical["name"])
        if name not in known_rows:
            normalized.append(dict(canonical))
            continue
        copied = dict(canonical)
        copied.update(known_rows[name][0])
        copied["name"] = name
        copied["path"] = canonical["path"]
        if not isinstance(copied.get("max_age_days"), int) or int(copied.get("max_age_days", 0)) <= 0:
            copied["max_age_days"] = canonical["max_age_days"]
        normalized.append(copied)
    normalized.extend(unknown_rows)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _manifest_preference_key(row: dict[str, Any], sequence: int) -> tuple[str, int] | None:
    """Input: manifest row and position. Output: sort key or none. Prefer date-only freshness rows."""
    updated_at = str(row.get("updated_at", ""))
    try:
        date.fromisoformat(updated_at)
    except ValueError:
        return None
    return updated_at, sequence


def bootstrap_summary_to_dict(summary: BootstrapSummary) -> dict[str, Any]:
    """Input: BootstrapSummary. Output: dict. Convert bootstrap summary to JSON-safe data."""
    return asdict(summary)


def bootstrap_knowledge(knowledge_root: str | Path, seed_root: str | Path, generated_at: str | None = None) -> BootstrapSummary:
    """Input: knowledge root and seed root. Output: summary. Create only missing initial scaffold artifacts."""
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    root = Path(knowledge_root)
    seed = Path(seed_root)
    for name in ("raw", "machine", "wiki"):
        (root / name).mkdir(parents=True, exist_ok=True)
    ledger_rows = _stamp_rows(
        _read_jsonl(seed / "data_ledger.example.jsonl"),
        "schema_seed",
        "partial",
        normalize_coverage=True,
    )
    template_rows = _stamp_rows(_read_jsonl(seed / "template_library.example.jsonl"), "schema_seed", "partial")
    ledger_jsonl = machine_resource_path(root, DATA_LEDGER_RESOURCE)
    ledger_md = root / DATA_LEDGER_MD
    template_jsonl = machine_resource_path(root, TEMPLATE_LIBRARY_RESOURCE)
    template_md = root / TEMPLATE_LIBRARY_MD
    activity = root / ACTIVITY_SNAPSHOT
    manifest = machine_resource_path(root, FRESHNESS_MANIFEST_RESOURCE)
    report = _bootstrap_report_path(root, generated)
    initialized_names: set[str] = set()
    preserved_paths: list[str] = []

    if ledger_jsonl.exists():
        preserved_paths.append(str(ledger_jsonl))
    else:
        _write_jsonl(ledger_jsonl, ledger_rows)
        initialized_names.add("data_ledger")
    if ledger_md.exists():
        preserved_paths.append(str(ledger_md))
    else:
        write_data_ledger_markdown(ledger_md, load_data_ledger(ledger_jsonl), generated)

    if template_jsonl.exists():
        preserved_paths.append(str(template_jsonl))
    else:
        _write_jsonl(template_jsonl, template_rows)
        initialized_names.add("template_library")
    if template_md.exists():
        preserved_paths.append(str(template_md))
    else:
        write_template_library_markdown(template_md, load_template_library(template_jsonl), generated)

    if activity.exists():
        preserved_paths.append(str(activity))
        _ensure_activity_snapshot_contract(activity, root, generated)
    else:
        _write_activity_snapshot(activity, root, generated)
        initialized_names.add("activity_snapshot")
    if manifest.exists():
        preserved_paths.append(str(manifest))
        _normalize_existing_manifest(manifest, generated, initialized_names)
    else:
        _write_manifest(manifest, generated, initialized_names)

    actual_ledger_rows = _read_jsonl(ledger_jsonl)
    actual_template_rows = _read_jsonl(template_jsonl)
    non_refreshed = ["benchmark_rules", "operator_catalog", "research_option_cards"]
    warnings = ["The following required artifacts were not refreshed by bootstrap: " + ", ".join(non_refreshed) + "."]
    if {"data_ledger", "template_library"} & initialized_names:
        warnings.insert(0, "New data ledger or template library artifacts are schema-seeded and partial until platform metadata refresh runs.")
    if report.exists():
        preserved_paths.append(str(report))
    if preserved_paths:
        warnings.append("Preserved existing knowledge artifacts: " + ", ".join(preserved_paths) + ".")
    artifact_paths = [str(path) for path in [ledger_jsonl, ledger_md, template_jsonl, template_md, manifest, activity, report]]
    if not report.exists():
        report.parent.mkdir(parents=True, exist_ok=True)
        source_quality = "schema_seed" if {"data_ledger", "template_library"} <= initialized_names else "preserved_existing"
        refreshed = ", ".join(sorted(initialized_names)) or "none"
        report.write_text(
            json.dumps(
                {
                    "report_type": "knowledge_bootstrap",
                    "generated_at": generated,
                    "data_ledger_records": len(actual_ledger_rows),
                    "template_records": len(actual_template_rows),
                    "source_quality": source_quality,
                    "coverage_status": "partial",
                    "manifest_status": "partial",
                    "refreshed_artifacts": sorted(initialized_names),
                    "not_refreshed": non_refreshed,
                    "refreshed_label": refreshed,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    return BootstrapSummary(
        generated,
        str(root),
        len(actual_ledger_rows),
        len(actual_template_rows),
        artifact_paths,
        warnings,
    )
