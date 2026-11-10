# Manual Multiplier Scope Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans or subagent-driven-development; every delegate explicitly medium or lower.

**Goal:** User selects Multiplier, region/delay and, only when necessary, universe; Start prepares missing exact-scope fields then runs the existing preplanned research.

**Architecture:** Reuse Console Start intent, Stop/CAS, async job, preplanned coordinator and bounded field-capture/compiler. Keep manual activity judgment separate from technical scope and resource checks. Do not implement guessed Theme endpoints or browser sessions.

**Tech Stack:** Existing Python/client/raw/index/compilers, React/TypeScript/unittest/Vitest and current native packaging.

**Spec:** user-approved amendment below to `2026-11-10-goal-preparation-and-knowledge-refresh-design.md`.

## Approved Design And Change Map

User controls Region/Delay; configured universe is reused only if allowed for that
pair, otherwise a dropdown is required. Choices derive from cached official
simulation metadata, independent of whether fields have already been captured.
Start carries the exact selection and version-bound acquisition authority. Local
valid fields are reused; missing/stale fields trigger one bounded exact-scope
capture and compile. Activity eligibility is explicitly user-assessed, not proved
by the software. No maintenance-session live calls or research starts.

| Owner | Input -> output | Change |
| --- | --- | --- |
| scope metadata | certified settings OPTIONS -> valid region/delay/universe choices | compact reconstructable local catalog; provenance/age remain explicit |
| Console/API | card+user selection -> versioned exact Start form | schema/CAS validation; ordinary cards/Resume unchanged |
| field preparation | scope+frozen bounds -> local-resource receipt | scripted conditional acquisition/compile; Stop and finite network limits |
| frontend | option+catalog -> selects/feedback | Region/Delay controls for Multiplier only; no free-form scope entry |
| experiment/Seed/Repair | frozen plan -> results | unchanged |
| accounting/submit | original limits -> permissions | unchanged |

## Task1: Exact Scope Catalog And Command Contract

- [x] RED tests actual nested choices shape, scope with no local fields, invalid universe fallback, strict types, stale metadata and conflicting command scope.
- [x] Add focused `multiplier_scope.py` parser/reader using original indexed raw and a compact reconstructable catalog; never hard-code allowed universes or label regexes as official settings.
- [x] Add optional `selected_scope` to native command schema ONLY for new Multiplier Start; bind choices/policy to request revision. Existing Resume cannot consume a new selection or broaden authority.
- [x] Freeze `multiplier_scope_version=1` at new registration. Preserve absent-marker compatibility.

## Task2: Conditional Field Preparation

- [x] RED ready-local/no transport; absent/stale fields -> exact bounded capture; provenance/compiler errors; budget/deadline/429; Stop before/after capture and compile.
- [x] New focused `multiplier_preparation.py`: defaults24actual transport attempts,300s acquisition total,12s inactivity timeout,100fields,2datasets/50fields each,0hidden retries. Store attempt/progress receipts under existing Start preparation area, no secrets.
- [x] Use existing data capture, source index, data compilation and knowledge maintenance. No semantic-model job, fabricated source dates or overwritten old-run inputs.
- [x] Integrate before initial planning, without modifying selected identity on replay. Preserve cancelled intent and reject late handoff. Expose centrally configurable bounds and a `.sh` maintenance entry, not routine CLI usage.

## Task3: Frontend And Durable Progress

- [x] TDD Region/Delay dropdowns, valid configured Universe reuse, explicit Universe fallback, selection reset and no duplicate POST.
- [x] Show preparation stage/count/failure while retaining original Start/Stop; never require internal stage clicks.
- [x] Clearly label manual multiplier judgment; no claims that an Alpha qualifies for a theme merely because scope was selected.

## Task4: Integrated Verification And Delivery

- [x] Native HTTP -> actual saved card -> selection -> local preparation -> fake initial-model/coordinator test; no real requests.
- [ ] Independent review and full offline suite after frozen source; frontend/browser desktop/mobile and native packaged smoke.
- [ ] Commit/push before audited installation/ordinary cleanup, loaded-version check without Start; private knowledge/runs/config/binaries excluded.
- [x] Record remaining PowerPool/Competition activity adapters separately; do not call those complete from this narrowed iteration.

## Implementation Checkpoint

Scope/selection, optional native command payload, Start CAS/Stop integration,
preparation receipts and React controls are implemented, not deployed. Offline:
68 initial combined backend tests passed; 145 related regressions passed (one
skip); frontend27 and TypeScript passed. Later missing-selection and partial-saved-
scope regressions were observed failing before fixes. Dataset pagination now
receives the sampling bound for isolated preparations instead of fetching1000
datasets before slicing; its regression was also observed failing first.
Latest preparation/scope/Start/capture/entry group:89 passed.

Independent review identified inactivity-only transport timeout and forced-kill
publication risk. The new multiplier_supervision worker uses OwnedExecutionTree,
an attachment-before-admission permit and persistent wall/monotonic deadlines.
The child can only acquire isolated raw evidence; settings/source-index publication
and ledger compilation run in the parent with no transport client. Stop prevents
the next phase/handoff; an already-started local publication can finish safely.
Thus300seconds bounds acquisition, not an interruptible multi-file compile. The
standalone maintenance shell uses this same owner. Final review/release remains
pending; do not enable the flag or claim installation from source-only tests.

Evidence:7 process supervision tests (including real offline child/replay),138
combined backend tests before the publication split,68 after the split; frontend27,
TypeScript and production build pass. Isolated browser1440/390 passes configured
Universe reuse, fallback selection, incomplete-selection disabled Start and exact
intercepted command payload; screenshots inspected, no overflow/page errors.
No platform/model/research/submit calls. PowerPool/Competition adapters remain
explicitly outside this narrowed release.

The original full3391 run failed only an existing semantic-cancellation Windows
sharing race (9skips,1335.907s), with unchanged source f63d2972. This is not waived:
console_jobs now retries only transient PermissionError while retaining the
publication guard, and persistent unreadability still fails closed. Two injected
regressions,93 related tests and20 repetitions of the original concurrency case
pass; independent medium review found no issue. Fresh full source b313f953 and
build155619-1023 supersede the candidate153106, whose failed proof remains local.
