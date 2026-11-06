# Knowledge Source Repair And Lifecycle Implementation Plan

> For agentic workers: use superpowers:executing-plans, or approved subagent-driven-development with explicit medium-or-lower reasoning. Root todo.md is the only progress ledger.

**Goal:** Remove measured local source-ingestion and retention defects, then expose remaining real readiness gaps without changing research eligibility policy.

**Architecture:** Extend existing capture extraction, indexes, semantic compilation and cleanup ownership. The user approved a rebuildable sqlite3 field-directory index, not canonical ledger/run migration. Share catalog/inventory generations; retain separately bound jobs/releases/runs. No new framework/server or external dependency.

**Tech stack:** Existing Python312/unittest, JSONL/Markdown, local Console and established offline UI verification.

**Spec:** ../specs/2026-11-04-knowledge-source-repair-and-lifecycle-design.md

## P1: Correct Local Source Consumption

SQLite implementation contract (user confirmed approach and detailed spec):
- Add `wqb/field_source_catalog.py` and isolated `tests/test_field_source_catalog.py` only for derived directory ownership. Store identities/scope, ordinal, offset/length and row digest, not full raw payloads. Key generation by exact source/manifest bytes and schema; parameterized SQL, bounded reads, atomic build and safe read-only open.
- `catalog_field_scan(source, identities, manifest, *, bulk_limits=None, create=False)` returns the existing scan dict or None for an absent/unusable optional cache. It validates original hash/count/current stat and reads selected raw offsets; creates/rebuilds only when explicitly requested by local maintenance. Full-inventory callbacks remain a deliberate full parse, not a claimed SQL-only hit.
- `knowledge_contracts._scan_field_source` consumes an existing verified catalog when no full-row callback is needed. `extract_field_source_batches(..., use_catalog=True)` explicitly prepares it; default False preserves prior opt-in behavior. Incremental `resume_existing=True` is strict, verifies prior receipts and reports cumulative extraction completion separately from platform certification. Preserve v1 receipts and finite query/grid limits.
- RED tests: >2MB source, selected exact scopes, no repeated JSON parse on index hit, bounded reads, changed raw/manifest, cache corruption/rebuild, unsafe paths, missing identities, valid prior-excerpt continuation and unchanged default replay. Keep actual raw/release/run evidence unchanged during initial implementation.

Files: wqb/knowledge_contracts.py, semantic_compilation.py, full_semantic_compile.py, data_ledger_compile.py as needed; tests/test_bulk_field_extracts.py, test_full_semantic_inventory.py and existing source/extraction tests.

- [x] Reproduce the >2MB failure using a real-format multiscope temporary capture and assert exact requested fields can be consumed without enlarging model packs.
- [x] Add RED tests for single-generation streaming, bounded pages, partial/resumed work, no silent prefix-only completion, changed source bytes/counts and unsafe paths.
- [x] Extend existing extractor/resolver; reuse exact identity/source receipts. No unbounded text reads or per-field whole-catalog rescans.
- [x] Preserve existing small-source jobs/readers and test absence of fabricated timing/units/grain, freshness renewal, release publication or model calls.
- [x] Run focused regressions and a bounded actual-vault diagnostic; report direct source-reader failures separately from later semantic gates.

## P2: Index And Nonplatform Metadata

Files: wqb/knowledge_contracts.py, knowledge_freshness.py, knowledge_maintenance.py; existing contract/maintenance/freshness tests.

- [ ] Add RED fixtures for body/full hash disagreement, canonical newline/frontmatter conversion, unindexed verified captures and genuine unexplained content drift.
- [ ] Implement only corroborated local repairs with receipts and unchanged capture dates; keep unexplained selected facts blocked rather than refreshing hashes blindly.
- [x] Test date-only user-note classification: missing platform capture metadata is not global resource failure; required official capture fields remain enforced.
- [ ] Extend maintenance reporting with stage/target/reason/severity/scope and demonstrate unchanged authoritative raw, selected releases and run evidence.

## P3: Shared Inventory And Idempotent Projection

Files: wqb/full_semantic_compile.py, full_semantic_coverage.py, full_semantic_execution.py, knowledge_paths.py and consumers requiring storage compatibility; existing inventory/execution/coverage tests.

- [x] Add RED tests for repeated preparation with changed execution budget but identical catalog bytes; reuse content storage while authority remains distinct.
- [x] Replace repeated embedded source/ledger rows with shared bounded pages and identity/digest locators. Preserve all scopes and complete inventory counts.
- [x] Default reports to compact aggregates/references; provide explicit detailed output without multiplying copies.
- [x] Test selected evidence reconstruction, old-plan reading, interrupted writes, cache validation and stable replay. Do not enable old results via status edits.

## P4: Reference-Aware Compile Cleanup

Files: wqb/knowledge_clean_compile.py, knowledge_maintenance.py and existing cleanup/maintenance tests. Add a narrowly scoped helper only if existing ownership otherwise becomes tangled; no second resource authority.

