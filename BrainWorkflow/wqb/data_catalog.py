from typing import Any
from urllib.parse import quote


GROUPING_FIELD_IDS = {"country", "industry", "subindustry", "currency", "market", "sector", "exchange"}


def _payload_rows_and_count(payload: Any) -> tuple[list[dict[str, Any]], int | None]:
    """Input: API payload. Output: rows and optional total count. Strictly validate catalog result shapes."""
    count: int | None = None
    if isinstance(payload, list):
        raw_rows = payload
    elif isinstance(payload, dict):
        if "results" not in payload:
            raise ValueError("catalog payload must be a list or contain a results list")
        raw_rows = payload["results"]
        if not isinstance(raw_rows, list):
            raise ValueError("catalog payload results must be a list")
        if "count" in payload:
            raw_count = payload.get("count")
            if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count < 0:
                raise ValueError("catalog payload count must be a non-negative integer")
            count = raw_count
    else:
        raise ValueError("catalog payload must be a list or contain a results list")
    if not all(isinstance(item, dict) for item in raw_rows):
        raise ValueError("catalog result entries must be JSON objects")
    return [dict(item) for item in raw_rows], count


def _fetch_paginated_rows(client, path_builder, limit: int, max_records: int) -> tuple[list[dict[str, Any]], bool]:
    """Input: client, path builder, page and record limits. Output: rows and truncation flag. Fetch a bounded catalog safely."""
    rows: list[dict[str, Any]] = []
    offset = 0
    page_limit = min(max(int(limit), 1), 50)
    record_limit = max(int(max_records), 0)
    latest_count: int | None = None
    while len(rows) < record_limit:
        request_limit = min(page_limit, record_limit - len(rows))
        batch, authoritative_count = _payload_rows_and_count(client.get_json(path_builder(request_limit, offset)))
        if authoritative_count is not None:
            latest_count = authoritative_count
        rows.extend(batch[:request_limit])
        fetched = offset + len(batch)
        if latest_count is not None and latest_count > fetched and len(batch) < request_limit:
            return rows, True
        if len(batch) < request_limit:
            return rows, False
        if latest_count is not None and latest_count <= fetched:
            return rows, False
        offset += request_limit
    if record_limit == 0:
        return rows, False
    if latest_count is not None and latest_count > len(rows):
        return rows, True
    return rows, bool(result_rows(client.get_json(path_builder(1, offset))))


def fetch_data_fields(
    client,
    instrument_type: str,
    region: str,
    delay: int,
    universe: str,
    dataset_id: str = "",
    search: str = "",
    limit: int = 50,
    max_records: int = 300,
) -> list[dict[str, Any]]:
    """Input: WQB client and field filters. Output: data-field records. Fetch a bounded field pool."""
    fields, _ = fetch_data_fields_with_metadata(
        client, instrument_type, region, delay, universe, dataset_id, search, limit, max_records
    )
    return fields


def fetch_data_fields_with_metadata(
    client,
    instrument_type: str,
    region: str,
    delay: int,
    universe: str,
    dataset_id: str = "",
    search: str = "",
    limit: int = 50,
    max_records: int = 300,
) -> tuple[list[dict[str, Any]], bool]:
    """Input: WQB client and field filters. Output: rows and truncation flag. Detect bounded field pagination."""
    def path_builder(page_limit: int, offset: int) -> str:
        path = (
            f"/data-fields?instrumentType={instrument_type}&region={region}&delay={delay}"
            f"&universe={universe}&limit={page_limit}&offset={offset}"
        )
        if dataset_id:
            path += f"&dataset.id={quote(dataset_id)}"
        if search:
            path += f"&search={quote(search)}"
        return path

    return _fetch_paginated_rows(client, path_builder, limit, max_records)


def select_seed_fields(fields: list[dict[str, Any]], max_fields: int = 40) -> list[dict[str, Any]]:
    """Input: data-field records. Output: ranked seed fields. Prefer high coverage and non-grouping fields."""
    usable = []
    for field in fields:
        field_id = field.get("id")
        if not field_id:
            continue
        if field_id in GROUPING_FIELD_IDS:
            continue
        usable.append(field)

    def score(field: dict[str, Any]) -> tuple[float, float, str]:
        """Input: data-field record. Output: sortable tuple. Rank by coverage, alpha count, then id."""
        coverage = field.get("coverage") or 0
        alpha_count = field.get("alphaCount") or 0
        return (float(coverage), float(alpha_count), str(field.get("id")))

    return sorted(usable, key=score, reverse=True)[:max_fields]


def filter_fields_by_suffix(fields: list[dict[str, Any]], suffix: str) -> list[dict[str, Any]]:
    """Input: data-field records and suffix. Output: fields whose ids end with suffix."""
    if not suffix:
        return list(fields)
    return [field for field in fields if str(field.get("id", "")).endswith(suffix)]


