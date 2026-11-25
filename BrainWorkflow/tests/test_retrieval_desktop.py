"""Optional real windowed-EXE query acceptance; isolated knowledge and no model/platform calls."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time
import unittest
from unittest.mock import patch


DESKTOP_EXE = os.environ.get('WQB_TEST_DESKTOP_EXE', '')
NATIVE_TIMEOUT_SECONDS = 30


@unittest.skipUnless(DESKTOP_EXE, 'set WQB_TEST_DESKTOP_EXE for packaged query acceptance')
class RetrievalDesktopTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('WQB_TEST_CODEX_SANDBOX_EXE'), 'set offline Codex sandbox executable')
    def test_sandbox_pipe_denial_is_not_hidden_by_a_fake_model(self):
        """Input: actual restricted token. Output: documented direct-pipe denial; host MCP is required instead."""
        from tests.test_retrieval_start import RetrievalStartTests
        from wqb.preplanned_start import prepare_preplanned_start
        import tempfile
        host = RetrievalStartTests()
        self.addCleanup(host.doCleanups)
        self.addCleanup(lambda: host.fixture.doCleanups() if hasattr(host, 'fixture') else None)
        output = Path(__file__).resolve().parents[3] / 'runs'
        output.mkdir(exist_ok=True)

        def temporary():
            """Input: none. Output: disposable inherited-ACL fixture, matching ordinary production directories."""
            from types import SimpleNamespace
            from uuid import uuid4
            path = output / ('st-' + uuid4().hex[:8])
            path.mkdir()
            return SimpleNamespace(name=str(path), cleanup=lambda: shutil.rmtree(path))

        with patch('tempfile.TemporaryDirectory', side_effect=temporary):
            host.setUp()
        observations = []

        def model(directory, brief):
            """Input: real owner task/brief. Output: fake plan after querying through the actual restricted-token sandbox."""
            command = [os.environ['WQB_TEST_CODEX_SANDBOX_EXE'], 'sandbox', '--permission-profile', ':read-only',
                '-C', str(directory), DESKTOP_EXE, '--worker-module', 'wqb.retrieval_research_planning',
                'query', '--task-dir', directory.as_posix(), '--operation', 'fields', '--arguments', '{}']
            result = subprocess.run(command, capture_output=True, timeout=30)
            stdout, stderr = result.stdout.decode('utf-8', errors='replace'), result.stderr.decode('utf-8', errors='replace')
            observations.append((result.returncode, stdout, stderr))
            if result.returncode:
                self.assertIn('PermissionError', stdout)
            else:
                self.assertTrue(json.loads(stdout)['items'])
            return host.model(directory, brief)

        result = prepare_preplanned_start(host.fixture.paths, host.fixture.option, host.fixture.authority,
            host.config, model_runner=lambda _: self.fail('legacy model'), retrieval_model_runner=model)
        self.assertTrue(observations)
        self.assertEqual(result['status'], 'completed', observations)

    def test_host_mcp_roundtrip_reuses_owner_scope_and_budget(self):
        from tests.test_retrieval_start import RetrievalStartTests
        from wqb.preplanned_start import prepare_preplanned_start
        host = RetrievalStartTests()
        host.setUp()
        self.addCleanup(host.doCleanups)

        def model(directory, brief):
            """Input: actual owner task. Output: frozen fake plan after a real native MCP exchange."""
            messages = [dict(jsonrpc='2.0', id=1, method='initialize', params=dict(protocolVersion='2025-06-18')),
                dict(jsonrpc='2.0', method='notifications/initialized'), dict(jsonrpc='2.0', id=2, method='tools/list')]
            for number, operation, arguments in [(3, 'contract', dict(section='tool_contracts')), (4, 'fields', {}), (5, 'validate',
                    dict(selection=[dict(dataset_id='not-in-scope', field_id='absent')]))]:
                messages.append(dict(jsonrpc='2.0', id=number, method='tools/call', params=dict(name='query',
                    arguments=dict(operation=operation, arguments_json=json.dumps(arguments)))))
            raw = ('\n'.join(json.dumps(item) for item in messages)+'\n').encode()
            result = subprocess.run([DESKTOP_EXE, '--worker-module', 'wqb.retrieval_research_planning', 'mcp',
                '--task-dir', str(directory)], input=raw, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            replies = [json.loads(line) for line in result.stdout.splitlines()]
            contract = json.loads(replies[2]['result']['content'][0]['text'])
            self.assertEqual(contract['kind'], 'task_contract')
            self.assertIn('source', json.loads(contract['text']))
            fields = json.loads(replies[3]['result']['content'][0]['text'])
            self.assertTrue(fields['items'])
            rejected = json.loads(replies[4]['result']['content'][0]['text'])
            self.assertFalse(rejected['valid'])
            self.assertEqual(rejected['tool_budget']['validations'], 1)
            self.assertEqual(rejected['tool_budget']['queries'], 3)
            return host.model(directory, brief)

        result = prepare_preplanned_start(host.fixture.paths, host.fixture.option, host.fixture.authority,
            host.config, model_runner=lambda _: self.fail('legacy model'), retrieval_model_runner=model)
        self.assertEqual(result['status'], 'completed', result)

    def _nested_checkpoint(self, *, invalid=False):
        """Input: invalid bool. Output: result/checkpoints; launch a real native worker with static offline Codex."""
        from tests.test_retrieval_start import RetrievalStartTests
        from wqb import ai_checkpoints
        from wqb.codex_locator import resolve_codex_executable
        from wqb.preplanned_start import prepare_preplanned_start
        from wqb.retrieval_research_planning import create_retrieval_model_runner
        host = RetrievalStartTests()
        host.setUp()
        self.addCleanup(host.doCleanups)
        exe = Path(DESKTOP_EXE).resolve(strict=True)
        isolated = host.fixture.root / 'offline codex'
        isolated.mkdir()
        for name in ('home', 'appdata', 'localappdata', 'temp', 'codex-home'):
            (isolated / name).mkdir()
        shim = isolated / 'codex.cmd'
        shim.write_text('@echo off\n"'+sys.executable+'" -B "%~dp0fake_model.py" %*\n', encoding='utf-8')
        (isolated / 'fake_model.py').write_text(
            'import sys, pathlib\nroot=pathlib.Path(__file__).parent\n'
            'with (root/"calls.txt").open("a") as f: f.write("invocation\\n")\n'
            '(root/"arguments.txt").write_text("\\n".join(sys.argv[1:]),encoding="utf-8")\n'
            'target=pathlib.Path(sys.argv[sys.argv.index("--output-last-message")+1])\n'
            'target.write_bytes((root/"answer.json").read_bytes())\n', encoding='utf-8')
        environment = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'COMSPEC') if key in os.environ}
        environment.update(PATH=str(isolated), PATHEXT='.CMD', HOME=str(isolated / 'home'),
            USERPROFILE=str(isolated / 'home'), APPDATA=str(isolated / 'appdata'),
            LOCALAPPDATA=str(isolated / 'localappdata'), CODEX_HOME=str(isolated / 'codex-home'),
            TEMP=str(isolated / 'temp'), TMP=str(isolated / 'temp'))
        owners, answers = [], []

        def model(directory, brief):
            """Input: live task Path/brief dict. Output: strict answer from native checkpoint, never a model service."""
            answer = host.model(directory, brief)
            if invalid:
                answer['unexpected_native_property'] = True
            answers.append(answer)
            from tests.test_model_schema_transport import wire_answer
            (isolated / 'answer.json').write_text(json.dumps(wire_answer(brief['output_schema'], answer)), encoding='utf-8')
            owners.append(directory)
            deadline = time.monotonic() + NATIVE_TIMEOUT_SECONDS

            def check_cancelled():
                """Input: none. Output: None or InterruptedError; bound the entire real worker tree to 30 seconds."""
                if time.monotonic() >= deadline:
                    raise InterruptedError('native acceptance deadline')

            with patch.dict(os.environ, environment, clear=True), \
                    patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(exe)):
                target = resolve_codex_executable({}, path_lookup=shutil.which)
                self.assertEqual(Path(target['executable']), shim)
                self.assertEqual(target['source'], 'path')
                runner = create_retrieval_model_runner(directory, dict(ai_executor='codex'), check_cancelled)
                value = runner(brief)
                self.assertEqual(value, answer)
                with self.assertRaisesRegex(ValueError, 'no blind model replay'):
                    runner(brief)
                return value

        with patch('wqb.client.WQBClient._dispatch', side_effect=AssertionError('platform transport forbidden')):
            result = prepare_preplanned_start(host.fixture.paths, host.fixture.option, host.fixture.authority,
                host.config, model_runner=lambda _: self.fail('second model called'), retrieval_model_runner=model)
        self.assertEqual(len(owners), 1)
        calls = isolated / 'calls.txt'
        self.assertTrue(calls.is_file(), result)
        self.assertEqual(calls.read_text().splitlines(), ['invocation'])
        arguments = (isolated / 'arguments.txt').read_text().splitlines()
        # CMD tokenizes the unquoted config assignment at '='.
        self.assertEqual(arguments[0], 'exec')
        self.assertIn('read-only', arguments)
        self.assertTrue(any('model_reasoning_effort' in item for item in arguments))
        self.assertTrue(any('mcp_servers.brain_research.command' in item for item in arguments))
        checkpoints = ai_checkpoints.load_ai_checkpoints(owners[0] / 'stages/ai')
        self.assertEqual(len(checkpoints), 1)
        checkpoint = checkpoints[0]
        attempt = Path(checkpoint['input_path']).parent
        from tests.test_model_schema_transport import assert_closed_provider_objects
        schema = json.loads((attempt / 'output_schema.json').read_text(encoding='utf-8'))
        assert_closed_provider_objects(schema)
        self.assertFalse(schema['additionalProperties'])
        self.assertIn('selection', schema['required'])
        if not invalid:
            self.assertEqual(json.loads(Path(checkpoint['output_path']).read_text(encoding='utf-8')), answers[0])
            again = prepare_preplanned_start(host.fixture.paths, host.fixture.option, host.fixture.authority,
                host.config, model_runner=lambda _: self.fail('legacy replay'),
                retrieval_model_runner=lambda *_: self.fail('native replay'))
            self.assertEqual(again['group']['group_id'], result['group']['group_id'])
            self.assertEqual(calls.read_text().splitlines(), ['invocation'])
            lane = host.fixture.paths.run_root / result['group']['lanes'][0]['run_id']
            self.assertTrue((lane / 'runtime/experiment_tree.json').is_file())
        return result, checkpoint

    def test_nested_native_codex_checkpoint_freezes_strict_tree_once(self):
        """Input: real windowed EXE. Output: completed strict checkpoint and frozen tree without model/network calls."""
        result, checkpoint = self._nested_checkpoint()
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(checkpoint['status'], 'completed', checkpoint)

    def test_nested_native_codex_checkpoint_rejects_non_strict_output(self):
        """Input: static answer with an unknown property. Output: failed strict checkpoint, never a second model."""
        result, checkpoint = self._nested_checkpoint(invalid=True)
        self.assertNotEqual(result['status'], 'completed', result)
        self.assertEqual(checkpoint['status'], 'failed', checkpoint)
        self.assertFalse(Path(checkpoint['output_path']).exists())

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
