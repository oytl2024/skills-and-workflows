# Daily Simulation Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if the human selects that method. Execute task-by-task with failing tests before product changes.

**Goal:** Enforce a shared 4,000-attempt Shanghai-calendar-day allowance and automatic, Stop-safe daily waiting without lifetime budget markers blocking research.

**Architecture:** One local budget owner supplies authoritative daily balance and recoverable lifetime projections. Existing submission, planning, driver and Console modules consume it; the research-stage state machine and platform submission identities stay intact.

**Tech Stack:** Existing Python, unittest, JSON atomic writes and OS-backed JSON locks; existing desktop Console. No database, agent framework, network dependency or recurring automation.

**Spec:** `docs/superpowers/specs/2026-10-21-daily-simulation-budget-design.md` (human-approved 2026-10-21).

## Global Constraints

- Default 4,000 simulation submission attempts/day, boundary 00:00 Asia/Shanghai, shared across managed runs/stages in the canonical workspace.
- Multisimulation costs its number of children. GETs/local planning cost zero; failed or unknown POST attempts keep their charge.
- Preserve lifetime attempts, historic buckets, immutable identities, frozen research resources and uncertain-POST recovery. Do not reinterpret platform quota.
- Daily wait is automatic within existing authorized worker/time limits. Stop, time expiry, explicit round/recovery limits, 429 pacing and final submission approval remain independent.
- Scout/Discovery cap 30, not a minimum; preserve Seed/Repair bounds and complete paired experiments.
- Original-only recovery never acquires new scope. Existing ordinary runs require revision-bound activation; no new mission or resetting historical counters.
- No live WQB/model work during development. Never resume the active run merely to test the change.
- Every delegated agent/reviewer explicitly uses reasoning effort medium or lower.

## Review Focus

Execution status (2026-10-22): Tasks1-5 implemented; independent findings closed.
Final2,164-test offline proof passed with unchanged source digest
`ebf6e5cb59e069dea4f1139159068855b302f2a47d6da2913007bd82f28116b4`.
Case `eb829cc7dd4df1c956f6ee5b` resolved; authorized local activation retained
150 lifetime attempts/64,800s/three recoveries and original intent. Day balance
150/4,000, remaining3,850; no research or WQB request. Frozen readiness passed;
Console local snapshot permits Resume/Stop and renders150/4000. Source commit
`f200010` synchronized with GitHub; no-deletion audit/63 post-audit tests passed.
Desktop app opened and loaded-source identity matched; final audit-commit/app
identity is recorded in root todo.md. Fake-clock tests use4,000 with boundary
charges, plus actual Repair-scheduler fixtures; they do not issue4,000 requests.
Fictional acceptance clocks are fixed without weakening production freshness.
Source-change failures remain preserved. Root todo.md owns current handoff.

1. Two runs race for the last unit: exactly one succeeds, with no request dispatched by the loser (Tasks 1-2).
2. Crash after a shared charge but before its run projection, including midnight: history reconstructs without refund, duplication or blind re-POST (Tasks 1-2).
3. Stop, time expiry or a newly pending maintenance case arrives during rollover/wait: it wins over automatic continuation (Tasks 3-4).
4. Old round/Repair receipts preserve their original reservations: daily availability must not corrupt receipt identity or cause false maintenance faults (Tasks 3-4).
5. App restarts while quota is exhausted: snapshot/action permissions show a resumable daily wait, not a permanently disabled gate or an implicitly started mission (Tasks 4-5).

## Task 1: Atomic Daily Ledger And Policy

**Files:** Create `wqb/daily_simulation_budget.py`, `tests/test_daily_simulation_budget.py`.

**Interfaces:**
- `ensure_daily_policy(runs_root: Path) -> dict`: create only a provably new budget store; reject missing pieces of an established store.
- `read_daily_budget(run_dir: Path, now: str | None = None) -> dict`: return `mode`, `budget_date`, `timezone`, `limit`, `used`, `remaining`, `next_reset_at`, `lifetime_attempts`, `policy_id`; read-only, no automatic repair/publication.
- `charge_daily_budget(run_dir: Path, count: int, charge_id: str, now: str | None = None) -> dict`: serialize and publish one positive reservation; exact replay is idempotent, a conflicting replay fails closed.
- `reconcile_lifetime_attempts(run_dir: Path) -> int`: project authoritative ledger totals, never issue POST or renew authority.

**Store:** `runs/daily_simulation_budget/{policy.json,ledger.json,archive/<date>.json}`. Ledger contains active date/used/charges, cumulative per-run totals, activation baselines and archived-day digests. Bound active-day receipts by the quota; do not rewrite years of per-attempt history at every POST. Carry cumulative run totals forward when archiving an old day. Policy owns the default limit/timezone once, not duplicated constants across callers.

