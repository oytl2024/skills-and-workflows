from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.interaction_memory import compile_interaction_lessons
from wqb.knowledge_clean_compile import (
    OBSOLETE_ACTIVE_PREFIXES,
    apply_obsolete_active_cleanup,
    migrate_legacy_decision_artifacts,
)
from wqb.knowledge_experience_compile import compile_human_experience_wiki
from wqb.knowledge_freshness import evaluate_knowledge_contract_health
from wqb.knowledge_paths import ensure_knowledge_dirs
from wqb.knowledge_vault_migration import run_knowledge_vault_migration


@dataclass(frozen=True)
class KnowledgeMaintenanceReport:
    report_type: str
    generated_at: str
    status: str
    migration: dict[str, Any]
    decision_migration: dict[str, Any]
    wiki: dict[str, Any]
    interaction_lessons: dict[str, Any]
    cleanup: dict[str, Any]
    health: dict[str, Any]


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for knowledge maintenance."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_report(knowledge_root: str | Path, report: dict[str, Any]) -> Path:
    """Input: knowledge root and report. Output: report path. Persist maintenance evidence."""
    generated = datetime.fromisoformat(str(report["generated_at"]).replace("Z", "+00:00"))
    stem = generated.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(knowledge_root).resolve()
    directory = root / "raw" / "maintenance" / "compile_reports"
    directory.mkdir(parents=True, exist_ok=True)
    index = 0
    while True:
        suffix = "" if index == 0 else f".{index}"
        path = directory / f"{stem}{suffix}.json"
        payload = {**report, "report_path": str(path)}
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            (directory / "latest.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            report["report_path"] = str(path)
            return path
        except FileExistsError:
            index += 1


def _is_cleanup_target_path(knowledge_root: Path, path: str | Path) -> bool:
    """Input: knowledge root and issue path. Output: bool. Identify health issues cleanup is allowed to resolve."""
    try:
        relative = Path(path).resolve().relative_to(knowledge_root.resolve())
    except ValueError:
        return False
    if relative.parent == Path(".") and (knowledge_root / relative).is_file():
        return True
    return any(relative == prefix or prefix in relative.parents for prefix in OBSOLETE_ACTIVE_PREFIXES)


def _pre_cleanup_evidence(
    knowledge_root: Path,
    generated_at: str,
    wiki: dict[str, Any],
    interaction_lessons: dict[str, Any],
    decision_migration: dict[str, Any],
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
            "decision_migration": decision_migration,
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
    root = Path(knowledge_root).resolve()
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
    pointer = Path(knowledge_root) / "machine" / "semantic_release.json"
    if pointer.exists() or pointer.is_symlink():
        return _maintain_active_release(Path(knowledge_root), generated, apply_cleanup, max_case_reports)
    ensure_knowledge_dirs(knowledge_root)
    migration = run_knowledge_vault_migration(knowledge_root, generated)
    migration["mode"] = "legacy_initialization"
    decision_migration = migrate_legacy_decision_artifacts(knowledge_root)
    wiki = compile_human_experience_wiki(knowledge_root, generated, max_case_reports=max_case_reports)
    interaction = compile_interaction_lessons(knowledge_root, generated)
    verification_report_path = None
    if apply_cleanup:
        verification_report_path = _write_pre_cleanup_evidence(
            knowledge_root,
            _pre_cleanup_evidence(
                Path(knowledge_root),
                generated,
                wiki,
                interaction,
                decision_migration,
            ),
        )
    cleanup = apply_obsolete_active_cleanup(
        knowledge_root,
        generated,
        dry_run=not apply_cleanup,
        verification_report_path=verification_report_path,
    )
    cleanup["status"] = "blocked" if cleanup.get("blocked") else "completed"
    health = evaluate_knowledge_contract_health(knowledge_root)
    status = (
        "completed"
        if health.get("issue_count", 0) == 0
        and migration.get("status") == "completed"
        and decision_migration.get("status") == "completed"
        and cleanup.get("status") == "completed"
        else "blocked"
    )
    report = asdict(
        KnowledgeMaintenanceReport(
            "knowledge_maintenance",
            generated,
            status,
            migration,
            decision_migration,
            wiki,
            interaction,
            cleanup,
            health,
        )
    )
    report["verification_report_path"] = str(verification_report_path) if verification_report_path else None
    _write_report(knowledge_root, report)
    return report


def _maintain_active_release(root: Path, generated: str, apply_cleanup: bool, max_case_reports: int) -> dict[str, Any]:
    """Input: root Path, timestamp str, cleanup bool, case limit int. Output: dict receipt. Compile owned outputs without legacy migration."""
    from wqb.semantic_publication import read_semantic_release

    report = asdict(KnowledgeMaintenanceReport(
        "knowledge_maintenance", generated, "blocked",
        {"mode": "active_release_preserved", "status": "blocked"},
        {"status": "skipped", "reason": "active semantic release; legacy migration not applicable"},
        {"status": "not_started"}, {"status": "not_started"},
        {"status": "skipped", "removed_count": 0}, {"status": "not_started"},
    ))
    report["verification_report_path"] = None
    report['data_compile'] = dict(status='not_started')
    step = "migration"
    try:
        receipt = read_semantic_release(root)
        if receipt["release_id"] is None:
            raise ValueError("active semantic pointer disappeared during maintenance")
        report["migration"].update(status="completed", release_id=receipt["release_id"])
        ensure_knowledge_dirs(root)
        step = 'data_compile'
        report[step] = _compile_active_fields(root, generated)
        step = "wiki"
        report[step] = compile_human_experience_wiki(root, generated, max_case_reports=max_case_reports)
        report[step]["status"] = "completed"
        step = "interaction_lessons"
        report[step] = compile_interaction_lessons(root, generated)
        if read_semantic_release(root) != receipt:
            raise ValueError("semantic release selection changed during maintenance")
        step = "cleanup"
        if apply_cleanup:
            raise ValueError("active-release cleanup refused: source preservation is not verified; legacy migration was skipped")
        report[step] = apply_obsolete_active_cleanup(
            root, generated, dry_run=True,
        )
        report[step]["status"] = "blocked" if report[step].get("blocked") else "completed"
        step = "health"
        report[step] = evaluate_knowledge_contract_health(root)
        if read_semantic_release(root) != receipt:
            raise ValueError("semantic release selection changed during maintenance")
        if report["health"].get("issue_count", 0) == 0 and report["cleanup"]["status"] == "completed":
            report["status"] = "completed"
    except (OSError, ValueError, RuntimeError) as error:
        report[step] = {**report[step], "status": "blocked", "error": str(error)}
        report["error"] = f"{step}: {error}"
    _write_report(root, report)
    return report


def _compile_active_fields(root: Path, generated: str) -> dict[str, Any]:
    """Input: vault Path/compile timestamp str. Output: chronological local capture reports; preserve source dates and release."""
    from wqb.data_ledger_compile import compile_data_ledger_from_raw, _read_jsonl, merge_field_enrichment
    from wqb.knowledge_paths import existing_machine_resource_path
    from wqb.knowledge_contracts import (
        MAX_CAPTURE_MANIFEST_BYTES, _capture_json, _capture_timestamp, _source_contract_bytes,
    )
    from wqb.semantic_compilation import _safe
    base = _safe(root, 'raw/platform/data_fields')
    captures = []
    if base.exists():
        for candidate in sorted(base.iterdir()):
            checked = _safe(root, candidate.relative_to(root).as_posix())
            if checked.is_dir() and (checked / 'data_fields.jsonl').is_file() and (checked / 'manifest.json').is_file():
                for name in ('data_fields.jsonl', 'manifest.json', 'scopes.jsonl'):
                    _safe(root, (checked / name).relative_to(root).as_posix())
                manifest = _capture_json(_source_contract_bytes(checked / 'manifest.json', MAX_CAPTURE_MANIFEST_BYTES))
                timestamp = _capture_timestamp(manifest.get('generated_at'))
                if checked.name != timestamp.date().isoformat():
                    raise ValueError('capture directory/date mismatch: ' + checked.relative_to(root).as_posix())
                captures.append((timestamp, checked))
    if not captures:
        return dict(status='skipped', reason='No complete local raw capture directory; existing ledger retained')
    selections = []
    for row in _read_jsonl(existing_machine_resource_path(root, 'data_ledger'), strict_objects=True):
        if row.get('field_semantics_ref') is not None or row.get('timing_contract'):
            captured = {key: value for key, value in row.items()
                        if key not in ('field_semantics_ref', 'timing_contract')}
            selections.append(merge_field_enrichment(root, captured, row))
    # A later capture may cover another scope; replay in actual source-time order
    # so the existing compiler preserves unattempted scopes and partial outcomes.
    results = []
    for _, capture in sorted(captures):
        result = compile_data_ledger_from_raw(root, capture_dir=capture, generated_at=generated)
        results.append(dict(result, capture_path=capture.relative_to(root).as_posix()))
    if selections:
        _preserve_active_field_selections(root, selections, generated)
    return dict(results[-1], status='completed', captures=results)


def _preserve_active_field_selections(root: Path, selections: list[dict], generated: str) -> None:
    """Input: vault Path/initially verified selection rows/timestamp str. Output: None; revalidate compatible final-row enrichment atomically."""
    from uuid import uuid4
    from wqb.data_ledger import load_data_ledger, write_data_ledger_markdown
    from wqb.data_ledger_compile import (
        COMPILE_LOCK_NAME, COMPILE_LOCK_TIMEOUT_SECONDS, COMPILE_LOCK_SLEEP_SECONDS,
        COMPILE_LOCK_STALE_SECONDS, DATA_LEDGER_MD, _ledger_row_scope_keys,
        _read_jsonl, _write_jsonl, _publish_staged_outputs, merge_field_enrichment,
    )
    from wqb.knowledge_paths import machine_resource_path
    from wqb.lockfile import exclusive_json_lock

    selected = {(row['dataset_id'], row['field_id'], frozenset(_ledger_row_scope_keys(row))): row
                for row in selections}
    ledger = machine_resource_path(root, 'data_ledger')
    preview = root / DATA_LEDGER_MD
    with exclusive_json_lock(root / COMPILE_LOCK_NAME, COMPILE_LOCK_TIMEOUT_SECONDS,
                             COMPILE_LOCK_SLEEP_SECONDS, COMPILE_LOCK_STALE_SECONDS,
                             'data ledger compile lock is busy'):
        rows = _read_jsonl(ledger, strict_objects=True)
        output = []
        for row in rows:
            prior = selected.get((row['dataset_id'], row['field_id'], frozenset(_ledger_row_scope_keys(row))))
            candidate = dict(row)
            if prior is not None:
                for key in ('field_semantics_ref', 'timing_contract'):
                    if key not in candidate and key in prior:
                        candidate[key] = prior[key]
            output.append(merge_field_enrichment(root, row, candidate) if candidate != row else row)
        if output == rows:
            return
        token = uuid4().hex
        staged = [(ledger.with_name(ledger.name + '.' + token + '.tmp'), ledger),
                  (preview.with_name(preview.name + '.' + token + '.tmp'), preview)]
        try:
            _write_jsonl(staged[0][0], output)
            write_data_ledger_markdown(staged[1][0], load_data_ledger(staged[0][0]), generated)
            _publish_staged_outputs(staged)
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)
