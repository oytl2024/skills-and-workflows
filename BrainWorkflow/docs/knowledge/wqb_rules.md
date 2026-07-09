# WorldQuant BRAIN Rules Knowledge Base

Last updated: 2026-07-03

Bottom-layer reference: `docs/knowledge/wqb_foundations.md`.
Operator/data semantic reference: `docs/knowledge/operator_data_semantics.md`.

## Submission Gates

- Regular USA Delay-1 Alpha: Sharpe must pass platform threshold, Fitness must pass, turnover must stay between platform low/high limits, max weight and sub-universe checks must pass.
- Consultant USA Delay-1 documentation currently states hard targets of Sharpe > 1.58, Fitness > 1, Turnover between 1% and 70%, max stock weight < 10%, plus sub-universe, correlation, IS Ladder, and bias tests.
- A candidate is only eligible for local `candidates.csv` when `/alphas/{id}/check` has no failed hard checks and no pending hard checks.
- `SELF_CORRELATION` and `PROD_CORRELATION` are hard blockers unless platform explicitly allows a Sharpe-improvement exception.
- Warnings are recorded but do not create a candidate unless hard checks are clean.
- Final submission is manual only. The local workflow never calls a submit endpoint.
- Submit-check promotion uses the current `/alphas/{id}/check` result. If the alpha detail payload still contains older embedded `PENDING` rows but `/check` returns no failed and no pending hard blockers, the local candidate gate may pass.

## Power Pool And Fast D1

- Power Pool Alphas should stay simple: no more than 8 counted unique operators and no more than 3 non-grouping data fields.
- Power Pool descriptions need an Idea and Rationale format when submitting on the platform.
- Fast D1 uses Delay-1 settings and `_fast_d1` fields.
- Prefer explicit field suffix filtering over broad text search. Searching for `fast_d1` can miss actual suffix fields or select unrelated fields.
- For Fast D1, useful starting templates include:
  - `rank(field_fast_d1 - field)`
  - `rank(ts_delta(field_fast_d1, 1))` for MATRIX fields only
  - `rank(ts_mean(field_fast_d1, 5))` for MATRIX fields only
  - `group_neutralize(rank(field_fast_d1), subindustry)`
- Fast-minus-regular deltas are preferred when trying to reduce production correlation.
- Fast D1 candidates should outperform their regular D1 equivalents before submission. A Fast D1 branch should therefore compare against a regular-peer expression when the peer exists.
- If raw fast-minus-regular templates are weak for broad accounting fields, switch to `--template-mode relational` before abandoning the economic area. This mode keeps Scout expressions simple and two-field:
  - `rank(positive_field) - rank(negative_field)`
  - `rank(ts_delta(positive_field, 5)) - rank(ts_delta(negative_field, 5))`
  - `rank(ts_mean(positive_field, 5)) - rank(ts_mean(negative_field, 5))`
  - `group_neutralize(rank(positive_field) - rank(negative_field), subindustry)`
- Use relational templates for interpretable hypotheses such as operating cash flow versus capex, cash/asset strength versus debt/liability pressure, or current asset strength versus goodwill/intangible/receivable pressure. Keep the field count at two where possible for Power Pool compatibility.
- Not every `_fast_d1` field has a usable regular D1 peer. If the platform returns `Attempted to use unknown variable`, mark that field as missing its regular peer and skip delta templates.
- Platform `/data-fields` search can return broad same-dataset results even for exact-looking search strings. Use `--exact-field-id` when the run must target one specific field.
- Large dataset field queries without an API-side `--field-search` can time out before local suffix filtering runs. For broad datasets, first use semantic search terms such as `revenue`, `cash`, `margin`, `short`, or `ownership`, then apply `--field-suffix _fast_d1`.

## Data Field Types

- MATRIX fields can usually use cross-sectional and time-series operators directly.
- VECTOR fields must be converted before cross-sectional use. Current emergency default is `vec_avg(field)`.
- VECTOR Fast D1 templates should use:
  - `rank(vec_avg(field_fast_d1) - vec_avg(field))`
  - `rank(vec_avg(field_fast_d1))`
  - `group_neutralize(rank(vec_avg(field_fast_d1)), subindustry)`
