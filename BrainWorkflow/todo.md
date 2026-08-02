# BrainWorkflow TODO

## 2026-08-02 Task 10: Documentation, Console Operating Guide, And Final Verification

### Requirement Summary
- Document simplified knowledge maintenance, breadth-first platform data capture, and the non-live delivery gate for routine Console operation.
- Verify the complete non-live suite and local delivery commands without live WorldQuant BRAIN API calls, simulations, or submissions.

### Execution Plan
1. [completed] Updated the operating guide and delivery-contract specification with the active three-layer vault, capture sequence, delivery gate, implementation status, and final verification commands.
2. [completed] Required wrapper discovery passed 696 tests and `compileall` passed. Local `compile-knowledge` wrote its report but remained blocked by the existing incomplete knowledge migration; `delivery-gate` wrote its report and failed on explicit local knowledge/readiness blockers without any live call.
3. [completed] Recorded verification results and committed the documentation/progress changes.

### Result
- Non-live verification: 696 tests passed; `python -m compileall -q wqb tests` exited 0.
- Compile report: `C:\Users\oytl\Desktop\pyproject\brain\knowledge\raw\maintenance\compile_reports\2026-08-02.json`.
- Delivery-gate report: `C:\Users\oytl\Desktop\pyproject\brain\knowledge\raw\maintenance\delivery_gates\2026-08-02.json`.
- Remaining blocker: the pre-existing knowledge vault has legacy active paths, no current `machine` resources, stale plan-only readiness artifacts, and no accepted durable workflow boundary. No live platform call, simulation, or submission ran.

## 2026-08-02 Task 9: Delivery Gate And Operational Handoff Report

### Requirement Summary
- Add the non-live `delivery-gate` workflow verification command, persisted report, and Console action/state/timeline integration.
- Preserve `compile-knowledge`; do not invoke live WorldQuant BRAIN APIs, simulations, or submissions.

### Execution Plan
1. [completed] Added focused delivery-gate and existing CLI/Console regression tests; RED failed for the expected absent module and missing integration points.
2. [completed] Implemented the durable gate report, CLI dispatch, asynchronous Console action, state reader, and timeline row.
3. [completed] Focused wrapper passed 206 tests and full non-live discovery passed 693 tests with the Windows compatibility environment; committed Task 9 code/tests as `68f3bc6` (`add delivery gate`).

### Result
- Report: `../.superpowers/sdd/2026-07-30-simplified-knowledge-structure-delivery-contract-implementation/task-9-report.md`.
- The first discovery invocation without the supplied Windows environment variables reproduced the known `WinError 10106` in two HTTP-server tests; the required compatibility wrapper passed the complete suite.

### Fix Round 1 (2026-08-02)
- [completed] Added RED regressions for plan-only readiness, durable approval boundaries, and persisted-time workflow-state selection.
- [completed] Made delivery-gate readiness-aware and reused validated durable workflow-state loading without affecting live execution paths.
- [completed] Focused wrapper passed 209 tests and full non-live discovery passed 696 tests; appended the Task 9 report and committed only the fix source/tests as `9d816c8` (`harden delivery gate`).

## 2026-07-30 Final Review Fix: Workflow Console Important Findings

### Requirement Summary
- Fix the four final-review Important findings only: runtime polling refresh, async long-action routing, job-owned capture progress, and terminal async context recording.
- Preserve the existing research workflow logic, job-record compatibility, and no-live-execution boundaries.

### Confirmed Details
- User authorized immediate execution and requires a single coherent committed patch.
- Use standard-library `unittest`; write regressions before production changes.
- Required report: `../.superpowers/sdd/2026-07-30-workflow-console-single-page-timeline-implementation/final-review-fix-report.md`.

### Execution Plan
1. [completed] Added focused regressions for DOM polling, async routing, job capture ownership, terminal context recording, and adjacent timeout/PID behavior.
2. [completed] Implemented minimal Console server, job, and progress changes.
3. [completed] Ran required verification, updated recovery records and report, and committed the fix.

### Result
- Commit `c55f9e4 fix workflow console final review findings` resolves all four Important final-review findings.
- Verification passed: focused Console suite 84 tests, full non-live discovery 630 tests, `compileall`, and root `git diff --check`.
- Report: `../.superpowers/sdd/2026-07-30-workflow-console-single-page-timeline-implementation/final-review-fix-report.md`.

## 2026-07-30 Task 5: Single-Page Console Server And API

### Fix Round 1
- [completed] Restored the existing research and knowledge-transparency anchors inside the single-page Control Center.
- [completed] Reproduced the two reported RED regressions, then verified all required Console suites with the Windows environment values set.
- [completed] Appended the report, updated recovery records, and committed the scoped Console server change.

### Fix Round 1 Result
- Commit `fcb04c4 restore console control center summaries` restores Workflow Console, Research Start, Workflow Progress, Knowledge Maintenance, Data Authority, Knowledge Contracts, Semantic Ledgers, and Option Blockers without reverting the single-page design.
- Verification passed: `tests.test_console_server` 35 tests; combined Console job/state/server suite 65 tests; compileall and diff check passed.

### Requirement Summary
- Integrate the Console timeline/current-work read model into one local HTTP Control Center.
- Add `/api/state`, render proposals inline while preserving `/proposals`, and start long Console actions asynchronously.
- Preserve workflow behavior and avoid model API calls from the HTTP server.

### Confirmed Details
- The controller approved execution; the Task 5 brief is authoritative.
- Scope is `wqb/console_server.py`, `wqb/console_context.py` only if terminal-only milestone writes are needed, and `tests/test_console_server.py`.
- Use unittest, execute the prescribed RED/GREEN tests, write the required report, and commit the Task 5 implementation/test files.

### Execution Plan
1. [completed] Added the prescribed render and async-routing regressions; the test runner is blocked before collection by Windows `WinError 10106` while importing `unittest.mock`/`asyncio`.
2. [completed] Implemented the control-center renderer, API state route, immediate async redirect, and async action routing.
3. [completed] `console_jobs` plus `console_state` passed 30 tests; `compileall`, diff check, and a direct production-module smoke check passed. Focused Console server verification remains blocked by the local Winsock provider error.

### Result
- Commit `5c4de5e render single page console timeline` contains only `wqb/console_server.py` and `tests/test_console_server.py`.
- Required report: `.superpowers/sdd/2026-07-30-workflow-console-single-page-timeline-implementation/task-5-report.md`.

## 2026-07-30 Task 4: Console Timeline Read Model

### Fix Round 1
- [completed] Align timeline rows with durable Orchestrator stage IDs and expose per-stage status in the Console state summary.
- [completed] Add regression coverage for real non-overlapping stage IDs and deterministic source labeling.
- [completed] Append the task report and commit only Task 4 files.

### Fix Round 1 Verification
- RED: focused tests failed because real Orchestrator stage rows were absent and `triage` was labeled `ai_judgment`.
- GREEN: `python -m unittest tests.test_console_timeline tests.test_console_state -v` passed 21 tests.
- `python -m compileall -q wqb` and `git diff --check` passed.
- Commit `6de3889 fix console timeline stage mapping` contains only Task 4 fix files.

### Fix Round 2
- [completed] Preserve persisted `paused` status for the current Orchestrator stage and render terminal `complete` as completed.
- [completed] Append the report and commit only Task 4 fix files.

### Fix Round 2 Verification
- RED: a current paused stage displayed as running.
- GREEN: `python -m unittest tests.test_console_timeline tests.test_console_state -v` passed 22 tests.
- `python -m compileall -q wqb` and `git diff --check` passed.
- Commit `e33691e fix console timeline terminal statuses` contains only the two Task 4 fix files.

### Requirement Summary
- Build the Console timeline and current-work read models, then include durable AI checkpoints in `load_console_state`.
- Preserve existing job-record readability and keep the change limited to the Task 4 files.

### Confirmed Details
- User authorized immediate execution.
- Use unittest and the Task 4 brief's focused tests.
- Required commit message: `add console timeline state`.

### Execution Plan
- [completed] Add the prescribed timeline and Console state integration tests, then verify the RED failure.
- [completed] Implement timeline rows and wire reconciled jobs and AI checkpoints into Console state.
- [completed] Write the required Task 4 report and commit only the four Task 4 files.

### Verification
- RED: `python -m unittest tests.test_console_timeline -v` failed as expected with `ModuleNotFoundError: No module named 'wqb.console_timeline'`.
- Focused verification: `python -m unittest tests.test_console_timeline tests.test_console_state -v` passed 19 tests.
- `git diff --check` passed.

### Result
- Timeline rows now distinguish deterministic actions, durable AI judgment checkpoints, and user approvals.
- `load_console_state` now exposes reconciled jobs, AI checkpoints, timeline rows, and current work.
- Commit `47d231f add console timeline state` contains only the four Task 4 implementation and test files; progress and report artifacts remain uncommitted.

## 2026-07-16 Final Re-review: Partial Capture Safety

### Requirement Summary
- Fix only partial raw-capture ledger coverage and scope completion/resume behavior.
- Do not alter live simulation, submission, or repair behavior.

### Confirmed Details
- Add RED regressions before implementation and run the brief's focused and full verification.
- Commit only the five allowed source/test files with message `fix partial capture coverage gates`.
- Keep this progress record and the required `.superpowers/sdd` report uncommitted.

### Execution Plan
- [completed] Add and verify regressions for partial ledger rows/start gating and retriable failed field capture.
- [completed] Apply minimal compile and capture status fixes.
- [completed] Run required verification, commit allowed files, and write the uncommitted report.

### Result
- RED verification failed as expected: warning manifests compiled as `measured_raw`, the selected option could start, and field failures finalized scopes as `completed`.
- Commit `2268247 fix partial capture coverage gates` contains only the five allowed source and test files.
- Focused verification passed 35 tests; full discovery passed 476 tests; `compileall` and `git diff --check` passed.
- The repository-level `milestone.md` requested by the recovery instructions is absent; it was not created because the re-review brief limits edits to the listed files and uncommitted report.

## 2026-07-13 Task 6: Stage Adapters And Plan-Only Orchestration

### Requirement Summary
- Add the schedule stage adapter and one-step plan-only continuation behavior exactly as specified in `.superpowers/sdd/task-6-brief.md`.
- Commit only the four Task 6 BrainWorkflow implementation and test files; do not stage progress artifacts.

