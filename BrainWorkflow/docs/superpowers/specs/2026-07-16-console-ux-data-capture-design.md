# BrainWorkflow Console UX And Full Data Field Capture Design

Date: 2026-07-16
Status: user-approved design direction, pending implementation plan

## Purpose

BrainWorkflow already has a durable Orchestrator, knowledge maintenance commands, and a first local console. The current console is operational but not yet a usable research control surface: it mixes modules, requires manual option IDs, and hides the difference between partial cached data and platform-wide data coverage.

This spec defines the next console and knowledge-data maintenance slice:

- redesign the local console so the user can understand what each module does;
- make research choices selectable from option cards or explicit option lists, not free-text IDs;
- capture all accessible platform data fields into the Obsidian raw layer, then compile the data ledger from raw evidence;
- preserve the existing Scout -> Seed -> Discovery -> Repair -> Submit research workflow and Orchestrator ownership model.

## Current Baseline

Relevant implementation files:

- `wqb/console_server.py`: local HTML server, dashboard renderer, action routing.
- `wqb/console_jobs.py`: durable local job records and action-to-CLI mapping.
- `wqb/console_state.py`: read model for readiness, freshness, option cards, jobs, active workflow, approvals, and proposals.
- `wqb/data_catalog.py`: bounded platform data-set, data-field, and operator fetch helpers.
- `wqb/data_ledger.py`: compiled scheduling ledger model and scoring.
- `wqb/knowledge_bootstrap.py`: schema-seeded bootstrap that currently writes partial data ledger rows.
- `wqb/cli.py`: CLI entry points, including `cache-metadata`, `bootstrap-knowledge`, `compile-research-records`, `plan-research-options`, and `workflow-start`.

Observed gaps:

- `workflow-start` in the console asks for `objective` and `selected_option_id` manually.
- Research option cards are rendered as a plain list, not as selectable decisions.
- The current `data_ledger.jsonl` is a small USA/D1 cache-derived ledger, not a full platform data inventory.
- `cache-metadata` writes local cache files and is useful for targeted exploration, but it is not a formal raw-to-wiki knowledge maintenance workflow.
- `bootstrap-knowledge` can overwrite ledger artifacts with schema-seeded partial rows, which is useful for initial structure but insufficient for real scheduling.

## Design Grounding

Subject: a local quantitative research operations console for WorldQuant BRAIN workflow control.

Audience: one consultant and future Codex maintainers who need to resume and extend the project without relying on chat context.

Single job of the console: show the next legal research or maintenance action, make the user choose from durable options, and write every action as recoverable state.

The UI should feel like a quiet research instrument, not a landing page or marketing app. It should be dense, legible, stateful, and explicit about evidence paths.

## UX Direction

### Visual System

The console remains a lightweight local web app implemented in Python standard-library HTML rendering for this slice. No React or frontend build pipeline is introduced yet.

Palette:

- `graphite-900 #18202A`: headings and primary text.
- `graphite-050 #F6F7F9`: app background.
- `steel-200 #D9E0E8`: borders and dividers.
- `teal-600 #167C80`: selectable/ready state.
- `amber-500 #B7791F`: stale, waiting, warning state.
- `red-600 #B42318`: blocked or failed state.

Type:

- Display/section labels: Segoe UI Semibold, compact and restrained.
- Body/control text: Segoe UI regular.
- Data, IDs, paths, commands: Consolas or a monospace fallback.

Layout concept:

```text
+------------------------------------------------------------------+
| BrainWorkflow Console                 readiness | freshness | run |
+-------------------+----------------------------------------------+
| Research Start    | Current Decision                             |
| Workflow Progress | selectable option cards / explicit controls   |
| Knowledge         |                                              |
| Data Coverage     |                                              |
| Proposals         |                                              |
+-------------------+----------------------------------------------+
| Recent jobs and evidence paths span the bottom when useful.       |
+------------------------------------------------------------------+
```

Signature element: a "ledger strip" at the top that summarizes the durable state chain: raw captured -> wiki compiled -> readiness clean -> option chosen -> workflow active. This is not decoration; it is the operating contract.

### Information Architecture

The console has five primary areas:

1. `Research Start`
   - Show latest option cards.
   - Let the user select exactly one card.
   - Start workflow only from a selected card and clean freshness state.
   - If there are no cards, show a disabled start area and a clear action to refresh options.

2. `Workflow Progress`
   - Show active run ID, current stage, next action, waiting-for-user status, approved queue count, and recent workflow events.
   - Provide continue/status/resume buttons when legal.

3. `Knowledge Maintenance`
   - Separate research-record compile from platform-material/data refresh.
   - Show whether compiled artifacts are stale or missing.
   - Provide local-only compile actions separately from live API refresh actions.

