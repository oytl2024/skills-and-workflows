import unittest

from wqb.novelty import expression_profile, score_expression_novelty


class NoveltyTests(unittest.TestCase):
    def test_expression_profile_extracts_fields_operators_and_template(self):
        profile = expression_profile(
            "trade_when(rank(volume) > 0.8, rank(ts_delta(close, 5)) - rank(ts_delta(volume, 5)), -1)",
            {"neutralization": "SUBINDUSTRY"},
        )

        self.assertEqual(profile["fields"], ["close", "volume"])
        self.assertEqual(profile["data_families"], ["price_volume"])
        self.assertEqual(
            profile["operator_sequence"],
            ["trade_when", "rank", "rank", "ts_delta", "rank", "ts_delta"],
        )
        self.assertIn("trade_when", profile["template_key"])
        self.assertEqual(profile["neutralization"], "SUBINDUSTRY")

    def test_score_penalizes_same_field_family_and_template_as_reference(self):
        references = [
            {
                "expression": "trade_when(rank(volume) > 0.8, rank(ts_delta(close, 5)) - rank(ts_delta(volume, 5)), -1)",
                "settings": {"neutralization": "SUBINDUSTRY"},
                "benchmark_label": "repairable_signal",
            }
        ]

        result = score_expression_novelty(
            "trade_when(rank(volume) > 0.8, rank(ts_delta(open, 5)) - rank(ts_delta(volume, 5)), -1)",
            {"neutralization": "SUBINDUSTRY"},
            references,
        )

        self.assertEqual(result.label, "low_novelty")
        self.assertLess(result.score, 0)
        self.assertIn("overlapping_data_family", result.reasons)
        self.assertIn("similar_operator_template", result.reasons)
        self.assertIn("same_neutralization_as_similar_reference", result.reasons)

    def test_score_rewards_fast_d1_delta_against_crowded_price_volume_reference(self):
        references = [
            {
                "expression": "rank(ts_delta(close, 5))",
                "settings": {"neutralization": "SUBINDUSTRY"},
                "benchmark_label": "repairable_signal",
            }
        ]

        result = score_expression_novelty(
            "group_neutralize(rank(snt_buzz_fast_d1 - snt_buzz), industry)",
            {"neutralization": "INDUSTRY"},
            references,
        )

        self.assertEqual(result.label, "high_novelty")
        self.assertGreaterEqual(result.score, 3)
        self.assertIn("new_data_family", result.reasons)
        self.assertIn("fast_d1_delta", result.reasons)


if __name__ == "__main__":
    unittest.main()