### Confirmed Details
- User explicitly confirmed Subagent-Driven execution and requested immediate continuation.
- Work from `BrainWorkflow`; preserve existing dirty progress files.
- Required commit message: `connect orchestrator schedule stage`.

### Execution Plan
- [completed] Add the brief's adapter and orchestrator RED tests and capture expected failure.
- [completed] Implement the schedule-only adapter and `continue_once` state transitions.
- [completed] Run focused tests, then the complete unittest suite once.
- [completed] Self-review, write `.superpowers/sdd/task-6-report.md`, and commit only the four owned files.

### Verification
- RED: `python -m unittest tests.test_workflow_stage_adapters -v` failed as expected with `ModuleNotFoundError: No module named 'wqb.workflow_stage_adapters'`.
- Focused suite: 8 tests passed.
- Full suite: 275 tests passed.
- `git diff --check` passed.
- Self-review found no correctness or scope defects. The brief's first test checked an artifact after `TemporaryDirectory` cleanup; its assertions were placed inside the context so it verifies the intended written artifact.

### Result
- Commit: `e98def9 connect orchestrator schedule stage`.
- Only the four required Task 6 implementation/test files were committed.

## 2026-07-12 Task 2: Workflow State And Event Store

### Requirement Summary
- Implement the exact interfaces and values from `.superpowers/sdd/task-2-brief.md`.
- Own only `wqb/workflow_state.py`, `wqb/workflow_events.py`, and their focused unittest files.
- Preserve the Orchestrator-owned `run_state.json` boundary and existing research framework.

### Confirmed Details
- User authorized execution on 2026-07-12.
- Base commit: `a9ccd0f1ca5b462ec8ce39bf75d47ebd1c3e5330`.
- Test runner: `python -m unittest` from `BrainWorkflow`.
- Required commit message: `add workflow state and events`.
- Required report: `.superpowers/sdd/task-2-report.md`.

### Execution Plan
- [completed] Add the brief's failing state and event tests and verify RED.
- [completed] Implement workflow state and append-only event store.
- [completed] Run focused and full unittest suites.
- [completed] Commit owned repository changes and write the task report.

### Result
- RED: focused tests failed with the expected missing `wqb.workflow_state` and `wqb.workflow_events` modules.
- Focused tests: 7 passed.
- Full suite: 258 passed.
- Commit: `cc03499 add workflow state and events`.
- Report: `.superpowers/sdd/task-2-report.md`.

## 2026-07-09 Repository Setup

### Requirement Summary
- Create `BrainWorkflow/` under `oytl2024/skills-and-workflows` as the clean project repository folder for the WorldQuant BRAIN workflow.
- Continue from the approved Phase 2 principle-led research workflow design.

### Confirmed Boundaries
- Include maintainable code, tests, configuration, design docs, implementation plans, and compiled/general knowledge.
- Exclude credentials, raw run artifacts, raw platform snapshots, temporary directories, and old root-level scripts with local assumptions.
- Do not hardcode API credentials.

### Current Next Step
- Implement the Phase 2 principle-led research planner from:
  `docs/superpowers/specs/2026-07-09-wqb-phase2-principle-led-research-workflow-design.md`

### Repository Status
- Branch: `agent/brainworkflow-phase2`
- Initial commit: `f42c5da`
- Draft PR: https://github.com/oytl2024/skills-and-workflows/pull/1
- Verification: `python -m unittest discover -s tests -v` passed 160 tests inside `BrainWorkflow/`.
- GitHub CLI `gh` is not installed locally; the PR was opened through the GitHub connector.

## 2026-07-09 Phase 2 SDD Execution

### Requirement Summary
- Execute the approved Phase 2 principle-led research planner implementation plan.
- Use option 1: subagent-driven development with an implementer and reviewer gate per task.

### Confirmed Details
- Work from repository root `C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows`.
- Edit project files under `BrainWorkflow/`.
- Keep `.superpowers/sdd/progress.md` as local execution scratch, not a committed project artifact.
- Preserve the workflow principle: no live simulations from planner commands; generate research options and decision records only.

### Execution Plan
- Commit the Task 5 plan correction that keeps CLI unittest discovery valid.
- Dispatch Tasks 1-6 from `docs/superpowers/plans/2026-07-09-wqb-phase2-principle-led-research-planner-implementation.md`.
- Run full verification and update the existing draft PR after review.

## 2026-07-09 Task 2: Official Rule Refresh

### Requirement Summary
- Create `BrainWorkflow/wqb/rule_refresh.py`.
- Create `BrainWorkflow/tests/test_rule_refresh.py`.
- Implement `DEFAULT_RULE_PAGE_IDS` and `refresh_incentive_snapshot(client, generated_at)`.
- Use `WQBClient.get_json`, `WQBClient.options_json`, `IncentiveSnapshot`, and `SourceEvidence`.

### Confirmed Details
- Follow the exact task brief values and normalize official rule sources only.
- Generate option cards before any concrete alpha batch logic; do not submit or simulate alphas here.
- If refresh fails, keep cached evidence visible with staleness and uncertainty instead of inventing data.
- Use the existing unittest style and keep the implementation simple.

### Execution Plan
- Add the failing rule refresh test first and run it to confirm the red state.
- Implement `wqb/rule_refresh.py` with safe source refresh helpers and rule page normalization.
- Run the focused, related, and full unittest suites.
- Commit the task changes with the brief-required message.

### Notes
- Task ownership is limited to `BrainWorkflow/wqb/rule_refresh.py` and `BrainWorkflow/tests/test_rule_refresh.py`.

### Completion
- Implemented the rule refresh snapshot loader and its focused regression test.
- Verified red-to-green flow for the new test, then ran related and full unittest suites successfully.
- No additional repository files were changed for this task.

## 2026-07-09 Task 5 Local Takeover And Learn Ingestion

### Requirement Summary
- Continue the Phase 2 implementation despite the Task 5 subagent failing with an external usage-limit error before any code changes.
- Implement Task 5 locally with the same red-green verification and no-touch constraint for existing backtest, repair, optimization, submission, submit-candidate, and Stage 1 sedimentation workflows.
- After completing the planner implementation and verification, save all WorldQuant BRAIN Learn material except Courses into `knowledge/raw/learn`, including Documentation and Operators, then compile the durable wiki.

### Confirmed Details
- The Task 5 worker produced no commit and no report; the working tree was clean before local takeover.
- The new Learn ingestion work is post-implementation work: finish the research planner CLI/docs first, then fetch and compile Learn material.
- Do not hardcode credentials or secrets. Use existing environment/config paths.
- Keep raw source material separate from compiled wiki pages.

### Execution Plan
- Add the Task 5 CLI test inside `CliTests`.
- Implement only the read-only `plan-research-options` command path in `wqb/cli.py`.
- Run focused, related, and full unittest suites before committing.
- Implement Task 6 knowledge pages.
- Fetch non-course Learn material through the platform API when credentials are available, store raw material under `knowledge/raw/learn`, and compile summary wiki pages.

### Completion
- Implemented and committed the read-only `plan-research-options` CLI command after the Task 5 subagent hit an external usage-limit error.
- Implemented and committed the Phase 2 principle/decision wiki pages.
- Captured non-course Learn material into `knowledge/raw/learn`: Operators, Documentation tutorial pages, FAQs, Videos, Recommended Readings, and search discovery results.
- Compiled `knowledge/wiki/10_foundations/learn_material_index.md` and `knowledge/wiki/20_semantics/operator_catalog_official.md`.
- Validation passed: raw JSON parses, `scripts/capture_learn_material.py` compiles, compiled wiki placeholder scan is clean, and full unittest discovery passed 169 tests.

## 2026-07-09 Phase 2 Finalization

### Requirement Summary
- Continue the task through final verification and update the existing remote PR branch.
- Run the read-only research planner once with current platform information so the decision-card output path is exercised against live data.
- Preserve the existing backtest, repair, optimization, submission, submit-candidate, and Stage 1 sedimentation workflows.

### Confirmed Details
- Use the existing branch `agent/brainworkflow-phase2`.
- Do not run simulations or submit alphas from the research planner.
- If the live planner cannot refresh current platform information, record the failure clearly instead of fabricating option cards.

### Execution Plan
- Run `plan-research-options` with the Stage 1 config and write cards under `knowledge/wiki/70_decisions`.
- Commit any generated decision-card artifacts and this finalization record.
- Run the full unittest suite and concise repository checks.
- Push the branch to the existing PR.

### Completion
- Ran the live read-only planner with `configs/stage1_usa_d1.yaml`.
- Generated four current research option cards under `knowledge/wiki/70_decisions` without running simulations or submissions.
- Verification passed: full unittest discovery ran 169 tests successfully, Learn raw JSON parsed, research option JSONL parsed, and compiled wiki placeholder scan was clean.

## 2026-07-09 Shared Knowledge Vault Migration

### Requirement Summary
- Use `C:\Users\oytl\Desktop\pyproject\brain\knowledge` as the only Obsidian knowledge vault.
- Move the BrainWorkflow knowledge material into that shared vault.
- Remove the repository-local `BrainWorkflow\knowledge` copy after validation.

### Confirmed Details
- Keep `docs/knowledge` as compact repository documentation; it is not the Obsidian vault.
- Preserve root vault `.obsidian` settings.
- Future knowledge-writing commands should default to the shared vault and avoid recreating `BrainWorkflow\knowledge`.

### Execution Plan
- Merge the repository-local knowledge files into the root vault.
- Change Learn capture and research option defaults to resolve the shared vault, with `BRAIN_KNOWLEDGE_ROOT` as an override.
- Add a regression test for the shared-vault default.
- Delete the repository-local knowledge copy and ignore accidental future recreation.
- Run full verification.

### Completion
- Merged Learn raw material, official operator catalog, principles, decision cards, and wiki index updates into the root vault.
- Updated `scripts/capture_learn_material.py` and `wqb/cli.py` to default to the shared vault.
- Removed `BrainWorkflow\knowledge` and added `knowledge/` to `.gitignore`.
- Verification passed: full unittest discovery ran 170 tests successfully.

## 2026-07-09 Raw Layer Semantics Correction

