# Preplanned Research Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute sourced, preplanned branching experiments in two isolated lanes, then select Seeds and run deterministic Repair.

**Architecture:** Keep the existing Orchestrator, compiler, simulation/recovery and shared accounting. Add immutable tree attachments, pure decisions, a versioned Repair provider and thin process supervisor. New runs opt in; old runs never silently adopt new contracts.

**Tech Stack:** Existing Python312/unittest/JSON artifacts; no new Agent framework.

**Spec:** ../specs/2026-10-22-preplanned-parallel-research-console-design.md

## Global Constraints

- Offline development: no real WQB, research model calls, research resume or Alpha submission.
- Defaults: parallel_workflows=2, initial_hypotheses=4, plan_depth=2, seed_selection_limit=8 per lane.
- N-way implementation, tests N1/2/4 and invalid N; fair scheduling, independent
  transport concurrency, no multiplied budget/time/recovery authority.
- Signal >=0.9 with positive returns; negative <=-0.9 with negative returns and frozen reverse interpretation. Seed strictly Sharpe>1.25, turnover<0.40; hard gates precede existing score eligibility/ranking.
- Source batches <=30, existing Repair stage cap8, shared daily4000 Shanghai reset unchanged.
- Source-backed auto-exploration is not reviewed publication. Unsupported operations fail explicitly.
- Respect durable Stop, unknown POST identities, frozen contexts, time/recovery caps, separate submission authority.
- Every subagent explicitly reasoning_effort=medium or lower. No unrelated refactors/deletions.
- All new public functions document inputs/outputs/types; parameters use existing config boundary.

## Review Focus

- Partial/NaN/out-of-period arms must not become no-signal; Task2 tests completeness.
- Both arms signal in opposite directions; Task2 tests two children and reverse confirmation identities.
- Two workers race Stop, quota and duplicate reservation; Task5 tests process isolation and fences.
- A child passes platform checks but fails local comparison; Task3 preserves candidate evidence independently.
- A legacy run resumes after upgrade; Tasks1/4/6 preserve frozen release/planner/authority and receipts.

## File Map

Create narrowly scoped modules: wqb/exploration_eligibility.py (run-local template permission),
wqb/experiment_tree.py (immutable tree validation/routing), wqb/seed_policy.py (eligibility/ranking),
wqb/repair_search.py (finite planner), wqb/research_group.py (group process authority).
Reuse hypothesis_design.py, hypothesis_template_compiler.py, hypothesis_selection.py,
research_planning.py, repair_scheduler.py, repair_trace.py, workflow_driver.py,
runtime_control.py, console_start.py, daily_simulation_budget.py. Do not create a second ledger.
New tests mirror these modules in tests/. Config goes into configs/workflow_defaults.example.json;
never overwrite user workflow_local.json. Update operations docs and root architecture/handoff.

## Task1: Sourced Exploration Eligibility

**Files:** new exploration_eligibility.py/tests/test_exploration_eligibility.py;
modify hypothesis_design.py, hypothesis_template_compiler.py, hypothesis_selection.py,
research_planning.py and configs/workflow_defaults.example.json.

**Interfaces:** validate_exploration(design: dict, resources: dict, scope: dict) -> dict
returns immutable content-digested eligibility referencing existing compiler output,
raw certificates, roles and frozen policy; no forged semantic_status=reviewed.
compile_design remains the expression compiler. Add only explicit condition feature
nodes backed by trusted available operator signatures; never raw formula escape.

- [ ] Write failing tests for new sourced template eligibility, tampered source, absent operator,
  role/type mismatch, false reviewed promotion and unchanged legacy path.
- [ ] Run `python -m unittest tests.test_exploration_eligibility -v`; observe meaningful failures.
- [ ] Implement eligibility/frozen attachment and lookup-first/generate-if-unmatched path.
  Generated proposals enter existing knowledge records as exploratory with provenance,
  without silently publishing a global reviewed release or compiling the vault at Start.
- [ ] Test at least one actual executable condition using offline trusted fixtures. If no
  trustworthy supported subset can be specified, stop this deliverable with a concrete
  scope decision; do not claim prose-only applicability implements conditional experiments.
- [ ] Run new suite plus test_hypothesis_design/test_hypothesis_selection/test_hypothesis_pipeline;
  inspect diff and commit only this deliverable after green.

## Task2: Complete Preplanned Tree And Routing

