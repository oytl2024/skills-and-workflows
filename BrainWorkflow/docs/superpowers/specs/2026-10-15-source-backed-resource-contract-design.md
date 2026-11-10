# Source-Backed Resource Contract Design

Date: 2026-10-15. Status: written specification for user review; implementation is not approved by this document alone.

## Purpose And Success

Close the real-source M1 gate without inventing platform metadata, rewriting inference as raw fact, or relaxing legacy checks. Use real documentation, operator signatures and scoped field captures to produce a small executable resource subset. Only after that acceptance prepare M2's pair-aware Scout spec and plan.

This corrects an evidence/interface mismatch found after M1: an absolute field timestamp is not the same as a platform execution-delay rule, and separate documentation cannot currently support a compiled typed operator contract. It does not prove that all missing information is present locally.

Success has two independent gates:

1. Engineering: strict contracts, deterministic source resolution and template compilation, compatibility, cancellation/replay and full offline regression.
2. Real resources: at least one nonduplicate baseline/treatment pair using actual accessible field identities and supported Level/Change/Relative constructions, with unreviewed drafts and complete binding receipts; no fictional substitutes or real simulations. Report support for all three feature families separately. Unsupported families remain rejected and cannot be scheduled; a missing indispensable source fact for every possible supported pair keeps the gate blocked. A successful pair is not global field/operator coverage.

## Scope And Authority

User authorized local source verification/repair, necessary bounded platform read-only capture and local knowledge compilation, including model assistance when needed. Authentication necessary for permitted reads is allowed; simulation, research resume, budget changes, final Alpha submission, old-run proof renewal and Git publication are not.

Keep raw/machine/wiki and the existing semantic jobs/publication/checkpoint boundaries. No new Agent framework, global truth ledger, Orchestrator state or routine Console button. Source-contract implementation requires approval of this spec, then an implementation plan. M2 remains a separate architectural change.

## Alternatives And Decision

| Approach | Benefit | Problem |
| --- | --- | --- |
| Require platform sources to contain the existing exact typed JSON and absolute timestamp | No contract change | Repeated capture of ordinary signatures and relative-delay documentation cannot resolve the representation mismatch. |
| Let the model fill missing metadata or mark it verified | Fast apparent readiness | Unverifiable types/timing, false provenance and silent gate bypass; rejected. |
| Add a versioned source-backed resource contract | Uses actual documented facts, keeps uncertainty explicit | Small interface and verifier changes; selected, with restricted derivation rules and backward compatibility. |

## 1. Evidence Layers And Identity

- Raw retains original platform responses/material, endpoint/page identity, captured date, exclusions and failed requests. Never insert derived types, units or synthetic timestamps into a captured response.
- Machine stores normalized facts and explicitly derived contracts, their verified premises and rule versions. Human-readable wiki explains meaning, applicability, uncertainty and derivation, not a giant field table.
- Each premise identifies a source path, existing content hash, source capture date, locator and exact supporting text or structured value. Verify source bytes before interpreting premises, selecting a rule, replaying cache, compiling or publishing.
- Indexed Markdown uses normalized body hashes; full-file transport/copy hashes remain separate. JSONL sources require full-file integrity plus exact row identity and scoped context. Bounded row selection never claims complete catalog coverage.
- Derived contracts bind all consumed sources and the derivation-rule version to a digest. Duplicate IDs, conflicting sources, altered quotes, wrong scope and incomplete premises reject; no first-match or model confidence override.
- `documented` source premises are not measured strategy evidence. A verified derivation is a compiler result, not a claim that the platform published that result verbatim.

## 2. Versioning And Legacy Behavior

One producer-controlled `resource_contract_version` distinguishes modes; absent means existing version 1. Version 2 is opt-in in the frozen resource envelope and its evidence pack, not a field chosen by the model. Mismatched versions reject.

- Version 1 preserves current `available_at`, `scope.as_of`, typed-definition checks, model schemas and frozen-run interpretation.
- Version 2 permits the source-backed timing and definition bases described below, while retaining explicit legacy facts when applicable. Explicit contradictory/future timestamps do not become acceptable merely because a delay rule also exists.
- `bind_template` may receive a keyword-only resource contract version with default 1; existing callers are unchanged. Only callers holding verified version-2 resources may pass 2. Passing a version flag is never sufficient evidence.
- Update source/compiler/context/schema versions and content keys when interpretation changes. Do not mutate old job manifests, failed receipts, releases or frozen research records. New semantics create new identities; unchanged failed/cancelled jobs remain terminal.
- Existing templates keep their legacy/v2 template schema and lifecycle rules. Resource-contract version is separate from `semantic_version`, `binding_version` and evidence grade; it does not promote a template.

