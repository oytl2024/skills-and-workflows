# Simplified Knowledge Structure And Delivery Contract Design

Date: 2026-07-30
Status: implemented, pending live platform refresh and routine operation hardening

## Purpose

BrainWorkflow needs a simpler knowledge contract. The current vault has useful material, but its active structure still mixes old raw folders, compiled pages, machine ledgers, research artifacts, and historical leftovers. That makes the system harder to operate and harder for the user to learn from.

This spec defines the simplified target:

- keep the existing Orchestrator, Console, readiness gates, and Scout -> Seed -> Discovery -> Repair -> Submit workflow;
- make knowledge compile produce a clean active vault every time;
- separate machine-readable resources from human-readable experience;
- compile useful user corrections and recurring problems into durable workflow rules, tests, checks, or lessons;
- add a delivery gate so the workflow is handed off only after the fixed automated path can run to its intended boundary;
- change platform data capture from deep single-scope crawling to broad stratified sampling.

This spec supersedes the heavier knowledge-governance direction in the earlier knowledge workflow design. It keeps the useful contracts and removes excess process.

## Non-Goals

- Do not rewrite the Orchestrator, workflow state files, candidate queue, or Console job model.
- Do not make `data_ledger` or other machine ledgers pleasant for human reading.
- Do not keep old mixed paths in the active knowledge tree after a successful compile.
- Do not build a large knowledge governance product.
- Do not run live simulations or submit Alphas as part of this design step.

## Core Principle

The knowledge base has three jobs:

1. preserve facts long enough to compile them;
2. provide stable machine inputs for workflow code;
3. teach the user reusable factor-mining and engineering lessons.

Anything that does not serve one of these jobs is either a temporary input, a machine artifact, a human lesson, or removable after compile.

## Target Active Structure

The active knowledge root contains only three top-level knowledge areas:

```text
knowledge/
  raw/
  machine/
  wiki/
```

Operational recovery files such as root `todo.md`, root `milestone.md`, and `runs/` remain outside this knowledge contract.

### `raw/`

`raw/` is the input inbox for facts and interaction memory.

It contains:

- official platform material;
- forum and advisor material;
- platform API snapshots;
- user-provided requirements and corrections from Codex conversations;
- research run raw material that has not yet been compiled.

Rules:

- Raw material needs source metadata sufficient to recompile it.
- Raw material is not the human learning surface.
- Once raw material is compiled into `machine/` or `wiki/` and verification passes, old mixed copies are removed from the active structure.
- Ordinary obsolete files may be deleted by the cleanup workflow after compile verification.
- Sensitive files, credentials, account secrets, `.env` files, and ambiguous private files are never deleted automatically.

### `machine/`

`machine/` is for workflow code.

It contains structured resources such as:

- `scope_matrix.jsonl`;
- `data_ledger.jsonl`;
- `operator_ledger.jsonl`;
- `template_library.jsonl`;
- `benchmark_rules.jsonl`;
- `research_records.jsonl`;
- `source_index.jsonl`;
- `freshness_manifest.json`.

Rules:

- Machine resources are optimized for stable parsing, queryability, and incremental updates.
- They are allowed to be large.
- They should not live inside the human wiki.
- A compact Markdown entry point may exist in `wiki/`, but it must not duplicate the full machine ledger.

### `wiki/`

`wiki/` is for the user to read and learn from.

It should stay small, curated, and experience-oriented.

Target structure:

```text
wiki/
  00_start_here.md
  10_factor_principles.md
  20_data_semantics.md
  30_template_and_operator_patterns.md
  40_benchmark_and_repair_rules.md
  50_engineering_lessons.md
  60_research_cases/
```

Rules:

- Wiki pages contain reusable interpretation, not raw dumps.
- The wiki is not a chronological log.
- Each page should explain what was learned and how it changes research behavior.
- Large JSONL files and complete API payloads do not belong in `wiki/`.

## Human Wiki Page Roles

### `00_start_here.md`

The top-level orientation page.

It explains:

- current workflow status;
- how to operate the system;
- current strongest principles;
- where to look next.

### `10_factor_principles.md`

General factor-mining lessons.

Examples:

- prefer simple economic logic before operator complexity;
- use new data and new templates to reduce self/prod correlation risk;
- treat straight PnL with weak checks as a repair candidate, not an automatic reject;
- avoid overfitting through excessive nesting and too many parameters.

### `20_data_semantics.md`

Lessons about data meaning and usefulness.

Examples:

- what attention, event, analyst, fundamental, option, news, risk, or sentiment data represents;
- which data types fit matrix, vector, group, sparse, or event templates;
- what worked, failed, or remains underexplored.

### `30_template_and_operator_patterns.md`

Lessons about expression structure.

Examples:

- which template families fit which data semantics;
- which operator combinations improve signal stability;
- which structures tend to be crowded;
- which neutralization or ranking patterns reduce correlation risk.

### `40_benchmark_and_repair_rules.md`

Lessons about interpreting results and fixing near misses.

Examples:

- when a result deserves repair;
- how to react to low Sharpe, low fitness, high turnover, low turnover, self correlation, prod correlation, and sub-universe failures;
- when to abandon a branch.

### `50_engineering_lessons.md`

Lessons about building and maintaining the workflow itself.

Examples:

- bugs that became readiness checks;
- UI or Console mistakes that became workflow rules;
- context-loss recovery rules;
- data capture and knowledge compile lessons.

### `60_research_cases/`

Selected human-readable case reports.

Case reports are not raw logs. They are compact studies of useful runs:

- successful runs;
- near misses;
- representative failures;
- important repair loops;
- workflow bugs that taught an engineering lesson.

Each case report should include:

- objective and incentive;
- data and templates used;
- first batch logic;
- key metrics or checks;
- repair attempts;
- final outcome;
- reusable lesson;
- links to `run_id` and machine records.

Case reports should be concise. Complete factual detail stays in `machine/research_records.jsonl` and `runs/`.

## Research Record Design

Use both machine records and human cases.

`machine/research_records.jsonl` is the authoritative structured ledger for code. It records facts by `run_id` and time:

- objective;
- selected option;
- scope;
- data fields;
- templates;
- generated expressions;
- simulation IDs;
- alpha IDs;
- metrics;
- platform checks;
- repair actions;
- candidate decisions;
- final state.

Human research reports live only for selected cases under `wiki/60_research_cases/`.

The rule is:

- every run can have a machine record;
- only learning-worthy runs get a human case report;
- repeated lessons from case reports are promoted into the main wiki pages.

This keeps machines efficient and gives the user full-process examples without turning the wiki into a log dump.

## Problem-To-Workflow Principle

When the user corrects the system, or when the workflow hits a bug or repeated blocker, the reusable lesson must enter durable project memory.

The capture target can be one of:

- a workflow rule;
- a readiness check;
- a regression test;
- a knowledge compile rule;
- a benchmark rule;
- a template/data semantic note;
- an engineering lesson;
- a proposal for later implementation.

The purpose is not to add bureaucracy. The purpose is to prevent the user from repeating the same instruction in future sessions.

## Conversation Memory Contract

Useful user-provided information should be captured once.

Conversation-derived facts are stored as raw interaction memory first, then compiled into either:

- machine rules when the workflow needs to enforce them;
- human wiki lessons when the user can learn from them;
- implementation specs or plans when code changes are needed.

Examples of user information worth capturing:

- workflow preferences;
- platform domain corrections;
- factor-mining heuristics;
- examples of missed signals;
- UI operating preferences;
- cleanup rules;
- delivery expectations.

## Clean Compile Contract

Every knowledge compile must end with a clean active structure.

The compile workflow must:

1. ingest raw material;
2. update machine resources;
3. update human wiki lessons where useful;
4. remove obsolete active mixed paths after verification;
5. write a cleanup log with removed paths, hashes, and compiled targets;
6. run a knowledge health check.

The health check fails if:

- old mixed paths remain in the active tree;
- large machine resources are placed under `wiki/`;
- raw material lacks enough metadata to recompile;
- wiki pages contain raw dumps instead of compiled lessons;
- machine resources required by readiness are missing or stale;
- active files are not represented in source indexes or manifests.

## Stratified Platform Data Capture

Platform data capture should maximize diversity before depth.

The capture workflow should work in stages:

