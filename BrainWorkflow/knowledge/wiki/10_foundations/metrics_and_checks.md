# Metrics And Checks

## Core Performance Metrics

- `Sharpe`: risk-adjusted return measure used by platform checks and ranking.
- `Fitness`: platform quality metric that combines performance and implementation quality.
- `Turnover`: trading intensity; very high turnover can fail checks or reduce real tradability.
- `Returns / Drawdown`: robustness-oriented performance measure.
- `PnL shape`: local visual benchmark. A straight and persistent PnL path can reveal repairable signal even when a formal check fails.

## Required Checks

The platform can check performance, turnover, sub-universe behavior, weight concentration, self correlation, production correlation, and robustness. A passing simulation is not enough; all required checks must pass before candidate submission.

Source: `docs/knowledge/wqb_doc_search_snapshot_20260702.json`.

## Self Correlation

Self correlation compares the alpha against the user's own submitted alphas. Local documentation records a `0.7` PnL correlation threshold. If correlation exceeds that level, the alpha may still pass only if its Sharpe is at least `10%` higher than the correlated submitted alpha.

Sources:

- `docs/knowledge/wqb_doc_details_20260702.json`, self-correlation check notes.
- User clarification on 2026-07-02.

## Production Correlation

Production correlation compares the alpha against the broader platform production pool. Local documentation records similar criteria: correlation below `0.7`, or Sharpe at least `10%` higher than each highly correlated production alpha. Production correlation requests can be rate-limited, so local novelty filters should reduce wasted checks.

Source: `docs/knowledge/wqb_doc_details_20260702.json`.

## Power Pool

Power Pool has easier submission criteria than ordinary alpha submission but still has explicit checks. Local documentation records criteria including Sharpe at least `1.0`, no more than `8` operators, no more than `3` data fields excluding grouping fields, Power Pool correlation below `0.5`, turnover pass, sub-universe pass, and robustness pass. The idea description should include rationale for the data and operators.

Source: `docs/knowledge/wqb_doc_details_20260702.json`.

## Benchmark Implication

Near-miss alphas should not be discarded solely because a check fails. If Sharpe is strong, fitness is near threshold, PnL is straight, and the failure is repairable, the alpha should enter Repair.

