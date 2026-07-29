# Workflow Console Single-Page Timeline Design

Date: 2026-07-30
Status: user-approved direction, ready for implementation planning

## Purpose

BrainWorkflow already has durable workflow state, readiness gates, knowledge maintenance commands, platform data capture, research option cards, proposal records, and a first local Console. The current Console is operational, but it still feels like a set of backend panels. During a long platform data capture, the browser keeps spinning and the user has to ask Codex what is happening.

This spec defines a narrower, more useful Console slice:

- one page as the only normal operating surface;
- a visual runtime timeline that explains what is running, why it is running, and what happens next;
- asynchronous long jobs with live progress polling;
- explicit labels for deterministic workflow actions and GPT/Codex judgment checkpoints;
- no changes to the existing Knowledge Maintenance -> Planner -> Scout -> Seed -> Discovery -> Repair -> Submit research framework.

## Current Baseline

Relevant files:

- `wqb/console_server.py`: renders the current HTML pages and handles form posts.
- `wqb/console_jobs.py`: creates durable job directories and currently runs CLI commands synchronously with `subprocess.run`.
- `wqb/console_state.py`: aggregates readiness, freshness, coverage, option cards, jobs, workflow events, proposals, and approved queue state.
- `wqb/workflow_state.py`, `wqb/workflow_events.py`, and `wqb/orchestrator.py`: own the durable research workflow state.

Observed UX failures:

- The page is organized by backend module names rather than the user's workflow.
- The main screen contains too many similarly weighted panels.
- Long actions block the HTTP POST, so the browser spinner becomes the only progress signal.
- `stdout.txt`, `stderr.txt`, and `summary.md` are written only after a child process exits.
- The UI does not tell the user where GPT/Codex judgment is expected.
- Proposal review is on a second route; normal use should not require leaving the control page.

## Design Grounding

Subject: a local research-operations console for WorldQuant BRAIN alpha workflow control.

Audience: one consultant running the workflow and future Codex maintainers who need durable state rather than chat memory.

Single job of the page: show the current workflow state, the next legal action, running job progress, and decision points clearly enough that the user does not need to ask Codex for routine status.

The UI should feel like a research instrument: restrained, dense, explicit, and evidence-backed. It is not a dashboard for decoration, and it is not a landing page.

## Visual Plan

Palette:

- `ink-900 #151922`: primary text and top bar.
- `paper-050 #F7F8FA`: app background.
- `line-200 #D7DDE5`: borders and rails.
- `cyan-600 #087C8F`: current stage and selected action.
- `green-600 #2E7D4F`: passed and completed states.
- `amber-500 #B7791F`: waiting, stale, or needs attention.
- `red-600 #B42318`: blocked or failed states.

Type:

- UI text: Segoe UI, system fallback.
- Compact state labels: Segoe UI Semibold.
- IDs, paths, counts, and commands: Consolas or a monospace fallback.

Layout concept:

```text
+--------------------------------------------------------------------------------+
| BrainWorkflow Control Center     current stage | elapsed | next safe action     |
+--------------------------------------------------------------------------------+
| Objective and Gate Summary                                                        |
| active goal, why it matters, blockers, approval requirements                      |
+----------------------------+---------------------------------------------------+
| Runtime Timeline           | Current Work                                      |
| stage rail with statuses   | job progress, evidence paths, logs, next action   |
|                            |                                                   |
+----------------------------+---------------------------------------------------+
| Decisions, Proposals, and AI Checkpoints                                          |
| option choice, approvals, proposal inbox, GPT/Codex judgment tasks               |
+--------------------------------------------------------------------------------+
```

Signature element: the `run tape`, a vertical timeline where every stage is a durable event-backed row. It is not decoration. It is the page's source of orientation.

Self-critique:

- The palette avoids a generic one-hue dashboard by using neutral structure plus distinct semantic colors.
- The design spends its visual emphasis on the timeline only; other panels stay quiet.
- Since this is an operational tool, type scale is compact and stable rather than hero-sized.

## Single-Page Information Architecture

The normal route `/` renders the full control surface. A separate raw JSON route is allowed for polling, but not for normal user navigation.

### 1. Objective And Gate Summary

Top band content:

- active objective or `No active workflow`;
- current workflow stage;
- elapsed time for active run or active job;
- next legal action;
- whether the system is waiting for user approval;
- most important blocker, if any;
- one primary button that performs the next safe action when available.

