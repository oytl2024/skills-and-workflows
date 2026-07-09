import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from wqb.client import WQBClient


OUTPUT_DIR = Path("knowledge/rawmaterial/learn")
WIKI_LEARN_PAGE = Path("knowledge/wiki/10_foundations/learn_material_index.md")
WIKI_OPERATOR_PAGE = Path("knowledge/wiki/20_semantics/operator_catalog_official.md")
PAGE_LIMIT = 100
MAX_RECORDS = 1000
REQUEST_TIMEOUT_SECONDS = 12
REQUEST_MAX_RETRIES = 1
REQUEST_BASE_BACKOFF_SECONDS = 1
SEARCH_QUERIES = [
    "documentation",
    "operators",
    "learn",
    "alpha",
    "simulation",
    "expression",
    "data fields",
    "power pool",
    "correlation",
    "neutralization",
    "metrics",
    "checks",
    "regions",
    "universe",
    "dataset",
    "fast d1",
    "consultant",
    "osmosis",
    "genius",
    "theme",
    "python alpha",
    "ace api",
    "superalpha",
    "submission",
    "settings",
]
SEED_TUTORIAL_PAGE_IDS = [
    "introduction-brain-expression-language",
    "understanding-simulation-limits",
    "parameters-simulation-results",
    "consultant-submission-tests",
    "getting-started-finding-consultant-alphas-read-first",
    "getting-started-power-pool-alphas",
    "fast-d1-documentation",
    "vector-datafields",
    "group-data-fields",
    "neut-cons",
    "brain-genius",
    "osmosis-allocation-guide-consultants",
    "multiplier-rules",
    "multi-alpha-simulation",
]
PAGINATED_ENDPOINTS = {
    "faqs": "/faqs",
    "videos": "/videos",
    "recommended_readings": "/recommended-readings",
}
COURSE_TERMS = ["course", "courses"]


def write_json(path: Path, payload: Any) -> None:
    """Input: output path and JSON-like payload. Output: None. Persist raw Learn material with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def result_rows(payload: Any) -> list[dict[str, Any]]:
    """Input: API payload. Output: list of dict rows. Normalize list and paginated response shapes."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [item for item in payload["results"] if isinstance(item, dict)]
    return []


def fetch_paginated(client: WQBClient, endpoint: str) -> list[dict[str, Any]]:
    """Input: WQB client and endpoint. Output: all available rows up to MAX_RECORDS. Fetch one Learn section efficiently."""
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < MAX_RECORDS:
        print(f"fetch {endpoint} offset={offset}", flush=True)
        payload = client.get_json(f"{endpoint}?limit={PAGE_LIMIT}&offset={offset}")
        batch = result_rows(payload)
        rows.extend(batch)
        if len(batch) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    return rows[:MAX_RECORDS]


def looks_like_course(row: dict[str, Any]) -> bool:
    """Input: metadata row. Output: bool. Exclude course-like Learn material from this capture."""
    haystack = " ".join(str(row.get(key, "")) for key in ("title", "name", "category", "type", "id")).lower()
    return any(term in haystack for term in COURSE_TERMS)


def collect_search_results(client: WQBClient) -> dict[str, Any]:
    """Input: WQB client. Output: search result dict. Capture broad Learn discovery queries once."""
    results: dict[str, Any] = {}
    for query in SEARCH_QUERIES:
        print(f"search {query}", flush=True)
        try:
            results[query] = client.get_json(f"/search?query={quote(query)}")
        except Exception as err:
            results[query] = {"error": type(err).__name__, "message": str(err)}
    return results


def tutorial_ids_from_search(search_results: dict[str, Any]) -> list[str]:
    """Input: search result dict. Output: tutorial page ids. Collect documentation pages discovered by search."""
    ids = set(SEED_TUTORIAL_PAGE_IDS)
    for payload in search_results.values():
        group = payload.get("tutorialPage") if isinstance(payload, dict) else None
        rows = group.get("results", []) if isinstance(group, dict) else []
        for row in rows:
            if isinstance(row, dict) and row.get("id") and not looks_like_course(row):
                ids.add(str(row["id"]))
    return sorted(ids)


