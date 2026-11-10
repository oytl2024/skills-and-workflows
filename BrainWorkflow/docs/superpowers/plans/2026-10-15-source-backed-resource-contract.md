# Source-Backed Resource Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close M1's real-source gap with versioned, auditable timing and typed-operator evidence, then prepare M2 design without running research.

**Architecture:** Retain existing raw/machine/wiki, semantic jobs, publication and binding boundaries. Add one pure evidence helper so source audit, proposal validation and binding use the same rules instead of duplicating inference in already-large modules. All new interpretation is explicit version 2; legacy defaults stay version 1.

**Tech Stack:** Existing Python 3.12, standard library, unittest and existing AST/client/locking/checkpoint utilities. No new dependencies or services.

**Spec:** `docs/superpowers/specs/2026-10-15-source-backed-resource-contract-design.md`, approved 2026-10-15.

## Global Constraints

- No Orchestrator, POST recovery, simulation identity, quota, Stop/Pause or final-submit changes. No simulation/research resume/proof renewal/commit/push.
- Actual source reads/capture and local knowledge/model compilation are authorized, but only after offline implementations pass. Authentication for permitted reads is not simulation authority.
- Raw is not rewritten with inferred metadata. Do not fabricate units, absolute availability, historical PIT verification, current access or freshness.
- Preserve explicit legacy timestamp/signature behavior and old frozen resources. Failed/cancelled unchanged jobs remain terminal; new compiler/rule/schema versions create new keys.
- Initial features remain Level/Change/grouped Relative; no implicit VECTOR reduction, arbitrary expressions or condition filters.
- Actual acceptance needs at least one nonduplicate real baseline/treatment pair; unsupported feature families remain explicit. No full-catalog enrichment requirement.
- Project rules override skill defaults: preserve existing dirty checkout, sole root todo, architecture-only milestone, no automatic commits. Tests use temporary roots; evidence goes in existing output/semantic-job boundaries.
- Every subagent/reviewer explicitly medium or lower. Add input/output/type comments and keep adjustable constants below imports. Manual edits use apply_patch.

## Review Focus

1. A version flag or model-written premise cannot grant trust; all consumed bytes and exact premise identities must be verified (Tasks1-3).
2. Regular Delay 1 cannot silently certify Fast D1/external fields or historical PIT; contradictory explicit timestamps must still block (Task2).
3. Optional basis/timing metadata must survive dataclasses, paired publication and frozen context, or be rejected rather than silently dropped (Tasks1/4).
4. Correcting an old payload hash must not certify unverifiable old bytes or renew capture dates; partial source/index publication must fail closed on restart (Task5).
5. Stale/changed source, cancelled worker and concurrent first preparation must not replay a model or publish a different contract under the same key (Tasks4/6).

## Interfaces And Ownership

- New `wqb/resource_evidence.py`: pure premise validation and finite derivation, no filesystem/network/model IO. One focused helper, not a framework or registry service.
- Existing `semantic_contracts.py`, `data_ledger.py`, `operator_semantics.py`: strict optional metadata and lossless serializers.
- Existing `template_binding.py`, `hypothesis_design.py`, `hypothesis_template_compiler.py`: explicit opt-in and unchanged default semantics.
- Existing `semantic_compilation.py`, `knowledge_compile.py`, `semantic_publication.py`, `codex_ai_worker.py`: verified context, shared resolver, versioned cache and persisted receipts.
- Existing capture/index utilities: targeted raw-only capture and verifiable repair. New tests only `tests/test_resource_evidence.py`; extend existing contract/binding/compile/publication/capture/hypothesis tests.
- Existing operation manual/wiki/compiler pages and root entry docs: explain support and uncertainty, no new knowledge hierarchy.

## Wire Decisions

- Producer-owned optional `resource_contract_version` on resource envelope and evidence pack; absent means 1, only exact integer 1 or 2 allowed, bool rejected, envelope/pack must agree.
- `Premise` is `{evidence_ref, locator}`. evidence_ref uses existing EvidenceRef fields. locator is exactly one of:
  - `{kind: markdown_quote, heading: str, quote: str}`: unique heading and exact LF-normalized text within that section.
  - `{kind: json_value, row_identity: object, value_path: list[str], expected_value: JSON}`: unique dataset/field/scope identity and exact typed value in verified JSON/JSONL, no evaluated paths.
