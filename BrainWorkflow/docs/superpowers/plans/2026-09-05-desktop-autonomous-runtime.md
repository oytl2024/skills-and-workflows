# Desktop Autonomous Runtime Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development and test-driven-development. Maintain this plan as the execution ledger.

Goal: deliver double-click, responsive operation with automatic stage progress and durable maintenance context.
Architecture: existing Orchestrator plus a persistent driver, source outcome contracts, shared lightweight Console projection, and app-mode desktop entry.
Tech stack: Python standard library, current HTML UI, SSE, Windows installed browser app mode.
Spec: ../specs/2026-09-05-desktop-autonomous-runtime-design.md

## Ownership And Interfaces

| Task | Owned files | Contract |
| --- | --- | --- |
| A: stage outcomes | source_bridge.py, workflow_stage_adapters.py, orchestrator.py and their tests | accept checked signals without hard-pass candidate CSV; actual stage receipts; strict final candidates |
| B: Console projection/UI | console_state.py, console_server.py, console_timeline.py, console_progress.py, new strategy_progress.py and their tests | GET lightweight/SSE updates, source-bound readiness; start/continue actions stay Console jobs; new runtime_control is read-only UI input |
| C: desktop entry | new desktop.py, launchers, desktop tests | starts/reuses launch-console backend, app window, logs and single-instance checks |
| D: driver/controller | new runtime_control.py, workflow_driver.py, workflow_auto_continue.py, cli.py, console_jobs.py and tests | runtime_control_path(run_dir), read_runtime_control(run_dir), request_runtime_state(run_dir, desired_state, **options), run_workflow_driver(paths, config, ...); cooperative checks before submit |
| E: integration/maintenance | docs, console_context.py, delivery_verification.py, AI execution boundary, acceptance tests | current architecture/tasks and real native test evidence |

Ruling: use the current dirty feature checkout; it contains essential approved fixes not present in HEAD. Disjoint agent ownership avoids reverting them. Controller owns shared integration and docs. No automatic commit or push.
Ruling: existing operation permission is preserved, but development does not perform live research. Final Alpha submission stays separately authorized.

## Tasks

- [x] A. Reproduce empty Repair success and no-hard-pass Scout dead end. Implement research artifact routing, meaningful completion receipts and near-miss handoff using existing optimizer. Test empty/weak/repairable/qualified outcomes and strict import identity.
- [x] B. Reproduce cross-run readiness and input loss. Implement common source-bound status, cold resource caching, per-alpha projection and stable SSE updates. Test identity joins, stale status, no hot ledger reads and browser input preservation.
- [x] C. Implement double-click launcher/backend reuse and app window. Test command construction, Python discovery, duplicate-launch prevention and clear startup diagnostics.
- [x] D. Reproduce one-step progression and abort-only stop. Implement persisted driver, bounded waits/recovery and pause guard at every new submit. Test fake clock, rate limits, restart/dedupe, authorization and terminal boundaries. Finish previous 429 throttling tests.
- [x] E. Integrate driver actions in Console and source outcomes; add durable AI worker contract, maintenance architecture/tasks, compact recovery anchor, native delivery verification and whole-flow fake-platform/browser acceptance.
- [x] F. Independent final code review, fix findings, full native non-live suite, screenshots/performance measurements, user guide and verified launch link. App-mode launcher was already verified locally; this does not claim a packaged native installer or a live WQB run.

## Verification Commands

From BrainWorkflow with SystemRoot=C:\Windows and windir=C:\Windows:

```powershell
python -m unittest tests.test_workflow_auto_continue tests.test_console_timeline tests.test_workflow_stage_adapters -q
python -m unittest discover -s tests -q
python -m compileall -q wqb tests scripts
git diff --check
```

Each agent records RED/GREEN evidence and exact changed files below. Controller records integration failures and acceptance evidence; incomplete items remain unchecked.

## Execution Ledger

- 2026-10-10: final native suite passed 1041 tests in 156.798s; runtime browser passed real offline Resume click, SSE/mobile and zero live API; architecture browser, compileall and diff check passed. Loaded source fingerprints reject outdated backend/viewer reuse. Follow-up review fixes disable every simulation POST retry, preserve original Start receipts and atomically reject stale Resume revisions. Concurrent Pause receipt regression covered; narrow independent re-review reported no remaining receipt/CAS finding. Isolated root VBS smoke verified visible window, same-backend reuse and close/reopen; owned smoke processes cleaned up. No actual model or WQB call, no commit/push.

- 2026-09-05: user authorized implementation. Plan/spec written before code changes. A/B/C disjoint implementation can proceed alongside controller D; E depends on their interfaces. Baseline: 38 focused tests, 3 errors from old readiness mocks; working tree includes prior uncommitted fixes.
- 2026-10-08: local Signboard board installed under `management/board`, native suite passed 979 tests after all edits, responsive desktop/mobile browser acceptance passed without live API, bounded Repair executor and durable AI checkpoint worker contract added. A-D now have focused/full test evidence. E remains open: no automatic model checkpoint scheduling or whole-flow fake-platform acceptance yet. F remains open.
- 2026-10-09: workflow-first board, 30-Scout/429/Repair/approval/restart offline acceptance, automatic advisory AI checkpoints, simplified daily controls and updated manual completed. Regression test exposed terminal capture progress recount; fixed to preserve persisted terminal progress without rescanning raw files. Full native suite 1024/1024 (159.628s), browser smoke with zero live API calls, compileall and diff check passed. Real local runtime projection 530.6 ms first and 46.4 ms repeated; cold knowledge summary 3623.8 ms. F remains open for independent review, launcher verification and final delivery; no live model or WQB call in this maintenance verification.
- 2026-10-09: independent read-only review found four live-control risks. Added durable submission attempt events and fail-closed unknown-outcome recovery; moved live authorization to Start and removed Resume escalation; rejected foreign-origin and stale Start/Resume POSTs; serialized pause acknowledgement with simulation POST using an OS file lock. Added RED/GREEN tests including actual blocking fake HTTP and stable action revision. Final full native suite passed 1034/1034 (150.824s), browser smoke passed with zero live API calls. Prior app-mode launcher verification remains the delivery entry; no native installer, live WQB simulation or actual Codex worker invocation was part of this maintenance acceptance.
