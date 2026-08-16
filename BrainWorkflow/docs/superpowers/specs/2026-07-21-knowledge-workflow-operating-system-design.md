# BrainWorkflow Knowledge And Workflow Operating System Design

Date: 2026-07-21
Status: superseded as active vault layout by `2026-07-30-simplified-knowledge-structure-delivery-contract-design.md`

> Current authority note: this document is preserved for background concepts such
> as raw sources, semantic ledgers, template matrices, and proposal-driven
> workflow evolution. Its older multi-directory `wiki/10_foundations`,
> `wiki/20_semantics`, etc. layout is not the active vault contract. The active
> Obsidian vault must compile into `raw/`, `machine/`, and compact `wiki/`
> only, with `.obsidian` allowed as UI configuration.

## Purpose

BrainWorkflow already has stronger code-side workflow boundaries than knowledge-side boundaries. The Orchestrator, start snapshots, readiness gates, console actions, and durable job records provide a usable state machine. The knowledge base is less mature: it has a raw/wiki split, but still contains historical mixing, partial platform coverage, cache-derived ledgers, and underdeveloped semantic/template layers.

This spec defines the long-term knowledge and workflow operating system for BrainWorkflow:

- make the Obsidian vault the canonical durable knowledge layer;
- separate facts, compiled rules, machine ledgers, decisions, and proposals;
- eliminate historical source mixing through a migration contract;
- distinguish cache/bootstrap seed knowledge from authoritative measured platform knowledge;
- define where Codex should spend reasoning tokens and where deterministic commands should do the work;
- preserve the existing Scout -> Seed -> Discovery -> Repair -> Submit research workflow while making it easier to maintain and improve.

## Non-Goals

- Do not build a human learning curriculum. Human readability matters, but the goal is source-clean operating knowledge, not a tutorial path.
- Do not rewrite the Orchestrator, readiness gate, console job model, or candidate queue in this spec.
- Do not force all knowledge into databases now. The system remains Markdown-first, with schema-first ledgers only for high-value machine inputs.
- Do not implement the Windows double-click launcher here. That belongs in a later launcher/UI startup spec.
- Do not run live WorldQuant BRAIN simulations, data captures, or submissions as part of this design step.

## Current Baseline

### Code-Side Baseline

These components are already mature enough to keep as the official workflow backbone:

- `wqb/orchestrator.py`: owns legal workflow lifecycle and durable run manifests.
- `wqb/workflow_stage_adapters.py`: connects workflow stages to existing planner and record modules.
- `wqb/run_readiness.py`: blocks unsafe starts when required knowledge artifacts are stale, missing, partial, or not live-authorized.
- `wqb/console_server.py` and `wqb/console_jobs.py`: expose local UI actions as durable jobs.
- `wqb/research_record.py`, `wqb/candidate_queue.py`, and workflow event files: preserve candidate decisions and recovery context.

Spec B strengthens the knowledge contracts that feed those components. It does not replace them.

### Knowledge-Side Baseline

The vault already follows a rough raw-to-wiki model:

```text
knowledge/
  raw/
  wiki/
```

Current issues:

- Historical mixing remains. For example, older source families such as `raw/learn` coexist with newer canonical paths such as `raw/platform/learn`.
- `raw/platform/data_fields/` is absent in the current vault, so the root knowledge base has no durable raw platform data-field capture to compile.
- `wiki/20_semantics/data_ledger.jsonl` currently has 14 rows, all `USA / D1 / TOP3000`, all from `platform_metadata_cache`, with no `source_updated_at`.
- `template_library.jsonl` contains a few seed templates, not a full matrix from data semantics to economic hypothesis, operator composition, correlation risk, repair levers, and experiment outcomes.
- Official operator documentation exists, but the system lacks a workflow-oriented operator semantic layer.
- Benchmark rules exist as notes, but repeated signal-recognition and repair lessons need stronger promotion into active rules.
- Workflow improvement ideas can still live in conversation unless they become proposals, wiki rules, or implementation plans.

## Evidence: Data Ledger Root Cause

The current data ledger is not a failed full-platform compile. It is a cache/bootstrap artifact.

Observed evidence from the current vault:

- `knowledge/raw/platform/data_fields/` does not exist.
- `wiki/20_semantics/data_ledger.jsonl` has 14 rows.
- Every row has:
  - `region = USA`;
  - `delay = 1`;
  - `universe = TOP3000`;
  - `source_quality = platform_metadata_cache`;
  - `coverage_status = measured_cache`.
- No row has `source_updated_at`.
- Source paths point to old local cache files under `docs/knowledge/cache/platform_metadata_20260702_014429.json` and `docs/knowledge/cache/platform_metadata_20260703_022956.json`.
- Console job history does not show `capture-platform-data-fields` or `compile-data-ledger`.

