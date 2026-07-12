import unittest

from wqb.principle_model import (
    OptionCard,
    ScoreBreakdown,
    SourceEvidence,
    option_card_to_dict,
    validate_option_card,
)


class PrincipleModelTest(unittest.TestCase):
    # Input: none; Output: none; Purpose: verify nested evidence serializes into plain dictionaries.
    def test_option_card_to_dict_serializes_nested_evidence(self):
        evidence = SourceEvidence(
            source_type="api",
            path="/competitions/PAC2026",
            title="Python Alphas Competition 2026",
            timestamp="2026-07-09T00:00:00Z",
        )
        card = OptionCard(
            title="PAC feasibility check",
            primary_incentive="competition",
            secondary_incentives=["learning"],
            why_now="Active competition window is visible.",
            candidate_scope="Python alpha feasibility only.",
            expected_asset_value="May unlock reusable Python alpha workflow.",
            correlation_risk="Unknown until alpha expressions exist.",
            resource_cost="Read-only API refresh plus no simulations.",
            evidence=[evidence],
            failure_modes=["Competition submission may be disabled."],
            decision_needed="Choose whether to spend a feasibility slot.",
            score=ScoreBreakdown(
                total=6.0,
                components={"competition_expected_value": 4.0, "learning": 2.0},
                penalties={"tooling_gap_cost": 0.0},
                reasons=["Active competition evidence exists."],
            ),
        )

        row = option_card_to_dict(card)

        self.assertEqual(row["title"], "PAC feasibility check")
        self.assertEqual(row["evidence"][0]["path"], "/competitions/PAC2026")
        self.assertEqual(row["score"]["total"], 6.0)

    # Input: none; Output: none; Purpose: verify invalid cards raise when required text is missing.
    def test_validate_option_card_rejects_missing_required_text(self):
        card = OptionCard(
            title="",
            primary_incentive="power_pool",
            secondary_incentives=[],
            why_now="Board exists.",
            candidate_scope="USA D1.",
            expected_asset_value="Simple alpha asset.",
            correlation_risk="Medium.",
            resource_cost="One read-only refresh.",
            evidence=[],
            failure_modes=[],
            decision_needed="Choose this option.",
            score=ScoreBreakdown(total=1.0, components={}, penalties={}, reasons=[]),
        )

        with self.assertRaises(ValueError):
            validate_option_card(card)


if __name__ == "__main__":
    unittest.main()
