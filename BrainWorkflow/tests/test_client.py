import unittest
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import requests

from wqb.client import BASE_URL, WQBClient
from wqb.runtime_control import CONTROL_ENV, RuntimePaused, read_runtime_control, request_runtime_state, update_runtime_status


class FakeResponse:
    def __init__(self, status_code: int = 200, headers: dict | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, results: list | None = None) -> None:
        self.results = list(results or [FakeResponse()])
        self.auth = None
        self.headers = {}
        self.posts = []
        self.requests = []

    def post(self, url: str, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse(status_code=201)

    def request(self, method: str, url: str, **kwargs):
        self.requests.append((method, url, kwargs))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class AuthenticatingClient(WQBClient):
    def __init__(self) -> None:
        super().__init__(session=FakeSession())
        self.authenticate_calls = 0

    def authenticate(self) -> None:
        self.authenticate_calls += 1
        self.authenticated = True


class WQBClientRequestTest(unittest.TestCase):
    def test_expired_rate_retry_is_rechecked_after_authentication_before_post(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            source = Path(directory) / "source"
            source.mkdir()
            (source / "rate_limit_state.json").write_text(json.dumps({"status": "cooldown",
                "consecutive_429_count": 3, "retry_at": "2000-01-01T00:00:00+00:00"}))
            request_runtime_state(run, "running", enable_live_api=True)
            update_runtime_status(run, recovery_rate_limit_source=str(source))
            client = AuthenticatingClient()
            with patch.dict(os.environ, {CONTROL_ENV: str(run)}):
                with self.assertRaises(RuntimePaused):
                    client.post_json("/simulations", [{}])
            self.assertEqual(client.authenticate_calls, 1)
            self.assertEqual(client.session.requests, [])

    def test_standalone_simulation_post_never_retries_unknown_outcome(self):
        session = FakeSession([requests.exceptions.Timeout("response lost"), FakeResponse(status_code=201)])
        client = WQBClient(session=session, max_retries=1, base_backoff_seconds=0)
        client.authenticated = True
        with patch.dict(os.environ):
            os.environ.pop(CONTROL_ENV, None)
            with self.assertRaisesRegex(RuntimeError, "outcome unknown"):
                client.request("POST", "/simulations", json={})

        self.assertEqual(len(session.requests), 1)

    def test_managed_pause_ack_waits_for_actual_simulation_post(self):
        entered = threading.Event()
        release = threading.Event()
        pause_done = threading.Event()

        class BlockingSession(FakeSession):
            def request(self, method, url, **kwargs):
                self.requests.append((method, url, kwargs))
                entered.set()
                if not release.wait(3):
                    raise AssertionError("test POST was not released")
                return FakeResponse(status_code=201, headers={"Location": "/simulations/one"})

        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            request_runtime_state(run, "running", enable_live_api=True)
            session = BlockingSession()
            client = WQBClient(session=session)
            client.authenticated = True
            with patch.dict(os.environ, {CONTROL_ENV: str(run)}):
                worker = threading.Thread(target=lambda: client.request("POST", "/simulations", json={}))
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    pause = threading.Thread(target=lambda: (request_runtime_state(run, "paused"), pause_done.set()))
                    pause.start()
                    deadline = time.monotonic() + 2
                    while read_runtime_control(run).get("desired_state") != "paused" and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertEqual(read_runtime_control(run)["desired_state"], "paused")
                    self.assertFalse(pause_done.is_set())
                finally:
                    release.set()
                    worker.join(timeout=3)
                    pause.join(timeout=3)
                self.assertTrue(pause_done.is_set())
                with self.assertRaises(RuntimePaused):
                    client.request("POST", "/simulations", json={})
                self.assertEqual(len(session.requests), 1)

    def test_constructor_rejects_negative_max_retries(self):
        with self.assertRaises(ValueError):
            WQBClient(max_retries=-1)

    def test_constructor_rejects_non_positive_timeout(self):
        with self.assertRaises(ValueError):
            WQBClient(timeout_seconds=0)

    def test_constructor_rejects_negative_base_backoff(self):
        with self.assertRaises(ValueError):
            WQBClient(base_backoff_seconds=-1)

    def test_constructor_sets_proxy_compatible_headers(self):
        fake_session = FakeSession()

        WQBClient(session=fake_session)

        self.assertEqual("Mozilla/5.0", fake_session.headers["User-Agent"])
        self.assertEqual("close", fake_session.headers["Connection"])

    def test_request_adds_slash_for_relative_path_without_leading_slash(self):
        fake_session = FakeSession()
        client = WQBClient(session=fake_session)
        client.authenticated = True

        client.request("GET", "users/self")

        self.assertEqual(f"{BASE_URL}/users/self", fake_session.requests[0][1])

    def test_request_keeps_relative_path_with_leading_slash(self):
        fake_session = FakeSession()
        client = WQBClient(session=fake_session)
        client.authenticated = True

        client.request("GET", "/users/self")

        self.assertEqual(f"{BASE_URL}/users/self", fake_session.requests[0][1])

    def test_request_keeps_absolute_url(self):
        fake_session = FakeSession()
        client = WQBClient(session=fake_session)
        client.authenticated = True
        url = "https://example.com/users/self"

        client.request("GET", url)

        self.assertEqual(url, fake_session.requests[0][1])

    def test_retry_after_sleeps_before_final_attempt_only(self):
        fake_session = FakeSession(
            [
                FakeResponse(status_code=429, headers={"Retry-After": "2"}),
                FakeResponse(status_code=429, headers={"Retry-After": "2"}),
            ]
        )
        client = WQBClient(max_retries=1, session=fake_session)
        client.authenticated = True

        with patch("wqb.client.time.sleep") as sleep_mock:
            response = client.request("GET", "users/self")

        self.assertEqual(429, response.status_code)
        self.assertEqual(2, len(fake_session.requests))
        sleep_mock.assert_called_once_with(2.0)

    def test_429_retries_with_backoff(self):
        fake_session = FakeSession([FakeResponse(status_code=429), FakeResponse(status_code=200)])
        client = WQBClient(max_retries=1, base_backoff_seconds=3, session=fake_session)
        client.authenticated = True

        with patch("wqb.client.time.sleep") as sleep_mock:
            response = client.request("GET", "users/self")

        self.assertEqual(200, response.status_code)
        self.assertEqual(2, len(fake_session.requests))
        sleep_mock.assert_called_once_with(3)

    def test_5xx_retries_with_backoff(self):
        fake_session = FakeSession([FakeResponse(status_code=503), FakeResponse(status_code=200)])
        client = WQBClient(max_retries=1, base_backoff_seconds=4, session=fake_session)
        client.authenticated = True

        with patch("wqb.client.time.sleep") as sleep_mock:
            response = client.request("GET", "users/self")

        self.assertEqual(200, response.status_code)
        self.assertEqual(2, len(fake_session.requests))
        sleep_mock.assert_called_once_with(4)

    def test_401_reauthenticates_and_retries(self):
        client = AuthenticatingClient()
        client.session.results = [FakeResponse(status_code=401), FakeResponse(status_code=200)]
        client.max_retries = 1
        client.authenticated = True

        response = client.request("GET", "users/self")

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, client.authenticate_calls)
        self.assertEqual(2, len(client.session.requests))

    def test_timeout_exception_retries_and_succeeds(self):
        fake_session = FakeSession([requests.exceptions.Timeout("slow"), FakeResponse(status_code=200)])
        client = WQBClient(max_retries=1, base_backoff_seconds=5, session=fake_session)
        client.authenticated = True

        with patch("wqb.client.time.sleep") as sleep_mock:
            response = client.request("GET", "users/self")

        self.assertEqual(200, response.status_code)
        self.assertEqual(2, len(fake_session.requests))
        sleep_mock.assert_called_once_with(5)

    def test_final_transient_exception_is_reraised(self):
        fake_session = FakeSession(
            [
                requests.exceptions.Timeout("first"),
                requests.exceptions.Timeout("final"),
            ]
        )
        client = WQBClient(max_retries=1, base_backoff_seconds=5, session=fake_session)
        client.authenticated = True

        with patch("wqb.client.time.sleep") as sleep_mock:
            with self.assertRaises(requests.exceptions.Timeout):
                client.request("GET", "users/self")

        self.assertEqual(2, len(fake_session.requests))
        sleep_mock.assert_called_once_with(5)

    def test_authenticate_retries_transient_exception(self):
        class LoginSession(FakeSession):
            def __init__(self):
                super().__init__()
                self.post_results = [requests.exceptions.ConnectionError("reset"), FakeResponse(status_code=201)]

            def post(self, url: str, **kwargs):
                self.posts.append((url, kwargs))
                result = self.post_results.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result

        fake_session = LoginSession()
        client = WQBClient(max_retries=1, base_backoff_seconds=2, session=fake_session)

        with patch("wqb.client.load_credentials", return_value=("user", "pass")):
            with patch("wqb.client.time.sleep") as sleep_mock:
                client.authenticate()

        self.assertTrue(client.authenticated)
        self.assertEqual(2, len(fake_session.posts))
        sleep_mock.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
