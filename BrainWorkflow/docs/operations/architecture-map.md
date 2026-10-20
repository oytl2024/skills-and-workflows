# BrainWorkflow architecture map

The current, validated module and dependency map is in workspace-root `milestone.md`; the interactive projection is reached through Signboard's Project architecture card. This page explains runtime boundaries and should not become a second module status ledger. Current tasks and handoffs are in workspace-root `todo.md`.

## Workspace Directories

The workspace is `C:/Users/oytl/Desktop/pyproject/brain`. Its existing boundaries are:

```text
brain/
  AGENTS.md                   Workspace safety and collaboration rules
  todo.md                     Sole task, current blocker and handoff ledger
  milestone.md                Current architecture and module responsibilities
  BrainWorkflow.cmd/.vbs      Click-to-launch entry points
  knowledge/
    raw/                      Source materials and original research evidence
    machine/                  Machine ledgers and version-bound resources
    wiki/                     Reusable human-readable experience and cases
  runs/                       Durable research, jobs, recovery and proof evidence
  tools/signboard/            Installed project-board dependency
  archive/                    Related Stage1 history; not active product code
  skills-and-workflows/
    .git/                     Repository history; never workspace scratch
    AGENTS.md                 Repository product and file-placement rules
    BrainWorkflow/
      wqb/                    Runtime, Console, knowledge and research modules
      tests/                  Offline unit and workflow acceptance tests
      scripts/                Capture, verification and developer entry scripts
      configs/                Defaults/examples; no hardcoded credentials
      docs/                   Operations, approved designs/plans and history
      management/             Interactive project-board integration
      output/                 Generated verification artifacts and diagnostics
```

This is the relevant project map, not the full physical tree. On 2026-10-14 the user manually removed unrelated shared skills and the fourteen verified legacy/test paths in manual-cleanup-2026-10-14.md section A; read-only verification confirms they are absent. Agent deletion commands were policy-rejected, so these were not agent deletions. A historical browser smoke profile contains Cookie/session files and is separately protected pending explicit sensitive-deletion approval. Existing related local runs, caches, configuration and evidence must not be deleted solely because they are not shown in this summary. Remaining history/duplicate-run review is not declared complete. Cleanup status is only in root todo.md.

### Human Entry Points

| Need | Entry | Durable state |
| --- | --- | --- |
| Run research | `launch-desktop.cmd` or workspace `BrainWorkflow.vbs` | active run `run_state.json`, `runtime/runtime_control.json`, workflow events and Console jobs |
| View project work | `management/Open Board.cmd` | Markdown cards in `management/board/` |
| Maintain scope and recovery | root `todo.md` and `milestone.md` | task plan and exact resume command |
| Read learned knowledge | workspace `knowledge/wiki/` | compiled experience; `knowledge/raw/` stores source evidence |

## Runtime flow

```text
Desktop launcher -> local Console -> Orchestrator -> persisted run_state
                                      |                  |
                                      |                  +-> stage receipts / checked alpha evidence
                                      +-> workflow driver -> Scout/Seed source batch
                                                            -> triage -> bounded Repair
                                                            -> candidate gate -> user approval
```

The driver honors a durable pause request before a new simulation POST. Existing progress URLs can be polled on recovery; an uncertain POST is not silently repeated. Rate-limit state and retry times are persisted. `workflow-auto-continue` advances deterministic stages, but the final Alpha submission is a separate authorized action. The Console's strategy progress is a read-only projection of local evidence, not a second source of truth.

## Knowledge and AI boundary

The knowledge vault separates raw platform/research evidence from compiled wiki pages and machine-readable ledgers. Readiness checks use source-bound evidence before live research. A knowledge update or compile is a separate maintenance workflow, not an implicit hot-path action on every Console refresh.

AI judgment is currently **not automatically executed** by the research runtime. `wqb/ai_checkpoints.py` can persist an explicitly configured worker attempt and its input/output/status, but stage scheduling and UI invocation remain open work; see `ai-execution-boundary.md`. Do not infer model participation from a passing readiness gate or an AI-looking label.

## Maintenance rule

An operations task follows the current Console state and reports blockers. A maintenance task reproduces a blocker in a test, fixes the contract, updates docs/board/recovery state, and hands back a verified build. Do not copy private strategy expressions, credentials, or platform run artifacts into a remote project board.
