# Preplanned parallel research and desktop Console

Status: user-approved functional direction, revised 2026-10-22; implementation
plans and remaining engineering choices require review before product changes.
Date: 2026-10-22. Canonical rules and handoff remain at workspace root.

## Goal and boundaries

Reuse the existing semantic contracts, compilation, binding, research planning,
runtime recovery and Console. Do not introduce a new Agent framework or replace
the Orchestrator core state machine. New behavior is opt-in/versioned; existing
runs retain their frozen behavior and identities. Final submission stays separate.
The current Repair context blocker must be reproduced and resolved without
weakening provenance; this document is not repair approval for that case.

## Approved research design

- AI acts before execution: sourced field characteristics, mechanism, conditions,
  alternative explanation, falsification, template and entire experiment tree.
- Match existing templates by economic roles and conditions; otherwise compile a
  structured draft. Automatically validated exploration eligibility is separate
  from established knowledge status. Retain new templates as exploratory, supported,
  failed or inconclusive with immutable evidence; never imply causal proof.
- Supported observable conditions must compile into actual experiments; prose-only
  conditions are identified as interpretive, not represented as tested filters.
- plan_depth defaults to 2. Precompute alternatives. The latest approved routing
  supersedes the earlier single-winning-path proposal: continue every signal arm,
  not every unselected alternative. No model calls between nodes or during Repair.
- Each lane starts with initial_hypotheses=4 distinct sourced hypotheses. Layer1
  tests baseline+treatment for each (8 configurations). Each signal arm may spawn
  two preplanned layer2 treatments compared with its measured parent. If all eight
  arms signal, this adds16 configurations, for24 per lane and48 across two lanes,
  before reuse/deduplication. This is not a universal bound including result recovery,
  explicitly planned reverse confirmation or no-signal fallback; reserve their
  identities/budget before dispatch and keep each source batch <=30. No padding.
- Routing truth table for each complete pair: signal/no-signal continues the signal
  arm; no-signal/signal continues the other; signal/signal continues both. Two
  no-signal results select an explicitly frozen alternative-explanation experiment,
  or finish that hypothesis if none is defensible. Unknown is recovery, not a branch.
  Negative signals require predeclared reverse semantics and actual reverse
  measurement before positive Seed eligibility; never transform cached metrics.
- Signal routing: Sharpe >=0.9 with positive returns; reverse signal <=-0.9 with
  negative returns and a predeclared economic interpretation. Otherwise no clear
  signal. Missing/invalid results go to recovery, never the no-signal branch.
- Nodes store hypothesis, expressions, settings, roles, sources, applicability,
  comparison period/scope, routing predicates, acceptance and rollback references.
  Branch predicates must be exhaustive and nonoverlapping, with explicit unknown.
- Single-change comparisons use fixed scope/period and declared metrics. Target
  improves, Sharpe/Fitness do not regress, no new baseline failures, turnover stays
  within declared bounds; otherwise retain the previous best. Incomparability is
  inconclusive. Directional scoring is frozen before tests, never post-hoc abs().
- Seed eligibility first requires strict Sharpe >1.25 and turnover <0.40 plus
  complete valid research evidence. Preserve the current signal-score eligibility,
  then rank by score; select seed_selection_limit=8 per lane. Distinguish this
  number of selected cores from existing stage simulation caps (Seed8/Repair8).
  Existing v1 runs keep their original eligibility. Stable tie-breaking must be
  specified in the implementation plan; Seed status is never submission clearance.

## Parallel lanes

- parallel_workflows (n) defaults to 2. Generate n distinct sourced data/hypothesis
  plans before execution. Global identity deduplication rejects padded duplicates.
  Insufficient valid plans produce fewer lanes with an explicit explanation.
- N is a validated positive configuration, not a two-slot implementation. Test
  N=1,2,4 and invalid input. Keep lane count separate from bounded request
  concurrency; fair dispatch prevents starvation. Larger N needs measured capacity
  evidence, never larger account authority. UI page count derives from membership.
