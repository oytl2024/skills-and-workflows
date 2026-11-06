# Autonomous Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Track steps using checkboxes.

**Goal:** Resolve recoverable blockers without human message relay and reduce platform HTTP traffic without losing simulation/check evidence.

**Architecture:** Delivery A centralizes request accounting, batching and deterministic recovery. Delivery B adds durable maintenance cases, an isolated patch worker and an external deployment supervisor; it depends on A but cannot silently expand existing advisory AI permissions. The supervisor survives backend restart and preserves user Pause and durable platform evidence.

**Tech Stack:** Existing Python 3.12, unittest, requests, JSON/JSONL, existing OS locks, Console SSE and Windows app-mode launcher. No new dependency by default.

**Spec:** ../specs/2026-10-11-autonomous-blocker-recovery-design.md

## Global Constraints

- No live WQB or model execution during implementation acceptance. Later live validation is separate and must respect stored authorization and budget.
- No research-rule, budget, credential, final-check or Alpha-authorization changes by maintenance workers. No automatic commit/push or sensitive-file deletion.
- Every subagent/worker reasoning effort is explicitly medium or lower.
- Use apply_patch, concise functions with input/output/function comments, constants after imports, existing structured parsers and locking patterns.
- Dirty checkout is the source baseline; never reset it or base repair solely on HEAD. Source drift aborts deployment.
- Unknown POST outcomes fail closed. A successful multisimulation child still consumes simulation quota.
- Do not invent a current platform batch limit. Until authoritative capability evidence is available, retain the existing conservative batch ceiling; unify recovery sizing without claiming it supports dozens.
- Worker command, network and filesystem isolation must be enforced outside prompts. If enforceable isolation or usage ceilings are unavailable, keep automatic patch execution disabled with a precise reason; never use unrestricted execution as fallback.
- Planning does not authorize implementation. Review this plan and select execution method first.

## Review Focus

1. Process crashes between POST and result persistence must not duplicate submissions (Tasks 2, 3).
2. Pause racing with repair completion/deployment must never restart research (Tasks 4, 6).
3. Untrusted evidence or Windows junction/symlink paths must not escape the worker boundary (Task 5).
4. Dirty source edits and stale test receipts must stop patch activation, not overwrite user work (Task 6).
5. UI refresh/reconnect and expired worker leases must not create duplicate recovery/model/API requests (Tasks 3, 4, 7).

## Delivery A: Requests And Scripted Recovery

### Task 1: Identify Actual Blocker And Measure Requests

**Files:** modify wqb/client.py; create wqb/request_metrics.py, tests/test_request_metrics.py; update tests/test_client.py and root todo.md.

**Interfaces:** request_metrics.record_request(run_dir: Path, event: dict) -> None; request_metrics.summarize_requests(run_dir: Path) -> dict. Events contain endpoint class, method, status, duration, payload_count, retry/reset hints and timestamp, never credentials/full URL/query/body.

- [ ] Read Console launch roots and active-job/run identity, then inspect only corresponding runtime, bridge and submission evidence. Record actual blocker and distinguish old persisted run state from current projection.
- [ ] Write tests for secret redaction, one event per actual HTTP attempt including authentication/errors, endpoint normalization and bounded summary reads. Run `python -m unittest tests.test_request_metrics tests.test_client -q`; observe RED for missing contract.
- [ ] Implement accounting at actual HTTP dispatch without adding platform requests or changing retry policy. Add deterministic fixtures representing 30 candidates and record the current initial/recovery baseline.
- [ ] Rerun focused tests GREEN; record exact counts and failure evidence in todo. Request metrics are diagnostic, not a new authoritative quota counter.

### Task 2: Shared Batch And Poll Policy

**Files:** create wqb/simulation_request_policy.py and tests/test_simulation_request_policy.py; modify wqb/cli.py, wqb/simulator.py, wqb/source_bridge.py and their existing tests.

