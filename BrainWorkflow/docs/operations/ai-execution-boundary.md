# AI execution boundary

Opening the desktop app does not create a Codex task or call a GPT model. Initial preplanned research uses a bounded read-only model task per lane to propose hypotheses, roles and a finite experiment tree. Subsequent tree decisions and Repair are deterministic and consume frozen rules. A pending checkpoint is not evidence of model execution. See root todo.md for actual deployment/readiness, not just implemented capabilities.

`wqb/ai_checkpoints.py` provides the first durable worker contract. A caller supplies an explicit executable argv with `{input}` and `{output}` placeholders. The worker receives a JSON checkpoint input and must write JSON output with a nonempty `summary`. Every attempt stores input, output location, and running/completed/failed status in the decisions directory. No default model, credential, or shell command is selected, and an empty argv leaves the checkpoint pending. The worker does not submit Alpha or change research rules.

The run-local adapter lives in `wqb/codex_ai_worker.py`: it passes bounded evidence excerpts to `codex exec` with `--sandbox read-only`, `model_reasoning_effort=medium`, a JSON output schema, and a 600-second inner timeout. The enclosing checkpoint worker persists attempt input/output/status and has a 900-second outer timeout. It does not run WQB API calls, change workflow files, or submit an Alpha. When the Codex executable is unavailable, the checkpoint fails visibly while the deterministic workflow remains independently auditable. Direct CLI workflow runs without `--ai-executor codex` leave checkpoints pending; the Console workflow-run path configures it explicitly.

Initial research and independent knowledge compilation retain their separate schemas and authority. Legacy repair_decision and near_miss_interpretation checkpoints reject before subprocess dispatch. Historical answers remain readable but cannot authorize a new experiment. repair_policy.py verifies only deterministic receipts; validated/consumed does not mean checked or qualified.

Repair consumes certified finite settings/transform rules, preserves the accepted economic kernel and tests one permitted edit at a time. Missing sources, arbitrary operators/new fields and changed authority fail closed. The user approved retiring old AI Repair missions on Nov 3: they remain read-only evidence and are not automatically migrated. Independent eligible parents may advance within the existing reservations and platform policy.

Driver-owned workers are cancellable on Stop and bounded by the remaining absolute runtime deadline, including the pre-POST gate. Pending baseline checks recover the saved AlphaID with paced bounded attempts; no simulation resubmission. Resource and long-wait notices are durable event-driven messages, not repair/renewal permission. Rule-change proposals and wiki compilation remain separate maintenance work. Live model/platform quality is not established by offline fixtures.
# Deterministic Repair and maintenance feedback

Repair does not build a model prompt. Exact field identifiers, source digests,
parent identity, measured history and frozen search rules bind its receipts.
No model or simulation allowance is created by retiring the old adapter.

An unrecoverable planning error is reported immediately as maintenance-blocker,
not retried until generic no-progress. Current Work reports case ID, notification
delivery and whether human repair confirmation or verification is pending. A
delivered notification is not repair authority; runtime renewal cannot waive it.
