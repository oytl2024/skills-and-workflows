import json
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_proposals import (
    proposal_from_issue,
    workflow_change_proposal_to_dict,
    write_workflow_proposals,
)


class WorkflowProposalsTest(unittest.TestCase):
    def test_proposal_from_correlation_issue(self):
        issue = {
            "issue_type": "prod_correlation_cluster",
            "summary": "Three event templates failed production correlation.",
            "evidence_paths": ["runs/20260710_scout/all_alphas.jsonl"],
            "affected_modules": ["template_library", "benchmark"],
        }

        proposal = proposal_from_issue(issue, "2026-07-10T00:00:00Z")

        self.assertEqual(proposal.status, "proposed")
        self.assertIn("production correlation", proposal.proposed_rule_change.lower())
        self.assertIn("template_library", proposal.affected_modules)

    def test_write_workflow_proposals_creates_jsonl_and_markdown(self):
        proposal = proposal_from_issue(
            {
                "issue_type": "pnl_signal_misclassified",
                "summary": "Stable PnL was discarded because fitness was below threshold.",
                "evidence_paths": ["runs/20260710_repair/summary.json"],
                "affected_modules": ["benchmark"],
            },
            "2026-07-10T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_path, markdown_path = write_workflow_proposals(Path(tmp), [proposal])
            rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual(rows[0]["status"], "proposed")
        self.assertIn("Stable PnL", markdown)
        self.assertIn("User Decision Options", markdown)
        self.assertEqual(workflow_change_proposal_to_dict(proposal)["issue_type"], "pnl_signal_misclassified")

    def test_proposal_ids_include_evidence_and_summary_hash(self):
        first = proposal_from_issue(
            {"issue_type": "prod_correlation_cluster", "summary": "First cluster.", "evidence_paths": ["runs/one.json"]},
            "2026-07-10T00:00:00Z",
        )
        second = proposal_from_issue(
            {"issue_type": "prod_correlation_cluster", "summary": "Second cluster.", "evidence_paths": ["runs/two.json"]},
            "2026-07-10T00:00:00Z",
        )

        self.assertNotEqual(first.proposal_id, second.proposal_id)

    def test_write_workflow_proposals_upserts_and_preserves_user_decision(self):
        proposal = proposal_from_issue(
            {"issue_type": "pnl_signal_misclassified", "summary": "Stable PnL was discarded.", "evidence_paths": ["runs/one.json"]},
            "2026-07-10T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            existing = workflow_change_proposal_to_dict(proposal)
            existing["status"] = "accepted"
            existing["user_decision"] = "accept"
            (output_dir / "workflow_change_proposals.jsonl").write_text(json.dumps(existing) + "\n", encoding="utf-8")

            jsonl_path, _ = write_workflow_proposals(output_dir, [proposal])
            rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "accepted")
        self.assertEqual(rows[0]["user_decision"], "accept")


if __name__ == "__main__":
    unittest.main()
