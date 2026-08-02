from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.interaction_memory import compile_interaction_lessons
from wqb.knowledge_clean_compile import apply_obsolete_active_cleanup
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
    compile_evidence = asdict(
        KnowledgeMaintenanceReport(
            generated_at=generated,
            status="completed",
            wiki=wiki,
            interaction_lessons=interaction,
            cleanup={"status": "pending"},
            health={"issue_count": 0},
        )
    )
    report_path = _write_report(knowledge_root, compile_evidence)
    cleanup = apply_obsolete_active_cleanup(
        knowledge_root,
        generated,
        dry_run=not apply_cleanup,
        verification_report_path=report_path if apply_cleanup else None,
    )
    cleanup["status"] = "blocked" if cleanup.get("blocked") else "completed"
    health = evaluate_knowledge_contract_health(knowledge_root)
    status = "completed" if health.get("issue_count", 0) == 0 else "blocked"
    report = asdict(KnowledgeMaintenanceReport(generated, status, wiki, interaction, cleanup, health))
    report["report_path"] = str(report_path)
    _write_report(knowledge_root, report)
    return report
