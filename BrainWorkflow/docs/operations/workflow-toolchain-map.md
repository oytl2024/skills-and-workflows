# Workflow Toolchain Map

This is the implemented new preplanned desktop path, not permission to execute it.
Older frozen runs retain their original contracts. An installed app opening or an
accepted HTTP command does not prove research or a model call has started.

## Independent Owners

| Concern | Owner | Input -> output |
| --- | --- | --- |
| Interaction and command identity | React ApplicationClient, console_api | selection + displayed revision -> durable command receipt |
| Start and Stop authority | console_start | command -> original request, cancellation or prepared group |
| Local field availability | multiplier_preparation | exact scope + source evidence -> reusable field proof |
| Network containment | multiplier_supervision | original request + finite bounds -> isolated raw capture |
| Scientific publication | data_ledger_compile, semantic compilation | raw -> indexed/compiled resources; no research authority |
| Planning and technical validation | initial_research_planning, template compiler | sourced brief -> checked full experiment tree |
| Execution and routing | group driver, workflow driver, tree runtime | frozen plan + measured results -> selected experiments |
| Seed and Repair | seed_policy, repair_search | results + frozen rules -> retained cores and finite search |
| Checks, evidence and retirement | checker, research_record, execution lifecycle | complete evidence -> qualified records and terminal summary |
| Maintenance delivery | notification modules | durable fault -> deduplicated delivery receipt; never repair permission |

Resource admission, syntax/type checking, scientific plan standards, execution,
Repair and authority are separate contracts. Improving a resource scan must not
weaken Stop, exact scope, source dates, accounting or submission authorization.

## Research Path

### Expression Tool Mode

New Starts use explicit `expression_tool_version=1`; old frozen runs are not
reinterpreted. AI reads knowledge, proposes unrestricted economic prose and
structural `design_version=4` baseline/treatment ASTs. The budgeted `compile`
operation calls `expression_tools.compile_expression` ->
`template_binding.bind_technical_template`; the same binder checks types, arity
and supported grammar without semantic approval. `validate` checks the full tree.
`expression_planning.compile_design` adapts those receipts to the existing
exploration/compiler/package interfaces. Scripts derive field identities and
facts; AI assumptions remain assumptions. No mandatory reviewed-template family.

After sealing, `expression_repair` policy3 uses frozen wrapper templates, literal
paths and finite setting grids. `repair_search` retains the existing persistent
receipts, comparison, rollback, dedup and batch execution. New fields and late
model formulas are not Repair. Invalid recipes return planning diagnostics.
Syntax is nested named calls/kwargs, literals, unary +/- and binary +,-,*,/;
not complete BRAIN language. Unknown signatures produce per-call diagnostics,
not a global resource gate. Audited current context:104 visible operators,8 typed;
the107 identity ledger rows are not executable signature coverage.

Task-local diagnostics retain32 bounded records (<=64KB), hashes/counters and
short diagnostics, not raw arguments/catalogs. Latest failed draft and feedback
are overwritten in place. Cancellable worker transport owns children; timeout
records exception/deadline and preserves unknown outcome, never retries blindly.

| Step | Concrete tool/function | Persistent boundary / external activity |
| --- | --- | --- |
| Open desktop | BrainWorkflow.vbs/cmd -> desktop_application.main -> launch_application -> ensure_backend | local EXE/WebView2/backend only |
| Read live view | GET /api/application/snapshot; console_api.project_application; event stream/polling | projection of existing state, not stage execution |
| Select and Start | App.tsx -> ApplicationClient.command -> POST /api/application/commands -> console_api.submit_command | command_id, expected_revision and selected_scope; duplicates cannot launch twice |
| Dispatch | console_server._run_application_command -> application_start_form -> run_console_action | exact selected scope; internal worker process, not a second user CLI |
| Register | console_start.register_start -> console_jobs.start_job_async -> packaged_worker_command/dispatch_worker -> console_start.execute_start | console_start/request.json and console_jobs/<job>/job.json |
| Prepare Multiplier | _prepare_multiplier_start -> prepare_multiplier_fields_supervised -> supervise_command -> OwnedExecutionTree | owned child admits only the original finite preparation |
| Reuse or capture | multiplier_preparation.prepare_multiplier_fields -> _prepare -> _ready/_raw_evidence; capture_platform_data_fields when needed | authenticate; OPTIONS /simulations; GET operators/datasets/fields only when acquisition is needed; never POST simulations here |
| Publish locally | parent publish_scope_catalog, _write_index, compile_data_ledger_from_raw | immutable raw sources -> machine/index/ledger; child never publishes shared scientific files |
| Compose new retrieval lanes | _execute_preplanned_start -> prepare_preplanned_start -> prepare_retrieval_design | marker retrieval_design_version=1; bind scope, generation, original Start and one model task per lane |
| Query and design | run_ai_checkpoint -> codex_ai_worker -> codex exec -> scripts/research_query.py or packaged retrieval worker -> task-local research_tool_service -> research_queries/research_query_index | indexed compact fields/operators/templates/history/source; local validation, no WQB; owner persists quotas/progress |
| Resolve selection | read_selected_catalog_resources -> _resolve_answer -> _repair_policy -> prepare_group_lanes | verify exact selected fields/cited sources/history and closing generation; script resolves traits/finite Repair rules |
| Reuse validated answer | prepare_initial_research with bound answer callback | original coordinator/schema, not a second AI invocation; old unmarked Start keeps its original runner |
| Compile and freeze | _compiled_graph -> hypothesis_template_compiler; freeze_initial_research_snapshot, freeze_tree, seal_execution_context | hypotheses/traits -> deterministic expressions, complete tree and script-owned execution package |
| Start lane drivers | initialize_group_runtime -> start_group_workers -> supervise_group_lane/run_group_lane -> run_workflow_driver | N lanes share accounting and keep independent durable progress |
| Execute Scout | workflow_auto_continue -> tree_runtime.continue_tree -> advance_tree/execute_tree_round -> source_batch_runner -> cli.run_field_batch | only frozen selected experiments; local dedup, reservations and durable POST identity |
| Simulate and poll | simulator.submit_multisimulation or submit_simulation -> WQBClient.request -> poll_simulation/resolve_multisimulation_alpha_ids | POST /simulations; bounded progress GETs; children count against simulation attempts |
| Check results | checker.fetch_check_summary -> classify_check_response; candidate_evidence cache | alpha detail/basic checks first; /alphas/<id>/check only when eligible; valid cache reuse |
| Select Seed | workflow_stage_adapters.advance_post_schedule_stage -> seed_policy.select_seeds | hard gates then score/rank; passing Seed is not final submission eligibility |
| Finite Repair | RepairRuntimeExecutor.prepare -> prepare_persisted_search -> prepare_search; executor __call__ -> same simulation/check tools -> compare_versions | data traits + failure metrics -> approved single-factor candidates; accept/revert/exhaust; no late AI planning |
| Record and retire | record_alpha_result/record_repair_attempts, sync_research_record_to_machine/raw; terminal_retirement_proof -> retire_execution_package | preserve learning, check and submission identities; retire only genuine completed work |

