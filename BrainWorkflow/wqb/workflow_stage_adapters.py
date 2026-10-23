from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import date, datetime, timezone
from dataclasses import asdict
from pathlib import Path
import re
from typing import Any, Callable

from wqb.benchmark_rules import (
    BENCHMARK_RULES_PATH,
    OFFICIAL_WORKFLOW_MARKER_FILES,
    START_SNAPSHOT_VERSION,
    benchmark_rule_to_dict,
    benchmark_rules_path_for_knowledge,
    benchmark_rulebook_digest,
    benchmark_rules_from_start_snapshot,
    load_benchmark_rules,
    load_run_benchmark_rules,
)
from wqb.data_ledger import data_ledger_path_for_knowledge, data_ledger_record_from_dict, load_data_ledger_from_knowledge
from wqb.knowledge_paths import existing_decision_artifact_path
from wqb.option_cards import option_card_from_row, read_option_card_jsonl
from wqb.principle_model import OptionCard
from wqb.research_scheduler import build_research_schedule, research_schedule_to_dict, write_research_schedule
from wqb.run_readiness import evaluate_run_readiness
from wqb.stage_outcomes import checked_research_rows, research_outcome, validate_checked_rows, research_benchmark_label
from wqb.models import CheckItem, CheckSummary
from wqb.optimizer import actions_for_check_summary
from wqb.repair_runtime import RepairRateLimited, RepairRecoveryPending, RepairProgressPending
from wqb.runtime_control import RuntimePaused
from wqb.template_library import load_template_library_from_knowledge, select_templates_for_data, template_library_path_for_knowledge, template_record_from_dict


START_SNAPSHOT_DATA_LEDGER_ROW_LIMIT = 200
DEFAULT_REPAIR_MAX_SIMULATIONS = 8
LEGACY_REPAIR_CONTEXT_FAILURE = ('Repair planning failed: RepairPlanningBlocked: '
    'AI Repair context exceeds bounded evidence input; compile concise semantics')
REPAIR_OUTPUT_CONTRACT_FAILURE = ('Repair planning failed: RepairPlanningBlocked: '
    'AI Repair action must be test or stop')
RepairExecutor = Callable[[Path, dict, list[dict], int], list[dict]]

POST_SCHEDULE_STAGES = (
    "scout_seed",
    "batch_generation",
    "backtest",
    "triage",
    "repair",
)

SCOUT_SEED_REQUIRED_IMPORT_ARTIFACTS = ("candidates.csv",)
SCOUT_SEED_OPTIONAL_IMPORT_ARTIFACTS = (
    "all_alphas.jsonl",
    "simulation_events.jsonl",
    "run_errors.jsonl",
    "run_summary.md",
)


def import_scout_seed_artifacts(
    run_dir: str | Path,
    source_run_dir: str | Path,
    imported_at: str,
) -> dict[str, object]:
    """Input: active run dir, source run dir, timestamp. Output: import summary. Copy audited Scout/Seed artifacts into the active run."""
    target_root = Path(run_dir)
    source_root = Path(source_run_dir)
    if not target_root.exists() or not target_root.is_dir():
        raise ValueError("active workflow run directory does not exist")
    if not source_root.exists() or not source_root.is_dir():
        raise ValueError("source scout/seed run directory does not exist")
    if target_root.is_symlink():
        raise ValueError("active workflow run directory must not be a symlink")
    if source_root.is_symlink():
        raise ValueError("source scout/seed run directory must not be a symlink")
    if target_root.resolve() == source_root.resolve():
        raise ValueError("source scout/seed run must differ from the active workflow run")

    missing = [
        name
        for name in SCOUT_SEED_REQUIRED_IMPORT_ARTIFACTS
        if not (source_root / name).exists()
    ]
    outcome = research_outcome(source_root) if not (source_root / "candidates.csv").exists() else {}
    if missing and outcome.get("outcome") not in {"repairable_signal", "qualified", "no_signal"}:
        raise ValueError(f"missing required scout/seed artifact: {', '.join(missing)}")

    available_names = [
        name
        for name in (
            *SCOUT_SEED_REQUIRED_IMPORT_ARTIFACTS,
            *SCOUT_SEED_OPTIONAL_IMPORT_ARTIFACTS,
        )
        if (source_root / name).exists()
    ]
    import_namespace = (
        *SCOUT_SEED_REQUIRED_IMPORT_ARTIFACTS,
        *SCOUT_SEED_OPTIONAL_IMPORT_ARTIFACTS,
    )
    existing_targets = [name for name in import_namespace if (target_root / name).exists()]
    if existing_targets:
        raise ValueError(
            "target scout/seed artifact already exists: " + ", ".join(existing_targets)
        )
    for name in available_names:
        artifact_path = source_root / name
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise ValueError(f"source scout/seed artifact must be a regular file: {name}")

    candidate_count = _count_candidate_rows(source_root / "candidates.csv") if not missing else 0
    imported_artifacts: list[dict[str, object]] = []
    copied_paths: list[str] = []
    for name in available_names:
        source_path = source_root / name
        target_path = target_root / name
        shutil.copy2(source_path, target_path)
        copied_paths.append(str(target_path))
        imported_artifacts.append(
            {
                "name": name,
                "source_path": str(source_path),
                "target_path": str(target_path),
                "bytes": target_path.stat().st_size,
                "sha256": _sha256_file(target_path),
            }
        )

    stage_dir = target_root / "stages" / "scout_seed"
    stage_dir.mkdir(parents=True, exist_ok=True)
    provenance_path = stage_dir / "scout_seed_import.json"
    provenance = {
        "stage": "scout_seed",
        "mode": "artifact_import",
        "source_run_id": source_root.name,
        "source_run_dir": str(source_root),
        "target_run_id": target_root.name,
        "target_run_dir": str(target_root),
        "imported_at": imported_at,
        "candidate_count": candidate_count,
        "outcome": outcome.get("outcome", "legacy_candidates"),
        "imported_artifacts": imported_artifacts,
    }
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "stage": "scout_seed",
        "status": "imported",
        "source_run_id": source_root.name,
        "candidate_count": candidate_count,
        "outcome": outcome.get("outcome", "legacy_candidates"),
        "imported_artifacts": [item["name"] for item in imported_artifacts],
        "evidence_paths": [str(provenance_path), *copied_paths],
    }


def _count_candidate_rows(path: Path) -> int:
    """Input: candidates.csv path. Output: row count. Validate the minimal candidate identity columns."""
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = set(reader.fieldnames or [])
        required = {"alpha_id", "expression_hash"}
        if not required.issubset(fieldnames):
            raise ValueError("candidates.csv must include alpha_id and expression_hash columns")
        row_count = 0
        for row_number, row in enumerate(reader, start=1):
            row_count += 1
            alpha_id = str(row.get("alpha_id", "") or "").strip()
            expression_hash = str(row.get("expression_hash", "") or "").strip()
            if not alpha_id or not expression_hash:
                raise ValueError(
                    f"candidate row {row_number} must include alpha_id and expression_hash"
                )
        if row_count < 1:
            raise ValueError("candidates.csv must contain at least one candidate row")
        return row_count


