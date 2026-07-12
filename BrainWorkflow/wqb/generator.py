from typing import Any

from wqb.models import AlphaCandidate
from wqb.semantics import select_semantic_field_pairs


LOOKBACKS = [5, 10, 20, 60, 120]
BACKFILLS = [20, 60]
FAST_D1_SUFFIX = "_fast_d1"
BASE_TEMPLATES = [
    "rank({field})",
    "-rank({field})",
    "rank(ts_mean({field}, {window}))",
    "-rank(ts_mean({field}, {window}))",
    "rank(ts_delta({field}, {window}))",
    "-rank(ts_delta({field}, {window}))",
    "group_neutralize(rank({field}), subindustry)",
]
GENERATION_TEMPLATES = [
    BASE_TEMPLATES,
    [
        "rank(ts_mean(ts_backfill({field}, {backfill}), {window}))",
        "-rank(ts_mean(ts_backfill({field}, {backfill}), {window}))",
        "group_neutralize(rank(ts_mean({field}, {window})), subindustry)",
    ],
    [
        "rank(ts_delta(ts_backfill({field}, {backfill}), {window}))",
        "-rank(ts_delta(ts_backfill({field}, {backfill}), {window}))",
        "group_neutralize(rank(ts_delta({field}, {window})), subindustry)",
    ],
]
ECONOMIC_TEMPLATES = [
    "rank({field} - {regular_field})",
    "rank({field})",
    "rank(ts_delta({field}, 1))",
    "rank(ts_mean({field}, 5))",
    "group_neutralize(rank({field}), subindustry)",
    "-rank({field} - {regular_field})",
    "-rank({field})",
    "-rank(ts_delta({field}, 1))",
    "-rank(ts_mean({field}, 5))",
    "group_neutralize(rank({field} - {regular_field}), subindustry)",
    "group_neutralize(rank({field} - {regular_field}), industry)",
    "group_neutralize(rank({field}), industry)",
    "rank(ts_delta({field}, {window}))",
    "-rank(ts_delta({field}, {window}))",
    "rank(ts_mean({field}, {window}))",
    "-rank(ts_mean({field}, {window}))",
    "rank(ts_rank({field}, {window}))",
    "-rank(ts_rank({field}, {window}))",
]
ECONOMIC_EVENT_TEMPLATES = [
    "rank({field} - {regular_field})",
    "rank({field})",
    "group_neutralize(rank({field}), subindustry)",
    "-rank({field} - {regular_field})",
]
ECONOMIC_VECTOR_TEMPLATES = [
    "rank(vec_avg({field}) - vec_avg({regular_field}))",
    "rank(vec_avg({field}))",
    "group_neutralize(rank(vec_avg({field})), subindustry)",
    "-rank(vec_avg({field}) - vec_avg({regular_field}))",
    "-rank(vec_avg({field}))",
    "group_neutralize(rank(vec_avg({field}) - vec_avg({regular_field})), subindustry)",
    "group_neutralize(rank(vec_avg({field}) - vec_avg({regular_field})), industry)",
    "group_neutralize(rank(vec_avg({field})), industry)",
    "group_neutralize(rank(vec_avg({field})), sector)",
    "rank(ts_delta(vec_avg({field}), {window}))",
    "-rank(ts_delta(vec_avg({field}), {window}))",
    "rank(ts_mean(vec_avg({field}), {window}))",
    "-rank(ts_mean(vec_avg({field}), {window}))",
    "rank(ts_rank(vec_avg({field}), {window}))",
    "-rank(ts_rank(vec_avg({field}), {window}))",
]
RELATIONAL_POSITIVE_KEYWORDS = [
    "operating_cashflow",
    "ope_cf",
    "cash_change",
    "cash",
    "currentassets",
    "assets",
    "revenue",
    "grossprofit",
    "gross_profit",
    "net_income",
    "netincome",
    "ebitda",
]
RELATIONAL_NEGATIVE_KEYWORDS = [
    "currentliabilities",
    "liabilities",
    "totaldebt",
    "longdebt",
    "debt",
    "accpayable",
    "payable",
    "capex",
    "investing_cashflow",
    "inv_cf",
    "financing_cashflow",
    "financing_cf",
    "cost",
    "sga",
    "goodwill",
    "int_ass",
    "accreceivable",
    "acc_dep",
]
RELATIONAL_TEMPLATES = [
    "rank({positive}) - rank({negative})",
    "rank(ts_delta({positive}, 5)) - rank(ts_delta({negative}, 5))",
    "rank(ts_mean({positive}, 5)) - rank(ts_mean({negative}, 5))",
    "group_neutralize(rank({positive}) - rank({negative}), subindustry)",
    "group_neutralize(rank(ts_delta({positive}, 5)) - rank(ts_delta({negative}, 5)), subindustry)",
    "group_neutralize(rank(ts_mean({positive}, 5)) - rank(ts_mean({negative}, 5)), subindustry)",
]
SEMANTIC_TEMPLATES = [
    "rank({positive}) - rank({negative})",
    "rank(ts_delta({positive}, 5)) - rank(ts_delta({negative}, 5))",
    "rank(ts_mean({positive}, 5)) - rank(ts_mean({negative}, 5))",
    "group_neutralize(rank({positive}) - rank({negative}), subindustry)",
    "group_neutralize(rank(ts_delta({positive}, 5)) - rank(ts_delta({negative}, 5)), subindustry)",
    "group_neutralize(rank(ts_mean({positive}, 5)) - rank(ts_mean({negative}, 5)), subindustry)",
]