- [x] Add RED tests for active-release maintenance currently refusing every apply_cleanup request.
- [ ] Implement inventory/current publication/job/run/recovery protection roots, compact retirement of only superseded unexecuted maintenance derivatives and exact allowlisted candidates.
- [ ] Test duplicate generation removal, protected raw/research/results, symlink/junction refusal, publication races, candidate replacement and interrupted cleanup recovery.
- [ ] Integrate cleanup at maintenance completion; repeated unchanged compile must not grow inventories/reports or duplicate current records.
- [ ] Audit actual deletion candidates before writes; verify Git sync first. Do not delete uncertain evidence. Report deferred/failed cleanup honestly.

## P5: Actual Closure And Deployment Handoff

### P4 Execution Detail Confirmed Nov 5

Latest authorization: implement safe retirement, remove migrated legacy copies,
and remove Signboard. Keep one canonical lossless historical object in the new
shared inventory store; do not retain expanded and transitional old copies after
successful migration. No platform/model/research/proof/budget authority follows.

1. Archive primitive (`semantic_inventory_archive.py`, isolated matching tests):
   `prepare_inventory_archive(root, inventory_path, expected_sha256, *, timeout_seconds)`
   returns `{path, sha256, uncompressed_sha256, uncompressed_bytes}` in the existing
   shared store. `verify_inventory_archive(root, ref)` verifies bounded compressed
   and exact decompressed bytes. Deterministic gzip, checked paths, immutable
   publication and no source removal. RED: corruption, changed source, restart,
   bounded decompression, concurrent writer, link/escape and replay.
2. Lifecycle (`knowledge_derivative_lifecycle.py`, existing tests): factor original
   manifest authentication from inventory loading. Implement `plan_guard` and
   `assert_semantic_plan_active`, plus `prepare_semantic_retirement` (archive and
   durable intent, no unlink), `read_retired_semantic_plan` (historical-only), and
   approval/path-bound `apply_semantic_retirement` (idempotent collection/recovery).
   Validate original job references, absent execution, explicit replacement
   identity/scope coverage and reference-owner snapshots. Shared inventories,
   funded/executed/unknown plans and unique evidence remain protected.
3. Admission/readers (`full_semantic_compile/execution/coverage.py`): prepare
   publication and execution loading take the same plan guard; retirement is
   checked before authority or payload recreation. Never reacquire runner locks
   in worker authentication. Top-level reports pin their plan; retired reports
   return verified read-only historical summaries, not current coverage. Reuse
   source/publication locks in fixed order and protect original `owner_plan`.
4. Reference contracts (`knowledge_clean_compile.py`): extend the existing bounded
   scanner with exact authenticated self-owner exclusions and inventory-history
   report classification; retain all frozen/recovery/job references and unsafe
   ancestors. Snapshot validation and streaming JSONL must not lose unknown refs.
5. Signboard: inventory exact exclusive files/dependencies and unique state,
   remove surviving product controls/routes, add absence regressions. Preserve
   Console/desktop and shared AI architecture parsing. Commit/push audit and
   verify equality before literal-path deletion; no secret/config/profile sweep.
6. Integrate and review once stable. Test interruptions before/after archive,
   intent, unlink and completion; active/replayed workers and concurrent refs;
   old inventory lossless readability; unchanged authority/accounting/Stop.
   Full offline suite and loaded package verification, Git sync, then audited
   real cleanup and regression/cleanup sync. Record all retained/blocked targets,
   bytes actually recovered and remaining capture/semantic/deployment gaps.

- [ ] Run fast architecture/root-entry checks after the last handoff edit, then affected suites and one stable full suite with before/after source digests.
- [ ] Validate actual local source consumption, counts, current projection, references, protected raw/release/run identity and idempotent maintenance replay. Measure size/read time; avoid inventing target savings or all-field trust.
- [ ] List remaining semantic gates by actual reason and scope. Bring semantic policy changes, truly missing capture and finite model allowance back for review rather than bypassing them.
- [ ] Confirm no research/API/submit/model-budget or old-run proof changes. Verify loaded Console state and documented next legal action.
- [ ] Commit/push verified implementation without force; audit/execute approved derivative cleanup, run affected regression and synchronize cleanup receipts. Formal EXE activation remains gated on resource acceptance and explicit deployment review, not implicit in this plan.

## Verified Slice And Remaining Closure

Nov5 actual-capture regression found `_normalize_capture` inserting an extra
newline after `render_front_matter` (already newline-terminated), invalidating
the recorded body hash. Preserve the body exactly; a known old one-newline
prefix may be recovered only if removing it matches the pre-existing hash and
identity/tool metadata. Other edits still need a fresh capture. Return before/
after byte hashes, preserve capture time, and revalidate/reindex the actual
bounded capture without new GETs or rewriting expected hashes to fit bytes.
Unknown legacy metadata repair remains separately guarded.

