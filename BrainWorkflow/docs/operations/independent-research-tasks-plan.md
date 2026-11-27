# Independent Research Tasks And Single Reports

Status: source and native acceptance complete; installation verification pending.
Date: 2026-11-26 (Asia/Shanghai).
Rules: outer brain/AGENTS.md. Handoff: outer brain/todo.md.

## Contract

Each deliberate Start creates one independent task and visible card immediately.
Re-delivery of one command does not create another task. A task may contain N
experiment-tree lanes; separate Starts are separate tasks, not extra lanes of
the existing group. Stop targets a task. Start always creates a new task, not
Resume. Terminal cards remain visible. No automatic research maintenance chat.

Task ID: REGION_UNIVERSE_D<delay>_YYYYMMDDTHHMMSS_<unique suffix>.
Example: ALL_LARGE_D1_20261126T102500_a7c2. Use atomic creation/collision retry;
timestamp alone is insufficient. Alpha IDs belong to experiment nodes. When an
activity has no resolved scope yet, use explicit UNKNOWN components rather than
invent a scope or disable Start; record the subsequently resolved scope without
renaming the durable task identity. No Alpha ID is needed at Start.

## Orthogonal Module Map

| Module | Change | Input -> output |
| --- | --- | --- |
| Task registry/start identity | Changed: console_start plus small research_tasks helper | command_id/selection -> unique task/status; no global previous-task veto |
| Console command/snapshot | Changed: console_server, console_api | task_id/command -> task-specific action and list; no singleton busy flag |
| UI | Changed: frontend App/types/api and existing navigation | task list/selection -> cards and per-task tree/Seed/Repair views |
| Planning/expression tools | Interface affected | owning task/scope -> full tree or local terminal error; uncertainty advisory |
| Shared accounting/transport | Existing owners retained | identities/allowances -> budgeted or queued work; no refund or duplicate POST |
| Group/driver | Interface affected: research_group_driver, workflow_driver | owning task's group/lanes -> progress and terminal outcome |
| Terminal report | New small research_task_report module; reuse research_record formatting | immutable run observations -> one complete MD report |
| Knowledge summary | Changed: knowledge_compile/experience compiler | completed MD reports -> compiled experience when explicitly started |
| Maintenance notification | Disabled for new research-task failures | failure -> card/report only; explicit maintenance remains separate |

Current code has one console_start/request.json, previous-task guard and latest
group projection. Removing one guard alone would cause concurrent writers to
overwrite request/Stop/dispatch ownership. Replace the ownership contract and
all relevant callers together; do not just remove the error message.

Implementation ruling:reuse existing per-group drivers inside each task's
`runs/research_tasks/<short-storage-key>/runs` namespace. This naturally isolates legacy
singleton pointers/Start intent without a second engine. Resolve daily budget,
identity reservations, account cooldown and POST capacity to canonical workspace
runs; never initialize an independent account budget per namespace. Global
Console jobs/command receipts remain canonical, callbacks receive owning paths.
Windows integration exposed MAX_PATH with readable task IDs and full digest
folders. Keep complete IDs/digests in records, use8hex physical task keys and16hex
preparation/Repair keys, and same-directory UUID atomic temp names. Collision
or inconsistent full identity fails only the owning task; never overwrite it.

## Lifecycle

Start -> accepted card -> preparing/planning/queued/running -> terminal.
Terminal: stopped, failed, stalled, awaiting_submission, completed_no_candidate.
Existing watchdog/retry bounds apply; no new unlimited work or altered budgets.
An unresolved fault ends only its task, with known/unknown reason. Termination
quiesces owned workers before confirming stopped; unknown POST identities stay
unresolved in minimum runtime state. Do not falsely mark external work cancelled.

Competition/resource preparation happens inside accepted tasks. Missing activity
definitions are not verified eligibility; report inability to resolve honestly.
Old unknown model tasks stay preserved/read-only and do not veto independent
new tasks. Do not clear their usage, recreate their expressions or replay them.

## Verified Constraints Versus Exploration

Code tools enforce verified syntax and known applicable technical constraints.
Unknown semantics/signatures/parameter behavior are not blanket admission vetoes.
Return separate syntax/type/platform-test status. Allow supported-grammar calls
with uncertain technical behavior into predeclared, budgeted platform experiments;
record rejections as experimental results, not maintenance. No guessed execution
code, fake type proof, fabricated financial facts or arbitrary late formulas.
Verified constraint records must retain applicability and evidence; one example
does not prove a complete parameter domain. Keep safety/authority/accounting.

## One Research Output

knowledge/machine/researchreport/<task_id>.md

Script-rendered, atomic/idempotent publication; no extra report model call.
Report metadata: report_version, task_id, selected/resolved scope, option,
started/ended time, terminal status, counts, unresolved-outcome indicator.

1. Initial hypotheses and preplanned experiment tree, conditions and assumptions.
2. Every executed point: node/parent, expression, settings, Alpha ID or blank,
   metrics/check state, signal classification, branch, accepted/reverted outcome.
   Distinguish unexecuted, unknown and weak signal; never silently truncate points.
