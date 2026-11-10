# Readiness Overrides Source Retry UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure blocked research readiness is the highest-priority local workflow state so Console never exposes a normal source retry while exact-scope data is stale.

**Architecture:** Keep the existing Orchestrator/source bridge modules intact. Add a read-only readiness overlay to workflow status decoration and Console current-work/action authority so the latest blocked readiness report wins over `retry_planned` display and Continue permissions.

**Tech Stack:** Python 3.12, `unittest`, existing `wqb` local workflow modules, Markdown operator documentation.

**Spec:** Operational incident from 2026-09-02: job `20260902-workflow-auto-continue-06975172` returned `readiness_blocked` for `stale_scope_data` while the Console still showed `Retry planned source` with Continue enabled.

## Global Constraints

- Do not call WQB live API in this maintenance task.
- Do not refresh platform data fields in this maintenance task.
- Do not run simulations or submit Alpha.
- Preserve the existing Console layout and primary-button model.
- Readiness blockers must override source bridge retry displays and normal Continue permissions.
- Keep source bridge details available as evidence; do not delete source recovery state.

---

### Task 1: Readiness Blocker Read Model

**Files:**
- Modify: `wqb/workflow_auto_continue.py`
- Modify: `wqb/console_timeline.py`
- Modify: `wqb/console_server.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_console_timeline.py`
- Test: `tests/test_console_server.py`

**Interfaces:**
- Consumes: latest `readiness_report.json` shape with `blocked`, `passed`, and `issues`.
- Produces: `readiness_blocker` dict on decorated workflow status, current-work title `Readiness blocker`, and disabled `continue_workflow`.

- [ ] **Step 1: Write CLI RED test**

```python
def test_workflow_status_readiness_blocker_overrides_source_retry(self):
    # Mock latest readiness as blocked and source bridge as retry_planned.
    # Expected: next_action == "readiness-blocked" and source_bridge remains present.
```

- [ ] **Step 2: Run CLI RED test**

Run: `python -m unittest tests.test_cli.WorkflowOrchestratorCliTests.test_workflow_status_readiness_blocker_overrides_source_retry -v`

Expected: FAIL because `workflow-status` still returns `workflow-auto-continue`.

- [ ] **Step 3: Write Console current-work and button RED tests**

```python
def test_current_work_prioritizes_blocked_readiness_over_source_retry(self):
    # Expected title is "Readiness blocker", not "Retry planned source".

def test_render_dashboard_disables_continue_when_readiness_blocked_even_if_source_retry_exists(self):
    # Expected Continue is disabled and no workflow-auto-continue form is rendered.
```

- [ ] **Step 4: Run Console RED tests**

Run: `python -m unittest tests.test_console_timeline.ConsoleTimelineTests.test_current_work_prioritizes_blocked_readiness_over_source_retry tests.test_console_server.ConsoleServerTests.test_render_dashboard_disables_continue_when_readiness_blocked_even_if_source_retry_exists -v`

Expected: FAIL because source bridge current work and Continue permissions currently win.

- [ ] **Step 5: Implement minimal overlay**

Add a helper that converts blocked readiness into:

```python
{
    "title": "Readiness blocker",
    "status": "blocked",
    "next_action": "readiness-blocked",
    "details": ["stale_scope_data: ..."],
    "evidence_paths": [".../readiness_report.json"]
}
```

Use it before source bridge current-work selection and before normal Continue permission checks.

- [ ] **Step 6: Run focused GREEN tests**

Run: `python -m unittest tests.test_cli tests.test_console_timeline tests.test_console_server tests.test_workflow_auto_continue -v`

Expected: PASS.

- [ ] **Step 7: Verify full local suite**

Run:

```powershell
python -m unittest discover -s tests -q
python -m compileall -q wqb tests scripts
git diff --check
```

Expected: all commands exit 0; CRLF warnings are acceptable.

- [ ] **Step 8: Update handoff docs**

Update `docs/operations/user_workflow_manual.md`, root `todo.md`, root `milestone.md`, repo `todo.md`, and repo `milestone.md` with the readiness override rule and exact next operation command.
