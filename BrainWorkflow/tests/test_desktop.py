from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch


class DesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        """Input: test instance. Output: None. Create isolated Path fixtures."""
        self.assertIsNotNone(importlib.util.find_spec("wqb.desktop"), "desktop launcher is missing")
        from wqb import desktop
        self.desktop = desktop
        revision_patch = patch.object(desktop, "LOADED_CODE_REVISION", "fixture-code", create=True)
        revision_patch.start()
        self.addCleanup(revision_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = desktop.DesktopConfig(self.root / "package space", self.root / "knowledge", self.root / "runs")

    def serve(self, payload: object) -> int:
        """Input: JSON-compatible payload. Output: int port. Serve local identity fixtures."""
        body = json.dumps(payload).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                """Input: HTTP request via self. Output: None. Return fixture health bytes."""
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                """Input: str format and object args. Output: None. Silence test HTTP logs."""
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def identity(self) -> dict[str, str]:
        """Input: instance fixture. Output: dict[str,str]. Define the independently specified hook."""
        return {"app": "BrainWorkflow", "workflow_root": str(self.root / "package space"),
                "knowledge_root": str(self.root / "knowledge"), "runs_root": str(self.root / "runs"),
                "server_revision": "fixture", "code_revision": "fixture-code"}

    def test_child_env_repairs_windows_roots_without_mutating_parent(self) -> None:
        """Input: corrupt environment dict. Output: None. Catch inherited broken Windows roots."""
        original = {"SystemRoot": "broken", "windir": "broken", "OTHER": "preserved"}
        actual = self.desktop.child_environment(original)
        self.assertEqual(actual["SystemRoot"].replace("\\", "/").lower(), "c:/windows")
        self.assertEqual(actual["windir"], actual["SystemRoot"])
        self.assertEqual(actual["OTHER"], "preserved")
        self.assertEqual(original["windir"], "broken")

    def test_backend_command_keeps_paths_as_single_arguments_and_disables_browser(self) -> None:
        """Input: Path fixture and int port. Output: None. Catch shell quoting and accidental browser launch."""
        command = self.desktop.backend_command(self.config, 18765, Path("C:/Python/python.exe"))
        self.assertEqual(command[:4], [str(Path("C:/Python/python.exe")), "-m", "wqb.cli", "launch-console"])
        self.assertIn("--no-open-browser", command)
        self.assertEqual(command[command.index("--console-host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--console-port") + 1], "18765")
        self.assertEqual(command[command.index("--run-dir") + 1], str(self.root / "runs"))
        self.assertNotIn("--enable-live-api", command)

    def test_browser_command_uses_stable_private_profile_and_app_mode(self) -> None:
        """Input: browser Path and local URL. Output: None. Catch ordinary-tab launch or profile churn."""
        command = self.desktop.browser_command(Path("C:/Browser space/msedge.exe"), self.config, 18765)
        self.assertEqual(command[0], str(Path("C:/Browser space/msedge.exe")))
        self.assertIn("--app=http://127.0.0.1:18765", command)
        self.assertIn(f"--user-data-dir={self.root / 'runs' / 'desktop' / 'browser'}", command)
        self.assertNotIn("--headless", command)

    def test_browser_discovery_uses_installed_edge(self) -> None:
        """Input: fake installed browser tree. Output: None. Catch missing ProgramFiles discovery."""
        edge = self.root / "Microsoft/Edge/Application/msedge.exe"
        edge.parent.mkdir(parents=True)
        edge.touch()
        with patch.dict(os.environ, {"ProgramFiles(x86)": str(self.root)}, clear=True):
            self.assertEqual(self.desktop.find_browser(), edge)

    def test_bad_explicit_browser_reports_configuration_error(self) -> None:
        """Input: missing override executable. Output: None. Prevent silent fallback from broken configuration."""
        with patch.dict(os.environ, {"BRAINWORKFLOW_BROWSER": str(self.root / "absent.exe")}):
            with self.assertRaises(self.desktop.DesktopError):
                self.desktop.find_browser()

    def test_browser_discovery_survives_missing_process_folder_environment(self):
        edge = self.root / 'known/Microsoft/Edge/Application/msedge.exe'
        edge.parent.mkdir(parents=True)
        edge.touch()
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(self.desktop, 'windows_browser_roots', return_value=[self.root / 'known'], create=True), \
             patch.object(self.desktop.shutil, 'which', return_value=None):
            self.assertEqual(self.desktop.find_browser(), edge)

    def test_pythonw_resolves_sibling_python_for_backend(self) -> None:
        """Input: fake Python installation. Output: None. Catch launching backend through a missing interpreter."""
        executable = self.root / "pythonw.exe"
        executable.touch()
        sibling = self.root / "python.exe"
        sibling.touch()
        self.assertEqual(self.desktop.find_python(executable), sibling)

    def test_health_reuses_exact_identity_even_when_proxy_is_invalid(self) -> None:
        """Input: real local server and bad proxy. Output: None. Prevent proxy routing and false ownership."""
        port = self.serve(self.identity())
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}):
            self.assertTrue(self.desktop.owns_backend(self.config, port))

    def test_health_rejects_other_application_and_different_roots(self) -> None:
        """Input: foreign health payloads. Output: None. Prevent hijacking another Console or arbitrary service."""
        for key in ("app", "workflow_root", "knowledge_root", "runs_root"):
            with self.subTest(key=key):
                payload = self.identity()
                payload[key] = "foreign"
                self.assertFalse(self.desktop.owns_backend(self.config, self.serve(payload)))
        self.assertFalse(self.desktop.owns_backend(self.config, self.serve(["BrainWorkflow"])))

    def test_health_requires_nonempty_revision(self) -> None:
        """Input: incomplete health payloads. Output: None. Reject legacy or malformed identity contracts."""
        for revision in (None, "", "  ", 42):
            with self.subTest(revision=revision):
                payload = self.identity()
                payload["server_revision"] = revision
                self.assertFalse(self.desktop.owns_backend(self.config, self.serve(payload)))

    def test_launcher_refuses_same_workspace_backend_with_old_loaded_code(self) -> None:
        """Input: old-code local server. Output: None. Prevent silently operating an obsolete backend."""
        payload = self.identity()
        payload["code_revision"] = "old-code"
        port = self.serve(payload)

        self.assertFalse(self.desktop.owns_backend(self.config, port))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            free_port = sock.getsockname()[1]
        with self.assertRaisesRegex(self.desktop.DesktopError, "outdated.*restart"):
            self.desktop.select_port(self.config, [port, free_port])

    def test_source_fingerprint_changes_for_uncommitted_code_edits(self) -> None:
        """Input: isolated Python source files. Output: None. Verify content-based compatibility detection."""
        from wqb.runtime_revision import source_code_revision

        source = self.root / "source"
        source.mkdir()
        module = source / "example.py"
        module.write_text("value = 1\n", encoding="utf-8")
        first = source_code_revision(source)
        self.assertEqual(first, source_code_revision(source))
        module.write_text("value = 2\n", encoding="utf-8")
        self.assertNotEqual(first, source_code_revision(source))

    def test_window_timeout_is_not_reported_as_success(self) -> None:
        """Input: browser with no visible window. Output: None. Catch silent app-mode startup failure."""
        process = Mock(pid=123, returncode=0)
        process.poll.return_value = 0
        with patch.object(self.desktop, "find_browser", return_value=Path("browser.exe")), \
                patch.object(self.desktop, "ensure_backend", return_value=18765), \
                patch.object(self.desktop, "app_window", return_value=False), \
                patch.object(self.desktop.subprocess, "Popen", return_value=process), \
                patch.object(self.desktop, "WINDOW_TIMEOUT", 0.02):
            with self.assertRaisesRegex(self.desktop.DesktopError, "window"):
                self.desktop.launch_desktop(self.config)

    def test_port_selection_skips_foreign_listener_and_prefers_existing_owner(self) -> None:
        """Input: real occupied loopback ports. Output: None. Catch opening an arbitrary listener."""
        foreign = self.serve({"app": "unrelated"})
        owned = self.serve(self.identity())
        self.assertEqual(self.desktop.select_port(self.config, [foreign, owned]), (owned, True))
        with self.assertRaises(self.desktop.DesktopError):
            self.desktop.select_port(self.config, [foreign])

    def test_port_selection_returns_free_port_without_marking_it_owned(self) -> None:
        """Input: free loopback port. Output: None. Verify first launch can choose a free listener."""
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.assertEqual(self.desktop.select_port(self.config, [port]), (port, False))

    def test_os_lock_blocks_other_process_and_recovers_after_release(self) -> None:
        """Input: lock Path and child process. Output: None. Prevent concurrent backend ownership."""
        lock_path = self.root / "backend.lock"
        code = "from pathlib import Path; from wqb.desktop import ProcessLock; import sys; lock=ProcessLock(Path(sys.argv[1])); sys.exit(0 if lock.acquire() else 7)"
        lock = self.desktop.ProcessLock(lock_path)
        self.assertTrue(lock.acquire())
        try:
            completed = subprocess.run([sys.executable, "-c", code, str(lock_path)], env=self.desktop.child_environment(), capture_output=True)
            self.assertEqual(completed.returncode, 7, completed.stderr.decode())
        finally:
            lock.release()
        completed = subprocess.run([sys.executable, "-c", code, str(lock_path)], env=self.desktop.child_environment(), capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())

    def test_start_reuses_identity_without_spawning_backend(self) -> None:
        """Input: already-owned local service. Output: None. Catch duplicate launch on repeated double-click."""
        port = self.serve(self.identity())
        with patch("wqb.desktop.subprocess.Popen", side_effect=AssertionError("must reuse")):
            self.assertEqual(self.desktop.ensure_backend(self.config, [port]), port)

    def test_startup_failure_creates_log_and_visible_message(self) -> None:
        """Input: controlled DesktopError. Output: None. Catch silent pythonw startup failures."""
        messages = []
        self.desktop.report_failure(self.config, self.desktop.DesktopError("Browser unavailable"), messages.append)
        log = self.config.runtime_dir / "startup.log"
        self.assertTrue(log.is_file())
        self.assertIn("Browser unavailable", log.read_text(encoding="utf-8"))
        self.assertIn(str(log), messages[0])

    @unittest.skipUnless(os.name == "nt", "Windows Script Host integration")
    def test_double_click_entries_resolve_paths_forward_arguments_and_repair_env(self) -> None:
        """Input: copied launchers and fake local module. Output: None. Run actual scripts without browser or research."""
        package = Path(self.desktop.__file__).resolve().parents[1]
        workspace = package.parents[1]
        target = self.root / "workspace space & test"
        copied_package = target / "skills-and-workflows" / "BrainWorkflow"
        module = copied_package / "wqb"
        module.mkdir(parents=True)
        capture = target / "capture.json"
        (module / "__init__.py").write_text("", encoding="utf-8")
        (module / "desktop.py").write_text(
            "import json, os, pathlib, sys\n"
            "pathlib.Path(os.environ['TEST_CAPTURE']).write_text(json.dumps({"
            "'argv':sys.argv[1:], 'cwd':os.getcwd(), 'root':os.environ['SystemRoot'], "
            "'windir':os.environ['windir'], 'preserved':os.environ['TEST_PRESERVED']}))\n"
            "sys.exit(int(os.environ.get('TEST_EXIT', '0')))\n", encoding="utf-8")
        for source, destination in (
                (workspace / "BrainWorkflow.vbs", target / "BrainWorkflow.vbs"),
                (workspace / "BrainWorkflow.cmd", target / "BrainWorkflow.cmd"),
                (package / "launch-desktop.vbs", copied_package / "launch-desktop.vbs"),
                (package / "launch-desktop.cmd", copied_package / "launch-desktop.cmd")):
            self.assertTrue(source.is_file(), f"Executable launcher missing: {source}")
            shutil.copyfile(source, destination)
        env = self.desktop.child_environment()
        env.update(TEST_CAPTURE=str(capture), BRAINWORKFLOW_PYTHON=sys.executable,
                   SystemRoot="broken", windir="broken", TEST_PRESERVED="space & ! unchanged")
        cscript = "C:/Windows/System32/cscript.exe"
        for entry in (target / "BrainWorkflow.vbs", copied_package / "launch-desktop.vbs",
                      target / "BrainWorkflow.cmd", copied_package / "launch-desktop.cmd"):
            with self.subTest(entry=entry.name):
                if capture.exists():
                    capture.unlink()
                forwarded = ["--runs-root", str(target / "runs with spaces & punctuation!") + "\\"]
                arguments = [str(entry), *forwarded]
                # WSH (unlike Python's CRT parser) treats backslashes literally.
                script_arguments = " ".join('"' + value + '"' for value in arguments)
                if entry.suffix == ".vbs":
                    command = subprocess.list2cmdline([cscript, "//nologo"]) + " " + script_arguments
                else:
                    # cmd /s /c removes one outer quote pair before parsing the batch path.
                    command = str(Path("C:/Windows/System32/cmd.exe")) + ' /d /v:on /s /c "' + script_arguments + '"'
                result = subprocess.run(command, cwd=self.root, env=env, capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))
                self.assertTrue(capture.is_file(), "Launcher did not wait for the bootstrap")
                actual = json.loads(capture.read_text())
                self.assertEqual(actual["argv"], forwarded)
                self.assertEqual(Path(actual["cwd"]), copied_package)
                self.assertEqual(actual["root"].replace("\\", "/").lower(), "c:/windows")
                self.assertEqual(actual["windir"], actual["root"])
                self.assertEqual(actual["preserved"], env["TEST_PRESERVED"])
                capture.unlink()
                failure = subprocess.run(command, cwd=self.root, env=dict(env, TEST_EXIT="7"),
                                         capture_output=True, timeout=20)
                self.assertEqual(failure.returncode, 1)
                self.assertTrue(capture.is_file(), "Failure must come from the executed bootstrap")
                expected_error = "Desktop startup failed (launcher exit 1)" if entry.parent == target else "Desktop startup failed (exit 7)"
                self.assertIn(expected_error, failure.stdout.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
