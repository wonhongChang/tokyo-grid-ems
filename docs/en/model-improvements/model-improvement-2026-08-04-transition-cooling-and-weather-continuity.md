# Transition Cooling Attenuation and Weather Continuity

## Incident

The 2026-08-03 business-day forecast overpredicted all 24 completed hours. Its served MAE was 1,668.7 MW, its mean bias was +1,668.7 MW, and TEPCO had the lower absolute error in 21 of 24 hours. The error was already present at midnight and expanded again from late morning through evening. On 2026-08-04, the first 16 completed hours had a smaller but still positive bias, with the largest misses at 06:00 and 07:00.

TEPCO forecasts were used only as an external benchmark. They were not used as model inputs, targets, anchors, or calibration values.

## Root-cause separation

Two independent mechanisms were found.

1. The business-day q50 contract blended absolute-demand q50 with `lag_24h + residual q50` at a fixed 50:50 ratio. On the Sunday-to-Monday transition, the residual estimate raised q50 by as much as roughly 3.7 GW above the absolute-demand estimate even though `cooling_delta_24h` was around -8 to -10 C. Intraday correction reached its -1,200 MW cap, but the raw miss was too large for that controller to recover.
2. The operational weather cache replaced past forecast rows with AMeDAS observations before the old forecast-bias comparison ran. The comparison therefore often measured an observation against itself and produced zero bias. At the 2026-08-03 morning boundary, AMeDAS was 22.9 C at 07:00 while the first JMA forecast row jumped to 26.1 C at 08:00. That discontinuity amplified weather-sensitive inference and also contributed to the rejected weekly Challenger's prediction drift.

Published-forecast freeze was not the primary cause. It preserved already published points, but future points were being reduced by intraday correction. The dominant problem remained the raw q50 level.

## Changes

### 1. Transition-aware residual weight

The v13 Challenger keeps the normal residual blend on ordinary business days. Only business days whose previous day has a different business type receive a row-level weight:

```text
effective_weight = configured_weight * clip((cooling_delta_24h - (-4)) / (0 - (-4)), 0, 1)
```

- `cooling_delta_24h >= 0 C`: retain the configured 0.5 weight.
- `cooling_delta_24h <= -4 C`: use the absolute-demand q50 without the residual blend.
- Between -4 and 0 C: attenuate continuously.

This is part of the v13 model contract. It is not forced onto the current v11 Champion and must pass the promotion gates before serving.

### 2. AMeDAS-to-JMA continuity correction

For the first same-day JMA forecast after recent AMeDAS observations:

- estimate the recent observed temperature slope from up to three consecutive hourly changes;
- clip the observed slope to +/-1.0 C/hour;
- compare the projected next observation with the first JMA forecast;
- intervene only when the gap is at least 1.5 C;
- cap the gap at +/-2.5 C, apply 70% shrinkage, and decay it by 0.6 for the next three hours.

The correction changes only the in-memory model input. It does not overwrite AMeDAS observations, persisted source temperatures, or dashboard weather values.

## Validation

### q50 temporal replay

| Window | Metric | Previous contract | v13 | Result |
|---|---:|---:|---:|---|
| 28 days | Overall MAE | 1,070.3 MW | 1,036.6 MW | improved |
| 28 days | Transition MAE | 1,602.9 MW | 1,366.7 MW | improved |
| 28 days | Cooler-transition MAE | 2,509.8 MW | 1,424.0 MW | improved |
| 84 days | Overall MAE | 720.3 MW | 709.7 MW | improved |
| 84 days | Transition MAE | 903.5 MW | 829.6 MW | improved |
| 84 days | Cooler-transition MAE | 1,643.1 MW | 1,192.3 MW | improved |

The 84-day gate passed. The latest 28-day result still exceeded the 1,000 MW absolute MAE limit by 36.6 MW, so the Challenger remains rejected and v11 remains the Champion. The threshold was not relaxed to make this change pass.

On 2026-08-03, the same trained validation model improved from 2,865.3 MW MAE with the full residual blend to 1,973.8 MW with attenuation. It still overpredicted, confirming that attenuation fixes a major amplifier but does not claim to solve every base-model error.

### Weather snapshot replay

Across 18 available live ETL forecast-to-observation comparisons, the near-term temperature MAE fell from 1.926 C to 1.302 C and the maximum error fell from 4.00 C to 2.95 C. Eighteen comparisons improved and none worsened under the selected threshold, cap, shrinkage, and decay settings.

## Rejected alternatives

- Disabling the residual model for every business-type transition degraded transitions that were not cooler.
- A dedicated business-return q50 model worsened both aggregate replay and 2026-08-03.
- Removing humidity and discomfort features globally degraded the long-window replay.
- Restricting training to 180, 365, or 730 days degraded the 28-day replay relative to the full history.
- Extra transition interaction features and changes to LightGBM leaf complexity did not pass the absolute gate.
- The promotion threshold and prediction-drift limits were not loosened.

## Operational status

- The weather continuity correction becomes active in ETL and intraday inference after deployment.
- The q50 change remains a Challenger contract until the normal weekly promotion process passes temporal, segment, absolute-quality, and prediction-drift gates.
- Continue tracking business-return days, especially sharply cooler transitions, separately from ordinary business days.