def _sha256_file(path: Path) -> str:
    """Input: file path. Output: SHA-256 hex digest. Fingerprint imported artifacts."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def advance_post_schedule_stage(
    run_dir: str | Path, stage_name: str,
    repair_executor: RepairExecutor | None = None,
    repair_max_simulations: int = DEFAULT_REPAIR_MAX_SIMULATIONS,
    discovery_executor: Callable | None = None,
) -> dict[str, object]:
    """Input: run directory and post-schedule stage name. Output: stage summary. Complete from local artifacts or write a plan-only handoff."""
    if stage_name not in POST_SCHEDULE_STAGES:
        raise ValueError(f"unsupported post-schedule stage: {stage_name}")
    root = Path(run_dir)
    if stage_name == 'scout_seed':
        from wqb.research_seed_stage import preplanned_research_enabled
        if preplanned_research_enabled(root):
            try:
                from wqb.tree_runtime import verify_tree_results
                verify_tree_results(root)
            except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
                return dict(stage=stage_name, status='paused',
                            blocker='checked research results require completed tree: ' + str(error), evidence_paths=[])
    check_receipt_path = root / 'stages/backtest/check_recovery.json'
    if check_receipt_path.exists() and (root / 'all_alphas.jsonl').exists():
        saved_checks = json.loads(check_receipt_path.read_text(encoding='utf-8'))
        if (saved_checks.get('run_id') == root.name and saved_checks.get('status') == 'prepared'
                and saved_checks.get('output_sha256') == _sha256_file(root / 'all_alphas.jsonl')):
            from wqb.runtime_control import _write
            _write(check_receipt_path, {**saved_checks, 'status': saved_checks.get('publish_status', 'completed')})
    discovery_receipt_path = root / 'stages/batch_generation/discovery_execution.json'
    if discovery_receipt_path.exists() and (root / 'all_alphas.jsonl').exists():
        saved_discovery = json.loads(discovery_receipt_path.read_text(encoding='utf-8'))
        if (saved_discovery.get('run_id') == root.name and saved_discovery.get('children')
                and saved_discovery.get('output_sha256') == _sha256_file(root / 'all_alphas.jsonl')
                and saved_discovery.get('status') in {'prepared', 'paused'}):
            from wqb.runtime_control import _write
            _write(discovery_receipt_path, {**saved_discovery, 'status': 'completed', 'blocker': ''})
    outcome = research_outcome(root)
    artifacts = {key: value for key, value in outcome.items() if key != "rows"}
    required_paths = [root / "all_alphas.jsonl"]
    stage_dir = root / "stages" / stage_name
    stage_dir.mkdir(parents=True, exist_ok=True)
    blocker = research_evidence_blocker(root)
    if stage_name == "repair" and blocker == "checked research differs from its import receipt":
        repair_path = root / "stages" / "repair" / "repair_execution.json"
        import_path = root / "stages" / "scout_seed" / "scout_seed_import.json"
        if repair_path.is_file() and import_path.is_file():
            repair = json.loads(repair_path.read_text(encoding="utf-8"))
            imported = json.loads(import_path.read_text(encoding="utf-8"))
            source = next((item for item in imported.get("imported_artifacts", [])
                           if item.get("name") == "all_alphas.jsonl"), {})
            if discovery_receipt_path.exists():
                discovery_receipt = json.loads(discovery_receipt_path.read_text(encoding='utf-8'))
                if (discovery_receipt.get('run_id') == root.name and discovery_receipt.get('status') == 'completed'
                        and discovery_receipt.get('input_sha256') == source.get('sha256')):
                    source = {**source, 'sha256': discovery_receipt.get('output_sha256')}
            check_path = root / 'stages/backtest/check_recovery.json'
            if check_path.exists():
                check_receipt = json.loads(check_path.read_text(encoding='utf-8'))
                if (check_receipt.get('run_id') == root.name and check_receipt.get('status') == 'completed'
                        and check_receipt.get('input_sha256') == source.get('sha256')):
                    source = {**source, 'sha256': check_receipt.get('output_sha256')}
            can_resume = repair.get("recovery_eligible") is True or (
                repair.get("status") == "running" and getattr(repair_executor, "supports_durable_recovery", False))
            append_only = False
            if repair.get('scheduler_version') == 1 and getattr(repair_executor, 'supports_ai_planning', False) is True:
                from wqb.repair_scheduler import _verified_prefix, cached_collision_children
                append_only = _verified_prefix(root / 'all_alphas.jsonl', repair, root)
                blocked_attempts = [a for a in repair.get('attempts', []) if a.get('phase') == 'blocked']
                from wqb.repair_unknown import quarantine_source, local_completion_source
                if (append_only and repair.get('status') == 'paused' and blocked_attempts
                        and getattr(repair_executor, 'supports_durable_recovery', False) is True
                        and all(quarantine_source(root, a) is not None or local_completion_source(root, a) is not None
                            or cached_collision_children(root, a, outcome['rows']) for a in blocked_attempts)):
                    can_resume = True
                if (append_only and repair.get('status') == 'paused' and blocked_attempts
                        and all(cached_collision_children(root, a, outcome['rows']) for a in blocked_attempts)):
                    can_resume = True
                # Re-enter only the fixed pre-simulation planning fault; never relax digest lineage.
                pattern = '(?:' + '|'.join(re.escape(message) for message in
                    (LEGACY_REPAIR_CONTEXT_FAILURE, REPAIR_OUTPUT_CONTRACT_FAILURE)) + ')'
                if (append_only and repair.get('status') == 'paused' and not blocked_attempts
                        and getattr(repair_executor, 'supports_durable_recovery', False) is True
                        and all(a.get('phase') in {'checked', 'waiting'} for a in repair.get('attempts', []))
                        and re.fullmatch(pattern + '(?:; ' + pattern + ')*', str(repair.get('blocker', '')))):
                    can_resume = True
            if (repair.get("run_id") == root.name and can_resume
                    and repair.get("input_sha256") == source.get("sha256")
                    and (repair.get("last_sha256") == _sha256_file(root / "all_alphas.jsonl") or append_only)):
                blocker = ""
    if not blocker and stage_name == 'backtest' and outcome['outcome'] == 'pending_review':
        recover_checks = getattr(discovery_executor, 'recover_checks', None)
        if callable(recover_checks):
            try:
                recover_checks(root)
                outcome = research_outcome(root)
                artifacts = {key: value for key, value in outcome.items() if key != 'rows'}
            except RepairRecoveryPending as exc:
                blocker = str(exc)
    if outcome["outcome"] == "missing_results":
        blocker = "checked research results required: all_alphas.jsonl (candidates.csv alone is insufficient)"
    elif outcome['outcome'] == 'pending_review' and not blocker:
        blocker = f"existing Alpha checks pending: {outcome['counts']['pending_review']} identities require check recovery (results file exists)"
    repair_result = {}
    discovery = {}
    if not blocker and stage_name == 'batch_generation' and discovery_executor is not None:
        discovery = _execute_discovery(root, outcome, discovery_executor)
        blocker = str(discovery.get('blocker', ''))
        if not blocker:
            outcome = research_outcome(root)
            artifacts = {key: value for key, value in outcome.items() if key != 'rows'}
    if not blocker and stage_name == "repair" and outcome["counts"]["repairable_signal"]:
        repair_result = _execute_repair(root, outcome, repair_executor, repair_max_simulations)
        blocker = str(repair_result.get("blocker", ""))
        if not blocker:
            outcome = research_outcome(root)
            artifacts = {key: value for key, value in outcome.items() if key != "rows"}
    if blocker:
        handoff_path = stage_dir / f"{stage_name}_handoff.json"
        handoff_path.write_text(
            json.dumps(
                {
                    "stage": stage_name,
                    "mode": "plan_only",
                    "blocker": blocker,
                    "missing_artifacts": [str(path) for path in required_paths if not path.exists()],
                    "artifact_summary": artifacts,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "stage": stage_name,
            "status": "paused",
            "blocker": blocker,
            "evidence_paths": [str(handoff_path)],
        }
    execution = repair_result.get("execution", "skipped") if stage_name == "repair" else "reused_checked_results"
    if stage_name == 'batch_generation' and discovery:
        execution = ('bounded_variants_exhausted' if discovery.get('discovery_exhausted') else
                     'executed' if discovery.get('status') == 'completed' else 'skipped')
    next_stage = ("candidate_gate" if outcome["counts"]["hard_pass"] else "research_record_sync") if stage_name == "repair" else ""
    if stage_name == "repair":
        _write_qualified_candidates(root, outcome["rows"])
    summary_path = stage_dir / f"{stage_name}_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "stage": stage_name,
                "run_id": root.name,
                "mode": "local_artifacts",
                "artifact_summary": artifacts,
                "source_artifacts": [str(path) for path in required_paths],
                "execution": execution,
                "reason": "bounded Discovery results verified" if stage_name == 'batch_generation' and execution == 'executed' else
                          "no novel bounded Discovery variants; continue to measured-seed Repair" if execution == 'bounded_variants_exhausted' else
                          "bounded repair results verified" if execution == "executed" else
                          "no repairable signals" if stage_name == "repair" else
                          "checked research reused; no new simulations executed by this stage",
                "outcome": outcome["outcome"],
                "checked_rows": outcome["rows"],
                "source_sha256": _sha256_file(root / "all_alphas.jsonl"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "stage": stage_name,
        "status": "completed",
        **artifacts,
        "execution": execution,
        "next_stage": next_stage,
        "checked_rows": outcome["rows"],
        "repair_attempts": repair_result.get("attempts", []),
        "evidence_paths": [str(summary_path), *[str(path) for path in required_paths]],
    }


def research_evidence_blocker(root: Path) -> str:
    """Input: run Path. Output: blocker str. Bind reused research to import identity and content."""
    provenance_path = root / "stages" / "scout_seed" / "scout_seed_import.json"
    if not provenance_path.exists():
        return ""
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if provenance.get("target_run_id") != root.name:
        return "research import receipt belongs to another run"
    imported = next((item for item in provenance.get("imported_artifacts", [])
                     if item.get("name") == "all_alphas.jsonl"), None)
    if not imported or not (root / "all_alphas.jsonl").is_file():
        return "checked research import evidence is missing"
    digest = _sha256_file(root / "all_alphas.jsonl")
    check_path = root / 'stages/backtest/check_recovery.json'
    if check_path.exists():
        checks = json.loads(check_path.read_text(encoding='utf-8'))
        if (checks.get('run_id') == root.name and checks.get('status') in {'prepared', 'completed', 'paused'}
                and checks.get('output_sha256') == digest):
            digest = str(checks.get('input_sha256', ''))
    if digest == imported.get("sha256"):
        return ""
    discovery_path = root / 'stages/batch_generation/discovery_execution.json'
    if discovery_path.exists():
        discovery = json.loads(discovery_path.read_text(encoding='utf-8'))
        if (discovery.get('run_id') == root.name and discovery.get('status') == 'completed'
                and discovery.get('input_sha256') == imported.get('sha256')):
            if discovery.get('output_sha256') == digest:
                return ''
            imported = {**imported, 'sha256': discovery.get('output_sha256')}
    if check_path.exists():
        checks = json.loads(check_path.read_text(encoding='utf-8'))
        if (checks.get('run_id') == root.name and checks.get('status') == 'completed'
                and checks.get('input_sha256') == imported.get('sha256')):
            imported = {**imported, 'sha256': checks.get('output_sha256')}
    repair_path = root / "stages" / "repair" / "repair_execution.json"
    if repair_path.exists():
        repair = json.loads(repair_path.read_text(encoding="utf-8"))
        if (repair.get("run_id") == root.name and repair.get("status") == "completed"
                and repair.get("input_sha256") == imported.get("sha256")
                and repair.get("output_sha256") == digest):
            return ""
    return "checked research differs from its import receipt"


def _write_qualified_candidates(root: Path, rows: list[dict]) -> None:
    """Input: run Path, checked dict rows. Output: None. Append only clean qualified identities."""
    qualified = [row for row in rows if row["hard_pass"] is True and not row["failed"] and not row["pending"]]
    if not qualified:
        return
    path = root / "candidates.csv"
    existing = []
    fields = ["alpha_id", "expression_hash"]
    if path.exists():
        _count_candidate_rows(path)
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames
            existing = list(reader)
    identities = {(row["alpha_id"], row["expression_hash"]) for row in existing}
    additions = [row for row in qualified if (row["alpha_id"], row["expression_hash"]) not in identities]
    if not additions:
        return
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if not existing:
            writer.writeheader()
        writer.writerows(additions)


def _execute_discovery(root: Path, outcome: dict, executor: Callable) -> dict:
    """Input: run Path, research outcome, executor. Output: receipt. Lock a measured seed and execute bounded Discovery once."""
    from wqb.runtime_control import _write
    from wqb.research_seed_stage import preplanned_research_enabled, prepare_seed_selection
    if preplanned_research_enabled(root):
        selection = prepare_seed_selection(root, outcome['rows'])
        return dict(status='completed', execution='preplanned_seed_selection',
                    seed_count=len(selection['selected']), discovery_exhausted=not selection['selected'])
    path = root / 'stages/batch_generation/discovery_execution.json'
    current = _sha256_file(root / 'all_alphas.jsonl')
    receipt = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if receipt.get('status') == 'completed' and receipt.get('output_sha256') == current:
        return receipt
    parents = [row for row in outcome['rows'] if row.get('benchmark_label') == 'repairable_signal']
    if not parents or outcome['counts']['hard_pass']:
        return {'status': 'skipped'}
    if not receipt:
        parent = max(parents, key=lambda row: float(row.get('metrics', {}).get('sharpe', 0)))
        receipt = {'run_id': root.name, 'status': 'running', 'input_sha256': current, 'parent': parent}
        _write(root / 'stages/batch_generation/seed.json',
               {'parent': parent, 'reason': 'Measured repairable signal, ranked by Sharpe; not candidate approval.'})
        _write(path, receipt)
    if receipt.get('run_id') != root.name or receipt.get('input_sha256') != current:
        return {'blocker': 'discovery input differs from immutable seed evidence'}
    try:
        children = validate_checked_rows(executor(root, receipt['parent']))
        if not children or len(children) > 30:
            raise ValueError('Discovery requires bounded checked children')
        parent = receipt['parent']
        identities = {(row['alpha_id'], row['expression_hash']) for row in outcome['rows']}
        for child in children:
            if (child.get('parent_alpha_id') != parent['alpha_id'] or
                    child.get('parent_expression_hash') != parent['expression_hash'] or
                    (child['alpha_id'], child['expression_hash']) in identities):
                raise ValueError('Discovery child lineage/identity invalid')
            identities.add((child['alpha_id'], child['expression_hash']))
        if _sha256_file(root / 'all_alphas.jsonl') != current:
            raise ValueError('Discovery executor modified original research')
        output = (root / 'all_alphas.jsonl').read_text(encoding='utf-8').rstrip() + '\n'
        output += ''.join(json.dumps(row) + '\n' for row in children)
        receipt.update(status='prepared', children=children, blocker='', recovery_eligible=False,
                       output_sha256=hashlib.sha256(output.encode()).hexdigest())
        receipt.pop('rate_limit_retry_at', None)
        receipt.pop('rate_limit_source_run_dir', None)
        _write(path, receipt)
        temporary = root / 'stages/batch_generation/merged_alphas.jsonl'
        temporary.write_text(output, encoding='utf-8', newline='')
        temporary.replace(root / 'all_alphas.jsonl')
        receipt.update(status='completed', output_sha256=_sha256_file(root / 'all_alphas.jsonl'))
        _write(path, receipt)
        return receipt
    except Exception as exc:
        from wqb.research_planning import ResearchVariantsExhausted
        from wqb.runtime_control import DailyBudgetExhausted
        if isinstance(exc, DailyBudgetExhausted):
            _write(path, receipt)
            raise
        if isinstance(exc, ResearchVariantsExhausted):
            receipt.update(status='completed', output_sha256=current, children=[], blocker='', recovery_eligible=False,
                           discovery_exhausted=True, reason=str(exc))
            receipt.pop('rate_limit_retry_at', None)
            receipt.pop('rate_limit_source_run_dir', None)
            _write(path, receipt)
            return receipt
        receipt.update(status='paused', blocker=f'discovery recovery required: {type(exc).__name__}: {exc}',
                       recovery_eligible=isinstance(exc, RepairRecoveryPending))
        if isinstance(exc, RepairRateLimited):
            receipt.update(rate_limit_retry_at=exc.retry_at, rate_limit_source_run_dir=exc.source_run_dir)
        _write(path, receipt)
        return receipt


def _execute_repair(root: Path, outcome: dict, executor: RepairExecutor | None, maximum: int) -> dict:
    """Input: run Path, outcome dict, optional executor, int budget. Output: receipt dict. Execute bounded repair once."""
    path = root / "stages" / "repair" / "repair_execution.json"
    from wqb.research_seed_stage import preplanned_research_enabled, prepare_seed_selection
    if preplanned_research_enabled(root):
        selection = prepare_seed_selection(root, outcome['rows'])
        if not selection['seed_rows']:
            return dict(status='completed', execution='no_eligible_seeds', blocker='')
        outcome = {**outcome, 'rows': selection['seed_rows']}
    if executor is None:
        return {"blocker": "repair executor is required for checked repairable signals"}
    if type(maximum) is not int or maximum < 1:
        return {"blocker": "repair simulation budget must be a positive integer"}
    if getattr(executor, 'supports_ai_planning', False) is True:
        from wqb.repair_scheduler import execute_repair_round
        return execute_repair_round(root, outcome, executor, maximum)
    all_parents = [row for row in outcome["rows"] if row["benchmark_label"] == "repairable_signal"]
    current_sha = _sha256_file(root / "all_alphas.jsonl")
    if path.exists():
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if (receipt.get("run_id") == root.name and receipt.get("status") == "completed"
                and receipt.get("output_sha256") == current_sha):
            return {**receipt, "execution": "executed"}
        recoverable = receipt.get("recovery_eligible") is True or (
            receipt.get("status") == "running" and getattr(executor, "supports_durable_recovery", False)
        )
        if (receipt.get("run_id") != root.name or receipt.get("max_simulations") != maximum
                or receipt.get("last_sha256", receipt.get("input_sha256")) != current_sha
                or not recoverable):
            return {"blocker": "repair attempt requires recovery; automatic resubmission is disabled"}
        parent_keys = {(row["alpha_id"], row["expression_hash"]): row for row in all_parents}
        parents = [parent_keys.get(tuple(key)) for key in receipt.get("parent_keys", [])]
        if not parents or any(parent is None for parent in parents):
            return {"blocker": "repair parent evidence changed during recovery"}
        receipt["status"] = "running"
        receipt["recovery_eligible"] = False
        receipt.pop("blocker", None)
    else:
        parents = all_parents
        receipt = {"run_id": root.name, "status": "running", "input_sha256": current_sha,
                   "last_sha256": current_sha, "max_simulations": maximum, "attempts": [],
                   "parent_keys": [[row["alpha_id"], row["expression_hash"]] for row in parents]}
    completed_count = sum(attempt.get("status") == "completed" for attempt in receipt["attempts"])
    if any(attempt.get("status") != "completed" for attempt in receipt["attempts"][:completed_count]):
        return {"blocker": "repair attempt order is inconsistent"}
    remaining = maximum - sum(int(attempt["max_simulations"]) for attempt in receipt["attempts"][:completed_count])
    known = checked_research_rows(root)
    for index, parent in enumerate(parents):
        if index < completed_count:
            continue
        if not remaining:
            break
        allowance = (int(receipt["attempts"][index]["max_simulations"])
                     if index < len(receipt["attempts"]) else max(1, remaining // (len(parents) - index)))
        summary = CheckSummary(parent["alpha_id"], False,
                               [CheckItem(str(item.get("name", "") if isinstance(item, dict) else item), "FAIL")
                                for item in parent["failed"]], [], [], parent.get("metrics", {}))
        actions = [asdict(action) for action in actions_for_check_summary(parent["expression_hash"], summary)]
        if index < len(receipt["attempts"]):
            attempt = receipt["attempts"][index]
            if (attempt.get("parent_alpha_id") != parent["alpha_id"] or
                    attempt.get("parent_expression_hash") != parent["expression_hash"] or
                    attempt.get("actions") != actions):
                return {"blocker": "repair plan changed during recovery"}
        else:
            attempt = {"parent_alpha_id": parent["alpha_id"], "parent_expression_hash": parent["expression_hash"],
                       "max_simulations": allowance, "actions": actions, "status": "started", "children": []}
            receipt["attempts"].append(attempt)
        path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        try:
            returned = executor(root, json.loads(json.dumps(parent)), actions, allowance)
            children = validate_checked_rows(returned) if isinstance(returned, list) else []
            existing_ids = {(row["alpha_id"], row["expression_hash"]) for row in known}
            if not children or len(children) != len(returned) or len(children) > allowance:
                raise ValueError("repair executor must return nonempty bounded checked child rows")
            for child in children:
                if (child.get("parent_alpha_id") != parent["alpha_id"]
                        or research_benchmark_label(child, root) == "pending_review"
                        or child.get("parent_expression_hash", parent["expression_hash"]) != parent["expression_hash"]
                        or child["alpha_id"] == parent["alpha_id"]
                        or child["expression_hash"] == parent["expression_hash"]
                        or (child["alpha_id"], child["expression_hash"]) in existing_ids):
                    raise ValueError("repair child must have fresh identity, matching parent and completed checks")
                child["parent_expression_hash"] = parent["expression_hash"]
            current = checked_research_rows(root)
            if not all(row in current for row in known):
                raise ValueError("repair executor changed existing checked research")
            with (root / "all_alphas.jsonl").open("a", encoding="utf-8") as handle:
                for child in children:
                    saved = next((row for row in current if (row["alpha_id"], row["expression_hash"]) ==
                                  (child["alpha_id"], child["expression_hash"])), None)
                    if saved is not None:
                        if {**saved, "parent_expression_hash": parent["expression_hash"]} != child:
                            raise ValueError("repair return disagrees with persisted child")
                    else:
                        handle.write(json.dumps(child) + "\n")
            known = checked_research_rows(root)
            attempt.update(status="completed", children=children)
            receipt["last_sha256"] = _sha256_file(root / "all_alphas.jsonl")
        except Exception as exc:
            receipt.update(status="paused", blocker=f"repair recovery required: {type(exc).__name__}: {exc}",
                           recovery_eligible=isinstance(exc, (RepairRecoveryPending, RuntimePaused)))
            for key in ('rate_limit_retry_at', 'rate_limit_source_run_dir', 'progress_retry_at', 'progress_source_run_dir'):
                receipt.pop(key, None)
            if isinstance(exc, RepairRateLimited):
                receipt["rate_limit_retry_at"] = exc.retry_at
                receipt["rate_limit_source_run_dir"] = exc.source_run_dir
            elif isinstance(exc, RepairProgressPending):
                receipt['progress_retry_at'] = exc.next_poll_at
                receipt['progress_source_run_dir'] = exc.source_run_dir
            path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            if isinstance(exc, RuntimePaused):
                raise
            return receipt
        remaining -= allowance
        path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    receipt.update(status="completed", recovery_eligible=False, output_sha256=_sha256_file(root / "all_alphas.jsonl"),
                   execution="executed", budget_reserved=maximum - remaining,
                   unattempted_parent_count=len(parents) - len(receipt["attempts"]))
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: rows. Read valid JSONL rows."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: dict rows list. Read JSONL and reject non-object rows."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path} line {line_number} must be a JSON object")
        rows.append(row)
    return rows


def _validate_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    """Input: optional scope dict. Output: normalized scope dict. Validate concrete workflow scheduling scope."""
    if not isinstance(scope, dict):
        raise ValueError("selected workflow scope must include region, delay, and universe")
    try:
        normalized = {
            "region": str(scope["region"]).strip().upper(),
            "delay": int(scope["delay"]),
            "universe": str(scope["universe"]).strip().upper(),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("selected workflow scope must include region, delay, and universe") from exc
    if not normalized["region"] or normalized["delay"] < 0 or not normalized["universe"]:
        raise ValueError("selected workflow scope must include region, delay, and universe")
    return normalized


def _row_matches_scope(row: dict[str, Any], scope: dict[str, Any]) -> bool:
    """Input: ledger row and scope dict. Output: bool. Match exact available scopes before legacy fields."""
    if "available_scopes" in row:
        return any(
            isinstance(item, dict)
            and str(item.get("region", "")).upper() == scope["region"]
            and int(item.get("delay", -1)) == scope["delay"]
            and str(item.get("universe", "")).upper() == scope["universe"]
            for item in row.get("available_scopes", [])
        )
    try:
        return (
            str(row.get("region", "")).upper() == scope["region"]
            and int(row.get("delay", -1)) == scope["delay"]
            and str(row.get("universe", "")).upper() == scope["universe"]
        )
    except (TypeError, ValueError):
        return False


def _require_start_snapshot_readiness(knowledge: Path, scope: dict[str, Any], *, operational_snapshot: dict | None = None) -> None:
    """Input: root Path, scope dict, optional paired snapshot dict. Output: None; reject all unresolved readiness blockers."""
    report = evaluate_run_readiness(
        knowledge,
        mode="research",
        batch_size=30,
        live_api_enabled=True,
        region=str(scope["region"]),
        delay=int(scope["delay"]),
        universe=str(scope["universe"]),
    )
    from wqb.run_readiness import resolve_operational_readiness
    report = resolve_operational_readiness(report, operational_snapshot)
    issues = [issue for issue in report.issues if issue.level == 'block']
    if issues or report.blocked:
        codes = ", ".join(issue.code for issue in issues) or "blocked"
        raise ValueError(f"start snapshot readiness blocked: {codes}")


def _freeze_operational_resource_context(knowledge: Path, receipt: dict, templates: list[dict],
                                         operators: list[dict], ledger: list[dict], scope: dict) -> dict:
    """Input: vault Path/release/resources/scope dicts and lists. Output: validated paired snapshot patch; read-only.

    Reuse immutable release source_refs and template experiment_paths. Read full
    UTF-8 bytes through existing path/source guards and compare compiler source
    metadata with the actual index before permitting frozen operational use.
    """
    from wqb.semantic_publication import _safe_path, _verify_sources, _load, validate_semantic_receipt
    from wqb.semantic_compilation import _material
    from wqb.hypothesis_selection import validate_operational_resource_context, OPERATIONAL_CONTEXT_VERSION
    from wqb.resource_evidence import resource_contract_version
    if not receipt.get('release_id') or resource_contract_version(receipt) != 2:
        raise ValueError('paired_scout requires reviewed immutable resource v2 release')
    refs = receipt['manifest']['source_refs']
    _verify_sources(knowledge, refs)
    source_files = {}
    for ref in refs:
        raw = _safe_path(knowledge, ref['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref['sha256']:
            raise ValueError('paired_scout consumed source bytes digest mismatch')
        source_files[ref['path']] = raw.decode('utf-8')
    release_files = {}
    for name, value in {**receipt['paths'], 'manifest': receipt['manifest_path']}.items():
        release_files[name] = Path(value).read_bytes().decode('utf-8')
    index_rows = _read_jsonl_objects(knowledge / 'machine/source_index.jsonl')
    fields = []
    for relative in sorted({path for row in templates for path in row.get('experiment_paths', [])}):
        if relative not in source_files:
            raise ValueError('paired_scout experiment attachment missing from release')
        doc = _load(source_files[relative].encode('utf-8'))
        try:
            frozen_scope = doc['compiler_input']['scope']
            if any(key not in frozen_scope or type(value) is not type(frozen_scope[key]) or value != frozen_scope[key]
                   for key, value in scope.items()):
                raise ValueError('paired_scout reviewed experiment scope differs from requested context')
            scope = dict(frozen_scope)
            resources = doc['compiler_input']['resources']
            for path, declared in resources['source_index'].items():
                matches = [row for row in index_rows if row.get('path') == path]
                if len(matches) != 1:
                    raise ValueError('paired_scout missing or ambiguous indexed source')
                checked, text = _material(knowledge, matches[0])
                if (text != source_files.get(path) or any(checked.get(key) != value for key, value in declared.items())):
                    raise ValueError('paired_scout indexed source metadata/bytes mismatch')
            for row in resources['field_rows']:
                matches = [item for item in ledger if item.get('dataset_id') == row.get('dataset_id')
                           and item.get('field_id') == row.get('field_id')]
                if len(matches) != 1 or matches[0] != row:
                    raise ValueError('paired_scout compiler field differs from exact local data ledger')
                if not (_row_has_measured_platform_coverage(row) and _row_has_positive_coverage(row)
                        and _row_has_source_date(row)):
                    raise ValueError('paired_scout field requires measured dated coverage')
                if row not in fields:
                    fields.append(row)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError('paired_scout missing compiler/source context in experiment attachment') from error
    if len(fields) > START_SNAPSHOT_DATA_LEDGER_ROW_LIMIT:
        raise ValueError('paired_scout whole dependencies exceed data ledger row limit')
    patch = dict(resource_contract_version=2, hypothesis_binding_version=2, research_policy=dict(paired_scout=True),
                 selected_scope=dict(scope), data_ledger_rows=fields, template_rows=templates, operator_rows=operators,
                 compatible_template_ids=sorted(row['template_id'] for row in templates), semantic_release=receipt,
                 operational_resource_context=dict(schema_version=OPERATIONAL_CONTEXT_VERSION,
                     release_files=release_files, source_files=source_files))
    validate_operational_resource_context(patch)
    validate_semantic_receipt(knowledge, receipt)
    # Recheck original extracts/repairs as well as full bytes after all reads.
    _verify_sources(knowledge, refs)
    return patch


def _row_has_positive_coverage(row: dict[str, Any]) -> bool:
    """Input: ledger row. Output: bool. Validate measured row coverage is positive."""
    try:
        return float(row.get("coverage", 0.0)) > 0.0
    except (TypeError, ValueError):
        return False


def _row_has_source_date(row: dict[str, Any]) -> bool:
    """Input: ledger row. Output: bool. Validate raw-source date shape for immutable snapshots."""
    try:
        date.fromisoformat(str(row.get("source_updated_at", "")))
    except ValueError:
        return False
    return True


def _row_has_measured_platform_coverage(row: dict[str, Any]) -> bool:
    """Input: ledger row. Output: bool. Check whether the row is certified raw platform coverage."""
    return row.get("source_quality") == "platform_raw_capture" and row.get("coverage_status") == "measured_raw"


def _row_template_matches(
    option: dict[str, Any],
    scope: dict[str, Any],
    row: dict[str, Any],
    templates: list[Any],
) -> set[str]:
    """Input: option, scope, ledger row, templates. Output: matching template IDs for this data row."""
    row_template_ids = row.get("compatible_template_ids")
    if not isinstance(row_template_ids, list) or not row_template_ids:
        return set()
    incentive = str(option.get("primary_incentive", ""))
    selected = select_templates_for_data(
        templates,
        data_ledger_record_from_dict(row),
        incentive,
        len(templates),
        region=scope["region"],
        delay=scope["delay"],
        universe=scope["universe"],
    )
    return {str(item) for item in row_template_ids} & {template.template_id for template in selected}


def _select_start_snapshot_rows(
    option: dict[str, Any],
    scope: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    template_rows: list[dict[str, Any]],
    operator_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, int]]:
    """Input: option, scope, ledger rows, templates. Output: bounded snapshot rows, template IDs, and row counts."""
    if not ledger_rows:
        raise ValueError("start snapshot data ledger rows are required")
    if not template_rows:
        raise ValueError("start snapshot template rows are required")
    if any(row.get('binding_version') == 2 for row in template_rows):
        return _select_hypothesis_snapshot_rows(scope, ledger_rows, template_rows, operator_rows or [])
    templates = [template_record_from_dict(row) for row in template_rows]
    compatible_ids: set[str] = set()
    selected_rows: list[dict[str, Any]] = []
    counts = {
        "matching_data_ledger_row_count": len(ledger_rows),
        "measured_platform_row_count": 0,
        "positive_coverage_row_count": 0,
        "source_dated_row_count": 0,
        "template_id_row_count": 0,
        "template_matched_row_count": 0,
    }
    for row in ledger_rows:
        if not _row_matches_scope(row, scope):
            raise ValueError("start snapshot data ledger row does not match selected scope")
        if not _row_has_measured_platform_coverage(row):
            continue
        counts["measured_platform_row_count"] += 1
        if not _row_has_positive_coverage(row):
            continue
        counts["positive_coverage_row_count"] += 1
        if not _row_has_source_date(row):
            continue
        counts["source_dated_row_count"] += 1
        row_template_ids = row.get("compatible_template_ids")
        if not isinstance(row_template_ids, list) or not row_template_ids:
            continue
        counts["template_id_row_count"] += 1
        matching = _row_template_matches(option, scope, row, templates)
        if not matching:
            continue
        counts["template_matched_row_count"] += 1
        compatible_ids.update(matching)
        if len(selected_rows) < START_SNAPSHOT_DATA_LEDGER_ROW_LIMIT:
            selected_rows.append(dict(row))
    if counts["measured_platform_row_count"] == 0:
        raise ValueError("start snapshot data ledger rows must be measured platform coverage")
    if counts["positive_coverage_row_count"] == 0:
        raise ValueError("start snapshot data ledger rows must have positive measured coverage")
    if counts["source_dated_row_count"] == 0:
        raise ValueError("start snapshot data ledger rows must include source_updated_at")
    if counts["template_id_row_count"] == 0:
        raise ValueError("start snapshot data ledger rows must include compatible template IDs")
    if counts["template_matched_row_count"] == 0:
        raise ValueError("start snapshot has no compatible templates for measured ledger rows")
    return selected_rows, sorted(compatible_ids), counts


def _read_start_semantic_pair(knowledge: Path) -> tuple[dict, list[dict], list[dict]]:
    """Input: knowledge Path. Output: receipt/templates/operators tuple. Hash consumed bytes before decoding a paired read."""
    from wqb.semantic_publication import read_semantic_release, validate_semantic_receipt
    receipt = read_semantic_release(knowledge)
    consumed = {}
    for name in ('template_library', 'operator_ledger'):
        path = Path(receipt['paths'][name])
        data = path.read_bytes() if path.exists() else None
        digest = hashlib.sha256(data).hexdigest() if data is not None else None
        if digest != receipt['digests'][name]:
            raise ValueError('semantic consumed bytes digest mismatch: ' + name)
        consumed[name] = data
    # Legacy files can change between reads; immutable generations keep their selected receipt.
    validate_semantic_receipt(knowledge, receipt)
    decoded = {}
    for name, data in consumed.items():
        rows = [json.loads(line) for line in (data or b'').decode('utf-8').splitlines() if line.strip()]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError('semantic snapshot requires JSONL objects')
        decoded[name] = rows
    return receipt, decoded['template_library'], decoded['operator_ledger']


def _select_hypothesis_snapshot_rows(scope: dict, ledger_rows: list[dict], templates: list[dict],
                                     operators: list[dict]) -> tuple[list[dict], list[str], dict]:
    """Input: scope/raw fields/templates/operators. Output: whole dependency rows, executable IDs, counts. Never truncate slots."""
    from wqb.template_binding import bind_template, TemplateBindingError
    from wqb.semantic_contracts import semantic_fields_from_dict
    from wqb.hypothesis_selection import enumerate_hypothesis_bindings, rejection_reason, MAX_REJECTION_SAMPLES
    eligible = [row for row in ledger_rows if _row_matches_scope(row, scope)
                and _row_has_measured_platform_coverage(row) and _row_has_positive_coverage(row)
                and _row_has_source_date(row)]
    chosen, identities, compatible = [], set(), []
    quality = dict(template_attempt_count=0, template_pass_count=0, binding_attempt_count=0, binding_pass_count=0, rejections=[])
    for template in sorted(templates, key=lambda row: (str(row.get('template_id', '')), str(row.get('hypothesis_version', '')))):
        if template.get('binding_version') != 2 or template.get('semantic_status') != 'reviewed':
            continue
        quality['template_attempt_count'] += 1
        try:
            semantic_fields_from_dict(template)
            for key, plural in [('region', 'regions'), ('delay', 'delays'), ('universe', 'universes')]:
                allowed = template.get('compatible_' + plural, [])
                if allowed and scope[key] not in allowed:
                    raise ValueError('template excludes selected scope')
            report = {}
            groups = enumerate_hypothesis_bindings(template, eligible, operators, scope, report=report)
            for key in ('binding_attempt_count', 'binding_pass_count'):
                quality[key] += report[key]
            quality['rejections'].extend(report['rejections'][:max(0, MAX_REJECTION_SAMPLES - len(quality['rejections']))])
        except (TemplateBindingError, ValueError, TypeError, KeyError) as exc:
            if len(quality['rejections']) < MAX_REJECTION_SAMPLES:
                quality['rejections'].append(rejection_reason('template_unexecutable', str(template.get('template_id')) + ': ' + str(exc)))
            continue
        passed = False
        for bound in groups:
            required = {(item['dataset_id'], item['field_id']) for item in bound['bindings'].values()}
            additional = [row for row in eligible if (row.get('dataset_id'), row.get('field_id')) in required - identities]
            if len(chosen) + len(additional) > START_SNAPSHOT_DATA_LEDGER_ROW_LIMIT:
                if len(quality['rejections']) < MAX_REJECTION_SAMPLES:
                    quality['rejections'].append(rejection_reason('dependency_row_limit', str(template.get('template_id')) + ': whole group does not fit'))
                continue
            chosen.extend(additional)
            identities.update(required)
            compatible.append(template['template_id'])
            passed = True
        quality['template_pass_count'] += int(passed)
    if not compatible:
        raise ValueError('start snapshot has no executable whole hypothesis binding within dependencies/row limit: ' + json.dumps(quality))
    counts = dict(matching_data_ledger_row_count=len(ledger_rows), measured_platform_row_count=len(eligible),
                  positive_coverage_row_count=len(eligible), source_dated_row_count=len(eligible),
                  template_id_row_count=len(chosen), template_matched_row_count=len(chosen), hypothesis_quality=quality)
    return chosen, sorted(set(compatible)), counts


def _validate_start_artifact_rows(
    option: dict[str, Any],
    scope: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    template_rows: list[dict[str, Any]],
) -> list[str]:
    """Input: option, scope, ledger rows, template rows. Output: compatible template IDs. Revalidate start gates."""
    if not ledger_rows:
        raise ValueError("start snapshot data ledger rows are required")
    if not template_rows:
        raise ValueError("start snapshot template rows are required")
    templates = [template_record_from_dict(row) for row in template_rows]
    compatible_ids: set[str] = set()
    for row in ledger_rows:
        if not _row_matches_scope(row, scope):
            raise ValueError("start snapshot data ledger row does not match selected scope")
        if not _row_has_measured_platform_coverage(row):
            raise ValueError("start snapshot data ledger rows must be measured platform coverage")
        if not _row_has_positive_coverage(row):
            raise ValueError("start snapshot data ledger rows must have positive measured coverage")
        if not _row_has_source_date(row):
            raise ValueError("start snapshot data ledger rows must include source_updated_at")
        row_template_ids = row.get("compatible_template_ids")
        if not isinstance(row_template_ids, list) or not row_template_ids:
            raise ValueError("start snapshot data ledger rows must include compatible template IDs")
        matching = _row_template_matches(option, scope, row, templates)
        if not matching:
            raise ValueError("start snapshot has no compatible templates for a measured ledger row")
        compatible_ids.update(matching)
    return sorted(compatible_ids)


def create_start_snapshot(
    knowledge_root: str | Path,
    selected_option_id: str,
    selected_scope: dict[str, Any] | None,
    *, research_policy: dict | None = None,
) -> dict[str, Any]:
    """Input: root str/Path, option ID str, optional scope/policy dicts. Output: immutable snapshot dict; paired defaults off."""
    from wqb.hypothesis_selection import paired_scout_enabled
    paired = paired_scout_enabled(research_policy)
    knowledge = Path(knowledge_root)
    options_path = existing_decision_artifact_path(
        knowledge,
        "research_option_cards.jsonl",
    )
    options = read_option_card_jsonl(options_path)
    selected = next((row for row in options if str(row.get("option_id", "")) == str(selected_option_id)), None)
    if not options:
        raise ValueError("no research option cards found")
    if selected is None:
        raise ValueError(f"selected research option not found: {selected_option_id}")
    if selected_scope is None:
        region, delay, universe = _scope_from_option(selected)
        scope = _validate_scope({"region": region, "delay": delay, "universe": universe})
    else:
        scope = _validate_scope(selected_scope)
    if not paired:
        _require_start_snapshot_readiness(knowledge, scope)
    ledger_rows = [
        row
        for row in _read_jsonl_objects(data_ledger_path_for_knowledge(knowledge))
        if _row_matches_scope(row, scope)
    ]
    receipt, template_rows, operator_rows = _read_start_semantic_pair(knowledge)
    hypothesis_mode = any(row.get('binding_version') == 2 for row in template_rows)
    if hypothesis_mode and not paired:
        scope['as_of'] = (selected_scope or {}).get('as_of') or datetime.now(timezone.utc).isoformat()
    operational = {}
    if paired:
        requested_scope = {**(selected_scope or {}), **scope}
        operational = _freeze_operational_resource_context(knowledge, receipt, template_rows, operator_rows, ledger_rows, requested_scope)
        scope = operational['selected_scope']
        _require_start_snapshot_readiness(knowledge, scope, operational_snapshot=operational)
        snapshot_ledger_rows = operational['data_ledger_rows']
        compatible_ids = operational['compatible_template_ids']
        row_counts = dict(matching_data_ledger_row_count=len(ledger_rows),
                          template_matched_row_count=len(snapshot_ledger_rows))
    else:
        snapshot_ledger_rows, compatible_ids, row_counts = _select_start_snapshot_rows(
            selected, scope, ledger_rows, template_rows, operator_rows
        )
    if not hypothesis_mode:
        _validate_start_artifact_rows(selected, scope, snapshot_ledger_rows, template_rows)
    selected_template_rows = [row for row in template_rows if str(row.get("template_id", "")) in set(compatible_ids)]
    benchmark_rules = load_benchmark_rules(benchmark_rules_path_for_knowledge(knowledge))
    if not benchmark_rules:
        raise ValueError("start snapshot benchmark rule rows are required")
    return {
        "artifact_binding_version": START_SNAPSHOT_VERSION,
        "selected_option": dict(selected),
        "selected_scope": dict(scope),
        "data_ledger_rows": [dict(row) for row in snapshot_ledger_rows],
        "compatible_template_ids": compatible_ids,
        "template_rows": selected_template_rows,
        "operator_rows": operator_rows,
        "semantic_release": receipt,
        **operational,
        **({'hypothesis_binding_version': 2} if hypothesis_mode else {}),
        "benchmark_rulebook": {
            "path": BENCHMARK_RULES_PATH.as_posix(),
            "sha256": benchmark_rulebook_digest(benchmark_rules),
            "rules": [benchmark_rule_to_dict(rule) for rule in benchmark_rules],
        },
        "gate_metadata": {
            "required_source_quality": "platform_raw_capture",
            "required_coverage_status": "measured_raw",
            "required_positive_coverage": True,
            "required_source_updated_at": True,
            "data_ledger_row_limit": START_SNAPSHOT_DATA_LEDGER_ROW_LIMIT,
            "snapshot_data_ledger_row_count": len(snapshot_ledger_rows),
            **row_counts,
        },
    }


def _snapshot_schedule_inputs(
    snapshot: Any,
    selected_option_id: str,
    selected_scope: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[Any], list[Any], list[Any]]:
    """Input: snapshot payload, option id, scope. Output: option, scope, ledger, templates, rules."""
    if not isinstance(snapshot, dict):
        raise ValueError("start snapshot is required for this workflow")
    if int(snapshot.get("artifact_binding_version", 0) or 0) != START_SNAPSHOT_VERSION:
        raise ValueError("start snapshot version is unsupported")
    selected_option = snapshot.get("selected_option")
    if not isinstance(selected_option, dict):
        raise ValueError("start snapshot selected option is missing")
    selected_option = dict(selected_option)
    if str(selected_option.get("option_id", "")) != str(selected_option_id):
        raise ValueError("start snapshot selected option mismatch")
    option_card_from_row(selected_option)
    scope = _validate_scope(snapshot.get("selected_scope") if isinstance(snapshot.get("selected_scope"), dict) else None)
    if selected_scope is not None and _validate_scope(selected_scope) != scope:
        raise ValueError("start snapshot selected scope mismatch")
    if snapshot.get('hypothesis_binding_version') == 2:
        as_of = snapshot['selected_scope'].get('as_of')
        if not as_of or (selected_scope is not None and 'as_of' in selected_scope and selected_scope['as_of'] != as_of):
            raise ValueError('start hypothesis snapshot as_of mismatch or missing')
        scope['as_of'] = as_of
    ledger_rows = snapshot.get("data_ledger_rows")
    template_rows = snapshot.get("template_rows")
    if not isinstance(ledger_rows, list) or not all(isinstance(row, dict) for row in ledger_rows):
        raise ValueError("start snapshot data ledger rows are required")
    if not isinstance(template_rows, list) or not all(isinstance(row, dict) for row in template_rows):
        raise ValueError("start snapshot template rows are required")
    benchmark_rules = benchmark_rules_from_start_snapshot(snapshot)
    from wqb.hypothesis_selection import validate_operational_resource_context
    operational = validate_operational_resource_context(snapshot)
    if operational:
        compatible_ids = sorted(row['template_id'] for row in template_rows)
    elif snapshot.get('hypothesis_binding_version') == 2:
        _, compatible_ids, _ = _select_hypothesis_snapshot_rows(snapshot['selected_scope'], ledger_rows,
                                                                template_rows, snapshot.get('operator_rows', []))
    else:
        compatible_ids = _validate_start_artifact_rows(selected_option, scope, [dict(row) for row in ledger_rows], [dict(row) for row in template_rows])
    stored_compatible_ids = snapshot.get("compatible_template_ids")
    if not isinstance(stored_compatible_ids, list) or not set(compatible_ids).issubset({str(item) for item in stored_compatible_ids}):
        raise ValueError("start snapshot compatible template IDs are incomplete")
    return (
        selected_option,
        scope,
        [data_ledger_record_from_dict(dict(row)) for row in ledger_rows],
        [template_record_from_dict(dict(row)) for row in template_rows],
        benchmark_rules,
    )


def schedule_research_stage(
    knowledge_root: str | Path,
    run_dir: str | Path,
    selected_option_id: str,
    selected_scope: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Input: knowledge root, run dir, option id. Output: schedule summary. Write a plan-only schedule artifact."""
    knowledge = Path(knowledge_root)
    run_root = Path(run_dir)
    manifest_path = run_root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    if isinstance(manifest, dict) and "start_snapshot" in manifest:
        selected, scope, ledger, templates, benchmark_rules = _snapshot_schedule_inputs(
            manifest.get("start_snapshot"), selected_option_id, selected_scope
        )
        region, delay, universe = scope["region"], scope["delay"], scope["universe"]
    elif manifest_path.exists() or any(
        (run_root / marker).exists() for marker in OFFICIAL_WORKFLOW_MARKER_FILES
    ):
        raise ValueError("start snapshot is required for workflow schedule authority")
    else:
        options_path = existing_decision_artifact_path(
            knowledge,
            "research_option_cards.jsonl",
        )
        options = read_option_card_jsonl(options_path)
        selected = next(
            (row for row in options if str(row.get("option_id", "")) == str(selected_option_id)), None
        )
        if not options:
            raise ValueError("no research option cards found")
        if selected is None:
            raise ValueError(f"selected research option not found: {selected_option_id}")
        region, delay, universe = _scope_from_selected_or_option(selected_scope, selected)
        ledger = load_data_ledger_from_knowledge(knowledge)
        templates = load_template_library_from_knowledge(knowledge)
        benchmark_rules = []
    stage_dir = run_root / "stages" / "schedule"
    stage_dir.mkdir(parents=True, exist_ok=True)
    option = _option_card_from_row(selected)
    schedule = build_research_schedule(option, ledger, templates, region, delay, universe)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    markdown_path = write_research_schedule(stage_dir / "research_schedule.md", schedule, generated_at)
    schedule_row = research_schedule_to_dict(schedule)
    snapshot = manifest.get('start_snapshot', {})
    if snapshot.get('hypothesis_binding_version') == 2:
        from wqb.hypothesis_selection import enumerate_hypothesis_bindings, binding_group_id, validate_operational_resource_context
        context = validate_operational_resource_context(snapshot)
        matches = []
        for template in snapshot['template_rows']:
            groups = ([arm['binding'] for experiment in context['experiments'] for arm in experiment['arms']
                       if arm['template_id'] == template['template_id']] if context else
                      enumerate_hypothesis_bindings(template, snapshot['data_ledger_rows'], snapshot['operator_rows'], snapshot['selected_scope']))
            for bound in groups:
                first_field = next(iter(bound['bindings'].values()))
                matches.append({**first_field, 'template_id': template['template_id'],
                                'hypothesis_id': template['hypothesis_id'], 'hypothesis_version': template['hypothesis_version'],
                                'skeleton': template['skeleton'], 'hypothesis': template['hypothesis'],
                                'binding_id': binding_group_id(bound), 'hypothesis_binding': bound})
        schedule_row.update(hypothesis_binding_version=2, template_matches=matches,
                            selected_data=snapshot['data_ledger_rows'])
    schedule_row.update(
        {
            "stage": "schedule",
            "selected_option_id": str(selected_option_id),
            "selected_option": dict(selected),
            "schedule_path": str(markdown_path),
            "benchmark_rule_ids": [rule.rule_id for rule in benchmark_rules],
        }
    )
    json_path = stage_dir / "research_schedule.json"
    json_path.write_text(json.dumps(schedule_row, ensure_ascii=False, indent=2), encoding="utf-8")
    schedule_row["evidence_paths"] = [str(json_path), str(markdown_path)]
    return schedule_row