Conclusion: full data-field capture and compile capability exists in code, but it has not been executed into the root Obsidian vault. Research scheduling must not treat the current cache-derived ledger as an authoritative platform-wide data inventory.

## Design Choice

Use **Canonical Vault + Migration Contract** now, while reserving schema-first interfaces for the future.

This means:

- Markdown remains the durable human-readable knowledge format for raw source notes and wiki pages.
- High-value planner inputs also have JSONL ledgers.
- Historical materials must be explicitly migrated, compiled, archived, or deleted after confirmation.
- Future schema-first ledgers can be added without rewriting the vault.

## 1. Canonical Knowledge Vault

The canonical vault structure is:

```text
knowledge/
  README.md
  raw/
    source_index.md
    _manifests/
    platform/
      learn/
      data_fields/
      activities/
      account_rules/
    community/
      forum/
      advisor_notes/
      user_messages/
    research/
      daily/
      batches/
      near_misses/
      repairs/
      submissions/
  wiki/
    00_principles/
    10_foundations/
    20_semantics/
    30_templates/
    40_experiments/
    50_benchmarks/
    60_workflows/
    70_decisions/
    80_maintenance/
    90_index/
```

Canonical rules:

- `raw/` stores factual material and minimal source metadata.
- `wiki/` stores compiled interpretation, rules, principles, and planner inputs.
- `wiki/70_decisions/` stores generated options, schedules, readiness reports, and user decisions.
- Machine caches may exist outside the vault or in ignored folders, but they are not canonical knowledge unless converted into raw Markdown and indexed.
- Legacy source paths are migration inputs, not ongoing planner inputs.

## 2. Raw Source Contract

Raw Markdown files preserve facts. They may normalize HTML or JSON into readable Markdown, but they do not add strategy interpretation.

Every raw source file must include a small metadata block:

```yaml
---
source_type: platform_api
source_family: data_fields
source_path: /data-fields
captured_at: 2026-07-21T10:00:00+08:00
capture_tool: wqb.cli capture-platform-data-fields
scope: EQUITY/USA/D1/TOP3000
record_count: 1240
content_hash: example-hash
content_status: raw_markdown
update_check: compare field ids, dataset ids, coverage, userCount, alphaCount, and scope availability
compiled_targets:
  - wiki/20_semantics/data_ledger.md
  - wiki/30_templates/template_library.md
  - wiki/70_decisions/research_option_cards.md
---
```

Required raw source families:

- Platform official material: Learn documentation, operators, FAQs, videos, recommended readings.
- Platform data coverage: data fields, datasets, region/delay/universe availability, coverage, user counts, alpha counts.
- Platform incentives and account rules: Power Pool, Theme, Genius, Osmosis, competitions, consultant requirements, dormancy rules.
- Community material: forum posts, advisor notes, consultant examples, user-provided workflow guidance.
- Research material: daily logs, 30-alpha batches, simulations, near misses, repair attempts, submissions.

`raw/source_index.md` is the global inventory. It records each raw file, what it contains, how to check for updates, and which wiki pages it can affect.

## 3. Wiki Compile Contract

Wiki pages contain reusable interpretation. Every compiled page must point back to raw facts and identify who consumes it.

Required wiki metadata:

```yaml
---
compiled_from:
  - raw/platform/learn/2026-07-09/documentation_pages.md
compiled_at: 2026-07-21
trust_level: working_rule
stale_after_days: 14
update_trigger: platform check rules changed or repeated research failures contradict this page
consumed_by:
  - research_planner
  - candidate_gate
  - repair_loop
---
```

Compile quality gate:

- A wiki page must cite raw sources.
- A wiki page must state the workflow implication of the compiled knowledge.
- A wiki page must define when it should be updated.
- A wiki page that drives automation must also have a machine-readable ledger or rule counterpart when practical.

## 4. Data Semantic Ledger

The data semantic ledger is the planner's authoritative data inventory. It must not confuse bootstrap/cache data with measured platform data.

Ledger classes:

- `seed/cache ledger`: useful for development, fallback, and examples; not sufficient for live research scheduling.
- `authoritative measured ledger`: compiled from `raw/platform/data_fields/YYYY-MM-DD/` captures and suitable for research scheduling when freshness gates pass.

Required fields for authoritative rows:

- identity: `field_id`, `dataset_id`, `field_type`, `instrument_type`;
- scope: `region`, `delay`, `universe`, `available_scopes`;
- provenance: `source_quality`, `source_updated_at`, `source_paths`, capture manifest path;
- platform stats: `coverage`, `alpha_count`, `user_count`, `date_coverage`, `date_created`;
- semantics: `semantic_tags`, `data_category`, `field_description`;
- planner links: `compatible_template_ids`, `known_operators`, `activity_tags`;
- usage: `simulation_usage_count`, `submitted_usage_count`, `repair_usage_count`, `last_used_at`, `experiment_paths`;
- risk: `correlation_risk`, `crowding_risk`, `gate_requirements`.

