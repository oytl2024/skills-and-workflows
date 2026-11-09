# Historical Storage Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans; explicit medium-or-lower delegates. No real deletion by subagents.

**Goal:** Finish verified old-inventory/recovery-copy retirement and prevent unbounded artifact accumulation without losing scientific/authority evidence.

**Architecture:** Reuse the inventory archive and derivative lifecycle instead of bypassing their guards. Add explicit maintenance integration and bounded read/restore bridges where actual consumers require them. Separate historical documentary references from active execution dependencies.

**Tech Stack:** Existing Python gzip/JSON/hash/locks, native literal-path cleanup, unittest; no new dependencies/storage authority.

**Spec:** `docs/superpowers/specs/2026-11-09-execution-package-retirement-design.md`.

## Constraints And Review Focus

- No models/platform/research/submit or authority/freshness migration.
- Keep source facts, unique history, Stop, budget/POST/candidate identities and separate sensitive deletion approval.
- Classifying a link as documentary must not discard an actual worker or historical reader.
- Interrupted archive/publication/removal must be recoverable; hashes/bytes/paths remain bound.
- New current inventories and active/paused unresolved work stay protected; never age-sweep `runs`.
- Tests use temporary fixtures and no actual vault mutation. Real audit/collection is a later explicit bounded step after Git equality.

## Task 1: Legacy Inventory Consumer Closure

Owners: existing `knowledge_derivative_lifecycle.py`, `semantic_inventory_archive.py`,
`full_semantic_execution.py`/coverage readers only where archive fallback is needed;
tests for archive/read/retire contracts. Central CLI/maintenance wiring belongs to main.

- [ ] Reproduce the actual three legacy plans' audit barriers in bounded offline fixtures. Inventory actual consumer paths; do not label generic audit-only reasons as proven live dependencies.
- [ ] Distinguish verified historical/read-only plans from active tasks and retain original plan/job/accounting bytes.
- [ ] Reuse lossless archive support and authenticated retired read bridge; classify references by their declared role, not a substring match alone.
- [ ] RED/GREEN replacement/archival coverage, active worker refusal, altered raw/job/archive detection, concurrency/crash/idempotent recovery.
- [ ] Expose plan/audit/collect through explicit maintenance API; script-bound exact path approval remains mandatory.

## Task 2: Run-Local Recovery Copy Lifecycle

Owners: `knowledge_recovery.py`; one focused archive/restore helper only if needed;
tests for existing recovery receipt compatibility and retired/no-writer handling.

- [x] Identify readers of the two old recovery trees and their immutable receipts; determine terminal/read-only versus unresolved ownership.
- [x] Preserve necessary recovery identities and original facts in verified historical storage; existing consumers must read/restore exact bytes where required, never silently substitute current knowledge.
- [x] RED/GREEN no active/in-flight collection, interrupted restore, timestamps/scope/hash parity, no source freshness renewal or budget reset.
- [x] Plan exact historical collection; do not delete an unresolved paused run or shared unique raw evidence.

Recovery implementation: `knowledge_recovery_retirement.py` archives exact closed
original-batch copies and provides read-only/history restore bridges. Reference
projection validates the owning schemas before distinguishing routing identities
from actual input paths; original bytes stay hashed. Chronological POST/checks,
legacy pending receipts and sibling archives are covered. Actual two-copy audits
passed with 184 files per copy. Archive preparation is bounded separately at600s;
read-only operations retain180s. Full-source/native/Git acceptance and actual
collection remain Task4, not implied by these completed implementation items.

## Task 3: Artifact Retention Integration

Owners: existing build/maintenance completion interfaces and a focused lifecycle helper if required; no new scheduler/agent.

- [ ] Define current/installed/verified-rollback plus compact proof/source retention, with visible byte estimates and refusal reasons.
- [ ] Reuse Batch A's containment/hashes/metadata preservation approach; never sweep profile/session files.
- [ ] Integrate approved collection after successful publication/build verification, not on every arbitrary status GET.
- [ ] Enumerate precise browser/cache/profile paths for separate human deletion approval; continue independent safe work while waiting.

## Task 4: Actual Migration And Guarded Collection

- [ ] Offline tests/review and immutable source proof; commit/push and verify local/remote equality.
- [ ] Audit actual vault and run owners, freeze exact path/digest manifests, retain lossless necessary evidence.
- [ ] Apply only proven safe ordinary-file candidates. Sensitive candidates require named approval; unresolved owners remain explicit blockers.
- [ ] Verify sources/authority/app/next legal action, report actual reclaimed and residual bytes, sync outcome and update root handoff.

Historical cleanup and execution-package implementation can progress independently;
do not conflate deleting a large file with removing runtime knowledge dependency.