The implementation plan must enumerate all affected readers/writers and prove that new optional data is either preserved and checked or rejected, never silently discarded by dataclass serialization.

## 3. Timing Contract

Version-2 fields may carry a strict `timing_contract` instead of a fabricated absolute availability timestamp. Required members:

| Member | Meaning |
| --- | --- |
| `kind` | `platform_execution_policy`, distinct from absolute timestamp evidence. |
| `scope` | Exact captured instrument/region/delay/universe tuple; no list cross-product. |
| `cutoff_class` | Explicit documented class: regular delay or an individually supported special cutoff. |
| `field_identity` | Exact dataset/field identity to which the captured policy applies. |
| `premises` | Verified references supporting policy, field classification and applicability. |
| `rule_id` / `rule_version` | Deterministic approved timing-resolution rule. |
| `historical_pit_verified` | `false` for this platform-policy mode; it cannot claim verified historical release alignment. |

The compiler may certify eligibility for a platform-managed experiment under the documented execution policy, not economic information availability for every historical observation. Outputs and wiki must expose this limitation.

Rules:

- Data Explorer access, `dateCreated`, capture time and freshness are not historical availability evidence.
- Delay must match actual scoped field capture and simulation settings; it is not freely selected to repair missing timing metadata.
- Regular Delay 1 documentation cannot certify Fast D1, other special cutoffs, dataset-specific lags or arbitrary uploaded/external fields. Ambiguous applicability rejects until separately sourced.
- Source dates remain real. Freshness and activity deadlines are independent. A newly compiled policy does not refresh an old source or prove current access.
- Unknown units remain unknown; only operations/slots requiring units are blocked by their absence. Do not require units for every Level feature, and do not infer them from field names.
- VECTOR support remains outside M1 feature grammar; no implicit reduction or new vector support is introduced here.
- Explicit timestamp and derived timing policy modes remain distinguishable in binding receipts. A policy-backed receipt must never serialize a synthetic `available_at` value.

Version-2 role metadata requirements may use `timing_contract`; the parser must require either legacy explicit availability or the selected, verified timing contract. Empty requirements or a model-written timing object cannot bypass validation.

## 4. Typed Operator Contracts

Keep existing explicitly typed source definitions valid. Add a separate `definition_basis` for derived definitions in version-2 resources. It identifies the operator, signature premise, type/parameter premises, approved rule/version and resulting definition digest.

The existing `definition` remains the resulting typed interface: description, ordered input/output types, named parameter types/required/default facts and source references. A separate basis makes the derivation visible rather than pretending raw contains this exact JSON.

Initial resolver supports only the M1-required operator intents: Change via `ts_delta`, grouped rank via `group_rank`, grouped demeaning via `group_neutralize`. Level requires no added operator. This is not a general signature interpreter or type inference engine.

Requirements:

- Signature parsing uses the existing restricted AST/parser or an equally bounded parser. Never evaluate source code.
- A signature supplies names/order/default literals only; it does not by itself prove MATRIX, GROUP, INTEGER, output type or economic meaning.
- Every required type and parameter constraint needs explicit applicable documentation or an approved compositional rule whose premises supply those facts. Unsupported parameter semantics remain unknown.
- Generic matrix documentation must be scoped to the relevant expression/operator family. Python Alpha and SuperAlpha reduction-array semantics are not interchangeable with regular Fast Expression operators.
- GROUP documentation may support a grouping role only when the specific signature and operator purpose also match. Vector exceptions cannot be ignored.
- Economic behavior must match the chosen intent: grouped demeaning needs documented subtraction of group mean, not merely a familiar operator name.
- AI can propose mechanisms, source locators and candidate interpretations. A deterministic verifier establishes whether the approved rule is applicable; free-form reasoning, source membership, confidence or quoted unrelated text is insufficient.
- If current materials do not explicitly support an indispensable type/rule, capture the relevant official detail page when available. If still absent, reject and retain the exact gap; do not invent a derivation to reach acceptance.

## 5. Capture And Source Integrity Repair

First inspect local sources; request only the missing relevant operator/detail and timing/type pages. Reuse bounded client timeouts/backoff and local caches. Do not run the whole Learn crawler or enumerate all fields to repair three operator definitions.

Capture must not immediately write inferred wiki conclusions or publish semantic resources before compile validation. Current all-in-one legacy capture scripts need a raw-only path for this maintenance scope.

For old mismatched hashes/classifications/indexes:

