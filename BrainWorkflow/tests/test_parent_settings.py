import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock


class ParentSettingsTests(unittest.TestCase):
    def test_actual_settings_cached_with_expression_evidence(self):
        from wqb.repair_runtime import recover_parent_settings
        with tempfile.TemporaryDirectory() as tmp:
            parent = {"alpha_id": "abc", "expression": "rank(x)", "expression_hash": "hash"}
            client = Mock()
            client.get_json.return_value = {"id": "abc", "regular": {"code": "rank(x)"},
                                            "settings": {"region": "USA", "delay": 1}}
            result = recover_parent_settings(Path(tmp), parent, client)
            self.assertEqual(result["settings"], {"region": "USA", "delay": 1})
            self.assertNotIn("settings", parent)
            recover_parent_settings(Path(tmp), parent, client)
            client.get_json.assert_called_once_with("/alphas/abc")

    def test_remote_expression_mismatch_never_infers_defaults(self):
        from wqb.repair_runtime import recover_parent_settings
        with tempfile.TemporaryDirectory() as tmp:
            client = Mock()
            client.get_json.return_value = {"id": "abc", "regular": {"code": "rank(y)"}, "settings": {"decay": 4}}
            with self.assertRaisesRegex(ValueError, "expression"):
                recover_parent_settings(Path(tmp), {"alpha_id": "abc", "expression": "rank(x)", "expression_hash": "h"}, client)
