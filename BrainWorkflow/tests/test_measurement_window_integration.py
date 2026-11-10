"""Window-evidence adapters retain existing transport and research authority."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
from unittest.mock import Mock, patch
import unittest

import requests

from wqb.client import WQBClient
from wqb.candidate_evidence import load_candidate_evidence, save_candidate_evidence
from wqb.checker import fetch_check_summary
from wqb.cli import simulation_identity_hash
from wqb.measurement_window import EVIDENCE_KEY, make_window_evidence, verified_window_period
from wqb.research_seed_stage import normalize_measured_row
from wqb.seed_policy import select_seeds


ALPHA_ID = 'window-alpha'
PERIOD = {'start': '2020-01-01', 'end': '2024-12-30'}


def window_fixture(*, passing=False, reported_end=False):
    """Input: baseline-pass/reported-end bools. Output: actual detail, PNL and submitted checked row dicts."""
    settings = dict(region='USA', delay=1, universe='TOP3000', decay=4)
    metrics = dict(startDate=PERIOD['start'], sharpe=1.5, fitness=1.1 if passing else .8,
                   returns=.1, turnover=.2, checks=[dict(name='LOW_SHARPE', result='PASS'),
                   dict(name='LOW_FITNESS', result='PASS' if passing else 'FAIL')])
    if reported_end:
        metrics['endDate'] = PERIOD['end']
    detail = dict(id=ALPHA_ID, status='UNSUBMITTED', regular=dict(code='rank(x)'),
                  settings=deepcopy(settings), **{'is': metrics})
    pnl = dict(schema=dict(name='pnl', properties=[dict(name='date', type='date'),
                                                 dict(name='pnl', type='double')]),
               records=[['2020-01-02', 1.], [PERIOD['end'], 2.]])
    identity = simulation_identity_hash('rank(x)', settings)
    row = dict(alpha_id=ALPHA_ID, expression='rank(x)', settings=settings,
               expression_hash=identity, status='CHECKED', hard_pass=passing,
               failed=[] if passing else ['LOW_FITNESS'], pending=[], metrics=deepcopy(metrics))
    return detail, pnl, row


def offline_window_client(detail, pnl, required=True):
    """Input: raw detail/PNL dicts and opt-in value. Output: fake transport client; no network or checks by default."""
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(pnl).encode('utf-8')
    return SimpleNamespace(measurement_window_required=required, timeout_seconds=2,
                           get_json=Mock(return_value=detail), request=Mock(return_value=response))


class BoundedWindowReadTests(unittest.TestCase):
    def client(self, status=200):
        """Input: fake response status int. Output: authenticated client/session pair, never a socket."""
        session = Mock()
        session.headers = {}
        response = requests.Response()
        response.status_code = status
        response._content = b'{}'
        session.request.return_value = response
        client = WQBClient(session=session, timeout_seconds=30, max_retries=4)
        client.authenticated = True
        return client, session

    def test_read_can_reduce_existing_retry_and_timeout_limits(self):
        client, session = self.client(503)
        with patch('wqb.client.cooperative_sleep') as sleep:
            client.request('GET', '/fixture', max_attempts=1, request_timeout_seconds=2)
        session.request.assert_called_once()
        self.assertEqual(session.request.call_args.kwargs['timeout'], 2)
        self.assertNotIn('max_attempts', session.request.call_args.kwargs)
        self.assertNotIn('request_timeout_seconds', session.request.call_args.kwargs)
        sleep.assert_not_called()

    def test_request_limits_cannot_widen_authority_or_override_post(self):
        for options in ({'max_attempts': 0}, {'max_attempts': True}, {'max_attempts': 6},
                        {'request_timeout_seconds': 31}, {'request_timeout_seconds': 0},
                        {'request_timeout_seconds': float('nan')}):
            client, session = self.client()
            with self.subTest(options=options), self.assertRaises(ValueError):
                client.request('GET', '/fixture', **options)
            session.request.assert_not_called()
        client, session = self.client()
        with self.assertRaises(ValueError):
            client.request('POST', '/simulations', max_attempts=1)
        session.request.assert_not_called()


class MeasurementWindowIntegrationTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated transport and owner environment for offline integration."""
        network = patch('socket.socket.connect', side_effect=AssertionError('No live network allowed'))
        network.start()
        self.addCleanup(network.stop)
        from wqb.runtime_control import CONTROL_ENV
        environment = patch.dict('os.environ', {CONTROL_ENV: ''})
        environment.start()
        self.addCleanup(environment.stop)

    def test_baseline_failure_gets_actual_window_without_mutating_reported_metrics(self):
        """Input: new-mode Alpha missing endDate. Output: real proof, no correlation GET or raw mutation."""
        detail, pnl, row = window_fixture()
        original = deepcopy(detail)
        client = offline_window_client(detail, pnl)
        summary = fetch_check_summary(client, ALPHA_ID)
        self.assertIn(EVIDENCE_KEY, summary.metrics)
        row['metrics'] = summary.metrics
        normalized = normalize_measured_row(row, 'lane')
        self.assertEqual(normalized['test_period'], PERIOD)
        self.assertTrue(select_seeds([normalized], {})['selected'])
        self.assertFalse(summary.hard_pass)
        self.assertNotIn('endDate', summary.metrics)
        self.assertEqual(detail, original)
        client.get_json.assert_called_once_with('/alphas/' + ALPHA_ID)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(client.request.call_args.args, ('GET', '/alphas/' + ALPHA_ID + '/recordsets/pnl'))

    def test_reported_dates_and_legacy_mode_never_fetch_pnl(self):
        """Input: full reported period or non-True opt-in. Output: unchanged dates and no PNL request."""
        for required, reported_end in ((True, True), (False, False), (None, False), (1, False), ('true', False)):
            with self.subTest(required=required, reported_end=reported_end):
                detail, pnl, _ = window_fixture(reported_end=reported_end)
                client = offline_window_client(detail, pnl, required)
                summary = fetch_check_summary(client, ALPHA_ID)
                self.assertNotIn(EVIDENCE_KEY, summary.metrics)
                client.request.assert_not_called()

    def test_full_checks_preserve_raw_candidate_cache_and_only_enrich_on_reuse(self):
        """Input: actual full-check evidence. Output: unchanged check cache, proof on reuse, no repeat SELF/PROD."""
        detail, pnl, _ = window_fixture(passing=True)
        full = {'is': {'checks': [dict(name=name, result='PASS')
                                 for name in ('SELF_CORRELATION', 'PROD_CORRELATION')]}}
        with tempfile.TemporaryDirectory() as directory:
            client = offline_window_client(detail, pnl)
            client.knowledge_root = Path(directory)
            client.measurement_window_cache_root = Path(directory) / 'windows'
            client.get_json.side_effect = [detail, full]
            summary = fetch_check_summary(client, ALPHA_ID)
            self.assertTrue(summary.hard_pass)
            self.assertIn(EVIDENCE_KEY, summary.metrics)
            files = list((Path(directory) / 'machine/candidate_evidence').glob('*.json'))
            self.assertEqual(len(files), 1)
            before = files[0].read_bytes()
            record = json.loads(before)
            self.assertEqual(record['alpha_detail'], detail)
            self.assertNotIn(EVIDENCE_KEY, record['alpha_detail']['is'])
            client.get_json.reset_mock(side_effect=True)
            client.get_json.return_value = detail
            client.request.reset_mock()
            reused = fetch_check_summary(client, ALPHA_ID)
            self.assertTrue(reused.hard_pass)
            self.assertEqual(reused.metrics['candidate_evidence']['evidence_source'], 'cached')
            self.assertIn(EVIDENCE_KEY, reused.metrics)
            client.get_json.assert_called_once_with('/alphas/' + ALPHA_ID)
            client.request.assert_not_called()
            self.assertEqual(files[0].read_bytes(), before)
            self.assertIsNotNone(load_candidate_evidence(client, ALPHA_ID))

    def test_cached_legacy_or_reported_period_never_fetches_detail_or_pnl(self):
        """Input: reusable check evidence not needing a window. Output: cache hit without any platform GET."""
        for required, reported_end in ((False, False), (True, True)):
            with self.subTest(required=required), tempfile.TemporaryDirectory() as directory:
                detail, pnl, _ = window_fixture(passing=True, reported_end=reported_end)
                client = offline_window_client(detail, pnl, required)
                client.knowledge_root = Path(directory)
                full = {'is': {'checks': [dict(name=name, result='PASS')
                                         for name in ('SELF_CORRELATION', 'PROD_CORRELATION')]}}
                self.assertEqual(save_candidate_evidence(client, ALPHA_ID, detail, full)['persistence_status'],
                                 'persisted')
                self.assertTrue(fetch_check_summary(client, ALPHA_ID).hard_pass)
                client.get_json.assert_not_called()
                client.request.assert_not_called()

    def test_pending_proof_propagates_existing_alpha_without_correlation_or_cache_loss(self):
        """Input: bounded pending PNL, with/without check cache. Output: recoverable exception with original Alpha ID."""
        for cached in (False, True):
            with self.subTest(cached=cached), tempfile.TemporaryDirectory() as directory:
                detail, pnl, _ = window_fixture(passing=cached)
                client = offline_window_client(detail, pnl)
                client.knowledge_root = Path(directory)
                if cached:
                    full = {'is': {'checks': [dict(name=name, result='PASS')
                                             for name in ('SELF_CORRELATION', 'PROD_CORRELATION')]}}
                    save_candidate_evidence(client, ALPHA_ID, detail, full)
                client.request.return_value._content = b''
                client.request.return_value.headers['Retry-After'] = '30'
                with self.assertRaises(requests.RequestException) as caught:
                    fetch_check_summary(client, ALPHA_ID)
                self.assertEqual(caught.exception.alpha_id, ALPHA_ID)
                self.assertTrue(caught.exception.measurement_window_pending)
                client.get_json.assert_called_once_with('/alphas/' + ALPHA_ID)
                self.assertEqual(client.request.call_count, 1)
                if cached:
                    self.assertIsNotNone(load_candidate_evidence(client, ALPHA_ID))

    def test_verified_window_requires_exact_declared_period_and_preserves_input(self):
        """Input: raw missing end and actual proof. Output: only exact reconciled periods become eligible Seeds."""
        detail, pnl, row = window_fixture()
        row['metrics'][EVIDENCE_KEY] = make_window_evidence(ALPHA_ID, detail, pnl)
        original = deepcopy(row)
        measured = normalize_measured_row(row, 'lane')
        self.assertEqual(measured['test_period'], PERIOD)
        self.assertEqual(verified_window_period(measured), PERIOD)
        self.assertTrue(select_seeds([measured], {})['selected'])
        self.assertEqual(row, original)
        for declaration in (dict(start=PERIOD['start'], end='2025-01-01'), '2020-2024'):
            with self.subTest(declaration=declaration):
                conflicting = dict(measured, test_period=declaration)
                self.assertFalse(select_seeds([conflicting], {})['selected'])

    def test_missing_or_forged_window_cannot_turn_plan_dates_into_measurements(self):
        """Input: missing, edited or identity-conflicting proof. Output: no derived period or accepted Seed."""
        detail, pnl, original = window_fixture()
        proof = make_window_evidence(ALPHA_ID, detail, pnl)
        for change in ('absent', 'period', 'alpha', 'settings', 'expression', 'raw_start', 'raw_end'):
            with self.subTest(change=change):
                row = deepcopy(original)
                if change != 'absent':
                    row['metrics'][EVIDENCE_KEY] = deepcopy(proof)
                if change == 'period':
                    row['metrics'][EVIDENCE_KEY]['period']['end'] = '2025-01-01'
                elif change == 'alpha':
                    row['alpha_id'] = 'other-alpha'
                elif change in ('settings', 'expression'):
                    if change == 'settings':
                        row['settings']['decay'] = 8
                    else:
                        row['expression'] = 'rank(y)'
                    row['expression_hash'] = simulation_identity_hash(row['expression'], row['settings'])
                elif change == 'raw_start':
                    row['metrics']['startDate'] = '2020-01-02'
                elif change == 'raw_end':
                    row['metrics']['endDate'] = '2025-01-01'
                normalized = normalize_measured_row(row, 'lane')
                self.assertNotIn('test_period', normalized)
                normalized['test_period'] = dict(PERIOD)
                self.assertFalse(select_seeds([normalized], {})['selected'])

    def test_reported_extra_settings_are_evidence_not_submitted_identity(self):
        """Input: reported platform defaults beyond exact POST subset. Output: accepted proof with original row hash."""
        detail, pnl, row = window_fixture()
        detail['settings'].update(maxTrade='OFF', maxPosition=.1, startDate='2020-01-01',
                                  endDate='2025-01-01', simulationMode='REGULAR')
        original_hash = row['expression_hash']
        original_detail = deepcopy(detail)
        client = offline_window_client(detail, pnl)
        row['metrics'] = fetch_check_summary(client, ALPHA_ID).metrics
        self.assertEqual(detail, original_detail)
        self.assertEqual(row['metrics'][EVIDENCE_KEY]['reported_settings'], detail['settings'])
        self.assertEqual(row['metrics'][EVIDENCE_KEY]['reported_expression'], row['expression'])
        self.assertEqual(row['metrics'][EVIDENCE_KEY]['simulation_identity'],
                         simulation_identity_hash(row['expression'], detail['settings']))
        normalized = normalize_measured_row(row, 'lane')
        self.assertEqual(normalized.get('test_period'), PERIOD)
        self.assertEqual(normalized['expression_hash'], original_hash)
        self.assertEqual(normalized['simulation_identity'], original_hash)
        self.assertNotEqual(simulation_identity_hash(row['expression'], detail['settings']), original_hash)
        self.assertTrue(select_seeds([normalized], {})['selected'])
        for conflicting_value in (8, 4.0, '4', True):
            with self.subTest(conflicting_value=conflicting_value):
                conflicting = deepcopy(row)
                conflicting['settings']['decay'] = conflicting_value
                conflicting['expression_hash'] = simulation_identity_hash(conflicting['expression'], conflicting['settings'])
                rejected = normalize_measured_row(conflicting, 'lane')
                self.assertNotIn('test_period', rejected)
                rejected['test_period'] = dict(PERIOD)
                self.assertFalse(select_seeds([rejected], {})['selected'])
