import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_repair_planning as fixtures
from wqb.repair_planning import prepare_repair_decision, verify_consumed_plan, RepairPlanningBlocked


class RepairOutputContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RepairPlanningTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def prepare(self):
        f = self.fixture
        return prepare_repair_decision(f.root, f.parent, [], 2, f.config, 'now')

    def test_json_schema_integral_numbers_keep_canonical_integer_effects(self):
        from wqb.repair_planning import validate_repair_decision
        f = self.fixture
        evidence = {'schema_version': 2, 'parent': f.parent | {
            'parent_alpha_id': f.parent['alpha_id'], 'parent_expression_hash': f.parent['expression_hash']}, 'history': []}
        decision = f.answer['decision'] | {'action': 'test', 'edit': 'decay', 'value': 8.0}
        child = validate_repair_decision(decision, evidence, strict_commands=True)
        self.assertIs(type(child['settings']['decay']), int)
        decision.update(edit='flip_direction', value=-1.0)
        self.assertTrue(validate_repair_decision(decision, evidence, strict_commands=True)['expression'].startswith('-('))

    def test_stop_prose_recovers_with_audited_receipt_without_second_model_call(self):
        f = self.fixture
        f.answer['decision'].update(action='stop', edit='None; do not spend more simulations.', value=1.)
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=f.answer) as model:
            first = self.prepare()
            second = self.prepare()
        self.assertEqual(model.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first['decision']['edit'], 'none')
        self.assertEqual(first['variants'], [])
        self.assertTrue(first['receipt_path'].endswith('.normalized.json'))
        original = json.loads(Path(first['normalization']['source_path']).read_text())
        self.assertEqual(original['status'], 'blocked')
        self.assertEqual(original['judgment']['decision']['edit'], f.answer['decision']['edit'])
        self.assertEqual(verify_consumed_plan(f.root, first), first)

    def test_normalized_receipt_rejects_modified_source_or_decision(self):
        for target in ('source', 'decision'):
            with self.subTest(target=target):
                self.setUp()
                f = self.fixture
                f.answer['decision'].update(action='stop', edit='None; stop.', value=1.)
                with patch('wqb.repair_planning.run_ai_checkpoint', return_value=f.answer):
                    receipt = self.prepare()
                path = Path(receipt['normalization']['source_path'] if target == 'source' else receipt['receipt_path'])
                changed = json.loads(path.read_text())
                if target == 'source':
                    changed['judgment']['summary'] = 'different'
                else:
                    changed['decision']['hypothesis'] = 'different'
                path.write_text(json.dumps(changed))
                with self.assertRaises(RepairPlanningBlocked):
                    verify_consumed_plan(f.root, receipt)

    def test_malformed_normalization_metadata_is_rejected(self):
        f = self.fixture
        f.answer['decision'].update(action='stop', edit='None; stop.', value=1.)
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=f.answer):
            receipt = self.prepare()
        receipt['normalization'] = 'invalid'
        Path(receipt['receipt_path']).write_text(json.dumps(receipt))
        with self.assertRaises(RepairPlanningBlocked):
            verify_consumed_plan(f.root, receipt)

    def test_ambiguous_action_is_not_converted(self):
        f = self.fixture
        f.answer['decision'].update(action='stop', edit='neutralization', value='INDUSTRY')
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=f.answer):
            with self.assertRaises(RepairPlanningBlocked):
                self.prepare()

    def test_contradictory_stop_prose_is_not_converted(self):
        f = self.fixture
        f.answer['decision'].update(action='stop',
            edit='None; actually change decay to 8 and run another simulation.', value=8)
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=f.answer):
            with self.assertRaises(RepairPlanningBlocked):
                self.prepare()

    def test_scheduler_checks_normalized_stop_integrity_before_recording_stop(self):
        from wqb.repair_scheduler import execute_repair_round
        f = self.fixture
        f.parent['benchmark_label'] = 'repairable_signal'
        (f.root / 'all_alphas.jsonl').write_text(json.dumps(f.parent) + '\n')
        f.answer['decision'].update(action='stop', edit='None; stop.', value=1.)
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=f.answer):
            plan = self.prepare()
        Path(plan['normalization']['source_path']).write_text('{}')

        class Executor:
            supports_ai_planning = True
            supports_durable_recovery = True

            def prepare(self, *args):
                """Input: scheduler arguments. Output: stale dict. Reproduce a changed stop receipt."""
                return plan

            def __call__(self, *args):
                """Input: execution arguments. Output: none. Stop must never execute simulations."""
                raise AssertionError('simulation must not execute')

        result = execute_repair_round(f.root, {'rows': [f.parent]}, Executor(), 2)
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(result['stopped_parents'], [])

    def test_scheduler_revalidates_stopped_parent_on_completed_and_paused_restart(self):
        from wqb.repair_scheduler import execute_repair_round
        for phase in ('completed', 'paused'):
            with self.subTest(phase=phase):
                self.setUp()
                f = self.fixture
                f.parent['benchmark_label'] = 'repairable_signal'
                (f.root / 'all_alphas.jsonl').write_text(json.dumps(f.parent) + '\n')
                f.answer['decision'].update(action='stop', edit='None; stop.', value=1.)
                with patch('wqb.repair_planning.run_ai_checkpoint', return_value=f.answer):
                    plan = self.prepare()

                class Executor:
                    supports_ai_planning = True
                    supports_durable_recovery = True

                    def prepare(self, *args):
                        """Input: scheduler args. Output: verified stop plan dict."""
                        return plan

                execute_repair_round(f.root, {'rows': [f.parent]}, Executor(), 2)
                receipt_path = f.root / 'stages/repair/repair_execution.json'
                receipt = json.loads(receipt_path.read_text())
                receipt['status'] = phase
                receipt_path.write_text(json.dumps(receipt))
                Path(plan['normalization']['source_path']).write_text('{}')
                result = execute_repair_round(f.root, {'rows': [f.parent]}, Executor(), 2)
                self.assertEqual(result['status'], 'paused')
                self.assertIn('stop evidence', result['blocker'])

    def test_neutralization_alias_with_exact_retained_settings_is_recoverable(self):
        f = self.fixture
        f.parent['settings'].update(region='USA', delay=1, universe='TOP3000', instrumentType='EQUITY',
            language='FASTEXPR', nanHandling='OFF', pasteurization='ON', unitHandling='VERIFY',
            visualization=False, neutralization='SUBINDUSTRY', decay=4, truncation=.08)
        f.answer['decision'].update(action='neutralization', value='INDUSTRY', edit=
            'Change only neutralization from SUBINDUSTRY to INDUSTRY. Retain expression, decay=4, '
            'USA/D1/TOP3000, EQUITY, truncation=0.08, FASTEXPR, nanHandling=OFF, pasteurization=ON, '
            'unitHandling=VERIFY and visualization=false.')
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=f.answer):
            receipt = self.prepare()
        self.assertEqual(receipt['decision']['action'], 'test')
        self.assertEqual(receipt['decision']['edit'], 'neutralization')
        self.assertEqual(receipt['variants'][0]['settings'], f.parent['settings'] | {'neutralization': 'INDUSTRY'})
        verify_consumed_plan(f.root, receipt)