**Files:** new experiment_tree.py/tests/test_experiment_tree.py;
modify hypothesis_design.py/research_planning.py/research_rounds.py.

**Interfaces:** validate_tree(tree: dict, resources: dict) -> dict;
route_pair(node: dict, measurements: list[dict]) -> dict.
Return status waiting|recover|branched|finished|inconclusive, selected arm/node IDs,
and structured reasons. Immutable plan contains expected simulation identities,
tree layer/parent references, sources, conditions, complete reverse/fallback plans
and finite expansion cost. Existing expression/settings identities remain authoritative.

- [ ] Write failing truth-table tests for zero/one/two signal arms, opposite signs,
  exact0.9/-0.9, zero returns, NaN/missing metrics, missing arm, mismatched period,
  duplicate/conflicting results and unknown POST. Require both expected arms before routing.
- [ ] Run `python -m unittest tests.test_experiment_tree -v`; verify failures.
- [ ] Implement root width4 with baseline+treatment, two children per selected arm,
  depth2 bound, deterministic stable ordering and no duplicate padded slots.
  Two no-signal arms use only a frozen defensible fallback, otherwise end hypothesis.
  Reverse confirmation needs actual measurements; cached negative values are not inverted.
- [ ] Reserve all executed alternatives within original limits.24/lane is the all-signal
  primary-path count, not permission for uncounted fallback/reverse submissions.
  Global transport chunking is independent of tree width; no partial comparison arms.
- [ ] Test restart replays identical routing without new AI calls or duplicate POST;
  new frozen plan tampering blocks. Run test_research_planning/test_research_rounds
  with the new suite; review and commit.

## Task3: Seed Policy And Real Incumbent Rollback

**Files:** new seed_policy.py/tests/test_seed_policy.py;
modify repair_trace.py, workflow_stage_adapters.py and experiment_tree.py.

**Interfaces:** select_seeds(rows: list[dict], policy: dict) -> dict;
compare_versions(parent: dict, child: dict, policy: dict) -> dict.
Outputs selected/rejected identities with reasons and accepted incumbent references.
Comparison evidence is not submission eligibility; retain all measured children.

- [ ] Write boundary tests:1.25 fails/greater passes,0.40 fails/less passes,
  missing/nonfinite metrics fail; existing score gate0.55, descending score then
  Sharpe then stable identity tie-break, maximum8, no-seed rotation.
  Required baseline research results must be complete; intentionally deferred SELF/PROD
  remain unqualified for submission, not a reason to demand expensive checks before Seed.
- [ ] Write rollback tests: accept objective improvement/no Sharpe-Fitness regression,
  new baseline failure rejects, turnover within frozen bound, comparison scope mismatch
  inconclusive, rejected child never becomes next parent. Test hard-pass child remains
  recorded/candidate-evaluable even when not the research incumbent.
- [ ] Run new tests and observe failures; implement versioned new-run policy only.
  Proposed initial comparison tolerance0 (no silent epsilon); declarations may set
  stricter turnover bounds, and Seed always applies0.40. Do not apply old repair_trace
  semantics accidentally to the new policy or alter legacy comparisons.
- [ ] Run test_repair_trace/test_workflow_stage_outcomes plus new suites; review/commit.

## Task4: Deterministic Semantic Repair Provider

**Files:** new repair_search.py/tests/test_repair_search.py;
modify repair_planning.py, repair_scheduler.py, repair_runtime.py and repair_trace.py.

**Interfaces:** prepare_search(run: Path, parent: dict, history: list[dict],
allowance: int, policy: dict) -> dict emits the existing verified plan envelope
with planner_kind=deterministic and version, no AI judgment receipt forgery.
Finite rule policy declares eligible data traits, trusted operator IDs, target
metric, one changed property, parameter grid, fixed priority and stop reason.

- [ ] Write failing tests for turnover->smoothing, concentration->bounded weights,
  sourced nuisance exposure->compatible neutralization, frequency-informed windows,
  unknown traits, unsupported transform, conflicting targets, dedup and finite exhaustion.
- [ ] Implement only trusted compiler/type-supported transformations; freeze exact
  parameters before dispatch. Reuse receipt/identity verification for both planner
  kinds; no direction/core-field/condition edits in deterministic Repair.
- [ ] Make scheduler consume accepted incumbent. Search from that parent; rejected
  edits remain measured history. Test cumulative accepted edits preserve mechanism.
