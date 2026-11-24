"""Offline Console projection of task-owned, sanitized retrieval telemetry."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_console_server import make_paths
from wqb import console_start, console_api
from wqb.retrieval_research_planning import _save
from wqb.semantic_compilation import _digest


class ConsoleRetrievalProgressTests(unittest.TestCase):
    def test_real_console_handoff_projects_nested_lane_activity_before_model_returns(self):
        from tests.test_retrieval_start import RetrievalStartTests
        from tests.test_console_start import PreplannedConsoleStartTests
        from wqb.retrieval_research_planning import read_design_task
        case, host = RetrievalStartTests(), PreplannedConsoleStartTests()
        case.setUp()
        host.setUp()
        self.addCleanup(case.doCleanups)
        self.addCleanup(host.doCleanups)
        case.fixture = host.case
        config = {**case.config, **host.config, 'research_policy': dict(
            preplanned_tree_version=1, execution_package_version=1, retrieval_design_version=1)}
        (host.paths.workflow_root / 'configs/workflow_local.json').write_text(json.dumps(config))
        request = console_start.register_start(host.paths, host.form, 'projection-job')
        seen = []

        def factory(directory, config, check):
            """Input: real owner/config/cancellation. Output: fake model; inspect live Console projection offline."""
            check()
            task = read_design_task(directory)
            progress = {**self.progress, 'input_sha256': task['input_sha256']}
            (directory / 'runtime/retrieval_research_planning/progress.json').write_text(json.dumps(progress))
            row = console_start.read_start_request(host.paths.runs_root)
            projected = console_start.preparation_projection(host.paths, row)
            self.assertEqual(projected.get('tool_progress', {}).get('queries'), 3)
            seen.append(projected)
            return lambda brief: case.model(directory, brief)

        with patch('wqb.retrieval_research_planning.create_retrieval_model_runner', side_effect=factory):
            result = console_start.execute_start(host.paths, host.form, request['request_id'])
        self.assertTrue(result['passed'], result)
        self.assertTrue(seen)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = make_paths(Path(self.tmp.name))
        self.directory = self.paths.runs_root / 'start_preflight/preplanned' / ('b' * 64)
        self.scope = dict(instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000')
        self.identity = dict(knowledge_root=str(self.paths.knowledge_root), scope=self.scope,
            config=dict(retrieval_owner=dict(runs_root=str(self.paths.runs_root), request_id='a' * 32)))
        self.token = _digest(self.identity)
        self.row = dict(request_id='a' * 32, status='preparing', source_intent=console_start._source_intent(self.paths.runs_root),
            selection=dict(scope=self.scope), multiplier_preparation=dict(stage='planning', status='running',
                retrieval_task=dict(directory=str(self.directory), input_sha256=self.token)))
        console_start._write_request(self.paths.runs_root, self.row)
        self.progress = dict(input_sha256=self.token, stage='retrieving', operation='fields', queries=3,
            validations=1, returned_bytes=500, max_queries=64, max_validations=24, max_returned_bytes=1048576,
            activity_at='2026-11-24T01:02:03+00:00', authkey='never expose', arguments='private query')
        self.save()

    def save(self):
        """Input: fixture state. Output: None; write verified task and untrusted telemetry in temporary storage."""
        _save(self.directory, dict(identity=self.identity, input_sha256=self.token, status='running'))
        path = self.directory / 'runtime/retrieval_research_planning/progress.json'
        path.write_text(json.dumps(self.progress), encoding='utf-8')

    def test_projects_only_sanitized_progress_for_original_start_and_task(self):
        before = copy.deepcopy(self.row)
        state = dict(active_workflow={}, runtime_control={}, option_cards=[], start_preparation=self.row)
        result = console_api.project_application(self.paths, state, 'test', 1)['preparation']
        expected = {k: v for k, v in self.progress.items() if k not in {'input_sha256', 'authkey', 'arguments'}}
        self.assertEqual(result['tool_progress'], expected)
        self.assertNotIn('retrieval_task', result)
        self.assertEqual(self.row, before)

    def test_rejects_stale_malformed_and_unbound_telemetry(self):
        for key, value in [('input_sha256', 'wrong'), ('queries', -1), ('queries', True),
                           ('max_queries', 99), ('operation', 'private query'), ('activity_at', 'bad')]:
            with self.subTest(key=key, value=value):
                original = copy.deepcopy(self.progress)
                self.progress[key] = value
                self.save()
                self.assertNotIn('tool_progress', console_start.preparation_projection(self.paths, self.row))
                self.progress = original
        self.save()
        console_start._write_request(self.paths.runs_root, {**self.row, 'status': 'cancelled'})
        self.assertNotIn('tool_progress', console_start.preparation_projection(self.paths, self.row))
        console_start._write_request(self.paths.runs_root, self.row)
        for change in [dict(request_id='c' * 32), dict(source_intent={}), dict(status='cancelled'), dict(status='completed')]:
            with self.subTest(change=change):
                row = {**self.row, **change}
                self.assertNotIn('tool_progress', console_start.preparation_projection(self.paths, row))
        stopped = console_start.preparation_projection(self.paths, {**self.row, 'status': 'cancelled'})
        self.assertEqual(stopped['stage'], 'cancelled')

    def test_whitelists_only_positive_integer_retrieval_limits(self):
        config = self.paths.configuration_root / 'configs/workflow_local.json'
        config.parent.mkdir(parents=True, exist_ok=True)
        limits = dict(retrieval_max_queries=7, retrieval_max_validations=2, retrieval_max_returned_bytes=1234)
        config.write_text(json.dumps({**limits, 'api_key': 'never persist'}))
        loaded = console_start.load_start_config(self.paths)
        self.assertEqual({key: loaded.get(key) for key in limits}, limits)
        self.assertNotIn('api_key', loaded)
        for value in (0, -1, True, 1.5, '7'):
            config.write_text(json.dumps({**limits, 'retrieval_max_queries': value}))
            with self.subTest(value=value), self.assertRaises(ValueError):
                console_start.load_start_config(self.paths)

    def test_old_lane_binding_is_hidden_when_durable_start_moves_to_next_task(self):
        active = copy.deepcopy(self.row)
        active['multiplier_preparation']['retrieval_task']['input_sha256'] = 'next-task'
        console_start._write_request(self.paths.runs_root, active)
        self.assertNotIn('tool_progress', console_start.preparation_projection(self.paths, self.row))

    def test_corrupt_or_out_of_scope_optional_evidence_never_breaks_projection(self):
        for scope in ({**self.scope, 'region': 'KOR'}, {**self.scope, 'instrument_type': 'OTHER'}):
            row = {**self.row, 'selection': dict(scope=scope)}
            self.assertNotIn('tool_progress', console_start.preparation_projection(self.paths, row))
        path = self.directory / 'runtime/retrieval_research_planning/progress.json'
        for raw in ('[]', '{broken', ' ' * (console_start.MAX_PREPARATION_STATE_BYTES + 1)):
            path.write_text(raw)
            self.assertNotIn('tool_progress', console_start.preparation_projection(self.paths, self.row))
        self.save()
        task_path = self.directory / 'runtime/retrieval_research_planning/task.json'
        task = json.loads(task_path.read_text())
        task['status'] = 'completed'
        task_path.write_text(json.dumps(task))
        self.assertNotIn('tool_progress', console_start.preparation_projection(self.paths, self.row))
