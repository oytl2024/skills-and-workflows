# Official Operator Catalog

Generated at: `2026-07-09T10:03:26+00:00`

Raw source: `knowledge/rawmaterial/learn/operators.json`.

Use this catalog as the local source for operator names, categories, scopes, definitions, descriptions, documentation fields, and level restrictions.

## Arithmetic

### `abs`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `abs(x)`
- Description: Returns the absolute value of a number, removing any negative sign.
- Documentation: /operators/abs

### `add`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `add(x, y, filter = false), x + y`
- Description: Adds two or more inputs element wise. Set filter=true to treat NaNs as 0 before summing.
- Documentation: /operators/add

### `densify`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `densify(x)`
- Description: Converts a grouping field of many buckets into lesser number of only available buckets so as to make working with grouping fields computationally efficient
- Documentation: /operators/densify

### `divide`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `divide(x, y), x / y`
- Description: x / y

### `inverse`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `inverse(x)`
- Description: 1 / x

### `log`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `log(x)`
- Description: Calculates the natural logarithm of the input value. Commonly used to transform data that has positive values.
- Documentation: /operators/log

### `max`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `max(x, y, ..)`
- Description: Maximum value of all inputs. At least 2 inputs are required
- Documentation: /operators/max

### `min`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `min(x, y ..)`
- Description: Minimum value of all inputs. At least 2 inputs are required
- Documentation: /operators/min

### `multiply`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `multiply(x ,y, ... , filter=false), x * y`
- Description: Multiplies two or more inputs element wise. Set filter=true to treat NaNs as 0 before multiplication
- Documentation: /operators/multiply

### `power`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `power(x, y)`
- Description: x ^ y
- Documentation: /operators/power

### `reverse`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `reverse(x)`
- Description: - x

### `sigmoid`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: unspecified
- Definition: `sigmoid(x)`
- Description: Returns 1 / (1 + exp(-x))

### `sign`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `sign(x)`
- Description: Returns the sign of a number: +1 for positive, -1 for negative, and 0 for zero. If the input is NaN, returns NaN. Input: Value of 7 instruments at day t: (2, -3, 5, 6, 3, NaN, -10) Output: (1, -1, 1, 1, 1, NaN, -1)
- Documentation: /operators/sign

### `signed_power`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `signed_power(x, y)`
- Description: x raised to the power of y such that final result preserves sign of x
- Documentation: /operators/signed_power

### `sqrt`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `sqrt(x)`
- Description: Returns the non negative square root of x. Equivalent to power(x, 0.5); for signed roots use signed_power(x, 0.5).
- Documentation: /operators/sqrt

### `subtract`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `subtract(x, y, filter=false), x - y`
- Description: Subtracts inputs left to right: x ? y ? … Supports two or more inputs. Set filter=true to treat NaNs as 0 before subtraction.
- Documentation: /operators/subtract

### `tanh`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: unspecified
- Definition: `tanh(x)`
- Description: Hyperbolic tangent of x
- Documentation: /operators/tanh

## Cross Sectional

### `normalize`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `normalize(x, useStd = false, limit = 0.0)`
- Description: Centers a daily cross section by subtracting the market mean; optionally divide by the cross sectional standard deviation and clamp the result to [?limit, +limit]. NaNs are ignored in mean/std.
- Documentation: /operators/normalize

### `quantile`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `quantile(x, driver = gaussian, sigma = 1.0)`
- Description: Ranks and shifts a vector of Alpha values, then applies a chosen statistical distribution (gaussian, cauchy, or uniform) to reduce outliers. The sigma parameter controls the scale of the output.
- Documentation: /operators/quantile

### `rank`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `rank(x, rate=2)`
- Description: Ranks the values of the input x among all instruments, returning numbers evenly spaced between 0.0 and 1.0. Useful for normalizing data and reducing the impact of outliers.
- Documentation: /operators/rank

### `regression_proj`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `regression_proj(y, x)`
- Description: Conducts the cross-sectional regression on the stocks with Y as target and X as the independent variable
- Documentation: /operators/regression_proj

### `scale`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `scale(x, scale=1, longscale=1, shortscale=1)`
- Description: Scales the input so that the sum of absolute values across all instruments equals a specified book size. Allows separate scaling for long and short positions using optional parameters.
- Documentation: /operators/scale