### Requirement Summary
- Correct the knowledge vault structure after user clarification.
- Store all unprocessed factual source material under the shared vault `raw/` layer.
- Move Learn API captures from `rawmaterial/learn` to `raw/learn`.
- Keep `wiki/` as the compiled knowledge layer.

### Confirmed Details
- `rawmaterial/` is not a desired top-level vault directory.
- `raw/source_index.md` must describe each raw source file, its contents, and how to check updates on the next website refresh.
- Future capture scripts must not recreate `rawmaterial/`.

### Execution Plan
- Move shared vault Learn raw files to `knowledge/raw/learn`.
- Update capture script defaults and compiled wiki source references.
- Update README/source index documentation.
- Add a regression test for Learn capture path semantics.
- Run full verification and push the branch.

### Completion
- Moved shared vault Learn captures to `knowledge/raw/learn` and removed the mistaken `knowledge/rawmaterial` directory.
- Updated `scripts/capture_learn_material.py` so future Learn captures write to the raw layer.
- Added a regression test for Learn capture raw-layer defaults.
- Updated source-index documentation in the shared vault so each raw Learn file has source, contents, update-check, and wiki target notes.

## 2026-07-10 Markdown Raw Source Implementation

### Requirement Summary
- Update the Learn capture workflow so Obsidian-facing raw materials are Markdown.
- Keep exact JSON payloads outside the vault in an ignored cache for deterministic diffs.
- Preserve the shared root vault as the only knowledge base.

### Confirmed Details
- Markdown raw output should live under `knowledge/raw/platform/learn/<capture-date>/`.
- JSON cache should live outside the vault under `docs/knowledge/cache/learn/<capture-date>/`.
- Stage 1 cleanup is not deletion in this task; it is indexing and planning.

### Execution Plan
- Update `scripts/capture_learn_material.py` raw output and cache behavior.
- Update tests for Markdown raw output and cache paths.
- Use the existing captured Learn JSON to generate Markdown raw files.
- Move existing JSON payloads to ignored cache after verifying Markdown files exist.
- Run full tests and push branch.

### Completion
- Updated `scripts/capture_learn_material.py` to write Markdown raw sources under `knowledge/raw/platform/learn/<capture-date>/`.
- Updated the same script to write exact JSON payloads under ignored `docs/knowledge/cache/learn/<capture-date>/`.
- Updated CLI tests for the Markdown raw and JSON cache defaults.
- Converted the existing 2026-07-09 Learn capture into Markdown raw files in the shared vault.

## 2026-07-10 Long-Term Self-Optimizing Workflow Design

### Requirement Summary
- Show the current BrainWorkflow research workflow as implemented and documented.
- Continue designing a long-term maintainable workflow that can improve its own rules, benchmarks, planner decisions, and knowledge base.
- Keep the existing concrete simulation/repair/submit workflow intact; this task focuses on planner, governance, knowledge architecture, and workflow optimization boundaries.

### Confirmed Details
- Start with inspection and design, not implementation changes to alpha simulation logic.
- Use the shared vault at `C:\Users\oytl\Desktop\pyproject\brain\knowledge` as the durable knowledge source.
- The long-term workflow should support incentive-aware planning, activity/data/region selection, and periodic rule refresh.
- Automatic workflow optimization should produce proposed rule changes only; the user decides whether to apply them.
- Scout and Seed must consult the knowledge base, including data semantics, historical data usage, template library, operator semantics, and strategy ideas.
- The data knowledge layer must record all available platform data plus data already used by submitted or simulated strategies, so incentive-aware planning can schedule underused data.
- The template knowledge layer must record operator embeddings, strategy templates, data-type-to-template fit, and periodic low-correlation template innovation or template repair proposals.

### Execution Plan
- Inspect current workflow docs, planner docs, maintenance pages, and Stage 1 inventory.
- Summarize the current workflow and known gaps.
- Propose 2-3 long-term architecture approaches with trade-offs.
- Recommend one maintainable design and wait for user approval before writing a formal spec.

### Completion
- Showed the current workflow: principle-led planner, Scout/Seed/Discovery/Repair/Submit execution chain, raw/wiki knowledge layers, benchmarks, and workflow optimizer backlog.
- Confirmed the automation boundary: the system proposes rule changes, and the user decides whether to apply them.
- Confirmed research workflow startup should consume existing Data Ledger, Template Library, benchmarks, and principles instead of running a large knowledge compile.
- Wrote the formal design spec at `docs/superpowers/specs/2026-07-10-long-term-self-optimizing-brain-workflow-design.md`.

## 2026-07-10 Long-Term Workflow Foundation Implementation Plan

### Requirement Summary
- The user approved the long-term self-optimizing workflow spec.
- Write an implementation plan that breaks the spec into independently testable tasks.
- Keep the first implementation plan focused on foundation infrastructure: Data Ledger, Template Library, knowledge freshness, research scheduler, workflow proposal outputs, and CLI skeletons.

### Confirmed Details
- Do not modify the core simulation/repair/submit execution path in this planning task.
- Do not implement heavy website recapture or full wiki compile automation in this first plan.
- Workflow optimization produces proposals only; the user decides whether accepted rules are applied.

### Execution Plan
- Write the plan under `docs/superpowers/plans/`.
- Self-review for spec coverage, placeholder wording, and type consistency.
- Commit and push the plan document.
- Offer execution choices: subagent-driven or inline execution.

### Completion
- Wrote the implementation plan at `docs/superpowers/plans/2026-07-10-long-term-workflow-foundation-implementation.md`.
- Split the foundation work into eight testable tasks: Data Ledger, Template Library, Knowledge Freshness, Research Scheduler, Workflow Proposals, CLI helpers, example knowledge artifacts, and final verification.
- Verified the plan exists, is linked from README, and has no forbidden planning markers.

## 2026-07-10 Task 3: Knowledge Freshness Checks

### Requirement Summary
- Implement the exact interfaces and values from `.superpowers/sdd/foundation-task-3-brief.md`.
- Own code files: `wqb/knowledge_freshness.py` and `tests/test_knowledge_freshness.py`.
- Follow TDD with a failing test, minimal implementation, focused tests, and the full unit suite.
- Commit with `add knowledge freshness checks` and write the required report.

### Completion
- RED failed with the expected `ModuleNotFoundError` for `wqb.knowledge_freshness`.
- Focused freshness tests passed 3/3.
- Full unit suite passed 180/180.
- Report written to `.superpowers/sdd/foundation-task-3-report.md`.

## 2026-07-10 Long-Term Workflow Foundation Execution

### Requirement Summary
- Execute the approved foundation implementation plan with subagent-driven development.
- Preserve the existing simulation, repair, and submit paths.
- Add Data Ledger, Template Library, freshness checks, scheduler, workflow proposals, CLI helpers, and seed documentation.

### Completion
- Task 1 Data Ledger completed and reviewed clean: `4b5878b`.
- Task 2 Template Library completed and reviewed clean: `cc1d959`.
- Task 3 Knowledge Freshness completed and reviewed clean: `beb8055`.
- Task 4 Research Scheduler completed and reviewed clean after docstring fix: `f61d272`, `59b3952`.
- Task 5 Workflow Proposals completed and reviewed clean: `2840375`.
- Task 6 CLI helpers completed and reviewed clean: `f7cab52`; minor noted for future direct argparse/main coverage.
- Task 7 seed docs completed and reviewed clean: `a362b61`.
- Task 8 verification passed: full suite 187/187, py_compile clean, git diff check clean except CRLF warning on this todo record.

## 2026-07-13 Task 8: Workflow CLI Commands

### Requirement Summary
- Add orchestrator lifecycle commands to the existing positional-command CLI.
- Cover workflow-start argument parsing and workflow-status dispatch, then run focused, CLI, and full test suites.

### Confirmed Details
- Preserve the current `argparse` positional `command` plus global optional-flag shape; do not refactor to subparsers.
- Add all six workflow command names and required global options, including a local candidate status update dispatch when supported.
- Only stage and commit `wqb/cli.py` and `tests/test_cli.py`; do not stage progress artifacts.

### Execution Plan
1. Add failing parsing and dispatch tests.
2. Add orchestrator imports, paths helper, CLI options, and early orchestrator dispatch.
3. Run focused, CLI, and full suites; write report and create the scoped commit.

### Completion
- Added six workflow CLI commands, orchestrator path resolution, and local approved-queue status updates without loading Stage 1 configuration.
- Added parser and dispatch coverage, including an assertion that workflow status does not call `load_config`.
- Verification passed: focused 2/2, CLI 93/93, full suite 280/280.
- Report written to `.superpowers/sdd/task-8-report.md`; only `wqb/cli.py` and `tests/test_cli.py` remain in commit scope.

## 2026-07-13 Second Final Review Fixes

### Requirement Summary
- Fix the six remaining Important findings after commit `90aeb03`: failed-run recovery, semantic state/artifact diagnostics, exact candidate approval validation, crash-idempotent approval retries, Research Record sync state, and deterministic schedule failure handling.
- Preserve the existing research framework and Orchestrator-only ownership of official `run_state.json`.
- Do not stage or commit progress files, `todo.md`, or `milestone.md`.

### Confirmed Details
- Branch is `agent/brainworkflow-phase2`; protected dirty files match the user-provided list.
- The CLI remains compatible with `--candidate-id`; ambiguous duplicate IDs must be rejected instead of silently approving multiple identities.
- No live API, automatic alpha submission, startup knowledge recapture, credentials, or large downloads are needed.

### Execution Plan
1. Inspect the workflow state, approval, Research Record, adapter, and Orchestrator paths against the second-review findings.
2. Add focused failing tests and capture RED evidence for all six findings.
3. Implement minimal fixes, rerunning focused tests after each logical group.
4. Run the required full unit suite, `py_compile`, and branch-wide `git diff --check`.
5. Write `.superpowers/sdd/final-review-fix2-report.md`, commit only scoped source/test/doc files, and record residual concerns.

### Completion
- RED evidence: 45 focused tests produced 23 expected failures and 2 expected errors; a later event-boundary regression test also failed as expected before the final minimal fix.
- GREEN evidence: 46 focused tests and 312 full-discovery tests passed; required `py_compile` and `git diff --check 2711667..HEAD` passed.
- Scoped commit: `869877c harden workflow recovery and approval state`.
- Report: `.superpowers/sdd/final-review-fix2-report.md`.
- Residual concern: live API, simulation, repair, and submission paths were intentionally not executed.
- Scoped commit created: `8cd9a06 add workflow orchestrator cli`.

