from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.data_ledger import load_data_ledger, write_data_ledger_markdown
from wqb.template_library import load_template_library, write_template_library_markdown


DATA_LEDGER_JSONL = Path("wiki") / "20_semantics" / "data_ledger.jsonl"
DATA_LEDGER_MD = Path("wiki") / "20_semantics" / "data_ledger.md"
TEMPLATE_LIBRARY_JSONL = Path("wiki") / "30_templates" / "template_library.jsonl"
TEMPLATE_LIBRARY_MD = Path("wiki") / "30_templates" / "template_library.md"
FRESHNESS_MANIFEST = Path("wiki") / "80_maintenance" / "freshness_manifest.json"
BOOTSTRAP_REPORT = Path("wiki") / "80_maintenance" / "bootstrap_report.md"
ACTIVITY_SNAPSHOT = Path("wiki") / "10_foundations" / "activity_snapshot.md"


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


def _stamp_rows(rows: list[dict[str, Any]], source_quality: str, coverage_status: str) -> list[dict[str, Any]]:
    """Input: rows and labels. Output: copied rows with source labels."""
    stamped = []
    for row in rows:
        copied = dict(row)
        copied["source_quality"] = source_quality
        copied["coverage_status"] = coverage_status
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


def _write_manifest(path: Path, generated_at: str) -> Path:
    """Input: manifest path and timestamp. Output: path. Write required freshness manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    day = generated_at[:10]
    rows = [
        {"name": "data_ledger", "path": str(DATA_LEDGER_JSONL).replace("\\", "/"), "updated_at": day, "max_age_days": 1},
        {"name": "template_library", "path": str(TEMPLATE_LIBRARY_JSONL).replace("\\", "/"), "updated_at": day, "max_age_days": 7},
        {"name": "benchmark_rules", "path": "wiki/50_benchmarks/correlation_and_novelty.md", "updated_at": day, "max_age_days": 7},
        {"name": "activity_snapshot", "path": str(ACTIVITY_SNAPSHOT).replace("\\", "/"), "updated_at": day, "max_age_days": 1},
        {"name": "operator_catalog", "path": "wiki/20_semantics/operator_catalog_official.md", "updated_at": day, "max_age_days": 30},
        {"name": "research_option_cards", "path": "wiki/70_decisions/research_option_cards.jsonl", "updated_at": day, "max_age_days": 7},
    ]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def bootstrap_summary_to_dict(summary: BootstrapSummary) -> dict[str, Any]:
    """Input: BootstrapSummary. Output: dict. Convert bootstrap summary to JSON-safe data."""
    return asdict(summary)


def bootstrap_knowledge(knowledge_root: str | Path, seed_root: str | Path, generated_at: str | None = None) -> BootstrapSummary:
    """Input: knowledge root and seed root. Output: summary. Materialize formal knowledge artifacts."""
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    root = Path(knowledge_root)
    seed = Path(seed_root)
    ledger_rows = _stamp_rows(_read_jsonl(seed / "data_ledger.example.jsonl"), "schema_seed", "partial")
    template_rows = _stamp_rows(_read_jsonl(seed / "template_library.example.jsonl"), "schema_seed", "partial")
    ledger_jsonl = _write_jsonl(root / DATA_LEDGER_JSONL, ledger_rows)
    template_jsonl = _write_jsonl(root / TEMPLATE_LIBRARY_JSONL, template_rows)
    ledger_md = write_data_ledger_markdown(root / DATA_LEDGER_MD, load_data_ledger(ledger_jsonl), generated)
    template_md = write_template_library_markdown(root / TEMPLATE_LIBRARY_MD, load_template_library(template_jsonl), generated)
    activity = _write_activity_snapshot(root / ACTIVITY_SNAPSHOT, generated)
    manifest = _write_manifest(root / FRESHNESS_MANIFEST, generated)
    report = root / BOOTSTRAP_REPORT
    report.parent.mkdir(parents=True, exist_ok=True)
    warnings = ["Data ledger is schema-seeded and partial until platform metadata refresh runs."]
    artifact_paths = [str(path) for path in [ledger_jsonl, ledger_md, template_jsonl, template_md, manifest, activity, report]]
    report.write_text(
        "# Knowledge Bootstrap Report\n\n"
        f"Generated at: `{generated}`\n\n"
        f"- Data Ledger Records: {len(ledger_rows)}\n"
        f"- Template Records: {len(template_rows)}\n"
        "- Source Quality: `schema_seed`\n"
        "- Coverage Status: `partial`\n",
        encoding="utf-8",
    )
    return BootstrapSummary(generated, str(root), len(ledger_rows), len(template_rows), artifact_paths, warnings)
