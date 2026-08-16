# Console Auto-Recovery And Knowledge-First Source Workflow Design

Date: 2026-08-12
Status: approved conversation design, written spec awaiting user review

## Purpose

The daily BrainWorkflow operations loop must not require the user to remember backend commands, source run IDs, artifact import rules, or the difference between resume, continue, retry planned, and complete in-flight. The Console should present one normal operating path:

1. Start a workflow.
2. Select one option card when research choices are available.
3. Continue or stop the workflow.
4. Approve Alpha submission only when a candidate has already passed required checks.

Everything else should be handled by deterministic workflow state, durable recovery records, or explicit AI judgment checkpoints. When an automatic step cannot proceed safely, the Console must explain the blocker in the page and write enough evidence for a maintenance task to reproduce and fix it.

This spec updates the existing single-page timeline design. It keeps the Scout, Seed, Discovery, Repair, and Submit research framework unchanged, but changes the Console and source-artifact bridge so routine operation is no longer a manual command puzzle.

## Current Failure Modes

The recent Power Pool run exposed four distinct issues.

1. The operations narrative mixed up Scout and Seed simulation caps. The code says Scout has an effective cap of 30 and Seed has an effective cap of 8. Runtime metadata confirmed Scout planned 30 candidates. Console copy, user docs, and tests must stop implying Scout is capped at 8.

2. The active Orchestrator run paused at Scout/Seed because `candidates.csv` was missing. The Console showed Resume and Continue, but those buttons could only repeat the same artifact check. The proper source-artifact generation path existed in separate CLI commands and timestamped source runs, not in the active Orchestrator control loop.

3. Source runs selected data fields from the live `/data-fields` API unless an explicit field cache path was supplied. Knowledge readiness passing did not mean fields and operators were selected from the knowledge vault. The system must display this provenance honestly and prefer knowledge-backed ledgers when they are available.

4. Submit-side HTTP 429 stops are recorded as recoverable errors, but there is no durable cooldown scheduler for planned candidates. The user sees a blocked workflow instead of a clear "rate limited, retry after this time, then resume planned queue" state.

## User Operating Contract

The normal Console must expose only four primary user actions.

- `Start workflow`: starts a new research workflow from the currently selected option card and measured scope.
- Option card selection: the user chooses among generated research options by clicking a card or a radio/select control bound to a card.
- `Continue workflow`: performs the next safe deterministic action, including recovery actions, without asking the user to pick a backend subcommand.
- `Stop workflow`: pauses or aborts the active workflow without deleting evidence.

Candidate submission approval remains a separate explicit control because no Alpha should be submitted automatically.

The primary page must not require these routine manual steps:

- choosing between `workflow-resume` and `workflow-continue`;
- typing a source run ID;
- manually importing Scout/Seed artifacts;
- deciding whether to call `complete-in-flight` or `retry-planned`;
- reading stdout/stderr to learn whether a job is still alive;
- asking Codex chat what a spinning browser means.

Advanced maintenance diagnostics may remain available in collapsible sections or a separate maintenance route, but they are not part of normal daily operation.

## Stage Budget Contract

`wqb.research_workflow.STAGE_MAX_SIMULATIONS` is the source of truth for stage caps:

- Scout: 30
- Seed: 8
- Discovery: 50
- Repair: 8
- Submit: 0

Readiness rules that require a minimum 30-alpha batch refer to the Scout/source generation batch contract, not to the Seed refinement cap. The code, Console labels, run metadata, user manual, and tests must use the same language:

- `requested_max_alphas`: what the caller requested;
- `effective_max_alphas`: the stage-capped count;
- `candidate_generation_limit`: the number of expressions that may be generated before simulation selection;
- `workflow_stage`: the stage whose cap was applied.

Any run that claims `workflow_stage=scout` and `effective_max_alphas=8` is inconsistent unless the stage cap contract is explicitly changed in code and tests.

## Single-Page Console Model

The Console remains a local server-rendered page. It should feel like an operations instrument rather than a collection of backend panels.

### Header

The header shows:

- active run ID or `No active workflow`;
- stage and status;
- next safe action in plain language;
- live API enabled/disabled;
- rate-limit/cooldown status if present;
- one primary `Continue workflow` button when a workflow is active.