def _option_card_from_row(row: dict[str, Any]) -> OptionCard:
    """Input: option-card row. Output: OptionCard. Normalize stored option evidence for pure scheduling."""
    return option_card_from_row(row)


def _scope_from_option(row: dict[str, Any]) -> tuple[str, int, str]:
    """Input: option-card row. Output: region, delay, universe. Derive scheduler scope without live API use."""
    scope = str(row.get("candidate_scope", row.get("scope", "")))
    tokens = scope.replace(",", " ").split()
    region = str(row.get("region", tokens[0] if tokens else "USA"))
    delay_match = re.search(r"\bD(\d+)\b", scope, re.IGNORECASE)
    delay = int(row.get("delay", delay_match.group(1) if delay_match else 1))
    universe = str(
        row.get("universe", next((item for item in tokens if item.upper().startswith("TOP")), "TOP3000"))
    )
    return region, delay, universe


def _scope_from_selected_or_option(
    selected_scope: dict[str, Any] | None, option: dict[str, Any]
) -> tuple[str, int, str]:
    """Input: optional selected scope and option card. Output: region, delay, universe. Prefer persisted concrete scope over planner prose."""
    if selected_scope is None:
        return _scope_from_option(option)
    try:
        region = str(selected_scope["region"]).strip().upper()
        delay = int(selected_scope["delay"])
        universe = str(selected_scope["universe"]).strip().upper()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("selected workflow scope must include region, delay, and universe") from exc
    if not region or delay < 0 or not universe:
        raise ValueError("selected workflow scope must include region, delay, and universe")
    return region, delay, universe


def summarize_stage_artifacts(run_dir: str | Path) -> dict[str, object]:
    """Input: run dir. Output: artifact summary. Read existing run artifacts without changing state."""
    root = Path(run_dir)
    alpha_results = _read_jsonl(root / "all_alphas.jsonl")
    benchmark_rules = load_run_benchmark_rules(root)
    return {
        "alpha_result_count": len(alpha_results),
        "candidate_file_exists": (root / "candidates.csv").exists(),
        "simulation_event_count": len(_read_jsonl(root / "simulation_events.jsonl")),
        "benchmark_rule_ids": [rule.rule_id for rule in benchmark_rules or []],
    }
