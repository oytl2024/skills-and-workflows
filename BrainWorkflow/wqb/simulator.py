import time
from typing import Any


def submit_simulation(client, payload: dict[str, Any]) -> str:
    """Input: WQB client and simulation payload. Output: progress URL. Submit one simulation."""
    response = client.post_json("/simulations", payload)
    location = response.headers.get("Location")
    if not location:
        raise RuntimeError("simulation response missing Location header")
    return location


def submit_multisimulation(client, payloads: list[dict[str, Any]]) -> str:
    """Input: WQB client and payload list. Output: progress URL. Submit a multisimulation batch."""
    if not payloads:
        raise ValueError("multisimulation requires at least one payload")
    response = client.post_json("/simulations", payloads)
    location = response.headers.get("Location")
    if not location:
        raise RuntimeError("multisimulation response missing Location header")
    return location


def poll_simulation(client, progress_url: str) -> dict[str, Any]:
    """Input: WQB client and progress URL. Output: final progress JSON. Poll until platform says complete."""
    while True:
        response = client.request("GET", progress_url)
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            time.sleep(float(retry_after))
            continue
        response.raise_for_status()
        return response.json()


def extract_alpha_id(progress: dict[str, Any]) -> str:
    """Input: simulation progress JSON. Output: alpha id. Normalize platform result variants."""
    alpha_id = progress.get("alpha")
    if isinstance(alpha_id, str) and alpha_id:
        return alpha_id
    if isinstance(alpha_id, dict) and alpha_id.get("id"):
        return str(alpha_id["id"])
    raise RuntimeError(f"simulation progress missing alpha id: {progress}")


def alpha_ids_from_value(value: Any) -> list[str]:
    """Input: alpha value variant. Output: alpha ids. Normalize strings, dicts, and lists."""
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, dict):
        if isinstance(value.get("alpha"), (str, dict, list)):
            return alpha_ids_from_value(value["alpha"])
        if value.get("id"):
            return [str(value["id"])]
    if isinstance(value, list):
        alpha_ids: list[str] = []
        for item in value:
            alpha_ids.extend(alpha_ids_from_value(item))
        return alpha_ids
    return []


def extract_alpha_ids(progress: dict[str, Any]) -> list[str]:
    """Input: multisimulation progress JSON. Output: alpha ids. Normalize batch result variants."""
    alpha_ids = alpha_ids_from_value(progress.get("alpha"))
    if not alpha_ids:
        children = progress.get("children")
        if isinstance(children, list) and all(isinstance(child, dict) for child in children):
            alpha_ids = alpha_ids_from_value(children)
    if alpha_ids:
        return alpha_ids
    raise RuntimeError(f"multisimulation progress missing alpha ids: {progress}")


def resolve_multisimulation_alpha_ids(client, progress: dict[str, Any]) -> list[str]:
    """Input: WQB client and parent progress. Output: alpha ids. Resolve child simulations if needed."""
    try:
        return extract_alpha_ids(progress)
    except RuntimeError:
        children = progress.get("children")
        if not isinstance(children, list) or not children:
            raise
    alpha_ids: list[str] = []
    for child in children:
        child_id = child.get("id") if isinstance(child, dict) else child
        if not child_id:
            continue
        child_progress = poll_simulation(client, f"/simulations/{child_id}")
        alpha_ids.append(extract_alpha_id(child_progress))
    if not alpha_ids:
        raise RuntimeError(f"multisimulation progress missing alpha ids: {progress}")
    return alpha_ids
