# BrainWorkflow Maintainer Handoff

This document is for future Codex sessions and human maintainers. It replaces dependence on a single long chat thread.

## First Files To Read

Read these before changing behavior:

1. `README.md`
2. `docs/operations/operating_guide.md`
3. `docs/superpowers/specs/2026-07-12-brainworkflow-orchestrator-state-design.md`
4. `docs/superpowers/plans/2026-07-12-brainworkflow-orchestrator-state-implementation.md`
5. Local root recovery anchor: `C:\Users\oytl\Desktop\pyproject\brain\milestone.md`
6. Local task log: `C:\Users\oytl\Desktop\pyproject\brain\todo.md`

If the root recovery files are unavailable, use this document plus the committed tests as the source of truth.

## Spec B Knowledge Contract

Before changing research scheduling, check whether planner inputs are authoritative or seed/cache. The approved Spec B design is `docs/superpowers/specs/2026-07-21-knowledge-workflow-operating-system-design.md`; implementation plan tasks live in `docs/superpowers/plans/2026-07-22-knowledge-workflow-operating-system-implementation.md`.

## Architecture Boundary

Do not rewrite the existing Scout -> Seed -> Discovery -> Repair -> Submit research model casually.

The current long-term architecture is:

```text
Knowledge Maintenance
  -> Planner
  -> Objective
  -> Schedule
  -> Scout/Seed
  -> 30 Alpha Batch
  -> Multisim/Backtest
  -> Triage
  -> Repair
  -> Candidate Gate
  -> User Approval
  -> Approved Candidate Queue
  -> Research Record
```

The Orchestrator owns legal state transitions and durable recovery. Low-level commands may still exist, but they are not the official state owner.

## Extension Workflow

Use small PR-sized loops instead of one long chat:

1. Write or update a short spec in `docs/superpowers/specs/`.
2. Write a concrete implementation plan in `docs/superpowers/plans/`.
3. Add RED tests before production code.
4. Implement one bounded module slice.
5. Run focused tests and full non-live verification.
6. Request a read-only code review.
7. Fix Critical/Important findings.
8. Update this handoff or `operating_guide.md` if the operator workflow changed.

For project continuity, update local `milestone.md` before interruption or handoff.

## Where To Extend

- New workflow state behavior: `wqb/workflow_state.py`, `wqb/orchestrator.py`, `tests/test_workflow_state.py`, `tests/test_orchestrator.py`.
- Candidate approval/queue behavior: `wqb/candidate_queue.py`, `wqb/research_record.py`, `tests/test_candidate_queue.py`, `tests/test_research_record.py`.
- Knowledge readiness and maintenance: `wqb/run_readiness.py`, `wqb/knowledge_bootstrap.py`, `wqb/knowledge_compile.py`, `wqb/knowledge_freshness.py`.
- Research planning: `wqb/research_planner.py`, `wqb/research_scheduler.py`, `wqb/principle_model.py`.
- Console read model: `wqb/console_state.py`, `tests/test_console_state.py`.
- Console UI/server and action layer: `wqb/console_server.py`, `wqb/console_jobs.py`, `wqb/console_context.py`, `wqb/console_proposals.py`.

## Durable Knowledge Base Contract

The active Obsidian vault has three canonical top-level layers:

- `knowledge/raw/`: source materials, platform snapshots, forum/advisor material, user interaction notes, raw research records, and immutable maintenance evidence.
- `knowledge/machine/`: JSON/JSONL resources consumed by code, including data ledgers, template libraries, benchmark rules, freshness manifests, research option cards, and maintenance reports.
- `knowledge/wiki/`: compact human lessons and selected case reports. Wiki pages must carry metadata and backlinks to concrete raw sources.

Research commands should read compiled machine resources and selected wiki lessons. Full source refresh and wiki compilation should be a separate maintenance loop.

## Data Field Coverage Contract

Authoritative data scheduling coverage comes from `knowledge/raw/platform/data_fields/YYYY-MM-DD/` snapshots compiled by `compile-data-ledger`.

The previous `cache-metadata` path is useful for small targeted experiments, but it does not represent all accessible data fields and must not be treated as full coverage.

If a future Codex resumes this work and sees a partial ledger, run or schedule:

