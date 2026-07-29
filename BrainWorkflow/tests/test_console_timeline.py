import unittest

from wqb.console_timeline import build_timeline_rows, select_current_work


class ConsoleTimelineTests(unittest.TestCase):
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
            "data_coverage": {"exists": True, "field_count": 120},
            "option_cards": [],
        }

        rows = build_timeline_rows(state)
        current = select_current_work(state, rows)

        capture_rows = [row for row in rows if row["stage_id"] == "platform_data_capture"]
        ai_rows = [row for row in rows if row["stage_id"] == "ai_checkpoint"]
        self.assertEqual(capture_rows[0]["status"], "running")
        self.assertEqual(ai_rows[0]["status"], "waiting")
        self.assertEqual(current["title"], "Platform data capture")
        self.assertIn("12", current["details"][0])

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
