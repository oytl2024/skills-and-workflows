"""Thin WebView2 host around the existing Console; no research authority."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
from urllib.parse import urlsplit

from wqb import desktop
from wqb.desktop import DesktopConfig, DesktopError, ProcessLock
from wqb.runtime_revision import LOADED_CODE_REVISION


WORKER_MODULES = frozenset({"wqb.cli", "wqb.console_start", "wqb.codex_ai_worker", "wqb.research_group_driver"})
WINDOW_SIZE = (1280, 840)
MIN_WINDOW_SIZE = (760, 540)


def product_root() -> Path:
    """Input: process mode. Output: Path. Locate only immutable source/bundled product assets."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()


def asset_root(root: Path | None = None) -> Path:
    """Input: optional product Path. Output: Path. Require the frontend owner's built entry."""
    assets = (root or product_root()) / "frontend" / "dist"
    if not (assets / "index.html").is_file():
        raise DesktopError("Built frontend/dist/index.html is unavailable; build the frontend before packaging.")
    return assets


def default_workspace() -> Path:
    """Input: source/frozen process. Output: Path. Find brain without embedding developer/private paths."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[3]
    for candidate in Path(sys.executable).resolve().parents:
        if (candidate / "skills-and-workflows" / "BrainWorkflow").is_dir():
            return candidate
    raise DesktopError("Workspace not found. Launch with --workspace-root pointing to your brain workspace.")


def resolve_config(workspace: Path, knowledge: Path | None, runs: Path | None) -> DesktopConfig:
    """Input: workspace and optional data Paths. Output: DesktopConfig. Keep writable data outside bundle."""
    workspace = workspace.resolve()
    return DesktopConfig(product_root(), (knowledge or workspace / "knowledge").resolve(),
                         (runs or workspace / "runs").resolve())


def backend_argv(config: DesktopConfig, workspace: Path, port: int, *,
                 frozen: bool | None = None, executable: str | None = None) -> list[str]:
    """Input: config, workspace, port and mode overrides. Output: argv. Avoid frozen EXE -m recursion."""
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    prefix = [executable or sys.executable]
    if not frozen:
        prefix.extend(["-m", "wqb.desktop_application"])
    return [*prefix, "--backend", "--port", str(port), "--workspace-root", str(workspace),
            "--knowledge-root", str(config.knowledge_root), "--runs-root", str(config.runs_root)]


def packaged_worker_command(command: list[str], *, frozen: bool | None = None,
                            executable: str | None = None) -> list[str]:
    """Input: Python module argv and mode overrides. Output: argv. Normalize allowlisted frozen workers only."""
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not frozen:
        return list(command)
    executable = executable or sys.executable
    if len(command) >= 3 and desktop.canonical(command[0]) == desktop.canonical(executable) and command[1] == "-m":
        if command[2] not in WORKER_MODULES:
            raise DesktopError("Packaged worker module is not allowlisted.")
        return [executable, "--worker-module", command[2], *command[3:]]
    return list(command)


def dispatch_worker(module: str, arguments: list[str]) -> int:
    """Input: allowlisted module name and argv strings. Output: exit code. Execute an explicit packaged worker."""
    if module not in WORKER_MODULES:
        raise DesktopError("Packaged worker module is not allowlisted.")
    sys.argv = [module, *arguments]
    try:
        runpy.run_module(module, run_name="__main__")
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
    return 0


def ensure_backend(config: DesktopConfig, workspace: Path,
                   ports: list[int] | tuple[int, ...] = desktop.DEFAULT_PORTS) -> int:
    """Input: config, external workspace and candidate ports. Output: owned port. Reuse existing lifecycle locks."""
    with ProcessLock(config.runtime_dir / "startup.lock"):
        port, reused = desktop.select_port(config, ports)
        if reused:
            return port
        with (config.runtime_dir / "backend.log").open("ab", buffering=0) as log:
            process = subprocess.Popen(backend_argv(config, workspace, port), cwd=config.workflow_root,
                                       env=desktop.child_environment(), stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=log, **desktop.hidden_process_options())
        deadline = time.monotonic() + desktop.STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if desktop.owns_backend(config, port):
                return port
            if process.poll() is not None:
                raise DesktopError("Console failed to start; see runs/desktop/backend.log. Existing research is retained.")
            time.sleep(desktop.POLL_INTERVAL)
        # An identity timeout is not permission to terminate a potentially active backend.
        raise DesktopError("Console identity timed out; backend was not killed. Inspect runs/desktop/backend.log before retrying.")


def local_url_allowed(url: str, port: int) -> bool:
    """Input: URL string and owned port int. Output: bool. Restrict navigation/resources to exact local origin."""
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port == port
                and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


def load_host():
    """Input: installed system runtime. Output: webview module. Fail visibly without browser-app fallback."""
    if os.name != "nt":
        raise DesktopError("The desktop application requires Windows and system WebView2.")
    try:
        webview = importlib.import_module("webview")
        winforms = importlib.import_module("webview.platforms.winforms")
        if not winforms.is_chromium:
            raise DesktopError("System WebView2 is unavailable. Install it separately; no runtime was downloaded.")
        return webview
    except DesktopError:
        raise
    except Exception as error:
        raise DesktopError("The WebView2/.NET desktop host is unavailable; no browser fallback was started.") from error


def secure_window(window, port: int) -> None:
    """Input: pywebview window and owned port. Output: None. Install native guards before first local navigation."""
    control = window.native.browser.webview

    def navigate(sender, args):
        """Input: WebView2 navigation event. Output: None. Cancel any non-owned destination."""
        if not local_url_allowed(str(args.Uri), port):
            args.Cancel = True

    def popup(sender, args):
        """Input: WebView2 popup event. Output: None. Never open external/native windows."""
        args.Handled = True

    def resource(sender, args):
        """Input: WebView2 resource event. Output: None. Deny remote resources including frames and redirects."""
        if not local_url_allowed(str(args.Request.Uri), port):
            args.Response = sender.Environment.CreateWebResourceResponse(None, 403, "Blocked", "Content-Type: text/plain")

    def permission(sender, args):
        """Input: WebView2 permission event. Output: None. Deny device/native privileges."""
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState
        args.State = CoreWebView2PermissionState.Deny
        args.Handled = True

    def ready(sender, args=None):
        """Input: initialized WebView2 event. Output: None. Disable bridges and install origin-bound handlers."""
        if args is not None and not args.IsSuccess:
            desktop.show_error("System WebView2 initialization failed. Research was not stopped.")
            window.destroy()
            return
        core = control.CoreWebView2
        settings = core.Settings
        settings.IsWebMessageEnabled = False
        settings.AreHostObjectsAllowed = False
        settings.AreDevToolsEnabled = False
        settings.AreDefaultContextMenusEnabled = False
        settings.AreDefaultScriptDialogsEnabled = False
        settings.AreBrowserAcceleratorKeysEnabled = False
        core.NavigationStarting += navigate
        core.FrameNavigationStarting += navigate
        # Remove pywebview's default popup handler (it may invoke the OS browser).
        core.NewWindowRequested -= window.native.browser.on_new_window_request
        core.NewWindowRequested += popup
        core.WebResourceRequested += resource
        core.PermissionRequested += permission
        core.Navigate(f"http://127.0.0.1:{port}/app")

    if control.CoreWebView2 is not None:
        ready(control)
    else:
        control.CoreWebView2InitializationCompleted += ready


def launch_application(config: DesktopConfig, workspace: Path, ports=desktop.DEFAULT_PORTS) -> int:
    """Input: config/workspace/candidate ports. Output: port. Show a thin view; close never Stops/kills research."""
    webview = load_host()
    asset_root()
    port = ensure_backend(config, workspace, ports)
    webview.settings.update(ALLOW_DOWNLOADS=False, ALLOW_FILE_URLS=False,
                            OPEN_EXTERNAL_LINKS_IN_BROWSER=False, IGNORE_SSL_ERRORS=False,
                            REMOTE_DEBUGGING_PORT=None)
    window = webview.create_window("BrainWorkflow", url=None, js_api=None, width=WINDOW_SIZE[0],
                                   height=WINDOW_SIZE[1], min_size=MIN_WINDOW_SIZE, text_select=True)
    window.events.before_show += lambda: secure_window(window, port)
    webview.start(gui="edgechromium", debug=False, private_mode=False,
                  storage_path=str(config.runtime_dir / "webview2"))
    return port


def self_test() -> dict:
    """Input: immutable package only. Output: safe diagnostics dict. Never load host/backend/user configuration."""
    root = product_root()
    sources = sorted((root / "wqb").rglob("*.py"))
    return {"schema_version": 1, "frozen": bool(getattr(sys, "frozen", False)),
            "code_revision": LOADED_CODE_REVISION, "source_file_count": len(sources),
            "source_identity_valid": bool(sources) and LOADED_CODE_REVISION != hashlib.sha256(b"").hexdigest(),
            "frontend_ready": (root / "frontend" / "dist" / "index.html").is_file(),
            "backend_started": False, "native_bridge": False,
            "worker_modules": sorted(WORKER_MODULES)}


def main(argv: list[str] | None = None) -> int:
    """Input: optional argv strings. Output: exit status. Dispatch diagnostics/backend/allowlisted worker or UI."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--worker-module"]:
        if len(arguments) < 2:
            return 2
        return dispatch_worker(arguments[1], arguments[2:])
    parser = argparse.ArgumentParser(description="BrainWorkflow desktop application")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--backend", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    parser.add_argument("--diagnostics-output", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--knowledge-root", type=Path)
    parser.add_argument("--runs-root", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args(arguments)
    if args.self_test:
        diagnostics = self_test()
        payload = json.dumps(diagnostics, sort_keys=True) + "\n"
        if args.diagnostics_output:
            args.diagnostics_output.write_text(payload, encoding="utf-8")
        if sys.stdout is not None:
            print(payload, end="")
        return 0 if diagnostics["source_identity_valid"] else 1
    config = None
    try:
        workspace = args.workspace_root or default_workspace()
        config = resolve_config(workspace, args.knowledge_root, args.runs_root)
        if args.port is not None and not 1 <= args.port <= 65535:
            raise DesktopError("Port must be between 1 and 65535.")
        if args.backend:
            return desktop.run_backend(config, args.port or desktop.DEFAULT_PORTS[0])
        launch_application(config, workspace, [args.port] if args.port else desktop.DEFAULT_PORTS)
        return 0
    except Exception as error:
        if config is not None:
            desktop.report_failure(config, error,
                (lambda message: print(message, file=sys.stderr) if sys.stderr is not None else None)
                if args.backend else desktop.show_error)
        else:
            desktop.show_error(str(error) if isinstance(error, DesktopError) else "Desktop startup failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
