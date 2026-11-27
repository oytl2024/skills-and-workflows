"""Structural expression construction uses technical contracts, not economic prose admission."""
from copy import deepcopy
import unittest


SCOPE = dict(instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000')


def field(name='signal', dataset='d'):
    """Input: identity strings. Output: exact field AST leaf."""
    return dict(kind='field', dataset_id=dataset, field_id=name)


def literal(value):
    """Input: scalar. Output: scalar AST node."""
    return dict(kind='literal', value=value)


def call(name, *args, **kwargs):
    """Input: operator name/AST args. Output: named-call AST node."""
    return dict(kind='call', operator=name, args=list(args), kwargs=kwargs)


def resources():
    """Input: none. Output: isolated technical-only fields/operators, with no documented semantic approval."""
    operators = []
    for name, inputs, output, parameters in [
            ('rank', ['MATRIX'], 'MATRIX', [('x','MATRIX')]),
            ('ts_delta', ['MATRIX'], 'MATRIX', [('x','MATRIX'),('d','INTEGER')]),
            ('ts_mean', ['MATRIX'], 'MATRIX', [('x','MATRIX'),('d','INTEGER')]),
            ('vec_sum', ['VECTOR'], 'MATRIX', [('x','VECTOR')]),
            ('greater', ['MATRIX','FLOAT'], 'MATRIX', [('x','MATRIX'),('y','FLOAT')]),
            ('if_else', ['MATRIX','MATRIX','FLOAT'], 'MATRIX', [('condition','MATRIX'),('x','MATRIX'),('y','FLOAT')])]:
        operators.append(dict(operator=name, definition=dict(input_types=inputs,output_type=output,
            parameters=[dict(name=k,type=t,required=True) for k,t in parameters])))
    fields=[dict(SCOPE,dataset_id='d',field_id='signal',field_type='MATRIX'),
        dict(SCOPE,dataset_id='d',field_id='events',field_type='VECTOR')]
    return dict(field_rows=fields,operator_rows=operators,scope=deepcopy(SCOPE))


class ExpressionToolsTests(unittest.TestCase):
    def test_brain_logical_operator_names_are_not_python_keywords(self):
        supplied = resources()
        for name, arity in [('and', 2), ('or', 2), ('not', 1)]:
            supplied['operator_rows'].append(dict(operator=name, definition=dict(
                input_types=['MATRIX'] * arity, output_type='MATRIX',
                parameters=[dict(name='x'+str(i), type='MATRIX', required=True) for i in range(arity)])))
        node = call('or', call('and', field(), field()), call('not', field()))
        compiled = self.compile(node, supplied)
        self.assertTrue(compiled['valid'], compiled)
        self.assertEqual(compiled['expression'], 'or(and(signal, signal), not(signal))')
        from wqb.expression_tools import expression_ast
        self.assertEqual(expression_ast(compiled['expression'], supplied), node)

    def test_boolean_parameter_uses_brain_spelling_and_roundtrips(self):
        supplied = resources()
        supplied['operator_rows'].append(dict(operator='add', definition=dict(
            input_types=['MATRIX', 'MATRIX'], output_type='MATRIX', parameters=[
                dict(name='x', type='MATRIX', required=True), dict(name='y', type='MATRIX', required=True),
                dict(name='filter', type='BOOLEAN', required=False, default=False)])))
        from wqb.expression_tools import expression_ast
        for value in (True, False):
            node = call('add', field(), field(), filter=literal(value))
            compiled = self.compile(node, supplied)
            self.assertTrue(compiled['valid'], compiled)
            self.assertEqual(compiled['expression'], 'add(signal, signal, filter='+str(value).lower()+')')
            self.assertEqual(expression_ast(compiled['expression'], supplied), node)

    def test_comparisons_can_condition_an_experiment(self):
        from wqb.expression_tools import expression_ast
        for operator in ('>', '>=', '<', '<=', '==', '!='):
            comparison = dict(kind='binary', operator=operator, left=field(), right=literal(0))
            node = call('if_else', comparison, field(), literal(0))
            compiled = self.compile(node)
            self.assertTrue(compiled['valid'], compiled)
            self.assertEqual(compiled['output_type'], 'MATRIX')
            self.assertEqual(expression_ast(compiled['expression'], resources()), node)
        vector_comparison = dict(kind='binary', operator='>', left=field('events'), right=literal(0))
        self.assertFalse(self.compile(vector_comparison)['valid'])

    def test_syntax_translation_preserves_strings_and_rejects_python_branches(self):
        from wqb.expression_tools import expression_ast
        supplied = resources()
        supplied['technical_exploration_version'] = 1
        text = 'true and(x) False or(not(y)) {window} {not_a_slot}'
        node = call('new_operator', field(), literal(text))
        compiled = self.compile(node, supplied)
        self.assertTrue(compiled['valid'], compiled)
        self.assertEqual(expression_ast(compiled['expression'], supplied), node)
        for expression in ('signal.x', 'signal[0]', '[x for x in signal]', 'lambda: signal',
                           '0 < signal < 1', 'signal and signal'):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                expression_ast(expression, supplied)

    def test_unknown_signature_is_explorable_without_claiming_type_proof(self):
        supplied = resources()
        supplied['technical_exploration_version'] = 1
        supplied['operator_rows'].append(dict(operator='untried_operator'))
        result = self.compile(call('untried_operator', field()), supplied)
        self.assertTrue(result['valid'], result)
        self.assertEqual(result['type_status'], 'unknown')
        self.assertTrue(result['warnings'])
        self.assertEqual(result['expression'], 'untried_operator(signal)')
        self.assertFalse(self.compile(call('untried_operator', call('ts_delta', field(), literal('bad'))), supplied)['valid'])
        self.assertFalse(self.compile(call('untried_operator', field()))['valid'])

    def test_declared_window_bounds_survive_technical_binding(self):
        supplied = resources()
        row = next(row for row in supplied['operator_rows'] if row['operator'] == 'ts_delta')
        row['definition_basis'] = dict(rule_id='ts_delta_project_window')
        for window in (0, -5, 2521):
            self.assertFalse(self.compile(call('ts_delta', field(), literal(window)), supplied)['valid'])

    def compile(self, node, supplied=None):
        from wqb.expression_tools import compile_expression
        return compile_expression(node, resources() if supplied is None else supplied, SCOPE)

    def test_nested_kwargs_without_semantic_or_provenance_admission(self):
        node=call('rank',call('ts_delta',field(),d=literal(22)))
        result=self.compile(node)
        self.assertTrue(result['valid'],result)
        self.assertEqual(result['expression'],'rank(ts_delta(signal, d=22))')
        self.assertEqual(result['output_type'],'MATRIX')
        self.assertEqual(result['used_fields'],[dict(dataset_id='d',field_id='signal')])
        self.assertEqual(result['used_operators'],['rank','ts_delta'])

    def test_vector_and_conditioned_calls_are_not_fixed_feature_families(self):
        for node in [call('vec_sum',field('events')),call('if_else',
                call('greater',field(),literal(0)),call('rank',field()),literal(0))]:
            self.assertTrue(self.compile(node)['valid'])
        self.assertFalse(self.compile(call('rank',field('events')))['valid'])

    def test_arithmetic_and_no_input_mutation(self):
        node=dict(kind='binary',operator='/',left=call('ts_delta',field(),literal(5)),right=literal(2))
        before=deepcopy(node)
        result=self.compile(node)
        self.assertTrue(result['valid'],result)
        self.assertEqual(node,before)

    def test_technical_errors_are_diagnostics(self):
        for node in [call('rank',field(),literal(2)),call('ts_delta',field(),literal('month')),
                call('missing',field()),field('absent'),dict(kind='python',code='import os'),
                dict(kind='literal',value=float('nan'))]:
            result=self.compile(node)
            self.assertFalse(result['valid'],result)
            self.assertTrue(result['diagnostics'][0]['path'])

    def test_scope_and_duplicate_identity_are_still_rejected(self):
        original=resources()
        original['field_rows'][0]['region']='EUR'
        self.assertFalse(self.compile(field(),original)['valid'])

    def test_many_field_slots_do_not_alias_token_prefixes(self):
        supplied=resources()
        supplied['field_rows']=[dict(SCOPE,dataset_id='d',field_id='x'+str(i),field_type='MATRIX') for i in range(12)]
        node=field('x0')
        for i in range(1,12):
            node=dict(kind='binary',operator='+',left=node,right=field('x'+str(i)))
        result=self.compile(node,supplied)
        self.assertTrue(result['valid'],result)
        original=resources()
        original['field_rows'].append(deepcopy(original['field_rows'][0]))
        self.assertFalse(self.compile(field(),original)['valid'])
