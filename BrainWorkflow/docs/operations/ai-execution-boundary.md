# AI execution boundary

Opening the desktop app does not create a Codex task or call a GPT model. The started Console driver selects the read-only Codex adapter. Generation, validation, simulation and platform checks remain Python-controlled, but validated structured model decisions now select bounded Scout/Discovery decay and new Repair edits. A pending checkpoint is not evidence of model execution.

`wqb/ai_checkpoints.py` provides the first durable worker contract. A caller supplies an explicit executable argv with `{input}` and `{output}` placeholders. The worker receives a JSON checkpoint input and must write JSON output with a nonempty `summary`. Every attempt stores input, output location, and running/completed/failed status in the decisions directory. No default model, credential, or shell command is selected, and an empty argv leaves the checkpoint pending. The worker does not submit Alpha or change research rules.

The run-local adapter lives in `wqb/codex_ai_worker.py`: it passes bounded evidence excerpts to `codex exec` with `--sandbox read-only`, `model_reasoning_effort=medium`, a JSON output schema, and a 600-second inner timeout. The enclosing checkpoint worker persists attempt input/output/status and has a 900-second outer timeout. It does not run WQB API calls, change workflow files, or submit an Alpha. When the Codex executable is unavailable, the checkpoint fails visibly while the deterministic workflow remains independently auditable. Direct CLI workflow runs without `--ai-executor codex` leave checkpoints pending; the Console workflow-run path configures it explicitly.

Research-option reasoning, near-miss summaries, candidate-risk review and reflection remain advisory. research_batch_plan and repair_decision are distinct structured decisions: only validated evidence-bound output can change the corresponding payload. repair_planning.py binds measured parent/history and local knowledge context to the model judgment; repair_runtime.py verifies and marks consumption. Validated/consumed does not mean checked or qualified.

Repair initially permits one settings/direction edit at a time (decay, neutralization, truncation or flip). No arbitrary expression, new field, unknown operator signature, research-rule change, budget change or final Alpha submission is accepted. Missing local PnL/semantic evidence is explicit. Frozen legacy in-flight plans recover without claiming AI authorship. Independent parents may advance while another simulation waits, within the existing reservation and platform policy.

Driver-owned workers are cancellable on Stop and bounded by the remaining absolute runtime deadline, including the pre-POST gate. Pending baseline checks recover the saved AlphaID with paced bounded attempts; no simulation resubmission. Resource and long-wait notices are durable event-driven messages, not repair/renewal permission. Rule-change proposals and wiki compilation remain separate maintenance work. Live model/platform quality is not established by offline fixtures.
# Repair context and maintenance feedback (2026-10-13)

Repair model input uses exact field identifiers, bounded semantic previews and
immutable manifest/original-row digests. Long administrative ledgers are not model
context; omitted/shortened material is explicitly marked. The9000character cap
still fails closed for genuinely oversized critical evidence. No additional model
or simulation budget is implied by compaction.

An unrecoverable planning error is reported immediately as maintenance-blocker,
not retried until generic no-progress. Current Work reports case ID, notification
delivery and whether human repair confirmation or verification is pending. A
delivered notification is not repair authority; runtime renewal cannot waive it.
