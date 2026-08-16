from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


CHECKPOINTS_FILENAME = "ai_checkpoints.jsonl"


@dataclass(frozen=True)
class AICheckpoint:
    checkpoint_id: str
    checkpoint_type: str
    reason: str
    evidence_paths: list[str]
    created_at: str
    status: str = "pending"


def _checkpoint_path(decisions_dir: str | Path) -> Path:
    """Input: decisions directory. Output: checkpoint file path. Resolve durable AI checkpoint storage."""
    return Path(decisions_dir) / CHECKPOINTS_FILENAME


def append_ai_checkpoint(
    decisions_dir: str | Path,
    checkpoint_type: str,
    reason: str,
    evidence_paths: list[str],
    created_at: str,
    status: str = "pending",
) -> AICheckpoint:
    """Input: checkpoint fields. Output: persisted checkpoint. Record required GPT/Codex judgment."""
    path = _checkpoint_path(decisions_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = AICheckpoint(
        checkpoint_id=f"ai-{uuid4().hex[:10]}",
        checkpoint_type=str(checkpoint_type),
        reason=str(reason),
        evidence_paths=[str(item) for item in evidence_paths],
        created_at=str(created_at),
        status=str(status),
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(checkpoint), ensure_ascii=False, sort_keys=True) + "\n")
    return checkpoint


def load_ai_checkpoints(decisions_dir: str | Path) -> list[dict[str, Any]]:
    """Input: decisions directory. Output: checkpoint rows. Read pending GPT/Codex judgment records."""
    path = _checkpoint_path(decisions_dir)
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("checkpoint_id") and row.get("checkpoint_type"):
            rows.append(row)
    return rows
