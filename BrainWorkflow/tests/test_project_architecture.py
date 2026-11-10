"""Contract tests for the human and machine project architecture map."""

import tempfile
import unittest
from pathlib import Path

from wqb.project_architecture import ArchitectureError, load_architecture


MAP = """# Project architecture
<!-- project-modules:start -->
| id | name | responsibility | status | code | tests | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| console | Console | Run workflow | implemented | code.py | tests.py | proof.md |
| planner | Planner | Pick research | planned | future.py | future-test.py | future-proof.md |
<!-- project-modules:end -->
<!-- project-dependencies:start -->
| from | to | relation | explanation |
| --- | --- | --- | --- |
| console | planner | invokes | Uses planned research |
<!-- project-dependencies:end -->
### console
Shows durable progress.
### planner
Research option owner.
"""

WORKFLOW = """
<!-- project-workflow-steps:start -->
| id | name | purpose | status | group | runtime_stages | owner_modules | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| scout | Scout | Probe new data | partial | research | scout_seed | planner, console | proof.md |
| seed | Seed | Refine a signal | partial | research | scout_seed | planner | proof.md |
| knowledge-compile | Knowledge compile | Refresh ledgers | partial | knowledge | | planner | proof.md |
| final-submit | Final submit | Submit with consent | manual | submission | | console | proof.md |
<!-- project-workflow-steps:end -->
<!-- project-workflow-edges:start -->
| from | to | kind | explanation |
| --- | --- | --- | --- |
| scout | seed | conditional | Only if signal found |
| knowledge-compile | scout | prerequisite | Fresh knowledge required when stale |
| seed | final-submit | manual | Only after all gates and consent |
<!-- project-workflow-edges:end -->
## Workflow details
### step:scout
Input: new data. Output: checked probes.
### step:seed
Input: signal. Output: reusable seed.
### step:knowledge-compile
Separate maintenance loop; not every run.
### step:final-submit
Human authorization required; never automatic.
"""


class ProjectArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("code.py", "tests.py", "proof.md"):
            (self.root / name).write_text("ok", encoding="utf-8")
        self.map_path = self.root / "milestone.md"

    def load(self, source=MAP):
        self.map_path.write_text(source, encoding="utf-8")
        return load_architecture(self.map_path, self.root)

    def test_valid_graph_and_planned_missing_paths(self):
        graph = self.load()
        self.assertEqual([item["id"] for item in graph["modules"]], ["console", "planner"])
        self.assertEqual(graph["edges"][0]["from"], "console")
        self.assertEqual(graph["modules"][0]["detail"], "Shows durable progress.")
        self.assertEqual(graph["modules"][1]["code"][0]["exists"], False)

    def test_real_knowledge_module_routes_reviewed_semantic_foundations(self):
        """Input: workspace architecture. Output: assertions. Route semantic ownership without claiming live research acceptance."""
        workspace = Path(__file__).resolve().parents[3]
        graph = load_architecture(workspace / 'milestone.md', workspace)
        knowledge = next(row for row in graph['modules'] if row['id'] == 'knowledge')
        for name in ('semantic_contracts.py', 'template_binding.py', 'semantic_publication.py'):
            self.assertIn(name, knowledge['detail'])
            self.assertTrue((workspace / 'skills-and-workflows/BrainWorkflow/wqb' / name).is_file())
        self.assertIn('file-atomic', knowledge['detail'])
        self.assertIn('separate', knowledge['detail'])

    def test_duplicate_id_is_rejected(self):
        with self.assertRaisesRegex(ArchitectureError, "duplicate module"):
            self.load(MAP.replace("| planner | Planner", "| console | Planner"))

    def test_unknown_dependency_is_rejected(self):
        with self.assertRaisesRegex(ArchitectureError, "unknown module"):
            self.load(MAP.replace("| console | planner | invokes", "| console | missing | invokes"))

    def test_missing_implemented_evidence_is_rejected(self):
        with self.assertRaisesRegex(ArchitectureError, "missing path"):
            self.load(MAP.replace("proof.md", "absent.md"))

    def test_directory_reference_is_not_a_clickable_file(self):
        (self.root / "docs").mkdir()
        with self.assertRaisesRegex(ArchitectureError, "not a file"):
            self.load(MAP.replace("proof.md", "docs"))

    def test_partial_module_missing_path_is_rejected(self):
        with self.assertRaisesRegex(ArchitectureError, "missing path"):
            self.load(MAP.replace("| console | Console | Run workflow | implemented", "| console | Console | Run workflow | partial").replace("proof.md", "absent.md"))

    def test_nonplanned_module_requires_code_tests_and_evidence(self):
        with self.assertRaisesRegex(ArchitectureError, "requires code, tests and evidence"):
            self.load(MAP.replace("| code.py | tests.py | proof.md |", "| code.py |  | proof.md |"))

    def test_traversal_is_rejected_even_when_planned(self):
        with self.assertRaisesRegex(ArchitectureError, "outside workspace"):
            self.load(MAP.replace("future.py", "../private.py"))

    def test_malformed_unescaped_table_cell_is_rejected(self):
        with self.assertRaisesRegex(ArchitectureError, "columns"):
            self.load(MAP.replace("Run workflow", "Run | workflow"))

    def test_escaped_pipe_is_accepted(self):
        graph = self.load(MAP.replace("Run workflow", r"Run \| workflow"))
        self.assertEqual(graph["modules"][0]["responsibility"], "Run | workflow")

    def test_workflow_maps_scout_and_seed_to_real_shared_stage(self):
        graph = self.load(MAP + WORKFLOW)
        steps = {item["id"]: item for item in graph["workflow_steps"]}
        self.assertEqual(steps["scout"]["runtime_stages"], ["scout_seed"])
        self.assertEqual(steps["seed"]["runtime_stages"], ["scout_seed"])
        self.assertEqual(steps["knowledge-compile"]["runtime_stages"], [])
        self.assertEqual(steps["final-submit"]["status"], "manual")
        self.assertEqual(graph["workflow_edges"][0]["kind"], "conditional")

    def test_unknown_runtime_stage_is_rejected(self):
        with self.assertRaisesRegex(ArchitectureError, "unknown runtime stage"):
            self.load(MAP + WORKFLOW.replace("| scout_seed |", "| discovery |", 1))

    def test_unknown_owner_is_rejected(self):
        with self.assertRaisesRegex(ArchitectureError, "unknown owner module"):
            self.load(MAP + WORKFLOW.replace("planner, console", "missing, console"))

    def test_unknown_transition_kind_is_rejected(self):
        with self.assertRaisesRegex(ArchitectureError, "invalid workflow edge kind"):
            self.load(MAP + WORKFLOW.replace("| scout | seed | conditional |", "| scout | seed | magic |"))

    def test_unknown_transition_target_is_rejected(self):
        with self.assertRaisesRegex(ArchitectureError, "unknown workflow step"):
            self.load(MAP + WORKFLOW.replace("| scout | seed | conditional |", "| scout | missing | conditional |"))

    def test_missing_nonplanned_workflow_evidence_is_rejected(self):
        with self.assertRaisesRegex(ArchitectureError, "missing path"):
            self.load(MAP + WORKFLOW.replace("| planner, console | proof.md |", "| planner, console | absent.md |"))

    def test_research_step_without_runtime_mapping_is_rejected(self):
        with self.assertRaisesRegex(ArchitectureError, "requires runtime stage"):
            self.load(MAP + WORKFLOW.replace("| scout_seed | planner, console |", "| | planner, console |"))


if __name__ == "__main__":
    unittest.main()