### Research Choice

When no workflow is active, option cards are the main content. Each card is selectable directly. The selected card drives `Start workflow`.

Cards should show:

- objective label;
- incentive or activity driver;
- region, delay, universe, and data source scope;
- knowledge/data coverage status;
- expected stage entry point;
- whether live fallback may be needed.

The user should not type an option ID in the normal path.

### Current Work

This panel explains what is happening now:

- deterministic local check;
- source-artifact generation;
- in-flight recovery;
- rate-limit wait;
- workflow pause;
- user approval;
- AI judgment checkpoint;
- failed maintenance blocker.

It shows the current job ID, elapsed time, latest event, evidence paths, and the exact next automatic step. If the browser request has returned while a job runs in the background, the panel says that directly.

### Runtime Timeline

The timeline is event-backed and stable in size. It includes:

- readiness;
- knowledge health;
- option generation;
- user option selection;
- workflow start;
- Scout/source artifact generation;
- Seed;
- Discovery;
- Repair;
- Submit review;
- knowledge compile after research.

Each row has a status, short explanation, evidence path, and source type:

- deterministic code;
- user decision;
- live platform call;
- AI judgment;
- maintenance blocker.

### Diagnostics

Diagnostics are read-only by default:

- raw workflow state;
- recent job summaries;
- run artifacts;
- stdout/stderr links;
- provenance records;
- manual CLI commands for maintainers.

Diagnostics must not compete visually with the primary action path.

## Smart Continue Dispatcher

`Continue workflow` should call one high-level action, for example `workflow-auto-continue`. The dispatcher reads durable state and chooses the next safe internal command.

The dispatcher algorithm:

1. If no active workflow exists, refuse and ask the user to pick an option card and start.
2. If the workflow is waiting for user approval, refuse automatic progress and show the approval needed.
3. If the active workflow is paused with a resumable reason, resume internally and then continue if the next action is deterministic.
4. If the active workflow is paused at Scout/Seed because `candidates.csv` is missing, enter source-artifact recovery:
   - import a valid unimported source run if one already exists;
   - otherwise complete an in-flight simulation from the chosen source run;
   - otherwise respect any active cooldown;
   - otherwise resume the persisted planned candidate queue;
   - otherwise start a bounded source batch using the knowledge-first resolver.
5. If the active source run hits too many consecutive rate limits, pause and create a maintenance blocker instead of continuing to consume budget.
6. If the active workflow has a normal `workflow-continue` next action, continue it.
7. If the active workflow reaches candidate submission, stop for explicit user approval.

The dispatcher must be idempotent. Repeated clicks cannot duplicate a simulation submission, duplicate an artifact import, or lose planned candidates.

## Source-Artifact Bridge

The Orchestrator owns the main workflow run. Source runs are allowed as implementation details, but the user should not have to manage them.

The source bridge owns:

- selecting or creating a source run for the active workflow;
- tracking the selected source run in active workflow metadata;
- generating or recovering source candidates;
- validating `candidates.csv`;
- importing candidates into the active workflow;
- recording every import or refusal event.

The active workflow metadata should include:

- `source_run_id`;
- `source_run_dir`;
- `source_status`;
- `source_next_action`;
- `source_candidate_count`;
- `source_hard_pass_count`;
- `source_last_error`;
- `source_field_source`;
- `source_operator_source`;
- `source_provenance_path`.

If a source run cannot produce candidates, the Console should say whether the issue is no signal, rate limit, in-flight recovery, invalid artifact, or missing knowledge coverage.

## Rate-Limit And Cooldown Contract

Submit-side HTTP 429 and platform Retry-After responses must become durable workflow state.

The MVP is local durable state plus Console-driven recovery, not a background daemon.

State files:

- account/platform-level cooldown: `runs/rate_limit_state.json`;
- source-run-specific cooldown and queue state: `<source_run_dir>/rate_limit_state.json`;
- source-run lock: `<source_run_dir>/source_run_lock.json`.

Cooldown fields:

