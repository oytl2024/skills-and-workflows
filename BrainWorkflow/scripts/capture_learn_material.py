import hashlib
import html
import json
import math
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from wqb.client import BASE_URL, WQBClient
from wqb.knowledge_contracts import SourceIndexRow, parse_markdown_front_matter, upsert_source_index_rows


KNOWLEDGE_ROOT_ENV = "BRAIN_KNOWLEDGE_ROOT"
LEARN_JSON_CACHE_ROOT_ENV = "BRAIN_LEARN_JSON_CACHE_ROOT"
PAGE_LIMIT = 100
MAX_RECORDS = 1000
REQUEST_TIMEOUT_SECONDS = 12
REQUEST_MAX_RETRIES = 1
REQUEST_BASE_BACKOFF_SECONDS = 1
ERROR_PAYLOAD_MAX_BYTES = 65536
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
LEARN_PREVIEW_PAGE = KNOWLEDGE_ROOT / "machine" / "previews" / "learn_material_index.md"
OPERATOR_PREVIEW_PAGE = KNOWLEDGE_ROOT / "machine" / "previews" / "operator_catalog_official.md"
WIKI_LEARN_PAGE = LEARN_PREVIEW_PAGE
WIKI_OPERATOR_PAGE = OPERATOR_PREVIEW_PAGE
RAW_LEARN_SOURCE_FAMILY = "raw/platform/learn"
START_HERE_TARGET = "wiki/00_start_here.md"
FACTOR_PRINCIPLES_TARGET = "wiki/10_factor_principles.md"
DATA_SEMANTICS_TARGET = "wiki/20_data_semantics.md"
TEMPLATE_OPERATOR_TARGET = "wiki/30_template_and_operator_patterns.md"
BENCHMARK_REPAIR_TARGET = "wiki/40_benchmark_and_repair_rules.md"
OPERATOR_LEDGER_TARGET = "machine/operator_ledger.jsonl"


