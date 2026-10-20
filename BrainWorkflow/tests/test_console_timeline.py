import unittest
import tempfile
import json
from pathlib import Path

from wqb.console_timeline import build_timeline_rows, select_current_work


class ConsoleTimelineTests(unittest.TestCase):
    def test_maintenance_case_delivery_and_approval_visible_in_current_work(self):
        state = {'runtime_control': {'status': 'blocked', 'reason': 'no_progress_detected',
                                    'recovery_case': {'case_id': 'abc', 'status': 'awaiting_maintenance_confirmation',
                                                      'notification': {'status': 'notified'}}}}
        work = select_current_work(state, [])
        self.assertEqual(work['next_action'], 'maintenance-blocker')
        self.assertIn('notified', ' '.join(work['details']))
        self.assertIn('confirmation', ' '.join(work['details']))

    def test_timeline_marks_running_capture_and_ai_checkpoint(self):
        state = {
            "jobs": [
                {
                    "job_id": "job-capture",
                    "action": "capture-platform-data-fields",
                    "status": "running",
                    "progress_kind": "data_capture",
                    "progress": {"data_field_rows": 12, "capture_dir": "knowledge/raw/platform/data_fields/2026-07-30"},
                }
            ],
            "active_workflow": {"exists": False},
            "workflow_events": [],
            "ai_checkpoints": [
                {
                    "checkpoint_id": "ai-1",
                    "checkpoint_type": "blocker_explanation",
                    "reason": "Explain stale data ledger.",
                    "status": "pending",
                    "evidence_paths": ["runs/readiness/report.md"],
                }
            ],
            "freshness": {"stale_count": 1, "missing_count": 0},
            "knowledge_maintenance": {"status": "completed"},
            "delivery_gate": {"status": "passed"},
            "data_coverage": {"exists": True, "field_count": 120},
            "option_cards": [],
        }

        rows = build_timeline_rows(state)
        current = select_current_work(state, rows)

        capture_rows = [row for row in rows if row["stage_id"] == "platform_data_capture"]
        ai_rows = [row for row in rows if row["stage_id"] == "ai_checkpoint"]
        self.assertEqual(capture_rows[0]["status"], "running")
        self.assertEqual(ai_rows[0]["status"], "waiting")
        self.assertEqual(ai_rows[0]["source"], "ai_judgment")
        self.assertEqual(current["title"], "Platform data capture")
        self.assertIn("12", current["details"][0])
        maintenance_rows = [row for row in rows if row["stage_id"] == "knowledge_compile"]
        self.assertEqual(maintenance_rows[0]["status"], "completed")
        delivery_rows = [row for row in rows if row["stage_id"] == "delivery_gate"]
        self.assertEqual(delivery_rows[0]["status"], "passed")

    def test_timeline_uses_active_workflow_stage_as_current_work(self):
        state = {
            "jobs": [],
            "active_workflow": {"exists": True, "run_id": "run1", "current_stage": "repair", "next_action": "workflow-continue", "waiting_for_user": False},
            "workflow_events": [{"event_type": "repair_started", "occurred_at": "2026-07-30T00:00:00+00:00", "payload": {}}],
            "ai_checkpoints": [],
            "freshness": {"stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120},
            "option_cards": [{"title": "Power Pool"}],
        }

        rows = build_timeline_rows(state)
        current = select_current_work(state, rows)

        repair_rows = [row for row in rows if row["stage_id"] == "repair"]
        self.assertEqual(repair_rows[0]["status"], "running")
        self.assertEqual(current["title"], "Repair")
        self.assertEqual(current["next_action"], "workflow-continue")

    def test_timeline_uses_real_orchestrator_stage_ids_and_persisted_statuses(self):
        base_state = {
            "jobs": [],
            "workflow_events": [],
            "ai_checkpoints": [],
            "freshness": {"stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120},
            "option_cards": [],
        }
        stage_labels = {
            "scout_seed": "Scout and Seed",
            "batch_generation": "30 alpha batch",
            "backtest": "Multisim and backtest",
            "candidate_gate": "Candidate gate",
            "user_approval": "User approval",
            "research_record_sync": "Research record sync",
        }

        for stage_id, label in stage_labels.items():
            with self.subTest(stage_id=stage_id):
                state = {
                    **base_state,
                    "active_workflow": {
                        "exists": True,
                        "run_id": "run1",
                        "current_stage": stage_id,
                        "status": "running",
                        "next_action": "workflow-continue",
                        "waiting_for_user": False,
                        "stages": {stage_id: {"status": "running"}},
                    },
                }

                rows = build_timeline_rows(state)
                current = select_current_work(state, rows)
                row = next(row for row in rows if row["stage_id"] == stage_id)

                self.assertEqual(row["status"], "running")
                self.assertEqual(current["title"], label)

        completed_state = {
            **base_state,
            "active_workflow": {
                "exists": True,
                "run_id": "run1",
                "current_stage": "batch_generation",
                "status": "running",
                "next_action": "workflow-continue",
                "waiting_for_user": False,
                "stages": {
                    "scout_seed": {"status": "completed"},
                    "batch_generation": {"status": "running"},
                },
            },
        }
        completed_rows = build_timeline_rows(completed_state)
        scout_seed = next(row for row in completed_rows if row["stage_id"] == "scout_seed")
        self.assertEqual(scout_seed["status"], "completed")

    def test_only_explicit_ai_checkpoints_are_labeled_ai_judgment(self):
        state = {
            "jobs": [],
            "active_workflow": {"exists": True, "current_stage": "repair", "waiting_for_user": False},
            "workflow_events": [],
            "ai_checkpoints": [
                {
                    "checkpoint_id": "ai-1",
                    "checkpoint_type": "blocker_explanation",
                    "reason": "Explain stale data ledger.",
                    "status": "pending",
                    "evidence_paths": [],
                }
            ],
            "freshness": {"stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120},
            "option_cards": [],
        }

        rows = build_timeline_rows(state)
        sources = {row["stage_id"]: row["source"] for row in rows}

        self.assertEqual(sources["triage"], "deterministic")
        self.assertEqual(sources["repair"], "deterministic")
        self.assertEqual(sources["ai_checkpoint"], "ai_judgment")
        self.assertTrue(all(row["stage_id"] == "ai_checkpoint" for row in rows if row["source"] == "ai_judgment"))

    def test_current_stage_preserves_paused_status_and_terminal_complete(self):
        base_state = {
            "jobs": [],
            "workflow_events": [],
            "ai_checkpoints": [],
            "freshness": {"stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120},
            "option_cards": [],
        }
        paused_state = {
            **base_state,
            "active_workflow": {
                "exists": True,
                "current_stage": "user_approval",
                "status": "paused",
                "waiting_for_user": False,
                "stages": {"user_approval": {"status": "paused"}},
            },
        }
        completed_state = {
            **base_state,
            "active_workflow": {
                "exists": True,
                "current_stage": "complete",
                "status": "completed",
                "waiting_for_user": False,
                "stages": {"complete": {"status": "not_started"}},
            },
        }

        paused_rows = build_timeline_rows(paused_state)
        completed_rows = build_timeline_rows(completed_state)
        paused_row = next(row for row in paused_rows if row["stage_id"] == "user_approval")
        complete_row = next(row for row in completed_rows if row["stage_id"] == "complete")

        self.assertEqual(paused_row["status"], "paused")
        self.assertEqual(complete_row["status"], "completed")

    def test_current_work_explains_source_bridge_recovery_states(self):
        base_state = {
            "jobs": [],
            "active_workflow": {"exists": True, "run_id": "run1", "current_stage": "scout_seed", "status": "paused"},
            "workflow_events": [],
            "ai_checkpoints": [],
            "freshness": {"stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120},
            "option_cards": [],
        }
        expected = {
            "rate_limit_wait": ("Rate limited", "waiting"),
            "maintenance_blocker": ("Maintenance blocker", "blocked"),
            "import_existing": ("Import existing source", "paused"),
            "complete_in_flight": ("Complete in-flight source", "waiting"),
            "retry_planned": ("Retry planned source", "waiting"),
        }

        for action, (title, status) in expected.items():
            with self.subTest(action=action):
                state = {
                    **base_state,
                    "jobs": [
                        {
                            "job_id": "auto-continue",
                            "action": "workflow-auto-continue",
                            "status": "running",
                            "summary_path": "runs/console_jobs/auto-continue/summary.md",
                        }
                    ],
                    "source_bridge": {
                        "action": action,
                        "reason": f"{action} reason",
                        "source_run_id": "source-1",
                        "evidence_paths": ["runs/source-1"],
                    },
                }

                current = select_current_work(state, build_timeline_rows(state))

                self.assertEqual(current["title"], title)
                self.assertEqual(current["status"], status)
                self.assertIn(f"{action} reason", current["details"])
                self.assertIn("Source run: source-1", current["details"])
                self.assertIn("Job ID: auto-continue", current["details"])
                self.assertEqual(
                    current["evidence_paths"],
                    ["runs/source-1", "runs/console_jobs/auto-continue/summary.md"],
                )

    def test_current_work_includes_rate_limit_retry_and_next_check_metadata(self):
        state = {
            "jobs": [],
            "active_workflow": {"exists": True, "run_id": "run1", "current_stage": "scout_seed", "status": "paused"},
            "workflow_events": [],
            "ai_checkpoints": [],
            "freshness": {"stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120},
            "option_cards": [],
            "source_bridge": {
                "action": "maintenance_blocker",
                "reason": "rate limit threshold still blocks retry",
                "source_run_id": "source-1",
                "evidence_paths": ["runs/source-1/rate_limit_state.json"],
                "metadata": {
                    "retry_at": "2026-08-16T07:11:30+00:00",
                    "consecutive_429_count": 3,
                    "max_consecutive_429": 3,
                    "threshold_reached": True,
                    "recovery_eligible": False,
                    "operator_acknowledgement_required": True,
                    "operator_message": "Cooldown has ended, but the 429 threshold still requires operator acknowledgement before retrying existing planned source work.",
                },
            },
        }

        current = select_current_work(state, build_timeline_rows(state))

        self.assertIn("Retry at: 2026-08-16T07:11:30+00:00", current["details"])
        self.assertNotIn("Next check: 2026-08-16T08:15:00+00:00", current["details"])
        self.assertIn("429 count: 3/3", current["details"])
        self.assertIn("Cooldown has ended, but the 429 threshold still requires operator acknowledgement before retrying existing planned source work.", current["details"])

    def test_current_work_prioritizes_blocked_readiness_over_source_retry(self):
        state = {
            "jobs": [],
            "active_workflow": {"exists": True, "run_id": "run1", "current_stage": "scout_seed", "status": "paused"},
            "workflow_events": [],
            "ai_checkpoints": [],
            "freshness": {"stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120},
            "option_cards": [],
            "readiness": {
                "exists": True,
                "passed": False,
                "blocked": True,
                "path": "runs/source/readiness_report.json",
                "issues": [
                    {
                        "level": "block",
                        "code": "stale_scope_data",
                        "message": "Compatible data ledger records for USA D1 TOP3000 are stale.",
                        "action": "Refresh platform raw data fields for this exact scope before research.",
                    }
                ],
            },
            "source_bridge": {
                "action": "retry_planned",
                "reason": "planned source candidates remain",
                "source_run_id": "source-1",
                "evidence_paths": ["runs/source-1/planned_candidates.jsonl"],
            },
        }

        current = select_current_work(state, build_timeline_rows(state))

        self.assertEqual(current["title"], "Readiness blocker")
        self.assertEqual(current["status"], "blocked")
        self.assertEqual(current["next_action"], "readiness-blocked")
        self.assertIn("stale_scope_data: Compatible data ledger records for USA D1 TOP3000 are stale.", current["details"])
        self.assertIn("Action: Refresh platform raw data fields for this exact scope before research.", current["details"])
        self.assertEqual(current["evidence_paths"], ["runs/source/readiness_report.json"])
class PairedTimelineTests(unittest.TestCase):
    def test_existing_timeline_projects_every_arm_without_completing_half_pair(self):
        from wqb.console_timeline import build_timeline_rows
        from tests.test_hypothesis_selection import paired_selection_fixture
        from wqb.research_planning import prepare_source_plan
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, experiments = paired_selection_fixture(root)
            run = root / 'run'
            run.mkdir()
            (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)))
            settings = experiments[0]['arms'][0]['settings']
            config = dict(settings, instrument_type=settings['instrumentType'], unit_handling=settings['unitHandling'],
                nan_handling=settings['nanHandling'], max_alphas_per_round=3)
            plan = prepare_source_plan(run, config, {}, 'now')
            sidecar = json.loads(Path(plan['experiment_sidecar_path']).read_text())
            state = dict(active_workflow=dict(run_dir=str(run)), strategy_progress=dict(rows=[]))
            arms = [row for row in build_timeline_rows(state) if row.get('experiment_id')]
            self.assertEqual([row['status'] for row in arms], ['queued', 'queued'])
            for status, expected in [('SUBMISSION_STARTED', 'uncertain'), ('SUBMITTED', 'submitted'), ('POLLING', 'polling'), ('ERROR', 'failed')]:
                state['strategy_progress']['rows'] = [dict(expression_hash=sidecar['arms'][0]['expression_hash'], status=status)]
                arms = [row for row in build_timeline_rows(state) if row.get('experiment_id')]
                self.assertEqual(arms[0]['status'], expected)
                self.assertFalse(arms[0]['comparison_complete'])
            state['strategy_progress']['rows'] = [dict(expression_hash=sidecar['arms'][0]['expression_hash'],
                status='checked', metrics=dict(sharpe=1))]
            arms = [row for row in build_timeline_rows(state) if row.get('experiment_id')]
            self.assertEqual(arms[0]['status'], 'measured')
            self.assertFalse(any(row['comparison_complete'] for row in arms))
            state['strategy_progress']['rows'].append(dict(expression_hash=sidecar['arms'][1]['expression_hash'],
                status='checked', metrics=dict(sharpe=0.5)))
            self.assertTrue(all(row['comparison_complete'] for row in build_timeline_rows(state) if row.get('experiment_id')))
            from wqb.recorder import RunRecorder
            from wqb.strategy_progress import load_strategy_progress
            recorder = RunRecorder(root / 'source')
            (recorder.run_dir / 'experiment_sidecar.json').write_bytes(Path(plan['experiment_sidecar_path']).read_bytes())
            for arm in sidecar['arms']:
                recorder.append_jsonl('simulation_events.jsonl', dict(event='SUBMITTED', expression_hash=arm['expression_hash']))
                recorder.append_jsonl('all_alphas.jsonl', dict(status='CHECKED', metrics=dict(sharpe=1),
                    expression_hash=arm['expression_hash']))
            state['strategy_progress'] = load_strategy_progress(recorder.run_dir)
            arms = [row for row in build_timeline_rows(state) if row.get('experiment_id')]
            self.assertEqual([row['status'] for row in arms], ['measured', 'measured'])
            self.assertTrue(all(row['comparison_complete'] for row in arms))
            # A new source cannot supply evidence for this historical paired plan.
            state['strategy_progress'] = dict(source_run_dir=str(root / 'next-source'), rows=[])
            self.assertEqual([row for row in build_timeline_rows(state) if row.get('experiment_id')], [])
