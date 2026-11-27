"""Offline contract: live-tool responses replace the global knowledge inventory."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from tests.test_expression_tools import SCOPE
from tests.test_expression_planning import design


class LiveResearchPlanningTests(unittest.TestCase):
    def test_one_plan_compiles_and_seals_without_raw_machine_or_wiki(self):
        from wqb.retrieval_research_planning import prepare_retrieval_design, query_design_task
        from wqb.preplanned_start import prepare_preplanned_start
        from types import SimpleNamespace
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            knowledge, directory = root / 'knowledge', root / 'planning'
            skill = knowledge / 'skills/brain-research'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('Test economic hypotheses; retain uncertainty.', encoding='utf-8')
            from wqb.config import DEFAULT_CONFIG
            config = dict(DEFAULT_CONFIG, live_mcp_version=1, expression_tool_version=1, direct_knowledge_version=1,
                independent_tasks_version=1, plan_depth=2, initial_hypotheses=4, parallel_workflows=1,
                measurement_period=dict(start='2014-01-01', end='2023-12-29'), **SCOPE)
            answer = dict(summary='Test a sentiment-change hypothesis.', designs=[design()], selection=[],
                history_selection=[], data_characteristics=[], tree=dict(roots=['r'], nodes=[dict(
                    node_id='r', parent_id=None, parent_arm_id=None, design_index=0,
                    targets=dict(baseline=[], treatment=[]), fallback=[], reverse={})]))
            client = Mock()
            def get(path):
                """Input: relative API path str. Output: explicit offline scoped response, never real requests."""
                if path.startswith('/data-fields?'):
                    return dict(results=[dict(id='signal', dataset=dict(id='d'), type='MATRIX', description='Sentiment')], count=1)
                if path == '/operators':
                    return [dict(name='rank', definition='rank(x)'), dict(name='ts_delta', definition='ts_delta(x,d)')]
                self.fail('unexpected resource read: ' + path)
            client.get_json.side_effect = get

            def model(owner, brief):
                """Input: task Path/brief dict. Output: complete tree built through production tool contracts."""
                query_design_task(owner, 'get_datafields', {})
                query_design_task(owner, 'get_operators', {})
                guidance = query_design_task(owner, 'skill', dict(path='skills/brain-research/SKILL.md'))
                self.assertIn('uncertainty', guidance['text'])
                built = query_design_task(owner, 'compile', dict(expression=answer['designs'][0]['treatment']))
                self.assertTrue(built['valid'], built)
                checked = query_design_task(owner, 'validate', dict(answer=answer))
                self.assertTrue(checked['valid'], checked)
                return answer

            with patch('wqb.client.WQBClient', return_value=client):
                result = prepare_retrieval_design(directory, knowledge, SCOPE, dict(option_id='test'),
                    config, model_runner=lambda brief:model(directory,brief), check_cancelled=lambda:None)
                self.assertEqual(result['status'], 'completed', result)
                self.assertEqual(len(result['resources']['field_rows']), 1)
                self.assertFalse((knowledge / 'machine').exists())
                self.assertFalse((knowledge / 'raw').exists())
                from wqb.retrieval_research_planning import LIVE_RESPONSES_PATH
                (directory/LIVE_RESPONSES_PATH).unlink()
                reused=prepare_retrieval_design(directory,knowledge,SCOPE,dict(option_id='test'),config,
                    model_runner=lambda _:self.fail('completed task replayed'),check_cancelled=lambda:None)
                self.assertEqual(reused['status'],'completed',reused)
                config.update(selected_scope=dict(SCOPE, as_of='2026-11-27T00:00:00+00:00'),
                    research_policy=dict(preplanned_tree_version=1, retrieval_design_version=1,
                        execution_package_version=1, live_mcp_version=1))
                from tests.test_workflow_stage_adapters import valid_option
                paths = SimpleNamespace(knowledge_root=knowledge, run_root=root / 'runs', project_root=root, workflow_root=root)
                prepared = prepare_preplanned_start(paths, valid_option(option_id='live-test'),
                    dict(enable_live_api=False, max_runtime_seconds=3600, max_recoveries=3), config,
                    model_runner=lambda _: self.fail('second model call'), retrieval_model_runner=model)
                self.assertEqual(prepared['status'], 'completed', prepared)
                self.assertFalse((knowledge / 'machine').exists())


if __name__ == '__main__':
    unittest.main()
