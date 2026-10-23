"""Read-only local architecture viewer and launcher contracts."""

from contextlib import contextmanager
from http.client import HTTPConnection
import json
from pathlib import Path
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from wqb.architecture_viewer import make_server, server_identity


ROOT = Path(__file__).resolve().parents[3]


@contextmanager
def local_viewer():
    server = make_server(ROOT, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class ArchitectureViewerTests(unittest.TestCase):
    def test_viewer_identity_changes_with_loaded_code_revision(self):
        with patch("wqb.architecture_viewer.LOADED_CODE_REVISION", "old-code", create=True):
            old = server_identity(ROOT)
        with patch("wqb.architecture_viewer.LOADED_CODE_REVISION", "new-code", create=True):
            current = server_identity(ROOT)

        self.assertNotEqual(old, current)

    def test_health_and_graph_are_bound_to_workspace(self):
        with local_viewer() as url:
            with urlopen(url + "/api/health", timeout=2) as response:
                health = json.load(response)
            self.assertEqual(health["identity"], server_identity(ROOT))
            with urlopen(url + "/api/architecture", timeout=2) as response:
                graph = json.load(response)
            self.assertGreaterEqual(len(graph["modules"]), 6)
            self.assertGreaterEqual(len(graph["workflow_steps"]), 13)
            self.assertEqual(graph["workflow_steps"][0]["id"], "objective")

    def test_only_validated_references_can_be_opened(self):
        with local_viewer() as url:
            with urlopen(url + "/workspace/todo.md", timeout=2) as response:
                self.assertIn(b"Current mainline", response.read())
            with urlopen(url + "/workspace/skills-and-workflows/BrainWorkflow/wqb/simulator.py", timeout=2) as response:
                self.assertIn(b"simulation", response.read().lower())
            with self.assertRaises(HTTPError) as error:
                urlopen(url + "/workspace/AGENTS.md", timeout=2)
            self.assertEqual(error.exception.code, 404)
            with self.assertRaises(HTTPError):
                urlopen(url + "/workspace/%2e%2e/private.txt", timeout=2)

    def test_post_cannot_mutate_project(self):
        with local_viewer() as url:
            with self.assertRaises(HTTPError) as error:
                from urllib.request import Request
                urlopen(Request(url + "/api/architecture", data=b"{}", method="POST"), timeout=2)
            self.assertEqual(error.exception.code, 405)

    def test_foreign_host_header_is_rejected(self):
        with local_viewer() as url:
            port = int(url.rsplit(":", 1)[1])
            connection = HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                connection.request("GET", "/workspace/todo.md", headers={"Host": "attacker.example"})
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
