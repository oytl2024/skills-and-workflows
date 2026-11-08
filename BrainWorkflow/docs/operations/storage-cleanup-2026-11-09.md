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

Pending execution: record actual removed/net bytes, protected hashes, application
health/action consistency and affected regression results, then sync the outcome.
Inventory/run-copy retirement and future automatic retention remain separate work.
