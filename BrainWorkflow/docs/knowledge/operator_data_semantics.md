# Operator And Data Semantics

Last updated: 2026-07-02

This file records the reusable semantic layer used by Stage 1. It is not a statistical embedding model yet; it is a controlled semantic embedding: each field/operator receives tags, polarity, and intended use so templates start from economic logic before simulation.

Implementation:
- `wqb/semantics.py`
- `generate_seed_candidates(..., template_mode="semantic")`
- `python -m wqb.cli cache-metadata ...`
- `python -m wqb.cli semantic-preview ...`
- `python -m wqb.cli run-field-batch --field-cache-path ... --template-mode semantic ...`

## Field Semantics

Field metadata is converted into:
- `tags`: semantic meanings such as `cashflow`, `asset_strength`, `investment_drag`, `leverage_pressure`, `sentiment`, `attention`, `option_activity`, `short_interest`, `analyst_revision`.
- `polarity`: `positive`, `negative`, or `neutral`.
- `expression_value`: direct field id for MATRIX fields and `vec_avg(field)` for VECTOR fields.
- `tag_vector`: a sparse local vector such as `{ "cashflow": 1, "matrix": 1 }`.

Current positive concepts:
- `cashflow`: operating cash flow and similar fields.
- `cash`: cash and cash-change fields.
- `asset_strength`: total/current asset strength.
- `profitability`: income, EBITDA, gross profit.
- `growth`: revenue/sales.

Current negative concepts:
- `investment_drag`: capex and investing cash flow.
- `leverage_pressure`: debt and interest burden.
- `liability_pressure`: liabilities.
- `working_capital_pressure`: payables and receivables.
- `cost_pressure`: cost, SG&A, expenses.
- `asset_quality_risk`: goodwill, intangibles, accumulated depreciation.

## Operator Semantics

Operator metadata is converted into purpose tags:
- `cross_sectional_normalizer`: `rank`, `zscore`, `normalize`, `scale`.
- `turnover_control` / `time_series_smoother`: `ts_mean`, `ts_decay_linear`, `hump`.
- `time_series_transform`: `ts_delta`, `ts_rank`, `ts_corr`, `ts_cov`.
- `group_transform`: `group_neutralize`, `group_rank`, `group_zscore`, `group_backfill`.
- `vector_reducer`: `vec_*` operators.
- `event_gate`: `trade_when`, `if_else`.
- `tail_control`: `winsorize`, `signed_power`, `power`.

## Economic Template Hypotheses

Semantic pairs are selected as positive-field minus negative-field relationships:

```text
rank(positive) - rank(negative)
rank(ts_delta(positive, 5)) - rank(ts_delta(negative, 5))
rank(ts_mean(positive, 5)) - rank(ts_mean(negative, 5))
group_neutralize(rank(positive) - rank(negative), subindustry)
```

Hypothesis labels:
- `cashflow_quality`: operating cash flow strength minus capex/investment drag.
- `balance_sheet_quality`: cash/cashflow/asset strength minus debt/liability pressure.
- `profitability_quality`: revenue/profitability strength minus cost pressure.
- `working_capital_quality`: cash/cashflow minus receivable/payable pressure.
- `asset_quality`: asset strength minus goodwill/intangible/depreciation risk.

## Efficient Metadata Workflow

Use one metadata fetch to build a local cache:

```powershell
python -m wqb.cli cache-metadata --config configs/stage1_usa_d1.yaml --dataset-id fundamental3 --field-search cash,debt,assets --field-suffix _fast_d1 --max-fields 80 --cache-dir docs/knowledge/cache --skip-data-sets
```

Preview locally without touching the platform:

```powershell
python -m wqb.cli semantic-preview --config configs/stage1_usa_d1.yaml --cache-path docs/knowledge/cache/platform_metadata_YYYYMMDD_HHMMSS.json --dataset-id fundamental3 --field-suffix _fast_d1 --template-mode semantic --max-alphas-per-round 30
```

Run actual simulations using the cached field list:

```powershell
python -m wqb.cli run-field-batch --config configs/stage1_usa_d1.yaml --field-cache-path docs/knowledge/cache/platform_metadata_YYYYMMDD_HHMMSS.json --dataset-id fundamental3 --field-suffix _fast_d1 --template-mode semantic --workflow-stage scout --submit-mode multi --max-alphas-per-round 30
```

Rules:
- Cache metadata before new Scout branches unless a fresh API query is explicitly needed.
- For fields/operators, prefer one larger cache query over many narrow repeated queries.
- For Stage 1 field embedding work, use `--skip-data-sets` unless dataset discovery itself is the task; this avoids letting a slow catalog request block field cache persistence.
- When a cache intentionally combines related searches such as `cash,debt,assets`, omit `--field-search` in `semantic-preview` and `run-field-batch` so the local semantic pairing can compare positive and negative concepts across the combined field pool.
- Simulation and checks still require live platform calls; metadata selection should not.
- Every template batch must preserve its economic hypothesis in `human_idea` and candidate tags.
