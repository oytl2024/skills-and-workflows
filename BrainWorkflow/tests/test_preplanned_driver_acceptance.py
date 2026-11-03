"""Production preplanned lane acceptance with fictional knowledge and HTTP only."""

from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import hashlib
import os
import threading
import time
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from tests import test_preplanned_research_acceptance as acceptance


class PreplannedDriverAcceptanceTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: two source-backed frozen lanes and finite project decay edits."""
        self.case = acceptance.IntegratedFourRootAcceptanceTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        fixture = self.case.fixture
        self.certify_resources()
        fixture.config['repair_search_policy'] = dict(compile_version=1, rules=[dict(
            rule_id='offline-finite-decay', edit='decay', effect='smoothing', priority=0,
            target_metric='turnover', target_direction='decrease', grid=[8, 16],
            requires=dict(matrix_observation=True), evidence_refs=[])])
        self.case.start_group()
        self.transport = self.case.transport
        self.write_readiness_inputs()
        dispatch = self.transport.request

        def request(method, url, **kwargs):
            """Input: real HTTP request. Output: fake auth/measurements for frozen expressions and finite decays only."""
            if method == 'POST' and urlsplit(url).path == '/authentication':
                import requests
                response = requests.Response()
                response.status_code = 201
                response._content = b'{}'
                self.transport.calls.append((method, '/authentication'))
                return response
            if method == 'POST' and urlsplit(url).path == '/simulations':
                from wqb.cli import simulation_identity_hash
                payloads = kwargs['json']
                for payload in payloads if isinstance(payloads, list) else [payloads]:
                    settings = payload['settings']
                    if settings['decay'] in (8, 16):
                        baseline = simulation_identity_hash(payload['regular'], dict(settings, decay=4))
                        metrics = self.transport.metrics[baseline]
                        identity = simulation_identity_hash(payload['regular'], settings)
                        self.transport.metrics[identity] = dict(metrics,
                            turnover=.15 if settings['decay'] == 8 else .1)
            return dispatch(method, url, **kwargs)

        self.transport_errors = []

        def observed_request(method, url, **kwargs):
            """Input: fake HTTP request. Output: unchanged response; retain fixture failures hidden by production safe errors."""
            try:
                return request(method, url, **kwargs)
            except Exception as error:
                import traceback
                self.transport_errors.append(traceback.format_exc())
                raise error

        self.transport.session.request.side_effect = observed_request
        self.transport.session.post.side_effect = lambda url, **kwargs: request('POST', url, **kwargs)
        environment = patch.dict(os.environ, WQB_USERNAME='offline-fixture', WQB_PASSWORD='offline-fixture')
        environment.start()
        self.addCleanup(environment.stop)
        client = patch('wqb.cli.build_client', return_value=self.transport.client)
        client.start()
        self.addCleanup(client.stop)
        process = patch('subprocess.Popen', side_effect=AssertionError('No late model/process allowed'))
        process.start()
        self.addCleanup(process.stop)
        # Only fake HTTP transport pacing is zero; real authority clocks and Stop fences remain active.
        pacing = patch('wqb.research_group_driver.SOURCE_MULTI_CHUNK_SLEEP_SECONDS', 0)
        pacing.start()
        self.addCleanup(pacing.stop)

    def certify_resources(self):
        """Input: fictional lane resources. Output: None; rebuild V2 jobs from exact raw data-field captures."""
        from wqb.semantic_compilation import prepare_design_job
        from wqb.semantic_contracts import SemanticPolicy
        fixture = self.case.fixture
        index = {}
        for number, resource in enumerate(fixture.resources):
            old = resource['field_rows'][0]['source_paths'][0]
            original = json.loads(resource['source_texts'][old])
            text = json.dumps(dict(original['fields'][0], operators=original['operators'])) + '\n'
            path = f'raw/platform/data_fields/offline-{number}/data_fields.jsonl'
            source = dict(path=path, content_hash=hashlib.sha256(text.encode()).hexdigest(),
                captured_at='2026-10-14T00:00:00Z', source_type='platform_data_field_capture',
                source_family='raw/platform/data_fields', contents='Fictional offline field and operator facts',
                update_check='Compare fixture source bytes', compiled_targets=['machine/data_ledger.jsonl'],
                record_count=1, content_status='raw_jsonl')
            for row in resource['field_rows']:
                row['source_paths'] = [path]
            for operator in resource['operator_rows']:
                operator['definition']['evidence_refs'] = [dict(source_path=path, sha256=source['content_hash'],
                    capture_date='2026-10-14', kind='documented', experiment_refs=[])]
            resource.update(resource_contract_version=2, source_index={path: source}, source_texts={path: text})
            resource['evidence_pack'].update(resource_contract_version=2,
                source_index=deepcopy(resource['source_index']), source_texts=deepcopy(resource['source_texts']))
            target = fixture.paths.knowledge_root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8', newline='\n')
            scope = {key: fixture.scope[key] for key in ('instrument_type', 'region', 'delay', 'universe')}
            (target.parent / 'manifest.json').write_text(json.dumps(dict(certification_status='complete',
                generated_at='2026-10-14T00:00:00Z', requested_matrix=[scope])))
            (target.parent / 'scopes.jsonl').write_text(json.dumps(dict(scope=scope,
                status='completed', certification_status='complete')) + '\n')
            index[path] = source
            prepare_design_job(fixture.paths.knowledge_root, resource['evidence_pack'], SemanticPolicy(), resource)
        machine = fixture.paths.knowledge_root / 'machine'
        (machine / 'source_index.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in index.values()))
        (machine / 'data_ledger.jsonl').write_text(''.join(json.dumps(row) + '\n'
            for resource in fixture.resources for row in resource['field_rows']))

    def write_readiness_inputs(self):
        """Input: prepared temporary knowledge. Output: None; index actual fixture ledgers for unmocked readiness."""
        from wqb.benchmark_rules import benchmark_rules_path_for_knowledge
        knowledge = self.case.fixture.paths.knowledge_root
        templates = {}
        for run in self.case.runs:
            snapshot = json.loads((run / 'run_manifest.json').read_text())['start_snapshot']
            templates.update({row['template_id']: row for row in snapshot['template_rows']})
        template_path = knowledge / 'machine/template_library.jsonl'
        template_path.write_text(''.join(json.dumps(row) + '\n' for row in templates.values()))
        (knowledge / 'machine/operator_ledger.jsonl').write_text(''.join(
            json.dumps(row) + '\n' for row in self.case.fixture.resources[0]['operator_rows']))
        activity = knowledge / 'wiki/10_foundations/activity_snapshot.md'
        activity.parent.mkdir(parents=True, exist_ok=True)
        activity.write_text('# Fictional offline activity\n')
        artifacts = dict(data_ledger=knowledge / 'machine/data_ledger.jsonl', template_library=template_path,
            benchmark_rules=benchmark_rules_path_for_knowledge(knowledge), activity_snapshot=activity)
        manifest = [dict(name=name, path=path.relative_to(knowledge).as_posix(),
            updated_at='2026-10-14', max_age_days=90) for name, path in artifacts.items()]
        (knowledge / 'machine/freshness_manifest.json').write_text(json.dumps(manifest))

    def drive(self, run):
        """Input: frozen lane Path. Output: real production driver result, no fake stage or step callbacks."""
        from wqb.research_group_driver import run_group_lane
        with redirect_stdout(StringIO()):
            return run_group_lane(self.case.fixture.paths, Path(self.case.group['group_dir']), run,
                config=dict(instrument_type='EQUITY', language='FASTEXPR', pasteurization='ON',
                    nan_handling='OFF', unit_handling='VERIFY', neutralization='NONE',
                    runtime_max_steps=50, max_alphas_per_round=30))

    def test_n2_real_driver_reaches_real_repair_without_internal_gate_or_late_model(self):
        """Input: N2/four roots/depth2. Output: actual tree, Seed and deterministic runtime Repair artifacts."""
        from wqb.daily_simulation_budget import read_daily_budget
        for run in self.case.runs:
            result = self.drive(run)
            path = run / 'stages/repair/repair_execution.json'
            self.assertTrue(path.exists(), {key: result.get(key) for key in
                ('current_stage', 'status', 'pause_reason', 'runtime_reason', 'source_bridge', 'message')}
                | {'readiness': [json.loads(path.read_text())['issues']
                    for path in run.parent.glob('*/readiness_report.json')]})
            receipt = json.loads(path.read_text())
            self.assertTrue(receipt['attempts'], receipt.get('blocker'))
            self.assertTrue(any(attempt.get('children') for attempt in receipt['attempts']),
                dict(driver=result, transport_errors=self.transport_errors,
                    receipt=receipt, readiness=[json.loads(item.read_text())
                    for item in run.glob('stages/repair/**/readiness_report.json')]))
            selection = json.loads((run / 'stages/scout_seed/seed_selection.json').read_text())
            self.assertTrue(selection['selected'])
            self.assertFalse(selection['submission_qualified'])
            self.assertFalse((run / 'rounds/round-0001/stages/repair').exists(),
                             'A completed frozen tree cannot enter legacy replay rounds')
            self.assertEqual(result['current_stage'], 'complete', result)
            self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(read_daily_budget(self.case.runs[0])['used'], len(self.transport.posted))
        self.assertEqual(len(set(self.transport.posted)), len(self.transport.posted))
        self.assertEqual(self.case.fixture.runner.call_count, 2)
        self.assertFalse(any(path.endswith('/submit') for _, path in self.transport.calls))

    def stop_inside_transport(self, matches):
        """Input: request predicate callable. Output: threads/errors lists; persist real group Stop while request is active."""
        from wqb.research_group import read_group, stop_group
        dispatch = self.transport.session.request.side_effect
        group = Path(self.case.group['group_dir'])
        threads, errors = [], []

        def stop():
            """Input: none. Output: None; use the real Stop fence and retain asynchronous errors."""
            try:
                stop_group(group, read_group(group)['request_revision'])
            except Exception as error:
                errors.append(error)

        def request(method, url, **kwargs):
            """Input: fake HTTP request. Output: real fake response after durable Stop intent, before releasing transport."""
            response = dispatch(method, url, **kwargs)
            if not threads and matches(method, urlsplit(url).path, kwargs):
                thread = threading.Thread(target=stop)
                threads.append(thread)
                thread.start()
                deadline = time.monotonic() + 5
                while read_group(group)['desired_state'] != 'paused':
                    if errors or time.monotonic() >= deadline:
                        self.fail('Stop did not persist while transport was active')
                    time.sleep(.01)
            return response

        self.transport.session.request.side_effect = request
        self.addCleanup(lambda: [thread.join(10) for thread in threads])
        return threads, errors

    def assert_stopped_without_replay(self, run, threads, errors):
        """Input: run Path/Stop threads/error list. Output: assertions for persisted pause, accounting and restart."""
        from wqb.daily_simulation_budget import read_daily_budget
        from wqb.research_group import read_group
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive(), 'Stop acknowledgment must finish after transport returns')
        self.assertTrue(threads, 'The requested in-flight boundary must actually execute')
        self.assertFalse(errors)
        group = Path(self.case.group['group_dir'])
        before = read_group(group)
        self.assertEqual(before['desired_state'], 'paused')
        posted = list(self.transport.posted)
        budget = read_daily_budget(run)
        self.assertEqual(budget['used'], len(posted))
        for _ in range(2):
            self.drive(run)
        after = read_group(group)
        self.assertEqual(after['desired_state'], 'paused')
        self.assertEqual(after['authority'], before['authority'])
        self.assertEqual(after['recoveries_used'], before['recoveries_used'])
        self.assertEqual(self.transport.posted, posted)
        self.assertEqual(read_daily_budget(run)['lifetime_attempts'], budget['lifetime_attempts'])
        self.assertEqual(self.case.fixture.runner.call_count, 2)

    def test_stop_inside_source_post_survives_production_driver_restart(self):
        """Input: Stop before POST response returns. Output: real acknowledgment, preserved charge and no replay."""
        run = self.case.runs[0]
        threads, errors = self.stop_inside_transport(lambda method, path, _: method == 'POST' and path == '/simulations')
        self.drive(run)
        self.assert_stopped_without_replay(run, threads, errors)

    def test_stop_inside_existing_progress_get_survives_production_driver_restart(self):
        """Input: durable in-flight source then Stop inside recovery GET. Output: no new POST and durable pause."""
        from wqb.tree_runtime import continue_tree
        run = self.case.runs[0]
        self.case.defer_poll = True
        continue_tree(run, self.case.fixture.config, acceptance.FIXTURE_NOW,
            enable_live_api=True, source_batch_runner=self.case.source_runner)
        posted = list(self.transport.posted)
        self.assertTrue(posted)
        threads, errors = self.stop_inside_transport(lambda method, path, _: method == 'GET' and path.startswith('/simulations/'))
        self.drive(run)
        self.assert_stopped_without_replay(run, threads, errors)
        self.assertEqual(self.transport.posted, posted)

    def test_stop_inside_real_repair_post_survives_production_driver_restart(self):
        """Input: Stop inside the actual Repair executor's POST. Output: paused original run and no duplicate attempt."""
        run = self.case.runs[0]

        def repair_post(method, path, kwargs):
            """Input: HTTP request fields. Output: bool; only match the finite Repair decay variants."""
            payload = kwargs.get('json', [])
            payloads = payload if isinstance(payload, list) else [payload]
            return method == 'POST' and path == '/simulations' and any(
                item['settings']['decay'] in (8, 16) for item in payloads)

        threads, errors = self.stop_inside_transport(repair_post)
        self.drive(run)
        self.assert_stopped_without_replay(run, threads, errors)
