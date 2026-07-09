import time
from typing import Any

from wqb.models import CheckItem, CheckSummary


CHECK_RESPONSE_RETRIES = 3
CHECK_RESPONSE_RETRY_SECONDS = 5.0
WARNING_RESULTS = {"WARNING"}
PASS_RESULTS = {"PASS"}
PENDING_RESULTS = {"PENDING"}


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
    alpha = client.get_json(f"/alphas/{alpha_id}")
    metrics = alpha.get("is", {}) if isinstance(alpha, dict) else {}
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
    return classify_check_response(alpha_id, check_response, metrics)
