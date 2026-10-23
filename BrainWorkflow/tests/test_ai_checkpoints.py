import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb.ai_checkpoints import append_ai_checkpoint, load_ai_checkpoints, run_ai_checkpoint, schedule_run_checkpoint


class AICheckpointTests(unittest.TestCase):
    def test_default_ai_executor_also_filters_credential_environment(self):
        """Input: synthetic credentials and mocked legacy executor. Output: assertions. Apply the same boundary without cancellation."""
        import json
        import os
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = append_ai_checkpoint(tmp, 'research_batch_plan', 'FAKE default worker', [], '2026-10-14')
            def reply(argv, **options):
                """Input: fake worker argv/options. Output: process result. Inspect environment without running a subprocess."""
                environment = options.get('env')
                self.assertIsNotNone(environment)
                self.assertEqual({key.upper(): value for key, value in environment.items()}, {'PATH': 'FAKE-runtime'})
                Path(argv[2]).write_text(json.dumps(dict(summary='FAKE bounded choice.', decision={})), encoding='utf-8')
                return CompletedProcess(argv, 0, '', '')
            with patch.dict(os.environ, {'PATH': 'FAKE-runtime', 'WQB_USERNAME': 'FAKE-user',
                    'wqb_password': 'FAKE-password', 'SERVICE_SECRET': 'FAKE-secret',
                    'OPENAI_API_KEY': 'FAKE-key'}, clear=True), patch('wqb.ai_checkpoints.subprocess.run', side_effect=reply):
                result = run_ai_checkpoint(tmp, checkpoint.checkpoint_id, ['fake', '{input}', '{output}'])
            self.assertEqual(result['status'], 'completed', result)

    def test_model_child_does_not_inherit_platform_or_secret_environment(self):
        """Input: synthetic environment and mocked process. Output: assertions. Keep credentials out of model workers."""
        import os
        from unittest.mock import MagicMock
        from wqb.ai_checkpoints import _run_cancellable
        environment = {'PATH': 'runtime', 'SystemRoot': 'C:\\Windows', 'HTTP_PROXY': 'http://127.0.0.1:7897',
                       'WQB_USERNAME': 'fake-user', 'wqb_password': 'fake-value', 'WQB_SESSION': 'fake-session',
                       'SERVICE_TOKEN': 'fake-token', 'SERVICE_SECRET': 'fake-secret',
                       'OPENAI_API_KEY': 'fake-api-key', 'PASSWORD': 'fake-password'}
        process = MagicMock()
        process.returncode = 0
        process.communicate.return_value = ('', '')
        with patch.dict(os.environ, environment, clear=True), patch(
                'wqb.ai_checkpoints.subprocess.Popen', return_value=process) as launch:
            _run_cancellable(['fake-worker'], 5, cancel_on_pause=False)
        child = launch.call_args.kwargs.get('env')
        self.assertIsNotNone(child, 'default process inheritance exposes platform credentials')
        self.assertEqual({key.upper(): value for key, value in child.items()},
                         {key.upper(): environment[key] for key in ('PATH', 'SystemRoot', 'HTTP_PROXY')})

    def test_semantic_checkpoint_preserves_proposals_and_rejects_extra_keys(self):
        import json
        for extra in (False, True):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                checkpoint = append_ai_checkpoint(tmp, 'semantic_compile', 'Compile data', [], '2026-10-13')
                answer = dict(summary='Hypotheses only.', proposals=dict(operators=[], templates=[]))
                if extra:
                    answer['decision'] = {}
                def fake(argv, **kwargs):
                    """Input: mock argv/options. Output: result. Write semantic output without model."""
                    Path(argv[2]).write_text(json.dumps(answer), encoding='utf-8')
                    return type('Result', (), dict(returncode=0, stderr=''))()
                with patch('wqb.ai_checkpoints.subprocess.run', side_effect=fake):
                    result = run_ai_checkpoint(tmp, checkpoint.checkpoint_id, ['fake', '{input}', '{output}'])
                self.assertEqual(result['status'], 'failed' if extra else 'completed')
                if not extra:
                    self.assertEqual(result['proposals'], answer['proposals'])
                    self.assertEqual(load_ai_checkpoints(tmp)[0]['proposals'], answer['proposals'])

    def test_optional_cancellation_does_not_check_research_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = append_ai_checkpoint(tmp, 'semantic_compile', 'Compile data', [], '2026-10-13')
            with patch('wqb.ai_checkpoints.subprocess.Popen') as worker, patch(
                    'wqb.ai_checkpoints.check_submission_allowed', side_effect=AssertionError('not a research task')):
                result = run_ai_checkpoint(tmp, checkpoint.checkpoint_id, ['fake', '{input}', '{output}'],
                                           cancellation_check=lambda: True)
            worker.assert_not_called()
            self.assertEqual(result['status'], 'cancelled')

    def test_independent_cancellation_after_worker_output_discards_proposals(self):
        import json
        from subprocess import Popen
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = append_ai_checkpoint(tmp, 'semantic_compile', 'Compile data', [], '2026-10-13')
            state = {'cancelled': False}
            process = MagicMock(spec=Popen)
            process.returncode = 0
            def launched(argv, **kwargs):
                """Input: mock argv/options. Output: mock process. Return output then cancel."""
                Path(argv[2]).write_text(json.dumps(dict(summary='Unverified.', proposals=dict(operators=[], templates=[]))), encoding='utf-8')
                def communicate(**options):
                    """Input: process options. Output: stdout/stderr pair. Race Stop with completion."""
                    state['cancelled'] = True
                    return '', ''
                process.communicate.side_effect = communicate
                return process
            with patch('wqb.ai_checkpoints.subprocess.Popen', side_effect=launched), patch(
                    'wqb.ai_checkpoints.stop_worker_tree') as stop, patch(
                    'wqb.ai_checkpoints.check_submission_allowed', side_effect=AssertionError('knowledge job')):
                result = run_ai_checkpoint(tmp, checkpoint.checkpoint_id, ['fake', '{input}', '{output}'],
                                           cancellation_check=lambda: state['cancelled'])
            self.assertEqual(result['status'], 'cancelled')
            self.assertNotIn('proposals', result)
            stop.assert_called_once()

    def test_stage_checkpoint_is_run_bound_idempotent_and_executor_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run-1"
            run.mkdir()
            (run / "all_alphas.jsonl").write_text("{}\n", encoding="utf-8")
            schedule = run / "stages" / "schedule" / "research_schedule.json"
            schedule.parent.mkdir(parents=True)
            schedule.write_text("{}", encoding="utf-8")
            first = schedule_run_checkpoint(run, {"current_stage": "repair", "status": "running"},
                                            "2026-10-09T00:00:00Z", [])
            second = schedule_run_checkpoint(run, {"current_stage": "repair", "status": "running"},
                                             "2026-10-09T00:01:00Z", [])
            rows = load_ai_checkpoints(run / "stages" / "ai")
            self.assertEqual(first["checkpoint_id"], second["checkpoint_id"])
            self.assertEqual(first["status"], "pending")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["checkpoint_type"], "near_miss_interpretation")
            self.assertEqual(schedule_run_checkpoint(run, {"current_stage": "scout_seed", "status": "running"},
                                                     "2026-10-09T00:02:00Z", [])["checkpoint_type"], "research_option_reasoning")

    def test_stage_checkpoint_runs_only_configured_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run-1"
            run.mkdir()
            (run / "all_alphas.jsonl").write_text("{}\n", encoding="utf-8")
            with patch("wqb.ai_checkpoints.run_ai_checkpoint", return_value={"checkpoint_id": "ai-1", "status": "completed", "summary": "Consider timing risk."}) as worker:
                result = schedule_run_checkpoint(run, {"current_stage": "repair", "status": "running"},
                                                 "2026-10-09T00:00:00Z", ["worker", "{input}", "{output}"])
            self.assertEqual(result["status"], "completed")
            worker.assert_called_once()

    def test_pending_checkpoint_runs_when_worker_becomes_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run-1"
            run.mkdir()
            (run / "all_alphas.jsonl").write_text("{}\n", encoding="utf-8")
            step = {"current_stage": "repair", "status": "running"}
            pending = schedule_run_checkpoint(run, step, "2026-10-09T00:00:00Z", [])
            with patch("wqb.ai_checkpoints.run_ai_checkpoint", return_value={
                "checkpoint_id": pending["checkpoint_id"], "status": "completed", "summary": "One bounded test."
            }) as worker:
                completed = schedule_run_checkpoint(run, step, "2026-10-09T00:01:00Z", ["worker", "{input}", "{output}"])
            self.assertEqual(completed["status"], "completed")
            worker.assert_called_once()

    def test_append_and_load_ai_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            decisions = Path(tmp) / "knowledge" / "wiki" / "70_decisions"

            checkpoint = append_ai_checkpoint(
                decisions,
                "blocker_explanation",
                "Research readiness is blocked by stale data ledger.",
                ["runs/readiness/report.md"],
                "2026-07-30T00:00:00+00:00",
            )
            rows = load_ai_checkpoints(decisions)

        self.assertTrue(checkpoint.checkpoint_id.startswith("ai-"))
        self.assertEqual(rows[0]["checkpoint_type"], "blocker_explanation")
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["evidence_paths"], ["runs/readiness/report.md"])

    def test_load_ai_checkpoints_skips_malformed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            decisions = Path(tmp)
            (decisions / "ai_checkpoints.jsonl").write_text(
                "not-json\n"
                '{"checkpoint_id":"ai-good","checkpoint_type":"template_innovation","reason":"Need a novel template.","evidence_paths":[],"created_at":"2026-07-30T00:00:00+00:00","status":"pending"}\n',
                encoding="utf-8",
            )

            rows = load_ai_checkpoints(decisions)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["checkpoint_id"], "ai-good")

    def test_executor_requires_explicit_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = append_ai_checkpoint(tmp, "template_innovation", "Find a new idea", [], "2026-10-08T00:00:00Z")
            result = run_ai_checkpoint(tmp, checkpoint.checkpoint_id, [])
            self.assertEqual(result["status"], "pending")
            self.assertEqual(load_ai_checkpoints(tmp)[0]["status"], "pending")

    def test_executor_persists_input_output_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = append_ai_checkpoint(tmp, "template_innovation", "Find a new idea", ["evidence.md"], "2026-10-08T00:00:00Z")
            def fake_run(argv, **kwargs):
                import json
                input_path, output_path = Path(argv[1]), Path(argv[2])
                self.assertEqual(json.loads(input_path.read_text(encoding="utf-8"))["checkpoint_id"], checkpoint.checkpoint_id)
                output_path.write_text(json.dumps({"summary": "Review this hypothesis."}), encoding="utf-8")
                return type("Result", (), {"returncode": 0, "stderr": ""})()
            with patch("wqb.ai_checkpoints.subprocess.run", side_effect=fake_run):
                result = run_ai_checkpoint(tmp, checkpoint.checkpoint_id, ["fake-agent", "{input}", "{output}"])
            self.assertEqual(result["status"], "completed")
            self.assertEqual(load_ai_checkpoints(tmp)[0]["status"], "completed")
            self.assertTrue(Path(result["output_path"]).exists())

    def test_executor_failure_is_not_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = append_ai_checkpoint(tmp, "blocker_explanation", "Explain", [], "2026-10-08T00:00:00Z")
            with patch("wqb.ai_checkpoints.subprocess.run", return_value=type("Result", (), {"returncode": 2, "stderr": "failed"})()):
                result = run_ai_checkpoint(tmp, checkpoint.checkpoint_id, ["fake-agent", "{input}", "{output}"])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(load_ai_checkpoints(tmp)[0]["status"], "failed")