- Platform errors seen:
  - `Operator ts_delta does not support event inputs`
  - `Operator ts_mean does not support event inputs`
  - `Operator rank does not support event inputs`
- These errors mean the field is not usable as a plain MATRIX input. Add the right vector/event conversion before resubmitting.
- `search_interest` fields observed in current runs are VECTOR and missing regular D1 peers, so use fast-only `vec_avg` templates such as `rank(vec_avg(relative_interest_score_3_fast_d1))`.

## Workflow Discipline

- Use `Scout -> Seed -> Discovery -> Repair -> Submit`.
- Before a new Scout branch, cache platform metadata in bulk where possible using `cache-metadata`; then preview candidates locally with `semantic-preview`.
- Scout: build a 30-Alpha candidate batch before submitting simulations. Goal is to decide whether a dataset or economic hypothesis has signal.
- Prefer applying one simple economic template across many new data fields first. If the field pool is too small, fill the 30-candidate batch with additional simple templates and setting-safe variants.
- Prefer `--template-mode semantic` when a field pool contains interpretable positive/negative economics. This mode tags fields and renders positive-minus-negative templates before simulation.
- Use `--field-cache-path` for `run-field-batch` when the fields were already cached. Do not re-query `/data-fields` just to regenerate a known candidate batch.
- For 30-candidate Scout batches, use `run-field-batch --submit-mode multi` by default. The workflow records `planned_candidates.jsonl`, submits small multisimulation chunks, and falls back to serial only for chunks rejected with HTTP 400.
- Scout starts from new data first when self/prod correlation is the dominant blocker. Use simple, interpretable economic templates on fresh datasets before touching old self-correlated price/volume seeds.
- Seed: keep a core structure that has enough evidence to reuse.
- Discovery: batch variants around a confirmed seed; save all results to files.
- Repair: only tune Alphas classified as `repairable_signal` by the benchmark layer. Strong core metrics are sufficient, but an explicit stable/straight PnL observation can also promote a near-threshold Alpha into Repair.
- Submit: no new simulation. Only check candidates and wait for human authorization.
- Before expressions, write the human idea in one sentence and store it as `human_idea`.
- In Scout/Seed, prefer one-line conservative expressions, shallow nesting, and at most two numeric parameters.
- If a branch is weak on Sharpe and Fitness, run the benchmark layer before discard. Discard only `weak_discard`; route `repairable_signal` to targeted Repair.
- Simulation quota is a hard research resource. All successful simulations count, including multi-simulation children, duplicate Alphas, and simulations of existing Alphas. Multi-simulation improves throughput but does not reduce quota use.
- Simulation POST responses can expose `X-Ratelimit-Limit`, `X-Ratelimit-Remaining`, and `X-Ratelimit-Reset`; until the CLI records these headers, HTTP 429 means stop the batch and recover/document rather than retrying blindly.
- Production correlation requests may be limited per hour. Do not spend correlation checks on weak Scout results.
- Use `python -m wqb.cli plan-stage --workflow-stage scout --dataset-id dataset_a,dataset_b` to generate an assignable task list before a parallel Scout session.

## Workflow-Improvement Loop

Any workflow optimization must itself use a workflow:

1. Trigger: name the repeated failure, platform rule, or efficiency bottleneck.
2. Evidence: cite official docs, source snapshot, run directory, API error, failed check, or test result.
3. Rule proposal: write the smallest rule that would prevent recurrence.
4. Implementation: update docs first; if code behavior changes, use TDD.
5. Verification: run focused tests or inspect the next run artifact proving the rule applies.
6. Promotion: update `wqb_rules.md`, `stage1_loop_agenda.md`, and `todo.md`.
7. Reuse: future loops must apply the rule before manual judgment.

Ad hoc workflow changes are allowed only as emergency exceptions and must be converted into a documented rule afterward.

