# Workflow-First Project Map Design

Date: 2026-10-09
Status: proposed for user review
Supersedes only the default graph view in `2026-10-09-project-cognition-board-design.md`; preserves its Signboard entry, read-only local viewer, `milestone.md` architecture ownership, `todo.md` task/handoff ownership, and source/test verification rules.

## Intent

The human should first understand **how research proceeds** and where it currently works or stops. The first project graph showed Python components instead, hiding Scout, Seed, Discovery, checks, approval and knowledge maintenance. The corrected Signboard graph defaults to the human research workflow. A second view exposes software modules, and every workflow step links to its actual runtime stage(s), owner module(s), source, tests, state of implementation and known gap. This is a project architecture map, not live progress for an individual Alpha; the Console continues to own live run status.

## Two views, one architecture source

`milestone.md` retains its validated module and dependency tables. It gains a bounded, parseable workflow-step table and workflow-edge table, followed by one human-readable detail section per step. The viewer reads both from that file. A `Workflow` / `Modules` segmented control switches views without opening another app. Workflow is the default on first and repeat visit; a query parameter may deep-link to a selected step or module. Selecting a workflow step shows its purpose, input/output evidence, conditional next actions, AI/human intervention and linked owner modules. Selecting a module shows the existing code/test/evidence pane plus the workflow steps it supports. Neither view has a second manually maintained status source.

## Workflow semantics and mapping

The conceptual flow follows the long-term research contract while naming the actual persisted stage that currently represents each step. Conceptual steps are not falsely promoted to independent runtime stages.

| Human step | Runtime stage mapping | Boundary |
| --- | --- | --- |
| Research objective and option choice | `objective_selected`, `schedule` | User selects an option card; planner supplies alternatives. |
| Scout | `scout_seed` | Explore data/idea directions with a bounded first batch; source artifacts are durable. |
| Seed | `scout_seed` | Refine a promising structure; Scout and Seed currently share one persisted stage. |
| Discovery / batch construction | `batch_generation` | Generate variants from selected seed or template; distinguish planned from actually simulated. |
| Backtest | `backtest` | Submit/poll bounded simulation work; retain identity and rate-limit evidence. |
| Triage | `triage` | Split weak, repairable and hard-pass outcomes; this is a branch, not an unconditional straight line. |
| Repair | `repair` | Bounded improvements on near misses; may return to backtest/triage, or end by budget. |
| Candidate gate | `candidate_gate` | Only fully checked, hard-pass Alphas may enter candidate review. |
| Human approval and approved queue | `user_approval`, `approved_queue` | Human decision is required. Approval is not Alpha submission. |
| Research record and completion | `research_record_sync`, `complete` | Persist what was tried, learned and decided. |
| Final Alpha submission | No automatic stage in this flow | Separate explicit user authorization and platform action; graph must label this boundary. |

Knowledge maintenance is a separate side loop: platform raw update or accumulated research records -> compile/validate -> wiki/machine ledger -> planner readiness. It is run when requested or when the relevant freshness gate requires it, **not** automatically at every workflow start. AI checkpoints are overlays on high-value judgment points, not a fictional always-running agent: current worker attempts can be persisted, but stage scheduling remains incomplete until the later Console/runtime work. The workflow graph must distinguish `current implementation` from `intended behavior` for both loops.

## Data contract and validation

Workflow rows have stable `step_id`, localized display name, purpose, implementation status (`implemented`, `partial`, `planned`, `blocked`, `manual`), comma-separated `runtime_stages`, comma-separated `owner_modules`, and evidence file paths. Edges have `from`, `to`, `kind` (`next`, `conditional`, `loop`, `prerequisite`, `manual`) and explanation. A side-loop/group field identifies `research`, `knowledge`, or `submission` without pretending that all nodes form one sequence. Each step has a detail section with inputs, outputs, decision rule, human/AI role, failure/budget behavior and known gap. Use short human-readable Markdown; the parser returns plain text and the frontend never injects it as HTML.

Validation rejects duplicate/unknown step IDs, unsupported edge kinds, self-links where no loop is declared, missing owner modules, missing/non-file evidence paths for non-planned steps, and runtime stages not in `wqb.workflow_contract.STAGE_NAMES`. A conceptual step may map to zero research runtime stages only when it is `manual`, `planned`, or in the separate `knowledge` loop; the graph labels that boundary explicitly. Tests assert the Scout/Seed shared mapping, the knowledge side loop, the non-automatic AI boundary and the separate final submit authorization. Breaking a workflow reference must fail the normal architecture check.

## Human interaction and visual behavior

The default workflow graph uses a clear left-to-right research path with conditional branches. The knowledge loop is visually adjacent but not in the primary arrow sequence; submission is beyond a visible human-authorization boundary. Status is conveyed by text plus restrained color. The toolbar contains the two-view segmented control, search, fit and zoom. Selecting a node highlights its immediate route and shows a compact detail pane; selecting an edge explains the transition condition. The module graph remains available unchanged in meaning, but a step/module cross-link takes the user directly to the related node in the other view. Signboard task cards may deep-link to a workflow step or module. On a narrow viewport, the selected node and neighbors are readable and the searchable list offers full keyboard access; the entire graph need not fit at once.

No UI element claims a model ran merely because a step has an AI role, nor claims a strategy was submitted because it passed the candidate gate. Actual per-strategy progress, API errors, budgets and live next actions remain in the Console.

## Migration and acceptance

Add the workflow tables/details to the **current** top-level `milestone.md`, leaving the existing module records and local historical archive intact. Update the architecture parser, viewer and tests in place. Update `management/README.md` and the Signboard architecture card to explain the default workflow and module switch. The root `todo.md` remains the only task/handoff ledger. Do not regenerate or overwrite knowledge-vault records.

Acceptance is a real browser run from the Signboard card URL: workflow view loads by default; clicking Scout, Seed, Discovery, Triage branch, Repair, Candidate gate, human approval, knowledge maintenance and final submit boundary shows accurate owner/stage/evidence; a cross-link switches to the matching software module and back. Desktop/mobile screenshots show nonblank, readable selected nodes with no overlap. Parser tests reject fabricated stage mappings and broken links. The project board stays read-only and makes zero WQB API calls.

## Console follow-on sequence already approved

After this map is verified, resume the approved desktop-autonomous-runtime plan at E/F. First add a single fake-platform acceptance that exercises planned batch, partial completion, 429 recovery, restart, Repair, candidate gate and human approval without live calls. Then simplify daily controls to option choice/start/pause-resume and wire selected durable AI checkpoints, keeping final Alpha submission separately authorized. Finally decide whether browser app-mode meets the user's software expectation or whether packaging is required, and profile/fix realistic-scale responsiveness. Console changes use their own tests and plan updates; this project-map correction must not silently change live research behavior.
