import json
import tempfile
import unittest
from pathlib import Path

from wqb.benchmark_rules import BenchmarkRule
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
    def test_proposal_uses_injected_persisted_benchmark_rule(self):
        persisted = BenchmarkRule(
            rule_id="curated_prod_corr",
            issue_types=["prod_correlation"],
            description="Curated production-correlation response.",
            promotion_condition="Production correlation fails.",
            action="Use the curated novelty action.",
            evidence_paths=["wiki/50_benchmarks/curated.md"],
            consumed_by=["workflow_proposals"],
            risk="curated risk",
        )

        proposal = proposal_from_issue(
            {"issue_type": "prod_correlation", "summary": "Correlation failed."},
            "2026-07-22T00:00:00Z",
            benchmark_rules=[persisted],
        )

        self.assertEqual(proposal.proposed_rule_change, "Use the curated novelty action.")
        self.assertIn("curated_prod_corr", proposal.expected_benefit)

    def test_proposal_filters_matching_rules_by_workflow_proposals_consumer(self):
        candidate_gate_rule = BenchmarkRule(
            rule_id="candidate_only_prod_corr",
            issue_types=["prod_correlation"],
            description="Candidate gate response.",
            promotion_condition="Production correlation fails.",
            action="Use candidate-gate-only action.",
            evidence_paths=[],
            consumed_by=["candidate_gate"],
            risk="candidate-only risk",
        )
        proposal_rule = BenchmarkRule(
            rule_id="proposal_prod_corr",
            issue_types=["prod_correlation"],
            description="Workflow proposal response.",
            promotion_condition="Production correlation fails.",
            action="Use workflow-proposal action.",
            evidence_paths=[],
            consumed_by=["workflow_proposals"],
            risk="proposal risk",
        )

        proposal = proposal_from_issue(
            {"issue_type": "prod_correlation", "summary": "Correlation failed."},
            "2026-07-22T00:00:00Z",
            benchmark_rules=[candidate_gate_rule, proposal_rule],
        )

        self.assertEqual(proposal.proposed_rule_change, "Use workflow-proposal action.")
        self.assertEqual(proposal.risk, "proposal risk")
        self.assertIn("proposal_prod_corr", proposal.expected_benefit)
        self.assertNotIn("candidate_only_prod_corr", proposal.expected_benefit)

    def test_load_normalizes_legacy_accepted_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "workflow_change_proposals.jsonl").write_text(
                json.dumps({"proposal_id": "legacy", "status": "accepted"}) + "\n",
                encoding="utf-8",
            )

            rows = load_workflow_proposals(output_dir)

        self.assertEqual(rows[0]["status"], "accepted_for_implementation")

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
            "Down-rank data-template pairs that repeatedly fail production correlation, and require a distinct data source, operator skeleton, or economic hypothesis before reusing them.",
        )
        self.assertNotIn("prod_correlation_novelty_required", proposal.expected_benefit)
        self.assertIn("template_library", proposal.affected_modules)

    def test_default_proposal_knowledge_updates_are_canonical(self):
        proposal = proposal_from_issue(
            {"issue_type": "manual_review", "summary": "Record repeated workflow issue."},
            "2026-07-22T00:00:00Z",
        )

        combined = "\n".join(proposal.required_knowledge_updates)
        self.assertNotIn("wiki/50_benchmarks", combined)
        self.assertNotIn("wiki/60_workflows", combined)
        self.assertEqual(
            proposal.required_knowledge_updates,
            [
                "knowledge/machine/benchmark_rules.jsonl",
                "knowledge/wiki/40_benchmark_and_repair_rules.md",
                "knowledge/wiki/50_engineering_lessons.md",
            ],
        )

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
        self.assertEqual(rows[0]["status"], "accepted_for_implementation")
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