Nov5 follow-up approved and TDD: preserve unobserved identities during sampled
ledger refresh; separate per-field observation from catalog completeness. Keep
failed unbounded-scope invalidation, original dates/usage and all downstream
semantic/timing/type gates. Actual capture: 21 bounded reads, 104 operator rows,
65 USA D1 TOP3000 fields (49 VECTOR/16 MATRIX), positive reported coverage65;
activity/scope validation passed, optional retired multiplier page404 retained.
Capture is partial, zero simulations/models; compile/publish is not implied.
This source follow-up supersedes the prior Console source fingerprint and needs
fresh full regression, package/installed-copy verification before final delivery.

Nov5 execution ruling: reference comparisons use per-owner lexical context and
a bounded 10,000-value memo, preserving hashes, dictionary keys and ancestor
references. Real 200 MB ledger scanning exceeds the obsolete-layout 30-second
budget. Explicit retirement maintenance receives a separate finite 180-second
read budget (2 GiB bound unchanged); ordinary cleanup retains 30 seconds. No
source-age, reference protection, authority or research limit is waived.

P1/P3 and protected obsolete-path cleanup are implemented. Shared inventory
format 3 excludes job IDs; rules/helper fingerprints still bind execution plans,
not copied source content. Default report v2 shares detailed JSONL and returns
compact aggregates. SQLite verifies actual raw date witnesses and physical
record positions, including coordinated cache/checksum alteration regressions.
Uniform epochs need one date witness; mixed epochs retain the full raw date
pass. This deliberately preserves correctness over the fastest possible query.

Fresh reviews reproduced and closed five findings with RED-to-GREEN tests:
cached original dates, cache-dependent ordinals, job-dependent inventory copies,
excluded recovery/event references and unsafe reference ancestors. The first
full suite ran 2,942 tests with one Windows foreign-POST connection error. A
deterministic regression verified that the legacy refusal path did not drain
its bounded body; it now shares the application's bounded refusal handling.
Console targeted regression: 109 tests passed, one skipped. Interrupted and
failed logs/builds are retained as diagnostics, never acceptance evidence.

Stable full suite: 2,943 tests passed, eight skips, 703.688 seconds. Source/test/
catalog digest before and after:
`e87cd30998d4a734bf39d4f05805f38a1b7696dce9981f755c9660dd2d3d70fd`.
Log: `output/desktop-validation/source-lifecycle-verified-full-suite-20261104.log`.
Package: `output/desktop-application/20261104-234500-7080`; self-test and CLI
smoke passed. Isolated packaged backend and desktop/mobile browser checks
passed with source-matching loaded revision
`858b3beed212af61e7bac802b7860ed58bdeb0bf655d38ba2ac266900772b9cc`.
No real roots, credentials, button actions or research were used in that check.

Actual current plan `666c07de` has 88,670 identities and a 182,941,296-byte
inventory (old plan-local files were approximately 693-697 MB). Report JSON is
3,456 bytes; details are shared rather than repeatedly embedded. Zero model
calls. Only 229 identities have verified material; 88,441 remain blocked.
Earlier replay verified unchanged raw/ledger/index/release hashes and zero new
job directories. Subsequent raw date validation took 0.408 seconds for 85,569
catalog rows, retaining the Jul30 date. Health: zero blockers, eleven local-note
warnings; this is not semantic or research readiness.

The plan is NOT fully closed. Authorized Nov5 bounded capture supplies fresh
operator/field/activity raw; it does not renew historical captures or certify
new typed operator definitions. The seven new Learn sources' serializer-prefix
drift is recoverable only by their existing recorded body hashes, preserving
dates. Normalization now uses staged, synced replacement and the shared source
writer guard; collision, disk failure and hardlink regressions protect originals.
The authenticated activity pointer alone is updated in the freshness manifest.
Jul29/30 captures remain over 90 days. New model explanation, publication and
proof renewal need their own authority. General Delay1 MATRIX timing remains a
separately proposed design, not deployed behavior. Nov5 P4 now implements
guarded preparation/collection, lossless archives and historical-only readers;
interruptions, admission and archive-consumption races have local regressions.
Actual-vault reference scans still reach their finite safety limit, so all three
expanded inventories remain protected. No real inventory was archived/retired/
deleted. This retains about 2.1 GB and must not be reported as completed GC or
whole-project research readiness. Current Console acceptance/deployment evidence
belongs in root todo.md; earlier package evidence above is historical only.

Nov6 frozen follow-up acceptance: 3,009 offline tests passed, nine skips,
812.028 seconds. Before/after production/test digest remained
`54b9edd077691bd3fa70cc24e1b8e44cbe7b85c4131b9e379bff19a7b628793a`.
Evidence: `output/desktop-validation/console-delivery-verified-full-suite-20261106.{log,json}`.
Build `20261106-113104-7809` passed self-test and isolated native window,
backend/assets, external workspace/config and profile containment checks with
loaded source `9944984c350f1485579f8862c9bdde867739b4da9aed2882b634f228d3aeee98`.
Frontend typecheck/15 tests and desktop/mobile interaction checks passed. These
checks grant no research authority. Installed-copy outcome is recorded separately
in the cleanup audit; timing generalization and actual inventory collection stay
open under the boundaries above.
