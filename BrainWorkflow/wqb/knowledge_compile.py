from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


RAW_RESEARCH_RECORD_PATTERN = Path("raw") / "research" / "runs" / "*" / "research_record.md"
RESEARCH_COMPILE_MD = Path("wiki") / "40_experiments" / "research_record_compile.md"
RESEARCH_COMPILE_JSON = Path("wiki") / "40_experiments" / "research_record_compile.json"


def _extract_line_value(text: str, label: str) -> str:
    """Input: markdown text and label. Output: value string. Extract a simple bullet field."""
    prefix = f"- {label}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip().strip("`")
    return ""


def _record_summary(path: Path) -> dict[str, Any]:
    """Input: raw research record path. Output: summary dict. Extract compact compile metadata."""
    text = path.read_text(encoding="utf-8")
    return {
        "run_id": _extract_line_value(text, "Run ID") or path.parent.name,
        "objective": _extract_line_value(text, "Objective"),
        "path": str(path),
        "preview": "\n".join(text.splitlines()[:12]),
    }


def compile_research_records(
    knowledge_root: str | Path,
    generated_at: str | None = None,
    max_records: int = 100,
) -> dict[str, Any]:
    """Input: knowledge root and limit. Output: summary dict. Compile raw research records into wiki notes."""
    root = Path(knowledge_root)
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    raw_paths = sorted(
        root.glob(str(RAW_RESEARCH_RECORD_PATTERN).replace("\\", "/")),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:max_records]
    rows = [_record_summary(path) for path in raw_paths]
    output_md = root / RESEARCH_COMPILE_MD
    output_json = root / RESEARCH_COMPILE_JSON
    output_md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Research Record Compile",
        "",
        f"Generated at: `{generated}`",
        f"Record count: `{len(rows)}`",
        "",
        "This page is compiled from raw research records after completed research sessions.",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"## {row['run_id']}",
                "",
                f"- Objective: {row['objective']}",
                f"- Source: `{row['path']}`",
                "",
                "```text",
                str(row["preview"]),
                "```",
                "",
            ]
        )
    output_md.write_text("\n".join(lines), encoding="utf-8")
    output_json.write_text(
        json.dumps({"generated_at": generated, "record_count": len(rows), "records": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "generated_at": generated,
        "record_count": len(rows),
        "markdown_path": str(output_md),
        "json_path": str(output_json),
        "source_paths": [row["path"] for row in rows],
    }
