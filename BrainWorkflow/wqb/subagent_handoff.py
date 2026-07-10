from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from wqb.workflow_launcher import WorkflowRunManifest


LANE_TEMPLATES = {
    "knowledge-readiness": {
        "task_title": "Inspect knowledge readiness",
        "expected_output": "readiness_notes.md",
        "verification_command": "python -m unittest tests.test_run_readiness -v",
    },
    "data-scheduling": {
        "task_title": "Rank data candidates",
        "expected_output": "data_schedule_notes.md",
        "verification_command": "python -m unittest tests.test_data_ledger tests.test_research_scheduler -v",
    },
    "template-selection": {
        "task_title": "Rank compatible templates",
        "expected_output": "template_selection_notes.md",
        "verification_command": "python -m unittest tests.test_template_library tests.test_research_scheduler -v",
    },
    "batch-construction": {
        "task_title": "Construct 30-alpha candidate batch",
        "expected_output": "candidate_batch.jsonl",
        "verification_command": "python -m unittest tests.test_generator tests.test_research_workflow -v",
    },
    "simulation-monitor": {
        "task_title": "Monitor simulations",
        "expected_output": "simulation_monitor_summary.md",
        "verification_command": "python -m unittest tests.test_simulator tests.test_cli -v",
    },
    "triage": {
        "task_title": "Triage results",
        "expected_output": "triage_summary.md",
        "verification_command": "python -m unittest tests.test_benchmark tests.test_checker -v",
    },
    "workflow-proposal": {
        "task_title": "Draft workflow rule proposals",
        "expected_output": "workflow_proposals.md",
        "verification_command": "python -m unittest tests.test_workflow_proposals -v",
    },
}


@dataclass(frozen=True)
class HandoffPacket:
    lane: str
    task_title: str
    objective: str
    allowed_files: list[str]
    forbidden_actions: list[str]
    input_artifacts: list[str]
    expected_output: str
    stop_condition: str
    verification_command: str
    summary_schema: dict[str, str]


def _packet_to_dict(packet: HandoffPacket) -> dict[str, Any]:
    """Input: packet. Output: dict. Convert handoff packet to JSON-safe data."""
    return asdict(packet)


def build_handoff_packets(manifest: WorkflowRunManifest, lanes: list[str] | None = None) -> list[HandoffPacket]:
    """Input: manifest and lanes. Output: handoff packets. Build bounded subagent assignments."""
    selected = manifest.lanes if lanes is None else lanes
    packets: list[HandoffPacket] = []
    for lane in selected:
        if lane not in LANE_TEMPLATES:
            raise ValueError(f"unsupported handoff lane: {lane}")
        template = LANE_TEMPLATES[lane]
        packets.append(
            HandoffPacket(
                lane=lane,
                task_title=template["task_title"],
                objective=manifest.objective,
                allowed_files=[manifest.knowledge_root, manifest.run_dir, "BrainWorkflow/wqb", "BrainWorkflow/tests"],
                forbidden_actions=[
                    "Do not submit alphas",
                    "Do not automatically change accepted workflow rules",
                    "Do not run broad platform crawling/full recapture",
                    "Do not write sensitive values/API credentials into tracked files",
                ],
                input_artifacts=[manifest.readiness_report_path, *manifest.knowledge_artifacts.values()],
                expected_output=str(Path(manifest.handoff_dir) / lane / template["expected_output"]),
                stop_condition="Stop after writing the expected output and verification summary.",
                verification_command=template["verification_command"],
                summary_schema={"status": "pass|fail|blocked", "output_path": "string", "notes": "string"},
            )
        )
    return packets


def _packet_markdown(packet: HandoffPacket) -> str:
    """Input: packet. Output: Markdown. Render a subagent handoff packet."""
    lines = [
        "# Subagent Handoff",
        "",
        f"- Lane: `{packet.lane}`",
        f"- Task: {packet.task_title}",
        f"- Objective: {packet.objective}",
        f"- Expected Output: `{packet.expected_output}`",
        f"- Stop Condition: {packet.stop_condition}",
        f"- Verification Command: `{packet.verification_command}`",
        "",
        "## Allowed Files",
    ]
    lines.extend(f"- `{item}`" for item in packet.allowed_files)
    lines.extend(["", "## Forbidden Actions"])
    lines.extend(f"- {item}" for item in packet.forbidden_actions)
    lines.extend(["", "## Input Artifacts"])
    lines.extend(f"- `{item}`" for item in packet.input_artifacts)
    lines.extend(["", "## Summary Schema"])
    lines.extend(f"- `{key}`: `{value}`" for key, value in packet.summary_schema.items())
    return "\n".join(lines) + "\n"


def write_handoff_packets(output_dir: Path, packets: list[HandoffPacket]) -> list[dict[str, str]]:
    """Input: output dir and packets. Output: path rows. Persist Markdown and JSON handoff files."""
    outputs: list[dict[str, str]] = []
    for packet in packets:
        lane_dir = output_dir / packet.lane
        lane_dir.mkdir(parents=True, exist_ok=True)
        json_path = lane_dir / "handoff.json"
        markdown_path = lane_dir / "handoff.md"
        json_path.write_text(json.dumps(_packet_to_dict(packet), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(_packet_markdown(packet), encoding="utf-8")
        outputs.append({"lane": packet.lane, "json_path": str(json_path), "markdown_path": str(markdown_path)})
    return outputs