- A source index alone is insufficient. Resolver receives full verified text/index, validates byte/body hashes via existing conventions, locators and allowed source family before applying rules.
- `timing_contract`: exactly kind/scope/cutoff_class/field_identity/premises/rule_id/rule_version/historical_pit_verified; kind=`platform_execution_policy`, historical_pit_verified=`false` only. Field identity includes dataset_id and field_id. Scope contains exact instrument_type/region/delay/universe.
- `definition_basis`: exactly operator/signature_premise/type_premises/rule_id/rule_version/definition_digest. Existing definition retains typed interface and evidence refs; basis is a separate optional sibling, never an extra key hidden inside definition.
- Canonical data rows may carry optional timing_contract; operator rows optional definition_basis. Missing optional members remain omitted in legacy round trips.
- Pure resolver output is `{status: supported|unsupported, value: object|null, rejections: list[dict]}`. Unsupported evidence never becomes a boolean verified flag.
- Resource v2 role metadata permits timing_contract instead of available_at only when the verified producer contract is v2. Version 1 keeps its existing requirement. A selected explicit timestamp, when present, retains its own strict check and cannot be overridden by policy.
- Large field JSONL must not be loaded into the 1MB design pack or force source-size caps upward. Stream-verify the original full-file digest and selected exact rows, then create a small immutable raw excerpt with original capture date, original path/full digest, row identities/digests and a separate extraction timestamp. It is labelled verified_raw_extract, not a new capture or semantic interpretation. Bind its own body/full hashes and reverify its extraction receipt against the original before use/replay; do not truncate a large source and pretend its hash covers the excerpt. Hash each original once per validation phase, not once per field.

### Task 1: Strict Optional Contracts And Premises

**Files:** create resource_evidence.py/test_resource_evidence.py; modify semantic_contracts.py, data_ledger.py, operator_semantics.py and existing serializer/contract tests.

**Produces:** `resource_contract_version(envelope: dict) -> int`; `verify_premise(premise: dict, source_index: dict, source_texts: dict) -> object` in the pure helper. Add `timing_contract_from_dict(row: dict) -> dict` and `definition_basis_from_dict(row: dict) -> dict` in semantic_contracts.py; no source/lifecycle authority from shape parsing alone.

- [x] Add RED tests `test_legacy_optional_fields_omitted`, `test_version_bool_unknown_or_mismatch_rejected`, `test_premise_hash_locator_identity_and_types`, `test_optional_contract_roundtrip`. Assert exact legacy dictionaries, unknown-key rejection, duplicate heading/row rejection and bool/int distinction.
- [x] Run `python -m unittest tests.test_resource_evidence tests.test_semantic_contracts tests.test_operator_semantics tests.test_data_ledger_compile -q`; record RED before implementation.
- [x] Implement strict wire parsing and pure source verification using existing Markdown/index/hash helpers. Bound premise count/quote size with named constants; reject oversized data without truncation. Do not accept all platform_api sources or treat hypotheses as platform definitions.
- [x] Markdown premise grammar is deliberately bounded: canonical ATX headings and straightforward fenced/inline source text, not full CommonMark rendering. Reject ambiguous unsupported escape/multiline-code/comment combinations with explicit ValueError rather than accepting hidden facts or adding a general Markdown parser dependency. Test hidden comments and actual nested field.dataset aliases; documented unsupported cases are not silently normalized into evidence.
- [x] Run the same suite to GREEN and independently review the evidence boundary; update sole root todo, not a new task ledger.

### Task 2: Timing Resolution And Legacy Binding

**Files:** resource_evidence.py, template_binding.py; resource-evidence/binder tests.

**Consumes:** Task1 strict contract and verify_premise.

