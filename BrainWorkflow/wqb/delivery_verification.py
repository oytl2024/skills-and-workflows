from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


UNITTEST_DISCOVERY_CODE = (
    "import sys, runpy; sys.platform='linux'; "
    "runpy.run_module('unittest', run_name='__main__')"
)


def _now() -> str:
    """Input: none. Output: UTC timestamp string. Timestamp local verification reports."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _verification_commands() -> tuple[tuple[str, list[str]], ...]:
    """Input: none. Output: named command lists. Build controller-compatible local verification commands."""
    return (
        (
            "unittest_discovery",
            [
                sys.executable,
                "-c",
                UNITTEST_DISCOVERY_CODE,
                "discover",
                "-s",
                "tests",
                "-q",
            ],
        ),
        (
            "compileall",
            [sys.executable, "-m", "compileall", "-q", "wqb", "tests"],
        ),
    )


def _run_check(code: str, command: list[str], project_root: Path) -> dict[str, Any]:
    """Input: check code, command, project root. Output: machine-readable local command result."""
    try:
        completed = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "code": code,
            "status": "passed" if completed.returncode == 0 else "failed",
            "command": command,
            "cwd": str(project_root),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except OSError as error:
        return {
            "code": code,
            "status": "failed",
            "command": command,
            "cwd": str(project_root),
            "returncode": -1,
            "stdout": "",
            "stderr": str(error),
        }


def _write_verification_report(
    knowledge_root: Path,
    generated_at: str,
    report: dict[str, Any],
) -> Path:
    """Input: vault root, timestamp, report. Output: immutable report path and latest pointer."""
    try:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid delivery verification timestamp: {generated_at}") from error
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    generated = generated.astimezone(timezone.utc)
    directory = (
        knowledge_root / "raw" / "maintenance" / "delivery_checks"
    ).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stem = generated.strftime("%Y%m%dT%H%M%SZ")
    index = 0
    while True:
        suffix = "" if index == 0 else f".{index}"
        path = directory / f"{stem}{suffix}.json"
        payload = {**report, "report_path": str(path)}
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            (directory / "latest.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            report["report_path"] = str(path)
            return path
        except FileExistsError:
            index += 1


def run_delivery_verification(
    knowledge_root: str | Path,
    project_root: str | Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Input: vault root, optional project root and timestamp. Output: persisted local verification report."""
    knowledge = Path(knowledge_root)
    project = Path(project_root) if project_root is not None else Path(__file__).resolve().parent.parent
    generated = generated_at or _now()
    checks = [
        _run_check(code, command, project)
        for code, command in _verification_commands()
    ]
    report = {
        "report_type": "delivery_verification",
        "generated_at": generated,
        "status": "passed" if all(check["status"] == "passed" for check in checks) else "failed",
        "checks": checks,
    }
    _write_verification_report(knowledge, generated, report)
    return report