**Lock/publication:** Canonical owning run determines shared root, never a source/Repair subrun. One shared budget guard protects read/check/charge/rollover. Daily charge and its cumulative per-run total are one atomic ledger replacement. Runtime status is a projection. Publish immutable previous-day archive before rolling the active ledger; replay verifies an existing identical archive, and rejects conflicting/missing established evidence. A passive snapshot can compute a new day's zero balance without writing; the next authorized mutation performs rollover. Reject backward dates rather than reopening historical allowance.

- [x] Write failing tests: `test_3999_plus_one_and_overflow`, `test_two_runs_share_balance`, `test_multichild_charge_and_replay`, `test_conflicting_replay_and_invalid_counts`, `test_no_read_side_effects`, `test_midnight_retains_lifetime`, `test_backward_clock_rejected`, `test_corrupt_or_missing_established_store_blocks`.
- [x] Add multiprocess race and crash-injection tests: last-unit race permits one winner; failure after ledger replacement leaves a recoverable lifetime projection; failure between archive and rollover replays once. No root-workspace fixtures or network.
- [x] Run `python -m unittest tests.test_daily_simulation_budget -q`; require the expected missing-interface failures, not setup failures.
- [x] Implement those interfaces using existing safe atomic writes/JSON locks and injectable UTC timestamps; validate canonical paths/links and timezone-aware values.
- [x] Rerun the same command; require PASS. Independently review the ledger/publication boundary before integrating it.

## Task 2: Submit Accounting And Explicit Activation

**Files:** Modify `wqb/runtime_control.py`, `wqb/simulator.py`, `wqb/run_authority.py`, `wqb/console_start.py`, `wqb/cli.py`; extend the Task 1 module. Tests: `tests/test_runtime_integration.py`, `tests/test_simulator.py`, `tests/test_run_authority.py`, `tests/test_console_start.py`, Task 1 tests.

**Interfaces:**
- `DailyBudgetExhausted(RuntimePaused)` in `runtime_control.py`, carrying a validated `budget: dict`; distinguish it from time expiry and legacy lifetime exhaustion.
- Preserve `check_submission_allowed(payload_count: int = 0)` callers. Daily mode delegates a positive reservation to Task 1 exactly once; a zero-count safety check does not consume quota or stop legitimate result polling at the exact limit. Keep the existing legacy authority checks.
- `activate_daily_policy(run_dir: Path, expected_revision: str, confirmation_reference: str, now: str | None = None) -> dict` in the budget module: audited CAS activation, preserving Stop and every non-simulation limit. Provide a local-only `python -m wqb.daily_simulation_budget activate` maintenance entry using those same arguments.

**Activation:** Bind a run's `simulation_budget_mode='daily'` and policy/activation identity to its validated owning authority. Keep historical `max_simulations` and renewal evidence; do not treat that legacy field as the daily mode's lifetime ceiling. Conservatively carry the active run's known 150 lifetime units into activation day once, explicitly labelled. Journal activation before publishing run intent; resume an interrupted identical activation without double charging. Do not waive unresolved maintenance, malformed authority or original-batch restrictions. New ordinary Start paths initialize/bind the approved policy; unmigrated records retain readable legacy semantics. If a shared policy is already established, legacy/original-only product submissions also charge it while retaining their stricter original ceilings; absence of policy in an untouched legacy fixture is not permission to manufacture daily authority.

- [x] Write failing tests for a one-child and multichild POST, zero-cost GET, unchanged legacy behavior without policy, crash projection recovery and concurrent reservation before dispatch. Assert the refused client is never called.
- [x] Add tests that same charge reconciliation does not invoke POST, unknown outcomes remain charged, actual subsequent POST attempts receive new identities, and mode/ledger corruption blocks rather than reverts to defaults.
- [x] Add activation tests for 150 lifetime/150 day usage, replay once, stale revision/newer Stop rejection, preserved time/recovery caps and protected original-only scope. Assert snapshots distinguish daily remaining from lifetime remaining in `run_authority`.
- [x] Run `python -m unittest tests.test_daily_simulation_budget tests.test_runtime_integration tests.test_simulator tests.test_run_authority tests.test_console_start -q`; inspect expected RED.
- [x] Integrate the central reservation at the existing simulator accounting boundary. Keep payload counting out of GET/HTTP retries and preserve platform POST identity handling. Update Start and authority projection only through existing local APIs.
- [x] Rerun the same command to PASS. Review the authority/accounting integration before touching live records.

## Task 3: Daily-Aware Planning And Budget Marker Reconciliation