def fetch_tutorial_pages(client: WQBClient, page_ids: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Input: WQB client and page ids. Output: pages and errors. Fetch documentation page details safely."""
    pages: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for page_id in page_ids:
        print(f"tutorial {page_id}", flush=True)
        try:
            page = client.get_json(f"/tutorial-pages/{quote(page_id)}")
            if isinstance(page, dict) and not looks_like_course(page):
                pages.append(page)
        except Exception as err:
            errors.append({"id": page_id, "error": type(err).__name__, "message": str(err)})
    return pages, errors


def clean_text(value: Any) -> str:
    """Input: arbitrary content value. Output: compact text. Extract readable snippets for compiled wiki pages."""
    if isinstance(value, str):
        without_style = re.sub(r"<style.*?</style>", " ", value, flags=re.IGNORECASE | re.DOTALL)
        without_tags = re.sub(r"<[^>]+>", " ", without_style)
        return " ".join(html.unescape(without_tags).split())
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(clean_text(item.get("value") or item.get("content") or item.get("text") or ""))
            else:
                parts.append(clean_text(item))
        return " ".join(part for part in parts if part)
    if isinstance(value, dict):
        return " ".join(clean_text(item) for item in value.values())
    return ""


def write_learn_wiki(capture: dict[str, Any]) -> None:
    """Input: raw capture dict. Output: None. Compile Learn source inventory into the wiki."""
    generated_at = capture["generated_at"]
    documentation_pages = capture["documentation_pages"]
    lines = [
        "# Learn Material Index",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "This page indexes the locally captured non-course Learn material. Raw API payloads live under `knowledge/rawmaterial/learn/`.",
        "",
        "## Captured Sections",
        "",
        f"- Operators: {len(capture['operators'])} rows from `/operators`.",
        f"- Documentation tutorial pages: {len(documentation_pages)} fetched pages.",
        f"- FAQs: {len(capture['faqs'])} rows from `/faqs`.",
        f"- Videos: {len(capture['videos'])} rows from `/videos`.",
        f"- Recommended readings: {len(capture['recommended_readings'])} rows from `/recommended-readings`.",
        "",
        "Courses are intentionally excluded.",
        "",
        "## Documentation Pages",
        "",
    ]
    for page in sorted(documentation_pages, key=lambda item: str(item.get("title", item.get("id", ""))).lower()):
        title = page.get("title") or page.get("id")
        page_id = page.get("id", "")
        category = page.get("category", "")
        snippet = clean_text(page.get("content"))[:220]
        lines.append(f"- `{page_id}`: {title} ({category})")
        if snippet:
            lines.append(f"  - {snippet}")
    if capture["documentation_errors"]:
        lines.extend(["", "## Documentation Fetch Errors", ""])
        for error in capture["documentation_errors"]:
            lines.append(f"- `{error['id']}`: {error['error']} - {error['message']}")
    lines.extend(
        [
            "",
            "## Research Workflow Use",
            "",
            "- Read this page before creating a new research plan when platform rules may have changed.",
            "- Use the operator catalog wiki page for operator availability and descriptions before generating templates.",
            "- Refresh this capture when rules, activities, operators, or Learn navigation changes.",
        ]
    )
    WIKI_LEARN_PAGE.parent.mkdir(parents=True, exist_ok=True)
    WIKI_LEARN_PAGE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_operator_wiki(operators: list[dict[str, Any]], generated_at: str) -> None:
    """Input: operator rows and timestamp. Output: None. Compile official operator metadata into the wiki."""
    by_category: dict[str, list[dict[str, Any]]] = {}
    for operator in operators:
        category = str(operator.get("category") or "Uncategorized")
        by_category.setdefault(category, []).append(operator)

    lines = [
        "# Official Operator Catalog",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "Raw source: `knowledge/rawmaterial/learn/operators.json`.",
        "",
        "Use this catalog as the local source for operator names, categories, scopes, definitions, descriptions, documentation fields, and level restrictions.",
        "",
    ]
    for category in sorted(by_category):
        rows = sorted(by_category[category], key=lambda item: str(item.get("name", "")).lower())
        lines.extend([f"## {category}", ""])
        for row in rows:
            name = row.get("name", "")
            scope = row.get("scope", "")
            level = row.get("level", "")
            definition = clean_text(row.get("definition"))
            description = clean_text(row.get("description"))
            doc = clean_text(row.get("documentation"))
            lines.append(f"### `{name}`")
            if scope or level:
                lines.append(f"- Scope: {scope or 'unspecified'}")
                lines.append(f"- Level: {level or 'unspecified'}")
            if definition:
                lines.append(f"- Definition: `{definition}`")
            if description:
                lines.append(f"- Description: {description}")
            if doc:
                lines.append(f"- Documentation: {doc}")
            lines.append("")
    WIKI_OPERATOR_PAGE.parent.mkdir(parents=True, exist_ok=True)
    WIKI_OPERATOR_PAGE.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """Input: env credentials. Output: rawmaterial JSON and wiki pages. Capture non-course Learn material."""
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    client = WQBClient(
        timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        max_retries=REQUEST_MAX_RETRIES,
        base_backoff_seconds=REQUEST_BASE_BACKOFF_SECONDS,
    )
    print("fetch /operators", flush=True)
    operators = [row for row in result_rows(client.get_json("/operators")) if not looks_like_course(row)]
    sections = {}
    for name, endpoint in PAGINATED_ENDPOINTS.items():
        sections[name] = [row for row in fetch_paginated(client, endpoint) if not looks_like_course(row)]
    search_results = collect_search_results(client)
    documentation_pages, documentation_errors = fetch_tutorial_pages(client, tutorial_ids_from_search(search_results))
    capture = {
        "generated_at": generated_at,
        "excluded": ["courses"],
        "operators": operators,
        "documentation_pages": documentation_pages,
        "documentation_errors": documentation_errors,
        "search_results": search_results,
        **sections,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": generated_at,
        "excluded": capture["excluded"],
        "counts": {key: len(value) for key, value in capture.items() if isinstance(value, list)},
        "search_query_count": len(search_results),
    }
    write_json(OUTPUT_DIR / "learn_capture_manifest.json", manifest)
    write_json(OUTPUT_DIR / "operators.json", operators)
    write_json(OUTPUT_DIR / "documentation_pages.json", documentation_pages)
    write_json(OUTPUT_DIR / "documentation_errors.json", documentation_errors)
    write_json(OUTPUT_DIR / "faqs.json", capture["faqs"])
    write_json(OUTPUT_DIR / "videos.json", capture["videos"])
    write_json(OUTPUT_DIR / "recommended_readings.json", capture["recommended_readings"])
    write_json(OUTPUT_DIR / "search_results.json", search_results)
    write_learn_wiki(capture)
    write_operator_wiki(operators, generated_at)
    print(json.dumps({"generated_at": generated_at, "output_dir": str(OUTPUT_DIR), "counts": {key: len(value) for key, value in capture.items() if isinstance(value, list)}}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
