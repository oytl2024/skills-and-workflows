# Full Local Semantic Compilation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Account for every local operator/field, compile sourced explanations without false trust, and make verified resources consumable by existing research.

**Architecture:** Repair the current maintenance/source contracts first. Reuse data ledgers, semantic jobs, immutable publication, coverage and wiki compilation; canonical machine resources select any immutable explanatory job outputs. No replacement Orchestrator or knowledge authority.

**Tech Stack:** Existing Python312/unittest/JSONL/Markdown; no additional service or dependency.

**Spec:** ../specs/2026-10-23-full-local-semantic-compile-design.md

## Global Constraints

- Local captured resources only; platform capture/model budget/publication approval is not inferred from a request to explain everything.
- Existing documented/hypothesis/measured classifications remain distinct from reviewed status and executable eligibility.
- Preserve raw dates, original bytes, reviewed releases, legacy snapshots, Stop, shared daily4000, runtime/recovery limits and separate final submission authority.
- Root todo.md is the sole task ledger; root milestone.md owns architecture. No additional entry documents or unrelated directories.
- Subagent mode retained from approved mainline; explicitly medium or lower. Source contracts precede their consumers; no concurrent writes to shared owners.
- New optional fields must round-trip, omit when absent and not force existing v1/v2 releases into a new schema.
- Do not mark an unsupported/missing record trusted to make completeness100%. Failed and unattempted targets stay in the denominator.
- No automatic cleanup or actual research resume; accepted releases follow verified Git sync/audited cleanup.

## Review Focus

1. Valid extra full-file digest versus conflicting authority metadata: K1 verifies actual bytes and identity separately.
2. Active release maintenance fails halfway: K2 preserves release selection and emits an honest failed receipt.
3. Same field appears in different scopes or changes source generation: K3 forbids semantic leakage and stale reuse.
4. Broad generic explanations conceal omitted IDs or poor typed coverage: K4 enforces complete target accounting and hypothesis labels.
5. Compile succeeds but Start reads stale/legacy resources: K5 tests actual consumption, frozen source certification and zero live/model calls.

## Execution Environment

Work from existing BrainWorkflow on agent/brainworkflow-phase2; preserve unrelated output/log.
Python: C:/Users/oytl/AppData/Local/Programs/Python/Python312/python.exe.
For commands set SystemRoot and windir to C:/Windows, PYTHONUTF8=1. Fixture subprocesses remove WQB credentials.
Do not call pnpm auto-install; existing frontend tools use direct Node entry points.
Before edits run existing relevant tests; each new behavior must demonstrate RED then GREEN.

## K1: Source Equivalence And Actual Corruption

**Files:** semantic_compilation.py, knowledge_contracts.py, preplanned_start.py;
tests/test_preplanned_start.py, tests/test_resource_evidence.py,
new tests/test_source_identity_equivalence.py.

**Interface:** add verify_source_equivalence(root: Path, frozen: dict, registered: dict) -> dict
in semantic_compilation.py. Return the verified enriched source index and actual
body/full digests via existing _material semantics; no writes or index repair.
preplanned_start._source_context consumes this helper instead of full-record equality.

- [ ] Write tests accepting a valid optional file_sha256 enrichment when canonical index omits it; assert both refer to the same verified raw bytes.
- [ ] Add negative tests for forged extra digest, altered body/date/family/scope/provenance, conflicting aliases and invalid repair/extract receipts; extra unknown authority metadata must not be silently discarded.
- [ ] Run `python -B -m unittest tests.test_source_identity_equivalence -v`; confirm meaningful failures.
- [ ] Implement explicit identity projection and enrichment verification. Retain consumed-byte/revalidation guards; optional target selection never widens source authority.
- [ ] Diagnose actual operator content_hash mismatch using readonly per-source reports. Any repair requires original-byte evidence and existing repair receipts; otherwise report missing source, never rewrite a hash to match unexplained bytes.
- [ ] Run new tests plus test_resource_evidence/test_semantic_publication/test_preplanned_start. Record review/commit; actual private raw repairs are not uploaded for backup.

## K2: Version-Aware Ordinary Maintenance

**Files:** knowledge_maintenance.py, knowledge_experience_compile.py, knowledge_freshness.py,
tests/test_knowledge_maintenance.py, tests/test_semantic_publication.py.

**Interface:** preserve run_knowledge_maintenance(root, generated_at=None,
apply_cleanup=False, max_case_reports=20) -> dict. Its migration result explicitly
reports mode legacy_initialization or active_release_preserved. No new command needed.

