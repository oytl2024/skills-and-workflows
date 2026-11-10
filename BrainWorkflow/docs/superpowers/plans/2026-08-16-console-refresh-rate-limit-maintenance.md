# Console Refresh And Rate-Limit Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the active maintenance blockers so the operations window can safely resume only when Console state, rate-limit state, and API-boundary provenance agree.

**Architecture:** Keep the existing Console layout and button placement. Add a single local server snapshot contract for refreshed runtime regions and button permissions, classify expired cooldown evidence in `source_bridge`, and add a local-only preflight for source recovery that blocks live field/template/operator discovery unless explicitly waived.

**Tech Stack:** Python standard library, `unittest`, existing BrainWorkflow modules.

## Global Constraints

- Do not change the existing Console UI layout, regions, button positions, or operator habits.
- Do not add platform API calls, data-field discovery, template/operator discovery, simulation, or Alpha submission behavior.
- Red tests must be written and observed failing before production code changes.
- `Continue workflow` must remain disabled for `maintenance-blocker`.
- Expired cooldown alone must not authorize live retry.

---

### Task 1: UI-Preserving Fresh Console Snapshot

**Files:**
- Modify: `wqb/console_server.py`
- Test: `tests/test_console_server.py`

**Interfaces:**
- Produces: `render_runtime_fragments(state: dict[str, Any]) -> dict[str, Any]` with HTML fragments plus `server_revision`, `state_hash`, `allowed_actions`, `last_refreshed_at`, and `refresh_interval_ms`.
- Produces: browser polling that replaces existing runtime fragments and the Workflow Progress controls without changing layout.

- [x] **Step 1: Write failing tests**

Add tests that assert `/api/fragments` includes `workflow_progress`, `allowed_actions`, `state_hash`, `server_revision`, and that dashboard HTML has `data-runtime-fragment='workflow_progress'` while preserving `Workflow Progress`, `Continue workflow`, and `Stop workflow`.

- [x] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_console_server -k "runtime_fragments_include_workflow_progress_permissions_and_revision or render_dashboard_refreshes_workflow_progress_without_layout_change" -v`

- [x] **Step 3: Implement minimal snapshot**

Render Workflow Progress through a helper, lower polling interval to 3000 ms, include metadata in `/api/fragments`, and update JS to apply the new `workflow_progress` fragment while ignoring metadata keys for DOM replacement.

- [x] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_console_server -v`

### Task 2: Cooldown-To-Retryable Source Bridge State

**Files:**
- Modify: `wqb/source_bridge.py`
- Modify: `wqb/console_timeline.py`
- Test: `tests/test_source_bridge.py`
- Test: `tests/test_workflow_auto_continue.py`
- Test: `tests/test_console_timeline.py`

**Interfaces:**
- Produces: source bridge metadata with `retry_at`, `next_check_at`, `evidence_timestamp`, and `consecutive_429_count`.
- Produces: visible state classification: `rate_limit_wait`, `retry_planned`, or `maintenance_blocker` with reason and next check time.

- [x] **Step 1: Write failing tests**

Add tests for expired cooldown at 429 threshold showing `maintenance_blocker` metadata includes `next_check_at` and a reason that says the threshold still blocks retry; add active cooldown metadata tests and timeline detail assertions.

- [x] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_source_bridge tests.test_workflow_auto_continue tests.test_console_timeline -v`

- [x] **Step 3: Implement minimal classification metadata**

Keep threshold as blocker, but attach explicit local evidence fields and next check time. Preserve active cooldown as `rate_limit_wait`; preserve unresolved planned queue as `retry_planned` only when not blocked.

- [x] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_source_bridge tests.test_workflow_auto_continue tests.test_console_timeline -v`

### Task 3: Local-Only Source Recovery API Boundary

**Files:**
- Modify: `wqb/workflow_auto_continue.py`
- Modify: `wqb/console_server.py`
- Test: `tests/test_workflow_auto_continue.py`
- Test: `tests/test_console_server.py`

**Interfaces:**
- Produces: `require_local_source_provenance` behavior before `start_source_batch`.
- Produces: Console refusal if the normal Continue path would allow live source fallback without an explicit local-only source batch runner.

- [x] **Step 1: Write failing tests**

Add tests that `auto_continue_workflow(... enable_live_api=True, source_batch_runner=...)` refuses `start_source_batch` when metadata does not include local field provenance allowing local-only construction.

- [x] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_workflow_auto_continue tests.test_console_server -v`

- [x] **Step 3: Implement minimal preflight**

Require source bridge metadata for `start_source_batch` to include `field_source` in `knowledge/cache`, no live fallback flag, and local operator/template provenance before running the source batch runner. Return `api-boundary-blocker`/`maintenance-blocker` locally when missing.

- [x] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_workflow_auto_continue tests.test_console_server -v`

### Task 4: Documentation, Recovery Records, And Verification

**Files:**
- Modify: `docs/operations/user_workflow_manual.md`
- Modify: `C:\Users\oytl\Desktop\pyproject\brain\todo.md`
- Modify: `C:\Users\oytl\Desktop\pyproject\brain\milestone.md`

**Interfaces:**
- Produces: updated operator guidance and durable recovery handoff.

- [x] **Step 1: Update docs**

Document near-real-time local refresh, stale banner, cooldown state interpretation, and local-only source construction boundary.

- [x] **Step 2: Run focused and full verification**

Run:
`python -m unittest tests.test_source_bridge tests.test_workflow_auto_continue tests.test_console_server tests.test_console_state tests.test_console_timeline -v`
`python -m unittest discover -s tests -q`
`python -m compileall -q wqb tests scripts`
`git diff --check`

- [x] **Step 3: Update milestone/todo**

Record commands, results, changed files, remaining blockers, and exact next operation command.
