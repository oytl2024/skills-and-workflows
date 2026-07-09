# WorldQuant BRAIN Foundations

Last updated: 2026-07-02

This file is the bottom-layer knowledge base for the Stage 1 Alpha workflow. It records platform concepts, hard constraints, resource rules, and research principles gathered from WorldQuant BRAIN documentation through the platform API.

Source artifacts:
- `docs/knowledge/wqb_doc_search_snapshot_20260702.json`
- `docs/knowledge/wqb_doc_details_20260702.json`

Key source pages fetched through the API:
- `/tutorial-pages/introduction-brain-expression-language`
- `/tutorial-pages/understanding-simulation-limits`
- `/tutorial-pages/parameters-simulation-results`
- `/tutorial-pages/consultant-submission-tests`
- `/tutorial-pages/getting-started-finding-consultant-alphas-read-first`
- `/tutorial-pages/getting-started-power-pool-alphas`
- `/tutorial-pages/fast-d1-documentation`
- `/tutorial-pages/vector-datafields`
- `/tutorial-pages/group-data-fields`
- `/tutorial-pages/neut-cons`
- `/faqs/how-is-correlation-tested`
- `/faqs/how-does-neutralization-work`
- `/messages/AvddGPy`
- `/messages/RxVxPe7`

## Alpha Model

- A Fast Expression Alpha is a concise expression made from data fields, operators, and numeric values.
- Data fields are named data series such as price, volume, fundamentals, news, sentiment, or group classifications.
- Operators transform fields into Alpha values. The final Alpha output must be a matrix-like daily value per instrument, which the platform turns into portfolio weights and PnL.
- Fast Expression is meant to make the high-level logic clear; the workflow should preserve a one-sentence economic idea for every batch before generating expressions.
- Useful Alpha templates should be explainable in human language first, then translated into conservative expressions.

Workflow implications:
- Every generated expression must be linked to `human_idea`, source fields, template mode, and expression hash.
- Prefer simple expressions where the economic direction is obvious. Do not treat random expression generation as research.
- If an expression cannot be explained in one sentence, it should not enter Scout unless there is a documented reason.

## Data Types

- MATRIX fields can usually be used directly by cross-sectional and time-series operators.
- VECTOR fields store a variable number of events per day and instrument. They must be converted to matrix values with vector operators before use with normal matrix operators.
- Common vector conversions include `vec_avg(x)`, `vec_count(x)`, and `vec_choose(x, nth=k)`.
- GROUP fields such as `sector`, `industry`, and `subindustry` are intended as inputs to group operators and should not count as research data fields for Power Pool complexity.

Workflow implications:
- Field type must be checked before template rendering.
- VECTOR fields use vector-safe templates first; direct `rank(field)` or `ts_delta(field, n)` should be rejected before API submission.
- GROUP fields are allowed for neutralization or group transforms, but should not be treated as signal data.

## Simulation Settings

- Settings such as region, universe, delay, neutralization, decay, truncation, pasteurization, unit handling, and NaN handling define how the platform converts Alpha values into a simulated portfolio.
- Neutralization subtracts the group mean from each Alpha value within a group. It helps remove market, sector, industry, or subindustry exposure and makes the portfolio approximately long-short balanced.
- Neutralization choice should match the economic idea. For broad equity ideas in USA, subindustry neutralization is a reasonable default. For cross-country regions, country-aware neutralization can matter.

Workflow implications:
- Do not change neutralization as a cosmetic tweak on weak signals. Use it when it matches the hypothesis or a specific failed check.
- Record settings with every run; otherwise a result is not reproducible.

## Performance Metrics

- Return is annualized PnL divided by half of book size.
- IR measures daily mean PnL divided by daily PnL volatility.
- Sharpe is the annualized IR, approximately `sqrt(252) * IR`.
- Fitness combines Sharpe, returns, and turnover:

```text
Fitness = Sharpe * sqrt(abs(Returns) / max(Turnover, 0.125))
```

- Delay-1 Fitness rating bands in the simulation results page are:
  - Spectacular: `> 2.5`
  - Excellent: `> 2`
  - Good: `> 1.5`
  - Average: `> 1`
  - Needs Improvement: `<= 1`

Workflow implications:
- A high return alone is not enough; unstable PnL or excessive turnover can destroy Fitness.
- Low Sharpe plus low Fitness is a branch-level signal problem, not a Repair target.
- Repair is justified only when core metrics are already strong and the remaining blocker is specific.

## Consultant Submission Gates

For consultant submission tests excluding CHN, the current documentation states:
- Delay-1 Fitness must be greater than 1.
- Delay-1 Sharpe must be greater than 1.58.
- Turnover must be greater than 1% and less than 70%.
- Max weight in any stock must be below 10%.
- Sub-universe test must pass.
- Self-correlation must be below 0.7, or Sharpe must be at least 10% higher than correlated own submitted Alphas.
- Prod-correlation uses the same logic, but against the full BRAIN consultant pool.
- IS Ladder / Check-IS-Sharpe tests require recent 2, 3, 4 ... 10 year Sharpe windows to clear thresholds.
- Bias test should not fail for expression Alphas; if it does, it is a platform/support issue rather than a normal optimization target.

