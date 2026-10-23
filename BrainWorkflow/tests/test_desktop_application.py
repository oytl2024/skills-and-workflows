"""Offline contracts for the source and packaged desktop host."""
from pathlib import Path
from types import SimpleNamespace
import os
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

from wqb import desktop_application as app
from wqb.desktop import DesktopConfig, DesktopError


class DesktopApplicationTests(unittest.TestCase):
    def test_frozen_backend_argv_preserves_roots(self):
        with tempfile.TemporaryDirectory(prefix="desktop space ") as directory:
            root = Path(directory) / "\u4e2d\u6587"
            config = DesktopConfig(root / "product", root / "knowledge", root / "runs")
            command = app.backend_argv(config, root, 8765, frozen=True, executable="host.exe")
            self.assertEqual(command[:2], ["host.exe", "--backend"])
            self.assertNotIn("-m", command)
            self.assertEqual(command[command.index("--workspace-root") + 1], str(root))
            self.assertIn(str(config.knowledge_root), command)

    def test_worker_dispatch_is_explicit_and_allowlisted(self):
        command = ["host.exe", "-m", "wqb.console_start", "--run-dir", "space path"]
        self.assertEqual(app.packaged_worker_command(command, frozen=True, executable="host.exe"),
                         ["host.exe", "--worker-module", "wqb.console_start", "--run-dir", "space path"])
        with self.assertRaises(DesktopError):
            app.packaged_worker_command(["host.exe", "-m", "os"], frozen=True, executable="host.exe")
        self.assertEqual(app.packaged_worker_command(command, frozen=False), command)

    def test_asset_root_and_missing_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(DesktopError):
                app.asset_root(root)
            assets = root / "frontend" / "dist"
            assets.mkdir(parents=True)
            (assets / "index.html").write_text("fixture", encoding="utf-8")
            self.assertEqual(app.asset_root(root), assets)

    def test_navigation_is_exact_owned_origin(self):
        for url in ("http://127.0.0.1:8765/app", "http://127.0.0.1:8765/api/status"):
            self.assertTrue(app.local_url_allowed(url, 8765))
        for url in ("https://127.0.0.1:8765/app", "http://localhost:8765/app", "file:///x",
                    "http://127.0.0.1:8766/app", "http://evil/app", "javascript:alert(1)",
                    "http://x@127.0.0.1:8765/app", "http://127.0.0.1:bad/app"):
            self.assertFalse(app.local_url_allowed(url, 8765))

    def test_missing_host_fails_before_backend_start(self):
        with patch.object(app, "load_host", side_effect=DesktopError("unavailable")), \
                patch.object(app, "ensure_backend") as backend:
            with self.assertRaises(DesktopError):
                app.launch_application(Mock(), Path("."))
            backend.assert_not_called()

    def test_self_test_never_starts_backend_or_reads_user_roots(self):
        with patch.object(app, "ensure_backend") as backend, patch.object(app, "load_host") as host:
            result = app.self_test()
            self.assertFalse(result["backend_started"])
            self.assertFalse(result["native_bridge"])
            self.assertIn("code_revision", result)
            backend.assert_not_called()
            host.assert_not_called()

    def test_reuse_and_revision_mismatch_use_source_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            config = DesktopConfig(Path(directory), Path(directory) / "knowledge", Path(directory) / "runs")
            with patch.object(app.desktop, "select_port", return_value=(8765, True)), \
                    patch.object(app.subprocess, "Popen") as spawn:
                self.assertEqual(app.ensure_backend(config, Path(directory), [8765]), 8765)
                spawn.assert_not_called()
            with patch.object(app.desktop, "select_port", side_effect=DesktopError("outdated")), \
                    patch.object(app.subprocess, "Popen") as spawn:
                with self.assertRaisesRegex(DesktopError, "outdated"):
                    app.ensure_backend(config, Path(directory), [8765])
                spawn.assert_not_called()

    def test_workspace_defaults_are_external_to_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "\u4e2d\u6587 space"
            config = app.resolve_config(workspace, None, None)
            self.assertEqual(config.knowledge_root, workspace.resolve() / "knowledge")
            self.assertEqual(config.runs_root, workspace.resolve() / "runs")
            self.assertEqual(config.workflow_root, app.product_root())

    def test_first_launch_uses_explicit_entry_and_owned_health(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = DesktopConfig(root, root / "knowledge", root / "runs")
            with patch.object(app.desktop, "select_port", return_value=(8765, False)), \
                    patch.object(app.desktop, "owns_backend", return_value=True), \
                    patch.object(app.subprocess, "Popen") as spawn:
                self.assertEqual(app.ensure_backend(config, root, [8765]), 8765)
                self.assertIn("--backend", spawn.call_args.args[0])
                spawn.return_value.terminate.assert_not_called()

    def test_identity_timeout_does_not_kill_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = DesktopConfig(root, root / "knowledge", root / "runs")
            with patch.object(app.desktop, "select_port", return_value=(8765, False)), \
                    patch.object(app.desktop, "STARTUP_TIMEOUT", 0), \
                    patch.object(app.subprocess, "Popen") as spawn:
                with self.assertRaisesRegex(DesktopError, "not killed"):
                    app.ensure_backend(config, root, [8765])
                spawn.return_value.terminate.assert_not_called()
                spawn.return_value.kill.assert_not_called()

    def test_dispatch_rejects_unknown_module_before_runpy(self):
        with patch.object(app.runpy, "run_module") as execute:
            with self.assertRaises(DesktopError):
                app.dispatch_worker("os", [])
            execute.assert_not_called()

    def test_view_close_returns_without_stopping_backend(self):
        host = MagicMock()
        host.settings = {}
        with patch.object(app, "load_host", return_value=host), \
                patch.object(app, "asset_root"), patch.object(app, "ensure_backend", return_value=8765), \
                patch.object(app.subprocess, "Popen") as spawn:
            config = DesktopConfig(Path("."), Path("knowledge"), Path("runs"))
            self.assertEqual(app.launch_application(config, Path(".")), 8765)
            self.assertIsNone(host.create_window.call_args.kwargs["js_api"])
            self.assertFalse(host.settings["ALLOW_DOWNLOADS"])
            spawn.assert_not_called()

    def test_native_guards_disable_bridge_navigation_popups_and_remote_resources(self):
        class Event(list):
            def __iadd__(self, handler):
                """Input: callable. Output: Event. Record a native fixture subscription."""
                self.append(handler)
                return self

            def __isub__(self, handler):
                """Input: callable. Output: Event. Remove a native fixture subscription."""
                self.remove(handler)
                return self

        popup_default = Mock()
        core = SimpleNamespace(Settings=SimpleNamespace(), NavigationStarting=Event(),
                               FrameNavigationStarting=Event(), NewWindowRequested=Event([popup_default]),
                               WebResourceRequested=Event(), PermissionRequested=Event(),
                               Navigate=Mock(), Environment=Mock())
        window = SimpleNamespace(native=SimpleNamespace(browser=SimpleNamespace(
            webview=SimpleNamespace(CoreWebView2=core), on_new_window_request=popup_default)))
        app.secure_window(window, 8765)
        self.assertFalse(core.Settings.IsWebMessageEnabled)
        self.assertFalse(core.Settings.AreHostObjectsAllowed)
        core.Navigate.assert_called_once_with("http://127.0.0.1:8765/app")
        external = SimpleNamespace(Uri="https://example.invalid", Cancel=False)
        core.NavigationStarting[0](core, external)
        self.assertTrue(external.Cancel)
        popup = SimpleNamespace(Handled=False)
        core.NewWindowRequested[0](core, popup)
        self.assertTrue(popup.Handled)
        self.assertNotIn(popup_default, core.NewWindowRequested)
        request = SimpleNamespace(Request=SimpleNamespace(Uri="https://example.invalid"), Response=None)
        core.WebResourceRequested[0](core, request)
        self.assertIsNotNone(request.Response)

    def test_existing_backend_health_with_isolated_fixture_roots(self):
        output = app.product_root() / "output"
        output.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="desktop fixture ", dir=output) as directory:
            workspace = Path(directory) / "\u4e2d\u6587 space"
            workspace.mkdir()
            config = app.resolve_config(workspace, None, None)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            environment = app.desktop.child_environment({
                key: value for key, value in os.environ.items()
                if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "PYTHONPATH"}
            })
            with (workspace / "backend-test.log").open("wb") as log:
                process = subprocess.Popen(app.backend_argv(config, workspace, port),
                    cwd=app.product_root(), env=environment, stdout=log, stderr=log,
                    **app.desktop.hidden_process_options())
                try:
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline and process.poll() is None:
                        if app.desktop.owns_backend(config, port):
                            break
                        time.sleep(0.1)
                    health = app.desktop.backend_health(port)
                    self.assertTrue(app.desktop.backend_roots_match(config, health))
                    self.assertEqual(health.get("code_revision"), app.LOADED_CODE_REVISION)
                    self.assertTrue(app.desktop.owns_backend(config, port))
                    self.assertFalse((config.runs_root / "console_jobs").exists())
                finally:
                    # Only this test-created fixture process is terminated; product close never does this.
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
