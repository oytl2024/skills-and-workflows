import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from wqb.subagent_handoff import HandoffPacket, LANE_TEMPLATES, build_handoff_packets, write_handoff_packets
from wqb.workflow_launcher import WorkflowRunManifest


class SubagentHandoffTests(unittest.TestCase):
    def manifest(self) -> WorkflowRunManifest:
        return WorkflowRunManifest(
            run_id="20260710-power-pool",
            generated_at="2026-07-10T00:00:00Z",
            run_dir="runs/20260710-power-pool",
            objective="Power Pool",
            region="USA",
            universe="TOP3000",
            delay=1,
            instrument_type="EQUITY",
            mode="plan-only",
            batch_size=30,
            max_simulation_budget=30,
            live_api_enabled=False,
            submit_policy="blocked",
            knowledge_root="knowledge",
            knowledge_artifacts={"data_ledger": "wiki/20_semantics/data_ledger.jsonl"},
            readiness_report_path="runs/20260710-power-pool/readiness_report.md",
            handoff_dir="runs/20260710-power-pool/handoffs",
            lanes=["knowledge-readiness", "data-scheduling"],
        )

    def test_build_handoff_packets_supports_every_lane_template(self):
        manifest = self.manifest()
        manifest = replace(manifest, lanes=list(LANE_TEMPLATES))

        packets = build_handoff_packets(manifest)

        self.assertEqual([packet.lane for packet in packets], list(LANE_TEMPLATES))

    def test_build_handoff_packets_contains_required_fields_and_guardrails(self):
        packets = build_handoff_packets(self.manifest())

        self.assertEqual([packet.lane for packet in packets], ["knowledge-readiness", "data-scheduling"])
        self.assertTrue(all(packet.allowed_files for packet in packets))
        self.assertTrue(all(packet.expected_output for packet in packets))
        self.assertTrue(all(packet.verification_command for packet in packets))
        forbidden_actions = packets[0].forbidden_actions
        self.assertIn("Do not submit alphas", forbidden_actions)
        self.assertIn("Do not automatically change accepted workflow rules", forbidden_actions)
        self.assertIn("Do not run broad platform crawling/full recapture", forbidden_actions)
        self.assertIn("Do not write sensitive values/API credentials into tracked files", forbidden_actions)

    def test_build_handoff_packets_honors_lane_overrides_including_empty(self):
        manifest = self.manifest()

        self.assertEqual([packet.lane for packet in build_handoff_packets(manifest, ["triage"])], ["triage"])
        self.assertEqual(build_handoff_packets(manifest, []), [])

    def test_build_handoff_packets_rejects_unsupported_lane(self):
        with self.assertRaisesRegex(ValueError, "unsupported handoff lane: unknown"):
            build_handoff_packets(self.manifest(), ["unknown"])

    def test_write_handoff_packets_creates_markdown_and_json(self):
        packets = build_handoff_packets(self.manifest())
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_handoff_packets(Path(tmp), packets)
            first_json = Path(outputs[0]["json_path"])
            first_md = Path(outputs[0]["markdown_path"])
            payload = json.loads(first_json.read_text(encoding="utf-8"))
            markdown = first_md.read_text(encoding="utf-8")

        self.assertEqual(payload["lane"], "knowledge-readiness")
        self.assertEqual(set(payload), set(HandoffPacket.__dataclass_fields__))
        self.assertIn("# Subagent Handoff", markdown)
        self.assertIn("## Summary Schema", markdown)
        for key, value in packets[0].summary_schema.items():
            self.assertIn(f"- `{key}`: `{value}`", markdown)