4. `Data Coverage`
   - Show raw platform data-field snapshot status: latest capture date, scope count, dataset count, field count, and compile status.
   - Provide a live-API-gated "capture platform data fields" action.
   - Provide a local "compile data ledger from raw" action.

5. `Proposal Inbox`
   - Keep workflow change proposals visible.
   - Use structured select controls for issue type and affected module.

### Interaction Rules

- The normal path never asks the user to type `option-1`, an objective string, region, delay, or universe.
- Option cards are rendered as selectable controls. The selected card supplies `selected_option_id`, primary incentive, and candidate scope.
- If a workflow path does not use option cards, the user still chooses from explicit lists loaded from compiled knowledge or config defaults.
- Free text is allowed only for proposal summaries and optional notes, not for core workflow routing.
- Live API actions require an explicit checkbox or equivalent confirmation before creating a job.
- All console actions continue to create durable job records under `runs/console_jobs/`.
- Any refused action must explain the missing precondition and name the command or UI action that fixes it.

## Data Field Raw Capture Workflow

### New Concept

Add a formal platform data-field maintenance workflow distinct from targeted field exploration:

```text
capture-platform-data-fields -> compile-data-ledger -> knowledge-health-check -> readiness-check
```

This workflow is required when the user asks to update platform data coverage. It does not run simulations.

### Raw Layer Contract

All accessible platform data-field materials are saved under:

```text
knowledge/raw/platform/data_fields/YYYY-MM-DD/
```

Required raw files:

- `index.md`: human-readable summary of the capture, scope list, counts, warnings, and next compile command.
- `manifest.json`: machine-readable capture metadata, source endpoints, parameters, counts, and errors.
- `operators.json`: raw operator catalog payload.
- `scopes.jsonl`: one row per attempted scope, including instrument type, region, delay, universe, status, and counts.
- `data_sets.jsonl`: data-set rows with source scope and raw fields preserved.
- `data_fields.jsonl`: data-field rows with source scope, dataset, endpoint parameters, and raw field payload preserved.
- `errors.jsonl`: recoverable fetch errors, including endpoint, scope, retry metadata, and message.

Raw records must preserve source details instead of rewriting them into the ledger schema too early.

### Scope Discovery

The first implementation should avoid hard-coding only USA/D1. It should support a configurable scope matrix.

Minimum default scope matrix:

- instrument type: `EQUITY`
- regions: `USA`, `EUR`, `ASI`, `GLB`
- delays: `0`, `1`
- universes: `TOP3000`, `TOP2000`, `TOP1000`, `TOP500`, `TOP200`

The command should tolerate platform-level invalid scopes by recording them in `errors.jsonl` rather than stopping the entire capture.

If the platform exposes an authoritative endpoint for available settings or if existing metadata reveals valid regions/universes, the workflow may use that source to reduce invalid scope attempts. If not, the configurable matrix is used and every skipped or failed scope is recorded.

### Server Interaction Efficiency

The capture command should minimize unnecessary server interaction:

- fetch operators once per capture;
- fetch data sets once per scope;
- fetch data fields by dataset and scope with pagination;
- use the largest safe page size already supported by the platform helper;
- write partial raw results as the capture progresses so it can be resumed or inspected after interruption;
- support `--max-scopes`, `--max-datasets-per-scope`, and `--max-fields-per-dataset` for dry/limited runs;
- default production capture should not be triggered automatically by research startup.

### Data Ledger Compile Contract

`compile-data-ledger` reads raw platform data-field snapshots and writes:

```text
knowledge/wiki/20_semantics/data_ledger.jsonl
knowledge/wiki/20_semantics/data_ledger.md
knowledge/wiki/80_maintenance/freshness_manifest.json
```

Each compiled ledger row must include:

- field identity, type, description, dataset, and category;
- all available regions, delays, and universes observed in raw snapshots;
- source raw paths;
- coverage and alpha/user count fields when present;
- semantic tags from `wqb.semantics`;
- crowding/correlation-risk hints from alpha/user counts and prior usage ledgers;
- simulation/submission usage counts from local research records when available;
- compatible template IDs when inference is possible.

`compile-data-ledger` must not fabricate full coverage. If raw snapshots are partial, it should mark `coverage_status` and source quality explicitly.

## Console Command Changes

Add safe actions to `wqb.console_jobs.build_cli_command` and route them in `wqb.console_server`:

- `capture-platform-data-fields`
  - live API required;
  - writes raw data-field snapshot;
  - not run automatically.

- `compile-data-ledger`
  - local-only compile from raw;
  - updates ledger and freshness manifest.

- `workflow-start-from-option`
  - internal console action that maps the selected card to existing `workflow-start`;
  - does not expose free-text `selected_option_id`.

