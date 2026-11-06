# Project Cognition Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make the Signboard project board open an interactive, evidence-linked architecture graph while giving AI maintainers two short canonical entry points: `milestone.md` for architecture and `todo.md` for tasks and handoffs.

**Architecture:** Parse a bounded Markdown module/dependency contract in workspace-root `milestone.md` into a validated graph. A read-only localhost viewer renders that graph, and a fixed Signboard card opens it. `todo.md` becomes the sole task/handoff ledger; existing history is archived without loss.

**Tech Stack:** Python standard library and unittest; local HTML/CSS/JavaScript; locally bundled Cytoscape.js 3.34.3, pinned with source URL/license/hash; existing Signboard 1.7.4 Markdown board. No runtime CDN or WQB API.

**Spec:** `docs/superpowers/specs/2026-10-09-project-cognition-board-design.md`

## Global Constraints

- Only bind the viewer to `127.0.0.1`; expose read-only routes and no WQB API calls.
- Preserve historical notes and all pre-existing dirty files; do not erase or reset unrelated work.
- Root `milestone.md` owns architecture; root `todo.md` owns task mainline and every interruption handoff.
- Source/tests remain authoritative; summaries route reading but never waive verification.
- Every subagent explicitly uses reasoning effort `medium` or lower.
- Do not modify the research Console until the project-board work is verified and Console issues have been presented to the user.

## Review Focus

- Port 8766 occupied by an unrelated service: refuse reuse and report the conflict, never send board users to that service (Task 4).
- A Markdown table cell contains `|`, relative `..`, or malformed links: reject invalid architecture data without serving an unsafe file link (Task 1).
- Signboard launches while viewer fails: the board still opens, and the architecture card/viewer error gives an actionable diagnostic (Task 4).
- A module has many edges or a narrow viewport: nodes and detail text stay readable without overlap; list fallback remains usable (Task 3).
- Historical notes mention stale plans or sensitive runtime details: archive locally without turning them into current claims or syncing them into board cards (Task 2).

## File Map

- Workspace-root `milestone.md`: canonical current architecture and bounded module/edge tables.
- Workspace-root `todo.md`: current task/handoff header and preserved history pointer.
- `docs/archive/project-recovery/`: dated historical root/project recovery text, preserved without changing content.
- `wqb/project_architecture.py`: table parser, typed graph projection, validation and safe path resolution.
- `wqb/architecture_viewer.py`: localhost read-only server and health identity.
- `management/architecture/{index.html,app.js,style.css,cytoscape.min.js,LICENSE}`: interactive graph frontend and pinned local vendor asset.
- `management/board/.../Project architecture.md`: persistent Signboard entry card.
- `wqb/signboard_launcher.py`: start/check viewer separately from Signboard opening; keep board usable on viewer failure.
- Root and repository `AGENTS.md`, `management/README.md`, operations docs: read-first and ownership instructions.
- Tests: `tests/test_project_architecture.py`, `tests/test_architecture_viewer.py`, existing `tests/test_signboard_launcher.py`, browser verifier.

## Task 1: Architecture data contract and validation

**Files:** Create `wqb/project_architecture.py`, `tests/test_project_architecture.py`; modify spec only if the exact table grammar needs clarification.

**Interfaces:** `load_architecture(path: Path, workspace_root: Path) -> dict[str, object]` returns `modules`, `edges`, `updated_at`; raises `ArchitectureError` with source line and reason. Module IDs are stable lowercase kebab-case. Table markers are `<!-- project-modules:start/end -->` and `<!-- project-dependencies:start/end -->`; required columns are specified in the parser docstring and tests. Local links must resolve inside workspace; a missing path is allowed only for a `planned` module and is identified as such in the projection.

- [x] Write failing tests for a valid two-module graph, duplicate/unknown IDs, malformed/escaped table cells, path traversal and a missing implemented evidence path.
- [x] Run `python -m unittest tests.test_project_architecture -q`; expect the new tests to fail.
- [x] Implement strict parsing and typed projection; never parse arbitrary Markdown into HTML or trust unvalidated path strings.
- [x] Run the focused tests; expect all to pass. Commit only this task's files if committing is agreed for this dirty checkout.

## Task 2: Canonical documentation migration

**Files:** Modify workspace-root `milestone.md`, `todo.md`, project `todo.md`, repository-root `milestone.md`/`todo.md` where present; create archive docs and `tests/test_project_entry_docs.py`.

**Interfaces:** The root `milestone.md` must parse via Task 1; root `todo.md` begins with `Current mainline` and `Latest handoff` sections including last verification, blocker, next exact action and dirty-file warning. Duplicate project-local entry points link to these root files. Archive files preserve prior recovery text verbatim where possible.

