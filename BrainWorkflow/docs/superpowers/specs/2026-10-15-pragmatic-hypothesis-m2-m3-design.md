# Pragmatic Hypothesis Contracts And M2/M3

Status: design and phased implementation plan approved2026-10-15; implementation in progress. Root todo.md carries acceptance evidence and remaining gates. Approval does not authorize live research.

## Intent

Finish source-backed M1 without confusing conservative project choices with platform facts. Then integrate economic baseline/treatment exploration (M2) and reusable mechanism evidence (M3). Reuse the existing workflow, knowledge vault, model worker, compiler, frozen plans, runtime executor and review boundaries. No new agent framework, UI gate or Orchestrator state machine.

This extends the approved structured-template design of 2026-10-14 and revises the integer-window requirement of the 2026-10-15 source-backed design. The revision is explicit; it does not invalidate or rewrite old frozen jobs and runs.

## Confirmed Parameter Policy

- Initial trading-day horizons: week5, month22, half-year122, year252. These are user research conventions, not exact calendar equivalences or platform-imposed values.
- These values are defaults, not a whitelist. Preserve existing positive-integer and maximum-horizon compiler guards. Reject booleans, nonfinite values and unsupported argument shapes.
- A hypothesis selects one justified initial horizon. Do not automatically expand all four horizons into a Scout grid. Discovery/Repair may propose bounded alternatives with recorded rationale under their existing authority.
- An explicitly documented operator restriction overrides project defaults. An unknown or contradictory restriction is reported; it is not silently erased.
- Do not require an official statement proving the complete integer parameter domain before using an ordinary positive-integer lookback in a documented time-series operator. Mark the integer-only emission constraint as project-owned, not source-derived platform typing.

## M1 Closure

### Operator Evidence

Keep official identity, syntax, argument positions, operation meaning and input/output applicability source-backed. Separate platform facts from the local compiler's accepted argument subset in definition receipts. The new policy applies initially to ts_delta, not to every scalar parameter of every operator. Existing explicit typed definitions remain valid.

Preserve source-backed bounds/defaults and reject conflicts. A model cannot create trusted facts or change the global policy. Policy changes enter rule/job identities, including the full receipt grammar; old failed keys remain terminal and old definitions are never silently reinterpreted.

### Official Documentation Pages

The actual operator-detail endpoint returns id/title/content pages, while the operator list returns name/definition/description cards. Consume both through finite validated adapters without inventing card fields from a page name. Preserve complete page JSON and GET receipt, exact identity, timestamps, source/body/full hashes and applicable section context. Unknown blocks or contradictory facts remain explicit unsupported evidence.

The source-backed resolver remains shared by compile, audit and binding. No second parser with weaker trust rules. A source excerpt or metadata repair must pass original-receipt/completion checks before model, cache and publication access.

### GROUP Context

Do not apply a numeric predictor's named-field cutoff rule to industry/sector by name alone. A grouping role needs documented GROUP applicability, original exact-scope identity and evidence of platform-managed grouping use. A distinct structural-context contract may represent those facts without inventing a numeric signal release timestamp or historical PIT proof. It must not accept arbitrary economic GROUP-valued signals as structural classification.

If the available sources cannot establish the structural-context contract, keep Relative unsupported and complete actual M1 acceptance with Level/Change instead. Relative is not a prerequisite for M2; its missing facts remain visible.

### Actual Acceptance

Use a bounded verified real field/operator subset to generate one structured economic hypothesis and two distinct baseline/treatment drafts through the actual compiler/binder. Keep drafts unreviewed/scout_only; do not promote them to runtime authority automatically. Cite sources and distinguish hypotheses from observations. No backtest is needed for compiler acceptance.

Use the remaining explicitly authorized capture/model allowance only when needed; do not infer new allowance from this design. Missing model execution configuration or exhausted allowance is a protected decision, not permission to invent model output.

## M2: Paired Scout

### Frozen Inputs

Activate only for new runs through a default-off setting frozen at Start. Read reviewed resources and experiment attachments through one validated immutable release/snapshot. Carry the resource version, source context and rule receipts explicitly; legacy runs retain their original readers and plans.

### Planning

Choose economically distinct experiments from the knowledge library. Compare feature construction first, not the Cartesian product of window/decay/neutralization. Both arms share field bindings, scope and non-treatment settings; the declared feature is the only intended change.