## 2026-07-13 Third Final Review Fixes

### Requirement Summary
- Fix the six remaining Important findings after commit `869877c`: terminal workflow completion, protected schedule manifest failures, gate-aware approval diagnostics, crash-tolerant artifact writes/reads, abort-time Research Record sync, and candidate-gate order enforcement.
- Preserve the existing research framework and Orchestrator-only ownership of official `run_state.json`.
- Do not stage or commit `.superpowers`, `todo.md`, or `milestone.md` progress files.

### Confirmed Details
- Branch is `agent/brainworkflow-phase2`; protected dirty files match the user-provided list.
- Use focused TDD: capture expected RED failures before production changes, then implement minimal fixes.
- No live API, automatic alpha submission, knowledge recapture, credentials, external downloads, or work outside the approved workspace roots are needed.

### Execution Plan
1. Trace current terminal, schedule, diagnostic, JSONL, abort, and candidate-gate state flows against the six findings.
2. Add focused failing tests for each finding and record RED command output.
3. Implement minimal source changes in the existing Orchestrator/state/record/queue boundaries.
4. Run focused tests, full discovery, required `py_compile`, and `git diff --check 2711667..HEAD`.
5. Write `.superpowers/sdd/final-review-fix3-report.md`, commit only scoped source/test/doc files, and record residual concerns.

### Completion
- RED evidence: 58 focused tests produced 13 expected failures and 6 expected errors; a trailing-JSONL normalization refinement produced one additional expected failure.
- GREEN evidence: 58 focused tests and 324 full-discovery tests passed; required `py_compile` and `git diff --check 2711667..HEAD` passed.
- Scoped commit: `ee562ff complete workflow terminal and recovery hardening`.
- Report: `.superpowers/sdd/final-review-fix3-report.md`.
- Residual concern: live API, simulation, repair, and submission paths were intentionally not executed; broader event/pointer filesystem fault injection remains untested.

## 2026-07-13 Fourth Final Review Fixes

### Requirement Summary
- Fix the three remaining Important findings after commit `ee562ff`: completed-run candidate status updates, candidate-identity-aware retry deduplication, and pre-mutation consistency diagnostics for candidate gate/approval operations.
- Preserve active-run update compatibility, terminal run state, Orchestrator-only official state ownership, and the existing research framework.
- Do not stage or commit `.superpowers`, `todo.md`, or `milestone.md` progress files.

### Confirmed Details
- Branch is `agent/brainworkflow-phase2`; protected dirty files match the user-provided list.
- Add an explicit run/source-run selector to Orchestrator and CLI while retaining active-run behavior when no selector is supplied.
- Use focused TDD and capture RED evidence before modifying production code.
- No live API, automatic submission, knowledge recapture, credentials, external downloads, or work outside approved workspace roots is needed.

### Execution Plan
1. Trace candidate-status selection, per-identity Research Record/event dedupe, and candidate mutation diagnostic flows.
2. Add focused failing tests for completed-run updates, interleaved retries, interrupted approval retries, and diagnostic rejection before writes; capture RED output.
3. Implement minimal source changes within Orchestrator, CLI, Research Record, event, and candidate queue boundaries.
4. Run focused tests, full discovery, required `py_compile`, and `git diff --check 2711667..HEAD`.
5. Write `.superpowers/sdd/final-review-fix4-report.md`, commit only scoped source/test files, and record completion and residual concerns.

### Completion
- RED evidence: 7 focused tests produced 5 expected failures and 2 expected errors for the missing selector, global-tail dedupe, mutation diagnostics, and non-object trailing JSONL handling.
- GREEN evidence: 7 focused regressions, 70 related module tests, and 331 full-discovery tests passed; required `py_compile` and `git diff --check 2711667..HEAD` passed.
- Scoped commit: `9e9366e allow completed run candidate status updates`.
- Report: `.superpowers/sdd/final-review-fix4-report.md`.
- Residual concern: live API, simulation, repair, and submission paths were intentionally not executed; broader filesystem fault injection remains untested.

## 2026-07-13 Sixth Final Review Fixes

### Requirement Summary
- Fix the three remaining Important findings after commit `e5a366b`: interrupted workflow-event tail append recovery, canonical active-run discovery validation, and run-bound artifact identity diagnostics before candidate status mutation.
- Preserve the existing research framework and Orchestrator-only ownership of official `run_state.json`.
- Do not stage or commit `.superpowers`, `todo.md`, or `milestone.md` progress files.

### Confirmed Details
- Branch is `agent/brainworkflow-phase2` at `e5a366b`; protected dirty progress files match the user-provided list.
- Discovery must remain read-only while returning diagnostics for malformed pointers and non-canonical run state.
- Explicit completed-run status updates must reject inconsistent Research Record, approval, queue, or candidate-gate identities without changing artifact bytes.
- Use focused TDD and capture RED evidence before production changes; no live API, automatic submission, knowledge recapture, credentials, downloads, or out-of-workspace operations are required.

### Execution Plan
1. Trace event append/read behavior, active-run pointer/scanned discovery, state diagnostics, and completed-run status mutation boundaries.
2. Add focused failing tests for partial event tails, malformed/out-of-root/mismatched discovery, missing completed-with-warnings Research Records, and cross-run artifact identities; capture RED output.
3. Implement minimal source changes and rerun the focused tests after each finding group.
4. Run related workflow tests, full unittest discovery, required `py_compile`, and `git diff --check 2711667..HEAD`.
5. Write `.superpowers/sdd/final-review-fix6-report.md`, commit only scoped source/test changes, and record completion evidence and residual concerns.

### Completion
- RED evidence: the initial 8 focused methods produced 9 expected failures and 1 expected error; 2 additional directory/run identity tests produced 2 expected failures.
- GREEN evidence: 10 focused regressions, 86 related workflow tests, and 345 full-discovery tests passed; required `py_compile` and post-commit `git diff --check 2711667..HEAD` passed.
- Scoped commit: `8548ad4 harden workflow artifact identity checks`.
- Report: `.superpowers/sdd/final-review-fix6-report.md`.
- Residual concern: live paths and concurrent external JSONL writers were not exercised; the optional first-time `queued -> queued` event suppression remains unchanged to preserve crash-retry reconciliation semantics.

## 2026-07-13 Seventh Final Review Recovery

### Requirement Summary
- Explain why final review repeated in rounds 5, 6, and 7, then continue the SDD completion loop without losing recovery state.
- Keep the existing workflow-state/orchestrator implementation scope unchanged.

### Current State
- Rounds 5, 6, and 7 are final whole-branch reviews because each prior review found remaining Important issues after a fix commit; SDD requires a new whole-branch review after each fix wave.
- Current HEAD is `8548ad4 harden workflow artifact identity checks`.
- Latest verification before the seventh review: 345 full-discovery tests passed, required `py_compile` passed, `git diff --check 2711667..HEAD` passed, and `.superpowers` stayed out of the branch diff.
- Active reviewer: `019f5978-e4c0-7b73-b044-5b1a41623d82`.

### Execution Plan
1. Wait for reviewer `019f5978-e4c0-7b73-b044-5b1a41623d82`.
2. If clean, close the reviewer, rerun final verification, update recovery ledgers, and enter branch finishing.
3. If Critical/Important findings remain, close the reviewer, record all findings, dispatch one fix subagent with the complete list, verify, and re-review.

### Seventh Review Result
- Reviewer returned 0 Critical and 4 Important findings.
- Required fixes:
  1. Prevent user-controlled `created_at` values from escaping `run_root` through `run_id` / `run_dir`.
  2. Prevent `start()` from creating a second run when discovery reports damaged or ambiguous active-run diagnostics.
  3. Make terminal active-pointer cleanup idempotent after terminal state write interruptions.
  4. Make event recovery tolerate truncated UTF-8 multibyte tails.
- Subagent constraint from user: use at most `gpt-5.6-terra` with `high` reasoning for all future subagents; do not exceed that token-consumption class.
- Next action: dispatch one fix subagent for all four findings, require focused RED tests, implementation, full verification, and a scoped commit.

### Seventh Fix Completion
- Fix subagent `019f5f64-db34-78e3-83b5-37f3c6d5023e` completed commit `67176c8 fix workflow recovery review blockers`.
- Verification reported: 49 affected-module tests passed, 350 full-discovery tests passed, required `py_compile` passed, and baseline diff checks passed.
- Follow-up package: `.superpowers/sdd/final-review-2711667..67176c8.diff`.

## 2026-07-14 Eighth Final Review Fixes

### Requirement Summary
- Fix the 1 Critical and 2 Important findings from reviewer `019f5f6d-ae71-7d60-b20b-df3b4a5bd7d7`.
- Preserve the existing Orchestrator design, official state ownership, and no-live-API boundary.
- Use focused RED regressions before production changes.
- Keep all progress/report files unstaged and uncommitted.
- Continue the user-imposed subagent limit: at most `gpt-5.6-terra` with `high` reasoning.

### Findings
1. Critical: canonical active pointer to a directory missing `run_state.json` is misclassified as terminal and can be cleared, allowing a new run to abandon damaged work.
2. Important: candidate hard-pass gate trusts caller-provided `hard_pass=True` instead of durable source-run artifacts.
3. Important: discovery silently picks one active run when multiple nonterminal runs exist; it must report `multiple_active_runs` and require operator repair.
4. Minor recorded for later: `run_manifest.json` could capture selected-option snapshot and scope context.

### Execution Plan
1. Create `.superpowers/sdd/final-review-fix8-brief.md` with exact fixes and verification.
2. Dispatch one fix subagent under the model cap.
3. Inspect report, verify commit and tests, then run another final whole-branch review.

### Completion
- Fix subagent `019f5f74-8cc5-7190-9e5e-44d5462359ab` completed commit `8370c48 harden workflow discovery and candidate evidence`.
- RED covered missing-state pointer, multiple active runs, caller-only hard pass, durable evidence mismatch, and non-empty identity requirements.
- GREEN evidence from report: 70 orchestrator/state tests passed, full discovery 358 tests passed, required `py_compile` passed, and baseline diff checks passed.