## Parallel Workflow Roles

- `data_scout`: run one dataset with simple economic templates and write all run artifacts. Different datasets can run in parallel when API quota allows.
- `result_recovery`: recover in-flight simulations with `complete-in-flight` before creating replacement simulations.
- `template_scout`: test a small set of alternative simple templates on an already selected dataset. It must use a distinct run directory from data scouts.
- `diagnosis`: compare checked results, promote only signal-bearing seeds, and reject weak Sharpe/Fitness branches.
- `repair`: make 4-8 targeted changes only for `repairable_signal` Alphas.
- `submit_check`: re-check candidates and ensure no hard failed or pending checks remain.
- `knowledge_update`: record platform errors, field lessons, and workflow rule changes after each batch.

## Parallel Subagent Contract

- Every subagent handoff must include inputs, expected outputs, forbidden actions, and a promotion gate.
- `data_scout-agent` inputs: dataset id, field suffix, template mode, and human idea. Outputs: run directory, selected field ids, progress URLs, alpha ids, check results, and proposed next action. Forbidden: submitting final Alphas or promoting Seeds without Diagnosis.
- `result-recovery-agent` inputs: run directory and simulation events. Outputs: recovered alpha ids, check results, and recoverable errors. Forbidden: new simulation submission or expression changes.
- `diagnosis-agent` inputs: run artifacts and check summaries. Outputs: promoted seeds, near-misses, discarded branches, and next actions. Forbidden: new simulation submission.
- `repair-agent` inputs: near-miss alpha id, benchmark reasons, failed checks, and a repair hypothesis. Outputs: repair run artifacts and check results. Forbidden: repairing `weak_discard` branches.
- `submit-check-agent` inputs: checked candidate records. Outputs: `candidates.csv` rows only when hard checks are clean. Forbidden: final platform submission.
- `knowledge-agent` inputs: diagnosis summaries, platform issues, and field lessons. Outputs: updated knowledge docs and `todo.md` notes. Forbidden: simulation or submission.

## Stage Gates And Dependencies

- `result_recovery` runs before any resubmission for the same `run_dir`.
- `data_scout` tasks can run in parallel only when they use distinct datasets and run directories.
- `template_scout` can run beside a data scout only when it targets a different dataset or an already recovered completed run.
- `diagnosis` is the only stage allowed to promote a Scout result into Seed/Repair.
- `repair` requires `is_near_miss(alpha_record) == True`, which means the benchmark label is `repairable_signal`.
- `submit_check` never submits; it only verifies `/check` and writes local candidates.

## Run Artifact Contract

- Every run must persist `run_dir`, `dataset_id`, `field_ids`, `template_mode`, `human_idea`, expression hash, progress URLs, alpha IDs, check results, recoverable errors, and proposed next action.
- Handoff state must live in files such as `run_meta.jsonl`, `simulation_events.jsonl`, `all_alphas.jsonl`, `run_errors.jsonl`, `candidates.csv`, `docs/knowledge/*.md`, and `todo.md`.
- Chat memory is not a valid handoff artifact.

## Issue-To-Workflow Rules

