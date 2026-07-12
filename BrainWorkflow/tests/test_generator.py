import unittest

from wqb.expression import count_data_fields
from wqb.generator import build_settings, generate_seed_candidates, regular_field_id, simulation_payload


class GeneratorTests(unittest.TestCase):
    def test_build_settings_uses_stage1_config(self):
        settings = build_settings(
            {
                "instrument_type": "EQUITY",
                "region": "USA",
                "universe": "TOP3000",
                "delay": 1,
                "decay": 4,
                "neutralization": "SUBINDUSTRY",
                "truncation": 0.08,
                "pasteurization": "ON",
                "unit_handling": "VERIFY",
                "nan_handling": "OFF",
                "language": "FASTEXPR",
            }
        )

        self.assertEqual(settings["region"], "USA")
        self.assertEqual(settings["language"], "FASTEXPR")
        self.assertEqual(settings["instrumentType"], "EQUITY")
        self.assertEqual(settings["unitHandling"], "VERIFY")
        self.assertFalse(settings["visualization"])

    def test_simulation_payload_shape(self):
        payload = simulation_payload({"region": "USA"}, "rank(close)")

        self.assertEqual(payload["type"], "REGULAR")
        self.assertEqual(payload["settings"], {"region": "USA"})
        self.assertEqual(payload["regular"], "rank(close)")

    def test_generate_seed_candidates_limits_count(self):
        fields = [{"id": "news_score"}, {"id": "volume"}]
        candidates = generate_seed_candidates(fields, {"region": "USA"}, max_count=3, generation=0)

        self.assertLessEqual(len(candidates), 3)
        self.assertTrue(all(candidate.expression for candidate in candidates))
        self.assertTrue(all(candidate.generation == 0 for candidate in candidates))

    def test_generate_seed_candidates_returns_empty_for_zero_count(self):
        fields = [{"id": "news_score"}]

        candidates = generate_seed_candidates(fields, {"region": "USA"}, max_count=0, generation=0)

        self.assertEqual(candidates, [])

    def test_generate_seed_candidates_uses_generation_variants(self):
        fields = [{"id": "news_score"}]

        generation_zero = generate_seed_candidates(fields, {"region": "USA"}, max_count=3, generation=0)
        generation_one = generate_seed_candidates(fields, {"region": "USA"}, max_count=3, generation=1)

        self.assertNotEqual(
            {candidate.expression for candidate in generation_zero},
            {candidate.expression for candidate in generation_one},
        )

    def test_regular_field_id_removes_fast_d1_suffix(self):
        self.assertEqual(regular_field_id("snt_value_fast_d1"), "snt_value")
        self.assertIsNone(regular_field_id("snt_value"))

    def test_generate_seed_candidates_economic_fast_d1_templates(self):
        fields = [{"id": "snt_value_fast_d1"}]

        candidates = generate_seed_candidates(
            fields,
            {"region": "USA"},
            max_count=4,
            generation=0,
            template_mode="economic",
        )
        expressions = [candidate.expression for candidate in candidates]

        self.assertIn("rank(snt_value_fast_d1 - snt_value)", expressions)
        self.assertIn("rank(ts_delta(snt_value_fast_d1, 1))", expressions)
        self.assertTrue(all("economic" in candidate.tags for candidate in candidates))

    def test_generate_seed_candidates_economic_prefers_template_across_fields(self):
        fields = [
            {"id": "snt_value_fast_d1"},
            {"id": "news_score_fast_d1"},
            {"id": "analyst_revision_fast_d1"},
        ]

        candidates = generate_seed_candidates(
            fields,
            {"region": "USA"},
            max_count=3,
            generation=0,
            template_mode="economic",
        )

        self.assertEqual(
            [candidate.expression for candidate in candidates],
            [
                "rank(snt_value_fast_d1 - snt_value)",
                "rank(news_score_fast_d1 - news_score)",
                "rank(analyst_revision_fast_d1 - analyst_revision)",
            ],
        )

    def test_generate_seed_candidates_economic_vector_fields_use_vector_operator(self):
        fields = [{"id": "mdl240_dilution_factor_fast_d1", "type": "VECTOR"}]

        candidates = generate_seed_candidates(
            fields,
            {"region": "USA"},
            max_count=4,
            generation=0,
            template_mode="economic",
        )
        expressions = [candidate.expression for candidate in candidates]

        self.assertIn(
            "rank(vec_avg(mdl240_dilution_factor_fast_d1) - vec_avg(mdl240_dilution_factor))",
            expressions,
        )
        self.assertIn("rank(vec_avg(mdl240_dilution_factor_fast_d1))", expressions)
        self.assertNotIn("rank(ts_delta(mdl240_dilution_factor_fast_d1, 1))", expressions)
        self.assertNotIn("rank(ts_mean(mdl240_dilution_factor_fast_d1, 5))", expressions)

    def test_generate_seed_candidates_skips_regular_delta_when_peer_missing(self):
        fields = [
            {
                "id": "relative_interest_score_3_fast_d1",
                "type": "VECTOR",
                "regular_peer_available": False,
            }
        ]

        candidates = generate_seed_candidates(
            fields,
            {"region": "USA"},
            max_count=3,
            generation=0,
            template_mode="economic",
        )
        expressions = [candidate.expression for candidate in candidates]

        self.assertNotIn(
            "rank(vec_avg(relative_interest_score_3_fast_d1) - vec_avg(relative_interest_score_3))",
            expressions,
        )
        self.assertIn("rank(vec_avg(relative_interest_score_3_fast_d1))", expressions)

    def test_generate_seed_candidates_builds_thirty_for_single_vector_fast_field_without_peer(self):
        fields = [
            {
                "id": "trend_estimation_confidence_score_2_fast_d1",
                "type": "VECTOR",
                "regular_peer_available": False,
            }
        ]

        candidates = generate_seed_candidates(
            fields,
            {"region": "USA", "decay": 4, "neutralization": "SUBINDUSTRY"},
            max_count=30,
            generation=0,
            template_mode="economic",
        )
        expressions = [candidate.expression for candidate in candidates]

        self.assertEqual(len(candidates), 30)
        self.assertEqual(len(set(expressions)), 30)
        self.assertTrue(all("vec_avg(trend_estimation_confidence_score_2_fast_d1)" in expression for expression in expressions))
        self.assertTrue(all("trend_estimation_confidence_score_2)" not in expression for expression in expressions))

    def test_generate_seed_candidates_relational_pairs_positive_and_negative_fields(self):
        fields = [
            {"id": "annual_operating_cashflow_amount_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_a_capex_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_q_totaldebt_fast_d1", "type": "MATRIX"},
        ]

        candidates = generate_seed_candidates(
            fields,
            {"region": "USA"},
            max_count=6,
            generation=0,
            template_mode="relational",
        )
        expressions = [candidate.expression for candidate in candidates]

        self.assertIn(
            "rank(annual_operating_cashflow_amount_fast_d1) - rank(fnd3_a_capex_fast_d1)",
            expressions,
        )
        self.assertTrue(all("relational" in candidate.tags for candidate in candidates))

    def test_generate_seed_candidates_relational_builds_thirty_with_two_field_limit(self):
        fields = [
            {"id": "fnd3_q_cash_fast_d1", "type": "MATRIX"},
            {"id": "annual_operating_cashflow_amount_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_a_ope_cf_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_a_capex_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_a_inv_cf_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_q_totaldebt_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_q_liabilities_fast_d1", "type": "MATRIX"},
        ]
        known_fields = {field["id"] for field in fields}

        candidates = generate_seed_candidates(
            fields,
            {"region": "USA"},
            max_count=30,
            generation=0,
            template_mode="relational",
        )
        expressions = [candidate.expression for candidate in candidates]

        self.assertEqual(len(candidates), 30)
        self.assertEqual(len(set(expressions)), 30)
        self.assertTrue(all(len(count_data_fields(expression, known_fields)) <= 2 for expression in expressions))


if __name__ == "__main__":
    unittest.main()
