# 2026-05-19 Afternoon Thermal Inertia and Shape Guard

> Follow-up after the 14:00-18:00 forecast line declined faster than the observed demand pattern.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-19-afternoon-thermal-inertia-shape-guard.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-19-afternoon-thermal-inertia-shape-guard.md)

---

## What Happened

The 2026-05-19 intraday refresh showed a steep afternoon decline in the model line.

The direction was not completely unreasonable: TEPCO also expected demand to decline from the afternoon into evening. The issue was the shape. The model dropped too quickly around 14:00-16:00 and then stayed low around the 18:00 lead-time.

This is risky operationally because warm-day electricity demand often has thermal inertia. Even if the air temperature starts to fall after the daily peak, cooling load does not always disappear immediately.

---

## Diagnosis

The model already had hourly temperature, cooling-degree, and weather-delta features. However, those features mostly describe the current hour or same-hour deltas.

They do not directly tell the model:

- the last few hours were also warm
- cooling demand may persist after the temperature peak
- afternoon demand can stay elevated even while forecast temperature begins to decline

The intraday ramp guard prevented the nearest future hour from collapsing below a hard bound, but it did not smooth the broader afternoon shape.

---

## Changes

### 1. Thermal inertia features

Added rolling weather-load features:

- `cooling_degree_3h_mean`
- `cooling_degree_6h_mean`
- `heating_degree_3h_mean`
- `heating_degree_6h_mean`

These are general demand-response features, not summer-only rules. Cooling inertia helps warm days; heating inertia can help cold winter mornings/evenings.

The LightGBM feature version was bumped so the model retrains on the next ETL/intraday run.

### 2. Intraday afternoon shape guard

Added a same-day shape guard under `intraday_correction.shape_guard`.

Default behavior:

- active after at least a 12:00 reference exists
- watches target hours `15-19`
- caps hour-to-hour forecast drops at `1000 MW`

This is not a TEPCO-following rule. It only prevents the published same-day line from forming an operationally implausible cliff when the recent context is already known.

---

## Expected Effect

For warm business afternoons, the model should be less eager to move from a high midday load to a low evening load in one or two hours.

This does not guarantee that the model beats TEPCO every day. It should reduce the specific failure mode where the forecast line turns down too sharply while demand is still elevated.

---

## Safety Notes

- The new features are symmetric: cooling and heating are both represented.
- The shape guard is narrow and only applies after same-day observations exist.
- The guard limits extreme line shape, not the daily peak level.
- Historical evaluation still depends on published forecast snapshots and daily reports.

---

## Tests

Added/updated tests for:

- thermal inertia feature creation in training and inference
- inference using recent same-day temperature hours
- LightGBM feature-version retraining trigger
- afternoon shape guard capping a steep model drop
- shape guard staying inactive before the configured reference hour
