# WorldQuant Brain Stage 1 Workflow Design

## Purpose

Build a maintainable command-line workflow for WorldQuant Brain that can produce a short list of Alpha candidates before 2026-07-02. The immediate objective is to avoid dormant consultant status by finding at least one Alpha that passes the platform's hard pre-submission checks and can be manually submitted by the user.

The workflow must support later evolution into a long-term optimization system with benchmark design, rules, and a knowledge base.

## Confirmed Scope

- Stage 1 is a rescue MVP focused on producing a submit-ready candidate Alpha.
- Stage 2 will address long-term workflow optimization, benchmark design, knowledge-base construction, and rule accumulation.
- The Stage 1 execution surface is a Python CLI and local JSONL/CSV records. No UI is included in Stage 1.
- The first ordinary Alpha target is `USA / TOP3000 / delay=1`.
- The search order is:
  1. Run a normal `REGULAR` Alpha workflow to prove the end-to-end loop.
  2. Prioritize Power Pool Alphas, especially the current `USA/D1 Fast Datasets Power Pool June'26` direction.
- The system must not automatically submit Alphas. Submission is a manual user decision.
- Credentials come only from `WQB_USERNAME` and `WQB_PASSWORD` environment variables.
- The system must never hard-code API credentials, cookies, tokens, or external sensitive file paths.

## Existing Project State

The current folder contains older semi-automated scripts for login, data-field retrieval, expression generation, multisimulation, result retrieval, and correlation checks. They show useful API intent but should not be extended directly as the main architecture because they have hard-coded credential paths, import-time network calls, broken payload construction, incomplete status handling, and hard-coded output paths.

The new design should reuse knowledge from these scripts but introduce clear module boundaries.

The current folder is not a git repository, so the design document cannot be committed from this workspace unless git is initialized or the project is moved into a repository.

## Architecture

Create a Python package with small modules:

```text
wqb/
  auth.py
  client.py
  models.py
  knowledge.py
  data_catalog.py
  generator.py
  simulator.py
  checker.py
  optimizer.py
  recorder.py
  cli.py
configs/
  stage1_usa_d1.yaml
runs/
run_stage1.sh
```

Responsibilities:

- `auth.py`: Read `WQB_USERNAME` and `WQB_PASSWORD`, create an authenticated session, and avoid logging secrets.
- `client.py`: Wrap all WorldQuant Brain API calls, retries, `Retry-After`, rate-limit handling, timeout handling, JSON parsing, and re-authentication.
- `models.py`: Define plain data structures for settings, generated candidates, simulation results, check results, optimization actions, and run summaries.
- `knowledge.py`: Fetch and snapshot platform materials used for the run, including search results, tutorial pages, FAQs, messages, videos, competitions, events, and Power Pool boards.
- `data_catalog.py`: Build data-field pools for the configured region, universe, delay, Power Pool theme, and source categories.
- `generator.py`: Generate expression payloads from field pools and templates. The generator must support later replacement by search, evolutionary, or LLM-based generators.
- `simulator.py`: Submit simulations, poll completion, and normalize alpha identifiers and result records.
- `checker.py`: Read `/alphas/{id}` and `/alphas/{id}/check`, classify hard checks, warnings, pending checks, and metrics.
- `optimizer.py`: Map failed checks and weak metrics to concrete rewrite actions for the next round.
- `recorder.py`: Write JSONL/CSV/Markdown artifacts and support expression-hash-based resume.
- `cli.py`: Provide `dry-run`, `smoke`, `run-stage1`, `status`, `scan-existing`, `refresh-alpha`, and `complete-in-flight` commands.

## Data Flow

1. Authenticate with WorldQuant Brain.
2. Load Stage 1 config from `configs/stage1_usa_d1.yaml` and optional CLI overrides.
3. Snapshot relevant platform knowledge:
   - `/search?query=...`
   - `/tutorial-pages/{id}`
   - `/faqs/{id}`
   - `/messages/{id}`
   - `/videos/{id}`
   - `/events`
   - `/competitions`
   - `/consultant/boards/power-pool`
4. Build a data-field pool for ordinary USA/D1 candidates.
5. Generate a small ordinary `REGULAR` batch and run it through simulate, poll, and check to prove the loop.
6. Switch to Power Pool-oriented candidates:
   - USA region.
   - Delay 1.
   - Simple expressions.
   - At most 8 unique operators.
   - At most 3 unique data fields, excluding grouping fields.
   - Prefer fields and datasets tied to current Power Pool theme signals when available.
7. Simulate each batch, poll completion, and fetch check results.
8. Add only hard-check-passing Alphas to `candidates.csv`.
9. For failed Alphas, diagnose failures and enqueue rewrite actions for the next round.
10. Stop when a hard-check-passing candidate is found, the round budget is exhausted, or the run is explicitly stopped.

## Stage 1 Budget

Default budget:

