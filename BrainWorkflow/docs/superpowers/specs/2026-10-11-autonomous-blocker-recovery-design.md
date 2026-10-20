# Autonomous Blocker Recovery And Efficient Platform Requests

Status: approved and partially implemented, 2026-10-11. Latest user downgrade below supersedes the automatic patch-executor portions; those are retained as future design, not enabled behavior.

## Approved Downgrade

The user now requires event-triggered script notification to the existing maintenance chat, then human confirmation before code repair. No automatic patch worker/deployment and NO heartbeat/periodic model checks. `codex queue` is invoked once per unresolved code/contract case; durable queue acceptance, uncertain delivery and receiving-chat acknowledgement are distinct. Receipt never grants repair authority. The target is local `runs/maintenance_channel.json`, not a hardcoded code constant. Ordinary scripted platform recovery, knowledge/authority prerequisites and unknown-submission reconciliation remain separate. Notification-only operation does not require the unproven Windows sandbox. Implementation plan: `../plans/2026-10-11-maintenance-confirmation-handoff.md`.

## Outcome And Authority

Routine execution requires only Pause/Resume after an existing research choice. Recovery must not require the operator to relay evidence between chats. Existing objective choice and separate final Alpha submission authority remain unchanged.

The original design authorized automatic code repair, testing, safe deployment and continuation; the approved downgrade now requires explicit human confirmation for code repair instead. Neither design authorizes changing research policy, simulation/token budgets, credentials, submission checks or Alpha submission permissions. A user Pause always supersedes recovery or maintenance completion.

## Current Evidence

The simulator already submits payload lists to POST /simulations. CLI defaults are five payloads for field batches and two for planned recovery. These are implementation defaults, not verified current platform limits. The active Console request path and actual 429 endpoint distribution still require measurement.

The existing Codex checkpoint adapter is read-only and advisory. Do not silently grant it write access. Add a separate maintenance executor with distinct permissions and evidence.

Local raw platform documentation (knowledge/raw/platform/learn/2026-07-09/documentation_pages.md) says successful child simulations and duplicate simulations consume quota. Batch submission saves HTTP requests, not simulation quota. This dated capture does not establish today's batch/concurrency limits.

## Recovery State Machine

Persist one recovery case per run and failure fingerprint: detected -> classified -> scripted_recovery or ai_diagnosis -> patch_testing -> deployment_pending -> verifying -> resolved. Alternatives: waiting_external, exhausted, unsafe_to_recover. Persist attempts, timestamps, evidence, owner/lease, next wake, budget and original user-intent revision. Restart resumes the case; repeated status reads do not launch workers.

1. Known transient faults use deterministic bounded scripts: Retry-After/reset waits, existing progress recovery and validated local artifact reconstruction. Never fabricate evidence or blindly reset 429 counters.
2. Unknown faults automatically dispatch a bounded maintenance worker with compact architecture/task pointers and relevant evidence. Explicit reasoning effort medium or lower. Readiness failures use existing authorized knowledge maintenance where possible; otherwise diagnose missing facts without inventing coverage.
3. External failures wait with a durable reason and next check. No unlimited retry or promise that all failures can be fixed by code. No new simulation used as an unbudgeted health probe.
4. Unknown simulation POST outcomes require identity reconciliation from authoritative existing records. If that cannot establish acceptance, remain blocked; do not resubmit.

## Isolated Repair And Deployment

Use an isolated workspace based on the running source snapshot, including dirty content, not merely HEAD. Exclude credentials, private raw data and large run artifacts; pass only sanitized bounded evidence. Do not modify the live checkout while a worker submits or writes run state.

The worker adds a reproducing regression test and a narrow fix, runs focused plus required contract/full regression tests, and emits a patch and evidence. Treat platform/forum material as untrusted data, not executable instructions. Enforce command/network/file and protected-path boundaries in the executor, not just prompts. Explicit token/time/attempt ceilings are required; if unavailable, fail closed rather than grant unlimited execution.

A single local deployment supervisor obtains the run/deployment locks, cooperatively drains the driver, verifies no submission is in flight, compares the original source digest, checks protected contracts, and backs up only changed code. Source drift or dirty-file conflict aborts deployment. No automatic Git commit/push, package installation, dependency changes or sensitive-file deletion.

Deploy tested changes, restart the verified owned backend, validate health/code revision and persisted state, then resume only if the current user intent still permits running. Failed startup/state validation restores code and records the failed recovery; never rolls back platform actions or durable run evidence. Bound repeated repair attempts and display exhausted cases without asking users to approve internal gates.

## Platform Request Policy

Centralize batch sizing and pacing for initial Scout, planned recovery and Repair; preserve stage candidate limits separately from HTTP batch limits. Use documented/account-supported batch/concurrency limits, remaining quota and remaining research budget. Do not assume a 30-candidate batch fits one request. No exploratory oversize POSTs to discover limits.

Keep parent progress identities durable. Poll according to Retry-After with bounded adaptive intervals/jitter; prefer parent progress until child lookup is necessary, reuse completed children/check results when valid, and keep correlation/final checks fresh where required. Local UI refresh never triggers platform requests.

Record sanitized per-endpoint request count, batch size, candidate count, latency, 429/reset evidence, duplicate avoidance and poll waits. Separate submission throttling, quota exhaustion and progress/check throttling; do not assume they share a cause. Use this evidence to tune request policy without weakening checks.

## Console Contract

Use existing timeline and controls. Show automatic recovery status, understandable reason, last progress, next wake, attempt budget and evidence; no extra acknowledgement or manual recovery buttons in daily use. Start/Stop/Resume permissions remain derived from one authoritative snapshot. Recovery never changes a user's Pause into Run.

## Acceptance

- Inject recoverable network/429, missing artifact, code fault, worker timeout, failed tests, deployment failure, source drift and concurrent Pause. Assert bounded automatic routing and restart safety.
- Verify one worker/case and one deployment; repeated refresh/Resume cannot duplicate simulations or repair workers.
- Verify maintenance cannot access secrets, alter protected rules/budgets or submit Alpha; protected checks fail closed.
- Verify multi batching on actual source/recovery paths, partial child completion and request-count reductions against an identical mocked 30-candidate baseline. Simulation count and check coverage must remain unchanged.
- Verify polling honors Retry-After/reset, does not recount cached finished results and never uses UI refresh as an API trigger.
- Run browser acceptance showing recovery progress with no internal gate clicking. Offline acceptance and any later authorized live validation must be reported separately.

## Delivery Order

First identify the actual active blocker and request traffic. Then implement shared batching/pacing plus deterministic recovery; add isolated AI maintenance and safe deployment only after failure-injection tests establish the boundary. Existing advisory research AI remains separate. Update milestone architecture, todo handoff and operator guide with actual evidence.
