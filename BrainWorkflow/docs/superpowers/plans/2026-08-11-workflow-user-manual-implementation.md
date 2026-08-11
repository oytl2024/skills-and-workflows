# Workflow User Manual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BrainWorkflow operable without relying on a long Codex chat by documenting the full console workflow and fixing the immediate missing Resume action.

**Architecture:** Keep the Console as a deterministic control surface over persisted workflow state. Document user operations separately from maintainer handoff material, and make the root agent rules preserve the split between actual workflow operation and project maintenance/iteration.

**Tech Stack:** Python standard-library console server, unittest, Markdown operations docs, root `AGENTS.md` project rules.

## Global Constraints

- Do not run live WorldQuant BRAIN simulations or Alpha submission while writing this documentation.
- Keep Orchestrator as the owner of legal workflow state.
- Keep Console actions as deterministic CLI wrappers; no model calls from `console_server.py`.
- Root `todo.md` and `milestone.md` are local recovery artifacts and must not be committed.
- Root `AGENTS.md` is a workspace rule file, not part of the `skills-and-workflows` Git repository.

---

### Task 1: Expose Resume Workflow In Console

**Files:**
- Modify: `BrainWorkflow/wqb/console_jobs.py`
- Modify: `BrainWorkflow/wqb/console_server.py`
- Modify: `BrainWorkflow/tests/test_console_server.py`

**Interfaces:**
- Consumes: `workflow-resume` CLI command already implemented by `wqb.cli`.
- Produces: Console action `workflow-resume` that maps to `python -m wqb.cli workflow-resume --knowledge-root <knowledge> --run-dir <runs>`.

- [ ] **Step 1: Write the failing console command test**

Add a test that calls `build_action_command("workflow-resume", paths, {})` and expects the command list to include `workflow-resume`, `--knowledge-root`, and `--run-dir`.

- [ ] **Step 2: Write the failing dashboard test**

Add a test that renders an active paused workflow and expects a `value="workflow-resume"` form and button text `Resume workflow`.

- [ ] **Step 3: Run tests to verify RED**

Run:

```powershell
$env:SystemRoot='C:\Windows'; $env:windir='C:\Windows'
python -m unittest tests.test_console_server.ConsoleServerTests.test_workflow_resume_action_builds_command tests.test_console_server.ConsoleServerTests.test_render_dashboard_exposes_resume_workflow_control -v
```

Expected: failures because the action and button do not exist.

- [ ] **Step 4: Implement minimal console action and button**

Add `workflow-resume` to `wqb.console_jobs.build_cli_command()` and add a `Resume workflow` form near `Continue workflow` in `wqb.console_server.render_dashboard()`.

- [ ] **Step 5: Run focused and related tests**

Run:

```powershell
$env:SystemRoot='C:\Windows'; $env:windir='C:\Windows'
python -m unittest tests.test_console_server tests.test_console_jobs -q
```

Expected: all console tests pass.

### Task 2: Write Operator-Facing Workflow Manual

**Files:**
- Create: `BrainWorkflow/docs/operations/user_workflow_manual.md`
- Modify: `BrainWorkflow/docs/operations/operating_guide.md`

**Interfaces:**
- Consumes: Existing Orchestrator/Console behavior and known run-state fields: `status`, `current_stage`, `next_action`, `pause_reason`, `Current Work`, `Runtime Timeline`, `Recent Jobs`, `AI Checkpoints`.
- Produces: A user manual that explains all normal click paths, what to do when paused, and when the issue is code instead of user operation.

- [ ] **Step 1: Write the manual**

Create a Chinese user manual with sections:

- Purpose and mental model.
- Console quick start.
- One-page console map.
- Golden path for daily research.
- Knowledge maintenance flow.
- Platform data refresh flow.
- Research option selection flow.
- Orchestrator advance/resume/continue flow.
- Scout/Seed source run and artifact import flow.
- Candidate approval/submission boundary.
- AI intervention and what changes in Codex.
- Stuck-state diagnosis table.
- Escalation rule: no button, repeated no-op, or state/action mismatch is a code/workflow bug requiring tests.

