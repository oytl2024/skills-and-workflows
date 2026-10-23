import time
from dataclasses import replace
from typing import Any

from wqb.candidate_evidence import capture_evidence_revision, load_candidate_evidence, save_candidate_evidence
from wqb.models import CheckItem, CheckSummary


CHECK_RESPONSE_RETRIES = 3
CHECK_RESPONSE_RETRY_SECONDS = 5.0
WARNING_RESULTS = {"WARNING"}
PASS_RESULTS = {"PASS"}
PENDING_RESULTS = {"PENDING"}
SUBMISSION_ONLY_CHECKS = {"SELF_CORRELATION", "PROD_CORRELATION", "DATA_DIVERSITY", "REGULAR_SUBMISSION",
                          "POWER_POOL_CORRELATION", "MATCHES_THEMES"}
BASELINE_REQUIRED_CHECKS = {"LOW_SHARPE", "LOW_FITNESS"}


def classify_check_response(alpha_id: str, check_response: dict[str, Any], metrics: dict[str, Any]) -> CheckSummary:
    """Input: alpha id, check JSON, metrics. Output: classified check summary for candidate gating."""
    checks = check_response.get("is", {}).get("checks", [])
    failed: list[CheckItem] = []
    warnings: list[CheckItem] = []
    pending: list[CheckItem] = []

    if not checks:
        pending.append(CheckItem(name="NO_CHECKS", result="PENDING"))

    for item in checks:
        name = str(item.get("name", "UNKNOWN"))
        result = str(item.get("result", "UNKNOWN")).upper()
        check_item = CheckItem(
            name=name,
            result=result,
            value=item.get("value"),
            limit=item.get("limit") or item.get("threshold") or item.get("cutoff"),
        )
        if result in PASS_RESULTS:
            continue
        if result in WARNING_RESULTS:
            warnings.append(check_item)
            continue
        if result in PENDING_RESULTS:
            pending.append(check_item)
            continue
        failed.append(check_item)

    hard_pass = not failed and not pending
    return CheckSummary(
        alpha_id=alpha_id,
        hard_pass=hard_pass,
        failed=failed,
        warnings=warnings,
        pending=pending,
        metrics=metrics,
    )


def fetch_check_summary(
    client,
    alpha_id: str,
    max_check_retries: int = CHECK_RESPONSE_RETRIES,
    sleep_seconds: float = CHECK_RESPONSE_RETRY_SECONDS,
    sleep_func=time.sleep,
) -> CheckSummary:
    """Input: WQB client and alpha id. Output: classified check summary. Fetch alpha detail and check JSON."""
    cached = load_candidate_evidence(client, alpha_id)
    if cached is not None:
        return classify_check_response(alpha_id, cached[0], cached[1])
    evidence_revision = capture_evidence_revision(client, alpha_id)
    alpha = client.get_json(f"/alphas/{alpha_id}")
    metrics = alpha.get("is", {}) if isinstance(alpha, dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}
    audit = {"evidence_source": "fresh", "checked_at": time.time(),
             "expires_at": None, "persistence_status": "ineligible"}
    baseline_checks = metrics.get("checks", []) if isinstance(metrics, dict) else []
    baseline = [item for item in baseline_checks if isinstance(item, dict)
                and item.get("name") not in SUBMISSION_ONLY_CHECKS]
    names = {item.get("name") for item in baseline if isinstance(item.get("name"), str)}
    baseline_ready = (BASELINE_REQUIRED_CHECKS.issubset(names)
                      and all(str(item.get("result", "UNKNOWN")).upper() in PASS_RESULTS | WARNING_RESULTS
                              for item in baseline))
    if not baseline_ready:
        summary = classify_check_response(alpha_id, {"is": {"checks": baseline_checks}}, metrics)
        if not BASELINE_REQUIRED_CHECKS.issubset(names):
            summary = replace(summary, hard_pass=False, pending=[
                *summary.pending, CheckItem(name="NO_CHECKS", result="PENDING")])
        return replace(summary, metrics={**metrics, "candidate_evidence": audit})
    check_response = None
    for attempt in range(max_check_retries + 1):
        try:
            check_response = client.get_json(f"/alphas/{alpha_id}/check")
            break
        except ValueError:
            if attempt >= max_check_retries:
                raise
            sleep_func(sleep_seconds)
    if not isinstance(check_response, dict):
        check_response = {}
    latest_metrics = check_response.get("is")
    latest_checks = latest_metrics.get("checks") if isinstance(latest_metrics, dict) else None
    complete_payload = (isinstance(latest_checks, list) and bool(latest_checks)
                        and all(isinstance(item, dict) and isinstance(item.get("name"), str)
                                and isinstance(item.get("result"), str) for item in latest_checks))
    if not isinstance(latest_checks, list):
        latest_checks = []
    merged = {item["name"]: item for item in baseline_checks if isinstance(item, dict) and "name" in item}
    for item in latest_checks:
        if isinstance(item, dict) and "name" in item:
            merged[item["name"]] = item
    if not complete_payload:
        merged["NO_CHECKS"] = {"name": "NO_CHECKS", "result": "PENDING"}
    summary = classify_check_response(alpha_id, {"is": {"checks": list(merged.values())}}, metrics)
    if summary.hard_pass:
        audit = save_candidate_evidence(client, alpha_id, alpha, check_response, evidence_revision)
    else:
        audit["checked_at"] = time.time()
    return replace(summary, metrics={**metrics, "candidate_evidence": audit})
