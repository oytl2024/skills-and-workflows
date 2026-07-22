import json
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_proposals import (
    WorkflowChangeProposal,
    load_workflow_proposals,
    normalize_proposal_status,
    proposal_from_issue,
    update_workflow_proposal_decision,
    workflow_change_proposal_to_dict,
    write_workflow_proposals,
)


class WorkflowProposalsTest(unittest.TestCase):
    def test_proposal_from_correlation_issue(self):
        issue = {
            "issue_type": "prod_correlation",
            "summary": "Three event templates failed production correlation.",
            "evidence_paths": ["runs/20260710_scout/all_alphas.jsonl"],
            "affected_modules": ["template_library", "benchmark"],
        }

        proposal = proposal_from_issue(issue, "2026-07-10T00:00:00Z")

        self.assertEqual(proposal.status, "proposed")
        self.assertEqual(
            proposal.proposed_rule_change,
            "Down-rank the data-template pair and request template or data novelty before another batch.",
        )
        self.assertIn("prod_correlation_novelty_required", proposal.expected_benefit)
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

    def test_update_workflow_proposal_decision_accepts_spec_b_lifecycle_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            proposal = WorkflowChangeProposal(
                proposal_id="p1",
                generated_at="2026-07-22T00:00:00+00:00",
                issue_type="data_coverage",
                title="Cache-only ledger blocked research",
                trigger="Research readiness saw only cache rows.",
                evidence_paths=["knowledge/wiki/20_semantics/data_ledger.jsonl"],
                affected_modules=["run_readiness", "research_planner"],
                proposed_rule_change="Require authoritative measured data before research.",
                expected_benefit="Prevents false readiness.",
                risk="May block research until capture completes.",
                required_code_changes=["run_readiness"],
                required_knowledge_updates=["knowledge/wiki/20_semantics/data_ledger.md"],
                user_decision_options=["accepted_for_wiki", "accepted_for_implementation", "rejected", "deferred"],
                status="proposed",
                current_behavior="Cache rows can appear in planner inputs.",
                expected_impact="Planner waits for measured data.",
                applied_at="",
                supersedes=[],
            )
            write_workflow_proposals(output_dir, [proposal])

            update_workflow_proposal_decision(output_dir, "p1", "accepted_for_implementation", "Implement readiness guard.")
            rows = load_workflow_proposals(output_dir)

        self.assertEqual(rows[0]["status"], "accepted_for_implementation")
        self.assertEqual(rows[0]["user_decision"], "Implement readiness guard.")
        self.assertEqual(rows[0]["current_behavior"], "Cache rows can appear in planner inputs.")

    def test_update_workflow_proposal_decision_loads_persisted_null_supersedes(self):
        proposal = proposal_from_issue(
            {"issue_type": "manual_review", "summary": "Review persisted null metadata."},
            "2026-07-22T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            persisted = workflow_change_proposal_to_dict(proposal)
            persisted["supersedes"] = None
            (output_dir / "workflow_change_proposals.jsonl").write_text(json.dumps(persisted) + "\n", encoding="utf-8")

            update_workflow_proposal_decision(output_dir, proposal.proposal_id, "deferred", "Need more evidence.")
            rows = load_workflow_proposals(output_dir)

        self.assertEqual(rows[0]["supersedes"], None)
        self.assertEqual(rows[0]["status"], "deferred")

    def test_normalize_proposal_status_maps_legacy_accepted(self):
        self.assertEqual(normalize_proposal_status("accepted"), "accepted_for_implementation")

    def test_normalize_proposal_status_rejects_invalid_value(self):
        with self.assertRaisesRegex(ValueError, "unsupported proposal status"):
            normalize_proposal_status("revise")


if __name__ == "__main__":
    unittest.main()