### `vector_proj`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `vector_proj(x, y)`
- Description: Returns vector projection of x onto y.

### `winsorize`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `winsorize(x, std=4)`
- Description: Winsorize limits values in a data to within a specified number of standard deviations from the mean, reducing the impact of extreme outliers.
- Documentation: /operators/winsorize

### `zscore`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `zscore(x)`
- Description: Z-score is a numerical measurement that describes a value's relationship to the mean of a group of values. Z-score is measured in terms of standard deviations from the mean
- Documentation: /operators/zscore

## Group

### `combo_a`
- Scope: ['COMBO']
- Level: ALL
- Definition: `combo_a(alpha, nlength = 250, mode = 'algo1')`
- Description: Combines multiple alpha signals into a single weighted output by balancing each alpha's historical return with its variability over the most recent nlength days. The parameter mode selects one of the several weighted approaches (algo1, algo2, algo3), each of which handles the tradeoff between performance and stability differently.

### `group_backfill`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `group_backfill(x, group, d, std = 4.0)`
- Description: Fills missing (NaN) values for instruments within the same group by calculating a winsorized mean of all non-NaN values over the past d days. The winsorized mean is computed by trimming extreme values based on a specified standard deviation multiplier (std, default 4.0).
- Documentation: /operators/group_backfill

### `group_cartesian_product`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `group_cartesian_product(g1, g2)`
- Description: Merge two groups into one group. If originally there are len_1 and len_2 group indices in g1 and g2, there will be len_1 * len_2 indices in the new group.

### `group_extra`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `group_extra(x, weight, group)`
- Description: Replaces NaN values by their corresponding group means.

### `group_mean`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `group_mean(x, weight, group)`
- Description: Calculates the harmonic mean of a data field within each specified group.
- Documentation: /operators/group_mean

### `group_neutralize`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `group_neutralize(x, group)`
- Description: Neutralizes Alpha values within each specified group by subtracting the group mean from each value. Groups can be industry, sector, country, or any custom grouping.
- Documentation: /operators/group_neutralize

### `group_rank`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `group_rank(x, group)`
- Description: Ranks each element within its group based on the input field, assigning a value between 0.0 and 1.0. This helps compare items within the same group, such as stocks in the same industry.
- Documentation: /operators/group_rank

### `group_scale`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `group_scale(x, group)`
- Description: Normalizes values within each group to a range between 0 and 1, making data comparable across different groups.
- Documentation: /operators/group_scale

### `group_zscore`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `group_zscore(x, group)`
- Description: Calculates the Z-score of each value within its group, showing how far each value is from the group mean in terms of standard deviations. Useful for comparing values relative to their group.
- Documentation: /operators/group_zscore

## Logical

### `and`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `and(input1, input2)`
- Description: Returns 1 ('true') if both inputs are 1 ('true'). Otherwise, returns 0 ('false').

### `equal`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `input1 == input2`
- Description: Returns 1 ('true') if input1 and input2 are the same. Otherwise, returns 0 ('false').

### `greater`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `input1 > input2`
- Description: Returns 1 ('true') if input1 is a larger than input2. Otherwise, returns 0 ('false').

### `greater_equal`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `input1 >= input2`
- Description: Returns 1 ('true') if input1 is a larger or the same as input2. Otherwise, returns 0 ('false').

### `if_else`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `if_else(input1, input2, input 3)`
- Description: The if_else operator returns one of two values based on a condition. If the condition is true, it returns the first value; if false, it returns the second value.
- Documentation: /operators/if_else

### `is_nan`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `is_nan(input)`
- Description: If (input == NaN) return 1 else return 0
- Documentation: /operators/is_nan

### `less`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `input1 < input2`
- Description: Returns 1 ('true') if input1 is a smaller than input2. Otherwise, returns 0 ('false').

### `less_equal`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `input1 <= input2`
- Description: Returns 1 ('true') if input1 is a smaller or the same as input2. Otherwise, returns 0 ('false').

### `not`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `not(x)`
- Description: Returns the logical negation of x. Returns 0 when x is 1 (‘true’) and 1 when x is 0 (‘false’).

### `not_equal`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `input1!= input2`
- Description: Returns 1 ('true') if input1 and input2 are different numbers. Otherwise, returns 0 ('false').

### `or`
- Scope: ['COMBO', 'REGULAR', 'SELECTION']
- Level: ALL
- Definition: `or(input1, input2)`
- Description: Returns 1 if either input is true (either input1 or input2 has a value of 1), otherwise it returns 0.