- `max_alphas_per_round = 50`
- `max_rounds = 5`
- `stop_after_first_candidate = true`

These values must be configurable through `configs/stage1_usa_d1.yaml` and `run_stage1.sh`.

## Candidate Policy

An Alpha enters the candidate list only if platform hard checks pass through `/alphas/{id}/check`.

Warnings are recorded but do not block candidate inclusion unless the platform state clearly indicates the Alpha cannot be submitted. Pending checks are not considered passing.

The workflow does not call a submit endpoint.

## Live Execution Findings

The Stage 1 rescue path added several operational commands after real API runs exposed platform behavior:

- `status`: summarize local run artifacts and detect in-flight simulations from `simulation_events.jsonl`.
- `refresh-alpha --alpha-id ID`: re-simulate an existing Alpha using its stored expression and settings.
- `refresh-alpha --replace-operator OLD=NEW`: rescue old expressions that use operators no longer available to the account.
- `refresh-alpha --set-setting KEY=VALUE`: re-simulate an old Alpha with small settings changes, such as higher `decay`.
- `complete-in-flight --run-dir RUN`: recover a run where simulation completed but the local process failed before writing check results.

Observed platform behaviors:

- Some old Alphas use inaccessible operators, for example `group_normalize`; these now produce structured `SIMULATION_ERROR` records instead of crashing the workflow.
- `/alphas/{id}/check` can briefly return an empty or non-JSON response after simulation completion; `checker.fetch_check_summary()` now retries before failing.
- Rate limiting can block new simulation submissions even after client retries. A 429 run is recorded in `run_errors.jsonl`; the correct response is to cool down and resume later, not to keep submitting.
- Candidate gating remains strict: a row is written to `candidates.csv` only when `/check` has no failed or pending hard checks.

Current strongest USA/TOP3000/D1 rescue lead:

- Parent `qXvKVNj` refreshed to `E5wQ2z10`: Sharpe 2.14, Fitness 1.28, Turnover 0.4118, only confirmed hard fail `LOW_2Y_SHARPE` with value 1.45 vs limit 1.58. Next planned experiment is `--set-setting decay=15` or `decay=20` after rate-limit cooldown.

## Platform Rules Captured So Far

Regular Delay-1 submission targets:

- Fitness greater than 1.
- Sharpe greater than 1.25.
- Turnover between 1% and 70%.
- Maximum single-stock weight under 10%.
- Sub-universe test passes.
- Self-correlation below 0.7, or Sharpe at least 10% greater than correlated Alphas.

Power Pool eligibility targets:

- Sharpe at least 1.0.
- Unique operators at most 8. `ts_backfill` and `group_backfill` do not count.
- Unique data fields at most 3, excluding grouping fields such as country, industry, subindustry, currency, market, sector, and exchange.
- Power Pool correlation below 0.5.
- Turnover tests pass.
- Sub-universe test passes.
- Robust-universe test passes where applicable.
- If self-correlation among Power Pool Alphas is greater than 0.5, Sharpe should be at least 10% higher than the most correlated Alpha.

Current Power Pool theme notes:

- `USA/D1 Fast Datasets Power Pool June'26` requires USA region and delay 1.
- Platform messages say the relevant datasets can be found on the Data page with the Theme checkbox.
- The exact API filter for that checkbox still needs implementation-time confirmation.
- Fast D1 fields should be selected by an explicit `_fast_d1` suffix filter or exact field id. Searching for `fast_d1` through `/data-fields` can return zero results or unrelated non-suffix fields, so the workflow must not rely on broad text search alone.
- For Fast D1 fields, prefer economic templates that use the incremental information in the faster field, especially `field_fast_d1 - field`, short-horizon `ts_delta(field_fast_d1, 1)`, light smoothing, and group-neutralized variants. This follows the platform Fast D1 guidance that faster data should outperform its D1 equivalent and can help reduce production correlation.
- Keep Fast D1 Power Pool templates low-complexity: no more than three data fields, no more than eight unique counted operators, and no unverified operator syntax in emergency runs.

Forum research status:

- Public support/forum pages are not currently readable through this environment. Proxy access resets TLS connections, direct access returns Cloudflare challenge pages, and in-app browser navigation timed out on a known community post.
- Until a logged-in browser session is available, forum-derived high-vote templates must remain a backlog item. Only official tutorial/message/API findings should be encoded into automated rules.

## Optimization Workflow

The optimizer must use a rule workflow, not one-shot filtering:

- Low Sharpe, low Fitness, or low Returns:
  - Try alternate fields in the same theme.
  - Try direction flips.
  - Try alternate lookback windows.
  - Add `rank`, `zscore`, `scale`, or similar stabilization.
  - Try a different neutralization.
  - Avoid excessive conditional stacking.
- High Turnover:
  - Increase decay.
  - Increase lookback window.
  - Add smoothing such as time-series mean or decay.
  - Consider `trade_when` to reduce trading frequency.
