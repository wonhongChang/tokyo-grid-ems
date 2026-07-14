# 2026-07-15 Intraday Anchor Cap Refinement

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-07-15-intraday-anchor-cap-refinement.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-07-15-intraday-anchor-cap-refinement.md)

## Context

The 2026-07-14 chart still failed even after the warm-day lag24 weather allowance was merged. A snapshot review separated two causes:

- The 10:00-12:00 false valley was mainly a late-application/freeze issue from the old warm-day lag24 cap.
- The 09:00 spike and 14:00-18:00 plateau overforecast remained structural intraday-control gaps.

The final 2026-07-14 observed evaluation showed the model losing to TEPCO for the day:

| Window | Model MAE | TEPCO MAE |
| --- | ---: | ---: |
| Observed 21 hours | 815 MW | 478 MW |
| 09:00-19:00 | 1,104 MW | 578 MW |
| 13:00-18:00 | 1,114 MW | 657 MW |

The largest model misses were:

- 09:00: +2,162 MW
- 14:00: +1,485 MW
- 16:00: +1,242 MW
- 18:00: +1,536 MW

## Root Cause

### Morning 09:00 Spike

At 08:00, the observed demand was almost on top of the model, so the existing `morning_observed_anchor_cap` did not trigger. However, the next 09:00 forecast jumped far above the level justified by same-day actual plus lag/recent ramp support.

The missing case was: the latest residual is not yet negative, but the near-term forecast already exceeds observed ramp support under a strong warming signal.

### Afternoon Plateau Overforecast

At 13:00, actual demand rebounded, so the existing afternoon anchor cap treated the shape as recovering and skipped the 14:00 cap. But the 13:00 forecast itself was already about +1.65 GW above actual. The controller needed a severe-overforecast override that allows capping even when the latest observed slope is positive.

## Change

### Morning Support-Overhang Mode

`morning_observed_anchor_cap` now has a `support_overhang` mode. It can run when:

- the target is a business-day morning hour,
- the latest observed residual is neutral or only mildly positive,
- the day is materially warmer than the previous day,
- the target forecast is more than the configured overhang threshold above `latest actual + lag/recent ramp support + buffer`.

This prevents a near-term 09:00 jump from escaping just because the latest observed bucket was not yet an overforecast.

### Afternoon Severe-Overforecast Mode

`afternoon_observed_anchor_cap` now has a `severe_overforecast` mode. It can run when:

- latest and mean residuals show a large persistent model overforecast,
- the recent same-day slope is recovering but still within a conservative upper bound,
- lag/recent support does not justify the raw plateau level.

The mode uses a tighter support fraction and lower cap buffer than the normal afternoon cap.

## Operational Effect

Replay-style checks on 2026-07-14 snapshots showed:

- 09:32 snapshot: 09:00 forecast reduced by about 1.0 GW via `support_overhang`.
- 14:15 snapshot: 14:00-16:00 future plateau reduced by roughly 0.7-1.3 GW via `severe_overforecast`.
- 16:03 snapshot: 15:00-16:00 future plateau reduced more strongly once the 14:00 overforecast was observed.

The update does not rewrite already frozen historical points. It prevents the same pattern from being re-served in future intraday runs.

## Validation

- `python -m pytest tests/test_intraday_correction.py`

Results:

- `83 passed`