This band answers: "What should I pay attention to now?"

### 2. Runtime Timeline

Timeline rows are derived from durable state and event sources:

- environment and credentials readiness;
- knowledge health;
- platform data capture;
- data ledger compile;
- research option generation;
- user research decision;
- workflow start;
- Scout;
- Seed;
- 30-alpha batch construction;
- multisim/backtest;
- triage;
- Repair;
- submit review;
- user submission approval;
- knowledge compile.

Each row shows:

- status: not started, ready, running, waiting, blocked, completed, failed;
- source: deterministic code, user approval, or GPT/Codex judgment;
- started time, finished time, and elapsed time when available;
- key evidence path;
- one short plain-language explanation.

The timeline should be stable in size so counts, labels, and job status changes do not shift the layout.

### 3. Current Work Panel

This panel expands the active timeline row.

For a platform data capture it shows:

- job ID;
- PID;
- elapsed time;
- last observed write time;
- raw capture directory;
- `scopes.jsonl`, `data_sets.jsonl`, `data_fields.jsonl`, and `errors.jsonl` counts;
- current file sizes;
- whether stdout/stderr are still pending because the child process has not exited.

For readiness or compile actions it shows:

- command name;
- exit code when complete;
- report path;
- blocked issue count and warning count;
- exact next corrective action.

For workflow stages it shows:

- run ID;
- current Orchestrator stage;
- latest workflow events;
- research record path;
- approved queue status.

### 4. Decisions And Approvals

Research options are selectable cards on the same page. The user never has to type an option ID for normal use.

Required user approvals remain visible but explicit:

- live API capture authorization;
- high-cost all-scope capture authorization;
- research objective choice when multiple options are valid;
- Alpha submission approval;
- durable workflow-rule proposal approval.

Proposal creation and proposal decisions move into an inline section on the same page, using select controls and text areas. The second `/proposals` route can remain as a compatibility route, but it is not the primary workflow.

### 5. AI Checkpoints

The page must show where GPT/Codex judgment is used.

Deterministic actions do not call GPT:

- checking readiness;
- reading job status;
- polling raw capture counts;
- compiling ledgers;
- rendering stale/missing files;
- starting or continuing existing CLI commands;
- checking active process state.

GPT/Codex judgment checkpoints are:

- explain a blocker and propose the smallest repair path;
- choose research objective from incentives, activity rules, data coverage, and template novelty;
- map data semantics to economic hypotheses and template families;
- innovate a low-correlation template variant;
- diagnose near-miss Alpha failures and recommend repair levers;
- write a workflow-rule proposal after repeated failures;
- compile research records and platform updates into the wiki.

In this implementation slice, the Console does not embed a model API key and does not call GPT directly. Instead, it writes and displays durable `ai_checkpoint` records that the Codex agent skill or a later automation runner can consume. Until that runner exists, the page clearly labels such checkpoints as `AI judgment required` rather than hiding them.

## Async Job Model

Long actions must not block the browser request.

### Job Lifecycle

`console_jobs.py` gains an asynchronous execution path:

```text
created -> running -> completed
created -> running -> failed
created -> refused
created -> running -> timed_out
created -> running -> detached
```

`detached` means the Console lost the child-process handle after a server restart or crash and can only report persisted evidence and whether the PID still exists.

### Job Record Additions

Existing job records remain readable. New records add:

- `started_at`;
- `finished_at`;
- `pid`;
- `duration_seconds`;
- `last_progress_at`;
- `progress_kind`;
- `progress`;
- `status_message`.

The `progress` field is action-specific and JSON-safe.

For `capture-platform-data-fields`, progress includes:

- `capture_dir`;
- `scope_rows`;
- `data_set_rows`;
- `data_field_rows`;
- `error_rows`;
- `data_fields_bytes`;
- `last_write_at`;
- `manifest_status` when manifest exists.

### Server Behavior

`POST /actions/run` should:

1. validate the action and create the job;
2. start the child command with `subprocess.Popen`;
3. redirect back to `/` immediately;
4. let a background watcher finalize `stdout.txt`, `stderr.txt`, `summary.md`, and `job.json`.

`GET /api/state` returns the same read model as the page plus refreshed job progress. The page polls this endpoint every few seconds and updates the timeline without a full reload.

If JavaScript is unavailable, the page still works through manual refresh and durable job files.

