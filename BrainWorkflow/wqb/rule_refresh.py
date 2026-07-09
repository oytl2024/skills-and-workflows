from typing import Any

from wqb.principle_model import IncentiveSnapshot, SourceEvidence


DEFAULT_RULE_PAGE_IDS = [
    "brain-genius",
    "osmosis-allocation-guide-consultants",
    "multiplier-rules",
    "getting-started-power-pool-alphas",
    "consultant-submission-tests",
    "multi-alpha-simulation",
]


# Input: API client, request path, and error list; Output: JSON-like payload or None; Purpose: fetch GET resources without aborting the refresh.
def _safe_get(client: Any, path: str, errors: list[dict[str, str]]) -> Any:
    try:
        return client.get_json(path)
    except Exception as err:
        errors.append({"path": path, "error": type(err).__name__, "message": str(err)})
        return None


# Input: API client, request path, and error list; Output: JSON-like payload or None; Purpose: fetch OPTIONS resources without aborting the refresh.
def _safe_options(client: Any, path: str, errors: list[dict[str, str]]) -> Any:
    try:
        return client.options_json(path)
    except Exception as err:
        errors.append({"path": path, "error": type(err).__name__, "message": str(err)})
        return None


# Input: JSON-like payload; Output: list[dict[str, Any]]; Purpose: extract paginated results from standard API responses.
def _results(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [item for item in payload["results"] if isinstance(item, dict)]
    return []


# Input: OPTIONS payload; Output: list[dict[str, str]]; Purpose: normalize visible power pool board choices.
def _power_pool_choices(payload: Any) -> list[dict[str, str]]:
    board = (((payload or {}).get("actions") or {}).get("GET") or {}).get("board") or {}
    choices = board.get("choices") or []
    rows: list[dict[str, str]] = []
    for choice in choices:
        if isinstance(choice, dict) and choice.get("value") and choice.get("label"):
            rows.append({"value": str(choice["value"]), "label": str(choice["label"])})
    return rows


# Input: tutorial page payload; Output: string; Purpose: flatten rule page content into readable text.
def _page_text(page: Any) -> str:
    if not isinstance(page, dict):
        return ""
    content = page.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        value = block.get("value")
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict) and isinstance(value.get("content"), str):
            parts.append(value["content"])
    return " ".join(parts)


# Input: WQB-like client and ISO timestamp; Output: IncentiveSnapshot; Purpose: refresh official rule and incentive sources into a normalized snapshot.
def refresh_incentive_snapshot(client: Any, generated_at: str) -> IncentiveSnapshot:
    errors: list[dict[str, str]] = []
    evidence: list[SourceEvidence] = []

    account = _safe_get(client, "/users/self", errors)
    if not isinstance(account, dict):
        account = {}
    evidence.append(SourceEvidence("api", "/users/self", "User account state", generated_at))

    events_payload = _safe_get(client, "/events?limit=50&offset=0", errors)
    evidence.append(SourceEvidence("api", "/events?limit=50&offset=0", "Events", generated_at))

    competitions_payload = _safe_get(client, "/competitions?limit=50&offset=0", errors)
    evidence.append(SourceEvidence("api", "/competitions?limit=50&offset=0", "Competitions", generated_at))

    power_pool_payload = _safe_options(client, "/consultant/boards/power-pool", errors)
    evidence.append(SourceEvidence("api", "/consultant/boards/power-pool", "Power Pool boards", generated_at))

    rule_pages: dict[str, str] = {}
    for page_id in DEFAULT_RULE_PAGE_IDS:
        path = f"/tutorial-pages/{page_id}"
        page = _safe_get(client, path, errors)
        if isinstance(page, dict):
            rule_pages[page_id] = _page_text(page)
            evidence.append(SourceEvidence("api", path, str(page.get("title", page_id)), generated_at))
        else:
            evidence.append(
                SourceEvidence(
                    "api",
                    path,
                    page_id,
                    generated_at,
                    stale=True,
                    note="refresh failed",
                )
            )

    return IncentiveSnapshot(
        generated_at=generated_at,
        account=account,
        activities=_results(events_payload),
        competitions=_results(competitions_payload),
        power_pool_boards=_power_pool_choices(power_pool_payload),
        rule_pages=rule_pages,
        evidence=evidence,
        refresh_errors=errors,
    )
