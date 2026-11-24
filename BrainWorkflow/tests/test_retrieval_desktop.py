"""Optional real windowed-EXE query acceptance; isolated knowledge and no model/platform calls."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import unittest


DESKTOP_EXE = os.environ.get('WQB_TEST_DESKTOP_EXE', '')
NATIVE_TIMEOUT_SECONDS = 30


@unittest.skipUnless(DESKTOP_EXE, 'set WQB_TEST_DESKTOP_EXE for packaged query acceptance')
class RetrievalDesktopTests(unittest.TestCase):
    def test_packaged_query_and_validation_roundtrip_to_source_owner(self):
        """Input: built windowed EXE and isolated real resources. Output: complete indexed JSON, then frozen tree."""
        from tests.test_retrieval_start import RetrievalStartTests
        from wqb.preplanned_start import prepare_preplanned_start
        host = RetrievalStartTests()
        host.setUp()
        self.addCleanup(host.doCleanups)
        exe = Path(DESKTOP_EXE).resolve(strict=True)
        responses = []

        def query(directory, operation, arguments):
            """Input: task Path/operation/JSON arguments. Output: real captured native helper response."""
            command = [str(exe), '--worker-module', 'wqb.retrieval_research_planning',
                'query', '--task-dir', str(directory), '--operation', operation,
                '--arguments', json.dumps(arguments)]
            if operation == 'validate':
                shell = shutil.which('pwsh')
                self.assertTrue(shell, 'PowerShell 7 is required for native shell-pipe acceptance')
                quoted = ' '.join("'" + item.replace("'", "''") + "'" for item in command)
                command = [shell, '-NoProfile', '-Command', '& ' + quoted + ' | Out-String']
            result = subprocess.run(command, capture_output=True, timeout=NATIVE_TIMEOUT_SECONDS,
                check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
            value = json.loads(result.stdout)
            responses.append(value)
            return value

        def model(directory, brief):
            """Input: task/brief. Output: fake economic proposal after native retrieval and draft validation."""
            field = host.fixture.resources[0]['field_rows'][0]
            fields = query(directory, 'fields', {'identities': [[field['dataset_id'], field['field_id']]]})
            self.assertEqual(fields['items'][0]['field_id'], field['field_id'])
            selected = [dict(dataset_id=field['dataset_id'], field_id=field['field_id'])]
            checked = query(directory, 'validate', {'selection': selected})
            self.assertTrue(checked['valid'], checked)
            return host.model(directory, brief)

        result = prepare_preplanned_start(host.fixture.paths, host.fixture.option, host.fixture.authority,
            host.config, model_runner=lambda _: self.fail('legacy model called'), retrieval_model_runner=model)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[-1]['tool_budget']['queries'], 2)
