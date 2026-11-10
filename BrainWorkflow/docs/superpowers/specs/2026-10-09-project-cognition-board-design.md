# Project Cognition Board Design

Date: 2026-10-09
Status: proposed for user review; no implementation approved yet

## Intent and boundaries

The project must be understandable without replaying a long Codex conversation. A human starts in Signboard and can navigate an interactive architecture graph to learn what each module does, what exists, what is incomplete, how modules depend on one another, and where the evidence lives. An AI maintainer starts with short, current project and task entry points, then reads only relevant source and tests. The research Console remains the operations surface, not a project-management surface.

This design does not change WorldQuant BRAIN research, simulations, candidate checks, submission authorization, knowledge compilation, or the Console runtime. Console issues are inventoried and discussed with the user only after this project-board work is verified.

## Ownership of durable information

| Artifact | Owns | Does not own |
| --- | --- | --- |
| Workspace `milestone.md` | Current architecture: module IDs, responsibility, capabilities, dependency edges, implementation status, evidence links, key invariants and known architectural gaps | Task queue, session-by-session handoffs, copied runtime status |
| Workspace `todo.md` | Current task mainline, acceptance criteria, blockers, latest verified result, exact next action, and chronological handoffs | A second architecture specification |
| Signboard cards | Human navigation and task discussion, linking to module IDs and todo items | Authoritative implementation status or live Alpha state |
| Interactive graph | Read-only projection of the architecture in `milestone.md` | Manually edited architecture facts |
| Source/tests/runtime artifacts | Behavioral truth and verification evidence | A user-friendly project map by themselves |

The existing project-local `BrainWorkflow/todo.md` and repository-root recovery files are historical inputs, not competing live ledgers. Migration must inventory them, preserve their content in an archive, and point readers to the two workspace-root canonical entry points. No old record is silently discarded.

## Architecture record in milestone.md

The top of the file is a one-screen current architecture overview. It names the system boundaries and links to a bounded machine-parseable section in the same Markdown file. The section contains a module table with stable ID, human name, one-sentence responsibility, status (`implemented`, `partial`, `planned`, `blocked`), relevant code paths, test paths, and evidence path; a dependency table contains `from`, `to`, relation label, and short explanation. Paths are relative to the workspace root. Each module has a short human-readable detail section for capabilities, limits and open gaps, keyed by stable ID.

The parser supports only the documented table format and explicit section markers. Unknown IDs, duplicate IDs, broken local evidence paths, invalid statuses, missing detail sections, and edges to absent modules fail validation with a file/line diagnostic. New paths may be marked `planned` instead of pretending they exist. Architecture status must not be inferred merely from an unchecked task or a passing unit test; each `implemented` claim needs linked code and verification evidence. The current graph is re-read from disk when requested, so stale generated JSON is not a second source of truth.

## Human path: Signboard to interactive graph

`management/Open Board.cmd` remains the double-click entry. It opens the existing Signboard task board and ensures a workspace-local, read-only architecture viewer is running. A persistent `Project architecture` card contains a fixed localhost link to that viewer; task cards refer to module IDs, allowing the viewer to highlight related work. The viewer opens in the default browser when the link is clicked. Signboard's documented Markdown-card and URL behavior is used; the installed third-party binary is not modified.

The viewer binds only to `127.0.0.1`, serves no write endpoint and never reaches the WQB API. Startup checks a health identity before reusing a port; if an unrelated process occupies it, the launcher reports a clear error rather than opening the wrong service. A failed graph validation is visible in the viewer with diagnostics, not an empty canvas. Opening the board must still work if the viewer fails, while the architecture card states what to fix.

The graph has a full-width node/edge canvas, small filter/search toolbar, and a compact detail pane. Node click selects the module, shows responsibility, capability status, gaps, upstream/downstream dependencies, and clickable code/test/docs/task references. Edge click explains the relationship. Search finds module names and capabilities; keyboard focus and a list fallback make the same information reachable without pointer use. It supports fit/zoom and meaningful status colors with text labels, not color alone. The graph is a work-focused project instrument, not a decorative hero. Its layout stays stable when a detail pane opens. A proven graph library may be bundled locally in the implementation plan, pinned to a version, with no CDN requirement at runtime.

## AI entry and recovery rule

The workspace and repository agent rules will direct a maintainer to read the current sections of `milestone.md` and `todo.md` first. It then follows the relevant module references into source, tests and docs. This is a routing rule, never permission to trust an outdated summary over code or skip verification. Any discovered mismatch is repaired in the same maintenance change. The task's final handoff updates only `todo.md`; architecture changes update only the appropriate `milestone.md` module record. The graph's validation runs in the same check.

If a user-wide AGENTS file outside this workspace is desired, its exact path and scope require separate confirmation before editing; the project works using its workspace/repository rules alone.

## Migration and maintenance

1. Inventory current root/project todo, root/repository milestone, architecture map, board cards, and related operations docs before moving content.
2. Build the concise architecture section in root `milestone.md` from verified code/docs; label uncertainty and unimplemented capabilities honestly. Archive historical recovery notes under a dated project documentation path, preserving backlinks.
3. Build the single task mainline and latest handoff at the top of root `todo.md`; retain earlier task/handoff records in an archive with a pointer from the current page. Project-local duplicate entry points link to the canonical files.
4. Add graph parser, validator, read-only viewer, Signboard architecture card, and launcher integration. Use stable module IDs so card links survive title changes.
5. Add the read-first rule and maintenance checklist. A code change touching an architectural contract must update the module record; a status-only task change updates todo. CI/local checks catch invalid links and diagram schema drift.
6. Verify the actual double-click path and browser interaction. Only then present the Console issues and evidence for user prioritization.

## Verification and acceptance

- Unit tests cover table parsing, module IDs, statuses, edges, path resolution, planned-path exceptions, and clear diagnostics.
- Integration tests cover board launcher/viewer health identity, port collision, card link, restart and viewer failure without losing the Signboard board.
- Browser tests click through multiple nodes and an edge, search, keyboard/list fallback, and code/test/task links at desktop and mobile widths; screenshots confirm graph is nonblank, framed and non-overlapping.
- A drift test intentionally breaks one dependency and one evidence path and proves validation fails.
- A cold AI-maintenance read of the two canonical pages must identify the correct relevant files and current next action without reading historical archives or the full repository.
- No live platform calls, simulations or Alpha submissions occur in this development task.

## Deliberately deferred

The viewer is read-only; it does not edit source architecture, drag nodes to persist layout, move Signboard cards, or display live Alpha progress. Signboard remains optional task management; the viewer's primary purpose is understanding system architecture. Console desktop-app interaction issues are gathered after this work and fixed only after a separate user alignment.
