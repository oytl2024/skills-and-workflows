"""Dependency-light desktop app-mode launcher; never starts research itself."""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import sys
import time
from typing import Callable
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from wqb.runtime_revision import LOADED_CODE_REVISION


DEFAULT_PORTS = tuple(range(8765, 8785))
STARTUP_TIMEOUT = 45.0
HEALTH_TIMEOUT = 0.35
POLL_INTERVAL = 0.15
WINDOW_TIMEOUT = 8.0
HEALTH_MAX_BYTES = 8192
WINDOWS_BROWSER_FOLDER_IDS = (42, 38, 28)


class DesktopError(RuntimeError):
    """A startup problem whose message is safe to display to the operator."""


@dataclass(frozen=True)
class DesktopConfig:
    workflow_root: Path
    knowledge_root: Path
    runs_root: Path

    @property
    def runtime_dir(self) -> Path:
        """Input: DesktopConfig self. Output: Path. Locate desktop process/profile state."""
        return self.runs_root / "desktop"


def child_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Input: optional str environment dict. Output: dict[str,str]. Repair Windows child roots."""
    env = dict(os.environ if source is None else source)
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer)):
            raise DesktopError("Cannot locate the Windows directory.")
        for key in list(env):
            if key.lower() in {"systemroot", "windir"}:
                del env[key]
        env.update(SystemRoot=buffer.value, windir=buffer.value)
    return env


def find_python(executable: Path | None = None) -> Path:
    """Input: optional current executable Path. Output: Path. Resolve installed Python without shell lookup."""
    executable = Path(executable or sys.executable).resolve()
    if executable.name.lower() == "pythonw.exe":
        sibling = executable.with_name("python.exe")
        if sibling.is_file():
            return sibling
    if executable.is_file():
        return executable
    raise DesktopError("Python is unavailable. Set BRAINWORKFLOW_PYTHON to an installed pythonw.exe.")


def windows_browser_roots() -> list[Path]:
    """Input: none. Output: list[Path]. Resolve Windows known folders when child environment omits them."""
    if os.name != 'nt':
        return []
    roots = []
    for folder_id in WINDOWS_BROWSER_FOLDER_IDS:
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, folder_id, None, 0, buffer) == 0 and buffer.value:
            roots.append(Path(buffer.value))
    return roots


def find_browser() -> Path:
    """Input: process environment. Output: executable Path. Find installed Edge/Chrome or explicit override."""
    override = os.environ.get("BRAINWORKFLOW_BROWSER")
    if override:
        browser = Path(override)
        if browser.is_file():
            return browser.resolve()
        raise DesktopError("BRAINWORKFLOW_BROWSER does not name an existing browser executable.")
    for relative in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
        for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base and (Path(base) / relative).is_file():
                return Path(base) / relative
    for base in windows_browser_roots():
        for relative in ('Microsoft/Edge/Application/msedge.exe', 'Google/Chrome/Application/chrome.exe'):
            if (base / relative).is_file():
                return base / relative
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise DesktopError("No installed Edge or Chrome found. Set BRAINWORKFLOW_BROWSER to its executable.")


def backend_command(config: DesktopConfig, port: int, python: Path) -> list[str]:
    """Input: DesktopConfig, int port, Python Path. Output: list[str]. Build the existing Console CLI argv."""
    return [str(python), "-m", "wqb.cli", "launch-console", "--console-host", "127.0.0.1",
            "--console-port", str(port), "--no-open-browser", "--knowledge-root",
            str(config.knowledge_root), "--run-dir", str(config.runs_root)]


def browser_command(browser: Path, config: DesktopConfig, port: int) -> list[str]:
    """Input: browser Path, DesktopConfig, int port. Output: list[str]. Build a stable isolated app window."""
    return [str(browser), f"--app=http://127.0.0.1:{port}",
            f"--user-data-dir={config.runtime_dir / 'browser'}", "--no-first-run",
            "--no-default-browser-check", "--disable-background-networking"]


class ProcessLock:
    def __init__(self, path: Path) -> None:
        """Input: lock file Path. Output: None. Prepare an OS-owned lock that survives stale files."""
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        """Input: ProcessLock self. Output: bool. Acquire exclusive ownership without stale PID assumptions."""
        if self.handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        """Input: ProcessLock self. Output: None. Release ownership; retain the harmless lock file."""
        if self.handle is not None:
            self.handle.close()
            self.handle = None

    def __enter__(self) -> ProcessLock:
        """Input: ProcessLock self. Output: ProcessLock. Serialize overlapping launcher invocations."""
        deadline = time.monotonic() + STARTUP_TIMEOUT + WINDOW_TIMEOUT
        while not self.acquire():
            if time.monotonic() >= deadline:
                raise DesktopError("Another desktop launch is still starting. Try again shortly.")
            time.sleep(POLL_INTERVAL)
        return self

    def __exit__(self, *args: object) -> None:
        """Input: context exception objects. Output: None. Always release the launcher lock."""
        self.release()


class LocalHealthOnly(HTTPRedirectHandler):
    def redirect_request(self, req: object, fp: object, code: int, msg: str, headers: object, newurl: str) -> None:
        """Input: urllib redirect arguments. Output: None. Refuse redirects away from the exact local endpoint."""
        return None


def canonical(path: str | Path) -> str:
    """Input: str or Path. Output: str. Compare resolved paths using native filesystem case rules."""
    return os.path.normcase(str(Path(path).resolve()))


def backend_health(port: int) -> dict[str, object]:
    """Input: loopback port int. Output: health dict. Read local backend identity without proxy routing."""
    try:
        opener = build_opener(ProxyHandler({}), LocalHealthOnly())
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=HEALTH_TIMEOUT) as response:
            if response.status != 200:
                return {}
            payload = json.loads(response.read(HEALTH_MAX_BYTES))
        return payload if isinstance(payload, dict) else {}
    except (OSError, URLError, ValueError, UnicodeError):
        return {}


def backend_roots_match(config: DesktopConfig, payload: dict[str, object]) -> bool:
    """Input: desktop config and health dict. Output: bool. Match app and all workspace roots."""
    return payload.get("app") == "BrainWorkflow" and all(
        isinstance(payload.get(name), str) and bool(payload[name])
        and canonical(payload[name]) == canonical(getattr(config, name))
        for name in ("workflow_root", "knowledge_root", "runs_root")
    )


def owns_backend(config: DesktopConfig, port: int) -> bool:
    """Input: DesktopConfig and int port. Output: bool. Require matching roots and loaded source code."""
    payload = backend_health(port)
    return (backend_roots_match(config, payload)
            and isinstance(payload.get("server_revision"), str) and bool(payload["server_revision"].strip())
            and payload.get("code_revision") == LOADED_CODE_REVISION)


def port_available(port: int) -> bool:
    """Input: int loopback port. Output: bool. Test exclusive bind without attaching to a foreign listener."""
    with socket.socket() as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def select_port(config: DesktopConfig, ports: list[int] | tuple[int, ...]) -> tuple[int, bool]:
    """Input: DesktopConfig and int ports. Output: (port, reused) tuple. Prefer owned service, skip foreign ports."""
    outdated = []
    for port in ports:
        payload = backend_health(port)
        if not backend_roots_match(config, payload):
            continue
        if payload.get("code_revision") == LOADED_CODE_REVISION and isinstance(payload.get("server_revision"), str) and payload["server_revision"].strip():
            return port, True
        outdated.append(port)
    if outdated:
        raise DesktopError(f"An outdated Console backend is running on port {outdated[0]}; restart that backend before reopening. Existing research state is preserved.")
    for port in ports:
        if port_available(port):
            return port, False
    raise DesktopError("All desktop ports are occupied by other services. No existing service was changed.")


def hidden_process_options() -> dict[str, object]:
    """Input: native OS. Output: subprocess options dict. Detach backend lifetime and hide its Windows console."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def ensure_backend(config: DesktopConfig, ports: list[int] | tuple[int, ...] = DEFAULT_PORTS) -> int:
    """Input: DesktopConfig and candidate ports. Output: int owned port. Start/reuse one locked Console backend."""
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    with ProcessLock(config.runtime_dir / "startup.lock"):
        port, reused = select_port(config, ports)
        if reused:
            return port
        command = [str(find_python()), "-m", "wqb.desktop", "--backend", "--port", str(port),
                   "--knowledge-root", str(config.knowledge_root), "--runs-root", str(config.runs_root)]
        with (config.runtime_dir / "backend.log").open("ab", buffering=0) as log:
            process = subprocess.Popen(command, cwd=config.workflow_root, env=child_environment(),
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, **hidden_process_options())
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if owns_backend(config, port):
                return port
            if process.poll() is not None:
                # A previous launcher may have died while its locked backend was starting.
                for candidate in ports:
                    if owns_backend(config, candidate):
                        return candidate
                raise DesktopError("Console failed to start. See backend.log beside startup.log.")
            time.sleep(POLL_INTERVAL)
        process.terminate()
        process.wait(timeout=10)
        raise DesktopError("Console identity health check timed out. See backend.log beside startup.log.")


