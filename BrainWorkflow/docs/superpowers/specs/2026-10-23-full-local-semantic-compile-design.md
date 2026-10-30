# Full Local Semantic Compilation And Workflow Readiness

Date: 2026-10-23
Status: approved by user on 2026-10-28; implementation acceptance tracked in outer todo.md

## 1. Goal And Scope

Make every locally captured operator and data field explainable and accounted for,
then expose only source-verified, operation-compatible resources to research.
Reuse the existing raw/machine/wiki vault, semantic jobs/publication, compiler,
Orchestrator and desktop application. No new agent framework or knowledge authority.

All means the complete local inventory, not all resources available on the live
platform. Current measured inventory is USA-only. Additional regions and missing
official documentation require separately scoped capture authority.

The actual audit is knowledge/machine/reports/knowledge_recompile_audit_2026-10-23.md.
It establishes inventory, one source-verified active operator and a narrow historical
field/template subset, not general new-Start readiness.

## 2. Approach

Reject bulk marking of current rows as reviewed: explanations cannot create facts.
Reject a replacement knowledge service/framework: it adds an unnecessary authority.
Use source-bounded incremental compilation within existing modules and contracts.
Current immutable releases and old-run snapshots remain readable and unchanged.

Full processing coverage and verified coverage are separate acceptance measures.
Every inventory identity receives either an explanation with evidence classification,
or an explicit missing/conflicting/unsupported result. Never drop failed targets
from the denominator or claim that attempted compilation made all targets trusted.

## 3. Explanation Contract

Use existing documented/hypothesis/measured EvidenceRef kinds and existing review
statuses. Do not introduce a blanket trusted boolean. Review status, source validity,
compiler support and measured strategy usefulness are independent.

Operator facts: official meaning, signature, inputs/output types, parameter syntax,
documented constraints, missing-value behavior when documented, source and capture date.
Operator research explanations: mathematical effect, appropriate conditions,
economic mechanisms it can express, counterexamples, interactions and Repair uses.
Research explanations are hypotheses unless supported by specific measured evidence.
No causal conclusion follows merely from a successful backtest.

Field facts: dataset/field identity, literal meaning, type, applicable scope, measured
coverage/date and documented timing/grain/unit/frequency when available. Availability
cannot be inferred from capture date; polarity cannot be inferred from a field name.
Field research explanations: economic role, plausible direction/conditions, confounds,
compatible template families and falsification experiments. Unsupported details stay
unknown; an explicit research assumption is not an official encoding fact.

Preserve dataset-level common explanations and field-specific differences. Link scope
rows to the appropriate evidence rather than duplicate long prose or model calls for
each scope. Existing machine resources remain the operational authority; readable
summaries stay in existing wiki categories, not giant ledger Markdown pages.

## 4. Version-Aware Maintenance

knowledge_maintenance must distinguish first-time legacy migration from maintenance
of an active semantic release. Active releases must no longer make ordinary local
maintenance fail merely because legacy migration is inapplicable.

Data/research/experience compilation and health checks can update their owned derived
artifacts. They cannot bypass semantic_publication or overwrite reviewed resources.
Semantic changes use the existing bounded job, schema, verification and publication
boundary. New producer requirements cannot rewrite an old immutable release.

Failed targets leave previous valid resources available and preserve rejection evidence.
Compilation timestamps do not replace capture dates or extend source freshness.
No automatic deletion, research resume, proof renewal or source recapture.

## 5. Source Identity And Hashes

Reuse knowledge_contracts and semantic_compilation source verification. Define the
canonical identity projection explicitly: path, content hash, capture date, source
type/family and all authority-relevant provenance/repair/extract fields.

Derived metadata such as file_sha256 must be verified against actual full bytes.
Its absence from a canonical index must not alone reject a context that carries an
independently valid enrichment. Conversely, never discard an asserted hash or
ignore a changed authority field simply to make records compare equal.

Keep Markdown body hashes distinct from full-file hashes. Actual content mismatch
requires evidence-based repair from original material, not overwriting the expected
hash with whatever bytes currently exist. Preserve original and repair receipts.

Regression cases include valid enrichment, incorrect full hash, changed body,
changed scope/date/type, conflicting indexes and invalid repair/extract receipts.

## 6. Field Semantics And Compiler Consumption

Reuse data_ledger/data_ledger_compile optional semantic fields, existing source-bound
compiler contexts and semantic contracts. Raw capture facts remain distinguishable
from certified semantic enrichment and project hypotheses.

