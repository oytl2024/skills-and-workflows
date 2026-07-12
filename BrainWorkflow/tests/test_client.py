import unittest
from unittest.mock import patch

import requests

from wqb.client import BASE_URL, WQBClient


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
