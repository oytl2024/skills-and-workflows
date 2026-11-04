# Knowledge Source Repair And Lifecycle Implementation Plan

> For agentic workers: use superpowers:executing-plans, or approved subagent-driven-development with explicit medium-or-lower reasoning. Root todo.md is the only progress ledger.

**Goal:** Remove measured local source-ingestion and retention defects, then expose remaining real readiness gaps without changing research eligibility policy.

**Architecture:** Extend existing capture extraction, indexes, semantic compilation and cleanup ownership. Share catalog/inventory generations; retain separately bound jobs/releases/runs. No new framework or database.

**Tech stack:** Existing Python312/unittest, JSONL/Markdown, local Console and established offline UI verification.

**Spec:** ../specs/2026-11-04-knowledge-source-repair-and-lifecycle-design.md

## P1: Correct Local Source Consumption

Files: wqb/knowledge_contracts.py, semantic_compilation.py, full_semantic_compile.py, data_ledger_compile.py as needed; tests/test_bulk_field_extracts.py, test_full_semantic_inventory.py and existing source/extraction tests.

- [ ] Reproduce the >2MB failure using a real-format multiscope temporary capture and assert exact requested fields can be consumed without enlarging model packs.
- [ ] Add RED tests for single-generation streaming, bounded pages, partial/resumed work, no silent prefix-only completion, changed source bytes/counts and unsafe paths.
- [ ] Extend existing extractor/resolver; reuse exact identity/source receipts. No unbounded text reads or per-field whole-catalog rescans.
- [ ] Preserve existing small-source jobs/readers and test absence of fabricated timing/units/grain, freshness renewal, release publication or model calls.
- [ ] Run focused regressions and a bounded actual-vault diagnostic; report direct source-reader failures separately from later semantic gates.

## P2: Index And Nonplatform Metadata

Files: wqb/knowledge_contracts.py, knowledge_freshness.py, knowledge_maintenance.py; existing contract/maintenance/freshness tests.

- [ ] Add RED fixtures for body/full hash disagreement, canonical newline/frontmatter conversion, unindexed verified captures and genuine unexplained content drift.
- [ ] Implement only corroborated local repairs with receipts and unchanged capture dates; keep unexplained selected facts blocked rather than refreshing hashes blindly.
- [ ] Test date-only user-note classification: missing platform capture metadata is not global resource failure; required official capture fields remain enforced.
- [ ] Extend maintenance reporting with stage/target/reason/severity/scope and demonstrate unchanged authoritative raw, selected releases and run evidence.

## P3: Shared Inventory And Idempotent Projection

Files: wqb/full_semantic_compile.py, full_semantic_coverage.py, full_semantic_execution.py, knowledge_paths.py and consumers requiring storage compatibility; existing inventory/execution/coverage tests.

- [ ] Add RED tests for repeated preparation with changed execution budget but identical catalog bytes; reuse content storage while authority remains distinct.
- [ ] Replace repeated embedded source/ledger rows with shared bounded pages and identity/digest locators. Preserve all scopes and complete inventory counts.
- [ ] Default reports to compact aggregates/references; provide explicit detailed output without multiplying copies.
- [ ] Test selected evidence reconstruction, old-plan reading, interrupted writes, cache validation and stable replay. Do not enable old results via status edits.

## P4: Reference-Aware Compile Cleanup

Files: wqb/knowledge_clean_compile.py, knowledge_maintenance.py and existing cleanup/maintenance tests. Add a narrowly scoped helper only if existing ownership otherwise becomes tangled; no second resource authority.

- [ ] Add RED tests for active-release maintenance currently refusing every apply_cleanup request.
- [ ] Implement inventory/current publication/job/run/recovery protection roots, compact retirement of only superseded unexecuted maintenance derivatives and exact allowlisted candidates.
- [ ] Test duplicate generation removal, protected raw/research/results, symlink/junction refusal, publication races, candidate replacement and interrupted cleanup recovery.
- [ ] Integrate cleanup at maintenance completion; repeated unchanged compile must not grow inventories/reports or duplicate current records.
- [ ] Audit actual deletion candidates before writes; verify Git sync first. Do not delete uncertain evidence. Report deferred/failed cleanup honestly.

## P5: Actual Closure And Deployment Handoff

- [ ] Run fast architecture/root-entry checks after the last handoff edit, then affected suites and one stable full suite with before/after source digests.
- [ ] Validate actual local source consumption, counts, current projection, references, protected raw/release/run identity and idempotent maintenance replay. Measure size/read time; avoid inventing target savings or all-field trust.
- [ ] List remaining semantic gates by actual reason and scope. Bring semantic policy changes, truly missing capture and finite model allowance back for review rather than bypassing them.
- [ ] Confirm no research/API/submit/model-budget or old-run proof changes. Verify loaded Console state and documented next legal action.
- [ ] Commit/push verified implementation without force; audit/execute approved derivative cleanup, run affected regression and synchronize cleanup receipts. Formal EXE activation remains gated on resource acceptance and explicit deployment review, not implicit in this plan.