Compile and deduplicate before applying the maximum30 and original remaining budget. Persist experiment_id, arm_id and baseline linkage in sidecars, not in existing simulation identity keys. Count unique simulations, not duplicate arm references. Reuse a shared baseline only when its exact existing identity and measurement are compatible.

Never label a half-pair as a completed comparison. If available authority cannot fund both missing arms, choose another feasible complete pair or record insufficient evidence. Do not increase budget or refund uncertain POSTs.

### Execution And UI

Use existing batch submission/multisimulation, polling, cooldown, Stop/Pause, recovery and cheap-before-correlation check order. No direct platform calls from the planner or evidence compiler. Persisted arm events project into existing Console progress; no new manual Next/gate buttons.

Discovery and Repair retain parameter optimization and existing seed/repair contracts. The stage framework remains unchanged. Zero candidates, partial failures and operational blockers use existing durable recovery and notification routes.

## M3: Mechanism Evidence

Build a deterministic derived view from existing identity-verified research records and M2 sidecars. Preserve mechanism/template/version, field/data roles, scope, period when known, arm/settings identities, metrics, unique attempts and source fingerprints. Do not pool incompatible scopes or settings as replications.

Labels: supports_prediction_in_scope, contradicts_prediction_in_scope, inconclusive, operational_failure. Missing measurements/controls, pending or contradictory checks remain inconclusive;429/timeouts are operational failures, not economic falsification. Submission is a lifecycle event, not proof of causality or validation of every historical check.

Feed a bounded relevant selection of positive, negative and insufficient evidence into the next hypothesis-design job. Include attempted directions to avoid repetition. Do not load the entire vault or rerun source compilation at research startup. Changed evidence changes the job identity; unchanged terminal jobs do not replay.

Reuse raw/machine/wiki: original records in raw, digest-bound derived evidence in machine, concise reusable findings/cases in existing wiki pages. No parallel success database or historical directory tree. Human lessons explain mechanism, conditions, comparison, observation and failure boundary, not a private model reasoning trace.

## Manual Submission Reconciliation

Record e76lZY3N as user-reported manually submitted, with report time separate from unknown actual submission time. Associate existing local expression/settings/field lineage only when identity matches. Preserve previous failed/pending checks as historical evidence.

Optionally reconcile through one separately authorized read-only Alpha status request. Do not POST, recheck SELF/PROD, fabricate prior approval or create a queued candidate merely to record submission. Update existing submission/usage projections idempotently; repeated ingestion must not double count. If a durable compatible ingestion path is missing, add a bounded tested path instead of manually editing several ledgers.

## Implementation Ownership

| Responsibility | Existing modules to extend |
| --- | --- |
| Window/source distinction and finite page evidence | resource_evidence.py, semantic_contracts.py, semantic_compilation.py |
| Structured design and deterministic drafts | hypothesis_design.py, hypothesis_template_compiler.py, template_binding.py |
| Frozen pair selection/plans | hypothesis_selection.py, research_planning.py, existing snapshot producer |
| Execution/progress | existing generator, stage adapters, Console projection; no core state-machine rewrite |
| Derived history and bounded retrieval | existing research-record, knowledge compilation and design-pack paths; one focused pure helper only if needed |
| Submission lifecycle/usage | candidate_queue.py and existing usage projections; no fabricated check evidence |

Exact APIs/file boundaries belong in the implementation plan after this spec is approved. Reuse existing configuration for shared defaults; expose them clearly rather than scatter magic values.

## Acceptance And Safety

- M1: default and alternative positive horizons, explicit restriction conflicts, source versus project provenance, page/card receipt tampering, source/cache changes, actual nonduplicate pair, no automatic publication.
- M2: default-off legacy equivalence, new frozen context, paired controls/dedup, shared baseline, odd budget, restart, Stop,429, unknown POST and no extra submission.
- M3: deterministic summaries, unique attempts, incompatible scopes, missing/contradictory evidence, technical failures, bounded retrieval and no causal promotion.
- Submission: repeated user report is idempotent, unknown submission time stays unknown, check conflicts survive, no approval fabrication or API POST.
- Each stage: RED/GREEN, independent review at medium or below, full offline suite with frozen source digest, entry/architecture checks, updated manual and root todo handoff.

No live research, simulations, final Alpha submission, quota expansion, old-run proof renewal, Git commit/push or automatic deployment follows from implementation approval. Routine product interaction remains Option Card and Start/Stop; genuine unresolved semantic decisions are consolidated for maintenance, not turned into internal gate clicking.
