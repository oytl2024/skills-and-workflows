# AI execution boundary

Opening the desktop app does not create a Codex task or call a GPT model. Initial preplanned research uses a bounded read-only model task per lane to propose hypotheses, roles and a finite experiment tree. Subsequent tree decisions and Repair are deterministic and consume frozen rules. A pending checkpoint is not evidence of model execution. See root todo.md for actual deployment/readiness, not just implemented capabilities.

## Catalog Admission Boundary

New frozen `knowledge_catalog_v1` contexts expose source-backed catalog resources
without requiring a published economic-semantic interpretation. Missing meaning,
polarity, timing or grain is explicitly unknown, not a reason to hide an identity
and not a fact the model may invent. Visibility does not prove compilability:
unknown operator signatures cannot pass deterministic type/arity validation.
New retrieval design_version3 accepts explicit source-backed VECTOR reductions
before numeric features; v1/v2 contracts remain unchanged. GROUP is context, not
a numeric feature. No implicit reduction is introduced. Source identity, dates
and returned-field coverage remain independent.

With retrieval_design_version=1, one read-only planning task per lane searches
generation-bound local tools and may correct drafts before final output. The
task owner enforces cumulative tool/validation/response limits and records compact
progress. Scripts resolve exact selected resources/history, compile and seal them
through the existing coordinator without a second model call. After sealing,
tree branching/Seed/Repair remain script-owned and use frozen scientific inputs.
No capture, late model plan, budget renewal or Alpha submission follows from a
query or validated draft. Installed acceptance belongs to root todo.md.

Resource admission, AST/type validation, experiment-tree standards, execution
routing, Seed gates, finite Repair search and permission/accounting are separate
contracts. This update changes admission and the result-input adapter, not Seed
thresholds, tree rollback, Repair grids or Stop/submission authority. Frozen runs
without the marker retain their prior rules. Deployment status is in root todo.md;
source support alone does not prove the installed app has switched entries.

`wqb/ai_checkpoints.py` provides the first durable worker contract. A caller supplies an explicit executable argv with `{input}` and `{output}` placeholders. The worker receives a JSON checkpoint input and must write JSON output with a nonempty `summary`. Every attempt stores input, output location, and running/completed/failed status in the decisions directory. No default model, credential, or shell command is selected, and an empty argv leaves the checkpoint pending. The worker does not submit Alpha or change research rules.

The run-local adapter lives in `wqb/codex_ai_worker.py`: it passes bounded evidence excerpts to `codex exec` with `--sandbox read-only`, `model_reasoning_effort=medium`, a JSON output schema, and a 600-second inner timeout. The enclosing checkpoint worker persists attempt input/output/status and has a 900-second outer timeout. It does not run WQB API calls, change workflow files, or submit an Alpha. When the Codex executable is unavailable, the checkpoint fails visibly while the deterministic workflow remains independently auditable. Direct CLI workflow runs without `--ai-executor codex` leave checkpoints pending; the Console workflow-run path configures it explicitly.

Initial research and independent knowledge compilation retain their separate schemas and authority. Legacy repair_decision and near_miss_interpretation checkpoints reject before subprocess dispatch. Historical answers remain readable but cannot authorize a new experiment. repair_policy.py verifies only deterministic receipts; validated/consumed does not mean checked or qualified.

Repair consumes certified finite settings/transform rules, preserves the accepted economic kernel and tests one permitted edit at a time. Missing sources, arbitrary operators/new fields and changed authority fail closed. The user approved retiring old AI Repair missions on Nov 3: they remain read-only evidence and are not automatically migrated. Independent eligible parents may advance within the existing reservations and platform policy.

Driver-owned workers are cancellable on Stop and bounded by the remaining absolute runtime deadline, including the pre-POST gate. Pending baseline checks recover the saved AlphaID with paced bounded attempts; no simulation resubmission. Resource and long-wait notices are durable event-driven messages, not repair/renewal permission. Rule-change proposals and wiki compilation remain separate maintenance work. Live model/platform quality is not established by offline fixtures.
# Deterministic Repair and maintenance feedback

Repair does not build a model prompt. Exact field identifiers, source digests,
parent identity, measured history and frozen search rules bind its receipts.
No model or simulation allowance is created by retiring the old adapter.

An unrecoverable planning error is reported immediately as maintenance-blocker,
not retried until generic no-progress. Current Work reports case ID, notification
delivery and whether human repair confirmation or verification is pending. A
delivered notification is not repair authority; runtime renewal cannot waive it.

