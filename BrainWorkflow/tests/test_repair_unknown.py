import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from wqb.repair_scheduler import execute_repair_round
from tests import test_repair_runtime as runtime_fixtures


def fixture(root):
    """Input: temp run Path. Output: source Path. Bind an old submitted attempt and exact poll404."""
    parent = {'alpha_id': 'p', 'expression_hash': 'parent-hash', 'benchmark_label': 'repairable_signal'}
    source = root / 'all_alphas.jsonl'
    source.write_text(json.dumps(parent) + '\n')
    subrun = root / 'stages/repair/parents/p-parent-hash'
    subrun.mkdir(parents=True)
    variant = {'expression': '-rank(cash)', 'settings': {'decay': 4},
               'parent_alpha_id': 'p', 'parent_expression_hash': 'parent-hash'}
    variant['expression_hash'] = hashlib.sha256(json.dumps([variant['expression'], variant['settings']], sort_keys=True).encode()).hexdigest()
    (subrun / 'repair_plan.json').write_text(json.dumps({'parent_alpha_id': 'p',
        'parent_expression_hash': 'parent-hash', 'maximum': 1, 'variants': [variant]}))
    (subrun / 'simulation_events.jsonl').write_text(json.dumps({'event': 'SUBMITTED',
        'progress_url': 'https://api.worldquantbrain.com/simulations/original', **variant}) + '\n')
    receipt = {'run_id': root.name, 'max_simulations': 1, 'scheduler_version': 1,
        'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'last_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'status': 'paused', 'recovery_eligible': False, 'parent_keys': [['p', 'parent-hash']],
        'stopped_parents': [], 'attempts': [{'parent_alpha_id': 'p', 'parent_expression_hash': 'parent-hash',
            'phase': 'blocked', 'max_simulations': 1, 'actions': [], 'legacy': True, 'source_run_dir': str(subrun),
            'blocker': 'RuntimeError: repair poll terminal HTTP 404; preserve submitted identity'}]}
    (root / 'stages/repair/repair_execution.json').write_text(json.dumps(receipt))
    return source