3. Errors/blockers: stage, code, evidence available, attempts, confirmed reason,
   unknown cause and effect on the task. Redact credentials/session material.
4. Final effective core/candidates and limitations, not economic causal proof.

Keep machine-readable versioned sections in the SAME Markdown if needed by the
summary reader, not a second JSON/JSONL report or full-vault catalog. Consume these
reports only during explicit knowledge summary. Stop new duplicate raw research
exports/research-ledger writes for the new mode; old records remain readable.
Minimal runs retain only driver inputs/state, frozen tree/package until legal
retirement, measured results, Stop, accounting/dedup/check and recovery evidence.
No new parallel detailed debug/history products. Do not delete existing history
as part of this feature. Failed report publication must be visible, retryable
locally and cannot turn into a claimed successful terminal report.

## Implementation Plan

Global constraints: no real model/platform calls in development/tests; preserve
shared4000/day, submission separation, unknown outcomes and installed-app path.
No Orchestrator rewrite or new Agent framework. Scoped regressions, one final
review and native acceptance; no routine full-suite/repeated review loops.

1. **Registry and identity.** Add research_tasks.py with create/read/list/update
   task helpers, atomic scoped IDs and command-id idempotency. Change console_start
   registration to task-local paths and route callbacks by task_id. Update every
   singleton request reader/writer/Stop caller, not only register_start.
   Tests: same-scope concurrent starts distinct; same command one task; old unknown
   cannot block new; concurrent writes cannot change another task's authority.
2. **Execution and isolation.** Pass task identity through Console jobs, planning,
   group dispatch and driver events. Shared capacity queues accepted tasks, never
   widens budget. Stop/fault affects only that task. New task mode routes final
   errors to terminal state, not automatic maintenance notices. Preserve old
   frozen readers, no old-task model replay.
   Tests: two independent mocked tasks; one fails/stalls/stops, other advances;
   shared budget/dedup/unknown POST survive restart; no notification emitted.
3. **Exploration constraints.** Separate unknown signature/parameter diagnostics
   from verified syntax/type conflicts in expression_tools/template_binding and
   package/Repair consumers. Preserve declared AST structure and script-owned
   plans; no fabricated signatures. Bounded invalid platform responses become
   recorded experiment failures. Tests: uncertain operator can be explored,
   proven syntax violation rejected, no unsupported AST/code injection and no
   late model decisions; original known execution bounds remain applicable.
4. **Reports and knowledge reader.** Add script renderer using existing formatting;
   wire all terminal exits, including preparation failure and user Stop. Consume
   reports in separate knowledge-summary path; suppress duplicate new-mode raw/
   machine research exports while preserving necessary operational evidence.
   Tests: every point/rollback/error retained, deterministic report, atomic retry,
   unknown outcomes clear, no credentials, one file only, compile reads MD once.
5. **Console and deployment.** Add multi-task cards and selected-task views/Stop;
   Start remains available for new task creation regardless of internal fault or
   unresolved activity. Same-command double click idempotent. Show pending/ended
   task/report state honestly, not stale running or refused-only navigation.
   Test source UI, command/snapshot consistency and packaged offline path with
   two tasks/one failure/report. Update root docs and manual, sync Git, then install
   and verify loaded revision. No research start, old-state cleanup or submission.

## Review Focus

Implementation evidence so far:166 scoped backend tests (one optional skipped),
32 frontend tests/typecheck/build, desktop/mobile task switching/report preview
and no horizontal overflow/page errors. Author review added a terminal-task POST
fence and corrupt-task isolation with observed RED->GREEN tests. The dispatched
fresh reviewer exhausted service quota and returned no findings; this is NOT
independent review approval. Final regression/native/deployment evidence belongs
to root todo.md; no live-model/platform or Alpha submission claim.

Author review additionally found an exited lane owner could leave its task
looking running when runtime_status never advanced. A RED->GREEN regression
now covers this, terminal-task POST fencing and owner deadline reconciliation.
Report regressions retain model-returned hypothesis/design (not private context),
every measured point, routing, Repair decisions and platform error fields.
Final broader run191 cases (190 passed/1 optional skip),32 frontend tests, then20
scoped post-review checks. Native proof must match the post-review source; the
first native build is superseded, not reused by relabeling its acceptance.
Post-review build20261127-101517-9885 passed9 native EXE tests; source revision
53aa5d5dde10d7ca581cf9a5902618dae63158dd5eb6bb8a21166b4d5ec41803.
No live research, WQB, submission or old-run reconciliation performed.

- Singleton callbacks/locks accidentally targeting the latest rather than owner.
- Command retries creating duplicate tasks or deliberate Starts deduplicated away.
- Task termination falsely resolving an in-flight POST or resetting accounting.
- Unknown-signature exploration accidentally labeled proven type-safe or exempt
  from declared technical/simulation identity checks.
- Terminal reports missing preflight faults, overwritten same-scope tasks, dropped
  points or summary compile still depending on now-suppressed duplicate ledgers.