**Interfaces:** choose_batch_size(policy: dict, remaining_candidates: int, remaining_budget: int, remaining_quota: int | None) -> int; next_poll_delay(policy: dict, attempt: int, retry_after: float | None, jitter: float) -> float. Policy records capability evidence/digest and supported ceiling separately from requested size and stage candidate count. Invalid/missing evidence cannot raise the conservative ceiling.

- [ ] RED tests: initial/recovery/Repair share policy; exact budget/quota truncation; zero budget makes no POST; missing capability cannot yield oversized batches; partial child completion and unknown POST preserve identities.
- [ ] Implement shared sizing across all actual initial/retry submit paths, keeping durable attempt journaling and existing single-submit safety. Do not refactor unrelated CLI commands.
- [ ] RED/GREEN polling tests: parent polling before needed child fetch, Retry-After respected, bounded jitter/backoff, completed evidence reused, mandatory fresh checks retained. No default cadence reduction without metric evidence.
- [ ] Run `python -m unittest tests.test_simulation_request_policy tests.test_cli tests.test_client tests.test_simulator tests.test_source_bridge -q` (verify existing test module names before execution).
- [ ] Assert mocked 30-candidate recovery uses fewer submission requests than existing two-item recovery at the same supported ceiling, with identical candidate count/check coverage. Report exact totals; do not imply quota savings.

### Task 3: Durable Deterministic Recovery

**Files:** create wqb/recovery_cases.py, tests/test_recovery_cases.py; modify wqb/workflow_driver.py, wqb/rate_limit_state.py and related tests.

**Interfaces:** classify_blocker(result: dict) -> dict; ensure_recovery_case(run_dir: Path, blocker: dict, now: str) -> dict; advance_scripted_recovery(run_dir: Path, case: dict, policy: dict, now: str) -> dict. Cases live under run/runtime/recovery/, with schema_version, fingerprint, intent_revision, attempts, lease, next_wake and evidence paths. Reuse current OS locking/atomic file patterns.

- [ ] RED tests for duplicate discovery, crash/restart, cooldown/reset, unknown outcome reconciliation, invalid evidence and no-progress detection.
- [ ] Implement known-fault handlers using existing in-flight/planned/knowledge-maintenance contracts. Remove the driver's blind threshold reset as a claim of platform recovery; classify quota versus transient throttling using evidence. Wait within stored limits and never probe with an extra simulation.
- [ ] Test external indefinite failure exits to durable waiting/exhausted state without busy polling or counter resets. No status read starts a worker. Missing live permission remains protected, not auto-elevated.
- [ ] Run `python -m unittest tests.test_recovery_cases tests.test_workflow_driver tests.test_rate_limit_state tests.test_workflow_acceptance -q`; record RED/GREEN and delivery A request measurements.

## Delivery B: Automatic Maintenance And Safe Activation

### Task 4: Maintenance Dispatch Contract

**Files:** create wqb/maintenance_dispatch.py, tests/test_maintenance_dispatch.py; modify wqb/workflow_driver.py, wqb/runtime_control.py and relevant tests.

**Interfaces:** build_maintenance_input(run_dir: Path, case: dict, source_root: Path) -> dict; dispatch_maintenance_case(run_dir: Path, case: dict, executor_argv: list[str]) -> dict. One case lease per failure/source digest; bounded sanitized evidence, milestone/todo pointers, protected policy digest, original intent and finite limits.

- [ ] RED tests: repeated no-progress/reconnect launches once; expired lease reconciles PID/result before redispatch; concurrent Pause cancels automatic resume; unavailable executor records reason without user relay.
- [ ] Implement separate maintenance jobs and explicit configured attempt/time/usage ceilings; do not alter read-only research checkpoint adapter. Initial defaults: at most 2 patch attempts per case, 600 seconds per worker and 1800 seconds total maintenance wall time. These are maintenance-only ceilings and cannot increase existing user limits.
- [ ] Require an enforceable worker usage ceiling before enabling patch execution; if current runtime supports no hard token ceiling, expose that blocker rather than pretending a timeout bounds tokens. Diagnose safe alternatives before implementation continues.
- [ ] Run `python -m unittest tests.test_maintenance_dispatch tests.test_workflow_driver tests.test_console_jobs -q`.

