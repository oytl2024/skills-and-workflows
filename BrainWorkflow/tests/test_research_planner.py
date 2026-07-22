import json
import tempfile
import unittest
from pathlib import Path

from wqb.principle_model import IncentiveSnapshot, SourceEvidence
from wqb.research_planner import generate_research_options, plan_research_options


def write_seed_knowledge(root: Path) -> None:
    """Input: knowledge root Path. Output: none. Write seed semantic ledgers without authoritative measured data."""
    semantics = root / "wiki" / "20_semantics"
    templates = root / "wiki" / "30_templates"
    benchmarks = root / "wiki" / "50_benchmarks"
    semantics.mkdir(parents=True, exist_ok=True)
    templates.mkdir(parents=True, exist_ok=True)
    benchmarks.mkdir(parents=True, exist_ok=True)
    (semantics / "data_ledger.jsonl").write_text(
        json.dumps(
            {
                "dataset_id": "seed_dataset",
                "dataset_name": "Seed Dataset",
                "field_id": "seed_field",
                "field_type": "MATRIX",
                "region": "USA",
                "delay": 1,
                "universe": "TOP3000",
                "semantic_tags": ["seed"],
                "coverage": 0.0,
                "alpha_count": 0,
                "user_count": 0,
                "simulation_usage_count": 0,
                "submitted_usage_count": 0,
                "last_used_at": "",
                "best_result_label": "seed",
                "correlation_risk": "unknown",
                "source_paths": [],
                "source_quality": "schema_seed",
                "coverage_status": "schema_seeded",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (semantics / "operator_semantics.jsonl").write_text(
        json.dumps(
            {
                "operator": "rank",
                "family": "cross_sectional",
                "workflow_uses": ["discovery"],
                "compatible_field_types": ["MATRIX"],
                "template_tags": ["seed"],
                "risk_tags": [],
                "repair_levers": [],
                "source_paths": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (templates / "template_library.jsonl").write_text(
        json.dumps(
            {
                "template_id": "seed_template",
                "hypothesis": "Seed template",
                "skeleton": "rank({field})",
                "required_field_types": ["MATRIX"],
                "compatible_semantic_tags": ["seed"],
                "operator_tags": ["rank"],
                "status": "seed",
                "correlation_risk": "unknown",
                "repair_levers": [],
                "source_paths": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (benchmarks / "benchmark_rules.jsonl").write_text(
        json.dumps(
            {
                "rule_id": "seed_rule",
                "issue_types": ["seed"],
                "description": "Seed rule.",
                "promotion_condition": "Seed condition.",
                "action": "Seed action.",
                "evidence_paths": [],
                "consumed_by": ["research_planner"],
                "risk": "low",
            }
        )
        + "\n",
        encoding="utf-8",
    )


class ResearchPlannerTest(unittest.TestCase):
    def test_plan_research_options_records_semantic_inputs_and_cache_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_seed_knowledge(root)

            result = plan_research_options(
                knowledge_root=root,
                generated_at="2026-07-22T00:00:00+00:00",
                max_options=2,
                live_api_enabled=False,
            )

        option = result["options"][0]
        self.assertIn("data_authority", option)
        self.assertIn("template_matrix_ready_count", option)
        self.assertIn("benchmark_rule_count", option)
        self.assertIn("maintenance_blockers", option)
        self.assertIn("authoritative data ledger", " ".join(option["maintenance_blockers"]).lower())

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
