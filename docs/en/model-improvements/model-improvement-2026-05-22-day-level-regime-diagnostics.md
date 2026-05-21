# 2026-05-22 Day-Level Lag and Weather Regime Diagnostics

> Adds full-day internal diagnostics before adding another correction rule, so cold-regime lag bias can be evaluated across the whole curve instead of one time window.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-22-day-level-regime-diagnostics.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-22-day-level-regime-diagnostics.md)

---

## Why This Was Needed

The recent forecast miss should not be treated as a fixed 07-10 morning problem. The larger operational question is whether the full-day curve can break away from a hot previous-day `lag_24h` when the target day is much cooler.

Hour-specific guards can make the line look patched together. Before adding a new model feature or correction, the pipeline now records a day-level regime summary in the internal diagnostic JSON.

---

## Change

Internal daily diagnostics now include `diagnosticSummary.dayLevelRegime` with:

- full-day model bias and MAE,
- mean `lag_24h_to_same_business_type_gap`,
- mean and hour count of `lag_24h` overheat versus recent same business-type demand,
- mean `temp_delta_24h`,
- mean previous-day temperature drop,
- mean `cooling_delta_24h`,
- mean `temp_anomaly_7d`,
- 72-hour cooling-memory mean,
- flags such as `cool_lag_overheat_regime`.

This is diagnostic only. It does not change the forecast curve.

---

## Expected Use

After ETL finalizes a day, the internal report can show whether a miss happened under:

- high previous-day lag pressure,
- a cooler-than-yesterday weather regime,
- lower cooling-load conditions,
- remaining thermal memory,
- model overprediction or underprediction.

That gives a cleaner basis for a future feature such as a full-day lag/weather interaction, without hard-coding one hour range.

---

## Tests

Updated internal diagnostic tests verify that `dayLevelRegime` is emitted with lag, weather, and flag fields.

Full regression suite: `308 passed`.
