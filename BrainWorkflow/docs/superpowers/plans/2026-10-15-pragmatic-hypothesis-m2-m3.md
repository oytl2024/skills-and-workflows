# Pragmatic Hypothesis M1 Closure And M2/M3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Track task steps with checkboxes; root todo.md is the sole interruption ledger.

**Goal:** Finish usable M1 resources, integrate paired Scout and mechanism feedback, and reconcile manual submission without weakening execution safety.

**Architecture:** Extend existing evidence/compiler/snapshot/planner/record boundaries. Add only one focused pure mechanism-evidence helper and its tests; no new framework, state machine, service or authoritative success ledger.

**Tech Stack:** Existing Python3.12, unittest, standard library, AST, immutable releases, existing locks/model worker/Console. No new dependency.

**Spec:** docs/superpowers/specs/2026-10-15-pragmatic-hypothesis-m2-m3-design.md. Spec and plan approved2026-10-15; sequential implementer/reviewer method preserved, all reasoning medium or lower. Root todo.md owns current progress.

## Global Constraints

- Preserve dirty checkout and unrelated changes/deletions; no automatic Git commits, push, worktree relocation or deployment. Skill commit steps are replaced by durable root handoffs.
- No Orchestrator core-state, simulation identity, POST recovery, quota, Stop/Pause, cheap-before-SELF/PROD or final-submit changes. No actual simulation/research resume/proof renewal.
- Offline tests remove process credentials and use temporary roots. Existing actual-source acceptance allowance has9/12 knowledge GETs used and0/4 distinct model jobs; do not reset those counters. Do not retry unchanged terminal model keys. Platform status reconciliation needs separate read-only authorization, not this plan's approval.
- Keep source capture dates and unknowns. Project-owned horizon constraints are never labelled official platform restrictions. Default5/22/122/252, not a whitelist or an automatic Scout grid.
- New runtime capability is default-off and frozen for new runs; old runs and v1/default paths retain their own readers/contracts.
- Every subagent/reviewer has explicit reasoning_effort medium or lower. Execution follows the previously selected sequential implementer/reviewer method unless the user changes it.
- New functions document input/output/type; constants below imports. Shared defaults use existing config/worker input and immutable snapshot, not new environment variables or shell-only product controls. Update scripts/demo-hypothesis-design.sh for optional developer overrides if shared CLI defaults change; routine use remains Console.

## Review Focus

1. Project INTEGER emission policy must not erase a contrary official parameter restriction or silently upgrade rule1/old failed jobs (Task1).
2. Fresh mixed-block pages/duplicate receipt facts/changed original sources must not grant semantics merely because HTTP succeeded (Task2).
3. Manual submission must not manufacture candidate approval, turn pending checks into passes or count repeated reports as new usage (Task3).
4. Partially deduplicated/shared baselines, odd quotas and stop/restart must not create unfunded half-pairs or new POST identities (Tasks4/5).
5. Repeated record snapshots, missing periods and incomparable controls must not inflate replication counts or produce causal claims in AI context (Tasks6/7).

## Interfaces And File Boundaries

- Existing resource_evidence.py remains the shared pure resolver. Introduce PROJECT_WINDOW_POLICY and a separately identified ts_delta_project_window@2 derived rule; retain ts_delta@1. Resolver receipts distinguish source facts and project parameter_policy. No model-written trust flag.
- Existing hypothesis_design.py exposes DEFAULT_HORIZONS=(5,22,122,252) and normalize_horizon_defaults(values:list[int]|tuple[int,...])->tuple[int,...]. Existing MAX_HORIZON remains the bound. No new fields on SemanticPolicy that would break its integer-only serialization.
- Existing hypothesis_selection.py exposes validate_operational_resource_context(snapshot:dict)->dict and select_experiment_batch(snapshot:dict, experiments:list[dict], maximum:int, available_measurements:dict|None=None)->dict.
- Existing research_planning.py exposes prepare_paired_hypothesis_plan(run:Path, config:dict, metadata:dict, now:str)->dict; existing prepare_source_plan dispatches only from the frozen mode. Output remains a consumed generator-config patch plus an experiment-sidecar reference.
- Existing create_start_snapshot(knowledge_root, selected_option_id, selected_scope, *, research_policy:dict|None=None) preserves its first three arguments. Optional paired_scout defaultsFalse and is validated/frozen at Start. No activation by the mere presence of v2 metadata.
- New wqb/mechanism_evidence.py exposes build_mechanism_evidence(records:list[dict], experiments:list[dict])->dict and select_mechanism_context(view:dict, query:dict, maximum:int=12)->dict. Inputs are caller-verified records; these pure functions perform no filesystem/platform/model calls. Returned view carries schema_version, input_digest, groups, exclusions; context carries input_digest, items, omitted_count.
- Existing research_record.py exposes reconcile_manual_submission(knowledge_root:Path, run_dir:Path, report_path:Path, reported_at:str)->dict. It consumes the indexed report and identity-matched local evidence; no network or invented approval. Returns status/alpha_id/identity/provenance/projection_paths/diagnostics, with unknown submission time left null.
- New derived artifact: machine/mechanism_evidence.json, replaceable and reproducible from research records/sidecars, never a second authority. Existing knowledge_paths.py registers its one canonical path if required. Tests: one new tests/test_mechanism_evidence.py; all other tests extend existing modules.

