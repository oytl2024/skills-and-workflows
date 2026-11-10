"""Isolated manual Multiplier selection and cancellable preparation."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_console_server import make_paths, valid_option
from tests.test_multiplier_scope import settings_fixture
from wqb import console_start
from wqb.knowledge_paths import decision_artifact_path
from wqb.multiplier_scope import publish_scope_catalog


class MultiplierStartTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated actual-style option/settings/config; no network credentials."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.paths = make_paths(Path(temporary.name))
        config = self.paths.workflow_root / 'configs/workflow_local.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps(dict(region='USA', delay=1, universe='TOP3000',
            measurement_period=dict(start='2014-01-01', end='2023-12-29'),
            research_policy=dict(paired_scout=True, preplanned_tree_version=1, multiplier_scope_version=1))))
        self.option = valid_option(option_id='multiplier', primary_incentive='theme',
            candidate_scope='Refresh active theme announcements before choosing data or templates.')
        path = decision_artifact_path(self.paths.knowledge_root, 'research_option_cards.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.option) + '\n', encoding='utf-8')
        publish_scope_catalog(self.paths.knowledge_root, settings_fixture(), datetime.now(timezone.utc).isoformat())

    def form(self):
        """Input: fixture. Output: selected-scope Start form, explicitly submitted by the user."""
        return console_start.application_start_form(self.paths, 'multiplier',
            selected_scope=dict(region='KOR', delay=1, universe='TOP600'))

    def test_multiplier_is_selectable_without_local_fields_or_activity_lookup(self):
        option = console_start.application_option(self.paths, self.option)
        self.assertTrue(option['startable'])
        self.assertEqual(option['selection_mode'], 'manual_multiplier')
        self.assertIn(dict(region='KOR', delay=1, universe='TOP600'), option['scope_selection']['choices'])
        self.assertIsNone(option['scope'])

    def test_selected_scope_and_capture_permission_are_explicit(self):
        form = self.form()
        self.assertEqual((form['selected_region'], form['selected_delay'], form['selected_universe']), ('KOR', 1, 'TOP600'))
        self.assertTrue(form['enable_live_api'])
        with self.assertRaises(ValueError):
            console_start.application_start_form(self.paths, 'multiplier')
        with self.assertRaises(ValueError):
            console_start.application_start_form(self.paths, 'multiplier', selected_scope=dict(region='KOR', delay=0, universe='TOP600'))

    def test_preparation_precedes_existing_coordinator_and_records_manual_judgment(self):
        form = self.form()
        request = console_start.register_start(self.paths, form, 'offline-job')
        with patch('wqb.multiplier_supervision.prepare_multiplier_fields_supervised', return_value=dict(status='completed', reused=True, requests_used=0)) as prepare, \
             patch.object(console_start, '_execute_preplanned_start', return_value=dict(status='completed', passed=True)) as coordinate:
            result = console_start.execute_start(self.paths, form, request['request_id'])
        self.assertTrue(result['passed'])
        prepare.assert_called_once()
        coordinate.assert_called_once()
        persisted = console_start.read_start_request(self.paths.runs_root)
        self.assertEqual(persisted['multiplier_preparation']['status'], 'completed')
        self.assertEqual(persisted['preplanned_option']['manual_multiplier']['eligibility'], 'user_assessed')
        self.assertFalse(list(self.paths.runs_root.glob('*/run_state.json')))

    def test_stop_during_preparation_prevents_planning_and_never_notifies_a_code_fault(self):
        form = self.form()
        request = console_start.register_start(self.paths, form, 'offline-job')

        def interrupted(*args, **kwargs):
            """Input: preparation args. Output: interruption; emulate Stop without changing any old mission."""
            console_start.cancel_start(self.paths.runs_root)
            kwargs['check_cancelled']()

        with patch('wqb.multiplier_supervision.prepare_multiplier_fields_supervised', side_effect=interrupted), \
             patch.object(console_start, '_execute_preplanned_start') as coordinate, \
             patch.object(console_start, '_notify_blocked_request') as notify:
            result = console_start.execute_start(self.paths, form, request['request_id'])
        self.assertEqual(result['status'], 'cancelled')
        coordinate.assert_not_called()
        notify.assert_not_called()

    def test_failed_preparation_exposes_failure_without_starting_planning(self):
        """Input: bounded worker timeout. Output: durable failure and notification, never planning."""
        form = self.form()
        request = console_start.register_start(self.paths, form, 'offline-job')
        with patch('wqb.multiplier_supervision.prepare_multiplier_fields_supervised', side_effect=TimeoutError('preparation deadline exhausted')), \
             patch.object(console_start, '_execute_preplanned_start') as coordinate, \
             patch.object(console_start, '_notify_blocked_request', side_effect=lambda paths, row: row):
            result = console_start.execute_start(self.paths, form, request['request_id'])
        self.assertEqual(result['multiplier_preparation']['status'], 'blocked')
        self.assertIn('deadline', result['multiplier_preparation']['reason'])
        coordinate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
