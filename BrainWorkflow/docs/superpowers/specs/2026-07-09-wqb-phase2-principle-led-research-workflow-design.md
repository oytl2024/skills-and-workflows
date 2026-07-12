# WQB Phase 2 Principle-Led Research Workflow Design

Date: 2026-07-09

## Purpose

Phase 2 will use a principle-led research workflow for WorldQuant BRAIN. The workflow must not start by choosing a specific activity, region, dataset, or template. It must first evaluate long-term consultant incentives and research quality principles, then generate a small set of current research options only when the user starts a run.

This design turns the current workflow from "pick a data source and simulate" into "refresh rules, score opportunities against durable principles, ask the user to choose, then plan execution."

## Evidence Used

The principle layer is based on local Stage 1 experience and platform API checks performed on 2026-07-09:

- `/users/self`: current account is consultant-approved and visible Genius level is `GOLD`.
- `/tutorial-pages/brain-genius`: Genius level is evaluated quarterly and depends on signal submissions, pyramids, and Combined Alpha Performance. It affects data, operators, regions, SuperAlpha access, and potential quarterly payment opportunity.
- `/tutorial-pages/osmosis-allocation-guide-consultants`: Osmosis affects daily base payment quality factor multiplier, Combined Osmosis Performance for Genius, and Daily Osmosis Rank. Valid allocation requires at least 3 region-delay scopes, with 100,000 points and at least 10 alphas per scope.
- `/tutorial-pages/multiplier-rules`: Theme-qualified alphas can increase QualityFactor and therefore potential base payment.
- `/tutorial-pages/getting-started-power-pool-alphas`: Power Pool alphas are simpler alpha assets that can support Genius, competitions, and themes, with separate eligibility, theme, and quota rules.
- `/competitions/PAC2026`: Python Alphas Competition 2026 was visible as accepted, with an end date of 2026-07-12 23:59:59 -04:00, but specific feasibility must be rechecked before planning.
- `OPTIONS /consultant/boards/power-pool`: currently visible Power Pool boards include USA/D1 July 2026, GLB/D1 Dataset June 2026, and USA/D1 Fast Datasets June 2026.

These facts are time-sensitive. The workflow must refresh dynamic rules before each run.

## Non-Goals

- Do not create a fixed current research plan in this design.
- Do not preselect a concrete activity, region, dataset, or template.
- Do not run simulations, checks, or submissions during principle selection.
- Do not automatically submit alphas. Submission remains gated by explicit user confirmation and platform checks.
- Do not treat forum or experience posts as official rules unless marked as experience and later validated.

## Core Long-Term Metrics

### 1. Consultant Incentive Value

This is the top-level objective. It estimates whether a research direction improves the user's long-term consultant outcome.

Components:

- Dormancy safety and regular submission continuity.
- Genius level progress and retention.
- Signal submission count when it contributes to a real target.
- Pyramid coverage across region, delay, and dataset category.
- Combined Alpha Performance, including submitted alphas and selected alphas.
- Combined Power Pool Alpha Performance.
- Combined Osmosis Performance.
- Daily Osmosis Rank and base payment multiplier exposure.
- Theme multiplier eligibility.
- Power Pool eligibility and quota usefulness.
- Competition expected value when a competition is active and feasible.
- Future access unlocks such as data, operators, regions, and SuperAlpha pools.

### 2. Alpha Asset Quality

This measures whether a produced alpha is worth owning in the long-term pool, not merely whether it can be submitted.

Components:

- All required platform checks pass before entering the submit-candidate list.
- Sharpe, fitness, returns, and turnover clear thresholds with margin.
- PnL is stable, with low ladder risk and no obvious single-period dependency.
- Self-correlation and prod-correlation risk are low by design, not only by repair.
- The expression has clear economic rationale.
- The expression is simple enough to explain and maintain.
- Turnover and investability constraints are acceptable for after-cost performance.
- The alpha improves portfolio diversity across data, operator, neutralization, holding period, and economic story.

### 3. Portfolio Structure Value

This measures whether the alpha pool becomes useful for Genius and Osmosis.

Components:

- Coverage of at least 3 valid region-delay scopes for Osmosis.
- At least 10 useful alphas per intended Osmosis scope before allocating points.
- Diversity across dataset categories and data vendors.
- Diversity across operator families and neutralization styles.
- Diversity across turnover buckets.
- Avoidance of synchronized drawdowns across candidate alphas.
- Preference for alphas that improve a combined pool rather than isolated headline metrics.

### 4. Research Efficiency And Learning

This measures whether the workflow is improving over time.

Components:

- Submit-ready hit rate per API budget.
- Repair success rate for near-miss alphas.
- Scout signal discovery rate.
- Recovery rate after API/network/rate-limit interruptions.
- Reuse rate of templates, field semantics, and benchmark lessons.
- Reduction in repeated failure patterns.
- Knowledge-base entries created per meaningful experiment.

## Principle Stack

### P0. Refresh Rules Before Decisions

Before generating research options, the workflow must refresh or validate the latest platform activities, competitions, Power Pool boards, themes, rule pages, account state, and relevant data metadata. If fresh API access fails, cached data may be used only with a visible staleness flag.

### P1. Incentives Before Execution

The workflow must first ask which consultant incentive a research option serves: Genius, Osmosis, base payment, Theme, Power Pool, competition, dormancy safety, or long-term alpha asset quality. A direction without an incentive target is down-ranked.

### P2. Principles Before Plans

The system must not create concrete alpha batches until it has generated 3-5 option cards and the user has selected one. Option cards are decision artifacts, not execution plans.

