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
| Compose lanes | _execute_preplanned_start -> prepare_preplanned_start -> _local_resources/_repair_policy -> prepare_group_lanes | exact scoped resources, frozen period, finite Repair rules and paused lane identities |
| Call initial AI | prepare_initial_research -> create_initial_model_runner -> run_ai_checkpoint -> codex_ai_worker.run_worker -> codex exec | per-lane task/brief/checkpoint; read-only sandbox, medium reasoning, strict output schema |
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
