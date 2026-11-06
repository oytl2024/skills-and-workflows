"""Maintenance selects certified bounded sources without changing captured facts."""

from copy import deepcopy
import json
import unittest

from wqb.data_ledger_compile import compile_data_ledger_from_raw


class FieldSourceProjectionTests(unittest.TestCase):
    def setUp(self):
        """Input: none. Output: isolated multi-megabyte raw capture and one certified bounded subset."""
        from tests.test_bulk_field_extracts import BulkFieldExtractTests
        self.fixture = BulkFieldExtractTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.rows = self.fixture.rows[:1]
        for number in range(7):
            row = deepcopy(self.fixture.rows[0])
            row['field'].update(id='padding_' + str(number), description='x' * 350_000)
            self.fixture.rows.append(row)
        self.fixture.save()
        self.proof = self.fixture.produce(max_batches=1, max_fields=1)

    def test_large_capture_selects_verified_subset_and_keeps_partial_status(self):
        """Input: partial capture plus certified excerpt. Output: bounded canonical source, original date, no coverage promotion."""
        root = self.fixture.root
        compile_data_ledger_from_raw(root, self.fixture.source.parent)
        rows = [json.loads(line) for line in (root / 'machine/data_ledger.jsonl').read_text().splitlines()]
        selected = next(row for row in rows if row['field_id'] == 'f000')
        self.assertEqual(selected['source_paths'], [self.proof['extracts'][0]['excerpt_path']])
        self.assertEqual(selected['coverage_status'], 'partial')
        self.assertEqual(selected['source_updated_at'], '2026-10-23')

    def test_tampered_excerpt_cannot_replace_existing_ledger(self):
        """Input: previously compiled ledger then altered selected excerpt. Output: rejection before ledger replacement."""
        root = self.fixture.root
        compile_data_ledger_from_raw(root, self.fixture.source.parent)
        ledger = root / 'machine/data_ledger.jsonl'
        original = ledger.read_bytes()
        excerpt = root / self.proof['extracts'][0]['excerpt_path']
        excerpt.write_bytes(excerpt.read_bytes() + b'changed')
        with self.assertRaises(ValueError):
            compile_data_ledger_from_raw(root, self.fixture.source.parent)
        self.assertEqual(ledger.read_bytes(), original)

    def test_new_overlapping_extract_preserves_existing_valid_explanation_source(self):
        """Input: same-source overlapping excerpts. Output: retain the already selected explanation and compatible source."""
        from tests.test_field_semantic_enrichment import FieldSemanticEnrichmentTests, SCOPE
        from wqb.knowledge_contracts import extract_field_source_subset
        fixture = FieldSemanticEnrichmentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        first = fixture.certified_large_extract()
        fixture.ledger.write_text(json.dumps(fixture.row), encoding='utf-8')
        preferred = first['excerpt_path']
        earlier = None
        for number in range(20):
            result = extract_field_source_subset(fixture.root, first['source_path'], [
                dict(dataset_id='d', field_id='f', scope=SCOPE),
                dict(dataset_id='d', field_id='padding_' + str(number), scope=SCOPE)])
            if result['excerpt_path'] < preferred:
                earlier = result['excerpt_path']
                break
        self.assertIsNotNone(earlier, 'Deterministic fixture needs a lexically earlier overlapping excerpt')
        compile_data_ledger_from_raw(fixture.root, fixture.capture)
        rows = [json.loads(line) for line in fixture.ledger.read_text().splitlines()]
        selected = next(row for row in rows if row['field_id'] == 'f')
        self.assertEqual(selected.get('field_semantics_ref'), fixture.row['field_semantics_ref'])
        self.assertEqual(selected['source_paths'], [preferred])


if __name__ == '__main__':
    unittest.main()
