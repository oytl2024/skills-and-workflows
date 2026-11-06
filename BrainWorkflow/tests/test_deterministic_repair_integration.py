"""A deterministic provider uses durable verified plans without AI judgments."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_repair_search import search_fixture
from wqb.repair_search import prepare_persisted_search, verify_persisted_search


class DeterministicRepairIntegrationTests(unittest.TestCase):
    def test_sourced_start_accepted_incumbent_then_cached_variant_exact_lineage(self):
        """Input: measured Start/Seed plus finite decay grid. Output: exact accepted-parent cache alias, zero POST charge."""
        from tests.test_preplanned_research_acceptance import IntegratedFourRootAcceptanceTests
        from wqb import preplanned_start
        from wqb.cli import simulation_identity_hash, submit_candidate_payloads
        from wqb.daily_simulation_budget import read_daily_budget
        from wqb.recorder import RunRecorder
        from wqb.repair_scheduler import execute_repair_round
        from wqb.research_seed_stage import prepare_seed_selection
        from wqb.runtime_control import CONTROL_ENV
        from wqb.tree_runtime import checked_research_rows
        fixture = IntegratedFourRootAcceptanceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        from tests.test_preplanned_start import PreplannedStartTests
        from tests.test_preplanned_research_acceptance import four_root_answer
        fixture.fixture = PreplannedStartTests()
        fixture.fixture.setUp()
        self.addCleanup(fixture.fixture.doCleanups)
        fixture.fixture.config['parallel_workflows'] = 1
        fixture.fixture.authority['enable_live_api'] = True
        fixture.fixture.paths.workflow_root = Path(__file__).resolve().parents[1]
        fixture.fixture.runner.side_effect = lambda brief: four_root_answer(fixture.fixture, brief)
        traits = preplanned_start._repair_policy(fixture.fixture.resources[0])['traits']
        rule = dict(rule_id='finite-project-decay', edit='decay', effect='smoothing', priority=0,
            target_metric='turnover', target_direction='decrease', grid=[8, 16],
            requires=dict(matrix_observation=True),
            evidence_refs=deepcopy(traits['matrix_observation']['evidence_refs']))
        fixture.fixture.config['repair_search_policy'] = dict(schema_version=1, rules=[rule], traits=traits)
        fixture.start_group()
        fixture.finish_trees()
        run = fixture.runs[0]
        selection = prepare_seed_selection(run, checked_research_rows(run))
        self.assertTrue(selection['seed_rows'])
        parent = selection['seed_rows'][0]
        transport = fixture.transport

        def measure(variant, directory):
            """Input: immutable variant dict/temp Path. Output: checked row from real CLI and fake HTTP."""
            recorder = RunRecorder(directory)
            payload = dict(type='REGULAR', regular=variant['expression'], settings=variant['settings'])
            with patch.dict(os.environ, {CONTROL_ENV: str(run)}):
                submit_candidate_payloads(transport.client, recorder, [payload], [variant], 'multi',
                    'offline-repair', knowledge_root=fixture.fixture.paths.knowledge_root)
            rows = recorder.read_jsonl('all_alphas.jsonl')
            self.assertEqual(len(rows), 1)
            return rows[0]

        variants = {}
        for decay, turnover in ((8, .15), (16, .1), (32, .01)):
            settings = dict(parent['settings'], decay=decay)
            identity = simulation_identity_hash(parent['expression'], settings)
            variants[decay] = dict(expression=parent['expression'], settings=settings,
                expression_hash=identity, simulation_identity=identity, lane_id=run.name,
                measurement_scope=deepcopy(parent['measurement_scope']), test_period=deepcopy(parent['test_period']),
                parent_alpha_id='unrelated-original-parent', parent_expression_hash='f' * 64)
            transport.metrics[identity] = {key: parent['metrics'][key]
                for key in ('sharpe', 'fitness', 'returns', 'turnover')}
            transport.metrics[identity]['turnover'] = turnover
        cached = measure(variants[16], run / 'stages/repair/offline-cache-16')
        unrelated = measure(variants[32], run / 'stages/repair/offline-cache-32')
        recorder = RunRecorder(run)
        recorder.append_jsonl('all_alphas.jsonl', cached)
        recorder.append_jsonl('all_alphas.jsonl', unrelated)
        before = read_daily_budget(run)
        executions = []
        test = self

        class Executor:
            supports_plan_preparation = True
            supports_durable_recovery = True

            def prepare(self, root, current, history, maximum):
                """Input: real scheduler incumbent/history/cap. Output: source-verified deterministic receipt."""
                return prepare_persisted_search(root, current, history, maximum)

            def __call__(self, root, current, actions, maximum):
                """Input: genuine frozen plan. Output: real checked CLI row; cache reuse must skip this path."""
                executions.append(current['alpha_id'])
                test.assertEqual(maximum, 1)
                plan = actions[0]['repair_plan']
                return [measure(plan['variants'][0], root / 'stages/repair/offline-executed')]

        with patch.dict(os.environ, {CONTROL_ENV: str(run)}), patch(
                'wqb.ai_checkpoints.run_ai_checkpoint', side_effect=AssertionError('No late model')):
            first = execute_repair_round(run, dict(rows=[parent]), Executor(), 3)
            self.assertEqual(first['attempts'][0]['experiment_trace']['outcome'], 'accepted', first.get('blocker'))
            incumbent = first['attempts'][0]['children'][0]
            charged = read_daily_budget(run)
            posted = list(transport.posted)
            from wqb.research_group import read_group, resume_group, stop_group
            from wqb.runtime_control import RuntimePaused
            group_path = Path(fixture.group['group_dir'])
            group_before_stop = read_group(group_path)
            stopped = stop_group(group_path, group_before_stop['request_revision'])
            scheduler_path = run / 'stages/repair/repair_execution.json'
            saved_receipt = scheduler_path.read_bytes()
            with self.assertRaises(RuntimePaused):
                execute_repair_round(run, dict(rows=[parent]), Executor(), 3)
            self.assertEqual(read_group(group_path)['desired_state'], 'paused')
            self.assertEqual(scheduler_path.read_bytes(), saved_receipt)
            self.assertEqual(transport.posted, posted)
            self.assertEqual(read_daily_budget(run)['used'], charged['used'])
            resumed = resume_group(group_path, stopped['request_revision'])
            self.assertEqual(resumed['authority'], group_before_stop['authority'])
            self.assertEqual(resumed['recoveries_used'], group_before_stop['recoveries_used'])
            second = execute_repair_round(run, dict(rows=[parent]), Executor(), 3)
            reused = second['attempts'][1]
            self.assertTrue(reused['reused_existing_simulation'])
            self.assertEqual(reused['max_simulations'], 0)
            self.assertEqual(reused['parent_alpha_id'], incumbent['alpha_id'])
            self.assertEqual(reused['parent_expression_hash'], incumbent['expression_hash'])
            self.assertEqual(reused['root_parent_key'], [parent['alpha_id'], parent['expression_hash']])
            self.assertEqual(reused['children'][0]['parent_alpha_id'], incumbent['alpha_id'])
            self.assertEqual(reused['children'][0]['settings'], cached['settings'])
            self.assertEqual(reused['children'][0]['alpha_id'], cached['alpha_id'])
            plan = verify_persisted_search(run, reused['plan'])
            self.assertEqual(plan['decision']['parent_alpha_id'], incumbent['alpha_id'])
            self.assertEqual(plan['decision']['parent_expression_hash'], incumbent['expression_hash'])
            evidence = json.loads(Path(plan['receipt_path']).with_suffix('.input.json').read_text())
            self.assertEqual(evidence['parent'], incumbent)
            self.assertEqual(reused['experiment_trace']['outcome'], 'accepted')
            self.assertEqual(read_daily_budget(run)['used'], charged['used'])
            self.assertEqual(read_daily_budget(run)['lifetime_attempts'], charged['lifetime_attempts'])
            self.assertEqual(transport.posted, posted)
            third = execute_repair_round(run, dict(rows=[parent]), Executor(), 3)
        self.assertEqual(executions, [parent['alpha_id']])
        self.assertEqual(charged['used'], before['used'] + 1)
        self.assertEqual(third['incumbents'][parent['expression_hash']]['alpha_id'], cached['alpha_id'])
        self.assertNotEqual(third['incumbents'][parent['expression_hash']]['alpha_id'], unrelated['alpha_id'])
        published = recorder.read_jsonl('all_alphas.jsonl')
        self.assertIn(cached, published, 'Original cache lineage must remain immutable')
        self.assertEqual(fixture.fixture.runner.call_count, 1)

    def test_transform_comparison_requires_rebuilt_typed_search(self):
        from tests.test_repair_search import RepairSearchTests
        from wqb.repair_search import prepare_search
        from wqb.seed_policy import compare_versions
        helper = RepairSearchTests()
        helper.setUp()
        helper.transform_policy()
        parent = helper.parent
        parent.update(status='CHECKED', hard_pass=False, failed=['LOW_FITNESS'], pending=[],
                      test_period=dict(start='2020-01-01', end='2025-12-31'))
        parent['measurement_scope'] = {key: parent['settings'][key] for key in ('region', 'delay', 'universe')}
        parent['metrics']['returns'] = .08
        parent['simulation_identity'] = parent['expression_hash']
        variant = prepare_search(Path('.'), parent, [], 1, helper.policy)['variants'][0]
        child = {**variant, 'alpha_id': 'smoothed', 'status': 'CHECKED', 'hard_pass': False,
                 'failed': ['LOW_FITNESS'], 'pending': [],
                 'metrics': dict(sharpe=1.5, fitness=.9, turnover=.30, returns=.08)}
        decision = {key: variant['decision'][key] for key in ('target_metric', 'target_direction', 'edit', 'value')}
        decision['turnover_max'] = .4
        self.assertEqual(compare_versions(parent, child, decision)['outcome'], 'inconclusive')
        frozen = dict(policy=helper.policy, history=[])
        self.assertEqual(compare_versions(parent, child, decision, frozen_search=frozen)['outcome'], 'accepted')
        altered = dict(child, expression='invented_signal')
        self.assertEqual(compare_versions(parent, altered, decision, frozen_search=frozen)['outcome'], 'inconclusive')

    def test_scheduler_uses_accepted_incumbent_not_rejected_child(self):
        from wqb.repair_scheduler import execute_repair_round
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent, policy, context = self.fixture(root)
            parent.update(status='CHECKED', hard_pass=False, failed=['LOW_FITNESS'], pending=[],
                          benchmark_label='repairable_signal', test_period=dict(start='2020-01-01', end='2025-12-31'))
            parent['measurement_scope'] = {key: parent['settings'][key] for key in ('region', 'delay', 'universe')}
            parent['metrics']['returns'] = .08
            policy['rules'] = [dict(policy['rules'][0], grid=[4, 8, 16])]
            manifest = json.loads((root / 'run_manifest.json').read_text())
            manifest['start_snapshot']['repair_search_policy'] = policy
            (root / 'run_manifest.json').write_text(json.dumps(manifest))
            (root / 'all_alphas.jsonl').write_text(json.dumps(parent) + '\n')
            seen = []
            class Executor:
                supports_plan_preparation = True
                supports_durable_recovery = True

                def prepare(self, run, current, history, maximum):
                    """Input: fixture run/parent/history/cap. Output: actual persisted deterministic plan."""
                    return prepare_persisted_search(run, current, history, maximum)

                def __call__(self, run, current, actions, maximum):
                    """Input: fixture execution. Output: checked rows; second test regresses fitness."""
                    seen.append(current['alpha_id'])
                    index = len(seen)
                    variant = actions[0]['repair_plan']['variants'][0]
                    return [{**variant, 'alpha_id': f'child-{index}', 'status': 'CHECKED',
                             'failed': ['LOW_FITNESS'], 'pending': [], 'hard_pass': False,
                             'metrics': dict(sharpe=1.4, fitness=.9 if index != 2 else .7,
                                             turnover=.35 - .03 * index, returns=.08)}]

            with patch('wqb.hypothesis_selection.validate_operational_resource_context', return_value=context):
                for _ in range(3):
                    result = execute_repair_round(root, dict(rows=[parent]), Executor(), 3)
            self.assertEqual(seen, ['seed', 'child-1', 'child-1'])
            self.assertEqual(result['incumbents'][parent['expression_hash']]['alpha_id'], 'child-3')

    def fixture(self, root):
        """Input: temporary Path. Output: parent/policy/context dict tuple with isolated evidence."""
        parent, policy = search_fixture()
        ref = policy['rules'][0]['evidence_refs'][0]
        context = dict(source_index={ref['source_path']: dict(path=ref['source_path'],
            content_hash=ref['sha256'], captured_at=ref['capture_date'] + 'T00:00:00Z')},
            source_texts={ref['source_path']: 'Offline already-certified source.'})
        snapshot = dict(research_policy=dict(deterministic_repair=True), repair_search_policy=policy)
        (root / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)))
        return parent, policy, context

    def test_verified_provider_replays_without_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent, _, context = self.fixture(root)
            with patch('wqb.hypothesis_selection.validate_operational_resource_context', return_value=context), patch(
                    'wqb.ai_checkpoints.run_ai_checkpoint', side_effect=AssertionError('unexpected AI')):
                plan = prepare_persisted_search(root, parent, [], 8)
                self.assertEqual(len(plan['variants']), 1)
                self.assertEqual(plan['planner_kind'], 'deterministic')
                self.assertEqual(verify_persisted_search(root, plan), plan)
                self.assertEqual(prepare_persisted_search(root, parent, [], 8), plan)

    def test_frozen_policy_or_receipt_change_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent, _, context = self.fixture(root)
            with patch('wqb.hypothesis_selection.validate_operational_resource_context', return_value=context):
                plan = prepare_persisted_search(root, parent, [], 8)
                changed = deepcopy(plan)
                changed['variants'][0]['settings']['decay'] = 99
                with self.assertRaises(ValueError):
                    verify_persisted_search(root, changed)
                manifest = json.loads((root / 'run_manifest.json').read_text())
                manifest['start_snapshot']['repair_search_policy']['rules'][0]['grid'] = [15]
                (root / 'run_manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    verify_persisted_search(root, plan)

    def test_missing_or_legacy_policy_never_enables_new_planner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent, _, _ = self.fixture(root)
            (root / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot={})))
            with self.assertRaises(ValueError):
                prepare_persisted_search(root, parent, [], 8)


if __name__ == '__main__':
    unittest.main()
