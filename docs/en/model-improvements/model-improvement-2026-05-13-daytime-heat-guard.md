# Daytime Heat Guard Improvement

> Operational improvement added after the 2026-05-13 warm-afternoon forecast miss.

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-05-13-daytime-heat-guard.md) · [日本語](../../ja/model-improvements/model-improvement-2026-05-13-daytime-heat-guard.md)

---

## Why This Was Needed

On 2026-05-13, the model under-forecasted Tokyo-area demand during the 11:00-17:00 JST window. The miss was concentrated around the daytime peak:

| Hour | Actual MW | Model MW | Error MW |
|---:|---:|---:|---:|
| 12 | 33,000 | 31,751 | -1,249 |
| 13 | 33,280 | 32,014 | -1,266 |
| 14 | 33,450 | 31,479 | -1,971 |
| 15 | 33,060 | 31,652 | -1,408 |
| 16 | 32,260 | 31,167 | -1,093 |

The important observation was not simply that the model was wrong. The pattern suggested that a warm business afternoon was being pulled down by lag features from a holiday-affected prior week.

## Root Cause

The model uses same-hour historical lag features such as:

- `lag_24h`
- `lag_48h`
- `lag_168h`
- `lag_last_biz_hour`

For 2026-05-13, the `lag_168h` reference pointed to 2026-05-06. That date was still affected by the Golden Week holiday period, so daytime demand was much lower than a normal business day.

At the same time, the 2026-05-13 afternoon had positive temperature anomaly around several daytime hours. This can increase cooling demand even when the full-day average temperature does not look extreme.

In short:

```text
warm business afternoon
+ holiday-contaminated 168h lag
+ analogous-day adjustment allowed to move downward
= under-forecasted daytime demand
```

## Forecasting Change

The improvement is intentionally conservative. It does not add TEPCO forecast values as model features, and it does not replace the LightGBM model.

Instead, `python/forecast/adjustment.py` now adds two guardrails:

1. **Daytime analog matching**
   - Analogous-day candidate selection uses daytime temperature anomaly for the 10:00-17:00 JST window.
   - This avoids diluting a warm afternoon signal with cool overnight or evening hours.

2. **Holiday-lag daytime guard**
   - When the same-hour 168h lag points to a holiday or weekend, and the current daytime temperature anomaly is high, the guard prevents the analogous-day adjustment from pushing the forecast downward.
   - The configured upward offset remains capped and conservative.

Relevant config:

```yaml
adjustment:
  analogous_day:
    daytime_temp_hours: [10, 11, 12, 13, 14, 15, 16, 17]

  post_holiday_timeband_guard:
    daytime:
      min_temp_anomaly_7d: 2.0
      block_negative_shift: true
      activate_on_holiday_lag: true
      upward_offset_mw: 300
      max_upward_offset_mw: 900
```

## Anomaly Detection Change

The same investigation also showed that p95 edge crossings were too sensitive. A 1-50 MW breach of the p95 band could become a warning even though that is not operationally meaningful.

`python/anomaly/detector.py` now requires a p95 breach to exceed either:

- `warning_breach_mw: 150`
- `warning_breach_pct: 0.5`

p99 breaches still use the critical threshold logic.

Relevant config:

```yaml
anomaly:
  spike_drop:
    warning_breach_mw: 150
    warning_breach_pct: 0.5
    critical_breach_mw: 500
    critical_breach_pct: 2.0
```

## Validation

The 2026-05-13 live cache and model were replayed locally.

| Metric | Before | After |
|---|---:|---:|
| 11:00-17:00 MAE | 1,110 MW | 900 MW |
| Alert count | 8 warnings | 4 warnings |

After the change, the remaining alerts were:

- 3 reserve-risk warnings
- 1 residual-drift warning

The tiny p95 edge-crossing spike warnings were removed, while the meaningful sustained under-forecast signal remained visible through drift detection.

Full regression test result:

```text
230 passed
```

## Design Boundary

This change keeps a clear boundary:

- TEPCO forecast values are still comparison data.
- TEPCO forecast values may still be used as temporary fallback actuals when an hour such as 23:00 has not been finalized yet.
- TEPCO forecast values are not used to blend or improve the model forecast directly.

That keeps the project explainable as a public-data forecasting pipeline rather than a TEPCO-forecast blending wrapper.