## 2026-07-14 Ninth Final Review Fixes

### Requirement Summary
- Fix 3 Important findings from valid reviewer `019f5f81-8b1d-7c81-a71f-a8174491d9d8`.
- Keep subagent model capped at `gpt-5.6-terra` with `high` reasoning.
- Use focused RED regressions before production changes.
- Do not stage or commit progress/report files.

### Findings
1. A valid active pointer can hide a sibling nonterminal run because discovery returns before scanning siblings.
2. Candidate-gate retry can duplicate Research Record `candidate_gate` entries after interruption between Research Record write and gate/state write.
3. Damaged `run_state.json` recovery needs event-based reconstruction or a recoverable checkpoint; this project will use the explicit checkpoint path for maintainability.

### Execution Plan
1. Create `.superpowers/sdd/final-review-fix9-brief.md`.
2. Dispatch one fix subagent under the model cap.
3. Inspect the report, verify commit/test evidence, then re-run final whole-branch review.

### Completion
- Fix subagent `019f5f88-b8bf-75c3-b37d-d1de152f92b8` completed commit `a54ec39 harden workflow checkpoint recovery`.
- RED evidence: 85 focused tests produced 4 expected failures and 2 expected errors.
- GREEN evidence: 86 focused orchestrator/state/research-record tests passed; 365 full-discovery tests passed; required `py_compile` and baseline diff checks passed.
- Report: `.superpowers/sdd/final-review-fix9-report.md`.
- Residual concern: live API, simulation, repair, and submission paths were intentionally not executed.

## 2026-07-14 Tenth Final Review Fixes

### Requirement Summary
- Fix 2 Important findings from reviewer `019f5fa2-9827-7080-9f34-efcfa8eae430`.
- Keep subagent model capped at `gpt-5.6-terra` with `high` reasoning.
- Use focused RED regressions before production changes.
- Do not stage or commit progress/report files.

### Findings
1. Explicit `--source-run-id` completed-run selection must reject symlink/junction or otherwise resolved paths outside `run_root`.
2. Queue action layer must enforce a durable daily limit before recording `api_submitted`.
3. Minor only: candidate-gate identity validation can be made earlier for all approval-required fields.

### Execution Plan
1. Create `.superpowers/sdd/final-review-fix10-brief.md`.
2. Dispatch one fix subagent under the model cap.
3. Inspect report, verify commit/test evidence, then re-run final whole-branch review.

### Completion
- Fix subagent `019f5fa8-a4b6-73a3-ba4b-5f84b31d691e` completed commit `2edfa8a fix final review queue and selector guards`.
- RED evidence: source-run resolved path selector regression and second same-day API-submission regression failed as expected.
- GREEN evidence: 68 focused orchestrator/candidate-queue tests passed; 370 full-discovery tests passed; required `py_compile` and baseline diff checks passed.
- Report: `.superpowers/sdd/final-review-fix10-report.md`.
- Residual concern: selector regression uses an equivalent resolved-path simulation because this Windows environment may not permit unprivileged junction/symlink creation.

### Fix 8 Execution Record
- [completed] Add focused RED regressions for missing active state, durable hard-pass evidence, and ambiguous recovered runs.
- [completed] Apply the minimum discovery and candidate-evidence validation changes without live API use.
- [completed] Run required focused/full verification, write the Fix 8 report, and commit only scoped source/test files.

### Fix 8 Result
- RED: 8 focused methods produced 9 expected assertion failures before production changes.
- GREEN: 8 focused regressions, 70 orchestrator/state tests, and 358 full-discovery tests passed; required `py_compile` passed.
- Scoped commit: `8370c48 harden workflow discovery and candidate evidence`.
- Report: `.superpowers/sdd/final-review-fix8-report.md` remains untracked and unstaged as required.
- Residual concern: live API, simulation, repair, and submission paths were intentionally not executed; the `run_manifest.json` context suggestion remains deferred.
## 2026-07-14 Final Review Fix 11

### Requirement Summary
- Continue the Orchestrator Workflow State SDD final-review loop after reviewer `019f5fb0-56f9-7aa2-97ed-ed57196d0557`.
- New user constraint: every future subagent for this project must use at most `gpt-5.6-terra` with `high` reasoning.

### Confirmed Boundaries
- Do not resume Workflow Console UI work in this loop.
- Do not run live WorldQuant BRAIN API calls, simulations, or alpha submissions.
- Do not rewrite the legacy Stage 1 research workflow; fix only the Orchestrator/queue/state gaps needed for official state ownership.

### Plan
1. Write `.superpowers/sdd/final-review-fix11-brief.md` with the four Important findings and the test/report contract.
2. Dispatch one fixer subagent with `model=gpt-5.6-terra`, `reasoning_effort=high`.
3. Inspect the fixer report and commit, then generate a fresh `2711667..HEAD` final-review package.
4. Re-run whole-branch review and only proceed to final verification if there are no Critical or Important findings.

## 2026-07-14 Final Review Fix 12

### Requirement Summary
- Continue after reviewer `019f5fc6-f4f2-7341-ab25-0bf646c5d9b4` returned 2 Critical and 2 Important findings on `2711667..55f38fb`.
- The same user model budget rule remains active: all future subagents at most `gpt-5.6-terra` with `high` reasoning.

### Blocking Findings
- Event recovery must not reconstruct stale creation-only state when later progress events exist.
- Daily API submission limit must not be reversible by changing `api_submitted` back to another status.
- `workflow-continue` at `candidate_gate` must not silently no-op, and CLI must expose a candidate-approval request path.
- Discovery must scan sibling run directories even when the active pointer target is valid-but-unrecoverable.

### Plan
1. Write `.superpowers/sdd/final-review-fix12-brief.md`.
2. Dispatch one capped fix subagent with the complete findings list.
3. Verify fixer report, commit scope, focused tests, full tests, py_compile, and diff hygiene.
4. Generate a fresh `2711667..HEAD` package and re-run final whole-branch review.

### Execution Record
- [completed] Read `AGENTS.md`, `milestone.md`, and the Fix 12 brief; added focused RED regressions before source changes.
- [completed] Ran the required focused and full non-live verification, wrote the required report, and committed only scoped source/test changes.

### Fix 12 Result
- Commit `15d4f11 fix workflow final review blockers` fixes both Critical and both Important findings.
- RED: the focused suite ran 108 tests with 5 expected failures and 2 expected CLI-dispatch errors before implementation.
- GREEN: focused suite passed 108 tests; full discovery passed 381 tests; required `py_compile`, `git diff --check 2711667..HEAD`, and the `.superpowers` branch-diff check passed.
- Report: `.superpowers/sdd/final-review-fix12-report.md` remains untracked and unstaged as required.
- No live API, simulation, multisimulation, checks, or alpha submissions were run.

### Fix 11 Execution Record
- [completed] Add focused RED regressions for run-root-wide API submission limiting, raw research-record sync failure, post-schedule stage progress, and event-backed damaged-state diagnostics.
- [completed] Implement the minimum Orchestrator, queue, state, event, and non-live adapter fixes within the existing ownership boundaries.
- [completed] Run required focused/full verification, write the Fix 11 report, and commit only scoped source/test changes.

### Fix 11 Result
- RED: 4 focused regressions produced 3 expected assertion failures and 1 expected unhandled raw-sync `OSError` before production changes.
- GREEN: 4 direct regressions, 99 focused workflow tests, and 374 full-discovery tests passed; required `py_compile` and baseline diff checks passed.
- Scoped commit: `55f38fb fix orchestrator final review gaps`.
- Report: `.superpowers/sdd/final-review-fix11-report.md` remains untracked and unstaged as required.
- Residual concern: live API, simulation, multisimulation, checks, and alpha submissions were intentionally not executed.

## 2026-07-14 Final Review Fix 13

### Requirement Summary
- Continue the Orchestrator Workflow State SDD final-review loop after reviewer `019f5fda-2eaa-7c32-b6c6-cee6a60d4db0`.
- Keep all implementation inside the existing Orchestrator/state/queue boundaries.
- Keep subagents capped at `gpt-5.6-terra` with `high` reasoning.

### Blocking Findings
1. Corrupt workflow-event rows can still cause stale state recovery because the recovery path uses the tolerant event reader.
2. Cross-run daily API submission limit can be bypassed by concurrent queue updates.
3. Candidate-gate validation allows incomplete approval identity before writing gate artifacts.
4. Hard-pass evidence can pass with only `candidates.csv`; it must require canonical hard-pass evidence from the run result artifact.

### Plan
1. Create `.superpowers/sdd/final-review-fix13-brief.md`.
2. Dispatch one capped fix subagent.
3. Verify report, commit, focused/full tests, `py_compile`, and branch diff hygiene.
4. Re-run final whole-branch review after the fix.

### Current State
- Fix brief exists at `.superpowers/sdd/final-review-fix13-brief.md`.
- Active fixer: `019f5fe3-3d48-7c60-90e5-7f3a690cd1d2`, dispatched with `gpt-5.6-terra/high`.
- Next step: wait for the fixer, then inspect its report, commit, and verification evidence.

### Pause Record
- User paused the task for shutdown before Fix 13 completed.
- Fixer `019f5fe3-3d48-7c60-90e5-7f3a690cd1d2` timed out once after 600000 ms and was closed while still `running`.
- There is no `.superpowers/sdd/final-review-fix13-report.md` and no Fix 13 commit; HEAD remains `15d4f11 fix workflow final review blockers`.
- Partial unverified RED-test drafts are present in `tests/test_orchestrator.py` and `tests/test_workflow_state.py`.
- Resume by reading `milestone.md`, inspecting the partial test diff, then continuing from `.superpowers/sdd/final-review-fix13-brief.md`. Keep all future subagents at or below `gpt-5.6-terra/high`.

### Resume Record
- User requested continuation.
- Read root and repo milestones, Fix 13 brief, git status/log, and the partial test diff.
- No active subagent remains. Because the main worktree already has partial RED-test drafts in the target files, the controller is taking over locally before spawning any new worker.
- Next step: run the focused RED suite, then implement the minimum fixes for strict event recovery, atomic run-root API submission guard, complete candidate-gate identity validation, and canonical hard-pass evidence.

