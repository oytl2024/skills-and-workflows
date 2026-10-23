# Pending check recovery maintenance

Human approved code maintenance for case76e4846d9a97ebb2721711af. No live API,
research resume, budget changes or Alpha submission are authorized by this loop.

## Diagnosis

The real backtest has59 checked identities, including6 Discovery rows whose
baseline checks passed but POWER_POOL_CORRELATION and MATCHES_THEMES remain
pending. Those two checks were incorrectly included in the baseline gate.
After Discovery published its children, backtest only reread the artifact and
repeated a misleading missing-results message; there was no check-only executor.

## Implementation And Verification

1. RED/GREEN: activity-dependent checks cannot prevent final check after valid
   LOW_SHARPE/LOW_FITNESS; baseline failure still makes no expensive check call.
2. Recover existing pending identities only, at most30, with per-identity durable
   results, atomic publication and input/output provenance; never simulate.
3. Wire managed backtest recovery and existing cooldown/threshold policy.
   Preserve Pause, budgets, candidate hard-pass requirements and raw history.
4. Regression tests: interruption/restart, no duplicate GET, receipt chain,
   429 cooldown and accurate pending message. Full suite and independent review.
5. Resolve the specific approved maintenance case only after fixed offline
   verification. Reload Console and verify source identity; do not resume research.

Progress and final evidence are recorded in root todo.md.