**Produces:** `resolve_timing_contract(contract: dict, field_row: dict, scope: dict, source_index: dict, source_texts: dict) -> dict`. Extend `bind_template(..., *, resource_contract_version: int = 1, evidence_context: dict | None = None) -> dict`; evidence_context contains source_index/source_texts. Existing four positional arguments remain valid.

- [x] Add RED `test_v1_timestamp_path_unchanged`, `test_v2_regular_delay_policy_receipt`, `test_fast_d1_external_or_ambiguous_policy_rejected`, `test_policy_cannot_override_future_timestamp`, `test_policy_scope_and_source_age_bound`.
- [x] Run `python -m unittest tests.test_resource_evidence tests.test_template_binding -q`; record RED.
- [x] Implement only a regular platform Delay-1 timing rule initially. Require explicit premises establishing automatic delay, field applicability and exact captured scope. Reject special/unknown cutoff or external-field applicability; a name without Fast D1 suffix is not proof of regular status. Do not invent policy support if local docs lack a premise.
- [x] Preserve existing available_at path. Version-2 policy receipts include verified contract/rule/source digests and historical_pit_verified=false, no synthetic timestamp. Freshness reads actual source dates and caller frozen validation date, not compile time as source time.
- [x] Run GREEN plus old binder fixtures; independently review that version selection alone cannot grant readiness.

### Task 3: Restricted Typed Operator Derivation

**Files:** resource_evidence.py, semantic_compilation.py::_definition_supported, knowledge_compile.py::_coverage_operator_supported; existing semantic/operator tests and new resource-evidence tests.

**Produces:** `resolve_operator_definition(record: dict, source_index: dict, source_texts: dict, *, resource_contract_version: int = 1) -> dict`.

- [x] Add RED `test_signature_only_never_proves_types`, `test_supported_cross_source_definition`, `test_wrong_family_or_unrelated_quote_rejected`, `test_missing_parameter_fact_or_conflict_rejected`, `test_direct_typed_v1_definition_unchanged`.
- [x] Run `python -m unittest tests.test_resource_evidence tests.test_semantic_compilation tests.test_semantic_compile_console tests.test_operator_semantics -q`; record RED.
- [x] Implement finite rules for ts_delta, group_rank and group_neutralize only. Signature AST establishes names/order/default literals; applicable explicit documentation must establish required types, integer window constraints and operation meaning. Each rule validates exact premises and resulting typed interface; do not infer types from parameter names or keyword occurrence alone.
- [x] Reject absent indispensable premises with specific diagnostics. Keep raw syntax/description intact and distinguish directly documented definitions from source-backed derivations. Share the resolver between audit and proposal validation, not two acceptance implementations.
- [x] Run GREEN and review cross-source semantic applicability. Unsupported real definitions are a gate outcome, not permission to broaden rules during live operation.

### Task 4: End-To-End Version Propagation And Immutable Resources

**Files:** hypothesis_design.py/hypothesis_template_compiler.py, semantic_compilation.py, knowledge_compile.py, semantic_publication.py, codex_ai_worker.py; existing hypothesis/worker/publication tests. Modify research_planning.py/hypothesis_selection.py only if their existing resource readers must preserve/reject new metadata; do not implement M2 selection here.

**Consumes:** Tasks1-3; existing compile_hypothesis_design, prepare/compile_design_job and semantic release APIs.

