import json
import tempfile
import unittest
from pathlib import Path

from wqb.benchmark_rules import BenchmarkRule, write_benchmark_rules_jsonl
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

    def test_create_proposal_from_form_uses_only_workflow_proposal_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge_root = Path(tmp) / "knowledge"
            output_dir = knowledge_root / "wiki" / "70_decisions"
            rulebook = knowledge_root / "wiki" / "50_benchmarks" / "benchmark_rules.jsonl"
            write_benchmark_rules_jsonl(
                rulebook,
                [
                    BenchmarkRule(
                        rule_id="candidate_only_prod_corr",
                        issue_types=["prod_correlation"],
                        description="Candidate gate response.",
                        promotion_condition="Production correlation fails.",
                        action="Use candidate-gate-only action.",
                        evidence_paths=[],
                        consumed_by=["candidate_gate"],
                        risk="candidate-only risk",
                    ),
                    BenchmarkRule(
                        rule_id="proposal_prod_corr",
                        issue_types=["prod_correlation"],
                        description="Workflow proposal response.",
                        promotion_condition="Production correlation fails.",
                        action="Use workflow-proposal action.",
                        evidence_paths=[],
                        consumed_by=["workflow_proposals"],
                        risk="proposal risk",
                    ),
                ],
            )

            proposal = create_proposal_from_form(
                output_dir,
                {"issue_type": "prod_correlation", "summary": "Correlation failed."},
                generated_at="2026-07-16T00:00:00Z",
            )

        self.assertEqual(proposal.proposed_rule_change, "Use workflow-proposal action.")
        self.assertEqual(proposal.risk, "proposal risk")

    def test_create_proposal_from_form_does_not_restore_default_rules_when_runtime_rulebook_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "knowledge" / "wiki" / "70_decisions"

            proposal = create_proposal_from_form(
                output_dir,
                {"issue_type": "pnl_signal", "summary": "Stable PnL needs review."},
                generated_at="2026-07-16T00:00:00Z",
            )

        self.assertNotIn("near_miss_stable_pnl_promotion", proposal.expected_benefit)
        self.assertNotEqual(
            proposal.proposed_rule_change,
            "Create a repair candidate and test one lever at a time before abandoning.",
        )

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
