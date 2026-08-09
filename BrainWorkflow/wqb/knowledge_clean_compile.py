from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_paths import (
    ACTIVE_TOP_LEVELS,
    DECISION_ARTIFACTS_ROOT,
    LEGACY_DECISION_ARTIFACTS_ROOT,
    active_top_level_names,
)


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
    Path("wiki") / "10_foundations",
    Path("wiki") / "20_semantics",
    Path("wiki") / "30_templates",
    Path("wiki") / "40_experiments",
    Path("wiki") / "50_benchmarks",
    Path("wiki") / "60_workflows",
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


def _is_sensitive(path: Path, root: Path) -> bool:
    """Input: candidate path and knowledge root. Output: bool. Refuse sensitive relative path components."""
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return True
    return any(fragment in part.lower() for part in parts for fragment in SENSITIVE_NAME_FRAGMENTS)


def evaluate_clean_knowledge_structure(knowledge_root: str | Path) -> dict[str, Any]:
    """Input: knowledge root. Output: dict. Check the simplified active knowledge contract."""
    root = Path(knowledge_root)
    issues: list[KnowledgeCleanIssue] = []
    top_levels = active_top_level_names(root)
    for name in sorted(ACTIVE_TOP_LEVELS - top_levels):
        issues.append(
            KnowledgeCleanIssue(
                "missing_required_layer",
                str(root / name),
                "Required active knowledge layer is missing.",
                "Create the raw, machine, and wiki active knowledge layers before compile.",
            )
        )
    for name in sorted(top_levels - ACTIVE_TOP_LEVELS):
        issues.append(
            KnowledgeCleanIssue(
                "extra_active_layer",
                str(root / name),
                "Top-level active knowledge layer is not allowed.",
                "Move compiled content under raw, machine, or wiki.",
            )
        )
    if root.exists():
        for path in sorted(item for item in root.iterdir() if item.is_file()):
            issues.append(
                KnowledgeCleanIssue(
                    "root_level_file",
                    str(path),
                    "Files are not allowed at the knowledge root.",
                    "Move the file under raw, machine, or wiki, or remove it through guarded cleanup.",
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
    if root.exists():
        for path in sorted(item for item in root.iterdir() if item.is_file()):
            action = "refuse" if _is_sensitive(path, root) else "remove"
            rows.append(
                CleanupCandidate(
                    str(path),
                    "file at knowledge root",
                    action,
                    _sha256(path),
                )
            )
    for prefix in OBSOLETE_ACTIVE_PREFIXES:
        base = root / prefix
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                migrated = True
                if prefix == LEGACY_DECISION_ARTIFACTS_ROOT:
                    relative = path.relative_to(base)
                    canonical = root / DECISION_ARTIFACTS_ROOT / relative
                    migrated = canonical.is_file() and _sha256(canonical) == _sha256(path)
                action = "refuse" if _is_sensitive(path, root) or not migrated else "remove"
                reason = f"obsolete active prefix {prefix.as_posix()}"
                if prefix == LEGACY_DECISION_ARTIFACTS_ROOT:
                    reason += (
                        " with exact canonical migration"
                        if migrated
                        else " without exact canonical migration"
                    )
                rows.append(
                    CleanupCandidate(
                        str(path),
                        reason,
                        action,
                        _sha256(path),
                    )
                )
    return rows


def migrate_legacy_decision_artifacts(knowledge_root: str | Path) -> dict[str, Any]:
    """Input: knowledge root. Output: migration evidence. Copy legacy decisions without overwriting conflicts."""
    root = Path(knowledge_root)
    legacy = root / LEGACY_DECISION_ARTIFACTS_ROOT
    canonical = root / DECISION_ARTIFACTS_ROOT
    artifacts: list[dict[str, Any]] = []
    if legacy.exists():
        for source in sorted(path for path in legacy.rglob("*") if path.is_file()):
            relative = source.relative_to(legacy)
            target = canonical / relative
            source_hash = _sha256(source)
            target_hash = _sha256(target) if target.is_file() else ""
            if target.is_file() and target_hash != source_hash:
                status = "conflict"
            elif target.is_file():
                status = "verified_existing"
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
                target_hash = _sha256(target)
                status = "migrated"
            artifacts.append(
                {
                    "source_path": str(source),
                    "target_path": str(target),
                    "source_sha256": source_hash,
                    "target_sha256": target_hash,
                    "status": status,
                }
            )
    return {
        "status": "completed"
        if all(row["status"] != "conflict" for row in artifacts)
        else "blocked",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def write_cleanup_log(knowledge_root: str | Path, rows: list[dict[str, Any]], generated_at: str) -> Path:
    """Input: knowledge root, cleanup rows, timestamp. Output: log path. Persist cleanup evidence."""
    root = Path(knowledge_root).resolve()
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


def _compile_verification_evidence(
    root: Path,
    verification_report_path: str | Path | None,
    dry_run: bool,
) -> dict[str, Any]:
    """Input: root, report path, dry-run flag. Output: evidence dict. Validate compile report before deletion."""
    if dry_run:
        return {"verification_report_path": None, "verification_status": "not_required", "verified": True}
    if verification_report_path is None:
        return {"verification_report_path": None, "verification_status": "missing", "verified": False}

    report_path = Path(verification_report_path).resolve()
    report_root = (root / "raw" / "maintenance" / "compile_reports").resolve()
    try:
        report_path.relative_to(report_root)
    except ValueError:
        return {
            "verification_report_path": str(report_path),
            "verification_status": "outside_maintenance_directory",
            "verified": False,
        }
    if not report_path.is_file():
        return {"verification_report_path": str(report_path), "verification_status": "missing", "verified": False}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"verification_report_path": str(report_path), "verification_status": "invalid", "verified": False}
    if not isinstance(report, dict):
        return {"verification_report_path": str(report_path), "verification_status": "invalid", "verified": False}

    status = report.get("status")
    compile_summary = report.get("compile")
    pre_cleanup_health = report.get("pre_cleanup_health")
    verified = (
        report.get("report_type") == "knowledge_maintenance_pre_cleanup_evidence"
        and status == "completed"
        and isinstance(compile_summary, dict)
        and compile_summary.get("status") == "completed"
        and isinstance(pre_cleanup_health, dict)
        and pre_cleanup_health.get("blocking_issue_count") == 0
    )
    if verified:
        verification_status = "completed"
    elif isinstance(status, str) and status not in {"completed", "passed"}:
        verification_status = status
    else:
        verification_status = "invalid"
    return {
        "verification_report_path": str(report_path),
        "verification_status": verification_status,
        "verified": verified,
    }


def apply_obsolete_active_cleanup(
    knowledge_root: str | Path,
    generated_at: str | None = None,
    dry_run: bool = True,
    verification_report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Input: root, timestamp, dry run, compile report path. Output: cleanup summary with audit log."""
    generated = generated_at or _now()
    root = Path(knowledge_root).resolve()
    candidates = plan_obsolete_active_cleanup(root)
    evidence = _compile_verification_evidence(root, verification_report_path, dry_run)
    blocked = not evidence["verified"]
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        path = Path(candidate.path)
        row = asdict(candidate) | {
            "generated_at": generated,
            "dry_run": dry_run,
            "blocked": blocked,
            "verification_report_path": evidence["verification_report_path"],
            "verification_status": evidence["verification_status"],
        }
        if candidate.action == "remove" and not dry_run and not blocked:
            path.unlink(missing_ok=True)
            row["applied"] = True
        else:
            row["applied"] = False
        rows.append(row)
    if not dry_run and not blocked:
        _remove_empty_obsolete_directories(root)
    summary_row = {
        "event": "cleanup_run",
        "generated_at": generated,
        "dry_run": dry_run,
        "blocked": blocked,
        "verification_report_path": evidence["verification_report_path"],
        "verification_status": evidence["verification_status"],
        "candidate_count": len(rows),
        "removed_count": sum(1 for row in rows if row.get("applied")),
        "refused_count": sum(1 for row in rows if row["action"] == "refuse"),
    }
    log_path = write_cleanup_log(root, [*rows, summary_row], generated)
    return {
        "generated_at": generated,
        "dry_run": dry_run,
        "blocked": blocked,
        "verification_report_path": evidence["verification_report_path"],
        "verification_status": evidence["verification_status"],
        "removed_count": summary_row["removed_count"],
        "refused_count": summary_row["refused_count"],
        "candidate_count": summary_row["candidate_count"],
        "cleanup_log_path": str(log_path),
    }
