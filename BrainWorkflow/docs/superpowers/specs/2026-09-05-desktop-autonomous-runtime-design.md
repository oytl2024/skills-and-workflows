# Desktop Autonomous Runtime Design

Approved intent: user confirmed the 2026-09-05 review recommendations and requested Superpowers implementation. This specification makes that approved direction executable; it does not alter the Scout -> Seed -> Discovery -> Repair -> Submit research model.

## Boundaries

- Keep Python backend, authoritative Orchestrator state, knowledge provenance, hard candidate checks and explicit final submission approval.
- Add durable automatic driving, cooperative pause/resume, source outcome routing, local incremental progress, double-click desktop entry, and maintainable task/architecture records.
- No live simulation or Alpha submission during development acceptance. Test against injected/fake platform responses. No credential copying or new paid model purchase.
- Work with existing uncommitted maintenance changes on the current feature branch; no bulk revert, migration deletion or automatic commit/push.

## Runtime

One active run has one persisted runtime control file. It records desired state, live permission, limits, next wake, last result and stop reason. A worker drives existing legal actions without asking for stage-by-stage clicks. Waiting is bounded by run budgets and retry policy, survives restart, and never infers success from process exit alone. Stop is a cooperative resumable pause; no new simulation POST may begin after pause is acknowledged. Already submitted simulations retain identities and URLs for recovery.

Transient rate limits use existing Retry-After evidence and a bounded recovery allowance, rather than repeatedly requesting human acknowledgement. Permission changes, exhausted budget, invalid credentials, external persistent failure and final submission remain explicit boundaries. Ordinary weak signals are research results, not maintenance failures.

## Stage Contracts

Scout output includes checked research results, repairable signals and optionally qualified candidates. Absence of a hard-pass CSV cannot prevent signal triage. Empty/unrelated result files cannot complete execution stages. Repair uses existing optimization helpers and records parent/child lineage; unnecessary work is explicitly skipped. Candidate checks remain strict.

## Console And Desktop

- Start from an option card, then pause/resume. Run permission persists with the run; refresh cannot clear inputs.
- One source-bound state projection powers UI and runtime. Strategy rows join planned work, simulation events and checks by simulation identity/expression hash, retaining multi parent/child distinctions.
- Cache cold knowledge summaries by file changes. Runtime updates avoid full ledger scans. Push local state changes via SSE with lightweight fallback polling and stable DOM.
- Ship a double-click launcher for an independent app window, reuse a local backend, avoid duplicate processes, hide helper windows. Prefer installed Windows browser app mode as the dependency-light shell; document it honestly as a desktop app window, not a native rewritten UI. Runtime survives closing the UI.
- Show running/waiting/paused/error/qualified states and timestamps; do not invent platform progress percentages.

## Maintenance

Keep a short canonical milestone plus archived history; version architecture and task acceptance. Provide a local maintenance view/board and GitHub Projects integration path without copying private alpha evidence to remote boards. AI tasks must have durable input/output/status and an explicitly configured executor; lack of credentials/executor is visible, never represented as completed AI work.

## Acceptance

Fake-platform E2E: option -> 30 planned -> partial completion -> rate wait/recovery -> signal routing/repair -> validated candidates -> approval boundary. Pause prevents new POST, restart resumes without duplicates. Unrelated readiness cannot affect active run; empty files cannot mark repair complete. UI selection survives updates; close/reopen preserves work. Per-strategy updates use local state only. Native Windows tests must not fake sys.platform. Measure state response and report limits truthfully.
