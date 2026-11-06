import json
import os
from pathlib import Path
import tempfile
import unittest

from tests.test_console_state import make_paths
from wqb.console_state import project_start_readiness
from wqb.console_timeline import select_current_work


class StartProjectionTests(unittest.TestCase):
    def test_stop_intent_takes_priority_over_preparation_job(self):
        """Input: cancelled prep and old running job. Output: assertions. Stop is visible immediately."""
        state = {'start_request': {'status': 'cancelled'},
                 'readiness': {'context': 'new-mission-preflight'},
                 'jobs': [{'action': 'workflow-start-from-option', 'status': 'running'}]}
        self.assertEqual(select_current_work(state, [])['next_action'], 'start-preflight-paused')

    def test_completed_original_scope_does_not_certify_new_start(self):
        """Input: old passing run. Output: assertions. A new mission requires its own preflight."""
        with tempfile.TemporaryDirectory() as tmp:
            state = {'readiness': {'passed': True}, 'runtime_control': {
                'original_batch_recovery': {'authorized': True, 'planned': 29, 'remaining': 0}}}
            project_start_readiness(make_paths(Path(tmp)), state)
            self.assertFalse(state['readiness']['passed'])
            self.assertTrue(state['run_readiness']['passed'])

    def test_failed_preflight_visible_ahead_of_completed_original_scope(self):
        """Input: failed scoped receipt. Output: assertions. Show exact blocked artifacts, not old completion."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            directory = paths.runs_root / 'start_preflight'
            directory.mkdir(parents=True)
            receipt = {'passed': False, 'blocked': True, 'scope': {'region': 'USA', 'delay': 1, 'universe': 'TOP3000'},
                       'issues': [{'level': 'block', 'code': 'stale', 'path': 'raw/platform/operators.md',
                                   'message': 'Old operators', 'action': 'Explicit refresh required'}]}
            (directory / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
            state = {'readiness': {'passed': True}, 'runtime_control': {
                'original_batch_recovery': {'authorized': True, 'planned': 29, 'remaining': 0}}}
            project_start_readiness(paths, state)
            current = select_current_work(state, [])
            self.assertEqual(current['next_action'], 'start-preflight-blocked')
            self.assertIn('raw/platform/operators.md', ' '.join(current['details']))

    def test_live_mission_keeps_own_readiness(self):
        """Input: live mission. Output: assertions. Old Start receipts cannot block unrelated active work."""
        with tempfile.TemporaryDirectory() as tmp:
            state = {'active_workflow': {'exists': True, 'status': 'running'}, 'readiness': {'passed': True}}
            project_start_readiness(make_paths(Path(tmp)), state)
            self.assertTrue(state['readiness']['passed'])

    def test_blocked_request_never_borrows_newer_other_scope_receipt(self):
        """Input: current request A and newer receipt B. Output: assertions. Keep scope and evidence from one attempt."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            directory = paths.runs_root / 'start_preflight'
            directory.mkdir(parents=True)
            scope = {'region': 'USA', 'delay': 1, 'universe': 'TOP3000'}
            a = directory / 'a.json'
            a.write_text(json.dumps({'scope': scope, 'checked_at': 'A', 'receipt_path': str(a)}))
            b = directory / 'b.json'
            b.write_text(json.dumps({'scope': {'region': 'CHN'}, 'checked_at': 'B', 'receipt_path': str(b)}))
            os.utime(a, (1, 1))
            os.utime(b, (2, 2))
            request = paths.runs_root / 'console_start' / 'request.json'
            request.parent.mkdir(parents=True)
            request.write_text(json.dumps({'status': 'blocked', 'selection': {'scope': scope},
                'preflight_receipt_path': str(a), 'issues': [{'code': 'stale-A'}]}))
            state = {'readiness': {'passed': True}}
            project_start_readiness(paths, state)
            self.assertEqual(state['start_preflight']['scope'], scope)
            self.assertEqual(state['start_preflight']['checked_at'], 'A')
            self.assertEqual(state['start_preflight']['receipt_path'], str(a))
