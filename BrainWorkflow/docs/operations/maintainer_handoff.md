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
- Knowledge readiness and maintenance: `wqb/run_readiness.py`, `wqb/knowledge_bootstrap.py`, `wqb/knowledge_freshness.py`.
- Research planning: `wqb/research_planner.py`, `wqb/research_scheduler.py`, `wqb/principle_model.py`.
- Console read model: `wqb/console_state.py`, `tests/test_console_state.py`.
- Future console UI/server: implement from the existing console spec and plan, starting with read-only pages before write actions.

## Durable Knowledge Base Contract

The Obsidian vault follows a raw-to-wiki pattern:

- `knowledge/raw/`: source materials and daily research records.
- `knowledge/wiki/00_principles/`: durable principles.
- `knowledge/wiki/10_foundations/`: platform foundations, checks, activities.
- `knowledge/wiki/20_semantics/`: data ledger, operators, datasets.
- `knowledge/wiki/30_templates/`: template library and template families.
- `knowledge/wiki/40_experiments/`: research session notes.
- `knowledge/wiki/50_benchmarks/`: signal, correlation, novelty, repair benchmarks.
- `knowledge/wiki/60_workflows/`: workflow contracts and optimization backlog.
- `knowledge/wiki/70_decisions/`: option cards, schedules, readiness outputs.
- `knowledge/wiki/80_maintenance/`: freshness manifest and health checks.
- `knowledge/wiki/90_index/`: glossary, open questions, health check index.

Research commands should read compiled wiki artifacts. Full source refresh and wiki compilation should be a separate maintenance loop.

## Current Known Minor Follow-Ups

The final review of `2711667..974158a` found no Critical or Important issues. Minor polish:

- successful raw sync retry after `completed_with_warnings` could promote status to `completed`, or the console should explain historical warning status;
- no-active `workflow-status` can present `consistent=false` because `active_run_missing` remains in diagnostics.

## Verification Baseline

Use this baseline before claiming completion:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
python -m compileall -q wqb tests
```

Latest clean implementation review:

- Range: `2711667..974158a`
- Result: 0 Critical, 0 Important
- Full non-live tests: 418 passed
