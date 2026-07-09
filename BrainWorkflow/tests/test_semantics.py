import unittest

from wqb.generator import generate_seed_candidates
from wqb.semantics import field_semantic_embedding, operator_semantic_embedding, select_semantic_field_pairs


class SemanticsTests(unittest.TestCase):
    def test_field_semantic_embedding_tags_cashflow_and_pressure_fields(self):
        cashflow = field_semantic_embedding(
            {"id": "annual_operating_cashflow_amount_fast_d1", "type": "MATRIX"}
        )
        capex = field_semantic_embedding({"id": "fnd3_a_capex_fast_d1", "type": "MATRIX"})
        debt = field_semantic_embedding({"id": "fnd3_q_totaldebt_fast_d1", "type": "MATRIX"})

        self.assertIn("cashflow", cashflow["tags"])
        self.assertEqual(cashflow["polarity"], "positive")
        self.assertIn("investment_drag", capex["tags"])
        self.assertEqual(capex["polarity"], "negative")
        self.assertIn("leverage_pressure", debt["tags"])
        self.assertEqual(debt["polarity"], "negative")

    def test_operator_semantic_embedding_classifies_common_operator_uses(self):
        rank = operator_semantic_embedding({"name": "rank", "category": "Cross Sectional"})
        decay = operator_semantic_embedding({"name": "ts_decay_linear", "category": "Time Series"})
        vec_avg = operator_semantic_embedding({"name": "vec_avg", "category": "Vector"})

        self.assertIn("cross_sectional_normalizer", rank["tags"])
        self.assertIn("turnover_control", decay["tags"])
        self.assertIn("vector_reducer", vec_avg["tags"])

    def test_select_semantic_field_pairs_prefers_positive_minus_negative(self):
        fields = [
            {"id": "annual_operating_cashflow_amount_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_a_capex_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_q_totaldebt_fast_d1", "type": "MATRIX"},
        ]

        pairs = select_semantic_field_pairs(fields, max_pairs=4)
        rendered = [(pair["positive"]["id"], pair["negative"]["id"], pair["hypothesis"]) for pair in pairs]

        self.assertIn(
            (
                "annual_operating_cashflow_amount_fast_d1",
                "fnd3_a_capex_fast_d1",
                "cashflow_quality",
            ),
            rendered,
        )
        self.assertIn(
            (
                "annual_operating_cashflow_amount_fast_d1",
                "fnd3_q_totaldebt_fast_d1",
                "balance_sheet_quality",
            ),
            rendered,
        )

    def test_generate_seed_candidates_semantic_builds_thirty_with_hypothesis_tags(self):
        fields = [
            {"id": "fnd3_q_cash_fast_d1", "type": "MATRIX"},
            {"id": "annual_operating_cashflow_amount_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_a_ope_cf_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_a_capex_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_a_inv_cf_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_q_totaldebt_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_q_liabilities_fast_d1", "type": "MATRIX"},
        ]

        candidates = generate_seed_candidates(
            fields,
            {"region": "USA"},
            max_count=30,
            generation=0,
            template_mode="semantic",
        )
        expressions = [candidate.expression for candidate in candidates]

        self.assertEqual(len(candidates), 30)
        self.assertEqual(len(set(expressions)), 30)
        self.assertTrue(all("semantic" in candidate.tags for candidate in candidates))
        self.assertTrue(any("cashflow_quality" in candidate.tags for candidate in candidates))
        self.assertIn(
            "rank(annual_operating_cashflow_amount_fast_d1) - rank(fnd3_a_capex_fast_d1)",
            expressions,
        )

    def test_generate_seed_candidates_semantic_diversifies_hypotheses_and_templates(self):
        fields = [
            {"id": "fnd3_q_assets_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_q_cash_fast_d1", "type": "MATRIX"},
            {"id": "annual_operating_cashflow_amount_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_a_capex_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_q_totaldebt_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_q_liabilities_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_q_accreceivable_fast_d1", "type": "MATRIX"},
            {"id": "fnd3_q_goodwill_fast_d1", "type": "MATRIX"},
        ]

        candidates = generate_seed_candidates(
            fields,
            {"region": "USA"},
            max_count=18,
            generation=0,
            template_mode="semantic",
        )
        expressions = [candidate.expression for candidate in candidates]
        hypothesis_tags = {
            tag
            for candidate in candidates
            for tag in candidate.tags
            if tag not in {"seed", "economic", "semantic"}
        }

        self.assertGreaterEqual(len(hypothesis_tags), 3)
        self.assertTrue(any("ts_delta" in expression or "ts_mean" in expression for expression in expressions))
        self.assertTrue(any("group_neutralize" in expression for expression in expressions))


if __name__ == "__main__":
    unittest.main()