- One selected objective owns a durable group and child-lane references. Proposed
  coordinator reuses existing run APIs, locks and workers; final storage schema
  follows implementation inspection, not a second state authority.
- Lanes progress independently, but share account/workspace daily4000 accounting,
  rate-limit cooldown and bounded transport concurrency. Never multiply quota by n.
- Global Stop persists before cancelling dispatch; in-flight evidence survives.
  An account-wide blocker pauses affected lanes; lane-local failure need not stop
  unrelated safe work. Unknown POST outcomes are reconciled, not resubmitted.
- Apply existing time/recovery authority explicitly; do not silently create fresh
  budgets for child lanes or migrate an active old run into n new runs.

## Deterministic Repair

Input: measured seed, sourced/measured/assumed characteristics kept distinct,
failed metrics, frozen operator rules, allowed parameters and tested identities.
Output: bounded single-change plans and comparable result/rollback receipts.

Actions: supported smoothing/decay for turnover/noise, truncation or approved
weight transformations for concentration, justified neutralization for nuisance
exposure, frequency-informed windows. Preserve core fields, economic roles,
conditions and direction. New mechanisms or condition data return to Scout.
Unknown facts do not authorize imputation or operators. Rule tables require source,
types and bounds. Search is finite/deduplicated; no intermediate model judgment.
Stop when qualified, no novel legal candidates remain or stage authority expires.
Exhaustion means no improvement in this search space, not a disproved mechanism.

## Desktop interaction and projection

Build on the current desktop launcher/backend after dependency inspection.
Deliver a clickable .exe application, not merely a renamed command script.
Choose packaging after inspecting the existing host; avoid another backend or an
unnecessary browser runtime. No administrative installation assumed.

Approved stack direction: React + TypeScript frontend, existing Python backend,
and a lightweight system-WebView desktop host subject to offline feasibility.
No Vercel/cloud deployment, Electron or Rust stack is implicitly approved. The
WebView/EXE toolchain remains an evidence-based packaging decision, not a promise
that an unchanged HTML wrapper meets application interaction requirements.

Routine controls: option selection, Start and Stop; status navigation is read-only.
Top bar: group state, shared daily use, data/evidence freshness, connection state.
Replace lane tabs with previous/next arrow icon buttons and a visible page indicator
such as "Workflow 1 / 2", alongside the current lane name and status. Arrows are
disabled at the first/last lane; no implicit wraparound. Navigation only changes
the viewed lane, never starts, stops or resumes research. Preserve each lane's
selected stage/node and scroll position when switching. Selected lane shows Scout
tree, Seed and Repair. Keep a distinct overview entry for group-level status.
Node selection displays full expression/settings/alpha ID if known, hypothesis,
field characteristics, source references, metrics, signal and routing reason.
Unexecuted nodes display planned, never fabricated metrics or alpha IDs.
Seed shows retained core, identity, metrics, origin and why it passed.
Repair contains an independently scrollable experiment list with current expression,
settings, alpha ID (blank if absent), score, metrics and acceptance/rollback reason.

Near-real-time local updates reuse source-bound snapshots and revision checks;
prefer push with bounded polling fallback. No extra WQB calls for rendering.
Stale data visibly marked; action authority comes from current server state.
Colors supplement text: running teal, waiting amber, failed red, unselected gray.
Use a restrained white/graphite surface, readable Chinese text and monospace code.
No decorative cards around sections; tree is the primary visualization.

### Visual direction: Notion-inspired readability

