# BrainWorkflow TODO

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
