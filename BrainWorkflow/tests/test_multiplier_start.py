"""Isolated manual Multiplier selection and cancellable preparation."""
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tests.test_console_server import make_paths, valid_option
from tests.test_multiplier_scope import settings_fixture
from wqb import console_start
from wqb.knowledge_paths import decision_artifact_path
from wqb.multiplier_scope import publish_scope_catalog


class MultiplierStartTests(unittest.TestCase):
    def test_actual_large_catalog_scan_detects_changed_source_with_bounded_checks(self):
        """Input: real153k-row ledger and advancing clock. Output: mid-scan cancellation with bounded discovery cost."""
        from wqb.multiplier_preparation import _ready
        ledger = self.paths.knowledge_root/'machine/data_ledger.jsonl'
        line = json.dumps(dict(field_type='MATRIX', source_quality='platform_raw_capture',
            coverage_status='measured_raw', coverage=.5,
            available_scopes=[dict(instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000')]))+'\n'
        ledger.write_text(line*153513)
        form = self.form()
        request = console_start.register_start(self.paths, form, 'actual-large-scan')
        source = dict(request['source_intent'])
        clock, rows, discoveries = [0.0], [0], []
        def intent(root):
            """Input: runs Path. Output: current test authority and an observable full-check count."""
            discoveries.append(clock[0])
            return dict(source)
        def prepare(root, job, scope, **kwargs):
            """Input: real scan resources. Output: cancelled when an independent source revision changes."""
            def check():
                rows[0] += 1
                clock[0] = rows[0]/50000
                if rows[0] == 75000:
                    source['request_revision'] = 'new-source-revision'
                kwargs['check_cancelled']()
            _ready(root, scope, check)
            raise AssertionError('changed source ignored throughout real catalog')
        with patch.object(console_start, 'time', SimpleNamespace(monotonic=lambda: clock[0])), \
             patch.object(console_start, '_source_intent', side_effect=intent), \
             patch('wqb.multiplier_supervision.prepare_multiplier_fields_supervised', side_effect=prepare), \
             patch.object(console_start, '_execute_preplanned_start') as coordinate:
            result = console_start.execute_start(self.paths, form, request['request_id'])
        self.assertEqual(result['status'], 'cancelled')
        self.assertGreaterEqual(rows[0], 75000)
        self.assertLess(rows[0], 87510)
        self.assertLess(len(discoveries), 15)
        self.assertGreater(len(discoveries), 4)
        coordinate.assert_not_called()

    def test_malformed_optional_capture_cannot_prevent_terminal_failure(self):
        """Input: checksum-valid malformed display capture. Output: terminal blocked request, no qualification."""
        from wqb.multiplier_preparation import _save
        form = self.form()
        request = console_start.register_start(self.paths, form, 'bad-display')
        directory = self.paths.runs_root/'start_preflight/multiplier'/request['request_id']
        directory.mkdir(parents=True)
        _save(directory/'state.json', dict(scope=request['selection']['scope'],
            knowledge_root=str(self.paths.knowledge_root), requests_used=6, capture='malformed'))
        with console_start.start_request_guard(self.paths.runs_root):
            result = console_start._blocked_request(self.paths, request, {}, 'worker failed')
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['multiplier_preparation']['status'], 'blocked')
        self.assertEqual(result['multiplier_preparation']['field_count'] if 'field_count' in result['multiplier_preparation'] else 0, 0)

    def test_stop_is_observed_within_check_interval_during_scan(self):
        """Input: Stop between cached checks. Output: cancelled before any next phase or model handoff."""
        form = self.form()
        request = console_start.register_start(self.paths, form, 'stop-scan')
        clock = [0.0]
        def scan(*args, **kwargs):
            """Input: scan callback. Output: interruption after durable Stop and bounded poll interval."""
            kwargs['check_cancelled']()
            console_start.cancel_start(self.paths.runs_root)
            clock[0] += console_start.PREPARATION_CHECK_INTERVAL_SECONDS
            kwargs['check_cancelled']()
            raise AssertionError('Stop was ignored')
        with patch.object(console_start, 'time', SimpleNamespace(monotonic=lambda: clock[0])), \
             patch('wqb.multiplier_supervision.prepare_multiplier_fields_supervised', side_effect=scan), \
             patch.object(console_start, '_execute_preplanned_start') as coordinate:
            result = console_start.execute_start(self.paths, form, request['request_id'])
        self.assertEqual(result['status'], 'cancelled')
        coordinate.assert_not_called()

    def test_catalog_scale_checks_do_not_discover_old_runs_for_each_field(self):
        """Input:153513 scan callbacks. Output: bounded full-intent checks, preserved final validation."""
        form = self.form()
        request = console_start.register_start(self.paths, form, 'large-scan-job')
        calls = []
        def intent(root):
            """Input: runs Path. Output: original authority, rejecting per-row full discovery."""
            calls.append(root)
            if len(calls) > 8:
                raise AssertionError('full source discovery repeated per field')
            return request['source_intent']
        def scan(*args, **kwargs):
            """Input: preparation callbacks. Output: successful scripted153k-row scan."""
            for _ in range(153513):
                kwargs['check_cancelled']()
            return dict(status='completed', reused=True, requests_used=0)
        with patch.object(console_start, '_source_intent', side_effect=intent), \
             patch.object(console_start, 'time', SimpleNamespace(monotonic=lambda: 0), create=True), \
             patch('wqb.multiplier_supervision.prepare_multiplier_fields_supervised', side_effect=scan), \
             patch.object(console_start, '_execute_preplanned_start', return_value=dict(passed=True)), \
             patch.object(console_start, '_notify_blocked_request', side_effect=lambda paths, row: row):
            result = console_start.execute_start(self.paths, form, request['request_id'])
        self.assertTrue(result.get('passed'), result)
        self.assertLessEqual(len(calls), 8)
        self.assertGreaterEqual(len(calls), 2)

    def test_final_authority_check_cannot_be_skipped_by_scan_throttle(self):
        """Input: changed source just before handoff. Output: cancellation despite unchanged clock."""
        form = self.form()
        request = console_start.register_start(self.paths, form, 'source-change-job')
        current = dict(request['source_intent'])
        def prepare(*args, **kwargs):
            """Input: callbacks. Output: result after a concurrent authority change."""
            current['request_revision'] = 'changed'
            return dict(status='completed')
        with patch.object(console_start, '_source_intent', side_effect=lambda root: dict(current)), \
             patch('wqb.multiplier_supervision.prepare_multiplier_fields_supervised', side_effect=prepare), \
             patch.object(console_start, '_execute_preplanned_start') as coordinate:
            result = console_start.execute_start(self.paths, form, request['request_id'])
        self.assertEqual(result['status'], 'cancelled')
        coordinate.assert_not_called()

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

    def test_outer_timeout_finalizes_preparation_and_retains_captured_count(self):
        """Input: outer worker timeout after capture. Output: terminal nested status with preserved65-field evidence."""
        from wqb.multiplier_preparation import _save
        from wqb import console_server
        form = self.form()
        request = console_start.register_start(self.paths, form, 'timeout-job')
        directory = self.paths.runs_root/'start_preflight/multiplier'/request['request_id']
        directory.mkdir(parents=True)
        _save(directory/'state.json', dict(scope=request['selection']['scope'],
            knowledge_root=str(self.paths.knowledge_root), requests_used=6,
            capture=dict(field_count=65)))
        completed = SimpleNamespace(job_id='timeout-job', status='timed_out', exit_code=1,
            stderr_path='offline-stderr', error='timed out after 3600s')
        with patch.object(console_server, '_record_async_console_job_context'), \
             patch.object(console_start, '_notify_blocked_request', side_effect=lambda paths, row: row):
            console_server._complete_start_job(self.paths, completed)
        saved = console_start.read_start_request(self.paths.runs_root)
        self.assertEqual(saved['multiplier_preparation']['status'], 'blocked')
        self.assertEqual(saved['multiplier_preparation']['field_count'], 65)
        self.assertEqual(saved['multiplier_preparation']['requests_used'], 6)


if __name__ == '__main__':
    unittest.main()
