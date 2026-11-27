# Live MCP Research

## Use

Open the installed BrainWorkflow application, select a research option and its
scope, then Start. Each Start is a separate task. Stop affects the selected task.
The model plans before simulation; no gate/stage clicks or chat relay are needed.
A task may end with no signal, a technical limitation, an external failure or a
qualified candidate. An ended task is not a promise of successful research.
Final Alpha submission still needs separate explicit authorization.

New Starts freeze live_mcp_version=1. Historical tasks do not silently acquire
this contract, new budget or Resume authority. Unknown submissions retain their
original identities even when the old inventory is retired.

## Tool Chain

| Owner | Inputs and outputs |
| --- | --- |
| console_start | Selected option/scope -> task-owned preplanned configuration. No full-vault capture/compile. |
| retrieval_research_planning | One initial model plan per lane; task rules, Skill, resources and diagnostics -> complete tree and finite Repair recipes. |
| research_mcp / research_tool_service | Task-bound named read tools and local construction/validation; original owner checks, Stop and query accounting. |
| live_research_resources | WQBClient GET/OPTIONS -> bounded resource pages and provenance. Same-query memoization is task-local, not a global inventory. |
| research_skill_resources | Only research Skill/report Markdown -> paged guidance. Text is untrusted data, not execution authority. |
| expression_tools / existing tree compiler | Structural AST and selected returned facts -> expressions/type-known or type-unknown diagnostics, then tree validation. |
| preplanned_start / exploration_eligibility / execution_package | Script-selected facts and plan -> existing source-bound paused group/seal. No raw/machine/wiki lookup for the new mode. |
| existing execution / Seed / Repair | Frozen package and measured results -> routed experiments, bounded deterministic search and checks. No late-model decisions. |
| research_task_report | Terminal task -> one knowledge/researchreport/ Markdown file; no model needed for formatting. |

Planner resource tools: get_datasets, get_datafields, get_operators,
get_documentations, get_documentation_page and get_platform_setting_options.
read_research_skill reads methods/reports; query exposes contract, compile and
validate. It cannot submit simulations or Alphas. This is a CNHK-compatible
adapter, not the third-party package's full server.

Fields/datasets use the selected instrument/region/delay/universe. Pages contain
at most 50 rows; reported API counts do not prove complete catalog coverage.
Operator pages are filtered locally from one cached read. Defaults: 24 logical
resource reads, no transport retry; query/response/model bounds stay independent.
Authentication and reads use the existing bounded transport. Errors are feedback,
not authority for unlimited retries or invented facts.

Unknown semantics/signatures are not admission gates. Verified syntax, known type
conflicts, tree structure, freezing integrity, Stop, budget, dedup, unknown POST
reconciliation and final-submit authority remain independent. Read-only sandboxing
is not a filesystem path allowlist; research uses the task MCP interface, not
arbitrary shell/network access.

## Storage

knowledge/skills/brain-research contains methods and compact references.
knowledge/researchreport contains complete terminal reports. The user's .obsidian
configuration is not removed. Console choices, decisions and candidate revision
state belong in runs/console_resources, runs/decisions and runs/candidate_evidence,
not a second scientific inventory. Selected source fragments travel with execution
packages. Full temporary GET caches are discarded only after successful sealing;
completed plans can be revalidated from retained selected facts without new reads.

## Skill Maintenance

The existing Compile knowledge action (or python -m wqb.cli compile-knowledge
--knowledge-root <knowledge>) summarizes reports into Skill guidance when the
research Skill exists. It does not recreate raw/wiki/machine. It makes one bounded
Codex task per selected report digest, with no WQB calls or research resume.
No reports means no model call. Completed digests are reused; unknown outcomes
are persisted and never automatically replayed. Lessons cite supplied report paths,
consolidate existing guidance instead of appending duplicate report-set sections,
retain limitations and cannot change code hard rules, budgets, platform facts or
final submission authority. Job state lives under runs/skill_maintenance.

## Verification Boundary

Scoped tests cover a no-inventory plan -> expression -> tree -> sealed paused
group, report compatibility and shared safety regressions. Native acceptance uses
the real EXE transport with offline resource/model doubles. Bounded real metadata
GETs separately validate transport/source format, not economic causality, all
language/parameter behavior or a successful live simulation.
