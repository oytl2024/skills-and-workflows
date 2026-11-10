"""Offline preparation contracts; all transport responses are explicit fixture bytes."""
import importlib
import json
import os
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import requests
from requests.adapters import HTTPAdapter

from wqb.client import WQBClient
from wqb.data_field_capture import capture_platform_data_fields
from wqb.data_ledger_compile import compile_data_ledger_from_raw


SCOPE = dict(region='USA', delay=1, universe='TOP3000')
OPTIONS = {'actions': {'POST': {'settings': {'children': {
    'region': {'choices': ['USA']}, 'delay': {'choices': [1]},
    'universe': {'choices': ['TOP3000']}}}}}}


class FixtureAdapter(HTTPAdapter):
    def __init__(self, owner):
        """Input: TestCase owner. Output: adapter; never connect to a socket."""
        super().__init__(max_retries=0)
        self.owner = owner

    def send(self, request, **kwargs):
        """Input: prepared request/kwargs. Output: Response from named local fixtures."""
        owner = self.owner
        owner.calls.append((request.method, request.url, kwargs))
        path = requests.utils.urlparse(request.url).path
        if owner.on_request:
            owner.on_request(path)
        payload = {'/authentication': {}, '/simulations': OPTIONS,
                   '/operators': [], '/data-sets': {'results': [{'id': 'd'}], 'count': 1},
                   '/data-fields': {'results': [{'id': 'f', 'type': 'MATRIX', 'coverage': 0.8}], 'count': 1}}[path]
        response = requests.Response()
        response.status_code = owner.http_status if path == '/data-fields' else 200
        response._content = json.dumps(payload).encode()
        response.headers = {}
        response.url = request.url
        response.request = request
        return response


class FixtureClient(WQBClient):
    def authenticate(self):
        """Input: none. Output: none; fixture auth exercises real dispatch without credentials."""
        response = self._dispatch('POST', 'https://api.worldquantbrain.com/authentication',
                                  authentication=True, timeout=self.timeout_seconds)
        response.raise_for_status()
        self.authenticated = True


