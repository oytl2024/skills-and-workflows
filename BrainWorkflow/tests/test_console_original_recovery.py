import unittest
from unittest.mock import patch

from wqb.console_server import _workflow_action_state, _render_workflow_progress


class ConsoleOriginalRecoveryTests(unittest.TestCase):
    def state(self):
        return {'active_workflow': {'exists': True},
                'source_bridge': {'action': 'rate_limit_wait'},
                'current_work': {'next_action': 'readiness-blocked'},
                'runtime_control': {'desired_state': 'paused', 'status': 'paused',
                                    'original_batch_recovery': {'authorized': True, 'remaining': 9, 'planned': 29}}}

    def test_approved_original_batch_resume_owns_scripted_recovery(self):
        state = self.state()
        self.assertTrue(_workflow_action_state(state)['continue_workflow'])
        self.assertIn('9', _render_workflow_progress(state))

    def test_code_confirmation_still_blocks_original_batch(self):
        state = self.state()
        state['runtime_control']['recovery_case'] = {'status': 'awaiting_maintenance_confirmation'}
        self.assertFalse(_workflow_action_state(state)['continue_workflow'])

    def test_unknown_source_blocker_not_overridden(self):
        state = self.state()
        state['source_bridge'] = {'action': 'maintenance_blocker', 'metadata': {}}
        self.assertFalse(_workflow_action_state(state)['continue_workflow'])

    def test_original_recovery_progress_precedes_old_readiness_banner(self):
        from wqb.console_timeline import select_current_work
        state = self.state()
        state['runtime_control'].update(status='completed', reason='original batch complete')
        with patch('wqb.console_timeline.readiness_blocker_current_work', return_value={'title': 'old blocker'}):
            work = select_current_work(state, [])
        self.assertEqual(work['status'], 'completed')
        self.assertIn('Original', work['title'])
