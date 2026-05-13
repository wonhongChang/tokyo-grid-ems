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

An event is raised when usage rate reaches a threshold.

| Severity | Condition |
|---|---|
| warning | `usage_pct >= 90.0` |
| critical | `usage_pct >= 95.0` |

Dashboard copy keeps the message short, while usage rate, threshold, and supply capacity are shown as metric chips.

---

## Spike / Drop

Spike/drop compares actual demand against prediction intervals.

| Event | warning | critical |
|---|---|---|
| Spike | actual > `p95Upper` | actual > `p99Upper` and breach exceeds MW or % threshold |
| Drop | actual < `p95Lower` | actual < `p99Lower` and breach exceeds MW or % threshold |

Tiny p95 breaches are ignored so that a 1-50 MW edge crossing does not become a dashboard alert. By default, a p95 warning needs either a 150 MW breach or a 0.5% breach.

Default critical thresholds:

```yaml
spike_drop:
  warning_breach_mw: 150
  warning_breach_pct: 0.5
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
