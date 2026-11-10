"""Offline official-style settings metadata, independent of captured data fields."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import tempfile
from pathlib import Path
import unittest

from wqb import multiplier_scope as scopes


def settings_fixture():
    """Input: none. Output: fictional nested OPTIONS dict for dependent region/delay/universe choices."""
    return dict(actions=dict(POST=dict(settings=dict(children=dict(
        region=dict(choices=dict(instrumentType=dict(EQUITY=[dict(value='USA'), dict(value='KOR')]))),
        delay=dict(choices=dict(instrumentType=dict(EQUITY=dict(region=dict(USA=[dict(value=0), dict(value=1)], KOR=[dict(value=1)]))))),
        universe=dict(choices=dict(instrumentType=dict(EQUITY=dict(region=dict(USA=[dict(value='TOP3000')], KOR=[dict(value='TOP600'), dict(value='TOP200')])))))
    )))))


class MultiplierScopeTests(unittest.TestCase):
    def test_official_nested_settings_work_without_a_data_ledger(self):
        choices = scopes.compile_scope_choices(settings_fixture())
        self.assertEqual(len(choices), 4)
        self.assertIn(dict(region='KOR', delay=1, universe='TOP600'), choices)
        self.assertNotIn(dict(region='KOR', delay=0, universe='TOP600'), choices)

    def test_boolean_delay_and_unknown_dependency_are_rejected(self):
        payload = settings_fixture()
        payload['actions']['POST']['settings']['children']['delay']['choices'] = [dict(value=True)]
        with self.assertRaises(ValueError):
            scopes.compile_scope_choices(payload)
        payload['actions']['POST']['settings']['children']['delay']['choices'] = {'mystery': [1]}
        with self.assertRaises(ValueError):
            scopes.compile_scope_choices(payload)

    def test_publish_reader_preserves_source_age_and_detects_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captured = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
            receipt = scopes.publish_scope_catalog(root, settings_fixture(), captured)
            result = scopes.read_scope_catalog(root)
            self.assertTrue(result['stale'])
            self.assertEqual(result['captured_at'], captured)
            self.assertEqual(len(result['scopes']), 4)
            source = root / receipt['source_path']
            source.write_text(source.read_text() + 'tampered')
            with self.assertRaises(ValueError):
                scopes.read_scope_catalog(root)

    def test_valid_configuration_is_reused_only_for_matching_pair(self):
        catalog = dict(scopes=scopes.compile_scope_choices(settings_fixture()))
        config = dict(region='USA', delay=1, universe='TOP3000')
        self.assertEqual(scopes.select_multiplier_scope(catalog, config, dict(region='USA', delay=1)), config)
        with self.assertRaisesRegex(ValueError, 'universe'):
            scopes.select_multiplier_scope(catalog, config, dict(region='KOR', delay=1))
        self.assertEqual(scopes.select_multiplier_scope(catalog, config, dict(region='KOR', delay=1, universe='TOP600')),
                         dict(region='KOR', delay=1, universe='TOP600'))

    def test_partial_selected_config_is_not_mixed_into_other_scope(self):
        catalog = dict(scopes=scopes.compile_scope_choices(settings_fixture()))
        config = dict(region='USA', delay=1, universe='TOP3000', selected_scope=dict(region='KOR'))
        with self.assertRaises(ValueError):
            scopes.select_multiplier_scope(catalog, config, dict(region='KOR', delay=1))

    def test_partial_saved_scope_is_not_exposed_as_invalid_frontend_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scopes.publish_scope_catalog(root, settings_fixture(), datetime.now(timezone.utc).isoformat())
            result = scopes.scope_selection_contract(root, {'selected_scope': {'region': 'KOR'}})
            self.assertIsNone(result['configured_scope'])
            self.assertTrue(result['choices'])


if __name__ == '__main__':
    unittest.main()