- [x] Add RED `test_v2_proposal_to_binding_receipt`, `test_v2_contract_survives_release_and_snapshot`, `test_v1_pack_and_frozen_run_unchanged`, `test_changed_rule_or_source_changes_content_key`, `test_cancel_failed_cache_and_concurrent_preparation_stay_bounded`.
- [x] Run `python -m unittest tests.test_hypothesis_design tests.test_hypothesis_design_acceptance tests.test_semantic_publication tests.test_codex_ai_worker tests.test_ai_checkpoints -q`; record RED.
- [x] Propagate producer-owned version and verified context through validators, workers, binding and receipts; reject mismatches and dropped metadata. Bump hypothesis compiler and semantic/context task versions when interpretation changes. Model may propose interpretations but cannot choose trusted global version or self-verify facts.
- [x] Preserve version-1 OPERATOR_CONTRACTS behavior. For verified version-2 derived definitions, check intent through the approved rule and its sourced meaning premises, not exact membership in the old English-description whitelist. Retain original description rather than rewriting it into an accepted phrase. Add a real-source-format regression using current captured group_rank/group_neutralize descriptions and an unrelated-meaning negative case.
- [x] Preserve atomic paired publication/source digests and terminal no-repeat cache/cancellation. Verify raw premises before cache replay and after worker output. Keep default old worker schema/behavior and no new model calls on unchanged failures.
- [x] Run GREEN and cross-module review. Assert unreviewed/scout_only lifecycle, unchanged final-submit authority, exact shared baseline/treatment bindings and no modifications to the old research run.

### Task 5: Bounded Raw Capture And Auditable Source Repair

**Files:** scripts/capture_learn_material.py, knowledge_contracts.py; existing capture/source-index tests. No crawler framework or parallel source index.

**Produces:** `capture_resource_subset(root: Path, client: WQBClient, targets: list[dict], generated_at: str, *, request_limit: int = 12) -> dict` in the capture script; `repair_source_metadata(root: Path, paths: list[str], *, dry_run: bool = True) -> dict` and `extract_field_source_subset(root: Path, source_path: str, identities: list[dict], *, max_rows: int = 30) -> dict` in knowledge_contracts.py. Extraction returns excerpt/index metadata plus original full-file/row receipts, never derived semantics.

- [x] Add RED `test_targeted_capture_writes_raw_only`, `test_capture_budget_and_failed_request_evidence`, `test_source_repair_preserves_date_and_payload_digest`, `test_unverifiable_original_requires_fresh_capture`, `test_index_correction_restart_fail_closed`, `test_concurrent_source_index_upserts_preserve_both_rows`, `test_large_jsonl_excerpt_preserves_original_hash_and_date`, `test_excerpt_replay_rejects_changed_original`.
- [x] Run `python -m unittest tests.test_capture_learn_material tests.test_knowledge_contracts tests.test_knowledge_source_resolver -q`; record RED.
- [x] Implement raw-only subset capture using existing client/renderers. Targets are explicitly selected official operator list/detail or tutorial pages, not arbitrary URLs/search sweeps. GET only after required authentication; no simulation endpoints. Existing renderer/root helpers gain optional explicit root where needed, not process-global root mutation.
- [x] Future captures of known successful Learn endpoints receive the verified material-family classification; failures remain separate error evidence that cannot satisfy semantic premises. Do not blanket-trust platform_api or silently relabel old raw. Cover the ordinary known-endpoint writer as well as the bounded entry so the same classification bug does not recur on the next refresh.
- [x] Count attempted knowledge GETs against 12 even on failed attempts; reuse finite timeout/retry policy and preserve failure/429 evidence. Do not repeatedly authenticate, bypass biometrics or retry forever. If missing details need a larger scope, record the exact unresolved sources rather than expand silently.
- [x] Implement dry-run-first repair. Verify retained originals/response payloads; preserve old date/hash metadata in content-addressed source_repair receipts under existing semantic_jobs. Correct only proven body/payload/classification/index defects using existing index writers/locks. Unverifiable bytes remain unknown; prefer fresh capture. No blanket platform_api trust or date renewal.
- [x] Source-index preflight found existing upsert/write functions unguarded. Add one shared local index write guard across read/merge/write and file-atomic staging; avoid nested acquisition when upsert calls an internal writer. Verify human/machine agreement before acknowledging a repair and detect/recover partial publication on replay. Do not claim two independent files are a filesystem-atomic transaction or change legacy source evidence grades.
- [x] Implement streaming field extraction with bounded row memory, exact duplicate/scope rejection, full original integrity verification and content-addressed immutable excerpts under the existing raw/platform/data_fields capture family. Resolve original-source indexing from verifiable capture metadata, not a model-supplied source family. Preserve original bytes/dates and identify extraction distinctly. Integrate receipt verification with existing material preparation before model/cache access, leaving old small-source behavior unchanged.
- [x] Extend resource_evidence JSON locators narrowly for canonical Markdown field excerpts (explicit JSON block/row container), with source type platform_data_field_capture and extraction receipt checked upstream against the original. Add `test_markdown_field_excerpt_json_locator` and a negative documentation-example case. Generic Markdown examples or a verified_raw_extract marker alone cannot certify captured fields. This is a Task5 format adapter, not new operator inference.
- [x] Run GREEN and review partial-publication/restart behavior and sensitive path exclusions. These utilities do not compile wiki or publish automatically.

