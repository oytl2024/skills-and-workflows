# AI Repair and Runtime Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Consume real AI Repair judgments, advance independent children safely, and report resource/stalled-task boundaries automatically.

**Architecture:** Add a bounded evidence planner and identity-keyed Repair scheduler around the existing executor. Keep resource notifications separate from code-repair approvals and project consistent runtime state into the existing Console.

**Tech Stack:** Python3.12, unittest, existing Codex read-only executor, JSON/JSONL durable receipts, existing local Console.

**Spec:** ../specs/2026-10-12-ai-repair-and-runtime-boundaries-design.md

## Global Constraints

- No WQB calls, live research resume, authority expansion, elapsed reset, Alpha submission, commit or push during implementation acceptance.
- Preserve Stop, existing submission locks, unknown-POST reconciliation, stage Repair allowance and mission limits.
- Every delegated implementer/reviewer uses explicit reasoning_effort=medium or lower.
- Existing submitted plans are immutable; do not force a new model decision onto an in-flight child.
- No new dependency, UI layout or recurring automation. API secrets never enter fixtures/receipts/prompts.

## Review Focus

- Old submitted plans without AI evidence must recover once without claiming AI authorship (Task2).
- A model stop decision or failure must not fabricate a checked result or permanently block unrelated parents (Tasks1/2).
- Stop during the model subprocess must cancel promptly, not merely block the eventual POST (Task1).
- Partial child publication followed by restart must neither lose checked evidence nor duplicate reservations (Task2).
- Notification uncertainty and an old resolved maintenance case must not hide a new resource boundary (Task3).

## Task1: Evidence-Bound AI Repair Planning

**Files:** Create wqb/repair_planning.py and tests/test_repair_planning.py. Modify wqb/ai_checkpoints.py and its tests for cancellable execution; wqb/repair_runtime.py for validated edit execution.

**Interfaces:** prepare_repair_decision(run: Path, parent: dict, history: list[dict], allowance: int, config: dict, now: str) -> dict returns a persisted validated plan or explicit stop decision. validate_repair_decision(decision: dict, evidence: dict) -> dict rejects stale/unsupported edits. The executor consumes the validated plan digest, not advisory text.

- [ ] Write tests named test_decision_changes_payload, test_stale_parent_rejected, test_missing_semantics_not_invented, test_invalid_or_missing_ai_not_rule_fallback, test_stop_decision_no_post, test_prior_results_drive_next_decision, test_restart_reuses_receipt, test_pause_cancels_worker. Assert model input references bounded local evidence and output identity matches the parent.
- [ ] Run python -m unittest tests.test_repair_planning tests.test_ai_checkpoints -q; confirm new assertions fail for the intended missing behavior.
- [ ] Implement input/output receipts, validation and bounded knowledge selection from immutable snapshot/local resources. Include economic rationale, failure diagnosis, expected improvement and risks. Existing settings edits use explicit ranges: decay0..32, truncation greater than0 and at most0.15, neutralization from existing NEUTRALIZATIONS. Add structured smooth/rank operator wrapping only when canonical operator signatures and field types validate it; no arbitrary expressions or new data. Persist allowed edit/range evidence in the input. Reject duplicate hashes.
- [ ] Implement cancellable bounded subprocess execution using the existing executor argv and medium effort. Preserve generic checkpoint compatibility; persist failed/cancelled output honestly and stop child processes on cancellation.
- [ ] Re-run focused tests, inspect diff for authority or credential leakage, request independent medium review of decision validation before scheduler integration.

## Task2: Fair Durable Repair Scheduling

**Files:** Create wqb/repair_scheduler.py and tests/test_repair_scheduler.py. Modify wqb/workflow_stage_adapters.py, wqb/repair_runtime.py and tests/test_repair_runtime.py, tests/test_repair_progress_wait.py. Wire planner config via existing RepairRuntimeExecutor construction in wqb/cli.py if needed.

**Interfaces:** execute_repair_round(root: Path, outcome: dict, executor: object, maximum: int) -> dict replaces adapter completed-prefix execution and retains its receipt return contract. Scheduler consumes Task1 decisions via executor planning interface; the existing __call__ recovery interface remains supported for frozen legacy plans.

- [ ] Add test_pending_first_parent_does_not_block_second, test_reserved_sum_never_exceeds_maximum, test_recover_old_submitted_plan_without_replan, test_partial_publication_restart_once, test_stopped_parent_releases_only_unsubmitted_allowance, test_global_cooldown_prevents_new_post, test_unknown_post_not_replayed, test_next_iteration_uses_checked_comparison.
- [ ] Run python -m unittest tests.test_repair_scheduler tests.test_repair_runtime tests.test_repair_progress_wait -q; confirm failing scheduler assertions.
- [ ] Implement identity-keyed reservations and per-child phases. Migrate existing receipt attempts idempotently without altering hashes/settings/source events. Reject ambiguous/corrupt migration evidence. Each slice visits ready independent parents and persists results once; respect existing request/concurrency policy rather than creating thread concurrency.
- [ ] Reuse saved URLs/AlphaIDs and earliest eligible wake when all work waits. Reserve before dispatch, include pending reservations in allowance, and persist measured parent/child comparisons. Exhausted completed lines return to existing research-round behavior; pending children do not become fake completed results.
- [ ] Add persisted first-observed-wait timestamp. Define REPAIR_STALL_NOTICE_SECONDS=1800 below imports; after30minutes emit a once-per-identity diagnostic via Task3 without marking platform failure or replaying POST. The notice is actionable inspection evidence, not authorization.
- [ ] Run focused scheduler/adapter/research-loop tests and get medium review of migration, fairness, reservation and Stop boundaries.

