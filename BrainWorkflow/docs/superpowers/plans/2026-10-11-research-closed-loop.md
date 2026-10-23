# Research Closed Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task with test-driven development.

**Goal:** Make Orchestrator implement the confirmed bounded iterative research architecture rather than treating batch exhaustion as mission completion.

**Architecture:** Orchestrator owns durable rounds. Existing source runners, benchmark, Repair and runtime authority remain separate services; no parallel controller or implicit permission expansion.

**Tech Stack:** Existing Python, unittest, JSON/JSONL state and desktop Console.

**Spec:** ../specs/2026-10-11-research-closed-loop-design.md

## Global Constraints

- Preserve dirty work, real evidence, user Pause and separate final submission authorization.
- Scout/Discovery30; Seed/Repair bounded small batches; multisim request sizing separate.
- New research requires persisted mission authority; original-only recovery cannot mint it.
- Subagents, if used, explicit reasoning effort medium or lower.
- No new live batch during implementation/test preparation.

## Review Focus

- Missing/pending checks are not evidence of a weak signal.
- Crash between round creation and source binding must not produce duplicate simulation.
- Paused intent must survive migration/restart and delayed callbacks.
- Changing hypotheses must stay within the selected objective and authorized budget.
- Console completion must distinguish source completion from mission completion.

## Task 1: Reconcile classification

- [x] Inspect stage_outcomes.py, benchmark.py, source checker records and actual pending reasons for29checked/28pending_review.
- [x] Add failing tests for legacy/modern evidence and genuinely unresolved checks; confirm RED.
- [x] Implement evidence-preserving normalization/reconciliation without inventing checks; confirm GREEN.

## Task 2: Durable round transitions

- [x] Inspect orchestrator.py, workflow_stage_adapters.py and persisted run-state contracts.
- [x] Add RED tests: weak->newScout30; Repair exhausted->new round; qualified->candidate gate; unresolved->reconcile.
- [x] Implement Orchestrator-owned round identity, source linkage and idempotent transitions using existing locks/atomic state patterns. Preserve each round's evidence; GREEN tests.

## Task 3: Candidate planning and execution wiring

- [x] Inspect source_bridge.py, workflow_auto_continue.py and knowledge-first candidate generation interfaces.
- [x] RED/GREEN tests for fresh/deduplicated30, snapshot provenance, unavailable AI/planner output, persisted settings and restart. Real read-only structured Codex probe succeeded without WQB.
- [x] Wire validated planning outputs to source execution; scheduled skeletons and bounded AI decay choices are consumed. Planner failures persist a blocker. No arbitrary AI template innovation claimed.

## Task 4: Runtime migration and Console

- [x] RED tests for original_batch_recovery.py completion handoff, cli.py/runtime authority, Console projection and bounded budgets.
- [x] Preserve legacy original-only receipt; expose explicit mission-authority need without default budget or erasing historical use.
- [x] Update Console/driver integration so authorized subsequent rounds need no extra routine clicks; maintain stale-version protection and Pause.

## Task 5: Acceptance and handoff

- [x] Whole-path fake-platform multiple-round Discovery/Repair/approval/restart acceptance plus focused rate-limit, unknown POST, Pause and quota tests. Horizon-free exhausted variants proceed to measured-seed Repair, not repeated construction.
- [x] Independent medium review: partial check losing PROD pending and settings GET bypassing retry lease reproduced RED/fixed GREEN; narrow re-review found no remaining issue in those fixes. This does not cover undelivered planning/deployment work.
- [x] Update milestone.md, todo.md and operator manual with exact ownership and stop conditions.
- [x] Fresh full1215 tests/86.823s, architecture/entry22, compileall/diff check; deployed source digest401547d2 matches health; browser shows Live29 strategies and new Option Card Start.
- [x] Code verified and Console deployed. No new live research authority/execution, Alpha submission, commit or push. Original29/29 completed scope remains preserved; global7stale knowledge facts not relabeled fresh.

## Delivery boundaries (2026-10-11)

- Source generation consumes the selected skeleton, field/operator provenance and validated bounded AI holding-decay decision. Seed comes from measured Scout evidence; arbitrary template invention and rule changes remain proposal-based.
- Independent medium review found recovery-settings drift, insufficient five-day variants, partial plan publication and stale recovered blockers. Regression coverage and durable fixes added for each; no platform checks fabricated.
- Current legacy original-only receipt permits no new exploration. Its completed29 identities expose NEW Option Card Start; never erase old scope or infer new budget. Final fresh regression/deployed revision/browser evidence belongs in root todo.md.