**Files:** Modify `wqb/research_planning.py`, `wqb/research_rounds.py`, `wqb/workflow_auto_continue.py`; narrowly integrate `wqb/discovery_runtime.py`, `wqb/repair_runtime.py`, `wqb/repair_scheduler.py`, `wqb/workflow_stage_adapters.py` where stage allocation/wait projection requires it. Tests: `tests/test_research_planning.py`, `tests/test_research_rounds.py`, `tests/test_research_loop_runtime.py`, `tests/test_discovery_runtime.py`, `tests/test_repair_runtime.py`, `tests/test_repair_scheduler.py`, `tests/test_workflow_auto_continue.py`.

**Interfaces:**
- `remaining_submission_allowance(run_dir: Path, now: str | None = None) -> int` in Task 1 module: daily remaining for valid daily mode; for legacy mode, validated run-total remaining capped by shared daily remaining if the shared policy exists.
- `reconcile_research_budget_wait(run: Path, now: str) -> dict` in `research_rounds.py`: re-evaluate only a recognized daily wait or an activation-bound obsolete simulation-budget stop; return `unchanged`, `ready`, or `daily-budget-wait` with evidence. Never change user intent or unrelated blockers.
- `hypothesis_authorized_maximum` and round allocation use that interface instead of subtracting lifetime usage from the preserved legacy ceiling.

**Planning:** Existing historical `budget_used`/reservations remain meaningful run history, not today's new submissions. Do not double charge them or zero them. Preserve explicit `max_rounds`; do not derive a permanent daily-mode lifetime round limit from 150/180. A new batch fits the available day allowance, including complete paired arms. Existing immutable Repair attempt maxima/lineage are not rewritten just because daily remaining changed.

- [x] Write failing tests: lifetime 5,000 with fresh day allows a valid new batch; 3 units left yields at most 3 new candidates; a pair cannot be reduced to half; old `budget_reserved` does not subtract today's balance twice.
- [x] Add tests for 150-to-daily activation releasing the exact old marker, unchanged unrelated planning/knowledge faults, explicit round limit retention, and no marker release after a newer Stop or invalid activation.
- [x] Add Repair tests where day quota exhausts between independent children: preserve pending/planned work and previous children, do not mark quota wait as code failure or unknown POST. Rollover continues existing receipt identity rather than regenerating a parent plan.
- [x] Run the named seven unittest modules to establish RED.
- [x] Integrate the shared allowance and reusable reconciliation before `workflow_auto_continue`'s early paused-research return. Preserve the core Orchestrator stage architecture; do not manually edit actual round JSON.
- [x] Rerun those modules to PASS and review round/Repair compatibility.

## Task 4: Cooperative Daily Wait And Restart Recovery

**Files:** Modify `wqb/workflow_driver.py`, `wqb/runtime_boundaries.py`, `wqb/workflow_auto_continue.py`, Task 3 wait projections. Tests: `tests/test_console_runtime.py`, `tests/test_runtime_boundaries.py`, `tests/test_research_loop_runtime.py`, `tests/test_workflow_auto_continue.py`; create `tests/test_daily_budget_workflow.py`.

**Interfaces:**
- Daily exhaustion produces `next_action='daily-budget-wait'` with `budget_date`, `used`, `limit`, `next_reset_at` and policy identity. This is not a maintenance case or a request for renewed daily authority.
- Catch `DailyBudgetExhausted` before generic `RuntimePaused`/Repair error handling. The driver persists a wait and revalidates Task 1 at wakeup.
- `reconcile_research_budget_wait` runs again after restart/wakeup, before new work. Reuse the existing worker lock/heartbeat and cooperative sleep; no second scheduler.

- [x] Write a fake-clock full-flow test: exhaust a tiny test policy across Scout/Repair, finish existing poll/check work, wait through midnight, continue automatically, retain lifetime/unknown POST identities and original mission.
- [x] Test Stop during wait, time expiry before midnight, new maintenance case during wait, another run consuming the new day first, restart during wait and policy corruption. All win over new POSTs.
- [x] Assert waiting does not repeatedly call AI/platform, create timestamp-changing no-op batches, consume 1,000 empty driver steps or send recurring maintenance notices.
- [x] Run `python -m unittest tests.test_daily_budget_workflow tests.test_console_runtime tests.test_runtime_boundaries tests.test_research_loop_runtime tests.test_workflow_auto_continue -q`; establish RED.
- [x] Implement daily waits and source-bound historical wait evidence. Preserve time accounting while waiting, original 429 behavior and independent legacy resource boundaries. GET/check reconciliation must not accidentally schedule fresh AI research while quota is zero.
- [x] Rerun to PASS and review fake-clock end-to-end evidence.

