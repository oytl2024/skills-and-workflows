import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

from tests import test_console_server as server_fixtures
from wqb import console_server
from wqb.console_jobs import finish_job


FORM = {"action": "workflow-start-from-option", "selected_option_id": "option-1",
        "selected_region": "USA", "selected_delay": "1", "selected_universe": "TOP3000",
        "enable_live_api": "on"}
SCOPE = {"region": "USA", "delay": 1, "universe": "TOP3000"}
make_paths = server_fixtures.make_paths


def fixture(paths):
    """Input: ConsolePaths. Output: None. Write isolated certified local start evidence."""
    server_fixtures.ConsoleServerTests()._write_start_fixture(paths, {"title": "Power Pool"}, [{
        "dataset_id": "fundamental3", "field_id": "cash_field", **SCOPE,
        "source_quality": "platform_raw_capture", "coverage_status": "measured_raw",
        "compatible_template_ids": ["matrix_ts_zscore_rank"],
    }])


class OfficialPairedStartTests(unittest.TestCase):
    def test_console_local_policy_overrides_example_without_editing_defaults(self):
        """Input: isolated Console paths. Output: assertions. Freeze local policy without changing shared defaults."""
        from wqb.console_start import register_start
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            config = paths.workflow_root / 'configs'
            config.mkdir(parents=True, exist_ok=True)
            defaults = json.dumps(dict(research_policy=dict(paired_scout=False)))
            (config / 'workflow_defaults.example.json').write_text(defaults, encoding='utf-8')
            local = config / 'workflow_local.json'
            local.write_text(json.dumps(dict(research_policy=dict(paired_scout=True))), encoding='utf-8')
            request = register_start(paths, FORM, 'local-policy')
            self.assertEqual(request['research_policy'], dict(paired_scout=True))
            self.assertEqual((config / 'workflow_defaults.example.json').read_text(encoding='utf-8'), defaults)
            local.write_text(json.dumps(dict(research_policy=dict(paired_scout='true'))), encoding='utf-8')
            with self.assertRaises(ValueError):
                register_start(paths, FORM, 'invalid-local-policy')

    def test_config_to_console_to_real_frozen_snapshot_uses_official_producer(self):
        from copy import deepcopy
        from tests.test_hypothesis_design_acceptance import reviewed_pair_knowledge, HypothesisResourceAuditTests
        from wqb.console_start import register_start, execute_start
        from wqb.runtime_control import read_runtime_control
        from wqb.hypothesis_selection import validate_operational_resource_context
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            original = HypothesisResourceAuditTests.page_pair_fixture

            def certified_resources(case):
                """Input: fixture TestCase. Output: fictional design/resources/scope with complete offline capture evidence."""
                design, resources, scope = original(case)
                old = 'raw/platform/data_fields/fields.jsonl'
                new = 'raw/platform/data_fields/data_fields.jsonl'
                for target in (resources, resources['evidence_pack']):
                    target['source_index'][new] = dict(deepcopy(target['source_index'][old]), path=new)
                    target['source_texts'][new] = target['source_texts'][old]
                resources['field_rows'][0]['source_paths'].append(new)
                return design, resources, scope

            with patch.object(HypothesisResourceAuditTests, 'page_pair_fixture', certified_resources):
                knowledge, scope, _ = reviewed_pair_knowledge(root)
            capture = knowledge / 'raw/platform/data_fields'
            exact = dict(instrument_type='EQUITY', **{k: scope[k] for k in ('region', 'delay', 'universe')})
            (capture / 'manifest.json').write_text(json.dumps(dict(generated_at='2026-10-13T00:00:00Z',
                certification_status='complete', requested_matrix=[exact])), encoding='utf-8')
            (capture / 'scopes.jsonl').write_text(json.dumps(dict(scope=exact, status='completed',
                certification_status='complete')) + '\n', encoding='utf-8')
            manifest_path = knowledge / 'machine/freshness_manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            for row in manifest:
                if row['name'] == 'activity_snapshot':
                    row['path'] = 'wiki/10_platform_rules.md'
                row['max_age_days'] = 90
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            config = paths.workflow_root / 'configs/workflow_defaults.example.json'
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(json.dumps(dict(research_policy=dict(paired_scout=True))), encoding='utf-8')
            request = register_start(paths, FORM, 'official')
            with patch('wqb.preflight_notifications.notify_preflight_blocker', return_value=dict(status='queued')):
                result = execute_start(paths, FORM, request['request_id'])
            self.assertTrue(result['passed'], result)
            run = Path(result['run_dir'])
            snapshot = json.loads((run / 'run_manifest.json').read_text(encoding='utf-8'))['start_snapshot']
            self.assertEqual(snapshot['research_policy'], dict(paired_scout=True))
            self.assertEqual(len(validate_operational_resource_context(snapshot)['experiments']), 1)
            self.assertEqual(read_runtime_control(run)['desired_state'], 'paused')


