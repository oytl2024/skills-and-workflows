# Retrieval-Led Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Checkboxes are the durable task ledger alongside root todo.md.

**Goal:** Implement the approved retrieval-led design task and explicit VECTOR
compilation, then verify and run three new trees in ALL/D1/LARGE.

**Architecture:** Keep current compiler/package/runtime owners. Add a rebuildable
catalog offset index and bounded local query adapter, then one source-bound
preparation design task per lane. Its selected resources and answer flow through
the existing initial coordinator with no second model call. No Agent framework.

**Tech Stack:** Python312, sqlite3, existing JSON contracts/AST/compiler/Codex
read-only worker; existing React/WebView2/PyInstaller application.

**Spec:** ../specs/2026-11-23-retrieval-led-research-design.md

## Execution Record

Preserved predecessor handoff (formerly root todo):
Nov23 synced71ffe58,README retained,digest1b0a4d9e.3412tests/9skip/1148.034s PASS:
output/desktop-validation/console-delivery-verified-full-suite-20261123-preparation.{json,log};
27frontend/tsc/build PASS. Build20261123-140037-6347/native140145-2732 PASS,
revision199adf7c,EXE0e320217; installedNov10. Approved product %SystemDrive%4db/989184B
deletion policy-REJECTED; no deletion/receipt,never bypass. Saved65fields compiled16.625s,
_ready0.125s;N2 has1MATRIX. Goodall medium reviewed. No live resume/budget/proofrenewal/submit.
Diagnosis:runs/start_preflight/79805fb3be8742d2ba25b6d1ee98019e-diagnosis-20261123.md.

Nov24: Task1-4 implemented; focused aggregate193PASS before lifecycle additions.
Schema2 query index also binds optional supporting publications, uses one active
replaceable SQL slot. Selected historical groups freeze original bytes run-locally.
Review fixes RED->GREEN: independent references retained; verified extracts support
Repair; final compile rechecks generation; malformed tool envelopes cannot kill
the owner. A standard-library task-local authenticated JSON pipe serializes tools
and owns cumulative budgets/progress because read-only model clients cannot write
counters. This is an implementation detail of the bounded adapter, not a new
service framework. Defaults64queries/24validations/1MiB are frozen in task identity
and exposed in the brief; configuration overrides are positive integers.

Task5: Console progress integrated;30 frontend tests/typecheck/build PASS. Build
20261124-152931-7083 passed native fixture GUI/backend/assets and real windowed
field-query/validation JSON round-trip (including PowerShell Out-String). Later
source fixes require a fresh build. No app installed or live/model task started.

Task6 in progress: strict postseal lifecycle RED->GREEN; source/summary benchmark
consumers now use explicit verified sealed owner rules. Repeated-Start uncertainty
guard RED->GREEN survives Stop without a fresh timestamp/model task. VECTOR
occurrence-specific setting-only Repair RED->GREEN; legacy/transform restrictions
unchanged.57 lifecycle/Start/benchmark/Console tests and12 uncertainty/Repair tests
PASS. Qualified candidate and weak/Stop/restart paths covered with fictional raw
HTTP, not mocked hard-pass summaries. Full-suite/Git/deploy and Task7 pending.

Release freeze: staged43 intended source/test/docs files reviewed and whitespace
check passed. Full offline proof running under stem
`output/desktop-validation/retrieval-full-suite-20261124-reviewed`; code/test
digest9ae21790b105ca9936613be242a578a231d37d7843c78d9f31b7f4ed18eb0298.
Fresh build20261124-154123-9668 passed native query+PowerShell validation and GUI
smoke20261124-154256-23120; source revision32a5f56996f7dad37ee0ea6ca308b618c01c5ef4100ff39326493b2cfbd90c1f,
EXEf15861b8169f225c367737d66aeb708209e017c096978b49cf38b681a8424628.
No installation/real research until full proof and Git equality. Read-only install
audit366->371 files,5code additions plus JS replacement; no private resources.

Full offline acceptance PASS:3524 tests/10 skips/1222.058s, returncode0,
before/after digest unchanged9ae21790...; log/receipt use the stem above.
Native query acceptance is separate and passed (the optional native test is
skipped in the portable full suite). Actual ALL/D1/LARGE source probe:
64VECTOR/1MATRIX fields,8typed operators (ts_delta+7reducers), legal sourced
vec_avg(field) and ts_delta(vec_avg(field),22);6finite default Repair rules.
This is technical support, not proof of economic performance or full104operator
typed coverage. Evidence:output/desktop-validation/retrieval-resources-20261124.json.

