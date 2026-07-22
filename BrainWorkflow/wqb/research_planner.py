from dataclasses import replace
from pathlib import Path
from typing import Any

from wqb.benchmark_rules import BenchmarkRule, load_active_benchmark_rules, rules_for_consumer
from wqb.data_ledger import load_data_ledger, summarize_data_ledger_authority
from wqb.operator_semantics import load_operator_semantics
from wqb.principle_model import (
    IncentiveSnapshot,
    OptionCard,
    ScoreBreakdown,
    SourceEvidence,
    option_card_to_dict,
    validate_option_card,
)
from wqb.template_library import load_template_library, template_matrix_summary


GENIUS_BASE_SCORE = 7.0
OSMOSIS_BASE_SCORE = 6.5
POWER_POOL_BASE_SCORE = 7.5
THEME_BASE_SCORE = 6.0
COMPETITION_BASE_SCORE = 5.5
REFRESH_RECOVERY_SCORE = 10.0
STALE_REFRESH_PENALTY = 3.0


def _planner_contract_inputs(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: planner input summary. Summarize semantic ledgers for option cards."""
    data_records = load_data_ledger(knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl")
    template_records = load_template_library(knowledge_root / "wiki" / "30_templates" / "template_library.jsonl")
    operators = load_operator_semantics(knowledge_root / "wiki" / "20_semantics" / "operator_semantics.jsonl")
    benchmark_rules = load_active_benchmark_rules(knowledge_root, fallback_to_defaults=False)
    planner_rules = rules_for_consumer(benchmark_rules, "research_planner")
    data_authority = summarize_data_ledger_authority(data_records, knowledge_root)
    blockers = []
    if not data_authority.get("authoritative_measured_count"):
        blockers.append("Authoritative data ledger is missing or has no measured platform rows.")
    return {
        "data_authority": data_authority,
        "operator_semantic_count": len(operators),
        "template_matrix_ready_count": template_matrix_summary(template_records)["matrix_ready_count"],
        "benchmark_rule_count": len(benchmark_rules),
        "benchmark_rule_ids": [rule.rule_id for rule in planner_rules],
        "benchmark_actions": [rule.action for rule in planner_rules],
        "maintenance_blockers": blockers,
    }


def _apply_planner_rule_annotations(option: dict[str, Any], rules: list[BenchmarkRule]) -> dict[str, Any]:
    """Input: option row and planner rules. Output: annotated option row. Apply persisted rules to option risk."""
    if option.get("primary_incentive") == "knowledge_refresh" or not rules:
        return option
    annotations = [
        f"Active benchmark rule {rule.rule_id}: {rule.action} Rule risk: {rule.risk}"
        for rule in rules
        if rule.action or rule.risk
    ]
    if annotations:
        option["correlation_risk"] = " ".join([str(option.get("correlation_risk", "")).strip(), *annotations]).strip()
        score = option.get("score")
        if isinstance(score, dict):
            score["reasons"] = [*score.get("reasons", []), *annotations]
    return option


def plan_research_options(
    knowledge_root: str | Path,
    generated_at: str,
    max_options: int = 5,
    live_api_enabled: bool = False,
    snapshot: IncentiveSnapshot | None = None,
) -> dict[str, Any]:
    """Input: knowledge root, timestamp, limit, live API flag, snapshot. Output: planner rows. Build durable option rows with semantic contract inputs."""
    root = Path(knowledge_root)
    if snapshot is None:
        snapshot = IncentiveSnapshot(
            generated_at=generated_at,
            account={},
            activities=[],
            competitions=[],
            power_pool_boards=[],
            rule_pages={},
            evidence=[
                SourceEvidence(
                    "knowledge",
                    str(root),
                    "Knowledge contract inputs",
                    generated_at,
                    stale=True,
                    note="No live incentive snapshot was supplied.",
                )
            ],
            refresh_errors=[
                {
                    "path": "incentive_snapshot",
                    "error": "SnapshotUnavailable",
                    "message": "No live incentive snapshot was supplied.",
                }
            ],
        )
    contract_inputs = _planner_contract_inputs(root)
    planner_rules = rules_for_consumer(load_active_benchmark_rules(root, fallback_to_defaults=False), "research_planner")
    options = []
    for card in generate_research_options(snapshot, max_options=max_options):
        option = option_card_to_dict(card)
        option.update(contract_inputs)
        options.append(_apply_planner_rule_annotations(option, planner_rules))
    return {
        "generated_at": generated_at,
        "option_count": len(options),
        "options": options,
    }


# Input: IncentiveSnapshot, path fragment, fallback title; Output: SourceEvidence; Purpose: choose the most relevant evidence row for one option card.
def _source(snapshot: IncentiveSnapshot, path_fragment: str, fallback_title: str) -> SourceEvidence:
    for item in snapshot.evidence:
        if path_fragment in item.path:
            return item
    return SourceEvidence("snapshot", path_fragment, fallback_title, snapshot.generated_at, stale=bool(snapshot.refresh_errors))


# Input: raw score values and optional penalty; Output: ScoreBreakdown; Purpose: build a consistent score record for one option card.
def _score(total: float, name: str, reason: str, penalty_name: str = "", penalty: float = 0.0) -> ScoreBreakdown:
    penalties = {penalty_name: penalty} if penalty_name else {}
    return ScoreBreakdown(total=total - penalty, components={name: total}, penalties=penalties, reasons=[reason])


# Input: IncentiveSnapshot; Output: bool; Purpose: decide whether the snapshot contains any visible opportunity evidence beyond refresh errors.
def _has_visible_opportunities(snapshot: IncentiveSnapshot) -> bool:
    return bool(snapshot.activities or snapshot.competitions or snapshot.power_pool_boards or snapshot.rule_pages)


# Input: OptionCard; Output: OptionCard; Purpose: mark cached opportunity cards as uncertain and apply a stale-refresh score penalty.
def _apply_refresh_uncertainty(card: OptionCard) -> OptionCard:
    stale_evidence = [
        replace(
            item,
            stale=True,
            note=item.note or "Displayed from cached evidence because the latest refresh failed.",
        )
        for item in card.evidence
    ]
    uncertain_score = ScoreBreakdown(
        total=max(card.score.total - STALE_REFRESH_PENALTY, 0.0),
        components=card.score.components,
        penalties={**card.score.penalties, "stale_refresh_uncertainty": STALE_REFRESH_PENALTY},
        reasons=[*card.score.reasons, "Latest refresh failed, so this opportunity is based on stale cached evidence."],
    )
    return replace(
        card,
        title=f"Stale snapshot: {card.title}",
        why_now=f"{card.why_now} Current visibility is uncertain because the latest refresh failed and this card may rely on cached evidence.",
        evidence=stale_evidence,
        score=uncertain_score,
    )


# Input: IncentiveSnapshot; Output: OptionCard; Purpose: create a refresh-first fallback option when live evidence is too uncertain.
def _refresh_recovery_option(snapshot: IncentiveSnapshot) -> OptionCard:
    card = OptionCard(
        title="Refresh platform rules before research",
        primary_incentive="knowledge_refresh",
        secondary_incentives=["risk_control"],
        why_now="Live rule refresh produced errors, so current activity choices may be stale.",
        candidate_scope="No alpha research scope until official rules are refreshed.",
        expected_asset_value="Prevents spending API budget under stale incentive assumptions.",
        correlation_risk="No alpha generation happens in this option.",
        resource_cost="Read-only API refresh and local cache update.",
        evidence=snapshot.evidence or [SourceEvidence("local", "knowledge", "Local knowledge cache", snapshot.generated_at, stale=True)],
        failure_modes=["Network access remains unavailable.", "Platform endpoint schema changes."],
        decision_needed="Choose whether to retry refresh or proceed with stale-cache warnings.",
        score=_score(REFRESH_RECOVERY_SCORE, "refresh_required", "Official source refresh failed."),
    )
    validate_option_card(card)
    return card


# Input: IncentiveSnapshot; Output: OptionCard; Purpose: create the long-term Genius and Osmosis planning option.
def _genius_osmosis_option(snapshot: IncentiveSnapshot) -> OptionCard:
    genius_level = snapshot.account.get("geniusLevel", "unknown")
    total = GENIUS_BASE_SCORE + OSMOSIS_BASE_SCORE
    card = OptionCard(
        title="Build Genius and Osmosis alpha pool",
        primary_incentive="genius_osmosis",
        secondary_incentives=["quarterly_payment", "portfolio_structure"],
        why_now=f"Current visible Genius level is {genius_level}; platform rules value signals, pyramids, and combined performance.",
        candidate_scope="Generate a later concrete plan across multiple region-delay scopes after user selection.",
        expected_asset_value="Improves long-term pool diversity for Genius and Osmosis allocation.",
        correlation_risk="Medium; must enforce data, template, operator, and neutralization diversity before simulation.",
        resource_cost="Planning only now; later execution should use 30-alpha batches and multisimulation packing.",
        evidence=[_source(snapshot, "brain-genius", "Brain Genius"), _source(snapshot, "osmosis", "Osmosis Allocation")],
        failure_modes=["Insufficient submitted alpha count per Osmosis scope.", "Pool diversity improves slowly."],
        decision_needed="Choose this if the next run should optimize long-term consultant pool value.",
        score=_score(total, "genius_osmosis_value", "Genius and Osmosis are durable consultant incentives."),
    )
    validate_option_card(card)
    return card


# Input: IncentiveSnapshot; Output: OptionCard or None; Purpose: create a Power Pool option only when visible boards exist.
def _power_pool_option(snapshot: IncentiveSnapshot) -> OptionCard | None:
    if not snapshot.power_pool_boards:
        return None
    labels = ", ".join(board["label"] for board in snapshot.power_pool_boards[:3])
    total = POWER_POOL_BASE_SCORE + min(len(snapshot.power_pool_boards), 3)
    card = OptionCard(
        title="Explore current Power Pool boards",
        primary_incentive="power_pool",
        secondary_incentives=["theme", "genius", "regular_submission"],
        why_now=f"Visible Power Pool boards include: {labels}.",
        candidate_scope="Choose a board first; only then select matching region, delay, data, and simple templates.",
        expected_asset_value="May create simpler alpha assets with lower submission criteria and reusable rationale.",
        correlation_risk="Medium-high if common fields or templates are crowded; must prefer new data and simple distinct logic.",
        resource_cost="Planning only now; later execution should build 30 candidates per selected board where feasible.",
        evidence=[_source(snapshot, "power-pool", "Power Pool boards")],
        failure_modes=["Pure Power Pool theme mismatch.", "Daily or monthly pure Power Pool quota limits.", "Power Pool correlation failure."],
        decision_needed="Choose this if the next run should target currently visible Power Pool opportunities.",
        score=_score(total, "power_pool_value", "Power Pool boards are visible and can serve multiple incentives."),
    )
    validate_option_card(card)
    return card


# Input: IncentiveSnapshot; Output: OptionCard or None; Purpose: create a Theme multiplier option when rule evidence mentions themes.
def _theme_option(snapshot: IncentiveSnapshot) -> OptionCard | None:
    theme_text = snapshot.rule_pages.get("multiplier-rules", "").lower()
    if "theme" not in theme_text and "qualityfactor" not in theme_text:
        return None
    card = OptionCard(
        title="Check active Theme multiplier opportunities",
        primary_incentive="theme",
        secondary_incentives=["base_payment", "power_pool"],
        why_now="Official multiplier rules state Theme-qualified alphas can raise QualityFactor.",
        candidate_scope="Refresh active theme announcements before choosing data or templates.",
        expected_asset_value="Can improve base payment exposure if the resulting alpha also has durable pool quality.",
        correlation_risk="Unknown until the active theme and common crowding patterns are identified.",
        resource_cost="Read-only theme discovery first; simulation budget only after user selects this option.",
        evidence=[_source(snapshot, "multiplier-rules", "Multiplier Rules")],
        failure_modes=["No active theme is available.", "Theme field is crowded.", "Theme alpha fails regular checks."],
        decision_needed="Choose this if the next run should inspect and exploit current Theme multipliers.",
        score=_score(THEME_BASE_SCORE, "theme_multiplier_value", "Theme rules can increase QualityFactor."),
    )
    validate_option_card(card)
    return card


# Input: IncentiveSnapshot; Output: OptionCard or None; Purpose: create a competition feasibility option when an accepted competition is visible.
def _competition_option(snapshot: IncentiveSnapshot) -> OptionCard | None:
    accepted = [item for item in snapshot.competitions if str(item.get("status", "")).upper() == "ACCEPTED"]
    if not accepted:
        return None
    competition = accepted[0]
    name = str(competition.get("name") or competition.get("id") or "Accepted competition")
    card = OptionCard(
        title=f"Feasibility check for {name}",
        primary_incentive="competition",
        secondary_incentives=["learning", "tooling"],
        why_now=f"Competition is visible as ACCEPTED with end date {competition.get('endDate', 'unknown')}.",
        candidate_scope="Do not select data or templates until competition submission feasibility is verified.",
        expected_asset_value="Can create reusable competition/Python alpha workflow if feasible.",
        correlation_risk="Unknown; competition-specific alphas still need novelty and check gates.",
        resource_cost="One read-only feasibility pass first; no alpha batch before user confirms.",
        evidence=[_source(snapshot, "/competitions", "Competitions")],
        failure_modes=["Competition submissions are disabled.", "Python alpha tooling takes too much setup time.", "Deadline is too close."],
        decision_needed="Choose this if the next run should spend a short feasibility slot on the active competition.",
        score=_score(COMPETITION_BASE_SCORE, "competition_expected_value", "Accepted competition is visible."),
    )
    validate_option_card(card)
    return card


# Input: IncentiveSnapshot and max option count; Output: list[OptionCard]; Purpose: score visible research directions and return ranked option cards before any concrete alpha planning.
def generate_research_options(snapshot: IncentiveSnapshot, max_options: int = 5) -> list[OptionCard]:
    if snapshot.refresh_errors and not _has_visible_opportunities(snapshot):
        return [_refresh_recovery_option(snapshot)]

    options: list[OptionCard] = [_genius_osmosis_option(snapshot)]
    for maybe_option in (_power_pool_option(snapshot), _theme_option(snapshot), _competition_option(snapshot)):
        if maybe_option is not None:
            options.append(maybe_option)
    if snapshot.refresh_errors:
        options = [_apply_refresh_uncertainty(option) for option in options]
        options.append(_refresh_recovery_option(snapshot))
    options.sort(key=lambda card: card.score.total, reverse=True)
    return options[: max(max_options, 1)]
