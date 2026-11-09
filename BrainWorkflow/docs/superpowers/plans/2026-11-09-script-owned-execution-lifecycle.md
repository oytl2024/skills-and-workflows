# Script-Owned Execution Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task; every delegate uses explicit medium or lower.

**Goal:** Freeze self-contained script-owned research inputs, preserve existing execution semantics, and retire completed packages to useful scientific summaries.

**Architecture:** Add one focused execution-package module beside existing tree adapters. New frozen policy opts in; legacy reads remain unchanged. Scripts, never model output, own sealing, finite resource resolution and lifecycle transitions.

**Tech Stack:** Existing Python, unittest, JSON/hash contracts, lockfile, native Console; no new dependencies/framework.

**Spec:** `docs/superpowers/specs/2026-11-09-execution-package-retirement-design.md`.

## Global Constraints

- No WQB/model/research/Alpha effects. Preserve Stop/accounting/POST recovery/approval.
- Existing scientific rules, grids, simulation identities and Orchestrator core unchanged.
- Work in the existing dedicated maintenance checkout, per established in-place layout preference; installed app remains isolated until verified deployment. No duplicate worktree/vault.
- Source/permission integrity is checked at freeze. Runtime scientific reads use sealed local facts; mutable platform/check/account state remains independent.
- Do not delete sensitive profiles, active inputs or unique evidence without named authority.

## Review Focus

- A fabricated package file must not opt an old run into a weaker policy.
- Global knowledge removal/change after freeze must not affect tree/Seed/Repair decisions.
- Stop/pending POST/Repair must never be mistaken for terminal completion.
- Crash between summary, marker and deletion must remain interpretable and recoverable.
- Compact retired views must preserve expressions/check evidence and remain useful to Console/wiki readers.

## Task 1: Freeze And Local Read Contract

Owners: new `wqb/execution_package.py`; narrow interfaces in
`preplanned_start.py`, `initial_research_planning.py`, `research_tree.py`,
`exploration_eligibility.py`; `tests/test_execution_package.py`.

- [x] RED: reject unversioned/fabricated/stale owner packages; preserve old `_load` behavior.
- [x] Define producer-only policy/version, script-owned seal, exact source/manifest/context identities and bounded local payload references; no AI-controlled paths.
- [x] Freeze from already certified existing receipts, avoiding another full-vault copy.
- [x] RED/GREEN: authenticated local context still loads when global resource catalogs are renamed; corruption/identity/scope changes reject.
- [x] Review package creation/reader ownership before consumer integration.

Task1 review reproduced interrupted freeze, repeated freeze re-opening global
sources and boolean delay equality. Producer-only recovery and exact local
sealed replay are tested; operational readers still reject incomplete seals.

## Task 2: Existing Execution Consumers And AI Annotations

Owners: existing `initial_research_planning.py`, `initial_model_worker.py`,
`cli.py`, `run_readiness.py`, `repair_runtime.py` and frozen benchmark readers;
new package integration tests, existing preplanned acceptance fixtures.

- [x] Trace every post-freeze knowledge read; classify scientific input versus independent dynamic safety/check evidence.
- [x] Add a compatible strict annotation schema for new mode only: known field traits, explicit unknown/hypothesis labels and existing Repair resource IDs; scripts resolve facts and actionable rules.
- [x] Preserve the old `{summary, designs, tree}` worker path. Do not add model packaging or late model calls.
- [x] Route readiness/operational/baseline consumers through owner-validated local package context. No merely flag-based bypass.
- [x] RED/GREEN complete offline tree/Seed/Repair with global scientific catalogs unavailable, same outcomes/thresholds/grids; keep Stop/accounting/in-flight and shared dedup live.
- [x] Verify two lanes and old version replay. No CLI/UI research-start effects.

Scientific consumers: tree and hypothesis selection use sealed/in-memory context;
Seed uses owner-frozen benchmark rules; Repair uses frozen traits/resources/grids.
Child Repair triage previously fell back to the global benchmark: the narrow
owner adapter fixes this for new mode only. Stop/accounting/POST/check expiry,
candidate invalidation and shared identity history remain dynamic. New-mode
ordinary checkpoints are suppressed: only initial planning uses the model;
separately requested knowledge maintenance remains unchanged. Read-only archival
preparation/roundtrip and the completion hook are tested, but not yet deployed.

## Task 3: Completion Summary And Automatic Retirement

Owners: `execution_package.py`; narrow completion hook in `workflow_driver.py`
or owning group adapter; `research_retirement.py`, `console_api.py` and existing
record readers where necessary; `tests/test_execution_package_retirement.py`.

- [x] RED: Pause/cooldown/budgets/pending simulation/check/Repair cannot retire.
- [x] Define exact necessary summary and protected accounting/candidate/check fields; preserve learning and raw measured facts, not prose only.
- [x] Implement journaled summary -> retired receipt -> exact-path payload collection under existing worker/intent fences. Do not alter frozen original authority.
- [x] RED/GREEN retries/crashes/tampered summary/links/unexpected files; no repeated deletion/model/POST effects.
- [x] Add completion-event trigger only after derived work and recording are final; no cron/model polling.
- [x] Retired Console/history read from verified summaries; no Resume of completed payload, no layout rewrite.

Task3 offline evidence includes actual RepairRuntimeExecutor with mocked transport,
finite scheduler completion, qualified raw cache retained without refresh, partial
collection interruption/retry, durable Stop during archive preparation and retired
peer reservation/group-resource reads. Submission-only checks skipped because
cheap metrics failed are not required pending research work; they never qualify a
candidate. Full-suite/native release acceptance remains Task4, not inferred here.

## Task 4: Integrated Acceptance And Delivery

- [x] Offline acceptance compares original versus package-backed branch/Seed/Repair results; candidate cache does not repeat SELF/PROD after retirement.
- [x] Review full branch, close important findings, freeze source and run full offline suite.
- [x] Update canonical architecture/rules/handoff and operator docs with changed/unchanged boundaries.
- [ ] Build/test installed native application; Git sync before guarded collection/deployment; loaded-version check without Start.
- [ ] Integrate historical storage plan, report actual reclaimed bytes and protected exclusions; sync cleanup outcome.

Approved scope is the Nov9 user-confirmed design and script-owned clarification.
Task status/evidence and exact interrupted next command belong in root todo.md.

Release source proof:3315 offline tests PASS,9 skips,1174.850s; code/test digest
`151f6dcee493e3ac5d5bc19050d487ce031103f2ae4053d8a56f5eda52483285`
unchanged before/after. The earlier missing-policy legacy brief error was
reproduced and fixed by retaining the unmarked legacy path; targeted68 tests and
independent review passed. Native build `20261109-220044-3881` and isolated
GUI/backend/worker smoke passed, revision
`74d3265be46304e55b8ae6e7baaa821037e44f9600aea47b7a4aa609ce80a77f`.
Private proofs remain in desktop-validation; no platform/model/research calls.
Installation, new-only policy activation and actual collection remain pending.
