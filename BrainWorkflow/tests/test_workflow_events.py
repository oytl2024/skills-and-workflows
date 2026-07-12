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