Recompiling platform metadata must not silently erase valid semantic enrichment.
Merge enrichment only when dataset/field/scope/source identity remains compatible;
changed identity invalidates reuse and preserves diagnostic history. Do not blindly
copy a historical context row into the current ledger.

Require metadata per operation, not a universal impossible completeness gate:
VECTOR reduction needs supported grain/reducer; timing-sensitive operations need
their timing premise; unit-sensitive comparisons need compatible units. Missing an
unrelated attribute must not block every possible use of a field.

Level/Change/Relative and the already implemented sourced conditional subset remain
the supported feature domain. Type-checking alone does not establish economic meaning.
Unsupported types/operators are visible inventory entries, not executable proposals.

Start consumes only eligible current exact-scope rows and frozen certified resources.
No live discovery or whole-vault compile is introduced into Start.

## 7. Complete Inventory And Efficient Compilation

Build the target manifest deterministically from all local captures/ledgers; retain
source generation, unique dataset/field identity and actual scope membership.
Deduplicate scope copies for explanation work, never for measured scope coverage.

First perform deterministic source parsing/validation. Group model-assisted economic
explanations by dataset or operator family, with explicit target IDs and bounded
inputs/outputs; reuse completed valid jobs and only process changed inputs.
Do not launch one model task for each of 153513 scope records.

Large batches require an explicit model-call/token/wall-time allowance before launch.
User authorization of this design does not imply an unlimited model or platform
budget. Unknown job outcomes are not automatically replayed. Readonly sources,
strict schema and medium-or-lower delegated reasoning remain required.

Report four levels, each with its own denominator and rejection reasons:
1. Local inventory and scope/source certification.
2. Documented facts plus hypothesis explanations and their evidence classifications.
3. Typed, source-verified features/templates that actually compile/bind.
4. Resources actually consumed by new-Start and deterministic Repair tests.

Also report stale sources, unsupported operations, conflicts, rejected targets and
unattempted work. No model-generated prose may hide low executable coverage.

## 8. Repair And Remaining Gaps

After knowledge consumption is verified, extend the existing finite Repair provider,
not an additional agent loop. Use trusted signatures plus explicit project search
rules, preserving the economic kernel and comparing to the accepted incumbent.
Cadence-aware windows are used when cadence is known. Otherwise bounded project
windows (for example 5/22/122/252) remain experiment choices, not source facts.
Transforms and neutralization must have verified supported inputs/settings and
declared invariants; no claim that all transforms preserve meaning or direction.

Add one integrated two-lane/four-root/depth-two scenario through Seed and Repair,
covering both-signal paths, negative confirmation, fallback, rollback, accepted-parent
cache reuse, Stop/restart, shared accounting and separate final submission authority.

Hard HTTP total-time protection must reuse owned-worker supervision where feasible.
Persist request identity before dispatch; terminate/reconcile only owned work after
the bound. Never release a POST fence while its sending worker is still active,
silently refund attempts or replay an unknown POST. Durable Stop remains dominant.

Only after resource/read-model/E2E checks and final EXE revision verification may
formal entry migration be proposed. Legacy-run proof renewal and live research
remain separately authorized operations.

## 9. Ownership And Compatibility

Expected owners: knowledge_maintenance.py (version-aware maintenance),
knowledge_contracts.py/semantic_compilation.py/resource_evidence.py (source facts),
data_ledger.py/data_ledger_compile.py (field enrichment), operator_semantics.py/
semantic_contracts.py (operator explanations), semantic_publication.py (immutable
release), knowledge_compile.py (coverage), preplanned_start.py (consumption),
repair_search.py (finite edits), existing driver/client supervisor (network bound).
Use existing wiki compiler, tests and reports; do not introduce parallel stores.

Specific code/test tasks and dependency order are written in the implementation
plan after approval of this spec. Old rows without optional enrichment remain
readable and honestly ineligible where required; old runs keep their frozen path.

## 10. Acceptance

Every local identity accounted for; no unexplained omissions or global trust flip.
Every claimed official fact traceable to validated original bytes and exact identity.
Every claimed executable feature passes existing type/source/binding checks.
Recompilation is incremental/idempotent, preserves valid enrichments and capture
dates, and never silently promotes hypotheses or publishes unsupported operations.
Actual-vault report distinguishes what was verified from what merely exists.
Full offline regressions, adversarial provenance tests and integrated consumption
must pass before claiming knowledge maintenance repaired. Report external/source
gaps rather than labelling the entire workflow ready.
