import time
from typing import Any

import requests

from wqb.auth import load_credentials


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

    def authenticate(self) -> None:
        """Input: env credentials. Output: authenticated session. Authenticate against WorldQuant Brain."""
        username, password = load_credentials()
        self.session.auth = (username, password)
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(f"{BASE_URL}/authentication", timeout=self.timeout_seconds)
            except requests.exceptions.RequestException:
                if attempt < self.max_retries:
                    time.sleep(self.base_backoff_seconds * (attempt + 1))
                    continue
                raise
            retry_after = response.headers.get("Retry-After")
            if retry_after and attempt < self.max_retries:
                time.sleep(float(retry_after))
                continue
            if response.status_code == 429 and attempt < self.max_retries:
                time.sleep(self.base_backoff_seconds * (attempt + 1))
                continue
            if 500 <= response.status_code < 600 and attempt < self.max_retries:
                time.sleep(self.base_backoff_seconds * (attempt + 1))
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
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout_seconds, **kwargs)
            except requests.exceptions.RequestException:
                if attempt < self.max_retries:
                    time.sleep(self.base_backoff_seconds * (attempt + 1))
                    continue
                raise
            retry_after = response.headers.get("Retry-After")
            if respect_retry_after and retry_after and attempt < self.max_retries:
                time.sleep(float(retry_after))
                continue
            if response.status_code == 401 and attempt < self.max_retries:
                self.authenticated = False
                self.authenticate()
                continue
            if respect_retry_after and response.status_code == 429 and attempt < self.max_retries:
                time.sleep(self.base_backoff_seconds * (attempt + 1))
                continue
            if 500 <= response.status_code < 600 and attempt < self.max_retries:
                time.sleep(self.base_backoff_seconds * (attempt + 1))
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
