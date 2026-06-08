# 2026-06-08 Business-Return Shape Veto

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-06-08-business-return-shape-veto.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-06-08-business-return-shape-veto.md)

---

## Problem

The 2026-06-08 live forecast showed that the raw LightGBM line was already carrying a reasonable Monday business-return ramp. The post-processing layer then applied the `business_return_anchor_shortfall` lift because the recent same-business level anchor was still higher than the weekend `lag_24h` level.

That made the served line worse around 08:00-11:00. The issue was not a weak raw model on that day. It was an anchor-level guard applying even when the forecast shape was already supported.

## Change

Added a shape-based veto to `business_return_anchor_shortfall`.

The guard now checks the forecast's hour-to-hour ramp against `recent_same_business_type_delta_mean`. It only applies the level-anchor lift when the forecast ramp is also materially short of the recent same-business ramp.

New config:

```yaml
business_return_anchor_shortfall:
  min_shape_shortfall_mw: 800
```

The late-morning excess cap now also includes 11:00:

```yaml
business_return_anchor_excess_cap:
  target_hours: [8, 9, 10, 11]
```

## Operational Effect

This keeps the Monday/post-holiday recovery guard available for true under-ramp cases, but prevents it from adding MW when the raw or analogous-day line already has a healthy ramp shape.

The change does not use TEPCO forecast values as a calibration input. TEPCO remains a reference benchmark only.

## Validation

- Added a regression test that still lifts a true 09:00 business-return shortfall.
- Added a regression test that skips the lift when the morning ramp shape is already supported.
- Added a regression test that confirms the business-return excess cap also covers 11:00.
- Full test suite: `383 passed`.