Readiness rule:

- If authoritative measured data is missing, stale, partial, or lacks exact requested scope coverage, research scheduling must block or explicitly label the run as degraded.
- `bootstrap-knowledge` must not silently replace authoritative measured ledgers with schema-seeded partial rows.
- `compile-data-ledger` is the official path from raw platform data-field capture to authoritative ledger.

## 5. Operator Semantic Ledger

The official operator catalog answers what operators exist. The operator semantic layer answers how they are used in research.

Required concepts:

- operator family: cross-sectional rank, time-series change, smoothing, vector-to-matrix conversion, neutralization, winsorization, decay, regression, grouping;
- workflow use: normalize, denoise, reduce turnover, reduce correlation, strengthen event surprise, stabilize sparse fields;
- data compatibility: MATRIX, VECTOR, GROUP, sparse fields, event fields, fundamental fields;
- risk: future-looking misuse, over-nesting, crowded structures, turnover inflation, invalid vector handling;
- template compatibility: template families that naturally consume this operator;
- repair compatibility: cases where the operator is a one-change repair lever.

Future machine interface:

```text
wiki/20_semantics/operator_semantics.jsonl
```

## 6. Template Matrix

The current template library is a seed library. It must evolve into a matrix:

```text
data semantics
  -> economic hypothesis
  -> template family
  -> operator composition
  -> correlation risk
  -> repair levers
  -> experiment outcomes
```

Template records must include:

- `template_id`;
- human-readable economic hypothesis;
- required data types and semantic tags;
- expression skeleton;
- operator tags;
- compatible scopes;
- expected horizon and turnover bucket;
- neutralization styles;
- known crowded variants;
- correlation risk;
- repair levers;
- successful and failed experiment links;
- abandon conditions.

The template matrix is the main mechanism for generating explainable 30-alpha batches from new or underused data.

## 7. Benchmark Rulebook

Benchmarks must become active rules, not only notes.

Rule families:

- hard platform checks: Sharpe, fitness, turnover, self correlation, production correlation, submission criteria;
- signal quality: PnL straightness, drawdown pattern, stability, in-sample/out-of-sample decay;
- near-miss promotion: when an alpha should enter repair instead of being discarded;
- correlation novelty: data novelty, operator novelty, template novelty, self/prod correlation risk;
- repairability: which failures can be repaired by neutralization, delay/window changes, field substitution, truncation, decay, or operator simplification;
- abandon thresholds: when repeated variants show no signal or only overfit artifacts.

Stage 1 lessons such as the missed `3q7OQaog` signal should become explicit near-miss promotion rules with evidence paths.

Future machine interface:

```text
wiki/50_benchmarks/benchmark_rules.jsonl
```

## 8. Research Planner Inputs

Research planning starts from incentives and current opportunity state, not from random template enumeration.

Planner inputs:

- consultant incentive mechanism and account state;
- current activities, competitions, Power Pool boards, Theme multipliers, Genius/Osmosis rules;
- authoritative measured data ledger;
- operator semantic ledger;
- template matrix;
- benchmark rulebook;
- recent data/template/operator usage history;
- submission and repair records;
- freshness and readiness reports.

Planner output:

- option cards in `wiki/70_decisions/research_option_cards.jsonl` and `.md`;
- each option card has objective, scope, incentive rationale, data families, template families, novelty/correlation risk, required maintenance gates, and expected workflow mode.

The planner must not create a concrete simulation schedule until the user selects an option card.

## 9. Workflow Intervention Policy

Codex should spend reasoning tokens where judgment matters.

High-value LLM intervention points:

- platform material changes -> affected-wiki analysis;
- forum/advisor/user material -> reusable rule extraction;
- data semantic interpretation and template matching;
- option card generation and tradeoff explanation;
- template innovation and operator composition brainstorming;
- near-miss explanation;
- self/prod correlation failure attribution;
- repair direction selection;
- workflow proposal generation;
- raw-to-wiki compilation and health-check explanation.

Low-value deterministic actions should stay in CLI/Orchestrator:

- API data capture;
- JSON/Markdown conversion;
- ledger compilation;
- readiness checks;
- workflow state transitions;
- console job records;
- test execution;
- candidate queue persistence.

This policy prevents long chat context from becoming the source of truth.

## 10. Migration/Cleanup Contract

Historical material has to pass through a contract before it disappears or becomes canonical.

Migration workflow:

1. Inventory historical file or folder.
2. Identify reusable facts, rules, API behavior, settings, or research lessons.
3. Move facts to canonical `raw/`.
4. Compile reusable interpretation into `wiki/`.
5. Add backlinks from wiki pages to raw sources.
6. Mark the old artifact as retained, archived, or delete candidate.
7. Delete only ordinary obsolete artifacts after user confirmation when needed.