Final Alpha submission is a separately approved operation, never an automatic
consequence of Start, passing checks, candidate caching or retirement.

## AI And Maintenance Are Different Paths

The initial research worker runs `codex exec --sandbox read-only` with
`model_reasoning_effort=medium`, an output schema and an owning run directory.
Its answer is saved and validated. It is not a message delivered to the maintenance
chat. Scout branching and deterministic Repair do not call AI at every step.

Retrieval marker1 uses one logical design task per lane, with bounded local tools
inside that task. Defaults:64 total tool calls,24 draft validations,1,048,576 total
response bytes; each response is at most64,000 bytes. Existing local configuration
keys `retrieval_max_queries`, `retrieval_max_validations` and
`retrieval_max_returned_bytes` override positive limits before identity freezing.
The task owner, not the read-only worker, owns counters/progress. Transport is a
task-local authenticated JSON pipe (loopback on non-Windows), not a platform call
or separate service framework. Counters record rows/source/response bytes and tool
elapsed time, never infer token use. Stop invalidates subsequent queries. Unknown
model outcomes do not replay. Selected historical groups keep original scope and
inconclusive labels; transfer evidence never proves target-scope causality.

Explicit VECTOR reductions require a current sourced technical declaration, then
lower before Level/Change/Relative; missing reduction is rejected, not silently
converted to vec_avg. GROUP is context-only. Final plan selection resolves exactly
the fields used; generation changes block before sealing. Runtime uses sealed
resources only. Current installed/source acceptance remains in root todo.md.

For a blocked Start, `_complete_start_job` or `_notify_blocked_request` persists
preflight evidence, then `notify_preflight_blocker` reads maintenance_channel.json,
resolves the executable through codex_locator (explicit absolute executable,
PATH, then bounded Windows registered-package discovery) and invokes
`codex queue --thread <configured-id> --resume --message <evidence-reference>`.
Run-stage faults use maintenance_notifications.dispatch_notification instead.
Resume requests chat attention, not repair authority. Queued is not acknowledged,
reviewed or repaired. Failed/uncertain delivery is
retained, not blindly resent. Code repair still requires human confirmation.

## Knowledge Maintenance Is Separately Requested

1. After research, compile_research_records consolidates persisted research
   evidence; semantic/wiki compilation derives reusable findings rather than
   turning associations into proven economic causes.
2. Explicit platform refresh uses scripts/capture_learn_material.py and/or
   capture_platform_data_fields. Compile captured sources using the owning
   data/semantic compilers before a new research task uses them.
3. prepare_full_semantic_compile/run_full_semantic_compile implement bounded
   semantic interpretation work and publication. This is not automatic model
   polling during research.
4. Versioned manual Multiplier field acquisition is the narrow Start exception,
   not permission for general platform crawling, activity discovery or rule edits.

## Diagnostic Boundaries

- Large-catalog read loops must not repeatedly rediscover every old run as a
  per-row cancellation operation. Fast Stop checks and phase-level full authority
  validation need separate costs and tests at realistic catalog scale.
- Worker termination must finalize both the outer job and nested preparation
  status. An outer timeout with nested status=pending is misleading.
- Notification executable resolution must work in a normal desktop environment,
  not only the parent Codex terminal. Record distinct configuration, resolver,
  process-start and delivery errors without exposing secrets.

The implementation bounds repeated intent/permit reads to 250ms, forces complete
authority checks at phase/handoff boundaries and projects terminal outer failures
into preparation status. Capture publication registers original payload hashes and
dates, not just the human summary. These changes preserve independent validation
policies. Current acceptance/deployment status belongs to root todo.md; source
changes or targeted tests alone never prove a running app has the fix.

Catalog visibility is not feature-DSL support: VECTOR/GROUP remain visible, while
the current structured feature compiler needs a MATRIX starting field per lane.
Insufficient distinct starting fields must be reported, not silently converted,
duplicated or worked around by reducing the requested parallelism.
