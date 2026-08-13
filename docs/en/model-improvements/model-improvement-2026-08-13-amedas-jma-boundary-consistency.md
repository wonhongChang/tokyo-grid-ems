# AMeDAS-JMA Boundary Consistency

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-08-13-amedas-jma-boundary-consistency.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-08-13-amedas-jma-boundary-consistency.md)

## Incident

On 2026-08-13, the served forecast was close to actual demand at 15:00 but rebounded by about 3.1 GW at 16:00. The 15:50 operational snapshot showed that raw LightGBM output jumped from 32,384 MW to 36,889 MW while intraday calibration was already applying a -1,904 MW correction.

The forecast input crossed a weather-source boundary at the same point:

| Hour | Source | Temperature | Discomfort index |
|---|---|---:|---:|
| 15:00 | AMeDAS actual | 24.3 C | 75.3 |
| 16:00 | JMA forecast | about 28.7 C | 81.3 |

The published AMeDAS row at 15:00 was present in the cache, but the generic one-hour observation lag excluded it from the continuity anchor. In addition, continuity correction changed temperature and apparent temperature without recomputing the model's discomfort-index input.

## Change

- Source-tagged `AMEDAS_ACTUAL` rows now use the latest published hour as the observed boundary.
- Forecast correction starts strictly after that latest AMeDAS observation.
- Shrinkage is applied before the configured absolute adjustment cap, so `max_abs_bias_c` is the real final cap.
- After temperature correction, apparent temperature and discomfort index are recomputed from the corrected temperature and humidity.
- Corrected rows receive the `CONTINUITY_CORRECTED` source marker for diagnostics.
- The conservative observation lag remains in place for legacy caches without explicit source metadata.

## Safety Boundary

This change does not smooth the demand curve, alter LightGBM weights, relax published-forecast freeze, or change prediction-band calibration. It only makes weather features internally consistent at an observed-to-forecast source transition. Corrections remain thresholded, capped, limited to the near-term horizon, and decayed by lead hour.

## Verification

The regression fixture reproduces the 2026-08-13 15:50 boundary. The first JMA forecast temperature is limited from 28.7 C to 26.2 C, and the related apparent temperature and discomfort index are recalculated. Existing tests also verify small source transitions and legitimate warming transitions are preserved.