class RepairUnknownTests(unittest.TestCase):
    def test_foreign_completion_lineage_cannot_recover_original_attempt(self):
        from wqb.repair_unknown import local_completion_source
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            subrun = root / 'stages/repair/parents/p-parent-hash'
            event = json.loads((subrun / 'simulation_events.jsonl').read_text())
            with (subrun / 'simulation_events.jsonl').open('a') as handle:
                handle.write(json.dumps(event | {'event': 'SIMULATION_COMPLETED', 'alpha_id': 'known',
                    'parent_alpha_id': 'foreign', 'parent_expression_hash': 'foreign-hash'}) + '\n')
            attempt = json.loads((root / 'stages/repair/repair_execution.json').read_text())['attempts'][0]
            self.assertIsNone(local_completion_source(root, attempt))

    def test_local_completion_is_recovered_instead_of_quarantined(self):
        from wqb.repair_unknown import local_completion_source
        from tests.test_workflow_stage_outcomes import checked_alpha
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            subrun = root / 'stages/repair/parents/p-parent-hash'
            variant = json.loads((subrun / 'repair_plan.json').read_text())['variants'][0]
            with (subrun / 'simulation_events.jsonl').open('a') as handle:
                handle.write(json.dumps({'event': 'SIMULATION_COMPLETED', 'alpha_id': 'known', **variant}) + '\n')
            attempt = json.loads((root / 'stages/repair/repair_execution.json').read_text())['attempts'][0]
            self.assertEqual(local_completion_source(root, attempt), subrun.resolve())
            executor = Mock(return_value=[checked_alpha('weak', alpha_id='known', **variant)])
            result = execute_repair_round(root, {'rows': [json.loads(source.read_text())]}, executor, 1)
            self.assertEqual(result['status'], 'completed', result.get('blocker'))
            self.assertEqual(result['attempts'][0]['phase'], 'checked')
            self.assertEqual(executor.call_count, 1)
            executor.prepare.assert_not_called()
            self.assertFalse((subrun / 'result_unknown.json').exists())

    def test_adapter_handles_mixed_cached_collision_and_poll404(self):
        import shutil
        from tests import test_repair_import_recovery as fixtures
        from tests.test_workflow_stage_outcomes import checked_alpha
        from wqb.workflow_stage_adapters import advance_post_schedule_stage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'run'
            root.mkdir()
            receipt, _ = fixtures.fixture(root)
            aux = Path(directory) / 'aux'
            aux.mkdir()
            fixture(aux)
            unknown = json.loads((aux / 'stages/repair/repair_execution.json').read_text())['attempts'][0]
            target = root / 'stages/repair/parents/p-parent-hash'
            shutil.copytree(Path(unknown['source_run_dir']), target)
            unknown['source_run_dir'] = str(target)
            source = root / 'all_alphas.jsonl'
            with source.open('a') as handle:
                handle.write(json.dumps(checked_alpha(alpha_id='p', expression_hash='parent-hash')) + '\n')
            receipt.update(max_simulations=2, last_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
            receipt['attempts'].append(unknown)
            receipt['parent_keys'].append(['p', 'parent-hash'])
            (root / 'stages/repair/repair_execution.json').write_text(json.dumps(receipt))
            executor = Mock(supports_ai_planning=True, supports_durable_recovery=True)
            result = advance_post_schedule_stage(root, 'repair', repair_executor=executor, repair_max_simulations=2)
            self.assertEqual(result['status'], 'completed', result.get('blocker'))
            executor.assert_not_called()
            executor.prepare.assert_not_called()

    def test_unknown_source_is_bound_to_attempt_variant(self):
        from wqb.repair_unknown import quarantine_source
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            receipt = json.loads((root / 'stages/repair/repair_execution.json').read_text())
            attempt = receipt['attempts'][0]
            attempt['legacy'] = False
            attempt['plan'] = {'variants': [{'expression_hash': 'different-iteration'}]}
            self.assertIsNone(quarantine_source(root, attempt))

    def test_persisted_unknown_shortcuts_parent_settings_authentication(self):
        from wqb.repair_unknown import record_unknown
        from wqb.repair_runtime import RepairRuntimeExecutor, RepairResultUnknown
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            record_unknown(root / 'stages/repair/parents/p-parent-hash', 'p', 'parent-hash')
            executor = RepairRuntimeExecutor({'allow_parent_settings_recovery': True}, enable_live_api=True)
            with patch('wqb.cli.require_readiness_gate'), patch('wqb.cli.build_client',
                    side_effect=AssertionError('unknown result must not authenticate')) as client:
                with self.assertRaises(RepairResultUnknown):
                    executor(root, {'alpha_id': 'p', 'expression_hash': 'parent-hash', 'expression': 'rank(cash)'},
                        [{'action_type': 'flip_direction'}], 1)
                client.assert_not_called()

    def test_poll404_is_distinct_from_auth_check404_and429(self):
        import requests
        from wqb.repair_runtime import _classify_get_failure, RepairResultUnknown, RepairRateLimited
        for phase, status in (('poll', 404), ('check', 404), ('authentication', 404), ('poll', 429)):
            with self.subTest(phase=phase, status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture(root)
                subrun = root / 'stages/repair/parents/p-parent-hash'
                variant = json.loads((subrun / 'repair_plan.json').read_text())['variants'][0]
                response = requests.Response()
                response.status_code = status
                response.headers['Retry-After'] = '60'
                error = requests.HTTPError('recorded failure', response=response)
                if phase != 'poll':
                    with self.assertRaises(RuntimeError):
                        _classify_get_failure(subrun, variant, error, phase)
                    self.assertFalse((subrun / 'result_unknown.json').exists())
                else:
                    result = _classify_get_failure(subrun, variant, error, phase)
                    self.assertIsInstance(result, RepairResultUnknown if status == 404 else RepairRateLimited)

    def test_missing_or_completed_or_changed_identity_cannot_be_quarantined(self):
        from wqb.repair_unknown import quarantine_source
        for kind in ('missing', 'completed', 'bad_hash', 'outside', 'duplicate', 'stored_receipt'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture(root)
                receipt = json.loads((root / 'stages/repair/repair_execution.json').read_text())
                attempt = receipt['attempts'][0]
                subrun = Path(attempt['source_run_dir'])
                path = subrun / 'simulation_events.jsonl'
                event = json.loads(path.read_text())
                if kind == 'missing': path.write_text('')
                elif kind == 'completed': path.write_text(json.dumps(event) + '\n' + json.dumps(event | {'event': 'SIMULATION_COMPLETED', 'alpha_id': 'known'}) + '\n')
                elif kind == 'bad_hash': path.write_text(json.dumps(event | {'expression_hash': 'wrong'}) + '\n')
                elif kind == 'outside': attempt['source_run_dir'] = str(root.parent)
                elif kind == 'stored_receipt': (subrun / 'result_unknown.json').write_text('{}')
                else: path.write_text(json.dumps(event) + '\n' + json.dumps(event) + '\n')
                self.assertIsNone(quarantine_source(root, attempt))

    def test_isolated_attempt_does_not_block_independent_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            parent = json.loads(source.read_text())
            other = {'alpha_id': 'q', 'expression_hash': 'q-hash', 'benchmark_label': 'repairable_signal'}
            source.write_text(json.dumps(parent) + '\n' + json.dumps(other) + '\n')
            path = root / 'stages/repair/repair_execution.json'
            receipt = json.loads(path.read_text())
            receipt.update(max_simulations=2, last_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
            receipt['parent_keys'].append(['q', 'q-hash'])
            path.write_text(json.dumps(receipt))
            executor = Mock()
            executor.prepare.return_value = {'variants': [], 'evidence_digest': 'independent-stop'}
            result = execute_repair_round(root, {'rows': [parent, other]}, executor, 2)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['budget_reserved'], 1)
            self.assertIn(['q', 'q-hash'], result['stopped_parents'])
            self.assertNotIn(['p', 'parent-hash'], result['stopped_parents'])
            executor.assert_not_called()
            self.assertEqual(executor.prepare.call_count, 1)

    def test_verified_404_is_isolated_without_retry_or_refund_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            original = source.read_bytes()
            executor = Mock()
            for _ in range(2):
                result = execute_repair_round(root, {'rows': [json.loads(original)]}, executor, 1)
                self.assertEqual(result['status'], 'completed', result.get('blocker'))
                self.assertEqual(result['attempts'][0]['phase'], 'result_unknown')
                self.assertEqual(result['budget_reserved'], 1)
                self.assertEqual(result['unknown_result_count'], 1)
                self.assertEqual(result['attempts'][0]['children'], [])
                self.assertNotIn(['p', 'parent-hash'], result['stopped_parents'])
            executor.assert_not_called()
            executor.prepare.assert_not_called()
            self.assertEqual(source.read_bytes(), original)
            evidence = root / 'stages/repair/parents/p-parent-hash/result_unknown.json'
            evidence.write_text('{}')
            blocked = execute_repair_round(root, {'rows': [json.loads(original)]}, executor, 1)
            self.assertEqual(blocked['status'], 'paused')
            self.assertIn('isolation evidence', blocked['blocker'])


class RepairUnknownRuntimeIntegrationTests(unittest.TestCase):
    setUp = runtime_fixtures.RepairRuntimeTests.setUp

    def test_new_ai_simulation_poll404_is_durable_without_second_post_or_poll(self):
        import requests
        from wqb.repair_runtime import RepairRuntimeExecutor
        parent = runtime_fixtures.parent_row()
        parent.update(benchmark_label='repairable_signal', metrics={'fitness': .5})
        (self.root / 'all_alphas.jsonl').write_text(json.dumps(parent) + '\n')
        response = requests.Response()
        response.status_code = 404
        self.poll.side_effect = requests.HTTPError('progress unavailable', response=response)
        decision = {'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash'],
            'diagnosis': 'Low fitness.', 'economic_rationale': 'Persistence.', 'hypothesis': 'Smooth noise.',
            'expected_improvement': 'fitness', 'risks': 'Lag.', 'action': 'test', 'edit': 'decay', 'value': 8,
            'target_metric': 'fitness', 'target_direction': 'increase',
            'falsification': 'Fitness unchanged.', 'applicability': 'Same signal.'}
        executor = RepairRuntimeExecutor({'ai_executor_argv': ['fake', '{input}', '{output}']}, enable_live_api=True)
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value={
                'status': 'completed', 'summary': 'One test.', 'decision': decision}) as model:
            first = execute_repair_round(self.root, {'rows': [parent]}, executor, 1)
            second = execute_repair_round(self.root, {'rows': [parent]}, executor, 1)
        self.assertEqual(first['status'], 'completed', first.get('blocker'))
        self.assertEqual(second['unknown_result_count'], 1)
        self.assertEqual(second['budget_reserved'], 1)
        self.assertEqual(self.submit.call_count, 1)
        self.assertEqual(self.poll.call_count, 1)
        self.assertEqual(model.call_count, 1)
        self.assertFalse(second['attempts'][0]['children'])
