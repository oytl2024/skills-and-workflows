# Explicit Runtime Renewal

When cumulative runtime reaches its authorized limit, normal Resume remains
disabled. Select additional runtime (6 or 12 hours) in Workflow Progress and
click **Authorize extension and resume**. This is explicit additional authority,
not a reset. Simulation usage/cap, elapsed time, live permission, recovery limits
and final Alpha submission restrictions remain unchanged.

The run-bound revision prevents stale actions from overriding a newer Stop.
An embedded atomic `runtime_renewals` receipt records old/new limits, duration,
timestamp and revisions. Repeated requests cannot grant the same extension twice.
The existing background resume path receives the resulting revision. If launch
fails, the extension remains recorded and normal Resume can retry without another
extension. A newer Stop requires a fresh user action.

Original-batch restricted and incomplete legacy authority cannot be expanded here.
Maintenance and readiness blockers are not repaired or waived by renewal. Historical
runtime boundary notices remain evidence; renewal does not delete them.

2026-10-12 approved instance: add21600seconds to run
`20261011T175340059665-edf5bbdf`, total43200seconds; simulation cap150 unchanged.
