# Task 2 Report: Official Rule Refresh

## What I Implemented
- Added `BrainWorkflow/wqb/rule_refresh.py`.
- Added `BrainWorkflow/tests/test_rule_refresh.py`.
- Implemented `DEFAULT_RULE_PAGE_IDS` with the exact rule page ids from the brief.
- Implemented `refresh_incentive_snapshot(client, generated_at)` to refresh:
  - `/users/self`
  - `/events?limit=50&offset=0`
  - `/competitions?limit=50&offset=0`
  - `/consultant/boards/power-pool`
  - `/tutorial-pages/<page_id>` for each default rule page
- Normalized the payloads into `IncentiveSnapshot`, `SourceEvidence`, results lists, power pool board choices, and rule page text.
- Kept the refresh resilient by collecting errors instead of aborting on a single source failure.

## What I Tested
- Focused test:
  - `python -m unittest tests.test_rule_refresh -v`
  - Result: passed
- Related tests:
  - `python -m unittest tests.test_rule_refresh tests.test_principle_model -v`
  - Result: passed
- Full suite:
  - `python -m unittest discover -s tests -v`
  - Result: passed

## TDD Evidence
### RED
- Command:
  - `python -m unittest tests.test_rule_refresh -v`
- Output:
  - `ImportError: Failed to import test module: test_rule_refresh`
  - `ModuleNotFoundError: No module named 'wqb.rule_refresh'`

### GREEN
- Command:
  - `python -m unittest tests.test_rule_refresh -v`
- Output:
  - `test_refresh_incentive_snapshot_normalizes_core_sources ... ok`
  - `Ran 1 test in 0.000s`
  - `OK`

## Files Changed
- `BrainWorkflow/wqb/rule_refresh.py`
- `BrainWorkflow/tests/test_rule_refresh.py`
- `BrainWorkflow/todo.md`

## Self-Review Findings
- The implementation stays simple and follows the repo's unittest style.
- The new helper functions are small and isolate refresh failure handling cleanly.
- The snapshot contains visible error collection and stale evidence markers when rule-page fetches fail.
- No unrelated code was modified.

## Concerns
- The refresh logic is intentionally conservative and only normalizes the sources covered by the brief.
- I did not add any promotion or submission logic; this task only refreshes official rule evidence.

## Review Fix: Core-source stale evidence
### What changed
- Added `_append_evidence(...)` in `BrainWorkflow/wqb/rule_refresh.py` so every refreshed source uses one path for evidence rows.
- Marked `/users/self`, `/events?limit=50&offset=0`, `/competitions?limit=50&offset=0`, and `/consultant/boards/power-pool` evidence as `stale=True` with `note="refresh failed"` when the fetch fails.
- Kept existing normalization behavior for successful payloads and tutorial page refreshes.
- Added a regression test in `BrainWorkflow/tests/test_rule_refresh.py` covering failures for those four core sources.

### Covering tests with exact command/output summary
- `python -m unittest tests.test_rule_refresh -v`
  - Output summary: `Ran 2 tests in 0.000s` / `OK`
- `python -m unittest tests.test_rule_refresh tests.test_principle_model -v`
  - Output summary: `Ran 4 tests in 0.001s` / `OK`
- `python -m unittest discover -s tests -v`
  - Output summary: `Ran 164 tests in 0.402s` / `OK`

### Commit SHA
- `2cabcde5b02d78a18a73e458b726178a28266e8c`
