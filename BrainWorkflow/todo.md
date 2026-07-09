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
- After completing the planner implementation and verification, save all WorldQuant BRAIN Learn material except Courses into `knowledge/rawmaterial`, including Documentation and Operators, then compile the durable wiki.

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
- Fetch non-course Learn material through the platform API when credentials are available, store raw material under `knowledge/rawmaterial`, and compile summary wiki pages.

### Completion
- Implemented and committed the read-only `plan-research-options` CLI command after the Task 5 subagent hit an external usage-limit error.
- Implemented and committed the Phase 2 principle/decision wiki pages.
- Captured non-course Learn material into `knowledge/rawmaterial/learn`: Operators, Documentation tutorial pages, FAQs, Videos, Recommended Readings, and search discovery results.
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
