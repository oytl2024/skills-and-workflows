import tempfile
import os
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wqb.workflow_auto_continue import auto_continue_workflow


class ResearchLoopRuntimeTests(unittest.TestCase):
    def test_paired_mock_transport_counts_stop_replay_429_and_unknown_post(self):
        import requests
        from tests.test_hypothesis_selection import paired_selection_fixture
        from wqb.client import WQBClient
        from wqb.cli import run_field_batch
        from wqb.recorder import RunRecorder
        from wqb.research_planning import prepare_source_plan, ResearchPlanningBlocked
        from wqb.runtime_control import request_runtime_state, RuntimePaused
        for scenario in ('submitted', 'unknown', '429', 'stop'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                snapshot, experiments = paired_selection_fixture(root)
                run = root / 'run'
                run.mkdir()
                (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)))
                settings = experiments[0]['arms'][0]['settings']
                config = dict(settings, instrument_type=settings['instrumentType'], unit_handling=settings['unitHandling'],
                    nan_handling=settings['nanHandling'], max_alphas_per_round=3, run_root=str(root),
                    knowledge_root=str(root / 'knowledge'))
                request_runtime_state(run, 'running', enable_live_api=True, max_simulations=3)
                (run / 'runtime_status.json').write_text(json.dumps(dict(simulation_attempts=0)))
                plan = prepare_source_plan(run, config, {}, 'now')
                config.update(plan)
                recorder = RunRecorder(root / 'source')
                transport = Mock()
                response = requests.Response()
                response.status_code = 429 if scenario == '429' else 201
                response.url = 'https://offline.invalid/simulations'
                response.headers.update({'Location': '/simulations/offline-pair', 'Retry-After': '1'})
                def dispatch(method, url, **kwargs):
                    """Input: fake HTTP request. Output: fake response or unknown-result timeout. Assert durable evidence before transport."""
                    self.assertEqual(method, 'POST')
                    self.assertTrue(Path(plan['ai_plan_receipt']).is_file())
                    self.assertTrue((recorder.run_dir / 'experiment_sidecar.json').is_file())
                    self.assertEqual(len(recorder.read_jsonl('planned_candidates.jsonl')), 2)
                    self.assertEqual(len(kwargs['json']), 2)
                    if scenario == 'unknown':
                        raise requests.exceptions.ReadTimeout('offline unknown POST outcome')
                    return response
                transport.request.side_effect = dispatch
                client = WQBClient(session=transport)
                client.authenticated = True
                with patch.dict(os.environ, {'BRAIN_WORKFLOW_CONTROL_PATH': str(run)}):
                    if scenario == 'stop':
                        request_runtime_state(run, 'paused')
                        with self.assertRaises(RuntimePaused):
                            run_field_batch(client, recorder, config, workflow_stage='scout', submit_mode='multi', defer_poll=True)
                        self.assertEqual(transport.request.call_count, 0)
                        continue
                    if scenario == 'unknown':
                        with self.assertRaisesRegex(RuntimeError, 'outcome unknown'):
                            run_field_batch(client, recorder, config, workflow_stage='scout', submit_mode='multi', defer_poll=True)
                    else:
                        run_field_batch(client, recorder, config, workflow_stage='scout', submit_mode='multi', defer_poll=True)
                    self.assertEqual(transport.request.call_count, 1)
                    if scenario in ('submitted', 'unknown'):
                        with self.assertRaises(ResearchPlanningBlocked):
                            run_field_batch(client, recorder, config, workflow_stage='scout', submit_mode='multi', defer_poll=True)
                    request_runtime_state(run, 'paused')
                    with self.assertRaises(RuntimePaused):
                        run_field_batch(client, recorder, config, workflow_stage='scout', submit_mode='multi', defer_poll=True)
                    self.assertEqual(transport.request.call_count, 1)
                if scenario == 'submitted':
                    submitted = [row for row in recorder.read_jsonl('simulation_events.jsonl') if row.get('event') == 'SUBMITTED']
                    self.assertEqual(len(submitted), 2)
                    self.assertTrue(all(row.get('experiment_arms') for row in submitted))
                    self.assertEqual(plan['hypothesis_plan_quality'], dict(generated_count=2, selected_count=2,
                        experiment_count=1, model_status='not_requested_frozen_pairs'))

    def test_planning_fault_is_not_silently_classified_as_external_authority(self):
        """Input: exact planning fault. Output: assertions. Route maintenance, retaining budget protection."""
        from wqb.recovery_cases import classify_blocker
        fault = classify_blocker({'next_action': 'research-loop-blocked',
            'stop_reason': 'research_planning_blocked', 'message': 'no valid novel scheduled candidates'})
        self.assertEqual(fault['category'], 'code_or_contract')
        unavailable = classify_blocker({'next_action': 'research-loop-blocked',
                                       'pause_reason': 'research_plan_unavailable'})
        self.assertEqual(unavailable['category'], 'code_or_contract')

    def test_completed_original_batch_allows_new_option_start_not_resume(self):
        """Input: terminal original-only inventory. Output: assertions. Offer new explicit Start without extending old consent."""
        from wqb.console_server import _workflow_action_state
        state = {'active_workflow': {'exists': True},
                 'runtime_control': {'status': 'blocked', 'desired_state': 'running',
                    'original_batch_recovery': {'authorized': True, 'planned': 29, 'checked': 29, 'remaining': 0}},
                 'current_work': {'next_action': 'research-mission-authority-required'}}
        actions = _workflow_action_state(state)
        self.assertTrue(actions['start_workflow'])
        self.assertFalse(actions['continue_workflow'])

    def test_console_round_budget_stop_disables_noop_resume(self):
        from wqb.console_server import _workflow_action_state
        from wqb.console_timeline import select_current_work
        state = {"active_workflow": {"exists": True},
                 "runtime_control": {"status": "blocked", "desired_state": "running"},
                 "research_rounds": {"status": "blocked", "current_round_id": "round-0002",
                                     "stop_reason": "research_simulation_budget_exhausted"}}
        work = select_current_work(state, [])
        self.assertEqual(work["next_action"], "research-loop-blocked")
        state["current_work"] = work
        self.assertFalse(_workflow_action_state(state)["continue_workflow"])
        self.assertTrue(_workflow_action_state(state)["stop_workflow"])

    def test_mission_budget_and_authority_stops_are_not_code_repair_cases(self):
        from wqb.recovery_cases import classify_blocker
        for action in ("research-loop-blocked", "research-mission-authority-required"):
            self.assertEqual(classify_blocker({"next_action": action})["category"], "protected_prerequisite")

    def test_budget_stop_is_not_automatically_resumed(self):
        controller = Mock()
        controller.status.return_value = {"active": True, "status": "paused", "current_stage": "triage",
                                         "pause_reason": "research_simulation_budget_exhausted"}
        with patch("wqb.workflow_auto_continue.WorkflowOrchestrator", return_value=controller):
            result = auto_continue_workflow(Mock(), {}, "now")
        self.assertEqual(result["next_action"], "research-loop-blocked")
        self.assertEqual(result["message"], "research_simulation_budget_exhausted")
        controller.resume.assert_not_called()

    def test_finished_original_batch_has_controller_handoff_not_mission_success(self):
        from wqb.research_rounds import finish_original_batch_handoff
        with tempfile.TemporaryDirectory() as tmp:
            result = finish_original_batch_handoff(Path(tmp), "now")
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["next_action"], "research-mission-authority-required")