## Reduce

### `reduce_avg`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_avg(input, threshold=0)`
- Description: Average of non-NAN elements of d(..., :). Threshold: Minimum required number of valid (non-nan) values. If there is not enough valid values, then the output is nan. 0 means no limit.threshold (Default: 0) *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_choose`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_choose(input, nth, ignoreNan=true)`
- Description: Choose the 'nth' element in the array, return NAN if not found. Threshold: nth=" " (Required) ignoreNan="true|false" (Default: true) *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_count`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_count(input, threshold)`
- Description: Count the number of element of d(..., :) > threshold. threshold= *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_ir`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_ir(input)`
- Description: IR of values in the array *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_kurtosis`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_kurtosis(input)`
- Description: Kurtosis of values in the array ***Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. If input matrix is (D x N), output matrix (D x 1) If input matrix is (D x N X N), output matrix (D x N X 1) The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_max`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_max(input)`
- Description: Maximum of elements of d(..., :) *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_min`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_min(input)`
- Description: Minimum of elements of d(..., :) ***Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. If input matrix is (D x N), output matrix (D x 1) If input matrix is (D x N X N), output matrix (D x N X 1) The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_norm`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_norm(input)`
- Description: Absolute sum of number of element of d(..., :) *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_percentage`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_percentage(input, percentage=0.5)`
- Description: Return the value of percentage in the sorted array: e.g., median value when percentage=0.5. Threshold: percentage=" " (Default: 0.5) *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_powersum`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_powersum(input, constant=2, precise=false)`
- Description: Sum of power, sum(power(x, constant)). Threshold: precise, whether calculate power precise if constant greater than 4, default false constant= , default:2 *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_range`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_range(input)`
- Description: Return the range of values in the array, return NAN if no valid value *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_skewness`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_skewness(input)`
- Description: Skewness of values in the array *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_stddev`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_stddev(input, threshold=0)`
- Description: Standard deviation of values in the array. Threshold: Minimum required percentage of valid (non-nan) values. If there is not enough valid values, then the output is NAN. 0 means no limit.threshold (Default: 0) *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

### `reduce_sum`
- Scope: ['COMBO']
- Level: ALL
- Definition: `reduce_sum(input)`
- Description: Sum the number of element of d(..., :) *** Takes an input 2-D or 3-D matrix with user-defined reducer, producing an output matrix. *If input matrix is (D x N), output matrix (D x 1) *If input matrix is (D x N X N), output matrix (D x N X 1) *The defined function is applied on the last dimension : output(I) = reduce(input(I, 0:N)).

## Special

### `in`
- Scope: ['SELECTION']
- Level: ALL
- Definition: `in`
- Description: in

### `inst_pnl`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `inst_pnl(x)`
- Description: Generate pnl per instruments. Please note that the use of the inst_pnl() operator in an Alpha Expression is considered as utilizing the pv1 dataset (Price Volume Data for Equity) since it relies on pv1 data for calculations.

### `self_corr`
- Scope: ['COMBO']
- Level: ALL
- Definition: `self_corr(input)`
- Description: Taking an input matrix of (D x N) with lookback="K", producing an output matrix of (D x N x N), where each output(di, j, k) refers to correlation of input(di-K:di, j) and input(di-K:di, k). Outputs (D x N x N) from the input of (D x N)

### `universe_size`
- Scope: ['SELECTION']
- Level: ALL
- Definition: `universe_size`
- Description: universe_size

## Time Series

### `days_from_last_change`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `days_from_last_change(x)`
- Description: Calculates the number of days since the last change in the value of a given variable.
- Documentation: /operators/days_from_last_change

### `hump`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `hump(x, hump = 0.01)`
- Description: Limits amount and magnitude of changes in input (thus reducing turnover)
- Documentation: /operators/hump

### `hump_decay`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `hump_decay(x, p=0)`
- Description: This operator helps to ignore the values that changed too little corresponding to previous ones
- Documentation: /operators/hump_decay

### `kth_element`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `kth_element(x, d, k, ignore=“NaN”)`
- Description: Returns the K-th value from a time series by looking back over a specified number of (‘d’) days, with the option to ignore certain values. Commonly used for backfilling missing data.
- Documentation: /operators/kth_element

