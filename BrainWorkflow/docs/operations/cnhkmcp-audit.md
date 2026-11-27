# CNHK MCP Static Audit

Date: 2026-11-27, Asia/Shanghai.
Purpose: reuse documented integration knowledge without replacing research authority.
Status: publisher distribution inspected as data, not installed, imported or executed.
No platform requests, credentials, research Starts or knowledge publication in this audit.

## Subsequent Authorized Read-Only Probe

After the initial static audit,user approved the live-MCP/Skill target and technical
tool repair. On2026-11-27T07:37:13Z,scripts/probe_cnhkmcp.py used the real MCP stdio
SDK and inspected upstream functions to read104 current operators,18 parsed
settings groups,and expression-language/VECTOR documentation pages. Only3 read
tools were exposed;four resource calls succeeded,with necessary authentication
reused from the existing WQB client in memory. No simulation,Alpha submission,
credential file or global MCP configuration change. This supersedes the initial
static-only status above,not the limitations of the original53-tool package.
Current definitions confirm logical call names and lowercase boolean defaults.
They do not prove complete typed signatures or every parameter domain.

The package entry names a missing main;its __init__ imports absent functions.
The probe loads the hash-verified module directly,not those broken exports.
Isolated SDK1.30 and email-validator are required by this inspected release.
The SDK2.3 trial is unused and can be removed after verified Git sync;do not
delete the working mcp-v1 directory or verified source wheel during this increment.

## Source Identity

- PyPI: https://pypi.org/project/cnhkmcp/4.3.17/
- Release: 4.3.17; wheel size 79,409,792 bytes.
- Wheel SHA256: e2f4473bede44dc1db98223ba669144fd88a057005dbc6642213e0970a756a57.
- Local inspection archive: output/cnhkmcp-audit/cnhkmcp-4.3.17-py3-none-any.whl.
- Declared repository https://github.com/cnhk/cnhkmcp returned 404 during this audit.
- Entry point: cnhkmcp.untracked.platform_functions:main.
- AST inspection finds 53 module-level MCP tool registrations in platform_functions.py.
- The wheel includes old project copies, a Windows EXE, pip caches and a vector database.
  Do not copy the whole wheel into knowledge or adopt these unrelated dependencies.

## Useful Tool Map

| Concern | Tools | Implementation evidence |
| --- | --- | --- |
| Exact research settings | get_platform_setting_options | BrainApiClient method line2682, OPTIONS /simulations |
| Field identity and descriptions | get_datasets, get_datafields | methods1183/1209, GET /data-sets and /data-fields |
| Operator signatures and descriptions | get_operators | method1544, GET /operators |
| Learn documents | get_documentations, get_documentation_page | methods1603/2783, GET /tutorials and /tutorial-pages/{id} |
| Support experience | list_forum_topics, search_specific_forum_fast, search_all_forum_slow, read_forum_post, list_forum_posts_in_topic, list_help_center_articles, get_help_center_article | support API/browser implementation, requires separate support authentication |
| Activities and incentives | get_events, get_pyramid_multipliers, get_user_competitions, get_competition_details, get_competition_agreement | /events, /users/self/activities/pyramid-multipliers, /competitions routes |
| Existing experiment evidence | get_alpha_details, get_alpha_pnl, get_alpha_yearly_stats, get_record_sets, get_record_set_data, get_user_alphas | Alpha/result retrieval; use known IDs and existing request evidence |
| Simulation error recovery | lookINTO_SimError_message | tool4149; GET supplied progress locations, does not prove unknown POST absent |
| Batching reference | create_multi_simulation | tool3884; list payload to POST /simulations; wrapper accepts2..8 expressions |
| Expensive checks | check_correlation, get_submission_check | tools3728/3736; do not replace our full checks or cheap-before-correlation ordering |

The2..8 wrapper constraint is not proof of the complete current platform limit.
Route discovery from third-party code is evidence of implementation, not account eligibility.
No expression-construction/complete-AST-validation MCP tool is registered among these53.
An auxiliary PLY validator exists in bundled skills, separate from the MCP tools.

