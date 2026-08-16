from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from wqb.rate_limit_state import (
    cooldown_is_active,
    rate_limit_requires_maintenance,
    read_rate_limit_state,
)
from wqb.workflow_events import append_workflow_event
from wqb.workflow_stage_adapters import import_scout_seed_artifacts


SOURCE_BINDING_RELATIVE_PATH = Path("stages") / "scout_seed" / "source_bridge_binding.json"


@dataclass(frozen=True)
class SourceBridgeDecision:
    """Input: source bridge fields. Output: immutable decision. Explain the next source recovery action."""

    action: str
    reason: str
    source_run_id: str = ""
    source_run_dir: str = ""
    evidence_paths: list[str] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Input: decision. Output: dict. Serialize source bridge decision for CLI and Console."""
        row = asdict(self)
        row["evidence_paths"] = list(self.evidence_paths or [])
        row["metadata"] = dict(self.metadata or {})
        return row


def active_run_needs_scout_seed_candidates(summary: dict[str, Any]) -> bool:
    """Input: workflow summary. Output: bool. Detect the paused missing-candidate bridge state."""
    return (
        bool(summary.get("active"))
        and str(summary.get("status", "")) == "paused"
        and str(summary.get("current_stage", "")) == "scout_seed"
        and "candidates.csv" in str(summary.get("pause_reason", ""))
    )


def _candidate_file_valid(source: Path) -> bool:
    """Input: source run dir. Output: bool. Check candidate file existence before audited import."""
    path = source / "candidates.csv"
    if not path.exists() or not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            required = {"alpha_id", "expression_hash"}
            if not required.issubset(set(reader.fieldnames or [])):
                return False
            has_candidate = False
            for row in reader:
                alpha_id = str(row.get("alpha_id", "") or "").strip()
                expression_hash = str(row.get("expression_hash", "") or "").strip()
                if not alpha_id or not expression_hash:
                    return False
                has_candidate = True
            return has_candidate
    except (OSError, csv.Error):
        return False


def _simulation_event_keys(record: dict[str, Any]) -> list[str]:
    """Input: simulation event row. Output: identity keys. Match terminal events to their submitted simulation."""
    return [
        f"{name}:{str(record[name]).strip()}"
        for name in ("progress_url", "simulation_id", "expression_hash")
        if str(record.get(name, "") or "").strip()
    ]


def _has_in_flight_simulation(events_path: Path) -> bool:
    """Input: simulation JSONL path. Output: bool. Track submitted simulations until their own terminal event."""
    pending: dict[str, dict[str, Any]] = {}
    submission_for_key: dict[str, str] = {}
    try:
        with events_path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                keys = _simulation_event_keys(record)
                if not keys:
                    continue
                event = str(record.get("event", "")).upper()
                if event == "SUBMITTED":
                    submission_key = keys[0]
                    pending[submission_key] = record
                    for key in keys:
                        submission_for_key[key] = submission_key
                elif event in {"CHECKED", "ERROR"}:
                    submission_key = submission_for_key.get(keys[0])
                    if submission_key:
                        pending.pop(submission_key, None)
        return bool(pending)
    except OSError:
        return False


def _source_runs(runs_root: Path, active_run_dir: Path) -> list[Path]:
    """Input: runs root and active dir. Output: candidate source dirs. List newest source dirs first."""
    active_resolved = active_run_dir.resolve()
    rows = [
        path
        for path in runs_root.iterdir()
        if path.is_dir() and path.resolve() != active_resolved
    ]
    return sorted(rows, key=lambda path: path.stat().st_mtime, reverse=True)


def _read_json(path: Path) -> dict[str, Any]:
    """Input: JSON path. Output: object dict or empty dict. Read bridge metadata conservatively."""
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return row if isinstance(row, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: valid object rows. Ignore malformed evidence lines without crashing inspection."""
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _selected_scope(active_run_dir: Path) -> dict[str, Any]:
    """Input: active workflow directory. Output: normalized scope dict. Read the workflow-owned selected scope."""
    manifest = _read_json(active_run_dir / "run_manifest.json")
    scope = manifest.get("selected_scope")
    if not isinstance(scope, dict):
        return {}
    try:
        delay = int(scope.get("delay"))
    except (TypeError, ValueError):
        return {}
    region = str(scope.get("region", "")).strip().upper()
    universe = str(scope.get("universe", "")).strip().upper()
    instrument_type = str(scope.get("instrument_type", "EQUITY")).strip().upper()
    if not region or not universe or delay < 0:
        return {}
    return {
        "instrument_type": instrument_type or "EQUITY",
        "region": region,
        "delay": delay,
        "universe": universe,
    }


