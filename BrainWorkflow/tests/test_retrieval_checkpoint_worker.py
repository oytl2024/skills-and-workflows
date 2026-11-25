"""The new checkpoint must use existing read-only process boundaries without live calls."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class RetrievalCheckpointWorkerTests(unittest.TestCase):
    def test_worker_supplies_retrieval_tools_and_returns_strict_complete_answer(self):
        from wqb import codex_ai_worker as worker
        from wqb import retrieval_research_planning as planning
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            input_path = run / 'stages/ai/ai_checkpoint_runs/test/attempt/input.json'
            input_path.parent.mkdir(parents=True)
            input_path.write_text(json.dumps(dict(checkpoint_type=planning.CHECKPOINT_TYPE,
                evidence_paths=[planning.TASK_PATH], reason='Offline test.')), encoding='utf-8')
            task_path = run / planning.TASK_PATH
            task_path.parent.mkdir(parents=True)
            task_path.write_text('{}', encoding='utf-8')
            schema = dict(type='object', properties=dict(summary=dict(type='string'),
                selection=dict(type='array', items=dict(type='string')),
                reverse=dict(type='object', properties=dict(baseline=dict(type='string')),
                    required=[], additionalProperties=False)),
                required=['summary', 'selection'], additionalProperties=False)
            task = dict(brief=dict(output_schema=schema))
            answer = dict(summary='An offline plan.', selection=['field'], reverse={})
            commands = []

            def execute(argv, **kwargs):
                """Input: owned Codex argv/options. Output: fake successful process and strict answer file."""
                commands.append(argv)
                from tests.test_model_schema_transport import assert_closed_provider_objects, wire_answer
                sent = json.loads(Path(argv[argv.index('--output-schema') + 1]).read_text())
                assert_closed_provider_objects(sent)
                Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(wire_answer(schema, answer)), encoding='utf-8')
                return subprocess.CompletedProcess(argv, 0, '', '')

            with patch.object(planning, 'authenticated_design_task', return_value=task), \
                    patch.object(planning, 'retrieval_projection', return_value=dict(query_command=['local-query'])), \
                    patch.object(worker.shutil, 'which', return_value='codex'), \
                    patch.object(worker.subprocess, 'run', side_effect=execute):
                result = worker.run_worker(input_path, input_path.parent / 'result.json')
            self.assertEqual(result, answer)
            self.assertIn('read-only', commands[0])
            self.assertIn('model_reasoning_effort=medium', commands[0])
            self.assertIn('local-query', commands[0][-1])
            self.assertNotIn('Read full source_texts', commands[0][-1])