## Task1: Project-Owned Horizon Contract

**Modify:** resource_evidence.py, semantic_contracts.py only if receipt serialization requires it, hypothesis_design.py, semantic_compilation.py, codex_ai_worker.py; existing tests/test_resource_evidence.py, test_hypothesis_design.py, test_hypothesis_design_acceptance.py, test_codex_ai_worker.py.

**Produces:** normalized defaults and a ts_delta_project_window@2 receipt with parameter_policy owner=project, positive integer subset, existing maximum bound; source-backed identity/syntax/meaning/types remain mandatory. Keep the basis wire shape where possible; choose the rule by explicit rule_id/version, never by missing integer documentation.

- [x] Write RED tests: defaults equal(5,22,122,252); justified17 accepted; bool/0/negative/over-bound rejected. New rule accepts sourced ordinary lookback without an integer-domain quote, but rejects contrary positive/even/default constraints it cannot satisfy. Legacy ts_delta@1 still requires its old premise. Mutation of project policy changes semantic/design keys; unchanged terminal keys do not replay.
- [x] Run `python -m unittest tests.test_resource_evidence tests.test_hypothesis_design_acceptance -q`; expected new cases FAIL for missing policy/rule support.
- [x] Implement minimal explicit rule branch and receipt provenance; bind full policy/schema to cache identities and worker context. One selected horizon per hypothesis, no automatic four-way expansion.
- [x] Rerun those suites plus `tests.test_hypothesis_design tests.test_codex_ai_worker`; expected PASS. Review before Task2; record changed files and exact proofs in root todo.

Task1 Ruling2026-10-16: independent review reproduced resolver-supported project rules rejected by the compiler, and invalid project horizons accepted by direct binding/coverage. Extend Task1 narrowly to hypothesis_template_compiler.py/template_binding.py and their existing tests so explicit rule/version acceptance and verified project bounds are enforced at both entry points. Preserve legacy nonnegative-zero behavior; this is not a new global restriction. Root todo owns fix/review progress.

Task1 Windows recovery ruling: real concurrent first preparation reproduced4/15 failures because resolving a missing machine/source_index.jsonl transiently returned an extended filesystem namespace while the root used ordinary form. Normalize only equivalent Windows drive/UNC filesystem namespaces in knowledge_contracts.py containment comparison; retain lexical, resolved-escape, device-namespace, reparse and hardlink rejection and zero-write verification. Deterministic RED/GREEN and existing concurrency/security regressions must pass; no retry or ignored exception may hide this defect.

## Task2: Fresh Page Interpretation And Actual M1 Acceptance

Accepted2026-10-16: all steps below completed with R4 and prompt/read-root reviews; frozen2043PASS2skips178.908s,digest2afd54a38acede332f944bb16078bfc43b28fee611c38ca94a68bcefc4c4c09b,compileall/diff/24entryPASS. Actualjob0102eb6c44dbd026dcd1dfccffedeb3b02e46ca3b58449d155d8947c946b1f7d generated two distinct sourced/unreviewed/scout_only drafts and one experiment; cache replay HIT with unchanged checkpoint events. Polarity uses separately indexed explicit user hypothesis, never official facts.3/4modeljobs9/12GET used; old two failures retained. No publication/research/measurement/submission authority.

