# Knowledge Resource Admission

Status: functional boundary and implementation approved Nov6; new-entry activation explicitly reconfirmed Nov8.

## Goal And Non-Goals

Knowledge ingestion makes a resource available to research planning. Economic
semantics, explanatory completeness, timing/grain interpretation and semantic
publication status must not be an admission whitelist. Unknown facts remain
unknown; exploratory assumptions are not certified facts.

This changes resource admission, not the Orchestrator, experiment-tree standard,
AST language, Seed gates, deterministic Repair search or submission authority.
The proposed Nov5 general Delay1 derivation is no longer a prerequisite.

## Independent Modules And Change Map

| Concern / owner | Input -> output | Dependency and this change |
| --- | --- | --- |
| Knowledge storage / existing raw, ledger, SQLite | Captured sources -> indexed resource records | Storage/schema unchanged; never create a second knowledge authority. |
| Resource admission / research_resource_catalog, preplanned_start | Local catalog + scope -> bounded AI resource view | Changed: semantic publication/completeness is not a whitelist. |
| Initial AI planning / initial_research_planning, initial_model_worker | Resource view + history -> structured hypotheses/tree | Input context changes; existing output Schema and one-shot model boundary remain. |
| Technical compilation / hypothesis_template_compiler, template_binding | Structured feature/roles -> typed AST expression pairs | Split economic evidence checks from unchanged grammar, arity, known types and supported feature DSL. |
| Frozen context / exploration_eligibility | Resource/plan -> immutable receipts and owning context | Carry explicit new admission policy; old contexts retain original behavior. |
| Readiness / run_readiness | Frozen resources + current facts -> permission to execute | Published semantic library is optional for validated catalog runs; selected identity/source/age and authority remain independent. |
| Transport / existing client, simulator, batch/recovery adapters | Frozen identities -> measured results | No change to POST, polling, cooldown, Stop or duplicate reconciliation. |
| Measured window adapter / measurement_window, existing result normalization | Actual Alpha IS metadata + its PNL -> identity-bound observed period | Nov8 deployment closure: supply missing end evidence, never copy planned dates or change comparison standards. |
| Routing and Seed / experiment_tree, research_tree, seed_policy | Measurements + frozen predicates -> branches/retained cores | No change to tree standard, comparison, rollback, scoring or hard gates. |
| Repair / repair_search, repair_rulebook | Traits + failed metrics + rules -> finite experiments | Mappings/grids/triggers unchanged; remove repeated semantic certification, retain technical compatibility. |
| Orchestration / existing group driver, Orchestrator | Durable authority/state -> legal execution | No core state-machine, quota or submission change. |
| Console / existing native application | Durable projections -> user view and Start/Stop | No layout/interaction redesign; rebuild only after integrated acceptance. |

Path: knowledge -> admission -> AI plan -> compiler/freeze -> transport ->
routing/Seed -> Repair -> candidate evidence. Readiness and authority constrain
execution; they are not substitutes for resource confidence or experiment quality.

## Current Coupling Detail

`preplanned_start._local_resources` reads published semantic operators and prior
compiler contexts. `_validate_resource` requires source-backed descriptive,
timing/grain and operator-definition evidence before AI sees resources.
`template_binding` repeats field metadata/timing and operator-basis checks.
`repair_search` also checks transformation sources. Merely widening the prompt
would therefore fail later in compilation.

Existing code already provides AST parsing, argument/type checks, strict AI
output Schema, experiment-tree graph/routing validation and finite Repair rules.
Retain these mechanisms rather than replacing them with model judgment.

## Resource View

Read the canonical local field/operator catalogs, including resources absent
from the published semantic release. Reuse existing readers, scope selection,
SQLite field lookup where appropriate, and optional semantic enrichment.
Do not create another ledger, source authority or model framework.

Expose all ingested candidates to local selection; the bounded per-lane view
is still selected inside the requested scope and original limits. Batching is
not permanent exclusion of the remainder of the catalog.

Each selected resource carries identity/type, actual description if present,
technical signature if available, provenance and explicit unknowns/warnings.
Optional semantic notes and history enrich the model brief; absence must not
prevent it. Keep capture dates unchanged. Preserve the existing 90-day age
policy and identity/scope consistency; this change does not renew sources or
grant online capture. Unreadable material cannot be invented into a resource.

## Compilation Boundary

Separate technical executable rules from proof of economic interpretation:

- Keep the supported AST subset, valid identifiers, field binding, known
  parameter/arity/type rules and explicit VECTOR-to-MATRIX reduction.
- Do not require reviewed semantics, a timing derivation receipt or known
  vector economic grain merely to explore a selected catalog resource.
- Reuse actual technical definitions from catalog/documentation and existing
  contracts; economic explanations are not prerequisites for using them.
- A missing technical signature is not permission to fabricate one or silently
  treat VECTOR as MATRIX. Keep that resource visible, report the particular
  unsupported call/combination, and do not invalidate the entire catalog.
- This is not an extension of the supported feature DSL or a promise that every
  operator combination is implemented. Local unsupported-expression diagnostics
  remain distinct from semantic-completeness warnings.
- Validate the existing hypothesis/tree Schema, direction/configuration,
  executable branch predicates, parent comparison and rollback constraints.

Invalid generated plans still fail existing output validation; bounded planning
and error routing stay in force. Missing semantics alone must never produce a
maintenance blocker. No new runtime model replanning loop is introduced.

## Repair And Frozen Context

After offline acceptance, activate the preplanned entry for NEW Console research
in the existing local configuration. Keep existing saved requests and missions
on their frozen mode. Do not start research during deployment, increase any
model/simulation/runtime/recovery budget, or change Stop. Entry configuration is
an explicit deployment step, not an implicit behavior change while reading old
requests. Research/Alpha submission retain their separate authority.

Keep metric triggers, trait-to-action mappings, parameter grids, one-factor
changes, accept/rollback/stop and budgets unchanged. Known technical operator
contracts remain enforced. Lack of semantic publication must not disable an
otherwise supported transformation. An unknown trait does not trigger a rule
that explicitly requires that trait. Record unavailable actions and an exhausted
finite search normally; do not request semantic certification as a routine gate.

Use an explicit versioned admission-policy marker in new frozen resource
contexts. Absence of that marker retains old validation and frozen authority.
Do not silently rewrite snapshots, historical receipts, resource identities,
model jobs, source dates, quotas or Stop. No old retired AI Repair mission resumes.

## Acceptance

Offline tests must show an ingested field/operator omitted from semantic release
can reach the AI brief and compile with valid technical rules despite unknown
economic metadata. Invalid syntax, wrong known types, malformed trees and
unauthorized actions must still fail. Repair uses the same valid rule choices
and grids; unknown traits do not activate extra actions. Old frozen contexts
retain original behavior. Local intake/compile performs zero platform or model
calls. Report catalog visibility separately from technical combination support.

Finish with independent medium-or-lower review, complete offline regression,
source digest, verified Git sync, rebuilt native package and loaded-version
verification. Research execution and final Alpha submission are not authorized
by this maintenance acceptance.