Use Notion as a functional reference, not a branded replica or dependency. Prefer
neutral white surfaces, dark readable text, restrained separators, generous but
work-efficient spacing and clear heading hierarchy. Avoid marketing composition,
decorative gradients, nested cards and excessive status colors. Navigation and
stage views remain predictable; tables align numeric metrics and preserve units.
Use a Chinese-capable system font for prose and monospace for expressions/IDs.
Long expressions can expand/wrap in details; overview rows stay compact. Secondary
metadata is progressively disclosed, never hide current blockers or key metrics.
Keep arrow navigation, page count and Start/Stop in stable positions. Use familiar
icons with tooltips and text status labels; color is supplemental. Support visible
keyboard focus, adequate contrast, reduced motion and text zoom without overlap.

### Application interaction and latency contract

The user rejects the current document/form-navigation experience, not merely its
colors. Deliver a desktop application window with persistent in-place views: no
form POST navigation, raw refused/JSON pages, manual refresh or whole-page reload
for normal actions. Web-rendered internals may be reused inside a desktop host;
an .exe wrapper around unchanged page interactions is not acceptance.

On click, immediately show a local pending state and prevent duplicate commands;
then show server acceptance/job identity or an inline actionable error. Never
present pending as successful execution. Preserve command identities and Stop
authority on timeouts/disconnects; reconcile uncertain acknowledgments instead of
blind replay. Known action conflicts remain in the application with a clear reason,
not an HTTP error page. Show source-stale, reconnecting and offline states separately
from platform cooldown, failed jobs and unfinished simulations.

Use an initial bounded snapshot and ordered/versioned event updates, preferably
SSE with reconnect/cursor catch-up and local polling fallback. Reject stale events;
resnapshot on gaps. Keep UI projection separate from authoritative durable state.
Switching workflows or inspecting a node uses cached view data immediately and
does not query WQB. Fetch large details lazily; bound/virtualize long experiment
lists. Slow knowledge parsing, model work and network jobs stay off request/UI
threads; measure actual bottlenecks before adding infrastructure.

Proposed local acceptance targets, measured under documented fixture/load: click
pending feedback within 100ms, cached lane switching within 150ms, and persisted
event-to-view p95 within 1s on a healthy local connection. Report API acknowledgment
latency separately; external simulation/model times are not UI latency promises.
Exercise queued/running/accepted/rejected/error/disconnected/reconnected states,
duplicate clicks, lost acknowledgments, Stop races and large-history rendering.

## Verification and delivery sequence

1. Human reviews this design, wireframe and depth convention.
2. Inspect task-relevant code and write an approved implementation plan, including
   a reuse/deletion map. Preserve compatibility readers and protected evidence.
3. Offline compiler/tree/routing/rollback/seed/search tests; concurrency, Stop,
   restart, quota, cooldown and unknown POST tests. No actual WQB/model calls.
4. UI tests for two lanes, node selection, blank IDs, long expressions, scroll,
   stale state and automatic progress. Desktop launch and loaded-source check.
5. End-to-end offline path: generate fixtures, select branches, rollback, Seed,
   deterministic Repair, qualified candidate; user never clicks internal gates.
6. Report source gaps honestly. Deployment/proof renewal/live resume need their
   applicable approvals. Follow verified Git sync and audited cleanup rules.

## Open review points

- Confirm tree-depth counting and desktop wireframe.
- Exact runnable condition/transformation subset must follow trusted definitions
  and compiler support. Reject unsupported designs rather than broad formula escape.
- Strong-signal detection currently uses the approved coarse threshold; later
  robustness refinements require proposals, not silently changed routing rules.

## Independent static audit, 2026-10-22

Two read-only agents used explicit medium reasoning; frontend review used the
installed frontend-design skill (no frontendslide skill is available). No runtime
tests or platform/model research were performed. These are design findings, not
implementation approval or evidence that the current application meets targets.

### Required implementation decisions

1. Parallelism: driver uses process environment for run/deadline; use isolated
   lane processes, not threads sharing that environment. Existing active-run/Stop
   routing is single-run. Define group identity, Stop revision/fence before POST,
   lock ordering, global identity reservation, shared cooldown and explicit time/
   recovery authority. Do not rotate the active pointer to simulate concurrency.
