import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_repair_planning as fixtures
from wqb.repair_planning import prepare_repair_decision


class RepairBriefTests(unittest.TestCase):
    def test_planner_checkpoint_worker_integration_projects_only_brief(self):
        from subprocess import CompletedProcess
        from wqb.codex_ai_worker import run_worker
        from wqb.ai_checkpoints import load_ai_checkpoints
        fixture = fixtures.RepairPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        (fixture.root / 'run_manifest.json').write_text('{"start_snapshot": {}}')
        fixture.parent['metrics']['details'] = 'RAW_DO_NOT_INLINE' * 4000
        prompts = []

        def fake_model(argv, **kwargs):
            prompts.append(argv[-1])
            Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(fixture.answer))
            return CompletedProcess(argv, 0, '', '')

        def local_worker(argv, timeout_seconds):
            run_worker(Path(argv[1]), Path(argv[2]))
            return CompletedProcess(argv, 0, '', '')

        with patch('wqb.ai_checkpoints._run_cancellable', side_effect=local_worker), \
                patch('wqb.codex_ai_worker.shutil.which', return_value='codex'), \
                patch('wqb.codex_ai_worker.subprocess.run', side_effect=fake_model):
            result = prepare_repair_decision(fixture.root, fixture.parent, [], 2, fixture.config, 'now')
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(load_ai_checkpoints(fixture.root / 'stages/ai')[0]['status'], 'completed')
        self.assertEqual(len(prompts), 1)
        self.assertNotIn('RAW_DO_NOT_INLINE', prompts[0])
        self.assertIn('read supporting evidence', prompts[0])

    def test_large_history_uses_four_sentences_and_preserves_full_evidence(self):
        fixture = fixtures.RepairPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        parent = fixture.parent
        parent['metrics']['checks'] = [{'name': 'LOW_FITNESS', 'result': 'FAIL',
                                        'limit': 1, 'value': .5, 'details': 'x' * 20000}]
        history = [dict(parent, alpha_id='child', expression_hash='child-hash')]
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=fixture.answer):
            receipt = prepare_repair_decision(fixture.root, parent, history, 2, fixture.config, 'now')
        evidence = json.loads((fixture.root / 'runtime/repair_decisions' /
                               (receipt['evidence_digest'] + '.input.json')).read_text())
        self.assertEqual(set(evidence['brief']), {'strategy', 'problem', 'history', 'task'})
        for sentence in evidence['brief'].values():
            self.assertTrue(sentence.endswith('.'))
            self.assertNotIn('\n', sentence)
            self.assertLess(len(sentence), 1800)
        self.assertIn('LOW_FITNESS', evidence['brief']['problem'])
        self.assertIn('unknown', evidence['brief']['strategy'])
        self.assertLess(len(json.dumps(evidence['brief'])), 9000)
        raw = json.loads(Path(evidence['supporting_evidence']['path']).read_text())
        self.assertEqual(raw['parent']['metrics']['checks'], parent['metrics']['checks'])
        self.assertEqual(raw['history'][0]['metrics'], history[0]['metrics'])

    def test_no_history_and_unknown_thresholds_are_explicit(self):
        fixture = fixtures.RepairPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=fixture.answer):
            receipt = prepare_repair_decision(fixture.root, fixture.parent, [], 2, fixture.config, 'now')
        evidence = json.loads((fixture.root / 'runtime/repair_decisions' /
                               (receipt['evidence_digest'] + '.input.json')).read_text())
        self.assertIn('no prior', evidence['brief']['history'])
        self.assertIn('unknown', evidence['brief']['problem'])
        self.assertIn('2', evidence['brief']['task'])

    def test_tampered_support_is_rejected_on_restart(self):
        fixture = fixtures.RepairPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=fixture.answer):
            receipt = prepare_repair_decision(fixture.root, fixture.parent, [], 2, fixture.config, 'now')
        support = next((fixture.root / 'runtime/repair_decisions').glob('*.support.json'))
        support.write_text('{}')
        from wqb.repair_planning import RepairPlanningBlocked, verify_consumed_plan
        with self.assertRaises(RepairPlanningBlocked):
            verify_consumed_plan(fixture.root, receipt)

    def test_history_records_actual_edit_and_negative_result(self):
        from wqb.repair_brief import build_repair_brief
        evidence = {'parent': {'parent_alpha_id': 'p', 'expression': 'rank(x)',
                    'settings': {'decay': 2}, 'metrics': {'sharpe': 1, 'fitness': .5, 'turnover': .3}},
                    'history': [{'alpha_id': 'c', 'expression': 'rank(x)', 'settings': {'decay': 8},
                                 'metrics': {'fitness': .2, 'sharpe': .8, 'turnover': .2}}],
                    'allowance': 2}
        brief = build_repair_brief(evidence)
        self.assertIn('decay', brief['history'])
        self.assertIn('8', brief['history'])
        self.assertIn('fitness=0.2', brief['history'])

    def test_reformat_support_cannot_rebind_receipt_and_reinvoke_ai(self):
        fixture = fixtures.RepairPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        from wqb.repair_planning import RepairPlanningBlocked
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=fixture.answer) as model:
            prepare_repair_decision(fixture.root, fixture.parent, [], 2, fixture.config, 'now')
            support = next((fixture.root / 'runtime/repair_decisions').glob('*.support.json'))
            support.write_text(json.dumps(json.loads(support.read_text()), indent=7))
            with self.assertRaises(RepairPlanningBlocked):
                prepare_repair_decision(fixture.root, fixture.parent, [], 2, fixture.config, 'later')
            self.assertEqual(model.call_count, 1)

    def test_reordered_input_keys_reuse_same_immutable_receipt(self):
        fixture = fixtures.RepairPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with patch('wqb.repair_planning.run_ai_checkpoint', return_value=fixture.answer) as model:
            first = prepare_repair_decision(fixture.root, fixture.parent, [], 2, fixture.config, 'now')
            reordered = dict(reversed(list(fixture.parent.items())))
            reordered['metrics'] = dict(reversed(list(reordered['metrics'].items())))
            second = prepare_repair_decision(fixture.root, reordered, [], 2, fixture.config, 'later')
        self.assertEqual(first, second)
        self.assertEqual(model.call_count, 1)

    def test_history_preserves_decimal_edit_and_adverse_checks(self):
        from wqb.repair_brief import build_repair_brief
        evidence = {'parent': {'parent_alpha_id': 'p', 'expression': 'rank(x)',
                    'settings': {'truncation': .1}, 'metrics': {}},
                    'history': [{'alpha_id': 'c', 'expression': 'rank(x)', 'settings': {'truncation': .08},
                                 'metrics': {'checks': [{'name': 'CONCENTRATED_WEIGHT', 'result': 'FAIL'}]},
                                 'hard_pass': False}], 'allowance': 2}
        brief = build_repair_brief(evidence)
        self.assertIn('truncation=0.08', brief['history'])
        self.assertIn('CONCENTRATED_WEIGHT', brief['history'])

    def test_worker_cannot_publish_test_or_stop_after_evidence_changes(self):
        from wqb.repair_planning import RepairPlanningBlocked
        for action in ('test', 'stop'):
            for target in ('support', 'manifest'):
                with self.subTest(action=action, target=target):
                    fixture = fixtures.RepairPlanningTests()
                    fixture.setUp()
                    self.addCleanup(fixture.doCleanups)
                    manifest = fixture.root / 'run_manifest.json'
                    manifest.write_text('{"start_snapshot": {}}')
                    if action == 'stop':
                        fixture.answer['decision'].update(action='stop', edit='none', value=0)

                    def mutate(*args, **kwargs):
                        path = manifest if target == 'manifest' else next(
                            (fixture.root / 'runtime/repair_decisions').glob('*.support.json'))
                        path.write_text('{}')
                        return fixture.answer

                    with patch('wqb.repair_planning.run_ai_checkpoint', side_effect=mutate):
                        with self.assertRaises(RepairPlanningBlocked):
                            prepare_repair_decision(fixture.root, fixture.parent, [], 2, fixture.config, 'now')
                    receipts = [json.loads(p.read_text()) for p in
                                (fixture.root / 'runtime/repair_decisions').glob('*.json')
                                if not p.name.endswith(('.input.json', '.support.json'))]
                    self.assertFalse(any(row.get('status') == 'validated' for row in receipts))
