# Metric-Directed Deterministic Repair

User approved implementation on 2026-11-04 after the explicit Repair gap audit. This supplements the approved preplanned workflow, not a new agent framework. Execute with TDD and medium-or-lower agents only; root todo.md owns progress.

## Contract

New Repair policy schema v2 adds explicit rule trigger, project-hypothesis basis, rationale and parameter direction. Keep schema-v1 frozen rules/receipt rebuilding byte-compatible; never rewrite existing run manifests. A trigger records checks plus an optional finite metric comparison; a measured predicate or a corresponding completed failure activates it. Pending checks are not failures. Current metric severity influences eligible-rule ranking; fixed priority is only a declared tie-breaker. Untriggered rules never produce candidates.

Rule v2 fields: existing RULE_KEYS plus `trigger`, `basis`, `rationale`, `parameter_direction`. Trigger keys: `checks` (known baseline failure names list), `metric` (sharpe/fitness/turnover or null), `operator` (gt/lt or null), `threshold` (finite scalar or null). Parameter direction: increase/decrease/any. basis is project_hypothesis; official field facts remain in source/measured traits, not inferred economic effects.

Default new-Start rules are finite project research hypotheses, not official platform claims: high turnover -> increase decay; concentration -> reduce truncation; low Sharpe/Fitness -> controlled response/smoothing search with explicit target and known data prerequisites. Use known matrix/source properties, recorded cadence where required, and narrow finite settings grids. Do not invent noisy/persistent/exposure facts or arbitrary formulas. Existing source-certified transform/neutralization rules remain available when prerequisites are satisfied; do not waive unknown-grain/timing/signature/exposure gates in this change.

Default policy generation is a pure resource-to-policy function in `repair_rulebook.py`. Start freezes it, including its project rulebook version and actual field references. Selection uses the checked accepted incumbent; only one property changes. A project experiment can test a setting effect without pretending the field description officially guarantees that effect. No late model calls.

Stop distinctions: no_rules_configured, no_triggered_rules, missing_prerequisites, no_novel_candidates, tested_without_improvement, search_space_exhausted and existing budget/Stop boundaries. Preserve detailed skipped reasons and measured traces; never label the mechanism disproven. Incomplete evidence remains inconclusive.

## Tasks

- [x] R1: Add RED tests for low/high turnover with same failed Fitness, actual failed-check routing, pending/unknown payloads, severity ordering, parameter direction and v1 replay. Implement v2 selection in repair_search.py; expose valid stop categories without changing authority.
- [x] R2: Add RED tests for a source-backed new Start receiving nonempty default rules without fake raw setting-effect records. Implement repair_rulebook.py and integrate preplanned_start.py, preserving explicit supplied v1/compiled policies. Attach only justified traits and project-labelled hypotheses. Test cadence/unsupported fields, parent identity/scope and dedup.
- [x] R3: Propagate stop distinctions into repair_scheduler.py and existing record/Console projections. Test no-POST exhaustion, blocked prerequisites, tried/rejected history, accepted-parent updates and restart consistency.
- [x] R4: Real composer/fake HTTP end-to-end test: failed metric -> selected rule -> finite candidate -> checked comparison -> accept/rollback/stop -> record; no internal clicks or model calls. Test Stop/unknown POST and shared daily accounting unchanged.
- [ ] R5: Audit actual local resource coverage separately from policy construction; retain genuine source/freshness blockers, do not claim real-vault readiness from fixtures. Run fast doc checks, affected suites, stable full suite and loaded Console validation. Review, commit/push, audit cleanup and sync; protect raw/history and existing dirty documents.

No platform calls, explanation-model budget, research resume, proof renewal, quota changes or Alpha submission. SQLite/source lifecycle work remains a separate tracked dependency; default rule availability is not a shortcut around source readiness. Record unsupported actions honestly rather than promise universal rule coverage.

## Implementation Evidence

R1-R4 source-backed affected acceptance: 98 tests passed in 58.361 seconds; subsequent bounded review fixes passed 40 tests. Three reproduced review findings are closed: missing batch-level cadence cannot hide actual parent cadence, manually supplied source-free V2 policies are refused before mission creation, and inconclusive attempts cannot be classified as measured rejection. V1 receipt bytes retain their prior regression digest.

Real local probe remains 0 usable USA D1 TOP3000 lanes with 298 source diagnostics. It made no platform/model calls and changed no raw or mission. Source/lifecycle and proposed SQLite work remain outstanding, not silently waived by defaults.

Final desktop build `output/desktop-application/20261104-142807-5366` passed frozen self-test and CLI import smoke; its public rulebook is present. An isolated packaged backend served React desktop/mobile without overflow or page errors, with loaded revision `a7101e6feecc31fa9a8c27892507a3c7bfd6174f7e6f5825fcf1932735b17f19` equal to current source. No controls were clicked and no real workspace data roots or WQB credentials were passed. Existing isolated Console browser/SSE/Resume regression also passed with zero live calls. This is not formal entry activation.

The first full suite (2,861 tests, 683.322 seconds, one failure/five skips) exposed advisory ledger tags being required as raw facts by the new Repair consumer. A RED regression and two focused fact projections fixed this without accepting invented traits or relaxing type/description/timing/grain/hash checks. All 62 affected tests and a narrow independent source-safety review passed; the failed full log and superseded build remain diagnostic evidence, not current acceptance. A second stable full suite is required.

Stable final full suite: 2,862 tests passed (five skips), 835.716 seconds, source/test/catalog digest before and after `3eee974f07e8ec2c47e95f8ff9fda3ae91c5abaf51ca8469940f5166b1b72add`. Log: `output/desktop-validation/metric-directed-repair-final-full-suite-20261104.log`. Git/cleanup closure belongs in root todo.md; until recorded, R5 is not complete. No old maintenance proof was renewed.
