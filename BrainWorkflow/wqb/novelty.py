import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from wqb.expression import GROUPING_FIELDS, OPERATOR_RE, count_operators


FIELD_TOKEN_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
FAST_D1_DELTA_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)_fast_d1\s*-\s*\1\b")
LOW_NOVELTY_MAX_SCORE = 0
HIGH_NOVELTY_MIN_SCORE = 3
SIMILAR_TEMPLATE_MIN_RATIO = 0.82
NON_FIELD_TOKENS = {
    "and",
    "or",
    "not",
    "nan",
    "true",
    "false",
    "if",
    "else",
}
PRICE_VOLUME_FIELDS = {
    "open",
    "close",
    "high",
    "low",
    "volume",
    "vwap",
    "returns",
    "adv20",
    "cap",
}
FAMILY_RULES = [
    (("open", "close", "high", "low", "volume", "vwap", "returns", "adv", "cap"), "price_volume"),
    (("snt_", "sentiment", "buzz", "news", "article", "social"), "sentiment_attention"),
    (("option", "opt_", "ivol", "implied"), "options"),
    (("analyst", "estimate", "revision"), "analyst_revision"),
    (
        (
            "fnd",
            "cash",
            "cashflow",
            "asset",
            "debt",
            "liabil",
            "capex",
            "revenue",
            "profit",
            "income",
            "ebitda",
        ),
        "fundamental",
    ),
    (("short", "borrow"), "short_interest"),
]


@dataclass(frozen=True)
class NoveltyResult:
    score: int
    label: str
    reasons: list[str]
    profile: dict[str, Any]


def expression_fields(expression: str) -> list[str]:
    """Input: expression str. Output: field tokens list[str]. Extract likely data fields from an expression."""
    operators = set(count_operators(expression))
    fields: set[str] = set()
    for token in FIELD_TOKEN_RE.findall(expression):
        lowered = token.lower()
        if token in operators or lowered in operators:
            continue
        if lowered in GROUPING_FIELDS or lowered in NON_FIELD_TOKENS:
            continue
        fields.add(token)
    return sorted(fields)


def field_family(field: str) -> str:
    """Input: field id str. Output: family str. Map a data field to a coarse economic family."""
    normalized = field.lower()
    if normalized in PRICE_VOLUME_FIELDS:
        return "price_volume"
    for keywords, family in FAMILY_RULES:
        if any(keyword in normalized for keyword in keywords):
            return family
    if normalized.endswith("_fast_d1"):
        return "fast_d1_other"
    return "other"


def expression_profile(expression: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Input: expression str and settings dict|None. Output: profile dict. Fingerprint expression structure."""
    settings = settings or {}
    operators = count_operators(expression)
    operator_sequence = [match.group(1) for match in OPERATOR_RE.finditer(expression)]
    fields = expression_fields(expression)
    data_families = sorted({field_family(field) for field in fields if field_family(field) != "other"})
    template_key = "|".join(operator_sequence)
    return {
        "fields": fields,
        "data_families": data_families,
        "operator_sequence": operator_sequence,
        "operator_counts": operators,
        "template_key": template_key,
        "neutralization": str(settings.get("neutralization", "")),
        "has_fast_d1_delta": bool(FAST_D1_DELTA_RE.search(expression)),
        "has_event_gate": "trade_when" in operators,
    }


def template_similarity(left: list[str], right: list[str]) -> float:
    """Input: two operator sequences list[str]. Output: float. Measure template similarity."""
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=left, b=right).ratio()


def novelty_label(score: int) -> str:
    """Input: novelty score int. Output: label str. Convert score into workflow gate label."""
    if score <= LOW_NOVELTY_MAX_SCORE:
        return "low_novelty"
    if score >= HIGH_NOVELTY_MIN_SCORE:
        return "high_novelty"
    return "medium_novelty"


def score_expression_novelty(
    expression: str,
    settings: dict[str, Any] | None,
    reference_records: list[dict[str, Any]],
) -> NoveltyResult:
    """Input: expression/settings/references. Output: NoveltyResult. Score self/prod correlation proxy risk."""
    profile = expression_profile(expression, settings)
    score = 0
    reasons: list[str] = []
    candidate_families = set(profile["data_families"])
    similar_reference = False
    family_overlap = False
    same_neutralization = False
    reference_families: set[str] = set()
    for record in reference_records:
        reference_expression = record.get("expression")
        if not isinstance(reference_expression, str) or not reference_expression.strip():
            continue
        reference_profile = expression_profile(reference_expression, record.get("settings") or {})
        reference_families.update(reference_profile["data_families"])
        if candidate_families and candidate_families & set(reference_profile["data_families"]):
            family_overlap = True
        similarity = template_similarity(profile["operator_sequence"], reference_profile["operator_sequence"])
        if similarity >= SIMILAR_TEMPLATE_MIN_RATIO:
            similar_reference = True
            if profile["neutralization"] and profile["neutralization"] == reference_profile["neutralization"]:
                same_neutralization = True

    if family_overlap:
        score -= 2
        reasons.append("overlapping_data_family")
    elif candidate_families and not (candidate_families & reference_families):
        score += 2
        reasons.append("new_data_family")

    if similar_reference:
        score -= 2
        reasons.append("similar_operator_template")
    elif reference_records and profile["operator_sequence"]:
        score += 1
        reasons.append("distinct_operator_template")

    if same_neutralization:
        score -= 1
        reasons.append("same_neutralization_as_similar_reference")

    if profile["has_fast_d1_delta"]:
        score += 2
        reasons.append("fast_d1_delta")

    if profile["has_event_gate"]:
        score += 1
        reasons.append("event_gate")

    if not reference_records and candidate_families:
        score += 1
        reasons.append("no_reference_overlap")

    return NoveltyResult(score=score, label=novelty_label(score), reasons=reasons, profile=profile)
