# Maintenance Confirmation Handoff

Approved bounded downgrade, 2026-10-11: code/contract blockers request human confirmation in the existing maintenance chat. No automatic code patching/deployment; no sandbox dependency for notifications. Scripted external recovery and unknown-submission reconciliation remain separate.

1. Recovery cases become `awaiting_maintenance_confirmation`, with a sanitized durable notification. Same fault keeps one case and one notification across restarts. Pause takes precedence.
2. `wqb.maintenance_notifications` supplies list/claim/acknowledge with the existing case OS lock and atomic publication. Claim before notifying; ambiguous delivery is not retried automatically. CLI cannot grant repair authority.
3. User correction: NO heartbeat or AI polling. Automation `brainworkflow` was deleted. Driver blocked-exit calls an event-triggered script using installed `codex queue --thread ... --message ...`, bound through local `runs/maintenance_channel.json`. Fifteen-second transport timeout, no `exec` worker, no sandbox bypass. Successful queue acceptance is not processing/user approval; a later maintenance receipt is separate. Claimed/uncertain outcomes never automatically retransmit.
4. Console shows queue/delivery state in existing progress region. No new routine control. Documentation and architecture distinguish notification from repair approval.
5. RED/GREEN tests: routing, pause, external/unknown exclusions, restart deduplication, concurrent claim, acknowledgement ordering, CLI, Console rendering. Full tests and architecture checks before delivery.

Notification does not prove a code defect: maintenance first diagnoses and proposes a scoped repair, then waits for the user's confirmation. Sending or acknowledging a request never resumes the workflow, changes budgets/permissions, or submits an Alpha.

Transport limitation: event enqueue depends on the local Codex queue/daemon supporting the target thread. A real synthetic transport-only probe was accepted for the configured maintenance thread; it did not create a research defect or authorize repair. No receipt means Console must not say read/notified. After approved repair, maintenance separately verifies the fix and notifies the operations chat; it must preserve an explicit user Pause. Repair resolution/deployment is not automated by this notification module.
