from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkRule:
    rule_id: str
    issue_types: list[str]
    description: str
    promotion_condition: str
    action: str
    evidence_paths: list[str]
    consumed_by: list[str]
    risk: str


def benchmark_rule_from_dict(row: dict[str, Any]) -> BenchmarkRule:
    """Input: dict row. Output: BenchmarkRule. Normalize one active benchmark rule."""
    return BenchmarkRule(
        rule_id=str(row.get("rule_id", "")),
        issue_types=[str(item) for item in row.get("issue_types", []) if str(item)],
        description=str(row.get("description", "")),
        promotion_condition=str(row.get("promotion_condition", "")),
        action=str(row.get("action", "")),
        evidence_paths=[str(item) for item in row.get("evidence_paths", []) if str(item)],
        consumed_by=[str(item) for item in row.get("consumed_by", []) if str(item)],
        risk=str(row.get("risk", "")),
    )


def benchmark_rule_to_dict(rule: BenchmarkRule) -> dict[str, Any]:
    """Input: BenchmarkRule. Output: dict. Convert rule to JSON-safe row."""
    return asdict(rule)


def default_benchmark_rules() -> list[BenchmarkRule]:
    """Input: none. Output: default benchmark rules. Seed active rules from Stage 1 lessons."""
    return [
        BenchmarkRule(
            rule_id="near_miss_stable_pnl_promotion",
            issue_types=["pnl_signal", "near_miss"],
            description="Stable PnL shape should promote an alpha into repair review even when one metric misses threshold.",
            promotion_condition="PnL is visually stable or monotonic enough to resemble the 3q7OQaog signal-recognition case.",
            action="Create a repair candidate and test one lever at a time before abandoning.",
            evidence_paths=["knowledge/wiki/50_benchmarks/signal_quality_and_repairability.md"],
            consumed_by=["triage", "repair_loop", "workflow_proposals"],
            risk="May spend repair budget on fragile in-sample signals.",
        ),
        BenchmarkRule(
            rule_id="prod_correlation_novelty_required",
            issue_types=["prod_correlation", "correlation"],
            description="Repeated production-correlation failures require a distinct data source, operator skeleton, or economic hypothesis.",
            promotion_condition="Candidate or family fails production correlation after otherwise acceptable metrics.",
            action="Down-rank the data-template pair and request template or data novelty before another batch.",
            evidence_paths=["knowledge/wiki/50_benchmarks/correlation_and_novelty.md"],
            consumed_by=["research_planner", "candidate_gate", "repair_loop"],
            risk="May suppress a family that could pass with a large quality improvement.",
        ),
    ]


def load_benchmark_rules(path: Path) -> list[BenchmarkRule]:
    """Input: JSONL path. Output: benchmark rules. Load active rulebook."""
    if not path.exists():
        return []
    return [benchmark_rule_from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_benchmark_rules_jsonl(path: Path, rules: list[BenchmarkRule]) -> Path:
    """Input: path and rules. Output: path. Write deterministic benchmark JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for rule in sorted(rules, key=lambda item: item.rule_id):
            handle.write(json.dumps(benchmark_rule_to_dict(rule), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def write_benchmark_rules_markdown(path: Path, rules: list[BenchmarkRule], generated_at: str) -> Path:
    """Input: path, rules, timestamp. Output: path. Write readable active benchmark rules."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Benchmark Rules", "", f"Generated at: `{generated_at}`", ""]
    for rule in sorted(rules, key=lambda item: item.rule_id):
        lines.extend(
            [
                f"## {rule.rule_id}",
                "",
                f"- Issue Types: {', '.join(rule.issue_types)}",
                f"- Description: {rule.description}",
                f"- Promotion Condition: {rule.promotion_condition}",
                f"- Action: {rule.action}",
                f"- Consumed By: {', '.join(rule.consumed_by)}",
                f"- Risk: {rule.risk}",
                "- Evidence:",
                *[f"  - `{path}`" for path in rule.evidence_paths],
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def rules_for_issue_type(rules: list[BenchmarkRule], issue_type: str) -> list[BenchmarkRule]:
    """Input: rules and issue type. Output: matching rules. Find active rules for a failure class."""
    normalized = issue_type.lower()
    return [rule for rule in rules if normalized in {item.lower() for item in rule.issue_types}]
