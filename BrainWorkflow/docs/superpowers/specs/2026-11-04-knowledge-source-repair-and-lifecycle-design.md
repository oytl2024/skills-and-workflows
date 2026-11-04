# Knowledge Source Repair And Derived Artifact Lifecycle

Date: 2026-11-04
Status: proposed implementation supplement; priorities confirmed, detailed contract awaits review.
Supersedes only the affected source-ingestion/derived-storage parts of the Oct23 semantic compilation design. Research meaning/eligibility policies are unchanged in this first slice.

## Outcome

Repair local engineering barriers before weakening research gates: large catalog reading, index/body inconsistencies, user-note metadata classification, repeated inventories and uncollected superseded derived files. Reuse raw/machine/wiki and the existing compiler, publication, maintenance and Console boundaries. This slice performs no database migration and creates no agent framework or second source authority.

Later discussion accepted SQLite as a candidate machine storage/read optimization; it is not yet implemented or an exemption from source validation. The detailed migration must preserve raw/wiki Markdown, source identities, frozen run readers and transactional publication, with one authoritative machine generation rather than concurrent independent SQL/JSON authorities. Resolve its implementation scope before changing storage; do not lose this requirement while closing Repair.

## Confirmed Evidence

The Nov3 source probe had 298 gap items: 296 local sources above the 2MB read bound and two aged excerpts. Full preparation had 88,441 identities without verified material; these are not independent market-data failures. Two indexed Markdown sources had digest mismatches, three raw captures were unindexed. Eleven health findings concern one user note. These observations do not establish downstream timing/unit/transform eligibility.

## 1. Source Reading

- Separate local catalog I/O from model context. Keep model material/pack/output bounds; do not send whole catalogs to a model or simply enlarge every memory bound.
- Extend the existing verified extraction pipeline in knowledge_contracts.py. Stream a captured generation using bounded lines/pages; retain exact dataset/field/scope and capture-manifest identity. Compute/verify the original digest and counts before publishing certified pages.
- A complete local catalog pass must not silently end after the default small extraction prefix. Persist progress when bounded work must yield; resume from the same source generation and verify that it has not changed. Prefer one source scan per generation over one scan per field/batch.
- Existing jobs may keep small immutable source excerpts. New preparation resolves exact requested rows from the verified catalog/pages, rather than treating the original file size as field ineligibility. Preserve quoted row/source provenance.
- Preserve path/link checks, malformed/duplicate-key JSON rejection and exact raw identities. Source-byte verification does not imply semantic completeness, freshness or platform availability.

## 2. Index And Metadata Repair

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

## 5. Gate Policy Not Changed Yet

Do not silently change the 90-day policy, timing/units/grain requirements, Repair frequency/exposure/invariants, Seed thresholds, publication review, Stop, budgets, unknown POST handling, correlation checks or final-submit authorization. Report every evaluated rejection with target, stage, code, evidence, scope and disposition. Distinguish not_evaluated, missing explanation, local implementation limit and actual incompatibility.

After source repair, measure remaining failures and discuss semantic gate changes from those observations. Full catalog explanation is not a prerequisite for starting a valid scoped experiment; the existing selected-resource contract must still be satisfied until revised.

## 6. Acceptance And Remaining Authority

- TDD covers large/multiscope catalogs, Unicode/line limits, generation changes, unsafe paths, index drift, date-only notes, unchanged replay, shared inventory, GC references and interrupted cleanup.
- Exercise the real maintenance -> machine -> selected-resource -> Console read path with isolated raw/fake transport. No fabricated stage-success receipts, extra UI gates or late model calls.
- Use bounded local actual-vault verification after isolated tests, with before/after raw/release/run evidence checks. Report inventory/readability separately from semantic and research readiness; no promise of zero downstream gaps.
- Before final acceptance run fast root-entry checks, affected suites, one stable full suite, loaded-version verification, Git sync and cleanup audit. Preserve failed logs.
- No platform capture, explanation model calls, research resume, proof renewal, budget change or Alpha submission. Request any genuinely missing online material and finite explanation budget separately. Formal EXE activation follows resource acceptance and a separately reviewed deployment step; do not label the whole project complete prematurely.
