"""Fictional, offline result-window evidence and bounded GET regressions."""
from copy import deepcopy
import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from wqb.cli import simulation_identity_hash
from wqb.measurement_window import (make_window_evidence, verified_window_period,
                                    fetch_window_evidence)
from wqb.runtime_control import CONTROL_ENV, RuntimePaused


def alpha():
    """Input: none. Output: fictional Alpha detail dict with exact submitted settings."""
    return {'id': 'fixture1', 'regular': {'code': 'rank(x)'},
            'settings': {'region': 'USA', 'delay': 1, 'universe': 'TOP3000'},
            'is': {'startDate': '2020-01-01', 'sharpe': 1.5},
            'os': {'startDate': '2021-01-01'}}


def pnl():
    """Input: none. Output: fictional PNL dict, including an explicitly excluded OS row."""
    return {'schema': {'name': 'pnl', 'properties': [
        {'name': 'date', 'type': 'date'}, {'name': 'pnl', 'type': 'amount'}]},
        'records': [['2020-01-02', 1], ['2020-12-30', 2], ['2021-01-04', 3]]}


def measured(detail, evidence):
    """Input: Alpha/receipt dicts. Output: row dict with independent copied metrics."""
    return {'alpha_id': detail['id'], 'expression': detail['regular']['code'],
            'settings': deepcopy(detail['settings']),
            'metrics': {**deepcopy(detail['is']), 'measurement_window_evidence': evidence}}


class Response:
    def __init__(self, payload=None, headers=None, status=200, content=None):
        """Input: fake payload/headers/status/body. Output: queued offline response object."""
        self.payload, self.headers, self.status_code = payload, headers or {}, status
        self.content = content if content is not None else (json.dumps(payload).encode() if payload is not None else b'')

    def raise_for_status(self):
        """Input: none. Output: None or ordinary HTTPError for fake error responses."""
        if self.status_code >= 400:
            raise requests.HTTPError('fixture HTTP error', response=self)

    def json(self):
        """Input: none. Output: detached fake JSON, or ValueError for an empty body."""
        if not self.content:
            raise ValueError('empty')
        return deepcopy(self.payload)


