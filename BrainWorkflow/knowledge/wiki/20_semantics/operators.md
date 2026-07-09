# Operators

## Operator Semantic Record

Each operator should eventually have:

- name,
- category,
- input type,
- output type,
- plain-language meaning,
- common use,
- common failure mode,
- correlation risk,
- safer alternatives.

Source for initial definitions: `docs/knowledge/cache/platform_metadata_20260702_014429.json`.

## Important Operator Families

### Cross-Sectional

Operators such as `rank`, `zscore`, and group operations compare instruments on the same date. They are useful for building relative-value alphas but can become crowded if used with common price-volume fields.

### Time-Series

Operators such as `ts_mean`, `ts_delta`, `ts_rank`, `ts_corr`, and `ts_decay_linear` transform each instrument over time. Documentation metadata defines `ts_corr` as Pearson correlation over the past `d` days.

### Group

Group operators can neutralize or rank within sector, industry, subindustry, country, or other groupings. They reduce broad exposure and may reduce correlation when used with a distinct data source and economic story.

### Vector

`vec_` operators convert variable-length event fields into matrix-like values. These are essential for event datasets and new data exploration.

### Event / Conditional

Operators such as `trade_when` can activate a signal only when an economic event or data condition is present. This can reduce turnover and correlation when the event condition is meaningful.

## Simplicity Bias

Forum experience and current project evidence both favor simple, explainable templates. A template should usually be explainable in one sentence before it is simulated.

