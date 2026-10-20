from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path

import wqb.rate_limit_state as rate_limit_state
from wqb.rate_limit_state import (
    compute_backoff_seconds,
    cooldown_is_active,
    parse_retry_after_seconds,
    read_rate_limit_state,
    record_rate_limit,
)


class RateLimitStateTests(unittest.TestCase):
    def test_bounded_retry_preserves_platform_evidence_and_expires(self):
        class Error(Exception):
            response = type("Response", (), {"status_code": 429, "headers": {"Retry-After": "60"}})()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for _ in range(3):
                before = record_rate_limit(root, "submit", Error(), {}, "2026-08-12T00:00:00+00:00")
            granted = rate_limit_state.authorize_bounded_retry(root, "2026-08-12T00:02:00+00:00")
            self.assertEqual(granted["consecutive_429_count"], 3)
            self.assertEqual(granted["retry_at"], before["retry_at"])
            self.assertEqual(granted["updated_at"], before["updated_at"])
            self.assertFalse(rate_limit_state.rate_limit_requires_maintenance(granted, "2026-08-12T00:02:01+00:00"))
            self.assertTrue(rate_limit_state.rate_limit_requires_maintenance(granted, "2026-08-12T00:04:01+00:00"))
            latest = record_rate_limit(root, "submit", Error(), {}, "2026-08-12T00:02:01+00:00")
            self.assertTrue(rate_limit_state.rate_limit_requires_maintenance(latest, "2026-08-12T00:02:02+00:00"))

    def test_bounded_retry_does_not_shorten_active_server_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rate_limit_state.json"
            path.write_text(json.dumps({"status": "cooldown", "consecutive_429_count": 3,
                                        "retry_at": "2026-08-12T01:00:00+00:00"}))
            with self.assertRaises(ValueError):
                rate_limit_state.authorize_bounded_retry(Path(tmp), "2026-08-12T00:01:00+00:00")

    def test_expired_retry_is_rejected_at_submission_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rate_limit_state.json"
            path.write_text(json.dumps({"status": "cooldown", "consecutive_429_count": 3,
                                        "retry_at": "2026-08-12T00:00:00+00:00"}))
            with self.assertRaises(rate_limit_state.RateLimitRecoveryRequired):
                rate_limit_state.check_source_retry_authorization(Path(tmp), "2026-08-12T01:00:00+00:00")
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

    def test_record_rate_limit_preserves_server_retry_after(self):
        class Error(Exception):
            response = type("Response", (), {"status_code": 429, "headers": {"Retry-After": "3600"}})()

        with tempfile.TemporaryDirectory() as tmp:
            state = record_rate_limit(
                Path(tmp),
                "retry_planned_submit",
                Error("HTTP 429"),
                {},
                "2026-08-12T00:00:00+00:00",
            )

        self.assertEqual(state["retry_after_seconds"], 3600)
        self.assertEqual(state["retry_at"], "2026-08-12T01:00:00+00:00")

    def test_record_rate_limit_normalizes_malformed_counters(self):
        class Error(Exception):
            response = type("Response", (), {"status_code": 429, "headers": {}})()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rate_limit_state.json").write_text(
                '{"attempt_count":"invalid","consecutive_429_count":{}}', encoding="utf-8"
            )
            state = record_rate_limit(
                root,
                "retry_planned_submit",
                Error("HTTP 429"),
                {},
                "2026-08-12T00:00:00+00:00",
            )

        self.assertEqual(state["attempt_count"], 1)
        self.assertEqual(state["consecutive_429_count"], 1)

    def test_record_rate_limit_bounds_unreasonable_counters(self):
        class Error(Exception):
            response = type("Response", (), {"status_code": 429, "headers": {}})()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rate_limit_state.json").write_text(
                json.dumps({"attempt_count": 10**9, "consecutive_429_count": 10**9}),
                encoding="utf-8",
            )
            state = record_rate_limit(
                root,
                "retry_planned_submit",
                Error("HTTP 429"),
                {},
                "2026-08-12T00:00:00+00:00",
            )

        self.assertLessEqual(state["attempt_count"], rate_limit_state.MAX_BACKOFF_ATTEMPT_COUNT)
        self.assertEqual(state["consecutive_429_count"], rate_limit_state.MAX_CONSECUTIVE_429)

    def test_reset_rate_limit_clears_consecutive_count_after_platform_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rate_limit_state.json").write_text(
                json.dumps(
                    {
                        "status": "cooldown",
                        "attempt_count": 3,
                        "consecutive_429_count": 3,
                        "retry_at": "2099-01-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            reset = rate_limit_state.reset_rate_limit(
                root, "complete_in_flight", "2026-08-12T00:02:00+00:00"
            )
            loaded = read_rate_limit_state(root / "rate_limit_state.json")

        self.assertEqual(reset["status"], "ready")
        self.assertEqual(loaded["consecutive_429_count"], 0)
        self.assertEqual(loaded["reset_reason"], "complete_in_flight")

    def test_acknowledge_rate_limit_recovery_clears_threshold_with_audit_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rate_limit_state.json").write_text(
                json.dumps(
                    {
                        "status": "cooldown",
                        "attempt_count": 3,
                        "consecutive_429_count": 3,
                        "retry_at": "2026-08-16T07:11:30+00:00",
                    }
                ),
                encoding="utf-8",
            )

            acknowledged = rate_limit_state.acknowledge_rate_limit_recovery(
                root,
                "operator confirmed platform recovery",
                "2026-08-16T09:30:00+00:00",
            )
            loaded = read_rate_limit_state(root / "rate_limit_state.json")

        self.assertEqual(acknowledged["status"], "ready")
        self.assertEqual(loaded["consecutive_429_count"], 0)
        self.assertEqual(loaded["attempt_count"], 0)
        self.assertEqual(loaded["acknowledged_reason"], "operator confirmed platform recovery")
        self.assertEqual(loaded["acknowledged_at"], "2026-08-16T09:30:00+00:00")
        self.assertEqual(loaded["reset_reason"], "operator_acknowledged_rate_limit_recovery")


if __name__ == "__main__":
    unittest.main()