### `last_diff_value`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `last_diff_value(x, d)`
- Description: Returns the most recent value of x from the past d days that is different from the current value of x.
- Documentation: /operators/last_diff_value

### `ts_arg_max`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_arg_max(x, d)`
- Description: Returns the number of days since the maximum value occurred in the last d days of a time series. If today's value is the maximum, returns 0; if it was yesterday, returns 1, and so on.
- Documentation: /operators/ts_arg_max

### `ts_arg_min`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_arg_min(x, d)`
- Description: Returns the number of days since the minimum value occurred in a time series over the past d days. If today's value is the minimum, returns 0; if it was yesterday, returns 1, and so on.
- Documentation: /operators/ts_arg_min

### `ts_av_diff`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_av_diff(x, d)`
- Description: Calculates the difference between a value and its mean over a specified period, ignoring NaN values in the mean calculation. In short, it returns x – ts_mean(x, d) with NaNs ignored.
- Documentation: /operators/ts_av_diff

### `ts_backfill`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_backfill(x,lookback = d, k=1)`
- Description: Replaces missing (NaN) values in a time series with the most recent valid value from a specified lookback window, improving data coverage and reducing risk from missing data.
- Documentation: /operators/ts_backfill

### `ts_corr`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_corr(x, y, d)`
- Description: Calculates the Pearson correlation between two variables, x and y, over the past d days, showing how closely they move together.
- Documentation: /operators/ts_corr

### `ts_count_nans`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_count_nans(x ,d)`
- Description: Counts the number of missing (NaN) values in a data series over a specified number of days.
- Documentation: /operators/ts_count_nans

### `ts_covariance`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_covariance(y, x, d)`
- Description: Calculates the covariance between two time-series variables, y and x, over the past d days. Useful for measuring how two variables move together within a specified historical window.
- Documentation: /operators/ts_covariance

### `ts_decay_exp_window`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `ts_decay_exp_window(x, d, factor = f)`
- Description: Returns exponential decay of x with smoothing factor for the past d days
- Documentation: /operators/ts_decay_exp_window

### `ts_decay_linear`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_decay_linear(x, d, dense = false)`
- Description: Applies a linear decay to time-series data over a set number of days, smoothing the data by averaging recent values and reducing the impact of older or missing data.
- Documentation: /operators/ts_decay_linear

### `ts_delay`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_delay(x, d)`
- Description: Returns the value of a variable x from d days ago. Use this operator to access historical data points by specifying the desired time lag in days.
- Documentation: /operators/ts_delay

### `ts_delta`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_delta(x, d)`
- Description: Calculates the difference between a value and its delayed version over a specified period. Useful for measuring changes or momentum in time-series data.
- Documentation: /operators/ts_delta

### `ts_entropy`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `ts_entropy(x,d)`
- Description: For each instrument, we collect values of input in the past d days and calculate the probability distribution then the information entropy via a histogram as a result
- Documentation: /operators/ts_entropy

### `ts_mean`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_mean(x, d)`
- Description: Calculates the simple average (mean) value of a variable x over the past d days.
- Documentation: /operators/ts_mean

### `ts_min_diff`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `ts_min_diff(x, d)`
- Description: Returns x - ts_min(x, d)

### `ts_min_max_cps`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `ts_min_max_cps(x, d, f = 2)`
- Description: Returns (ts_min(x, d) + ts_max(x, d)) - f * x. If not specified, by default f = 2

### `ts_min_max_diff`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `ts_min_max_diff(x, d, f = 0.5)`
- Description: Returns x - f * (ts_min(x, d) + ts_max(x, d)). If not specified, by default f = 0.5

### `ts_product`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_product(x, d)`
- Description: Returns the product of the values of x over the past d days. Useful for calculating geometric means and compounding returns or growth rates.
- Documentation: /operators/ts_product

### `ts_quantile`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_quantile(x,d, driver="gaussian" )`
- Description: Calculates the ts_rank of the input and transforms it using the inverse cumulative distribution function (quantile function) of a specified probability distribution (default: Gaussian/normal). This helps to normalize or reshape the distribution of your data over a rolling window.
- Documentation: /operators/ts_quantile

### `ts_rank`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_rank(x, d, constant = 0)`
- Description: Ranks the value of a variable for each instrument over a specified number of past days, returning the rank of the current value (optionally adjusted by a constant). Useful for normalizing time-series data and highlighting relative performance over time.
- Documentation: /operators/ts_rank