def write_json(path: Path, payload: Any) -> None:
    """Input: output path and JSON-like payload. Output: None. Persist exact Learn JSON cache with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def guard_capture_path(root: Path, path: Path) -> None:
    """Input: knowledge root/output Paths. Output: None. Reject escapes and linked/reparse ancestors."""
    root = root.absolute()
    path = path.absolute()
    if not path.is_relative_to(root) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("capture output escapes knowledge root")
    for parent in (path, *path.parents):
        try:
            metadata = parent.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise ValueError("linked capture output or parent is not allowed")


def guard_capture_outputs(root: Path, generated_at: str) -> None:
    """Input: knowledge Path/ISO str. Output: None. Preflight raw/index paths before any GET."""
    dated = raw_capture_dir(generated_at, root)
    for path in (dated, root / "raw/source_index.md", root / "machine/source_index.jsonl",
                 root / "machine/source_index_write.guard"):
        guard_capture_path(root, path)
    pending = [dated] if dated.exists() else []
    while pending:
        for child in pending.pop().iterdir():
            guard_capture_path(root, child)
            if child.is_dir():
                pending.append(child)


def material_rows_valid(rows: Any, kind: str) -> bool:
    """Input: row payload Any/material kind str. Output: bool. Exclude error envelopes and malformed material."""
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        if not isinstance(row, dict) or any(key in row for key in ("error", "errors", "detail")) or looks_like_course(row):
            return False
        if kind == "operator" and (not isinstance(row.get("name"), str) or not row["name"].strip()):
            return False
        if kind == "tutorial" and (not isinstance(row.get("id"), str) or not row["id"].strip()
                                   or not readable_content(row.get("content"))):
            return False
    return True


def readable_content(content: Any) -> bool:
    """Input: source content Any. Output: bool. Validate known text/block schemas without discarding nontext facts."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return bool(content) and all(readable_content(item) for item in content)
    if not isinstance(content, dict):
        return False
    if 'type' not in content:
        return (len(content) == 1 and next(iter(content)) in {'value', 'content', 'text'}
                and readable_content(next(iter(content.values()))))
    if (set(content) != {'id', 'type', 'value'} or not isinstance(content['id'], str)
            or not content['id'].strip()):
        return False
    kind, value = content['type'], content['value']
    if kind in ('TEXT', 'EQUATION'):
        return isinstance(value, str) and bool(value.strip())
    if not isinstance(value, dict):
        return False
    if kind == 'HEADING':
        return (set(value) == {'content', 'level'} and isinstance(value['content'], str)
                and bool(value['content'].strip()) and value['level'] in ('1', '2', '3', '4', '5', '6'))
    if kind == 'TABLE':
        data = value.get('data')
        return (set(value) == {'data', 'firstColIsHeader', 'firstRowIsTableHeader'}
                and type(value['firstColIsHeader']) is bool and type(value['firstRowIsTableHeader']) is bool
                and isinstance(data, list) and bool(data)
                and all(isinstance(row, list) and bool(row) and all(isinstance(cell, str) for cell in row)
                        for row in data)
                and all(len(row) == len(data[0]) for row in data)
                and any(cell.strip() for row in data for cell in row))
    if kind == 'IMAGE':
        return (set(value) == {'fileSize', 'height', 'title', 'url', 'width'}
                and all(type(value[key]) is int and value[key] > 0 for key in ('height', 'width'))
                and type(value['fileSize']) is int and value['fileSize'] >= 0
                and isinstance(value['title'], str) and bool(value['title'].strip())
                and isinstance(value['url'], str) and re.fullmatch(r'https://[^\s/]+/\S+', value['url']) is not None)
    if kind == 'SIMULATION_EXAMPLE':
        settings = value.get('settings')
        string_keys = {'instrumentType', 'language', 'maxTrade', 'nanHandling', 'neutralization',
                       'pasteurization', 'region', 'unitHandling', 'universe'}
        return (set(value) == {'regular', 'settings', 'type'} and value['type'] == 'REGULAR'
                and isinstance(value['regular'], str) and bool(value['regular'].strip())
                and isinstance(settings, dict) and set(settings) == string_keys | {'decay', 'delay', 'truncation'}
                and all(isinstance(settings[key], str) and bool(settings[key].strip()) for key in string_keys)
                and all(type(settings[key]) is int for key in ('decay', 'delay'))
                and type(settings['truncation']) in (int, float) and math.isfinite(settings['truncation']))
    return False


def bounded_response_payload(response) -> Any:
    """Input: requests Response. Output: JSON/text evidence Any. Bound retained HTTP error bytes without hiding truncation."""
    body = response.content or b""
    prefix = body[:ERROR_PAYLOAD_MAX_BYTES].decode("utf-8", errors="replace")
    if len(body) > ERROR_PAYLOAD_MAX_BYTES:
        return {"truncated": True, "body_bytes": len(body), "body_prefix": prefix}
    try:
        return json.loads(prefix)
    except (ValueError, RecursionError):
        return {"truncated": False, "body_bytes": len(body), "body_text": prefix}


def write_markdown(path: Path, lines: list[str], *, root: Path | None = None) -> None:
    """Input: output path and markdown lines. Output: None. Persist an Obsidian-readable raw source file."""
    active_root = root if root is not None else KNOWLEDGE_ROOT
    guard_capture_path(active_root, path)
    text = "\n".join(lines).rstrip() + "\n"
    metadata, body = parse_markdown_front_matter(text)
    if (metadata.get('capture_tool') == 'scripts/capture_learn_material.py'
            and metadata.get('content_status') == 'raw_markdown'):
        body_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
        text = re.sub(r'^content_hash: [a-f0-9]{64}$', 'content_hash: ' + body_hash,
                      text, count=1, flags=re.MULTILINE)
    path.parent.mkdir(parents=True, exist_ok=True)
    guard_capture_path(active_root, path)
    path.write_text(text, encoding="utf-8")


