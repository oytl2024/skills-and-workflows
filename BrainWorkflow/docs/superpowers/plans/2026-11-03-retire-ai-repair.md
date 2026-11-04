# Retire AI Repair Implementation Plan

**Goal:** Remove the legacy model-driven Repair execution path; preserve immutable historical evidence and deterministic Repair safety.

**Approval:** User approved retirement of old runs, with no further recovery execution. This is a scoped exception to old-run execution compatibility, not permission to delete research evidence or run the platform.

**Architecture:** Keep deterministic frozen search, simulation identity, Stop, daily accounting, cooldown and unknown-POST recovery. Move shared limits/receipt verification out of the AI planner. Retired mission entry points must fail locally before platform/model work; never silently upgrade old frozen authority.

**Tech stack:** Existing Python unittest and Console/service boundaries. No new framework.

- [x] Inventory callers, old-only modules/tests/config and current entry points; record exact deletion paths in the existing cleanup audit.
- [x] Add failing regressions for retired execution, historical evidence preservation, deterministic preparation/verification and no late model calls.
- [x] Isolate shared constants/verification, remove runtime AI fallback and project clear retirement state at execution boundaries.
- [x] Update project rules, architecture and operator docs; retain archives as historical evidence, not active instructions.
- [ ] Run affected tests and full offline suite, review diff, commit/push without force and verify remote equality before permanent cleanup.
- [ ] Delete only audited old-only source/tests after sync; repair references and run affected/full regressions, then cleanup commit/push.

Do not delete raw knowledge, runs, model receipts, Alpha/check identities, secrets or uniquely referenced evidence. Do not renew old proofs, change budgets, resume missions, capture knowledge or submit Alphas. If Git sync fails, stop deletion and record the exact blocker.

Execution ruling: first synchronized the approved plan/precise deletion audit at f761152 (local and remote verified equal), preserving all deleted source in Git. Then removed the seven audited source/test files while final runtime implementation was uncommitted. Targeted checks preceded cleanup; a stable full-suite proof and final cleanup commit/push remain required. The initial all-suite run overlaps final integration and is diagnostic only, not final acceptance.
