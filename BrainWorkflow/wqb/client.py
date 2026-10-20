import time
import os
from contextlib import nullcontext
from typing import Any
from pathlib import Path

import requests

from wqb.auth import load_credentials
from wqb.request_metrics import record_request
from wqb.runtime_control import CONTROL_ENV, check_submission_allowed, cooperative_sleep, submission_request_gate


BASE_URL = "https://api.worldquantbrain.com"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Connection": "close",
}


class WQBClient:
    def __init__(
        self,
        timeout_seconds: int = 30,
        max_retries: int = 4,
        base_backoff_seconds: int = 3,
        session: requests.Session | None = None,
        metrics_run_dir: Path | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        if max_retries < 0:
            raise ValueError("max_retries must be greater than or equal to 0")
        if base_backoff_seconds < 0:
            raise ValueError("base_backoff_seconds must be greater than or equal to 0")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.authenticated = False
        self.metrics_run_dir = metrics_run_dir

    def _dispatch(self, method: str, url: str, *, authentication: bool = False, **kwargs: Any):
        """Input: method/URL and request kwargs. Output: response. Measure one actual attempt without changing outcomes."""
        started = time.monotonic()
        response = None
        payload = kwargs.get("json")
        try:
            if authentication:
                response = self.session.post(url, **kwargs)
            else:
                response = self.session.request(method, url, **kwargs)
            return response
        finally:
            root = self.metrics_run_dir or os.environ.get(CONTROL_ENV)
            if root:
                try:
                    record_request(Path(root), {"method": method, "path": url,
                        "status": response.status_code if response is not None else 0,
                        "headers": response.headers if response is not None else {},
                        "duration_seconds": time.monotonic() - started,
                        "payload_count": len(payload) if isinstance(payload, list) else int(isinstance(payload, dict)),
                        "transport_error": response is None})
                except (OSError, ValueError, TypeError):
                    # Diagnostic failure must not turn an accepted POST into a retry.
                    pass

    def authenticate(self) -> None:
        """Input: env credentials. Output: authenticated session. Authenticate against WorldQuant Brain."""
        username, password = load_credentials()
        self.session.auth = (username, password)
        for attempt in range(self.max_retries + 1):
            try:
                response = self._dispatch("POST", f"{BASE_URL}/authentication", authentication=True, timeout=self.timeout_seconds)
            except requests.exceptions.RequestException:
                if attempt < self.max_retries:
                    cooperative_sleep(self.base_backoff_seconds * (attempt + 1))
                    continue
                raise
            retry_after = response.headers.get("Retry-After")
            if retry_after and attempt < self.max_retries:
                cooperative_sleep(float(retry_after))
                continue
            if response.status_code == 429 and attempt < self.max_retries:
                cooperative_sleep(self.base_backoff_seconds * (attempt + 1))
                continue
            if 500 <= response.status_code < 600 and attempt < self.max_retries:
                cooperative_sleep(self.base_backoff_seconds * (attempt + 1))
                continue
            break
        response.raise_for_status()
        self.authenticated = True

    def request(self, method: str, path: str, *, respect_retry_after: bool = True, **kwargs: Any) -> requests.Response:
        """Input: HTTP method/path. Output: response. Retry transient failures and respect platform pacing."""
        if not self.authenticated:
            self.authenticate()
        if path.startswith(("http://", "https://")):
            url = path
        else:
            url = f"{BASE_URL}/{path.lstrip('/')}"
        managed = bool(os.environ.get(CONTROL_ENV))
        # Simulation POST has no idempotency guarantee; let the durable driver own retries.
        simulation_submit = method.upper() == "POST" and url.rstrip('/').endswith('/simulations')
        managed_submit = managed and simulation_submit
        retry_limit = 0 if simulation_submit else self.max_retries
        for attempt in range(retry_limit + 1):
            gate = submission_request_gate(os.environ[CONTROL_ENV]) if managed_submit else nullcontext()
            with gate:
                if managed:
                    check_submission_allowed()
                if managed_submit:
                    from wqb.original_batch_recovery import validate_original_payloads
                    validate_original_payloads(kwargs.get('json'))
                    from wqb.runtime_control import read_runtime_control
                    from wqb.rate_limit_state import check_source_retry_authorization
                    source = read_runtime_control(os.environ[CONTROL_ENV]).get("recovery_rate_limit_source", "")
                    if source:
                        check_source_retry_authorization(Path(source))
                try:
                    response = self._dispatch(method, url, timeout=self.timeout_seconds, **kwargs)
                except requests.exceptions.RequestException:
                    if simulation_submit:
                        raise RuntimeError("simulation submission outcome unknown; reconcile before retry") from None
                    if attempt < retry_limit:
                        cooperative_sleep(self.base_backoff_seconds * (attempt + 1))
                        continue
                    raise
            if simulation_submit:
                if response.status_code >= 500:
                    raise RuntimeError("simulation submission outcome unknown after server error; reconcile before retry")
                return response
            retry_after = response.headers.get("Retry-After")
            if respect_retry_after and retry_after and attempt < self.max_retries:
                cooperative_sleep(float(retry_after))
                continue
            if response.status_code == 401 and attempt < self.max_retries:
                self.authenticated = False
                self.authenticate()
                continue
            if respect_retry_after and response.status_code == 429 and attempt < self.max_retries:
                cooperative_sleep(self.base_backoff_seconds * (attempt + 1))
                continue
            if 500 <= response.status_code < 600 and attempt < self.max_retries:
                cooperative_sleep(self.base_backoff_seconds * (attempt + 1))
                continue
            return response
        return response

    def get_json(self, path: str) -> Any:
        """Input: API path. Output: parsed JSON. Fetch JSON with retry handling."""
        response = self.request("GET", path)
        response.raise_for_status()
        return response.json()

    def post_json(self, path: str, payload: Any) -> requests.Response:
        """Input: API path and JSON payload. Output: response. POST JSON with retry handling."""
        response = self.request("POST", path, json=payload)
        response.raise_for_status()
        return response

    def options_json(self, path: str) -> Any:
        """Input: API path. Output: parsed OPTIONS JSON. Read API metadata for allowed filters."""
        response = self.request("OPTIONS", path)
        response.raise_for_status()
        return response.json()