### `ts_regression`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_regression(y, x, d, lag = 0, rettype = 0)`
- Description: Returns various parameters related to regression function
- Documentation: /operators/ts_regression

### `ts_scale`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_scale(x, d, constant = 0)`
- Description: Scales a time series to a 0–1 range based on its minimum and maximum values over a specified period, with an optional constant shift.
- Documentation: /operators/ts_scale

### `ts_skewness`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `ts_skewness(x, d)`
- Description: Return skewness of x for the past d days
- Documentation: /operators/ts_skewness

### `ts_std_dev`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_std_dev(x, d)`
- Description: Calculates the standard deviation of a data series x over the past d days, measuring how much the values deviate from their mean during that period.
- Documentation: /operators/ts_std_dev

### `ts_step`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_step(1)`
- Description: Returns a counter of days, incrementing by one each day.
- Documentation: /operators/ts_step

### `ts_sum`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_sum(x, d)`
- Description: Sum values of x for the past d days.

### `ts_target_tvr_decay`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `ts_target_tvr_decay(x, lambda_min=0, lambda_max=1, target_tvr=0.1)`
- Description: Tune "ts_decay" to have a turnover equal to a certain target, with optimization weight range between lambda_min, lambda_max

### `ts_target_tvr_delta_limit`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `ts_target_tvr_delta_limit(x, y, lambda_min=0, lambda_max=1, target_tvr=0.1)`
- Description: Tune "ts_delta_limit" to have a turnover equal to a certain target with optimization weight range between lambda_min, lambda_max. Also, please be aware of the scaling for x and y. Besides setting y as adv20 or volume related data, you can also set y as a constant.

### `ts_target_tvr_hump`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `ts_target_tvr_hump(x, lambda_min=0, lambda_max=1, target_tvr=0.1)`
- Description: Tune "hump" to have a turnover equal to a certain target with optimization weight range between lambda_min, lambda_max.

### `ts_zscore`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `ts_zscore(x, d)`
- Description: Calculates the Z-score of a time series, showing how far today's value is from the recent average, measured in standard deviations. Useful for standardizing and comparing values over time.
- Documentation: /operators/ts_zscore

## Transformational

### `bucket`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `bucket(rank(x), range=“0, 1, 0.1”, skipBoth=False, NaNGroup=False) or bucket(rank(x), buckets = “2,5,6,7,10”, skipBoth=False, NaNGroup=False)`
- Description: The bucket operator creates custom groups by dividing data into buckets (ranges) based on ranked values of any data field. These buckets can then be used with group operators like group_neutralize, group_rank, group_zscore etc.
- Documentation: /operators/bucket

### `generate_stats`
- Scope: ['COMBO']
- Level: ALL
- Definition: `generate_stats(alpha)`
- Description: The generate_stats() operator calculates Alpha statistics for each day in the IS period. It takes an input of selected Alphas with shape = (A x D x I). It outputs daily statistics for each Alpha with shape = (S x D x A), where S is the number of statistics calculated.

### `trade_when`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `trade_when(x, y, z)`
- Description: The trade_when operator changes Alpha values only when a specific condition is met, keeps previous values otherwise, and can close positions by assigning NaN under an exit condition. It is useful for reducing turnover and controlling when trades are executed.
- Documentation: /operators/trade_when

## Vector

### `vec_avg`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `vec_avg(x)`
- Description: Calculates the mean (average) of all elements in a vector field for each instrument and date, converting vector data to a single matrix value.
- Documentation: /operators/vec_avg

### `vec_count`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `vec_count(x)`
- Description: Number of elements in vector field x

### `vec_max`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `vec_max(x)`
- Description: Maximum value form vector field x

### `vec_min`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `vec_min(x)`
- Description: Minimum value form vector field x

### `vec_range`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `vec_range(x)`
- Description: Difference between maximum and minimum element in vector field x

### `vec_stddev`
- Scope: ['COMBO', 'REGULAR']
- Level: unspecified
- Definition: `vec_stddev(x)`
- Description: Standard Deviation of vector field x

### `vec_sum`
- Scope: ['COMBO', 'REGULAR']
- Level: ALL
- Definition: `vec_sum(x)`
- Description: Calculates the sum of all values in a vector field.
- Documentation: /operators/vec_sum
