# Shared Daily Simulation Budget

Status: draft for human review, not implementation or live-run authority.

## Approved Product Intent

Replace the ordinary research run's lifetime simulation ceiling with a shared
local allowance of 4,000 simulation submission attempts per calendar day.
The day boundary is 00:00 Asia/Shanghai. Scout, Seed, Discovery and Repair,
including different research runs in this workspace, share that allowance.
Routine interaction remains Option Card selection and Start/Stop. No recurring
Codex automation, new agent framework or manual stage-advancement controls.

The allowance is a project safety policy, not a claim about platform quota.
Activity outside this product or another workspace is not measured by it.
Supporting multiple unrelated accounts/workspaces is outside this change.

## Existing Behavior And Gap

- `runtime_control.py::check_submission_allowed` charges the owning run's
  cumulative `simulation_attempts`; `simulator.py` supplies one or the number
  of children in a multisimulation. GETs do not increment that counter.
- `research_rounds.py` uses the run ceiling, historical reservations and a
  derived lifetime round limit when allocating subsequent Scout rounds.
- `workflow_auto_continue.py` and Console retain a blocked round's resource
  marker even after an explicit local simulation-limit increase. This made
  the approved 150-to-180 increase insufficient to resume through the app.
- `workflow_driver.py` already provides durable Stop, time limits, submission
  identity recovery and bounded script-based waits. Reuse those boundaries.

This is not a change from 180 to 4,000 in one constant: historical run usage
must not exhaust a future day's allowance, and a stale round marker must not
require one-off manual JSON editing.

## Counting Contract

1. Count a positive simulation submission reservation at the existing
   pre-submit accounting boundary. One multisimulation containing N children
   consumes N units, not one HTTP request.
2. A failed or outcome-unknown submission retains its charge. A later genuinely
   new POST attempt is a new charge; GET polling/checks and local planning are not.
3. Planned candidates and round reservations are not themselves submitted units.
   They constrain planning but must not be charged twice against shared usage.
4. Changing days selects a new bucket; never zero or overwrite lifetime counters,
   previous buckets, POST identities, unknown outcomes or raw check evidence.
5. Remaining budget is shared by all product-managed stages/runs. Allocation
   uses `min(stage_cap, remaining_today)`; Scout/Discovery still cap at 30 and
   Repair retains its existing per-batch bound. No padding duplicate candidates.
6. A batch that cannot fit is not partially submitted behind the caller's back.
   Build a smaller valid batch first; indivisible paired experiments wait when
   they cannot fit as a complete pair.

## Durable Ownership And Concurrency

Use one small budget module, tentatively `wqb/daily_simulation_budget.py`, for
the default limit, timezone conversion, policy validation, bucket selection,
atomic charge receipts and remaining-budget queries. Reuse existing JSON locks
and atomic publication helpers; add no database or scheduler dependency.

Store shared policy and accounting under the existing `runs/` boundary, not
inside the human wiki. Bind paths to the canonical workspace run root. A source
batch nested under an owning mission must not create an independent allowance.
No network or model calls are needed to read, charge or roll over the budget.

Cross-run charges must be serialized by one shared guard. Persist a unique
charge receipt before issuing POST. The daily ledger is authoritative for
post-activation charges; the per-run lifetime projection is recoverable from
its activation baseline and receipts. A crash between ledger publication and
run-counter projection must neither refund quota nor double-charge recovery.
Corrupt/missing established policy or ledger fails closed, not to a fresh day.
Reject date rollback or a bucket inconsistent with trusted local time; retain
evidence rather than silently opening another quota bucket.

Keep Stop and the final POST gate effective while reserving budget. An old
Start, timer, callback or daily rollover must never override a newer Stop.
No blind re-POST of outcome-unknown identities, even across midnight.

## Activation And Old Runs

New ordinary research runs use the approved daily policy. Existing runs adopt
it only through an explicit, revision-bound activation receipt. Preserve old
`max_simulations` values as historical legacy authority, not the daily mode's
effective lifetime ceiling. Unmigrated records remain readable; protected
original-batch recovery retains its original scope and stricter limits.

