# Task 3: Knowledge Bootstrap Core Report

## Scope

Implemented the pure knowledge bootstrap materialization core in `BrainWorkflow/wqb/knowledge_bootstrap.py` and added focused coverage in `BrainWorkflow/tests/test_knowledge_bootstrap.py`.

## Implementation

- Loads seed JSONL rows for the data ledger and template library.
- Stamps seed rows with `source_quality: schema_seed` and `coverage_status: partial`.
- Writes deterministic formal JSONL artifacts and reviewable Markdown artifacts.
- Writes the freshness manifest, bootstrap report, and non-live activity snapshot.
- Exposes `BootstrapSummary`, `bootstrap_knowledge`, and `bootstrap_summary_to_dict`.

## Verification

Commands run from `BrainWorkflow`:

```text
python -m unittest tests.test_knowledge_bootstrap -v
Ran 2 tests in 0.021s
OK

python -m unittest discover -s tests -q
Ran 217 tests in 0.512s
OK
```

## Note

The brief's supplied test used `assertIn("freshness_manifest.json", payload["artifact_paths"])` against a list of full paths. The assertion was corrected to check whether any full path contains the expected filename; production behavior remains the specified full artifact paths.

## Outcome

Implementation and tests completed successfully.

Commit: `3813f54 add knowledge bootstrap materialization`

## Task 3 Review Fix

### Changes

- Preserved all required freshness manifest entries.
- Marked only `data_ledger`, `template_library`, and `activity_snapshot` as `refreshed` at bootstrap time.
- Marked `benchmark_rules`, `operator_catalog`, and `research_option_cards` as `not_refreshed` with a `1970-01-01` stale baseline and source notes.
- Added explicit partial/schema-seed and refreshed versus not-refreshed status to the bootstrap report and warnings.
- Added regression coverage for manifest and report truthfulness.

### Verification

```text
python -m unittest tests.test_knowledge_bootstrap -v
Ran 3 tests in 0.052s
OK

python -m unittest discover -s tests -q
Ran 218 tests in 0.539s
OK
```

Commit: `a76a7fa fix truthful knowledge bootstrap freshness`

## Task 3 Re-review P1 Fix

### Changes

- Normalized schema-seeded data ledger rows to `coverage: 0.0` before writing JSONL.
- Preserved `source_quality: schema_seed` and `coverage_status: partial` in the raw JSONL.
- Added a regression test proving `load_data_ledger` cannot consume the seed coverage value as factual coverage.

### Verification

```text
python -m unittest tests.test_knowledge_bootstrap -v
Ran 4 tests in 0.053s
OK

python -m unittest discover -s tests -q
Ran 219 tests in 0.586s
OK
```
