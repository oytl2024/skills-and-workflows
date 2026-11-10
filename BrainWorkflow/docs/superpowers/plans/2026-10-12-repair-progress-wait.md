# Repair progress wait maintenance

Approved case86172bb91bad03a536e9b283; no WQB calls, research resume, budget
changes or Alpha submission during maintenance.

## Evidence And Cause

The durable source has one SUBMITTED progress URL and no checked child. Local
HTTP telemetry shows repeated200 responses with Retry-After5. Repair formerly
ran120 polls per invocation, converted bounded poll expiry to generic recovery,
and eventually hit the driver's no-progress protection. There is no evidence
that this particular pending simulation completed or that429 caused this poll.

## Implementation

- One bounded progress GET per slice; durable wake at least60seconds and never
  earlier than server Retry-After. Existing runtime limit bounds total waiting.
- Store SIMULATION_COMPLETED/Alpha ID before checks. Resume checks directly;
  retain SUBMITTED identity and never resubmit an uncertain POST.
- Project simulation-progress-wait separately from true429 cooldown; bind its
  receipt to the current pause reason. No synthetic429 or quota reset.
- Preserve Stop resumability, classify auth/transient failures, fail closed on
  malformed JSON, programming errors and terminal HTTP failures.
- RED/GREEN tests, independent medium review, formal full verification, durable
  case resolution, loaded Console identity and legal next-transition check.

Final evidence and remaining external uncertainty are in root todo.md.