class Client:
    def __init__(self, responses, root=None):
        """Input: response list/optional Path. Output: fake GET-only client and call ledger."""
        self.responses, self.calls, self.timeout_seconds = list(responses), [], 5
        self.measurement_window_cache_root = root

    def request(self, method, path, **kwargs):
        """Input: method/path/kwargs. Output: queued fake response; no network exists."""
        self.calls.append((method, path, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class MeasurementWindowTests(unittest.TestCase):
    def setUp(self):
        """Input: none. Output: isolated managed-run environment and fictional fixtures."""
        self.env = patch.dict(os.environ, {CONTROL_ENV: ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.detail, self.series = alpha(), pnl()

    def test_receipt_uses_is_start_and_last_is_observation_without_mutation(self):
        """Input: fixtures. Output: evidence bound to IS dates, raw hashes and exact identity."""
        before = deepcopy((self.detail, self.series))
        receipt = make_window_evidence('fixture1', self.detail, self.series)
        self.assertEqual(receipt['period'], {'start': '2020-01-01', 'end': '2020-12-30'})
        self.assertEqual(receipt['first_observation'], '2020-01-02')
        self.assertEqual(receipt['last_observation'], '2020-12-30')
        self.assertEqual(receipt['observations'], 2)
        self.assertEqual(receipt['simulation_identity'], simulation_identity_hash('rank(x)', self.detail['settings']))
        self.assertEqual((self.detail, self.series), before)
        self.assertNotIn('endDate', self.detail['is'])
        self.assertNotIn('reported', receipt['method'])
        self.assertEqual(verified_window_period(measured(self.detail, receipt)), receipt['period'])

    def test_no_os_cutoff_retains_all_observations_and_date_column_can_move(self):
        """Input: no OS and reordered schema. Output: full PNL bounds from named date column."""
        self.detail['os'] = None
        self.series['schema']['properties'].reverse()
        self.series['records'] = [list(reversed(row)) for row in self.series['records']]
        receipt = make_window_evidence('fixture1', self.detail, self.series)
        self.assertEqual(receipt['period']['end'], '2021-01-04')
        self.assertEqual(receipt['observations'], 3)

    def test_rejects_malformed_conflicting_and_unordered_dates(self):
        """Input: malformed recordsets/details. Output: explicit ValueError, never guessed periods."""
        cases = []
        for records in ([], [['2020-1-02', 1]], [['2020-02-30', 1]],
                        [['2020-01-02', 1], ['2020-01-02', 2]],
                        [['2020-01-03', 1], ['2020-01-02', 2]],
                        [['2019-12-31', 1]], [['2021-01-04', 1]],
                        [['2020-01-02']], [['2020-01-02', float('nan')]],
                        [['2020-01-02', 'not-a-number']]):
            series = pnl()
            series['records'] = records
            cases.append((alpha(), series))
        for change in ({'name': 'other'}, {'properties': []},
                       {'properties': [{'name': 'date', 'type': 'date'}, {'name': 'date', 'type': 'date'}]},
                       {'properties': [{'name': 'date', 'type': 'string'}, {'name': 'pnl', 'type': 'amount'}]}):
            series = pnl()
            series['schema'].update(change)
            cases.append((alpha(), series))
        for field, value in (('startDate', '2020-1-01'), ('endDate', '2020-12-31')):
            detail = alpha()
            detail['is'][field] = value
            cases.append((detail, pnl()))
        detail = alpha()
        detail['os']['startDate'] = '2019-01-01'
        cases.append((detail, pnl()))
        detail = alpha()
        detail['id'] = 'different'
        cases.append((detail, pnl()))
        for detail, series in cases:
            with self.subTest(detail=detail, series=series), self.assertRaises(ValueError):
                make_window_evidence('fixture1', detail, series)

    def test_verified_period_rejects_tampering_identity_or_metric_conflicts(self):
        """Input: modified rows/receipts. Output: None on any unrelated or inconsistent evidence."""
        receipt = make_window_evidence('fixture1', self.detail, self.series)
        row = measured(self.detail, receipt)
        cases = [None, {}, {'metrics': {'startDate': '2020-01-01'}, 'measurement_period': receipt['period']}]
        for key, value in (('alpha_id', 'other'), ('expression', 'rank(y)'), ('settings', {'delay': 2})):
            bad = deepcopy(row)
            bad[key] = value
            cases.append(bad)
        for key, value in (('startDate', '2020-01-02'), ('endDate', '2020-12-31')):
            bad = deepcopy(row)
            bad['metrics'][key] = value
            cases.append(bad)
        for key, value in (('observations', 0), ('method', 'configured_period'),
                           ('alpha_sha256', 'bad'), ('period', {'start': '2020-01-01', 'end': '2020-12-31'})):
            bad = deepcopy(row)
            bad['metrics']['measurement_window_evidence'][key] = value
            cases.append(bad)
        for bad in cases:
            with self.subTest(row=bad):
                self.assertIsNone(verified_window_period(bad))
        row['metrics']['endDate'] = '2020-12-30'
        self.assertEqual(verified_window_period(row), receipt['period'])

    def test_fetch_is_bounded_get_only_and_cache_hit_verifies_raw(self):
        """Input: fake ready response and isolated cache. Output: one GET, then authenticated zero-GET reuse."""
        with tempfile.TemporaryDirectory() as directory:
            client = Client([Response(self.series)], Path(directory))
            receipt = fetch_window_evidence(client, 'fixture1', self.detail)
            self.assertEqual(len(client.calls), 1)
            method, path, kwargs = client.calls[0]
            self.assertEqual((method, path), ('GET', '/alphas/fixture1/recordsets/pnl'))
            self.assertFalse(kwargs['respect_retry_after'])
            self.assertEqual(kwargs['max_attempts'], 1)
            self.assertTrue(0 < kwargs['request_timeout_seconds'] <= 5)
            self.assertEqual(fetch_window_evidence(client, 'fixture1', self.detail), receipt)
            self.assertEqual(len(client.calls), 1)
            paths = list(Path(directory).glob('*.json'))
            self.assertEqual(len(paths), 1)
            cache = json.loads(paths[0].read_text(encoding='utf-8'))
            self.assertEqual(cache['alpha_detail'], self.detail)
            self.assertEqual(cache['pnl_recordset'], self.series)
            cache['pnl_recordset']['records'][0][1] = 99
            paths[0].write_text(json.dumps(cache), encoding='utf-8')
            with self.assertRaises(requests.RequestException):
                fetch_window_evidence(client, 'fixture1', self.detail)
            self.assertEqual(len(client.calls), 1)

    def test_pending_empty_200_respects_retry_after(self):
        """Input: empty pending responses and a ready payload. Output: at most three logical GETs."""
        client = Client([Response(headers={'Retry-After': '0.1'}), Response(headers={'Retry-After': '0'}), Response(self.series)])
        with patch('wqb.measurement_window.cooperative_sleep') as sleep:
            receipt = fetch_window_evidence(client, 'fixture1', self.detail)
        self.assertEqual(receipt['observations'], 2)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(sleep.call_args_list[0].args, (0.1,))

    def test_pending_exhaustion_time_bytes_and_stop_fail_closed(self):
        """Input: bounded failures and Stop. Output: recoverable network errors or preserved RuntimePaused."""
        for responses in ([Response() for _ in range(3)],
                          [requests.Timeout('fixture') for _ in range(3)],
                          [Response(headers={'Retry-After': '99'})],
                          [Response(self.series, content=b'x' * 2_000_001)],
                          [Response({'schema': {}, 'records': []})]):
            client = Client(responses)
            with patch('wqb.measurement_window.cooperative_sleep'), self.assertRaises(requests.RequestException):
                fetch_window_evidence(client, 'fixture1', self.detail)
            self.assertLessEqual(len(client.calls), 3)
        client = Client([Response(self.series)])
        with patch('wqb.measurement_window.check_submission_allowed', side_effect=RuntimePaused('stop')):
            with self.assertRaises(RuntimePaused):
                fetch_window_evidence(client, 'fixture1', self.detail)
        self.assertEqual(client.calls, [])

    def test_changed_whole_alpha_is_not_a_cache_hit(self):
        """Input: same identity but changed raw Alpha metadata. Output: fresh raw-bound receipt."""
        with tempfile.TemporaryDirectory() as directory:
            client = Client([Response(self.series), Response(self.series)], Path(directory))
            first = fetch_window_evidence(client, 'fixture1', self.detail)
            self.detail['name'] = 'changed raw'
            second = fetch_window_evidence(client, 'fixture1', self.detail)
            self.assertNotEqual(first['alpha_sha256'], second['alpha_sha256'])
            self.assertEqual(len(client.calls), 2)

    def test_rehashed_impossible_receipts_are_still_rejected(self):
        """Input: valid hash over impossible compact metadata. Output: None, not syntax-only acceptance."""
        receipt = make_window_evidence('fixture1', self.detail, self.series)
        for key, value in (('observations', True), ('observations', 99999),
                           ('first_observation', '2021-01-01'), ('os_start', '2020-12-30'),
                           ('schema_version', True), ('last_observation', '2020-12-29')):
            bad = deepcopy(receipt)
            bad[key] = value
            unsigned = {name: item for name, item in bad.items() if name != 'evidence_sha256'}
            bad['evidence_sha256'] = hashlib.sha256(json.dumps(unsigned, sort_keys=True,
                ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
            self.assertIsNone(verified_window_period(measured(self.detail, bad)))

    def test_reported_extras_preserved_without_changing_submission_identity(self):
        """Input: reported defaults beyond submission. Output: accepted period and unchanged original identity."""
        submitted = deepcopy(self.detail['settings'])
        self.detail['settings'].update(maxTrade='OFF', maxPosition='OFF', startDate='2020-01-01',
                                       endDate='2020-12-31', simulationMode='FULL')
        receipt = make_window_evidence('fixture1', self.detail, self.series)
        row = measured(self.detail, receipt)
        row['settings'] = submitted
        identity = simulation_identity_hash(row['expression'], submitted)
        row.update(expression_hash=identity, simulation_identity=identity)
        before = deepcopy(row)
        self.assertEqual(verified_window_period(row), receipt['period'])
        self.assertEqual(row, before)
        self.assertEqual(receipt['reported_settings'], self.detail['settings'])
        self.assertEqual(receipt['reported_expression'], self.detail['regular']['code'])
        self.assertNotEqual(receipt['simulation_identity'], identity)
        self.detail['settings']['maxTrade'] = 'ON'
        self.assertEqual(receipt['reported_settings']['maxTrade'], 'OFF')

    def test_submitted_settings_subset_requires_strict_json_values_and_scope(self):
        """Input: changed submitted values/types or missing scope. Output: rejection despite self-consistent row hash."""
        self.detail['settings'].update(decay=2, truncation=0.08,
                                       options={'flags': [True, 1, 1.0]})
        receipt = make_window_evidence('fixture1', self.detail, self.series)
        for key, value in (('delay', True), ('delay', 1.0), ('decay', 3),
                           ('truncation', '0.08'), ('options', {'flags': [1, 1, 1.0]}),
                           ('newUnreportedKey', 'value')):
            row = measured(self.detail, receipt)
            row['settings'][key] = value
            row['expression_hash'] = simulation_identity_hash(row['expression'], row['settings'])
            with self.subTest(key=key, value=value):
                self.assertIsNone(verified_window_period(row))
        for settings in ({}, {'decay': 2}, {'region': '', 'universe': 'TOP3000', 'delay': 1}):
            row = measured(self.detail, receipt)
            row['settings'] = settings
            self.assertIsNone(verified_window_period(row))

    def test_bogus_reported_identity_rejected_even_with_rehashed_receipt(self):
        """Input: internally rehashed receipt but mismatching reported identity. Output: rejection."""
        receipt = make_window_evidence('fixture1', self.detail, self.series)
        receipt['simulation_identity'] = '0' * 64
        unsigned = {key: value for key, value in receipt.items() if key != 'evidence_sha256'}
        receipt['evidence_sha256'] = hashlib.sha256(json.dumps(unsigned, sort_keys=True,
            ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
        self.assertIsNone(verified_window_period(measured(self.detail, receipt)))

    def test_original_row_identity_fields_are_not_replaced_by_reported_hash(self):
        """Input: original identity or unrelated ID/expression. Output: original accepted, conflicts rejected."""
        submitted = deepcopy(self.detail['settings'])
        self.detail['settings']['maxTrade'] = 'OFF'
        receipt = make_window_evidence('fixture1', self.detail, self.series)
        row = measured(self.detail, receipt)
        row['settings'] = submitted
        identity = simulation_identity_hash(row['expression'], submitted)
        row.update(expression_hash=identity, simulation_identity=identity)
        self.assertEqual(verified_window_period(row), receipt['period'])
        for key, value in (('expression_hash', receipt['simulation_identity']),
                           ('simulation_identity', receipt['simulation_identity']),
                           ('alpha_id', 'another'), ('expression', 'rank(y)')):
            bad = deepcopy(row)
            bad[key] = value
            self.assertIsNone(verified_window_period(bad))

    def test_deadline_exhaustion_never_writes_cache_or_replays_get(self):
        """Input: response arriving after total deadline. Output: recoverable failure with no cache."""
        with tempfile.TemporaryDirectory() as directory:
            client = Client([Response(self.series)], Path(directory))
            with patch('wqb.measurement_window.time.monotonic', side_effect=[0, 0, 13]):
                with self.assertRaises(requests.RequestException) as failure:
                    fetch_window_evidence(client, 'fixture1', self.detail)
            self.assertEqual(failure.exception.alpha_id, 'fixture1')
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_retry_after_http_date_is_honored(self):
        """Input: HTTP-date pacing beyond total budget. Output: pending without sleeping or replaying."""
        client = Client([Response(headers={'Retry-After': 'Wed, 01 Jan 2098 00:00:00 GMT'})])
        with patch('wqb.measurement_window.cooperative_sleep') as sleep:
            with self.assertRaises(requests.RequestException):
                fetch_window_evidence(client, 'fixture1', self.detail)
        sleep.assert_not_called()
        self.assertEqual(len(client.calls), 1)

    def test_owner_root_precedes_client_cache_and_metrics_root_fallback(self):
        """Input: isolated run/cache roots. Output: owner-scoped cache; fallback stays under metrics root."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = Client([Response(self.series)], root / 'explicit')
            with patch.dict(os.environ, {CONTROL_ENV: str(root / 'owner')}), patch(
                    'wqb.measurement_window.check_submission_allowed'):
                fetch_window_evidence(client, 'fixture1', self.detail)
            self.assertTrue((root / 'owner/runtime/measurement_windows/fixture1.json').is_file())
            self.assertFalse((root / 'explicit').exists())
            client = Client([Response(self.series)])
            client.metrics_run_dir = root / 'metrics'
            fetch_window_evidence(client, 'fixture1', self.detail)
            self.assertTrue((root / 'metrics/runtime/measurement_windows/fixture1.json').is_file())

    def test_linked_root_is_rejected_before_any_get(self):
        """Input: linked cache root. Output: fail-closed RequestException without dispatch."""
        client = Client([Response(self.series)], Path('fictional-cache'))
        with patch('wqb.measurement_window.Path.is_symlink', return_value=True):
            with self.assertRaises(requests.RequestException):
                fetch_window_evidence(client, 'fixture1', self.detail)
        self.assertEqual(client.calls, [])

    def test_missing_primary_pnl_is_not_an_observed_value(self):
        """Input: dated null PNL rows. Output: reject absent primary measured observations."""
        self.series['records'] = [['2020-01-02', None]]
        with self.assertRaises(ValueError):
            make_window_evidence('fixture1', self.detail, self.series)


if __name__ == '__main__':
    unittest.main()
