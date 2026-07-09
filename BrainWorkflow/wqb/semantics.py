from typing import Any


POSITIVE_TAGS = {"cash", "cashflow", "asset_strength", "profitability", "growth"}
NEGATIVE_TAGS = {
    "investment_drag",
    "leverage_pressure",
    "liability_pressure",
    "working_capital_pressure",
    "cost_pressure",
    "asset_quality_risk",
}
FIELD_RULES = [
    (("operating_cashflow", "ope_cf", "cashflow"), {"cashflow"}),
    (("cash_change", "cash"), {"cash"}),
    (("currentassets", "assets"), {"asset_strength"}),
    (("revenue", "sales"), {"growth"}),
    (("grossprofit", "gross_profit", "net_income", "netincome", "ebitda", "income"), {"profitability"}),
    (("capex", "inv_cf", "investing_cashflow"), {"investment_drag"}),
    (("totaldebt", "longdebt", "shortdebt", "debt", "interest"), {"leverage_pressure"}),
    (("currentliabilities", "liabilities"), {"liability_pressure"}),
    (("accpayable", "payable", "accreceivable", "receivable"), {"working_capital_pressure"}),
    (("cost", "sga", "expense"), {"cost_pressure"}),
    (("goodwill", "int_ass", "intangible", "acc_dep"), {"asset_quality_risk"}),
    (("sentiment", "snt_"), {"sentiment"}),
    (("buzz", "news", "article"), {"attention"}),
    (("option", "ivol", "implied"), {"option_activity"}),
    (("short", "borrow"), {"short_interest"}),
    (("analyst", "estimate", "revision"), {"analyst_revision"}),
]
OPERATOR_RULES = [
    (("rank", "zscore", "normalize", "scale"), {"cross_sectional_normalizer"}),
    (("ts_mean", "ts_decay", "ts_decay_linear", "hump"), {"turnover_control", "time_series_smoother"}),
    (("ts_delta", "ts_rank", "ts_corr", "ts_cov"), {"time_series_transform"}),
    (("group_neutralize", "group_rank", "group_zscore", "group_backfill"), {"group_transform"}),
    (("vec_",), {"vector_reducer"}),
    (("trade_when", "if_else"), {"event_gate"}),
    (("winsorize", "signed_power", "power"), {"tail_control"}),
]
HYPOTHESIS_PRIORITY = [
    "cashflow_quality",
    "balance_sheet_quality",
    "working_capital_quality",
    "profitability_quality",
    "asset_quality",
    "semantic_quality_spread",
]


def field_semantic_embedding(field: dict[str, Any]) -> dict[str, Any]:
    """Input: data-field metadata dict. Output: semantic dict. Tag field meaning and polarity."""
    field_id = str(field.get("id", ""))
    normalized = field_id.lower()
    tags: set[str] = set()
    for keywords, rule_tags in FIELD_RULES:
        if any(keyword in normalized for keyword in keywords):
            tags.update(rule_tags)
    field_type = str(field.get("type", "")).upper()
    if field_type:
        tags.add(field_type.lower())
    polarity = "neutral"
    if tags & NEGATIVE_TAGS:
        polarity = "negative"
    elif tags & POSITIVE_TAGS:
        polarity = "positive"
    dataset = field.get("dataset") if isinstance(field.get("dataset"), dict) else {}
    expression_value = field_id
    if field_type == "VECTOR":
        expression_value = f"vec_avg({field_id})"
    return {
        "id": field_id,
        "type": field_type,
        "dataset_id": dataset.get("id") or field.get("dataset_id") or "",
        "tags": sorted(tags),
        "tag_vector": {tag: 1 for tag in sorted(tags)},
        "polarity": polarity,
        "expression_value": expression_value,
    }


def operator_semantic_embedding(operator: dict[str, Any]) -> dict[str, Any]:
    """Input: operator metadata dict. Output: semantic dict. Tag operator purpose for templates."""
    name = str(operator.get("name") or operator.get("id") or "")
    category = str(operator.get("category", ""))
    normalized = name.lower()
    tags: set[str] = set()
    for keywords, rule_tags in OPERATOR_RULES:
        if any(keyword in normalized for keyword in keywords):
            tags.update(rule_tags)
    if category:
        tags.add(category.lower().replace(" ", "_"))
    return {
        "name": name,
        "category": category,
        "tags": sorted(tags),
        "tag_vector": {tag: 1 for tag in sorted(tags)},
    }


def semantic_pair_hypothesis(positive: dict[str, Any], negative: dict[str, Any]) -> str:
    """Input: positive and negative embeddings. Output: hypothesis label. Name economic relation."""
    positive_tags = set(positive["tags"])
    negative_tags = set(negative["tags"])
    if "cashflow" in positive_tags and "investment_drag" in negative_tags:
        return "cashflow_quality"
    if positive_tags & {"cash", "cashflow", "asset_strength"} and negative_tags & {
        "leverage_pressure",
        "liability_pressure",
    }:
        return "balance_sheet_quality"
    if positive_tags & {"growth", "profitability"} and negative_tags & {"cost_pressure"}:
        return "profitability_quality"
    if positive_tags & {"cash", "cashflow"} and negative_tags & {"working_capital_pressure"}:
        return "working_capital_quality"
    if positive_tags & {"asset_strength"} and negative_tags & {"asset_quality_risk"}:
        return "asset_quality"
    return "semantic_quality_spread"


def select_semantic_field_pairs(fields: list[dict[str, Any]], max_pairs: int) -> list[dict[str, Any]]:
    """Input: fields and max count. Output: positive-negative semantic pairs. Build economic relations."""
    embeddings = [field_semantic_embedding(field) for field in fields if field.get("id")]
    usable = [item for item in embeddings if item["type"] != "EVENT"]
    positives = [item for item in usable if item["polarity"] == "positive"]
    negatives = [item for item in usable if item["polarity"] == "negative"]
    grouped_pairs: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for positive in positives:
        for negative in negatives:
            key = (positive["id"], negative["id"])
            if key in seen:
                continue
            seen.add(key)
            hypothesis = semantic_pair_hypothesis(positive, negative)
            grouped_pairs.setdefault(hypothesis, []).append(
                {"positive": positive, "negative": negative, "hypothesis": hypothesis}
            )

    selected: list[dict[str, Any]] = []
    indexes = {hypothesis: 0 for hypothesis in grouped_pairs}
    priority = HYPOTHESIS_PRIORITY + sorted(
        hypothesis for hypothesis in grouped_pairs if hypothesis not in HYPOTHESIS_PRIORITY
    )
    while len(selected) < max_pairs:
        added = False
        for hypothesis in priority:
            pairs = grouped_pairs.get(hypothesis, [])
            index = indexes.get(hypothesis, 0)
            if index >= len(pairs):
                continue
            selected.append(pairs[index])
            indexes[hypothesis] = index + 1
            added = True
            if len(selected) >= max_pairs:
                break
        if not added:
            break
    return selected
