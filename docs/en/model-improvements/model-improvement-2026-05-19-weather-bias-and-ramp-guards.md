# 2026-05-19 Weather Bias and Intraday Ramp Guards

> A conservative correction after the 2026-05-19 forecast miss, focused on avoiding midday overcorrection while keeping the real morning ramp intact.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-19-weather-bias-and-ramp-guards.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-19-weather-bias-and-ramp-guards.md)

---

## Why This Was Needed

On 2026-05-19, the forecast error had two different shapes:

- 06:00-09:00 was too low. The model did not follow the warm weekday morning ramp strongly enough.
- 11:00-13:00 became too high. Weather bias correction, warm-day adjustment, and intraday residual correction stacked in the same direction.

This was not simply a missing `lag_24h` problem. The previous day's actual demand was already available to the model. The issue was that the model and guards did not separate "true morning ramp" from "near-term overreaction after the morning miss" cleanly enough.

---

## Diagnosis

The published GitHub Pages forecast at `2026-05-19T14:45:12+09:00` was compared with TEPCO observed actuals for 00:00-13:00.

| Series | MAE vs actual | Notes |
| --- | ---: | --- |
| Published model | 841.7 MW | Large 11:00-12:00 overprediction |
| TEPCO forecast | 377.9 MW | Better shape for this day |

The largest model miss was 11:00, where the published model was `+2533.1 MW` above actual demand. That pointed to an overcorrection problem, not only a weak base model.

---

## Forecasting Change

Weather forecast bias correction was made less reactive:

- `horizon_hours`: 4 -> 3
- `min_abs_bias_c`: 0.8 -> 1.5
- `max_abs_bias_c`: 2.5 -> 1.5
- `decay_per_hour`: 0.75 -> 0.6

This keeps the correction useful when the weather forecast is clearly biased, but avoids treating ordinary sub-1C forecast noise as a strong demand signal.

The warm-day daytime guard now caps excessive increases above the previous day's same-hour demand:

- `lag24_warm_day_cap_enabled: true`
- `lag24_warm_day_max_increase_mw: 2500`

When a warm-day guard is active, the forecast can still rise above `lag_24h`, but not by an unbounded amount. The quantile band is shifted together with q50, so the band width is preserved.

---

## Intraday Change

Intraday residual correction now has a short-horizon ramp guard.

After at least 10:00, the next 1-3 forecast hours are capped relative to the latest observed actual:

- +1200 MW for the next hour
- +1500 MW for the second hour
- +2000 MW for the third hour

The guard intentionally starts at 10:00. This avoids suppressing the real 06:00-09:00 morning rise, which was one of the problems on 2026-05-19.

When the guard changes a forecast, the ETL log now includes `ramp_guard=applied`.

---

## Local Check

After the change, a local regenerated forecast was compared against the same observed 00:00-13:00 window.

| Series | MAE vs actual | Notes |
| --- | ---: | --- |
| Published model | 841.7 MW | Before this correction |
| Revised local model | 599.4 MW | 11:00 overprediction reduced |
| TEPCO forecast | 377.9 MW | Still better on this day |

The 11:00 model error improved from `+2533.1 MW` to `+659.1 MW`.

This is a real improvement, but not a complete win. The model still underestimates the 06:00-09:00 morning ramp and remains high around 12:00-13:00.

---

## Safety Notes

- TEPCO forecast values are still not used as model features.
- The new guards are conservative rule-based limits around the model output.
- The ramp guard only affects the nearest future hours.
- The morning ramp before 10:00 is deliberately left open.
- The warm-day cap is season-neutral in intent: it limits excessive jumps from `lag_24h`, not only summer cooling demand.

---

## Next Watch Items

- Warm weekday morning ramp from 06:00-09:00.
- Midday overreaction after a high positive morning residual.
- Whether 14:00-18:00 remains stable on warm days after the cap.
- Daily diagnostics after ETL, especially when TEPCO forecast beats the model by a large margin.

---

## Tests

Validation run locally:

- `py -3 -m pytest -q` -> 273 passed
- `npm.cmd run build` -> passed
- `git diff --check` -> no whitespace errors
