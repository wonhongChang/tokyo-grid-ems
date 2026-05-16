from __future__ import annotations

import pandas as pd

from python.forecast.baseline import HourlyForecast

DEFAULT_RESERVE_WARNING_PCT = 92.0
DEFAULT_RESERVE_CRITICAL_PCT = 97.0


def detect_anomalies(
    hourly: pd.DataFrame,
    forecasts: list[HourlyForecast],
    config: dict,
    day_context: dict | None = None,
) -> list[dict]:
    """
    Run all three detectors and return a merged, deduplicated event list.

    hourly      : one day's hourly DataFrame (ts, actual_mw, usage_pct, supply_mw)
    forecasts   : baseline forecast for this day (may be empty)
    config      : anomaly block from config.yaml
    day_context : optional dict for contextual enrichment, e.g.
                  {"post_holiday_early_morning": True}
    """
    events: list[dict] = []
    events.extend(_reserve_risk(hourly, config.get("reserve_risk", {})))
    events.extend(_spike_drop(hourly, forecasts, config.get("spike_drop", {}), day_context))
    events.extend(_drift(hourly, forecasts, config.get("drift", {})))
    return events


# ---------------------------------------------------------------------------
# 1. Reserve Risk
# ---------------------------------------------------------------------------

def _reserve_risk(hourly: pd.DataFrame, cfg: dict) -> list[dict]:
    warning_pct = cfg.get("warning_pct", DEFAULT_RESERVE_WARNING_PCT)
    critical_pct = cfg.get("critical_pct", DEFAULT_RESERVE_CRITICAL_PCT)
    events = []

    for _, row in hourly.sort_values("ts").iterrows():
        ts = row["ts"]
        if pd.isna(ts):
            continue
        usage_pct = row.get("usage_pct")
        supply_mw = row.get("supply_mw")
        if pd.isna(usage_pct):
            continue

        pct = float(usage_pct)
        if pct < warning_pct:
            continue

        severity = "critical" if pct >= critical_pct else "warning"
        threshold = critical_pct if severity == "critical" else warning_pct
        ts_str = ts.isoformat(timespec="seconds")
        end_str = (ts + pd.Timedelta("1h")).isoformat(timespec="seconds")

        events.append({
            "id": f"{ts_str}_reserve_risk",
            "type": "reserve_risk",
            "severity": severity,
            "startAt": ts_str,
            "endAt": end_str,
            "metric": "usage_pct",
            "usagePct": round(pct, 1),
            "thresholdPct": threshold,
            "supplyMw": round(float(supply_mw), 1) if pd.notna(supply_mw) else None,
            "reason": f"Usage {pct:.1f}% exceeded {severity} threshold {threshold}%",
            "tags": ["kpi"],
        })
    return events


# ---------------------------------------------------------------------------
# 2. Spike / Drop
# ---------------------------------------------------------------------------

