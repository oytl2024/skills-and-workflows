# Repository Agent Rules

## BrainWorkflow File Placement

- Do not create unrelated files/directories while maintaining BrainWorkflow. Reuse existing code, tests, scripts, docs, knowledge and runs boundaries; no parallel framework or knowledge authority.
- Tests use isolated temporary directories with cleanup, not workspace-root mock/profile directories. Keep generated verification artifacts in the existing output/runs boundary and apply the same isolation to subprocesses.
- Permanent cleanup must distinguish shared repository projects, credentials/configuration and referenced research evidence from disposable artifacts. Do not infer permission to delete sensitive files or shared projects from a generic cleanup request; confirm the exact scope first.

## Knowledge Age Policy

- User-approved knowledge manifest default is at least 90 days (2026-10-12); central default is BrainWorkflow/wqb/knowledge_age_policy.py. Preserve real capture dates when migrating policy.
- This does not extend activity deadlines, research authorization, platform quota or Alpha check/correlation cache validity. Missing files and invalid provenance remain blockers. Freshness by age alone is not factual completeness.

- Read the current architecture in workspace `milestone.md` and task mainline/latest handoff in workspace `todo.md` first; then inspect only relevant source/tests. Do not treat summaries as a substitute for verification.
- Update architecture changes only in `milestone.md` and task/handoff recovery only in `todo.md`; repair any drift discovered during maintenance. Preserve existing changes and update the handoff before stopping.
- For BrainWorkflow, follow the approved Superpowers plan and tests; keep maintenance separate from live research.
- All subagents, including reviewers and nested workers, must run at reasoning effort `medium` or lower. Explicitly set `reasoning_effort` on dispatch; never inherit a higher effort or resume unknown settings. This is an effort cap, not a model-name cap.

## BrainWorkflow Product Interaction Contract

- Routine research interaction is limited to selecting an Option Card and Start/Stop. Start on a paused mission resumes its persisted authority; it does not create a replacement mission or silently widen its budget. Final Alpha submission requires separate explicit authorization.
- Execute ordinary stage transitions, local knowledge preparation, batches, polling, cooldown, in-flight reconciliation, bounded retries, triage, Discovery/Repair and research recording automatically. Do not require internal gate clicks, repeated chat instructions or a human message relay.
- Start checks exact-scope knowledge readiness before creating a mission. Repair locally compilable resources from existing raw evidence only when needed. Never manufacture freshness, coverage, successful checks or platform quota.
- Online platform documentation/data capture is an independently requested maintenance operation, not an implicit consequence of research Start. After capture, compile and validate the knowledge vault before research can use the changes.
- Stop is durable and takes priority over older Start/Resume requests, worker callbacks, retries and restarts. Preserve in-flight identities and evidence; never blindly resubmit an unknown POST outcome. Every automatic recovery remains within the original authority and bounded resource limits.
- Handle known recoverable blockers with scripts. Persist unresolved code/knowledge blockers and deliver a deduplicated event-driven maintenance request; do not use recurring model polling. Show the current action, blocker, evidence and delivery state in Console. Notification is not authority to edit code, capture data, deploy, change research rules or submit Alphas.
- Research/knowledge execution and project maintenance are separate loops. Human-AI maintenance conversations improve workflow design, rules, tests and knowledge contracts, rather than manually advance ordinary research steps. Convert repeated operational problems into durable automated handling and regression tests.
- Retain qualified unsubmitted Alpha IDs, expression/settings identity, raw metrics/check evidence and check time in the machine knowledge vault. Reuse valid evidence rather than repeat SELF/PROD checks on review or restart; expired, corrupted, invalidated or mismatched evidence cannot grant readiness. Invalidation preserves history and must dominate older in-flight saves. Final submission authorization remains separate.
- Admit no candidate on incomplete checks. Run inexpensive baseline checks before expensive SELF/PROD correlation checks; use bounded multisimulation and persisted local resources to reduce unnecessary platform requests.
- Scout and Discovery batches are capped at 30, not required to contain 30. Publish any nonempty valid novel batch before submission; never pad with duplicates. Zero-candidate plans rotate to another authoritative snapshot-backed selection under the original authority; exhausted planning faults must be visible and event-routed to maintenance, not silently classified as external waiting.
- Acceptance includes end-to-end offline regression, current loaded-version verification and Console action/state consistency. A passing isolated unit test is not delivery. Record external/protected blockers honestly in todo.md; never label a blocked live workflow as fully runnable.
