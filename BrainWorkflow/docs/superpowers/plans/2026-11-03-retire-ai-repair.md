# Retire AI Repair Implementation Plan

**Goal:** Remove the legacy model-driven Repair execution path; preserve immutable historical evidence and deterministic Repair safety.

**Approval:** User approved retirement of old runs, with no further recovery execution. This is a scoped exception to old-run execution compatibility, not permission to delete research evidence or run the platform.

**Architecture:** Keep deterministic frozen search, simulation identity, Stop, daily accounting, cooldown and unknown-POST recovery. Move shared limits/receipt verification out of the AI planner. Retired mission entry points must fail locally before platform/model work; never silently upgrade old frozen authority.

**Tech stack:** Existing Python unittest and Console/service boundaries. No new framework.

- [ ] Inventory callers, old-only modules/tests/config and current entry points; record exact deletion paths in the existing cleanup audit.
- [ ] Add failing regressions for retired execution, historical evidence preservation, deterministic preparation/verification and no late model calls.
- [ ] Isolate shared constants/verification, remove runtime AI fallback and project clear retirement state at execution boundaries.
- [ ] Update project rules, architecture and operator docs; retain archives as historical evidence, not active instructions.
- [ ] Run affected tests and full offline suite, review diff, commit/push without force and verify remote equality before permanent cleanup.
- [ ] Delete only audited old-only source/tests after sync; repair references and run affected/full regressions, then cleanup commit/push.

Do not delete raw knowledge, runs, model receipts, Alpha/check identities, secrets or uniquely referenced evidence. Do not renew old proofs, change budgets, resume missions, capture knowledge or submit Alphas. If Git sync fails, stop deletion and record the exact blocker.
