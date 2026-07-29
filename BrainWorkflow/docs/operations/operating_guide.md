# BrainWorkflow Operating Guide

This guide is the operator-facing entry point for using BrainWorkflow without relying on a long Codex chat context.

## Current Status

- The durable Orchestrator workflow is implemented.
- The read-only console state aggregator is implemented in `wqb/console_state.py`.
- A first local browser console, action runner, proposal inbox, and context guard are implemented.
- Live WorldQuant BRAIN API work still requires credentials, platform availability, and readiness gates.

## Important Local Paths

- Code repository: `C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow`
- Obsidian knowledge vault: `C:\Users\oytl\Desktop\pyproject\brain\knowledge`
- Default run root: `C:\Users\oytl\Desktop\pyproject\brain\runs`
- Local recovery anchor: `C:\Users\oytl\Desktop\pyproject\brain\milestone.md`
- Local task log: `C:\Users\oytl\Desktop\pyproject\brain\todo.md`

## Daily Research Startup

Run commands from `BrainWorkflow`:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
```

Refresh plan-only readiness:

```powershell
python -m wqb.cli readiness-check --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --readiness-mode plan-only --batch-size 30
```

The canonical runtime benchmark rulebook is
`wiki/50_benchmarks/benchmark_rules.jsonl`. Strict research and
submit-candidate readiness require this file to exist, contain at least one
valid rule, and parse with every required rule field. Rule consumers are
isolated through `consumed_by`; planner or proposal-only rules do not change
triage, repair-loop, or candidate-gate classification.

Generate research option cards from the compiled knowledge base:

```powershell
python -m wqb.cli plan-research-options --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --max-options 5 --option-output-dir 'C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\70_decisions'
```

After choosing an option card, start an Orchestrator-owned workflow:

```powershell
python -m wqb.cli workflow-start --objective "Power Pool" --selected-option-id option-1 --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
```

Advance the workflow one legal step at a time:

```powershell
python -m wqb.cli workflow-continue --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
```

Inspect or resume after interruption:

```powershell
python -m wqb.cli workflow-status --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
python -m wqb.cli workflow-resume --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
```

## Knowledge Maintenance

The research workflow consumes compiled knowledge. It should not recapture all platform documents at every startup.

There are two distinct maintenance situations:

1. **Research-record compile after a research session.** Historical workflow runs write raw research records under `knowledge/raw/research/...`. After enough new research accumulates, manually compile those records into wiki experiment memory:

```powershell
python -m wqb.cli compile-research-records --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
```

2. **Platform-material refresh before new research.** When the user asks to update platform Learn/docs/operators/activities/forum raw material, update the raw source layer first, then run knowledge maintenance before starting research. Research startup consumes the newly compiled wiki, ledger, template, and manifest artifacts rather than raw captures directly.

`bootstrap-knowledge` is an initialization scaffold command. Run it only for a new vault or to recreate missing scaffold files; it preserves existing compiled ledger and template artifacts and does not compile refreshed platform data.

Initial scaffold command:

```powershell
python -m wqb.cli bootstrap-knowledge --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
```

Routine maintenance loop:

```powershell
python -m wqb.cli compile-research-records --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
python -m wqb.cli knowledge-health-check --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
python -m wqb.cli readiness-check --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --readiness-mode maintenance
```

Use the routine loop after a research session or on a scheduled maintenance day. After platform data-field capture, run `compile-data-ledger` before the health and readiness checks below.

## Platform Data Field Maintenance

Use this when the user asks to refresh platform data coverage before research.

Raw capture is a live platform API action and must be run only with explicit authorization via `--enable-live-api`.

Capture raw platform data fields:

```powershell
python -m wqb.cli capture-platform-data-fields --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --enable-live-api
```

If a capture is interrupted, rerun the same command with `--resume-capture`. Completed scopes are retained; failed or started-only scopes are retried.

Compile the data ledger from raw local snapshots. This command is local-only and does not call the platform API:

```powershell
python -m wqb.cli compile-data-ledger --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
```

Then check knowledge health:

```powershell
python -m wqb.cli knowledge-health-check --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
```

Research readiness treats a compiled data-ledger row as authoritative only when its
canonical raw capture contains the matching field and scope, the scope outcome and
manifest are certified complete, and the source date is valid. The health command
also reports wiki metadata, `compiled_from` backlinks, source-index coverage, and
orphan raw sources alongside the existing freshness results.

`compile-operator-semantics` merges canonical operator captures and missing defaults
with the existing reviewed ledger by operator ID. Reviewed records take precedence
and are not discarded by recompilation.

`cache-metadata` remains a targeted exploration command. It is not the authoritative data scheduling ledger.

## Console Research Selection

The normal UI path is:

1. Refresh option cards with live API authorization.
2. Select one research option card in the console.
3. Start workflow from the selected card.
4. Continue the Orchestrator one legal step at a time.

Do not type option IDs manually in normal operation. The console maps the selected card to `workflow-start`.

## Contract Status In The Console

The console distinguishes `seed/cache` data from `authoritative measured` data. Research starts should use authoritative measured data for the selected exact scope. If the console shows only seed/cache rows, run platform data-field maintenance before research.

The Knowledge Contracts panel reports legacy raw paths and missing raw/wiki metadata. These are maintenance issues, not alpha simulation failures.

## Candidate Gate And Submission Records

The Orchestrator owns durable candidate state:

- `run_state.json`: current legal state and next action.
- `workflow_events.jsonl`: append-only workflow events.
- `research_record.json`: human-readable research history and candidate reasoning.
- `approval.jsonl`: user-approved candidates.
- `approved_candidates.jsonl`: approved candidate queue.

Only candidates that pass hard checks should enter approval/submission queues.

Generic candidate status updates cannot mark a candidate as `invalidated`; invalidation uses the dedicated path. Submitted statuses are terminal:

- `manually_submitted`
- `api_submitted`

## Console Status

Implemented:

- `wqb.console_state.load_console_state()`
- active workflow summary;
- readiness, freshness, option cards, schedule preview;
- workflow events and approved queue diagnostics;
- local web server and browser dashboard;
- action buttons for readiness, option refresh, workflow start/continue, platform compile, research-record compile, and knowledge health checks;
- durable job records under `runs/console_jobs/`;
- workflow-change proposal form UI.

Launch:

```powershell
python -m wqb.cli launch-console --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --run-dir 'C:\Users\oytl\Desktop\pyproject\brain\runs' --console-port 8765
```

Safety rules:

- Platform option refresh requires the `enable_live_api` checkbox.
- Workflow start refuses to run from the console when required compiled knowledge is stale or missing; run knowledge maintenance first.
- Submit actions are not auto-triggered by the first console version.

## Minimum Verification

On this Windows setup, direct unittest startup can hit a local `_overlapped` import issue. Use:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
python -m compileall -q wqb tests
```

