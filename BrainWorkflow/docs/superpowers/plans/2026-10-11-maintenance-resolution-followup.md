# Approved Maintenance Follow-Up

User confirmed continuation of remaining maintenance after event-only notification delivery was verified. Scope: offline repair lifecycle and truthful bounded429 recovery, not actual research or sandbox provisioning.

1. RED: receipt cannot resolve; approved repair cannot resume; failed/zero/stale verification stays blocked; verified repair preserves Pause and budgets; later fault gets a new case identity.
2. Implement maintenance-only approve/verify-and-resolve, fixed unittest command, before/after production+test source digest, sanitized child environment, durable receipt and shared run worker lock. No repair worker or deployment.
3. Share fresh case resolution reading across Console and driver; unknown/corrupt receipts remain blocked. CLI/POST cannot resume an approved-but-unverified case.
4. RED: existing driver must not reset429 evidence or authorize after runtime budget expires in cooldown. Implement source-locked 90-second evidence-bound bounded-retry lease, charge pre-existing max_recoveries budget; new429 invalidates the lease, never shorten server waiting.
5. Focused then full regression, architecture/docs checks, one independent medium reviewer. Preserve all existing dirty files; no commit/push/live WQB. Remaining legacy adoption and quota integration are separate follow-up work.

Rulings: notification acknowledgement never grants approval; approvals are maintenance records of direct human consent, not cryptographic authentication of arbitrary filesystem editors. Console operations do not expose an approve button. Verification locks the same driver runtime directory. No automatic resume/deployment is added. Original rate-limit counts and timestamps remain platform evidence, while bounded_retry is explicitly local policy authorization, not evidence of recovery.

Result: steps1-5 verified offline. Fresh full suite1094 passed/129.020s; architecture/entry22 passed, compileall and diff check passed. Independent medium review findings reproduced and fixed, final narrow reopening review found no concrete safety regression. Legacy adoption remains blocked by saved budget10 versus20 recorded submissions; no platform execution, Console deployment or authority expansion performed. Current handoff is root todo.md.
