"""Durable evidence for simulation submissions whose outcome may be uncertain."""

from __future__ import annotations

from typing import Any
from uuid import uuid4


def start_submission_attempt(recorder: Any, items: list[dict[str, Any]], stage: str) -> str:
    """Input: recorder, candidate rows and stage. Output: attempt ID. Persist intent before the platform POST."""
    attempt_id = uuid4().hex
    for item in items:
        recorder.append_jsonl("simulation_events.jsonl", {
            "event": "SUBMISSION_STARTED", "attempt_id": attempt_id, "stage": stage, **item,
        })
    return attempt_id


def finish_submission_attempt(
    recorder: Any, items: list[dict[str, Any]], attempt_id: str, event: str, **details: Any,
) -> None:
    """Input: recorder, items, attempt ID and definitive event. Output: None. Close one platform POST attempt."""
    if event not in {"SUBMITTED", "SUBMISSION_REJECTED"}:
        raise ValueError("submission event must be definitive")
    for item in items:
        recorder.append_jsonl("simulation_events.jsonl", {
            "event": event, "attempt_id": attempt_id, **details, **item,
        })


def uncertain_submission_hashes(events: list[dict[str, Any]]) -> set[str]:
    """Input: simulation event rows. Output: expression hashes. Find attempts without a definitive outcome."""
    started: dict[str, set[str]] = {}
    finished: set[tuple[str, str]] = set()
    for row in events:
        attempt_id = str(row.get("attempt_id", ""))
        expr_hash = str(row.get("expression_hash", ""))
        if attempt_id and expr_hash and row.get("event") == "SUBMISSION_STARTED":
            started.setdefault(attempt_id, set()).add(expr_hash)
        if attempt_id and expr_hash and row.get("event") in {"SUBMITTED", "SUBMISSION_REJECTED"}:
            finished.add((attempt_id, expr_hash))
    return {expr_hash for attempt_id, hashes in started.items() for expr_hash in hashes
            if (attempt_id, expr_hash) not in finished}
