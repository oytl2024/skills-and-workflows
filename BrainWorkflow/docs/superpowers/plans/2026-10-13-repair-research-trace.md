# Metric-driven Repair trace implementation

Approved: user confirmed proposal and requested implementation on 2026-10-13.

1. Add a versioned experiment contract to new AI inputs. Require a finite measured
   target metric, explicit direction, falsification and applicability rationale.
   Legacy immutable inputs/decisions remain validated under their original contract.
2. Add a deterministic comparison helper. Compare one permitted edit, parent
   lineage, scope/settings and finite metrics. Missing evidence is inconclusive;
   metric improvement is not submission qualification or causal proof.
3. Attach the trajectory to existing scheduler attempts, including cached recovery;
   retain stop decisions without consuming simulation allowance.
4. Carry attempts into the existing research record, then render concise evidence
   in existing raw and wiki case reports. Compile only via knowledge maintenance.
5. TDD for validation, comparisons, legacy evidence, idempotent records/reports and
   scheduler integration; run focused tests then full offline regression/review.

No live API, new operator permissions, budget renewal or research resume. No
additional parallel ledger. Existing Stop and final submission authority unchanged.

## Verification

- Steps 1-5 completed, 2026-10-13. New tests observed RED before implementation.
- Independent review caught incomplete periods and lost baseline metrics; both
  now produce inconclusive outcomes with regression coverage.
- Full source-bound offline suite: 1375 tests passed, source unchanged, no failures.
- Compileall, diff check and architecture entry tests passed. Loaded desktop
  revision matches current source; Resume/Stop available, research not resumed.
- Live effectiveness and advanced nonlinear operators remain outside this scope.
