# Workflow-First Project Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Signboard-linked architecture viewer default to the real research workflow, with a second software-module view and validated cross-links between them.

**Architecture:** Extend workspace `milestone.md` with workflow-step and transition tables in addition to its current module graph. The parser validates conceptual-to-runtime mappings against `workflow_contract.STAGE_NAMES`; the read-only viewer switches between workflow and module projections. No live runtime state or WQB API enters the project board.

**Tech Stack:** Python 3.12 standard library and unittest; existing Cytoscape.js 3.34.3 bundle; Playwright acceptance using installed Edge.

**Spec:** `docs/superpowers/specs/2026-10-09-workflow-first-project-map-design.md`

## Global Constraints

- Workflow is the default view; modules remain available in the same viewer.
- Scout and Seed both map to `scout_seed`; Discovery maps to actual batch/backtest stages without inventing a persisted `discovery` stage.
- Knowledge maintenance is a separate loop, not an unconditional predecessor to every research run.
- AI checkpoints must not display as completed model work without a recorded attempt; final Alpha submit stays separate and human-authorized.
- Root `milestone.md` owns architecture and root `todo.md` owns tasks/handoffs; preserve existing dirty changes and local historical archives.
- Use only local read-only routes; no live WQB calls, simulations or Alpha submission in this plan.
- All subagents, if any, use reasoning effort `medium` or lower.

## Review Focus

- Missing or renamed actual stage in `workflow_contract.STAGE_NAMES`: fail with a source-line mapping diagnostic, not a misleading diagram (Task 1).
- A workflow step names an absent owner module or evidence file: fail validation; `planned` paths may be explicitly marked missing (Task 1).
- Knowledge maintenance accidentally connected as a mandatory research arrow: reject via contract tests and display it as a side loop (Tasks 2-3).
- Backward Signboard `?module=repair` links: open the module view and preserve selected module after the new default changes (Task 3).
- Mobile and desktop with many steps: selected node, label and detail remain readable; list/keyboard fallback reaches every step (Task 4).

## File Map

- Workspace-root `milestone.md`: add workflow step/transition tables and detail sections, keeping current module tables untouched.
- `wqb/project_architecture.py`: parse and validate the additional workflow projection.
- `wqb/architecture_viewer.py`: continue serving the one validated JSON response and restricted evidence links.
- `management/architecture/{index.html,app.js,style.css}`: two-view navigation and step/module cross-links.
- `management/board/.../000-project-architecture-c5vpa.md` and `management/README.md`: explain workflow-first entry.
- `tests/test_project_architecture.py`, `tests/test_project_entry_docs.py`, `tests/test_architecture_viewer.py`, `scripts/verify_architecture_browser.py`, `scripts/verify_architecture_live.py`: contract and browser acceptance.
- Root `todo.md`: current loop, verification, Console follow-on; no duplicate task ledger.

## Task 1: Workflow contract parser

**Interfaces:** `load_architecture(path: Path, workspace_root: Path) -> dict[str, object]` adds `workflow_steps: list[dict]` and `workflow_edges: list[dict]` while retaining `modules`, `edges`, `updated_at`. `<!-- project-workflow-steps:start/end -->` table columns: `id,name,purpose,status,group,runtime_stages,owner_modules,evidence`. `<!-- project-workflow-edges:start/end -->` columns: `from,to,kind,explanation`. Details use `### step:<id>`. Valid groups: `research`, `knowledge`, `submission`; statuses: `implemented`, `partial`, `planned`, `blocked`, `manual`; edge kinds: `next`, `conditional`, `loop`, `prerequisite`, `manual`. Empty runtime mapping is allowed only for `manual`, `planned` or `knowledge` group. Evidence links use the existing safe reference resolver.

**Files:** Modify `wqb/project_architecture.py`; extend `tests/test_project_architecture.py`.

