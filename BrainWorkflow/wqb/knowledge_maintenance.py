from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.interaction_memory import compile_interaction_lessons
from wqb.knowledge_clean_compile import OBSOLETE_ACTIVE_PREFIXES, apply_obsolete_active_cleanup
from wqb.knowledge_experience_compile import compile_human_experience_wiki
from wqb.knowledge_freshness import evaluate_knowledge_contract_health
from wqb.knowledge_paths import ensure_knowledge_dirs


@dataclass(frozen=True)
class KnowledgeMaintenanceReport:
    generated_at: str
    status: str
    wiki: dict[str, Any]
    interaction_lessons: dict[str, Any]
    cleanup: dict[str, Any]
    health: dict[str, Any]


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for knowledge maintenance."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_report(knowledge_root: str | Path, report: dict[str, Any]) -> Path:
    """Input: knowledge root and report. Output: report path. Persist maintenance evidence."""
    day = str(report["generated_at"])[:10]
    path = Path(knowledge_root) / "raw" / "maintenance" / "compile_reports" / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _is_cleanup_target_path(knowledge_root: Path, path: str | Path) -> bool:
    """Input: knowledge root and issue path. Output: bool. Identify health issues cleanup is allowed to resolve."""
    try:
        relative = Path(path).resolve().relative_to(knowledge_root.resolve())
    except ValueError:
        return False
    return any(relative == prefix or prefix in relative.parents for prefix in OBSOLETE_ACTIVE_PREFIXES)


def _pre_cleanup_evidence(
    knowledge_root: Path,
    generated_at: str,
    wiki: dict[str, Any],
    interaction_lessons: dict[str, Any],
) -> dict[str, Any]:
    """Input: compile outputs and root. Output: evidence dict. Verify only cleanup-resolvable health issues remain."""
    health = evaluate_knowledge_contract_health(knowledge_root)
    allowed_issues = [
        issue for issue in health.get("issues", [])
        if isinstance(issue, dict) and _is_cleanup_target_path(knowledge_root, str(issue.get("path", "")))
    ]
    blocking_issues = [
        issue for issue in health.get("issues", [])
        if isinstance(issue, dict) and issue not in allowed_issues
    ]
    return {
        "report_type": "knowledge_maintenance_pre_cleanup_evidence",
        "generated_at": generated_at,
        "status": "completed" if not blocking_issues else "blocked",
        "compile": {
            "status": "completed",
            "wiki": wiki,
            "interaction_lessons": interaction_lessons,
        },
        "pre_cleanup_health": {
            "issue_count": int(health.get("issue_count", 0)),
            "cleanup_resolvable_issue_count": len(allowed_issues),
            "blocking_issue_count": len(blocking_issues),
            "blocking_issues": blocking_issues,
        },
    }


def _write_pre_cleanup_evidence(knowledge_root: str | Path, evidence: dict[str, Any]) -> Path:
    """Input: knowledge root and evidence. Output: immutable evidence path. Persist a one-time cleanup authorization record."""
    root = Path(knowledge_root)
    day = str(evidence["generated_at"])[:10]
    directory = root / "raw" / "maintenance" / "compile_reports"
    directory.mkdir(parents=True, exist_ok=True)
    index = 0
    while True:
        suffix = "" if index == 0 else f".{index}"
        path = directory / f"{day}.pre_cleanup_evidence{suffix}.json"
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
            return path
        except FileExistsError:
            index += 1


def run_knowledge_maintenance(
    knowledge_root: str | Path,
    generated_at: str | None = None,
    apply_cleanup: bool = False,
    max_case_reports: int = 20,
) -> dict[str, Any]:
    """Input: knowledge root and compile settings. Output: maintenance report. Run compile, cleanup, and health verification."""
    generated = generated_at or _now()
    ensure_knowledge_dirs(knowledge_root)
    wiki = compile_human_experience_wiki(knowledge_root, generated, max_case_reports=max_case_reports)
    interaction = compile_interaction_lessons(knowledge_root, generated)
    verification_report_path = None
    if apply_cleanup:
        verification_report_path = _write_pre_cleanup_evidence(
            knowledge_root,
            _pre_cleanup_evidence(Path(knowledge_root), generated, wiki, interaction),
        )
    cleanup = apply_obsolete_active_cleanup(
        knowledge_root,
        generated,
        dry_run=not apply_cleanup,
        verification_report_path=verification_report_path,
    )
    cleanup["status"] = "blocked" if cleanup.get("blocked") else "completed"
    health = evaluate_knowledge_contract_health(knowledge_root)
    status = "completed" if health.get("issue_count", 0) == 0 else "blocked"
    report = asdict(KnowledgeMaintenanceReport(generated, status, wiki, interaction, cleanup, health))
    report_path = _write_report(knowledge_root, report)
    report["report_path"] = str(report_path)
    report["verification_report_path"] = str(verification_report_path) if verification_report_path else None
    _write_report(knowledge_root, report)
    return report
