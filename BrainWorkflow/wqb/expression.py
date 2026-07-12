import hashlib
import re

from wqb.models import ComplexityResult


GROUPING_FIELDS = {"country", "industry", "subindustry", "currency", "market", "sector", "exchange"}
BACKFILL_OPERATORS_EXCLUDED_FROM_POWER_POOL = {"ts_backfill", "group_backfill"}
OPERATOR_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def normalize_expression(expression: str) -> str:
    """Input: expression string. Output: normalized string. Collapse whitespace for stable hashing."""
    return re.sub(r"\s+", " ", expression.strip())


def expression_hash(expression: str) -> str:
    """Input: expression string. Output: sha256 hex digest. Identify equivalent generated expressions."""
    normalized = normalize_expression(expression)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def count_operators(expression: str) -> dict[str, int]:
    """Input: expression string. Output: operator count dict. Count function-like tokens."""
    counts: dict[str, int] = {}
    for match in OPERATOR_RE.finditer(expression):
        name = match.group(1)
        counts[name] = counts.get(name, 0) + 1
    return counts


def replace_operator_names(expression: str, replacements: dict[str, str]) -> str:
    """Input: expression and old-to-new operators. Output: expression. Replace function-call operator names."""
    def replace_match(match: re.Match[str]) -> str:
        name = match.group(1)
        replacement = replacements.get(name, name)
        return f"{replacement}("

    return OPERATOR_RE.sub(replace_match, expression)


def count_data_fields(expression: str, known_fields: set[str]) -> set[str]:
    """Input: expression and known fields. Output: data fields used, excluding grouping fields."""
    used: set[str] = set()
    for field in known_fields:
        if field in GROUPING_FIELDS:
            continue
        if re.search(rf"\b{re.escape(field)}\b", expression):
            used.add(field)
    return used


def is_power_pool_complexity_ok(
    expression: str,
    known_fields: set[str],
    operator_limit: int,
    field_limit: int,
) -> ComplexityResult:
    """Input: expression, known fields, limits. Output: complexity result for Power Pool eligibility."""
    operators = count_operators(expression)
    operator_count = len(
        {name for name in operators if name not in BACKFILL_OPERATORS_EXCLUDED_FROM_POWER_POOL}
    )
    fields = count_data_fields(expression, known_fields)
    reasons: list[str] = []
    if operator_count > operator_limit:
        reasons.append(f"operator_count {operator_count} exceeds {operator_limit}")
    if len(fields) > field_limit:
        reasons.append(f"field_count {len(fields)} exceeds {field_limit}")
    return ComplexityResult(
        ok=not reasons,
        operator_count=operator_count,
        field_count=len(fields),
        operators=operators,
        fields=fields,
        reasons=reasons,
    )