## Single-Page Workflow Console

Launch the Console from PowerShell. Set `SystemRoot` and `windir` first when
the local Windows shell does not provide them:

```powershell
$env:SystemRoot='C:\Windows'
$env:windir='C:\Windows'
$env:WQB_USERNAME=[Environment]::GetEnvironmentVariable('WQB_USERNAME','User')
$env:WQB_PASSWORD=[Environment]::GetEnvironmentVariable('WQB_PASSWORD','User')
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m wqb.cli launch-console --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --run-dir 'C:\Users\oytl\Desktop\pyproject\brain\runs' --console-port 8765
```

Open `http://127.0.0.1:8765`. The page is the normal operating surface:

1. Read `Objective and Gate Summary` for the active objective and readiness blockers.
2. Check `Runtime Timeline` for running, waiting, blocked, and completed stages.
3. Inspect `Current Work` for async job progress, status, and evidence paths.
4. Use `Decisions and Approvals` for research option selection and proposal review.
5. Use `AI Checkpoints` to see where later GPT/Codex judgment is required.

The page state is served by `/api/state`. Refreshing it is a read operation;
long actions create an async Console job and return a job identifier instead of
blocking the browser request. Inspect the job record under
`runs/console_jobs/<job-id>/job.json` when recovering an interrupted action.

Live API actions require their explicit checkbox. Deterministic checks,
captures, compiles, readiness gates, and job monitoring do not imply GPT/Codex
work. The local server must not call model APIs directly. Model work is recorded
durably in `ai_checkpoints.jsonl` for a later Codex agent or automation runner to
consume and write back with evidence. Alpha submission still requires user
approval.