### Task 5: Isolated Worker And Patch Validation

**Files:** create wqb/maintenance_workspace.py, wqb/maintenance_worker.py, tests/test_maintenance_workspace.py, tests/test_maintenance_worker.py. Read existing codex_ai_worker for invocation conventions only.

**Interfaces:** capture_source_snapshot(source_root: Path, destination: Path) -> dict; validate_patch(snapshot: dict, changed_files: list[str], policy: dict) -> dict; run_maintenance_worker(input_path: Path, output_path: Path) -> dict.

- [ ] RED tests for dirty-source fidelity, secret exclusion, oversized evidence, junction/symlink traversal, environment credential leakage, shell/network escape, forbidden file/policy changes and malformed output.
- [ ] Prove the selected Windows worker sandbox denies live source writes, secrets and external network/command execution before using it. A workspace copy or prompt alone is not sandbox proof. If unavailable, stop patch execution but keep deterministic recovery and diagnostic status usable.
- [ ] Implement bounded read/write workspace and permitted test runner; sanitized environment. Worker produces minimal patch, reproducer, test output and input/source digest, not live deployment or platform calls. Protected paths include AGENTS, configuration/credentials, benchmark/rule/authorization resources, runtime budgets and persisted runs/knowledge. A fix needing protected files becomes unsafe_to_recover.
- [ ] Execute focused then full tests under trusted runner, record command/exit/digest and validate the patch again after tests (tests cannot silently modify deliverables). Run `python -m unittest tests.test_maintenance_workspace tests.test_maintenance_worker -q` with fake executor.

### Task 6: External Deployment Supervisor

**Files:** create wqb/maintenance_supervisor.py, tests/test_maintenance_supervisor.py; modify wqb/desktop.py, wqb/console_server.py, wqb/runtime_revision.py and their tests.

**Interfaces:** prepare_deployment(source_root: Path, case: dict, test_receipt: dict) -> dict; activate_deployment(receipt: dict, process_controller: object) -> dict. Supervisor receipt records source/patch/protected-contract digests, changed-file backup, owned process identity, intent revision and deployment phase.

- [ ] RED tests for source drift, forged/stale receipts, live POST drain, supervisor crash at each phase, failed health, rollback, user Pause and multiple Console instances sharing one source tree.
- [ ] Acquire workspace-wide deployment lock; stop new submissions, drain and verify every owned worker using that source tree. Never terminate unknown processes; timeout is deployment-blocked. Driver lock alone is insufficient for CLI/other-run consumers.
- [ ] Apply only validated changed files after confirming unchanged baseline, restart verified backend from outside its process, check code fingerprint/state/schema. Restore changed code on failed activation without restoring run events, quota or platform state.
- [ ] Resume only with matching current running intent and original authority/budget. Existing paused runs stay paused. Persist rollback failure as unsafe_to_recover.
- [ ] Run `python -m unittest tests.test_maintenance_supervisor tests.test_desktop tests.test_console_runtime tests.test_runtime_integration -q`.

### Task 7: Console And Whole-Path Acceptance

**Files:** modify wqb/console_state.py, wqb/console_server.py, wqb/console_timeline.py, scripts/verify_runtime_browser.py, docs/operations/user_workflow_manual.md, root milestone.md and todo.md; create tests/test_autonomous_recovery_acceptance.py and update existing Console tests.

**Interfaces:** Console snapshot gains recovery_case_id, recovery_status, reason, last_progress, next_wake, attempts_remaining and evidence; values derive from durable cases only. No internal acknowledgement buttons.

