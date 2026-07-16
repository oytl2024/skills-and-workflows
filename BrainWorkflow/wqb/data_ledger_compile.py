from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from wqb.data_field_capture import DATA_CAPTURE_LOCK_NAME
from wqb.data_ledger import DataLedgerRecord, data_ledger_record_to_dict, load_data_ledger, write_data_ledger_markdown
from wqb.lockfile import exclusive_json_lock
from wqb.semantics import field_semantic_embedding


RAW_CAPTURE_ROOT = Path("raw") / "platform" / "data_fields"
DATA_LEDGER_JSONL = Path("wiki") / "20_semantics" / "data_ledger.jsonl"
DATA_LEDGER_MD = Path("wiki") / "20_semantics" / "data_ledger.md"
FRESHNESS_MANIFEST = Path("wiki") / "80_maintenance" / "freshness_manifest.json"
COMPILE_LOCK_NAME = DATA_CAPTURE_LOCK_NAME
COMPILE_LOCK_TIMEOUT_SECONDS = 5.0
COMPILE_LOCK_SLEEP_SECONDS = 0.05
COMPILE_LOCK_STALE_SECONDS = 3600.0


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


def _read_jsonl(path: Path, strict_objects: bool = False) -> list[dict[str, Any]]:
    """Input: JSONL path and strict flag. Output: row list. Load capture rows and reject non-object compile input."""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
            elif strict_objects:
                raise ValueError(f"{path} line {line_number} must be a JSON object")
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


