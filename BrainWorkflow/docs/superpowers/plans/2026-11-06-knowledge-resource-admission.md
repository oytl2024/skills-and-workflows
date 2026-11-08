# Knowledge Resource Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task by task. Preserve isolated test fixtures and explicitly medium-or-lower delegated reasoning.

**Goal:** Remove semantic-completeness admission restrictions without weakening technical expression/tree validation or changing Repair search.

**Architecture:** Reuse canonical catalogs as research input and semantic publication as optional enrichment. Carry an explicit admission-policy marker through the existing frozen resource context; keep old-context validation unchanged. Separate technical compatibility from economic-evidence confidence at the existing binder/Repair boundaries.

**Tech Stack:** Existing Python, JSON/JSONL/SQLite readers, AST binder, unittest and native React/WebView2 application. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-06-knowledge-resource-admission-design.md`.

## Global Constraints

- No WQB, platform capture, research-model jobs, research resume or Alpha submit.
- Preserve Stop, frozen authority, daily/runtime/recovery budgets and exact identities.
- Do not invent metadata, typed signatures, source dates or completed checks.
- Do not change tree standards, Seed thresholds or Repair mappings/grids.
- Keep old frozen contexts strict; new admission policy must be explicit.
- Canonical rules/architecture/handoff remain at the outer workspace root only.

## Task 1: Catalog-First Input And Admission Contract

Files: `wqb/preplanned_start.py`, existing catalog readers and
`tests/test_preplanned_start.py`. If extraction is needed to avoid enlarging the
Start module, use one focused `wqb/research_resource_catalog.py` with corresponding
tests, not another persistent catalog.

- [x] Write RED tests for raw/catalog resources absent from published semantics;
  missing explanatory/timing/grain notes must not remove them from the AI input.
- [x] Cover scope/identity conflicts, bounded lanes and optional enrichment;
  unreadable/corrupt entries are diagnosed, never fabricated.
- [x] Implement canonical catalog selection and explicit warnings/unknowns;
  preserve actual dates and configured age policy.
- [x] Define one admission-policy marker and propagate it in existing resources,
  brief and frozen context. Update `_resources` schema only as needed.
- [x] Run focused tests; review catalog visibility and prove no source/model calls.

## Task 2: Binder And Tree Integration

Files: `wqb/template_binding.py`, `wqb/hypothesis_template_compiler.py`,
`wqb/hypothesis_design.py`, `wqb/exploration_eligibility.py`,
`wqb/initial_research_planning.py`, related existing tests.

- [x] Trace the marker through current compiler, Schema and receipt reconstruction;
  identify economic-proof checks separately from technical checks before editing.
- [x] Write RED tests for valid syntax/type/tree using incomplete semantic metadata
  under the new policy, and unchanged strict replay without the marker.
- [x] Keep parameter/arity/type and VECTOR reduction checks; reuse technical
  definitions without mandatory semantic publication/basis certification.
- [x] Keep missing technical definition diagnostic explicit and per combination;
  do not fabricate a contract or exclude the resource from the AI catalog.
- [x] Assert invalid AST, mismatched known types, invalid branch/routing/rollback,
  stale identities and authority violations still fail the owning checks.
- [x] Run binder, hypothesis, exploration and initial-planning tests offline.

## Task 3: Repair And Readiness Consumers

Files: `wqb/repair_search.py`, `wqb/repair_rulebook.py`,
`wqb/preplanned_start.py`, relevant Start/readiness consumers and existing tests.

- [x] Write RED tests that semantic-publication absence does not block a technical
  supported Repair transform in a new-policy context.
- [x] Preserve exact metric triggers, rule selection, parameter grids, one-factor
  change, acceptance/rollback and accounting; unknown traits do not trigger rules.
- [x] Remove repeated semantic admission checks in consumers, not technical rules.
  Ensure general Start readiness cannot silently restore the old whitelist.
- [x] Test normal no-legal-action/exhaustion handling versus genuine invalid output;
  no maintenance notification solely for incomplete economic metadata.
- [x] Test old snapshots/retired missions and Stop/budget/submit boundaries unchanged.

## Task 4: Acceptance, Rules And Native Delivery

### Nov8 Deployment Ruling: Measured Window Adapter

User approved the new entry and a four-GET investigation plus up to four PNL
polls. Six GETs total captured two real Alpha details and PNL sets: IS start
2014-01-01, PNL trading dates 2014-01-02 through 2023-12-29. Details lack endDate;
one submitted Alpha explicitly starts OS on 2024-01-01. Local config lacks a
comparison period. Evidence is private runs/knowledge_maintenance/default-test-window*
and must not be uploaded or treated as proof for every future Alpha.

- [x] Add one bounded result-window adapter: actual Alpha IS start plus that
  same Alpha's PNL dates, excluding explicit OS dates, identity-bound evidence.
  Keep original metrics unchanged; never manufacture a reported endDate.
- [x] Invoke only for new preplanned results with missing date evidence; complete
  reported dates and old workflows make no extra PNL requests. Bound retries,
  use existing Stop/network/account cooldown handling, retain raw/source evidence
  and reuse valid cached evidence. No fresh simulation or correlation request.
- [x] Normalize verified result-period evidence for the existing date comparison;
  keep tree/Seed thresholds, comparable-period requirement and rollback unchanged.
  Missing/conflicting evidence remains recoverable/explicit, not no-signal.
- [x] Configure only NEW research with the observed local comparison period after
  acceptance, retaining its provenance; future results must independently match.
  Existing frozen contexts/requests, quotas and Stop stay unchanged. This is a
  result-input adapter and configuration closure, not a relaxation of Seed rules.

Nov8 adapter identity ruling: authenticated Alpha settings contain additional
platform defaults (maxTrade/maxPosition, configured dates, simulationMode).
Preserve those full reported settings and their own digest in the window receipt.
Validate every submitted setting with exact JSON type/value against the returned
setting and require the same expression/Alpha ID. Validate the row identity
against the original submitted settings, never rewrite it to the response hash.
Extra reported defaults are evidence, not a budget, expression or permission
change. Conflicting submitted settings remain invalid. Observation end dates
come from PNL, not the response's requested settings.endDate.

- [x] Add integrated fake-model/fake-platform coverage from catalog input through
  valid tree freeze, scripted branch selection, Seed and deterministic Repair.
- [x] Read-only local real-vault report: visible catalogs, technical definitions,
  supported examples and warnings; never label visibility as universal compatibility.
- [x] Update root AGENTS/milestone/todo and operator docs; explicitly supersede the
  semantic-admission rules while retaining the technical/safety contracts.
- [x] Independent review at medium or lower; close findings with regressions.
- [x] Freeze source, full offline tests and digest, frontend checks, native build
  and isolated window/backend/root-context tests. No code edits during full suite.
- [x] Commit/push and verify remote equality; audited installed replacement,
  affected regressions, loaded-version proof and cleanup-outcome sync.
- [x] Preserve protected knowledge/research/recovery evidence; report unrelated
  inventory-reference retirement gap separately, never silently delete originals.

Nov8 source-freeze evidence: catalog N2 real-driver/Stop acceptance passed with
fake transports only; frontend 15 tests, type check and production build passed.
Canonical extracted fields now retain their ledger paths. A shared pure evidence
resolver is used by compiler, Repair and the default rulebook; Start still checks
the existing immutable extract receipt against the original. Authentic-extract
compiler and five Repair regressions pass; 92 related tests pass. No changed
rule grids, original identities, model/WQB calls or research resume follow.

Implementation approved Nov6. Full offline acceptance and delivery remain open;
the first 3145-test run found one legacy selected-scope default KeyError. It was
fixed by reusing DEFAULT_CONFIG, not changing frozen scope. A second RED/GREEN
case aligns complete JSON technical signatures with Markdown when economic
description is absent: add an explicit unknown note, never infer missing types
or change partial definitions. All 177 related tests pass. The replacement full
proof is `console-delivery-verified-full-suite-20261108-admission-reviewed`;
the failed initial proof is retained and may not authorize deployment.
Reviewed full proof: 3146 tests in 894.073 seconds, OK with 9 skips;
source/test digest unchanged at
`70f921598af63ccd77a7cbe1949daaeed7b4f0222b5ce8a63c784fd51a1a6be6`.
Build `20261108-223912-0783` passed isolated native/backend/asset/context smoke;
loaded revision `78ecda0780c0e220984c218707eda74b530e3c14ecd0cd0cb1260d48c6d358db`.
Actual read-only catalog report verifies two 30-field views and 104 visible
operators, with one typed enrichment (`ts_delta`); visibility is not universal
technical compatibility. Raw/ledger hashes were unchanged. Windows subprocess
decode warnings remain in the log but caused no test failure; they are not
silently claimed repaired by this admission change.
their exact handoff is in root todo.md. Do not replace the deployed app or renew
proof before integrated acceptance and verified Git synchronization.

Nov8 delivery accepted: implementation `a7667eb305e70d0fc1ef154e081308cef3af53d0`
was pushed and remote equality verified before replacing the 358-file app.
Root click entry loads revision `78ecda0780c0e220984c218707eda74b530e3c14ecd0cd0cb1260d48c6d358db`;
mission-state hashes unchanged, no Start pressed. New local configuration changes
only the preplanned version flag and observed comparison period, not old mission
authority or limits. Read-only snapshot: Start/Stop enabled, four options, no
blocker; the old mission is retired. Post-install 98 regressions pass. No files
were deleted: both new modules are required; historical/source/research evidence
remains protected. The independent old-inventory retirement remains open, not a
claim of completed storage collection. This audit outcome is separately synced.
