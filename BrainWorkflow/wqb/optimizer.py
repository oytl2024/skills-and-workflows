from wqb.models import CheckSummary, OptimizationAction


FAILURE_ACTIONS = {
    "LOW_SHARPE": ["flip_direction", "change_window", "change_neutralization", "rank_or_zscore"],
    "LOW_2Y_SHARPE": ["change_window", "change_field", "change_neutralization"],
    "LOW_FITNESS": ["improve_returns", "reduce_turnover", "change_window"],
    "LOW_RETURNS": ["flip_direction", "change_field", "rank_or_zscore"],
    "HIGH_TURNOVER": ["increase_decay", "smooth_signal", "add_trade_when"],
    "LOW_TURNOVER": ["decrease_decay", "shorten_window"],
    "CONCENTRATED_WEIGHT": ["rank_or_scale", "adjust_truncation", "add_backfill"],
    "LOW_SUB_UNIVERSE_SHARPE": ["change_field", "change_neutralization", "reduce_overfit"],
    "LOW_ROBUST_UNIVERSE_SHARPE.WITH_RATIO": ["change_field", "change_neutralization", "reduce_overfit"],
    "LOW_ROBUST_UNIVERSE_RETURNS": ["change_field", "flip_direction", "reduce_overfit"],
    "SELF_CORRELATION": ["change_dataset", "change_operator_family", "new_hypothesis"],
    "PROD_CORRELATION": ["change_dataset", "change_operator_family", "new_hypothesis"],
    "DATA_DIVERSITY": ["change_dataset", "use_theme_field"],
    "MATCHES_THEMES": ["use_theme_field", "refresh_power_pool_catalog"],
    "MATCHES_COMPETITION": ["refresh_competition_rules", "use_theme_field"],
}


def actions_for_check_summary(parent_hash: str, summary: CheckSummary) -> list[OptimizationAction]:
    """Input: parent expression hash and check summary. Output: ordered optimization actions."""
    actions: list[OptimizationAction] = []
    for failed in summary.failed + summary.pending:
        for action_type in FAILURE_ACTIONS.get(failed.name, ["change_field"]):
            actions.append(
                OptimizationAction(
                    parent_hash=parent_hash,
                    reason=failed.name,
                    action_type=action_type,
                    details={"alpha_id": summary.alpha_id, "result": failed.result},
                )
            )
    return actions
