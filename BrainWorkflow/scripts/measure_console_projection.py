"""Measure local-only strategy projection and fragment latency at realistic run sizes."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from wqb.console_server import render_runtime_fragments
from wqb.strategy_progress import load_strategy_progress


def write_rows(path: Path, rows: list[dict]) -> None:
    """Input: JSONL path and rows. Output: none. Persist synthetic local run evidence."""
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def measure(count: int) -> dict:
    """Input: synthetic strategy count. Output: latency metrics. Avoid platform and model calls."""
    with TemporaryDirectory() as tmp:
        run = Path(tmp)
        write_rows(run / "planned_candidates.jsonl", [
            {"expression_hash": f"hash-{i}", "expression": f"rank(field_{i})"} for i in range(count)
        ])
        write_rows(run / "simulation_events.jsonl", [
            {"expression_hash": f"hash-{i}", "event": "CHECKED", "alpha_id": f"a{i}"} for i in range(count)
        ])
        write_rows(run / "all_alphas.jsonl", [
            {"expression_hash": f"hash-{i}", "alpha_id": f"a{i}", "status": "CHECKED",
             "hard_pass": False, "failed": ["LOW_FITNESS"]} for i in range(count)
        ])
        started = perf_counter()
        projection = load_strategy_progress(run)
        cold_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        load_strategy_progress(run)
        warm_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        render_runtime_fragments({"strategy_progress": projection, "active_workflow": {"exists": True}})
        fragment_ms = (perf_counter() - started) * 1000
        return {"planned": count, "projected_rows": len(projection["rows"]),
                "cold_ms": round(cold_ms, 2), "warm_ms": round(warm_ms, 2),
                "fragment_ms": round(fragment_ms, 2)}


if __name__ == "__main__":
    print(json.dumps([measure(size) for size in (30, 300, 1000)], indent=2))
