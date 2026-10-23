"""Local-only research preparation; this module grants no platform authority."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from wqb.run_readiness import evaluate_run_readiness, readiness_report_to_dict


def compile_local_knowledge(knowledge_root: Path) -> dict:
    """Input: vault Path. Output: compile report dict. Repair compiled fields from existing raw evidence only."""
    from wqb.data_ledger_compile import compile_data_ledger_from_raw

    return compile_data_ledger_from_raw(knowledge_root)


def prepare_start(knowledge_root: Path, runs_root: Path, scope: dict, live_api_enabled: bool,
                  *, research_policy: dict | None = None, selected_option_id: str | None = None) -> dict:
    """Input: vault/runs Paths, scope dict, permission bool. Output: receipt dict. Check locally before mission creation."""
    scope = {key: scope[key] for key in ("region", "delay", "universe")}
    options = dict(mode="research", batch_size=30, live_api_enabled=live_api_enabled, **scope)
    report = evaluate_run_readiness(knowledge_root, **options)
    compilation = None
    # Only missing compiled field resources are repairable here. Stale facts
    # require a separate capture request, never a fabricated fresh timestamp.
    repairable = any(
        "data_ledger" in issue.path and "missing" in issue.code.lower()
        for issue in report.issues
    )
    if not report.passed and repairable:
        try:
            compilation = compile_local_knowledge(Path(knowledge_root))
        except (OSError, ValueError, RuntimeError) as error:
            compilation = {"status": "failed", "error": str(error)}
        report = evaluate_run_readiness(knowledge_root, **options)
    from wqb.hypothesis_selection import paired_scout_enabled
    snapshot = None
    if paired_scout_enabled(research_policy):
        from wqb.workflow_stage_adapters import create_start_snapshot
        from wqb.run_readiness import resolve_operational_readiness
        if not selected_option_id:
            raise ValueError('paired_scout preflight requires selected option')
        snapshot = create_start_snapshot(knowledge_root, selected_option_id, scope, research_policy=research_policy)
        report = resolve_operational_readiness(report, snapshot)
    receipt = {
        **readiness_report_to_dict(report),
        "scope": scope,
        "knowledge_root": str(Path(knowledge_root).resolve()),
        "online_refresh_authorized": False,
        "local_compilation": compilation,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        **({'paired_context_sha256': hashlib.sha256(json.dumps(snapshot, sort_keys=True,
             ensure_ascii=True, allow_nan=False).encode()).hexdigest()} if snapshot is not None else {}),
    }
    directory = Path(runs_root) / "start_preflight"
    directory.mkdir(parents=True, exist_ok=True)
    receipt_path = directory / f"{uuid4().hex}.json"
    receipt["receipt_path"] = str(receipt_path)
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    return receipt