- [ ] Add active-release fixture test: ordinary compile skips legacy migration, preserves pointer/release bytes and capture dates, compiles owned experience outputs and reports mode.
- [ ] Add tests that legacy initialization remains compatible, corrupt active receipt fails closed, partial wiki failure cannot claim completed, and cleanup=False never deletes sources.
- [ ] Run `python -B -m unittest tests.test_knowledge_maintenance -v`; observe RED for active release.
- [ ] Implement release-aware branch; reuse existing report writer/health checks and ensure renderers consume the selected release rather than a stale canonical shadow. Preserve semantic-publication-owned wiki boundaries.
- [ ] Run test_knowledge_maintenance/test_semantic_publication/test_knowledge_freshness and root architecture/entry tests; review/commit.

## K3: Field Explanations And Certified Enrichment

**Files:** data_ledger.py, data_ledger_compile.py, semantic_contracts.py,
knowledge_compile.py, semantic_compilation.py;
tests/test_data_ledger.py, tests/test_data_ledger_compile.py,
new tests/test_field_semantic_enrichment.py.

**Interfaces:** extend DataLedgerRecord with optional field_semantics_ref: dict|None.
Reference shape: schema_version=1, path, sha256, dataset_id, field_id; path must be an
immutable validated result under existing machine/semantic_jobs. The canonical row
is the only selector, not an independent active semantic pointer.
Add resolve_field_semantics(root: Path, row: dict) -> dict in knowledge_compile.py.
Add merge_field_enrichment(root: Path, captured: dict, prior: dict|None) -> dict in
data_ledger_compile.py; preserve existing source facts and optional timing/grain/unit contracts.

- [ ] Write round-trip/omission tests for legacy rows and valid references; reject traversal, junctions, wrong digest/field/dataset and incompatible scope/source generation.
- [ ] Write recompilation tests preserving verified timing/meaning evidence and usage history, rejecting changed identities and ensuring scope coverage is never inherited from another universe/delay.
- [ ] Run new enrichment tests; observe RED.
- [ ] Reuse HypothesisCard/EvidenceRef for economic explanations and existing documented field premises for factual enrichment. Immutable result rows contain source identities, allowed scopes, literal fact explanation, hypothesis cards and explicit missing facts. Dataset-common text is referenced, not copied across every scope row.
- [ ] Implement resolver and merge; validate referenced bytes and exact row compatibility before selecting enrichment. Retain rejected history. A model-proposed timing value alone cannot become a fact.
- [ ] Test that cadence is required only by cadence-dependent rules, VECTOR reduction needs grain/reducer, and absent units do not block an unrelated Level operation. Preserve unknown polarity as hypothesis.
- [ ] Run test_data_ledger/test_data_ledger_compile/test_resource_evidence plus new suite; review/commit.

## K4: Full Inventory, Incremental Jobs And Explanation Coverage

**Files:** knowledge_compile.py, semantic_compilation.py, operator_semantics.py,
semantic_contracts.py, codex_ai_worker.py, cli.py;
new tests/test_full_semantic_inventory.py, tests/test_semantic_compilation.py,
tests/test_codex_ai_worker.py.

**Interfaces:** add prepare_full_semantic_compile(root: Path, config: dict) -> dict
and run_full_semantic_compile(root: Path, plan: dict, *, executor) -> dict in
knowledge_compile.py. Extend compile-semantic-knowledge with explicit full-local
prepare/execute modes, keeping existing bounded request behavior unchanged.
Preparation produces deterministic target manifest/job references/cost estimates
under existing machine/semantic_jobs, with zero model calls or publication.

