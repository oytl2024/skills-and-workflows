import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb.runtime_control import CONTROL_ENV, RuntimePaused, request_runtime_state


class OriginalBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / 'run'
        self.source = Path(self.temp.name) / 'source'
        self.source.mkdir()
        binding = self.run / 'stages/scout_seed/source_bridge_binding.json'
        binding.parent.mkdir(parents=True)
        binding.write_text(json.dumps({'source_run_dir': str(self.source)}))
        self.plan = [{'expression': 'rank(x)', 'expression_hash': 'a'},
                     {'expression': 'rank(y)', 'expression_hash': 'b'}]
        self.write_rows('planned_candidates.jsonl', self.plan)
        self.write_rows('simulation_events.jsonl', [{'event': 'CHECKED', 'expression_hash': 'a'}])
        self.settings = {'region': 'USA', 'delay': 1, 'universe': 'TOP3000'}

    def write_rows(self, name, rows):
        (self.source / name).write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def approve(self):
        from wqb.original_batch_recovery import approve_original_batch
        return approve_original_batch(self.run, self.settings, 'user: finish original pending batch')

    def test_approval_freezes_remaining_and_stays_paused(self):
        receipt = self.approve()
        self.assertEqual(receipt['allowed_expressions'], ['rank(y)'])
        self.assertEqual(receipt['historical_attempts'], None)
        self.assertEqual(json.loads((self.run / 'runtime_control.json').read_text())['desired_state'], 'paused')
        self.assertEqual(json.loads((self.run / 'runtime_status.json').read_text())['status'], 'paused')

    def test_repeat_approval_does_not_reset_usage_or_pause(self):
        from wqb.runtime_control import update_runtime_status, read_runtime_control
        first = self.approve()
        update_runtime_status(self.run, simulation_attempts=2)
        self.assertEqual(self.approve(), first)
        self.assertEqual(read_runtime_control(self.run)['simulation_attempts'], 2)

    def test_plan_drift_fails_closed(self):
        from wqb.original_batch_recovery import read_original_batch
        self.approve()
        self.write_rows('planned_candidates.jsonl', self.plan + [{'expression': 'rank(z)', 'expression_hash': 'c'}])
        with self.assertRaisesRegex(RuntimePaused, 'changed'):
            read_original_batch(self.run)

    def test_guard_rejects_new_expression_and_changed_settings(self):
        from wqb.original_batch_recovery import validate_original_payloads
        self.approve()
        with patch.dict(os.environ, {CONTROL_ENV: str(self.run)}):
            validate_original_payloads({'type': 'REGULAR', 'settings': self.settings, 'regular': 'rank(y)'})
            for expression, settings in [('rank(x)', self.settings), ('rank(y)', {**self.settings, 'delay': 0})]:
                with self.assertRaises(RuntimePaused):
                    validate_original_payloads({'type': 'REGULAR', 'settings': settings, 'regular': expression})

    def test_pause_prevents_submission_after_adoption(self):
        from wqb.runtime_control import check_submission_allowed
        self.approve()
        with patch.dict(os.environ, {CONTROL_ENV: str(self.run)}):
            with self.assertRaises(RuntimePaused):
                check_submission_allowed(1)
            request_runtime_state(self.run, 'running')
            check_submission_allowed(1)
            request_runtime_state(self.run, 'paused')
            with self.assertRaises(RuntimePaused):
                check_submission_allowed(1)

    def test_resume_cannot_increase_scoped_limits(self):
        self.approve()
        with self.assertRaisesRegex(ValueError, 'scope'):
            request_runtime_state(self.run, 'running', max_simulations=150)

    def test_pause_cannot_expand_scoped_time_limit(self):
        self.approve()
        with self.assertRaisesRegex(ValueError, 'scope'):
            request_runtime_state(self.run, 'paused', max_runtime_seconds=999999)

    def test_deleted_scope_cannot_become_general_authority(self):
        from wqb.runtime_control import has_runtime_authority
        self.approve()
        (self.run / 'runtime/original_batch_scope.json').unlink()
        self.assertFalse(has_runtime_authority(self.run))

    def test_partial_scope_fails_closed_without_crashing_authority_projection(self):
        from wqb.runtime_control import has_runtime_authority
        self.approve()
        path = self.run / 'runtime/original_batch_scope.json'
        row = json.loads(path.read_text())
        del row['max_runtime_seconds']
        path.write_text(json.dumps(row))
        self.assertFalse(has_runtime_authority(self.run))

    def test_finished_batch_stops_without_knowledge_refresh_or_new_research(self):
        from wqb.original_batch_recovery import original_batch_step
        self.approve()
        self.write_rows('simulation_events.jsonl', [{'event': 'CHECKED', 'expression_hash': x} for x in ['a', 'b']])
        with patch('wqb.knowledge_recovery.recover_knowledge') as knowledge:
            result = original_batch_step(self.run, {}, '2026-10-11T00:00:00+00:00')
        self.assertEqual(result['status'], 'completed')
        knowledge.assert_not_called()

    def test_knowledge_recovery_uses_frozen_scope_not_current_config(self):
        from wqb.original_batch_recovery import original_batch_step
        self.approve()
        request_runtime_state(self.run, 'running')
        config = {'region': 'EUR', 'delay': 0, 'universe': 'TOP500', 'knowledge_root': str(self.run.parent / 'vault')}
        with patch.dict(os.environ, {CONTROL_ENV: str(self.run)}), \
             patch('wqb.knowledge_recovery.recover_knowledge', return_value={'status': 'blocked'}) as knowledge:
            result = original_batch_step(self.run, config, '2026-10-11T00:00:00+00:00')
        self.assertEqual(result['next_action'], 'readiness-blocked')
        passed = knowledge.call_args.args[1]
        self.assertEqual((passed['region'], passed['delay'], passed['universe']), ('USA', 1, 'TOP3000'))

    def test_driver_recovers_original_batch_without_general_stage_runner(self):
        from wqb.original_batch_recovery import original_batch_step
        from wqb.workflow_driver import run_workflow_driver
        from types import SimpleNamespace
        self.approve()
        request_runtime_state(self.run, 'running')
        config = {'knowledge_root': str(self.run.parent / 'vault'), 'runtime_max_steps': 3}
        def finish(client, recorder, frozen, **kwargs):
            self.assertEqual(kwargs['submit_mode'], 'multi')
            self.assertEqual(kwargs['multi_chunk_size'], 5)
            self.assertEqual(frozen['region'], 'USA')
            self.write_rows('simulation_events.jsonl', [{'event': 'CHECKED', 'expression_hash': x} for x in ['a', 'b']])
        with patch('wqb.knowledge_recovery.recover_knowledge', return_value={'status': 'completed'}), \
             patch('wqb.cli.build_client'), patch('wqb.cli.retry_planned_candidates', side_effect=finish) as retry, \
             patch('wqb.workflow_driver.schedule_run_checkpoint'):
            result = run_workflow_driver(SimpleNamespace(), config,
                status_reader=lambda: {'active': True, 'run_dir': str(self.run)},
                step=lambda: original_batch_step(self.run, config, '2026-10-11T00:00:00+00:00'))
        self.assertEqual(result['runtime_status'], 'completed')
        self.assertEqual(result['next_action'], 'original-batch-complete')
        retry.assert_called_once()

    def test_pause_remains_possible_when_scope_has_drifted(self):
        self.approve()
        request_runtime_state(self.run, 'running')
        self.write_rows('planned_candidates.jsonl', self.plan + [{'expression': 'rank(z)', 'expression_hash': 'c'}])
        self.assertEqual(request_runtime_state(self.run, 'paused')['desired_state'], 'paused')

    def test_standalone_step_cannot_bypass_driver_authority(self):
        from wqb.original_batch_recovery import original_batch_step
        self.approve()
        request_runtime_state(self.run, 'running')
        with patch.dict(os.environ, {}, clear=True), patch('wqb.knowledge_recovery.recover_knowledge') as knowledge:
            with self.assertRaises(RuntimePaused):
                original_batch_step(self.run, {}, '2026-10-11T00:00:00+00:00')
        knowledge.assert_not_called()

    def test_current_submission_journal_does_not_block_own_post(self):
        from wqb.original_batch_recovery import validate_original_payloads
        from wqb.recorder import RunRecorder
        from wqb.submission_attempts import start_submission_attempt
        self.approve()
        request_runtime_state(self.run, 'running')
        start_submission_attempt(RunRecorder(self.source), [self.plan[1]], 'test')
        with patch.dict(os.environ, {CONTROL_ENV: str(self.run)}):
            validate_original_payloads({'type': 'REGULAR', 'settings': self.settings, 'regular': 'rank(y)'})