class MultiplierPreparationTests(unittest.TestCase):
    def test_owned_network_phase_never_publishes_shared_resources(self):
        """Input: deferred preparation. Output: staged capture only, no shared index/catalog/compiler changes."""
        self.catalog['stale'] = True
        with patch.object(self.module, 'compile_data_ledger_from_raw', side_effect=AssertionError('shared compile in child')), \
             patch('wqb.data_field_capture.upsert_source_index_rows', side_effect=AssertionError('shared index in child')):
            result = self.prepare(defer_shared_publication=True)
        self.assertEqual(result['status'], 'staged')
        self.assertFalse(self.published)
        self.assertFalse((self.root / 'machine/data_ledger.jsonl').exists())
        self.assertTrue((self.job / 'scope_options.json').exists())
        self.assertFalse((self.root / '.data_capture_compile.lock.guard').exists())

    def test_dataset_pagination_receives_sampling_bound(self):
        """Input: bounded preparation fixture. Output: sampler constrains pagination before fetching pages."""
        from wqb import data_field_capture
        original = data_field_capture.fetch_data_sets_with_metadata
        with patch.object(data_field_capture, 'fetch_data_sets_with_metadata', wraps=original) as fetch:
            self.prepare()
        self.assertEqual(fetch.call_args.kwargs.get('max_records'), 2)

    def setUp(self):
        """Input: none. Output: isolated vault/job and explicitly fake catalog module."""
        self.assertIsNotNone(importlib.util.find_spec('wqb.multiplier_preparation'),
                             'Task2 implementation is missing')
        self.module = importlib.import_module('wqb.multiplier_preparation')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'knowledge'
        self.job = Path(self.temp.name) / 'job'
        self.calls, self.updates = [], []
        self.cancelled = False
        self.on_request = None
        self.http_status = 200
        self.catalog = dict(scopes=[SCOPE], stale=False, captured_at=datetime.now(timezone.utc).isoformat())
        self.published = []
        fake = types.ModuleType('wqb.multiplier_scope')
        fake.read_scope_catalog = lambda root: self.catalog
        fake.compile_scope_choices = lambda payload, instrument_type='EQUITY': [SCOPE]
        fake.publish_scope_catalog = lambda root, payload, captured_at: self.published.append((payload, captured_at))
        self.catalog_patch = patch.dict('sys.modules', {'wqb.multiplier_scope': fake})
        self.catalog_patch.start()
        self.addCleanup(self.catalog_patch.stop)

    def check(self):
        """Input: none. Output: none; reproduce durable Stop using InterruptedError."""
        if self.cancelled:
            raise InterruptedError('fixture Stop')

    def factory(self, **kwargs):
        """Input: guarded client kwargs. Output: real client with offline adapters only."""
        session = kwargs['session']
        session.mount('https://', FixtureAdapter(self))
        return FixtureClient(**kwargs)

    def prepare(self, **kwargs):
        """Input: optional overrides. Output: preparation receipt from the public API."""
        return self.module.prepare_multiplier_fields(self.root, self.job, SCOPE,
            check_cancelled=self.check, progress=self.updates.append,
            client_factory=kwargs.pop('client_factory', self.factory), **kwargs)

    def seed(self):
        """Input: none. Output: none; create dated raw evidence using real capture/compiler."""
        class Client:
            def get_json(inner, path):
                """Input: catalog path str. Output: explicit non-network fixture payload."""
                if path == '/operators':
                    return []
                if path.startswith('/data-sets'):
                    return {'results': [{'id': 'd'}], 'count': 1}
                return {'results': [{'id': 'f', 'type': 'MATRIX', 'coverage': 0.8}], 'count': 1}
        summary = capture_platform_data_fields(Client(), self.root,
            instrument_types=['EQUITY'], regions=['USA'], delays=[1], universes=['TOP3000'],
            max_scopes=1, fields_per_scope=100, resume_capture=True)
        compile_data_ledger_from_raw(self.root, summary['capture_dir'])

    def test_ready_fields_and_fresh_catalog_do_not_create_client(self):
        self.seed()
        with patch.object(self.module, 'capture_platform_data_fields', side_effect=AssertionError('capture')):
            result = self.prepare(client_factory=lambda **kw: self.fail('client creation'))
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['reused'])
        self.assertEqual(result['requests_used'], 0)
        self.assertEqual(result['field_count'], 1)

    def test_explicit_equity_scope_keeps_exact_identity(self):
        scope = dict(instrument_type='EQUITY', **SCOPE)
        result = self.module.prepare_multiplier_fields(self.root, self.job, scope,
            check_cancelled=self.check, progress=self.updates.append, client_factory=self.factory)
        self.assertEqual(result['scope'], scope)

    def test_missing_fields_refresh_options_then_exact_capture_and_compile(self):
        result = self.prepare()
        paths = [requests.utils.urlparse(url).path for _, url, _ in self.calls]
        self.assertEqual(paths, ['/authentication', '/simulations', '/operators', '/data-sets', '/data-fields'])
        self.assertEqual(self.calls[1][0], 'OPTIONS')
        self.assertEqual(result['requests_used'], len(self.calls))
        self.assertEqual(result['scope'], SCOPE)
        self.assertEqual(len(self.published), 1)
        self.assertEqual(result['field_count'], 1)
        self.assertTrue(Path(result['compile']['ledger_path']).is_file())
        field_url = self.calls[-1][1]
        for text in ('region=USA', 'delay=1', 'universe=TOP3000'):
            self.assertIn(text, field_url)
        manifest = json.loads((Path(result['capture']['capture_dir']) / 'manifest.json').read_text())
        self.assertEqual(manifest['active_limits'], dict(max_scopes=1, max_datasets_per_scope=2, max_fields_per_dataset=50))
        self.assertEqual(manifest['fields_per_scope'], 100)

    def test_ready_fields_stale_catalog_refreshes_options_only(self):
        self.seed()
        self.catalog['stale'] = True
        result = self.prepare()
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(result['reused'])
        self.assertEqual(len(self.published), 1)

    def test_unknown_scope_from_options_blocks_before_data_get(self):
        with patch.dict('sys.modules', {'wqb.multiplier_scope': types.SimpleNamespace(
                read_scope_catalog=lambda root: self.catalog,
                compile_scope_choices=lambda payload, instrument_type='EQUITY': [],
                publish_scope_catalog=lambda *a: self.fail('publish invalid scope'))}):
            with self.assertRaisesRegex(ValueError, 'scope'):
                self.prepare()
        self.assertEqual(len(self.calls), 2)

    def test_policy_is_strict_and_cannot_widen_default_caps(self):
        defaults = self.module.validated_preparation_policy()
        self.assertEqual(defaults, dict(request_limit=24, total_seconds=300,
            request_timeout_seconds=12, max_fields=100, max_datasets=2,
            max_fields_per_dataset=50, max_retries=0))
        for bad in ({'request_limit': True}, {'max_fields': 101},
                    {'total_seconds': 0}, {'max_retries': 1}, {'unknown': 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.module.validated_preparation_policy(bad)

    def test_auth_counts_and_budget_is_not_renewed_on_resume(self):
        policy = {'request_limit': 1}
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, 'attempt'):
                self.prepare(policy=policy)
        self.assertEqual(len(self.calls), 1)
        with self.assertRaisesRegex(ValueError, 'policy'):
            self.prepare()

    def test_deadline_covers_auth_and_survives_resume(self):
        def expire(path):
            self.clock = 1001.0
        self.clock = 1000.0
        self.on_request = expire
        with patch.object(self.module.time, 'time', side_effect=lambda: self.clock):
            with self.assertRaisesRegex(RuntimeError, 'deadline'):
                self.prepare(policy={'total_seconds': 1})
            with self.assertRaisesRegex(RuntimeError, 'deadline'):
                self.prepare(policy={'total_seconds': 1})
        self.assertEqual(len(self.calls), 1)

    def test_stop_before_effects_and_after_network_propagates(self):
        self.cancelled = True
        with self.assertRaises(InterruptedError):
            self.prepare()
        self.assertFalse(self.job.exists())
        self.cancelled = False
        self.on_request = lambda path: setattr(self, 'cancelled', True)
        with self.assertRaises(InterruptedError):
            self.prepare()
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.published)

    def test_429_has_no_hidden_retry_and_partial_is_not_completed(self):
        self.http_status = 429
        with self.assertRaises((RuntimeError, requests.HTTPError)):
            self.prepare()
        self.assertEqual(len(self.calls), 5)
        self.assertFalse((self.job / 'completed.json').exists())

    def test_completed_receipt_replay_reuses_without_transport(self):
        first = self.prepare()
        second = self.prepare(client_factory=lambda **kw: self.fail('replayed client'))
        self.assertEqual(first['requests_used'], second['requests_used'])
        self.assertTrue(second['reused'])

    def test_capture_cached_before_compile_stop_and_resumed_without_redownload(self):
        real_capture = self.module.capture_platform_data_fields
        def stop_after(*args, **kwargs):
            """Input: real capture args. Output: summary; emulate Stop at phase boundary."""
            summary = real_capture(*args, **kwargs)
            self.cancelled = True
            return summary
        with patch.object(self.module, 'capture_platform_data_fields', side_effect=stop_after):
            with self.assertRaises(InterruptedError):
                self.prepare()
        calls = len(self.calls)
        self.cancelled = False
        result = self.prepare(client_factory=lambda **kw: self.fail('capture redownload'))
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(result['status'], 'completed')

    def test_stop_after_compile_does_not_handoff(self):
        real_compile = self.module.compile_data_ledger_from_raw
        def stop_after(*args, **kwargs):
            """Input: compiler args. Output: receipt; emulate Stop after atomic compilation."""
            result = real_compile(*args, **kwargs)
            self.cancelled = True
            return result
        with patch.object(self.module, 'compile_data_ledger_from_raw', side_effect=stop_after):
            with self.assertRaises(InterruptedError):
                self.prepare()
        self.assertFalse((self.job / 'completed.json').exists())

    def test_raw_or_attempt_tamper_is_rejected(self):
        result = self.prepare()
        raw = Path(result['capture']['capture_dir']) / 'data_fields.jsonl'
        raw.write_text('{}\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed|tamper|digest'):
            self.prepare()

    def test_unexpected_job_contents_are_rejected(self):
        self.job.mkdir()
        (self.job / 'foreign.txt').write_text('not ours')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            self.prepare()

    def test_capture_id_isolated_and_stop_not_swallowed(self):
        class StopClient:
            def get_json(self, path):
                """Input: path str. Output: never; Stop must escape capture catches."""
                raise InterruptedError('Stop')
        with self.assertRaises(InterruptedError):
            capture_platform_data_fields(StopClient(), self.root, capture_id='a' * 32,
                regions=['USA'], delays=[1], universes=['TOP3000'], resume_capture=True)
        with self.assertRaises(ValueError):
            capture_platform_data_fields(StopClient(), self.root, capture_id='../escape', resume_capture=True)

    def test_capture_child_hardlink_is_refused_without_writing(self):
        capture = self.root / 'raw/platform/data_fields' / ('2026-11-10-' + 'a' * 32)
        capture.mkdir(parents=True)
        target = Path(self.temp.name) / 'protected'
        target.write_text('protected', encoding='utf-8')
        os.link(target, capture / 'operators.json')
        with self.assertRaises(ValueError):
            capture_platform_data_fields(object(), self.root, generated_at='2026-11-10T00:00:00Z',
                capture_id='a' * 32, resume_capture=True)
        self.assertEqual(target.read_text(), 'protected')

    def test_attempt_journal_tamper_is_refused(self):
        self.prepare()
        path = self.job / 'attempts.jsonl'
        path.write_text('', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'journal'):
            self.prepare()

    def test_receipt_scope_tamper_even_with_recomputed_digest_is_refused(self):
        self.prepare()
        path = self.job / 'completed.json'
        envelope = json.loads(path.read_text())
        envelope['payload']['scope']['region'] = 'EUR'
        envelope['sha256'] = self.module._digest(envelope['payload'])
        path.write_text(json.dumps(envelope), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'receipt'):
            self.prepare()

    def test_stale_or_wrong_scope_or_untyped_local_rows_trigger_capture(self):
        self.seed()
        path = self.root / 'machine/data_ledger.jsonl'
        initial = json.loads(path.read_text())
        for overrides in ({'source_updated_at': '2020-01-01'}, {'field_type': 'UNKNOWN'},
                          {'coverage': 0}, {'available_scopes': [dict(instrument_type='EQUITY', **dict(SCOPE, region='EUR'))]}):
            with self.subTest(overrides=overrides):
                path.write_text(json.dumps(dict(initial, **overrides)) + '\n', encoding='utf-8')
                self.assertIsNone(self.module._ready(self.root, SCOPE, self.check))

    def test_stop_inside_each_capture_transport_is_propagated(self):
        for index, endpoint in enumerate(('/operators', '/data-sets', '/data-fields')):
            with self.subTest(endpoint=endpoint):
                self.job = Path(self.temp.name) / ('job' + str(index))
                self.cancelled = False
                self.on_request = lambda path: setattr(self, 'cancelled', path == endpoint)
                with self.assertRaises(InterruptedError):
                    self.prepare()
                self.assertFalse((self.job / 'completed.json').exists())

    def test_real_authentication_uses_guard_and_no_auth_secrets_are_recorded(self):
        def factory(**kwargs):
            """Input: guarded kwargs. Output: unmodified WQBClient using offline adapter."""
            kwargs['session'].mount('https://', FixtureAdapter(self))
            return WQBClient(**kwargs)
        with patch('wqb.client.load_credentials', return_value=('fixture-user', 'fixture-password')):
            result = self.prepare(client_factory=factory)
        self.assertEqual(result['requests_used'], 5)
        for path in self.job.iterdir():
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('fixture-password', text)
            self.assertNotIn('Authorization', text)

    def test_partial_retry_does_not_reset_attempt_budget(self):
        self.http_status = 429
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                self.prepare(policy={'request_limit': 7})
        self.assertEqual(len(self.calls), 7)

    def test_failed_compile_reuses_capture_and_propagates_error(self):
        with patch.object(self.module, 'compile_data_ledger_from_raw', side_effect=ValueError('compiler provenance')):
            with self.assertRaisesRegex(ValueError, 'compiler provenance'):
                self.prepare()
        result = self.prepare(client_factory=lambda **kw: self.fail('redownload on compiler retry'))
        self.assertEqual(result['status'], 'completed')

    def test_compilation_preserves_active_release_and_frozen_bytes(self):
        from tests.test_knowledge_maintenance import KnowledgeMaintenanceTests
        from wqb.semantic_publication import read_semantic_release
        from wqb.knowledge_contracts import SourceIndexRow, write_machine_source_index
        import hashlib
        receipt = KnowledgeMaintenanceTests()._active_release(self.root)
        write_machine_source_index(self.root, [SourceIndexRow(
            path='raw/platform/learn/operators.md', source_family='learn', source_type='platform_api',
            contents='Explicit existing operator fixture', update_check='compare original',
            captured_at='2026-07-30T00:00:00Z', record_count=1, content_status='raw_markdown',
            content_hash=hashlib.sha256(b'# Captured operator definition\n').hexdigest())])
        before = {p: p.read_bytes() for p in (self.root / 'machine/semantic_releases').rglob('*') if p.is_file()}
        self.prepare()
        self.assertEqual(read_semantic_release(self.root), receipt)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_data_capture_limits_and_unique_directory_do_not_touch_date_bucket(self):
        self.seed()
        day = datetime.now(timezone.utc).date().isoformat()
        dated = self.root / 'raw/platform/data_fields' / day
        before = {p.name: p.read_bytes() for p in dated.iterdir()}
        # Force a refresh by invalidating only the compiled projection.
        ledger = self.root / 'machine/data_ledger.jsonl'
        row = json.loads(ledger.read_text())
        row['source_updated_at'] = '2020-01-01'
        ledger.write_text(json.dumps(row) + '\n', encoding='utf-8')
        result = self.prepare(policy={'max_fields': 2, 'max_fields_per_dataset': 1, 'max_datasets': 1})
        self.assertEqual(before, {p.name: p.read_bytes() for p in dated.iterdir()})
        self.assertNotEqual(Path(result['capture']['capture_dir']), dated)

    def test_client_cannot_post_simulation_or_follow_redirect_or_hide_retry(self):
        def factory(**kwargs):
            """Input: guarded kwargs. Output: client whose construction attempts prohibited transport."""
            kwargs['session'].post('https://api.worldquantbrain.com/simulations')
        with self.assertRaisesRegex(ValueError, 'allowlisted'):
            self.prepare(client_factory=factory)
        self.assertFalse(self.calls)

    def test_real_catalog_interface_missing_then_published_then_no_client_replay(self):
        self.catalog_patch.stop()
        result = self.prepare()
        from wqb.multiplier_scope import read_scope_catalog
        catalog = read_scope_catalog(self.root)
        self.assertEqual(catalog['scopes'], [SCOPE])
        self.assertFalse(catalog['stale'])
        replay = self.prepare(client_factory=lambda **kw: self.fail('real catalog cache replay'))
        self.assertEqual(result['requests_used'], replay['requests_used'])

    def test_ledger_source_path_traversal_is_rejected(self):
        self.seed()
        ledger = self.root / 'machine/data_ledger.jsonl'
        row = json.loads(ledger.read_text())
        row['source_paths'] = ['raw/platform/data_fields/../../../../outside/data_fields.jsonl']
        ledger.write_text(json.dumps(row) + '\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'traversal'):
            self.prepare()

    def test_compiler_output_hardlink_is_rejected_before_capture(self):
        (self.root / 'machine/previews').mkdir(parents=True)
        target = Path(self.temp.name) / 'protected-preview'
        target.write_text('protected', encoding='utf-8')
        os.link(target, self.root / 'machine/previews/data_ledger.md')
        with self.assertRaisesRegex(ValueError, 'hardlinked'):
            self.prepare()
        self.assertFalse(self.calls)
        self.assertEqual(target.read_text(), 'protected')

    def test_transport_adapter_retry_is_rejected(self):
        def factory(**kwargs):
            """Input: guarded kwargs. Output: unsafe adapter fixture; guard must reject it."""
            kwargs['session'].mount('https://', HTTPAdapter(max_retries=2))
            return FixtureClient(**kwargs)
        with self.assertRaisesRegex(ValueError, 'retries'):
            self.prepare(client_factory=factory)
        self.assertFalse(self.calls)

    def test_completed_receipt_provenance_tamper_is_rejected(self):
        self.prepare()
        path = self.job / 'completed.json'
        envelope = json.loads(path.read_text())
        envelope['payload']['provenance']['source']['sha256'] = '0' * 64
        envelope['sha256'] = self.module._digest(envelope['payload'])
        path.write_text(json.dumps(envelope), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'receipt'):
            self.prepare()

    def test_invalid_existing_catalog_is_not_silently_replaced(self):
        path = self.root / 'machine/multiplier_scope_catalog.json'
        path.parent.mkdir(parents=True)
        path.write_text('tampered', encoding='utf-8')
        with patch.dict('sys.modules', {'wqb.multiplier_scope': types.SimpleNamespace(
                read_scope_catalog=lambda root: (_ for _ in ()).throw(ValueError('catalog tamper')),
                compile_scope_choices=lambda *a, **kw: [SCOPE],
                publish_scope_catalog=lambda *a: self.fail('replaced tampered catalog'))}):
            with self.assertRaisesRegex(ValueError, 'catalog tamper'):
                self.prepare()
        self.assertFalse(self.calls)

    def test_capture_hook_rejects_path_timestamp_and_nonresume(self):
        for timestamp, resume in (('../../outside', True), ('2026-11-10T00:00:00Z', False)):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                capture_platform_data_fields(object(), self.root, generated_at=timestamp,
                    capture_id='a' * 32, resume_capture=resume)

    def test_transport_timeout_is_capped_and_redirect_disabled(self):
        self.prepare(policy={'request_timeout_seconds': 2})
        self.assertTrue(all(0 < kwargs['timeout'] <= 2 for _, _, kwargs in self.calls))

    def test_incomplete_sample_never_redownloads_or_appends_over_field_cap(self):
        class PartialAdapter(FixtureAdapter):
            def send(adapter, request, **kwargs):
                """Input: prepared request. Output: two datasets, second unavailable after first field."""
                response = super().send(request, **kwargs)
                if '/data-sets?' in request.url:
                    response._content = json.dumps({'results': [{'id': 'd'}, {'id': 'other'}], 'count': 2}).encode()
                if 'dataset.id=other' in request.url:
                    response.status_code = 429
                return response
        def factory(**kwargs):
            """Input: guarded kwargs. Output: offline partially failing client."""
            kwargs['session'].mount('https://', PartialAdapter(self))
            return FixtureClient(**kwargs)
        with self.assertRaises(RuntimeError):
            self.prepare(client_factory=factory)
        raw = next((self.root / 'raw/platform/data_fields').glob('*/data_fields.jsonl'))
        original = raw.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'partial'):
            self.prepare(client_factory=lambda **kw: self.fail('partial redownload'))
        self.assertEqual(raw.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
