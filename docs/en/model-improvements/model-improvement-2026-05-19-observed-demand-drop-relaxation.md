# 2026-05-19 Observed Demand Drop Relaxation

> A follow-up to the operational ramp guard after the 2026-05-19 evening forecast was lifted too much around 21:00-22:00.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-19-observed-demand-drop-relaxation.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-19-observed-demand-drop-relaxation.md)

---

## Why This Was Needed

The 20:30 intraday snapshot used 19:00 as the latest observed actual.

At that point, the bidirectional ramp guard treated a sharp 21:00-22:00 decline as suspicious and lifted the model line:

| Hour | Before guard intent | Published snapshot |
| --- | ---: | ---: |
| 21:00 | about 28,600 MW | 30,180 MW |
| 22:00 | about 27,500 MW | 29,580 MW |

The exact published values came from the generic drop caps:

- 21:00 floor: `31,980 - 1,800 = 30,180 MW`
- 22:00 floor: `31,980 - 2,400 = 29,580 MW`

The root issue was not the clock time itself. When actual demand is already falling quickly, the system should allow the near future to continue falling regardless of whether that happens at 17:00, 19:00, or another hour.

---

## Operational Change

The ramp guard now has an observed-demand-drop relaxation:

```yaml
intraday_correction:
  ramp_guard:
    observed_drop_relaxation:
      enabled: true
      min_recent_drop_mw: 700
      lookback_hours: 2
      skip_shape_guard: true
      max_decrease_mw_by_lead_hour: [2000, 3600, 5000]
```

If the latest observed actuals already show a large hour-to-hour drop, the guard allows a wider near-term decline. This works for normal after-work demand decline and for unusual early shutdown patterns once they appear in actuals.

The normal ramp guard still applies when recent actuals do not show a meaningful drop, and extreme future drops are still capped.

---

## Expected Effect

The model should no longer over-lift future hours simply because demand is falling quickly after the latest actual.

This is not a TEPCO-following rule. It is an operational shape rule:

- observed demand trend is treated as stronger evidence than a fixed clock rule,
- after-work demand can fall quickly,
- unusual early demand drops are supported once they are visible in actuals,
- impossible-looking collapses still need a safety cap.

---

## Tests

Added tests cover:

- observed demand drops relaxing the ramp guard without a fixed time gate,
- shape guard being skipped when an observed demand drop is already active,
- extreme future drops still being capped,
- existing morning and afternoon ramp guard behavior remaining unchanged.
