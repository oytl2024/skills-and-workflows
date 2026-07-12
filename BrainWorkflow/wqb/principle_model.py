from dataclasses import asdict, dataclass
from typing import Any


REQUIRED_OPTION_TEXT_FIELDS = (
    "title",
    "primary_incentive",
    "why_now",
    "candidate_scope",
    "expected_asset_value",
    "correlation_risk",
    "resource_cost",
    "decision_needed",
)


@dataclass(frozen=True)
class SourceEvidence:
    source_type: str
    path: str
    title: str
    timestamp: str
    stale: bool = False
    note: str = ""


@dataclass(frozen=True)
class IncentiveSnapshot:
    generated_at: str
    account: dict[str, Any]
    activities: list[dict[str, Any]]
    competitions: list[dict[str, Any]]
    power_pool_boards: list[dict[str, str]]
    rule_pages: dict[str, str]
    evidence: list[SourceEvidence]
    refresh_errors: list[dict[str, str]]


@dataclass(frozen=True)
class ScoreBreakdown:
    total: float
    components: dict[str, float]
    penalties: dict[str, float]
    reasons: list[str]


@dataclass(frozen=True)
class OptionCard:
    title: str
    primary_incentive: str
    secondary_incentives: list[str]
    why_now: str
    candidate_scope: str
    expected_asset_value: str
    correlation_risk: str
    resource_cost: str
    evidence: list[SourceEvidence]
    failure_modes: list[str]
    decision_needed: str
    score: ScoreBreakdown


# Input: OptionCard; Output: dict[str, Any]; Purpose: convert a principle option card into JSON-safe nested data.
def option_card_to_dict(card: OptionCard) -> dict[str, Any]:
    return asdict(card)


# Input: OptionCard; Output: None; Purpose: reject option cards that are missing required user-facing content.
def validate_option_card(card: OptionCard) -> None:
    row = option_card_to_dict(card)
    missing = [field for field in REQUIRED_OPTION_TEXT_FIELDS if not str(row.get(field, "")).strip()]
    if missing:
        raise ValueError(f"option card missing required fields: {', '.join(missing)}")
    if not card.evidence:
        raise ValueError("option card must include at least one evidence source")
    if not card.score.reasons:
        raise ValueError("option card score must include reasons")
