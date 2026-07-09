# Template Families

## Template Record Format

Each template should be recorded with:

- economic hypothesis,
- expression skeleton,
- expected direction,
- required field type,
- useful settings,
- known failure modes,
- correlation risk,
- repair levers,
- experiment links.

## Preferred Stage-One Template Types

### Event Surprise

Hypothesis: sudden event-driven information changes future returns before the market fully incorporates it.

Useful data: news, options, earnings, short interest, social sentiment, Fast D1 deltas.

Correlation advantage: less likely to match old price-volume templates when the data source and event gate are distinct.

### Slow Fundamental Repricing

Hypothesis: improvements or deterioration in fundamental expectations are incorporated gradually.

Useful data: analyst estimates, fundamentals, quality, growth, profitability, revisions.

Correlation risk: high if implemented as a common analyst-revision rank without novel data or settings.

### Liquidity / Attention Imbalance

Hypothesis: abnormal attention or trading pressure predicts short-term continuation or reversal.

Useful data: volume, short interest, options, news counts, social media, event counts.

Correlation risk: high for plain price-volume versions; lower for new data and event-conditioned variants.

### Risk Compression / Expansion

Hypothesis: changes in uncertainty, volatility, or dispersion carry predictive information.

Useful data: options, estimates dispersion, sentiment dispersion, news volume, vector event distributions.

Correlation risk: moderate; reduce it by using less-common uncertainty proxies and nonstandard neutralization.

## Anti-Pattern

Do not generate many arbitrary formula mutations without an economic hypothesis. Random variation may create in-sample performance but tends to waste simulation budget and produce high production correlation.

