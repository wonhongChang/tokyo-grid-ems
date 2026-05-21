# Anomaly Detection Criteria

Languages: [한국어](../ko/anomaly-criteria.md) · [日本語](../ja/anomaly-criteria.md)

Tokyo Grid EMS separates anomaly detection into three event types so the dashboard can explain why an alert was raised.

| Event | Purpose | Inputs |
|---|---|---|
| Reserve Risk | Detect low supply margin periods | usage rate, supply capacity |
| Spike / Drop | Detect demand outside the forecast interval | actual demand, forecast bands |
| Drift | Detect sustained model bias over multiple hours | actual-minus-forecast residuals |

Thresholds are configured in the `anomaly` block of `config.yaml`.

---

## Reserve Risk

An event is raised when TEPCO usage rate reaches a threshold. Below 92% is treated as stable, 92% to below 97% is warning, and 97% or higher is critical.

| Severity | Condition |
|---|---|
| stable | `usage_pct < 92.0` |
| warning | `92.0 <= usage_pct < 97.0` |
| danger (`critical`) | `usage_pct >= 97.0` |

Dashboard copy keeps the message short, while usage rate, threshold, and supply capacity are shown as metric chips.

---

## Spike / Drop

Spike/drop compares actual demand against prediction intervals.

| Event | warning | critical |
|---|---|---|
| Spike | actual > `p99Upper` and breach exceeds the warning MW or % threshold | actual > `p99Upper` and breach exceeds the critical MW or % threshold |
| Drop | actual < `p99Lower` and breach exceeds the warning MW or % threshold | actual < `p99Lower` and breach exceeds the critical MW or % threshold |

p95-only edge crossings are ignored. Tiny p99 edge crossings are also suppressed unless the breach is operationally meaningful. They are treated as ordinary model-band misses, not operational spike/drop events. Sustained bias is still captured by drift detection.

Default thresholds:

```yaml
spike_drop:
  warning_breach_mw: 300
  warning_breach_pct: 1.0
  critical_breach_mw: 500
  critical_breach_pct: 2.0
```

---

## Drift

Drift captures sustained bias rather than a single-hour miss.

Process:

1. Compute `residual = actual_mw - forecast_mw`.
2. Apply EWMA with `ewma_alpha = 0.3`.
3. Raise an event when EWMA exceeds `threshold_mw = 800` for at least `sustained_hours = 3`.

Positive drift means actual demand stayed above the model forecast. Negative drift means it stayed below.

---

## Design Principles

- Keep alert messages short.
- Put numbers in metric chips.
- Separate model-error events from supply-risk events.
- Exclude `tepco_forecast_fallback` rows from actual-based anomaly checks.
- Keep thresholds in config rather than hardcoding them in detector logic.
