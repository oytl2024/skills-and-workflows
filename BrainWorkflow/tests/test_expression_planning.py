"""Generic expression experiments reuse existing tree/exploration receipts without prose gates."""
from copy import deepcopy
import unittest
from tests.test_expression_tools import SCOPE, resources, call, field, literal


def design():
    """Input: none. Output: two-arm structural experiment with intentionally unrestricted economic prose."""
    return dict(design_version=4,hypothesis='A possible mechanism. Another competing explanation.\nUnknown conditions remain open.',
        baseline=call('rank',field()),treatment=call('rank',call('ts_delta',field(),literal(22))),repair_recipe={})


def context():
    """Input: none. Output: finite local technical resources/settings, no source-certification assertion."""
    from wqb.generator import build_settings
    from wqb.config import DEFAULT_CONFIG
    value=resources()
    value.update(expression_tool_version=1, settings=build_settings(dict(DEFAULT_CONFIG,**SCOPE)),
        source_index={'raw/user/test.md':dict(path='raw/user/test.md',content_hash='a'*64)},
        source_texts={'raw/user/test.md':'Offline fixture'},evidence_pack={},resource_contract_version=2)
    return value


class ExpressionPlanningTests(unittest.TestCase):
    def test_generic_design_requires_explicit_resource_contract(self):
        from wqb.hypothesis_design import compile_hypothesis_design
        supplied = context()
        supplied.pop('expression_tool_version', None)
        self.assertNotEqual(compile_hypothesis_design(design(), supplied, SCOPE)['status'], 'compiled')

    def test_compile_and_reverify_existing_exploration_receipt(self):
        from wqb.exploration_eligibility import validate_exploration,verify_exploration
        from wqb.expression_planning import normalize_design
        proposed=normalize_design(design())
        receipt=validate_exploration(proposed,context(),SCOPE)
        self.assertEqual(verify_exploration(receipt),receipt)
        self.assertEqual(receipt['compiled']['experiment']['arms'][1]['binding']['bound_expression'],
            'rank(ts_delta(signal, 22))')
        self.assertIn('Another competing explanation',receipt['compiled']['drafts'][0]['hypothesis'])

    def test_generic_tree_compiles_without_economic_feature_contract(self):
        from wqb.initial_research_planning import _compiled_graph
        from wqb.expression_planning import output_schema
        answer=dict(summary='Multiple sentences. This is allowed.',designs=[design()],tree=dict(roots=['r'],nodes=[
            dict(node_id='r',parent_id=None,parent_arm_id=None,design_index=0,
                targets=dict(baseline=[],treatment=[]),fallback=[],reverse={})]))
        brief=dict(plan_depth=2,max_width=4,measurement_period=dict(start='2014-01-01',end='2023-12-29'),
            output_schema=output_schema(),compatible_template_receipts=[])
        tree,tree_resources,receipts,_=_compiled_graph(answer,context(),SCOPE,brief)
        self.assertEqual(tree['roots'],['r'])
        self.assertEqual(len(tree_resources['compiled_pairs']),1)
        self.assertEqual(receipts[0]['compiled']['experiment']['expression_tool_version'],1)

    def test_invalid_arm_returns_technical_diagnostics(self):
        from wqb.hypothesis_design import compile_hypothesis_design
        from wqb.expression_planning import normalize_design
        proposed=design()
        proposed['treatment']=call('ts_delta',field(),literal('month'))
        compiled=compile_hypothesis_design(normalize_design(proposed),context(),SCOPE)
        self.assertNotEqual(compiled['status'],'compiled')
        self.assertTrue(compiled['rejections'])

    def test_receipt_tampering_is_not_a_removed_gate(self):
        from wqb.exploration_eligibility import validate_exploration,verify_exploration
        from wqb.expression_planning import normalize_design
        receipt=validate_exploration(normalize_design(design()),context(),SCOPE)
        receipt['compiled']['experiment']['arms'][0]['binding']['bound_expression']='rank(other)'
        with self.assertRaises(ValueError):
            verify_exploration(receipt)
