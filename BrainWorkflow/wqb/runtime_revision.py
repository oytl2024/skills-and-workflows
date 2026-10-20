"""Identify the source snapshot loaded by a long-lived local backend."""

from __future__ import annotations

import hashlib
from pathlib import Path


def source_code_revision(source_root: Path) -> str:
    """Input: Python source root Path. Output: SHA256 str. Fingerprint local code, including uncommitted edits."""
    digest = hashlib.sha256()
    for path in sorted(source_root.rglob("*.py")):
        digest.update(path.relative_to(source_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


LOADED_CODE_REVISION = source_code_revision(Path(__file__).resolve().parent)
