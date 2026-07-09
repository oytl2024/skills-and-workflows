from typing import Any
from urllib.parse import quote


DETAIL_PATHS = {
    "tutorialPage": "/tutorial-pages/{id}",
    "faq": "/faqs/{id}",
    "message": "/messages/{id}",
    "video": "/videos/{id}",
}


def fetch_knowledge_snapshot(client, queries: list[str]) -> dict[str, Any]:
    """Input: WQB client and query list. Output: knowledge snapshot dict. Save source material for this run."""
    snapshot: dict[str, Any] = {"queries": {}, "details": {}, "detail_errors": {}, "power_pool_boards": None}
    for query in queries:
        result = client.get_json(f"/search?query={quote(query)}")
        snapshot["queries"][query] = result
        for group, template in DETAIL_PATHS.items():
            group_result = result.get(group)
            results = group_result.get("results", []) if isinstance(group_result, dict) else []
            for item in results[:3]:
                item_id = item.get("id")
                if not item_id:
                    continue
                key = f"{group}:{item_id}"
                if key not in snapshot["details"]:
                    try:
                        snapshot["details"][key] = client.get_json(template.format(id=item_id))
                    except Exception as err:
                        snapshot["detail_errors"][key] = {
                            "error": type(err).__name__,
                            "message": str(err),
                        }

    snapshot["events"] = client.get_json("/events?limit=20&offset=0")
    snapshot["competitions"] = client.get_json("/competitions?limit=20&offset=0")
    snapshot["power_pool_boards"] = client.options_json("/consultant/boards/power-pool")
    return snapshot
