from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from wqb.rate_limit_state import cooldown_is_active, read_rate_limit_state
from wqb.workflow_stage_adapters import import_scout_seed_artifacts


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
    return path.exists() and path.is_file() and path.stat().st_size > len("alpha_id,expression_hash\n")


def _source_runs(runs_root: Path, active_run_dir: Path) -> list[Path]:
    """Input: runs root and active dir. Output: candidate source dirs. List newest source dirs first."""
    active_resolved = active_run_dir.resolve()
    rows = [
        path
        for path in runs_root.iterdir()
        if path.is_dir() and path.resolve() != active_resolved
    ]
    return sorted(rows, key=lambda path: path.stat().st_mtime, reverse=True)


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
    return {
        "field_search": field_id,
        "exact_field_id": field_id,
        "dataset_id": str(first.get("dataset_id", "")).strip(),
        "template_mode": "economic",
        "workflow_stage": "scout",
        "submit_mode": "multi",
        "max_alphas_per_round": 30,
    }


def inspect_scout_seed_source_bridge(
    runs_root: str | Path,
    active_run_dir: str | Path,
    now: str,
) -> SourceBridgeDecision:
    """Input: runs root, active run dir, timestamp. Output: bridge decision. Choose source artifact recovery action."""
    root = Path(runs_root)
    active = Path(active_run_dir)
    for source in _source_runs(root, active):
        if _candidate_file_valid(source):
            return SourceBridgeDecision(
                "import_existing",
                "valid source candidates found",
                source.name,
                str(source),
                [str(source / "candidates.csv")],
            )
    for source in _source_runs(root, active):
        cooldown = read_rate_limit_state(source / "rate_limit_state.json")
        if cooldown_is_active(cooldown, now):
            return SourceBridgeDecision(
                "rate_limit_wait",
                "platform cooldown active",
                source.name,
                str(source),
                [str(source / "rate_limit_state.json")],
                cooldown,
            )
    for source in _source_runs(root, active):
        events_path = source / "simulation_events.jsonl"
        if events_path.exists():
            text = events_path.read_text(encoding="utf-8")
            if "SUBMITTED" in text and "CHECKED" not in text:
                return SourceBridgeDecision(
                    "complete_in_flight",
                    "submitted simulation needs recovery",
                    source.name,
                    str(source),
                    [str(events_path)],
                )
    for source in _source_runs(root, active):
        planned_path = source / "planned_candidates.jsonl"
        if planned_path.exists():
            return SourceBridgeDecision(
                "retry_planned",
                "planned source candidates remain",
                source.name,
                str(source),
                [str(planned_path)],
            )
    metadata = _source_batch_metadata(active)
    schedule_path = active / "stages" / "schedule" / "research_schedule.json"
    if metadata.get("field_search"):
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
        "research schedule has no source batch metadata",
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