### Fix 13 Result
- Local takeover completed in commit `d6f51d2 fix workflow final review safety gaps`.
- RED: the four new focused regressions failed for stale event recovery, missing global API claim, incomplete candidate-gate identity validation, and CSV-only hard-pass evidence.
- GREEN: 4 focused regressions passed; related workflow suite passed 109 tests; full discovery passed 385 tests; required `py_compile` and diff hygiene checks passed.
- Report: `.superpowers/sdd/final-review-fix13-report.md`.
- Residual concern: the API submission claim ledger is intentionally conservative if a process reserves a same-day claim and crashes before queue mutation.

### Review State
- Generated final whole-branch review package: `.superpowers/sdd/final-review-2711667..d6f51d2.diff`.
- Active final reviewer: `019f6048-6604-7340-a238-ab9d08248db1`, dispatched with `gpt-5.6-terra/high`.
- Next step: wait for review. Fix any Critical/Important findings before final verification.

### Review Result
- Final reviewer `019f6048-6604-7340-a238-ab9d08248db1` completed and was closed.
- Critical: `_candidate_has_verified_hard_pass()` accepts contradictory duplicate canonical rows because any one passing row is enough.
- Important: API submission lock lacks owner metadata/stale recovery; `sync_research_record()` marks the future `research_record_sync` stage completed during partial pre-approval sync.
- Next step: add RED regressions for these three cases, then implement minimal fixes and re-run focused/full verification.

## 2026-07-14 Fix 14 Continue

### Requirement Summary
- Continue the Orchestrator Workflow State final-review loop after Fix 13 review.
- Do not resume UI work and do not run live API, simulation, multisimulation, checks, or submit.
- Preserve the existing research workflow design; only harden the official Workflow State implementation against the three review blockers.

### Plan
1. Add focused RED tests for duplicate canonical hard-pass rows, stale API submission claim locks, and partial research-record sync preserving future stage state.
2. Implement minimal changes in `candidate_queue.py` and `orchestrator.py`.
3. Run focused tests, related workflow suite, full test discovery, required `py_compile`, and diff hygiene checks.
4. Commit only scoped source/test changes, write a Fix 14 report, and run a fresh whole-branch final review.

### Result
- Commit `048e5c6 fix workflow final review lock and gate edge cases` completed the scoped fix.
- RED: focused regressions failed before implementation for missing stale-lock recovery, premature sync-stage completion, and accepted contradictory canonical hard-pass rows.
- GREEN: 3 focused tests, 110 related workflow tests, and 386 full discovery tests passed; required `py_compile` and diff hygiene checks passed.
- Report: `.superpowers/sdd/final-review-fix14-report.md`.
- Next step: generate `2711667..048e5c6` final-review package and run a capped whole-branch reviewer.

### Review State
- Generated review package: `.superpowers/sdd/final-review-2711667..048e5c6.diff`.
- Active final reviewer: `019f6061-eef9-78e2-8e99-92e34de49072`, model `gpt-5.6-terra/high`.
- Next step: wait for reviewer; Critical/Important findings block completion and must be fixed.

### Review Result
- Reviewer `019f6061-eef9-78e2-8e99-92e34de49072` returned 1 Critical and 1 Important; it has been closed.
- Critical: stale API submission lock recovery can delete a fresh replacement lock due to TOCTOU.
- Important: `workflow-start` has no run-root transaction lock and can create multiple nonterminal runs under concurrent starts.
- Next step: add focused RED regressions for both concurrency cases, then implement minimal lock/start serialization fixes.

## 2026-07-14 Fix 15 Continue

### Requirement Summary
- Continue the Orchestrator Workflow State final-review loop after Fix 14 review.
- Do not resume UI work and do not run live API, simulation, multisimulation, checks, or submit.
- Preserve existing workflow semantics while hardening concurrency around lock recovery and workflow creation.

### Result
- Commit `76530f0 serialize workflow starts and harden lock recovery` completed the scoped fix.
- RED: focused regressions failed before implementation for stale-lock replacement TOCTOU and `workflow-start` ignoring a run-root lock.
- GREEN: 2 focused tests, 112 related workflow tests, and 388 full discovery tests passed; required `py_compile` and diff hygiene checks passed.
- Report: `.superpowers/sdd/final-review-fix15-report.md`.
- Next step: generate `2711667..76530f0` final-review package and run a capped whole-branch reviewer.

### Review State
- Generated review package: `.superpowers/sdd/final-review-2711667..76530f0.diff`.
- Active final reviewer: `019f6074-20fd-7d21-8de9-49b001a32a8c`, model `gpt-5.6-terra/high`.
- Next step: wait for reviewer; Critical/Important findings block completion and must be fixed.

### Review Result
- Reviewer `019f6074-20fd-7d21-8de9-49b001a32a8c` returned 1 Critical and 1 Important; it has been closed.
- Critical: generic stale-lock recovery still has a race after snapshot validation and before rename.
- Important: mutating orchestrator operations after start lack per-run serialization.
- Next step: add focused RED regressions, then implement transition-guarded lock recovery and run-scoped operation locks.

## 2026-07-14 Fix 16 Continue

### Requirement Summary
- Continue the Orchestrator Workflow State final-review loop after Fix 15 review.
- Do not resume UI work and do not run live API, simulation, multisimulation, checks, or submit.
- Preserve existing workflow semantics while hardening generic lock transitions and mutating Orchestrator operations.

### Result
- Commit `030cdc2 guard workflow locks and serialize mutations` completed the scoped fix.
- RED: focused regressions failed before implementation for nested acquisition during stale recovery and ignored mutation locks.
- GREEN: 3 focused tests, 115 related workflow tests, and 391 full discovery tests passed; required `py_compile` and diff hygiene checks passed.
- Report: `.superpowers/sdd/final-review-fix16-report.md`.
- Next step: generate `2711667..030cdc2` final-review package and run a capped whole-branch reviewer.

### Review State
- Generated review package: `.superpowers/sdd/final-review-2711667..030cdc2.diff`.
- Active final reviewer: `019f6082-1dbd-7da1-86e7-94f2f6304602`, model `gpt-5.6-terra/high`.
- Next step: wait for reviewer; Critical/Important findings block completion and must be fixed.

### Review Result
- Reviewer `019f6082-1dbd-7da1-86e7-94f2f6304602` returned 1 Critical and 1 Important; it has been closed.
- Critical: a live JSON lock holder can be evicted by age because the OS guard is not held for the full critical section.
- Important: start/status recovery/diagnostic writes and normal mutations use separate or missing run-root locks.
- Next step: add focused RED regressions, then hold the lock guard for the full critical section and unify workflow writes under one run-root mutation lock.

## 2026-07-14 Fix 17 Continue

### Requirement Summary
- Continue the Orchestrator Workflow State final-review loop after Fix 16 review.
- Do not resume UI work and do not run live API, simulation, multisimulation, checks, or submit.
- Preserve workflow semantics while ensuring lock holders cannot be evicted by stale recovery and all durable workflow writes share one run-root mutation boundary.

### Result
- Commit `52f2e41 hold workflow lock guards across critical sections` completed the scoped fix.
- RED: focused regressions failed before implementation for live stale-holder eviction, start lock mismatch, and status lock bypass.
- GREEN: focused 3 tests passed; related workflow suite 117 tests passed; full discovery 393 tests passed; required `py_compile` and diff hygiene checks passed.
- Report to write next: `.superpowers/sdd/final-review-fix17-report.md`.
- Next step: generate `2711667..52f2e41` final-review package and run a capped whole-branch reviewer.

### Review State
- Report written: `.superpowers/sdd/final-review-fix17-report.md`.
- Generated review package: `.superpowers/sdd/final-review-2711667..52f2e41.diff`.
- Active final reviewer: `019f6094-2992-76a1-b62d-cc14d61d8bad`, model `gpt-5.6-terra/high`.
- Next step: wait for reviewer; Critical/Important findings block final completion.

## 2026-07-14 Fix 18 Continue

### Requirement Summary
- Continue the Orchestrator Workflow State final-review loop after Fix 17 review.
- Fix the two Important findings: strict malformed workflow-event diagnostics and superseded candidate approval/queue invalidation.
- Do not resume UI work and do not run live API, simulation, multisimulation, checks, or submit.

### Plan
1. Verify the findings against current code.
2. Add RED tests for malformed event rows in status/diagnostics and for invalidating a queued candidate when its identity is superseded.
3. Implement the smallest state/orchestrator/queue changes.
4. Run focused/full verification, write report, and commit scoped source/test changes.

### Result
- Commit `fd9ee82 harden workflow diagnostics and approval invalidation` completed the scoped fix.
- RED: workflow event diagnostics missed malformed rows; `WorkflowOrchestrator.invalidate_candidate_approval()` was absent.
- GREEN: focused 4 tests passed; related workflow suite 128 tests passed; full discovery 397 tests passed; required `py_compile` and diff hygiene checks passed.
- Report: `.superpowers/sdd/final-review-fix18-report.md`.
- Next step: generate `2711667..fd9ee82` final-review package and run a capped whole-branch reviewer.

### Review State
- Generated review package: `.superpowers/sdd/final-review-2711667..fd9ee82.diff`.
- Active final reviewer: `019f60a3-f680-7bc3-a353-db669855fe8e`, model `gpt-5.6-terra/high`.
- Next step: wait for reviewer; Critical/Important findings block final completion.

## 2026-07-14 Fix 19 Continue

### Requirement Summary
- Continue the Orchestrator Workflow State final-review loop after Fix 18 review.
- Fix two Important findings: contradictory terminal completed states must not clear the active pointer, and invalidated-row API submission failures must not consume the daily claim.
- Do not resume UI work and do not run live API, simulation, multisimulation, checks, or submit.

### Plan
1. Verify the findings against current code.
2. Add focused RED tests for terminal-state inconsistency and invalidated-row API claim leakage.
3. Implement minimal state/orchestrator changes.
4. Run focused/full verification, write report, and commit scoped source/test changes.

