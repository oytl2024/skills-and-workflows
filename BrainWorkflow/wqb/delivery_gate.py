from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_clean_compile import evaluate_clean_knowledge_structure
from wqb.knowledge_paths import MACHINE_RESOURCE_FILES, machine_resource_path
from wqb.run_readiness import evaluate_run_readiness
from wqb.workflow_state import WorkflowRunState, load_run_state


REQUIRED_HUMAN_WIKI_FILES = (
    "00_start_here.md",
    "10_factor_principles.md",
    "20_data_semantics.md",
    "30_template_and_operator_patterns.md",
    "40_benchmark_and_repair_rules.md",
    "50_engineering_lessons.md",
)


@dataclass(frozen=True)
class DeliveryGateCheck:
    code: str
    status: str
    message: str
    evidence_path: str = ""


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for delivery gate reports."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _latest_run_state(runs_root: Path) -> WorkflowRunState | None:
    """Input: runs root. Output: newest valid WorkflowRunState or none. Select by durable state timestamps."""
    states: list[WorkflowRunState] = []
    for path in runs_root.glob("*/run_state.json"):
        try:
            states.append(load_run_state(path))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    if not states:
        return None
    return max(
        states,
        key=lambda state: (state.updated_at or state.created_at, state.created_at, state.run_id),
    )


def _check(status: bool, code: str, message: str, evidence_path: str = "") -> DeliveryGateCheck:
    """Input: pass flag and details. Output: DeliveryGateCheck."""
    return DeliveryGateCheck(code, "passed" if status else "failed", message, evidence_path)


def run_delivery_gate(
    knowledge_root: str | Path,
    runs_root: str | Path,
    generated_at: str | None = None,
    console_base_url: str = "",
) -> dict[str, Any]:
    """Input: knowledge root, runs root, timestamp, Console URL. Output: delivery gate report."""
    generated = generated_at or _now()
    knowledge = Path(knowledge_root)
    runs = Path(runs_root)
    checks: list[DeliveryGateCheck] = []
    clean = evaluate_clean_knowledge_structure(knowledge)
    checks.append(
        _check(
            bool(clean.get("clean")),
            "clean_knowledge_structure",
            "Knowledge active tree follows raw/machine/wiki.",
            str(knowledge),
        )
    )
    readiness = evaluate_run_readiness(
        knowledge,
        mode="plan-only",
        batch_size=30,
        live_api_enabled=False,
        today_value=generated[:10],
    )
    readiness_codes = ", ".join(issue.code for issue in readiness.issues)
    readiness_ok = readiness.passed and not readiness.blocked and not readiness.issues
    checks.append(
        _check(
            readiness_ok,
            "run_readiness",
            "Plan-only readiness has no issues."
            if readiness_ok
            else f"Plan-only readiness requires attention: {readiness_codes or 'readiness failed'}.",
            str(knowledge),
        )
    )
    for resource_name in MACHINE_RESOURCE_FILES:
        path = machine_resource_path(knowledge, resource_name)
        checks.append(
            _check(
                path.exists(),
                f"machine_resource_{resource_name}",
                f"Machine resource exists: {resource_name}.",
                str(path),
            )
        )
    for page_name in REQUIRED_HUMAN_WIKI_FILES:
        path = knowledge / "wiki" / page_name
        compact = path.exists() and path.stat().st_size <= 12000
        checks.append(
            _check(
                compact,
                f"human_wiki_{page_name}",
                f"Compact human wiki page exists: {page_name}.",
                str(path),
            )
        )
    state = _latest_run_state(runs)
    expected_pause = (
        state is not None
        and state.status == "paused"
        and state.current_stage == "scout_seed"
        and "candidates.csv" in state.pause_reason
    )
    expected_approval = (
        state is not None
        and state.status == "waiting_for_user"
        and state.current_stage == "user_approval"
        and state.waiting_for_user
    )
    evidence_path = state.run_dir if state is not None else str(runs)
    checks.append(_check(state is not None, "workflow_state_exists", "Latest workflow state is durable.", evidence_path))
    checks.append(
        _check(
            expected_pause
            or expected_approval
            or (state is not None and state.status in {"completed", "completed_with_warnings"}),
            "expected_pause",
            "Workflow reached a durable accepted boundary.",
            evidence_path,
        )
    )
    report = {
        "generated_at": generated,
        "status": "passed" if all(check.status == "passed" for check in checks) else "failed",
        "checks": [asdict(check) for check in checks],
    }
    report_path = knowledge / "raw" / "maintenance" / "delivery_gates" / f"{generated[:10]}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