def stable_json_hash(payload: Any) -> str:
    """Input: JSON-like payload. Output: sha256 hex string. Hash source content for update checks."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def payload_record_count(payload: Any) -> int:
    """Input: raw payload. Output: record count int. Count rows represented by one raw source note."""
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return len(payload["results"])
    return 1


def knowledge_relative_path(path: Path, root: Path | None = None) -> str:
    """Input: source Path/optional knowledge Path. Output: relative str. Preserve the legacy default root."""
    try:
        return path.resolve().relative_to((root if root is not None else KNOWLEDGE_ROOT).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def capture_date(generated_at: str) -> str:
    """Input: ISO timestamp string. Output: YYYY-MM-DD string. Derive a stable capture folder name."""
    return generated_at.split("T", 1)[0]


def raw_capture_dir(generated_at: str, root: Path | None = None) -> Path:
    """Input: ISO str/optional knowledge Path. Output: Path. Place raw sources by date without global mutation."""
    base = root / "raw" / "platform" / "learn" if root is not None else RAW_LEARN_ROOT
    return base / capture_date(generated_at)


def json_cache_dir(generated_at: str) -> Path:
    """Input: ISO timestamp string. Output: JSON cache directory. Place exact payloads outside Obsidian."""
    return JSON_CACHE_ROOT / capture_date(generated_at)


def frontmatter(source_type: str, source_path: str, generated_at: str, payload: Any, compiled_targets: list[str]) -> list[str]:
    """Input: source metadata and payload. Output: Markdown frontmatter lines. Describe raw source provenance."""
    lines = [
        "---",
        f"source_type: {source_type}",
        f"source_family: {RAW_LEARN_SOURCE_FAMILY}",
        f"source_path: {source_path}",
        f"captured_at: {generated_at}",
        "capture_tool: scripts/capture_learn_material.py",
        "content_status: raw_markdown",
        f"record_count: {payload_record_count(payload)}",
        f"content_hash: {stable_json_hash(payload)}",
        f"payload_hash: {stable_json_hash(payload)}",
        "update_check: compare record count, content hash, and platform endpoint against the previous Learn capture",
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
    """Input: WQB client/endpoint str. Output: list[dict] up to MAX_RECORDS. Preserve error envelopes before normalization."""
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < MAX_RECORDS:
        print(f"fetch {endpoint} offset={offset}", flush=True)
        request_path = f"{endpoint}?limit={PAGE_LIMIT}&offset={offset}"
        payload = client.get_json(request_path)
        if isinstance(payload, dict) and any(key in payload for key in ("error", "errors", "detail")):
            failure = {"error": "platform_error_envelope", "endpoint": request_path, "response_payload": payload}
            return rows[:MAX_RECORDS - 1] + [failure]
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
    path = output_dir / "index.md"
    lines = frontmatter(
        "platform_api",
        knowledge_relative_path(path),
        generated_at,
        manifest,
        [START_HERE_TARGET],
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
    write_markdown(path, lines)
    return path


def write_raw_operators(operators: list[dict[str, Any]], generated_at: str, output_dir: Path,
                        *, root: Path | None = None) -> Path:
    """Input: operator rows, timestamp, output dir. Output: path. Write raw official operator records as Markdown."""
    path = output_dir / "operators.md"
    lines = frontmatter(
        "platform_learn_material" if material_rows_valid(operators, "operator") else "platform_capture_error",
        knowledge_relative_path(path, root),
        generated_at,
        operators,
        [TEMPLATE_OPERATOR_TARGET, OPERATOR_LEDGER_TARGET],
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
    if not material_rows_valid(operators, "operator"):
        lines.extend(["", "## Untrusted Response", "", "```json",
                      json.dumps(operators, ensure_ascii=False, indent=2, sort_keys=True), "```"])
    write_markdown(path, lines, root=root)
    return path


def write_raw_documentation_pages(pages: list[dict[str, Any]], generated_at: str, output_dir: Path,
                                  *, root: Path | None = None) -> Path:
    """Input: documentation page rows, timestamp, output dir. Output: path. Write raw Learn documentation pages."""
    path = output_dir / "documentation_pages.md"
    lines = frontmatter(
        "platform_learn_material" if material_rows_valid(pages, "tutorial") else "platform_capture_error",
        knowledge_relative_path(path, root),
        generated_at,
        pages,
        [
            START_HERE_TARGET,
            FACTOR_PRINCIPLES_TARGET,
            DATA_SEMANTICS_TARGET,
            TEMPLATE_OPERATOR_TARGET,
            BENCHMARK_REPAIR_TARGET,
        ],
    )
    lines.insert(-1, 'material_kind: documentation_page')
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
    lines.extend(["", "## Raw Documentation Payload", "", "```json",
                  json.dumps(pages, ensure_ascii=False, indent=2, sort_keys=True), "```"])
    if not material_rows_valid(pages, "tutorial"):
        lines.extend(["", "## Untrusted Response", "", "```json",
                      json.dumps(pages, ensure_ascii=False, indent=2, sort_keys=True), "```"])
    write_markdown(path, lines, root=root)
    return path


def write_raw_errors(errors: list[dict[str, str]], generated_at: str, output_dir: Path,
                     *, root: Path | None = None) -> Path:
    """Input: fetch error rows, timestamp, output dir. Output: path. Write raw documentation fetch errors."""
    path = output_dir / "documentation_errors.md"
    lines = frontmatter(
        "platform_api",
        knowledge_relative_path(path, root),
        generated_at,
        errors,
        [START_HERE_TARGET],
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
    write_markdown(path, lines, root=root)
    return path


def write_raw_rows(
    section_name: str,
    endpoint: str,
    rows: list[dict[str, Any]],
    generated_at: str,
    output_dir: Path,
    filename: str,
    compiled_targets: list[str],
    *,
    root: Path | None = None,
) -> Path:
    """Input: row section metadata and rows. Output: path. Write raw API rows as Markdown."""
    path = output_dir / filename
    source_type = "platform_learn_material" if endpoint in PAGINATED_ENDPOINTS.values() and material_rows_valid(rows, "rows") else "platform_api"
    lines = frontmatter(source_type, knowledge_relative_path(path, root), generated_at, rows, compiled_targets)
    lines.extend(["", f"# {section_name}", "", f"Record count: {len(rows)}", ""])
    lines.extend(["", f"Source endpoint: `{endpoint}`", ""])
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
    write_markdown(path, lines, root=root)
    return path


def write_raw_search_results(search_results: dict[str, Any], generated_at: str, output_dir: Path) -> Path:
    """Input: search results, timestamp, output dir. Output: path. Write raw Learn search discovery results."""
    path = output_dir / "search_results.md"
    lines = frontmatter(
        "platform_api",
        knowledge_relative_path(path),
        generated_at,
        search_results,
        [START_HERE_TARGET],
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
    write_markdown(path, lines)
    return path


def update_learn_source_index(paths: list[Path], root: Path | None = None) -> Path:
    """Input: raw Learn paths. Output: source index path. Register raw Learn files in machine/raw indexes."""
    active_root = root if root is not None else KNOWLEDGE_ROOT
    for path in (*paths, active_root / "raw/source_index.md", active_root / "machine/source_index.jsonl",
                 active_root / "machine/source_index_write.guard"):
        guard_capture_path(active_root, path)
    rows: list[SourceIndexRow] = []
    for path in paths:
        metadata, _ = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
        relative_path = knowledge_relative_path(path, root)
        targets = metadata.get("compiled_targets", [])
        rows.append(
            SourceIndexRow(
                path=relative_path,
                source_family=str(metadata.get("source_family", RAW_LEARN_SOURCE_FAMILY)),
                source_type=str(metadata.get("source_type", "platform_api")),
                contents=f"WorldQuant BRAIN Learn capture file {path.name}",
                update_check=str(metadata.get("update_check", "compare with previous Learn capture")),
                captured_at=str(metadata.get("captured_at", "")),
                record_count=int(metadata.get("record_count", 0) or 0),
                content_hash=str(metadata.get("content_hash", "")),
                content_status=str(metadata.get("content_status", "")),
                compiled_targets=[str(target) for target in targets] if isinstance(targets, list) else [],
            )
        )
    return upsert_source_index_rows(root if root is not None else KNOWLEDGE_ROOT, rows)


def capture_resource_subset(root: Path, client, targets: list[dict], generated_at: str,
                            *, request_limit: int = 12) -> dict:
    """Input: knowledge Path, single-attempt client, target dicts, ISO str, int GET cap.

    Output: dict with attempted_requests, successful_targets, remaining_targets, errors,
    raw_markdown_files and generated_at. Persist raw/index receipts only. Targets are
    {kind: operators}, {kind: operator, id: name}, {kind: operator_detail, id: name},
    or {kind: tutorial, id: page_id}. Detail uses the /operators/{id} route recorded
    in official operator cards; it never accepts an arbitrary caller-supplied URL.
    WQBClient must already be authenticated; other clients must implement a finite
    single-attempt get_json(path). No authentication, retries or redirects here.
    """
    if type(request_limit) is not int or request_limit < 0:
        raise ValueError("request_limit must be a nonnegative integer")
    if not isinstance(targets, list):
        raise ValueError("targets must be a list")
    datetime.fromisoformat(generated_at)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T[^\r\n/\\]+", generated_at):
        raise ValueError("generated_at must be an ISO datetime")
    endpoints = []
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("target must be a dict")
        kind = target.get("kind")
        if kind == "operators" and set(target) == {"kind"}:
            endpoints.append("/operators")
        elif kind in {"operator", "operator_detail", "tutorial"} and set(target) == {"kind", "id"}:
            identity = target["id"]
            if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
                raise ValueError("target id must be a simple known source identifier")
            if kind == 'operator':
                endpoints.append('/operators')
            elif kind == 'operator_detail':
                endpoints.append(f'/operators/{identity}')
            else:
                endpoints.append(f'/tutorial-pages/{identity}')
        else:
            raise ValueError("only explicit operator/list or tutorial targets are supported")
    if isinstance(client, WQBClient) and targets and request_limit and not client.authenticated:
        raise ValueError("authenticate the WQBClient separately before bounded capture")
    result = {"generated_at": generated_at, "attempted_requests": 0, "successful_targets": [],
              "remaining_targets": [], "errors": [], "raw_markdown_files": []}
    paths = []
    for index, (target, endpoint) in enumerate(zip(targets, endpoints)):
        if result["attempted_requests"] >= request_limit:
            result["remaining_targets"] = targets[index:]
            break
        guard_capture_outputs(root, generated_at)
        result["attempted_requests"] += 1
        payload = None
        response = None
        try:
            if isinstance(client, WQBClient):
                response = client._dispatch("GET", BASE_URL + endpoint,
                                            timeout=min(client.timeout_seconds, REQUEST_TIMEOUT_SECONDS),
                                            allow_redirects=False)
                if response.status_code != 200:
                    payload = bounded_response_payload(response)
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError(f"unexpected HTTP status {response.status_code}")
                payload = response.json()
            else:
                payload = client.get_json(endpoint)
            documentation_page = (target['kind'] == 'tutorial' or
                (target['kind'] == 'operator_detail' and isinstance(payload, dict)
                 and ('content' in payload or ('title' in payload and 'name' not in payload))))
            if documentation_page:
                if (not isinstance(payload, dict) or payload.get("id") != target["id"]
                        or (target['kind'] == 'operator_detail' and
                            (not isinstance(payload.get('title'), str) or not payload['title'].strip()))
                        or not material_rows_valid([payload], "tutorial")):
                    raise ValueError("missing or invalid non-course tutorial material")
                rows = [payload]
            else:
                if target['kind'] == 'operator_detail':
                    if not isinstance(payload, dict):
                        raise ValueError('operator detail requires one direct object')
                    rows = [payload]
                else:
                    rows = result_rows(payload)
                if ((isinstance(payload, dict) and any(key in payload for key in ("error", "errors", "detail")))
                        or not material_rows_valid(rows, "operator")):
                    raise ValueError("missing or invalid operator material")
                if target["kind"] in {"operator", "operator_detail"}:
                    rows = [row for row in rows if row.get("name") == target["id"]]
                    if len(rows) != 1 or ('id' in rows[0] and rows[0]['id'] != target['id']):
                        raise ValueError("operator target must match exactly one returned row")
        except Exception as error:
            error_response = getattr(error, "response", None)
            if error_response is not None:
                response = error_response
                if payload is None:
                    payload = bounded_response_payload(response)
            failure = {"target": dict(target), "endpoint": endpoint, "error": type(error).__name__,
                       "message": str(error), "status_code": getattr(response, "status_code", None),
                       "retry_after": response.headers.get("Retry-After") if response is not None else None,
                       "response_payload": payload}
            result["errors"].append(failure)
            rows = None
        receipt = {"generated_at": generated_at, "target": target, "endpoint": endpoint, "payload": payload,
                   "error": result["errors"][-1] if rows is None else None}
        output_dir = raw_capture_dir(generated_at, root) / ("subset-" + stable_json_hash(receipt))
        guard_capture_outputs(root, generated_at)
        guard_capture_path(root, output_dir)
        if rows is None:
            path = output_dir / "request_error.md"
            lines = frontmatter("platform_capture_error", knowledge_relative_path(path, root),
                                generated_at, receipt, [])
        else:
            if documentation_page:
                path = write_raw_documentation_pages(rows, generated_at, output_dir, root=root)
            else:
                path = write_raw_operators(rows, generated_at, output_dir, root=root)
            lines = path.read_text(encoding="utf-8").splitlines()
            result["successful_targets"].append(dict(target))
        lines.extend(["", "## Raw GET Receipt", "", "```json",
                      json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True), "```"])
        write_markdown(path, lines, root=root)
        paths.append(path)
    if paths:
        update_learn_source_index(paths, root)
    result["raw_markdown_files"] = [str(path) for path in paths]
    return result


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
            [BENCHMARK_REPAIR_TARGET],
        ),
        write_raw_rows(
            "Videos",
            "/videos",
            capture["videos"],
            capture["generated_at"],
            output_dir,
            "videos.md",
            [DATA_SEMANTICS_TARGET, TEMPLATE_OPERATOR_TARGET],
        ),
        write_raw_rows(
            "Recommended Readings",
            "/recommended-readings",
            capture["recommended_readings"],
            capture["generated_at"],
            output_dir,
            "recommended_readings.md",
            [TEMPLATE_OPERATOR_TARGET],
        ),
        write_raw_search_results(capture["search_results"], capture["generated_at"], output_dir),
    ]
    update_learn_source_index(paths)
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
    """Input: raw capture dict. Output: None. Compile Learn source inventory into a machine preview."""
    generated_at = capture["generated_at"]
    documentation_pages = capture["documentation_pages"]
    lines = [
        "# Learn Material Preview",
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
            "- Read this preview before creating a new research plan when platform rules may have changed.",
            "- Use the operator catalog preview for operator availability and descriptions before generating templates.",
            "- Refresh this capture when rules, activities, operators, or Learn navigation changes.",
        ]
    )
    WIKI_LEARN_PAGE.parent.mkdir(parents=True, exist_ok=True)
    WIKI_LEARN_PAGE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_operator_wiki(operators: list[dict[str, Any]], generated_at: str) -> None:
    """Input: operator rows and timestamp. Output: None. Compile official operator metadata into a machine preview."""
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
