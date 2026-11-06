import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from wqb.preflight_notifications import notify_preflight_blocker


class PreflightNotificationTests(unittest.TestCase):
    def test_failed_preflight_queues_once_without_authorizing_capture(self):
        """Input: blocked receipt and configured channel. Output: assertions. Duplicate requests never replay delivery."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'maintenance_channel.json').write_text(json.dumps({'thread_id': '019ff06b-7447-7071-a13d-b2568f62bdb2'}))
            receipt = {'blocked': True, 'scope': {'region': 'USA'}, 'knowledge_root': str(root / 'knowledge'),
                       'issues': [{'code': 'stale', 'path': 'raw/platform/operators.md'}], 'receipt_path': str(root / 'receipt.json')}
            with patch('wqb.preflight_notifications.shutil.which', return_value='codex'), \
                    patch('wqb.preflight_notifications.subprocess.run', return_value=Mock(returncode=0)) as queue:
                first = notify_preflight_blocker(root, receipt)
                second = notify_preflight_blocker(root, receipt)
            self.assertEqual(first['status'], 'queued')
            self.assertEqual(second['request_id'], first['request_id'])
            self.assertFalse(first['online_refresh_authorized'])
            queue.assert_called_once()
            self.assertEqual(list(root.glob('*/run_state.json')), [])

    def test_missing_channel_is_visible_not_delivered(self):
        """Input: no notification channel. Output: assertions. Delivery failure is persisted, not reported successful."""
        with tempfile.TemporaryDirectory() as tmp:
            result = notify_preflight_blocker(Path(tmp), {'blocked': True, 'issues': []})
            self.assertEqual(result['status'], 'failed')

    def test_passing_preflight_has_no_notification(self):
        """Input: passing receipt. Output: assertions. Healthy Start creates no maintenance request."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(notify_preflight_blocker(Path(tmp), {'passed': True}), {})
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_corrupt_delivery_evidence_is_not_replayed(self):
        """Input: unreadable prior request. Output: assertions. Uncertain delivery never retries automatically."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = {'blocked': True, 'issues': []}
            first = notify_preflight_blocker(root, receipt)
            path = root / 'start_preflight' / 'notifications' / (first['request_id'] + '.json')
            path.write_text('{', encoding='utf-8')
            with patch('wqb.preflight_notifications.subprocess.run') as queue:
                result = notify_preflight_blocker(root, receipt)
            self.assertEqual(result['status'], 'delivery_uncertain')
            queue.assert_not_called()