### Result
- Commit `5156f8a protect terminal recovery and API claim ordering` completed the scoped fix.
- RED: contradictory terminal completed state was silently retired; invalidated-row `api_submitted` rejection consumed a daily claim.
- GREEN: focused 2 tests passed; related workflow suite 126 tests passed; full discovery 399 tests passed; required `py_compile` and diff hygiene checks passed.
- Report: `.superpowers/sdd/final-review-fix19-report.md`.
- Next step: generate `2711667..5156f8a` final-review package and run a capped whole-branch reviewer.

### Review State
- Generated review package: `.superpowers/sdd/final-review-2711667..5156f8a.diff`.
- Active final reviewer: `019f60b1-68f9-7ec2-a745-969a091c8836`, model `gpt-5.6-terra/high`.
- Next step: wait for reviewer; Critical/Important findings block final completion.

## 2026-07-14 Fix 20 Continue

### Requirement Summary
- Continue the Orchestrator Workflow State final-review loop after Fix 19 review.
- Fix API claim count/rollback, missing-pointer terminal corruption, and queue contract-key uniqueness.
- Do not resume UI work and do not run live API, simulation, multisimulation, checks, or submit.

### Plan
1. Add focused RED tests for all three findings.
2. Implement minimal state/queue/orchestrator changes.
3. Run focused/full verification, write report, and commit scoped source/test changes.

### Pause
- 用户暂停任务；Fix 20 还没有开始 RED tests 或 implementation。
- 当前 HEAD：`5156f8a protect terminal recovery and API claim ordering`。
- 当前没有未提交源码改动。
- 下次恢复命令：
  `rg -n "claim_api_submission_slot|count_api_submissions_for_date|queue_approved_candidate|_status_identity|active_run_missing|terminal_state" BrainWorkflow/wqb BrainWorkflow/tests`

### Model Limit Update
- 用户取消之前“子代理最高 `gpt-5.6-terra/high`”的临时限制。
- 后续子代理模型不再受该上限约束；按工具默认、任务复杂度和用户新的显式要求选择。
- 当前任务仍暂停在 Fix 20。

## 2026-07-15 Fix 20 Resume

### Requirement Summary
- 用户要求继续任务，并明确不用处理网络问题。
- 继续现有 Final Review Fix 20，不恢复 UI，不运行 live WQB API/simulation/multisimulation/check/repair/submit。
- 必须先写 RED 回归测试，再改生产代码。

### Plan
1. 定位 API claim、queue 去重、terminal discovery 相关代码和测试。
2. 添加 focused RED regressions 覆盖 reviewer 的 1 Critical + 2 Important。
3. 最小实现修复，运行 focused/full verification，写 report，提交 scoped source/test changes，并重新发起 final review。

### Result
- Commit：`f3edc46 harden candidate queue submission invariants`。
- 修复：API claim 计数与 rollback、queue contract-key 冲突、candidate gate duplicate contract key、missing pointer terminal damage discovery。
- 验证：focused 5 tests、related 92 tests、full 404 tests、`compileall`、diff check 均通过。
- Review package：`.superpowers/sdd/final-review-2711667..f3edc46.diff`。
- Active final reviewer：`019f6523-fd88-7cd1-abc7-512833338f5d`。
- 下一步：等待 reviewer；Critical/Important 必须继续修复。

## 2026-07-15 Fix 21 Review Finding

### Requirement Summary
- Reviewer 返回 0 Critical、1 Important。
- 问题：`discover_active_workflow()` 从 checkpoint 恢复 terminal state 时，后续 `diagnose_state_consistency()` 只读 official `run_state.json`，如果 official 缺失会漏掉 terminal invariant。
- 范围：只修复该 Important；Minor cleanup 暂存以后做。

### Plan
1. 添加 active pointer + checkpoint-only terminal corruption 的 RED regression。
2. 添加 missing pointer + checkpoint-only terminal corruption 的 RED regression。
3. 最小修改 workflow_state，让 terminal consistency diagnostics 能使用已恢复 state。
4. 跑 focused/full verification，写 report，提交并重新 final review。

### Result
- Commit：`1cd24a1 detect recovered terminal checkpoint damage`。
- 修复：`diagnose_state_consistency()` 支持 recovered state override，discovery 的 terminal 分支传入已恢复 state。
- 验证：focused 2 tests、related 104 tests、full 406 tests、`compileall`、diff check 均通过。
- 下一步：生成 `2711667..1cd24a1` final review package 并重新 review。

### Review State
- Review package：`.superpowers/sdd/final-review-2711667..1cd24a1.diff`。
- Active final reviewer：`019f6530-8794-7a92-8ce8-8b59990df03a`。
- 下一步：等待 reviewer；Critical/Important 必须继续修复。

## 2026-07-15 Fix 22 Review Finding

### Requirement Summary
- Reviewer 返回 0 Critical、1 Important。
- 问题：gate 可写入同 `candidate_id` 的多个候选，但 approval/CLI 只按 candidate id 选择，导致 persisted gate 状态不可审批。
- 方案：保留 candidate-id-only approval，request gate 阶段拒绝重复 `candidate_id`。

### Plan
1. 将现有 ambiguous approval 测试改成 gate 阶段 RED regression。
2. 在 `request_candidate_approval()` 写 artifacts 前检查 duplicate candidate IDs。
3. 跑 focused/full verification，写 report，提交并重新 final review。

### Result
- Commit：`618c276 reject ambiguous candidate gate ids`。
- 修复：candidate gate request 在 durable artifacts 写入前拒绝重复 `candidate_id`。
- 验证：focused 1 test、related 172 tests、full 406 tests、`compileall`、diff check 均通过。
- 下一步：生成 `2711667..618c276` final review package 并重新 review。

### Review State
- Review package：`.superpowers/sdd/final-review-2711667..618c276.diff`。
- Active final reviewer：`019f6539-ae9a-76b2-a4ab-50ec1ad62782`。
- 下一步：等待 reviewer；Critical/Important 必须继续修复。

## 2026-07-15 Fix 23 Review Finding

### Requirement Summary
- Reviewer 返回 0 Critical、1 Important。
- 问题：通用 status update/CLI 仍允许 `invalidated`，绕过 dedicated invalidation API 的 reason 与 immutability 语义。
- 方案：`invalidated` 保留为 persisted status，但不再被 generic update 与 CLI `--candidate-status` 接受。

### Plan
1. 添加 queue regression：`manually_submitted -> invalidated` 应被拒绝且不改写 queue。
2. 添加 CLI regression：`workflow-update-candidate-status --candidate-status invalidated` 应被 argparse/CLI 拒绝，不 dispatch 到 Orchestrator。
3. 最小修改 candidate_queue/cli，跑 focused/full verification，写 report，提交并重新 final review。

### Result
- 修复：新增 `STATUS_UPDATE_STATUSES`，通用 queue status update 和 CLI choices 不再接受 `invalidated`。
- RED：focused queue/CLI regressions 先失败，证明旧路径会绕过 dedicated invalidation。
- GREEN：focused 2 tests passed；related queue/CLI/orchestrator 102 tests passed；full discovery 408 tests passed；`compileall`、`git diff --check`、`git diff --check 2711667..HEAD` 通过。
- Report：`skills-and-workflows/.superpowers/sdd/final-review-fix23-report.md`。
- 下一步：提交 scoped source/test changes，生成 `2711667..HEAD` review package 并重新 final review。

### Review State
- Commit：`0ec202e reject generic invalidation status updates`。
- Review package：`.superpowers/sdd/final-review-2711667..0ec202e.diff`。
- Active final reviewer：`019f6545-58de-7ae3-b8f3-292df1d02c2e`。
- 下一步：等待 reviewer；Critical/Important 归零后才能进入最终本地验证和 branch finishing。

## 2026-07-15 Fix 24 Review Findings

### Requirement Summary
- Reviewer `019f6545-58de-7ae3-b8f3-292df1d02c2e` 已完成并关闭。
- Critical：0。
- Important：2，必须修复：
  1. terminal run 后续 candidate status update / invalidation 如果 raw Research Record sync 失败，会留下 `completed` + `research_record_synced=False`，diagnostics 仍可能显示 clean。
  2. `continue_once()` 的 post-schedule adapter 读取本地 artifact 失败时会直接抛异常，未持久化 failed state/event，resume 会重复崩溃。
- Minor：workflow CLI 忽略 config run_root、缺 dedicated invalidation CLI，暂存以后，不混入本轮 Important 修复。

### Plan
1. 添加 RED regression：terminal status update raw sync failure 应持久化 `completed_with_warnings` 或 diagnostic blocker。
2. 添加 RED regression：post-schedule malformed artifact 应写入 failed state 和 `stage_failed` event，而不是让 `workflow-continue` 崩溃。
3. 最小修复 orchestrator/workflow_state，跑 focused/full verification，写 report，提交并重新 final review。

### Result
- 修复：post-schedule adapter 异常现在落盘为 failed state 与 `stage_failed` event；terminal status/invalidation raw sync failure 现在落盘为 `completed_with_warnings`、sync blocker 与 `research_record_sync_warning` event。
- 补充：`terminal_research_record_not_synced` diagnostic 会标记 unsynced terminal；对 `completed_with_warnings` 作为非阻断 warning 处理，避免阻塞新 workflow start。
- RED：post-schedule malformed artifact 与 terminal status sync failure 两条 focused regressions 先失败；warning terminal blocking 回归也先失败。
- GREEN：focused 4 tests passed；related orchestrator/workflow_state/stage_adapter 112 tests passed；full discovery 412 tests passed；`compileall`、`git diff --check`、`git diff --check 2711667..HEAD` 通过。
- Report：`skills-and-workflows/.superpowers/sdd/final-review-fix24-report.md`。
- 下一步：提交 scoped source/test changes，生成 `2711667..HEAD` review package 并重新 final review。

### Review State
- Commit：`8a7af4b persist workflow warning and stage failures`。
- Review package：`.superpowers/sdd/final-review-2711667..8a7af4b.diff`。
- Active final reviewer：`019f6555-4306-7921-857b-beb7e5a9612c`。
- 下一步：等待 reviewer；Critical/Important 归零后进入最终本地验证和 branch finishing。

## 2026-07-15 Fix 25 Review Finding

