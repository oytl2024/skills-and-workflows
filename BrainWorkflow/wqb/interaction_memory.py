from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_contracts import render_front_matter
from wqb.knowledge_paths import relative_to_knowledge_root


RAW_INTERACTION_ROOT = Path("raw") / "community" / "user_messages"
LESSON_CATEGORIES = {"workflow_rule", "engineering_lesson", "factor_lesson"}


@dataclass(frozen=True)
class InteractionNote:
    captured_at: str
    source: str
    category: str
    summary: str
    tags: list[str]
    evidence_paths: list[str]
    note_hash: str


def _now() -> str:
    """Input: none. Output: UTC timestamp string. Return the capture time for a new interaction note."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash_note(summary: str, category: str, tags: list[str]) -> str:
    """Input: note summary, category, and tags. Output: SHA-256 digest. Identify repeated interaction notes."""
    payload = json.dumps(
        {"summary": summary, "category": category, "tags": sorted(tags)},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _interaction_note_paths(knowledge_root: str | Path) -> list[Path]:
    """Input: knowledge root. Output: sorted JSONL paths. Find canonical raw interaction fact files."""
    root = Path(knowledge_root) / RAW_INTERACTION_ROOT
    return sorted(root.rglob("interaction_notes.jsonl")) if root.exists() else []


def _load_note_rows(knowledge_root: str | Path) -> list[tuple[Path, dict[str, Any]]]:
    """Input: knowledge root. Output: source paths and note rows. Load valid canonical interaction facts."""
    rows: list[tuple[Path, dict[str, Any]]] = []
    for path in _interaction_note_paths(knowledge_root):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append((path, row))
    return rows


def append_interaction_note(
    knowledge_root: str | Path,
    summary: str,
    category: str,
    tags: list[str],
    evidence_paths: list[str],
    captured_at: str | None = None,
    source: str = "codex_chat",
) -> Path:
    """Input: knowledge root and interaction fields. Output: raw JSONL path. Persist one deduplicated interaction fact."""
    generated = captured_at or _now()
    clean_tags = [str(tag) for tag in tags if str(tag).strip()]
    note = InteractionNote(
        captured_at=generated,
        source=str(source),
        category=str(category),
        summary=str(summary),
        tags=clean_tags,
        evidence_paths=[str(path) for path in evidence_paths],
        note_hash=_hash_note(str(summary), str(category), clean_tags),
    )
    path = Path(knowledge_root) / RAW_INTERACTION_ROOT / generated[:10] / "interaction_notes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_hashes = {row.get("note_hash") for _, row in _load_note_rows(knowledge_root)}
    if note.note_hash not in existing_hashes:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(note), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_interaction_notes(knowledge_root: str | Path) -> list[dict[str, Any]]:
    """Input: knowledge root. Output: interaction note rows. Load durable raw interaction memory."""
    return [row for _, row in _load_note_rows(knowledge_root)]


def compile_interaction_lessons(knowledge_root: str | Path, generated_at: str) -> dict[str, Any]:
    """Input: knowledge root and compile time. Output: summary dict. Compile reusable interaction lessons for the wiki."""
    root = Path(knowledge_root)
    lesson_rows = [
        (path, row)
        for path, row in _load_note_rows(root)
        if str(row.get("category", "")) in LESSON_CATEGORIES
    ]
    compiled_from = sorted({relative_to_knowledge_root(path, root) for path, _ in lesson_rows})
    path = root / "wiki" / "50_engineering_lessons.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    front_matter = render_front_matter(
        {
            "compiled_at": generated_at,
            "compiled_from": compiled_from,
            "consumed_by": ["human_learning", "workflow_maintenance"],
            "stale_after_days": 14,
            "trust_level": "compiled_experience",
            "update_trigger": "compile-knowledge",
        }
    )
    lessons = [f"- {' '.join(str(row.get('summary', '')).split())}" for _, row in lesson_rows]
    path.write_text(front_matter + "\n# Engineering Lessons\n\n" + "\n".join(lessons) + "\n", encoding="utf-8")
    return {"generated_at": generated_at, "lesson_count": len(lesson_rows), "path": str(path)}
