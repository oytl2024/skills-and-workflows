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

Manual maintenance loop:

```powershell
python -m wqb.cli bootstrap-knowledge --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
python -m wqb.cli knowledge-health-check --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
python -m wqb.cli readiness-check --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --readiness-mode maintenance
```

Use this after a research session, after platform rule/activity changes, or on a scheduled maintenance day.

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