- `status`;
- `updated_at`;
- `retry_after_seconds`;
- `retry_at`;
- `attempt_count`;
- `consecutive_429_count`;
- `max_consecutive_429`;
- `last_status_code`;
- `last_error_type`;
- `last_command`;
- `last_run_id`;
- `last_candidate_hash`;
- `last_progress_url`;
- `evidence_path`.

Behavior:

- On submit 429, retain planned candidates and write cooldown state.
- If Retry-After is present, respect it within configured maximum cooldown limits.
- If Retry-After is absent, use bounded exponential backoff with deterministic jitter so tests are stable.
- While cooldown is active, `Continue workflow` reports `rate-limit-wait` and does not contact the platform.
- After cooldown expires, `Continue workflow` resumes planned candidates through the persisted queue.
- If a progress URL exists, recovery uses `complete-in-flight` before submitting a new simulation.
- Consecutive 429 above the threshold creates a maintenance blocker and stops automatic live calls.
- No rate-limit recovery path can auto-submit a final Alpha.

## Source-Run Lock Contract

Only one source action may mutate a source run at a time.

The lock record stores:

- `run_id`;
- `action`;
- `pid`;
- `created_at`;
- `expires_at`;
- `command_hash`;
- `candidate_hash`;
- `progress_url`;
- `status`.

Before `retry-planned`, `complete-in-flight`, source batch generation, or artifact import, the system tries to acquire the lock.

If the lock process is alive, the Console shows the running action. If the lock is stale and the process is gone, the dispatcher records stale-lock recovery and continues from durable events. If the lock cannot be interpreted, the workflow pauses with a maintenance blocker.

## Knowledge-First Resolver

Field and operator selection should be knowledge-first. Live API fallback remains allowed only when the run mode and user authorization permit it.

Introduce a resolver boundary, for example `wqb.knowledge_source_resolver`, with one main read API:

```text
resolve_source_inputs(
    knowledge_root,
    option_card,
    scope,
    template_mode,
    allow_live_fallback
) -> SourceSelection
```

`SourceSelection` contains:

- selected fields;
- selected operators;
- selected template family;
- field source: `knowledge`, `cache`, or `live_api`;
- operator source: `knowledge`, `code_default`, or `live_api`;
- template source: `template_library`, `code_default`, or `proposal`;
- provenance records with source path, capture date, digest, region, delay, universe, and authoritative/seed-cache status;
- blocker records when the knowledge vault cannot support the requested scope.

Resolver priority:

1. authoritative machine data ledger and field catalog provenance;
2. curated template matrix and operator semantic ledger;
3. measured cache supplied by the CLI;
4. live API fallback only when explicitly allowed;
5. block with a readable knowledge readiness issue.

This change does not claim that the current knowledge vault is complete. It makes the system honest: each run must say where fields, operators, and templates came from.

## AI Intervention Policy

The local Console does not embed a model key or silently call GPT. It records AI checkpoints that a Codex task, an agent skill, or a future automation runner can consume.

Use AI judgment for:

- choosing among research objectives from incentives, activity rules, data novelty, and template novelty;
- mapping data semantics to economic hypotheses and template families;
- innovating low-correlation template variants;
- explaining near-miss results and choosing repair levers;
- proposing rule changes after repeated workflow failures;
- compiling research records and platform updates into the human-readable wiki.

Do not use AI judgment for:

- checking whether files exist;
- polling jobs;
- computing readiness status;
- reading stage caps;
- enforcing cooldown;
- importing validated artifacts;
- rendering Console state.

If an AI checkpoint is required, the Console shows it as a waiting state and writes the checkpoint to durable storage. The operations loop can then hand that checkpoint to the maintenance or research Codex task.

## Stop Workflow Contract

`Stop workflow` is a non-destructive operation.

It should:

- write a workflow event with user-stop reason;
- mark the active run stopped or paused according to Orchestrator rules;
- release any Console-owned action lock if no live child process is active;
- preserve source run evidence;
- not delete candidates, logs, credentials, or raw knowledge files;
- not kill an external live platform request unless a safe child-process handle is owned by the Console.

After stop, the page returns to the research option/start state and keeps recent stopped runs visible in diagnostics.

## Testing Strategy

