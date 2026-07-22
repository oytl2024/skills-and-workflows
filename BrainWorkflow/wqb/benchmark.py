from dataclasses import dataclass
from datetime import date
from typing import Any

from wqb.benchmark_rules import BenchmarkRule, default_benchmark_rules, rules_for_issue_type


BENCHMARK_REVIEW_DAYS = 3
SIGNAL_SHARPE_FLOOR = 0.9
SIGNAL_FITNESS_FLOOR = 0.35
SIGNAL_RETURNS_FLOOR = 0.0
SIGNAL_TURNOVER_MIN = 0.01
SIGNAL_TURNOVER_MAX = 0.7
PNL_SIGNAL_KEYWORDS = (
    "straight",
    "smooth",
    "steady",
    "linear",
    "monotonic",
    "stable",
    "upward",
    "直",
    "稳定",
)
REPAIRABLE_CHECKS = {
    "SELF_CORRELATION",
    "PROD_CORRELATION",
    "LOW_SHARPE",
    "LOW_FITNESS",
    "LOW_RETURNS",
    "LOW_2Y_SHARPE",
    "HIGH_TURNOVER",
    "LOW_TURNOVER",
    "CONCENTRATED_WEIGHT",
    "LOW_SUB_UNIVERSE_SHARPE",
    "LOW_ROBUST_UNIVERSE_SHARPE.WITH_RATIO",
    "LOW_ROBUST_UNIVERSE_RETURNS",
}


@dataclass(frozen=True)
class AlphaBenchmarkResult:
    label: str
    score: float
    repair_priority: int
    reasons: list[str]
    next_stage: str


def safe_float(value: Any, default: float = 0.0) -> float:
    """Input: arbitrary metric value. Output: float. Convert WQB numeric fields defensively."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    try:
        if text.endswith("%"):
            return float(text[:-1].strip()) / 100.0
        return float(text)
    except ValueError:
        return default


def check_name_set(alpha_record: dict[str, Any], key: str) -> set[str]:
    """Input: alpha record and list key. Output: check name set. Normalize check names for benchmark rules."""
    raw_items = alpha_record.get(key, [])
    if not isinstance(raw_items, list):
        return set()
    names: set[str] = set()
    for item in raw_items:
        if isinstance(item, dict):
            name = item.get("name")
        else:
            name = item
        if name:
            names.add(str(name))
    return names


def pnl_signal_observed(alpha_record: dict[str, Any]) -> bool:
    """Input: alpha record. Output: bool. Detect explicit human/API notes that PnL shape has signal."""
    parts = [
        alpha_record.get("signal_note"),
        alpha_record.get("pnl_note"),
        alpha_record.get("pnl_shape"),
        alpha_record.get("benchmark_note"),
    ]
    text = " ".join(str(part).lower() for part in parts if part)
    return any(keyword in text for keyword in PNL_SIGNAL_KEYWORDS)


def benchmark_alpha_record(
    alpha_record: dict[str, Any], benchmark_rules: list[BenchmarkRule] | None = None
) -> AlphaBenchmarkResult:
    """Input: alpha record and optional active rules. Output: benchmark result. Apply persisted promotion authority."""
    metrics = alpha_record.get("metrics") if isinstance(alpha_record.get("metrics"), dict) else {}
    failed = check_name_set(alpha_record, "failed")
    pending = check_name_set(alpha_record, "pending")
    checks_to_repair = failed | pending
    reasons: list[str] = []

    if bool(alpha_record.get("hard_pass")):
        return AlphaBenchmarkResult(
            label="hard_pass",
            score=1.0,
            repair_priority=0,
            reasons=["platform_hard_checks_clean"],
            next_stage="submit_check",
        )

    if "NO_CHECKS" in pending:
        return AlphaBenchmarkResult(
            label="pending_review",
            score=0.0,
            repair_priority=99,
            reasons=["checks_pending_or_missing"],
            next_stage="result_recovery",
        )

    sharpe = safe_float(metrics.get("sharpe"))
    fitness = safe_float(metrics.get("fitness"))
    returns = safe_float(metrics.get("returns"))
    turnover = safe_float(metrics.get("turnover"))

    if checks_to_repair and not checks_to_repair.issubset(REPAIRABLE_CHECKS):
        return AlphaBenchmarkResult(
            label="weak_discard",
            score=0.0,
            repair_priority=99,
            reasons=["non_repairable_check:" + ",".join(sorted(checks_to_repair - REPAIRABLE_CHECKS))],
            next_stage="discard",
        )

    score = 0.0
    if sharpe >= 1.25:
        score += 0.25
        reasons.append("strong_sharpe")
    elif sharpe >= SIGNAL_SHARPE_FLOOR:
        score += 0.18
        reasons.append("near_threshold_sharpe")
    elif sharpe >= 0.6:
        score += 0.08
        reasons.append("weak_positive_sharpe")

    if fitness >= 1.0:
        score += 0.25
        reasons.append("strong_fitness")
    elif fitness >= SIGNAL_FITNESS_FLOOR:
        score += 0.12
        reasons.append("near_threshold_fitness")

    if returns > SIGNAL_RETURNS_FLOOR:
        score += 0.12
        reasons.append("positive_returns")

    if SIGNAL_TURNOVER_MIN <= turnover <= SIGNAL_TURNOVER_MAX:
        score += 0.1
        reasons.append("repairable_turnover")

    active_rules = default_benchmark_rules() if benchmark_rules is None else benchmark_rules
    pnl_rules = rules_for_issue_type(active_rules, "pnl_signal")
    if pnl_signal_observed(alpha_record) and pnl_rules:
        score += 0.25
        reasons.append("pnl_shape_signal")
        reasons.extend(f"benchmark_rule:{rule.rule_id}" for rule in pnl_rules)

    if checks_to_repair:
        score += 0.1
        reasons.append("repairable_failed_checks")

    score = round(min(score, 1.0), 4)
    if checks_to_repair and score >= 0.55:
        priority = 1 if score >= 0.75 else 2
        return AlphaBenchmarkResult(
            label="repairable_signal",
            score=score,
            repair_priority=priority,
            reasons=reasons,
            next_stage="repair",
        )

    return AlphaBenchmarkResult(
        label="weak_discard",
        score=score,
        repair_priority=99,
        reasons=reasons or ["no_repairable_signal_evidence"],
        next_stage="discard",
    )


def parse_review_date(value: str | date) -> date:
    """Input: date or ISO date string. Output: date. Parse benchmark review timestamps."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def benchmark_review_due(last_review_date: str | date, today: str | date) -> bool:
    """Input: last review date and current date. Output: bool. Enforce three-day benchmark calibration."""
    last_review = parse_review_date(last_review_date)
    current = parse_review_date(today)
    return (current - last_review).days >= BENCHMARK_REVIEW_DAYS