**Modify:** resource_evidence.py, semantic_compilation.py, hypothesis_template_compiler.py, template_binding.py only at existing contracts; tests/test_resource_evidence.py, test_hypothesis_design_demo.py, test_hypothesis_design_acceptance.py. Capture code changes only if a new losslessness bug is reproduced.

**Consumes:** Task1 policy; complete indexed page/card receipts and original-bound field extracts. **Produces:** supported or explicitly unsupported sourced definitions, actual unreviewed baseline/Change pair and immutable compilation attachments.

- [x] Add RED fixtures for actual ts_delta/settings/FastD1/vector/group page shapes: heading/text/table/media and full raw JSON/GET receipts. Assert exact identity, complete bytes, duplicate/conflicting facts, unknown blocks, changed receipt/original and expired source behavior. Do not make an entire page's hash the only admissible meaning rule.
- [x] Run `python -m unittest tests.test_resource_evidence tests.test_hypothesis_design_demo -q`; expected new page evidence cases FAIL before implementation.
- [x] Extend the one shared finite adapter/resolver. Source signature and operation meaning may come from different compatible official sources; no synthetic operator card. Accept documented equivalents only through scoped, audited finite rules, not model self-certification.
- [x] For GROUP, add structural-context support only if official applicability and exact-scope original rows establish it. Otherwise retain Relative unsupported, with a test proving no named-field timing generalization. Do not block Level/Change acceptance on optional Relative.
- [x] Run resource/demo/acceptance/publication suites; expected PASS before actual model use.
- [x] Verify the five already retained actual sources through current guards. If facts support the subset, use existing prepare/compile design interfaces and at most remaining authorized distinct jobs to generate the actual economic proposal/pair; preserve unreviewed/scout_only. Save source/rule/binding digests and coverage in existing output/semantic_jobs. No manual fake model answers, automatic review/publication or research.
- [x] Freeze and run full suite/digest, compileall, entry checks, diff check; collect independent review. Expected actual nonduplicate pair plus engineering PASS. If protected allowance/configuration or facts block acceptance, record the exact decision and continue only independent safe work, not Task4 runtime activation.

## Task3: Manual Submission Reconciliation

Accepted2026-10-16: all steps below completed; implementation165+10tests, independent review127tests then R1scope4tests+race probesPASS; same frozen2043 fullproof. Actuale76lZY3N ingest reconciled and exactrepeat preserved four projection bytes,oneevent,submitted_at=null,fieldsubmitted_usage_count=1,submitted_alpha_ids=[e76lZY3N]. Original run_state/run_manifest/runtimecontrol bytes unchanged. No queue existed or was fabricated; no platform query. Global SELF revision is local eligibility invalidation, not a success ledger.

Task2 actual-worker ruling2026-10-16: the first real job returned schema-shaped but semantically invalid multi-sentence/role/feature declarations. Preserve its terminal receipt and count1/4; do not edit its answer or retry its key. Extend the existing hypothesis_design/codex_ai_worker/semantic_compilation prompt boundary with a concise shared DESIGN_WORKER_CONTRACT bound into content identity. Explicitly communicate single-sentence, sourced trigger, allowed roles/metadata and baseline equality requirements already enforced by the validator. RED/GREEN and independent review precede a genuinely changed-key attempt; no validation relaxation or framework addition.

**Modify:** research_record.py, candidate_queue.py only if a compatible queue row exists, data_ledger_compile.py/data_ledger.py for idempotent usage projection, existing knowledge command entry; tests/test_research_record.py, test_candidate_queue.py, test_data_ledger_compile.py.

**Consumes:** indexed raw user report for e76lZY3N, exact local Alpha/expression/settings identity. **Produces:** reconcile_manual_submission result, preserved raw lifecycle evidence and existing record/usage projections. No new approval row or queued candidate is created.

Task3 safety ruling: a new submitted Alpha changes the account's SELF comparison set. Extend this task narrowly to candidate_evidence.py and its existing tests: conservatively invalidate prior SELF eligibility through the existing local invalidation mechanism, retain raw evidence and reject older in-flight saves. If a shared local revision is needed for previously absent entries, keep it under the existing candidate-evidence boundary, not a new success ledger. Repeated report ingestion must not repeatedly invalidate; no platform recheck follows from invalidation.

