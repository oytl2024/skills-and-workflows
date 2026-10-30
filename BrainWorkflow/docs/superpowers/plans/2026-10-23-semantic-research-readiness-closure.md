# Semantic Research Readiness Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close finite Repair, integrated tree testing, total network deadline and desktop deployment-readiness gaps after verified knowledge consumption.

**Architecture:** Extend existing typed Repair provider, runtime/request evidence and owned worker lifecycle; retain the Orchestrator and frozen lane authority. Test through fake transport, then propose a source-bound desktop deployment.

**Tech Stack:** Existing Python312/unittest, React/TypeScript, pywebview/PyInstaller.

**Spec:** ../specs/2026-10-23-full-local-semantic-compile-design.md

## Global Constraints

- Depends on K1-K5 in 2026-10-23-full-local-semantic-compile.md; no invented resource eligibility.
- Research defaults N2,4 initial hypotheses,depth2; Scout cap30 maximum,Seed cap8,lane-independent shared4000/day; preserve original time/recovery/Stop limits.
- No actual WQB/model research/resume/submission during development. Final submission and old-run proof renewal remain separately authorized.
- No additional agent framework, uncontrolled parameter grid or new UI gate clicks.
- Every subagent explicitly medium or lower. Apply TDD and independent review to authority/process changes.

## Review Focus

1. A typed transform changes economic meaning/sign: R1 requires explicit allowed invariant and measured comparison, not generic transformation permission.
2. A cache hit after accepted improvement is attributed to the root: R2 asserts selected parent identity and exact decision lineage.
3. Slow/trickling POST outlives budget while sending thread remains active: R3 terminates only the owned process before releasing the fence.
4. PID is reused or request completed at the deadline: R3 authenticates ownership/nonce and reconciles completion races without replay.
5. New EXE loads old source/config or silently adopts a legacy run: R4 checks actual loaded revision and preserves old mission authority.

## R1: Certified Finite Repair Rules

**Files:** repair_search.py, preplanned_start.py, resource_evidence.py,
semantic_contracts.py, configs/workflow_defaults.example.json;
tests/test_repair_search.py, tests/test_deterministic_repair_integration.py,
tests/test_preplanned_start.py.

**Interface:** add compile_repair_search_policy(resources: dict, project_policy: dict) -> dict
in repair_search.py. Return the existing strict policy schema consumed by
prepare_persisted_search; verified source resources and project finite grids stay distinct.

- [ ] Write tests for sourced MATRIX transform, VECTOR reduction prerequisite, known/unknown cadence, source-backed neutralization setting and unsupported signature rejection.
- [ ] Test preserved economic kernel/typed inputs and exact parent subtree; no automatic sign inversion or changed data/conditions. Reject transforms lacking an explicit supported invariant.
- [ ] Run new tests; observe RED for current Start transform rejection.
- [ ] Compile finite rules from K5-certified traits/signatures and explicit project policy. Use no runtime model calls; unknown exposure/frequency does not become a fact.
- [ ] Remove the blanket Start transform rejection only for compiler-produced policies bound to certified resources. Keep rejection for arbitrary user/model-supplied transform objects.
- [ ] Test finite exhaustion, baseline failures before correlation checks, accepted-incumbent updates, novelty and shared budget; run existing Repair/Seed/Start suites; review/commit.

## R2: Integrated N2/Four-Root/Depth2 Acceptance

**Files:** tests/test_preplanned_research_acceptance.py,
tests/test_deterministic_repair_integration.py, tests/test_console_application_server.py.

**Interfaces:** use real prepare_preplanned_start, group driver, continue_tree,
prepare_seed_selection and deterministic Repair provider; inject only fake model,
HTTP and process transport, not fabricated stage-success receipts.

- [ ] Write one fixture with two distinct sourced datasets, four initial hypotheses per lane and two levels; freeze all possible branches before fake transport starts.
- [ ] Drive strong/weak/opposite-sign cases through both-signal expansion, real reverse confirmation, no-signal fallback, child regression rollback and strict Seed gates/ranking.
- [ ] Add accepted-incumbent then cached-variant scenario; assert exact parent/settings/decision refs, no new POST charge for valid reused evidence and no adoption of unrelated cached rows.
- [ ] Interrupt during planning/POST/recovery/Repair, persist Stop and restart; assert frozen identities, unknown outcomes, group time/recovery and daily accounting remain unchanged. Assert actual Stop state, not merely a generic blocked return.
- [ ] Assert no model call after initial freeze, no internal gate clicks, cheap checks precede self/prod checks and no implicit final submission. Run integrated suite then full discovery; fix only reproduced defects with regressions; review/commit.