class BackgroundStartServerTests(unittest.TestCase):
    def test_command_defers_readiness_and_coverage_to_background_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            fixture(paths)
            with patch.object(console_server, "_freshness_clean", side_effect=AssertionError("HTTP freshness")), patch.object(
                console_server, "_validate_option_data_coverage", side_effect=AssertionError("HTTP coverage")
            ):
                command = console_server.build_action_command(FORM["action"], paths, FORM)
            self.assertEqual(command[2], "wqb.console_start")
            self.assertIn("workflow-start", command)
            self.assertIn("--enable-live-api", command)

    def test_start_returns_running_and_duplicate_reuses_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            fixture(paths)

            def launched(job, **kwargs):
                """Input: job/callback. Output: running job. Simulate launch without spawning a worker."""
                return replace(job, status="running", pid=os.getpid())

            with patch.object(console_server, "start_job_async", side_effect=launched) as launch, patch.object(
                console_server, "run_job", side_effect=AssertionError("blocking start")
            ):
                first = console_server.run_console_action(paths, FORM)
                second = console_server.run_console_action(paths, FORM)
            self.assertEqual(first.status, "running")
            self.assertEqual(first.job_id, second.job_id)
            self.assertEqual(launch.call_count, 1)
            self.assertIn("--start-request-id", launch.call_args.args[0].command)

    def test_preflight_json_invalidates_server_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            before = console_server._console_state_signature(paths)
            receipt = paths.runs_root / "start_preflight" / "receipt.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text('{"passed": false}', encoding="utf-8")
            self.assertNotEqual(before, console_server._console_state_signature(paths))

    def test_same_preparation_duplicate_form_does_not_fail_stale_hash(self):
        from wqb.console_start import _selection
        state = {"active_workflow": {"exists": False}, "start_preparation": {
            "request_id": "active", "status": "preparing", "selection": _selection(FORM)}}
        console_server.assert_workflow_action_current({**FORM, "state_hash": "before-preparation"}, state)
        with self.assertRaisesRegex(ValueError, "stale workflow state"):
            console_server.assert_workflow_action_current({**FORM, "selected_universe": "TOP500", "state_hash": "before-preparation"}, state)

    def test_preparation_without_mission_keeps_stop_visible(self):
        state = {"active_workflow": {"exists": False},
                 "start_preparation": {"status": "preparing", "request_id": "id"}}
        fragment = console_server.render_runtime_fragments(state)
        self.assertTrue(fragment["allowed_actions"]["stop_workflow"])
        self.assertFalse(fragment["allowed_actions"]["continue_workflow"])
        self.assertIn("Stop workflow", console_server.render_dashboard(state))
        self.assertIn("Local Start preflight", console_server.render_dashboard(state))

    def test_unverified_new_start_badge_is_neutral(self):
        state = {"readiness": {"passed": False, "context": "new-mission-preflight"}}
        html = console_server.render_runtime_fragments(state)["objective"]
        self.assertIn("Checked on Start", html)
        self.assertNotIn("badge-blocked", html)

    def test_stop_without_mission_completes_locally(self):
        from wqb.console_start import register_start, read_start_request
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            fixture(paths)
            register_start(paths, FORM, "pending")
            with patch.object(console_server, "run_job", side_effect=AssertionError("no mission CLI")):
                result = console_server.run_console_action(paths, {"action": "workflow-stop"})
            self.assertEqual(result.status, "completed")
            self.assertEqual(read_start_request(paths.runs_root)["status"], "cancelled")

    def test_start_on_paused_mission_routes_revision_bound_resume(self):
        state = {"active_workflow": {"exists": True, "run_id": "old"},
                 "runtime_control": {"desired_state": "paused", "request_revision": "pause-revision"}}
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            with patch.object(console_server, "load_runtime_state", return_value=state), patch.object(
                console_server, "_run_console_action_unlocked", return_value="resumed"
            ) as run:
                result = console_server.run_console_action(paths, {**FORM, "expected_runtime_revision": "pause-revision"})
            self.assertEqual(result, "resumed")
            self.assertEqual(run.call_args.args[2], "workflow-auto-continue")
            self.assertEqual(run.call_args.args[1]["expected_runtime_revision"], "pause-revision")

    def test_validated_start_cannot_adopt_stop_revision(self):
        """Input: validated form and changed runtime dict. Output: None. Reject Stop's newer authority."""
        state = {"active_workflow": {"exists": True, "run_id": "old"},
                 "runtime_control": {"desired_state": "paused", "request_revision": "before-stop"}}
        form = {**FORM, "state_hash": console_server._workflow_action_hash(state)}
        console_server.assert_workflow_action_current(form, state)
        self.assertEqual(form.get("expected_runtime_revision"), "before-stop")
        stopped = {**state, "runtime_control": {"desired_state": "paused", "request_revision": "after-stop"}}
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            with patch.object(console_server, "load_runtime_state", return_value=stopped), patch.object(
                console_server, "_run_console_action_unlocked", side_effect=AssertionError("must not resume")
            ):
                with self.assertRaisesRegex(ValueError, "stale runtime intent"):
                    console_server.run_console_action(paths, form)

    def test_start_resume_requires_original_revision_without_fallback(self):
        """Input: unbound Start form. Output: None. Refuse to manufacture Resume authority."""
        state = {"active_workflow": {"exists": True},
                 "runtime_control": {"desired_state": "paused", "request_revision": "new"}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(console_server, "load_runtime_state", return_value=state), patch.object(
                console_server, "_run_console_action_unlocked", side_effect=AssertionError("must not resume")
            ):
                with self.assertRaisesRegex(ValueError, "runtime authority"):
                    console_server.run_console_action(make_paths(Path(tmp)), FORM)

    def test_start_validation_rejects_supplied_stale_revision(self):
        """Input: matching state hash but old authority. Output: None. Never replace supplied authority."""
        state = {"active_workflow": {"exists": True},
                 "runtime_control": {"desired_state": "paused", "request_revision": "after-stop"}}
        form = {**FORM, "state_hash": console_server._workflow_action_hash(state),
                "expected_runtime_revision": "before-stop"}
        with self.assertRaisesRegex(ValueError, "stale runtime intent"):
            console_server.assert_workflow_action_current(form, state)
        self.assertEqual(form["expected_runtime_revision"], "before-stop")

    def test_blocked_preparation_polling_restores_start_controls(self):
        state = {"active_workflow": {"exists": False}, "start_preparation": {"status": "blocked"}}
        fragment = console_server.render_runtime_fragments(state)["workflow_progress"]
        self.assertIn('value="workflow-start-from-option"', fragment)
        self.assertIn("data-runtime-fragment='workflow_progress'", console_server.render_dashboard(state))

    def test_failed_launch_clears_preparing_state(self):
        from wqb.console_start import read_start_request
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            fixture(paths)

            def fail_launch(job, on_complete):
                """Input: job and callback. Output: failed job. Simulate process creation failure without subprocesses."""
                completed = finish_job(job, "failed", exit_code=-1, error="worker not started")
                on_complete(completed)
                return completed

            with patch.object(console_server, "start_job_async", side_effect=fail_launch), patch.object(console_server, "record_console_job_context"):
                result = console_server.run_console_action(paths, FORM)
            self.assertEqual(result.status, "failed")
            self.assertEqual(read_start_request(paths.runs_root)["status"], "blocked")

    def test_synchronous_launcher_exception_invokes_failure_callback(self):
        """Input: launcher raising OSError. Output: None. Persist blocked receipt through the failure callback."""
        from wqb.console_start import read_start_request
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))
            fixture(paths)
            with patch.object(console_server, "start_job_async", side_effect=OSError("launch unavailable")), patch.object(
                console_server, "record_console_job_context"
            ), patch("wqb.preflight_notifications.notify_preflight_blocker", return_value={"status": "queued"}) as notify:
                result = console_server.run_console_action(paths, FORM)
            row = read_start_request(paths.runs_root)
            self.assertEqual(result.status, "failed")
            self.assertEqual(row["status"], "blocked")
            receipt = json.loads(Path(row["preflight_receipt_path"]).read_text(encoding="utf-8"))
            self.assertEqual(receipt["job_id"], result.job_id)
            self.assertEqual(receipt["issues"][0]["message"], "launch unavailable")
            self.assertEqual(row["notification"]["status"], "queued")
            self.assertEqual(notify.call_count, 1)

    def test_success_callback_never_resumes_after_stop_or_revision_change(self):
        from wqb.console_start import _write_request, cancel_start
        from wqb.console_jobs import create_job
        from wqb.runtime_control import request_runtime_state
        for stop in (True, False):
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as tmp:
                paths = make_paths(Path(tmp))
                run_dir = paths.runs_root / "created"
                control = request_runtime_state(run_dir, "paused", enable_live_api=True)
                receipt = {"request_id": "one", "status": "completed", "passed": True,
                           "runtime_request_revision": control["request_revision"], "run_dir": str(run_dir)}
                _write_request(paths.runs_root, receipt)
                job = create_job(paths.job_root, FORM["action"], ["fake"], paths.workflow_root)
                Path(job.stdout_path).write_text(json.dumps(receipt), encoding="utf-8")
                completed = finish_job(job, "completed", exit_code=0)
                if stop:
                    cancel_start(paths.runs_root)
                else:
                    request_runtime_state(run_dir, "paused")
                with patch.object(console_server, "run_console_action") as run, patch.object(console_server, "record_console_job_context"):
                    console_server._complete_start_job(paths, completed)
                run.assert_not_called()