```powershell
python -m wqb.cli capture-platform-data-fields --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --enable-live-api
python -m wqb.cli compile-data-ledger --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
```

Knowledge maintenance has three official entry points:

- Research-record compile: raw research records accumulated from completed runs are synced into `machine/research_records.jsonl`; selected human case reports are written under `wiki/60_research_cases/` by `python -m wqb.cli compile-research-records`.
- Platform-material maintenance: after platform data-field raw materials are refreshed, run `compile-data-ledger`, then `compile-knowledge --apply-cleanup`, `knowledge-health-check`, and readiness maintenance before starting a research workflow. Do not run `bootstrap-knowledge` after a data-field refresh because it can replace missing compiled ledgers with schema-seeded partial rows. Use `bootstrap-knowledge` only for initial knowledge-structure recovery.
- Authority and semantic maintenance: research readiness verifies compiled ledger rows against certified canonical raw captures. `knowledge-health-check` includes contract integrity, and `compile-operator-semantics` preserves reviewed rows while merging canonical operators and missing defaults into `machine/operator_ledger.jsonl` plus `machine/previews/operator_semantics.md`.

## Current Known Minor Follow-Ups

The final review of `2711667..974158a` found no Critical or Important issues. Minor polish:

- no-active `workflow-status` can present `consistent=false` because `active_run_missing` remains in diagnostics.

## Verification Baseline

Use this baseline before claiming completion:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
$env:SystemRoot='C:\Windows'
$env:windir='C:\Windows'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
python -m compileall -q wqb tests scripts
```

Latest clean implementation review:

- Range: `f7ae8cb..4214a0e`
- Result: final whole-branch review findings were fixed, and scoped re-review of the final fix found 0 Critical, 0 Important, and 0 Minor issues.
- Full non-live tests: 756 passed
- Additional checks: `python -m compileall -q wqb tests scripts`, `git diff --check f7ae8cb..HEAD`, and the obsolete wiki path scan over production/docs/scripts passed.

## GitHub Sync On Windows

This Codex Windows shell may start without `SystemRoot` and `windir`. When those
variables are missing, Git network operations can fail with WinSock error
`10106` even when the Clash proxy variables are already set. Before `git push`
or `git ls-remote`, set:

```powershell
$env:SystemRoot='C:\Windows'
$env:windir='C:\Windows'
```

The local proxy is normally available at `127.0.0.1:7897`; check the root
`AGENTS.md` before changing proxy settings.

## Console Timeline Maintenance Contract

The Console is a read and control layer. The Orchestrator owns research workflow
state, Console jobs own command execution evidence, and `console_timeline.py`
maps durable state into the timeline rows shown by the page. Keep these
ownership boundaries intact when extending the UI or API.

`/api/state` must remain a deterministic read model. New fields should be
derived from persisted workflow, readiness, job, proposal, and checkpoint data;
do not make a browser request depend on a model call or an unrecorded process
side effect. Existing job records must remain readable across code changes.

Long actions (`bootstrap-knowledge`, `compile-research-records`,
`capture-platform-data-fields`, `compile-data-ledger`, and
`plan-research-options`) must use `start_job_async`. Short local checks may use `run_job`.
When recovering a running job, reconcile `job.json`, PID state, and the
persisted raw, machine, wiki, or run artifacts before retrying it. Capture jobs persist
their target raw capture directory in `job.json`; use that directory rather
than a globally newest capture. Do not launch a second
live capture or compile merely because the browser lost its connection.

Do not put model API calls or model credentials in `console_server.py`. When
GPT/Codex judgment is needed, write an `ai_checkpoints.jsonl` record through
`ai_checkpoints.py`. A later Codex skill or automation runner consumes the
checkpoint, records its decision or proposal, and links the resulting durable
artifact and evidence path. Deterministic actions must remain explicitly
non-AI in labels and behavior.

Workflow proposals and rule evolution are durable project changes, not
transient UI state. Keep the proposal, approval/rejection decision, rationale,
and affected rule or template path in the project records before changing a
workflow rule. Human approval remains required for durable rule changes and
Alpha submission. Preserve append-only records and existing legacy/stage1
archive material; update compiled wiki or benchmark artifacts through their
normal maintenance commands.
