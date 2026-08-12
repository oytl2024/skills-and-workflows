from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path

from wqb.rate_limit_state import (
    compute_backoff_seconds,
    cooldown_is_active,
    parse_retry_after_seconds,
    read_rate_limit_state,
    record_rate_limit,
)


class RateLimitStateTests(unittest.TestCase):
    def test_parse_retry_after_seconds_accepts_delta_seconds(self):
        now = datetime(2026, 8, 12, 0, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(parse_retry_after_seconds({"Retry-After": "120"}, now), 120)

    def test_parse_retry_after_seconds_accepts_http_date(self):
        now = datetime(2026, 8, 12, 0, 0, 0, tzinfo=timezone.utc)

        seconds = parse_retry_after_seconds({"Retry-After": "Wed, 12 Aug 2026 00:02:00 GMT"}, now)

        self.assertEqual(seconds, 120)

    def test_compute_backoff_is_bounded_and_deterministic(self):
        self.assertEqual(compute_backoff_seconds(1), 63)
        self.assertEqual(compute_backoff_seconds(2), 126)
        self.assertEqual(compute_backoff_seconds(20), 900)

    def test_record_rate_limit_writes_durable_state(self):
        class Error(Exception):
            response = type("Response", (), {"status_code": 429, "headers": {"Retry-After": "60"}})()

        with tempfile.TemporaryDirectory() as tmp:
            state = record_rate_limit(
                Path(tmp),
                "retry_planned_submit",
                Error("HTTP 429"),
                {"expression_hash": "h1", "progress_url": "progress/1"},
                "2026-08-12T00:00:00+00:00",
            )
            loaded = read_rate_limit_state(Path(tmp) / "rate_limit_state.json")

        self.assertEqual(state["status"], "cooldown")
        self.assertEqual(loaded["last_status_code"], 429)
        self.assertEqual(loaded["last_candidate_hash"], "h1")
        self.assertTrue(cooldown_is_active(loaded, "2026-08-12T00:00:30+00:00"))
        self.assertFalse(cooldown_is_active(loaded, "2026-08-12T00:01:01+00:00"))


if __name__ == "__main__":
    unittest.main()
