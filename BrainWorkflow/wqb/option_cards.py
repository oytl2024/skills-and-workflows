from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wqb.principle_model import OptionCard, ScoreBreakdown, SourceEvidence, validate_option_card


PASSTHROUGH_OPTION_FIELDS = {
    "data_authority",
    "operator_semantic_count",
    "template_matrix_ready_count",
    "benchmark_rule_count",
    "maintenance_blockers",
}


def fallback_option_id(index: int) -> str:
    """Input: valid option order int. Output: str. Build the durable fallback option ID."""
    return f"option-{int(index)}"


def normalize_option_card_row(row: dict[str, Any], fallback_index: int) -> dict[str, Any] | None:
    """Input: option row dict and fallback index int. Output: normalized dict or None. Validate one durable option card."""
    try:
        secondary_incentives = row.get("secondary_incentives")
        failure_modes = row.get("failure_modes")
        evidence_rows = row.get("evidence")
        score_row = row.get("score")
        if not all(isinstance(value, list) for value in (secondary_incentives, failure_modes, evidence_rows)):
            return None
        if not isinstance(score_row, dict) or not all(isinstance(value, str) for value in secondary_incentives + failure_modes):
            return None
        evidence = [
            SourceEvidence(
                source_type=str(item["source_type"]),
                path=str(item["path"]),
                title=str(item["title"]),
                timestamp=str(item["timestamp"]),
                stale=bool(item.get("stale", False)),
                note=str(item.get("note", "")),
            )
            for item in evidence_rows
            if isinstance(item, dict)
            and all(isinstance(item.get(name), str) and item[name].strip() for name in ("source_type", "path", "title", "timestamp"))
        ]
        if len(evidence) != len(evidence_rows):
            return None
        reasons = score_row.get("reasons")
        components = score_row.get("components")
        penalties = score_row.get("penalties")
        total = score_row.get("total")
        if (
            not isinstance(reasons, list)
            or not all(isinstance(item, str) for item in reasons)
            or not isinstance(components, dict)
            or not isinstance(penalties, dict)
            or isinstance(total, bool)
            or not isinstance(total, (int, float))
        ):
            return None
        required_text = (
            "title",
            "primary_incentive",
            "why_now",
            "candidate_scope",
            "expected_asset_value",
            "correlation_risk",
            "resource_cost",
            "decision_needed",
        )
        if not all(isinstance(row.get(name), str) and row[name].strip() for name in required_text):
            return None
        card = OptionCard(
            title=row["title"],
            primary_incentive=row["primary_incentive"],
            secondary_incentives=secondary_incentives,
            why_now=row["why_now"],
            candidate_scope=row["candidate_scope"],
            expected_asset_value=row["expected_asset_value"],
            correlation_risk=row["correlation_risk"],
            resource_cost=row["resource_cost"],
            evidence=evidence,
            failure_modes=failure_modes,
            decision_needed=row["decision_needed"],
            score=ScoreBreakdown(float(total), dict(components), dict(penalties), list(reasons)),
        )
        validate_option_card(card)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    normalized = {
        key: value
        for key, value in row.items()
        if key not in PASSTHROUGH_OPTION_FIELDS
    }
    normalized.update(
        {
            key: row[key]
            for key in PASSTHROUGH_OPTION_FIELDS
            if key in row
        }
    )
    option_id = normalized.get("option_id")
    normalized["option_id"] = option_id.strip() if isinstance(option_id, str) and option_id.strip() else fallback_option_id(fallback_index)
    return normalized


def normalize_option_card_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Input: raw option-card rows list. Output: normalized rows list. Skip invalid rows and reject ID collisions."""
    normalized_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = normalize_option_card_row(row, len(normalized_rows) + 1)
        if normalized is None:
            continue
        option_id = str(normalized.get("option_id", ""))
        if option_id in seen_ids:
            raise ValueError(f"duplicate research option id: {option_id}")
        seen_ids.add(option_id)
        normalized_rows.append(normalized)
    return normalized_rows


def read_option_card_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: normalized option-card rows list. Load durable cards while ignoring malformed rows."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return normalize_option_card_rows(rows)


def option_card_from_row(row: dict[str, Any]) -> OptionCard:
    """Input: normalized option row dict. Output: OptionCard. Rebuild a strict option card for scheduling."""
    normalized = normalize_option_card_row(row, 1)
    if normalized is None:
        raise ValueError("invalid research option card")
    score_row = normalized["score"]
    evidence = [
        SourceEvidence(
            source_type=str(item["source_type"]),
            path=str(item["path"]),
            title=str(item["title"]),
            timestamp=str(item["timestamp"]),
            stale=bool(item.get("stale", False)),
            note=str(item.get("note", "")),
        )
        for item in normalized["evidence"]
    ]
    return OptionCard(
        title=str(normalized["title"]),
        primary_incentive=str(normalized["primary_incentive"]),
        secondary_incentives=[str(item) for item in normalized["secondary_incentives"]],
        why_now=str(normalized["why_now"]),
        candidate_scope=str(normalized["candidate_scope"]),
        expected_asset_value=str(normalized["expected_asset_value"]),
        correlation_risk=str(normalized["correlation_risk"]),
        resource_cost=str(normalized["resource_cost"]),
        evidence=evidence,
        failure_modes=[str(item) for item in normalized["failure_modes"]],
        decision_needed=str(normalized["decision_needed"]),
        score=ScoreBreakdown(
            total=float(score_row["total"]),
            components=dict(score_row["components"]),
            penalties=dict(score_row["penalties"]),
            reasons=[str(item) for item in score_row["reasons"]],
        ),
    )
