from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_paths import ACTIVE_TOP_LEVELS, active_top_level_names


SENSITIVE_NAME_FRAGMENTS = (
    ".env",
    "credential",
    "secret",
    "token",
    "password",
    "key",
    "private",
)
OBSOLETE_ACTIVE_PREFIXES = (
    Path("raw") / "learn",
    Path("wiki") / "20_semantics",
    Path("wiki") / "30_templates",
    Path("wiki") / "40_experiments",
    Path("wiki") / "50_benchmarks",
    Path("wiki") / "70_decisions",
    Path("wiki") / "80_maintenance",
)
WIKI_MACHINE_EXTENSIONS = {".json", ".jsonl", ".csv"}


@dataclass(frozen=True)
class KnowledgeCleanIssue:
    code: str
    path: str
    message: str
    action: str


@dataclass(frozen=True)
class CleanupCandidate:
    path: str
    reason: str
    action: str
    sha256: str


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for clean compile logs."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str:
    """Input: file path. Output: SHA-256 hex digest. Hash cleanup candidates before removal."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _is_sensitive(path: Path) -> bool:
    """Input: path. Output: bool. Identify files that must not be auto-deleted."""
    lowered = path.name.lower()
    return any(fragment in lowered for fragment in SENSITIVE_NAME_FRAGMENTS)


def evaluate_clean_knowledge_structure(knowledge_root: str | Path) -> dict[str, Any]:
    """Input: knowledge root. Output: dict. Check the simplified active knowledge contract."""
    root = Path(knowledge_root)
    issues: list[KnowledgeCleanIssue] = []
    top_levels = active_top_level_names(root)
    for name in sorted(top_levels - ACTIVE_TOP_LEVELS):
        issues.append(
            KnowledgeCleanIssue(
                "extra_active_layer",
                str(root / name),
                "Top-level active knowledge layer is not allowed.",
                "Move compiled content under raw, machine, or wiki.",
            )
        )
    for prefix in OBSOLETE_ACTIVE_PREFIXES:
        path = root / prefix
        if path.exists():
            issues.append(
                KnowledgeCleanIssue(
                    "legacy_active_path",
                    str(path),
                    "Legacy mixed active path remains after compile.",
                    "Run clean compile cleanup after successful compile verification.",
                )
            )
    wiki_root = root / "wiki"
    if wiki_root.exists():
        for path in sorted(wiki_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in WIKI_MACHINE_EXTENSIONS:
                issues.append(
                    KnowledgeCleanIssue(
                        "machine_resource_inside_wiki",
                        str(path),
                        "Machine-readable artifact is inside the human wiki.",
                        "Move machine artifacts under knowledge/machine.",
                    )
                )
    return {
        "clean": not issues,
        "issue_count": len(issues),
        "top_levels": sorted(top_levels),
        "issues": [asdict(issue) for issue in issues],
    }


def plan_obsolete_active_cleanup(knowledge_root: str | Path) -> list[CleanupCandidate]:
    """Input: knowledge root. Output: cleanup candidates. Plan ordinary removals and sensitive refusals."""
    root = Path(knowledge_root)
    rows: list[CleanupCandidate] = []
    for prefix in OBSOLETE_ACTIVE_PREFIXES:
        base = root / prefix
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                action = "refuse" if _is_sensitive(path) else "remove"
                rows.append(
                    CleanupCandidate(
                        str(path),
                        f"obsolete active prefix {prefix.as_posix()}",
                        action,
                        _sha256(path),
                    )
                )
    return rows


def write_cleanup_log(knowledge_root: str | Path, rows: list[dict[str, Any]], generated_at: str) -> Path:
    """Input: knowledge root, cleanup rows, timestamp. Output: log path. Persist cleanup evidence."""
    root = Path(knowledge_root)
    path = root / "raw" / "maintenance" / "cleanup_logs" / f"{generated_at[:10]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _remove_empty_obsolete_directories(root: Path) -> None:
    """Input: knowledge root. Output: none. Remove empty directories under obsolete active prefixes."""
    for prefix in OBSOLETE_ACTIVE_PREFIXES:
        base = root / prefix
        if not base.is_dir():
            continue
        for directory in sorted((path for path in base.rglob("*") if path.is_dir()), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
        if not any(base.iterdir()):
            base.rmdir()


def apply_obsolete_active_cleanup(
    knowledge_root: str | Path,
    generated_at: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Input: root, timestamp, dry run. Output: cleanup summary. Remove ordinary obsolete files after verification."""
    generated = generated_at or _now()
    root = Path(knowledge_root)
    candidates = plan_obsolete_active_cleanup(root)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        path = Path(candidate.path)
        row = asdict(candidate) | {"generated_at": generated, "dry_run": dry_run}
        if candidate.action == "remove" and not dry_run:
            path.unlink(missing_ok=True)
            row["applied"] = True
        else:
            row["applied"] = False
        rows.append(row)
    if not dry_run:
        _remove_empty_obsolete_directories(root)
    log_path = (
        write_cleanup_log(root, rows, generated)
        if rows
        else root / "raw" / "maintenance" / "cleanup_logs" / f"{generated[:10]}.jsonl"
    )
    return {
        "generated_at": generated,
        "dry_run": dry_run,
        "removed_count": sum(1 for row in rows if row.get("applied")),
        "refused_count": sum(1 for row in rows if row["action"] == "refuse"),
        "candidate_count": len(rows),
        "cleanup_log_path": str(log_path),
    }
