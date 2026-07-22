import json
import tempfile
import unittest
from pathlib import Path

from wqb.console_proposals import create_proposal_from_form
from wqb.workflow_proposals import load_workflow_proposals, update_workflow_proposal_decision


class ConsoleProposalsTests(unittest.TestCase):
    def test_create_proposal_from_form_persists_reviewable_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            proposal = create_proposal_from_form(
                output_dir,
                {
                    "issue_type": "template_innovation",
                    "summary": "Need lower-correlation event template.",
                    "evidence_paths": "runs/a.json\nruns/b.json",
                    "affected_modules": "template_library,benchmark",
                },
                generated_at="2026-07-16T00:00:00Z",
            )
            rows = load_workflow_proposals(output_dir)

        self.assertEqual(proposal.status, "proposed")
        self.assertEqual(rows[0]["proposal_id"], proposal.proposal_id)
        self.assertEqual(rows[0]["affected_modules"], ["template_library", "benchmark"])

    def test_update_workflow_proposal_decision_rewrites_jsonl_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            proposal = create_proposal_from_form(
                output_dir,
                {"issue_type": "manual_review", "summary": "Review rule."},
                generated_at="2026-07-16T00:00:00Z",
            )

            update_workflow_proposal_decision(output_dir, proposal.proposal_id, "accepted_for_implementation", "Approved by user.")
            rows = [json.loads(line) for line in (output_dir / "workflow_change_proposals.jsonl").read_text(encoding="utf-8").splitlines()]
            markdown = (output_dir / "workflow_change_proposals.md").read_text(encoding="utf-8")

        self.assertEqual(rows[0]["status"], "accepted_for_implementation")
        self.assertEqual(rows[0]["user_decision"], "Approved by user.")
        self.assertIn("accepted_for_implementation", markdown)


if __name__ == "__main__":
    unittest.main()
