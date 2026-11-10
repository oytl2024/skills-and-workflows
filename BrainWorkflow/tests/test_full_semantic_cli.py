"""Existing maintenance CLI exposes full-local preparation without platform/model calls."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wqb import cli


class FullSemanticCLITests(unittest.TestCase):
    def invoke(self, root, policy):
        """Input: temporary root Path/policy dict. Output: parsed CLI JSON; no real config read."""
        args = SimpleNamespace(command='compile-semantic-knowledge', config='fixture',
            knowledge_root=str(root), max_mechanisms=3, max_conditions_per_mechanism=2)
        output = io.StringIO()
        with patch.object(cli, 'parse_args', return_value=args), \
             patch.object(cli, 'load_config', return_value=dict(semantic_policy=policy)), \
             patch.object(cli, 'WQBClient', side_effect=AssertionError('platform client forbidden')), \
             redirect_stdout(output):
            cli.main()
        return json.loads(output.getvalue())

    def test_full_prepare_uses_existing_cli_and_never_runs_legacy_semantic_model(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(cli,
                'compile_semantic_knowledge_command', side_effect=AssertionError('legacy model dispatch')):
            root = Path(tmp)
            result = self.invoke(root, dict(full_local_mode='prepare', full_local={}))
            self.assertEqual(result['kind'], 'full_semantic_compile_plan')
            self.assertEqual(result['model_calls'], 0)
            self.assertEqual(result['budget']['model_call_budget'], 0)
            self.assertFalse(result['publication_authorized'])
            self.assertTrue((root / result['plan_path']).is_file())

    def test_invalid_mode_fails_before_any_legacy_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(cli,
                'compile_semantic_knowledge_command', side_effect=AssertionError('legacy dispatch')):
            with self.assertRaisesRegex(ValueError, 'full_local_mode'):
                self.invoke(Path(tmp), dict(full_local_mode='anything'))

    def test_default_bounded_mode_remains_compatible(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(cli,
                'compile_semantic_knowledge_command', return_value=dict(status='completed')) as legacy:
            self.assertEqual(self.invoke(Path(tmp), {}), dict(status='completed'))
            legacy.assert_called_once()

    def test_execute_uses_frozen_zero_budget_without_model_or_quota_override(self):
        from tests.test_full_semantic_execution import FullSemanticExecutionTests
        fixture = FullSemanticExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = fixture.plan(0)
        policy = dict(full_local_mode='execute', full_local=dict(plan_path=plan['plan_path']))
        with patch('wqb.ai_checkpoints.run_ai_checkpoint', side_effect=AssertionError('model forbidden')):
            with self.assertRaises(SystemExit) as stopped:
                self.invoke(fixture.root, policy)
        self.assertEqual(stopped.exception.code, 2)
        policy['full_local']['model_call_budget'] = 999
        with self.assertRaisesRegex(ValueError, 'plan_path'):
            self.invoke(fixture.root, policy)


if __name__ == '__main__':
    unittest.main()
