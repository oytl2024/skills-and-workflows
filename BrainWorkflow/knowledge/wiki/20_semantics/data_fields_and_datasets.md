# Data Fields And Datasets

## Field Metadata To Capture

For each dataset or field family, capture:

- economic meaning,
- data category,
- matrix or vector type,
- coverage,
- date coverage,
- region availability,
- alpha count,
- user count,
- common transformations,
- known correlation risk.

Source: `docs/knowledge/wqb_doc_details_20260702.json`.

## Crowding Interpretation

`Alpha Count` and `User Count` are not direct quality scores. They are crowding signals:

- high count: more known examples, easier to learn, higher production-correlation risk;
- low count: less explored, higher novelty, but possibly weaker or harder data.

## Vector Fields

Vector fields can contain variable-length values for one instrument and date. They need `vec_` operators before ordinary matrix operations. Useful vector operators include `vec_avg`, `vec_sum`, `vec_count`, `vec_max`, `vec_min`, `vec_stddev`, `vec_skewness`, `vec_kurtosis`, `vec_norm`, and related transformations.

Source: `docs/knowledge/wqb_doc_details_20260702.json`.

## Fast D1

Fast D1 fields use the `_fast_d1` suffix. Platform guidance suggests using Fast D1 for high-turnover or event-driven datasets such as news, options, social media sentiment, earnings, and short interest. A delta between Fast D1 and regular D1 can reduce production-correlation risk because it captures the incremental fast signal rather than the common base signal.

Source: `docs/knowledge/wqb_doc_details_20260702.json`.

## New-Data Exploration Rule

Stage-one exploration should begin with economically meaningful new or less-used data. The preferred pattern is:

1. choose a dataset with clear economic meaning and acceptable coverage;
2. choose one simple template;
3. apply it to many fields from that dataset;
4. simulate a 30-alpha batch after local syntax and novelty filtering;
5. promote only signals with strong performance or repairable PnL shape.

