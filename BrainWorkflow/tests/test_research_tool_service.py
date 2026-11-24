"""Cumulative read-only tool budgets, not simulation authority."""
import unittest
import json

from wqb.research_tool_service import ToolBudget


class ResearchToolServiceTests(unittest.TestCase):
    def test_cumulative_queries_and_validations_are_enforced(self):
        budget = ToolBudget(dict(max_queries=3, max_validations=1, max_returned_bytes=1000))
        evaluate = lambda *_: {'valid': True}
        budget.execute('validate', {}, evaluate)
        with self.assertRaisesRegex(ValueError, 'validation_budget_exhausted'):
            budget.execute('validate', {}, evaluate)
        budget.execute('fields', {}, evaluate)
        budget.execute('operators', {}, evaluate)
        with self.assertRaisesRegex(ValueError, 'query_budget_exhausted'):
            budget.execute('fields', {}, evaluate)

    def test_cumulative_bytes_do_not_truncate_evidence(self):
        budget = ToolBudget(dict(max_queries=3, max_validations=1, max_returned_bytes=512))
        first = budget.execute('fields', {}, lambda *_: {'x': 'a'})
        used = first['tool_budget']['returned_bytes']
        with self.assertRaisesRegex(ValueError, 'response_budget_exhausted'):
            budget.execute('source', {}, lambda *_: {'full': 'x' * 500})
        self.assertEqual(budget.returned_bytes, used)

    def test_returned_bytes_include_exact_metadata_bytes(self):
        budget = ToolBudget(dict(max_queries=3, max_validations=1, max_returned_bytes=5000))
        used = 0
        for operation in ['fields', 'validate', 'source']:
            reply = budget.execute(operation, {}, lambda *_: {'text': 'bounded'})
            used += len(json.dumps(reply, ensure_ascii=False, allow_nan=False,
                                   separators=(',', ':')).encode('utf-8'))
            self.assertEqual(reply['tool_budget']['returned_bytes'], used)

    def test_source_rows_bytes_and_elapsed_are_distinct_measurements(self):
        budget = ToolBudget(dict(max_queries=3, max_validations=1, max_returned_bytes=5000))
        result = budget.execute('source', {}, lambda *_: dict(items=[dict(excerpt='text')]))
        counts = result['tool_budget']
        self.assertEqual(counts['rows_returned'], 1)
        self.assertEqual(counts['source_bytes'], 4)
        self.assertGreaterEqual(counts['elapsed_seconds'], 0)
        self.assertNotIn('tokens', counts)