- [x] Inventory all existing recovery/task files and add tests asserting canonical headings, unique root ownership, valid module links and archived-history backlinks.
- [x] Run focused docs tests and expect failures.
- [x] Migrate current architecture only from verified code/docs, mark uncertain modules `partial` or `planned`, move historical material to dated archive, and leave concise root entry pages.
- [x] Run parser and docs tests; compare archived content against pre-migration text; report anything that could not be mapped. Commit this migration separately if agreed.

## Task 3: Interactive architecture viewer

**Files:** Create `management/architecture/index.html`, `app.js`, `style.css`, local Cytoscape.js asset/license; create `tests/test_architecture_viewer.py` frontend fixture and `scripts/verify_architecture_browser.py`.

**Interfaces:** GET `/api/architecture` returns Task 1's graph plus validation diagnostics; frontend uses module IDs for selection and task links. A graph load error renders diagnostics and the module list instead of a blank canvas. No client-side editor or mutation endpoint.

- [x] Pin Cytoscape.js 3.34.3 from the official release; record the actual downloaded SHA256 and license in `management/architecture/README.md`.
- [x] Write failing browser checks: nonblank graph, node click, edge click, search, keyboard/list fallback, status/links, desktop/mobile layout and malformed graph error.
- [x] Implement the frontend with a full-width canvas, stable detail pane, visible focus, fit/zoom and text-labeled status; all navigation links derive from validated paths.
- [x] Run browser checks and inspect desktop/mobile screenshots plus canvas pixel changes; revise any overlap or blank state. Commit this task if agreed.

## Task 4: Local server and Signboard handoff

**Files:** Create `wqb/architecture_viewer.py`; modify `wqb/signboard_launcher.py`, `management/Open Board.cmd`, `management/README.md`; create the Signboard architecture card; extend launcher/viewer tests.

**Interfaces:** `start_viewer(workspace_root: Path, port: int = 8766) -> ViewerStatus` checks `/api/health` with an application identity before reusing a listener; server serves only packaged static assets and validated JSON. The Signboard architecture card contains `http://127.0.0.1:8766/` as a raw URL that Signboard can open. Board launcher reports viewer failure while preserving the existing successful board-opening path.

- [x] Write failing tests for viewer identity, unrelated port occupant, viewer crash, board-only fallback, repeat launch and card URL.
- [x] Run `python -m unittest tests.test_architecture_viewer tests.test_signboard_launcher -q`; expect failures.
- [x] Implement the server/launcher and add the fixed architecture card without rewriting existing task-card content.
- [x] Run focused tests, then double-click the actual CMD and click from Signboard to graph; verify both processes and links, including a restart. Commit if agreed.

## Task 5: AI read-first rule and drift checks

**Files:** Modify workspace-root and repository `AGENTS.md`, `management/README.md`, `docs/operations/architecture-map.md`; extend docs/architecture tests. User-wide AGENTS outside this workspace is excluded until separately authorized.

**Interfaces:** Rules say: read root current architecture and task sections first, then task-relevant source/tests; update `todo.md` for handoffs and `milestone.md` only for architecture changes; repair disagreements found during maintenance. Existing milestone-recovery and Knowledge Readiness rules must be rewritten to point handoff/blocker updates to `todo.md`, not left contradictory.

- [x] Write failing tests that assert both rule files agree on ownership and a broken dependency/path fails the architecture check.
- [x] Run tests and observe failure.
- [x] Update rules/docs and add a single documented architecture-validation command to the normal maintenance checklist.
- [x] Run tests and a cold-read exercise: read only root entry sections, identify the correct module source/test and next action, then verify against code. Commit if agreed.

## Task 6: End-to-end acceptance and Console handoff

**Files:** Update `management/README.md`, root `todo.md`, browser verification script and screenshots/evidence as needed; no Console production edits.

- [x] Run `python -m unittest tests.test_project_architecture tests.test_project_entry_docs tests.test_architecture_viewer tests.test_signboard_launcher -q`, then the full native unittest suite with `SystemRoot`/`windir` set.
- [x] Run `python -m compileall -q wqb tests scripts` and `git diff --check` in the project/repository, recording any pre-existing failures separately.
- [x] Verify actual Signboard -> architecture graph click path, graph node/edge/links, wrong path diagnostic, cold restart and offline behavior; capture desktop/mobile screenshots.
- [x] Read Console review, current implementation and user manual; write a concise, evidence-based Console issue list in `todo.md` and present it to the user for priority alignment. Stop before Console fixes.

## Execution note

This repository is already heavily dirty. Before implementation, review `git status` and preserve every unrelated change. Task commits are optional only if the user approves committing in this checkout; do not stage all files. No live WQB calls or Alpha submissions are part of this plan.
