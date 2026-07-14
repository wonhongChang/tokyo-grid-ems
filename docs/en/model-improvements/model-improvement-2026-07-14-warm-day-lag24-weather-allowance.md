# 2026-07-14 Warm-Day Lag24 Weather Allowance

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-07-14-warm-day-lag24-weather-allowance.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-07-14-warm-day-lag24-weather-allowance.md)

## Context

The live 2026-07-14 forecast showed an artificial morning/daytime shape break:

- 09:00 stayed high at about 46.1 GW
- 10:00 was forced down to about 42.8 GW
- 11:00-12:00 also stayed suppressed
- 13:00 jumped back to about 50.3 GW

The issue was not intraday residual carryover. At the 09:32 JST calibration snapshot, the residual correction was only about -194 MW. The break was introduced earlier in the `PostHolidayTimeBandGuard` stage.

The root cause was the fixed warm-day `lag24_warm_day_cap`:

```text
max forecast = lag_24h + 2500 MW
```

That cap is useful when the model overreacts to a warm day, but it is too rigid when the current day is several degrees hotter than the previous day. On 2026-07-14, the morning cooling delta was roughly +3.8C to +5.2C versus the previous day, and the observed 08:00 actual was not below the model. The fixed cap incorrectly treated yesterday's cooler demand as the upper anchor.

## Change

The warm-day lag24 cap now adds a weather-based allowance:

```text
max forecast =
  lag_24h
  + lag24_warm_day_max_increase_mw
  + min(weather_delta_c * allowance_per_c, max_weather_allowance)
```

Production config:

| Config key | Value |
| --- | ---: |
| `lag24_warm_day_max_increase_mw` | `2500` |
| `lag24_warm_day_weather_allowance_mw_per_c` | `1200` |
| `lag24_warm_day_max_weather_allowance_mw` | `5000` |

The weather delta uses the strongest available cooling signal among:

- `temp_delta_24h`
- `cooling_delta_24h`
- `apparent_cooling_delta_24h`

## Expected Effect

For hot business days that are much warmer than yesterday, the cap no longer creates a false 10:00-12:00 valley. The cap still remains active for extreme forecasts, but its upper bound scales with the actual cooling-load regime change.

This keeps the original safety idea while avoiding a hard same-hour lag ceiling on days where yesterday is not a fair upper anchor.

## Validation

- `python -m pytest tests/test_adjustment.py`

Results:

- `53 passed`

The added regression case mirrors the 2026-07-14 pattern: without the allowance, the 10:00 forecast would be capped near 42.8 GW; with the allowance, the forecast remains near the raw/analog level instead of producing an artificial dip.
