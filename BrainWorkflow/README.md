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

## Current Phase

Phase 2 is implementing the principle-led research planner. The active design is:

`docs/superpowers/specs/2026-07-09-wqb-phase2-principle-led-research-workflow-design.md`