Workflow implications:
- Local candidate admission must remain stricter than a single good metric: no failed hard checks and no pending hard checks.
- USA is crowded; production correlation should be assumed difficult. New data and new economic structures are primary tools, not late-stage cosmetics.
- Production correlation requests can be rate-limited, so run them only for promising Alphas or before final candidate promotion.

## Simulation Resource Limits

The platform simulation-limit documentation states:
- All successful simulations count against the limit.
- Child simulations inside multi-simulations count.
- Simulations of previously existing Alphas count.
- Duplicate Alphas are not removed from the count.
- Simulating the same Alpha on different days consumes quota even if the Alpha only appears under its original creation date.
- Simulation POST responses expose rate-limit headers:
  - `X-Ratelimit-Limit`: total daily simulation limit.
  - `X-Ratelimit-Remaining`: remaining simulations today.
  - `X-Ratelimit-Reset`: seconds until reset.

Workflow implications:
- Never re-POST an expression before checking existing `simulation_events.jsonl`, `planned_candidates.jsonl`, `all_alphas.jsonl`, and expression hashes across the run root.
- Multi-simulation is an efficiency tool, not a quota discount.
- `retry-planned` is required for recoverable submit failures so already-submitted hashes are skipped.
- The workflow should eventually record rate-limit headers from simulation POST responses; until then, treat HTTP 429 as a hard stop for the current batch.

## Power Pool Alphas

Power Pool Alphas are described as simpler, smaller, higher-quality Alphas.

Eligibility criteria from the Power Pool documentation:
- Sharpe `>= 1.0`.
- Operator count threshold `<= 8`; `ts_backfill` and `group_backfill` are not counted.
- Data fields `<= 3`, excluding grouping fields such as country, industry, subindustry, currency, market, sector, and exchange.
- Power Pool correlation `< 0.5`.
- Turnover tests pass.
- Sub-universe test passes.
- Robust-universe test passes where applicable.
- If Power Pool self-correlation is `> 0.5`, Sharpe should be 10% higher than the most correlated Alpha.

Submission and activity notes:
- Pure Power Pool Alpha submission requires matching the current Power Pool theme.
- The documentation mentions a limit of 1 pure Power Pool Alpha per day, while Power Pool + Regular / ATOM classifications are excluded from that pure limit.
- Power Pool submissions require a description of the idea, and the docs recommend an Idea / Rationale style.

Workflow implications:
- Keep Power Pool candidates simple by construction. Do not rely on cleanup after simulation.
- Two-field relational templates are acceptable only when they stay within the field/operator limits and have a clear rationale.
- Prefer one dataset per Power Pool branch when possible, because Power Pool + ATOM classification may be possible if all other tests pass except IS Ladder.

## Fast D1

Fast D1 is a Delay-1 framework using information available between D0 and D1, especially overnight catalysts before the market open.

Documented usage:
- Select Delay-1 in simulation settings.
- Use fields with `_fast_d1` suffix.
- Fast D1 fields are designed to capture overnight information that regular D1 fields miss.
- Fast D1 Alphas should be submitted only if they outperform their regular D1 equivalents.
- Production correlation uses the same pool as regular D1.
- `field_fast_d1 - field` can help reduce production correlation.

Documented research directions:
- News datasets.
- Options activity such as `option24`.
- Social media sentiment such as `socialmedia12`.
- Earnings data such as `earnings7`, `earnings1`, and `earningscall_sentiment`.
- Short interest changes such as `shortinterest30`.
- Delta/change-based Alphas are recommended as a priority direction.

Workflow implications:
- A Fast D1 Scout should record both the fast expression and, when available, a regular D1 comparison or regular-peer expression.
- If raw fast-minus-regular is weak, test a clearly different economic relation before abandoning the dataset family.
- Because the correlation pool is shared with regular D1, new data and delta structures matter more than small operator rewrites.

## Workflow-Improvement Loop

Workflow changes must follow the same discipline as Alpha research:

1. Trigger: identify the repeated failure, platform rule, or efficiency bottleneck.
2. Evidence: cite the source artifact, run directory, failed check, API error, or official doc.
3. Rule proposal: write the smallest workflow rule that would prevent recurrence.
4. Implementation: update docs first; if behavior changes are needed in code, use TDD.
5. Verification: run focused tests or inspect the next run artifact that proves the rule is applied.
6. Promotion: update `wqb_rules.md`, `stage1_loop_agenda.md`, and `todo.md`.
7. Reuse: future loops must apply the rule automatically before manual judgment.

This meta-loop is mandatory for workflow optimization. Ad hoc changes are not accepted unless they are recorded as an emergency exception with a follow-up rule.
