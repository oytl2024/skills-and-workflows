"""Offline real planner/scheduler/executor integration; fake platform and model only."""

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_repair_runtime as fixtures
from wqb.repair_runtime import RepairRuntimeExecutor
from wqb.repair_planning import prepare_repair_decision


class AIRepairAcceptanceTests(unittest.TestCase):
    setUp = fixtures.RepairRuntimeTests.setUp

    def test_normalized_neutralization_executes_once_and_preserves_original_judgment(self):
        parent = fixtures.parent_row()
        parent['metrics'] = {'fitness': .5}
        parent['settings'].update(region='USA', delay=1, universe='TOP3000', instrumentType='EQUITY',
            language='FASTEXPR', nanHandling='OFF', pasteurization='ON', unitHandling='VERIFY',
            visualization=False, neutralization='SUBINDUSTRY', decay=4, truncation=.08)
        config = {'ai_executor_argv': ['fake', '{input}', '{output}']}
        decision = {'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash'],
            'diagnosis': 'Low fitness.', 'economic_rationale': 'Persistent signal.', 'hypothesis': 'Preserve cross-industry signal.',
            'expected_improvement': 'fitness', 'risks': 'Risk exposure.', 'action': 'neutralization', 'value': 'INDUSTRY',
            'edit': 'Change only neutralization from SUBINDUSTRY to INDUSTRY. Retain expression, decay=4, '
                'USA/D1/TOP3000, EQUITY, truncation=0.08, FASTEXPR, nanHandling=OFF, pasteurization=ON, '
                'unitHandling=VERIFY and visualization=false.',
            'target_metric': 'fitness', 'target_direction': 'increase',
            'falsification': 'Fitness unchanged.', 'applicability': 'Persistent signal.'}
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value={
                'status': 'completed', 'summary': 'One test.', 'decision': decision}) as worker:
            plan = prepare_repair_decision(self.root, parent, [], 2, config, 'now')
            executor = RepairRuntimeExecutor(config, enable_live_api=True)
            executor(self.root, parent, [{'ai_plan': plan}], 1)
            executor(self.root, parent, [{'ai_plan': plan}], 1)
        self.assertEqual(worker.call_count, 1)
        self.assertEqual(self.submit.call_count, 1)
        self.assertEqual(self.submit.call_args.args[1]['settings']['neutralization'], 'INDUSTRY')
        self.assertEqual(json.loads(Path(plan['receipt_path']).read_text())['status'], 'consumed')
        original = json.loads(Path(plan['normalization']['source_path']).read_text())
        self.assertEqual(original['status'], 'blocked')
        self.assertEqual(original['judgment']['decision'], decision)

    def test_two_parents_staggered_completion_restart_uses_saved_identity(self):
        from wqb.repair_scheduler import execute_repair_round
        from wqb.ai_checkpoints import load_ai_checkpoints
        from wqb.simulator import SimulationPollTimeout
        import requests
        parents = []
        for name in ('a', 'b'):
            row = fixtures.parent_row()
            row['metrics'] = {'fitness': .5}
            row.update(alpha_id=name, expression_hash=name + '-hash', benchmark_label='repairable_signal')
            if name == 'b':
                row['expression'] = 'rank(debt)'
            parents.append(row)
        (self.root / 'all_alphas.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in parents))
        self.submit.side_effect = ['progress/a', 'progress/b']
        response = requests.Response()
        response.status_code = 200
        response.headers['Retry-After'] = '5'
        def poll(client, url, **kwargs):
            if url == 'progress/a':
                raise SimulationPollTimeout('processing', response=response)
            return {'alpha': 'child-b'}
        self.poll.side_effect = poll
        def model(directory, checkpoint_id, argv, **kwargs):
            checkpoint = next(r for r in load_ai_checkpoints(directory) if r['checkpoint_id'] == checkpoint_id)
            evidence = json.loads(Path(checkpoint['evidence_paths'][0]).read_text())
            p = evidence['parent']
            return {'status': 'completed', 'summary': 'One measured test.', 'decision': {
                'parent_alpha_id': p['parent_alpha_id'], 'parent_expression_hash': p['parent_expression_hash'],
                'diagnosis': 'Fitness weak.', 'economic_rationale': 'Persistent signal.', 'hypothesis': 'Smooth noise.',
                'expected_improvement': 'fitness', 'risks': 'Lag.', 'action': 'test', 'edit': 'decay', 'value': 8,
                'target_metric': 'fitness', 'target_direction': 'increase',
                'falsification': 'Fitness unchanged.', 'applicability': 'Persistent signal.'}}
        executor = RepairRuntimeExecutor({'ai_executor_argv': ['fake', '{input}', '{output}']}, enable_live_api=True)
        with patch('wqb.repair_planning.run_ai_checkpoint', side_effect=model) as worker:
            first = execute_repair_round(self.root, {'rows': parents}, executor, 2)
            self.assertEqual(first['status'], 'paused')
            self.assertEqual(self.submit.call_count, 2)
            self.assertEqual(first['attempts'][1]['phase'], 'checked')
            self.assertEqual(worker.call_count, 2)
            receipt_path = self.root / 'stages/repair/repair_execution.json'
            receipt = json.loads(receipt_path.read_text())
            receipt['attempts'][0]['next_poll_at'] = '2000-01-01T00:00:00+00:00'
            receipt_path.write_text(json.dumps(receipt))
            for wait_path in self.root.glob('stages/repair/parents/**/progress_wait.json'):
                wait = json.loads(wait_path.read_text())
                wait['next_poll_at'] = '2000-01-01T00:00:00+00:00'
                wait_path.write_text(json.dumps(wait))
            self.poll.side_effect = None
            self.poll.return_value = {'alpha': 'child-a'}
            final = execute_repair_round(self.root, {'rows': parents}, executor, 2)
        self.assertEqual(final['status'], 'completed', final.get('blocker'))
        self.assertEqual(self.submit.call_count, 2)
        self.assertEqual(worker.call_count, 2)

    def test_validated_model_decision_changes_actual_simulation_payload_and_is_consumed(self):
        parent = fixtures.parent_row()
        parent['metrics'] = {'fitness': .5}
        config = {'ai_executor_argv': ['fake', '{input}', '{output}']}
        answer = {'status': 'completed', 'summary': 'Test longer holding.', 'decision': {
            'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash'],
            'diagnosis': 'Low fitness.', 'economic_rationale': 'Persistent signal.',
            'hypothesis': 'Reduce high frequency noise.', 'expected_improvement': 'fitness',
            'risks': 'Lag.', 'action': 'test', 'edit': 'decay', 'value': 12,
            'target_metric': 'fitness', 'target_direction': 'increase',
            'falsification': 'Fitness unchanged.', 'applicability': 'Persistent signal.'}}
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=answer):
            plan = prepare_repair_decision(self.root, parent, [], 2, config, 'now')
        executor = RepairRuntimeExecutor(config, enable_live_api=True)
        rows = executor(self.root, parent, [{'ai_plan': plan}], 1)
        self.assertEqual(rows[0]['settings']['decay'], 12)
        self.assertEqual(self.submit.call_args.args[1]['settings']['decay'], 12)
        self.assertEqual(json.loads(Path(plan['receipt_path']).read_text())['status'], 'consumed')
        executor(self.root, parent, [{'ai_plan': plan}], 1)
        self.assertEqual(self.submit.call_count, 1)
        stale_plan = {**plan, 'status': 'validated'}
        executor(self.root, parent, [{'ai_plan': stale_plan}], 1)
        self.assertEqual(self.submit.call_count, 1, 'crash before scheduler lifecycle write must recover')

    def test_scheduler_recovers_legacy_wait_without_model_replan(self):
        from wqb.repair_scheduler import execute_repair_round
        from wqb.runtime_control import _write
        import hashlib
        parent = fixtures.parent_row()
        parent['benchmark_label'] = 'repairable_signal'
        source = self.root / 'all_alphas.jsonl'
        source.write_text(json.dumps(parent) + '\n')
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        receipt = {'run_id': self.root.name, 'max_simulations': 1, 'input_sha256': sha,
                   'last_sha256': sha, 'parent_keys': [[parent['alpha_id'], parent['expression_hash']]],
                   'attempts': [{'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash'],
                                 'max_simulations': 1, 'actions': fixtures.repair_actions(), 'status': 'started', 'children': []}]}
        _write(self.root / 'stages/repair/repair_execution.json', receipt)
        with patch('wqb.repair_planning.run_ai_checkpoint') as worker:
            result = execute_repair_round(self.root, {'rows': [parent]}, RepairRuntimeExecutor({}, enable_live_api=True), 1)
        self.assertEqual(result['status'], 'completed')
        worker.assert_not_called()
        self.assertEqual(self.submit.call_count, 1)
