# Karpathy-Style LLM Knowledge Base Method

Source: user-provided text from `https://x.com/karpathy/status/2039805659525644595`, pasted in the Codex conversation on 2026-07-02.

## Core Method

The workflow collects raw source documents into a `raw/` directory, then uses an LLM to incrementally compile a markdown wiki. The wiki contains summaries, backlinks, concept articles, indexes, and derived outputs. Obsidian is used as the human frontend, while the LLM owns most wiki maintenance.

## Useful Principles For This Project

- Store source material before interpretation.
- Compile source material into small linked markdown pages.
- File useful Q&A outputs back into the wiki so research accumulates.
- Maintain index files and brief summaries so the LLM can navigate the corpus without a heavyweight RAG stack.
- Run health checks to find inconsistent, missing, stale, or weakly sourced content.
- Build small tools over the wiki only after the markdown structure is stable.

## Translation To WQB Research

- `raw/` holds official docs, API metadata, forum posts, activity rules, and experiment exports.
- `wiki/10_foundations/` explains how WQB alphas, metrics, and checks work.
- `wiki/20_semantics/` records operator and data-field meaning.
- `wiki/30_templates/` maps economic ideas to simple expression templates.
- `wiki/40_experiments/` stores near-miss alphas and repair attempts.
- `wiki/50_benchmarks/` turns repeated failures into gates.
- `wiki/60_workflows/` is the executable operating manual for the next run.

