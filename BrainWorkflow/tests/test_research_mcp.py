"""Task-bound stdio MCP is a read-only adapter, never another research executor."""
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch


class ResearchMCPTests(unittest.TestCase):
    def test_cli_accepts_the_shared_live_resource_operation(self):
        from wqb.retrieval_research_planning import main
        with patch('wqb.retrieval_research_planning.query_design_task', return_value=dict(items=[])) as query, \
                patch('wqb.retrieval_research_planning.emit_query_result'):
            self.assertEqual(main(['query','--task-dir','task','--operation','get_datafields','--arguments','{}']),0)
        query.assert_called_once_with(Path('task'),'get_datafields',{})

    def test_live_tools_have_only_named_reads_skill_and_local_construction(self):
        from wqb.research_mcp import task_tools
        tools = task_tools(dict(identity=dict(config=dict(live_mcp_version=1))))
        names = {row['name'] for row in tools}
        self.assertEqual(names, {'query','get_datafields','get_datasets','get_operators','get_documentations',
            'get_documentation_page','get_platform_setting_options','read_research_skill'})
        self.assertEqual(tools[0]['inputSchema']['properties']['operation']['enum'], ['contract','compile','validate'])
        self.assertTrue(all(row['annotations']['readOnlyHint'] for row in tools))

    def test_protocol_preserves_scope_budget_and_validation_diagnostics(self):
        from wqb.research_mcp import serve
        requests = [dict(jsonrpc='2.0', id=1, method='initialize', params=dict(protocolVersion='2025-06-18')),
            dict(jsonrpc='2.0', method='notifications/initialized'),
            dict(jsonrpc='2.0', id=2, method='tools/list'),
            dict(jsonrpc='2.0', id=3, method='tools/call', params=dict(name='query',
                arguments=dict(operation='validate', arguments_json='{"selection":[]}')))]
        stream = io.BytesIO(('\n'.join(json.dumps(row) for row in requests) + '\n').encode())
        replies = []
        with patch('wqb.retrieval_research_planning.authenticated_design_task'), \
                patch('wqb.research_tool_service.request_tool', return_value=dict(valid=False,
                    diagnostics=[dict(message='missing exact-scope field')], tool_budget=dict(queries=1))) as query:
            self.assertEqual(serve(Path('task'), stream, replies.append), 0)
        self.assertEqual(len(replies), 3)
        self.assertTrue(replies[1]['result']['tools'][0]['annotations']['readOnlyHint'])
        result = json.loads(replies[2]['result']['content'][0]['text'])
        self.assertFalse(result['valid'])
        self.assertEqual(result['tool_budget']['queries'], 1)
        query.assert_called_once_with(Path('task'), 'validate', dict(selection=[]))

    def test_task_path_is_not_a_tool_argument(self):
        from wqb.research_mcp import serve
        rows = [dict(jsonrpc='2.0', id=1, method='initialize', params=dict(protocolVersion='2025-06-18')),
            dict(jsonrpc='2.0', id=2, method='tools/call', params=dict(name='query', arguments=dict(
                operation='fields', arguments_json='{}', task_dir='../other')))]
        replies = []
        with patch('wqb.retrieval_research_planning.authenticated_design_task'), \
                patch('wqb.research_tool_service.request_tool') as query:
            serve(Path('task'), io.BytesIO(('\n'.join(json.dumps(row) for row in rows)+'\n').encode()), replies.append)
        query.assert_not_called()
        self.assertTrue(replies[-1]['result']['isError'])

    def test_config_is_ephemeral_task_bound_and_required(self):
        from wqb.research_mcp import codex_config
        with patch('sys.frozen', True, create=True), patch('sys.executable', 'app.exe'):
            config = codex_config(Path('task'))
        self.assertEqual(config['command'], 'app.exe')
        self.assertEqual(config['args'][:3], ['--worker-module', 'wqb.retrieval_research_planning', 'mcp'])
        self.assertTrue(config['required'])
        self.assertEqual(config['enabled_tools'], ['query'])
