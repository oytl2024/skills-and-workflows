# Knowledge Source Repair And Derived Artifact Lifecycle

Date: 2026-11-04
Status: local maintenance implementation in progress; SQLite approach and detailed contract explicitly confirmed. Acceptance/progress: outer todo.md.
Supersedes only the affected source-ingestion/derived-storage parts of the Oct23 semantic compilation design. Research meaning/eligibility policies are unchanged in this first slice.

## Outcome

Repair local engineering barriers before weakening research gates: large catalog reading, index/body inconsistencies, user-note metadata classification, repeated inventories and uncollected superseded derived files. Reuse raw/machine/wiki and the existing compiler, publication, maintenance and Console boundaries. This slice performs no database migration and creates no agent framework or second source authority.

The subsequently approved SQLite scope is a rebuildable field-directory cache, now implemented and under acceptance. It is not a machine-store migration or an exemption from source validation. Raw/wiki Markdown, source identities, frozen run readers and transactional publication remain unchanged; SQL never becomes a second fact authority.

## Confirmed Evidence

The Nov3 source probe had 298 gap items: 296 local sources above the 2MB read bound and two aged excerpts. Full preparation had 88,441 identities without verified material; these are not independent market-data failures. Two indexed Markdown sources had digest mismatches, three raw captures were unindexed. Eleven health findings concern one user note. These observations do not establish downstream timing/unit/transform eligibility.

## 1. Source Reading

- Separate local catalog I/O from model context. Keep model material/pack/output bounds; do not send whole catalogs to a model or simply enlarge every memory bound.
- Extend the existing verified extraction pipeline in knowledge_contracts.py. Stream a captured generation using bounded lines/pages; retain exact dataset/field/scope and capture-manifest identity. Compute/verify the original digest and counts before publishing certified pages.
- A complete local catalog pass must not silently end after the default small extraction prefix. Persist progress when bounded work must yield; resume from the same source generation and verify that it has not changed. Prefer one source scan per generation over one scan per field/batch.
- Existing jobs may keep small immutable source excerpts. New preparation resolves exact requested rows from the verified catalog/pages, rather than treating the original file size as field ineligibility. Preserve quoted row/source provenance.
- Preserve path/link checks, malformed/duplicate-key JSON rejection and exact raw identities. Source-byte verification does not imply semantic completeness, freshness or platform availability.

## 2. Index And Metadata Repair

### Approved SQLite Approach And Confirmed Detailed Contract

The user selected a rebuildable field-directory index, not a machine-store migration. Use Python's sqlite3 only; no server, new dependency or second fact authority. Store the derived index under `machine/field_catalogs/`. Its generation key binds original capture bytes, capture manifest and index schema, not timestamps, model budget or runtime limits.

Build through a bounded JSONL stream and parameterized SQL transaction, with immutable generation publication and cleanup of only owned temporary build files. Index exact dataset/field/scope, raw byte offset/length, row digest and capture epoch; do not duplicate full raw payloads or turn index metadata into semantic explanations. A damaged index is rejected/rebuilt, never accepted by status alone. Reject links/junctions, unsafe cache paths, malformed records and ambiguous identities.

Queries return a finite identity selection. The source reader seeks selected original rows and verifies their identities, bytes, manifest scope/epoch and current original digest before producing existing bounded excerpt receipts. Freshness, source facts, typed binding and model material limits remain independent. An index hit avoids JSON parsing of unrelated rows; original digest checks still read bytes as needed. Full inventory operations requiring every raw row remain explicitly more expensive, not secretly counted as cache-only queries.

Integrate through the existing local extraction/maintenance entry, preserving old JSONL/Markdown/source-extract readers and frozen receipt reconstruction. Start may consume certified local materials, not implicitly capture or rebuild the entire vault. Keep legacy default behavior where required; an explicit incremental mode skips only verified prior excerpts, reports cumulative completion and never conflates extraction completion with platform coverage. Existing ledger/release/run formats do not migrate. Prove unchanged raw bytes/dates, bounded query memory, constant parsing per generation, cache tamper/rebuild, restart and index-free compatibility before actual-vault use.

