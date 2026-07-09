# Correlation-Aware Stage-One Workflow

## Purpose

Find one submit-ready alpha while also building a reusable long-term WQB research system.

## Phase 0: Knowledge Refresh

Read platform docs, metadata, forum notes, activity rules, and experiment results. File source notes into `knowledge/raw/` and compiled rules into `knowledge/wiki/`.

## Phase 1: Scout New Data

Select datasets with clear economic meaning and lower crowding. Prefer event-driven, vector, Fast D1, or less-used non-price-volume data when coverage is acceptable.

Output: a short list of dataset-field candidates and one-sentence hypotheses.

## Phase 2: Seed Simple Templates

Create simple templates that map directly to the economic hypothesis. Prefer templates with few parameters and easy interpretation.

Output: one or more seed templates with field requirements.

## Phase 3: Build A 30-Alpha Batch

Before any simulation, build a full batch of 30 candidates. A batch can use one template across many fields, or several templates across a focused data family. Run local gates first:

- syntax sanity;
- field availability;
- no obvious future-looking logic;
- operator count and field count constraints where Power Pool is targeted;
- local novelty score;
- self-correlation proxy against local submitted and near-miss ledger.

For custom expression batches, pass prior submitted or strong near-miss records as references:

```powershell
python -m wqb.cli run-expression-file `
  --expression-file research_batches\batch.jsonl `
  --run-dir runs\batch_run `
  --novelty-reference-file runs\20260702_broad_existing_scan\all_alphas.jsonl `
  --min-novelty-score 1
```

Low-novelty expressions are skipped locally and recorded in `novelty_rejections.jsonl`. This prevents spending platform POST quota on candidates likely to fail self or production correlation.

## Phase 4: Simulate Efficiently

Use multisimulation when it materially improves throughput. Avoid unnecessary server calls for metadata that can be fetched once and processed locally.

Output: simulation results, checks, and alpha IDs.

## Phase 5: Triage

Classify each result:

- `hard_pass`: all required checks pass;
- `repairable`: strong Sharpe, stable PnL, or near-threshold fitness with fixable failures;
- `correlation_risk`: good performance but self/prod correlation risk;
- `discard`: weak performance or incoherent behavior.

## Phase 6: Repair

Repair only the best near-misses. Use small 4-8 candidate batches and change one dimension at a time. File every successful and failed repair lever into the wiki.

## Phase 7: Submit Candidate

Only alphas that pass all platform checks enter the candidate submission list. Final submission requires user confirmation.

## Phase 8: Retrospective

Update:

- experiment notes;
- benchmark thresholds;
- correlation-risk patterns;
- operator and data semantics;
- workflow rules.

Any repeated problem becomes a new automatic workflow rule.
