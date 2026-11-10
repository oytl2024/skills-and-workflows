# Goal Preparation And Knowledge Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans or superpowers:subagent-driven-development. Explicit reasoning_effort medium or lower for every delegate.

**Goal:** Select any goal and Start; run bounded prerequisite preparation before research, with durable Stop/progress and no silent objective substitution.

**Architecture:** Extend the existing Console Start intent/job before its preplanned handoff. Separate pure goal/activity interpretation from source acquisition/compilation and Start authority. Freeze resolved goal context into the existing selected-option snapshot and initial model brief; no new agent framework or Orchestrator rewrite.

**Tech Stack:** Existing Python/requests/JSON/locks, current raw/source index and compilation, React/TypeScript, unittest/Vitest, current WebView2 packaging.

**Spec:** `docs/superpowers/specs/2026-11-10-goal-preparation-and-knowledge-refresh-design.md` (approved).

## Global Constraints

- Implementation/acceptance offline. Separately authorized actual investigation used12read calls plus necessary authentication; allowance exhausted. Evidence remains private in `runs/knowledge_maintenance/goal-contract-audit-20261110`.
- Browser grant: <=3 official support pages, no cookie/token export. Tool could not bind even the user-restored window, so0pages read; record external dependency, never pretend article contents were verified.
- Preserve old frozen runs/Stop/POST/accounting/model and simulation limits/final-submit permission. No implicit model enrichment or actual research activation during maintenance.
- New mode explicitly opt-in for new Start only. Partial/failed capture never renews unrelated sources or proves absence of unseen activities.
- Central preparation defaults:24resource attempts,300seconds total,12seconds per request,0hidden HTTP retries,100fields per selected scope,1scope per Start. Authentication uses the existing client and is logged separately. Expose configuration centrally and a maintenance `.sh` entry for shared knobs; never embed credentials.

## Review Focus

- Provisional configured scope must not be mistaken for activity compatibility; handoff only uses resolved facts within explicit scope authority.
- Stop between reads, compile and handoff must prevent subsequent effects and preserve evidence.
- Current competitions list uses boolean submissions=false; ACCEPTED alone is not submission feasibility. Never auto-sign-up or auto-submit.
- Current Power Pool choices are value/label only. Theme-specific constraints live in authenticated official support, not in leaderboard metrics or a regex label alone.
- /themes and /alphas/themes returned404; do not ship guessed endpoints or interpret webinar events as complete Theme coverage.

## Task1: Pure Goal Contracts And Historical Evidence

Files: new `wqb/goal_contracts.py`, `tests/test_goal_contracts.py`.

- [ ] RED source-shaped fixtures: Power Pool OPTIONS choices, typed theme facts, competition dates/status/boolean submissions, malformed and partial metadata.
- [ ] Implement `resolve_goal(option, scope, payloads, now)` returning ready/unavailable/blocked with reason_code, activity identity, exact scope, source selectors, constraints and unknowns. No I/O.
- [ ] Keep time-aware comparisons, explicit selected activity IDs, deterministic ranking and candidate constraints. No readiness from an activity name alone.
- [ ] Validate compact source-bound goal contexts and compiled-expression requirements using existing AST/complexity helpers; distinguish official facts from project limits.
- [ ] GREEN targeted tests; review contracts before integration.

## Task2: Bounded Source Update And Local Compile

Files: new `wqb/goal_resources.py`, `tests/test_goal_resources.py`; existing raw writers/index/compiler interfaces; `scripts/prepare-goal.sh` for shared configurable bounds.

- [ ] RED transport allowlist/count/deadline, exact method ownership, retries/429, provenance, cache reuse, failed/partial facts and cancellation fixtures.
- [ ] Persist capture attempt/checkpoint receipts below `runs/start_preflight/goal_preparation/<request_id>/` before requests. Sources go to canonical raw with indexed date/body hash and private exact payload receipts. No credentials or response auth headers recorded.
- [ ] `acquire_goal_sources(paths, request, *, check_cancelled, progress, client=None)` returns typed payloads and source refs; use only verified API paths, goal-specific required sources and valid local official evidence. Unsupported authenticated support transport is an explicit connection prerequisite, never credential reuse across hosts.
- [ ] `compile_goal_resources(paths, request, scope, *, check_cancelled, progress, client=None)` refreshes only missing/stale exact resources within bounds and calls existing data/operator/knowledge compilation. No model calls or global semantic release replacement by inference.
- [ ] Persist replayable completed steps; claimed/uncertain network or publication effects cannot be blindly repeated. Respect Stop between phases and source writer locks.

## Task3: Start Integration And Frozen Goal Context

Files: `console_start.py`, `console_server.py`, `console_api.py`, `group_preparation.py`, `initial_research_planning.py`, `initial_model_worker.py`; matching existing tests.

- [ ] RED all actual planner card shapes -> native command -> durable prep -> resolver -> compile -> exact preplanned handoff (mock transport/model only).
- [ ] Add `goal_preparation_version=1` and validated preparation config; preserve absent-marker legacy semantics. Existing Start owns original selection/intent; resolved selection/config is separately persisted without breaking request idempotence.
- [ ] All selected goals are dispatchable in the new mode; provisional scope is explicitly labeled. Persist original Start before network; no jobless synchronous capture.
- [ ] Execute new prep before existing preplanned coordinator, checking Start/Stop CAS at each boundary. Preserve requested identity and separately freeze resolved option/scope/source evidence.
- [ ] Add optional versioned `research_goal` brief from the frozen selected option; authenticate the same projection and enforce finite constraints before freezing expressions. No late AI or model-budget increase.
- [ ] Handle unavailable as an explicit outcome without research, and unsupported/connection/code gaps via existing deduplicated outbox. No empty success and no repeated source attempts after exhausted authority.

## Task4: Console Progress And Standalone Maintenance

Files: existing console state/timeline/API and frontend types/App/components/tests; operator docs and root rules/architecture/handoff.

- [ ] Show checking/acquiring/compiling/eligibility/binding/planning stages, bounded counts and precise outcome. Preserve layout/Start/Stop and live feedback; remove disabled-card workaround only after backend path works.
- [ ] Resume Stop-interrupted preparation from persisted completed work within original limits. Never require a new option for existing frozen research.
- [ ] Document research-record compile versus platform refresh commands. A standalone update never starts research; all-platform capture remains explicit stratified maintenance, not Start behavior.
- [ ] Rewrite approved rule boundary consistently; no stale "all Start preparation is local-only" entry text remains authoritative for new mode.

## Task5: End-To-End Acceptance And Delivery

- [ ] Whole-branch review; no P1/P2; isolated HTTP/browser tests for all modes and Stop/cooldown/restart.
- [ ] Freeze intended source and complete offline suite; frontend typecheck/test/build; source-bound native smoke/install and loaded version checks without Start.
- [ ] Git sync before audited cleanup; keep private knowledge/runs/binaries off Git, preserve verified rollback and necessary evidence.
- [ ] Report which actual goals are demonstrably eligible versus blocked by real current platform facts/connection. Do not call all goals runnable from synthetic fixtures alone.

## Investigation Findings To Preserve

Current read observations: three Power Pool choices including a Nov26 GLB/D1
board; official general rules require active-theme scope/conditions and <=8 total
operators/<=3non-group fields. Competitions list includes currently active AQP
with submissions=false and expired Python competition. Official support article
37443810800535 is linked by the platform but unauthenticated access returns401.
Those are dated observations, not permanent rules or proof that future activities
are unavailable. Implementation must use fetched/cached facts, never these IDs
as hard-coded operational choices.
