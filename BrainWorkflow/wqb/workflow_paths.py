from __future__ import annotations

from pathlib import Path


def resolve_project_root(workflow_root: str | Path) -> Path:
    """Input: workflow package root path. Output: project root Path. Locate the shared brain project root."""
    return Path(workflow_root).resolve().parents[1]


def resolve_run_root(workflow_root: str | Path, run_root: str | Path | None = None) -> Path:
    """Input: workflow root and optional run path. Output: absolute run root. Share CLI and console defaults."""
    root = Path(run_root) if run_root is not None else Path("runs")
    if root.is_absolute():
        return root
    return resolve_project_root(workflow_root) / root