2. New-template eligibility: compiler emits unreviewed scout_only proposals while
   selection expects reviewed immutable releases. Proposed run-local versioned
   exploration eligibility must freeze source/rule/compiler evidence without
   forging reviewed status or silently publishing global knowledge at Start.
3. Tree semantics: define the complete baseline/treatment routing truth table,
   including opposing signs, one-arm signals and ties. Compiler already orients
   expressions. Reverse candidates require their own measured identity, not a
   sign change applied to cached results. Supported conditions need real compiler
   operators; restricting to prose/proxies alone does not satisfy conditional
   experiment requirements and needs explicit scope approval if proposed.
4. Completion: freeze expected arm identities and necessary finite metrics. Pending,
   unknown POST, permanent failure, conflict and no-signal are distinct. Exhausted
   recovery is inconclusive/blocked, never fabricated no-signal or infinite wait.
5. Rollback: persist accepted incumbent identity and make subsequent scheduling
   consume it. Existing comparison traces alone do not implement rollback. Freeze
   acceptance policy, turnover bounds and numerical tolerance; retain all children.
   Define handling of a hard-pass child rejected by comparison separately from
   candidate eligibility, without discarding valid evidence.
6. Seed: introduce one versioned pure eligibility policy consumed by planning,
   Discovery/Repair and UI. Existing selection uses Sharpe ranking; explicitly
   define retained score gate, ordering/ties and strict new thresholds for opt-in
   runs only. No Seed must lead to the next legal research choice.
7. Repair: deterministic planner-kind/version produces the existing verified
   single-change plan contract; freeze action ordering, parameter bounds and
   exhaustion. Old runs retain AI receipts/planner, including historical flips.
8. Selection bias: log experiment families and every tested/reused candidate.
   Same-sample improvements are exploratory observations; preregistration and
   rollback do not establish causality or eliminate multiple-testing bias.

### Frontend and packaging findings

- SSE already exists. Its client lacks a runtime-error handler and monotonic
  snapshot ordering; an open broken stream can suppress polling and appear Live.
  Prefer versioned complete snapshots with timeout/error recovery. Cursor event
  replay is optional, not required infrastructure for this UI.
- Form POST still returns 303/standalone refused HTML. Replace normal actions with
  in-place command acknowledgment, durable identity and reconciliation. Separate
  pending, persisted Stop intent and confirmed submission fence.
- Current fragment replacement loses view state. Use stable node/row identities,
  incremental rendering and per-lane focus/selection/scroll preservation.
- Full required tree/Seed/Repair detail projections do not exist yet. Derive them
  from authoritative artifacts; UI selection is not execution state.
- Hot SSE already avoids cold knowledge traversal. Remaining work includes cold
  startup/Start traversal, full history reads, repeated timeline building and
  progress-row scans. Benchmark before optimization; no claim every SSE update
  traverses the knowledge vault.
- Existing desktop host is Python + Edge/Chrome app-mode. Validate a lightweight
  system-WebView/EXE packaging spike before choosing dependencies. Define packaged
  subprocess entry, roots, shutdown behavior and safe version mismatch handling.
  Closing a window must not silently erase Stop or kill unknown worker processes.

### Recommended smallest architecture, pending approval

Keep the Orchestrator and pair compiler. Add immutable tree attachments, pure
completion/routing/Seed predicates, deterministic Repair provider and a thin group
supervisor around isolated lane workers. Keep one authority for state/budget/checks.
Reuse SSE with versioned complete snapshots and a small in-place frontend; avoid
new event-replay infrastructure, another backend or a new Agent framework.

Before writing the implementation plan, close routing/acceptance/authority details
and perform an explicitly approved offline desktop packaging feasibility spike.
Measure p50/p95 for click feedback, durable command acknowledgment, event-to-view,
cached navigation and cold startup with fixed realistic history fixtures.