Existing actions remain:

- `readiness-check`
- `plan-research-options`
- `workflow-continue`
- `workflow-status`
- `compile-research-records`
- `bootstrap-knowledge`
- `knowledge-health-check`
- proposal creation

`bootstrap-knowledge` remains available for initial structure recovery, but UI copy must not imply that it refreshes all platform data fields.

## CLI Changes

Add commands:

```powershell
python -m wqb.cli capture-platform-data-fields --knowledge-root <vault> --enable-live-api
python -m wqb.cli compile-data-ledger --knowledge-root <vault>
```

Optional capture flags:

- `--data-capture-date`
- `--capture-region`
- `--capture-delay`
- `--capture-universe`
- `--max-scopes`
- `--max-datasets-per-scope`
- `--max-fields-per-dataset`
- `--resume-capture`

Existing `cache-metadata` remains a targeted exploration/debug command and should not be used as the authoritative data ledger source.

## Readiness And Gates

Research startup must stay blocked when:

- freshness manifest is missing, invalid, stale, or missing required entries;
- data ledger is schema-seeded or partial while the selected research scope needs full data coverage;
- selected option card is absent or malformed;
- selected scope has no matching data ledger records;
- template library has no compatible templates for the selected data scope.

The UI should present these as fixable states:

- "Compile data ledger from raw"
- "Capture platform data fields"
- "Refresh option cards"
- "Run knowledge health check"
- "Run readiness check"

## Error Handling

- Live API/network failures are recorded as recoverable job failures with stdout/stderr and `errors.jsonl` entries when applicable.
- Invalid platform scope attempts do not stop a broad capture; they are recorded and summarized.
- Partial captures can still be compiled, but the manifest and ledger must mark them as partial.
- A failed compile must not delete or overwrite the last known good ledger. Use a temporary output path and replace only on successful validation.
- The console must render absent or malformed option card files as an empty state, not crash.

## Testing Strategy

Follow TDD for implementation.

Required tests:

- `test_console_server.py`
  - dashboard renders five clear areas;
  - option cards render as selectable controls;
  - workflow start command is built from selected card, not manual ID fields;
  - start is refused when no card is selected;
  - data capture action requires live API.

- `test_console_jobs.py`
  - new action mapping for `capture-platform-data-fields`;
  - new action mapping for `compile-data-ledger`;
  - no manual `selected_option_id` path for normal console workflow start.

- New data capture tests
  - scope matrix expansion;
  - raw manifest and Markdown index writing;
  - paginated data-field capture with multiple regions/delays/universes;
  - invalid scope recorded as error without aborting whole capture.

- New data ledger compile tests
  - compile all raw field rows into ledger records;
  - aggregate available regions/delays/universes for the same field;
  - mark partial source quality when captures are incomplete;
  - preserve source raw paths;
  - do not overwrite last good ledger on validation failure.

- CLI tests
  - parse and dispatch both new commands;
  - `capture-platform-data-fields` requires `--enable-live-api`;
  - `compile-data-ledger` is local-only.

Minimum verification before claiming implementation complete:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
python -m compileall -q wqb tests
git diff --check
```

## Documentation Updates

Update:

- `docs/operations/operating_guide.md`
- `docs/operations/maintainer_handoff.md`
- relevant README sections

The docs must explain:

- how to launch the console;
- how to choose a research option in the UI;
- the difference between `cache-metadata`, `capture-platform-data-fields`, `compile-data-ledger`, and `bootstrap-knowledge`;
- when platform raw refresh is required before research;
- how to recover from interrupted data capture or stale knowledge.

## Non-Goals

- No frontend framework migration in this slice.
- No automatic full platform data recapture during daily research startup.
- No live simulations, alpha submission, or candidate repair behavior changes.
- No rewrite of the Orchestrator or core Scout/Seed/Discovery/Repair/Submit workflow.
- No deletion of stage1 archive or historical knowledge material.

## Open Implementation Decision

The implementation plan must choose whether `compile-data-ledger` lives in a new module such as `wqb/data_field_capture.py` plus `wqb/data_ledger_compile.py`, or whether capture and compile are combined in one module. The preferred direction is two modules because raw capture and semantic compile have different failure modes and test boundaries.

## Spec Self-Review

- Completion-marker scan: clean.
- Scope check: this is one implementation slice covering UI selection plus the data-field raw-to-ledger maintenance path; it deliberately excludes simulation and submission changes.
- Consistency check: research startup remains Orchestrator-owned; console only selects options and creates durable jobs.
- Ambiguity check: "all available data fields" means all fields accessible to the authenticated account through the configured platform API scopes attempted by the capture matrix, with partial or failed scopes explicitly recorded instead of hidden.
