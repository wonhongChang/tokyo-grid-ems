# 2026-05-30 Negative Residual Continuity Floor
> A non-business-day intraday guard that prevents early negative residuals from pulling a flat same-day demand curve too far below the latest observed level.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-30-negative-residual-continuity-floor.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-30-negative-residual-continuity-floor.md)

---

## Why

The 2026-05-30 Saturday live forecast showed a controller overshoot in the opposite direction of the 2026-05-29 evening case.

The model overpredicted parts of the late morning, so intraday correction carried a negative residual into the afternoon. However, same-day actual demand around 11:00-13:00 was no longer falling; it was nearly flat. The negative residual then pushed the near-term afternoon forecast below the observed plateau, creating underprediction at 14:00-16:00.

## Change

Added `negative_residual_continuity_floor` inside the intraday correction layer.

The guard is intentionally narrow:

- applies only to non-business days by default,
- requires enough same-day actual history,
- requires the latest and mean actual slopes to be flat or not strongly falling,
- applies only to near-term future buckets,
- restores only the amount needed to stay above a conservative latest-actual floor,
- never applies automatically to production changes outside the configured guard.

## Operating Parameters

Default configuration:

- `target_hours`: 10-17
- `min_reference_hour`: 10
- `max_lead_hours`: 2
- `latest_slope_min_mw`: -300
- `mean_slope_min_mw`: -300
- `floor_slack_mw`: 500
- `floor_slope_fraction`: 0.25
- `max_floor_slope_mw`: 300
- `max_restore_mw`: 900
- `min_restore_mw`: 100

## Diagnostics

The correction metadata records:

- `negativeResidualContinuityFloorApplied`
- `negativeResidualContinuityFloorMaxRestoreMw`
- per-hour `negativeResidualContinuityFloorMw`
- per-hour `negativeResidualContinuityRestoreMw`

These fields are also compacted into the Ops Report fact packet so AI reports can distinguish residual overshoot from raw model bias.

## Test Coverage

Added a regression test for a 2026-05-30-style Saturday plateau where early negative residuals would otherwise push the 14:00 forecast below the latest observed demand context.
