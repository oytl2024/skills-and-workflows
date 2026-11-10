"""Offline contracts for actual planner cards and pre-mission failures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from tests.test_console_server import make_paths, valid_option
from wqb import console_start
from wqb.knowledge_paths import decision_artifact_path


class ApplicationOptionContractTests(unittest.TestCase):
    def setUp(self):
        # Input: TestCase; output: isolated paths and public-like configuration.
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.paths = make_paths(Path(temporary.name))
        directory = self.paths.workflow_root / 'configs'
        directory.mkdir(parents=True)
        self.config = directory / 'workflow_local.json'
        self.config.write_text(json.dumps(dict(region='USA', delay=1, universe='TOP3000', live_api_enabled=False)))

    def save_option(self, **overrides):
        # Input: option keyword overrides; output: normalized input row written in isolated vault.
        row = valid_option(option_id='choice', **overrides)
        path = decision_artifact_path(self.paths.knowledge_root, 'research_option_cards.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row) + '\n', encoding='utf-8')
        return row

    def test_generated_generic_goal_uses_explicit_saved_scope(self):
        self.save_option(primary_incentive='genius_osmosis', candidate_scope='Generate a later concrete plan across multiple region-delay scopes after user selection.')
        form = console_start.application_start_form(self.paths, 'choice')
        self.assertEqual((form['selected_region'], form['selected_delay'], form['selected_universe']), ('USA', 1, 'TOP3000'))
        self.assertFalse(form['enable_live_api'])

    def test_selected_scope_overrides_flat_configuration(self):
        self.config.write_text(json.dumps(dict(region='USA', delay=1, universe='TOP3000', selected_scope=dict(region='KOR', delay=0, universe='TOP600'))))
        self.save_option(primary_incentive='genius_osmosis', candidate_scope='Generate a later concrete plan across multiple region-delay scopes after user selection.')
        form = console_start.application_start_form(self.paths, 'choice')
        self.assertEqual((form['selected_region'], form['selected_delay'], form['selected_universe']), ('KOR', 0, 'TOP600'))

    def test_structured_option_scope_is_authoritative(self):
        self.save_option(candidate_scope='Selected research scope', execution_scope=dict(region='KOR', delay=0, universe='TOP600'))
        form = console_start.application_start_form(self.paths, 'choice')
        self.assertEqual((form['selected_region'], form['selected_delay'], form['selected_universe']), ('KOR', 0, 'TOP600'))

    def test_bad_explicit_scope_never_falls_back(self):
        for scope in [dict(region='KOR', delay=True, universe='TOP600'), dict(region='KOR', delay=0), None]:
            self.save_option(candidate_scope='USA D1 TOP3000', execution_scope=scope)
            with self.assertRaises(ValueError):
                console_start.application_start_form(self.paths, 'choice')

    def test_maintenance_cards_do_not_become_generic_research(self):
        for incentive in ['knowledge_refresh', 'theme', 'competition']:
            self.save_option(primary_incentive=incentive, candidate_scope='Refresh active announcements before choosing data or templates.')
            with self.assertRaisesRegex(ValueError, 'maintenance'):
                console_start.application_start_form(self.paths, 'choice')

    def test_multi_scope_description_does_not_fall_back(self):
        self.save_option(candidate_scope='USA D1 TOP3000 or KOR D0 TOP600')
        with self.assertRaises(ValueError):
            console_start.application_start_form(self.paths, 'choice')

    def test_unresolved_power_pool_board_never_becomes_generic_usa_research(self):
        self.save_option(primary_incentive='power_pool', candidate_scope='Choose a board first; only then select matching region, delay, data, and simple templates.')
        with self.assertRaisesRegex(ValueError, 'maintenance'):
            console_start.application_start_form(self.paths, 'choice')

    def test_conflicting_scope_and_partial_configuration_are_rejected(self):
        self.save_option(candidate_scope='USA D1 TOP3000', execution_scope=dict(region='KOR', delay=0, universe='TOP600'))
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            console_start.application_start_form(self.paths, 'choice')
        self.config.write_text(json.dumps(dict(region='USA', delay=1, universe='TOP3000', selected_scope=dict(region='KOR'))))
        self.save_option(primary_incentive='genius_osmosis', candidate_scope='Plan across region-delay scopes after selection.')
        with self.assertRaises(ValueError):
            console_start.application_start_form(self.paths, 'choice')

    def test_display_contract_shows_scope_and_disabled_reason(self):
        row = self.save_option(primary_incentive='genius_osmosis', candidate_scope='Generate a later concrete plan across multiple region-delay scopes after user selection.')
        result = console_start.application_option(self.paths, row)
        self.assertTrue(result['startable'])
        self.assertEqual(result['scope'], dict(region='USA', delay=1, universe='TOP3000'))
        self.assertEqual(result['scope_source'], 'configuration')
        row.update(primary_incentive='theme')
        result = console_start.application_option(self.paths, row)
        self.assertFalse(result['startable'])
        self.assertIn('maintenance', result['reason'])

    def test_failure_is_durable_without_job_and_delivery_deduplicates(self):
        from wqb import preflight_notifications as notices
        command = dict(command_id='offline-command', selected_option_id='choice')
        with patch.object(notices.shutil, 'which', return_value='codex'), patch.object(
                notices.subprocess, 'run', return_value=Mock(returncode=0)) as queue:
            (self.paths.runs_root / 'maintenance_channel.json').parent.mkdir(parents=True, exist_ok=True)
            (self.paths.runs_root / 'maintenance_channel.json').write_text(json.dumps(dict(thread_id='019ff06b-7447-7071-a13d-b2568f62bdb2')))
            first = notices.record_start_contract_failure(self.paths, command, 'unbound scope')
            self.assertEqual(first['notification']['status'], 'pending')
            notices.dispatch_start_contract_notice(self.paths.runs_root, Path(first['receipt_path']))
            second = notices.record_start_contract_failure(self.paths, {**command, 'command_id': 'retry'}, 'unbound scope')
            notices.dispatch_start_contract_notice(self.paths.runs_root, Path(second['receipt_path']))
        self.assertEqual(first['receipt_path'], second['receipt_path'])
        self.assertEqual(second['notification']['status'], 'queued')
        queue.assert_called_once()
        self.assertFalse(list(self.paths.runs_root.glob('*/run_state.json')))
        self.assertFalse((self.paths.runs_root / 'console_start/request.json').exists())

    def test_pending_failure_is_dispatched_on_restart_not_status_poll(self):
        from wqb import preflight_notifications as notices
        row = notices.record_start_contract_failure(self.paths, dict(command_id='one', selected_option_id='choice'), 'scope unavailable')
        with patch.object(notices, 'notify_preflight_blocker', return_value=dict(status='delivery_uncertain')) as notify:
            notices.dispatch_pending_start_contract_notices(self.paths.runs_root)
            notices.dispatch_pending_start_contract_notices(self.paths.runs_root)
        notify.assert_called_once()
        self.assertEqual(json.loads(Path(row['receipt_path']).read_text())['notification']['status'], 'delivery_uncertain')

    def test_completed_notice_prefix_cannot_starve_pending_startup_delivery(self):
        from wqb import preflight_notifications as notices
        row = notices.record_start_contract_failure(self.paths, dict(command_id='one', selected_option_id='choice'), 'pending')
        path = Path(row['receipt_path'])
        for number in range(100):
            (path.parent / f'{number:064x}.json').write_text(json.dumps(dict(notification=dict(status='queued'))))
        with patch.object(notices, 'notify_preflight_blocker', return_value=dict(status='queued')) as notify:
            notices.dispatch_pending_start_contract_notices(self.paths.runs_root)
        notify.assert_called_once()

    def test_malformed_notice_does_not_abort_other_pending_deliveries(self):
        from wqb import preflight_notifications as notices
        row = notices.record_start_contract_failure(self.paths, dict(command_id='one', selected_option_id='choice'), 'pending')
        (Path(row['receipt_path']).parent / ('0' * 64 + '.json')).write_text(json.dumps(dict(notification=None)))
        with patch.object(notices, 'notify_preflight_blocker', return_value=dict(status='queued')) as notify:
            notices.dispatch_pending_start_contract_notices(self.paths.runs_root)
        notify.assert_called_once()


if __name__ == '__main__':
    unittest.main()
