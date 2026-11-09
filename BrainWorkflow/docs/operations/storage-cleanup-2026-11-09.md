# Old Desktop Payload Cleanup

## Approved Boundary

User confirmed returning to surplus-file cleanup after the Nov8 read-only audit.
First collect reproducible desktop payloads, not raw knowledge, research state,
profiles or unretired inventories. This is a file-maintenance operation, not a
workflow/code migration, research resume or model/platform authorization.

Future design requirement recorded separately: each self-contained tree execution
package must retire after completion, retaining compact results and necessary
audit/recovery evidence. No execution-package redesign is implemented here.

## Exact Scope

Root: `BrainWorkflow/output/desktop-application/`.
Keep all of `installed/`, current `20261108-223912-0783/`, and verified rollback
`20261106-113104-7809/`. Their complete file hashes are bound in the private audit.

For each ID below, the ONLY deletion targets are its literal `dist space 中文/`
and `work/` children, never the build root or `source/`:

```text
20261023-095722-9119
20261023-105748-7249
20261023-110338-1094
20261103-142317-8984
20261103-143150-1562
20261103-144244-0670
20261103-145837-8680
20261104-141503-9289
20261104-142807-5366
20261104-232445-7010
20261104-232849-2823
20261104-234500-7080
20261105-193909-3140
20261105-201344-5237
20261105-205410-9288
20261108-222039-2271
```

32 targets, 1,135,244,667 logical bytes before retaining compressed metadata.
Private exact per-file hashes/paths:
`output/desktop-validation/build-cleanup-manifest-20261109.json`;
SHA256 `937daef8e5430b28027d1bc296e1380d71bca696fe78ab24f0c3051e75a7ae87`.
Read-only preparation found no sensitive filenames or links in these targets.

## Recoverability And Execution

- Keep each old staged `source/` in place: do not assume every intermediate
  source state was committed. Preserve root specs/manifests/diagnostics too.
- Before removing `work/`, archive its `.toc/.txt/.html/.json/.log/.spec` files
  losslessly and verify every archived file against its original SHA256.
- Old generated executables are not Git-backed. Only current and rollback
  distributions remain supported rollback payloads; this explicitly retires
  the other executable checkpoints, not their source/proof.
- Commit/push this audit and verify remote equality before deletion. Recheck
  target hashes/containment/links and running-process ownership. Any unexpected
  content, sensitive path, mutation or in-use target blocks deletion.
- Use native PowerShell literal paths only, with a durable per-target receipt.
  Check protected application and old staged-source hashes after collection.
- No run, browser profile, dependency root, raw source, inventory, private config,
  Git history or current application path belongs to this deletion allowlist.

## Acceptance

Batch A completed after audit commit `54183cf` was pushed and remote equality
verified. Removed all 32 allowlisted payload directories: 1,135,244,667 bytes.
Sixteen verified work-metadata archives total 2,290,655 bytes, giving net
reclamation of **1,132,954,012 bytes** (1.13 GB decimal). Old staged-source hashes
and complete current/rollback/installed file hashes are unchanged. The original
production/test digest still matches the passing Nov8 full-suite proof; the
running application's loaded revision remains `78ecda0780...`. No research started.

Private receipts: `output/desktop-validation/build-cleanup-result-20261109.json`
and `storage-cleanup-verification-20261109.json`. Pre-collection 42 documentation
and desktop regressions passed; the same 42 post-collection tests passed in
1.615 seconds after compacting the canonical handoff index to its size limit.

Overall storage retirement is NOT complete. The read-only audit of all three old
inventories validates their original records but returns `audit_only/protected`:
job content validation was not requested, replacement and external-reference
closure are required, shared-writer retirement was not verified. These are not
proof that a current research step needs all three inventories. No plan retirement
or inventory deletion occurred. The 1.15 GB run-local recovery copies and browser
profiles remain outside this batch. Future self-contained tree-package retirement
and automatically triggered artifact retention require separate implementation;
this one-time collection does not claim those mechanisms are already deployed.

## Batch B: Named Old Profile Removal

User explicitly approved permanent deletion of these two potentially sensitive
dedicated profiles on Nov9, after no-process/path checks:

- `brain/runs/desktop/browser`: 1,304 files, 524,510,272 logical bytes.
- `brain/skills-and-workflows/BrainWorkflow/.desktop-launch-smoke-20260923`:
  470 files, 70,623,751 logical bytes.

Both resolved literal directories are inside the workspace; no root/descendant
reparse points were found. Source/config/script/launcher exact-name searches found
no current dependency. A process-only SystemRoot/windir correction made the CIM
command-line inspection work; no non-shell process referenced either target.
Repeat these checks immediately before removal and refuse unexpected changes.