### Running Job Reconciliation

When loading Console state, the system reconciles running jobs:

- if the PID is alive, keep status `running` and compute progress from files;
- if the PID is gone and the watcher wrote an exit code, show the terminal status;
- if the PID is gone without terminal evidence, mark `detached` and show the latest durable files;
- never mark a job completed only because a file exists.

## Action Grouping

The single page exposes actions by workflow meaning:

1. Maintain knowledge
   - check knowledge health;
   - compile research records;
   - capture platform data fields;
   - compile data ledger from raw;
   - refresh research options.

2. Start or continue research
   - select an option card;
   - select a measured scope from available data;
   - start workflow;
   - continue workflow.

3. Review decisions
   - review blockers;
   - approve or reject workflow-rule proposals;
   - review candidate queue;
   - approve Alpha submission.

Raw command details, paths, and JSON diagnostics should be available inside compact `details` blocks on the same page.

## Error Copy

The Console should use direct operational language:

- "Platform data capture is running. The browser request has returned; progress is shown below."
- "Research cannot start because the selected scope has no measured platform data ledger."
- "This action needs live API authorization. Enable it only when you intend to contact WorldQuant BRAIN."
- "GPT/Codex judgment is needed to explain this blocker. The checkpoint has been recorded."
- "The job ended without a watcher result. Check the evidence files before rerunning."

Errors should name the file, action, or approval that fixes the state.

## Data Flow

```text
CLI command
  -> console job record
  -> stdout/stderr/summary files
  -> raw/wiki/run artifacts
  -> console_state read model
  -> timeline rows
  -> page + /api/state
```

AI checkpoints follow a separate durable path:

```text
blocker or repeated pattern
  -> ai_checkpoint.jsonl
  -> Console displays required judgment
  -> Codex agent skill consumes checkpoint
  -> proposal, explanation, template idea, or wiki compile artifact
  -> workflow_events.jsonl and knowledge wiki
```

## Acceptance Criteria

- The main Console route renders one page with no required navigation for normal operation.
- The page contains a stable runtime timeline.
- A long action such as platform data capture returns immediately and shows progress from persisted files.
- The page can explain the current capture state without consulting Codex chat.
- Existing job records remain readable.
- Research option cards are directly selectable.
- Proposal review is visible on the main page.
- GPT/Codex intervention points are labeled, and deterministic actions are not mislabeled as AI work.
- The existing research workflow framework is unchanged.
- No live simulation or Alpha submission behavior changes in this slice.

## Testing Strategy

Use standard-library `unittest`.

Required tests:

- `test_console_jobs.py`
  - async job creation records PID and returns before command completion;
  - completed async job writes stdout, stderr, summary, exit code, and terminal status;
  - detached job reconciliation does not claim success;
  - capture progress probe counts raw JSONL files and bytes.

- `test_console_state.py`
  - timeline rows are produced from readiness, data coverage, jobs, active workflow, workflow events, and proposals;
  - running data capture appears as the current work item;
  - AI checkpoints appear as judgment rows.

- `test_console_server.py`
  - main page renders the Objective/Gate Summary, Runtime Timeline, Current Work, Decisions, and AI Checkpoints;
  - `POST /actions/run` redirects immediately for long actions;
  - `/api/state` returns JSON state for polling;
  - option cards remain selectable controls.

Minimum verification:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
python -m compileall -q wqb tests
git diff --check
```

## Documentation Updates

Update the operating docs to explain:

- how to launch the Console with the Windows `SystemRoot` and `windir` environment patch when needed;
- how to read the single-page timeline;
- how to monitor running captures;
- which actions contact the live platform;
- where GPT/Codex judgment checkpoints appear;
- how future agent-skill automation can consume the same durable state.

## Non-Goals

- No frontend framework migration.
- No multi-page app redesign.
- No change to Scout, Seed, Discovery, Repair, or Submit logic.
- No live simulation execution.
- No automatic Alpha submission.
- No direct model API integration inside the local HTTP server.
- No deletion of legacy or stage1 archive material.

## Spec Self-Review

- Completion-marker scan: clean.
- Scope check: focused on the Console control surface and async job observability.
- Consistency check: Orchestrator remains the owner of research workflow state; Console remains a local control and observation layer.
- Ambiguity check: "automatic AI use" means durable checkpoints for an agent runner, not hidden GPT calls from the local HTTP server in this slice.
