import unittest

from wqb.data_catalog import (
    build_metadata_cache,
    cached_fields,
    fetch_data_fields,
    fetch_data_fields_with_metadata,
    fetch_data_sets,
    fetch_data_sets_with_metadata,
    field_ids,
    filter_fields_by_suffix,
    select_seed_fields,
)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.paths = []

    def get_json(self, path):
        self.paths.append(path)
        return self.responses.pop(0)


class DataCatalogTests(unittest.TestCase):
    def test_fetch_data_fields_paginates_until_short_batch(self):
        client = FakeClient(
            [
                {"results": [{"id": "field1"}, {"id": "field2"}]},
                {"results": [{"id": "field3"}]},
            ]
        )

        fields = fetch_data_fields(
            client,
            instrument_type="EQUITY",
            region="USA",
            delay=1,
            universe="TOP3000",
            limit=2,
            max_records=5,
        )

        self.assertEqual([field["id"] for field in fields], ["field1", "field2", "field3"])
        self.assertIn("offset=0", client.paths[0])
        self.assertIn("offset=2", client.paths[1])

    def test_catalog_metadata_reports_truncation_when_an_extra_page_exists(self):
        client = FakeClient(
            [
                {"results": [{"id": "dataset-1"}, {"id": "dataset-2"}]},
                {"results": [{"id": "dataset-3"}]},
            ]
        )

        rows, truncated = fetch_data_sets_with_metadata(
            client,
            instrument_type="EQUITY",
            region="USA",
            delay=1,
            universe="TOP3000",
            limit=2,
            max_records=2,
        )

        self.assertEqual([row["id"] for row in rows], ["dataset-1", "dataset-2"])
        self.assertTrue(truncated)
        self.assertIn("offset=2", client.paths[1])

    def test_field_catalog_metadata_preserves_public_rows_and_reports_truncation(self):
        responses = [
            {"results": [{"id": "field-1"}, {"id": "field-2"}]},
            {"results": [{"id": "field-3"}]},
        ]

        rows, truncated = fetch_data_fields_with_metadata(
            FakeClient(responses),
            instrument_type="EQUITY",
            region="USA",
            delay=1,
            universe="TOP3000",
            dataset_id="fundamental3",
            limit=2,
            max_records=2,
        )

        self.assertEqual([row["id"] for row in rows], ["field-1", "field-2"])
        self.assertTrue(truncated)

    def test_catalog_payload_rejects_non_list_results(self):
        client = FakeClient([{"results": {"id": "dataset-1"}}])

        with self.assertRaisesRegex(ValueError, "results.*list"):
            fetch_data_sets_with_metadata(
                client,
                instrument_type="EQUITY",
                region="USA",
                delay=1,
                universe="TOP3000",
                limit=10,
                max_records=10,
            )

    def test_catalog_payload_rejects_non_object_result_entries(self):
        client = FakeClient([{"results": [{"id": "dataset-1"}, "truncated-row"]}])

        with self.assertRaisesRegex(ValueError, "result entries"):
            fetch_data_sets_with_metadata(
                client,
                instrument_type="EQUITY",
                region="USA",
                delay=1,
                universe="TOP3000",
                limit=10,
                max_records=10,
            )

    def test_catalog_count_greater_than_fetched_rows_reports_truncation(self):
        client = FakeClient([{"results": [{"id": "dataset-1"}], "count": 2}])

        rows, truncated = fetch_data_sets_with_metadata(
            client,
            instrument_type="EQUITY",
            region="USA",
            delay=1,
            universe="TOP3000",
            limit=10,
            max_records=10,
        )

        self.assertEqual([row["id"] for row in rows], ["dataset-1"])
        self.assertTrue(truncated)

    def test_catalog_retains_authoritative_count_when_later_page_omits_count(self):
        client = FakeClient(
            [
                {"results": [{"id": "dataset-1"}, {"id": "dataset-2"}], "count": 5},
                {"results": [{"id": "dataset-3"}]},
            ]
        )

        rows, truncated = fetch_data_sets_with_metadata(
            client,
            instrument_type="EQUITY",
            region="USA",
            delay=1,
            universe="TOP3000",
            limit=2,
            max_records=10,
        )

        self.assertEqual([row["id"] for row in rows], ["dataset-1", "dataset-2", "dataset-3"])
        self.assertTrue(truncated)

    def test_catalog_rejects_invalid_count_type(self):
        client = FakeClient([{"results": [{"id": "dataset-1"}], "count": "5"}])

        with self.assertRaisesRegex(ValueError, "count"):
            fetch_data_sets_with_metadata(
                client,
                instrument_type="EQUITY",
                region="USA",
                delay=1,
                universe="TOP3000",
                limit=10,
                max_records=10,
            )

    def test_select_seed_fields_skips_grouping_and_sorts(self):
        fields = [
            {"id": "industry", "coverage": 1.0, "alphaCount": 100},
            {"id": "slow", "coverage": 0.5, "alphaCount": 20},
            {"id": "best", "coverage": 0.9, "alphaCount": 3},
            {"id": "popular", "coverage": 0.9, "alphaCount": 30},
            {"coverage": 1.0, "alphaCount": 999},
        ]

        selected = select_seed_fields(fields, max_fields=2)

        self.assertEqual([field["id"] for field in selected], ["popular", "best"])

    def test_field_ids_returns_present_ids(self):
        self.assertEqual(field_ids([{"id": "x"}, {"id": ""}, {"name": "missing"}]), {"x"})

    def test_filter_fields_by_suffix_keeps_only_matching_ids(self):
        fields = [
            {"id": "snt_value_fast_d1"},
            {"id": "snt_value"},
            {"id": "relative_interest_score_3_fast_d1"},
            {"name": "missing"},
        ]

        filtered = filter_fields_by_suffix(fields, "_fast_d1")

        self.assertEqual(
            [field["id"] for field in filtered],
            ["snt_value_fast_d1", "relative_interest_score_3_fast_d1"],
        )

    def test_build_metadata_cache_fetches_large_local_catalog_once_per_query(self):
        class CacheClient:
            def __init__(self):
                self.paths = []

            def get_json(self, path):
                self.paths.append(path)
                if path == "/operators":
                    return [{"name": "rank"}, {"name": "ts_mean"}]
                if path.startswith("/data-sets"):
                    return {"results": [{"id": "fundamental3"}, {"id": "news21"}]}
                if "dataset.id=fundamental3" in path and "search=cash" in path:
                    return {
                        "results": [
                            {"id": "fnd3_q_cash_fast_d1", "type": "MATRIX"},
                            {"id": "fnd3_q_cash", "type": "MATRIX"},
                        ]
                    }
                if "dataset.id=fundamental3" in path and "search=debt" in path:
                    return {"results": [{"id": "fnd3_q_totaldebt_fast_d1", "type": "MATRIX"}]}
                raise AssertionError(f"unexpected path: {path}")

        client = CacheClient()
        cache = build_metadata_cache(
            client,
            {
                "instrument_type": "EQUITY",
                "region": "USA",
                "delay": 1,
                "universe": "TOP3000",
            },
            dataset_ids=["fundamental3"],
            field_searches=["cash", "debt"],
            field_suffix="_fast_d1",
            max_fields_per_query=100,
        )
        fields = cached_fields(cache, dataset_id="fundamental3", field_suffix="_fast_d1")

        self.assertIn("/operators", client.paths)
        self.assertEqual(cache["operators"], [{"name": "rank"}, {"name": "ts_mean"}])
        self.assertEqual(len(cache["field_queries"]), 2)
        self.assertEqual(
            [field["id"] for field in fields],
            ["fnd3_q_cash_fast_d1", "fnd3_q_totaldebt_fast_d1"],
        )

    def test_build_metadata_cache_can_skip_data_sets_catalog(self):
        class CacheClient:
            def __init__(self):
                self.paths = []

            def get_json(self, path):
                self.paths.append(path)
                if path == "/operators":
                    return [{"name": "rank"}]
                if path.startswith("/data-fields"):
                    return {"results": [{"id": "fnd3_q_cash_fast_d1", "type": "MATRIX"}]}
                raise AssertionError(f"unexpected path: {path}")

        client = CacheClient()
        cache = build_metadata_cache(
            client,
            {
                "instrument_type": "EQUITY",
                "region": "USA",
                "delay": 1,
                "universe": "TOP3000",
            },
            dataset_ids=["fundamental3"],
            field_searches=["cash"],
            field_suffix="_fast_d1",
            max_fields_per_query=100,
            include_data_sets=False,
        )

        self.assertEqual(cache["data_sets"], [])
        self.assertFalse(any(path.startswith("/data-sets") for path in client.paths))

    def test_build_metadata_cache_fetches_global_search_when_dataset_ids_empty(self):
        class CacheClient:
            def __init__(self):
                self.paths = []

            def get_json(self, path):
                self.paths.append(path)
                if path == "/operators":
                    return [{"name": "rank"}]
                if path.startswith("/data-fields") and "search=sentiment" in path:
                    return {
                        "results": [
                            {"id": "news_sentiment_fast_d1", "type": "MATRIX"},
                            {"id": "news_sentiment", "type": "MATRIX"},
                        ]
                    }
                raise AssertionError(f"unexpected path: {path}")

        client = CacheClient()
        cache = build_metadata_cache(
            client,
            {
                "instrument_type": "EQUITY",
                "region": "USA",
                "delay": 1,
                "universe": "TOP3000",
            },
            dataset_ids=[],
            field_searches=["sentiment"],
            field_suffix="_fast_d1",
            max_fields_per_query=50,
            include_data_sets=False,
        )

        self.assertEqual(cache["field_queries"][0]["dataset_id"], "")
        self.assertEqual(cache["field_queries"][0]["field_search"], "sentiment")
        self.assertEqual([field["id"] for field in cached_fields(cache)], ["news_sentiment_fast_d1"])
        self.assertTrue(any("search=sentiment" in path for path in client.paths))

    def test_cached_fields_filters_field_dataset_inside_global_query(self):
        cache = {
            "field_queries": [
                {
                    "dataset_id": "",
                    "field_search": "news",
                    "field_suffix": "_fast_d1",
                    "fields": [
                        {"id": "news_item_count_300_fast_d1", "dataset": {"id": "news7"}},
                        {"id": "snt_buzz_fast_d1", "dataset": {"id": "socialmedia12"}},
                    ],
                }
            ]
        }

        fields = cached_fields(cache, dataset_id="news7", field_suffix="_fast_d1")

        self.assertEqual([field["id"] for field in fields], ["news_item_count_300_fast_d1"])

    def test_fetch_data_sets_caps_page_limit_to_platform_safe_size(self):
        client = FakeClient([{"results": [{"id": "fundamental3"}]}])

        rows = fetch_data_sets(
            client,
            instrument_type="EQUITY",
            region="USA",
            delay=1,
            universe="TOP3000",
            limit=100,
            max_records=100,
        )

        self.assertEqual(rows, [{"id": "fundamental3"}])
        self.assertIn("limit=50", client.paths[0])

    def test_fetch_data_fields_caps_page_limit_to_platform_safe_size(self):
        client = FakeClient([{"results": [{"id": "fnd3_q_cash_fast_d1"}]}])

        rows = fetch_data_fields(
            client,
            instrument_type="EQUITY",
            region="USA",
            delay=1,
            universe="TOP3000",
            dataset_id="fundamental3",
            search="cash",
            limit=100,
            max_records=100,
        )

        self.assertEqual(rows, [{"id": "fnd3_q_cash_fast_d1"}])
        self.assertIn("limit=50", client.paths[0])


if __name__ == "__main__":
    unittest.main()
