# Correlation And Novelty Benchmarks

## Why This Matters

Self correlation and production correlation are not post-processing details. They directly determine whether a good backtest can become a submit-ready alpha.

## Self-Correlation Risk Factors

Increase risk when a candidate overlaps with the user's submitted or strong near-miss alphas on:

- same dataset family,
- same data field or close sibling field,
- same operator sequence,
- same expression tree shape,
- same neutralization,
- same holding-period behavior,
- same economic hypothesis.

## Production-Correlation Risk Factors

Increase risk when a candidate uses:

- old and heavily explored datasets,
- high `Alpha Count` and `User Count` fields,
- common price-volume templates,
- plain momentum or reversal without a distinctive data source,
- USA/PV combinations without additional novelty,
- popular operator skeletons copied from examples.

## Novelty Score

A local novelty score should be computed before simulation. Initial manual scoring:

- `+2`: dataset family is new or low-crowding;
- `+2`: economic hypothesis is specific and not generic price-volume;
- `+1`: operator family differs from recent own candidates;
- `+1`: event gate or vector transformation is economically meaningful;
- `+1`: region/universe/neutralization choice differs for a reason;
- `-2`: same data family as submitted or strong near-miss alpha;
- `-2`: common template skeleton;
- `-1`: crowded field metadata;
- `-1`: no one-sentence economic rationale.

Only high-novelty candidates should fill scarce simulation and correlation-check slots.

## Implemented Local Gate

The code now has a local novelty scorer in `wqb/novelty.py`. It extracts:

- likely data fields;
- coarse data families such as `price_volume`, `sentiment_attention`, `fundamental`, `options`, and `analyst_revision`;
- operator sequence with repeated operators preserved;
- template key;
- neutralization;
- Fast D1 delta usage;
- event gate usage.

The first implemented score rules are:

- `-2` for overlapping data family against reference records;
- `-2` for highly similar operator template;
- `-1` for same neutralization when template is similar;
- `+2` for a new data family;
- `+2` for Fast D1 delta such as `field_fast_d1 - field`;
- `+1` for distinct operator template;
- `+1` for `trade_when` event gate.

Labels:

- `low_novelty`: score `<= 0`;
- `medium_novelty`: score `1-2`;
- `high_novelty`: score `>= 3`.

`run-expression-file` can now reject low-novelty expressions before live simulation when called with `--novelty-reference-file` and `--min-novelty-score`. Rejections are recorded in `novelty_rejections.jsonl`.

## Benchmark Update Rule

When an alpha fails self or production correlation, update this page or a linked benchmark page with the failure pattern. The next batch generator must automatically avoid or down-rank that pattern.