- [ ] Write failing tests for valid Scout/Seed shared mapping, knowledge side loop, final manual submit, unknown stage/owner/edge, duplicate step, missing evidence and unsafe reference.
- [ ] Run `python -m unittest tests.test_project_architecture -q`; observe failures caused by missing workflow support.
- [ ] Implement the smallest parser/validation extension, using `STAGE_NAMES` from `wqb.workflow_contract` and existing line-aware error conventions.
- [ ] Rerun focused tests; keep existing module graph tests green.

## Task 2: Canonical workflow map in milestone.md

**Interfaces:** The table contains the 10 conceptual research steps from objective through record, plus separate knowledge refresh/compile and a manual final-submit boundary. The approval step maps both `user_approval` and `approved_queue`. Every non-planned step has an existing evidence file and one or more owner module IDs. Conditional edges describe weak discard, near-miss Repair, hard-pass gate and bounded Repair return, never an unconditional straight-line claim. The top overview states that this is design/implementation architecture, not live Alpha status.

**Files:** Modify workspace-root `milestone.md`; extend `tests/test_project_entry_docs.py`.

- [ ] Write failing docs contract tests for exact conceptual step IDs, actual runtime mapping, side-loop isolation, manual final submission and parseable details.
- [ ] Run `python -m unittest tests.test_project_entry_docs -q`; observe failures.
- [ ] Add the human workflow tables and short step details without rewriting existing module records or historical archive.
- [ ] Rerun parser/docs tests and inspect the returned projection for honest `partial`/`manual` statuses.

## Task 3: Workflow-first dual-view interaction

**Interfaces:** `?view=workflow&step=<id>` selects workflow view/node; `?view=modules&module=<id>` selects modules view/node; legacy `?module=<id>` remains valid. A segmented control chooses Workflow/Modules; workflow details link to owner modules; module details link back to supported workflow steps. Search and dependency detail operate on the active view. Graph nodes use stable IDs and text plus color for status. The viewer server allows links only to graph-validated evidence or root todo/milestone.

**Files:** Modify `management/architecture/index.html`, `app.js`, `style.css`, `wqb/architecture_viewer.py`; extend `tests/test_architecture_viewer.py`, `scripts/verify_architecture_browser.py`.

- [ ] Write failing browser tests for default workflow, selected Scout/Seed/Discovery, branch edge detail, knowledge side loop, cross-view navigation and legacy module deep link.
- [ ] Run browser verifier and focused viewer tests; observe failure before UI changes.
- [ ] Implement view switch and one graph renderer for both projections; keep all untrusted detail as text and reuse local Cytoscape bundle.
- [ ] Run browser and viewer tests; inspect screenshots at desktop/mobile widths, adjusting zoom/fit and list fallback until selected labels are readable.

## Task 4: Real entry, documentation and handoff

**Files:** Modify architecture Signboard card, `management/README.md`, `scripts/verify_architecture_live.py`, root `todo.md`; extend tests only where a new invariant needs proof.

- [ ] Add failing live-entry checks: exact Signboard card URL opens Workflow by default, task deep links still open modules, evidence links work, and final submit shows manual authorization.
- [ ] Update card/docs and acceptance script; run actual `management/Open Board.cmd`, then browser acceptance against `127.0.0.1:8766` after restarting the owned viewer so stale code cannot mask results.
- [ ] Run focused tests, full native `python -m unittest discover -s tests -q`, compileall and `git diff --check`; record evidence and any residual limitations in root todo.
- [ ] After verified delivery, continue the already-approved `2026-09-05-desktop-autonomous-runtime.md` plan at E/F, beginning with the whole-flow fake-platform acceptance. Do not silently label the broader Console work complete when only the project map is done.

## Execution note

The feature checkout is heavily dirty and the canonical workspace-root pages sit outside the Git repository. Keep changes scoped, preserve all unrelated edits, and do not commit/push or copy private historical archives into GitHub without separate review. The earlier project-board plan used native in-session execution; this plan may preserve that method after user review.
