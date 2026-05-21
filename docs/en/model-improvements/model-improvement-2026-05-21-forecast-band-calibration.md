# 2026-05-21 Forecast Band Calibration

> Stops one-sided quantile uncertainty from being mirrored into the opposite side of the displayed forecast band.

Languages: [Korean](../../ko/model-improvements/model-improvement-2026-05-21-forecast-band-calibration.md) / [Japanese](../../ja/model-improvements/model-improvement-2026-05-21-forecast-band-calibration.md)

---

## Why This Was Needed

During the 2026-05-21 intraday forecast, the 14:00 prediction band became visually abnormal. The point forecast itself was not the main problem. The LightGBM quantiles were strongly asymmetric:

- q50 stayed near the expected demand line.
- q025 was very close to q50.
- q975 stayed much higher.

The previous interval calibration treated the collapsed lower side as suspicious and mirrored the wider upper-side half-width into the lower side. That made the displayed lower band fall much farther than the model's lower quantile actually implied.

---

## Change

`interval_calibration.mirror_collapsed_side` is now disabled in production config.

The calibration still enforces a minimum p95 half-width so bands do not collapse into a line. However, it no longer copies a large upper-side uncertainty into the lower side, or vice versa.

```yaml
interval_calibration:
  min_p95_half_width_mw: 500
  mirror_collapsed_side: false
```

---

## Expected Effect

Forecast bands should remain readable when the quantile model expresses one-sided uncertainty.

For the reproduced 2026-05-21 14:00 case, p95 width falls from roughly `9,260 MW` to roughly `5,130 MW`. The upper uncertainty remains visible, but the lower side no longer implies an unsupported downside range.

---

## Tests

Added tests cover:

- Default calibration keeps only the minimum width on a collapsed side.
- The old mirroring behavior remains available only when explicitly configured.
