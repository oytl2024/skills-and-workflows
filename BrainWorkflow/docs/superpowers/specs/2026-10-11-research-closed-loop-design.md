# Orchestrator research closed loop

Status: architecture confirmed by user on 2026-10-11. Closed-loop implementation and offline acceptance present; final deployment verification is recorded in root todo.md, separately from live research authority/quality.

## Ownership

Orchestrator owns research rounds and transitions. Source recovery finishes a source batch, not a research mission. One selected option permits hypothesis/data/template changes within that objective and explicitly persisted resource limits. Do not reinterpret legacy original-only recovery authority as new research permission.

## Transitions

Start -> knowledge readiness -> option selection -> schedule -> Scout30 -> multisimulation -> complete evidence -> triage.

- Incomplete evidence: reconcile actual check/benchmark evidence; never classify missing evidence as weak signal.
- Deferred SELF/PROD correlation checks with finite measured Sharpe/fitness/returns/turnover and actual failed checks permit research-only assessment. Preserve pending checks and hard_pass=false; never qualify a candidate. Missing metrics, unknown pending checks or only-pending otherwise-passing records still require reconciliation.
- The same research-only deferral applies to known DATA_DIVERSITY/REGULAR_SUBMISSION flags. Fetch Alpha detail first; only passing baseline checks permit the expensive submission-check endpoint. This ordering reduces unnecessary correlation requests without weakening candidate admission.
- Weak signals: persist observations, select a different knowledge-backed hypothesis/data/template, then Scout30.
- Promising signal: Seed fixes the kernel; Discovery30 constructs justified variants; triage chooses Repair or renewed exploration.
- If the bounded kernel has fewer than30 novel variants after Scout deduplication, record Discovery exhaustion without a POST and proceed to measured-seed Repair. Missing knowledge/operator provenance remains a blocker, never exhaustion or a passing result.
- Repair: bounded small batches, improvement comparisons and finite attempts; failure returns to another seed or Scout.
- Qualified signal: authoritative checks including correlations -> eligible candidate queue -> separate final submission authorization.
- Budget exhausted, user Pause, unknown submission outcome or protected decision: explicit durable stop, not successful research completion.

Thirty is candidate count for Scout/Discovery; request chunk size is independent. Seed/Repair remain small. No infinite quota, synthetic checks, duplicate submissions or automatic final Alpha submission.

## Durable contracts

Persist round identity, parent round/source linkage, selected hypothesis and provenance, candidate hashes, evidence/classification version, budget use, next transition and stop reason. Preserve earlier evidence. Resume reconciles in-flight work before new submission. Completed original-only recovery returns to the controller without silently widening its scope.

AI judgments for hypotheses/templates/near misses must be persisted, validated and consumed explicitly; deterministic code owns safety and transitions. Daily evidence capture is automatic; knowledge compile remains a separate maintenance loop unless readiness requires it.

Legacy Repair settings may be recovered through a bounded authenticated GET of the exact Alpha, with matching platform id and expression, then cached as provenance. Never infer original settings from current defaults; never rewrite raw checked rows to claim missing checks passed.

Console retains objective selection, Start, Pause/Resume and protected final approval. No routine per-round gate clicks. Unrecoverable code blockers use the existing event-driven maintenance channel.

## Acceptance

Exercise weak round -> new30 -> promising round -> bounded Repair -> passing checks; Repair exhausted -> alternate exploration; missing evidence -> reconciliation; quota exhaustion; Pause during cooldown; restart during multisim; duplicate callbacks; original-only migration; Console next-action consistency. Offline fixtures prove control flow, not live alpha quality.
