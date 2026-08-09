from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_experience_compile import compile_research_case_reports
from wqb.knowledge_paths import machine_resource_path


RAW_RESEARCH_RECORD_PATTERN = Path("raw") / "research" / "runs" / "*" / "research_record.md"
RESEARCH_COMPILE_JSON = Path("machine") / "reports" / "research_record_compile.json"


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
    benchmark_label = "near_miss" if "near_miss" in text else ""
    return {
        "run_id": _extract_line_value(text, "Run ID") or path.parent.name,
        "objective": _extract_line_value(text, "Objective"),
        "path": str(path),
        "preview": "\n".join(text.splitlines()[:12]),
        "case_reason": "near_miss" if benchmark_label else "representative_failure",
        "triage": [{"benchmark_label": benchmark_label, "failed": []}] if benchmark_label else [],
    }


def _read_existing_research_rows(path: Path) -> list[dict[str, Any]]:
    """Input: machine ledger path. Output: existing row dicts. Preserve richer synced rows when present."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_research_rows(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Input: machine ledger path and rows. Output: path. Write deterministic research record JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in sorted(rows, key=lambda item: str(item.get("run_id", ""))):
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def compile_research_records(
    knowledge_root: str | Path,
    generated_at: str | None = None,
    max_records: int = 100,
) -> dict[str, Any]:
    """Input: knowledge root and limit. Output: summary dict. Compile raw research records into canonical ledgers."""
    root = Path(knowledge_root)
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for name in ("raw", "machine", "wiki"):
        (root / name).mkdir(parents=True, exist_ok=True)
    raw_paths = sorted(
        root.glob(str(RAW_RESEARCH_RECORD_PATTERN).replace("\\", "/")),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:max_records]
    rows = [_record_summary(path) for path in raw_paths]
    ledger_path = machine_resource_path(root, "research_records")
    existing_by_run = {
        str(row.get("run_id", "")): row
        for row in _read_existing_research_rows(ledger_path)
        if str(row.get("run_id", ""))
    }
    for row in rows:
        existing_by_run.setdefault(
            str(row["run_id"]),
            {
                "run_id": str(row["run_id"]),
                "objective": str(row["objective"]),
                "backtest": [],
                "triage": row["triage"],
                "repair": {},
                "candidate_gate": [],
                "user_approval": [],
                "approved_queue": [],
                "manual_submission_status": [],
                "synced_at": generated,
                "final_state": "compiled_from_raw",
                "case_reason": str(row["case_reason"]),
                "raw_source_path": str(row["path"]),
            },
        )
    _write_research_rows(ledger_path, list(existing_by_run.values()))
    case_report_paths = compile_research_case_reports(root, generated, max_records)
    output_json = root / RESEARCH_COMPILE_JSON
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(
            {
                "report_type": "research_record_compile",
                "generated_at": generated,
                "record_count": len(rows),
                "ledger_path": str(ledger_path),
                "case_report_paths": [str(path) for path in case_report_paths],
                "source_paths": [row["path"] for row in rows],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "generated_at": generated,
        "record_count": len(rows),
        "markdown_path": str(case_report_paths[0]) if case_report_paths else "",
        "case_report_paths": [str(path) for path in case_report_paths],
        "json_path": str(output_json),
        "source_paths": [row["path"] for row in rows],
    }
