# Option Start Contract And Pre-Mission Notification Repair

## Approved Boundary

User approved investigating native command150332c6-b615-403d-baa6-1da10952a858,
fixing Start and missing maintenance delivery, offline native validation and PR
integration into the default branch. No platform/model calls or research Start.
Knowledge, credentials and runtime artifacts remain private; no proof renewal.

## Reproduction And Cause

The actual persisted option3 is a theme feasibility card with narrative
candidate_scope, not a region/delay/universe triple. All four planner-produced
cards are high-level goals. application_start_form required display prose to
match an exact-scope regex, whereas the old HTML surface supplied separate scope
controls. Native commands supply only option ID. The resulting ValueError is
returned before register_start/prepare_start, so no mission, job or preflight
notification is created. Command receipt says refused/job_id null, not delivery
failed. The previous acceptance checked available actions, not these real cards.

## Orthogonal Change Map

| Owner | Input / output | Change |
| --- | --- | --- |
| console_start | saved card + nonsecret config -> exact scope or typed refusal | explicit card scope wins; known generic research uses saved configured scope; maintenance-only goals do not become unrelated research |
| console_api | raw state -> displayed options and action revision | expose scope/startability/reason; bind displayed options in revision |
| preflight_notifications | typed pre-mission contract failure -> durable evidence/outbox | reuse event-only channel outside command locks; no mission/authority mutation |
| console_server | Start command -> accepted job or refusal + routed evidence | cover pre-job failures; fast asynchronous delivery, deduplicated |
| frontend | option contract -> selection and immediate feedback | disable maintenance-only cards; show exact range/reason; preserve Start/Stop layout |
| tree/Seed/Repair/Orchestrator | frozen plan/results -> research | unchanged |
| authority/accounting | Stop/budgets/POST/checks -> permission | unchanged |

## Execution Plan

1. RED tests: actual planner prose, exact non-USA override, explicit malformed or
   ambiguous scope never falls back, maintenance-only goals, notification/no job,
   duplicate event/restart, same-command idempotence and Stop independence.
2. Implement narrow resolver and display contract. Do not parse arbitrary prose
   into scope or guess the first ledger scope; configured scope stays explicit.
3. Persist pre-mission contract evidence, route once asynchronously via existing
   notification helper, expose delivery status without model polling.
4. Frontend checks and offline HTTP integration; no real queue during tests.
5. Review, freeze/stage intended inputs, full offline regression; build/smoke and
   install only verified source after Git sync. Inspect loaded app without Start.
6. PR default-branch integration after inspecting remote/main divergence; no force,
   branch switching or implicit merge. Record outcomes in root todo.

## Acceptance

- Exact card scope never becomes configured USA by accident.
- Theme/competition feasibility and capture goals cannot implicitly launch research.
- A backend contract failure cannot vanish as an inline string only; durable
  receipt and one event-only notification exist before any mission.
- Invalid/stale commands and user selection mistakes do not spam maintenance.
- Unknown delivery never automatically repeats; Stop and existing authority stay
  unchanged. The installed version and displayed scope must match tested source.

## Reviewed Verification And Installation Scope

All four review findings were reproduced before fixing: post-revision scope race,
legacy Resume with no cards, completed-prefix outbox starvation and malformed
notification objects. The targeted group passed131 tests/1skip; frontend18 tests,
TypeScript check and production build passed. Actual four saved cards were
projected in an isolated browser at1440/390 widths: one configured-scope research
option and three explicit prerequisites, no overflow/page errors, two commands
captured only by test routes and zero real commands/platform requests.

Frozen Python/test digest for the full run:
`4f22af2a075aa0ad498780fa367f9c3a216492f01013c3accd65a2098f4c0840`.
Full proof remains pending until its immutable receipt reports success.
First full run completed3334 tests/9skips in1333.919s; only the historical
single-startup-thread assertion failed. The original log/failed proof remain.
The updated test checks exactly one startup pass for each of the two independent
outboxes, distinct worker objects and one start per worker, without weakening
deduplication or uncertain-delivery tests. Production code/native revision is
unchanged; a fresh complete suite is required for this changed test contract.
Native build `20261110-093248-7744` and owned GUI/backend/worker smoke passed,
code revision `651ec8b25e18104ac6c3234226c3dfb5cd50291582146aec6dec32fcac9325b4`.
Private evidence stays under `output/desktop-validation/`.

Audited installation has363 old/new files. Only the hashed generated JS name
changes: add `_internal/frontend/dist/assets/index-Vec44rGF.js`, remove exactly
`_internal/frontend/dist/assets/index-JNDWZUc-.js` after verified replacement.
The private install audit binds every old/new member hash. Existing rollback
build230304, current profile/config/knowledge/runs and all research identities
remain. No sensitive deletion is included. Git equality and accepted full proof
precede installation/ordinary obsolete-JS collection; outcome recorded afterward.

Fresh complete acceptance:3334 tests passed/9skips in1328.899s, returncode0,
unchanged code/test digest
`df6b6198991191fafe557ee11fad6f7fdfbe85189218775491bb7f6f3f690b98`.
Proof: `option-start-full-suite-20261110-reviewed.{json,log}` (private output).
The earlier failed run remains separate; no code failures were waived. Existing
Windows subprocess decoding warnings remain in the test log and are not claimed
fixed by this scope. Native production revision651ec8b2 is unchanged by the
startup-test contract update. Installation and default-branch merge follow.

## Installed Outcome

Implementation `c45d4889889fc21d100f549b6c2dbd80e4b79d80` was pushed and
remote equality verified before installation. First copy encountered an old
process file handle; no source/receipt was replaced. After the exact owned
processes exited, the same full-hash audit passed and installation succeeded.
All363 files match the verified staged application, obsolete JS removed; current
profile, knowledge and research paths were not deletion targets. Rollback230304
remains. Loaded revision651ec8b2 and EXE32a8cfd7 match native smoke.

Read-only installed acceptance passed: `start_mode=new`, Start/Stop available,
no blocker; actual option1 shows USA D1 TOP3000 and is startable, options2..4
show independent prerequisites. Mission state hashes unchanged, zero command
POSTs/platform/model/research calls. Receipt `option-start-installed-20261110.json`
is private. This proves the application/control boundary, not live model/platform
availability or successful Alpha production. Old maintenance proofs were not
renewed. Existing draft PR2 is being reused for default-branch publication.

Post-install affected desktop/notification/scope/HTTP/entry regressions:
84 tests passed in21.991s. No tracked private resource paths were found. The
cleanup/install outcome is committed separately before merging PR2; the source
and reviewed3334-case proof remain unchanged.