- [x] Write RED tests: same report twice does not append a second lifecycle event or increase usage; two distinct Alphas using one field count twice; unknown/ambiguous local identity does not change usage; pending/failed checks survive; actual submitted_at remains unknown. Existing matching queue may become manually_submitted under its immutable identity, absent queue is not fabricated.
- [x] Run `python -m unittest tests.test_research_record tests.test_candidate_queue tests.test_data_ledger_compile -q`; expected new reconciliation cases FAIL.
- [x] Implement one durable reconciliation path using existing record/source registration/locks. Derive distinct submission identities for projections; preserve legacy counts explicitly where no reconstructable identity exists rather than resetting or blindly adding totals. Failed partial projection is resumable/idempotent and visible.
- [x] Rerun suites; expected PASS. Ingest the already indexed actual report through this path after offline acceptance, not by editing several ledgers. No API status request without separate authorization; no SELF/PROD or POST. Record whether usage was matched or left unresolved.

## Task4: New-Run Frozen Operational Context

Accepted2026-10-16 loader/snapshot scope: independent49tests+13offlineprobesPASS;parent73targeted/entryPASS;implementer218StartStop/runtimePASS and full2053tests2skips192.308s frozen maintenance digest3d43b51bab2cc93ff9e77b9c5ee4fbbb5965cecc9d0dd136659335ac595934e0;sevenfiledigest439c1ac44442269805e96b617b2db90ef7beb106581e3895fc5b8c4b6d149e05. Orchestrator.start only forwards optional research_policy before mission creation; no state-machine change. Existing experiment_paths/source_refs suffice, no newreleaseformat. Missing official attachment producer is a mandatory Task7integration gap, not overall delivery acceptance.

**Modify:** workflow_stage_adapters.py, hypothesis_selection.py, research_planning.py, console_start.py/config producer as needed, configs/workflow_defaults.example.json; tests/test_hypothesis_pipeline.py, test_hypothesis_selection.py, test_console_start.py if present or existing Console start suite.

**Consumes:** reviewed paired release/experiment attachments and verified M1 context. **Produces:** explicit paired_scout=False default; when enabled, frozen resource_contract_version, source bytes/digests, policy and exact experiment references. Legacy snapshots remain unchanged.

- [x] Add RED tests for default-off equivalence, strict bool flag, unreviewed resources, mismatched release/context versions, source mutation and tampered sidecars. Enabling paired mode without adequate reviewed resources returns a specific readiness rejection before mission creation.
- [x] Run `python -m unittest tests.test_hypothesis_pipeline tests.test_hypothesis_selection -q`; expected new operational-context cases FAIL.
- [x] Implement validate_operational_resource_context and explicit frozen-policy producer. Do not remove require_legacy_resource_snapshot globally; route only new explicitly enabled snapshots to the new validator. No active-vault rereads in a running mission.
- [x] Rerun these suites plus existing Start/Stop tests; expected PASS, including old run replay. Review context version propagation before Task5.

## Task5: Pair-Aware Scout Through Existing Executors

**Modify:** hypothesis_selection.py, research_planning.py, generator.py, cli.py only for sidecar propagation, workflow_stage_adapters.py and existing console_timeline.py projection; tests/test_hypothesis_selection.py, test_research_planning.py, test_hypothesis_pipeline.py, test_generator.py, test_console_timeline.py.

**Consumes:** Task4 frozen paired snapshot. **Produces:** select_experiment_batch and prepare_paired_hypothesis_plan; existing candidate identities unchanged; persisted experiment/arm/baseline sidecars alongside plans.

