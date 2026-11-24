# Validation results (simulation only)

Generated 2026-11-22 16:07 by `scripts/validate.py` on Python 3.12.3.

All quakes come from the **validation** random stream, which was not used to choose any threshold. The server saw only phone reports and per-cell phone counts. **These numbers describe our simulation, not real earthquakes.**

## Baseline (K = 10)

| Measure | Result | Proposed target | |
|---|---|---|---|
| median_error_km | 1.62 | <= 3.0 | PASS |
| p90_error_km | 3.16 | <= 8.0 | PASS |
| missed_inside_network_pct | 0.00 | <= 2.0 | PASS |
| false_reassurance_pct | 0.50 | <= 1.0 | PASS |
| within_predicted_error_pct | 93.97 | 85.0-99.0 | PASS |
| false alerts at K=10 (hours with any) | 0 | 0 | PASS |

Other measures: 200 quakes, 187 inside the phone network (at least 20 phones within 30 km), 199 alerted; median alert 5.89 s after the quake started; average origin-time error 0.81 s (positive = estimated later than true; mostly the phones' detection delay, which the server does not model).

## The report threshold K (the slider)

100 hidden quakes per K, and 20 simulated hours of noise (no earthquake) to count false alerts.

| K | Alerted | Median error (km) | 90th pct error (km) | Median alert delay (s) | Noise hours with a false alert |
|---|---|---|---|---|---|
| 4 | 100/100 | 1.91 | 3.73 | 5.78 | 0 of 20 |
| 6 | 100/100 | 1.79 | 3.73 | 5.79 | 0 of 20 |
| 10 | 100/100 | 1.59 | 2.55 | 6.12 | 0 of 20 |
| 20 | 100/100 | 1.06 | 2.28 | 6.99 | 0 of 20 |
| 40 | 100/100 | 0.95 | 2.40 | 8.28 | 0 of 20 |

## Robustness sweeps (K = 10, no pass/fail)

50 hidden quakes per row.

| Condition | Inside network | Alerted | Missed inside (%) | Median error (km) | 90th pct error (km) | Median alert delay (s) |
|---|---|---|---|---|---|---|
| Baseline | 48 | 49 | 0.0 | 1.37 | 4.38 | 5.96 |
| 50 % of phones online | 48 | 50 | 0.0 | 1.60 | 3.62 | 6.89 |
| 25 % of phones online | 48 | 48 | 2.1 | 1.68 | 4.57 | 7.76 |
| 10 % of phones online | 48 | 42 | 12.5 | 2.08 | 7.63 | 8.85 |
| Upload delays x2 | 48 | 49 | 0.0 | 1.48 | 3.41 | 7.15 |
| Upload delays x4 | 48 | 49 | 0.0 | 1.45 | 4.16 | 9.55 |
| Clock error 0.2 s | 48 | 49 | 0.0 | 1.59 | 3.55 | 5.94 |
| Clock error 0.5 s | 48 | 49 | 0.0 | 3.29 | 5.34 | 6.14 |
| False reports x5 | 48 | 49 | 0.0 | 1.19 | 2.90 | 6.34 |
| False reports x20 | 48 | 39 | 18.8 | 0.82 | 2.23 | 8.62 |
| Late S-wave reports 10 % | 48 | 49 | 0.0 | 1.43 | 3.99 | 6.00 |
| Late S-wave reports 30 % | 48 | 50 | 0.0 | 1.51 | 3.22 | 6.28 |
| Towns only (no countryside phones) | 15 | 9 | 73.3 | 7.29 | 11.83 | 7.77 |
| Inverse-crime check: true speeds = assumed, depth = 10 km | 48 | 50 | 0.0 | 1.25 | 2.80 | 5.67 |

## How to read this

- **Inside network** means at least 20 phones within 30 km of the epicentre. Quakes outside it are harder, and are not counted as missed if no alert is sent.
- The **inverse-crime check** gives the server a perfect model. Its errors should be smaller than the baseline's; the gap shows how much the deliberately imperfect model costs, and that we did not test with the same model we solve with.
- Thresholds were tuned on the tuning stream; targets were set before this run. A FAIL is reported as it is, not hidden by changing the target.

## Validation history (disclosed)

This validation stream was run three times during development. Each time it revealed a weakness, the fix was chosen using the **tuning** stream only, then validation was run again:
1. First run: with phones only in towns, alerts had a median error of 18.2 km and a 90th percentile of 71.5 km (wrong estimates in empty countryside passed the silent-phones check because no phones were there to be silent). Fix: also require reports from near the estimate.
2. Second run: requiring a fixed 5 nearby reports made sparse networks miss many quakes (25 % missed with a quarter of phones online, 69 % with a tenth). Fix: require 5, or 30 % of the active phones actually near the estimate if that is fewer (at least 1).
3. This file is the third run.

Run time: 606 s.
