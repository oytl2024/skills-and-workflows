import unittest
from unittest.mock import patch

from wqb.simulator import (
    extract_alpha_id,
    extract_alpha_ids,
    poll_simulation,
    resolve_multisimulation_alpha_ids,
    submit_multisimulation,
    submit_simulation,
)


class FakeResponse:
    def __init__(self, headers=None, payload=None):
        self.headers = headers or {}
        self.payload = payload or {}
        self.raise_for_status_called = False

    def raise_for_status(self):
        self.raise_for_status_called = True

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.posted = []
        self.requested = []

    def post_json(self, path, payload):
        self.posted.append((path, payload))
        return self.responses.pop(0)

    def request(self, method, path):
        self.requested.append((method, path))
        return self.responses.pop(0)


class SimulatorTests(unittest.TestCase):
    def test_submit_simulation_returns_location_header(self):
        client = FakeClient([FakeResponse(headers={"Location": "/simulations/abc"})])

        location = submit_simulation(client, {"regular": "rank(close)"})

        self.assertEqual(location, "/simulations/abc")
        self.assertEqual(client.posted, [("/simulations", {"regular": "rank(close)"})])

    def test_submit_simulation_rejects_missing_location(self):
        client = FakeClient([FakeResponse()])

        with self.assertRaisesRegex(RuntimeError, "missing Location"):
            submit_simulation(client, {})

    def test_submit_multisimulation_posts_payload_list(self):
        client = FakeClient([FakeResponse(headers={"Location": "/simulations/multi1"})])

        location = submit_multisimulation(client, [{"regular": "a"}, {"regular": "b"}])

        self.assertEqual(location, "/simulations/multi1")
        self.assertEqual(client.posted, [("/simulations", [{"regular": "a"}, {"regular": "b"}])])

    def test_submit_multisimulation_rejects_empty_payloads(self):
        client = FakeClient([])

        with self.assertRaisesRegex(ValueError, "at least one"):
            submit_multisimulation(client, [])

    def test_poll_simulation_waits_for_retry_after_then_returns_json(self):
        client = FakeClient(
            [
                FakeResponse(headers={"Retry-After": "1"}),
                FakeResponse(payload={"alpha": "alpha123"}),
            ]
        )

        with patch("wqb.simulator.time.sleep") as sleep_mock:
            progress = poll_simulation(client, "/simulations/abc")

        self.assertEqual(progress, {"alpha": "alpha123"})
        self.assertEqual(client.requested, [("GET", "/simulations/abc"), ("GET", "/simulations/abc")])
        sleep_mock.assert_called_once_with(1.0)

    def test_extract_alpha_id_accepts_string(self):
        self.assertEqual(extract_alpha_id({"alpha": "alpha123"}), "alpha123")

    def test_extract_alpha_id_accepts_dict(self):
        self.assertEqual(extract_alpha_id({"alpha": {"id": "alpha123"}}), "alpha123")

    def test_extract_alpha_id_rejects_missing_alpha(self):
        with self.assertRaisesRegex(RuntimeError, "missing alpha id"):
            extract_alpha_id({"status": "COMPLETE"})

    def test_extract_alpha_ids_accepts_alpha_list_and_children(self):
        self.assertEqual(extract_alpha_ids({"alpha": ["a1", {"id": "a2"}]}), ["a1", "a2"])
        self.assertEqual(extract_alpha_ids({"children": [{"alpha": "a3"}, {"alpha": {"id": "a4"}}]}), ["a3", "a4"])

    def test_extract_alpha_ids_rejects_missing_ids(self):
        with self.assertRaisesRegex(RuntimeError, "missing alpha ids"):
            extract_alpha_ids({"status": "COMPLETE"})

    def test_resolve_multisimulation_alpha_ids_polls_child_simulations(self):
        client = FakeClient(
            [
                FakeResponse(payload={"alpha": "alpha1"}),
                FakeResponse(payload={"alpha": {"id": "alpha2"}}),
            ]
        )

        alpha_ids = resolve_multisimulation_alpha_ids(client, {"children": ["child1", "child2"]})

        self.assertEqual(alpha_ids, ["alpha1", "alpha2"])
        self.assertEqual(client.requested, [("GET", "/simulations/child1"), ("GET", "/simulations/child2")])


if __name__ == "__main__":
    unittest.main()
