# Rate-Limit Recovery Acknowledgement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a 429-threshold maintenance blocker explicit and provide a local-only acknowledgement path that can make existing planned source work retryable without contacting the platform.

**Architecture:** Keep automatic recovery blocked when `consecutive_429_count` reaches the threshold. Enrich source bridge metadata and UI wording so operators understand waiting alone will not recover. Add a separate local CLI/Console action that records operator acknowledgement and clears only the local threshold state; actual live retry remains a separate `Continue workflow` action and still cannot perform live field/template/operator discovery.

**Tech Stack:** Python standard library, `unittest`, existing BrainWorkflow Console and CLI modules.

## Global Constraints

- Do not call WQB APIs, submit simulations, import artifacts, or submit Alpha during acknowledgement.
- Do not make waiting alone clear the 429 threshold.
- Do not let `Continue workflow` become enabled while `source_bridge.action=maintenance_blocker`.
- Do not trigger online field, template, operator discovery, or new strategy construction from the acknowledgement action.
- Keep the existing Console layout and primary operation habit: the acknowledgement is an explicit local maintenance action, not hidden inside `Continue workflow`.

---

### Task 1: Explicit Threshold Metadata And UI Explanation

**Files:**
- Modify: `wqb/source_bridge.py`
- Modify: `wqb/console_timeline.py`
- Test: `tests/test_source_bridge.py`
- Test: `tests/test_console_timeline.py`

**Interfaces:**
- Produces: source bridge metadata keys `threshold_reached`, `recovery_eligible`, `operator_acknowledgement_required`, and `operator_message`.
- Produces: Current Work details explaining that cooldown ended but threshold still requires operator acknowledgement.

- [x] **Step 1: Write failing tests**

Add tests asserting an expired cooldown at `3/3` has `threshold_reached=true`, `recovery_eligible=false`, `operator_acknowledgement_required=true`, no rolling `next_check_at`, and a UI detail containing `operator acknowledgement`.

- [x] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_source_bridge tests.test_console_timeline -v`

- [x] **Step 3: Implement minimal metadata and UI details**

Update `_rate_limit_metadata()` and `select_current_work()` to expose the three-state distinction without changing source submission behavior.

- [x] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_source_bridge tests.test_console_timeline -v`

### Task 2: Local-Only Acknowledgement Command

**Files:**
- Modify: `wqb/rate_limit_state.py`
- Modify: `wqb/cli.py`
- Test: `tests/test_rate_limit_state.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `acknowledge_rate_limit_recovery(run_dir: str | Path, reason: str, now: str) -> dict[str, Any]`.
- Produces: CLI command `workflow-acknowledge-source-rate-limit`.

- [x] **Step 1: Write failing tests**

Add tests that acknowledgement writes `status=ready`, clears `consecutive_429_count`, records `acknowledged_at` and `acknowledged_reason`, and CLI resolves the active source run from source bridge without invoking live runners.

- [x] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_rate_limit_state tests.test_cli -v`

- [x] **Step 3: Implement minimal local acknowledgement**

Add the helper and CLI command. The command should inspect local workflow/source state, refuse if no source maintenance blocker is present, reset only the source run rate-limit state, and print JSON evidence.

- [x] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_rate_limit_state tests.test_cli -v`

### Task 3: Console Local Maintenance Action

**Files:**
- Modify: `wqb/console_server.py`
- Modify: `wqb/console_jobs.py`
- Test: `tests/test_console_server.py`
- Test: `tests/test_console_jobs.py`

**Interfaces:**
- Produces: Console form action `workflow-acknowledge-source-rate-limit`.
- Produces: a synchronous local job that runs the CLI acknowledgement command and then reloads the same Console page.

- [x] **Step 1: Write failing tests**

Add tests that the maintenance-blocker UI renders a separate `Acknowledge rate limit recovery` button only when metadata requires acknowledgement, and that the action builds `python -m wqb.cli workflow-acknowledge-source-rate-limit` without `--enable-live-api`.

- [x] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_console_server tests.test_console_jobs -v`

- [x] **Step 3: Implement minimal Console action**

Add the action to the allowed local action list, command builder, and `_render_workflow_progress()` blocker branch. Keep `Continue workflow` disabled until the acknowledgement command has changed local state and the next refresh reports `retry_planned`.

- [x] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_console_server tests.test_console_jobs -v`

### Task 4: Documentation, Recovery Records, And Verification

**Files:**
- Modify: `docs/operations/user_workflow_manual.md`
- Modify: `C:\Users\oytl\Desktop\pyproject\brain\todo.md`
- Modify: `C:\Users\oytl\Desktop\pyproject\brain\milestone.md`

**Interfaces:**
- Produces: durable operator guidance and recovery handoff.

- [x] **Step 1: Update docs**

Document that waiting does not clear thresholded 429 state, explain the local acknowledgement button, and restate that actual live retry is still separate and user-controlled.

- [x] **Step 2: Run verification**

Run:
`python -m unittest tests.test_source_bridge tests.test_console_timeline tests.test_rate_limit_state tests.test_cli tests.test_console_server tests.test_console_jobs -v`
`python -m unittest discover -s tests -q`
`python -m compileall -q wqb tests scripts`
`git diff --check`

- [x] **Step 3: Update milestone/todo and notify operations**

Record evidence, current workflow state, and the exact Console click rule for the operations window.
