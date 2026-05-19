# 2026-05-19 Operational Intraday Drop Guard

> A follow-up operational guard after the 2026-05-19 afternoon forecast line dropped much faster than observed demand.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-19-operational-intraday-drop-guard.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-19-operational-intraday-drop-guard.md)

---

## Why This Was Needed

After the first 2026-05-19 correction, the model still produced an operationally implausible afternoon shape.

Observed demand changed only slightly from 14:00 to 15:00:

| Hour | Actual | Model | Error |
| --- | ---: | ---: | ---: |
| 14:00 | 35,210 MW | 36,434 MW | +1,224 MW |
| 15:00 | 34,790 MW | 33,128 MW | -1,662 MW |

Actual demand fell by about `420 MW`, while the model line fell by about `3,306 MW`.

From an operational forecasting viewpoint, this kind of hourly drop needs a strong external reason such as a major weather change, holiday regime shift, or large demand-side event. None of those was visible in the available inputs.

---

## Diagnosis

The problem was not only the base LightGBM forecast. The intraday residual correction could also amplify the shape error.

Recent hours around 12:00-14:00 had positive model errors. The correction then saw the model as "too high" and pushed the near future downward. That is dangerous on warm weekday afternoons, where demand can remain high even after the temperature peak starts to fade.

The feature review also showed that the following weather-delta features can pull late afternoon demand down:

- `cooling_delta_24h`
- `temp_delta_24h`
- `temp_c`
- `apparent_temp_c`

Those features are still useful, so they were not removed in this change. The immediate operational issue was that the published line must not collapse faster than plausible demand dynamics.

---

## Operational Change

The intraday ramp guard is now bidirectional.

Before this change, the guard only capped excessive upward jumps from the latest observed actual. It now also caps excessive near-term drops:

- next 1 hour: at most `-1000 MW`
- next 2 hours: at most `-1800 MW`
- next 3 hours: at most `-2400 MW`

The existing upward caps remain:

- next 1 hour: at most `+1200 MW`
- next 2 hours: at most `+1500 MW`
- next 3 hours: at most `+2000 MW`

This does not make the model follow TEPCO forecast values. It is a shape-safety guard that keeps the intraday correction within a plausible operating envelope around the latest observed demand.

---

## Local Check

Using the 2026-05-19 15:00 observed actual as the latest reference, the corrected near-term line becomes smoother:

| Hour | Existing Pages model | Revised local model |
| --- | ---: | ---: |
| 16:00 | 31,984 MW | 33,790 MW |
| 17:00 | 31,979 MW | 32,990 MW |
| 18:00 | 31,395 MW | 32,390 MW |

The revised line still declines, but it no longer collapses unrealistically.

---

## Safety Notes

- This is an operational post-processing guard, not a feature hack.
- TEPCO forecast values are not used as model inputs.
- The guard only affects the nearest future hours after a real or fallback intraday reference.
- Genuine evening decline is still allowed within the configured envelope.
- The next modeling task is to validate whether 24h weather-delta features are too aggressive in warm weekday afternoons.

---

## Tests

Added tests cover:

- Near-term downward drop capping after an afternoon actual.
- Plausible near-term decline remaining unchanged.
- Existing upward jump guard behavior.
- Morning ramp guard remaining inactive before the configured reference hour.