### Task 6: Real Subset Compilation, Wiki And Final Acceptance

**Files:** existing knowledge compile/audit/demo interfaces, existing wiki compilation/manual, root todo/milestone; extend existing acceptance tests. Runtime artifacts remain in existing output and machine/semantic_jobs boundaries.

- [x] Add RED fake-transport acceptance for real-source-format input -> verified timing/type contracts -> structured proposal -> actual compiler/binder -> immutable unreviewed pair; include unsupported arms, tampered/cancelled replay and unchanged old release/run.
- [x] Run `python -m unittest tests.test_resource_evidence tests.test_hypothesis_design_acceptance tests.test_hypothesis_design_demo tests.test_semantic_compile_console -q`; implement minimal integration and run GREEN before real knowledge operations.
- [ ] Inventory actual sources with Tasks1-5, repair only verifiable defects, capture only missing/freshness-required subset within scope. Before each real model job verify sources, compact context and task limits; at most one execution for each content key and four distinct model jobs for this initial subset, no automatic retries/whole-catalog enrichment. This conservative maintenance bound is not a claim about account quota; unresolved work remains explicit when reached.
- [ ] Compile actual resources using existing knowledge commands, never manually copy fabricated artifacts around gates. Save source/rule/binding digests and support matrix for Level/Change/Relative. Require at least one actual nonduplicate baseline/treatment pair; if none can be supported, report the exact external fact blocking it and leave gate blocked.
- [ ] Compile existing human wiki pages with platform facts, derived contracts and uncertainty separated. Preserve original raw dates and partial coverage. Record existing historical ledger fragments explicitly, not as global cleanup completed.
- [x] Freeze source and run `python -m unittest discover -s tests -q`, `python -m compileall -q wqb tests`, `python -m unittest tests.test_project_architecture tests.test_project_entry_docs -q`, and `git diff --check`; compare before/after source digest. Filter credentials in offline test children; set process SystemRoot/windir on Windows and local NO_PROXY without modifying global configuration.
- [x] Collect final independent review and fix actionable findings, rerun affected/full tests after source changes. Report code/interfaces, tests, real coverage and remaining blockers; preserve old research pause/proof and all dirty work. No automatic deployment/resume or Git publication.
- [ ] Only after both gates pass, prepare the M2 written spec for frozen pair-aware Scout under existing budgets and default-off new-run activation. Do not implement M2 or run simulations as part of this task.

## Self-Review And Execution Handoff

Spec sections1-2 map to Tasks1/4; timing to Task2; typed definitions to Task3; capture/integrity to Task5; responsibilities/workflow/acceptance to Tasks4/6. All five review-focus classes have named tests. Wire version, context keys and public defaults are consistent; no second truth ledger or new research authority.

Recommend sequential subagent-driven execution with independent review at each task, explicit medium effort, because source/type/timing mistakes could silently invalidate every later experiment. Reuse the dirty checkout only after verifying the existing in-place rationale still holds; never isolate by omitting required uncommitted M1 code. Root todo is the sole handoff ledger.

The user approved this plan and sequential implementer/reviewer execution on 2026-10-15. Execute Tasks1-6 without intermediate permission requests for already-authorized offline work; current progress and interruption recovery are solely in root todo.md. Delegated reviews execute the approved review scope, rather than asking the user to approve it again. Consolidate genuine external/security/protected-decision blockers; do not relax contracts to manufacture acceptance. M2 implementation still requires its separate approved spec and plan.