- [x] Add RED tests: controls identical except declared feature;30 unique candidates maximum, remaining1 produces no unfunded pair, remaining3 permits one two-arm experiment; shared compatible measured baseline charges only missing arm; identical arms/duplicate collision excluded; incompatible prior measurement is not reused. Correlation cache is not a substitute for compatible simulation measurements.
- [x] Run `python -m unittest tests.test_hypothesis_selection tests.test_research_planning -q`; expected new pair tests FAIL.
- [x] Build feasible groups and deduplicate before cap; do not call _hypothesis_pool's window/decay/neutralization product in paired Scout. Persist the complete plan and sidecars before existing executor handoff. Restart reuses exact inputs. Discovery/Repair remain their current optimization paths.
- [x] Project per-arm queued/submitted/polling/measured/failed state into existing timeline, no new layout or manual stage buttons. Partial results are not labelled a completed comparison.
- [x] Run named suites plus existing runtime integration/research-loop/Stop/429/uncertain-POST regression suites. Expected PASS; fake transport proves no extra POST on replay and no calls after durable Stop. No actual WQB test.
- [x] Offline performance assertion: for a fixed fixture, paired path expands only bound experiment arms, not horizon*decay*neutralization products; report generated/selected counts and mock request counts, not unverified live speed claims.

Acceptance2026-10-20: recovered interrupted implementation;18module434testsPASS72.504s. Independent review found two timeline P2s; unknown POST now uncertain and current-source sidecar hash restricts projections so historical comparisons never become queued under a different source. Timeline10testsPASS1.202s and independent8probesPASS. No live performance claim; official publication/config bridges remain Task7.

## Task6: Reproducible Mechanism Evidence

**Create:** wqb/mechanism_evidence.py, tests/test_mechanism_evidence.py. **Modify:** research_record.py, knowledge_compile.py, knowledge_paths.py, knowledge_experience_compile.py and related existing tests at the maintenance compile boundary only.

**Consumes:** exact-identity research records and Task5 sidecars. **Produces:** pure evidence view and reproducible machine/mechanism_evidence.json; no online calls or research-start full compile.

- [x] Add RED tests: input reordering yields identical view/digest; repeated run snapshots/duplicate arm references count unique simulations once; distinct scopes/versions/settings/periods remain separated; missing period/control cannot become replication; conflicting metrics/check evidence stays inconclusive.
- [x] Add labels tests: compatible measured prediction supports/contradicts only in scope; missing control inconclusive;429/timeout operational_failure; manual submission alone never establishes supports_prediction_in_scope. Labels use explicit existing benchmark/prediction controls, not invented universal Sharpe cutoffs.
- [x] Run `python -m unittest tests.test_mechanism_evidence -q`; expected FAIL before new helper.
- [x] Implement build_mechanism_evidence and select_mechanism_context. Selection includes relevant failures/insufficient cases with deterministic ordering and explicit omitted_count. Accept integer maximum from0 through12;0 returns no items with the eligible count omitted. Negative, over12 and boolean bounds reject.
- [x] Wire the derived view to knowledge maintenance after record ingestion, write atomically under existing maintenance controls and preserve original records. Extend existing human wiki/cases with concise conditions/mechanism/comparison/results/limits; do not create new catalog pages.
- [x] Run new/helper plus record/knowledge/experience suites; expected PASS including failed-write replay and removal/rebuild of derived view without loss of raw evidence.

Acceptance2026-10-20: implementer103scopedPASS; independent review exposed malformed/contradictory/empty checks and reused-control status/identity conflicts. Parent observed RED counterexamples, fixed evidence retention and validation, then63focusedPASS3.149s; independent scopedPASS. Actual compiler experiments have no numerical comparison: they remain inconclusive with observed differences; synthetic explicit comparisons do not grant publication or measured causal claims.

## Task7: Feedback, Integrated Acceptance And Handoff

Integration ruling2026-10-16: Task4review found only fixtures produce its experiment wrapper. Extend Task7 minimally at existing semantic_compilation/knowledge_compile/semantic_publication review/export boundaries to export verified M1 compiler inputs, version contract and experiment into the exact consumed wrapper, bind experiment_paths and immutable source_refs, and exercise normal review/publication with tempfixtures. Also trace Console/config->frozen policy forwarding; if missing, wire through existing producers/defaults without new UI gates or implicit activation. No actual publication authorization is inferred. Final end-to-end tests must use these official producers, not manually fabricate the missing bridge. This closes the approved user-visible pipeline rather than creating a new framework.

