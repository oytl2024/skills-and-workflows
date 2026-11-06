import tempfile
import unittest
from pathlib import Path

from wqb.workflow_contract import (
    APPROVAL_REQUIRED_FIELDS,
    LEGAL_RUN_TRANSITIONS,
    RESEARCH_RECORD_SECTIONS,
    RUN_STATUSES,
    STAGE_NAMES,
    STAGE_STATUSES,
    render_workflow_contract_pages,
    write_workflow_contract_pages,
)


class WorkflowContractTests(unittest.TestCase):
    def test_contract_terms_match_approved_orchestrator_design(self):
        self.assertEqual(
            RUN_STATUSES,
            (
                "created",
                "running",
                "waiting_for_user",
                "paused",
                "completed",
                "completed_with_warnings",
                "failed",
                "aborted",
            ),
        )
        self.assertIn("candidate_gate", STAGE_NAMES)
        self.assertIn("research_record_sync", STAGE_NAMES)
        self.assertIn("skipped", STAGE_STATUSES)
        self.assertEqual(LEGAL_RUN_TRANSITIONS["created"], ("running", "aborted"))
        self.assertIn("expression_hash", APPROVAL_REQUIRED_FIELDS)
        self.assertIn("repair", RESEARCH_RECORD_SECTIONS)

    def test_rendered_contract_pages_include_workflow_and_approval_rules(self):
        pages = render_workflow_contract_pages()

        self.assertEqual(
            sorted(pages),
            [
                "candidate_approval_policy.md",
                "long_term_workflow_contract.md",
                "research_record_schema.md",
                "workflow_state_machine.md",
            ],
        )
        self.assertIn("Knowledge Maintenance -> Research Planner", pages["long_term_workflow_contract.md"])
        self.assertIn("Only the Orchestrator may write", pages["workflow_state_machine.md"])
        self.assertIn("candidate_id", pages["candidate_approval_policy.md"])
        self.assertIn("near-miss", pages["research_record_schema.md"])
        self.assertIn("created -> running", pages["workflow_state_machine.md"])

    def test_write_workflow_contract_pages_writes_markdown_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_workflow_contract_pages(Path(tmp))

            names = sorted(path.name for path in paths)
            state_page = Path(tmp) / "workflow_state_machine.md"
            state_exists = state_page.exists()

        self.assertEqual(names, sorted(render_workflow_contract_pages()))
        self.assertTrue(state_exists)
