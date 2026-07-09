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