def _source_batch_metadata(active_run_dir: Path) -> dict[str, Any]:
    """Input: active run dir. Output: source batch args. Read first scheduled Scout field/template."""
    schedule_path = active_run_dir / "stages" / "schedule" / "research_schedule.json"
    if not schedule_path.exists():
        return {}
    try:
        schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    matches = schedule.get("template_matches", [])
    if not isinstance(matches, list) or not matches or not isinstance(matches[0], dict):
        return {}
    first = matches[0]
    field_id = str(first.get("field_id", "")).strip()
    scope = _selected_scope(active_run_dir)
    return {
        "field_search": field_id,
        "exact_field_id": field_id,
        "dataset_id": str(first.get("dataset_id", "")).strip(),
        "template_mode": "economic",
        "workflow_stage": "scout",
        "submit_mode": "multi",
        "max_alphas_per_round": 30,
        **scope,
    }


def _latest_source_metadata(source: Path) -> dict[str, Any]:
    """Input: source run directory. Output: latest run metadata dict. Read source provenance for compatibility checks."""
    rows = _read_jsonl(source / "run_meta.jsonl")
    return dict(rows[-1]) if rows else {}


def _source_scope(metadata: dict[str, Any]) -> dict[str, Any]:
    """Input: source run metadata. Output: normalized scope dict. Read explicit scope or legacy data-fields query metadata."""
    query = parse_qs(urlparse(str(metadata.get("data_fields_path", ""))).query)

    def value(name: str, query_name: str | None = None) -> Any:
        direct = metadata.get(name)
        if direct not in (None, ""):
            return direct
        values = query.get(query_name or name, [])
        return values[0] if values else ""

    try:
        delay = int(value("delay"))
    except (TypeError, ValueError):
        return {}
    region = str(value("region")).strip().upper()
    universe = str(value("universe")).strip().upper()
    instrument_type = str(value("instrument_type", "instrumentType")).strip().upper()
    if not region or not universe or delay < 0:
        return {}
    return {
        "instrument_type": instrument_type or "EQUITY",
        "region": region,
        "delay": delay,
        "universe": universe,
    }


def _source_is_compatible(source: Path, expected: dict[str, Any]) -> bool:
    """Input: source directory and active expectations. Output: bool. Require matching field, dataset, stage, and scope provenance."""
    metadata = _latest_source_metadata(source)
    source_field = str(metadata.get("exact_field_id", "")).strip()
    if not source_field:
        source_field = str(metadata.get("field_search", "")).strip()
    expected_field = str(expected.get("exact_field_id", "")).strip()
    if not metadata or not expected_field or source_field != expected_field:
        return False
    if str(metadata.get("dataset_id", "")).strip() != str(
        expected.get("dataset_id", "")
    ).strip():
        return False
    if str(metadata.get("workflow_stage", "")).strip().lower() != "scout":
        return False
    return _source_scope(metadata) == {
        key: expected.get(key) for key in ("instrument_type", "region", "delay", "universe")
    }


def _planned_candidate_state(source: Path) -> tuple[bool, bool]:
    """Input: source run directory. Output: has-planned and has-unresolved flags. Subtract submitted or terminal identities."""
    planned_rows = _read_jsonl(source / "planned_candidates.jsonl")
    planned_hashes = {
        str(row.get("expression_hash", "")).strip()
        for row in planned_rows
        if str(row.get("expression_hash", "")).strip()
        and str(row.get("expression", "")).strip()
    }
    completed_hashes = {
        str(row.get("expression_hash", "")).strip()
        for row in _read_jsonl(source / "simulation_events.jsonl")
        if str(row.get("event", "")).upper() in {"SUBMITTED", "CHECKED", "ERROR"}
        and str(row.get("expression_hash", "")).strip()
    }
    return bool(planned_rows), bool(planned_hashes - completed_hashes)


