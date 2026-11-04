# Retire AI Repair Implementation Plan

**Goal:** Remove the legacy model-driven Repair execution path; preserve immutable historical evidence and deterministic Repair safety.

**Approval:** User approved retirement of old runs, with no further recovery execution. This is a scoped exception to old-run execution compatibility, not permission to delete research evidence or run the platform.

**Architecture:** Keep deterministic frozen search, simulation identity, Stop, daily accounting, cooldown and unknown-POST recovery. Move shared limits/receipt verification out of the AI planner. Retired mission entry points must fail locally before platform/model work; never silently upgrade old frozen authority.

**Tech stack:** Existing Python unittest and Console/service boundaries. No new framework.

- [x] Inventory callers, old-only modules/tests/config and current entry points; record exact deletion paths in the existing cleanup audit.
- [x] Add failing regressions for retired execution, historical evidence preservation, deterministic preparation/verification and no late model calls.
- [x] Isolate shared constants/verification, remove runtime AI fallback and project clear retirement state at execution boundaries.
- [x] Update project rules, architecture and operator docs; retain archives as historical evidence, not active instructions.
- [x] Run affected tests and full offline suite, review diff, commit/push without force and verify remote equality. Pre-cleanup audit/source backup was synchronized at f761152; final implementation at dad56a7.
- [x] Delete only audited old-only source/tests after sync; repair references and run affected/full regressions, then cleanup commit/push.

Do not delete raw knowledge, runs, model receipts, Alpha/check identities, secrets or uniquely referenced evidence. Do not renew old proofs, change budgets, resume missions, capture knowledge or submit Alphas. If Git sync fails, stop deletion and record the exact blocker.

Execution ruling: first synchronized the approved plan/precise deletion audit at f761152 (local and remote verified equal), preserving all deleted source in Git. Then removed the seven audited source/test files while final runtime implementation was uncommitted. Targeted checks preceded cleanup; stable full-suite proof and final cleanup commit/push were required before the acceptance below. The initial all-suite run overlapped final integration and is diagnostic only, not final acceptance.

## Acceptance (2026-11-04)

- Final source: `4651deb0e81f35998cb7e6f5e892059d95d2f73c8661afeda7a52b06b79f7870`, identical before/after 2,820-test full suite (zero failures/errors, five skips, 645.977s).
- Log: `output/desktop-validation/retire-ai-repair-final-full-suite-20261104.log`. Earlier 2,819-test run failed only the handoff size check; compacted root handoff and final run supersede it. Run cheap entry-doc tests after handoff edits before starting expensive verification.
- Isolated real Console and browser acceptance passed. New separately authorized preplanned Start beside retired history publishes only new paused group authority; history remains unchanged and newer Stop/pointer changes cancel preparation. Retired startup proof notices are suppressed, not replayed.
- Implementation dad56a70f70e06b5d0b7596dec1f04a38d5fa582 was pushed and local/remote equality verified. This completion audit is a documentation-only follow-up; its final sync belongs in outer todo.md.
- Post-cleanup architecture/entry-doc regression: 24 tests passed in 0.175s; source digest remains the frozen value above. No additional deletion targets were selected.
- No platform/model/research/budget/proof/submit authority was exercised. Formal EXE deployment and real semantic readiness remain outside this completed retirement scope.