- Explain each drift before repair: canonical-body hashing, newline/frontmatter conversion, documented derivation, missing index, or unexplained content change. Do not fix a mismatch by blindly replacing its hash with the current file hash.
- Rebuild current indexes only from corroborated local captures and receipts; preserve capture dates and previous evidence. Never edit frozen run snapshots to make a new index fit.
- Hashes, counts and local paths are mechanically derived. Unknown capture tools/times remain unknown, not fabricated. Record repair provenance using existing receipts.
- Platform captures retain necessary capture/scope contracts. User notes are not platform captures: date-only notes may retain date precision and unknown capture method; missing platform-only metadata becomes a housekeeping warning, not global platform-resource failure.
- Invalid selected official evidence still blocks the corresponding use. A problem in an unrelated note does not make every dataset unusable. Reports expose warning/block scope rather than merely issue_count.

## 3. One Current Projection And Shared Inventory

- machine contains one current resource projection, while immutable run/job inputs preserve the exact versions they consumed. Historical usage must not be lost when scope records are merged.
- Catalog generation identity derives from captured content and normalization contract, not a model budget, runtime cap or unrelated helper edit. Execution authority remains separately bound to its job/plan; content reuse never reuses authority.
- Reuse unchanged inventory pages. Do not embed full raw rows plus full ledger rows in each plan. Plans use compact identity, page/row locator and digest references. Readers reconstruct and validate the selected facts.
- Default coverage reports contain counts, reason codes and references. Detailed target rows are shared or generated on demand, not another full expanded report for every plan.
- Running maintenance twice on unchanged inputs must not add another inventory/report generation or another model task. Prior compatible answers may only be reused through current validation, never by declaring them trusted.

## 4. Fixed Cleanup At Compile Completion

Compile sequence: source update -> canonical projection -> experience compile -> reference assessment -> derived cleanup -> integrity/structure verification -> receipt. Replace the active-release branch's blanket cleanup refusal with this reference-aware operation; an active release is a protection root, not a reason never to collect any derivative.

Classification:

- Duplicate content: one canonical stored object, references reused.
- Superseded derivative: excluded from the current projection; eligible for deletion when not required by protected execution/evidence.
- Old capture date: a freshness property, not deletion permission. Stable-definition age policy changes remain a later explicit decision.
- Research failure: reusable evidence, not disposable clutter.

Protect raw sources, research records/experience, Alpha and check identities, budgets/Stop, submitted/unknown POST evidence, active/recoverable jobs, frozen run inputs and consumed release/source receipts. Never delete secrets or browser data under this feature.

Garbage-collection roots are declared machine references required by a current projection, publication, frozen run, active job or recovery contract. A pathname merely printed in an old diagnostic log is not by itself a permanent retention root. Superseded unexecuted maintenance plans may be made non-executable with a compact retirement receipt before collecting their reproducible inventory/report payloads; preserve identities, source-generation digests and summary counts. Do not apply this retirement to research missions or jobs with unresolved/model/POST outcomes.

Use exact allowlisted paths under owned machine-derived boundaries. Reject links/junctions, changed candidates and uncertain references. Journal cleanup, serialize it against compilation/publication and tolerate interruption. Reference uncertainty blocks that deletion candidate, not unrelated research resources. Failed required cleanup cannot be labelled fully completed; distinguish warnings/deferred cleanup from unsafe source failures.

Real deletion follows verified Git sync and a precise path/reference audit. Migrate readers before removing referenced old storage; retain compatibility or protect the artifact when preservation cannot be proved. No broad age-based recursive removal.

### P4 Detailed Retirement Contract (Nov 5 Confirmed)

The user confirmed read-only retirement and lossless preservation, then approved
deleting migrated old knowledge copies and all Signboard functionality. The
following contract refines section 4; the Orchestrator remains unchanged.

