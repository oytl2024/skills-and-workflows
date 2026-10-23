"""A deterministic provider uses durable verified plans without AI judgments."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_repair_search import search_fixture
from wqb.repair_search import prepare_persisted_search, verify_persisted_search


class DeterministicRepairIntegrationTests(unittest.TestCase):
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
                supports_ai_planning = True
                supports_durable_recovery = True

                def prepare(self, run, current, history, maximum):
                    """Input: fixture run/parent/history/cap. Output: actual persisted deterministic plan."""
                    return prepare_persisted_search(run, current, history, maximum)

                def __call__(self, run, current, actions, maximum):
                    """Input: fixture execution. Output: checked rows; second test regresses fitness."""
                    seen.append(current['alpha_id'])
                    index = len(seen)
                    variant = actions[0]['ai_plan']['variants'][0]
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
                    'wqb.repair_planning.run_ai_checkpoint', side_effect=AssertionError('unexpected AI')):
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