Deployment Nov24:implementation2d71d561 synchronized to intended branch without
force. Audited installer verified all371 files and old-run authority/state hashes,
replaced only named old JS and wrote matching installation receipt. Actual loaded
health revision32a5f569 matches source/build. Private newStart configuration now
retrieval1, codex executor, N2/depth2/width4 and live-enabled for the explicitly
authorized trial. No old mission resumed; existing retired history remains.

## Global Constraints

- Workspace branch agent/brainworkflow-phase2; retain unrelated files and user README.
- Work in existing authorized maintenance checkout; do not create another workspace
  or move global knowledge/runs. The user requires canonical root entry docs and no
  unrelated directories. Agents use disjoint file sets and reasoning medium.
- New-start feature marker only; old frozen formats/execution unchanged.
- No implicit VECTOR conversion or semantic-confidence admission whitelist.
- No network/model calls in tests. Live3 trees only after offline and deployment
  acceptance; scope ALL/D1/LARGE, N2/depth2. No old-run resume or final Alpha POST.
- Source raw/date/scope/type identity, Stop/accounting/dedup/unknown POST and final
  check evidence remain independent. Unknown empirical properties are not facts.
- Git sync before audited cleanup; prior rejected cache deletion is not retried.

## Review Focus

1. Model searches outside an initial shortlist and actually consumes historical
   contradictions, rather than merely exposing an unused query function.
2. Changed ledger/source generations or duplicate identities cannot substitute
   resources between query, final compilation and package sealing.
3. Query/validation subprocesses work in the packaged EXE and never authenticate,
   mutate scientific resources or produce simulated evidence.
4. Interrupted/uncertain model outcomes, Stop and repeated Start cannot replay or
   create a replacement mission; selected design lineage survives callbacks.
5. VECTOR reductions preserve declared economic meaning and old contract behavior;
   query visibility never implies unsupported operators will compile.

## Task 1: Rebuildable Field Query Index

Files: new wqb/research_query_index.py, tests/test_research_query_index.py.
Interfaces:
- prepare_query_index(root: Path) -> dict: generation, hashes and index path.
- query_fields(root: Path, generation: str, scope: dict, query: str = '',
  field_type: str | None = None, offset: int = 0, limit: int = 20) -> dict.
- read_field_rows(root: Path, generation: str, scope: dict,
  identities: list[tuple[str,str]]) -> list[dict].
Store identity/scope/type/search tokens and original JSONL byte offsets/hashes,
not a second ledger/raw copy. Use existing machine/field_catalogs boundary,
SQLite transactions/atomic publication and a generation bound to actual inputs.

- [x] RED exact scope/pagination/duplicate/stale generation/corrupt cache tests.
- [x] Implement index and compact responses, bounded selected-row source reads.
- [x] Verify warm queries do not reopen/parse the full ledger. Rebuild is explicit
      local preparation, never a side effect of read-only queries.
- [x] Run python -m unittest tests.test_research_query_index -q; review before integration.

## Task 2: Sourced VECTOR Features

Files: hypothesis_design.py, hypothesis_template_compiler.py, resource_evidence.py;
new focused tests/test_vector_feature_design.py and affected existing compiler tests.
Introduce a versioned structured reduction choice, supported by the newly captured
official vector guide/operator pages. Preserve v1/v2 frozen schemas and receipts.
Allow explicit aggregation before Level/Change/Relative/condition operands using
existing template_binding input-slot reductions, not guessed formula text.

- [x] RED explicit vec_avg/vec_sum/vec_count composition and missing reduction.
- [x] Add versioned schema, semantic normalization, deterministic lowering and
      sourced technical declarations; preserve full-source/evidence binding.
- [x] Reject unsupported reductions and wrong GROUP/MATRIX/VECTOR combinations.
- [x] Preserve sum versus mean and reject contradictory source-only examples as
      technical premises. Unknown NaN/order facts stay unknown.
- [x] Run focused design/compiler/binding regressions; review changed interfaces.

## Task 3: Local Research Query Adapter