**Preservation choice.** Retire an unexecuted knowledge-compilation plan, never
a research mission. Preserve its immutable plan, job inputs, source identities,
dates, usage and evidence. Before collecting its expanded legacy inventory,
create a lossless, streaming gzip object of its exact original bytes in the new
shared `machine/semantic_inventories/<original-sha>/` store. Verify compressed and uncompressed
hashes and the exact uncompressed byte count. This capsule is historical
evidence, not a current machine projection or new raw authority. A summary-only
receipt is insufficient when original row details cannot be reconstructed.
Keep one canonical historical object, not permanent old-directory backups.
After verified migration collect expanded legacy copies and owned transitional
copies; unique historical bytes remain available from the new store. Reusable
raw/research/recovery evidence is protected, not erased as a legacy copy.

**Eligibility.** Limit version 1 to explicitly selected plan-local inventories:
`machine/semantic_jobs/<plan-key>/inventory.jsonl`. Require authenticated plan,
inventory and job references; integer-zero original/declared model allowances;
zero recorded calls; no execution authority, reservations, worker claims,
results, cancellation/recovery state or unknown files in the owning plan.
Job evidence is verified against its original bound input hashes, not promoted
to current semantic/execution validity. Any uncertain or executed job evidence
protects the candidate. Current shared inventories and all research runs remain
outside the collection allowlist.

The history-preserving capsule does not make an original model owner disposable.
Protect every historical `owner_plan` dependency, including when another plan
reuses a shared job. Worker authentication must not acquire the runner-held
plan/job guard or a publication lock retained across the waiting model call.

**Replacement proof.** The caller names an authenticated replacement plan from
the same vault. Verify that its current inventory contains every old target
identity and exact scope; record both plan/inventory digests and the coverage
comparison. Never infer supersession from mtime, a newest directory, a filename,
equal counts or zero allowance. Coverage is not equivalent economic meaning,
freshness, successful explanation or research eligibility. A missing target or
scope protects the old candidate. Original source-generation references remain
in the historical plan and capsule even when the replacement uses newer facts.

**Coordination.** Preparation, execution admission, retirement and top-level
report publication use this order: owning plan execution guard -> sorted
referenced-job guards during retirement commit -> semantic publication lock ->
source-index guard when needed. No inverse acquisition. Retirement acquires job
guards only after compression, with bounded waits, so shared evidence cannot
change during final assessment; it never deletes or retires the shared jobs.
The plan guard pins a reader/executor; publication locks cover only short
admission/reference/commit sections, not compression or model/network work.
Nested worker and historical-owner authentication never reacquires its parent's
plan/job guards. Executed/original-owner plans remain ineligible and protected;
no new pin registry or global research lock is introduced. Execution must recheck retirement while
holding the plan guard, before loading inventory or creating authority. A retired
key cannot be prepared again to resurrect its original execution. Shared jobs
belonging to other plans are never deleted or silently retired.

**Reference assessment.** Under the participating guards, inspect declared
current publication, frozen-run, model-job, source-index and recovery reference
contracts. Exclude only the candidate's own authenticated plan/transaction
records, not generic report filenames or run JSONL. Recheck owner snapshots
before commit. Unsafe paths, unsupported writers, incomplete scans, changed
references and unresolved outcomes protect that candidate. Diagnostic paths do
not automatically become permanent roots. Audit results alone grant no deletion
authority, and uncertainty must not create a global research-readiness failure.

Coverage reports explicitly store `inventory_ref`; do not inherit the general
cleanup helper's blanket exclusion of `machine/reports`. Classify exact known
coverage reports as historical read-only consumers only after the historical
resolver supports their bound reference. Unsupported report/reference contracts
remain protected. Frozen Start/publication references are never rewritten into
summary-only replacements.