- [ ] Test zero budget, Stop,429, unknown POST, result404 quarantine and old AI plan
  receipt replay without new model invocation. Run test_repair_scheduler/test_repair_runtime/
  test_repair_planning plus new suite; review/commit.

## Task5: Isolated Lanes With Shared Authority

**Files:** new research_group.py/tests/test_research_group.py;
modify workflow_driver.py/runtime_control.py/console_start.py/workflow_state.py
and existing source request policy/lock integration points only as needed.

**Interfaces:** create_group(runs_root: Path, plans: list[dict], authority: dict) -> dict;
stop_group(group: Path, expected_revision: str) -> dict;
read_group(group: Path) -> dict. Child runs keep their existing state machine;
group stores membership/intent/authority, not copied stage truth.

- [ ] Write failing subprocess tests for separate run envs, membership tamper, atomic
  identity reservation, duplicate Start, group Stop racing POST and disconnected UI.
- [ ] Specify/enforce lock ordering group authority -> identity reservation -> existing
  run submission/accounting locks consistently, without holding locks over network I/O.
  Validate ordering against current locks before code; adjust design if deadlock found.
- [ ] Share existing daily ledger and account cooldown. Proposed time authority is
  group wall-clock active time (not n independently renewed clocks); recovery allowance
  shared through group reservations. Exact values come from approved Start authority,
  not new defaults. Group Stop fence is checked immediately before child POST boundary.
- [ ] Test bounded concurrency, partial worker failure, orphan restart, daily rollover,
  global limit, recovery limit and original-only/legacy non-adoption. No real API calls.
- [ ] Run new suite plus test_daily_simulation_budget/test_daily_budget_workflow/
  test_research_loop_runtime/test_console_start; review/commit.

## Task6: Offline End-To-End And Handoff

**Files:** tests/test_preplanned_research_acceptance.py;
docs/operations/user_workflow_manual.md/maintainer_handoff.md; root milestone.md/todo.md.

- [ ] Write fixture scenario4roots x2arms x2lanes covering both-signal expansion,
  fallback, negative confirmation, reject/rollback, Seed ranking and deterministic Repair.
- [ ] Execute with fake transport/model fixture output; assert no model call after plan
  freeze, no live network, correct actual attempt charges, no internal gate clicks,
  durable Stop/restart and separate final submission authority.
- [ ] Full offline unittest discovery; independent medium review; fix regressions then rerun.
  Architecture tests: `python -m unittest tests.test_project_architecture tests.test_project_entry_docs -q`.
- [ ] Update architecture/capability facts and latest handoff. Report legacy Repair
  readiness case separately; no proof renewal/repair authorization inferred from design.
- [ ] Follow approved Git sync/cleanup procedure; no source/evidence deletion without
  audit. Desktop plan consumes verified group/tree/Seed/Repair read models after this boundary.

## Execution Gate

### Implementation Evidence And Rulings (2026-10-23)

- R1 source certification, opt-in conditional compiler, R2 immutable measured tree,
  R3 strict Seed, R4 finite Repair and R5 group/worker/Console wiring are implemented
  with isolated tests. R6 integrated fixture traverses two source-backed lanes
  through real multisimulation accounting (fake HTTP), cumulative tree evidence and
  Seed; branching/reversal/rollback and deterministic Repair have focused suites.
  This is not one exhaustive4-root/two-layer/Repair transport scenario.
- Daily pair waiting returns actual accounting/reset evidence; rollover reuses the
  frozen pair without another model call or refund. Stop interrupts waiting.
- Ruling: only the submission fence spans actual POST; intent locks do not. This
  serializes account requests and makes unknown outcomes durable. Fair queue wait
  is paced and bounded by original group runtime/Stop, not a false30s POST failure.
- Ruling: Start-supplied Repair currently accepts finite source-bound setting rules,
  not arbitrary transform resources. Unknown traits remain unknown; empty rules
  exhaust visibly. The typed transform engine is not proof of a deployed rule producer.
- Old runs retain their original path. Actual legacy Repair case/proof remains
  protected. No actual knowledge migration, model research, WQB or resume occurred.
- Final suite/reviews/Git status and next actions are authoritative in root todo.md;
  unchecked checklist items are not blanket completion claims.

User approves this written plan and chooses execution approach before product edits.
Changes to proposed interfaces/authority or trusted operator scope are recorded in
todo/spec before implementation, not silently improvised. The frontend plan is
separate and may proceed on fixtures while research contracts are implemented.
