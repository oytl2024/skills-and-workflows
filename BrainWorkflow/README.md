# BrainWorkflow

BrainWorkflow is a maintainable WorldQuant BRAIN research workflow for alpha discovery, simulation, check triage, repair, and knowledge-base iteration.

The project is intentionally principle-led:

1. Refresh current platform rules, activities, Power Pool boards, themes, competitions, and account state.
2. Score current opportunities against long-term consultant incentives and alpha-pool quality principles.
3. Present option cards to the user.
4. Create a concrete execution plan only after the user chooses an option.
5. Run batches, checks, repair, and submission gates with durable experiment and knowledge records.

## Repository Scope

This folder contains the maintainable code and documentation from the local Brain workflow:

- `wqb/`: API client, simulation helpers, benchmark logic, novelty scoring, and workflow utilities.
- `tests/`: unit tests for the maintainable workflow modules.
- `configs/`: editable run configuration.
- `docs/superpowers/specs/`: design specs.
- `docs/superpowers/plans/`: implementation plans.
- `docs/knowledge/`: compact operational rules and foundation notes.
- `../../knowledge/`: shared Obsidian vault for raw material, compiled wiki pages, decision cards, and long-term research memory.

The following local artifacts are intentionally excluded:

- raw `runs/` outputs;
- raw API snapshots and metadata caches;
- temporary folders;
- old root-level semi-automated scripts that may contain hard-coded local assumptions;
- credentials and environment files.

## Credentials

Do not hardcode credentials. The workflow expects WorldQuant BRAIN credentials through environment variables:

```powershell
$env:WQB_USERNAME="..."
$env:WQB_PASSWORD="..."
```

## Knowledge Vault

The local Obsidian vault is outside this repository at `C:\Users\oytl\Desktop\pyproject\brain\knowledge`.
Commands that write knowledge use `BRAIN_KNOWLEDGE_ROOT` when set; otherwise they resolve that shared vault from the current workspace layout.

## Basic Verification

Run from this folder:

```powershell
python -m unittest discover -s tests -v
```

## Orchestrator-First Workflow

Long-term research should start from the Orchestrator commands instead of manually chaining low-level commands.

```powershell
python -m wqb.cli workflow-start --objective "Power Pool" --selected-option-id option-1
python -m wqb.cli workflow-continue
python -m wqb.cli workflow-status
python -m wqb.cli workflow-resume
```

The Orchestrator owns `run_state.json`, `workflow_events.jsonl`, Research Record sync, candidate approval, and approved candidate queue records. Legacy commands remain useful for diagnostics and focused recovery, but they are not the source of official workflow state.

Operational docs:

- `docs/operations/operating_guide.md`: how to run research, readiness, knowledge maintenance, and console state inspection.
- `docs/operations/maintainer_handoff.md`: how future Codex sessions should maintain and extend the project without relying on a long chat context.
- Platform data-field maintenance and selectable console operation are documented in `docs/operations/operating_guide.md`.

## Current Phase

Phase 2 is implementing the principle-led research planner. The active design is:

`docs/superpowers/specs/2026-07-09-wqb-phase2-principle-led-research-workflow-design.md`

The long-term workflow design is:

`docs/superpowers/specs/2026-07-10-long-term-self-optimizing-brain-workflow-design.md`

The foundation implementation plan is:

`docs/superpowers/plans/2026-07-10-long-term-workflow-foundation-implementation.md`

## Long-Term Workflow Foundation

The long-term workflow separates research runs from knowledge maintenance.

Research commands consume compiled knowledge artifacts such as Data Ledger, Template Library, benchmark rules, and principle pages. They should not trigger full Learn/forum/operator recapture or full wiki compilation.

Maintenance commands refresh raw sources, update compiled ledgers, run freshness checks, and generate workflow-change proposals for user review.

Example foundation files live under `docs/knowledge/`:

- `freshness_manifest.example.json`
- `data_ledger.example.jsonl`
- `template_library.example.jsonl`

### Startup Layer

The startup layer separates maintenance from research execution:

- `bootstrap-knowledge` materializes Data Ledger, Template Library, Freshness Manifest, and bootstrap reports into the shared Obsidian vault.
- `compile-research-records` compiles raw research records from completed runs into `wiki/40_experiments/research_record_compile.md`.
- `readiness-check` validates required artifacts, parseability, freshness, batch size, live API permission, and submit confirmation.
- `launch-workflow` writes a run manifest, readiness report, and subagent handoff packets before research execution. In strict research or submit-candidate modes, blocked readiness writes only a blocked readiness report and does not create a run manifest or handoffs.
- `schedule-research` and live simulation/repair commands run the same readiness gate before writing schedules or contacting the API.

Example:

```powershell
python -m wqb.cli bootstrap-knowledge --knowledge-root C:\Users\oytl\Desktop\pyproject\brain\knowledge
python -m wqb.cli compile-research-records --knowledge-root C:\Users\oytl\Desktop\pyproject\brain\knowledge
python -m wqb.cli readiness-check --knowledge-root C:\Users\oytl\Desktop\pyproject\brain\knowledge --readiness-mode plan-only
python -m wqb.cli launch-workflow --workflow-objective current-incentives --workflow-mode plan-only
```

## Workflow Console

The local console is a small standard-library browser UI for operating the existing CLI and Orchestrator without relying on a long chat context.

```powershell
python -m wqb.cli launch-console --knowledge-root C:\Users\oytl\Desktop\pyproject\brain\knowledge --run-dir C:\Users\oytl\Desktop\pyproject\brain\runs --console-port 8765
```

It shows readiness, freshness, research options, current workflow state, job history, and the workflow proposal inbox. Console actions write durable job records under `runs/console_jobs/` and update recovery context files.

Knowledge maintenance is deliberately split:

- Compile research records after research sessions with `compile-research-records`.
- Compile refreshed platform material with `bootstrap-knowledge` and verify with `knowledge-health-check` before starting research.