**Durable transaction.** The identity binds the old plan/inventory, capsule,
explicit replacement and policy version, never merely the current date. Stages:
prepare and verify capsule -> atomically publish a retirement intent -> recheck
references, identities and approved target -> collect expanded inventory ->
publish completion evidence. Intent publication makes the knowledge plan
read-only even if interruption occurs before collection. Missing/corrupt intent
or capsule fails closed; it never restores execution authority. Recovery uses
the saved transaction and replacement, not a newly selected global plan.
Repeated recovery is idempotent; a failure keeps all available original bytes.
Unlink checks reject changed candidates, links/junctions/hardlinks and escapes.

**Readers.** A valid retired plan has an explicit historical view. Audit/report
readers can validate and stream its capsule without recreating an active
inventory. Active execution rejects retired or malformed retirement markers
before authority creation. Historical reports are labelled retired/read-only,
not current source coverage or completed model work. Existing nonretired plans,
receipts and all research-run readers retain their behavior.

**Interface and authority.** Keep audit as the default. Separate preparation of
a transaction from collection, which requires the exact approved inventory
paths and a bound maintenance approval reference. Routine research gets no new
buttons or gates. Existing knowledge maintenance may expose transaction stages
through its current job records; no automatic retirement is enabled by default
in this development round. The latest user approval permits actual removal of
verified migrated copies only after an exact path/reference audit, offline
verification and Git synchronization; it never permits deleting unique evidence.
That audit must verify the loaded writer revision and absence of old/unresolved
knowledge workers; an older running binary may not honor the new protocol.

**Bounds and acceptance.** Stream compression and validation with finite byte,
row, time and candidate limits. Unknown/oversized evidence is retained, never
truncated. Test scope and identity mismatches, prepared/active/shared jobs,
cross-process lock order, revival attempts, archive tampering, reference and
path replacement races, every interruption boundary, repeated recovery and
unchanged original accounting/Stop. Use isolated fixtures and fake executors;
no WQB, model calls, research resume, proof renewal or real deletion.

### Signboard Removal (Nov 5 Confirmed)

Remove Signboard as a product capability, including its dedicated launchers,
integration routes, local dependency distribution and board-only assets/tests.
Preserve the research Console, desktop launchers and canonical root architecture
and task ledgers. Shared architecture parsers remain only where used by surviving
Console/AI routing. Inventory exact dependency closure and Git recoverability
before removal; do not publish private runtime state for backup. Migrate unique
project facts into canonical project records before collecting any board state.
Secrets or unrelated browser/configuration files, if found, require named review.

## 5. Gate Policy Not Changed Yet

Do not silently change the 90-day policy, timing/units/grain requirements, Repair frequency/exposure/invariants, Seed thresholds, publication review, Stop, budgets, unknown POST handling, correlation checks or final-submit authorization. Report every evaluated rejection with target, stage, code, evidence, scope and disposition. Distinguish not_evaluated, missing explanation, local implementation limit and actual incompatibility.

After source repair, measure remaining failures and discuss semantic gate changes from those observations. Full catalog explanation is not a prerequisite for starting a valid scoped experiment; the existing selected-resource contract must still be satisfied until revised.

## 6. Acceptance And Remaining Authority

- TDD covers large/multiscope catalogs, Unicode/line limits, generation changes, unsafe paths, index drift, date-only notes, unchanged replay, shared inventory, GC references and interrupted cleanup.
- Exercise the real maintenance -> machine -> selected-resource -> Console read path with isolated raw/fake transport. No fabricated stage-success receipts, extra UI gates or late model calls.
- Use bounded local actual-vault verification after isolated tests, with before/after raw/release/run evidence checks. Report inventory/readability separately from semantic and research readiness; no promise of zero downstream gaps.
- Before final acceptance run fast root-entry checks, affected suites, one stable full suite, loaded-version verification, Git sync and cleanup audit. Preserve failed logs.
- No platform capture, explanation model calls, research resume, proof renewal, budget change or Alpha submission. Request any genuinely missing online material and finite explanation budget separately. Formal EXE activation follows resource acceptance and a separately reviewed deployment step; do not label the whole project complete prematurely.