- [ ] **Step 2: Link from operating guide**

Add a short section near the top of `operating_guide.md` pointing operators to `user_workflow_manual.md` as the click-by-click guide.

- [ ] **Step 3: Verify docs are discoverable**

Run:

```powershell
rg -n "user_workflow_manual|Resume workflow|Scout/Seed artifacts|代码/工作流" BrainWorkflow/docs/operations
```

Expected: references appear in the manual and operating guide.

### Task 3: Add Human/AI Context Management Rule To Root Agents

**Files:**
- Modify: `C:\Users\oytl\Desktop\pyproject\brain\AGENTS.md`
- Modify: `BrainWorkflow/docs/operations/maintainer_handoff.md`

**Interfaces:**
- Consumes: Existing Milestone Recovery and Knowledge Readiness rules.
- Produces: A global project rule requiring separation of workflow operation from project maintenance/iteration.

- [ ] **Step 1: Update root AGENTS.md**

Add a section explaining:

- Run operations and maintenance/iteration are separate loops.
- The operations loop should use Console/CLI, durable state, and small prompts.
- The maintenance loop should fix code/docs/tests, update specs/rules, and hand changes back.
- A console no-op or missing button is a workflow contract bug, not a user memory problem.
- Long-term principle: move repeated human-AI explanations into durable UI/docs/tests rather than relying on chat context.

- [ ] **Step 2: Update maintainer handoff**

Add the same principle in maintainer language and point to the new manual.

- [ ] **Step 3: Verify rule placement**

Run:

```powershell
rg -n "Operation And Maintenance Separation|user_workflow_manual|workflow contract bug|context" C:\Users\oytl\Desktop\pyproject\brain\AGENTS.md BrainWorkflow/docs/operations/maintainer_handoff.md
```

Expected: the new rule and links are present.

### Task 4: Final Verification And Commit

**Files:**
- Modified files from Tasks 1-3.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: pushed repository commit for code/docs, plus local root `AGENTS.md` update.

- [ ] **Step 1: Run focused tests**

```powershell
$env:SystemRoot='C:\Windows'; $env:windir='C:\Windows'
python -m unittest tests.test_console_server tests.test_console_jobs -q
```

- [ ] **Step 2: Run compile check**

```powershell
$env:SystemRoot='C:\Windows'; $env:windir='C:\Windows'
python -m compileall -q wqb tests scripts
```

- [ ] **Step 3: Run doc/rule grep checks**

```powershell
rg -n "user_workflow_manual|Resume workflow|Operation And Maintenance Separation|workflow contract bug" BrainWorkflow/docs C:\Users\oytl\Desktop\pyproject\brain\AGENTS.md
```

- [ ] **Step 4: Commit repository files only**

```powershell
git add BrainWorkflow/wqb/console_jobs.py BrainWorkflow/wqb/console_server.py BrainWorkflow/tests/test_console_server.py BrainWorkflow/docs/operations/user_workflow_manual.md BrainWorkflow/docs/operations/operating_guide.md BrainWorkflow/docs/operations/maintainer_handoff.md BrainWorkflow/docs/superpowers/plans/2026-08-11-workflow-user-manual-implementation.md
git commit -m "document workflow operation guide"
git push
```

Do not commit root `AGENTS.md`, root `todo.md`, root `milestone.md`, or repo-root recovery files.

## Self-Review

- Spec coverage: The plan covers the immediate console Resume bug, the requested user manual, and the global agent-rule update.
- Placeholder scan: No TBD/TODO placeholders remain.
- Type consistency: Console actions consistently use `workflow-resume`, `workflow-continue`, and `workflow-import-scout-seed-artifacts`.