- Repeated narrow metadata fetches: switch to `cache-metadata` and local `semantic-preview`; live API calls should be reserved for cache refreshes, simulations, checks, and recovery.
- Unknown regular peer, such as `Attempted to use unknown variable`: mark the field as missing its regular D1 peer and skip fast-minus-regular templates for that field.
- VECTOR/event operator rejection, such as `Operator rank does not support event inputs`: use a reducer such as `vec_avg(field)` before rank/group/time-series templates.
- Broad field search selects the wrong field: rerun with `--exact-field-id` and record the exact field in run metadata.
- Network reset or poll/check recoverable failure: run `complete-in-flight` on the existing run before resubmitting.
- HTTP 429 or rate limit: stop the batch, keep submitted progress URLs, back off, and resume later with fewer expressions.
- HTTP 429 after a successful multisimulation chunk: do not regenerate candidates. Resume the same run with `--multi-chunk-sleep-seconds` so chunk submission is throttled at the workflow level, and keep expression-hash dedupe on.
- `run-field-batch` also supports `--multi-chunk-sleep-seconds`; use it for cached 30-alpha Scout batches when the platform has recently returned 429.
- If a field batch has recoverable submit errors but no `SUBMITTED` events or progress URLs, classify the run as `submit_recoverable_error`, not `completed`; retry only after cooldown or move to read-only planning.
- For a `submit_recoverable_error` run with `planned_candidates.jsonl` but no progress URLs, use `python -m wqb.cli retry-planned --run-dir <run_dir> --submit-mode multi` after cooldown. It skips expression hashes already recorded as `SUBMITTED`, `CHECKED`, or `ERROR`.
- HTTP 400 from a multisimulation batch: record planned candidates and the failed chunk, then fall back to serial for that chunk to isolate invalid expressions without losing the whole batch.
- Repeated submit connection resets: raise request retry/timeout settings, recover existing progress URLs, and avoid immediate re-POST loops.
- Authentication TLS reset: record `run_errors.jsonl` and stop before field fetch or submission.
- Multiline Fast Expression syntax error from wrapping assignments: preserve assignment lines and wrap only the final expression.
- Repeated pending checks: schedule a recheck/recovery queue rather than generating new simulations for the same expression.
- A 500-alpha existing scan can exceed a 15-minute shell timeout while still writing records. Use a longer timeout or explicit smaller chunks; check the Python process and `existing_alpha_scan.jsonl` before restarting.
- Repeated weak Sharpe/Fitness in Scout: classify with the benchmark layer first. Stop only `weak_discard` branches; promote stable-PnL or near-threshold `repairable_signal` branches to Repair.
- During simulation POST cooldown or repeated HTTP 429, run read-only existing Alpha scans before spending more quota. If a scan finds a clean `/check` candidate, move directly to submit-check instead of continuing Scout.

## Failure-To-Action Notes

- Low Sharpe / low Fitness: if benchmark label is `weak_discard`, change data or economic hypothesis first. If label is `repairable_signal`, test 4-8 targeted changes such as direction flip, window, neutralization, decay, or fresh low-correlation data blend.
- High Turnover: increase decay, smooth the signal, or use a slower template only after core signal is good.
- Concentrated Weight: add rank/scale/winsorize or change field coverage. For VECTOR fields, check the vector conversion.
- Sub-universe failure: avoid size/liquidity multipliers that shift weights toward fragile liquidity buckets; consider neutralization changes only if core metrics are good.
- Self/prod correlation: prefer new datasets, new field types, and different economic hypotheses over minor operator rewrites.
- Before simulating custom expression batches, use the local novelty gate when reference ledgers are available: `run-expression-file --novelty-reference-file <all_alphas.jsonl> --min-novelty-score 1`. Low-novelty expressions are skipped and written to `novelty_rejections.jsonl`.

## Live Lessons

