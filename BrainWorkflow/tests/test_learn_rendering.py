"""Canonical Learn rendering must work without capture CLI or platform dependencies."""
import builtins
import unittest
from unittest.mock import patch


class LearnRenderingTests(unittest.TestCase):
    def test_desktop_self_test_checks_packaged_renderer(self):
        from wqb.desktop_application import self_test
        self.assertTrue(self_test()['learn_rendering_ready'])

    def test_runtime_rendering_does_not_import_scripts(self):
        from wqb.knowledge_contracts import _learn_repair_body
        original = builtins.__import__
        def restricted(name, *args, **kwargs):
            if name == 'scripts' or name.startswith('scripts.'):
                raise ModuleNotFoundError('scripts intentionally absent in desktop bundle')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=restricted):
            result = _learn_repair_body('operators', [dict(name='rank', category='Cross Sectional',
                definition='rank(x)', description='<p>Rank &amp; normalize.</p>')])
            self.assertIn('- Description: Rank & normalize.', result)

    def test_capture_adapter_preserves_formatter_contract(self):
        from scripts.capture_learn_material import clean_text, markdown_record_value
        for value, cleaned, rendered in [
                ('<style>x</style><p>A &amp; B</p>', 'A & B', 'A & B'),
                ([dict(value=' A '), dict(text='B')], 'A B', 'A B'),
                (dict(a='A', b='B'), 'A B', 'A B'), (42, '', '42'), (False, '', ''), (None, '', '')]:
            self.assertEqual(clean_text(value), cleaned)
            self.assertEqual(markdown_record_value(value), rendered)
