"""Finite AST Repair shares expression construction and existing simulation/comparison identities."""
from copy import deepcopy
from pathlib import Path
import unittest
from tests.test_expression_tools import call,field,literal,SCOPE
from tests.test_expression_planning import context


def repair_fixture():
    """Input: none. Output: measured parent and frozen resources/recipes, including unknown cadence."""
    from wqb.cli import simulation_identity_hash
    resources=context()
    parent=dict(alpha_id='seed',expression='ts_delta(signal, 22)',settings=deepcopy(resources['settings']),
        metrics=dict(sharpe=1.4,fitness=.8,turnover=.5),hard_pass=False,failed=['LOW_FITNESS'],core_fields=['signal'])
    parent['expression_hash']=simulation_identity_hash(parent['expression'],parent['settings'])
    rules=[dict(edit='wrap',template=call('ts_mean',dict(kind='parent'),dict(kind='parameter')),
                grid=[5,22],target_metric='turnover',target_direction='decrease'),
           dict(edit='parameter',path=['args',1],grid=[5,22,122],target_metric='fitness',target_direction='increase')]
    return parent,resources,dict(rules=rules)


class ExpressionRepairTests(unittest.TestCase):
    def test_conditioned_expression_repairs_only_the_planned_window(self):
        """Input: frozen conditional parent/finite window grid. Output: same condition and fields with changed window only."""
        from wqb.expression_repair import compile_policy
        from wqb.repair_search import prepare_search
        from wqb.cli import simulation_identity_hash
        parent, resources, recipe = repair_fixture()
        resources['technical_exploration_version'] = 1
        parent['expression'] = 'if_else(signal > 0, ts_delta(signal, 22), 0)'
        parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
        recipe['rules'] = [dict(edit='parameter', path=['args', 1, 'args', 1], grid=[5, 122],
            target_metric='fitness', target_direction='increase')]
        result = prepare_search(Path('.'), parent, [], 8, compile_policy(resources, [recipe]))
        self.assertEqual(result['status'], 'validated', result)
        self.assertEqual([row['expression'] for row in result['variants']], [
            'if_else(signal > 0, ts_delta(signal, 5), 0)',
            'if_else(signal > 0, ts_delta(signal, 122), 0)'])

    def test_frozen_operator_retains_window_constraints(self):
        from wqb.expression_repair import compile_policy
        from wqb.repair_search import prepare_search
        parent, resources, recipe = repair_fixture()
        operator = next(row for row in resources['operator_rows'] if row['operator'] == 'ts_delta')
        operator['definition_basis'] = dict(rule_id='ts_delta_project_window')
        recipe['rules'] = [dict(recipe['rules'][1], grid=[0, 2521])]
        policy = compile_policy(resources, [recipe])
        self.assertEqual(next(row for row in policy['resources']['operator_rows'] if row['operator'] == 'ts_delta')['definition_basis'], operator['definition_basis'])
        self.assertEqual(prepare_search(Path('.'), parent, [], 8, policy)['variants'], [])

    def test_parameter_direction_is_enforced(self):
        from wqb.expression_repair import compile_policy
        from wqb.repair_search import prepare_search
        parent, resources, recipe = repair_fixture()
        recipe['rules'] = [dict(recipe['rules'][1], parameter_direction='decrease')]
        result = prepare_search(Path('.'), parent, [], 8, compile_policy(resources, [recipe]))
        self.assertEqual([row['expression'] for row in result['variants']], ['ts_delta(signal, 5)'])

    def test_signed_literal_path_survives_expression_roundtrip(self):
        from wqb.expression_repair import compile_policy
        from wqb.repair_search import prepare_search
        from wqb.cli import simulation_identity_hash
        parent, resources, recipe = repair_fixture()
        parent['expression'] = 'signal * -2'
        parent['expression_hash'] = simulation_identity_hash(parent['expression'], parent['settings'])
        recipe['rules'] = [dict(edit='parameter', path=['right'], grid=[-3],
            target_metric='fitness', target_direction='increase')]
        result = prepare_search(Path('.'), parent, [], 8, compile_policy(resources, [recipe]))
        self.assertEqual([row['expression'] for row in result['variants']], ['signal * -3'])

    def test_wrapper_and_parameter_variants_without_semantic_trait_gate(self):
        from wqb.expression_repair import compile_policy
        from wqb.repair_search import prepare_search
        parent,resources,recipe=repair_fixture()
        policy=compile_policy(resources,[recipe])
        before=deepcopy((parent,policy))
        result=prepare_search(Path('.'),parent,[],8,policy)
        self.assertEqual(result['status'],'validated',result)
        expressions=[row['expression'] for row in result['variants']]
        self.assertIn('ts_mean(ts_delta(signal, 22), 5)',expressions)
        self.assertIn('ts_delta(signal, 122)',expressions)
        self.assertEqual((parent,policy),before)
        self.assertTrue(all(row['decision']['edit']=='transform' for row in result['variants']))

    def test_history_and_unknown_post_identities_are_not_retried(self):
        from wqb.expression_repair import compile_policy
        from wqb.repair_search import prepare_search
        parent,resources,recipe=repair_fixture()
        policy=compile_policy(resources,[recipe])
        first=prepare_search(Path('.'),parent,[],8,policy)
        history=[dict(row,status='UNKNOWN_POST') for row in first['variants']]
        result=prepare_search(Path('.'),parent,history,8,policy)
        self.assertEqual(result['variants'],[])
        self.assertEqual(result['status'],'exhausted',result)

    def test_field_replacement_is_not_a_parameter_edit(self):
        from wqb.expression_repair import compile_policy
        from wqb.repair_search import prepare_search
        parent,resources,recipe=repair_fixture()
        recipe['rules']=[dict(edit='parameter',path=['args',0],grid=[5],target_metric='fitness',target_direction='increase')]
        result=prepare_search(Path('.'),parent,[],8,compile_policy(resources,[recipe]))
        self.assertEqual(result['variants'],[])
        self.assertTrue(result['skipped'])

    def test_non_typed_wrapper_and_qualified_parent_do_not_dispatch(self):
        from wqb.expression_repair import compile_policy
        from wqb.repair_search import prepare_search
        parent,resources,recipe=repair_fixture()
        recipe['rules'][0]['template']['operator']='missing'
        recipe['rules']=recipe['rules'][:1]
        policy=compile_policy(resources,[recipe])
        result=prepare_search(Path('.'),parent,[],8,policy)
        self.assertEqual(result['variants'],[])
        parent['hard_pass']=True
        self.assertEqual(prepare_search(Path('.'),parent,[],8,policy)['status'],'stopped')
