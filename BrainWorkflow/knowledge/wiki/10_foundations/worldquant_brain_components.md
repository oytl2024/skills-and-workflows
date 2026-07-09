# WorldQuant BRAIN Components

## Alpha

An alpha is a mathematical model that assigns one value per instrument per day. The sign indicates long or short direction, and magnitude affects position sizing after platform processing. This model is expressed in Fast Expression syntax using data fields, operators, numeric constants, and settings.

Source: `docs/knowledge/wqb_doc_search_snapshot_20260702.json`.

## Fast Expression

Fast Expression combines data fields, operators, and values. The practical analogy from platform docs is similar to subject, verb, and object in language: data fields are the objects being transformed, operators are actions, and settings define the simulation environment.

Source: `docs/knowledge/wqb_doc_details_20260702.json`.

## Data Field

A data field is a named collection of data such as open price, close price, analyst values, news values, or event-derived values. A field can be matrix-like or vector-like. Vector fields must be converted with `vec_` operators before ordinary matrix operators.

Source: `docs/knowledge/wqb_doc_details_20260702.json`.

## Dataset

A dataset is a collection of related fields. The platform data page exposes metadata such as coverage, date coverage, description, alpha count, and user count. Low alpha count can indicate untapped potential; high user count can indicate crowding and production-correlation risk.

Source: `docs/knowledge/wqb_doc_details_20260702.json`.

## Simulation

Simulation evaluates an expression under a chosen region, universe, delay, neutralization, decay, truncation, pasteurization, NaN handling, unit handling, and related settings. A simulation result is not submit-ready unless it also passes required checks.

## Submission Candidate

For this project, an alpha enters the candidate submission list only after it passes all required platform tests, including performance, turnover, sub-universe, weight, self correlation, and production correlation where applicable.