These private profiles are not Git-backed and will not be uploaded or archived.
The named approval accepts permanent loss of their old sessions. This batch does
not include current `runs/desktop/webview2`, general Chrome/Edge profiles,
credentials elsewhere, research evidence, inventory or application binaries.
Commit/push this audit and verify branch equality before literal-path deletion;
run affected desktop/entry regressions and sync the resulting receipt afterward.
Lifecycle implementation remains an independent uncommitted maintenance change.

Batch B completed after audit commit `2c16e792bb64cb5a823c6f4583e1045ea0fefc8e`
matched the remote branch. Both exact directories were removed, reclaiming
**595,134,023 logical bytes**. No process owned either target and no links were
found on the final pre-removal pass. Current WebView2 remains present; installed
EXE SHA256 stayed `3423119e618a2978143562af8292f37f1ab71c3f9921d9c055a20bc48ff864fd`.
Pre/post affected desktop/entry suites both passed 67 tests (13.995s/10.903s).
Private receipt: `output/desktop-validation/named-profile-cleanup-result-20261109.json`;
private audited script: `remove-named-profiles-20261109.ps1` beside it. Neither is
uploaded with session contents. Do not rerun the one-shot deletion script.
Combined Batch A+B net reclamation is **1,728,088,035 bytes** (~1.73 GB decimal).
Old inventories and run-local knowledge recovery copies are still protected.

## Batch C: Recovery Copy Scope (Pending Verification)

User named approval on Nov9 permits removal after verified lossless local archival
of precisely these two expanded copies, including their contained `.obsidian`:

- `brain/runs/20260812T032626000000-b45f98a6/runtime/knowledge_recovery/6889bb348d51206eb531/knowledge`
- `brain/runs/20260812T032626000000-b45f98a6/runtime/knowledge_recovery/8cddada2cc65ce241582/knowledge`

Do not upload private archives. Preserve current `brain/knowledge/.obsidian`,
original recovery receipts, `sources/`, research/POST/check identities and all
accounting. Approval does not bypass owner/reference closure, archive integrity,
no-writer checks, regression acceptance or pre-deletion Git equality. This section
records authorization only: no Batch C archival or collection has occurred yet.

Inventory closure diagnostic: the bounded cold scan finally reached an old
recovery-copy `raw/maintenance/delivery_gates/2026-08-02.json` whose documentary
`evidence_path` names the original vault root. It returned protected after806.859s,
636,616,801 bytes/1,654 owners, not a timeout. This is not proof that a live run uses
the Oct30 inventories. Verify/archive the closed copied histories before repeating
inventory closure; do not exempt arbitrary ancestor paths or discard that report.
Private receipt: `output/desktop-validation/archive-closure-cached-20261109.json`.

Batch C pre-collection evidence: both exact copies passed the complete owner scan
and original 29/29 identity closure, each with184 files (574,345,325 and574,344,053
bytes). A routing root is not a scientific input: verified exited Console jobs,
cancelled Start CAS owner identities and the authenticated shared budget-store
root are projected only in the temporary reference view. Explicit input paths,
unknown active records and all original file hashes remain protected. The full
diagnostic traversed2,755 owners; it is not deletion authorization by itself.
Private receipt: `recovery-copies-budget-owner-audit-20261109.json` in desktop-validation.
Necessary archives remain local. Current vault configuration, research receipts,
raw checks and accounting are excluded from deletion. Final source verification,
Git equality and literal-path collection still precede any removal.

Both local archives are now prepared and round-trip verified: 11,913,917 and
11,913,360 compressed bytes respectively, preserving184 original files each.
Private preparation receipt: `prepared-recovery-history-20261109.json`.
Native literal-path preflight validates each remaining member hash and rejects
unexpected files, links or named live consumers. This is preparation only; the
expanded directories remain until the final collection outcome is recorded.

## Batch D: Superseded Nov9 Build Payloads

After the compatible release passes full verification and Git sync, collect only
`work/` and the literal `dist space 中文/` under these uninstalled build IDs:
`20261109-145647-9895` and `20261109-214018-8504`. Their staged source, manifests,
logs, smoke receipts and build metadata remain. Neither is a current release or
verified rollback: both predate the final legacy-brief compatibility correction.
Keep installed payload, final compatible build `20261109-220044-3881`, and both
previous protected Nov8/Nov6 releases. No profile, configuration or research path
is included. Native collection must bind exact file hashes and reject links,
live owners or source/target drift; outcome is recorded separately.
