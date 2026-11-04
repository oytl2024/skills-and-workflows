"""Offline boundaries for deterministic-only Repair."""

import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb.repair_runtime import RepairRuntimeExecutor


class RepairRetirementTests(unittest.TestCase):
    def test_new_preplanned_start_can_prepare_beside_retired_pointer(self):
        """Input: isolated retired pointer. Output: assertions. Allow new preparation without editing history."""
        from tests.test_console_start import make_paths, fixture, FORM
        from wqb.console_start import register_start
        from wqb.workflow_state import create_initial_state, write_run_state, write_active_run
        with tempfile.TemporaryDirectory() as directory:
            paths = make_paths(Path(directory))
            fixture(paths)
            run = paths.runs_root / 'historical'
            run.mkdir(parents=True)
            (run / 'run_manifest.json').write_text(json.dumps({'start_snapshot': {
                'research_policy': {'deterministic_repair': False}}}), encoding='utf-8')
            write_run_state(run / 'run_state.json', create_initial_state(run.name, run, 'old', '2026-10-11'))
            write_active_run(paths.runs_root, run.name, run)
            before = {str(path): path.read_bytes() for path in run.rglob('*') if path.is_file()}
            with patch('wqb.console_start.load_start_config', return_value={
                    'research_policy': {'preplanned_tree_version': 1}}):
                request = register_start(paths, FORM, 'new-job')
            self.assertEqual(request['status'], 'preparing')
            self.assertEqual(request['source_intent']['run_dir'], '')
            self.assertEqual(request['source_intent']['retired_run_dir'], str(run))
            self.assertEqual(before, {str(path): path.read_bytes() for path in run.rglob('*') if path.is_file()})

    def test_cli_resume_never_changes_retired_stop_or_authority(self):
        """Input: retired status fixture. Output: assertions. Reject CLI Resume before intent writes."""
        from wqb.cli import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / 'historical'
            run.mkdir()
            argv = ['wqb', 'workflow-run', '--knowledge-root', str(root / 'knowledge'),
                    '--run-dir', str(root / 'runs')]
            result = dict(active=True, run_dir=str(run), status='retired', read_only=True)
            with patch('sys.argv', argv), patch('wqb.cli.WorkflowOrchestrator') as engine, patch(
                    'wqb.runtime_control.request_runtime_state') as intent, redirect_stdout(io.StringIO()):
                engine.return_value.status.return_value = result
                main()
            intent.assert_not_called()
            self.assertEqual(list(run.iterdir()), [])

    def test_console_never_resumes_retired_mission_but_allows_new_selection(self):
        """Input: retired/damaged snapshots. Output: assertions. Keep action permissions aligned with authority."""
        from wqb.console_server import _workflow_action_state
        state = {'active_workflow': {'exists': True, 'status': 'retired', 'can_resume': False, 'read_only': True},
                 'runtime_control': {'desired_state': 'paused', 'status': 'blocked'},
                 'current_work': {'next_action': ''}}
        actions = _workflow_action_state(state)
        self.assertFalse(actions['continue_workflow'])
        self.assertTrue(actions['start_workflow'])
        state['active_workflow']['status'] = 'damaged'
        actions = _workflow_action_state(state)
        self.assertFalse(actions['continue_workflow'])
        self.assertFalse(actions['start_workflow'])

    def test_legacy_prepare_rejected_without_model_or_network(self):
        """Input: old frozen policy. Output: assertions. Refuse planning without model or HTTP work."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = json.dumps({'start_snapshot': {'research_policy': {}}})
            path = root / 'run_manifest.json'
            path.write_text(evidence, encoding='utf-8')
            with patch('wqb.cli.build_client') as network, patch('wqb.ai_checkpoints.run_ai_checkpoint') as model:
                with self.assertRaisesRegex(ValueError, 'retired'):
                    RepairRuntimeExecutor({}, enable_live_api=True).prepare(root, {}, [], 1)
            network.assert_not_called()
            model.assert_not_called()
            self.assertEqual(path.read_text(encoding='utf-8'), evidence)

    def test_deterministic_prepare_uses_frozen_search_only(self):
        """Input: deterministic policy fixture. Output: assertions. Route only to frozen finite search."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'run_manifest.json').write_text(json.dumps({'start_snapshot': {
                'research_policy': {'deterministic_repair': True}}}), encoding='utf-8')
            expected = {'planner_kind': 'deterministic'}
            with patch('wqb.repair_search.prepare_persisted_search', return_value=expected) as search:
                self.assertEqual(RepairRuntimeExecutor({}).prepare(root, {}, [], 1), expected)
            search.assert_called_once_with(root, {}, [], 1)

    def test_model_receipt_cannot_be_consumed_as_search(self):
        """Input: old receipt dict. Output: assertions. Prevent model answers from becoming search authority."""
        from wqb.repair_policy import verify_consumed_plan
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'retired'):
                verify_consumed_plan(Path(directory), {'status': 'validated', 'variants': []})

    def test_direct_executor_rejects_old_payload_before_authentication(self):
        """Input: obsolete executor payload. Output: assertions. Reject before authentication or submission."""
        with tempfile.TemporaryDirectory() as directory:
            executor = RepairRuntimeExecutor({'allow_parent_settings_recovery': True}, enable_live_api=True)
            with patch('wqb.cli.build_client') as network:
                with self.assertRaisesRegex(ValueError, 'retired'):
                    executor(Path(directory), {}, [{'ai_plan': {'status': 'validated'}}], 1)
            network.assert_not_called()