## Task 5: One Console Snapshot For Budget And Actions

**Files:** Modify `wqb/console_state.py`, `wqb/console_timeline.py`, `wqb/console_server.py`; no new page, region or button layout. Tests: `tests/test_console_state.py`, `tests/test_console_timeline.py`, `tests/test_console_server.py`, `tests/test_console_jobs.py`.

**Interfaces:** `load_runtime_state` projects `daily_simulation_budget` from Task 1. Timeline, status text and action revision consume this one snapshot. Render today's `used / 4000`, separate lifetime attempts, Shanghai date/time and next midnight; identify an independent blocking boundary when present.

- [x] Write failing tests for running, quota wait, stopped, app restart, stale client snapshot, corrupt accounting, concurrent state changes and independent runtime/maintenance blocks.
- [x] Assert Stop remains available; an active waiting worker cannot be double-started. With no worker after restart, ordinary Continue can launch the authorized waiting/reconciliation path without a new quota/approval button.
- [x] Run `python -m unittest tests.test_console_state tests.test_console_timeline tests.test_console_server tests.test_console_jobs -q`; establish RED.
- [x] Replace obsolete daily-mode resource-marker projection with the shared snapshot; keep legacy markers for unmigrated/original-only runs. Refresh local budget state with the existing near-real-time stream, never a platform request.
- [x] Rerun to PASS; independently review action-state consistency, then inspect a local fake-ledger UI snapshot. Do not trigger an actual Start/POST.

## Task 6: Offline Acceptance, Controlled Migration And Delivery

**Files:** Update `docs/operations/user_workflow_manual.md`, `docs/operations/maintainer_handoff.md`, outer `AGENTS.md`, `milestone.md`, `todo.md`; update this plan's checkboxes. Actual policy/activation/verification artifacts stay under existing `runs/` boundaries, not Git or human wiki. No new root entry copies.

- [x] Document policy vs platform quota, attempt vs completed Alpha, conservative migration, daily wait vs time expiry, original-only compatibility and app Start/Stop behavior. Keep root entry documents under their tested size bounds.
- [x] Add/finish offline acceptance coverage for all spec bullets, then run `python -m unittest discover -s tests -q` with credentials filtered from child environment. Require nonempty PASS and unchanged source digest.
- [x] Run `python -m unittest tests.test_project_architecture tests.test_project_entry_docs -q`, `git diff --check`, and an independent whole-change review with explicit reasoning medium or lower. Close actionable findings and rerun affected/full verification after source changes.
- [x] Inspect current actual run control, worker lock, Stop revision and all blockers before any activation. Do not silently renew a stale maintenance proof: obtain separate human approval if required by the current source-bound contract.
- [x] Once approved and fully verified, apply local-only, revision-bound daily activation using the Task 2 entry point; current expected baseline is lifetime 150, old cap 180, runtime 64,800s, recoveries 3. If actual state changed, stop and reconcile instead of forcing these values. Persist migration/round-reconciliation evidence, without live research.
- [x] Verify all frozen resource/readiness gates and the app's next legal transition offline. A source/knowledge block is not repaired by a larger allowance.
- [x] Commit/push the intended existing branch without force; verify local and remote equality. Audit cleanup candidates in the existing cleanup record: preserve raw knowledge, research identities, receipts, legacy readers and uniquely referenced historical evidence. Delete only approved obsolete reproducible artifacts; if none exist, record that and do not manufacture cleanup work. Keep pre-existing `output/` and `tests/full-suite-maintenance.log` unless separately audited.
- [x] Reload only the owned passive desktop backend, requesting escalation if the sandbox blocks it. Verify loaded commit/source, proof, actual daily/lifetime labels and Start/Stop permissions. Never bypass a denied operation or report an old backend as deployed.
- [x] Record final command/results, changed/uncommitted paths, explicit remaining blockers and exact next action in root `todo.md`. Do not resume research or submit Alpha merely to prove the maintenance release works.

## Execution Choice And Approval Gate

Recommended: native sequential implementation in the current maintenance task,
with focused reviews at accounting/authority/round/wait boundaries and one final
independent review. These interfaces are tightly coupled; parallel writers would
create unnecessary integration and context-management cost. Every reviewer uses
medium reasoning or lower. Subagent-driven sequential execution is also valid
if selected explicitly; it is not permission for parallel live operations.

This plan has been self-reviewed against every section of the approved spec,
including crash recovery, midnight, multi-run races, paired experiments, protected
legacy authority, stale round markers and app action consistency. Product code
changes begin only after the human approves this plan and execution choice.