Never auto-delete:

- credentials;
- secrets;
- `.env` files;
- private login or account material;
- files whose sensitivity is unclear.

## 11. Proposal-Based Rule Evolution

Workflow changes should enter through proposals, not chat memory.

Required proposal fields:

- `proposal_id`;
- `created_at`;
- `issue_type`;
- `affected_modules`;
- `evidence_paths`;
- `current_behavior`;
- `proposed_rule_change`;
- `expected_impact`;
- `risk`;
- `user_decision`;
- `applied_at`;
- `supersedes`.

Proposal outcomes:

- rejected: record why;
- accepted for wiki: update wiki/rules;
- accepted for implementation: write spec and plan;
- accepted as experiment: add to research schedule or batch objective.

The console proposal UI is the human entry point for this loop.

## 12. Future Schema-First Interface

The current design stays Markdown-first. The future schema-first path is reserved through stable JSONL ledgers.

Reserved interfaces:

```text
wiki/20_semantics/data_ledger.jsonl
wiki/20_semantics/operator_semantics.jsonl
wiki/30_templates/template_library.jsonl
wiki/40_experiments/experiment_outcomes.jsonl
wiki/50_benchmarks/benchmark_rules.jsonl
wiki/60_workflows/workflow_rules.jsonl
wiki/70_decisions/research_option_cards.jsonl
```

When a Markdown page starts driving planner decisions repeatedly, it should gain a machine-readable counterpart. This migrates toward a schema-first Knowledge OS without losing Obsidian readability.

## Maintenance Loops

### Platform Refresh Loop

1. Capture official platform material into `raw/platform/`.
2. Capture data fields into `raw/platform/data_fields/YYYY-MM-DD/`.
3. Update `raw/source_index.md` and raw manifests.
4. Compile affected wiki pages and ledgers.
5. Run knowledge health check and readiness check.
6. Generate proposals for changed rules, thresholds, or workflow implications.

### Research Session Compile Loop

1. File daily objective and chosen option under `raw/research/daily/`.
2. File 30-alpha batches under `raw/research/batches/`.
3. File near misses, repairs, and submissions under their canonical raw folders.
4. Compile reusable findings into experiments, templates, benchmarks, data semantics, and principles.
5. Update usage counters in data/template/operator ledgers.
6. Propose workflow rule changes for repeated failures or efficiency gains.

### Cleanup Loop

1. Read the migration inventory.
2. Confirm lessons are represented in raw or wiki.
3. Archive or remove obsolete duplicates according to the cleanup policy.
4. Refresh indexes and health checks.

## Console Implications

The existing console should eventually reflect the contracts in this spec:

- show whether the data ledger is seed/cache or authoritative measured;
- show freshness and exact scope readiness before workflow start;
- label platform data capture and data ledger compile as maintenance actions, not daily research actions;
- route user workflow improvements through proposal records;
- keep option selection and scope selection as explicit user decisions.

## Acceptance Criteria

Spec B is implemented when:

- `knowledge/raw/` has one canonical source tree and `raw/source_index.md` covers all active raw families.
- Legacy raw paths are migrated, archived, or marked as delete candidates.
- Platform data-field capture exists under `raw/platform/data_fields/YYYY-MM-DD/` before data-ledger based live research scheduling.
- `data_ledger.jsonl` distinguishes seed/cache rows from authoritative measured rows and exposes exact scope freshness.
- Operator semantics exist as wiki content and, where needed, a JSONL interface.
- Template library records form the data-semantics-to-repair-levers matrix.
- Benchmark rules capture near-miss promotion and correlation repair lessons.
- Planner option cards consume incentives, activities, authoritative data, templates, operators, benchmarks, and recent usage.
- Workflow changes enter proposal records before becoming rules or code plans.
- Codex sessions can resume from docs, ledgers, state files, `todo.md`, and `milestone.md` without relying on a long chat context.

## Verification Strategy

Implementation planning should include:

- tests for raw metadata parsing and source index updates;
- tests for rejecting cache-only data ledgers in research readiness unless explicitly degraded;
- tests for authoritative data-field capture manifest detection;
- tests for template matrix schema validation;
- tests for proposal lifecycle transitions;
- knowledge health checks for stale pages, missing source backlinks, orphan raw files, and stale ledgers;
- non-live full test discovery and compile checks before commits.

## Design Summary

BrainWorkflow should become a canonical, proposal-driven research operating system. Markdown remains the durable human-readable layer; JSONL ledgers power planner and gate decisions. The existing Orchestrator remains the state owner. The largest near-term gap is not code capability but knowledge completeness: the root vault still lacks authoritative platform-wide data-field raw capture and a mature template/operator/benchmark semantic layer.
