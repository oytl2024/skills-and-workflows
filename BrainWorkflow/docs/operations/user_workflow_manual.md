# BrainWorkflow User Workflow Manual

This is the click-by-click operating manual for using BrainWorkflow without relying on a long Codex chat context.

The short rule: the Console is the control surface, the Orchestrator is the state owner, and Codex is the reasoning/repair worker when the system needs judgment or code changes.

## Mental Model

BrainWorkflow has two separate loops:

- **Operations loop:** run the existing workflow through the Console, watch durable state, approve candidates, and stop for explicit submission authorization.
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
- **Decisions and Approvals:** select a research option, start the workflow, and later record human candidate approvals.
- **AI Checkpoints:** shows where Codex/GPT judgment is needed later. The local Console does not call a model by itself.
- **Knowledge and Data Authority:** confirms whether data is authoritative measured data or only seed/cache scaffolding.
- **Recent Jobs:** durable job records for evidence and maintenance diagnosis; it is not a normal control surface.

## Daily Research Golden Path

1. Open the Console.
2. Check **Objective and Gate Summary**.
3. In **Decisions and Approvals**, select one research option card.
4. Click `Start workflow`.
5. Click `Continue workflow` whenever the Console shows active work or a deterministic next step. For source recovery that contacts the platform, explicitly select `Enable live source recovery` before continuing.
6. Read **Current Work** and **Runtime Timeline** after each action. Source bridge status, cooldown status, and source-run locks are shown there.
7. When candidate approval appears, review the evidence and record the human decision.
8. Use `Stop workflow` only when you want to abort the active workflow non-destructively.
9. Alpha submission is never automatic. It requires explicit user authorization.

Readiness, knowledge compilation, and platform-data refresh are maintenance-only
when the Console records a blocker. Use the command reference in
`docs/operations/operating_guide.md`; they are not top-level daily controls.

## Orchestrator Advance Flow

The normal Console path uses one primary advancement control:

| State | User action | System behavior |
| --- | --- | --- |
| No active workflow | Select one option card, then click `Start workflow` | Creates a durable Orchestrator run. |
| Active workflow | Click `Continue workflow` | Runs the next safe deterministic step. Live source runners remain disabled unless explicitly authorized. |
| Rate limited | After the displayed retry time, select `Enable live source recovery` and click `Continue workflow` | Resumes the persisted planned queue; it does not discard candidates. |
| Waiting for user | Review the approval shown by the Console | Automatic progress stops until the human decision is recorded. |
| User wants to stop | Click `Stop workflow` | Aborts the active workflow non-destructively and preserves evidence. |

Clicking the wrong button should not corrupt state, but repeated no-op clicks mean the Console is not giving a good enough path. Treat that as a workflow UX issue.

## Scout/Seed Recovery

Scout source batches are capped at 30 simulations. Seed refinement batches are
capped at 8 simulations. When Scout/Seed needs source artifacts, the Console
uses the source bridge to choose a safe recovery path. Click `Continue workflow`
and read **Current Work** and **Runtime Timeline**; do not type a source run ID,
copy files, or manually import artifacts during normal operation.

The bridge validates source field, dataset, Scout stage, and selected scope before
binding a source run. The first compatible source selection is persisted under
the active workflow and later recovery cannot switch to a newer sibling run.

If the Console records a maintenance blocker, use the maintenance-only source
recovery commands in `docs/operations/operating_guide.md`. Invalid artifacts,
missing durable evidence, or a repeated unexplained no-op are maintenance issues.

### Source Run Polling And Rate Limits

Live source runs submit simulations to the platform, then poll the returned progress URL. Platform `Retry-After` responses are normal during queueing and rate limiting, but they must leave durable evidence.

Expected behavior:

- Repeated `Retry-After` polling has a bounded wait.
- If the bound is exceeded, the source run records a recoverable `SIMULATION_POLL_TIMEOUT` error in `run_errors.jsonl`.
- The submitted simulation remains visible as in-flight through `simulation_events.jsonl`.
- After the displayed retry time, `Continue workflow` resumes the persisted planned queue without losing candidates.
- Three consecutive 429 responses stop automatic recovery and expose a maintenance blocker. Successful platform progress resets the consecutive counter.

If the browser spinner runs but **Recent Jobs** and `run_errors.jsonl` do not change, treat it as a maintenance bug. The correct fix is a tested workflow/observability repair, not repeated clicking.

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
| Repeated `Continue workflow` gives the same unexplained state | Workflow contract gap | Do not manually recover it; hand it to the maintenance window. |
| Source run polls a simulation for a long time after 429/`Retry-After` | Platform pacing or bounded poll recovery | Wait for the displayed retry time, then click `Continue workflow`. |
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