### Requirement Summary
- Reviewer `019f6555-4306-7921-857b-beb7e5a9612c` 已完成并关闭。
- Critical：0。
- Important：1，必须修复：Fix 24 的 warning terminal 在 discovery 中不阻塞新 start，但 `_reject_inconsistent_candidate_mutation()` 仍把 `terminal_research_record_not_synced` 当阻断，导致后续 terminal candidate status/invalidation 无法重试 raw sync。
- Minor：successful terminal retry 是否清理历史 warning metadata 先记录，不混入本轮。

### Plan
1. 添加 RED regression：status update raw sync warning 后，后续 status update 应允许执行并重试 raw sync。
2. 添加 RED regression：invalidation raw sync warning 后，后续可允许非重复 Orchestrator-owned mutation 或至少共享同一 warning diagnostic filter。
3. 将 intentional warning terminal diagnostic filter 抽成共享函数，并在 discovery 与 candidate mutation validation 同时使用；只对带 research sync warning evidence 的 `completed_with_warnings` 放行。
4. 跑 focused/full verification，写 report，提交并重新 final review。

### Result
- 修复：`blocking_terminal_issues()` 现在作为 workflow_state 共享函数，同时用于 discovery 和 candidate mutation validation。
- 收紧：只有 `completed_with_warnings`、`research_record_synced=False`、complete stage 指针、`research_record_sync` completed 且有 blocker/evidence 的状态，才把 `terminal_research_record_not_synced` 视为非阻断 warning。
- RED：warning terminal 后续 status retry 与 invalidation retry 两条 focused regressions 先失败。
- GREEN：focused 3 tests passed；related orchestrator/workflow_state 111 tests passed；full discovery 415 tests passed；`compileall`、`git diff --check`、`git diff --check 2711667..HEAD` 通过。
- Report：`skills-and-workflows/.superpowers/sdd/final-review-fix25-report.md`。
- 下一步：提交 scoped source/test changes，生成 `2711667..HEAD` review package 并重新 final review。

### Review State
- Commit：`402b67c allow warning terminal mutation retries`。
- Review package：`.superpowers/sdd/final-review-2711667..402b67c.diff`。
- Active final reviewer：`019f655f-a5db-7ca2-bbfd-c86b12e3a439`。
- 下一步：等待 reviewer；Critical/Important 归零后进入最终本地验证和 branch finishing。

## 2026-07-15 Fix 26 Review Finding

### Requirement Summary
- Reviewer `019f655f-a5db-7ca2-bbfd-c86b12e3a439` 已完成并关闭。
- Critical：0。
- Important：1，必须修复：warning terminal retry 成功后只设置 `research_record_synced=True`，但 `research_record_sync` stage 仍保留旧 blocker/local evidence，且没有追加 `research_record_synced` success event。
- Minor：提供单独 CLI 重试 completed warning run 的能力暂存以后，不混入本轮。

### Plan
1. 在 status retry 与 invalidation retry 测试中追加 RED 断言：blocker 清空、evidence 指向 raw markdown、写入 `research_record_synced` event。
2. 修改 `_sync_terminal_research_record_or_warn()` 成功路径，捕获 raw_path，更新 stage evidence/blocker，写 synced state 并 append success event。
3. 跑 focused/full verification，写 report，提交并重新 final review。

### Result
- 修复：terminal retry 成功路径现在清理旧 warning blocker/local evidence，写入 raw markdown evidence，并追加 `research_record_synced` event。
- RED：status retry 与 invalidation retry 的新断言先失败，证明旧实现保留了 `OSError: raw vault unavailable` blocker。
- GREEN：focused 2 tests passed；related orchestrator/workflow_state 111 tests passed；full discovery 415 tests passed；`compileall`、`git diff --check`、`git diff --check 2711667..HEAD` 通过。
- Report：`skills-and-workflows/.superpowers/sdd/final-review-fix26-report.md`。
- 下一步：提交 scoped source/test changes，生成 `2711667..HEAD` review package 并重新 final review。

### Review State
- Commit：`67cc66f record terminal sync retry success`。
- Review package：`skills-and-workflows/.superpowers/sdd/final-review-2711667..67cc66f.diff`。
- Active final reviewer：`019f656c-e5ad-74e1-86d2-40ccc8275a27`。
- 下一步：等待 reviewer；Critical/Important 归零后进入最终本地验证和 branch finishing。

## 2026-07-15 Fix 27 Review Findings

### Requirement Summary
- Reviewer `019f656c-e5ad-74e1-86d2-40ccc8275a27` 已完成并关闭。
- Critical：0。
- Important：3，必须修复：
  1. `manually_submitted` candidates 仍可被通用 status update 改回 queued/skipped/api_submitted，破坏 submitted terminal invariant。
  2. `workflow-*` CLI dispatch 未读取 `--config`，导致配置中的 `run_root`/`knowledge_root` 被忽略。
  3. console active workflow summary 未暴露 `diagnose_state_consistency()` 对 running/paused 状态的诊断，且 global approved queue malformed JSONL 会让 dashboard 崩溃。
- Minor：warning terminal retry 成功后 status 仍是 `completed_with_warnings`，先记录为可解释性改进，不混入本轮 Important 修复，除非最终 review 仍要求。

### Plan
1. Queue：先加 RED regressions，确保 `manually_submitted` 只能 idempotent same-status retry，不可回退或转 API submitted，也不创建 API claim。
2. CLI：先加 RED regression，用 custom config 验证 `workflow-status` 等 workflow command 使用 configured run_root/knowledge_root，而不是 parser default。
3. Console：先加 RED regressions，要求 active summary 暴露 consistency diagnostics，并且 malformed approved queue 返回诊断而不是抛异常。
4. 最小修复，跑 focused/full verification，写 report，提交并重新 final review。

### Result
- 修复：`manually_submitted` 与 `api_submitted` 统一为 submitted terminal statuses，仅允许 same-status idempotent retry；Orchestrator 不再对 manual-submitted row 创建 API claim。
- 修复：`workflow-*` CLI dispatch 先读取 config，使用 configured `run_root`/`knowledge_root`，且只有显式 `--knowledge-root` 才覆盖 config。
- 修复：console active workflow summary 合并 `diagnose_state_consistency()`；global approved queue malformed JSONL 返回 `queue_diagnostics`，dashboard 不崩溃。
- RED：5 条 focused regressions 先失败。
- GREEN：focused 5 tests passed；related queue/orchestrator/workflow-CLI/console 116 tests passed；full discovery 418 tests passed；`compileall`、`git diff --check`、`git diff --check 2711667..HEAD` 通过。
- Report：`skills-and-workflows/.superpowers/sdd/final-review-fix27-report.md`。
- 下一步：提交 scoped source/test changes，生成 `2711667..HEAD` review package 并重新 final review。

### Review State
- Commit：`974158a harden workflow queue and console diagnostics`。
- Review package：`skills-and-workflows/.superpowers/sdd/final-review-2711667..974158a.diff`。
- Active final reviewer：`019f657e-1333-7eb3-8600-a7e050c21048`。
- 下一步：等待 reviewer；Critical/Important 归零后进入最终本地验证和 branch finishing。

### Final Review Result
- Reviewer `019f657e-1333-7eb3-8600-a7e050c21048` 已完成并关闭。
- Critical：0；Important：0；Assessment：Ready to merge。
- Minor deferred：
  1. warning terminal raw sync retry 成功后仍显示 `completed_with_warnings`；
  2. no-active `workflow-status` 可能因 `active_run_missing` 显示 `consistent=false`。
- Final local verification：full discovery 418 tests passed；`compileall` passed；`git diff --check` 与 `git diff --check 2711667..HEAD` passed。
- Report：`skills-and-workflows/.superpowers/sdd/final-review-974158a-clean.md`。
- 当前实现分支可进入 integration choice：merge locally / push PR / keep as-is / discard。
## 2026-07-16 Task 2: Compile Data Ledger From Raw Captures

### Requirement Summary
- Add `wqb.data_ledger_compile` and focused tests for compiling raw platform data-field captures into the scheduling ledger.
- Preserve the last valid ledger when temporary ledger validation fails.
- Own and commit only `BrainWorkflow/wqb/data_ledger_compile.py` and `BrainWorkflow/tests/test_data_ledger_compile.py`; keep this progress file uncommitted.

### Plan
1. Add the brief's RED tests and run the focused test command.
2. Implement raw snapshot selection, aggregation, semantic tagging, validation-before-replace, Markdown, and freshness updates.
3. Run focused and relevant verification, self-review the diff, write the required report, and create a scoped commit.
### Result
- RED: focused Task 2 tests failed as expected because `wqb.data_ledger_compile` was missing.
- GREEN: focused 3 tests passed; full discovery 448 tests passed; `compileall` and scoped `git diff --check` passed.
- Implemented temporary JSONL validation before replacing the existing ledger, raw scope aggregation, semantic tags, source metadata, Markdown output, and freshness manifest update.
- Report: `skills-and-workflows/.superpowers/sdd/task-2-report.md`.
- Next step: commit only the two Task 2 source/test files.

## 2026-07-30 Fix6: Official Authority Fail-Closed Ordering

### Requirement Summary
- Fix only the two Required Fixes in `.superpowers/sdd/final-review-knowledge-os-fix6-brief.md`.
- Require v2 run-bound benchmark authority before all classification branches and make official `run_dir` authority take precedence.
- Reject marker-only official schedule directories that lack manifest/start-snapshot authority while preserving marker-free local fallback.
- Use RED/GREEN TDD and avoid all live WQB operations.

### Plan
1. Trace current benchmark and schedule authority resolution.
2. Add and run focused RED regressions for all brief cases.
3. Implement minimal source changes and run focused GREEN tests.
4. Run full non-live discovery, compileall, and diff checks.
5. Write the uncommitted fix6 report and commit only intended source/test changes.

### Result
- RED: early hard-pass, `NO_CHECKS`, non-repairable, injected-rule bypass, valid authority precedence, non-v2 snapshot, and marker-only schedule cases all failed for the expected pre-fix behavior.
- GREEN: 6 targeted tests passed; related benchmark/stage/orchestrator suite passed 112 tests.
- Full verification: 601 non-live tests passed; compileall and `git diff --check` passed.
- Optional `applied_at` minor deferred to keep the fix scoped to the Required Fixes.
- Report: `.superpowers/sdd/final-review-knowledge-os-fix6-report.md` (protected, uncommitted).
- Commit: `2d2b743 fail closed before workflow authority use`.
