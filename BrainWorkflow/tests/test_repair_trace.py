import copy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from wqb.repair_trace import compare_repair_experiment, validate_experiment_target


class RepairTraceTests(unittest.TestCase):
    def setUp(self):
        self.parent = {'alpha_id': 'p', 'expression_hash': 'ph', 'expression': 'rank(x)',
                       'settings': {'region': 'USA', 'delay': 1, 'universe': 'TOP3000', 'decay': 2},
                       'metrics': {'sharpe': 1., 'fitness': .5, 'turnover': .3}, 'failed': ['LOW_FITNESS'],
                       'test_period': '2014-2024'}
        self.child = copy.deepcopy(self.parent)
        self.child.update(alpha_id='c', expression_hash='ch', parent_alpha_id='p', parent_expression_hash='ph')
        self.child['settings']['decay'] = 8
        self.child['metrics']['fitness'] = .7
        self.decision = {'action': 'test', 'edit': 'decay', 'value': 8, 'target_metric': 'fitness',
                         'target_direction': 'increase', 'falsification': 'fitness fails to increase',
                         'applicability': 'persistent signal, same universe', 'hypothesis': 'reduce noise'}

    def test_measured_improvement_is_not_qualification(self):
        result = compare_repair_experiment(self.parent, self.child, self.decision)
        self.assertEqual(result['outcome'], 'accept')
        self.assertFalse(result['submission_qualified'])
        self.assertAlmostEqual(result['metric_changes']['fitness']['delta'], .2)

    def test_worse_metric_rejected_and_lower_turnover_supported(self):
        self.child['metrics']['fitness'] = .4
        self.assertEqual(compare_repair_experiment(self.parent, self.child, self.decision)['outcome'], 'reject')
        self.decision.update(target_metric='turnover', target_direction='decrease')
        self.child['metrics']['fitness'] = .5
        self.child['metrics']['turnover'] = .2
        self.assertEqual(compare_repair_experiment(self.parent, self.child, self.decision)['outcome'], 'accept')

    def test_missing_scope_multi_edit_lineage_and_nonfinite_are_inconclusive(self):
        for mutation in ('scope', 'extra_edit', 'lineage', 'nan'):
            child = copy.deepcopy(self.child)
            if mutation == 'scope':
                child['settings'].pop('region')
            elif mutation == 'extra_edit':
                child['settings']['truncation'] = .1
            elif mutation == 'lineage':
                child['parent_alpha_id'] = 'other'
            else:
                child['metrics']['fitness'] = float('nan')
            with self.subTest(mutation=mutation):
                self.assertEqual(compare_repair_experiment(self.parent, child, self.decision)['outcome'], 'inconclusive')

    def test_legacy_not_relabelled_and_invalid_targets_rejected(self):
        self.assertEqual(compare_repair_experiment(self.parent, self.child, {'edit': 'decay'})['outcome'], 'inconclusive')
        for change in ({'target_metric': 'invented'}, {'target_direction': 'decrease'}, {'falsification': ''}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_experiment_target(self.decision | change, self.parent)

    def test_malformed_metric_container_is_inconclusive(self):
        self.child['metrics'] = ['not measured']
        self.assertEqual(compare_repair_experiment(self.parent, self.child, self.decision)['outcome'], 'inconclusive')

    def test_legacy_validation_keeps_original_supported_edit(self):
        from wqb.repair_planning import validate_repair_decision
        decision = {key: value for key, value in self.decision.items()
                    if key not in ('target_metric', 'target_direction', 'falsification', 'applicability')}
        decision.update(parent_alpha_id='p', parent_expression_hash='ph', diagnosis='weak fitness',
                        economic_rationale='persistent signal', expected_improvement='fitness', risks='lag')
        evidence = {'parent': self.parent | {'parent_alpha_id': 'p', 'parent_expression_hash': 'ph'}, 'history': []}
        self.assertEqual(validate_repair_decision(decision, evidence)['settings']['decay'], 8)

    def test_target_gain_with_other_metric_regression_not_accepted(self):
        self.child['metrics']['sharpe'] = .1
        self.assertEqual(compare_repair_experiment(self.parent, self.child, self.decision)['outcome'], 'reject')

    def test_reported_test_start_dates_must_match(self):
        self.parent['metrics']['startDate'] = '2014-01-01'
        self.child['metrics']['startDate'] = '2015-01-01'
        self.assertEqual(compare_repair_experiment(self.parent, self.child, self.decision)['outcome'], 'inconclusive')

    def test_absent_measurement_period_is_inconclusive(self):
        self.parent.pop('test_period')
        self.child.pop('test_period')
        self.assertEqual(compare_repair_experiment(self.parent, self.child, self.decision)['outcome'], 'inconclusive')

    def test_start_date_without_end_is_not_complete_period(self):
        self.parent.pop('test_period')
        self.child.pop('test_period')
        self.parent['metrics']['startDate'] = self.child['metrics']['startDate'] = '2014-01-01'
        self.assertEqual(compare_repair_experiment(self.parent, self.child, self.decision)['outcome'], 'inconclusive')

    def test_lost_baseline_metric_cannot_claim_no_regression(self):
        for value in (None, float('nan')):
            self.child['metrics']['sharpe'] = value
            with self.subTest(value=value):
                self.assertEqual(compare_repair_experiment(self.parent, self.child, self.decision)['outcome'], 'inconclusive')

    def test_orchestrator_load_carries_existing_attempt_to_record(self):
        from wqb.orchestrator import WorkflowOrchestrator
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'stages/repair/repair_execution.json'
            path.parent.mkdir(parents=True)
            trace = compare_repair_experiment(self.parent, self.child, self.decision)
            path.write_text(json.dumps({'attempts': [{'parent_alpha_id': 'p', 'parent_expression_hash': 'ph',
                'children': [self.child], 'experiment_trace': trace, 'plan': {'evidence_digest': 'proof'}}]}))
            orchestrator = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
            record = orchestrator._load_or_create_research_record(SimpleNamespace(run_dir=str(root), run_id='r', objective='test'))
            self.assertTrue(record.repair)
