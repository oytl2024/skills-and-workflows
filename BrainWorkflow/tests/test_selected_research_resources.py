"""Exact selections must not fall back to the old first-thirty catalog view."""
from copy import deepcopy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_research_resource_catalog as fixtures


class SelectedResearchResourcesTests(unittest.TestCase):
    def test_verified_extract_also_supports_technical_repair(self):
        """Input: authentic field extract. Output: finite Repair policy without restoring a large original."""
        from wqb.research_resource_catalog import read_catalog_resources
        from wqb.preplanned_start import _repair_policy
        fixture = fixtures.ResearchResourceCatalogTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        extract, settings = fixture.prepare_measured_extract()
        resources, diagnostics = read_catalog_resources(fixture.root, fixture.scope, 1, settings=settings)
        self.assertEqual(len(resources), 1, diagnostics)
        resource = fixture.validate_against_canonical(resources[0])
        policy = _repair_policy(resource)
        self.assertEqual(policy['schema_version'], 2)
        self.assertNotIn(extract['source_path'], resource['source_texts'])

    def setUp(self):
        """Input: TestCase. Output: isolated actual-source catalog fixture."""
        self.fixture = fixtures.ResearchResourceCatalogTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.fields[0]['field_type'] = 'MATRIX'
        self.fixture.raw_fields[0]['field']['type'] = 'MATRIX'
        original = deepcopy(self.fixture.fields[0])
        raw = deepcopy(self.fixture.raw_fields[0])
        for number in range(45):
            row, observation = deepcopy(original), deepcopy(raw)
            row['field_id'] = observation['field']['id'] = 'later_' + str(number)
            self.fixture.fields.append(row)
            self.fixture.raw_fields.append(observation)
        self.fixture.refresh()

    def test_selected_field_outside_old_shortlist_is_exactly_resolved(self):
        from wqb.research_resource_catalog import read_selected_catalog_resources
        selected = [self.fixture.fields[-1]]
        fake = SimpleNamespace(read_field_rows=lambda *args: deepcopy(selected))
        with patch.dict(sys.modules, {'wqb.research_query_index': fake}):
            resource, diagnostics = read_selected_catalog_resources(self.fixture.root,
                self.fixture.scope, [('sample', 'later_44')], generation='generation',
                settings={'decay': 0})
        self.assertEqual([r['field_id'] for r in resource['field_rows']], ['later_44'], diagnostics)

    def test_missing_or_mismatched_requested_identity_is_not_replaced(self):
        from wqb.research_resource_catalog import read_selected_catalog_resources
        fake = SimpleNamespace(read_field_rows=lambda *args: deepcopy(self.fixture.fields[:1]))
        with patch.dict(sys.modules, {'wqb.research_query_index': fake}):
            with self.assertRaisesRegex(ValueError, 'selected|identity'):
                read_selected_catalog_resources(self.fixture.root, self.fixture.scope,
                    [('sample', 'does_not_exist')], generation='generation', settings={'decay': 0})

    def test_selection_never_scans_global_field_ledger(self):
        from wqb import research_resource_catalog as catalog
        original = catalog._rows
        selected = [self.fixture.fields[-1]]
        fake = SimpleNamespace(read_field_rows=lambda *args: deepcopy(selected))

        def limited(root, name, *args, **kwargs):
            """Input: reader args. Output: actual other resource rows; reject global field scans."""
            self.assertNotEqual(name, 'data_ledger')
            return original(root, name, *args, **kwargs)

        with patch.dict(sys.modules, {'wqb.research_query_index': fake}), patch.object(catalog, '_rows', limited):
            resource, _ = catalog.read_selected_catalog_resources(self.fixture.root,
                self.fixture.scope, [('sample', 'later_44')], generation='generation', settings={'decay': 0})
        self.assertEqual(len(resource['field_rows']), 1)

    def test_selected_vector_is_visible_without_invented_implicit_reduction(self):
        from wqb.research_resource_catalog import read_selected_catalog_resources
        self.fixture.fields[-1]['field_type'] = 'VECTOR'
        self.fixture.raw_fields[-1]['field']['type'] = 'VECTOR'
        self.fixture.refresh()
        selected = [self.fixture.fields[-1]]
        fake = SimpleNamespace(read_field_rows=lambda *args: deepcopy(selected))
        with patch.dict(sys.modules, {'wqb.research_query_index': fake}):
            resource, _ = read_selected_catalog_resources(self.fixture.root, self.fixture.scope,
                [('sample', 'later_44')], generation='generation', settings={'decay': 0})
        self.assertEqual(resource['field_rows'][0]['field_type'], 'VECTOR')
        self.assertNotIn('reduction', resource['field_rows'][0])
