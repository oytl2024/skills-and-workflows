import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from tests.test_client import FakeResponse, FakeSession
from wqb.client import WQBClient
from wqb.request_metrics import record_request, summarize_requests


class RequestMetricsTest(unittest.TestCase):
    def test_redacts_secrets_and_normalizes_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_request(root, {"method": "GET", "path": "https://user:secret@example.org/alphas/private/check?token=secret",
                                  "status": 429, "headers": {"Authorization": "secret", "Retry-After": "12"},
                                  "body": "secret", "duration_seconds": 0.1})
            content = (root / "runtime" / "request_metrics.jsonl").read_text()
            self.assertNotIn("secret", content)
            self.assertNotIn("private", content)
            self.assertNotIn("example.org", content)
            row = json.loads(content)
            self.assertEqual(row["endpoint"], "alpha_check")
            self.assertEqual(row["retry_after_seconds"], 12)
            self.assertEqual(summarize_requests(root)["rate_limited"], 1)

    def test_records_every_actual_attempt_including_auth_and_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = FakeSession([FakeResponse(500), FakeResponse(200), requests.exceptions.Timeout("secret")])
            client = WQBClient(session=session, max_retries=1, base_backoff_seconds=0, metrics_run_dir=root)
            with patch("wqb.client.load_credentials", return_value=("user", "secret")):
                client.request("GET", "/alphas/private")
                with self.assertRaisesRegex(RuntimeError, "outcome unknown"):
                    client.request("POST", "/simulations", json=[{}, {}, {}])
            summary = summarize_requests(root)
            self.assertEqual(summary["request_count"], 4)
            self.assertEqual(summary["by_endpoint"]["authentication"], 1)
            self.assertEqual(summary["by_endpoint"]["simulation_submit"], 1)
            self.assertEqual(summary["submitted_payload_count"], 3)
            self.assertEqual(summary["transport_errors"], 1)

    def test_summary_is_bounded_and_explicitly_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for _ in range(4):
                record_request(root, {"method": "GET", "path": "/simulations/private", "status": 200})
            summary = summarize_requests(root, max_events=2)
            self.assertEqual(summary["request_count"], 2)
            self.assertTrue(summary["truncated"])

    def test_metric_failure_does_not_change_unknown_post_outcome(self):
        session = FakeSession([requests.exceptions.Timeout("lost")])
        client = WQBClient(session=session, metrics_run_dir=Path("unused"))
        client.authenticated = True
        with patch("wqb.client.record_request", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "outcome unknown"):
                client.request("POST", "/simulations", json={})
        self.assertEqual(len(session.requests), 1)
