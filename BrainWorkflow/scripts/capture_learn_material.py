import hashlib
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from wqb.client import WQBClient


KNOWLEDGE_ROOT_ENV = "BRAIN_KNOWLEDGE_ROOT"
LEARN_JSON_CACHE_ROOT_ENV = "BRAIN_LEARN_JSON_CACHE_ROOT"
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


def default_knowledge_root() -> Path:
    """Input: none. Output: Path. Resolve the shared Obsidian knowledge vault root."""
    configured = os.environ.get(KNOWLEDGE_ROOT_ENV, "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "knowledge"


def default_json_cache_root() -> Path:
    """Input: none. Output: Path. Resolve the ignored JSON cache root for exact source diffs."""
    configured = os.environ.get(LEARN_JSON_CACHE_ROOT_ENV, "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "docs" / "knowledge" / "cache" / "learn"


KNOWLEDGE_ROOT = default_knowledge_root()
RAW_LEARN_ROOT = KNOWLEDGE_ROOT / "raw" / "platform" / "learn"
JSON_CACHE_ROOT = default_json_cache_root()
WIKI_LEARN_PAGE = KNOWLEDGE_ROOT / "wiki" / "10_foundations" / "learn_material_index.md"
WIKI_OPERATOR_PAGE = KNOWLEDGE_ROOT / "wiki" / "20_semantics" / "operator_catalog_official.md"


def write_json(path: Path, payload: Any) -> None:
    """Input: output path and JSON-like payload. Output: None. Persist exact Learn JSON cache with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_markdown(path: Path, lines: list[str]) -> None:
    """Input: output path and markdown lines. Output: None. Persist an Obsidian-readable raw source file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def stable_json_hash(payload: Any) -> str:
    """Input: JSON-like payload. Output: sha256 hex string. Hash source content for update checks."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def capture_date(generated_at: str) -> str:
    """Input: ISO timestamp string. Output: YYYY-MM-DD string. Derive a stable capture folder name."""
    return generated_at.split("T", 1)[0]


def raw_capture_dir(generated_at: str) -> Path:
    """Input: ISO timestamp string. Output: raw capture directory. Place Markdown raw sources by date."""
    return RAW_LEARN_ROOT / capture_date(generated_at)


def json_cache_dir(generated_at: str) -> Path:
    """Input: ISO timestamp string. Output: JSON cache directory. Place exact payloads outside Obsidian."""
    return JSON_CACHE_ROOT / capture_date(generated_at)


def frontmatter(source_type: str, source_path: str, generated_at: str, payload: Any, compiled_targets: list[str]) -> list[str]:
    """Input: source metadata and payload. Output: Markdown frontmatter lines. Describe raw source provenance."""
    lines = [
        "---",
        f"source_type: {source_type}",
        f"source_path: {source_path}",
        f"captured_at: {generated_at}",
        "capture_tool: scripts/capture_learn_material.py",
        "content_status: raw_markdown",
        f"content_hash: {stable_json_hash(payload)}",
        "compiled_targets:",
    ]
    for target in compiled_targets:
        lines.append(f"  - {target}")
    lines.append("---")
    return lines


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


def markdown_record_value(value: Any) -> str:
    """Input: arbitrary source value. Output: readable Markdown text. Preserve source content in raw notes."""
    text = clean_text(value)
    return text if text else str(value or "")


def write_raw_index(capture: dict[str, Any], manifest: dict[str, Any], output_dir: Path) -> Path:
    """Input: Learn capture, manifest, output dir. Output: index path. Write the raw capture overview."""
    generated_at = capture["generated_at"]
    lines = frontmatter(
        "platform_api",
        "learn capture aggregate",
        generated_at,
        manifest,
        ["knowledge/wiki/10_foundations/learn_material_index.md"],
    )
    lines.extend(
        [
            "",
            "# Learn Capture Index",
            "",
            f"Captured at: `{generated_at}`",
            "",
            "Courses are intentionally excluded.",
            "",
            "## Section Files",
            "",
            "- [[operators|Operators]]",
            "- [[documentation_pages|Documentation Pages]]",
            "- [[documentation_errors|Documentation Fetch Errors]]",
            "- [[faqs|FAQs]]",
            "- [[videos|Videos]]",
            "- [[recommended_readings|Recommended Readings]]",
            "- [[search_results|Search Results]]",
            "",
            "## Counts",
            "",
        ]
    )
    for key, value in sorted(manifest["counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            f"- search_query_count: {manifest['search_query_count']}",
            "",
            "## Update Check",
            "",
            "Compare counts and content hashes against the previous capture. Count changes identify which section files need deeper review before recompiling wiki pages.",
        ]
    )
    path = output_dir / "index.md"
    write_markdown(path, lines)
    return path


def write_raw_operators(operators: list[dict[str, Any]], generated_at: str, output_dir: Path) -> Path:
    """Input: operator rows, timestamp, output dir. Output: path. Write raw official operator records as Markdown."""
    lines = frontmatter(
        "platform_api",
        "/operators",
        generated_at,
        operators,
        ["knowledge/wiki/20_semantics/operator_catalog_official.md", "knowledge/wiki/20_semantics/operators.md"],
    )
    lines.extend(["", "# Operators", "", f"Record count: {len(operators)}", ""])
    by_category: dict[str, list[dict[str, Any]]] = {}
    for operator in operators:
        category = str(operator.get("category") or "Uncategorized")
        by_category.setdefault(category, []).append(operator)
    for category in sorted(by_category):
        lines.extend([f"## {category}", ""])
        for row in sorted(by_category[category], key=lambda item: str(item.get("name", "")).lower()):
            name = row.get("name", "")
            lines.extend(
                [
                    f"### `{name}`",
                    "",
                    f"- Source id: `{name}`",
                    f"- Scope: {row.get('scope', 'unspecified')}",
                    f"- Level: {row.get('level', 'unspecified')}",
                    f"- Documentation: {row.get('documentation', '')}",
                    f"- Definition: `{markdown_record_value(row.get('definition'))}`",
                    f"- Description: {markdown_record_value(row.get('description'))}",
                    "",
                ]
            )
    path = output_dir / "operators.md"
    write_markdown(path, lines)
    return path


def write_raw_documentation_pages(pages: list[dict[str, Any]], generated_at: str, output_dir: Path) -> Path:
    """Input: documentation page rows, timestamp, output dir. Output: path. Write raw Learn documentation pages."""
    lines = frontmatter(
        "platform_api",
        "/tutorial-pages/{id}",
        generated_at,
        pages,
        [
            "knowledge/wiki/10_foundations/learn_material_index.md",
            "knowledge/wiki/10_foundations/metrics_and_checks.md",
            "knowledge/wiki/60_workflows/correlation_aware_stage1.md",
        ],
    )
    lines.extend(["", "# Documentation Pages", "", f"Record count: {len(pages)}", ""])
    for page in sorted(pages, key=lambda item: str(item.get("title", item.get("id", ""))).lower()):
        page_id = page.get("id", "")
        title = page.get("title") or page_id
        lines.extend(
            [
                f"## {title}",
                "",
                f"- Page id: `{page_id}`",
                f"- Category: {page.get('category', '')}",
                "",
                markdown_record_value(page.get("content")),
                "",
            ]
        )
    path = output_dir / "documentation_pages.md"
    write_markdown(path, lines)
    return path


def write_raw_errors(errors: list[dict[str, str]], generated_at: str, output_dir: Path) -> Path:
    """Input: fetch error rows, timestamp, output dir. Output: path. Write raw documentation fetch errors."""
    lines = frontmatter(
        "platform_api",
        "/tutorial-pages/{id}",
        generated_at,
        errors,
        ["knowledge/wiki/10_foundations/learn_material_index.md"],
    )
    lines.extend(["", "# Documentation Fetch Errors", "", f"Record count: {len(errors)}", ""])
    for error in errors:
        lines.extend(
            [
                f"## `{error.get('id', '')}`",
                "",
                f"- Error: {error.get('error', '')}",
                f"- Message: {error.get('message', '')}",
                "",
            ]
        )
    path = output_dir / "documentation_errors.md"
    write_markdown(path, lines)
    return path


def write_raw_rows(
    section_name: str,
    endpoint: str,
    rows: list[dict[str, Any]],
    generated_at: str,
    output_dir: Path,
    filename: str,
    compiled_targets: list[str],
) -> Path:
    """Input: row section metadata and rows. Output: path. Write raw API rows as Markdown."""
    lines = frontmatter("platform_api", endpoint, generated_at, rows, compiled_targets)
    lines.extend(["", f"# {section_name}", "", f"Record count: {len(rows)}", ""])
    for index, row in enumerate(rows, 1):
        title = row.get("title") or row.get("name") or row.get("question") or row.get("id") or f"Record {index}"
        lines.extend([f"## {title}", ""])
        for key in sorted(row):
            value = row[key]
            if isinstance(value, (dict, list)):
                lines.append(f"- {key}: `{json.dumps(value, ensure_ascii=False, sort_keys=True)}`")
            else:
                text = markdown_record_value(value)
                if len(text) > 500:
                    lines.extend([f"- {key}:", "", text, ""])
                else:
                    lines.append(f"- {key}: {text}")
        lines.append("")
    path = output_dir / filename
    write_markdown(path, lines)
    return path


def write_raw_search_results(search_results: dict[str, Any], generated_at: str, output_dir: Path) -> Path:
    """Input: search results, timestamp, output dir. Output: path. Write raw Learn search discovery results."""
    lines = frontmatter(
        "platform_api",
        "/search?query=...",
        generated_at,
        search_results,
        ["knowledge/wiki/10_foundations/learn_material_index.md"],
    )
    lines.extend(["", "# Search Results", "", f"Query count: {len(search_results)}", ""])
    for query in sorted(search_results):
        payload = search_results[query]
        lines.extend([f"## Query: `{query}`", ""])
        if isinstance(payload, dict) and "error" in payload:
            lines.extend([f"- Error: {payload.get('error')}", f"- Message: {payload.get('message')}", ""])
            continue
        if isinstance(payload, dict):
            for group_name in sorted(payload):
                group = payload[group_name]
                rows = group.get("results", []) if isinstance(group, dict) else []
                lines.append(f"### {group_name}")
                lines.append("")
                lines.append(f"- Result count: {len(rows)}")
                for row in rows:
                    if isinstance(row, dict):
                        label = row.get("title") or row.get("name") or row.get("id") or row.get("url") or "result"
                        lines.append(f"- `{row.get('id', '')}` {label}")
                lines.append("")
        else:
            lines.extend(["```json", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), "```", ""])
    path = output_dir / "search_results.md"
    write_markdown(path, lines)
    return path


def write_raw_learn_markdown(capture: dict[str, Any], manifest: dict[str, Any]) -> list[Path]:
    """Input: Learn capture and manifest. Output: written Markdown paths. Convert raw Learn payloads for Obsidian."""
    output_dir = raw_capture_dir(capture["generated_at"])
    paths = [
        write_raw_index(capture, manifest, output_dir),
        write_raw_operators(capture["operators"], capture["generated_at"], output_dir),
        write_raw_documentation_pages(capture["documentation_pages"], capture["generated_at"], output_dir),
        write_raw_errors(capture["documentation_errors"], capture["generated_at"], output_dir),
        write_raw_rows(
            "FAQs",
            "/faqs",
            capture["faqs"],
            capture["generated_at"],
            output_dir,
            "faqs.md",
            ["knowledge/wiki/10_foundations/metrics_and_checks.md"],
        ),
        write_raw_rows(
            "Videos",
            "/videos",
            capture["videos"],
            capture["generated_at"],
            output_dir,
            "videos.md",
            ["knowledge/wiki/20_semantics/data_fields_and_datasets.md", "knowledge/wiki/30_templates/template_families.md"],
        ),
        write_raw_rows(
            "Recommended Readings",
            "/recommended-readings",
            capture["recommended_readings"],
            capture["generated_at"],
            output_dir,
            "recommended_readings.md",
            ["knowledge/wiki/30_templates/template_families.md"],
        ),
        write_raw_search_results(capture["search_results"], capture["generated_at"], output_dir),
    ]
    return paths


def write_json_cache(capture: dict[str, Any], manifest: dict[str, Any]) -> Path:
    """Input: Learn capture and manifest. Output: cache dir. Store exact JSON outside the Obsidian vault."""
    output_dir = json_cache_dir(capture["generated_at"])
    write_json(output_dir / "learn_capture_manifest.json", manifest)
    write_json(output_dir / "operators.json", capture["operators"])
    write_json(output_dir / "documentation_pages.json", capture["documentation_pages"])
    write_json(output_dir / "documentation_errors.json", capture["documentation_errors"])
    write_json(output_dir / "faqs.json", capture["faqs"])
    write_json(output_dir / "videos.json", capture["videos"])
    write_json(output_dir / "recommended_readings.json", capture["recommended_readings"])
    write_json(output_dir / "search_results.json", capture["search_results"])
    return output_dir


def write_learn_wiki(capture: dict[str, Any]) -> None:
    """Input: raw capture dict. Output: None. Compile Learn source inventory into the wiki."""
    generated_at = capture["generated_at"]
    documentation_pages = capture["documentation_pages"]
    lines = [
        "# Learn Material Index",
        "",
        f"Generated at: `{generated_at}`",
        "",
        f"This page indexes the locally captured non-course Learn material. Raw Markdown sources live under `knowledge/raw/platform/learn/{capture_date(generated_at)}/`.",
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
        f"Raw source: `knowledge/raw/platform/learn/{capture_date(generated_at)}/operators.md`.",
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
    """Input: env credentials. Output: raw Markdown, JSON cache, and wiki pages. Capture non-course Learn material."""
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

    manifest = {
        "generated_at": generated_at,
        "excluded": capture["excluded"],
        "counts": {key: len(value) for key, value in capture.items() if isinstance(value, list)},
        "search_query_count": len(search_results),
    }
    raw_paths = write_raw_learn_markdown(capture, manifest)
    cache_dir = write_json_cache(capture, manifest)
    write_learn_wiki(capture)
    write_operator_wiki(operators, generated_at)
    print(
        json.dumps(
            {
                "generated_at": generated_at,
                "raw_markdown_dir": str(raw_capture_dir(generated_at)),
                "raw_markdown_files": [str(path) for path in raw_paths],
                "json_cache_dir": str(cache_dir),
                "counts": {key: len(value) for key, value in capture.items() if isinstance(value, list)},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
