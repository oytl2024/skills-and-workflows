"""Bounded retrieval-to-driver acceptance using real decisions and offline HTTP.

Plan: freeze a queried VECTOR design, drive measured Seed/finite Repair, then
verify weak exhaustion, durable Stop and owner-local scientific inputs. Only
fictional raw HTTP is injected; no stage, readiness or hard-pass bypasses.

The strict postseal fence includes benchmark rules; classification consumes the
sealed owning run, never a newly published global scientific rulebook.
This bounded fixture has one root, not multi-lane/depth-two/GROUP acceptance.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from tests import test_preplanned_driver_acceptance as drivers
from tests import test_preplanned_research_acceptance as acceptance
from tests import test_retrieval_start as retrieval


REPAIR_GRID = [8, 16]


class RetrievalLifecycleTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: source-backed temporary VECTOR retrieval fixture and offline fences."""
        self.retrieval = retrieval.RetrievalStartTests()
        self.retrieval.setUp()
        self.addCleanup(self.retrieval.doCleanups)
        self.fixture = self.retrieval.fixture
        self.fixture.authority['enable_live_api'] = True
        self.fixture.paths.workflow_root = Path(__file__).resolve().parents[1]
        self.driver = drivers.PreplannedDriverAcceptanceTests()
        self.driver.case = SimpleNamespace(fixture=self.fixture)
        resource = self.fixture.resources[0]
        field = resource['field_rows'][0]
        source_path = field['source_paths'][0]
        payload = json.loads(resource['source_texts'][source_path])
        field['field_type'] = payload['fields'][0]['field']['type'] = 'VECTOR'
        operator = dict(operator='vec_avg', definition=dict(
            description='Taking mean of the vector field x', input_types=['VECTOR'],
            output_type='MATRIX', parameters=[dict(name='x', type='VECTOR', required=True)]))
        payload['operators'].append(deepcopy(operator))
        text = json.dumps(payload)
        digest = hashlib.sha256(text.encode()).hexdigest()
        resource['source_index'][source_path]['content_hash'] = digest
        resource['source_texts'][source_path] = text
        (self.fixture.paths.knowledge_root / source_path).write_text(text, encoding='utf-8')
        resource['operator_rows'].append(operator)
        self.driver.certify_resources()
        from wqb.repair_rulebook import load_repair_rulebook
        rulebook = load_repair_rulebook()
        rulebook['decay_grid'] = REPAIR_GRID
        rulebook['rules'] = [row for row in rulebook['rules'] if row['rule_id'] == 'fitness-averaging']
        self.enterContext(patch('wqb.repair_rulebook.load_repair_rulebook', return_value=rulebook))
        self.enterContext(patch('subprocess.Popen', side_effect=AssertionError('offline: no subprocess/model')))
        self.enterContext(patch('requests.sessions.Session.request',
                                side_effect=AssertionError('offline: no real HTTP')))
        self.enterContext(patch('socket.create_connection', side_effect=AssertionError('offline: no network')))
        self.enterContext(patch('wqb.research_group_driver.SOURCE_MULTI_CHUNK_SLEEP_SECONDS', 0))

    def prepare(self, *, weak=False, qualified=False):
        """Input: weak/qualified bools. Output: real sealed/resumed lane Path with identity-bound HTTP metrics."""
        from wqb.preplanned_start import prepare_preplanned_start
        from wqb.research_group_driver import initialize_group_runtime
        from wqb.research_group import resume_group
        from wqb.runtime_control import request_runtime_state
        from wqb.research_tree import _load
        from wqb.cli import simulation_identity_hash
        result = prepare_preplanned_start(self.fixture.paths, self.fixture.option,
            self.fixture.authority, self.retrieval.config,
            model_runner=lambda *_: self.fail('legacy model called'),
            retrieval_model_runner=self.retrieval.model)
        self.assertEqual(result['status'], 'completed', result)
        group = initialize_group_runtime(self.fixture.paths, result['group'])
        self.run = self.fixture.paths.run_root / group['lanes'][0]['run_id']
        request_runtime_state(self.run, 'running')
        self.driver.case.runs = [self.run]
        self.driver.case.group = resume_group(Path(group['group_dir']), group['request_revision'])
        tree, snapshot = _load(self.run)
        self.assertEqual(snapshot['research_policy']['retrieval_design_version'], 1)
        self.assertEqual(snapshot['data_ledger_rows'][0]['field_type'], 'VECTOR')
        self.assertTrue((self.run / 'runtime/execution_package/seal.json').exists())
        metrics = {}
        for node in tree['tree']['nodes']:
            for expected in node['expected'].values():
                self.assertIn('vec_avg(', expected['expression'])
                metrics[expected['simulation_identity']] = dict(
                    sharpe=.2 if weak else 1.6, fitness=.1 if weak else .8,
                    turnover=.2, returns=.1)
        self.transport = acceptance.OfflineResearchTransport(metrics)
        self.transport.client.knowledge_root = self.fixture.paths.knowledge_root
        self.driver.transport = self.transport
        dispatch = self.transport.request

        def request(method, url, **kwargs):
            """Input: HTTP fields. Output: raw auth/check/finite-Repair responses, never a classified summary."""
            import requests
            path = urlsplit(url).path
            if method == 'POST' and path == '/authentication':
                self.transport.calls.append((method, path))
                response = requests.Response()
                response.status_code, response._content = 201, b'{}'
                return response
            if method == 'POST' and path == '/simulations':
                payloads = kwargs['json']
                for payload in payloads if isinstance(payloads, list) else [payloads]:
                    settings = payload['settings']
                    if settings['decay'] in REPAIR_GRID:
                        parent = simulation_identity_hash(payload['regular'], dict(settings, decay=4))
                        identity = simulation_identity_hash(payload['regular'], settings)
                        self.transport.metrics[identity] = dict(self.transport.metrics[parent],
                            fitness=1.2 if qualified else .8, turnover=.15)
            response = dispatch(method, url, **kwargs)
            if qualified and method == 'GET' and path.endswith('/check'):
                response._content = json.dumps({'is': {'checks': [dict(name=name, result='PASS')
                    for name in ('SELF_CORRELATION', 'PROD_CORRELATION')]}}).encode()
            return response

        self.transport.session.request.side_effect = request
        self.transport.session.post.side_effect = lambda url, **kwargs: request('POST', url, **kwargs)
        self.enterContext(patch.dict(os.environ, WQB_USERNAME='offline-fixture', WQB_PASSWORD='offline-fixture'))
        self.enterContext(patch('wqb.cli.build_client', return_value=self.transport.client))
        return self.run

    def assert_accounting(self):
        """Input: current fixture. Output: assertions for exact charges, dedup and no final submission."""
        from wqb.daily_simulation_budget import read_daily_budget
        self.assertEqual(read_daily_budget(self.run)['used'], len(self.transport.posted))
        self.assertEqual(len(set(self.transport.posted)), len(self.transport.posted))
        self.assertEqual(len(self.retrieval.calls), 1)
        self.assertFalse(any(path.endswith('/submit') for _, path in self.transport.calls))

    def test_vector_retrieval_driver_selects_seed_and_exhausts_finite_repair(self):
        """Input: real retrieval package/near-miss HTTP. Output: measured Seed, finite Repair and durable record."""
        run = self.prepare()
        result = self.driver.drive(run)
        self.assertEqual((result['current_stage'], result['status']), ('complete', 'completed'), result)
        selection = json.loads((run / 'stages/scout_seed/seed_selection.json').read_text())
        self.assertTrue(selection['selected'], selection)
        self.assertFalse(selection['submission_qualified'])
        repair = json.loads((run / 'stages/repair/repair_execution.json').read_text())
        self.assertTrue(any(attempt.get('children') for attempt in repair['attempts']), repair)
        self.assertEqual(repair['status'], 'completed')
        variants = [row for attempt in repair['attempts'] for row in attempt['plan']['variants']]
        self.assertTrue(variants)
        self.assertTrue(all(attempt['plan']['planner_kind'] == 'deterministic' for attempt in repair['attempts']))
        self.assertTrue(all(row['settings']['decay'] in REPAIR_GRID for row in variants))
        self.assertLessEqual(len(variants), len(selection['selected']) * len(REPAIR_GRID))
        self.assertEqual(len(self.transport.posted), 2 + len(variants))
        record = json.loads((run / 'research_record.json').read_text())
        self.assertTrue(record['backtest'])
        self.assertTrue(record['repair'])
        self.assertEqual(record['approved_queue'], [])
        self.assertTrue(json.loads((run / 'run_state.json').read_text())['research_record_synced'])
        self.assertFalse((run / 'rounds/round-0001/stages/repair').exists())
        self.assertFalse(any(path.endswith('/check') for _, path in self.transport.calls),
                         'Failed cheap baseline checks must defer correlation checks')
        self.assert_accounting()

    def test_weak_retrieval_tree_finishes_without_seed_or_repair_posts(self):
        """Input: weak raw measurements. Output: terminal exhaustion without manufactured Seed or correlation calls."""
        run = self.prepare(weak=True)
        result = self.driver.drive(run)
        self.assertEqual((result['current_stage'], result['status']), ('complete', 'completed'), result)
        selection = json.loads((run / 'stages/scout_seed/seed_selection.json').read_text())
        self.assertEqual(selection['selected'], [])
        self.assertEqual(len(self.transport.posted), 2)
        self.assertFalse(any(path.endswith('/check') for _, path in self.transport.calls))
        self.assertFalse(list((run / 'runtime/repair_decisions').glob('*.json')))
        self.assert_accounting()

    def test_stop_inside_retrieval_repair_post_is_durable_without_replay(self):
        """Input: Stop during actual Repair POST. Output: original charge/authority/identity survive two restarts."""
        from wqb.daily_simulation_budget import read_daily_budget
        from wqb.research_group import read_group
        run = self.prepare()

        def repair_post(method, path, kwargs):
            """Input: HTTP method/path/options. Output: bool identifying only a frozen finite Repair edit."""
            payload = kwargs.get('json', [])
            rows = payload if isinstance(payload, list) else [payload]
            return method == 'POST' and path == '/simulations' and any(
                row['settings']['decay'] in REPAIR_GRID for row in rows)

        threads, errors = self.driver.stop_inside_transport(repair_post)
        self.addCleanup(self.driver.doCleanups)
        self.driver.drive(run)
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertTrue(threads, 'Must reach the real Repair POST before testing Stop')
        self.assertFalse(errors)
        group = Path(self.driver.case.group['group_dir'])
        before = read_group(group)
        self.assertEqual(before['desired_state'], 'paused')
        posts = list(self.transport.posted)
        budget = read_daily_budget(run)
        for _ in range(2):
            self.driver.drive(run)
        after = read_group(group)
        for key in ('desired_state', 'authority', 'recoveries_used', 'request_revision'):
            self.assertEqual(after[key], before[key])
        self.assertEqual(self.transport.posted, posts)
        self.assertEqual(read_daily_budget(run)['lifetime_attempts'], budget['lifetime_attempts'])
        from wqb.execution_package_lifecycle import RETIRED_RECEIPT
        self.assertFalse((run / RETIRED_RECEIPT).exists())
        self.assert_accounting()

    def test_postseal_driver_never_reopens_global_scientific_resources(self):
        """Input: sealed retrieval package. Output: real Seed/Repair/record finish with global science reads fenced.

        Candidate checks, account revisions and research-record/source-index writes
        remain live by contract; this fence targets scientific planning inputs.
        """
        run = self.prepare()
        knowledge = self.fixture.paths.knowledge_root
        original_open = Path.open
        forbidden = []
        scientific = {'data_ledger.jsonl', 'operator_ledger.jsonl', 'template_library.jsonl',
                      'freshness_manifest.json', 'benchmark_rules.jsonl', 'mechanism_evidence.json'}

        def guarded_open(path, mode='r', *args, **kwargs):
            """Input: Path/open arguments. Output: file handle; reject global scientific reads after sealing."""
            relative = path.relative_to(knowledge).as_posix() if path.is_relative_to(knowledge) else ''
            if ('r' in mode or '+' in mode) and (relative.startswith(('raw/platform/', 'wiki/'))
                    or (relative.startswith('machine/') and path.name in scientific)):
                forbidden.append(relative)
                raise AssertionError('postseal global scientific read: ' + relative)
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, 'open', guarded_open), patch(
                'wqb.exploration_eligibility._resource_certificate',
                side_effect=AssertionError('postseal global recertification')):
            result = self.driver.drive(run)
        self.assertEqual(forbidden, [])
        self.assertEqual((result['current_stage'], result['status']), ('complete', 'completed'), result)
        self.assertTrue(json.loads((run / 'run_state.json').read_text())['research_record_synced'])
        self.assert_accounting()

    def test_qualified_repair_child_records_raw_checks_but_never_submits(self):
        """Input: repaired baseline-pass HTTP plus raw correlation PASS. Output: real qualified cache and approval wait."""
        from wqb.candidate_evidence import load_candidate_evidence
        run = self.prepare(qualified=True)
        result = self.driver.drive(run)
        self.assertEqual(result['status'], 'waiting_for_user', result)
        files = list((self.fixture.paths.knowledge_root / 'machine/candidate_evidence').glob('*.json'))
        self.assertTrue(files, result)
        records = [json.loads(path.read_text()) for path in files]
        self.assertTrue(any(record.get('alpha_id') in self.transport.details for record in records), records)
        for record in records:
            alpha_id = record['alpha_id']
            cached = load_candidate_evidence(self.transport.client, alpha_id)
            self.assertIsNotNone(cached)
            checks = {item['name']: item['result'] for item in cached[0]['is']['checks']}
            for name in ('LOW_SHARPE', 'LOW_FITNESS', 'SELF_CORRELATION', 'PROD_CORRELATION'):
                self.assertEqual(checks[name], 'PASS')
            self.assertEqual(cached[1]['fitness'], self.transport.details[alpha_id]['is']['fitness'])
            self.assertEqual(record['identity']['expression'], self.transport.details[alpha_id]['regular']['code'])
            self.assertEqual(record['identity']['settings'], self.transport.details[alpha_id]['settings'])
        calls = self.transport.calls
        checked = [path.split('/')[2] for method, path in calls if method == 'GET' and path.endswith('/check')]
        self.assertTrue(checked)
        for alpha_id in checked:
            self.assertGreaterEqual(self.transport.details[alpha_id]['is']['fitness'], 1)
            detail_position = calls.index(('GET', '/alphas/' + alpha_id))
            self.assertLess(detail_position, calls.index(('GET', '/alphas/' + alpha_id + '/check')))
        record = json.loads((run / 'research_record.json').read_text())
        self.assertTrue(record['repair'])
        self.assertTrue(record['candidate_gate'])
        self.assertEqual(record['approved_queue'], [])
        posted = list(self.transport.posted)
        again = self.driver.drive(run)
        self.assertEqual(again['status'], 'waiting_for_user')
        self.assertEqual(self.transport.posted, posted)
        self.assert_accounting()
