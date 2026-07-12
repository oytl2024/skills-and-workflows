import unittest

import requests

from wqb.knowledge import fetch_knowledge_snapshot


class FakeClient:
    def __init__(self):
        self.get_paths = []
        self.option_paths = []

    def get_json(self, path):
        self.get_paths.append(path)
        if path.startswith("/search?query="):
            return {
                "tutorialPage": {"results": [{"id": "tutorial1"}]},
                "faq": {"results": [{"id": "faq1"}]},
                "message": {"results": [{"id": "message1"}]},
                "video": {"results": [{"id": "video1"}]},
            }
        if path.startswith("/tutorial-pages/"):
            return {"kind": "tutorial"}
        if path.startswith("/faqs/"):
            return {"kind": "faq"}
        if path.startswith("/messages/"):
            return {"kind": "message"}
        if path.startswith("/videos/"):
            return {"kind": "video"}
        if path.startswith("/events"):
            return {"results": [{"id": "event1"}]}
        if path.startswith("/competitions"):
            return {"results": [{"id": "competition1"}]}
        raise AssertionError(f"unexpected GET path: {path}")

    def options_json(self, path):
        self.option_paths.append(path)
        return {"actions": {"GET": {"board": {"choices": []}}}}


class KnowledgeTests(unittest.TestCase):
    def test_fetch_knowledge_snapshot_fetches_search_details_and_platform_context(self):
        client = FakeClient()

        snapshot = fetch_knowledge_snapshot(client, ["Power Pool"])

        self.assertIn("Power Pool", snapshot["queries"])
        self.assertEqual(snapshot["details"]["tutorialPage:tutorial1"], {"kind": "tutorial"})
        self.assertEqual(snapshot["details"]["faq:faq1"], {"kind": "faq"})
        self.assertEqual(snapshot["details"]["message:message1"], {"kind": "message"})
        self.assertEqual(snapshot["details"]["video:video1"], {"kind": "video"})
        self.assertEqual(snapshot["events"], {"results": [{"id": "event1"}]})
        self.assertEqual(snapshot["competitions"], {"results": [{"id": "competition1"}]})
        self.assertIn("/search?query=Power%20Pool", client.get_paths)
        self.assertEqual(client.option_paths, ["/consultant/boards/power-pool"])

    def test_fetch_knowledge_snapshot_records_detail_errors_and_continues(self):
        class DetailErrorClient(FakeClient):
            def get_json(self, path):
                if path.startswith("/tutorial-pages/"):
                    raise requests.exceptions.HTTPError("404 Client Error")
                return super().get_json(path)

        client = DetailErrorClient()

        snapshot = fetch_knowledge_snapshot(client, ["Power Pool"])

        self.assertEqual(snapshot["detail_errors"]["tutorialPage:tutorial1"]["error"], "HTTPError")
        self.assertEqual(snapshot["events"], {"results": [{"id": "event1"}]})
        self.assertEqual(snapshot["competitions"], {"results": [{"id": "competition1"}]})


if __name__ == "__main__":
    unittest.main()
