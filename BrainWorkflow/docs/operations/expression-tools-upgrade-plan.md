# Expression Tools And Script Repair Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans after approval. Implement task by task with failing tests first. This is a proposed plan, not an implemented capability.

**Goal:** AI reads local research experience, selects fields/operators/parameters, uses code tools to construct and validate expressions, then declares a complete experiment tree; scripts freeze inputs and execute finite Repair searches without late model decisions.

**Architecture:** Reuse the existing AST binder, task-bound MCP, tree validator, execution package and Repair runtime. Remove research-content admission from the new expression-tool path rather than adding a second agent framework or loosening the legacy compiler globally.

**Tech Stack:** Existing Python, standard-library AST/JSON, current local MCP and existing desktop build. No new service, database or dependency.

**Spec:** Design Contract below. Status: approved Nov25; implementation in progress.

## Design Contract

### Independent Modules

| Module | Input -> output | Change |
| --- | --- | --- |
| Knowledge/query | raw/machine/wiki -> paged resource cards/text | Reuse; expose technical signatures separately from economic confidence |
| AI planning | experience, cards, task limits -> hypotheses, AST requests, tree and finite Repair proposals | Replace fixed feature-family output; no mandatory prose format or semantic whitelist |
| Expression construction | structural nodes + exact resource identities -> canonical expression, type, diagnostics and binding receipt | New small pure adapter over template_binding |
| Experiment/tree | compiled baseline/treatment receipts + routes -> executable graph | Reuse graph rules; remove dependency on economic-card acceptance for new mode |
| Package producer | validated graph, selected resources and finite search recipe -> immutable local package | Script-owned, hash-bound; no full-vault copy or model-generated code |
| Repair search | measured parent + frozen operators/parameters/rules -> finite deduplicated candidates | Connect generic AST edits to existing scheduler, comparisons and rollback |
| Transport/evidence | tool requests/results and child lifecycle -> bounded diagnostic records | Add durable public results/diagnostics, not private model reasoning |
| Runtime/authority | sealed scientific inputs + live Stop/accounting -> controlled simulations/candidates | Unchanged |

### Admission Rules

Remove hard rejection for one-sentence prose, economic ID naming conventions,
trigger IDs equal to source paths, semantic phrase membership, reviewed-template
availability, unknown polarity/timing/grain, empirical-prose heuristics and fixed
Level/Change/Relative economic families. These may inform AI or produce warnings;
they do not certify truth and cannot be used as hidden execution requirements.
Scripts derive internal IDs, field selection, source references and hashes; AI
does not duplicate identity bookkeeping in prose or invent missing source facts.

Retain only concrete compatibility checks: valid structural input, supported AST,
actual selected field identity/type/scope, unique operator signature, parameter
binding/type, numeric bounds actually required by the technical contract, valid
graph routing and immutable self-consistent package/search inputs. Retain size,
recursion, time and work budgets as resource-safety bounds, not fill targets.
No semantic freshness/publication/certification prerequisite for resource use.

Stop, shared 4000/day accounting, dedup, unknown POST reconciliation, correlation
check validity, Seed/performance rules and separate final-submit authorization
are independent and unchanged. No live model, WQB, capture or research authority
is granted by this plan.

### Expression Tool

Proposed `compile_expression(request, resources, scope) -> dict` in
`wqb/expression_tools.py`, exposed through the existing budgeted MCP query owner.
Success returns canonical expression/AST, output type, used fields/operators,
parameter bindings, receipt identity and warnings. Failure returns stable codes,
JSON node paths and actionable diagnostics, never a guessed replacement formula.

Node kinds: exact field identity, scalar literal, named operator call with args
and kwargs, unary +/- and binary +,-,*,/. These are the existing parser's grammar,
not a claim of full BRAIN language support. Comparisons/conditions use operators
with supported signatures. Assignments, arbitrary Python, attributes, indexing,
imports and unsupported language constructs cannot silently enter execution.
Builder emits AST safely; it does not interpolate arbitrary formula fragments.

Reuse `template_binding.parse_kernel`/`bind_template` for parsing, parameter
matching, numeric widening and type checking. Separate those technical functions
from role-semantic/provenance publication decisions. Do not fork the binder into
two contradictory type systems. Unknown technical signatures remain visible but
produce a local signature diagnostic for that call; no full-catalog gate.

Audit finding: current selected local context exposes104 operators but supplies
typed definitions for8 (ts_delta and7 VECTOR reductions). The107-row machine
ledger is not a count of executable signatures. Inspect existing raw technical
definitions for needed signatures before promising broad operator coverage;
never infer platform facts from an operator's name or fabricate a definition.

### Tree And Package

