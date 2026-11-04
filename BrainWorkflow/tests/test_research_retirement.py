import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
from wqb.workflow_state import create_initial_state, write_run_state, write_active_run
from wqb.workflow_driver import run_workflow_driver
from wqb.research_retirement import retirement_boundary, _local_path


class ResearchRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'runs' / 'historical'
        self.run.mkdir(parents=True)

    def write(self, name, value):
        """Input: relative str and JSON value. Output: None. Persist isolated test evidence."""
        path = self.run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def legacy(self):
        """Input: None. Output: None. Build positively identified historical AI Repair evidence."""
        self.write('run_manifest.json', {'run_id': self.run.name, 'start_snapshot': {}})
        self.write('stages/repair/repair_execution.json', {
            'run_id': self.run.name, 'scheduler_version': 1,
            'attempts': [{'plan': {'judgment': {'checkpoint_id': 'ai-old', 'status': 'completed'}}}]})

    def test_missing_manifest_is_not_blanket_retirement(self):
        self.assertIsNone(retirement_boundary(self.run))

    def test_frozen_legacy_without_ai_evidence_is_not_retired(self):
        self.write('run_manifest.json', {'start_snapshot': {}})
        self.assertIsNone(retirement_boundary(self.run))

    def test_missing_manifest_with_ai_evidence_fails_closed(self):
        self.write('stages/ai/ai_checkpoints.jsonl', {
            'checkpoint_id': 'ai-old', 'checkpoint_type': 'near_miss_interpretation'})
        self.assertEqual(retirement_boundary(self.run)['status'], 'damaged')

    def test_checkpoint_authority_identifies_other_legacy_runs(self):
        self.write('run_manifest.json', {'start_snapshot': {'research_policy': {'deterministic_repair': False}}})
        self.write('stages/ai/ai_checkpoints.jsonl', {
            'checkpoint_id': 'ai-old', 'checkpoint_type': 'near_miss_interpretation'})
        self.assertEqual(retirement_boundary(self.run)['status'], 'retired')

    def test_unrelated_checkpoint_is_not_repair_authority(self):
        self.write('run_manifest.json', {'start_snapshot': {}})
        self.write('stages/ai/ai_checkpoints.jsonl', {
            'checkpoint_id': 'ai-old', 'checkpoint_type': 'research_batch_plan'})
        self.assertIsNone(retirement_boundary(self.run))

    def test_actual_repair_decision_checkpoint_without_ai_prefix(self):
        self.write('run_manifest.json', {'start_snapshot': {}})
        self.write('stages/ai/ai_checkpoints.jsonl', {
            'checkpoint_id': 'historical-123', 'checkpoint_type': 'repair_decision'})
        self.assertEqual(retirement_boundary(self.run)['status'], 'retired')

    def test_runtime_decision_judgment_without_ai_prefix(self):
        self.write('run_manifest.json', {'start_snapshot': {}})
        self.write('runtime/repair_decisions/old.json', {
            'judgment': {'checkpoint_id': 'historical-123', 'status': 'completed'}})
        self.assertEqual(retirement_boundary(self.run)['status'], 'retired')

    def test_explicit_legacy_policy_needs_no_completed_decision(self):
        self.write('run_manifest.json', {'start_snapshot': {'research_policy': {'deterministic_repair': False}}})
        self.assertEqual(retirement_boundary(self.run)['status'], 'retired')

    def test_external_manifest_link_fails_closed(self):
        outside = self.root / 'outside.json'
        outside.write_text('{}', encoding='utf-8')
        try:
            (self.run / 'run_manifest.json').symlink_to(outside)
        except OSError:
            self.skipTest('Windows symlink privilege unavailable')
        self.assertEqual(retirement_boundary(self.run)['status'], 'damaged')

    def test_evidence_path_cannot_escape_owning_run(self):
        with self.assertRaises(ValueError):
            _local_path(self.run, '../outside.json')

    def test_actual_historical_run_readonly(self):
        run = Path(__file__).resolve().parents[3] / 'runs/20261011T175340059665-edf5bbdf'
        if not run.is_dir():
            self.skipTest('private historical run unavailable')
        paths = [run / name for name in ('run_manifest.json', 'run_state.json',
                 'stages/repair/repair_execution.json', 'stages/ai/ai_checkpoints.jsonl')]
        paths += list((run / 'runtime/repair_decisions').glob('*.json'))
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
        result = retirement_boundary(run)
        self.assertEqual(result['status'], 'retired')
        self.assertFalse(result['can_resume'])
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})

    def test_corrupt_manifest_blocks_orchestrator_and_driver(self):
        self.test_orchestrator_boundaries_do_not_recover_or_mutate()
        (self.run / 'run_manifest.json').write_text('{', encoding='utf-8')
        paths = OrchestratorPaths(self.root, self.root, self.root / 'knowledge', self.run.parent)
        orchestrator = WorkflowOrchestrator(paths)
        for result in (orchestrator.status(), orchestrator.resume('now'), orchestrator.continue_once('now')):
            self.assertEqual(result['status'], 'damaged')
        result = run_workflow_driver(paths, {}, status_reader=orchestrator.status,
                                     step=lambda: self.fail('step forbidden'))
        self.assertEqual(result['status'], 'damaged')

    def test_positive_legacy_receipt_is_retired_and_readonly(self):
        self.legacy()
        before = {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()}
        result = retirement_boundary(self.run)
        self.assertEqual(result['status'], 'retired')
        self.assertEqual(result['next_action'], 'workflow-start')
        self.assertFalse(result['can_resume'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()})

    def test_receipt_judgment_does_not_require_ai_prefix(self):
        self.legacy()
        self.write('stages/repair/repair_execution.json', {
            'run_id': self.run.name,
            'attempts': [{'plan': {'judgment': {'checkpoint_id': 'old-model-123'}}}]})
        self.assertEqual(retirement_boundary(self.run)['status'], 'retired')

    def test_deterministic_policy_remains_executable(self):
        self.legacy()
        self.write('run_manifest.json', {'start_snapshot': {'research_policy': {'deterministic_repair': True}}})
        self.assertIsNone(retirement_boundary(self.run))

    def test_corrupt_manifest_is_damaged_not_retired(self):
        self.legacy()
        for content in ('{', '[]', '{"start_snapshot": []}', '{"start_snapshot":{"research_policy":{"deterministic_repair":"true"}}}'):
            with self.subTest(content=content):
                (self.run / 'run_manifest.json').write_text(content, encoding='utf-8')
                self.assertEqual(retirement_boundary(self.run)['status'], 'damaged')

    def test_orchestrator_boundaries_do_not_recover_or_mutate(self):
        self.legacy()
        self.write('runtime/stop_intent.json', {'desired_state': 'paused', 'revision': 7})
        self.write('runtime/submission_accounting.json', {'used': 143, 'limit': 150})
        state = create_initial_state(self.run.name, self.run, 'old', '2026-10-11T00:00:00Z')
        write_run_state(self.run / 'run_state.json', state)
        write_active_run(self.run.parent, self.run.name, self.run)
        paths = OrchestratorPaths(self.root, self.root, self.root / 'knowledge', self.run.parent)
        before = {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()}
        orchestrator = WorkflowOrchestrator(paths)
        with patch('wqb.orchestrator.recover_pending_research_round', side_effect=AssertionError('recovery forbidden')):
            for result in (orchestrator.status(), orchestrator.resume('now'), orchestrator.continue_once('now')):
                self.assertEqual(result['status'], 'retired')
                self.assertEqual(result['next_action'], 'workflow-start')
        self.assertEqual(before, {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()})

    def test_driver_blocks_before_authority_lock_or_step(self):
        self.legacy()
        with patch('wqb.workflow_driver.read_current_recovery_case', side_effect=AssertionError('recovery forbidden')):
            result = run_workflow_driver(None, {}, status_reader=lambda: {'active': True, 'run_dir': str(self.run)},
                                         step=lambda: self.fail('step forbidden'))
        self.assertEqual(result['status'], 'retired')
        self.assertFalse((self.run / 'runtime').exists())

    def test_retired_pointer_allows_separate_new_start_without_old_mutation(self):
        self.test_orchestrator_boundaries_do_not_recover_or_mutate()
        paths = OrchestratorPaths(self.root, self.root, self.root / 'knowledge', self.run.parent)
        orchestrator = WorkflowOrchestrator(paths)
        before = {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()}
        with patch('wqb.orchestrator.create_start_snapshot', side_effect=ValueError('readiness blocked')):
            with self.assertRaisesRegex(ValueError, 'readiness blocked'):
                orchestrator.start('new separately approved', 'new-option', '2026-11-03T00:00:00Z')
        with patch('wqb.orchestrator.create_start_snapshot', return_value={
                'selected_scope': {'region': 'USA'},
                'research_policy': {'deterministic_repair': True}}) as preflight:
            started = orchestrator.start('new separately approved', 'new-option', '2026-11-03T00:00:00Z',
                                         research_policy={'deterministic_repair': True})
        preflight.assert_called_once()
        self.assertNotEqual(started['run_id'], self.run.name)
        self.assertEqual(started['status'], 'created')
        self.assertEqual(orchestrator.status()['run_id'], started['run_id'])
        advanced = orchestrator.continue_once('2026-11-03T00:01:00Z')
        self.assertEqual(advanced['current_stage'], 'schedule')
        self.assertEqual(advanced['status'], 'running')
        self.assertEqual(before, {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()})

    def test_retired_sibling_does_not_hide_two_live_missions(self):
        self.test_retired_pointer_allows_separate_new_start_without_old_mutation()
        other = self.run.parent / 'another-live-run'
        other.mkdir()
        write_run_state(other / 'run_state.json', create_initial_state(
            other.name, other, 'independent', '2026-11-03T00:00:00Z'))
        paths = OrchestratorPaths(self.root, self.root, self.root / 'knowledge', self.run.parent)
        summary = WorkflowOrchestrator(paths).status()
        self.assertEqual(summary['status'], 'damaged')
        self.assertIn('multiple_active_runs', summary['diagnostics'])

    def test_console_finds_new_start_beside_retired_without_writes(self):
        from wqb.console_state import _active_workflow_summary
        self.test_retired_pointer_allows_separate_new_start_without_old_mutation()
        before = {p: p.read_bytes() for p in self.run.parent.rglob('*') if p.is_file()}
        summary, selected = _active_workflow_summary(self.run.parent)
        self.assertTrue(summary['exists'])
        self.assertNotEqual(summary['run_id'], self.run.name)
        self.assertEqual(summary['run_id'], selected.name)
        self.assertNotIn('multiple_active_runs', summary['diagnostics'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.run.parent.rglob('*') if p.is_file()})

    def test_console_keeps_multiple_live_missions_blocked(self):
        from wqb.console_state import _active_workflow_summary
        self.test_retired_sibling_does_not_hide_two_live_missions()
        summary, _ = _active_workflow_summary(self.run.parent)
        self.assertTrue(summary['exists'])
        self.assertFalse(summary['state_exists'])
        self.assertIn('multiple_active_runs', summary['diagnostics'])

    def test_retired_pointer_cannot_hide_an_unselected_live_mission(self):
        from wqb.console_state import _active_workflow_summary
        self.test_retired_pointer_allows_separate_new_start_without_old_mutation()
        write_active_run(self.run.parent, self.run.name, self.run)
        paths = OrchestratorPaths(self.root, self.root, self.root / 'knowledge', self.run.parent)
        orchestrator = WorkflowOrchestrator(paths)
        self.assertEqual(orchestrator.status()['status'], 'damaged')
        summary, _ = _active_workflow_summary(self.run.parent)
        self.assertIn('multiple_active_runs', summary['diagnostics'])
        with self.assertRaisesRegex(ValueError, 'active workflow'):
            orchestrator.start('not allowed', 'new-option', '2026-11-03T00:00:00Z')

    def test_console_new_mission_stop_uses_new_identity_and_preserves_stop(self):
        from tests.test_console_state import make_paths
        from wqb.console_state import _active_workflow_summary, load_console_state
        from wqb.console_server import _workflow_action_state
        from wqb.runtime_control import request_runtime_state
        self.test_retired_pointer_allows_separate_new_start_without_old_mutation()
        _, selected = _active_workflow_summary(self.run.parent)
        old_before = {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()}
        request_runtime_state(selected, 'running')
        state = load_console_state(make_paths(self.root))
        self.assertEqual(state['active_workflow']['run_id'], selected.name)
        self.assertTrue(_workflow_action_state(state)['stop_workflow'])
        request_runtime_state(selected, 'paused')
        stopped = load_console_state(make_paths(self.root))
        self.assertEqual(stopped['active_workflow']['run_id'], selected.name)
        self.assertEqual(stopped['runtime_control']['desired_state'], 'paused')
        self.assertEqual(old_before, {p: p.read_bytes() for p in self.run.rglob('*') if p.is_file()})

    def test_discovery_rejects_linked_sibling_before_raw_state_reads(self):
        from wqb.research_retirement import discover_retirement_aware_workflow
        for link_check in ('is_symlink', 'is_junction'):
            with self.subTest(link_check=link_check):
                with patch.object(Path, link_check, lambda path: path == self.run), patch(
                        'wqb.workflow_state.discover_active_workflow', side_effect=AssertionError('must not follow sibling')):
                    result = discover_retirement_aware_workflow(self.run.parent)
                self.assertIn('linked_run_directory', result.diagnostics)

    def test_discovery_reads_selected_retirement_boundary_once(self):
        from wqb.research_retirement import discover_retirement_aware_workflow
        self.test_retired_pointer_allows_separate_new_start_without_old_mutation()
        selected = discover_retirement_aware_workflow(self.run.parent).run_dir
        with patch('wqb.research_retirement.retirement_boundary', wraps=retirement_boundary) as classify:
            discover_retirement_aware_workflow(self.run.parent)
        self.assertEqual(sum(Path(call.args[0]).resolve() == selected.resolve()
                             for call in classify.call_args_list), 1)


if __name__ == '__main__':
    unittest.main()