## Useful Bundled Knowledge

The canonical cnhkmcp/knowledge/ directory contains74 JSON files, including9
operator-category files with102 distinct operator entries. Entries include name,
display signature, description, documentation link and REGULAR/COMBO scope.
Examples cover VECTOR reduction, grouping, change, distributions and transforms.
Documents preserve id/title/lastModified/content/category, but are third-party
redistributed snapshots, not newly captured account-specific platform evidence.
Some inspected documents were last modified in2025; package release date is not
the capture date or proof of current field availability.

## Current Product Comparison

- Current machine/operator_ledger.jsonl has107 rows;0 contain populated structured
  definition.parameters. It is mostly tags/uses/source paths, not a complete
  technical signature table. This observation does not mean the runtime has no
  operator definitions.
- read_direct_resources in wqb/direct_knowledge.py also reads operator facts from
  indexed raw captures and overlays optional published definitions. It preserves
  raw_definition/raw_description. Inspecting only the ledger misses this path.
- Ten bundled operator names are absent from that machine ledger: group_median,
  group_normalize, inst_tvr, left_tail, regression_neut, right_tail, s_log_1p,
  truncate, ts_delta_limit, ts_median. This is not proof they are absent from raw,
  unavailable in the account or usable in every scope.
- Existing wqb/data_catalog.py already uses /data-fields and /operators. Existing
  capture_learn_material.py already supports operator detail and tutorial routes.
- Existing wqb/simulator.py already POSTs list payloads for multisimulation.
  MCP packaging alone does not reduce server interactions or fix duplicate identities.

## Do Not Adopt Unchanged

1. get_datafields hardcodes limit50/offset0 without pagination and does not send
   its theme argument. A partial response cannot become a complete field ledger.
2. Several requests lack explicit network timeouts. Single simulation polling has
   an unbounded while loop; batch polling has attempt caps but no robust total
   network-time budget. Children are processed sequentially.
3. Batch creation does not enter our shared quota, Stop fence, durable dedup or
   unknown-POST reconciliation. Never expose it as a parallel production writer.
4. get_submission_check sets all_passed from correlation_checks alone; this is
   not our baseline-plus-all-submission-check qualification contract.
5. Negative-Sharpe flip advice is heuristic, not proof of an economic reverse
   mechanism; retain predeclared branch direction requirements.
6. The auxiliary PLY validator has a supported-function table and optional
   validOp whitelist. It cannot become an admission whitelist for unknown operators.
7. submit_alpha and forum/config mutation tools are not part of the proposed
   read-only resource integration. Authentication/cookie/config handling requires
   separate inspection before any execution of this third-party client.

## Minimal Proposed Change Map

| Independent module | Proposed treatment |
| --- | --- |
| Platform capture | Reuse verified route knowledge through existing bounded client; optional MCP read-only adapter later |
| Knowledge raw | Preserve original signature/description/doc/scope and actual capture identity; tag imported snapshot as third-party |
| Machine resource projection | Incrementally join raw facts and current rows once; expose compact operator/field cards, not duplicate full inventories |
| AI planning | Read signatures/examples, unknown properties and retrieval diagnostics; unknown semantics remain exploratory |
| Syntax/type/tree tools | Keep existing AST/tree tools; add only verified scoped syntax/signature support, not a wholesale whitelist |
| Execution, Repair, authority | Unchanged; current frozen contracts/shared accounting/dedup/final submission remain script-owned |

Recommended first increment: improve the current read-only resource projection
and targeted official-source capture, not install an unrestricted53-tool server.
Separate raw facts, documented technical contracts, empirical successes/failures
and economic hypotheses. Complete facts reduce avoidable planning errors; they
cannot promise that all unknown combinations pass or that accounting faults vanish.

Pending approval: concrete resource changes, bounded platform reads and any MCP
installation/configuration. Current research task30ad1e34 ended with an unresolved
simulation reservation/identity blocker; this is execution/accounting, not a missing
operator-semantic gate. Reconcile durable request evidence before further POSTs.
