import tempfile
import unittest
from pathlib import Path

from wqb.workflow_events import append_workflow_event, read_workflow_events


class WorkflowEventsTests(unittest.TestCase):
    def test_append_and_read_events_preserves_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            append_workflow_event(tmp, "workflow_created", {"run_id": "run1"}, "2026-07-12T00:00:00Z")
            append_workflow_event(tmp, "stage_started", {"stage": "schedule"}, "2026-07-12T00:01:00Z")
            events = read_workflow_events(tmp)

        self.assertEqual([event.event_type for event in events], ["workflow_created", "stage_started"])
        self.assertEqual(events[1].payload["stage"], "schedule")

    def test_invalid_event_rows_are_skipped_but_valid_rows_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow_events.jsonl"
            path.write_text("not-json\n" + '{"event_type":"workflow_created","occurred_at":"t","payload":{}}\n', encoding="utf-8")
            events = read_workflow_events(tmp)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "workflow_created")

    def test_malformed_event_objects_are_skipped_but_later_valid_rows_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow_events.jsonl"
            path.write_text(
                '{"event_type":"bad","occurred_at":"t","payload":null}\n'
                '{"event_type":"workflow_created","occurred_at":"t2","payload":{}}\n',
                encoding="utf-8",
            )
            events = read_workflow_events(tmp)

        self.assertEqual([event.event_type for event in events], ["workflow_created"])

    def test_append_after_incomplete_tail_preserves_exactly_one_new_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow_events.jsonl"
            path.write_text('{"event_type":"candidate_status_updated"', encoding="utf-8")

            append_workflow_event(
                tmp,
                "candidate_status_updated",
                {"candidate_id": "c1", "status": "manually_submitted"},
                "2026-07-12T00:01:00Z",
            )
            events = read_workflow_events(tmp)

        self.assertEqual([event.event_type for event in events], ["candidate_status_updated"])
        self.assertEqual(events[0].payload["candidate_id"], "c1")
        self.assertEqual(events[0].payload["status"], "manually_submitted")
