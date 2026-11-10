# Partial Scout batches and planning recovery

Approved contract: scheduled batches contain 1..30 valid distinct candidates, not exactly30. Zero candidates must select another authoritative snapshot-backed match without platform discovery; exhausted plans notify maintenance, never silent waiting. Preserve Stop, original quota, immutable evidence, unknown POST protection and final submission approval.

1. Add failing runner tests for partial batches, zero candidates and provenance rejection; cap/readiness tests for small requested batches.
2. Publish nonempty actual batches, retaining provenance checks and durable multisim queues. Zero raises a typed exhaustion only.
3. Add durable bounded same-round alternate selection, validated against the original snapshot and no outstanding submission. Record exhausted identities, replay interrupted selection, reject Stop/invalid authority.
4. Route planning faults to maintenance with exact cause; keep genuine budget/authority stops protected. Update Console/status evidence and tests.
5. Run offline integration/full suite, review and loaded-version acceptance. Do not run live research or submit Alphas as maintenance.

Task/progress evidence belongs in root todo.md.

Acceptance: all five steps complete; 1437 offline tests passed with unchanged source and resolved case22c0b040d423ca6fb9cb09ff. Medium scoped re-review passed (57 tests). Loaded Console revision and enabled Continue verified; no live research/POST/model invocation during maintenance. Explicit reducer correction includes multi-argument vector operators. Zero-candidate rotation/replay validates original snapshot data identity, corruption routes maintenance, and verified planning-stop release is replayable without Start. Full evidence/deployment details are in root todo.md.
