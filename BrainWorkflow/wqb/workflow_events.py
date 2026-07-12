from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


EVENTS_FILENAME = "workflow_events.jsonl"


@dataclass(frozen=True)
class WorkflowEvent:
    event_type: str
    occurred_at: str
    payload: dict[str, Any]


def append_workflow_event(run_dir: str | Path, event_type: str, payload: dict[str, object], occurred_at: str) -> Path:
    """Input: run dir, event type, payload, timestamp. Output: event path. Append one workflow event."""
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / EVENTS_FILENAME
    event = WorkflowEvent(event_type=str(event_type), occurred_at=str(occurred_at), payload=dict(payload))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def read_workflow_events(run_dir: str | Path) -> list[WorkflowEvent]:
    """Input: run dir. Output: workflow events. Read valid append-only events in file order."""
    path = Path(run_dir) / EVENTS_FILENAME
    if not path.exists():
        return []
    events: list[WorkflowEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or "event_type" not in row or "occurred_at" not in row:
            continue
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue
        events.append(
            WorkflowEvent(
                event_type=str(row["event_type"]),
                occurred_at=str(row["occurred_at"]),
                payload=payload,
            )
        )
    return events
