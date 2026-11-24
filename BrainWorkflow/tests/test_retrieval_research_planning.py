"""Durable one-task retrieval design, no model or platform services."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class RetrievalResearchPlanningTests(unittest.TestCase):
    def test_selected_history_rejects_changed_missing_or_duplicate_groups(self):
        """Input: selected historical identities. Output: exact-view rejection instead of a replacement observation."""
        from wqb.retrieval_research_planning import _selected_history
        machine = self.root / 'machine'
        machine.mkdir()
        path = machine / 'mechanism_evidence.json'
        raw = json.dumps(dict(input_digest='original', groups=[dict(group_id='g')])).encode()
        path.write_bytes(raw)
        task = dict(identity=dict(knowledge_root=str(self.root), generation='test', scope=self.scope))
        ref = dict(group_id='g', view_sha256=hashlib.sha256(raw).hexdigest())
        with patch('wqb.research_query_index.validate_query_generation'):
            self.assertEqual(_selected_history(task, [ref])['groups'], [dict(group_id='g')])
            with self.assertRaisesRegex(ValueError, 'duplicated'):
                _selected_history(task, [ref, ref])
            with self.assertRaisesRegex(ValueError, 'missing'):
                _selected_history(task, [dict(ref, group_id='absent')])
            path.write_bytes(raw + b'\n')
            with self.assertRaisesRegex(ValueError, 'changed'):
                _selected_history(task, [ref])
            path.unlink()
            with self.assertRaises(OSError):
                _selected_history(task, [ref])

    @unittest.skipUnless(os.name == 'nt', 'Windows inherited-handle behavior')
    def test_windowed_stdout_emits_json_into_inherited_pipe(self):
        """Input: child with no Python stdout. Output: complete UTF-8 JSON via inherited Windows pipe."""
        child = subprocess.run([sys.executable, '-B', '-c',
            "import sys; sys.stdout=None; from wqb.retrieval_research_planning import emit_query_result; "
            "emit_query_result({'status':'ok','value':'\\u6570\\u636e'})"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        self.assertEqual(child.returncode, 0, child.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(json.loads(child.stdout), dict(status='ok', value='\u6570\u636e'))

    def setUp(self):
        """Input: TestCase. Output: temporary task owner and frozen input dictionaries."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.job = self.root / 'preparation'
        self.scope = dict(instrument_type='EQUITY', region='ALL', delay=1, universe='LARGE',
                          as_of='2026-11-24T01:00:00+00:00')
        self.config = dict(plan_depth=2, initial_hypotheses=4,
                           measurement_period=dict(start='2014-01-01', end='2023-12-29'))
        self.answer = dict(summary='A temporary offline proposal.', selection=[dict(dataset_id='d', field_id='f')],
                           designs=[], tree=dict(roots=[], nodes=[]), data_characteristics=[])

    def invoke(self, model, check=lambda: None):
        """Input: injected offline model/cancellation callback. Output: task result without real query/compile work."""
        from wqb import retrieval_research_planning as planning
        with patch.object(planning, '_generation', return_value='g' * 64), \
                patch.object(planning, '_resolve_answer', return_value=dict(resources={'selected': True})), \
                patch.object(planning, 'design_schema', return_value={'type': 'object'}):
            return planning.prepare_retrieval_design(self.job, self.root, self.scope,
                {'option_id': 'option', 'title': 'A test objective'}, self.config,
                model_runner=model, check_cancelled=check)

    def test_task_is_saved_before_single_model_call_and_reused(self):
        from wqb import retrieval_research_planning as planning
        calls = []

        def model(brief):
            """Input: compact brief. Output: proposal; assert running state precedes invocation."""
            calls.append(brief)
            self.assertEqual(planning.read_design_task(self.job)['status'], 'running')
            self.assertNotIn('source_texts', brief)
            return deepcopy(self.answer)

        first = self.invoke(model)
        second = self.invoke(lambda _: self.fail('completed task replayed model'))
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(len(calls), 1)

    def test_unknown_model_outcome_never_replays(self):
        def lost(_):
            """Input: brief. Output: never; emulate transport outcome loss."""
            raise TimeoutError('outcome unknown')

        self.assertEqual(self.invoke(lost)['status'], 'blocked')
        result = self.invoke(lambda _: self.fail('unknown task replayed'))
        self.assertIn('unknown', result['reason'])

    def test_stop_before_dispatch_never_calls_model(self):
        def stop():
            """Input: none. Output: never; original Start is stopped."""
            raise InterruptedError('stopped')

        with self.assertRaises(InterruptedError):
            self.invoke(lambda _: self.fail('model called after Stop'), check=stop)

    def test_changed_scope_does_not_reuse_task_or_call_model(self):
        self.invoke(lambda _: deepcopy(self.answer))
        self.scope['universe'] = 'DIFFERENT'
        with self.assertRaisesRegex(ValueError, 'identity|input'):
            self.invoke(lambda _: self.fail('changed input dispatched'))

    def test_invalid_answer_is_saved_before_failure_and_not_regenerated(self):
        from wqb import retrieval_research_planning as planning
        with patch.object(planning, '_resolve_answer', side_effect=ValueError('invalid tree')):
            # invoke() supplies the normal resolver; patch directly for this case.
            with patch.object(planning, '_generation', return_value='g' * 64), \
                    patch.object(planning, 'design_schema', return_value={'type': 'object'}):
                result = planning.prepare_retrieval_design(self.job, self.root, self.scope,
                    {'option_id': 'option', 'title': 'A test objective'}, self.config,
                    model_runner=lambda _: deepcopy(self.answer), check_cancelled=lambda: None)
        self.assertEqual(result['status'], 'blocked')

        self.assertEqual(planning.read_design_task(self.job)['answer'], self.answer)
        result = self.invoke(lambda _: self.fail('invalid outcome regenerated'))
        self.assertEqual(result['status'], 'blocked')

    def test_projection_provides_local_query_command_not_inline_raw(self):
        from wqb import retrieval_research_planning as planning
        seen = []

        def model(_):
            """Input: brief. Output: fake answer after reading the authenticated compact projection."""
            task = planning.read_design_task(self.job)
            with patch.object(planning, 'authenticated_design_task', return_value=task):
                projection = planning.retrieval_projection(self.job)
            seen.append(projection)
            return deepcopy(self.answer)

        self.invoke(model)
        self.assertIn('query', seen[0]['query_command'])
        self.assertIn('research_query.py', ' '.join(seen[0]['query_command']))
        self.assertNotIn('source_texts', seen[0])

    def test_query_after_completed_task_is_not_allowed(self):
        from wqb import retrieval_research_planning as planning
        self.invoke(lambda _: deepcopy(self.answer))
        with self.assertRaisesRegex(ValueError, 'running'):
            planning.query_design_task(self.job, 'fields', {})

    def test_malformed_transport_request_cannot_kill_owner_service(self):
        """Input: valid local channel with malformed JSON envelope. Output: explicit error and live service."""
        from multiprocessing.connection import Client
        from wqb.research_tool_service import BROKER_PATH

        def model(_):
            """Input: brief. Output: dummy proposal after malformed-envelope recovery."""
            descriptor = json.loads((self.job / BROKER_PATH).read_text(encoding='utf-8'))
            address = descriptor['address']
            if descriptor['family'] == 'AF_INET':
                address = tuple(address)
            with Client(address, family=descriptor['family'],
                        authkey=bytes.fromhex(descriptor['authkey'])) as connection:
                connection.send_bytes(b'[]')
                self.assertTrue(connection.poll(3), 'malformed request killed owner without a response')
                reply = json.loads(connection.recv_bytes())
                self.assertEqual(reply['error'], 'ValueError')
            return deepcopy(self.answer)

        self.assertEqual(self.invoke(model)['status'], 'completed')
