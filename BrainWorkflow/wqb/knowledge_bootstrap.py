from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.benchmark_rules import BENCHMARK_RULES_PATH
from wqb.data_ledger import load_data_ledger, write_data_ledger_markdown
from wqb.knowledge_paths import machine_resource_path
from wqb.template_library import load_template_library, write_template_library_markdown


DATA_LEDGER_RESOURCE = "data_ledger"
TEMPLATE_LIBRARY_RESOURCE = "template_library"
FRESHNESS_MANIFEST_RESOURCE = "freshness_manifest"
DATA_LEDGER_JSONL = Path("machine") / "data_ledger.jsonl"
DATA_LEDGER_MD = Path("wiki") / "20_semantics" / "data_ledger.md"
TEMPLATE_LIBRARY_JSONL = Path("machine") / "template_library.jsonl"
TEMPLATE_LIBRARY_MD = Path("wiki") / "30_templates" / "template_library.md"
FRESHNESS_MANIFEST = Path("machine") / "freshness_manifest.json"
BOOTSTRAP_REPORT = Path("wiki") / "80_maintenance" / "bootstrap_report.md"
ACTIVITY_SNAPSHOT = Path("wiki") / "10_foundations" / "activity_snapshot.md"
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


def _write_activity_snapshot(path: Path, generated_at: str) -> Path:
    """Input: output path and timestamp. Output: path. Write non-live activity snapshot note."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Activity Snapshot\n\n"
        f"Generated at: `{generated_at}`\n\n"
        "No live platform activity refresh was executed by bootstrap. "
        "Run the research planner or maintenance refresh before activity-driven scheduling.\n",
        encoding="utf-8",
    )
    return path


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
    day = generated_at[:10]
    rows = [
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
            "path": "wiki/20_semantics/operator_catalog_official.md",
            "updated_at": NON_REFRESHED_BASELINE_DATE,
            "max_age_days": 30,
            "status": "not_refreshed",
            "source_note": "Bootstrap does not create or refresh the official operator catalog.",
        },
        {
            "name": "research_option_cards",
            "path": "wiki/70_decisions/research_option_cards.jsonl",
            "updated_at": NON_REFRESHED_BASELINE_DATE,
            "max_age_days": 7,
            "status": "not_refreshed",
            "source_note": "Bootstrap does not create or refresh research option cards.",
        },
    ]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def bootstrap_summary_to_dict(summary: BootstrapSummary) -> dict[str, Any]:
    """Input: BootstrapSummary. Output: dict. Convert bootstrap summary to JSON-safe data."""
    return asdict(summary)


def bootstrap_knowledge(knowledge_root: str | Path, seed_root: str | Path, generated_at: str | None = None) -> BootstrapSummary:
    """Input: knowledge root and seed root. Output: summary. Create only missing initial scaffold artifacts."""
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    root = Path(knowledge_root)
    seed = Path(seed_root)
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
    report = root / BOOTSTRAP_REPORT
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
    else:
        _write_activity_snapshot(activity, generated)
        initialized_names.add("activity_snapshot")
    if manifest.exists():
        preserved_paths.append(str(manifest))
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
            "# Knowledge Bootstrap Report\n\n"
            f"Generated at: `{generated}`\n\n"
            f"- Data Ledger Records: {len(actual_ledger_rows)}\n"
            f"- Template Records: {len(actual_template_rows)}\n"
            f"- Source Quality: `{source_quality}`\n"
            "- Coverage Status: `partial`\n"
            "- Manifest Status: `partial`\n"
            f"- Refreshed Artifacts: `{refreshed}`\n"
            "- Not Refreshed (stale baseline): `benchmark_rules`, `operator_catalog`, `research_option_cards`\n",
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
