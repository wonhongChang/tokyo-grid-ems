# 2026-05-20 Midday Transition Guard

> Adds UI-hidden lag-shape diagnostics and a conservative noon guard for business days when recent demand shape clearly points downward.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-20-midday-transition-features.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-20-midday-transition-features.md)

---

## Why This Was Needed

On 2026-05-20, the model followed the hot midday signal too strongly around the 12:00 chart bucket.

The previous day and TEPCO forecast both showed a temporary 12:00-13:00 dip, but the model kept the level elevated because the existing features emphasized:

- same-hour demand anchors such as `lag_24h`,
- weather and cooling load features,
- recent same-hour business-day averages.

Those inputs described the level of demand, but they did not explicitly describe the hour-to-hour transition shape.

---

## Change

Added five inference-only context values:

- `lag_24h_hourly_delta`
- `lag_168h_hourly_delta`
- `recent_same_business_type_delta_mean`
- `business_midday_x_lag_24h_delta`
- `business_midday_x_recent_delta_mean`

These values describe whether the same hour recently tended to rise or dip from the previous hour.

For example, when evaluating 12:00, `lag_24h_hourly_delta` compares yesterday 12:00 against yesterday 11:00. If yesterday had a lunch-time dip, the pipeline now has that shape context available.

After validation, these values were not added to the LightGBM training feature set because retraining with global hourly deltas moved unrelated morning hours. Instead, `MiddayTransitionGuard` uses them after LightGBM and existing guards:

- active only on business days,
- default target hour is 12:00,
- activates only when recent same-business shape shows a meaningful negative transition,
- applies only a capped partial downward adjustment when the forecast is much higher than that transition context.

The internal daily diagnostic JSON also stores the lag-shape context so operational postmortems can inspect whether a miss was caused by a level anchor or by a transition-shape error.

---

## Expected Effect

The pipeline should better distinguish:

- "hot day, demand level should be high",
- "hot day, but the 12:00 bucket may temporarily dip relative to 11:00",
- "recent business days are showing a different midday transition shape."

This should reduce over-elevation around 12:00 without making every business day noon lower by rule.

---

## Notes

- The LightGBM training feature count stays unchanged.
- The saved LightGBM interval version was not bumped, so the current trained model remains compatible.
- The context rows are included in UI-hidden internal diagnostics, not in the public dashboard.