def run_backend(config: DesktopConfig, port: int) -> int:
    """Input: DesktopConfig and int port. Output: int exit code. Hold the lifetime lock around existing Console CLI."""
    lock = ProcessLock(config.runtime_dir / "backend.lock")
    if not lock.acquire():
        return 8
    try:
        if owns_backend(config, port):
            return 0
        if not port_available(port):
            raise DesktopError("The selected port was occupied during startup. Relaunch to choose another port.")
        os.environ.update(child_environment())
        sys.argv = backend_command(config, port, find_python())[2:]
        runpy.run_module("wqb.cli", run_name="__main__")
        return 0
    finally:
        lock.release()


def app_window(config: DesktopConfig, pid: int | None = None) -> bool:
    """Input: DesktopConfig, optional new browser PID int. Output: bool. Tag/find an owned native app HWND and focus it."""
    if os.name != "nt":
        return False
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user32.GetPropW.restype = wintypes.HANDLE
    user32.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    key = "BrainWorkflow." + hashlib.sha256(canonical(config.runtime_dir).encode()).hexdigest()
    found = []

    def visit(hwnd: int, parameter: int) -> bool:
        """Input: HWND int and LPARAM int. Output: bool. Match tagged app windows or the newly spawned browser PID."""
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if user32.IsWindowVisible(hwnd) and (user32.GetPropW(hwnd, key) or (pid is not None and process_id.value == pid)):
            user32.SetPropW(hwnd, key, 1)
            found.append(hwnd)
            return False
        return True

    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows(callback_type(visit), 0)
    if found:
        user32.ShowWindow(found[0], 9)
        user32.SetForegroundWindow(found[0])
    return bool(found)


