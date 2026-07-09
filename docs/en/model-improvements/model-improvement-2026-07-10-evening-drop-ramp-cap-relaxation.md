# 2026-07-10 Evening Drop Ramp-Cap Relaxation

Languages: [한국어](../../ko/model-improvements/model-improvement-2026-07-10-evening-drop-ramp-cap-relaxation.md) / [日本語](../../ja/model-improvements/model-improvement-2026-07-10-evening-drop-ramp-cap-relaxation.md)

## Context

The 2026-07-09 forecast showed a clear late-evening shape failure. The model was broadly usable around 13:00-16:00, but 21:00 was too high even after same-day demand had started falling.

The important finding was that the existing decline controls were not absent. The 20:22 JST operational calibration snapshot had already applied:

- `afternoon_positive_residual_carryover_damping`
- `evening_decline_continuity_guard`

For 21:00, the pre-calibration forecast was already near the lower evening path, and the decline guard reduced it further. However, the final `ramp_guard` then enforced a near-term lower bound from the last observed actual demand and lifted the served forecast back up. In other words, the decline guard was trying to protect the evening curve, but the final ramp cap treated the sharp fall as too steep.

## Change

Added `ramp_guard.observed_drop_relaxation.decline_support`, a narrow extension of the existing observed-drop relaxation path.

The rule does not lower the forecast by itself. It only allows a wider drop cap when all of these conditions are true:

- actual demand is already falling fast enough for `observed_drop_relaxation` to be active
- the forecast lead time is at least two hours
- the day is a business day
- both target-hour shape signals support a steep decline:
  - `lag_24h_hourly_delta`
  - `recent_same_business_type_delta_mean`

Default production config:

| Config key | Value |
| --- | ---: |
| `enabled` | `true` |
| `business_day_only` | `true` |
| `min_lead_hours` | `2` |
| `max_support_delta_mw` | `-1000` |
| `max_decrease_mw_by_lead_hour` | `[1600, 4000, 5600]` |

## Expected Effect

When the evening demand curve is already falling and the target-hour lag/recent shape also points down, the final ramp guard no longer forces the forecast back toward the last observed level too aggressively.

This is intentionally conservative:

- lead-1 forecasts keep the standard near-term cap
- non-business days are not changed
- the rule needs both lag and recent same-business shape support
- TEPCO forecast values are not used as inputs

## Observability

The correction metadata now includes:

- `rampGuardDeclineSupportRelaxationApplied`
- `rampGuardDeclineSupportRelaxationMaxExtraDropMw`

The AI operation report fact packet also exposes the new control flag, so future daily reports can distinguish between "decline guard was not active" and "decline guard was active, but the final ramp cap still constrained the served line."

## Validation

- `python -m pytest tests/test_intraday_correction.py -k "ramp_guard_relaxes_drop_cap or ramp_guard_keeps_drop_cap or observed_demand_drop"`

Results:

- `3 passed`

## Notes

This is not a 21:00 hard-code. It is a final-stage cap relaxation that only triggers when observed demand is already dropping and independent lag/recent shape signals support a steep evening decline.
