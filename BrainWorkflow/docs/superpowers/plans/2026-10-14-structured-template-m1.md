# Structured Template M1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver sourced structured economic designs, deterministic V2 drafts and explicit baseline/treatment plans, with an honest real-source coverage audit and offline demo.

**Architecture:** Add one constrained design/compiler module beside existing semantic compilation; reuse AST binding, source validation, checkpoints and proposal/publication boundaries. Repair relevant source ingestion in existing modules rather than a new knowledge service. M1 produces validated proposals only; Scout scheduling remains unchanged.

**Tech Stack:** Existing Python 3.12, standard library ast/json/hashlib/unittest, existing Codex worker boundary; no new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-10-14-structured-template-upgrade-design.md` (approved 2026-10-14).

## Global Constraints

- No Orchestrator, Stop/Pause, API executor, identity algorithm, quota or final-submit changes; no real model/WQB/capture, real-vault mutation or research resume in development/tests.
- Legacy v1/v2 inputs and frozen runs retain current behavior. No commit/push without authorization. Preserve unrelated dirty edits.
- Use existing SemanticPolicy defaults: maximum3 mechanisms, maximum2 condition branches; maxima are not fill targets. Individual formulas remain simple.
- Level, Change, grouped Relative only. No unsupported fallback, arbitrary ratios, regression, invented signatures or fabricated availability.
- Strict schema and evidence validation precede persistence; compiled is not reviewed/measured. Missing local metadata can block usable-real-subset acceptance even when compiler tests pass.
- Subagents/reviewers explicitly reasoning_effort=medium or lower. Manual code edits via apply_patch; input/output/type comments on new functions.
- Keep files in existing directories. Test artifacts use isolated temporary roots and clean up. Human cleanup list is separate; never recreate deleted old launchers or mock directories.
- M2/M3 are subsequent plans after M1 acceptance, not implied delivered features.

## Review Focus

1. Same operator/field ID in different snapshots or datasets must not borrow another record's evidence (Tasks1/3).
2. Narrative conditions without observable proxies must not silently become executable filters (Task2).
3. Source capture/creation dates and existing generic tags must not masquerade as verified availability or financial meaning (Tasks1/4).
4. A draft accidentally marked reviewed must not enter the active library or existing research snapshots (Tasks3/5).
5. Failed/cancelled workers, malformed cache and concurrent retries must not publish or repeatedly invoke a model (Task5).

## File Responsibilities

- New `wqb/hypothesis_design.py`: strict schema/content identity and thin compiler entry; `wqb/hypothesis_template_compiler.py` owns pure lowering and experiment drafts, no filesystem/network IO. This focused split avoids mixing the large validator and compiler.
- Existing `wqb/operator_semantics.py`, `data_ledger_compile.py`, `knowledge_compile.py`: source normalization, bounded source selection and coverage reporting.
- Existing `wqb/semantic_compilation.py`, `codex_ai_worker.py`, `ai_checkpoints.py`: verified materials, design worker schema and existing execution/cancellation/cache boundary.
- New `scripts/demo_hypothesis_design.py`: developer-only offline audit/demo entry, never automatic production execution.
- Tests: new `tests/test_hypothesis_design.py`, `tests/test_hypothesis_design_acceptance.py`; extend existing semantic/operator/data/checkpoint tests.
- Existing manual/architecture and root todo: document real support and gaps; no second progress ledger.

### Task 1: Baseline And Sourced Resource Normalization

**Files:** operator_semantics.py, data_ledger_compile.py, knowledge_compile.py; existing operator/data/semantic-console tests.

**Interfaces:** `normalize_data_category(value: object) -> tuple[str, list[str]]` in data_ledger_compile returns category label and explicit id/name tags. `semantic_resource_coverage(resources: dict, scope: dict) -> dict` in knowledge_compile reports indexed_material/verified_semantics/executable_bindings plus reasons, never mutates resources. Existing operator compiler signature stays unchanged.

- [x] Run targeted baseline: `python -m unittest tests.test_operator_semantics tests.test_data_ledger_compile tests.test_template_binding tests.test_semantic_compile_console -q`; record actual result before edits.
- [x] Add RED tests for dictionary category stringification, Markdown-vs-JSON operator capture preservation, syntax without typed definition remaining unknown, hash-conflicting sources and missing provenance paths. Test coverage never counts mere freshness/row presence as executable.
- [x] Run targeted tests and record RED; minimally normalize categories and preserve indexed Markdown syntax/descriptions in the existing ingestion path. Reuse current Markdown/source-index verification; do not guess types from operator names or redirect to nonexistent docs. Where source facts conflict, preserve evidence and reject instead of choosing silently.
- [x] Re-run targeted tests to GREEN; record real-source subset gaps from read-only frozen copies, with scope-row and unique-field counts distinguished. Review independently; do not invoke actual semantic compile on the vault.

### Task 2: Strict Design Contract And Economic Branches

**Files:** new hypothesis_design.py and test_hypothesis_design.py.

**Interfaces:** `design_output_schema() -> dict`; `validate_hypothesis_design(answer: dict, evidence_pack: dict, policy: SemanticPolicy) -> dict`. Validated output includes design_version=1, content-derived design_id, mechanism_family, rationale/prediction/conditions/alternative/falsification, field_roles, feature_plan, experiment_plan, evidence_refs. IDs are derived, not trusted from AI. Use the existing schema-validator subset rather than adding a dependency.

Feature grammar is bounded depth2: role leaf; level(role); change(role, horizon); relative(role, group_role, comparison). comparison is explicit group_rank or group_demean intent, each requiring a sourced signature at compile time. No arbitrary expression/operator-name nodes. Prediction is positive/negative/unknown; conditions explicitly distinguish observable/interpretive/unidentifiable. Experiment has baseline and at most one treatment with controls and rejection/inconclusive criteria. Existing seven-card text remains one sentence per field.

- [x] Add RED tests rejecting unknown keys, nonfinite/overflow values, code/formula fragments, explicit fabricated field IDs/evidence, unsupported nesting/feature/condition mode, excessive3/2 branches and false measured conclusions.
- [x] Run `python -m unittest tests.test_hypothesis_design -q`; record RED.
- [x] Implement strict parsing, source-bound references and canonical content identity; no filesystem, mutable state or platform calls. Two applicable conditions must change the structured prediction/required role/experiment treatment, not just duplicate narrative with a different window.
- [x] Run tests to GREEN, including same normalized design/evidence -> same ID, changed evidence/compiler version -> changed identity; independent review of strictness and conditional meaning.

### Task 3: Deterministic Compiler And Experiment Attachments

**Files:** hypothesis_design.py, hypothesis_template_compiler.py, test_hypothesis_design.py; existing binder tests only if integration adds regressions.

**Interfaces:** `compile_hypothesis_design(design: dict, resources: dict, scope: dict) -> dict`. resources contains source-validated field_rows/operator_rows/source_index. Result is `{status, drafts, experiment, rejections, compilation_digest}`. Drafts are V2 TemplateRecord-compatible unreviewed records. Experiment is a non-authoritative attachment referencing baseline/treatment drafts and controlled settings, not candidate_id/POST state.

Lower role-based Level/Change/Relative nodes to restricted AST then parse_kernel/bind_template. Choose only operators with exactly compatible documented signatures: ts_delta for change; group_rank for rank comparison; group_neutralize only when its documented meaning matches group_demean. No substitutions based on familiar names alone. Use explicit supplied horizon/settings, not a search grid. Generated slots preserve required metadata, vector reduction, scope and economic roles. Fingerprints include validated design, evidence, compiler version and exact settings. No general algebraic-equivalence solver.

- [x] Add RED tests for legal sourced Level/Change/Relative, missing group/signature/unit/grain/timing, same-name ambiguous fields, cross-scope, unsupported operations and AST/settings duplicates. Assert baseline/treatment differ only in the declared treatment; invalid arm rejects the experiment.
- [x] Run compiler and binder tests to record RED, then implement lowering and typed binder revalidation. Map errors to explicit unsupported_feature/missing_operator_definition/missing_field_semantics/incompatible_scope/ambiguous_field/invalid_units/lookahead_risk/duplicate_template reasons; retain supporting diagnostics.
- [x] Run `python -m unittest tests.test_hypothesis_design tests.test_template_binding -q` to GREEN. Verify no compiled output self-marks reviewed, measured or submit_proven and deterministic serialized results on replay.
- [x] Independent review of type/evidence/AST boundary; reuse mature binder unchanged unless a demonstrated contract bug requires a separately explained scoped change.

### Task 4: Usable-Knowledge Audit And Real-Source Acceptance

**Files:** knowledge_compile.py, test_hypothesis_design_acceptance.py, demo_hypothesis_design.py.

**Interfaces:** `audit_hypothesis_resources(root: Path, scope: dict, template_requirements: list[dict]) -> dict` in knowledge_compile is read-only. Output includes source fingerprints and material/semantic/binding coverage, unknown reasons and required additional source facts. It must not turn audit into implicit capture/compile.

- [x] Add RED tests using actual existing source formats: latest operator Markdown syntax/descriptions, structured data categories and old source paths. Fixture copies retain original missing fields; no hand-added successful metadata represented as raw source.
- [x] Run acceptance tests to record RED; implement bounded source selection and validation through existing source-index/receipt contracts. Prefer required operators/field roles, not one model call per field or exhaustive catalog enrichment.
- [x] Verify audited real-source samples either produce legitimate bindable drafts or exact missing-fact rejections. Creation/capture dates, coverage ratios and descriptions do not supply historical availability/grain/units. An unsupported feature remains unsupported, not silently omitted from the coverage report.
- [x] Review coverage evidence. If no usable local subset exists, record M1 real-knowledge gate as BLOCKED and the exact external materials needed; continue independent offline implementation, never claim full M1 readiness or weaken gates. Actual vault compilation/capture/model runs require separate authority.

Task4 audit engineering is reviewed; the real usable-subset acceptance gate remains **BLOCKED**, not completed. Read-only evidence: `output/structured-template-m1-source-audit.json`, 30 sampled fields, zero verified semantics/executable bindings. Do not substitute fixture success for this gate.

### Task 5: Bounded AI Proposal And Existing Proposal Boundary

**Files:** semantic_compilation.py, knowledge_compile.py, codex_ai_worker.py, relevant checkpoint/semantic tests.

**Interfaces:** `prepare_hypothesis_design_job(root: Path, evidence_pack: dict, policy: SemanticPolicy) -> Path` and `compile_hypothesis_design_command(root: Path, config: dict) -> dict` in knowledge_compile. Reuse knowledge job manifests and verified material references, with task kind=hypothesis_design. Return validated proposals/attachments/diagnostics; do not publish or mutate research. Checkpoint type hypothesis_design routes to Task2 schema rather than free-form skeleton generation.

- [x] Add RED tests for compact source-bound context, relative material paths/hash failures, replay no model rerun, cancellation before/after output, malformed cache, worker failure and unknown verdicts. Fake executor only; production credential filtering/read-only/medium boundary remains unchanged.
- [x] Record RED; reuse append_ai_checkpoint/run_ai_checkpoint and existing semantic material-copy/cache/cancellation protocol rather than a second worker lifecycle. Cache key includes design schema/compiler/policy/evidence/context versions. No automatic retry of a failed unchanged content key.
- [x] Route output through Tasks2/3, preserve proposals as unreviewed and digest-bound attachments. Existing semantic publication handles only already-admitted resource records; no new reviewed bypass. Add tests that compilation alone cannot alter active release or frozen run, and legacy semantic checkpoints retain their schema/behavior.
- [x] Run `python -m unittest tests.test_hypothesis_design_acceptance tests.test_codex_ai_worker tests.test_ai_checkpoints tests.test_semantic_compilation tests.test_semantic_compile_console -q` to GREEN; independent review.

### Task 6: Offline Demo, Documentation And Full Acceptance

**Files:** scripts/demo_hypothesis_design.py, acceptance tests, operations/user_workflow_manual.md, root milestone.md/todo.md.

**Demo CLI:** `python scripts/demo_hypothesis_design.py --mode audit|demo --evidence-pack PATH --output-dir PATH`. audit uses only supplied frozen resources; demo accepts a supplied JSON design/fake transport in tests, never invokes a production model or WQB. Emit design.json, drafts.json, experiment.json, coverage.json and diagnostics.json only under the explicitly supplied output directory. Test same-input rerun byte stability and refusal to overwrite source/vault authority paths.

- [x] Add RED demo/integration tests for evidence -> fake AI design -> compiler -> binder -> unreviewed proposal, legacy library unchanged, honest real-source failures and cancellation. No manually copied artifact shortcuts past validation.
- [x] Implement and run the offline demo in an existing output subdirectory with explicit frozen input. Document compiler-vs-real-knowledge acceptance separately; no new normal-use research buttons. Keep canonical raw/machine/wiki layout and source distinctions.
- [x] Run focused suite, `python -m unittest discover -s tests -q`, `python -m compileall -q wqb tests`, entry/architecture tests and `git diff --check`; freeze source and collect independent final review. Do not renew old-run proof or resume research automatically.
- [x] Record files, interfaces, measured test/demo results, remaining metadata blockers, exact next command and uncommitted changes in root todo; update architecture only for delivered capabilities. Hand back M1 only when both engineering and sourced subset gates are satisfied, otherwise explicitly report the incomplete gate.

Engineering closure: independent reviews passed; frozen full suite 1805 tests, zero failures, two skips, matching before/after source digest (root todo). Fictional offline demo produced two unreviewed drafts with byte-stable replay. **Overall M1 usable acceptance remains BLOCKED** by Task4 actual source facts/integrity; M2/M3 not started. No real model/platform/vault mutation, old-run proof renewal, research resume or commit/push occurred.

## Subsequent Milestones (Not Executed By This Plan)

M2 gets a separate plan after M1 acceptance: default-off new-run flag, frozen experiment attachments, pair-aware selection before cap, no candidate-ID/schema mutation, fixed Scout settings and original quota/replay tests. Reuse current API executor and leave Discovery/Repair parameter optimization intact.

M3 gets a separate plan after M2 stability: reproducible mechanism evidence from identity-verified research records, scope/version/attempt/control separation, cautious prediction labels and bounded retrieval of failures/inconclusive outcomes. M1 may accept supplied history summaries; that is not a claim that M3 evidence generation exists.

## Execution And Approval

User approved this plan and task-by-task subagent execution on 2026-10-14. Use independent medium-effort review, sequential ownership for shared files, and the sole root todo ledger. Checkboxes track engineering steps, not real-knowledge readiness; the latter remains a separate acceptance gate. No automatic commits; record proof and handoff after each task.
