# Business-Return Observed Overforecast Veto

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-08-12-business-return-observed-overforecast-veto.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-08-12-business-return-observed-overforecast-veto.md)

## Incident

On 2026-08-12, the first business day after Mountain Day, the business-return anchor correctly recognized that lag-24 came from a holiday. However, same-day observations already showed that the forecast level was high:

- at 07:00, the pre-shortfall forecast was 27,498.3 MW against 25,380 MW actual demand, an overforecast of 2,118.3 MW;
- the anchor-shortfall layer still added 1,000 MW at 08:00 and 09:00;
- the post-holiday stage error at 08:00 was therefore 3,899 MW, and the later finalized 09:00 actual showed a 3,364.6 MW stage error.

The holiday-to-business prior and the same-day evidence were pointing in opposite directions. The prior remained useful before the morning ramp was observed, but its supplemental lift was no longer justified after a large observed overforecast.

## Change

Inference context now carries `same_day_latest_actual_mw` alongside `same_day_latest_actual_hour`. The `business_return_anchor_shortfall` layer evaluates an `observed_overforecast_veto` before applying its lift.

The veto is active only when all of the following are true:

- the existing business-return shortfall conditions already qualify;
- the latest observed reference bucket is hour 07 or later;
- the target is one to three hours ahead of that reference;
- the pre-shortfall forecast at the reference hour exceeds actual demand by at least 1,200 MW.

When active, the controller skips only the supplemental business-return lift for that target hour. It does not lower raw LightGBM output, alter the analogous-day result, widen or narrow intervals, change the global intraday residual cap, or use the TEPCO forecast.

## Configuration

```yaml
observed_overforecast_veto:
  enabled: true
  min_reference_hour: 7
  max_lead_hours: 3
  min_overforecast_mw: 1200
```

The high evidence threshold and short lead window keep the veto local. Smaller misses preserve the existing anchor-shortfall behavior.

## Operational Replay

The retained 21-day forecast-snapshot window contained one finalized target hour that satisfied the new condition. Removing only the supplemental lift changed its post-holiday stage error as follows:

| Date / hour | Existing stage error | Veto counterfactual | Change |
|---|---:|---:|---:|
| 2026-08-12 08:00 | 3,899 MW | 2,899 MW | -1,000 MW |

After 09:00 actual demand finalized at 29,370 MW, the same stage-level counterfactual reduced the 09:00 error from 3,364.6 MW to 2,364.6 MW. This is a narrow same-day controller correction, not evidence of a broad model-quality gain. No other retained transition record met the veto threshold, so the replay found no historical intervention regressions but also does not establish multi-regime coverage.

## Verification And Scope

- Focused feature-builder and adjustment tests: `139 passed`.
- Full repository suite: `502 passed`.
- Regression coverage verifies both paths: a confirmed large overforecast cancels the lift, while a modest miss preserves it.
- The v11 Champion, training feature set, raw quantile models, interval calibration, midday logic, and published-forecast freeze policy remain unchanged.
