# BrainWorkflow User Workflow Manual

This is the click-by-click operating manual for using BrainWorkflow without relying on a long Codex chat context.

The short rule: the Console is the control surface, the Orchestrator is the state owner, and Codex is the reasoning/repair worker when the system needs judgment or code changes.

## Mental Model

BrainWorkflow has two separate loops:

- **Operations loop:** run the existing workflow through Console/CLI, watch durable state, generate source runs, import artifacts, approve candidates, and stop for explicit submission authorization.
- **Maintenance loop:** change code, tests, docs, workflow rules, knowledge structure, or Console behavior when the operations loop exposes a missing button, repeated no-op, confusing state, or broken contract.

Do not mix these loops in one mental stack. A running workflow should not depend on the long chat remembering what happened. It should be recoverable from Console, `run_state.json`, `workflow_events.jsonl`, `runs/console_jobs/`, `todo.md`, and `milestone.md`.

## Start The Console

Run from PowerShell:

```powershell
$env:SystemRoot='C:\Windows'
$env:windir='C:\Windows'
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m wqb.cli launch-console --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --run-dir 'C:\Users\oytl\Desktop\pyproject\brain\runs' --console-port 8765
```

Open:

```text
http://127.0.0.1:8765
```

If the browser does not open, keep the PowerShell window open and paste the URL manually.

## Console Map

- **Objective and Gate Summary:** tells you whether readiness/freshness/data coverage allow research.
- **Runtime Timeline:** shows the workflow stage sequence and which stage is running, paused, blocked, or complete.
- **Current Work:** shows the current job or workflow blocker. Read this before clicking again.
- **Decisions and Approvals:** select a research option, start the workflow, resume/continue, import Scout/Seed artifacts, and later approve candidates.
- **AI Checkpoints:** shows where Codex/GPT judgment is needed later. The local Console does not call a model by itself.
- **Knowledge Maintenance:** run local knowledge compiles and readiness checks; refresh research options only when live API is explicitly enabled.
- **Platform Data:** live-gated platform data capture and local data-ledger compilation.
- **Knowledge and Data Authority:** confirms whether data is authoritative measured data or only seed/cache scaffolding.
- **Recent Jobs:** durable job records. Use this to recover after browser refresh, shutdown, or a stuck spinner.

## Daily Research Golden Path

1. Open the Console.
2. Check **Objective and Gate Summary**.
3. If readiness or knowledge is blocked, use **Knowledge Maintenance** before starting research.
4. If platform data was refreshed, run `Compile data ledger from raw`, then `Compile knowledge`, then `Run readiness check`.
5. In **Knowledge Maintenance**, enable live API only when authorized, then click `Refresh research options`.
6. In **Decisions and Approvals**, select one research option card and one scope.
7. Click `Start selected workflow`.
8. Use `Resume workflow` when `next_action` says `workflow-resume`.
9. Use `Continue workflow` when `next_action` says `workflow-continue`.
10. When Scout/Seed needs `candidates.csv`, generate a source Scout/Seed run, import it, then resume/continue.
11. When candidate approval appears, read candidate evidence and approve only exact candidates you want queued.
12. Alpha submission is never automatic. It requires explicit user authorization.

## Knowledge Maintenance Flow

Use this after research records accumulate or after platform materials/data are refreshed.

Click path:

1. `Compile research records` after completed research runs.
2. `Compile data ledger from raw` after platform data capture.
3. `Compile knowledge` after data/material changes.
4. `Check knowledge health`.
5. `Run readiness check`.

Interpretation:

- Local compile/check buttons do not call the platform API.
- `Refresh research options` can call live API only when its live checkbox is selected.
- `Capture platform data fields` can call live API only when its live checkbox is selected.

If the Console shows stale/missing artifacts, do not start research. Fix maintenance first.

## Platform Data Refresh Flow

Use this only when you intentionally update platform data-field coverage.

Click path:

1. In **Platform Data**, set `fields_per_scope` and `max_scopes`.
2. Check `enable_live_api`.
3. Click `Capture platform data fields`.
4. Watch **Current Work** and **Recent Jobs**.
5. After the job completes, click `Compile data ledger from raw`.
6. Click `Compile knowledge`.
7. Click `Run readiness check`.

Do not launch a second capture because the page spinner is confusing. Check `Recent Jobs` first.

## Research Option Flow

Click path:

1. Check **Knowledge and Data Authority**. Prefer authoritative measured data.
2. In **Knowledge Maintenance**, check `Enable live API` for option refresh only if authorized.
3. Click `Refresh research options`.
4. Read the option cards.
5. Select one card directly on the card.
6. Select one scope.
7. Click `Start selected workflow`.

If cards are missing or options are blocked, this is usually a knowledge/readiness issue, not a simulation issue.

## Orchestrator Advance Flow

The Orchestrator state controls what you click:

| Status / next_action | Click | Meaning |
| --- | --- | --- |
| `none` / `workflow-start` | Select option + `Start selected workflow` | No active run exists. |
| `created` / `workflow-continue` | `Continue workflow` | Move into scheduling. |
| `running` / `workflow-continue` | `Continue workflow` | Advance one legal stage. |
| `paused` / `workflow-resume` | `Resume workflow` | Reopen a paused run without repeating completed work. |
| after resume shows `workflow-continue` | `Continue workflow` | Run the next local stage check. |
| `waiting_for_user` | Candidate approval controls | Human decision required. |
| `failed` / `workflow-abort` | Stop and ask maintenance window | Failure needs diagnosis; do not keep clicking. |

Clicking the wrong button should not corrupt state, but repeated no-op clicks mean the Console is not giving a good enough path. Treat that as a workflow UX issue.

## Scout/Seed Source Run And Import

Scout/Seed needs a run-local `candidates.csv` before the active Orchestrator run can move forward.

Current state of the system:

- The active Orchestrator run owns the official workflow state.
- Existing live Stage 1 / field-batch tools may create a separate timestamped source run.
- The formal bridge is `Import Scout/Seed artifacts`.

Click/operation path:

1. If **Current Work** says `local artifacts required before plan-only stage completion: candidates.csv`, the active run needs Scout/Seed artifacts.
2. Generate a bounded source Scout/Seed run through the workflow runner/Codex automation using the existing live Stage 1 or field-batch command. This is the part still not fully click-only in the current Console.
3. Confirm the source run has a valid `candidates.csv`.
4. In **Workflow Progress**, type the source run id into `Source run ID`.
5. Click `Import Scout/Seed artifacts`.
6. Check **Recent Jobs** for completion.
7. Click `Resume workflow`.
8. Click `Continue workflow`.

If `Import Scout/Seed artifacts` rejects the source run, the source artifacts are invalid or unsafe. The import path rejects empty candidate files, blank identities, existing active-run artifacts, source path escape, symlink directories, and non-regular files.

## Candidate Approval And Submission

Candidate approval is a human decision point.

Rules:

- Only candidates with durable hard-pass evidence should enter the approval queue.
- Approving a candidate is not the same as submitting it.
- Alpha submission requires explicit user authorization.
- If candidate evidence is unclear, stop and ask Codex to explain the candidate, checks, correlations, and remaining risks.

## Where AI/Codex Intervenes

The local Console does not directly call GPT/Codex.

AI/Codex enters through:

- a Codex operations task that runs or monitors the workflow;
- a Codex maintenance task that changes code/docs/tests;
- subagents for bounded review or implementation tasks;
- future automation that consumes `ai_checkpoints.jsonl`;
- explicit user requests for interpretation, proposal generation, repair reasoning, or workflow improvement.

When AI is involved, the Codex app may show:

- a separate task/window for actual workflow operation;
- a separate maintenance/debugging task;
- subagent notifications for review or side tasks;
- a handoff message when an operations task finds a code blocker.

If the Console is only running deterministic jobs, the Codex page may not change. The evidence is in `Recent Jobs`, `run_state.json`, `workflow_events.jsonl`, and `milestone.md`.

## Stuck-State Diagnosis

| What you see | Likely class | What to do |
| --- | --- | --- |
| Button exists, job runs, state advances | Normal operation | Continue following `next_action`. |
| Button exists, job is running | Normal async job | Watch **Current Work** and **Recent Jobs**. |
| Browser spinner but no state change | Observability issue | Check `Recent Jobs`; if no job appears, report Console UX bug. |
| `paused` with `workflow-resume`, but no resume button | Code/UI bug | Maintenance window must add a tested Console action. |
| Repeated `Continue workflow` gives same missing artifact | Workflow contract gap unless the missing artifact is expected | Generate/import the artifact if documented; otherwise maintenance window fixes code/tests. |
| `failed` status | Code/data/platform failure | Stop clicking; inspect diagnostics and hand to maintenance window. |
| Login/API/network error | External state | Fix credentials, platform login, proxy, or retry after platform recovery. |
| Need candidate approval or submit confirmation | Human decision | User must choose; do not automate submission. |

## Code Bug Escalation Rule

Treat the following as code/workflow bugs, not user memory problems:

- the Console shows a `next_action` but has no matching control;
- a button only repeats the same local check without explaining the missing prerequisite;
- an operation requires manual file copying;
- a source artifact exists but cannot be attached to the active run through a formal path;
- a job runs but does not write durable evidence;
- the user needs to ask Codex "what is happening?" for routine progress.

Bug response:

1. Reproduce the stuck state.
2. Add a failing test for the missing control, state transition, or artifact contract.
3. Implement the minimal fix.
4. Run focused tests and non-live verification.
5. Update this manual if the click path changes.

## Current Power Pool Run Recovery

For run `20260811T111506000000-481c3452`:

1. Refresh/restart Console so it includes the latest buttons.
2. Generate a bounded source Scout/Seed run through the workflow runner.
3. Copy no files manually.
4. Import the source run through `Import Scout/Seed artifacts`.
5. Click `Resume workflow`.
6. Click `Continue workflow`.

If any step is unavailable in the Console, that is a maintenance task.