def field_ids(fields: list[dict[str, Any]]) -> set[str]:
    """Input: data-field records. Output: set of field ids. Support expression complexity checks."""
    return {str(field["id"]) for field in fields if field.get("id")}


def result_rows(payload: Any) -> list[dict[str, Any]]:
    """Input: API payload. Output: result rows. Normalize list and {'results': list} shapes."""
    rows, _ = _payload_rows_and_count(payload)
    return rows


def fetch_operators(client) -> list[dict[str, Any]]:
    """Input: WQB client. Output: operator metadata rows. Fetch the operator catalog once."""
    return result_rows(client.get_json("/operators"))


def fetch_data_sets(
    client,
    instrument_type: str,
    region: str,
    delay: int,
    universe: str,
    limit: int = 100,
    max_records: int = 1000,
) -> list[dict[str, Any]]:
    """Input: client and setting filters. Output: dataset rows. Fetch a bounded dataset catalog."""
    rows, _ = fetch_data_sets_with_metadata(
        client, instrument_type, region, delay, universe, limit, max_records
    )
    return rows


def fetch_data_sets_with_metadata(
    client,
    instrument_type: str,
    region: str,
    delay: int,
    universe: str,
    limit: int = 100,
    max_records: int = 1000,
) -> tuple[list[dict[str, Any]], bool]:
    """Input: client and setting filters. Output: rows and truncation flag. Detect bounded dataset pagination."""
    def path_builder(page_limit: int, offset: int) -> str:
        return (
            f"/data-sets?instrumentType={instrument_type}&region={region}&delay={delay}"
            f"&universe={universe}&limit={page_limit}&offset={offset}"
        )

    return _fetch_paginated_rows(client, path_builder, limit, max_records)


def build_metadata_cache(
    client,
    config: dict[str, Any],
    dataset_ids: list[str],
    field_searches: list[str],
    field_suffix: str,
    max_fields_per_query: int,
    include_data_sets: bool = True,
) -> dict[str, Any]:
    """Input: client, config, dataset/search filters. Output: cache dict. Fetch metadata for local reuse."""
    clean_dataset_ids = [item.strip() for item in dataset_ids if item and item.strip()]
    if not clean_dataset_ids:
        clean_dataset_ids = [""]
    clean_searches = [item.strip() for item in field_searches if item and item.strip()] or [""]
    data_sets = []
    if include_data_sets:
        data_sets = fetch_data_sets(
            client,
            config["instrument_type"],
            config["region"],
            int(config["delay"]),
            config["universe"],
        )
    cache: dict[str, Any] = {
        "config": {
            "instrument_type": config["instrument_type"],
            "region": config["region"],
            "delay": int(config["delay"]),
            "universe": config["universe"],
        },
        "operators": fetch_operators(client),
        "data_sets": data_sets,
        "field_queries": [],
    }
    for dataset_id in clean_dataset_ids:
        for search in clean_searches:
            fields = fetch_data_fields(
                client,
                config["instrument_type"],
                config["region"],
                int(config["delay"]),
                config["universe"],
                dataset_id=dataset_id,
                search=search,
                limit=min(max(int(max_fields_per_query), 1), 100),
                max_records=max(int(max_fields_per_query), 1),
            )
            if field_suffix:
                fields = filter_fields_by_suffix(fields, field_suffix)
            cache["field_queries"].append(
                {
                    "dataset_id": dataset_id,
                    "field_search": search,
                    "field_suffix": field_suffix,
                    "fields": fields,
                }
            )
    return cache


def cached_fields(
    cache: dict[str, Any],
    dataset_id: str = "",
    field_search: str = "",
    field_suffix: str = "",
) -> list[dict[str, Any]]:
    """Input: cache and filters. Output: fields. Select cached fields without calling the API."""
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for query in cache.get("field_queries", []):
        query_dataset_id = str(query.get("dataset_id", ""))
        if dataset_id and query_dataset_id and query_dataset_id != dataset_id:
            continue
        if field_search and query.get("field_search") != field_search:
            continue
        fields = query.get("fields", [])
        if field_suffix:
            fields = filter_fields_by_suffix(fields, field_suffix)
        for field in fields:
            field_dataset = field.get("dataset") if isinstance(field.get("dataset"), dict) else {}
            field_dataset_id = str(field_dataset.get("id") or field.get("dataset_id") or "")
            if dataset_id and not query_dataset_id and field_dataset_id != dataset_id:
                continue
            field_id = str(field.get("id", ""))
            if not field_id or field_id in seen_ids:
                continue
            seen_ids.add(field_id)
            rows.append(field)
    return rows
