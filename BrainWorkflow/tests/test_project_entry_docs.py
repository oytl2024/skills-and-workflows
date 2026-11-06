"""The project has two concise current entry points and lossless history."""

import unittest
from pathlib import Path
from hashlib import sha256

from wqb.project_architecture import load_architecture


ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / "skills-and-workflows" / "BrainWorkflow" / "docs" / "archive" / "project-recovery"


class ProjectEntryDocsTests(unittest.TestCase):
    def test_product_interaction_contract_is_a_durable_project_rule(self):
        """Input: canonical rules files. Output: assertions. Keep routine interaction and authority boundaries explicit."""
        rules = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        for term in ('BrainWorkflow Product Interaction Contract', 'Option Card', 'Start/Stop',
                     'Final Alpha submission', 'event-driven', 'SELF/PROD', 'in-flight saves',
                     'independently requested maintenance', 'end-to-end offline regression'):
            self.assertIn(term, rules)
        self.assertIn('BrainWorkflow Version Sync And Cleanup', rules)

    def test_milestone_is_current_valid_architecture(self):
        source = (ROOT / "milestone.md").read_text(encoding="utf-8")
        self.assertTrue("<!-- project-modules:start -->" in source)
        self.assertLess(len(source), 25000)
        graph = load_architecture(ROOT / "milestone.md", ROOT)
        self.assertGreaterEqual(len(graph["modules"]), 6)

    def test_workflow_projection_has_real_stages_and_separate_maintenance(self):
        graph = load_architecture(ROOT / "milestone.md", ROOT)
        steps = {step["id"]: step for step in graph["workflow_steps"]}
        for step_id in ("objective", "scout", "seed", "discovery", "backtest", "triage", "repair", "candidate-gate", "approval", "research-record", "knowledge-refresh", "knowledge-compile", "final-submit"):
            self.assertIn(step_id, steps)
        self.assertEqual(steps["scout"]["runtime_stages"], ["scout_seed"])
        self.assertEqual(steps["seed"]["runtime_stages"], ["scout_seed"])
        self.assertEqual(steps["discovery"]["runtime_stages"], ["batch_generation"])
        self.assertEqual(steps["final-submit"]["status"], "manual")
        self.assertEqual(steps["knowledge-compile"]["group"], "knowledge")
        self.assertFalse(any(edge["from"] == "knowledge-compile" and edge["kind"] == "next" for edge in graph["workflow_edges"]))

    def test_todo_owns_mainline_and_latest_handoff(self):
        source = (ROOT / "todo.md").read_text(encoding="utf-8")
        self.assertTrue("## Current mainline" in source)
        self.assertTrue("## Latest handoff" in source)
        self.assertTrue("Exact next action" in source)
        self.assertLess(len(source), 25000)

    def test_legacy_documents_are_archived_without_duplicate_entries(self):
        manifest = (ARCHIVE / "README.md").read_text(encoding="utf-8")
        for name in ("root-milestone.md", "root-todo.md", "repository-milestone.md", "repository-todo.md", "project-todo.md"):
            path = ARCHIVE / name
            self.assertIn(name, manifest)
            if path.is_file():
                self.assertGreater(path.stat().st_size, 1000)
                self.assertIn(sha256(path.read_bytes()).hexdigest(), manifest)
        for base in (ROOT / "skills-and-workflows", ROOT / "skills-and-workflows" / "BrainWorkflow"):
            for name in ("AGENTS.md", "todo.md", "milestone.md"):
                self.assertFalse((base / name).exists(), f"Duplicate root entry: {base / name}")

    def test_agent_rules_use_architecture_first_and_todo_for_handoffs(self):
        for path in (ROOT / "AGENTS.md",):
            rules = path.read_text(encoding="utf-8")
            self.assertIn("milestone.md", rules)
            self.assertIn("todo.md", rules)
            self.assertIn("architecture", rules.lower())
            self.assertIn("handoff", rules.lower())
            self.assertNotIn("milestone.md as the main loop-engineering recovery anchor", rules)


if __name__ == "__main__":
    unittest.main()