def _spike_drop(
    hourly: pd.DataFrame,
    forecasts: list[HourlyForecast],
    cfg: dict | None = None,
    day_context: dict | None = None,
) -> list[dict]:
    if not forecasts:
        return []
    if cfg is None:
        cfg = {}

    critical_breach_mw  = float(cfg.get("critical_breach_mw",  500.0))
    critical_breach_pct = float(cfg.get("critical_breach_pct",   2.0))
    warning_breach_mw   = float(cfg.get("warning_breach_mw",    150.0))
    warning_breach_pct  = float(cfg.get("warning_breach_pct",     0.5))

    # key: "2025-11-01T18" → HourlyForecast
    fc_map = {f.ts[:13]: f for f in forecasts}
    events = []

    for _, row in hourly.sort_values("ts").iterrows():
        ts = row["ts"]
        if pd.isna(ts):
            continue
        actual_mw = row.get("actual_mw")
        if pd.isna(actual_mw):
            continue

        key = ts.isoformat(timespec="seconds")[:13]
        fc = fc_map.get(key)
        if fc is None:
            continue

        actual = float(actual_mw)
        hour   = ts.hour
        ts_str = ts.isoformat(timespec="seconds")
        end_str = (ts + pd.Timedelta("1h")).isoformat(timespec="seconds")
        interval = {
            "p95Lower": fc.p95_lower_mw, "p95Upper": fc.p95_upper_mw,
            "p99Lower": fc.p99_lower_mw, "p99Upper": fc.p99_upper_mw,
        }

        if actual > fc.p99_upper_mw:
            breach_mw  = actual - fc.p99_upper_mw
            breach_pct = breach_mw / actual * 100 if actual > 0 else 0.0
            kind       = "spike"
            severity   = "critical" if (breach_mw >= critical_breach_mw or breach_pct >= critical_breach_pct) else "warning"
            reason     = (
                f"Actual {actual:.0f} MW exceeded p99 upper {fc.p99_upper_mw:.0f} MW "
                f"by {breach_mw:.0f} MW ({breach_pct:.2f}%)"
            )
        elif actual > fc.p95_upper_mw:
            breach_mw = actual - fc.p95_upper_mw
            breach_pct = breach_mw / actual * 100 if actual > 0 else 0.0
            if breach_mw < warning_breach_mw and breach_pct < warning_breach_pct:
                continue
            kind, severity = "spike", "warning"
            reason = (
                f"Actual {actual:.0f} MW exceeded p95 upper {fc.p95_upper_mw:.0f} MW "
                f"by {breach_mw:.0f} MW ({breach_pct:.2f}%)"
            )
        elif actual < fc.p99_lower_mw:
            breach_mw  = fc.p99_lower_mw - actual
            breach_pct = breach_mw / actual * 100 if actual > 0 else 0.0
            kind       = "drop"
            severity   = "critical" if (breach_mw >= critical_breach_mw or breach_pct >= critical_breach_pct) else "warning"
            reason     = (
                f"Actual {actual:.0f} MW fell below p99 lower {fc.p99_lower_mw:.0f} MW "
                f"by {breach_mw:.0f} MW ({breach_pct:.2f}%)"
            )
        elif actual < fc.p95_lower_mw:
            breach_mw = fc.p95_lower_mw - actual
            breach_pct = breach_mw / actual * 100 if actual > 0 else 0.0
            if breach_mw < warning_breach_mw and breach_pct < warning_breach_pct:
                continue
            kind, severity = "drop", "warning"
            reason = (
                f"Actual {actual:.0f} MW fell below p95 lower {fc.p95_lower_mw:.0f} MW "
                f"by {breach_mw:.0f} MW ({breach_pct:.2f}%)"
            )
        else:
            continue

        event: dict = {
            "id": f"{ts_str}_{kind}",
            "type": kind,
            "severity": severity,
            "startAt": ts_str,
            "endAt": end_str,
            "metric": "actual_mw",
            "actualMw": round(actual, 1),
            "expectedMw": fc.forecast_mw,
            "interval": interval,
            "reason": reason,
            "tags": ["interval"],
        }

        if (day_context and day_context.get("post_holiday_early_morning")
                and 1 <= hour <= 6):
            event["contextNote"] = (
                "Post-holiday early morning — model tends to overestimate overnight demand."
            )

        events.append(event)
    return events


# ---------------------------------------------------------------------------
# 3. Drift (EWMA of residuals)
# ---------------------------------------------------------------------------

def _drift(hourly: pd.DataFrame, forecasts: list[HourlyForecast], cfg: dict) -> list[dict]:
    if not forecasts:
        return []

    alpha = cfg.get("ewma_alpha", 0.3)
    threshold_mw = cfg.get("threshold_mw", 800.0)
    sustained = cfg.get("sustained_hours", 3)

    fc_map = {f.ts[:13]: f for f in forecasts}

    rows: list[dict] = []
    for _, row in hourly.sort_values("ts").iterrows():
        ts = row["ts"]
        if pd.isna(ts):
            continue
        actual_mw = row.get("actual_mw")
        if pd.isna(actual_mw):
            continue
        key = ts.isoformat(timespec="seconds")[:13]
        fc = fc_map.get(key)
        if fc is None:
            continue
        rows.append({"ts": ts, "residual": float(actual_mw) - fc.forecast_mw})

    if len(rows) < sustained:
        return []

    residuals = [r["residual"] for r in rows]
    ewma = pd.Series(residuals).ewm(alpha=alpha, adjust=False).mean().tolist()

    events = []
    i = 0
    while i < len(ewma):
        direction = None
        if ewma[i] > threshold_mw:
            direction = "above"
        elif ewma[i] < -threshold_mw:
            direction = "below"

        if direction is None:
            i += 1
            continue

        j = i + 1
        while j < len(ewma):
            if direction == "above" and ewma[j] > threshold_mw:
                j += 1
            elif direction == "below" and ewma[j] < -threshold_mw:
                j += 1
            else:
                break

        if j - i >= sustained:
            start_ts = rows[i]["ts"].isoformat(timespec="seconds")
            end_ts = rows[j - 1]["ts"].isoformat(timespec="seconds")
            avg_res = sum(rows[k]["residual"] for k in range(i, j)) / (j - i)
            sign = "above" if direction == "above" else "below"
            events.append({
                "id": f"{start_ts}_drift",
                "type": "drift",
                "severity": "warning",
                "startAt": start_ts,
                "endAt": end_ts,
                "metric": "residual_mw",
                "residualAvgMw": round(avg_res, 1),
                "method": "ewma",
                "thresholdMw": threshold_mw,
                "reason": (
                    f"EWMA residual {sign} ±{threshold_mw:.0f} MW "
                    f"for {j - i} consecutive hours"
                ),
                "tags": ["residual"],
            })
        i = j

    return events