## Repair Coverage Audit Before Maintenance (2026-11-04)

Deterministic execution is implemented, but this does not establish a complete useful Repair knowledge/rule library or actual deployment. Fresh targeted verification: 59 tests passed in 21.504s (repair_search, deterministic integration and compiled policy suites); fake/source-backed fixtures are not full real-vault acceptance.

- preplanned_start._repair_policy freezes an empty rule list when no explicit policy is supplied. A legal plan can therefore reach Repair and exhaust without a new simulation; this is not evidence of unsuccessful parameter optimization.
- repair_search.prepare_search filters frozen trait predicates, finite measured target presence, parameter bounds, identity novelty and a fixed declared priority. It does not yet derive action priority from current failed checks or metric-gap severity. In an offline fixture with only LOW_FITNESS, turnover .10 and .70 both selected the same smoothing rule first.
- Current compiled transform invariants cover ts_mean positive averaging and signed_power sign preservation, plus finite decay/truncation/neutralization settings subject to their prerequisites. This is narrower than a general characteristic-to-operator rule library.
- Single-change generation, accepted-incumbent lineage, controlled before/after comparisons, rollback, finite exhaustion, Stop/budgets and no late model execution are implemented. Missing rules, unmet prerequisites and tried-but-unhelpful candidates must not be conflated as economic-mechanism failure.
- Remaining acceptance must demonstrate actual data characteristics plus failed metrics selecting nonempty legal rules/finite parameters, useful rule coverage and auditable distinct stop reasons through the real resource consumer. Do not claim this is delivered solely because deterministic execution tests pass.

## Metric-Directed Repair Update

Modern source-contract-v2 Start now freezes a nonempty schema-v2 project rulebook from `configs/repair_rulebook.json`, with sourced numeric/matrix properties and cadence only when explicitly documented. The named public catalog participates in preparation identity, loaded-code identity and maintenance verification; the desktop bundle includes only that file, never private configs. Explicit v1 policies and legacy source-contract-v1 preparations retain their old behavior and receipt reconstruction. Existing missions are not migrated.

Rules activate from completed baseline failure names or a measured metric predicate. Gap severity precedes declared priority; an otherwise identical low-Fitness parent with high turnover selects turnover smoothing rather than blindly repeating the low-Fitness response search. Pending checks are not failed checks. Candidates must satisfy actual incumbent field/type/source binding, prerequisites, finite domains, parameter direction, known cadence and novelty. One property changes; comparison preserves the economic kernel and accepted-parent lineage. No late model task is dispatched.

Default coverage is deliberately narrow: decay response/averaging for low Sharpe/Fitness or high turnover, and lower truncation for concentration. These are competing project experiment hypotheses, not guaranteed improvements or invented noise/exposure facts. Source-certified ts_mean/signed_power transforms and justified neutralization remain supported through explicit frozen policies; the default catalog does not fabricate their missing prerequisites. This is not a universal operator/action library.

Receipts distinguish missing rules, no observed trigger, missing prerequisites, no novel candidates, tested without improvement and finite-space exhaustion. The scheduler retains the specific reason, skipped actions and measured attempt count; the existing Console comparison projection displays the trace. Exhaustion says nothing about economic causality. Full real-vault readiness and release/desktop activation remain separate acceptance boundaries; current results belong in root todo.md.

## Structured Output Transport (2026-11-25)

Initial and retrieval workers reuse strict_worker_schema/normalize_worker_answer:
all provider-object properties are required on the wire; optional canonical
properties are nullable and absent values are removed on return. Frozen task
schemas and experiment-tree semantics do not change. In particular, null reverse
arms do not create reversal experiments. Original schema validation and ownership
checks still run after normalization.

Fake-provider tests must inspect the actual transmitted schema recursively and
return wire-shaped values; merely copying canonical fixture JSON cannot detect
provider schema rejection.79 affected tests and3 native packaged tests passed
offline for this change, not a new full-suite or real model/API acceptance.
The failed HTTP400 Start was separately released by explicit human approval,
retaining original task/error/accounting and a local resolution receipt. This is
not a general automatic waiver for unknown model outcomes or retry authority.

Post-install build cleanup for output/desktop-application/20261125-091347-1980
and output/desktop-build-deps was rejected by environment policy before execution.
They remain disposable but retained; do not bypass that rejection using another
tool/language. Installed acceptance receipts remain separate from those caches.
