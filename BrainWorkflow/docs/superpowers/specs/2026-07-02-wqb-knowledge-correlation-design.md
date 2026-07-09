# WQB Knowledge Base And Correlation-Aware Workflow Design

Date: 2026-07-02

## Goal

Build an Obsidian-readable knowledge base under `knowledge/` and use it as the durable source of truth for WorldQuant BRAIN research, especially alpha syntax, operators, datasets, metrics, checks, activities, and correlation avoidance.

The immediate workflow change is to stop treating correlation as a late-stage surprise. Self correlation and production correlation become first-class constraints during idea generation, before batch simulation.

## Confirmed Requirements

- Use `C:\Users\oytl\Desktop\pyproject\brain\knowledge` as the main knowledge base.
- Follow the Karpathy-style loop: raw sources are indexed, then an LLM compiles a markdown wiki, then Q&A and outputs are filed back into the wiki, with periodic health checks.
- Learn platform definitions from official platform documentation and cached API metadata before relying on heuristics.
- Improve the alpha workflow for `SELF_CORRELATION` and `PROD_CORRELATION`.
- Continue stage-one alpha discovery only after the knowledge base has enough foundation to guide better batches.
- Prefer fewer server interactions: fetch broadly, process locally, and reserve live platform calls for simulations and required checks.

## Knowledge Base Structure

```text
knowledge/
  README.md
  raw/
    source_index.md
    karpathy_llm_knowledge_bases_20260702.md
  wiki/
    index.md
    10_foundations/
    20_semantics/
    30_templates/
    40_experiments/
    50_benchmarks/
    60_workflows/
    90_index/
```

`raw/` stores source inventories and minimally processed source notes. `wiki/` stores compiled, cross-linked operating knowledge. The LLM maintains the wiki; manual edits should be rare.

## Source Priority

1. Platform documentation snapshots and API metadata already captured locally in `docs/knowledge/`.
2. Forum posts and activity pages captured through authenticated platform access.
3. Local experiment outputs in `runs/`, especially near-miss alphas and check failures.
4. User-provided heuristics and consultant experience, clearly marked as experience until validated.

## Correlation Model

### Self Correlation

Self correlation checks whether a submitted alpha is highly correlated with previous submissions made by the same user. Local documentation records a key threshold of `0.7` PnL correlation, with a possible pass if the new alpha has Sharpe at least `10%` higher than the correlated submitted alpha.

Practical implication: avoid reusing the same field family, expression tree, operator n-grams, holding period, neutralization pattern, and economic story against the user's already-submitted or strong near-miss alphas.

### Production Correlation

Production correlation applies a similar criterion against the broader platform production pool. It is harder to see directly before platform checks, so the local proxy must penalize crowded ingredients:

- common price-volume templates,
- old datasets with high `Alpha Count` and `User Count`,
- common operator skeletons such as plain `rank(ts_delta(...))`,
- overused USA/PV combinations,
- templates whose economic explanation is indistinguishable from common momentum, reversal, or liquidity variants.

Practical implication: new data, event-driven datasets, Fast D1 deltas, vector-field transformations, non-USA regions, double neutralization, and less-common economic hypotheses should receive higher novelty scores.

## Generation Gate

Every 30-alpha batch should pass a local novelty gate before simulation:

1. Parse expression into field set, dataset family, operator sequence, and template family.
2. Compare against local submitted/near-miss ledger.
3. Compare against common crowded templates recorded in the wiki.
4. Reject or down-rank alpha candidates that are too close to known self/prod-correlation risks.
5. Simulate only the highest expected value batch.

## Workflow Revision

Stage one becomes:

1. Foundation ingestion: update knowledge base from platform docs, metadata, forum posts, and experiments.
2. Scout new data: choose datasets with low crowding and clear economic meaning.
3. Seed templates: pair one simple economic template with many fields, not many arbitrary formulas.
4. Discovery batch: build 30 candidates at a time, filtered by local novelty and syntax checks.
5. Repair: optimize only near-miss alphas with strong performance or straight PnL shape.
6. Submit: only move alphas that pass all platform checks into the candidate submission list; request user confirmation before final submission.
7. Retrospective: file each problem and repair rule back into the workflow wiki.

## Health Checks

The knowledge base needs periodic linting:

- Missing source: wiki claims without a source path or experiment link.
- Stale rule: platform thresholds that may have changed.
- Duplicate concept: same operator or check explained in multiple incompatible ways.
- Missing benchmark: repeated failure mode with no workflow rule.
- Underused signal: near-miss alpha with straight PnL or strong Sharpe not entered into repair queue.

## Out Of Scope For This Step

- Submitting an alpha.
- Building a full web UI or RAG system.
- Downloading large external datasets.
- Hardcoding platform credentials or API secrets.

