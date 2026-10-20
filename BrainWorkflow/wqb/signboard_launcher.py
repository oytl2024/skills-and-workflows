"""Open the project board in an isolated Signboard desktop profile."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote
from urllib.request import urlopen

from .architecture_viewer import server_identity


LIST_DIR_PATTERN = re.compile(r"^\d{3,}-")
MAX_OPEN_ATTEMPTS = 12
OPEN_RETRY_SECONDS = 0.75
ARCHITECTURE_PORT = 8766
VIEWER_START_ATTEMPTS = 20
VIEWER_RETRY_SECONDS = 0.25


def _viewer_health(port: int) -> dict[str, object] | None:
    """Input: local viewer port. Output: health dict, None if closed, or unrelated marker."""
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as response:
            return json.load(response)
    except OSError:
        import socket
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return {"identity": "unrelated"}
        except OSError:
            return None
    except (ValueError, json.JSONDecodeError):
        return {"identity": "unrelated"}


def ensure_viewer(workspace_root: str | Path, port: int = ARCHITECTURE_PORT) -> str:
    """Input: workspace path and fixed port. Output: viewer URL; start or verify exact service."""
    root = Path(workspace_root).resolve()
    expected = server_identity(root)
    health = _viewer_health(port)
    if health is not None:
        if health.get("identity") != expected:
            raise RuntimeError(f"Port {port} is occupied by an unrelated service or outdated architecture viewer; verify its owner before restarting")
        return f"http://127.0.0.1:{port}/"
    kwargs: dict[str, object] = {"cwd": str(root / "skills-and-workflows" / "BrainWorkflow"), "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen([sys.executable, "-m", "wqb.architecture_viewer", "--root", str(root), "--port", str(port)], **kwargs)
    for _ in range(VIEWER_START_ATTEMPTS):
        time.sleep(VIEWER_RETRY_SECONDS)
        health = _viewer_health(port)
        if health is not None:
            if health.get("identity") != expected:
                raise RuntimeError(f"Port {port} is occupied by an unrelated service or outdated architecture viewer; verify its owner before restarting")
            return f"http://127.0.0.1:{port}/"
        if process.poll() is not None:
            break
    raise RuntimeError("Architecture viewer did not start; check milestone.md and local Python environment")


def prepare_signboard_state(board_dir: str | Path, state_dir: str | Path) -> dict[str, object]:
    """Input: board/state paths. Output: board path and card count. Validate a nonempty board."""
    board = Path(board_dir).resolve()
    state = Path(state_dir).resolve()
    if not board.is_dir():
        raise ValueError(f"Signboard board is missing: {board}")
    card_count = sum(
        1
        for list_dir in board.iterdir()
        if list_dir.is_dir() and LIST_DIR_PATTERN.match(list_dir.name)
        for card in list_dir.glob("*.md")
        if card.is_file()
    )
    if card_count == 0:
        raise ValueError(f"Signboard board has no card files: {board}")
    state.mkdir(parents=True, exist_ok=True)
    trusted_file = state / "trusted-board-roots.json"
    try:
        existing = json.loads(trusted_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = []
    trusted = [str(item) for item in existing if isinstance(item, str)] if isinstance(existing, list) else []
    if str(board) not in trusted:
        trusted.append(str(board))
    trusted_file.write_text(json.dumps(trusted, indent=2), encoding="utf-8")
    return {"board_dir": str(board), "card_count": card_count, "state_dir": str(state)}


def _board_opened(state_file: Path, board_dir: str, previous_mtime_ns: int) -> bool:
    """Input: state file, board path, earlier timestamp. Output: bool. Confirm renderer selected this board."""
    try:
        if state_file.stat().st_mtime_ns <= previous_mtime_ns:
            return False
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(state, dict) and state.get("activeBoardRoot") == board_dir


def launch_signboard(executable: str | Path, board_dir: str | Path, state_dir: str | Path) -> dict[str, object]:
    """Input: executable/board/state paths. Output: bootstrap summary. Launch the selected project board."""
    exe = Path(executable).resolve()
    if not exe.is_file():
        raise FileNotFoundError(f"Signboard is not installed: {exe}")
    summary = prepare_signboard_state(board_dir, state_dir)
    env = os.environ.copy()
    env.pop("ELECTRON_RUN_AS_NODE", None)
    env["SIGNBOARD_USER_DATA_DIR"] = str(summary["state_dir"])
    env["SIGNBOARD_DESKTOP_USER_DATA_DIR"] = str(summary["state_dir"])
    state_file = Path(str(summary["state_dir"])) / "open-boards.json"
    previous_mtime_ns = state_file.stat().st_mtime_ns if state_file.exists() else 0
    subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env)
    board_link = f"signboard://open-board?path={quote(str(summary['board_dir']), safe='')}"
    for _ in range(MAX_OPEN_ATTEMPTS):
        time.sleep(OPEN_RETRY_SECONDS)
        # Signboard 1.7.4 treats a leading deep link as a CLI command.
        subprocess.Popen([str(exe), "--", board_link], cwd=str(exe.parent), env=env)
        time.sleep(OPEN_RETRY_SECONDS)
        if _board_opened(state_file, str(summary["board_dir"]), previous_mtime_ns):
            return summary
    raise RuntimeError(f"Signboard did not open the project board after {MAX_OPEN_ATTEMPTS} attempts")


def main() -> int:
    """Input: none. Output: exit code int. Resolve workspace locations and open the project board."""
    package = Path(__file__).resolve().parents[1]
    workspace = package.parents[1]
    viewer_error = None
    try:
        url = ensure_viewer(workspace)
    except (OSError, RuntimeError) as error:
        viewer_error = error
    try:
        summary = launch_signboard(
            workspace / "tools" / "signboard" / "app" / "Signboard.exe",
            package / "management" / "board",
            package / "management" / ".signboard-state",
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Cannot open Signboard: {error}", file=sys.stderr)
        return 1
    print(f"Opening Signboard: {summary['card_count']} cards in {summary['board_dir']}")
    if viewer_error is not None:
        print(f"Signboard opened, but project architecture is unavailable: {viewer_error}", file=sys.stderr)
        return 2
    print(f"Project architecture: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
