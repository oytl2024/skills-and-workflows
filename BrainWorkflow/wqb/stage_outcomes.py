from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from wqb.benchmark import benchmark_alpha_record
from wqb.checker import SUBMISSION_ONLY_CHECKS


DEFERRED_RESEARCH_CHECKS = SUBMISSION_ONLY_CHECKS
REQUIRED_RESEARCH_METRICS = ("sharpe", "fitness", "returns", "turnover")


def research_benchmark_label(row: dict[str, Any], root: Path) -> str:
    """Input: checked row dict and run Path. Output: label str. Separate research triage from final check eligibility."""
    if not row["pending"]:
        return benchmark_alpha_record(row, run_dir=root, consumer="triage").label
    metrics = row.get("metrics", {})
    names = []
    for item in row["pending"]:
        name = item.get("name") if isinstance(item, dict) else item
        if not isinstance(name, str) or name not in DEFERRED_RESEARCH_CHECKS:
            return "pending_review"
        if isinstance(item, dict) and item.get("result", "PENDING") != "PENDING":
            return "pending_review"
        names.append(name)
    if not row["failed"] or not names:
        return "pending_review"
    try:
        if not all(type(metrics[key]) in (int, float) and math.isfinite(metrics[key])
                   for key in REQUIRED_RESEARCH_METRICS):
            return "pending_review"
    except (KeyError, TypeError):
        return "pending_review"
    # Only the assessment view defers correlations; persisted checks and candidate gates stay unchanged.
    assessment = {**row, "pending": [], "hard_pass": False}
    return benchmark_alpha_record(assessment, run_dir=root, consumer="triage").label


def checked_research_rows(run_dir: str | Path) -> list[dict[str, Any]]:
    """Input: run_dir str or Path. Output: list[dict]. Validate checked identities including legacy results."""
    path = Path(run_dir) / "all_alphas.jsonl"
    if not path.exists():
        return []
    return validate_checked_rows([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                                  if line.strip()])


def validate_checked_rows(raw_rows: list) -> list[dict[str, Any]]:
    """Input: list of raw rows. Output: normalized dict rows or []. Reject ambiguous checked evidence."""
    rows = []
    identities = {}
    for row in raw_rows:
        if not isinstance(row, dict):
            return []
        if any(not isinstance(row.get(key), str) for key in ("alpha_id", "expression_hash")):
            return []
        identity = tuple(str(row.get(key, "") or "").strip() for key in ("alpha_id", "expression_hash"))
        if (not all(identity) or type(row.get("hard_pass")) is not bool
                or not isinstance(row.get("failed"), list) or not isinstance(row.get("pending"), list)
                or str(row.get("status", "CHECKED")).upper() != "CHECKED"):
            return []
        if row["hard_pass"] and (row["failed"] or row["pending"]):
            return []
        normalized = {**row, "alpha_id": identity[0], "expression_hash": identity[1]}
        if identity in identities:
            if normalized != identities[identity]:
                return []
            continue
        identities[identity] = normalized
        rows.append(normalized)
    return rows


def research_outcome(run_dir: str | Path) -> dict[str, Any]:
    """Input: run_dir str or Path. Output: dict of counts and rows. Classify verified research without relaxing candidates."""
    root = Path(run_dir)
    rows = checked_research_rows(root)
    classified = [
        {**row, "benchmark_label": research_benchmark_label(row, root)}
        for row in rows
    ]
    counts = {label: sum(row["benchmark_label"] == label for row in classified)
              for label in ("hard_pass", "repairable_signal", "weak_discard", "pending_review")}
    outcome = "missing_results"
    if rows:
        outcome = ("pending_review" if counts["pending_review"] else
                   "repairable_signal" if counts["repairable_signal"] else
                   "qualified" if counts["hard_pass"] else "no_signal")
    return {"outcome": outcome, "checked_count": len(rows), "counts": counts, "rows": classified}
