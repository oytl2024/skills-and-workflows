"""Offline composition -> real multisim transport boundary -> measured Seed acceptance."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from urllib.parse import urlsplit

import requests


FIXTURE_NOW = '2026-10-23T00:00:00Z'


class OfflineResearchTransport:
    def __init__(self, metrics):
        """Input: identity->metrics dict. Output: HTTP-only fake with a real authenticated WQBClient."""
        from wqb.client import WQBClient
        self.metrics, self.details, self.progress, self.calls = metrics, {}, {}, []
        self.posted = []
        self.session = Mock()
        self.session.request.side_effect = self.request
        self.client = WQBClient(session=self.session)
        self.client.authenticated = True

    def request(self, method, url, **kwargs):
        """Input: HTTP method/URL/options. Output: Response; reject every unplanned endpoint/identity."""
        from wqb.cli import simulation_identity_hash
        path = urlsplit(url).path
        self.calls.append((method, path))
        response = requests.Response()
        response.status_code = 200
        if method == 'POST' and path == '/simulations':
            payloads = kwargs['json']
            multiple = isinstance(payloads, list)
            payloads = payloads if multiple else [payloads]
            alpha_ids = []
            for payload in payloads:
                identity = simulation_identity_hash(payload['regular'], payload['settings'])
                metrics = deepcopy(self.metrics[identity])
                metrics.update(startDate='2020-01-01', endDate='2025-01-01')
                metrics['checks'] = [dict(name='LOW_SHARPE', result='PASS' if metrics['sharpe'] >= 1.25 else 'FAIL'),
                    dict(name='LOW_FITNESS', result='PASS' if metrics['fitness'] >= 1 else 'FAIL')]
                alpha_id = 'a' + identity[:20]
                self.details[alpha_id] = dict(id=alpha_id, status='UNSUBMITTED',
                    regular=dict(code=payload['regular']), settings=deepcopy(payload['settings']), **{'is': metrics})
                self.posted.append(identity)
                alpha_ids.append(alpha_id)
            location = '/simulations/offline' + str(len(self.progress))
            self.progress[location] = dict(status='COMPLETE', alpha=alpha_ids if multiple else alpha_ids[0])
            response.status_code = 201
            response.headers['Location'] = location
            body = {}
        elif method == 'GET' and path in self.progress:
            body = self.progress[path]
        elif method == 'GET' and path.startswith('/alphas/'):
            alpha_id = path.split('/')[2]
            detail = self.details[alpha_id]
            if path.endswith('/check'):
                body = {'is': {'checks': [dict(name=name, result='PENDING')
                    for name in ('SELF_CORRELATION', 'PROD_CORRELATION')]}}
            else:
                body = detail
        else:
            raise AssertionError('Forbidden offline HTTP: ' + method + ' ' + path)
        response._content = json.dumps(body).encode('utf-8')
        return response


def four_root_answer(fixture, brief):
    """Input: sourced Start fixture/brief dict. Output: four roots with all depth-two alternatives frozen."""
    answer = fixture.answer_for_brief(brief)
    base = answer['designs'][0]
    designs, nodes = [], []

    def add(name, horizon, parent=None, arm=None, direction='positive', family=None):
        """Input: node identity/horizon/edge/direction. Output: mutable node dict backed by a real design."""
        design = deepcopy(base)
        design['mechanism_family'] = family or name
        feature = dict(kind='change', input=dict(kind='role', role='pulse'), horizon=horizon)
        design['feature_plan'] = deepcopy(feature)
        design['experiment_plan']['baseline'] = feature
        design['experiment_plan']['treatments'][0]['feature'] = dict(feature, horizon=horizon + 1)
        design['prediction_direction'] = direction
        node = dict(node_id=name, parent_id=parent, parent_arm_id=arm, design_index=len(designs),
                    targets=dict(baseline=[], treatment=[]), fallback=[], reverse={})
        designs.append(design)
        nodes.append(node)
        return node

    both = add('both', 5)
    opposite = add('opposite', 22)
    weak = add('weak', 122)
    add('threshold', 252)
    add('left', 5, 'both', 'baseline', family='both')
    # Reuse the measured parent baseline, but test a distinct predeclared child feature.
    designs[-1]['experiment_plan']['treatments'][0]['feature']['horizon'] = 8
    add('right', 6, 'both', 'treatment', family='both')
    add('fallback', 124, 'weak', 'fallback')
    both['targets'] = dict(baseline=['left'], treatment=['right'])
    weak['fallback'] = ['fallback']
    reverse = deepcopy(designs[opposite['design_index']])
    reverse['prediction_direction'] = 'negative'
    opposite['reverse']['baseline'] = dict(design_index=len(designs), arm_id='baseline',
        interpretation='The opposite response may be informative.', targets=['reverse_child'])
    designs.append(reverse)
    add('reverse_child', 22, 'opposite', 'reverse:baseline', direction='negative', family='opposite')
    designs[-1]['experiment_plan']['treatments'][0]['feature']['horizon'] = 25
    return dict(summary='Four fictional offline hypotheses.', designs=designs,
                tree=dict(roots=['both', 'opposite', 'weak', 'threshold'], nodes=nodes))


class IntegratedFourRootAcceptanceTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: private two-dataset Start fixture with counted initial model only."""
        from tests.test_preplanned_start import PreplannedStartTests
        self.fixture = PreplannedStartTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.add_lane(1)
        self.fixture.config['parallel_workflows'] = 2
        self.fixture.authority['enable_live_api'] = True
        self.fixture.paths.workflow_root = Path(__file__).resolve().parents[1]
        self.fixture.runner.side_effect = lambda brief: four_root_answer(self.fixture, brief)

    def start_group(self):
        """Input: fixture on self. Output: initialized/resumed group dict and all predeclared HTTP metrics."""
        from wqb.research_group_driver import initialize_group_runtime
        from wqb.research_group import resume_group
        from wqb.research_tree import _load
        from wqb.runtime_control import request_runtime_state
        prepared = self.fixture.prepare()
        self.assertEqual(prepared['status'], 'completed', prepared)
        group = initialize_group_runtime(self.fixture.paths, prepared['group'])
        self.runs = [self.fixture.paths.run_root / lane['run_id'] for lane in group['lanes']]
        metrics = {}
        values = dict(both=((1.5, .8, .2), (1.7, .9, .2)),
            opposite=((-1.5, .8, .2), (.3, .1, .2)),
            weak=((.2, .1, .2), (.3, .2, .2)),
            threshold=((1.25, .8, .2), (1.4, .85, .4)),
            left=((1.5, .8, .2), (1.6, .7, .2)),
            right=((1.7, .9, .2), (1.8, .95, .2)),
            fallback=((1.5, .8, .2), (1.8, .98, .2)),
            reverse_child=((1.6, .85, .2), (1.9, .95, .2)))
        for run in self.runs:
            request_runtime_state(run, 'running')
            tree, _ = _load(run)
            for node in tree['tree']['nodes']:
                for arm, triple in zip(('baseline', 'treatment'), values[node['node_id']]):
                    identity = node['expected'][arm]['simulation_identity']
                    sharpe, fitness, turnover = triple
                    metrics[identity] = dict(sharpe=sharpe, fitness=fitness, turnover=turnover,
                        returns=-.1 if sharpe < 0 else .1)
            reverse = next(node for node in tree['tree']['nodes'] if node['node_id'] == 'opposite')['reverse']['baseline']
            metrics[reverse['expected']['simulation_identity']] = dict(sharpe=1.6, fitness=.85, turnover=.2, returns=.1)
            pair = tree['resources']['compiled_pairs'][reverse['pair_ref']]['experiment']['arms']
            from wqb.cli import simulation_identity_hash
            for arm in pair:
                identity = simulation_identity_hash(arm['binding']['bound_expression'], arm['settings'])
                metrics.setdefault(identity, dict(sharpe=.3, fitness=.1, turnover=.2, returns=.1))
        self.transport = OfflineResearchTransport(metrics)
        self.group = resume_group(Path(group['group_dir']), group['request_revision'])
        self.sources = []
        return self.group

    def source_runner(self, config, metadata):
        """Input: genuine consumed tree patch/metadata. Output: real CLI source artifacts via fake HTTP only."""
        from wqb.cli import run_field_batch
        from wqb.recorder import RunRecorder
        from wqb.runtime_control import CONTROL_ENV
        run = Path(config['active_workflow_run_dir'])
        source = run.parent / ('http-source-' + str(len(self.sources)))
        self.sources.append(source)
        settings = config['scheduled_hypotheses'][0]['settings']
        supplied = dict(config, knowledge_root=str(self.fixture.paths.knowledge_root),
            instrument_type=settings['instrumentType'], region=settings['region'],
            universe=settings['universe'], delay=settings['delay'], decay=settings['decay'],
            neutralization=settings['neutralization'], truncation=settings['truncation'],
            pasteurization=settings['pasteurization'], unit_handling=settings['unitHandling'],
            nan_handling=settings['nanHandling'], language=settings['language'])
        with patch.dict(os.environ, {CONTROL_ENV: str(run)}):
            run_field_batch(self.transport.client, RunRecorder(source), supplied,
                workflow_stage='scout', submit_mode='multi', multi_chunk_sleep_seconds=0,
                defer_poll=getattr(self, 'defer_poll', False))
        return dict(run_dir=str(source))

    def finish_trees(self):
        """Input: started fixture. Output: list of verified completed tree results from bounded real transitions."""
        from wqb.tree_runtime import continue_tree, verify_tree_results
        finished = []
        for run in self.runs:
            for _ in range(8):
                result = continue_tree(run, self.fixture.config, FIXTURE_NOW, enable_live_api=True,
                                       source_batch_runner=self.source_runner)
                self.assertEqual(result['next_action'], 'workflow-auto-continue',
                    {key: result.get(key) for key in ('next_action', 'message', 'source_bridge')})
                if result.get('tree_complete'):
                    finished.append(verify_tree_results(run))
                    break
            else:
                self.fail('Frozen finite tree did not finish in eight transitions')
        return finished

    def test_real_http_routes_both_reverse_fallback_rollback_and_seed_gates(self):
        """Input: frozen N2/four-root plans. Output: measured branches, strict Seed gates and original accounting."""
        from wqb.daily_simulation_budget import read_daily_budget
        from wqb.research_seed_stage import prepare_seed_selection
        from wqb.tree_runtime import checked_research_rows
        self.start_group()
        results = self.finish_trees()
        for run, tree in zip(self.runs, results):
            routes = tree['routes']
            self.assertEqual(routes['both']['selected_arm_ids'], ['baseline', 'treatment'])
            self.assertEqual(routes['both']['selected_node_ids'], ['left', 'right'])
            self.assertEqual(routes['weak']['branch_kind'], 'fallback')
            self.assertEqual(routes['weak']['selected_node_ids'], ['fallback'])
            self.assertEqual(routes['opposite']['selected_node_ids'], ['reverse_child'])
            self.assertEqual(tree['comparisons']['left']['outcome'], 'rejected')
            from wqb.research_tree import _load
            attachment, _ = _load(run)
            nodes = {node['node_id']: node for node in attachment['tree']['nodes']}
            self.assertEqual(tree['comparisons']['left']['incumbent']['expression_hash'],
                             nodes['both']['expected']['baseline']['simulation_identity'])
            reverse_id = nodes['opposite']['reverse']['baseline']['expected']['simulation_identity']
            self.assertIn(reverse_id, self.transport.posted)
            self.assertNotEqual(reverse_id, nodes['opposite']['expected']['baseline']['simulation_identity'])
            measured = checked_research_rows(run)
            from wqb.seed_policy import select_seeds
            from wqb.benchmark_rules import load_run_benchmark_rules
            all_seed_gates = select_seeds(measured, {}, benchmark_rules=load_run_benchmark_rules(run))
            turnover_id = nodes['threshold']['expected']['treatment']['simulation_identity']
            self.assertTrue(any(row['identity']['expression_hash'] == turnover_id
                and 'turnover_out_of_bounds' in row['reasons'] for row in all_seed_gates['rejected']))
            selection = prepare_seed_selection(run, measured)
            self.assertTrue(selection['selected'], selection)
            self.assertFalse(selection['submission_qualified'])
            self.assertTrue(all(not row['hard_pass'] for row in measured))
            threshold_id = nodes['threshold']['expected']['baseline']['simulation_identity']
            self.assertTrue(any(row['identity']['expression_hash'] == threshold_id
                and 'sharpe_not_above_floor' in row['reasons'] for row in selection['rejected']), selection)
            scores = [entry['score'] for entry in selection['selected']]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertLessEqual(len(scores), 8)
            rejected_child = nodes['left']['expected']['treatment']['simulation_identity']
            self.assertNotIn(rejected_child, [row['expression_hash'] for row in selection['seed_rows']])
        self.assertEqual(len(self.transport.posted), 30, '15 distinct measured identities per lane; reused parents cost zero')
        self.assertEqual(len(self.transport.posted), len(set(self.transport.posted)))
        self.assertEqual(read_daily_budget(self.runs[0])['used'], len(self.transport.posted))
        self.assertEqual(self.fixture.runner.call_count, 2)
        calls = self.transport.calls
        checks = [(i, path) for i, (method, path) in enumerate(calls) if path.endswith('/check')]
        self.assertFalse(checks, 'Every measured sample failed cheap baseline checks; defer correlation GETs')

    def test_baseline_pass_pending_correlations_recover_automatically_and_wait_unqualified(self):
        """Input: real baseline-pass source. Output: bounded known-ID check recovery and paced unqualified wait."""
        from wqb.tree_runtime import continue_tree
        from wqb.daily_simulation_budget import read_daily_budget
        from wqb.runtime_control import CONTROL_ENV
        self.start_group()
        for identity, metrics in self.transport.metrics.items():
            if metrics['fitness'] == .98:
                self.transport.metrics[identity] = dict(metrics, fitness=1.1)
        run = self.runs[0]
        with patch.dict(os.environ, {CONTROL_ENV: str(run)}), patch(
                'wqb.cli.build_client', return_value=self.transport.client):
            for _ in range(8):
                result = continue_tree(run, self.fixture.config, FIXTURE_NOW, enable_live_api=True,
                                       source_batch_runner=self.source_runner)
                if result['next_action'] != 'workflow-auto-continue':
                    break
            self.assertEqual(result['next_action'], 'rate-limit-wait', result)
            self.assertTrue(result['source_bridge']['metadata']['retry_at'])
            calls, posted = list(self.transport.calls), list(self.transport.posted)
            budget = read_daily_budget(run)
            restart = continue_tree(run, self.fixture.config, FIXTURE_NOW, enable_live_api=True,
                                    source_batch_runner=self.source_runner)
            self.assertEqual(restart['next_action'], 'rate-limit-wait', restart)
            self.assertEqual(self.transport.calls, calls, 'Cooldown cannot trigger another GET')
            self.assertEqual(self.transport.posted, posted)
            self.assertEqual(read_daily_budget(run)['used'], budget['used'])
        receipts = list(self.fixture.paths.run_root.glob('http-source-*/stages/backtest/check_recovery.json'))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text())
        self.assertEqual(set(receipt['attempts'].values()), {1})
        self.assertEqual(set(receipt['target_ids']), set(receipt['results']))
        self.assertFalse(result.get('tree_complete', False))
        checks = [(i, path) for i, (_, path) in enumerate(self.transport.calls) if path.endswith('/check')]
        self.assertTrue(checks)
        for index, path in checks:
            self.assertIn(('GET', path.removesuffix('/check')), self.transport.calls[:index])
            detail = self.transport.details[path.split('/')[2]]
            self.assertTrue(all(item['result'] == 'PASS' for item in detail['is']['checks']))
        from wqb.stage_outcomes import checked_research_rows
        rows = [row for source in self.sources for row in checked_research_rows(source)]
        self.assertTrue(all(not row['hard_pass'] for row in rows))
        from datetime import datetime, timedelta, timezone
        from wqb.tree_runtime import verify_tree_results
        future = datetime.now(timezone.utc) + timedelta(minutes=2)
        dispatch = self.transport.request

        def terminal_checks(method, url, **kwargs):
            """Input: fake transport request. Output: later terminal correlation evidence for the same existing IDs."""
            response = dispatch(method, url, **kwargs)
            if method == 'GET' and urlsplit(url).path.endswith('/check'):
                response._content = json.dumps({'is': {'checks': [dict(name=name, result='PASS')
                    for name in ('SELF_CORRELATION', 'PROD_CORRELATION')]}}).encode('utf-8')
            return response

        self.transport.session.request.side_effect = terminal_checks
        with patch.dict(os.environ, {CONTROL_ENV: str(run)}), patch(
                'wqb.cli.build_client', return_value=self.transport.client), patch(
                'wqb.pending_check_recovery.datetime', wraps=datetime) as clock:
            clock.now.return_value = future
            recovered = continue_tree(run, self.fixture.config, future.isoformat(), enable_live_api=True,
                                      source_batch_runner=self.source_runner)
            self.assertEqual(recovered['next_action'], 'workflow-auto-continue', recovered)
            self.assertEqual(self.transport.posted, posted, 'Terminal check recovery must never submit again')
            for _ in range(8):
                recovered = continue_tree(run, self.fixture.config, future.isoformat(), enable_live_api=True,
                                          source_batch_runner=self.source_runner)
                if recovered.get('tree_complete'):
                    break
            self.assertTrue(recovered.get('tree_complete'), recovered)
            self.assertTrue(verify_tree_results(run))

    def test_unknown_post_restart_then_stop_preserves_charge_and_frozen_authority(self):
        """Input: HTTP timeout after POST entry. Output: unknown identities never replay/refund; actual Stop wins."""
        from wqb.daily_simulation_budget import read_daily_budget
        from wqb.research_group import read_group, stop_group
        from wqb.tree_runtime import continue_tree
        self.start_group()
        run = self.runs[0]
        frozen = (run / 'run_manifest.json').read_bytes()
        before = read_group(Path(self.group['group_dir']))
        dispatch = self.transport.request

        def unknown(method, url, **kwargs):
            """Input: HTTP request. Output: timeout only after fake server accepted the immutable POST."""
            dispatch(method, url, **kwargs)
            raise requests.Timeout('Fictional lost POST response; acceptance unknown to client')

        self.transport.session.request.side_effect = unknown
        with self.assertRaisesRegex(RuntimeError, 'submission outcome unknown'):
            continue_tree(run, self.fixture.config, FIXTURE_NOW, enable_live_api=True,
                          source_batch_runner=self.source_runner)
        charged = read_daily_budget(run)
        identities = list(self.transport.posted)
        self.assertEqual(charged['used'], len(identities))
        self.assertGreater(len(identities), 0)
        self.assertLessEqual(len(identities), 8)
        for _ in range(2):
            restart = continue_tree(run, self.fixture.config, FIXTURE_NOW, enable_live_api=True,
                source_batch_runner=lambda *_: self.fail('Unknown POST must not be replayed'))
            self.assertEqual(restart['next_action'], 'maintenance-blocker')
            self.assertEqual(set(restart['source_bridge']['metadata']['uncertain_expression_hashes']), set(identities))
        stop_group(Path(self.group['group_dir']), self.group['request_revision'])
        stopped = continue_tree(run, self.fixture.config, FIXTURE_NOW, enable_live_api=True,
            source_batch_runner=lambda *_: self.fail('Durable Stop must win'))
        self.assertEqual(stopped['next_action'], 'runtime-paused')
        after = read_group(Path(self.group['group_dir']))
        self.assertEqual(after['desired_state'], 'paused')
        from wqb.runtime_control import CONTROL_ENV, RuntimePaused, check_submission_allowed
        with patch.dict(os.environ, {CONTROL_ENV: str(run)}), self.assertRaises(RuntimePaused):
            check_submission_allowed()
        self.assertEqual(after['authority'], before['authority'])
        self.assertEqual(after['recoveries_used'], before['recoveries_used'])
        self.assertGreaterEqual(after['elapsed_seconds'], before['elapsed_seconds'])
        self.assertEqual(read_daily_budget(run)['used'], charged['used'])
        self.assertEqual(read_daily_budget(run)['lifetime_attempts'], charged['lifetime_attempts'])
        self.assertEqual(self.transport.posted, identities)
        self.assertEqual((run / 'run_manifest.json').read_bytes(), frozen)
        self.assertEqual(self.fixture.runner.call_count, 2)

    def test_stop_during_existing_get_recovery_survives_restart_without_post(self):
        """Input: submitted pair and Stop during recovery callback. Output: no recovery POST or resumed authority."""
        from wqb.daily_simulation_budget import read_daily_budget
        from wqb.research_group import read_group, stop_group
        from wqb.tree_runtime import continue_tree
        self.start_group()
        self.defer_poll = True
        run = self.runs[0]
        continue_tree(run, self.fixture.config, FIXTURE_NOW, enable_live_api=True,
                      source_batch_runner=self.source_runner)
        posted = list(self.transport.posted)

        def recovery(source):
            """Input: existing source path str. Output: Stop acknowledgment, never a fabricated completion."""
            self.assertEqual(Path(source), self.sources[0])
            return stop_group(Path(self.group['group_dir']), self.group['request_revision'])

        continue_tree(run, self.fixture.config, FIXTURE_NOW, enable_live_api=True,
                      complete_in_flight_runner=recovery)
        for _ in range(2):
            result = continue_tree(run, self.fixture.config, FIXTURE_NOW, enable_live_api=True,
                complete_in_flight_runner=lambda *_: self.fail('Recovery cannot override Stop'))
            self.assertEqual(result['next_action'], 'runtime-paused')
        self.assertEqual(read_group(Path(self.group['group_dir']))['desired_state'], 'paused')
        from wqb.runtime_control import CONTROL_ENV, RuntimePaused, check_submission_allowed
        for lane in self.runs:
            with patch.dict(os.environ, {CONTROL_ENV: str(lane)}), self.assertRaises(RuntimePaused):
                check_submission_allowed()
        self.assertEqual(self.transport.posted, posted)
        self.assertEqual(read_daily_budget(run)['used'], len(posted))
        self.assertEqual(self.fixture.runner.call_count, 2)

    def test_stop_during_second_initial_plan_is_durable_and_not_replayed(self):
        """Input: Stop from second model transport. Output: paused N2 group; restart never calls a third model."""
        from wqb.research_group import group_for_run, read_group, stop_group
        from wqb.initial_research_planning import TASK_PATH
        stopped = []

        def planning(brief):
            """Input: certified brief dict. Output: valid offline plan after an optional persisted Stop."""
            if self.fixture.runner.call_count == 2:
                group = group_for_run(Path(brief['worker_context']['run_dir']))
                stopped.append(stop_group(Path(group['group_dir']), group['request_revision']))
            return four_root_answer(self.fixture, brief)

        self.fixture.runner.side_effect = planning
        first = self.fixture.prepare()
        self.assertEqual(first['status'], 'blocked')
        group = read_group(Path(stopped[0]['group_dir']))
        self.assertEqual(group['desired_state'], 'paused')
        self.assertEqual(group['request_revision'], stopped[0]['request_revision'])
        self.assertEqual(len(group['lanes']), 2)
        self.assertEqual(self.fixture.prepare()['status'], 'blocked')
        self.assertEqual(self.fixture.runner.call_count, 2)
        self.assertFalse((self.fixture.paths.run_root / 'active_research_group.json').exists())
        first_run = self.fixture.paths.run_root / group['lanes'][0]['run_id']
        self.assertEqual(json.loads((first_run / TASK_PATH).read_text())['status'], 'completed')
        self.assertFalse(any((self.fixture.paths.run_root / lane['run_id'] / 'runtime/group_worker.json').exists()
                             for lane in group['lanes']))

    def test_n2_has_four_genuine_roots_and_frozen_depth_two_before_http(self):
        """Input: source-backed fixture. Output: real N2 frozen trees; no synthetic stage receipts."""
        from wqb.research_tree import _load
        prepared = self.fixture.prepare()
        self.assertEqual(prepared['status'], 'completed', prepared)
        self.assertEqual(self.fixture.runner.call_count, 2)
        for lane in prepared['group']['lanes']:
            tree, _ = _load(self.fixture.paths.run_root / lane['run_id'])
            self.assertEqual(len(tree['tree']['roots']), 4)
            self.assertEqual(len(tree['tree']['nodes']), 8)
            self.assertEqual(tree['tree']['limits']['max_depth'], 2)


class PreplannedResearchAcceptanceTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: fixed default budget clock; explicit rollover timestamps remain effective."""
        from wqb import daily_simulation_budget
        clock = daily_simulation_budget._clock
        budget_clock = patch.object(daily_simulation_budget, '_clock',
                                    side_effect=lambda now: clock(now or FIXTURE_NOW))
        budget_clock.start()
        self.addCleanup(budget_clock.stop)

    def test_daily_rollover_releases_frozen_pair_without_refund_or_model_call(self):
        """Input: none. Output: None; next day funds the same pair while retaining lifetime usage and authority."""
        from tests.test_preplanned_start import PreplannedStartTests
        from wqb.daily_simulation_budget import charge_daily_budget, read_daily_budget
        from wqb.research_group_driver import initialize_group_runtime
        from wqb.research_group import resume_group, read_group
        from wqb.runtime_control import request_runtime_state
        from wqb.tree_runtime import continue_tree
        fixture = PreplannedStartTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.paths.project_root = fixture.root
        fixture.paths.workflow_root = Path(__file__).resolve().parents[1]
        fixture.authority['enable_live_api'] = True
        prepared = fixture.prepare()
        group = initialize_group_runtime(fixture.paths, prepared['group'])
        run = fixture.paths.run_root / group['lanes'][0]['run_id']
        request_runtime_state(run, 'running')
        group = resume_group(Path(group['group_dir']), group['request_revision'])
        charge_daily_budget(run, 3999, 'fixture-history')
        waiting = continue_tree(run, fixture.config, None)
        self.assertEqual(waiting['next_action'], 'daily-budget-wait', waiting)
        reset = waiting['daily_simulation_budget']['next_reset_at']
        handoffs = []
        def execute(config, metadata):
            """Input: frozen source config/metadata. Output: fake acknowledgement; no POST or worker."""
            handoffs.append(config)
            return dict(status='fixture-handoff-only')
        with patch('wqb.daily_simulation_budget.read_daily_budget',
                   side_effect=lambda owner, now=None: read_daily_budget(owner, now or reset)):
            resumed = continue_tree(run, fixture.config, reset, enable_live_api=True, source_batch_runner=execute)
        self.assertEqual(resumed['next_action'], 'workflow-auto-continue', resumed)
        self.assertEqual(len(handoffs), 1)
        self.assertEqual(len(handoffs[0]['scheduled_hypotheses']), 2)
        self.assertEqual(read_daily_budget(run, reset)['remaining'], 4000)
        self.assertEqual(read_daily_budget(run, reset)['lifetime_attempts'], 3999)
        self.assertEqual(fixture.runner.call_count, 1)
        self.assertEqual(read_group(Path(group['group_dir']))['authority'], group['authority'])

    def test_incomplete_pair_daily_wait_is_driver_compatible_and_stop_interrupts(self):
        from tests.test_preplanned_start import PreplannedStartTests
        from wqb.daily_simulation_budget import charge_daily_budget
        from wqb.research_group_driver import initialize_group_runtime
        from wqb.research_group import resume_group, stop_group
        from wqb.runtime_control import request_runtime_state
        from wqb.tree_runtime import continue_tree
        from wqb.workflow_driver import run_workflow_driver
        fixture = PreplannedStartTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.paths.project_root = fixture.root
        fixture.paths.workflow_root = Path(__file__).resolve().parents[1]
        fixture.authority['enable_live_api'] = True
        prepared = fixture.prepare()
        self.assertEqual(prepared['status'], 'completed', prepared)
        group = initialize_group_runtime(fixture.paths, prepared['group'])
        run = fixture.paths.run_root / group['lanes'][0]['run_id']
        request_runtime_state(run, 'running')
        group = resume_group(Path(group['group_dir']), group['request_revision'])
        charge_daily_budget(run, 3999, 'fixture-history')
        initial = dict(active=True, run_dir=str(run), status='running', current_stage='scout_seed')
        def step():
            """Input: none. Output: actual tree wait adapted to existing driver envelope, no fake transport."""
            return {**initial, **continue_tree(run, fixture.config, FIXTURE_NOW)}
        waiting = step()
        self.assertEqual(waiting['next_action'], 'daily-budget-wait', waiting)
        self.assertEqual(waiting['daily_simulation_budget']['remaining'], 1)
        self.assertEqual(waiting['required_pair_count'], 2)
        def stop(_seconds):
            """Input: wait slice float. Output: durable group Stop without sleeping or advancing authority."""
            stop_group(Path(group['group_dir']), group['request_revision'])
        result = run_workflow_driver(fixture.paths, dict(bound_group_lane=str(run)), step=step,
            status_reader=lambda: initial, now_func=lambda: FIXTURE_NOW, sleep_func=stop)
        self.assertEqual(result['runtime_status'], 'paused')

    def test_report_scope_is_comparable_without_fabricating_capture_timestamp(self):
        from tests.test_preplanned_start import PreplannedStartTests
        from wqb.research_tree import _load, _measurements
        from wqb.tree_runtime import measured_row
        from wqb.experiment_tree import route_pair
        fixture = PreplannedStartTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        prepared = fixture.prepare()
        self.assertEqual(prepared['status'], 'completed', prepared)
        run = fixture.paths.run_root / prepared['group']['lanes'][0]['run_id']
        tree, _ = _load(run)
        node = tree['tree']['nodes'][0]
        rows = []
        for expected in node['expected'].values():
            row = dict(status='CHECKED', alpha_id=expected['simulation_identity'][:12],
                expression_hash=expected['simulation_identity'], expression=expected['expression'],
                settings=expected['settings'], hard_pass=False, failed=['LOW_FITNESS'], pending=[],
                metrics=dict(sharpe=1.6, fitness=.8, returns=.1, turnover=.2,
                             startDate='2020-01-01', endDate='2025-01-01'))
            rows.append(measured_row(row, run.name))
        self.assertNotIn('as_of', rows[0]['scope'])
        self.assertEqual(route_pair(node, _measurements(rows))['status'], 'finished')

    def test_two_lanes_use_frozen_plans_shared_accounting_and_no_late_model(self):
        from tests.test_preplanned_start import PreplannedStartTests
        from tests.test_group_runtime_integration import transport
        from wqb import tree_runtime
        from wqb.cli import simulation_identity_hash
        from wqb.daily_simulation_budget import read_daily_budget
        from wqb.research_group import resume_group, stop_group
        from wqb.research_group_driver import initialize_group_runtime
        from wqb.research_seed_stage import prepare_seed_selection
        from wqb.runtime_control import CONTROL_ENV, request_runtime_state
        from wqb.simulator import submit_multisimulation
        fixture = PreplannedStartTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.add_lane(1)
        fixture.config['parallel_workflows'] = 2
        fixture.authority['enable_live_api'] = True
        fixture.paths.project_root = fixture.root
        fixture.paths.workflow_root = Path(__file__).resolve().parents[1]
        fixture.runner.side_effect = fixture.answer_for_brief
        prepared = fixture.prepare()
        self.assertEqual(prepared['status'], 'completed', prepared)
        self.assertEqual(fixture.runner.call_count, 2)
        group = initialize_group_runtime(fixture.paths, prepared['group'])
        for lane in group['lanes']:
            request_runtime_state(fixture.paths.run_root / lane['run_id'], 'running')
        group = resume_group(Path(group['group_dir']), group['request_revision'])
        attempts = []
        def source_runner(config, metadata):
            """Input: exact frozen tree candidates. Output: fake-source result after real bounded POST accounting."""
            run = Path(config['active_workflow_run_dir'])
            candidates = config['scheduled_hypotheses']
            client, session = transport()
            payloads = [dict(type='REGULAR', regular=row['bound_expression'], settings=row['settings']) for row in candidates]
            with patch.dict(os.environ, {CONTROL_ENV: str(run)}):
                submit_multisimulation(client, payloads)
            self.assertEqual(session.request.call_count, 1)
            source = run.parent / ('fixture-source-' + run.name)
            source.mkdir()
            (source / 'run_meta.jsonl').write_text(json.dumps(dict(ai_plan_receipt=config['ai_plan_receipt'],
                research_round_id=config['research_round_id']))+'\n')
            rows = []
            for index, candidate in enumerate(candidates):
                identity = simulation_identity_hash(candidate['bound_expression'], candidate['settings'])
                rows.append(dict(status='CHECKED', alpha_id='fixture-' + identity[:12], expression_hash=identity,
                    expression=candidate['bound_expression'], settings=deepcopy(candidate['settings']),
                    hard_pass=False, failed=['LOW_FITNESS'], pending=['SELF_CORRELATION', 'PROD_CORRELATION'],
                    metrics=dict(sharpe=1.5 + index*.1, fitness=.8 + index*.1, returns=.1, turnover=.2,
                                 startDate='2020-01-01', endDate='2025-01-01')))
            (source / 'all_alphas.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            (source / 'simulation_events.jsonl').write_text(''.join(json.dumps(dict(
                event='CHECKED', expression_hash=row['expression_hash']))+'\n' for row in rows))
            attempts.extend(row['expression_hash'] for row in rows)
            return dict(run_dir=str(source), status='completed')
        for lane in group['lanes']:
            run = fixture.paths.run_root / lane['run_id']
            first = tree_runtime.continue_tree(run, fixture.config, FIXTURE_NOW,
                enable_live_api=True, source_batch_runner=source_runner)
            self.assertEqual(first['next_action'], 'workflow-auto-continue', first)
            final = tree_runtime.continue_tree(run, fixture.config, '2026-10-23T00:00:01Z')
            self.assertTrue(final.get('tree_complete'), final)
            tree_runtime.verify_tree_results(run)
            selected = prepare_seed_selection(run, tree_runtime.checked_research_rows(run))
            self.assertTrue(selected['selected'], selected)
            self.assertFalse(selected['submission_qualified'])
        self.assertEqual(len(attempts), 4)
        self.assertEqual(len(set(attempts)), 4)
        self.assertEqual(read_daily_budget(run)['used'], 4)
        self.assertEqual(fixture.runner.call_count, 2)
        stop_group(Path(group['group_dir']), group['request_revision'])
        stopped = tree_runtime.continue_tree(run, fixture.config, '2026-10-23T00:00:02Z',
            enable_live_api=True, source_batch_runner=lambda *_: self.fail('Stop must win'))
        self.assertEqual(stopped['next_action'], 'runtime-paused')


if __name__ == '__main__':
    unittest.main()
