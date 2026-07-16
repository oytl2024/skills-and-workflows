from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.data_ledger import DataLedgerRecord, data_ledger_record_to_dict, load_data_ledger, write_data_ledger_markdown
from wqb.semantics import field_semantic_embedding


RAW_CAPTURE_ROOT = Path("raw") / "platform" / "data_fields"
DATA_LEDGER_JSONL = Path("wiki") / "20_semantics" / "data_ledger.jsonl"
DATA_LEDGER_MD = Path("wiki") / "20_semantics" / "data_ledger.md"
FRESHNESS_MANIFEST = Path("wiki") / "80_maintenance" / "freshness_manifest.json"


def _now() -> str:
    """Input: none. Output: str. Return UTC timestamp for compile records."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def latest_capture_dir(knowledge_root: str | Path) -> Path:
    """Input: knowledge root. Output: Path. Return newest raw platform data-field capture directory."""
    root = Path(knowledge_root) / RAW_CAPTURE_ROOT
    candidates = [path for path in root.glob("*") if path.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"no platform data-field captures found under {root}")
    return sorted(candidates)[-1]


def _read_json(path: Path) -> dict[str, Any]:
    """Input: JSON path. Output: dict. Read optional JSON capture metadata."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: row list. Load raw capture rows."""
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _relative_source(root: Path, path: Path) -> str:
    """Input: root and path. Output: portable source path string."""
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _risk_from_counts(alpha_count: int, user_count: int) -> str:
    """Input: alpha and user counts. Output: risk label string."""
    crowded = max(alpha_count, user_count)
    if crowded >= 50:
        return "high"
    if crowded >= 10:
        return "medium"
    return "low"


def _template_ids(field_type: str, tags: list[str]) -> list[str]:
    """Input: field type and tags. Output: compatible template id hints."""
    if field_type.upper() == "VECTOR":
        return ["vector_event_count_surprise", "vector_event_value_surprise"]
    if set(tags) & {"cash", "cashflow", "asset_strength", "profitability", "growth"}:
        return ["matrix_fast_delta_rank", "matrix_ts_zscore_rank"]
    return ["matrix_ts_zscore_rank"]


def _update_manifest(root: Path, generated_at: str) -> None:
    """Input: knowledge root and timestamp. Output: none. Mark ledger freshness after compile."""
    manifest_path = root / FRESHNESS_MANIFEST
    rows: list[dict[str, Any]] = []
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            rows = [row for row in payload if isinstance(row, dict)]
    by_name = {str(row.get("name", "")): row for row in rows}
    by_name["data_ledger"] = {
        "name": "data_ledger",
        "path": str(DATA_LEDGER_JSONL).replace("\\", "/"),
        "updated_at": generated_at[:10],
        "max_age_days": 1,
        "status": "refreshed",
        "source_note": "Compiled from raw platform data-field captures.",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps([by_name[name] for name in sorted(by_name)], ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Input: output path and rows. Output: none. Write JSONL deterministically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _record_from_group(root: Path, capture_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Input: root, raw source path, grouped rows. Output: data ledger JSON row."""
    first = rows[0]
    field = first.get("field", {}) if isinstance(first.get("field"), dict) else {}
    data_set = first.get("data_set", {}) if isinstance(first.get("data_set"), dict) else {}
    scopes = [row.get("scope", {}) for row in rows if isinstance(row.get("scope"), dict)]
    embedding = field_semantic_embedding({**field, "dataset": data_set})
    field_id = str(field.get("id", ""))
    field_type = str(field.get("type", ""))
    alpha_count = max(int(row.get("field", {}).get("alphaCount", 0) or 0) for row in rows)
    user_count = max(int(row.get("field", {}).get("userCount", row.get("field", {}).get("user_count", 0)) or 0) for row in rows)
    tags = sorted(set(embedding["tags"]) | {str(data_set.get("category", "")).lower()} - {""})
    regions = sorted({str(scope.get("region", "")) for scope in scopes if scope.get("region")})
    delays = sorted({int(scope.get("delay", 0)) for scope in scopes})
    universes = sorted({str(scope.get("universe", "")) for scope in scopes if scope.get("universe")})
    primary_scope = scopes[0] if scopes else {}
    coverage_values = [float(row.get("field", {}).get("coverage", 0.0) or 0.0) for row in rows]
    coverage = max(coverage_values) if coverage_values else 0.0
    correlation_risk = _risk_from_counts(alpha_count, user_count)
    return data_ledger_record_to_dict(
        DataLedgerRecord(
            dataset_id=str(data_set.get("id", embedding.get("dataset_id", ""))),
            dataset_name=str(data_set.get("name", "")),
            field_id=field_id,
            field_type=field_type,
            region=str(primary_scope.get("region", "")),
            delay=int(primary_scope.get("delay", 0)),
            universe=str(primary_scope.get("universe", "")),
            semantic_tags=tags,
            coverage=coverage,
            alpha_count=alpha_count,
            user_count=user_count,
            simulation_usage_count=0,
            submitted_usage_count=0,
            last_used_at="",
            best_result_label="unexplored_raw_candidate",
            correlation_risk=correlation_risk,
            source_paths=[_relative_source(root, capture_path)],
            available_regions=regions,
            available_delays=delays,
            available_universes=universes,
            activity_tags=[],
            compatible_template_ids=_template_ids(field_type, tags),
            gate_requirements=["verify_platform_availability_before_live_run"],
            experiment_paths=[],
            instrument_type=str(primary_scope.get("instrument_type", "")),
            date_coverage=str(field.get("dateCoverage", field.get("date_coverage", ""))),
            data_category=str(data_set.get("category", "")),
            crowding_risk=correlation_risk,
            known_operators=["rank", "ts_delta", "ts_zscore"],
            repair_usage_count=0,
        )
    ) | {"source_quality": "platform_raw_capture", "coverage_status": "measured_raw"}


def compile_data_ledger_from_raw(
    knowledge_root: str | Path,
    capture_dir: str | Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Input: vault root and optional capture dir. Output: summary dict. Compile data ledger from raw captures."""
    generated = generated_at or _now()
    root = Path(knowledge_root)
    selected_capture = Path(capture_dir) if capture_dir is not None else latest_capture_dir(root)
    fields_path = selected_capture / "data_fields.jsonl"
    manifest = _read_json(selected_capture / "manifest.json")
    rows = _read_jsonl(fields_path)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        field = row.get("field", {}) if isinstance(row.get("field"), dict) else {}
        data_set = row.get("data_set", {}) if isinstance(row.get("data_set"), dict) else {}
        field_id = str(field.get("id", ""))
        dataset_id = str(data_set.get("id", ""))
        if field_id:
            grouped[(dataset_id, field_id)].append(row)

    output_rows = [_record_from_group(root, fields_path, grouped[key]) for key in sorted(grouped)]
    ledger_path = root / DATA_LEDGER_JSONL
    markdown_path = root / DATA_LEDGER_MD
    tmp_path = ledger_path.with_suffix(".jsonl.tmp")
    _write_jsonl(tmp_path, output_rows)
    records = load_data_ledger(tmp_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.replace(ledger_path)
    write_data_ledger_markdown(markdown_path, records, generated)
    _update_manifest(root, generated)
    partial = str(manifest.get("status", "")) != "completed"
    return {
        "generated_at": generated,
        "capture_dir": str(selected_capture),
        "ledger_path": str(ledger_path),
        "markdown_path": str(markdown_path),
        "record_count": len(records),
        "source_status": "partial" if partial else "complete",
    }
