# Workspace Storage Audit

## Scope And Measurement

User approved a read-only audit of the outer `brain/` workspace. No files were
deleted; no research, model, platform request, cleanup job or scheduler was run.
Local audit scripts/reports and this explanation are the only new artifacts.

Inventory: 7,442,531,005 logical bytes (7.44 GB / 6.93 GiB), 44,618 files,
zero read/stat errors. Links/junctions were not followed. These are logical file
sizes, not NTFS allocated or globally deduplicated disk usage; live profiles may
change after measurement. Private JSON evidence is under
`output/desktop-validation/storage-audit-20261108.json` and
`storage-cleanup-evidence-20261108.json`, not intended for Git upload.

## Main Contributors

| Disjoint Area | Decimal Size | Explanation |
| --- | ---: | --- |
| `knowledge/` | 3.376 GB | Machine inventories, reports and captured source catalogs dominate. |
| outer `runs/` | 1.796 GB | 1.149 GB frozen recovery copies; 0.604 GB desktop profiles. |
| product `output/` | 1.797 GB | 1.381 GB desktop packages; 0.300 GB validation; build dependencies. |
| product `frontend/` | 0.332 GB | Almost entirely local development dependencies. |
| everything else | 0.141 GB | Includes Git, source/tests/docs, archive and old launcher smoke. |

Knowledge detail: three expanded old `semantic_jobs/*/inventory.jsonl` files
alone total 2.086 GB; their parent jobs total 2.103 GB. Two newer shared
`semantic_inventories` total 367 MB; machine coverage reports 285 MB; raw
materials 367 MB; canonical data ledger 200 MB; field catalog indexes 53 MB.
The human `wiki/` is only 35,516 bytes across nine files, not the storage cause.
The three old inventories are distinct evidence, not proven byte duplicates;
their safe retirement was explicitly unfinished in previous maintenance audits.

One old run, `20260812T032626000000-b45f98a6`, retains two knowledge recovery
trees, approximately 574.5 MB each. SHA-256 confirms that the 208,766,843-byte
raw field catalog is byte-identical in both trees and the canonical vault;
all three have link count one. The two 208,753,937-byte recovery ledgers also
match each other. This proves duplicate files, not equivalence/unreferenced
status of whole historical recovery trees. `knowledge_recovery.py::_copy_vault`
uses `copytree/copy2`; it preserves full run-local state, not shared blobs.

Desktop output retains 18 timestamped build directories plus the installed app.
Each timestamped build is about 72-76 MB; installed files are 45.7 MB. The build
script creates another timestamped directory without a retention/rotation step.
Validation also retains roughly 19 native smoke profiles, mostly 15.7 MB each.
An additional `.desktop-launch-smoke-20260923` tree is 70.6 MB. Profiles may
contain session information and require separately named deletion approval.

## What Cleanup Actually Exists

1. `knowledge_maintenance.py::run_knowledge_maintenance` defaults to
   `apply_cleanup=False`. Console's explicit knowledge-compile job passes
   `--apply-cleanup` via `console_jobs.py`. This is task-triggered, not a timer.
2. `knowledge_clean_compile.py::plan_obsolete_active_cleanup` targets root-level
   knowledge clutter and an allowlist of old raw/wiki layouts. It is not general
   machine-inventory, build, recovery-snapshot or browser-cache garbage collection.
   Source evidence and sensitive paths are refused; real deletion needs compile
   evidence and reference checks. A clean structure does not imply low disk use.
3. Local knowledge cleanup logs record 22 applied file deletions historically.
   The Oct30 and Nov3 runs were dry runs with zero candidates. This is evidence
   of partial cleanup, not periodic reclamation of today's large artifacts.
4. `knowledge_derivative_lifecycle.py` implements guarded retirement preparation,
   archival/replacement checks and path-approved collection. Production callers
   use its active/retired guards, but prepare/apply retirement has no production
   CLI/Console/maintenance invocation; calls are definitions and tests. No real
   retirement markers/completion receipts were found under canonical machine.
   Earlier audits recorded the reference scan timing out; the three originals
   remain. Do not confuse tested retirement primitives with deployed collection.
5. No built-in retention/periodic purge for desktop packages, validation profiles
   or run-local knowledge copies was found. Recovery explicitly invokes compile
   with cleanup disabled. Knowledge age expiry is not a deletion TTL.

Windows Task Scheduler and Codex automations outside this workspace were not
audited or modified. The conclusion concerns project-owned code and receipts.

## Assessment And Proposed Follow-Up

The cause is artifact lifecycle coverage, not Alpha log volume: repeated full
inventories/copies, repeated packaged dependencies and retained profiles. Prior
maintenance protected historical proof and entire reproducible payloads together,
without an explicit distinction between small durable evidence and large
rebuildable artifacts. The latest version's empty deletion list did not perform
workspace storage governance. This audit is not deletion authorization.

- First define post-build retention: installed app, current accepted distribution,
  one verified rollback distribution, and compact proof/manifests/logs. Keeping
  two full current/rollback build trees plus installed would put about 1.18 GB
  of other package content into an audit candidate set, not prove safe deletion.
- Finish explicit semantic-inventory retirement and expose a formal maintenance
  entry; verify references and archive fidelity before collecting expanded files.
- Introduce reference-counted/content-addressed recovery payload reuse and a
  completed-run retention contract; preserve identities, authority and receipts.
- Separate safe cache cleanup from profile/session deletion. Never blindly purge
  `runs`, raw sources, candidate checks or unsubmitted Alpha evidence by age.
- Integrate approved collection after successful build/knowledge maintenance,
  with dry-run byte estimates, actual removed bytes and visible refusal reasons.

Implementation requires a separate aligned plan/approval. No product source,
installed application, knowledge authority or research state changed here.