## R3: Hard Total Network Deadline With Owned Processes

**Files:** client.py, research_group_driver.py, runtime_control.py,
original_batch_recovery.py, workflow_driver.py;
new tests/test_owned_network_deadline.py,
tests/test_group_runtime_integration.py, tests/test_research_group_driver.py.

**Interfaces:** managed client request lifecycle writes an existing-run-local current
request projection plus immutable events containing request_id, owner nonce,
method/normalized operation, simulation identities and deadline. Never persist
credentials, payload secrets, raw auth URLs or response bodies for supervision.
Add supervise_group_lane(paths, group: Path, run_dir: Path, *, config: dict,
spawn_runner, now_func) -> dict around the existing lane execution body;
the current module owns both supervisor/execute roles and recorded child handles.
No network thread may continue after its fence is considered released.

- [ ] Write fake child-process tests where requests trickle beyond configured total timeout; connection/read timeout alone must fail the new test.
- [ ] Add completion/deadline race, PID reuse, mismatched owner nonce, corrupted deadline, Stop during POST and unknown outcome restart tests. No fixture calls real WQB.
- [ ] Persist authenticated dispatch identity/deadline immediately before request entry, not while waiting for fair admission. Derive total bound from existing validated request_timeout_seconds, further limited by remaining original runtime; do not extend runtime authority.
- [ ] Supervisor retains actual owned process identity/handles and terminates only that owned execution subtree after the bound. Confirm termination before fence acknowledgment/recovery; never kill an unverified PID. Keep outer durable Stop authoritative.
- [ ] On interrupted POST preserve charged/unknown submission identity; reconcile any already persisted valid response/Location before classifying unknown. Do not refund, resubmit or invent failed platform results.
- [ ] Integrate existing paced recovery/blocker notification and Console state. Test source locks/fairness under N1/N2/N4, old-run compatibility and packaging role allowlist; independent review/full regression/commit.

## R4: Offline Package And Explicit Deployment Readiness

**Files:** existing build/entry scripts, desktop_application.py as needed,
operations manual/maintainer handoff, root todo.md/milestone.md;
existing desktop/Console suites and frontend smoke/performance fixtures.

**Interfaces:** same source-bound JSON/SSE and Start/Stop; no new operating controls.
Proposed deployment receipt names EXE revision, source/config/resource identities,
authority exclusions and rollback target before changing formal entry.

- [ ] Run stable full Python/React suites and actual two-lane read-model/browser smoke. Measure UI pending, durable acknowledgment, event-to-view, lane switching and startup separately with stated sample/history sizes.
- [ ] Rebuild final source EXE and verify actual loaded revision/native backend/assets/worker roles in isolated roots; missing runtime/busy port/unowned backend must fail safely.
- [ ] Using K6 actual-vault report, prepare local deployment readiness receipt. Missing source, model allowance, publication or legacy proof remains an explicit blocker, not automatic permission.
- [ ] Obtain any separately required formal-entry/resource activation/old-proof approval before applying that protected operation. Otherwise deliver the verified offline package and exact pending activation, without claiming live-ready completion.
- [ ] On authorized entry migration preserve Stop, accumulated usage and original caps; opening/closing view does not start or stop research. No live simulation is part of deployment verification.
- [ ] Update operator guide and recovery ledger; Git push/equality, audited cleanup and affected regressions. Never delete referenced staged-build/proof evidence merely because a newer version exists.

## Execution Handoff

User approves both written plans before implementation; preserved method is
subagent-driven with explicit medium-or-lower reasoning. K tasks are the first
mainline; R tasks cannot quietly bypass an unresolved knowledge/readiness contract.
If source evidence or finite model budget blocks real compilation, continue safe
offline implementation/tests and report the exact external decision once.
