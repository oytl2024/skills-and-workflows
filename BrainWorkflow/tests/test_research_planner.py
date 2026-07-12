import unittest

from wqb.principle_model import IncentiveSnapshot, SourceEvidence
from wqb.research_planner import generate_research_options


class ResearchPlannerTest(unittest.TestCase):
    def test_generate_research_options_prioritizes_visible_incentives(self):
        snapshot = IncentiveSnapshot(
            generated_at="2026-07-09T00:00:00Z",
            account={"geniusLevel": "GOLD", "onboarding": {"status": "CONSULTANT_APPROVED"}},
            activities=[{"id": "E1", "title": "Opportunity Webinar", "description": "Brain Community Score"}],
            competitions=[
                {
                    "id": "PAC2026",
                    "name": "Python Alphas Competition 2026",
                    "status": "ACCEPTED",
                    "endDate": "2026-07-12T23:59:59-04:00",
                    "leaderboard": {"alphas": 0, "score": 0.0},
                }
            ],
            power_pool_boards=[{"value": "lyvRddy", "label": "USA/D1 Power Pool July'26"}],
            rule_pages={
                "brain-genius": "signal submissions pyramids Combined Alpha Performance",
                "osmosis-allocation-guide-consultants": "Daily Osmosis Rank Combined Osmosis Performance",
                "multiplier-rules": "Themes increase QualityFactor base payment",
                "getting-started-power-pool-alphas": "Power Pool Alphas are simpler",
            },
            evidence=[SourceEvidence("api", "/users/self", "User account state", "2026-07-09T00:00:00Z")],
            refresh_errors=[],
        )

        options = generate_research_options(snapshot, max_options=5)
        titles = [option.title for option in options]

        self.assertGreaterEqual(len(options), 3)
        self.assertTrue(any("Power Pool" in title for title in titles))
        self.assertTrue(any("Genius" in title or "Osmosis" in title for title in titles))
        self.assertTrue(any("Python" in title or "Competition" in title for title in titles))
        self.assertGreaterEqual(options[0].score.total, options[-1].score.total)

    def test_generate_research_options_marks_refresh_uncertainty(self):
        snapshot = IncentiveSnapshot(
            generated_at="2026-07-09T00:00:00Z",
            account={},
            activities=[],
            competitions=[],
            power_pool_boards=[],
            rule_pages={},
            evidence=[SourceEvidence("cache", "knowledge/raw/last_snapshot.json", "Cached snapshot", "2026-07-01T00:00:00Z", stale=True)],
            refresh_errors=[{"path": "/events", "error": "Timeout", "message": "network timeout"}],
        )

        options = generate_research_options(snapshot, max_options=5)

        self.assertEqual(options[0].primary_incentive, "knowledge_refresh")
        self.assertIn("refresh", options[0].title.lower())

    def test_generate_research_options_penalizes_stale_visible_opportunities(self):
        snapshot = IncentiveSnapshot(
            generated_at="2026-07-09T00:00:00Z",
            account={"geniusLevel": "GOLD"},
            activities=[{"id": "E1", "title": "Power Pool activity", "description": "Visible cached activity"}],
            competitions=[],
            power_pool_boards=[{"value": "lyvRddy", "label": "USA/D1 Power Pool July'26"}],
            rule_pages={
                "brain-genius": "signal submissions pyramids Combined Alpha Performance",
                "osmosis-allocation-guide-consultants": "Daily Osmosis Rank Combined Osmosis Performance",
                "getting-started-power-pool-alphas": "Power Pool Alphas are simpler",
            },
            evidence=[SourceEvidence("cache", "knowledge/raw/last_snapshot.json", "Cached snapshot", "2026-07-01T00:00:00Z", stale=True)],
            refresh_errors=[{"path": "/events", "error": "Timeout", "message": "network timeout"}],
        )

        options = generate_research_options(snapshot, max_options=5)
        power_pool_option = next(option for option in options if option.primary_incentive == "power_pool")

        self.assertIn("stale", power_pool_option.title.lower())
        self.assertIn("uncertain", power_pool_option.why_now.lower())
        self.assertGreater(power_pool_option.score.penalties.get("stale_refresh_uncertainty", 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