## Task3: Resource and Stalled-Task Notification Contract

**Files:** Create wqb/runtime_boundaries.py and tests/test_runtime_boundaries.py. Modify wqb/workflow_driver.py, wqb/maintenance_notifications.py, tests/test_workflow_driver.py, tests/test_maintenance_notifications.py, wqb/console_timeline.py, wqb/console_state.py and corresponding tests. Modify other Console action-owner modules only where routing tests identify them.

**Interfaces:** record_runtime_boundary(run: Path, kind: str, evidence: dict, now: str) -> dict writes a deterministic resource/stall receipt. dispatch_boundary_notice(run: Path, boundary: dict, now: str) -> dict uses the configured existing notification channel but never grants repair approval. project_runtime_boundary(result: dict, control: dict) -> dict provides one canonical action projection.

- [ ] Add test_elapsed_exhaustion_sends_once, test_exhaustion_during_wait, test_repeated_resume_no_requests_or_reset, test_step_exhaustion_visible, test_stop_wins_boundary_race, test_uncertain_delivery_not_replayed, test_old_resolved_case_does_not_hide_boundary, test_console_matches_cli_and_disables_noop_resume, test_stall_notice_preserves_submitted_identity.
- [ ] Run python -m unittest tests.test_runtime_boundaries tests.test_workflow_driver tests.test_maintenance_notifications tests.test_console_timeline -q; verify intended RED results.
- [ ] Implement distinct persisted boundary receipts and bounded event notification. Refactor shared transport narrowly instead of forging code_or_contract cases. Retain exact configured limits/usage, existing notification channel and transport15second bound. Write transport failure/uncertainty to receipt for UI display.
- [ ] Project runtime-budget-exhausted and step-budget-exhausted next actions ahead of stale workflow-resume. Resume cannot reset elapsed or silently renew any authority. Stop remains permitted; final submission authority remains separate. Integrate Task2 stall notices and show real AI validated/consumed states in existing Console sections.
- [ ] Run focused Console/action/driver tests and independent medium review for deduplication, intent races and stale-state correctness.

## Task4: Whole-Flow Acceptance and Handoff

**Files:** Create tests/test_ai_repair_acceptance.py; update docs/operations/user_workflow_manual.md, root milestone.md and todo.md.

- [ ] Build an offline fixture: two near misses, bounded fake model decisions, first child pending, second checked, comparison-driven next test, restart with no duplicate POST, eventual candidate formal checks or bounded round rollover, then exhaustion notice and consistent Console projection. Assert payloads match consumed decision receipts and SELF/PROD follows baseline success.
- [ ] Run the acceptance test RED then GREEN; run python -m unittest discover -s tests -q with credentials removed from child test environment. Require nonzero test count and no failures; run compileall and git diff --check.
- [ ] Update architecture/usage/handoff only with proven capabilities. Run python -m unittest tests.test_project_architecture tests.test_project_entry_docs -q. Run independent medium whole-change review and fix concrete issues with regressions.
- [ ] Inspect local active-job/version evidence. Reload owned Console only if no job would be interrupted and verify loaded source digest. Current exhausted run remains blocked honestly; do not resolve a code case without its required verification receipt. Record all remaining external/authority blockers and exact operations next action in todo.md.

## Execution Choice

Recommend native implementation in this maintenance window, with independent medium reviews at integration boundaries and final acceptance. Tasks share mutable execution/receipt interfaces, so concurrent implementation adds migration risk. No running verification or live research job is required for plan review.

## Execution Record

- Tasks1-3 implemented and reviewed, with bounded edits only: authoritative operator signatures are absent in the immutable snapshot, so wrappers remain rejected rather than guessed. Local PnL is used only when present. No live model/platform performance claim.
- Task4 offline acceptance, final1330test formal suite,23architecture/entry tests, compileall and diffcheck passed. Final review issues fixed with regressions. Console loaded/source digest verified; exhausted runtime stays blocked and event notice is queued.
- Architecture logging regression was included because operational appends broke the entry contract; history preserved, future jobs routed only to todo/jobs.
- Operational recovery is incomplete pending a separate human runtime-authority decision. No elapsed reset, simulation-limit increase, live resume, WQB request, Alpha submission, commit or push occurred.
- Exact durable evidence and next action are in root todo.md Latest handoff, not conversation memory.