def _binding_path(active_run_dir: Path) -> Path:
    """Input: active workflow directory. Output: binding path. Locate durable source-run selection evidence."""
    return active_run_dir / SOURCE_BINDING_RELATIVE_PATH


def _read_binding(active_run_dir: Path) -> tuple[str, dict[str, Any]]:
    """Input: active workflow directory. Output: binding status and data. Distinguish missing from malformed evidence."""
    path = _binding_path(active_run_dir)
    if not path.exists():
        return "none", {}
    row = _read_json(path)
    source_run_id = str(row.get("source_run_id", "")).strip()
    if not row or not source_run_id or Path(source_run_id).name != source_run_id:
        return "invalid", {}
    return "bound", row


def _persist_binding(
    active_run_dir: Path,
    source: Path,
    expected: dict[str, Any],
    now: str,
) -> Path:
    """Input: active run, compatible source, expected metadata, timestamp. Output: binding path. Persist first source selection."""
    path = _binding_path(active_run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    payload = {
        "source_run_id": source.name,
        "source_run_dir": str(source),
        "bound_at": now,
        "expected_metadata": dict(expected),
        "source_metadata": _latest_source_metadata(source),
        "provenance_paths": [
            str(active_run_dir / "run_manifest.json"),
            str(active_run_dir / "stages" / "schedule" / "research_schedule.json"),
            str(source / "run_meta.jsonl"),
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    append_workflow_event(
        active_run_dir,
        "source_run_bound",
        {
            "source_run_id": source.name,
            "source_run_dir": str(source),
            "binding_path": str(path),
            "expected_metadata": dict(expected),
        },
        now,
    )
    return path


def _decision_for_source(source: Path, now: str) -> SourceBridgeDecision | None:
    """Input: one compatible source and timestamp. Output: recovery decision or none. Classify durable source evidence."""
    candidate_path = source / "candidates.csv"
    if _candidate_file_valid(source):
        return SourceBridgeDecision(
            "import_existing",
            "valid source candidates found",
            source.name,
            str(source),
            [str(candidate_path)],
        )
    if candidate_path.exists():
        return SourceBridgeDecision(
            "maintenance_blocker",
            "source candidates artifact is invalid",
            source.name,
            str(source),
            [str(candidate_path)],
        )
    cooldown_path = source / "rate_limit_state.json"
    cooldown = read_rate_limit_state(cooldown_path)
    if rate_limit_requires_maintenance(cooldown):
        return SourceBridgeDecision(
            "maintenance_blocker",
            "consecutive platform rate limit threshold reached",
            source.name,
            str(source),
            [str(cooldown_path)],
            cooldown,
        )
    if cooldown_is_active(cooldown, now):
        return SourceBridgeDecision(
            "rate_limit_wait",
            "platform cooldown active",
            source.name,
            str(source),
            [str(cooldown_path)],
            cooldown,
        )
    events_path = source / "simulation_events.jsonl"
    if events_path.exists() and _has_in_flight_simulation(events_path):
        return SourceBridgeDecision(
            "complete_in_flight",
            "submitted simulation needs recovery",
            source.name,
            str(source),
            [str(events_path)],
        )
    planned_path = source / "planned_candidates.jsonl"
    has_planned, has_unresolved = _planned_candidate_state(source)
    if has_unresolved:
        return SourceBridgeDecision(
            "retry_planned",
            "planned source candidates remain",
            source.name,
            str(source),
            [str(planned_path)],
        )
    if planned_path.exists() or has_planned:
        return SourceBridgeDecision(
            "maintenance_blocker",
            "source run exhausted without hard-pass candidates",
            source.name,
            str(source),
            [str(planned_path), str(events_path)],
        )
    return None


def _bind_decision(
    active: Path,
    source: Path,
    expected: dict[str, Any],
    decision: SourceBridgeDecision,
    now: str,
) -> SourceBridgeDecision:
    """Input: active/source runs, expectations, decision, timestamp. Output: bound decision. Attach durable binding evidence."""
    binding = _persist_binding(active, source, expected, now)
    return SourceBridgeDecision(
        decision.action,
        decision.reason,
        decision.source_run_id,
        decision.source_run_dir,
        [*(decision.evidence_paths or []), str(binding)],
        decision.metadata,
    )


def inspect_scout_seed_source_bridge(
    runs_root: str | Path,
    active_run_dir: str | Path,
    now: str,
) -> SourceBridgeDecision:
    """Input: runs root, active run dir, timestamp. Output: bridge decision. Choose source artifact recovery action."""
    root = Path(runs_root)
    active = Path(active_run_dir)
    metadata = _source_batch_metadata(active)
    schedule_path = active / "stages" / "schedule" / "research_schedule.json"
    binding_status, binding = _read_binding(active)
    binding_path = _binding_path(active)
    if binding_status == "invalid":
        return SourceBridgeDecision(
            "maintenance_blocker",
            "source run binding evidence is invalid",
            evidence_paths=[str(binding_path)],
        )
    if binding_status == "bound":
        source_run_id = str(binding.get("source_run_id", ""))
        source = root / source_run_id
        if not source.is_dir() or source.resolve().parent != root.resolve():
            return SourceBridgeDecision(
                "maintenance_blocker",
                "bound source run is missing or outside the runs root",
                source_run_id,
                str(source),
                [str(binding_path)],
            )
        if not _source_is_compatible(source, metadata):
            return SourceBridgeDecision(
                "maintenance_blocker",
                "bound source run metadata no longer matches the active workflow",
                source_run_id,
                str(source),
                [str(binding_path), str(source / "run_meta.jsonl")],
            )
        decision = _decision_for_source(source, now)
        if decision is not None:
            return SourceBridgeDecision(
                decision.action,
                decision.reason,
                decision.source_run_id,
                decision.source_run_dir,
                [*(decision.evidence_paths or []), str(binding_path)],
                decision.metadata,
            )
        return SourceBridgeDecision(
            "maintenance_blocker",
            "bound source run has no recoverable evidence",
            source_run_id,
            str(source),
            [str(binding_path), str(source / "run_meta.jsonl")],
        )
    if metadata.get("field_search") and _selected_scope(active):
        sources = [
            source
            for source in _source_runs(root, active)
            if _source_is_compatible(source, metadata)
        ]
        decisions = [
            (source, decision)
            for source in sources
            for decision in [_decision_for_source(source, now)]
            if decision is not None
        ]
        action_priority = {
            "import_existing": 0,
            "rate_limit_wait": 1,
            "complete_in_flight": 2,
            "retry_planned": 3,
            "maintenance_blocker": 4,
        }
        if decisions:
            source, decision = min(
                decisions,
                key=lambda item: action_priority.get(item[1].action, 99),
            )
            return _bind_decision(active, source, metadata, decision, now)
        return SourceBridgeDecision(
            "start_source_batch",
            "no recoverable source run exists",
            "",
            "",
            [str(schedule_path)],
            metadata,
        )
    return SourceBridgeDecision(
        "maintenance_blocker",
        "research schedule or selected scope has no source batch metadata",
        "",
        "",
        [str(schedule_path)],
        {},
    )


def import_existing_source_artifacts(
    active_run_dir: str | Path,
    decision: SourceBridgeDecision,
    imported_at: str,
) -> dict[str, object]:
    """Input: active run dir, bridge decision, timestamp. Output: import summary. Import valid source candidates once."""
    if decision.action != "import_existing" or not decision.source_run_dir:
        raise ValueError("source bridge decision is not importable")
    return import_scout_seed_artifacts(active_run_dir, decision.source_run_dir, imported_at)
