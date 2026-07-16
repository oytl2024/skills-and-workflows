# Task 2 Report: Compile Data Ledger From Raw Captures

## Status

DONE

## Scope

Implemented only the Task 2 compiler and its tests:

- `BrainWorkflow/wqb/data_ledger_compile.py`
- `BrainWorkflow/tests/test_data_ledger_compile.py`

The existing `BrainWorkflow/todo.md` was updated as a local progress artifact and was not staged or committed.

## TDD Evidence

1. Added the three brief-specified tests for newest snapshot selection, multi-scope aggregation, and no-overwrite validation failure.
2. RED command failed with `ModuleNotFoundError: No module named 'wqb.data_ledger_compile'`.
3. Implemented the minimal compiler.
4. GREEN focused command passed: 3 tests.

## Implementation

- `latest_capture_dir()` selects the lexicographically newest raw data-field capture directory.
- `compile_data_ledger_from_raw()` reads `data_fields.jsonl`, groups rows by dataset and field, aggregates regions, delays, universes, coverage, and usage counts, and adds semantic/template metadata.
- The compiler writes a temporary JSONL, validates it through `load_data_ledger()`, and replaces the existing ledger only after validation succeeds. A validation exception therefore leaves the last valid ledger unchanged.
- The compiler writes the review Markdown ledger and refreshes the `data_ledger` freshness manifest entry after successful replacement.

## Verification

- Focused Task 2 tests: 3 passed.
- Full test discovery: 448 passed.
- `python -m compileall -q wqb tests`: passed.
- Scoped `git diff --check`: passed.

## Deviation

No functional deviation from the brief was required. The implementation preserves the brief's temporary-file validation order, which is necessary for the no-overwrite requirement.

## Remaining Concerns

No Task 2 blocker remains. CLI and console wiring are intentionally deferred to later tasks as required by the brief.

## Review Fix: Output Staging

The compiler previously replaced `data_ledger.jsonl` immediately after JSONL validation. A later Markdown write or freshness-manifest update failure could therefore leave the new ledger in place despite the failed compile.

- Added RED regression tests for `write_data_ledger_markdown` and `_update_manifest` failures after ledger validation. Both failed against the reviewed implementation because `data_ledger.jsonl` had already been replaced.
- The compiler now stages JSONL, Markdown, and freshness-manifest outputs in temporary files. It validates the staged JSONL, writes the other staged outputs, replaces Markdown and manifest, and replaces the ledger last. Temporary files are removed on every exit path.

## Review Fix Verification

RED command:

```powershell
python -c "import sys, runpy; sys.platform='linux'; sys.argv=['unittest', 'tests.test_data_ledger_compile.DataLedgerCompileTests.test_markdown_failure_keeps_existing_ledger', 'tests.test_data_ledger_compile.DataLedgerCompileTests.test_manifest_failure_keeps_existing_ledger', '-v']; runpy.run_module('unittest', run_name='__main__')"
```

Result: 2 tests ran and failed as expected; each showed `data_ledger.jsonl` had changed from `last_good`.

GREEN focused command:

```powershell
python -c "import sys, runpy; sys.platform='linux'; sys.argv=['unittest', 'tests.test_data_ledger_compile', '-v']; runpy.run_module('unittest', run_name='__main__')"
```

Result: 5 tests passed.

Additional verification:

```powershell
python -m compileall -q BrainWorkflow\wqb\data_ledger_compile.py BrainWorkflow\tests\test_data_ledger_compile.py
python -c "import sys, runpy; sys.platform='linux'; sys.argv=['unittest', 'discover', '-s', 'tests', '-v']; runpy.run_module('unittest', run_name='__main__')"
```

Result: compile check passed; full discovery passed with 450 tests.
