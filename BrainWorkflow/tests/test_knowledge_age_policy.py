import unittest
from datetime import date

from wqb.knowledge_bootstrap import _manifest_rows
from wqb.knowledge_freshness import KnowledgeFreshnessRecord, evaluate_freshness
from wqb.knowledge_vault_migration import DEFAULT_FRESHNESS_DAYS


class KnowledgeAgePolicyTests(unittest.TestCase):
    def test_new_manifests_allow_at_least_ninety_days(self):
        self.assertGreaterEqual(DEFAULT_FRESHNESS_DAYS, 90)
        for row in _manifest_rows('2026-10-12T00:00:00+00:00', set()):
            self.assertGreaterEqual(row['max_age_days'], 90, row['name'])

    def test_ninety_day_boundary_preserves_capture_date_and_missing_check(self):
        record = KnowledgeFreshnessRecord('operators', 'missing.md', '2026-07-14', 90)
        self.assertFalse(evaluate_freshness([record], date(2026, 10, 12))[0].stale)
        self.assertTrue(evaluate_freshness([record], date(2026, 10, 13))[0].stale)
        self.assertEqual(record.updated_at, '2026-07-14')