Files: new wqb/research_queries.py, tests/test_research_queries.py;
modify research_resource_catalog.py to resolve exact selected identities.
Use Task1's generation, query_fields/read_field_rows. Expose fields, operators,
templates, experience, source, and validate operations through bounded JSON.
Reuse semantic/mechanism-evidence readers and existing compiler/Repair rules;
no alternative knowledge authority. Source queries return scoped excerpts and
identity refs. Final resolution verifies all selected original evidence.

- [x] RED material outside old30 shortlist, exact-source lookup, history success/
      failure/inconclusive retrieval and empty findings explicitly labeled.
- [x] Implement compact bounded responses and source-backed field/operator cards.
- [x] Add side-effect-free draft validation yielding located diagnostics. No
      publish/seal/simulate/credentials path may be reachable from query commands.
- [x] Run tests and trace full-scan counts; Task1 warm queries remain indexed.

## Task 4: Single Source-Bound Design Task

Files: new wqb/retrieval_research_planning.py, tests/test_retrieval_research_planning.py;
modify codex_ai_worker.py, ai_checkpoints.py only at versioned new dispatch.
Planning evidence lives in the existing start_preflight boundary before mission
creation. Brief contains objective/scope/catalog generation/tool contract/schema,
not the whole vault. One bounded Codex checkpoint per lane may query and validate
locally and returns exact selected field identities plus full tree/characteristics.

- [x] RED fake worker searches outside shortlist, inspects negative history,
      corrects a draft locally and emits a valid final answer in one model task.
- [x] Bind task identity, source generation, output schema, Start request and Stop.
      Preserve unknown model outcomes; no blind model retries.
- [x] Implement source-bound projection/query entry, strict returned selection,
      tree/design validation and checkpoint lineage. Treat raw content as data.
- [x] Limit retrieval calls/bytes and validation attempts via explicit existing
      configuration, show exhaustion distinctly from unsupported syntax.

## Task 5: Start And Desktop Integration

Files: preplanned_start.py, console_start.py, initial_research_planning.py,
initial_model_worker.py, group_preparation.py as strictly needed;
worker dispatch registry and tests/test_retrieval_start.py.

- [x] New-start flag retrieval_design_version=1 routes to Task4 before field
      selection; assemble selected resources with Task3.
- [x] Feed authenticated answer to current coordinator without a second model
      invocation; bind original planning task/result digest in lineage.
- [x] Preserve N lane settings, measurement period and finite Repair rules.
      Distinct selected identities/ideas are not manufactured by padding.
- [x] Packaged executable provides the same read-only query/validate interface;
      no reliance on a separately installed Python or unrestricted sandbox.
- [x] Expose design/query/validation progress through existing snapshot/timeline,
      no routine extra buttons or misleading gate-advance actions.
- [x] RED/green repeated Start, Stop during retrieval, unknown checkpoint outcome,
      stale catalog, immutable run and no implicit Alpha submission tests.

## Task 6: End-To-End Acceptance And Deployment

- [x] Offline tree success/failure/rollback, Seed, deterministic Repair, cached
      checks, qualified candidate and terminal retirement fixtures all pass.
- [x] Record stage-skipping honestly when a tree has no eligible Seed.
- [x] Fresh whole-branch medium review; resolve actionable findings.
- [x] Stage/review intended source/docs, diff --check, freeze code/tests and run
      full offline unittest suite; frontend tests/typecheck/build and native smoke.
- [x] Update root architecture/handoff, operator docs and feature defaults for new
      research. Verify Git sync before audited application installation/cleanup.
- [x] Verify actual loaded revision, preserved Stop/accounting and next legal Start.

## Task 7: Authorized Three-Tree Operational Trial

- [ ] Create new research only in ALL/D1/LARGE after Task6, not an old-run resume.
- [ ] Run two lanes then one additional tree through the ordinary product path;
      one group cannot silently consume an unbounded replacement-tree budget.
- [ ] Use existing shared daily4000, runtime/recovery/POST/polling limits, bounded
      multisimulation and basic checks before SELF/PROD. No limit renewals inferred.
- [ ] Persist expressions/settings/IDs/metrics/branch decisions/Repair trajectories
      and legitimate weak/unsupported/exhausted outcomes. No invented success.
- [ ] Qualified Alphas stay unsubmitted pending separate concrete-ID authorization.
      Report trials reached versus skipped stages; never promise three trees suffice.
- [ ] Only afterward discuss which recorded findings to compile into reusable
      knowledge. Existing necessary evidence recording is never disabled.
