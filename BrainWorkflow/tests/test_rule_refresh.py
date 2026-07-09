import unittest

from wqb.rule_refresh import refresh_incentive_snapshot


class FakeClient:
    def __init__(self):
        self.get_paths = []
        self.option_paths = []

    def get_json(self, path):
        self.get_paths.append(path)
        if path == "/users/self":
            return {"id": "TO50928", "geniusLevel": "GOLD", "onboarding": {"status": "CONSULTANT_APPROVED"}}
        if path == "/events?limit=50&offset=0":
            return {"results": [{"id": "E1", "title": "Opportunity Webinar", "description": "Brain Community Score"}]}
        if path == "/competitions?limit=50&offset=0":
            return {"results": [{"id": "PAC2026", "name": "Python Alphas Competition 2026", "status": "ACCEPTED"}]}
        if path.startswith("/tutorial-pages/"):
            return {"id": path.rsplit("/", 1)[-1], "title": "Rule Page", "content": [{"type": "TEXT", "value": "rules"}]}
        raise AssertionError(path)

    def options_json(self, path):
        self.option_paths.append(path)
        return {
            "actions": {
                "GET": {
                    "board": {
                        "choices": [
                            {"value": "lyvRddy", "label": "USA/D1 Power Pool July'26"},
                            {"value": "Jypw8X4", "label": "USA/D1 Fast Datasets Power Pool June`26"},
                        ]
                    }
                }
            }
        }


class RuleRefreshTest(unittest.TestCase):
    def test_refresh_incentive_snapshot_normalizes_core_sources(self):
        client = FakeClient()

        snapshot = refresh_incentive_snapshot(client, generated_at="2026-07-09T00:00:00Z")

        self.assertEqual(snapshot.account["geniusLevel"], "GOLD")
        self.assertEqual(snapshot.competitions[0]["id"], "PAC2026")
        self.assertEqual(snapshot.power_pool_boards[0]["label"], "USA/D1 Power Pool July'26")
        self.assertIn("/users/self", client.get_paths)
        self.assertIn("/consultant/boards/power-pool", client.option_paths)
        self.assertEqual(snapshot.refresh_errors, [])
        self.assertGreaterEqual(len(snapshot.evidence), 4)


if __name__ == "__main__":
    unittest.main()