def build_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Input: run config. Output: WQB simulation settings dict. Convert config names to platform names."""
    return {
        "instrumentType": config["instrument_type"],
        "region": config["region"],
        "universe": config["universe"],
        "delay": config["delay"],
        "decay": config["decay"],
        "neutralization": config["neutralization"],
        "truncation": config["truncation"],
        "pasteurization": config["pasteurization"],
        "unitHandling": config["unit_handling"],
        "nanHandling": config["nan_handling"],
        "language": config["language"],
        "visualization": False,
    }


def simulation_payload(settings: dict[str, Any], expression: str) -> dict[str, Any]:
    """Input: settings and expression. Output: WQB regular simulation payload."""
    return {"type": "REGULAR", "settings": settings, "regular": expression}


def regular_field_id(field_id: str) -> str | None:
    """Input: field id string. Output: regular field id or None. Map Fast D1 fields to D1 peers."""
    if field_id.endswith(FAST_D1_SUFFIX):
        return field_id[: -len(FAST_D1_SUFFIX)]
    return None


def economic_templates_for_field(field: dict[str, Any]) -> list[str]:
    """Input: field metadata. Output: template strings. Select simple economic templates by field type."""
    field_type = str(field.get("type", "")).upper()
    if field_type == "VECTOR":
        return ECONOMIC_VECTOR_TEMPLATES
    if field_type == "EVENT":
        return ECONOMIC_EVENT_TEMPLATES
    return ECONOMIC_TEMPLATES


def template_expressions(template: str, field_id: str, regular_id: str) -> list[str]:
    """Input: template and field ids. Output: expressions. Render template parameter variants."""
    expressions: list[str] = []
    windows = LOOKBACKS if "{window}" in template else [None]
    for window in windows:
        backfills = BACKFILLS if "{backfill}" in template else [None]
        for backfill in backfills:
            expressions.append(
                template.format(
                    field=field_id,
                    regular_field=regular_id,
                    window=window,
                    backfill=backfill,
                )
            )
    return expressions


def generate_economic_candidates(
    fields: list[dict[str, Any]],
    settings: dict[str, Any],
    max_count: int,
    generation: int,
) -> list[AlphaCandidate]:
    """Input: fields, settings, count, generation. Output: economic candidates. Prefer templates across fields."""
    prepared_fields: list[dict[str, Any]] = []
    for field in fields:
        field_id = field.get("id")
        if not field_id:
            continue
        prepared_fields.append(
            {
                "field_id": str(field_id),
                "regular_id": regular_field_id(str(field_id)) or str(field_id),
                "regular_peer_available": bool(field.get("regular_peer_available", True)),
                "templates": economic_templates_for_field(field),
            }
        )
    max_templates = max((len(item["templates"]) for item in prepared_fields), default=0)
    candidates: list[AlphaCandidate] = []
    seen_expressions: set[str] = set()
    for template_index in range(max_templates):
        for item in prepared_fields:
            templates = item["templates"]
            if template_index >= len(templates):
                continue
            template = templates[template_index]
            field_id = item["field_id"]
            regular_id = item["regular_id"]
            if "{regular_field}" in template and regular_id == field_id:
                continue
            if "{regular_field}" in template and not item["regular_peer_available"]:
                continue
            for expression in template_expressions(template, field_id, regular_id):
                if expression in seen_expressions:
                    continue
                seen_expressions.add(expression)
                candidates.append(
                    AlphaCandidate(
                        expression=expression,
                        settings=settings,
                        generation=generation,
                        tags=["seed", "economic"],
                    )
                )
                if len(candidates) >= max_count:
                    return candidates
    return candidates


def relational_role(field_id: str) -> str:
    """Input: field id string. Output: role string. Classify simple financial direction for pairs."""
    normalized = field_id.lower()
    if any(keyword in normalized for keyword in RELATIONAL_NEGATIVE_KEYWORDS):
        return "negative"
    if any(keyword in normalized for keyword in RELATIONAL_POSITIVE_KEYWORDS):
        return "positive"
    return "neutral"


def relational_field_value(field: dict[str, Any]) -> str | None:
    """Input: field metadata. Output: expression atom or None. Convert supported field types for pairs."""
    field_id = str(field.get("field_id") or field.get("id") or "")
    if not field_id:
        return None
    field_type = str(field.get("type", "")).upper()
    if field_type == "EVENT":
        return None
    if field_type == "VECTOR":
        return f"vec_avg({field_id})"
    return field_id


def generate_relational_candidates(
    fields: list[dict[str, Any]],
    settings: dict[str, Any],
    max_count: int,
    generation: int,
) -> list[AlphaCandidate]:
    """Input: fields, settings, count, generation. Output: candidates. Build two-field economic relations."""
    prepared_fields: list[dict[str, str]] = []
    for field in fields:
        value = relational_field_value(field)
        if value is None:
            continue
        field_id = str(field.get("id") or "")
        role = relational_role(field_id)
        prepared_fields.append({"id": field_id, "value": value, "role": role})

    positive_fields = [field for field in prepared_fields if field["role"] == "positive"]
    negative_fields = [field for field in prepared_fields if field["role"] == "negative"]
    pairs = [(positive, negative) for positive in positive_fields for negative in negative_fields]
    if not pairs:
        pairs = [
            (left, right)
            for left in prepared_fields
            for right in prepared_fields
            if left["id"] != right["id"]
        ]

    candidates: list[AlphaCandidate] = []
    seen_expressions: set[str] = set()
    for template in RELATIONAL_TEMPLATES:
        for positive, negative in pairs:
            expression = template.format(positive=positive["value"], negative=negative["value"])
            if expression in seen_expressions:
                continue
            seen_expressions.add(expression)
            candidates.append(
                AlphaCandidate(
                    expression=expression,
                    settings=settings,
                    generation=generation,
                    tags=["seed", "economic", "relational"],
                )
            )
            if len(candidates) >= max_count:
                return candidates
    return candidates


def generate_semantic_candidates(
    fields: list[dict[str, Any]],
    settings: dict[str, Any],
    max_count: int,
    generation: int,
) -> list[AlphaCandidate]:
    """Input: fields, settings, count, generation. Output: candidates. Render semantic hypothesis pairs."""
    pairs = select_semantic_field_pairs(fields, max_pairs=max(max_count * 2, 1))
    candidates: list[AlphaCandidate] = []
    seen_expressions: set[str] = set()
    for pair_offset in range(max(len(pairs), 1)):
        for template_index, template in enumerate(SEMANTIC_TEMPLATES):
            if not pairs:
                return candidates
            pair = pairs[(pair_offset + template_index) % len(pairs)]
            expression = template.format(
                positive=pair["positive"]["expression_value"],
                negative=pair["negative"]["expression_value"],
            )
            if expression in seen_expressions:
                continue
            seen_expressions.add(expression)
            candidates.append(
                AlphaCandidate(
                    expression=expression,
                    settings=settings,
                    generation=generation,
                    tags=["seed", "economic", "semantic", str(pair["hypothesis"])],
                )
            )
            if len(candidates) >= max_count:
                return candidates
    return candidates


def generate_seed_candidates(
    fields: list[dict[str, Any]],
    settings: dict[str, Any],
    max_count: int,
    generation: int,
    template_mode: str = "basic",
) -> list[AlphaCandidate]:
    """Input: fields, settings, count, generation, mode. Output: seed Alpha candidates from templates."""
    if max_count <= 0:
        return []
    if template_mode == "semantic":
        return generate_semantic_candidates(fields, settings, max_count, generation)
    if template_mode == "relational":
        return generate_relational_candidates(fields, settings, max_count, generation)
    if template_mode == "economic":
        return generate_economic_candidates(fields, settings, max_count, generation)
    candidates: list[AlphaCandidate] = []
    templates = GENERATION_TEMPLATES[generation % len(GENERATION_TEMPLATES)]
    for field in fields:
        field_id = field.get("id")
        if not field_id:
            continue
        regular_id = regular_field_id(str(field_id)) or str(field_id)
        regular_peer_available = bool(field.get("regular_peer_available", True))
        for template in templates:
            if "{regular_field}" in template and regular_id == str(field_id):
                continue
            if "{regular_field}" in template and not regular_peer_available:
                continue
            for expression in template_expressions(template, str(field_id), regular_id):
                    candidates.append(
                        AlphaCandidate(
                            expression=expression,
                            settings=settings,
                            generation=generation,
                            tags=["seed", template_mode],
                        )
                    )
                    if len(candidates) >= max_count:
                        return candidates
    return candidates
