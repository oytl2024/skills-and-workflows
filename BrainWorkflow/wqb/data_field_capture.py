from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from wqb.data_catalog import fetch_data_fields_with_metadata, fetch_data_sets_with_metadata, fetch_operators
from wqb.lockfile import exclusive_json_lock


DEFAULT_CAPTURE_INSTRUMENT_TYPES = ("EQUITY",)
DEFAULT_CAPTURE_REGIONS = ("USA", "EUR", "ASI", "GLB")
DEFAULT_CAPTURE_DELAYS = (0, 1)
DEFAULT_CAPTURE_UNIVERSES = ("TOP3000", "TOP2000", "TOP1000", "TOP500", "TOP200")
RAW_CAPTURE_ROOT = Path("raw") / "platform" / "data_fields"
SAFE_PAGE_LIMIT = 50
DATA_CAPTURE_LOCK_NAME = ".data_capture_compile.lock"
DATA_CAPTURE_LOCK_TIMEOUT_SECONDS = 5.0
DATA_CAPTURE_LOCK_SLEEP_SECONDS = 0.05
DATA_CAPTURE_LOCK_STALE_SECONDS = 3600.0


@dataclass(frozen=True)
class CaptureScope:
    instrument_type: str
    region: str
    delay: int
    universe: str


def _now() -> str:
    """Input: none. Output: str. Return a UTC timestamp for data capture records."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _capture_day(generated_at: str) -> str:
    """Input: timestamp. Output: yyyy-mm-dd str. Choose the raw capture directory date."""
    return generated_at[:10]


def build_capture_scopes(
    instrument_types: list[str] | None = None,
    regions: list[str] | None = None,
    delays: list[int] | None = None,
    universes: list[str] | None = None,
    max_scopes: int = 0,
) -> list[CaptureScope]:
    """Input: optional scope lists. Output: CaptureScope list. Expand the platform data-field capture matrix."""
    selected_instruments = instrument_types or list(DEFAULT_CAPTURE_INSTRUMENT_TYPES)
    selected_regions = regions or list(DEFAULT_CAPTURE_REGIONS)
    selected_delays = delays or list(DEFAULT_CAPTURE_DELAYS)
    selected_universes = universes or list(DEFAULT_CAPTURE_UNIVERSES)
    scopes = [
        CaptureScope(str(instrument), str(region), int(delay), str(universe))
        for instrument in selected_instruments
        for region in selected_regions
        for delay in selected_delays
        for universe in selected_universes
    ]
    if max_scopes > 0:
        return scopes[: int(max_scopes)]
    return scopes


def _write_json(path: Path, payload: Any) -> None:
    """Input: path and payload. Output: none. Write stable JSON for raw capture artifacts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """Input: path and row. Output: none. Append one JSONL row for resumable raw capture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _clear_outputs(capture_dir: Path) -> None:
    """Input: capture directory. Output: none. Start a clean raw capture when resume is disabled."""
    for name in ("scopes.jsonl", "data_sets.jsonl", "data_fields.jsonl", "errors.jsonl"):
        path = capture_dir / name
        if path.exists():
            path.unlink()


def _completed_scope_keys(capture_dir: Path) -> set[tuple[str, str, int, str]]:
    """Input: capture directory and requested certification status. Output: reusable scope keys. Skip only fully certified completed scopes."""
    return {
        key
        for key, row in _latest_scope_rows(capture_dir).items()
        if row.get("status") == "completed" and row.get("certification_status") == "complete"
    }


def _scope_key(scope: CaptureScope | dict[str, Any]) -> tuple[str, str, int, str]:
    """Input: CaptureScope or scope dict. Output: stable scope key tuple. Normalize a persisted capture scope key."""
    if isinstance(scope, CaptureScope):
        key = scope.instrument_type, scope.region, int(scope.delay), scope.universe
    else:
        key = str(scope["instrument_type"]), str(scope["region"]), int(scope["delay"]), str(scope["universe"])
    if not key[0].strip() or not key[1].strip() or key[2] < 0 or not key[3].strip():
        raise ValueError("capture scope must include instrument_type, region, non-negative delay, and universe")
    return key


def _latest_scope_rows(capture_dir: Path) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    """Input: capture directory. Output: latest row per scope. Resolve resumable scope state from append-only JSONL."""
    path = capture_dir / "scopes.jsonl"
    latest: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    if not path.exists():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            scope = row.get("scope", {}) if isinstance(row, dict) else {}
            if not isinstance(scope, dict):
                continue
            latest[_scope_key(scope)] = row
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return latest


def _unresolved_scope_error_count(scope_rows: list[dict[str, Any]]) -> int:
    """Input: latest non-completed scope rows. Output: unresolved error count. Count only current scope failures."""
    count = 0
    for row in scope_rows:
        try:
            count += max(1, int(row.get("error_count", 1)))
        except (TypeError, ValueError):
            count += 1
    return count


def _jsonl_row_count(path: Path) -> int:
    """Input: JSONL path. Output: row count. Count persisted non-empty capture rows for resume summaries."""
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _scope_dict(scope: CaptureScope) -> dict[str, Any]:
    """Input: CaptureScope. Output: dict. Convert scope to a JSON-safe row."""
    return asdict(scope)


def _error_row(scope: CaptureScope | None, endpoint: str, error: Exception, generated_at: str) -> dict[str, Any]:
    """Input: scope, endpoint, error, timestamp. Output: JSON row. Preserve recoverable capture failures."""
    return {
        "generated_at": generated_at,
        "scope": _scope_dict(scope) if scope is not None else {},
        "endpoint": endpoint,
        "message": str(error),
        "error_type": type(error).__name__,
    }


def _write_index(capture_dir: Path, summary: dict[str, Any]) -> None:
    """Input: capture dir and summary. Output: none. Write the human-readable raw capture index."""
    lines = [
        "# Platform Data Field Capture",
        "",
        f"Generated at: `{summary['generated_at']}`",
        "",
        f"- Scope Count: `{summary['scope_count']}`",
        f"- Dataset Count: `{summary['data_set_count']}`",
        f"- Field Count: `{summary['field_count']}`",
        f"- Error Count: `{summary['error_count']}`",
        f"- Capture Status: `{summary['status']}`",
        "",
        "Next command:",
        "",
        "```powershell",
        "python -m wqb.cli compile-data-ledger --knowledge-root <knowledge-root>",
        "```",
    ]
    (capture_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def capture_platform_data_fields(
    client: Any,
    knowledge_root: str | Path,
    generated_at: str | None = None,
    instrument_types: list[str] | None = None,
    regions: list[str] | None = None,
    delays: list[int] | None = None,
    universes: list[str] | None = None,
    max_scopes: int = 0,
    max_datasets_per_scope: int = 0,
    max_fields_per_dataset: int = 0,
    resume_capture: bool = False,
    capture_plan_path: str | Path | None = None,
    fields_per_scope: int = 0,
) -> dict[str, Any]:
    """Input: client, vault root, scope filters, limits. Output: summary dict. Capture platform data fields into raw."""
    root = Path(knowledge_root)
    with exclusive_json_lock(
        root / DATA_CAPTURE_LOCK_NAME,
        DATA_CAPTURE_LOCK_TIMEOUT_SECONDS,
        DATA_CAPTURE_LOCK_SLEEP_SECONDS,
        DATA_CAPTURE_LOCK_STALE_SECONDS,
        "data capture lock is busy",
    ):
        return _capture_platform_data_fields_locked(
            client, knowledge_root, generated_at, instrument_types, regions, delays, universes,
            max_scopes, max_datasets_per_scope, max_fields_per_dataset, resume_capture,
            capture_plan_path, fields_per_scope,
        )


def _capture_platform_data_fields_locked(
    client: Any,
    knowledge_root: str | Path,
    generated_at: str | None = None,
    instrument_types: list[str] | None = None,
    regions: list[str] | None = None,
    delays: list[int] | None = None,
    universes: list[str] | None = None,
    max_scopes: int = 0,
    max_datasets_per_scope: int = 0,
    max_fields_per_dataset: int = 0,
    resume_capture: bool = False,
    capture_plan_path: str | Path | None = None,
    fields_per_scope: int = 0,
) -> dict[str, Any]:
    """Input: capture settings while holding the shared lock. Output: summary dict. Write one non-interleaved raw generation."""
    generated = generated_at or _now()
    root = Path(knowledge_root)
    capture_generation_id = uuid4().hex
    capture_dir = root / RAW_CAPTURE_ROOT / _capture_day(generated)
    capture_dir.mkdir(parents=True, exist_ok=True)
    if not resume_capture:
        _clear_outputs(capture_dir)
    certification_complete = not any(
        limit > 0 for limit in (max_scopes, max_datasets_per_scope, max_fields_per_dataset, fields_per_scope)
    ) and capture_plan_path is None
    completed_scopes = _completed_scope_keys(capture_dir) if resume_capture else set()

    def append(name: str, row: dict[str, Any]) -> None:
        """Input: artifact name and row. Output: none. Append one row tagged with this capture generation."""
        _append_jsonl(capture_dir / name, {**row, "capture_generation_id": capture_generation_id})

    operators: list[dict[str, Any]] = []
    operator_fetch_succeeded = True
    try:
        operators = fetch_operators(client)
        _write_json(capture_dir / "operators.json", {"generated_at": generated, "operators": operators})
    except Exception as error:
        operator_fetch_succeeded = False
        append("errors.jsonl", _error_row(None, "/operators", error, generated))
        _write_json(capture_dir / "operators.json", {"generated_at": generated, "operators": []})

    requested_scopes = build_capture_scopes(instrument_types, regions, delays, universes)
    plan_rows: list[dict[str, Any]] = []
    if capture_plan_path is not None:
        from wqb.data_capture_plan import load_capture_plan

        plan_rows = load_capture_plan(capture_plan_path)
        scopes = [
            CaptureScope(*_scope_key(row))
            for row in plan_rows
        ]
        requested_scopes = list(scopes)
    else:
        scopes = requested_scopes[: int(max_scopes)] if max_scopes > 0 else requested_scopes
    plan_by_key = {_scope_key(row): row for row in plan_rows}
    for scope in scopes:
        if _scope_key(scope) in completed_scopes:
            continue
        plan_row = plan_by_key.get(_scope_key(scope), {})
        field_budget = int(plan_row.get("field_budget", fields_per_scope)) if fields_per_scope > 0 else 0
        sampling_mode = "stratified" if fields_per_scope > 0 or capture_plan_path else "full_scope"
        scope_row = {
            "generated_at": generated,
            "scope": _scope_dict(scope),
            "status": "started",
            "sampling_mode": sampling_mode,
            "field_budget": field_budget,
        }
        append("scopes.jsonl", scope_row)
        try:
            data_sets, data_sets_truncated = fetch_data_sets_with_metadata(
                client,
                scope.instrument_type,
                scope.region,
                int(scope.delay),
                scope.universe,
                limit=SAFE_PAGE_LIMIT,
            )
            if max_datasets_per_scope > 0:
                data_sets = data_sets[: int(max_datasets_per_scope)]
        except Exception as error:
            scope_row.update({"status": "failed", "data_set_count": 0, "message": str(error), "certification_status": "partial"})
            append("scopes.jsonl", scope_row)
            append("errors.jsonl", _error_row(scope, "/data-sets", error, generated))
            continue

        field_errors: list[str] = []
        if data_sets_truncated and max_datasets_per_scope == 0:
            error = ValueError("data-set pagination truncated at implicit cap")
            append("errors.jsonl", _error_row(scope, "/data-sets", error, generated))
            field_errors.append(str(error))
        remaining_scope_budget = field_budget
        for data_set in data_sets:
            if remaining_scope_budget == 0 and fields_per_scope > 0:
                break
            dataset_id = str(data_set.get("id", ""))
            append(
                "data_sets.jsonl",
                {"generated_at": generated, "scope": _scope_dict(scope), "data_set": data_set},
            )
            if not dataset_id:
                error = ValueError("missing dataset id")
                append("errors.jsonl", _error_row(scope, "/data-sets", error, generated))
                field_errors.append(str(error))
                continue
            try:
                fields, fields_truncated = fetch_data_fields_with_metadata(
                    client,
                    scope.instrument_type,
                    scope.region,
                    int(scope.delay),
                    scope.universe,
                    dataset_id=dataset_id,
                    limit=SAFE_PAGE_LIMIT,
                    max_records=(
                        min(max(remaining_scope_budget, 1), SAFE_PAGE_LIMIT)
                        if fields_per_scope > 0
                        else max_fields_per_dataset if max_fields_per_dataset > 0 else 1000000
                    ),
                )
            except Exception as error:
                append("errors.jsonl", _error_row(scope, f"/data-fields?dataset.id={dataset_id}", error, generated))
                field_errors.append(str(error))
                continue
            if fields_per_scope > 0:
                remaining_scope_budget = max(0, remaining_scope_budget - len(fields))
            if fields_truncated and max_fields_per_dataset == 0 and fields_per_scope == 0:
                error = ValueError(f"data-field pagination truncated at implicit cap for dataset {dataset_id}")
                append("errors.jsonl", _error_row(scope, f"/data-fields?dataset.id={dataset_id}", error, generated))
                field_errors.append(str(error))
            for field in fields:
                append(
                    "data_fields.jsonl",
                    {
                        "generated_at": generated,
                        "scope": _scope_dict(scope),
                        "data_set": data_set,
                        "field": field,
                        "endpoint": "/data-fields",
                    },
                )
        if field_errors:
            scope_row.update({"status": "partial", "data_set_count": len(data_sets), "error_count": len(field_errors), "message": "; ".join(field_errors), "certification_status": "partial"})
        else:
            scope_row.update({
                "status": "completed",
                "data_set_count": len(data_sets),
                "certification_status": "partial" if fields_per_scope > 0 or capture_plan_path else "complete" if certification_complete else "partial",
            })
        append("scopes.jsonl", scope_row)

    latest_scope_rows = _latest_scope_rows(capture_dir)
    all_requested_scopes_certified = bool(requested_scopes) and all(
        (latest := latest_scope_rows.get(_scope_key(scope))) is not None
        and latest.get("status") == "completed"
        and latest.get("certification_status") == "complete"
        for scope in requested_scopes
    )
    unresolved_scope_rows = [
        latest_scope_rows.get(_scope_key(scope), {})
        for scope in scopes
        if latest_scope_rows.get(_scope_key(scope), {}).get("status") != "completed"
    ]
    error_count = _unresolved_scope_error_count(unresolved_scope_rows) + (0 if operator_fetch_succeeded else 1)
    summary = {
        "generated_at": generated,
        "capture_generation_id": capture_generation_id,
        "capture_dir": str(capture_dir),
        "scope_count": len(latest_scope_rows),
        "scope_event_count": _jsonl_row_count(capture_dir / "scopes.jsonl"),
        "operator_count": len(operators),
        "data_set_count": _jsonl_row_count(capture_dir / "data_sets.jsonl"),
        "field_count": _jsonl_row_count(capture_dir / "data_fields.jsonl"),
        "error_count": error_count,
        "status": "completed" if error_count == 0 else "completed_with_warnings",
        "requested_matrix": [_scope_dict(scope) for scope in requested_scopes],
        "active_limits": {
            "max_scopes": int(max_scopes),
            "max_datasets_per_scope": int(max_datasets_per_scope),
            "max_fields_per_dataset": int(max_fields_per_dataset),
        },
        "fields_per_scope": int(fields_per_scope),
        "capture_plan_path": str(capture_plan_path or ""),
        "latest_scope_outcomes": [latest_scope_rows[key] for key in sorted(latest_scope_rows)],
        "certification_status": "complete" if all_requested_scopes_certified else "partial",
    }
    _write_json(capture_dir / "manifest.json", summary)
    errors_path = capture_dir / "errors.jsonl"
    if not errors_path.exists():
        errors_path.write_text("", encoding="utf-8")
    _write_index(capture_dir, summary)
    return summary