def _update_manifest(root: Path, source_day: str, compiled_at: str, output_path: Path | None = None) -> None:
    """Input: root, source day, compile timestamp, output path. Output: none. Stage ledger freshness from raw capture age."""
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
        "updated_at": source_day,
        "compiled_at": compiled_at,
        "max_age_days": 1,
        "status": "refreshed",
        "source_note": "Compiled from raw platform data-field captures.",
    }
    destination = output_path or manifest_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps([by_name[name] for name in sorted(by_name)], ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Input: output path and rows. Output: none. Write JSONL deterministically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _publish_staged_outputs(staged: list[tuple[Path, Path]]) -> None:
    """Input: staged and destination path pairs. Output: none. Publish all outputs or restore every prior destination."""
    previous = {destination: destination.read_bytes() if destination.exists() else None for _, destination in staged}
    try:
        for temporary, destination in staged:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(destination)
    except Exception:
        for _, destination in staged:
            content = previous[destination]
            if content is None:
                destination.unlink(missing_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
        raise


def _scope_key(scope: dict[str, Any]) -> tuple[str, str, int, str] | None:
    """Input: raw scope dict. Output: normalized key or none. Identify one captured platform scope safely."""
    try:
        key = (
            str(scope.get("instrument_type", "")).strip().upper(),
            str(scope.get("region", "")).strip().upper(),
            int(scope.get("delay")),
            str(scope.get("universe", "")).strip().upper(),
        )
    except (TypeError, ValueError):
        return None
    return key if key[0] and key[1] and key[2] >= 0 and key[3] else None


def _latest_scope_outcomes(capture_dir: Path) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    """Input: capture directory. Output: latest outcome row by scope. Read append-only capture scope outcomes."""
    outcomes: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for row in _read_jsonl(capture_dir / "scopes.jsonl"):
        scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
        key = _scope_key(scope)
        if key is not None:
            outcomes[key] = row
    return outcomes


def _capture_certification_complete(manifest: dict[str, Any]) -> bool:
    """Input: capture manifest. Output: bool. Decide whether limits permit measured coverage certification."""
    if not manifest:
        return False
    if "certification_status" in manifest:
        return manifest.get("certification_status") == "complete"
    limits = manifest.get("active_limits", {})
    if isinstance(limits, dict) and any(int(limits.get(name, 0) or 0) > 0 for name in ("max_scopes", "max_datasets_per_scope", "max_fields_per_dataset")):
        return False
    return manifest.get("status", "completed") == "completed"


def _capture_source_day(manifest: dict[str, Any], capture_dir: Path) -> str:
    """Input: capture manifest and directory. Output: yyyy-mm-dd. Preserve raw source age for freshness evaluation."""
    generated_at = str(manifest.get("generated_at", ""))
    if len(generated_at) >= 10 and generated_at[4:5] == "-" and generated_at[7:8] == "-":
        return generated_at[:10]
    return capture_dir.name[:10]


def _validate_raw_rows(rows: list[dict[str, Any]]) -> None:
    """Input: raw field rows. Output: none. Refuse malformed or empty raw input before staging outputs."""
    if not rows:
        raise ValueError("raw data fields contain no valid rows")
    for row in rows:
        field = row.get("field") if isinstance(row.get("field"), dict) else {}
        data_set = row.get("data_set") if isinstance(row.get("data_set"), dict) else {}
        if not str(field.get("id", "")).strip() or not str(data_set.get("id", "")).strip():
            raise ValueError("raw data fields contain a row without dataset_id or field_id")


def _record_from_group(root: Path, capture_path: Path, rows: list[dict[str, Any]], prior: DataLedgerRecord | None = None) -> dict[str, Any]:
    """Input: root, raw source path, grouped rows. Output: data ledger JSON row."""
    first = rows[0]
    field = first.get("field", {}) if isinstance(first.get("field"), dict) else {}
    data_set = first.get("data_set", {}) if isinstance(first.get("data_set"), dict) else {}
    scopes = [row.get("scope", {}) for row in rows if isinstance(row.get("scope"), dict)]
    valid_scope_keys = [key for scope in scopes if (key := _scope_key(scope)) is not None]
    exact_scopes = [
        {"instrument_type": instrument_type, "region": region, "delay": delay, "universe": universe}
        for instrument_type, region, delay, universe in sorted(set(valid_scope_keys))
    ]
    embedding = field_semantic_embedding({**field, "dataset": data_set})
    field_id = str(field.get("id", ""))
    field_type = str(field.get("type", ""))
    alpha_count = max(int(row.get("field", {}).get("alphaCount", 0) or 0) for row in rows)
    user_count = max(int(row.get("field", {}).get("userCount", row.get("field", {}).get("user_count", 0)) or 0) for row in rows)
    tags = sorted(set(embedding["tags"]) | {str(data_set.get("category", "")).lower()} - {""})
    regions = sorted({scope["region"] for scope in exact_scopes})
    delays = sorted({scope["delay"] for scope in exact_scopes})
    universes = sorted({scope["universe"] for scope in exact_scopes})
    primary_scope = exact_scopes[0] if exact_scopes else {}
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
            simulation_usage_count=prior.simulation_usage_count if prior else 0,
            submitted_usage_count=prior.submitted_usage_count if prior else 0,
            last_used_at=prior.last_used_at if prior else "",
            best_result_label=prior.best_result_label if prior else "unexplored_raw_candidate",
            correlation_risk=correlation_risk,
            source_paths=[_relative_source(root, capture_path)],
            available_regions=regions,
            available_delays=delays,
            available_universes=universes,
            available_scopes=exact_scopes,
            activity_tags=prior.activity_tags if prior else [],
            compatible_template_ids=_template_ids(field_type, tags),
            gate_requirements=["verify_platform_availability_before_live_run"],
            experiment_paths=prior.experiment_paths if prior else [],
            instrument_type=str(primary_scope.get("instrument_type", "")),
            date_coverage=str(field.get("dateCoverage", field.get("date_coverage", ""))),
            data_category=str(data_set.get("category", "")),
            crowding_risk=correlation_risk,
            known_operators=["rank", "ts_delta", "ts_zscore"],
            repair_usage_count=prior.repair_usage_count if prior else 0,
            field_description=str(field.get("description", "")),
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
    ledger_path = root / DATA_LEDGER_JSONL
    markdown_path = root / DATA_LEDGER_MD
    manifest_path = root / FRESHNESS_MANIFEST
    token = uuid4().hex
    ledger_tmp_path = ledger_path.with_name(f"{ledger_path.name}.{token}.tmp")
    markdown_tmp_path = markdown_path.with_name(f"{markdown_path.name}.{token}.tmp")
    manifest_tmp_path = manifest_path.with_name(f"{manifest_path.name}.{token}.tmp")
    tmp_paths = [ledger_tmp_path, markdown_tmp_path, manifest_tmp_path]
    with exclusive_json_lock(
        root / COMPILE_LOCK_NAME,
        COMPILE_LOCK_TIMEOUT_SECONDS,
        COMPILE_LOCK_SLEEP_SECONDS,
        COMPILE_LOCK_STALE_SECONDS,
        "data ledger compile lock is busy",
    ):
        try:
            fields_path = selected_capture / "data_fields.jsonl"
            manifest = _read_json(selected_capture / "manifest.json")
            rows = _read_jsonl(fields_path, strict_objects=True)
            _validate_raw_rows(rows)
            grouped: dict[tuple[str, str, tuple[str, str, int, str] | None], list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                field = row.get("field", {}) if isinstance(row.get("field"), dict) else {}
                data_set = row.get("data_set", {}) if isinstance(row.get("data_set"), dict) else {}
                scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
                grouped[(str(data_set.get("id", "")), str(field.get("id", "")), _scope_key(scope))].append(row)
            if not grouped:
                raise ValueError("raw data fields contain no valid rows")

            certification_complete = _capture_certification_complete(manifest)
            scope_outcomes = _latest_scope_outcomes(selected_capture)
            source_day = _capture_source_day(manifest, selected_capture)
            prior_records = {(record.dataset_id, record.field_id): record for record in load_data_ledger(ledger_path)}
            output_rows = []
            for key in sorted(grouped, key=repr):
                row_scope_keys = [
                    _scope_key(row.get("scope")) if isinstance(row.get("scope"), dict) else None
                    for row in grouped[key]
                ]
                measured = certification_complete and all(
                    scope_key is not None
                    and (outcome := scope_outcomes.get(scope_key)) is not None
                    and outcome.get("status") == "completed"
                    and outcome.get("certification_status") == "complete"
                    for scope_key in row_scope_keys
                )
                output_rows.append(_record_from_group(root, fields_path, grouped[key], prior_records.get(key[:2])) | {"coverage_status": "measured_raw" if measured else "partial"})
            if not output_rows:
                raise ValueError("raw data fields contain no valid rows")
            _write_jsonl(ledger_tmp_path, output_rows)
            records = load_data_ledger(ledger_tmp_path)
            write_data_ledger_markdown(markdown_tmp_path, records, generated)
            _update_manifest(root, source_day, generated, manifest_tmp_path)

            _publish_staged_outputs([(ledger_tmp_path, ledger_path), (markdown_tmp_path, markdown_path), (manifest_tmp_path, manifest_path)])
        finally:
            for path in tmp_paths:
                path.unlink(missing_ok=True)
    return {
        "generated_at": generated,
        "capture_dir": str(selected_capture),
        "ledger_path": str(ledger_path),
        "markdown_path": str(markdown_path),
        "record_count": len(records),
        "source_status": "complete" if certification_complete else "partial",
    }