def launch_desktop(config: DesktopConfig, ports: list[int] | tuple[int, ...] = DEFAULT_PORTS) -> int:
    """Input: DesktopConfig and int ports. Output: int port. Start/reuse backend and show its independent app window."""
    browser = find_browser()
    with ProcessLock(config.runtime_dir / "window.lock"):
        port = ensure_backend(config, ports)
        if app_window(config):
            return port
        with (config.runtime_dir / "browser.log").open("ab", buffering=0) as log:
            process = subprocess.Popen(browser_command(browser, config, port), env=child_environment(),
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, **hidden_process_options())
        deadline = time.monotonic() + WINDOW_TIMEOUT
        while time.monotonic() < deadline:
            if app_window(config, process.pid):
                return port
            if process.poll() is not None:
                if process.returncode:
                    raise DesktopError("Browser app window failed to start. See browser.log beside startup.log.")
            time.sleep(POLL_INTERVAL)
        raise DesktopError("Browser window was not detected. The backend is still running. "
                           "See browser.log beside startup.log; close the dedicated app browser and retry.")


def show_error(message: str) -> None:
    """Input: safe str message. Output: None. Show a visible error even when launched through pythonw/WScript."""
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, "BrainWorkflow startup failed", 0x10)
    elif sys.stderr is not None:
        print(message, file=sys.stderr)


def report_failure(config: DesktopConfig, error: Exception, notify: Callable[[str], None] = show_error) -> None:
    """Input: DesktopConfig, Exception, str callback. Output: None. Persist safe diagnostics and display log location."""
    detail = str(error) if isinstance(error, DesktopError) else f"Startup failed ({type(error).__name__})."
    log = config.runtime_dir / "startup.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now(timezone.utc).isoformat()} {detail}\n")
        detail += f"\n\nStartup log: {log}"
    except OSError:
        detail += f"\n\nCannot write startup log: {log}"
    notify(detail)


def main(argv: list[str] | None = None) -> int:
    """Input: optional CLI list[str]. Output: int exit status. Resolve entry-relative roots and dispatch desktop/backend."""
    workflow = Path(__file__).resolve().parents[1]
    project = workflow.parents[1]
    config = DesktopConfig(workflow, project / "knowledge", project / "runs")
    try:
        parser = argparse.ArgumentParser(description="BrainWorkflow desktop app window")
        parser.add_argument("--backend", action="store_true", help=argparse.SUPPRESS)
        parser.add_argument("--port", type=int)
        parser.add_argument("--knowledge-root", type=Path, default=config.knowledge_root)
        parser.add_argument("--runs-root", type=Path, default=config.runs_root)
        args = parser.parse_args(argv)
        config = DesktopConfig(workflow, args.knowledge_root.resolve(), args.runs_root.resolve())
        if args.port is not None and not 1 <= args.port <= 65535:
            raise DesktopError("Port must be between 1 and 65535.")
        if args.backend:
            return run_backend(config, args.port or DEFAULT_PORTS[0])
        launch_desktop(config, [args.port] if args.port else DEFAULT_PORTS)
        return 0
    except Exception as error:
        report_failure(config, error, (lambda message: print(message, file=sys.stderr)) if "--backend" in (argv or sys.argv[1:]) else show_error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