Each tree node uses compiled baseline/treatment expressions plus hypothesis and
predeclared routing. Two-arm pairing, cycle/reference checks, parent-measurement
reuse and deterministic reverse/fallback behavior remain because consumers need
them to execute correctly. Eliminate redundant feature_plan/baseline equality
bookkeeping by deriving receipts from the actual compiled arms.

New Starts opt into an explicit expression-tool contract marker. Existing frozen
runs retain readers and authority; never silently reinterpret an unknown run.
Package records the selected ASTs/expressions, settings, technical field/operator
contracts, assumptions, data characteristics, finite Repair edits/grids/triggers
and comparison/stop rules. Reuse current package boundaries and integrity seals.
Post-seal scientific execution must not reopen the global knowledge vault.

### Repair

Support finite AST wrapping, named literal-parameter edits and existing setting
grids. Every candidate reuses the same expression compiler and simulation identity.
For a wrapper, preserve the complete parent subtree; for a parameter edit, change
only the addressed permitted literal. No replacement fields, economic conditions
or late formulas. Operator choices and their rationale are research hypotheses,
not a requirement for official proof of expected financial improvement.

Data characteristics select or rank frozen recipes. Unknown frequency does not
block all smoothing: retain unknown explicitly and use the package's declared
finite session windows, without claiming they equal an observed update frequency.
Actual signature bounds still apply. Current default policy only enables decay
and truncation; the new path must explicitly freeze compatible operator recipes,
not assume the existing generic transform helper already makes them available.

Generate <= existing allowance, deduplicate, use existing bounded batch dispatch,
apply existing metrics/acceptance/rollback and stop on finite-space exhaustion.
Record "no improvement in this search space", not "economic hypothesis disproven".
Exhausted/budget-waiting work is not a code-maintenance failure.

### Evidence And Errors

Persist bounded tool operation, node/diagnostic codes, elapsed time, result status
and draft/checkpoint identities. Avoid full catalogs, repeated raw text, credentials
and model-private reasoning. Save latest complete draft/full-tree validation.
Preserve exception type and deadline separately from argv; terminate owned process
trees before classifying timeout. Unknown outcomes are never blindly replayed.
Budget limits are not enlarged. Final timeout policy must be proven by tests,
not changed by relabeling an unknown task as completed.

## Implementation Tasks

- [x] **1. Technical compiler separation.** Structural AST construction shares the existing technical binder; type/signature/window bounds retained. Nested/kwargs/arithmetic/vector/condition/unsafe/identity tests pass. No all-syntax promise.
- [x] **2. AI tool and tree adapter.** Compile/MCP/schema/design4 wired; unrestricted prose and unknown semantics accepted. Exact new-mode owner/resource opt-in required; legacy authority unchanged.
- [x] **3. Frozen package integration.** Existing package/receipts reused; sealed execution test forbids global vault reads. Tampering and identity checks retained.
- [x] **4. Deterministic Repair integration.** Frozen wrapper/literal/settings grids use shared compiler and existing receipts/comparison/batch runtime. Mocked tree->Seed->AST Repair->qualified candidate passes; unknown-POST dedup, direction, signed literals, finite exhaustion tested.
- [x] **5. Bounded diagnostics and lifecycle.**32-record/64KB diagnostic ring, latest draft/feedback and structured faults implemented. Existing owned cancellable transport reused; timeout never retries. Scoped feedback/transport/Stop tests pass.
- [x] **6. Packaged offline acceptance.**136 scoped regressions plus9 real EXE tests passed. Includes generic native checkpoint and MCP client, frozen compiler self-test and separate current-local-resource/source-owner check. Mocked complete driver verifies tree->Seed->AST Repair->candidate; this is not live-platform acceptance.
- [ ] **7. Delivery.** Update current toolchain/user/AI docs and root architecture/handoff, commit/push intended public files, verify remote equality, deploy and audit only approved disposable outputs. Do not remove sensitive or previously policy-rejected paths. Report implemented behavior, coverage limits and remaining gaps accurately.

## Acceptance And Scope

Planning and Repair must use one compiler contract. A multi-sentence, unreviewed
economic hypothesis with known technical fields/operators can become a valid
tree/package without semantic approval. Script Repair must actually produce legal
operator/parameter variants and consume mocked results, not merely serialize a
recipe. No Orchestrator rewrite, no new agent framework, no arbitrary generated
execution code, no late model decisions and no migration of the current unknown
failed model task. Run targeted tests and native acceptance, not routine full-suite
or repeated full-project review. Approved and source-implemented Nov26; release
acceptance and exact deployment evidence live in the root todo.md.

## Review Rulings

One fresh review identified four execution defects. All fixed with observed
RED->GREEN regressions: project window bounds plus frozen basis; owning resource
and Start opt-in; numeric parameter direction; signed scalar parameter paths.
136 affected tests pass (not full suite). Keep economic uncertainty advisory;
these technical execution constraints are not semantic admission.