For active run `20261011T175340059665-edf5bbdf`, retain cumulative usage 150,
the unused 180-total authorization history, runtime limit 64,800 seconds,
recovery cap three, current stage, frozen data/templates and all evidence.
The known 150 lifetime attempts cannot honestly be assigned to individual
historical days. Conservatively carry them into the activation day's bucket,
once, with an explicit migration label. This is not a claim that all 150
occurred that day, nor a full account-wide platform consumption measurement.
Other unverified historical activity must not be fabricated into exact counts.

After activation, remove obsolete budget blockage through a reusable,
revision/authority-checked reconciliation path. Do not manually erase a round
marker or overwrite unrelated planning, maintenance or knowledge blockers.
Daily mode must not derive a permanent lifetime round ceiling from an old
150/180 cap. Preserve any independently explicit `max_rounds`, execution-step,
time, recovery or original-scope boundary.

## Wait And Recovery Flow

`Start -> existing work/reconciliation -> plan within remaining_today ->`
`submit/poll/triage/repair -> repeat`.

If daily quota is exhausted, persist `daily-budget-wait` with the local budget
date, used/limit and next midnight in UTC and local time. Permit reconciliation
of existing in-flight identities and valid result/check recording; prohibit new
POSTs and new research/model planning solely to fill the wait.

An already-authorized managed worker waits using the existing cooperative
driver mechanism. At midnight it re-reads policy, daily balance, Stop, runtime
and recovery/maintenance state before proceeding automatically. Waiting must
not busy-loop, consume repeated model calls or fill a thousand no-op steps.
There is no automatic extension of the run's time limit: existing wall-time
accounting still applies during waits. If another boundary prevents continuation,
show that boundary instead of promising automatic midnight recovery.

After shutdown, state remains recoverable through ordinary app Start/Continue;
do not create a recurring automation or a new mission to bypass shutdown/Stop.

## Console Contract

Keep the current app layout and primary Start/Stop controls. Display:

- Today's submitted-attempt budget: used / 4,000, shared across runs.
- This run's lifetime attempts as a separately labelled historical count.
- Budget timezone/date and next available time when waiting.
- Whether another boundary prevents automatic continuation.

Use the same service snapshot for text, timeline, action permissions and worker
decisions. A normal daily wait is not a maintenance failure or an approval gate;
Stop remains available. Do not require a daily renewal click or maintenance-chat
message. Corrupt accounting or an unresolved code fault remains a true blocker.
Application polling reads local accounting only; it must not probe WQB.

## Safety And Non-Goals

Keep platform 429/Retry-After behavior, cheap-before-correlation checks, known
POST recovery, knowledge readiness, frozen snapshots and final Alpha submission
authorization unchanged. Do not reset failed checks, quota evidence or counters.
No new knowledge capture, model generation or live simulations during development.
Deploying the policy or renewing source-bound maintenance proof does not itself
start research. Actual continuation remains separately authorized and Stop-bound.

## Acceptance Evidence

- Offline tests cover 3,999 + 1 allowed, the next unit refused; multisimulation
  child accounting; zero-cost GETs; negative/invalid counts and corrupt ledger.
- Two runs and concurrent processes cannot exceed the shared daily allowance.
- Midnight rollover, timezone conversion, backward dates and restart replay
  retain history without refunding/double charging an unknown POST.
- Failure between shared charge and run projection recovers consistently.
- Daily limits cap Scout/Discovery/Repair and complete experiment pairs without
  retaining a legacy lifetime round ceiling or widening explicit other limits.
- The active legacy budget marker automatically reconciles after approved
  activation; an unrelated blocker or durable Stop is never cleared.
- A fake-clock offline full-flow test reaches daily wait, wakes next day, and
  resumes automatically; Stop/time expiry wins while waiting. No live requests.
- Console snapshot/action tests match daily wait, restart, readiness/maintenance
  blockers and the running worker. No stale enabled/disabled action disagreement.
- Full offline regression, independent review, source-bound proof where approved,
  verified Git sync and loaded app-version check precede delivery. Preserve all
  uniquely referenced research, source and recovery artifacts during cleanup.

Implementation planning and product changes begin only after approval of this
written design. The implementation plan will name exact call sites and tests;
it is not permission to change Orchestrator's core research-stage architecture.