### P3. Pool Value Beats Single-Alpha Vanity

An alpha is valuable when it contributes to the user's long-term alpha pool. A single high Sharpe alpha can be down-ranked if it is correlated, fragile, uninvestable, or does not improve any Genius/Osmosis/Theme/Power Pool objective.

### P4. Platform Checks Are A Hard Gate

Only alphas that pass all required platform checks may enter the submit-candidate list. Repairable signals stay in repair queues. Warnings must be recorded, but pending or failed mandatory checks block candidate promotion.

### P5. Correlation And Novelty Are Upstream Constraints

Self-correlation and prod-correlation risk must influence field, dataset, template, operator, and neutralization selection before simulation. New data, distinct economic logic, and distinct expression structure are preferred over late-stage blending.

### P6. Economic Logic Comes Before Batch Scale

Every template family must start with a plain-language economic hypothesis. Batch generation fills data into that hypothesis. Pure combinatorial search is allowed only as a controlled discovery tool and must be labeled as such.

### P7. Resource Cost Must Be Visible

Every option must estimate API cost, multisimulation feasibility, expected run time, quota/rate-limit risk, and recovery path. Batches should normally be built in 30-alpha units and packed efficiently into multisimulations when settings allow.

### P8. Workflow Problems Update The Workflow

When a failure repeats or a new issue is discovered, the fix should be expressed as a workflow rule, benchmark update, or knowledge-base entry. The same class of problem should become easier to avoid next time.

### P9. User Choice Is A Gate

At workflow start, the system presents current options and asks the user to choose. Only after choice does it produce a concrete plan with activity, region, delay, data, templates, batch sizes, and stopping criteria.

### P10. Principle Health Checks Are Recurring

The principle stack must be reviewed regularly. Any material rule change, incentive change, activity launch, competition deadline, new Power Pool board, or repeated benchmark failure can trigger an immediate principle update.

## Runtime Decision Flow

1. Refresh official platform sources and account state.
2. Refresh or load cached data metadata, field semantics, operator semantics, and recent experiment results.
3. Extract active incentives and constraints.
4. Score current opportunities against the principle stack.
5. Generate 3-5 option cards.
6. Ask the user to choose one option.
7. Create a concrete execution plan only for the selected option.
8. Run the selected workflow stage.
9. Record results, update benchmarks, update knowledge, and check whether principles need revision.

## Option Card Contract

Each option shown to the user must include:

- `title`: short name of the research option.
- `primary_incentive`: Genius, Osmosis, Theme, Power Pool, competition, regular submission, or dormancy safety.
- `secondary_incentives`: other objectives it may help.
- `why_now`: current rule, activity, deadline, account state, or data opportunity.
- `candidate_scope`: likely region-delay and dataset area, without locking a concrete batch yet.
- `expected_asset_value`: expected contribution to alpha pool quality.
- `correlation_risk`: self/prod correlation risk and reason.
- `resource_cost`: expected API/simulation budget.
- `evidence`: source endpoints, docs, forum posts, or experiment files.
- `failure_modes`: likely ways this option can fail.
- `decision_needed`: the exact user choice requested.

## Source Priority

When sources conflict, the workflow uses this order:

1. Live platform API responses and official platform pages.
2. Recently cached official platform snapshots, marked with timestamp.
3. User-provided platform messages or emails.
4. Forum experience posts, marked as experience.
5. Local experiment results and benchmark logs.
6. Model inference, explicitly marked as inference.

## Refresh Cadence

- Before every workflow start: refresh dynamic activities, competitions, Power Pool boards, themes, account state, and relevant rule pages.
- Daily during active research periods: refresh active deadlines, board availability, and in-flight alpha/check state.
- Weekly: review principle health, benchmark drift, and stale knowledge pages.
- Immediately: refresh after any platform rule change, new activity announcement, unexpected check failure pattern, or user-provided platform message.

## Knowledge Outputs

The implementation should maintain these durable artifacts:

- `knowledge/raw/`: raw official snapshots, user-provided messages, and forum/source captures.
- `knowledge/wiki/00_principles/`: compiled principle pages.
- `knowledge/wiki/30_activities/`: activity, competition, Power Pool, and Theme summaries.
- `knowledge/wiki/50_benchmarks/`: benchmark rules and threshold changes.
- `knowledge/wiki/70_decisions/`: option cards, user choices, and decision rationales.
- `docs/knowledge/`: compact operational rules for future agents.
- `todo.md`: current task state, progress, failures, and next actions.

## Error Handling

- If live API refresh fails, use cached data only when the option card clearly marks cache timestamp and uncertainty.
- If a rule page is unavailable but affects submission feasibility, the related option must be marked high uncertainty or omitted.
- If activity rules and platform checks conflict, platform checks control submission readiness.
- If a run cannot support 30-alpha batches due to activity constraints or API limits, the deviation must be explicit in the user-facing plan.
- If an alpha is near-miss but does not improve any long-term metric, it should not consume repair budget.

## Review Gates

The user must approve:

1. The principle stack.
2. Any material change to top-level metric weights.
3. The option selected at workflow start.
4. Any final submission action.

## Success Criteria

This design is successful if future workflow runs:

- Start from refreshed consultant incentives rather than stale assumptions.
- Present clear research options before concrete planning.
- Preserve user choice before allocating API budget.
- Produce alpha batches that serve long-term pool value.
- Promote only fully checked alpha candidates.
- Convert repeated failures into durable workflow and benchmark updates.
