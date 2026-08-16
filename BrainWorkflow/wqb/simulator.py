import time
from typing import Any

import requests


MAX_SIMULATION_POLL_RETRY_AFTER_POLLS = 120
MAX_SIMULATION_POLL_RETRY_AFTER_WAIT_SECONDS = 900.0


class SimulationPollTimeout(requests.exceptions.Timeout):
    """Input: poll metadata. Output: recoverable timeout exception. Signal bounded simulation polling expiry."""

    def __init__(
        self,
        message: str,
        *,
        progress_url: str = "",
        retry_after_polls: int | None = None,
        wait_seconds: float | None = None,
        max_polls: int | None = None,
        max_wait_seconds: float | None = None,
        response=None,
    ) -> None:
        super().__init__(message, response=response)
        self.simulation_poll_timeout = True
        self.progress_url = progress_url
        self.retry_after_polls = retry_after_polls
        self.wait_seconds = wait_seconds
        self.max_polls = max_polls
        self.max_wait_seconds = max_wait_seconds


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


def _retry_after_seconds(value: str) -> float:
    """Input: Retry-After header string. Output: seconds as float. Parse platform pacing hints."""
    seconds = float(value)
    if seconds < 0:
        raise requests.exceptions.InvalidHeader(f"Retry-After must be non-negative: {value}")
    return seconds


def _request_progress(client, progress_url: str):
    """Input: WQB-compatible client and URL. Output: response. Request progress without client Retry-After sleep."""
    try:
        return client.request("GET", progress_url, respect_retry_after=False)
    except TypeError as err:
        if "respect_retry_after" not in str(err):
            raise
        return client.request("GET", progress_url)


def poll_simulation(
    client,
    progress_url: str,
    max_retry_after_polls: int = MAX_SIMULATION_POLL_RETRY_AFTER_POLLS,
    max_retry_after_wait_seconds: float = MAX_SIMULATION_POLL_RETRY_AFTER_WAIT_SECONDS,
) -> dict[str, Any]:
    """Input: WQB client, progress URL, bounds. Output: final progress JSON. Poll with bounded platform pacing."""
    if max_retry_after_polls < 0:
        raise ValueError("max_retry_after_polls must be greater than or equal to 0")
    if max_retry_after_wait_seconds < 0:
        raise ValueError("max_retry_after_wait_seconds must be greater than or equal to 0")
    retry_after_polls = 0
    retry_after_wait_seconds = 0.0
    while True:
        response = _request_progress(client, progress_url)
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            retry_after_polls += 1
            sleep_seconds = _retry_after_seconds(str(retry_after))
            projected_wait = retry_after_wait_seconds + sleep_seconds
            if retry_after_polls > max_retry_after_polls or projected_wait > max_retry_after_wait_seconds:
                raise SimulationPollTimeout(
                    (
                        "simulation poll exceeded Retry-After limit "
                        f"for {progress_url}: polls={retry_after_polls}, "
                        f"wait_seconds={projected_wait:.1f}, "
                        f"max_polls={max_retry_after_polls}, "
                        f"max_wait_seconds={max_retry_after_wait_seconds:.1f}"
                    ),
                    progress_url=progress_url,
                    retry_after_polls=retry_after_polls,
                    wait_seconds=projected_wait,
                    max_polls=max_retry_after_polls,
                    max_wait_seconds=max_retry_after_wait_seconds,
                    response=response,
                )
            retry_after_wait_seconds = projected_wait
            time.sleep(sleep_seconds)
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