- `socialmedia12` Fast D1 simple deltas were weak in current tests.
- `fundamental3` EPS Fast D1 scout was weak in current tests.
- `model240` fields are VECTOR; direct `rank/ts_delta/ts_mean` caused platform errors. VECTOR-safe `vec_avg` scouts still failed Sharpe/Fitness/weight checks in the first recovered run.
- `search_interest` broad search selected `relative_interest_score_3_fast_d1` even when another field was requested. The workflow now supports `--exact-field-id` to prevent this.
- Blending a strong old price-volume near-miss with a fundamental Fast D1 delta can destroy core metrics; stop that Repair branch unless a smaller or different new-data expression is justified.
- `search_interest` Fast D1 VECTOR-safe candidates recovered on 2026-07-01 remained weak on Sharpe/Fitness and should not be repaired without a new template or field hypothesis.
- `news21` full-field Scout can select date/time label fields; prefer semantic searches such as `--field-search sentiment`.
- `news21 sentiment` Fast D1 candidates recovered on 2026-07-01 were consistently weak with high turnover and low 2Y Sharpe. Treat this branch as discarded for now.
- `earningscall_sentiment` has interpretable sentiment Fast D1 fields and planned candidates, but submit attempts hit connection resets/HTTP 429 before progress URLs. Retry only after POST cooldown.
- `other696`, `pv90`, `news46`, and `earnings7` returned no `_fast_d1` fields in the current USA/TOP3000/D1 targeted checks on 2026-07-01. Revisit only if platform visibility changes or a documented exact field id is found.
- `fundamental3 --field-search revenue --field-suffix _fast_d1` returned 40 high-coverage MATRIX fields across revenue, gross profit, cost of revenue, net income, operating cash flow, SGA, and EBITDA. This is the next preferred non-sentiment Scout branch.
- `fundamental3 revenue/profitability` fast-minus-regular and fast-only Scout on 2026-07-01 produced 15 checked Alphas with 0 hard passes; best Sharpe was 0.67 and best Fitness was 0.42. Do not repair this branch. Move to a different economic dimension such as cash-flow quality, balance-sheet quality, or capital efficiency.
- `fundamental3 cash` returned 40 cash/cash-flow/capex fields on 2026-07-01, but the first run hit submit connection resets and a 429 before any progress URL. Treat it as untested signal, not a failed signal; retry after API cooldown if POST access is available.
- `fundamental3 assets` raw fast-minus-regular/fast-only Scout on 2026-07-01 produced 10 checked Alphas with 0 hard passes and no remaining in-flight simulations. All checked results failed Low Sharpe/Fitness, so this raw asset branch is discarded; only revisit assets with a relational asset-quality template.
- `relational` template mode was added after raw `fundamental3` accounting branches were weak. Unit tests verify it generates 30 two-field candidates and CLI accepts `--template-mode relational`.
- `fundamental3` cached semantic Scout is now scripted in `scripts/run_fundamental3_semantic_scout.ps1` and `scripts/run_fundamental3_semantic_scout.sh`. It previews and then submits 30 cashflow/assets-minus-debt/liability/investment-pressure candidates from local metadata cache, with proxy variables cleared and multisimulation chunk sleep enabled.
- `fundamental3` cached semantic Scout on 2026-07-03 (`runs/20260703_011350`) checked 30 Alphas with 0 hard passes and 30 `weak_discard`. Best Sharpe was only 0.29 and reverse-direction candidates were also weak. Do not repair this branch; switch to a different dataset family or a materially different event-driven template.
- Existing Alpha scan on 2026-07-03 (`runs/20260703_existing_scan_1500`) found one submit-check candidate, `rKoqa6E1`. Recheck run `runs/20260703_submit_check_rKoqa6E1` recorded `failed=[]`, `pending=[]`, `hard_pass=true`, and warnings only.
- Safe API probing on 2026-07-03 confirmed the final submit route shape as `POST /alphas/{alpha_id}/submit`; `/alphas/{alpha_id}/submission` returned 404. Do not call this endpoint without explicit user authorization.
- Final submit API protocol mirrors the frontend: call `POST /alphas/{alpha_id}/submit`; if the response has `Retry-After`, keep calling `GET /alphas/{alpha_id}/submit` after that delay until the response has no `Retry-After` and returns JSON. Do not treat an empty HTTP 200 from POST as completed submission.
- `rKoqa6E1` was submitted on 2026-07-03 Asia/Shanghai time. Final verification shows `stage=OS`, `status=ACTIVE`, and `dateSubmitted=2026-07-02T21:38:33-04:00`.

## Phase 2 Principle-Led Planning

- Before each workflow start, refresh platform rules, activities, competitions, Power Pool boards, themes, account state, and relevant data metadata.
- Generate 3-5 option cards before any concrete alpha batch plan.
- The user must choose one option before the system creates activity, region, delay, dataset, template, or batch instructions.
- If refresh fails, show stale-cache warnings and prefer a refresh-recovery option.
- Do not run simulations or submissions from the option-card planner.