**Modify:** semantic_compilation.py, hypothesis_design.py and knowledge_compile.py for exact review export and bounded design feedback; existing config.py, console_start.py, console_server.py, cli.py, start_preflight.py, run_readiness.py and workflow_stage_adapters.py for the approved config-to-snapshot bridge. knowledge_paths.py/delivery_gate.py distinguish optional derived JSON from mandatory primary ledgers. tests/test_hypothesis_design_acceptance.py, test_codex_ai_worker.py, test_economic_hypothesis_acceptance.py and corresponding config/Console/readiness/planning/delivery tests; existing manual, source diagnosis, root milestone/todo. Shared worker contract propagation reuses codex_ai_worker.py unchanged.

**Consumes:** Task6 bounded context and Task1 policy. **Produces:** hypothesis-design packs with evidence digest, relevant attempts and limitations; no formulas generated outside the structured schema.

- [x] Add RED tests: relevant failed/inconclusive histories reach the worker, unrelated full ledger does not; changed selected evidence changes job key; unrelated omitted history does not change already frozen jobs; worker cannot edit factual records or promote hypothesis/candidate lifecycle; empty history preserves supported legacy inputs.
- [x] Run `python -m unittest tests.test_hypothesis_design_acceptance tests.test_codex_ai_worker -q`; expected new feedback assertions FAIL.
- [x] Implement bounded pack injection using complete hashed supporting local records when needed; do not raise pack byte caps, truncate a source then hash as complete, or read credentials/config outside workspace. Prompt says observations are not causal proof and repeating an exhausted idea needs an explicit new experiment.
- [x] Run offline chain: sourced hypothesis -> drafts -> separately reviewed fixture release -> new paired snapshot -> fake batch/Stop/restart/partial-arm result -> record -> mechanism view -> next structured hypothesis context. Also assert old-run byte-stable replay and unchanged submission authority.
- [x] Freeze all relevant source, filter credentials and run `python -m unittest discover -s tests -q`, `python -m compileall -q wqb tests scripts`, `python -m unittest tests.test_project_architecture tests.test_project_entry_docs -q`, `git diff --check`; before/after source digest must match. Inspect actual results, not only command exit code aggregation.
- [x] Collect fresh final review, fix actionable findings RED/GREEN and rerun affected/full tests. Update manual with activation/readiness/arm-status/evidence semantics and actual coverage; record every protected/external blocker. No live acceptance claim or old-run proof renewal.

Acceptance2026-10-20: official producer/review/export, immutable release, configured Console Start with real Readiness, paired fake executor Stop/restart/partial result, verified record, maintenance view and next structured job are covered offline. Semantic310tests2skipsPASS; Start202+164regressionsPASS and independent57tests/25probesPASS. Final review found baseline evidence projection loss; RED repro fixed with full measurement retention/conflict exclusion. Firstfull2098 failed7 derived-resource delivery checks; optional derived absence and strict JSON parsing fixed RED->GREEN,88focusedPASS. Independent final/scoped review PASS including official reused-baseline record/view probe. FINAL frozen full2100tests0failures2skips236.680s; source_before=source_after=0fe27cf7eaba5f1c0dc7081a3600c3a6a9426b4bdf148fc1afd791b13af2c237; compileallPASS. Actual M1 pair still unreviewed; actual operators require review, GROUP unsupported, numeric comparison absent=>inconclusive+deltas. No real model/WQB/capture/publication/deployment/research/submission/Git or old-run proof renewal.

## Preflight And Execution Handoff

Tasks1->2 policy/source rule receipts agree;2->4 requires separately reviewed resources and frozen context, not merely compiled drafts;4->5 preserves identity and budget;5->6 joins via sidecars;6->7 bounds source retrieval and job identity. Task3 is independent of paired execution but feeds lifecycle/usage evidence without promoting quality. GROUP remains optional and cannot block the supported Level/Change branch merely by being absent.

Self-review: all spec sections map to Tasks1-7; five Review Focus classes have explicit tests. Read actual signatures before each edit, record minimal rulings if a caller contract differs, never silently broaden authority. Root todo carries current task and last proof; milestone changes only at implemented interface acceptance. No secondary SDD progress ledger.

Please review this plan before execution. Preserve the previously chosen sequential implementer plus independent reviewer method, all reasoning medium or lower. Approval starts Task1, not live research; stages continue under the plan without repeated permission requests for authorized offline tests/reviews. Stop only for a genuine protected decision or external blocker and continue independent safe work where possible.