- Verify the original body and any available retained response before assigning corrected metadata. Retain original payload hash and capture date.
- Record an auditable correction receipt linking old metadata, verified new metadata and the reason. Do not hide an inconsistent original by changing dates or deleting it.
- `platform_api` cannot be blanket accepted as authoritative semantic evidence. Classify only verified endpoint/material families, keep unknown API captures outside the allowed source family.
- Publish corrected index references consistently with existing index/locking conventions; reject stale caches and conflicting references. Human and machine indexes must agree.
- If the original bytes cannot be verified, use a fresh bounded capture and leave the old source quarantined/unknown rather than retroactively certify it.

Raw-source repairs and machine normalization may be accepted independently, but neither proves executable semantic coverage on its own.

## 6. Integration And Responsibilities

| Existing boundary | Change |
| --- | --- |
| `semantic_contracts.py` | Strict optional timing/definition-basis contracts and source-reference validation; no lifecycle authority. |
| `data_ledger_compile.py`, `operator_semantics.py` | Preserve actual captured facts and derived metadata through canonical serializers; no guessed raw facts. |
| `semantic_compilation.py` | Select verified premises, apply bounded derivation rules, include versions/sources in jobs/cache keys; preserve cancellation and no-repeat failure behavior. |
| `knowledge_compile.py` | Use the same verifier for source audit and proposal compilation; distinguish material, direct/derived semantics and executable binding coverage. |
| `template_binding.py` | Default legacy path unchanged; explicit version-2 timing/type validation and auditable receipts. |
| `hypothesis_design.py`, `hypothesis_template_compiler.py` | Strict version-aware metadata requirements and resource checks; keep feature grammar, simple formulas and experiment controls unchanged. |
| `semantic_publication.py` and snapshot readers | Preserve/hash/check supported optional contracts through existing paired releases and binding receipts; do not add a parallel ledger. |
| Capture/index utilities | Raw-only bounded collection and auditable source repairs; no automatic publication. |
| Existing wiki compilation | Explain documented premises, derived contracts and remaining uncertainty in existing pages. |

Prefer existing modules. A focused pure helper is acceptable only if the implementation plan demonstrates that it avoids duplicated verification or an oversized mixed-responsibility module. No new long-running service or dependency is required.

## 7. Workflow

1. Freeze the maintenance request and source inventory; preserve Stop and all research state.
2. Validate local bytes/indexes; determine direct facts, derivable facts, unsupported facts and source freshness separately.
3. Repair verifiable source/index defects and perform only necessary bounded raw capture.
4. Compile a small resource subset with provenance-backed timing/typed definitions; validate all premises before model calls and on replay.
5. Generate structured economic proposals and deterministically compile actual baseline/treatment experiments. Keep them unreviewed and preserve conditions as statements unless an explicitly supported filter exists.
6. Audit real source/semantic/binding coverage and compile wiki explanations without refreshing raw dates.
7. Run offline regression and independent review, record unresolved external gaps honestly.
8. Only if real subset and engineering gates pass, write the M2 spec/plan. Do not start live research or M2 implementation automatically.

## 8. Acceptance Tests

- Legacy timestamp/signature fixtures and frozen records remain byte/behavior compatible; missing opt-in cannot change their interpretation.
- Regular Delay policy, special Fast D1 exclusions, scope mismatch, source expiry, forged premises, future/conflicting explicit timestamps and external-field misuse.
- Signature-only rejection; supported multi-source type derivation; unrelated/wrong-family documentation, bool/integer ambiguity, missing defaults and conflicting duplicate operator facts.
- Raw/index/body/full-file hash distinctions; safe correction replay; unknown API families; exact JSONL row/dataset/scope identity.
- Strict schemas reject unknown keys and model-created provenance/trust flags. New optional contract metadata survives serialization, release loading and frozen resource receipts.
- Same inputs produce the same derived contract/template/experiment digests. Changed sources/rules/versions change identities. Failed/cancelled unchanged jobs do not rerun the model.
- Baseline/treatment bind the same shared fields and controlled settings; GROUP auxiliary receipts remain verified. No new VECTOR, arbitrary ratio/regression/filter support.
- Existing Stop/Pause, POST identity recovery, budgets, candidate checks and final-submit authority stay unchanged.
- Fake-worker acceptance first; separately report real sourced Level/Change/Relative support and each unresolved arm. Passing fictional fixtures never grants real readiness.
- Full unit regression, compileall, entry/architecture validation and independent review before any completion claim.

## Deliverables And Approval

Deliver existing-module changes, focused offline tests, bounded capture/repair receipts, actual-source coverage evidence, unreviewed experiment drafts and concise wiki explanations. Report changed files/interfaces, measured tests, compatibility and unresolved facts in root todo.

This spec does not authorize implementation yet. After written-spec approval, create the implementation plan with TDD tasks and medium-or-lower subagent/reviewer effort. M2 still requires a separate written design/plan and approval after this gap closes.
