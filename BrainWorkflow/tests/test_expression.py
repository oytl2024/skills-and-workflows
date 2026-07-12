import unittest

from wqb.expression import (
    count_data_fields,
    count_operators,
    expression_hash,
    is_power_pool_complexity_ok,
    replace_operator_names,
)


class ExpressionTests(unittest.TestCase):
    def test_expression_hash_is_stable(self):
        self.assertEqual(expression_hash("rank(close)"), expression_hash(" rank(close) "))

    def test_count_operators_ignores_backfill_for_power_pool(self):
        expression = "rank(ts_mean(ts_backfill(news_score, 20), 5))"
        counts = count_operators(expression)
        self.assertEqual(counts["rank"], 1)
        self.assertEqual(counts["ts_mean"], 1)
        self.assertEqual(counts["ts_backfill"], 1)

    def test_count_data_fields_excludes_grouping_fields(self):
        expression = "group_neutralize(rank(news_score), subindustry) + rank(volume)"
        fields = count_data_fields(expression, known_fields={"news_score", "volume", "subindustry"})
        self.assertEqual(fields, {"news_score", "volume"})

    def test_power_pool_complexity_passes_simple_expression(self):
        result = is_power_pool_complexity_ok(
            "rank(ts_mean(news_score, 5))",
            known_fields={"news_score"},
            operator_limit=8,
            field_limit=3,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.operator_count, 2)
        self.assertEqual(result.field_count, 1)

    def test_power_pool_complexity_counts_repeated_operator_once(self):
        result = is_power_pool_complexity_ok(
            "rank(rank(rank(news_score)))",
            known_fields={"news_score"},
            operator_limit=1,
            field_limit=3,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.operator_count, 1)

    def test_power_pool_complexity_excludes_backfill_operators(self):
        result = is_power_pool_complexity_ok(
            "rank(ts_backfill(group_backfill(news_score, industry, 20), 5))",
            known_fields={"news_score", "industry"},
            operator_limit=1,
            field_limit=3,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.operator_count, 1)
        self.assertEqual(result.operators["ts_backfill"], 1)
        self.assertEqual(result.operators["group_backfill"], 1)

    def test_power_pool_complexity_reports_operator_over_limit(self):
        result = is_power_pool_complexity_ok(
            "rank(ts_mean(zscore(news_score), 5))",
            known_fields={"news_score"},
            operator_limit=2,
            field_limit=3,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.operator_count, 3)
        self.assertEqual(result.reasons, ["operator_count 3 exceeds 2"])

    def test_power_pool_complexity_reports_field_over_limit(self):
        result = is_power_pool_complexity_ok(
            "rank(news_score) + rank(volume)",
            known_fields={"news_score", "volume"},
            operator_limit=8,
            field_limit=1,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.field_count, 2)
        self.assertEqual(result.reasons, ["field_count 2 exceeds 1"])

    def test_count_data_fields_uses_word_boundaries(self):
        fields = count_data_fields("rank(adv_volume)", known_fields={"volume"})
        self.assertEqual(fields, set())

    def test_replace_operator_names_only_replaces_function_calls(self):
        expression = "group_normalize(rank(group_normalize_score), industry)"

        result = replace_operator_names(expression, {"group_normalize": "group_zscore"})

        self.assertEqual(result, "group_zscore(rank(group_normalize_score), industry)")


if __name__ == "__main__":
    unittest.main()