Tests use standard-library `unittest` and no live platform calls.

Required tests:

- Stage budget tests:
  - Scout cap remains 30 and Seed cap remains 8.
  - run metadata records requested count, effective count, generation limit, and stage distinctly.
  - docs-facing helpers do not describe Scout as Seed.

- Console primary-path tests:
  - active workflow renders one primary `Continue workflow` button and one `Stop workflow` button.
  - paused `workflow-resume` state still renders `Continue workflow`, not separate resume/continue choices.
  - normal page does not require a visible source run ID input.
  - option cards are directly selectable and drive `Start workflow`.

- Smart dispatcher tests:
  - missing Scout/Seed candidates triggers source bridge recovery instead of repeating the same artifact check.
  - valid source candidates are imported once.
  - repeated Continue clicks do not duplicate imports or submissions.
  - waiting-for-user states refuse automatic progress.

- Rate-limit tests:
  - submit 429 writes cooldown state and retains planned candidates.
  - active cooldown prevents live platform calls.
  - expired cooldown resumes planned queue.
  - consecutive 429 threshold creates a maintenance blocker.
  - in-flight progress URL is recovered before any new submit.

- Source-run lock tests:
  - concurrent mutation is refused.
  - stale lock recovery records an event.
  - corrupt lock pauses with a maintenance blocker.

- Knowledge resolver tests:
  - resolver prefers knowledge ledger over live API.
  - resolver records field, operator, and template provenance.
  - missing knowledge with live fallback disabled blocks the run.
  - live fallback, when allowed, is labeled `live_api` in run metadata and Console state.

Minimum verification:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_research_workflow tests.test_console_server tests.test_console_jobs -q
python -m unittest discover -s tests -q
python -m compileall -q wqb tests scripts
git diff --check
```

## Documentation Updates

Update operation docs after implementation:

- user workflow manual: one-button Continue path, option card selection, stop behavior, candidate approval boundary;
- operating guide: maintenance-only commands and recovery evidence paths;
- Console UI text: Scout 30 and Seed 8 explained without ambiguity;
- knowledge docs: field/operator/template provenance meanings;
- milestone/todo guidance: operations task runs the workflow; maintenance task fixes workflow bugs and docs.

## Implementation Boundary

First implementation slice:

1. Fix stage-budget language and assertions.
2. Add smart Console `Continue workflow` action and hide manual source import from normal UI.
3. Add source bridge state for missing Scout/Seed candidates.
4. Add local rate-limit cooldown state, source-run lock, and idempotent recovery behavior.
5. Add knowledge-first resolver interface and provenance labeling. Full semantic ranking can evolve later behind this interface.
6. Update docs and tests.

Out of scope for this slice:

- direct model API integration inside the Console server;
- background daemon scheduling;
- automatic Alpha submission;
- broad redesign of the Scout, Seed, Discovery, Repair, and Submit research framework;
- deleting legacy run artifacts or knowledge raw materials.

## Acceptance Criteria

- The user can run the normal workflow from one Console page with Start, option card selection, Continue, Stop, and explicit candidate submission approval.
- A paused Scout/Seed run with missing candidates no longer loops on a no-op Continue; it either recovers/imports source artifacts, waits for cooldown, starts a bounded source batch, or records a maintenance blocker.
- Scout and Seed caps are presented consistently everywhere.
- Rate limits are visible, durable, bounded, and recoverable without losing planned candidates.
- Field/operator/template provenance is visible in run metadata and Console state.
- The Console clearly distinguishes deterministic code, live platform calls, user decisions, AI checkpoints, and maintenance blockers.
- No Alpha can be submitted automatically.
- Full non-live tests pass before handoff to the operations loop.

## Spec Self-Review

- Placeholder scan: no placeholder markers remain.
- Internal consistency: the Console is the normal operations surface; source runs are implementation details managed by the source bridge; Orchestrator remains the active workflow owner.
- Scope check: this is one implementation slice because all changes serve the same failure mode: daily operation cannot progress safely from a single Console action.
- Ambiguity check: automatic recovery means deterministic local recovery and bounded live calls only when already authorized. It does not mean hidden GPT calls, background daemons, or automatic Alpha submission.
