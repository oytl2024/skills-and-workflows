"""Surviving research and architecture routing must not require the retired board."""

import ast
from contextlib import redirect_stderr
import importlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from wqb.project_architecture import load_architecture


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
RETIRED_MODULES = {"signboard_launcher", "architecture_viewer"}


class SignboardRetirementTests(unittest.TestCase):
    def test_legacy_python_entry_cannot_start_processes_or_network(self):
        """Input: optional retired Python entry. Output: assertions; reject without side effects."""
        if not (PACKAGE / "wqb" / "signboard_launcher.py").exists():
            return
        launcher = importlib.import_module("wqb.signboard_launcher")
        errors = io.StringIO()
        with patch("subprocess.Popen", side_effect=AssertionError("process launch forbidden")), patch(
            "socket.socket", side_effect=AssertionError("network forbidden")
        ), redirect_stderr(errors):
            self.assertEqual(launcher.main(), 1)
        self.assertIn("retired", errors.getvalue().lower())
        for name in ("launch_signboard", "prepare_signboard_state", "ensure_viewer"):
            self.assertFalse(hasattr(launcher, name), name)

    def test_surviving_runtime_has_no_board_dependency(self):
        """Input: Python source files. Output: assertions; reject imports of retired adapters."""
        for path in (PACKAGE / "wqb").glob("*.py"):
            if path.stem in RETIRED_MODULES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ""] + [alias.name for alias in node.names]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                for name in names:
                    self.assertTrue(RETIRED_MODULES.isdisjoint(name.split(".")), str(path))

    def test_current_operator_docs_do_not_route_to_retired_board(self):
        """Input: current operator docs. Output: assertions; keep launch guidance board-free."""
        for name in ("architecture-map.md", "user_workflow_manual.md"):
            source = (PACKAGE / "docs" / "operations" / name).read_text(encoding="utf-8")
            for obsolete in ("Signboard", "Open Board.cmd", "management/board", "tools/signboard"):
                self.assertNotIn(obsolete, source, name)
            self.assertIn("milestone.md", source)
            self.assertIn("todo.md", source)

    def test_research_controls_and_launchers_have_no_board_navigation(self):
        """Input: research UI and launchers. Output: assertions; no retired navigation or launch command."""
        paths = list((PACKAGE / "frontend" / "src").rglob("*.tsx"))
        paths += list((PACKAGE / "frontend" / "src").rglob("*.ts"))
        for base in (ROOT, PACKAGE):
            paths += list(base.glob("*.cmd")) + list(base.glob("*.vbs"))
        self.assertTrue(paths)
        for path in paths:
            source = path.read_text(encoding="utf-8-sig").lower()
            for obsolete in ("signboard", "architecture_viewer", "open board.cmd", "management/board"):
                self.assertNotIn(obsolete, source, str(path))

    def test_board_entry_is_disabled_until_audited_deletion(self):
        """Input: optional pending-cleanup launcher. Output: assertions; no executable board command."""
        path = PACKAGE / "management" / "Open Board.cmd"
        if path.exists():
            source = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("python", source)
            self.assertNotIn("signboard_launcher", source)
            self.assertIn("exit /b 1", source)

    def test_ai_architecture_routing_survives_without_board_assets(self):
        """Input: canonical architecture. Output: assertions; retain validated source/test routing."""
        graph = load_architecture(ROOT / "milestone.md", ROOT)
        self.assertGreaterEqual(len(graph["modules"]), 6)
        self.assertGreaterEqual(len(graph["workflow_steps"]), 13)
        self.assertTrue((PACKAGE / "wqb" / "desktop.py").is_file())
        self.assertTrue((PACKAGE / "wqb" / "console_server.py").is_file())


if __name__ == "__main__":
    unittest.main()
