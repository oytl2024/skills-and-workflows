from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.data_catalog import fetch_data_sets_with_metadata
from wqb.data_field_capture import build_capture_scopes
from wqb.knowledge_paths import machine_resource_path


CAPTURE_PLAN_ROOT = Path("raw") / "platform" / "data_fields" / "capture_plans"


@dataclass(frozen=True)
class ScopeMatrixRow:
    generated_at: str
    instrument_type: str
    region: str
    delay: int
    universe: str
    status: str
    dataset_count: int
    truncated: bool
    message: str = ""


def _now() -> str:
    """Input: none. Output: timestamp str. Return UTC time for capture planning."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Input: JSONL path and rows. Output: none. Write deterministic planning records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def discover_scope_matrix(
    client: Any,
    knowledge_root: str | Path,
    generated_at: str | None = None,
    instrument_types: list[str] | None = None,
    regions: list[str] | None = None,
    delays: list[int] | None = None,
    universes: list[str] | None = None,
    max_scopes: int = 0,
) -> dict[str, Any]:
    """Input: client, knowledge root, scope filters. Output: discovery summary. Probe broad platform availability."""
    generated = generated_at or _now()
    scopes = build_capture_scopes(instrument_types, regions, delays, universes, max_scopes=max_scopes)
    rows: list[dict[str, Any]] = []
    for scope in scopes:
        try:
            data_sets, truncated = fetch_data_sets_with_metadata(
                client,
                scope.instrument_type,
                scope.region,
                int(scope.delay),
                scope.universe,
                limit=1,
                max_records=1,
            )
            row = ScopeMatrixRow(
                generated,
                scope.instrument_type,
                scope.region,
                int(scope.delay),
                scope.universe,
                "available" if data_sets else "empty",
                len(data_sets),
                bool(truncated),
            )
        except Exception as error:
            row = ScopeMatrixRow(
                generated,
                scope.instrument_type,
                scope.region,
                int(scope.delay),
                scope.universe,
                "failed",
                0,
                False,
                str(error),
            )
        rows.append(asdict(row))
    path = machine_resource_path(knowledge_root, "scope_matrix")
    _write_jsonl(path, rows)
    return {
        "generated_at": generated,
        "scope_matrix_path": str(path),
        "scope_count": len(rows),
        "available_scope_count": sum(1 for row in rows if row["status"] == "available"),
    }


def build_stratified_capture_plan(
    scope_rows: list[dict[str, Any]],
    fields_per_scope: int = 100,
    max_scopes: int = 0,
) -> list[dict[str, Any]]:
    """Input: scope matrix rows and limits. Output: plan rows. Select diverse scopes before deepening a scope."""
    available = [row for row in scope_rows if str(row.get("status", "")) == "available"]
    ordered = sorted(
        available,
        key=lambda row: (
            str(row.get("region", "")),
            int(row.get("delay", 0)),
            str(row.get("universe", "")),
        ),
    )
    if max_scopes > 0:
        ordered = ordered[: int(max_scopes)]
    return [
        {
            "instrument_type": str(row.get("instrument_type", "EQUITY")),
            "region": str(row.get("region", "")),
            "delay": int(row.get("delay", 0)),
            "universe": str(row.get("universe", "")),
            "field_budget": int(fields_per_scope),
            "status": "planned",
        }
        for row in ordered
    ]


def write_capture_plan(knowledge_root: str | Path, rows: list[dict[str, Any]], generated_at: str) -> Path:
    """Input: knowledge root, plan rows, timestamp. Output: plan path. Persist a dated stratified plan."""
    path = Path(knowledge_root) / CAPTURE_PLAN_ROOT / f"{generated_at[:10]}.jsonl"
    _write_jsonl(path, rows)
    return path


def load_capture_plan(path: str | Path) -> list[dict[str, Any]]:
    """Input: capture plan JSONL path. Output: plan rows. Load valid persisted plan records."""
    source = Path(path)
    if not source.exists():
        return []
    return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