class BackgroundStartWorkerTests(unittest.TestCase):
    def setUp(self):
        """Input: None. Output: None. Allocate isolated worker state and local knowledge fixture."""
        from wqb import console_start
        self.worker = console_start
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = make_paths(Path(self.temp.name))
        fixture(self.paths)
        self.request = self.worker.register_start(self.paths, FORM, "job-1")
        self.notify = patch("wqb.preflight_notifications.notify_preflight_blocker", return_value={"status": "queued"}).start()
        self.addCleanup(patch.stopall)

    def test_start_freezes_configured_policy_and_never_trusts_form_override(self):
        config = self.paths.workflow_root / 'configs/workflow_defaults.example.json'
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps(dict(research_policy=dict(paired_scout=True))), encoding='utf-8')
        request = self.worker.register_start(self.paths, {**FORM, 'research_policy': {'paired_scout': False}}, 'paired')
        self.assertEqual(request['research_policy'], dict(paired_scout=True))
        config.write_text(json.dumps(dict(research_policy=dict(paired_scout=False))), encoding='utf-8')
        run = self.paths.runs_root / 'paired'
        with patch.object(self.worker, 'prepare_start', return_value=dict(passed=True)) as prepare, patch.object(
                console_server, '_validate_option_data_coverage') as coverage, patch.object(
                self.worker.WorkflowOrchestrator, 'start', return_value=dict(run_dir=str(run))) as start:
            result = self.worker.execute_start(self.paths, FORM, request['request_id'])
        self.assertTrue(result['passed'])
        self.assertEqual(prepare.call_args.kwargs['research_policy'], dict(paired_scout=True))
        self.assertEqual(coverage.call_args.kwargs['research_policy'], dict(paired_scout=True))
        self.assertEqual(start.call_args.kwargs['research_policy'], dict(paired_scout=True))

    def test_failed_worker_callback_binds_receipt_and_deduplicates_notification(self):
        """Input: failed/timeout jobs. Output: None. Persist bound evidence and one local notification."""
        from wqb.console_jobs import create_job
        for status in ("failed", "timed_out"):
            with self.subTest(status=status):
                job = create_job(self.paths.job_root, FORM["action"], ["fake"], self.paths.workflow_root)
                request = self.worker.register_start(self.paths, FORM, job.job_id)
                completed = finish_job(job, status, exit_code=-1, error="worker unavailable")
                self.notify.reset_mock()
                with patch.object(console_server, "record_console_job_context"):
                    console_server._complete_start_job(self.paths, completed)
                    console_server._complete_start_job(self.paths, completed)
                row = self.worker.read_start_request(self.paths.runs_root)
                self.assertTrue(row.get("preflight_receipt_path"), row)
                receipt = json.loads(Path(row["preflight_receipt_path"]).read_text(encoding="utf-8"))
                self.assertEqual(receipt["scope"], SCOPE)
                self.assertEqual(receipt["knowledge_root"], str(self.paths.knowledge_root.resolve()))
                self.assertEqual(receipt["request_id"], request["request_id"])
                self.assertEqual(receipt["job_id"], job.job_id)
                self.assertTrue(receipt["blocked"])
                self.assertFalse(receipt["passed"])
                self.assertFalse(receipt["online_refresh_authorized"])
                self.assertEqual(receipt["issues"][0]["code"], "start_worker_failed")
                self.assertEqual(row["notification"]["status"], "queued")
                self.assertEqual(self.notify.call_count, 1)

    def test_failed_worker_notification_does_not_hold_intent_lock_or_undo_stop(self):
        """Input: failed job with delayed notification. Output: None. Stop wins while delivery waits."""
        from wqb.console_jobs import create_job
        job = create_job(self.paths.job_root, FORM["action"], ["fake"], self.paths.workflow_root)
        self.worker._write_request(self.paths.runs_root, {**self.request, "job_id": job.job_id})
        completed = finish_job(job, "failed", exit_code=-1, error="launch failed")
        entered, release = threading.Event(), threading.Event()

        def notify(*args):
            """Input: notification arguments. Output: dict. Delay delivery without external processes."""
            entered.set()
            release.wait(8)
            return {"status": "queued"}

        self.notify.side_effect = notify
        with patch.object(console_server, "record_console_job_context"):
            thread = threading.Thread(target=console_server._complete_start_job, args=(self.paths, completed))
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.worker.cancel_start(self.paths.runs_root)
            finally:
                release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        row = self.worker.read_start_request(self.paths.runs_root)
        self.assertEqual(row["status"], "cancelled")
        self.assertNotIn("notification", row)

    def test_failed_worker_callback_cannot_overwrite_stopped_or_superseded_request(self):
        """Input: obsolete terminal job. Output: None. Preserve Stop or replacement without notification."""
        from wqb.console_jobs import create_job
        job = create_job(self.paths.job_root, FORM["action"], ["fake"], self.paths.workflow_root)
        completed = finish_job(job, "failed", exit_code=-1, error="launch failed")
        for stopped in (True, False):
            with self.subTest(stopped=stopped):
                row = {**self.request, "job_id": job.job_id}
                self.worker._write_request(self.paths.runs_root, row)
                if stopped:
                    self.worker.cancel_start(self.paths.runs_root)
                else:
                    self.worker._write_request(self.paths.runs_root, {**row, "request_id": "replacement", "job_id": "other"})
                before = self.worker.read_start_request(self.paths.runs_root)
                with patch.object(console_server, "record_console_job_context"):
                    console_server._complete_start_job(self.paths, completed)
                self.assertEqual(self.worker.read_start_request(self.paths.runs_root), before)
                self.notify.assert_not_called()
                self.assertFalse(list((self.paths.runs_root / "start_preflight").glob("*-blocked.json")))

    def test_stop_remains_available_while_notification_is_waiting(self):
        entered, release = threading.Event(), threading.Event()
        results = []

        def notify(*args):
            """Input: notification args. Output: dict. Simulate delayed queue without running a subprocess."""
            entered.set()
            release.wait(8)
            return {"status": "queued"}

        self.notify.side_effect = notify
        with patch.object(self.worker, "prepare_start", return_value={"passed": False, "issues": []}):
            thread = threading.Thread(target=lambda: results.append(self.worker.execute_start(self.paths, FORM, self.request["request_id"])))
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.worker.cancel_start(self.paths.runs_root)
            finally:
                release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.worker.read_start_request(self.paths.runs_root)["status"], "cancelled")

    def test_stop_remains_available_during_post_preflight_coverage_validation(self):
        entered, release = threading.Event(), threading.Event()
        results = []

        def validate(*args):
            """Input: validation args. Output: None. Hold local validation to exercise durable cancellation."""
            entered.set()
            release.wait(8)

        with patch.object(self.worker, "prepare_start", return_value={"passed": True}), patch.object(
            console_server, "_validate_option_data_coverage", side_effect=validate
        ), patch.object(self.worker.WorkflowOrchestrator, "start") as create:
            thread = threading.Thread(target=lambda: results.append(self.worker.execute_start(self.paths, FORM, self.request["request_id"])))
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.worker.cancel_start(self.paths.runs_root)
            finally:
                release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]["status"], "cancelled")
        create.assert_not_called()

    def test_exception_creates_blocked_receipt_and_notification(self):
        with patch.object(self.worker, "prepare_start", side_effect=OSError("bad local file")):
            result = self.worker.execute_start(self.paths, FORM, self.request["request_id"])
        receipt = json.loads(Path(result["preflight_receipt_path"]).read_text(encoding="utf-8"))
        self.assertIs(receipt["blocked"], True)
        self.assertIs(receipt["passed"], False)
        self.assertTrue(receipt["issues"][0]["path"])
        self.assertEqual(result["notification"]["status"], "queued")
        self.assertTrue(self.notify.call_args.args[1]["blocked"])

    def test_stop_pauses_partially_committed_mission(self):
        from wqb.runtime_control import request_runtime_state, read_runtime_control
        run_dir = self.paths.runs_root / "partial"
        request_runtime_state(run_dir, "running", enable_live_api=True)
        self.worker._write_request(self.paths.runs_root, {**self.request, "status": "committing", "run_dir": str(run_dir)})
        self.worker.cancel_start(self.paths.runs_root)
        self.assertEqual(read_runtime_control(run_dir)["desired_state"], "paused")

    def test_failed_preflight_never_creates_mission(self):
        with patch.object(self.worker, "prepare_start", return_value={"passed": False, "issues": ["stale"], "receipt_path": "local.json"}), patch.object(
            self.worker.WorkflowOrchestrator, "start"
        ) as create:
            result = self.worker.execute_start(self.paths, FORM, self.request["request_id"])
        self.assertEqual(result["status"], "blocked")
        create.assert_not_called()
        self.assertFalse(list(self.paths.runs_root.glob("*/run_manifest.json")))

    def test_real_local_mission_commit_has_paused_authority(self):
        with patch.object(self.worker, "prepare_start", return_value={"passed": True}):
            result = self.worker.execute_start(self.paths, FORM, self.request["request_id"])
        self.assertEqual(result["status"], "completed", result.get("error"))
        self.assertTrue((Path(result["run_dir"]) / "run_manifest.json").exists())
        self.assertTrue(result["runtime_request_revision"])

    def test_stop_during_preflight_cancels_without_mission(self):
        entered, release = threading.Event(), threading.Event()
        results = []

        def prepare(*args):
            """Input: preflight args. Output: receipt dict. Hold local prep while Stop is acknowledged."""
            entered.set()
            release.wait(3)
            return {"passed": True, "receipt_path": "local.json"}

        with patch.object(self.worker, "prepare_start", side_effect=prepare), patch.object(self.worker.WorkflowOrchestrator, "start") as create:
            thread = threading.Thread(target=lambda: results.append(self.worker.execute_start(self.paths, FORM, self.request["request_id"])))
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.worker.cancel_start(self.paths.runs_root)
            finally:
                release.set()
                thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]["status"], "cancelled")
        create.assert_not_called()

    def test_success_creates_paused_mission_and_revision_once(self):
        run_dir = self.paths.runs_root / "created"
        with patch.object(self.worker, "prepare_start", return_value={"passed": True, "receipt_path": "local.json"}), patch.object(
            self.worker.WorkflowOrchestrator, "start", return_value={"run_dir": str(run_dir), "run_id": "created"}
        ) as create:
            result = self.worker.execute_start(self.paths, FORM, self.request["request_id"])
            repeated = self.worker.execute_start(self.paths, FORM, self.request["request_id"])
        self.assertEqual(result, repeated)
        self.assertTrue(result["runtime_request_revision"])
        self.assertEqual(json.loads((run_dir / "runtime_control.json").read_text())["desired_state"], "paused")
        self.assertEqual(create.call_count, 1)

    def test_cancel_after_creation_invalidates_runtime_revision(self):
        from wqb.runtime_control import read_runtime_control
        run_dir = self.paths.runs_root / "created"
        with patch.object(self.worker, "prepare_start", return_value={"passed": True}), patch.object(
            self.worker.WorkflowOrchestrator, "start", return_value={"run_dir": str(run_dir)}
        ):
            result = self.worker.execute_start(self.paths, FORM, self.request["request_id"])
        self.worker.cancel_start(self.paths.runs_root)
        self.assertNotEqual(result["runtime_request_revision"], read_runtime_control(run_dir)["request_revision"])
        self.assertEqual(read_runtime_control(run_dir)["desired_state"], "paused")

    def test_coverage_validation_after_prepare_still_rejects_uncertified_data(self):
        ledger = self.paths.knowledge_root / "machine" / "data_ledger.jsonl"
        row = json.loads(ledger.read_text().splitlines()[0])
        row["coverage_status"] = "partial"
        ledger.write_text(json.dumps(row), encoding="utf-8")
        with patch.object(self.worker, "prepare_start", return_value={"passed": True}), patch.object(self.worker.WorkflowOrchestrator, "start") as create:
            result = self.worker.execute_start(self.paths, FORM, self.request["request_id"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("certified", result["error"])
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