1. discover the platform research matrix:
   - regions;
   - delays;
   - universes or pools;
   - categories;
   - valid scope combinations;
2. write `machine/scope_matrix.jsonl`;
3. create a sampling plan across many scope combinations;
4. capture a bounded number of fields per scope, such as 50 or 100;
5. record partial coverage explicitly;
6. compile sampled rows into `machine/data_ledger.jsonl`.

This replaces the pattern of spending a long time fully crawling one region/universe while leaving the rest of the platform underexplored.

The planner may still request a deeper capture for a chosen scope, but that should be an explicit follow-up maintenance action.

## Delivery Gate

The system is not ready for user handoff until a fixed automated verification path passes.

The delivery gate should verify:

- knowledge compile produces the clean target structure;
- machine resources exist in `machine/`;
- human wiki pages exist and are compact;
- source indexes and cleanup logs are current;
- research option planning can run;
- workflow can start from a selected option;
- workflow can continue to the expected boundary;
- the expected boundary is represented as a durable state, timeline row, and evidence file;
- Console `/`, `/api/state`, and `/api/fragments` respond;
- tests and compile checks pass.

The gate may accept a planned pause, such as `scout_seed` requiring `candidates.csv`, only when that pause is intentional, durable, and explained by the workflow itself.

## Console Implications

The Console should remain the normal operating surface.

It should show:

- whether the latest knowledge compile is clean;
- whether machine resources are current;
- whether human wiki lessons were updated;
- latest stratified capture coverage;
- current workflow stage;
- expected pause reason;
- proposal or implementation requirements.

Routine execution should not require asking Codex what happened.

Codex conversation remains the place to iterate workflow design, approve proposals, and improve rules.

## Acceptance Criteria

Implementation is complete when:

- `knowledge/` active structure follows `raw/`, `machine/`, and `wiki/`;
- old mixed active paths are removed after successful compile verification;
- machine ledgers are moved out of `wiki/`;
- compact human wiki pages exist for principles, data semantics, templates/operators, repair rules, engineering lessons, and selected research cases;
- `research_records.jsonl` exists as a machine resource;
- selected research case reports compile from run records without duplicating full logs;
- user corrections can be captured into durable rules, lessons, or proposals;
- stratified capture can discover a scope matrix and sample bounded fields across scopes;
- delivery gate can run and report pass/fail without chat context;
- Console shows the delivery gate and workflow state clearly enough for routine operation.

## Verification Strategy

Implementation planning should include tests for:

- knowledge structure health after compile;
- deletion or relocation of obsolete non-sensitive active paths after verification;
- refusal to auto-delete sensitive or ambiguous files;
- machine resource loading from `knowledge/machine/`;
- compact wiki generation;
- research record JSONL writing and selected case report compilation;
- conversation-derived preference capture;
- stratified scope matrix discovery and sampling plan generation;
- delivery gate success and failure cases;
- Console state reporting for clean compile and delivery gate status.

Minimum non-live verification remains:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
$env:SystemRoot='C:\Windows'; $env:windir='C:\Windows'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
python -m compileall -q wqb tests
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git diff --check
```

## Implementation Notes

The simplified knowledge structure delivery contract was implemented in commits
`24a1d54` through `9d816c8`. The implementation keeps `knowledge/raw`,
`knowledge/machine`, and `knowledge/wiki` as the active knowledge layers,
compiles maintenance evidence locally, and writes durable delivery-gate reports.

Final non-live verification commands:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
$env:SystemRoot='C:\Windows'; $env:windir='C:\Windows'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
python -m compileall -q wqb tests
python -m wqb.cli compile-knowledge --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --apply-cleanup
python -m wqb.cli delivery-gate --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --runs-root 'C:\Users\oytl\Desktop\pyproject\brain\runs'
```

## Design Summary

BrainWorkflow should keep the knowledge system simple:

- `raw/` receives facts and interaction memory;
- `machine/` powers workflow automation;
- `wiki/` teaches reusable experience.

After compile, the active tree must be clean. Problems and user corrections become workflow improvements instead of repeated chat reminders. Research records stay machine-readable, while selected cases become human-readable learning material. Platform data capture broadens first through stratified sampling, then deepens only when the planner asks for it.