- Low Turnover:
  - Reduce decay.
  - Shorten lookback windows.
  - Avoid excessive smoothing.
- Concentrated Weight:
  - Add rank or scaling.
  - Adjust truncation.
  - Use backfill where coverage is weak.
- Sub-universe or Robust-universe failure:
  - Prefer more stable fields.
  - Reduce overfitting.
  - Try alternate neutralization or risk-neutralized settings.
  - Penalize narrow or fragile branches.
- Self, Prod, or Power Pool correlation failure:
  - Prefer a new dataset or operator family.
  - Change the economic hypothesis.
  - Prefer faster/newer fields and fast-minus-regular deltas over cosmetic rewrites of historical price-volume expressions.
  - Continue only if Sharpe is high enough to satisfy the 10% improvement exception.
- Data diversity, theme, or competition mismatch:
  - Re-query knowledge and catalog sources.
  - Restrict the generator to the active theme and eligible fields.

Implemented emergency CLI extensions:

- `run-field-batch --field-suffix _fast_d1` filters selected fields after catalog fetch and prevents accidental use of ordinary D1 fields.
- `run-field-batch --template-mode economic` generates economically motivated templates such as `rank(field_fast_d1 - field)`, `rank(ts_delta(field_fast_d1, 1))`, light `ts_mean`, and group-neutralized ranks.
- Run metadata records `field_suffix`, `template_mode`, and `seed_field_ids` so failed branches can be diagnosed later.
- `run-field-batch --workflow-stage scout --human-idea "..."` records the plain-language hypothesis and applies stage budgets. Scout and Repair are capped at 8 simulations by default.
- VECTOR Fast D1 fields must be converted before cross-sectional use. The economic generator uses `vec_avg(field)` and `vec_avg(field_fast_d1) - vec_avg(field)` for VECTOR fields instead of direct `rank`, `ts_delta`, or `ts_mean`.
- `repair-alpha-with-field` supports near-miss Repair by blending a high-quality old Alpha with a new data expression at small weights. It preserves multi-line Fast Expression assignments and only wraps the final expression.

Forum-derived workflow rules provided by the user:

- Start with a plain-language economic idea, then translate it into 1-3 conservative expressions.
- Default to simple operators, one-line expressions, shallow nesting, and no more than two numeric parameters for Scout/Seed.
- Do not use AI-generated bulk expressions as a substitute for research judgement; broad random generation tends to produce high production correlation.
- Split work into `Scout -> Seed -> Discovery -> Repair -> Submit`. Do not mix stage objectives in one run.
- Scout uses 4-8 small tests to decide whether a dataset or hypothesis is worth keeping.
- Repair is only for near-miss Alphas with good core metrics; weak Alphas are discarded rather than tuned repeatedly.
- Discovery stores all results in files, not conversation memory.
- Submit stage must not introduce new simulations; it only checks candidates and waits for human authorization.

Each optimization action must record its parent Alpha, failure reason, action type, and resulting child expression hash.

## Run Artifacts

Each run writes under `runs/<run_id>/`:

- `knowledge_snapshot.json`
- `all_alphas.jsonl`
- `optimization_trace.jsonl`
- `candidates.csv`
- `run_summary.md`
- Optional raw API response snippets with secrets excluded.

Terminal output should stay concise and avoid printing full credentials or session material. Expression code can be saved in run records, but summaries should prefer hashes and metrics.

## Safety and Rate Limits

The client must:

- Respect `Retry-After`.
- Back off on HTTP 429.
- Retry transient 5xx and JSON parsing failures.
- Re-authenticate on authentication expiry.
- Avoid aggressive concurrency during Stage 1.

Stage 1 should prioritize completing safely over maximizing throughput.

## Testing and Verification

Tests:

- Unit tests for payload structure.
- Unit tests for expression complexity counting.
- Unit tests for check classification.
- Unit tests for failure-to-action optimization mapping.
- Unit tests for JSONL/CSV recording and resume behavior.

Commands:

- `python -m unittest discover -s tests -v`
- `python -m wqb.cli dry-run --config configs/stage1_usa_d1.yaml`
- `python -m wqb.cli smoke --config configs/stage1_usa_d1.yaml --max-alphas-per-round 3 --max-rounds 1`
- `bash run_stage1.sh`

Verification gates:

- Unit tests pass.
- Dry-run generates structurally valid payloads.
- Smoke test completes one live simulate, poll, check, and record cycle.
- Full run produces either at least one hard-check-passing candidate or a clear failure summary with next actions.

## Open Implementation Questions

- Confirm the exact API filter for the Data page Theme checkbox used by the current Power Pool theme.
- Confirm whether correlation endpoints that currently return HTML require a different header, a prior trigger, or a different alpha state.
- Confirm the minimal submit-readiness state for Power Pool-only Alphas versus regular Alphas after `/check`.
- Decide during implementation whether local run directories should be ignored by git if the project becomes a repository.
