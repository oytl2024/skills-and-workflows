from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.data_catalog import fetch_data_fields, fetch_data_sets, fetch_operators


DEFAULT_CAPTURE_INSTRUMENT_TYPES = ("EQUITY",)
DEFAULT_CAPTURE_REGIONS = ("USA", "EUR", "ASI", "GLB")
DEFAULT_CAPTURE_DELAYS = (0, 1)
DEFAULT_CAPTURE_UNIVERSES = ("TOP3000", "TOP2000", "TOP1000", "TOP500", "TOP200")
RAW_CAPTURE_ROOT = Path("raw") / "platform" / "data_fields"
SAFE_PAGE_LIMIT = 50


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
    """Input: capture directory. Output: completed scope keys. Read resumable completed scopes from persisted JSONL."""
    return {key for key, row in _latest_scope_rows(capture_dir).items() if row.get("status") == "completed"}


def _scope_key(scope: CaptureScope | dict[str, Any]) -> tuple[str, str, int, str]:
    """Input: CaptureScope or scope dict. Output: stable scope key tuple. Normalize a persisted capture scope key."""
    if isinstance(scope, CaptureScope):
        return scope.instrument_type, scope.region, int(scope.delay), scope.universe
    return str(scope["instrument_type"]), str(scope["region"]), int(scope["delay"]), str(scope["universe"])


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
) -> dict[str, Any]:
    """Input: client, vault root, scope filters, limits. Output: summary dict. Capture platform data fields into raw."""
    generated = generated_at or _now()
    root = Path(knowledge_root)
    capture_dir = root / RAW_CAPTURE_ROOT / _capture_day(generated)
    capture_dir.mkdir(parents=True, exist_ok=True)
    if not resume_capture:
        _clear_outputs(capture_dir)
    completed_scopes = _completed_scope_keys(capture_dir) if resume_capture else set()

    operators: list[dict[str, Any]] = []
    operator_fetch_succeeded = True
    try:
        operators = fetch_operators(client)
        _write_json(capture_dir / "operators.json", {"generated_at": generated, "operators": operators})
    except Exception as error:
        operator_fetch_succeeded = False
        _append_jsonl(capture_dir / "errors.jsonl", _error_row(None, "/operators", error, generated))
        _write_json(capture_dir / "operators.json", {"generated_at": generated, "operators": []})

    scopes = build_capture_scopes(instrument_types, regions, delays, universes, max_scopes=max_scopes)
    for scope in scopes:
        if _scope_key(scope) in completed_scopes:
            continue
        scope_row = {"generated_at": generated, "scope": _scope_dict(scope), "status": "started"}
        _append_jsonl(capture_dir / "scopes.jsonl", scope_row)
        try:
            data_sets = fetch_data_sets(
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
            scope_row.update({"status": "failed", "data_set_count": 0, "message": str(error)})
            _append_jsonl(capture_dir / "scopes.jsonl", scope_row)
            _append_jsonl(capture_dir / "errors.jsonl", _error_row(scope, "/data-sets", error, generated))
            continue

        field_errors: list[str] = []
        for data_set in data_sets:
            dataset_id = str(data_set.get("id", ""))
            _append_jsonl(
                capture_dir / "data_sets.jsonl",
                {"generated_at": generated, "scope": _scope_dict(scope), "data_set": data_set},
            )
            if not dataset_id:
                error = ValueError("missing dataset id")
                _append_jsonl(capture_dir / "errors.jsonl", _error_row(scope, "/data-sets", error, generated))
                field_errors.append(str(error))
                continue
            try:
                fields = fetch_data_fields(
                    client,
                    scope.instrument_type,
                    scope.region,
                    int(scope.delay),
                    scope.universe,
                    dataset_id=dataset_id,
                    limit=SAFE_PAGE_LIMIT,
                    max_records=max_fields_per_dataset if max_fields_per_dataset > 0 else 1000000,
                )
            except Exception as error:
                _append_jsonl(capture_dir / "errors.jsonl", _error_row(scope, f"/data-fields?dataset.id={dataset_id}", error, generated))
                field_errors.append(str(error))
                continue
            for field in fields:
                _append_jsonl(
                    capture_dir / "data_fields.jsonl",
                    {
                        "generated_at": generated,
                        "scope": _scope_dict(scope),
                        "data_set": data_set,
                        "field": field,
                        "endpoint": "/data-fields",
                    },
                )
        if field_errors:
            scope_row.update({"status": "partial", "data_set_count": len(data_sets), "error_count": len(field_errors), "message": "; ".join(field_errors)})
        else:
            scope_row.update({"status": "completed", "data_set_count": len(data_sets)})
        _append_jsonl(capture_dir / "scopes.jsonl", scope_row)

    latest_scope_rows = _latest_scope_rows(capture_dir)
    unresolved_scope_rows = [
        latest_scope_rows.get(_scope_key(scope), {})
        for scope in scopes
        if latest_scope_rows.get(_scope_key(scope), {}).get("status") != "completed"
    ]
    error_count = _unresolved_scope_error_count(unresolved_scope_rows) + (0 if operator_fetch_succeeded else 1)
    summary = {
        "generated_at": generated,
        "capture_dir": str(capture_dir),
        "scope_count": _jsonl_row_count(capture_dir / "scopes.jsonl"),
        "operator_count": len(operators),
        "data_set_count": _jsonl_row_count(capture_dir / "data_sets.jsonl"),
        "field_count": _jsonl_row_count(capture_dir / "data_fields.jsonl"),
        "error_count": error_count,
        "status": "completed" if error_count == 0 else "completed_with_warnings",
    }
    _write_json(capture_dir / "manifest.json", summary)
    errors_path = capture_dir / "errors.jsonl"
    if not errors_path.exists():
        errors_path.write_text("", encoding="utf-8")
    _write_index(capture_dir, summary)
    return summary