- [ ] Test inventory reconciliation across raw captures, canonical rows and active releases. Union identities without losing provenance conflicts. Invalid source targets remain visible blocked records, not omitted records.
- [ ] Test that same field across scopes gets one meaning job but distinct scope facts; original per-field descriptions are retained even when sharing dataset explanation. Operator family grouping cannot substitute one generic answer for every target.
- [ ] Run test_full_semantic_inventory; observe RED.
- [ ] Implement streaming inventory and deterministic source/rule/schema-keyed jobs. Group by dataset/operator family; use existing bounded material/context validators, split before bounds, never raise source-read limits merely for full coverage.
- [ ] Produce strict per-target output: identity, literal fact summary, sourced typed facts where supported, hypothesis cards/conditional uses, missing/conflicting facts and evidence. Every requested ID occurs exactly once; reject duplicates, omissions, extra IDs and unsupported formula escapes.
- [ ] Test cache reuse on unchanged inputs, invalidation on changed source/rules, isolated failed targets, unknown outcome non-replay, interruption/restart and exact budget stop. Model calls remain zero unless an explicit finite allowance is supplied; reserve durably before dispatch.
- [ ] Report target count, changed versus cached jobs, input/output estimates labelled estimates, planned call count and maximum runtime. Never present estimates as actual account usage. Ask for the actual batch allowance before real model execution.
- [ ] Extend existing operator conditional_uses/repair_levers explanations without claiming official economic guarantees. Preserve previous verified rows until new outputs pass current contracts and publication boundaries.
- [ ] Run new suite plus test_semantic_compilation/test_semantic_publication/test_codex_ai_worker; medium review/commit. No actual model task yet.

## K5: Four-Level Coverage, Wiki And Actual Consumption

**Files:** knowledge_compile.py, knowledge_experience_compile.py, preplanned_start.py,
exploration_eligibility.py; new tests/test_full_semantic_coverage.py,
tests/test_initial_research_planning.py, tests/test_preplanned_start.py.

**Interfaces:** add build_full_semantic_report(root: Path, plan: dict) -> dict in
knowledge_compile.py; publish detailed JSON plus concise Markdown to existing
machine/reports. Extend existing wiki pages with dataset/operator-family summaries
and evidence backlinks; do not render the full field ledger into Obsidian.

- [ ] Write tests separating inventory, explained/documented coverage, compiler/binder eligibility and actual Start consumption; partial or unattempted targets remain counted.
- [ ] Add mixed fixture: usable Level field, missing VECTOR grain, unsupported operator, stale source and hypothesis-only polarity. Assert only appropriate operations are eligible, without marking all metadata universally mandatory.
- [ ] Run test_full_semantic_coverage; observe RED.
- [ ] Implement report using actual source bytes and existing validators. Reuse parsed source material within a report, but never reuse stale verification across mutations. Avoid per-row repeated large-file parsing.
- [ ] Verify prepared Start reads the new resources, not old sampled contexts/shadow ledgers; count exact usable distinct lanes. No compile/model/platform operation occurs at Start.
- [ ] Assert wiki distinguishes facts/hypotheses/observations and shows reusable conditions/counterexamples, not one enormous machine inventory page. Preserve publication ownership and current generation labels.
- [ ] Benchmark unchanged versus changed local compilation and bounded Start using real inventory size; record records/sec, wall time, peak working set and source/model call counts, without invented targets or platform throughput claims.
- [ ] Run new tests plus initial planning/eligibility/preplanned Start/wiki suites; review/commit.

## K6: Actual-Vault Recompile And Handoff

**Files:** existing operations docs, root todo.md/milestone.md; existing knowledge reports
and semantic-job artifacts only. No copied root entry documents.

- [ ] Run full offline discovery with credentials removed, root architecture/entry checks and current frontend contract tests. Freeze source for final verification.
- [ ] Prepare full-local actual inventory with zero model budget; report all target counts, sources, stale/conflicting/unsupported items and estimated changed model work.
- [ ] Run existing deterministic data/experience maintenance under user-approved local scope. Do not claim full semantic completion if model allowance/source repair/publication is still pending.
- [ ] With separately confirmed finite model allowance, execute changed explanation jobs; preserve all failed/unknown outcomes and do not silently extend budget. Otherwise hand off a concrete prepared plan, not a vague blocker.
- [ ] Publish only through existing reviewed/validated boundary when authorized; exact current-scope readiness must pass before any deployment recommendation.
- [ ] Produce actual-vault report with every identity accounted for and four-level coverage. Confirm no research/Stop/budget/proof/Alpha state changed.
- [ ] Update docs and handoff; verified Git push/equality precedes audited cleanup and affected regressions. No inferred sensitive deletion authority.

## Dependency And Acceptance Handoff

K1 before K2/K3 consumers; K3/K4 before K5; K6 consumes all verified contracts.
Independent test/review slices may run in parallel only with disjoint write scopes.
Next plan: 2026-10-23-semantic-research-readiness-closure.md. Its implementation
cannot assume all local records became trusted, only the reported usable subset.

User reviews this written plan before product implementation. Preserve previously
selected subagent execution, all with explicit medium-or-lower reasoning.