- [ ] RED test fake workflow: transient 429 -> wait -> progress; code fault -> isolated worker -> tested patch -> deployment -> resume; repeated UI refresh emits no API/model jobs. Inject Pause at each boundary and assert no resume/submit.
- [ ] Test failed patch, missing sandbox, exhausted allowance, uncertain submission and external platform outage remain truthful bounded states. Operator does not choose technical gates.
- [ ] Update existing timeline without a layout rewrite. Browser test shows recovery reason/timestamp and Stop/Resume updates without manual refresh.
- [ ] Run full native suite, compileall, diff check, architecture/entry-doc tests and offline browser acceptance. Compare identical 30-candidate request traces before/after, not just unit-test counts. Independent reviewer uses medium effort; fix findings with regression tests.
- [ ] Record supported/unsupported automatic repair cases, actual sandbox/usage enforcement and offline versus live evidence. Update architecture and single todo handoff; do not mark delivery B complete if the worker boundary is unproven.

## Execution And Handoff

### Execution ledger, 2026-10-11

- Subsequent sandbox authorization received. Elevated minimal profile requires :root read; explicit-deny profile triggered ACL refresh that exceeded 30 seconds. Verified and stopped only probe-owned orphan setup child. Added file-backed capture and owned-process-tree timeout cleanup (two RED/GREEN tests) to avoid descendant-held stdout pipes hanging the probe. MXC alternative fails locating a required Windows platform directory (HRESULT 0x80070003); no unrestricted fallback. Focused probe/recovery/architecture/entry-doc suite 30 passed. Patch worker still disabled. Verified current Console through local health/fragments: port 8765, workspace roots, legacy 429 2/3 acknowledgement blocker, no runtime_control. Prioritize deterministic legacy recovery/adoption tests, not automatic code patching for platform throttling. No live platform/model call.

- User selected inline execution. Baseline 50 tests passed. Metrics, shared batch policy and case routing added with observed RED/GREEN cycles. Actual mocked retry-planned path: 30 candidates -> six five-item POSTs, 30 durable in-flight records, compared with prior fifteen two-item submissions. This saves submission requests only, not simulation quota.
- Zero Retry-After poll now sleeps at least one second. Diagnostic HTTP attempts include authentication, retry/error dispatch and sanitized response pacing fields; bounded prefix summary reports truncation explicitly.
- Independent medium-effort review found distinct faults sharing a recovery case. Regression RED -> GREEN with sanitized source/uncertain-attempt fingerprint. Full native suite after fix: 1057 passed in 119.352s. Runtime browser passed offline Resume/SSE/mobile with zero live API; architecture/entry docs 22 passed.
- Delivery A is partial: quota/runtime budget integration, platform capability freshness, threshold-reset redesign and complete recovery projection still pending. Delivery B is not implemented or enabled; persisted ai_diagnosis_pending is not a model call.
- User authorized local non-model sandbox probe including Codex runtime state outside workspace. scripts/probe_maintenance_sandbox.py uses synthetic sentinel files only. Named minimal-read/workspace-write profile failed with "Restricted read-only access requires the elevated Windows sandbox backend". No elevation/install/unrestricted fallback performed. Sandbox and usage prerequisites remain unproven. Official reference documents experimental features.rollout_budget.limit_tokens: https://learn.chatgpt.com/docs/config-file/config-reference . Higher-privilege backend setup requires separate user confirmation.

Recommended: controller implements shared integration inline; medium-effort reviewer audits safety-critical worker/supervisor. Parallel agents may own disjoint metrics/policy tests only after contracts are established. Existing dirty source must be preserved. No automatic Git commits despite generic skill defaults.

After plan approval, first command from BrainWorkflow is `python -m unittest tests.test_workflow_driver tests.test_client tests.test_source_bridge -q` with SystemRoot/windir set to C:\Windows. Then inspect actual active-run evidence and begin Task 1 RED tests. Update root todo after each accepted task or interruption.
