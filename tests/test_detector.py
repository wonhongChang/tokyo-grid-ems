"""Tests for python/anomaly/detector.py."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from python.anomaly.detector import detect_anomalies
from python.forecast.baseline import HourlyForecast

JST = ZoneInfo("Asia/Tokyo")
BASE_DATE = "2024-01-01"


def _ts(hour: int) -> pd.Timestamp:
    return pd.Timestamp(f"{BASE_DATE}T{hour:02d}:00:00+09:00")


def _make_hourly(
    usage_pct: list[float] | None = None,
    actual_mw: list[float] | None = None,
    supply_mw: list[float] | None = None,
) -> pd.DataFrame:
    rows = []
    for h in range(24):
        rows.append({
            "ts": _ts(h),
            "actual_mw": actual_mw[h] if actual_mw else 30000.0,
            "usage_pct": usage_pct[h] if usage_pct else 80.0,
            "supply_mw": supply_mw[h] if supply_mw else 35000.0,
        })
    return pd.DataFrame(rows)


def _make_forecasts(forecast_mw: float = 30000.0, std: float = 1000.0) -> list[HourlyForecast]:
    return [
        HourlyForecast(
            ts=_ts(h).isoformat(timespec="seconds"),
            forecast_mw=forecast_mw,
            p95_lower_mw=round(forecast_mw - 1.96 * std, 1),
            p95_upper_mw=round(forecast_mw + 1.96 * std, 1),
            p99_lower_mw=round(forecast_mw - 2.576 * std, 1),
            p99_upper_mw=round(forecast_mw + 2.576 * std, 1),
        )
        for h in range(24)
    ]


# ── Reserve Risk ─────────────────────────────────────────────────────────────

def test_reserve_risk_warning():
    hourly = _make_hourly(usage_pct=[91.0] + [80.0] * 23)
    events = detect_anomalies(hourly, [], {})
    rr = [e for e in events if e["type"] == "reserve_risk"]
    assert len(rr) == 1
    assert rr[0]["severity"] == "warning"


def test_reserve_risk_critical():
    hourly = _make_hourly(usage_pct=[96.0] + [80.0] * 23)
    events = detect_anomalies(hourly, [], {})
    rr = [e for e in events if e["type"] == "reserve_risk"]
    assert len(rr) == 1
    assert rr[0]["severity"] == "critical"


def test_reserve_risk_below_threshold():
    hourly = _make_hourly(usage_pct=[89.9] * 24)
    events = detect_anomalies(hourly, [], {})
    assert not [e for e in events if e["type"] == "reserve_risk"]


def test_reserve_risk_custom_threshold():
    hourly = _make_hourly(usage_pct=[88.0] + [80.0] * 23)
    cfg = {"reserve_risk": {"warning_pct": 85.0, "critical_pct": 95.0}}
    events = detect_anomalies(hourly, [], cfg)
    rr = [e for e in events if e["type"] == "reserve_risk"]
    assert len(rr) == 1
    assert rr[0]["severity"] == "warning"


def test_reserve_risk_multiple_hours():
    hourly = _make_hourly(usage_pct=[91.0, 96.0] + [80.0] * 22)
    events = detect_anomalies(hourly, [], {})
    rr = [e for e in events if e["type"] == "reserve_risk"]
    assert len(rr) == 2


def test_reserve_risk_event_schema():
    hourly = _make_hourly(usage_pct=[91.0] + [80.0] * 23)
    events = detect_anomalies(hourly, [], {})
    rr = events[0]
    for key in ("id", "type", "severity", "startAt", "endAt", "metric", "usagePct", "reason"):
        assert key in rr, f"Missing key: {key}"


# ── Spike / Drop ─────────────────────────────────────────────────────────────

def test_spike_warning_above_p95():
    forecasts = _make_forecasts(forecast_mw=30000.0, std=1000.0)
    # p95_upper ≈ 31960; p99_upper ≈ 32576
    actual = [32100.0] + [30000.0] * 23  # above p95, below p99 → warning
    events = detect_anomalies(_make_hourly(actual_mw=actual), forecasts, {})
    spikes = [e for e in events if e["type"] == "spike"]
    assert len(spikes) >= 1
    assert spikes[0]["severity"] == "warning"


def test_spike_critical_above_p99():
    forecasts = _make_forecasts(forecast_mw=30000.0, std=1000.0)
    actual = [33000.0] + [30000.0] * 23  # above p99 → critical
    events = detect_anomalies(_make_hourly(actual_mw=actual), forecasts, {})
    spikes = [e for e in events if e["type"] == "spike"]
    assert len(spikes) >= 1
    assert spikes[0]["severity"] == "critical"


def test_drop_warning_below_p95():
    forecasts = _make_forecasts(forecast_mw=30000.0, std=1000.0)
    # p95_lower ≈ 28040; p99_lower ≈ 27424
    actual = [27900.0] + [30000.0] * 23  # below p95, above p99 → warning
    events = detect_anomalies(_make_hourly(actual_mw=actual), forecasts, {})
    drops = [e for e in events if e["type"] == "drop"]
    assert len(drops) >= 1
    assert drops[0]["severity"] == "warning"


def test_drop_critical_below_p99():
    forecasts = _make_forecasts(forecast_mw=30000.0, std=1000.0)
    actual = [27000.0] + [30000.0] * 23  # below p99 → critical
    events = detect_anomalies(_make_hourly(actual_mw=actual), forecasts, {})
    drops = [e for e in events if e["type"] == "drop"]
    assert len(drops) >= 1
    assert drops[0]["severity"] == "critical"


def test_no_spike_drop_within_bounds():
    forecasts = _make_forecasts(forecast_mw=30000.0, std=1000.0)
    events = detect_anomalies(_make_hourly(actual_mw=[30000.0] * 24), forecasts, {})
    assert not [e for e in events if e["type"] in ("spike", "drop")]


def test_no_spike_drop_without_forecasts():
    hourly = _make_hourly(actual_mw=[99999.0] * 24)
    events = detect_anomalies(hourly, [], {})
    assert not [e for e in events if e["type"] in ("spike", "drop")]


# ── Drift ────────────────────────────────────────────────────────────────────

def test_drift_detected_sustained_above():
    # residual = 30000 - 20000 = 10000 >> threshold 800 for all 24h
    forecasts = _make_forecasts(forecast_mw=20000.0, std=100.0)
    cfg = {"drift": {"ewma_alpha": 0.3, "threshold_mw": 800.0, "sustained_hours": 3}}
    events = detect_anomalies(_make_hourly(actual_mw=[30000.0] * 24), forecasts, cfg)
    drift = [e for e in events if e["type"] == "drift"]
    assert len(drift) >= 1
    assert drift[0]["severity"] == "warning"
    assert drift[0]["metric"] == "residual_mw"


def test_drift_detected_sustained_below():
    # residual = 10000 - 30000 = -20000 << -800 for all 24h
    forecasts = _make_forecasts(forecast_mw=30000.0, std=100.0)
    cfg = {"drift": {"ewma_alpha": 0.3, "threshold_mw": 800.0, "sustained_hours": 3}}
    events = detect_anomalies(_make_hourly(actual_mw=[10000.0] * 24), forecasts, cfg)
    drift = [e for e in events if e["type"] == "drift"]
    assert len(drift) >= 1


def test_drift_not_detected_small_residual():
    forecasts = _make_forecasts(forecast_mw=30000.0, std=1000.0)
    cfg = {"drift": {"ewma_alpha": 0.3, "threshold_mw": 800.0, "sustained_hours": 3}}
    # residual ≈ 100 << 800
    events = detect_anomalies(_make_hourly(actual_mw=[30100.0] * 24), forecasts, cfg)
    assert not [e for e in events if e["type"] == "drift"]


def test_drift_not_detected_without_forecasts():
    cfg = {"drift": {"ewma_alpha": 0.3, "threshold_mw": 800.0, "sustained_hours": 3}}
    events = detect_anomalies(_make_hourly(), [], cfg)
    assert not [e for e in events if e["type"] == "drift"]


def test_drift_event_schema():
    forecasts = _make_forecasts(forecast_mw=20000.0, std=100.0)
    cfg = {"drift": {"ewma_alpha": 0.3, "threshold_mw": 800.0, "sustained_hours": 3}}
    events = detect_anomalies(_make_hourly(actual_mw=[30000.0] * 24), forecasts, cfg)
    drift = [e for e in events if e["type"] == "drift"][0]
    for key in ("id", "type", "severity", "startAt", "endAt", "metric", "residualAvgMw", "method", "thresholdMw", "reason"):
        assert key in drift, f"Missing key: {key}"


# ── Event IDs ────────────────────────────────────────────────────────────────

def test_event_ids_are_unique():
    hourly = _make_hourly(
        usage_pct=[96.0] * 5 + [80.0] * 19,
        actual_mw=[33000.0] * 5 + [30000.0] * 19,
    )
    forecasts = _make_forecasts(forecast_mw=30000.0, std=1000.0)
    cfg = {
        "reserve_risk": {"warning_pct": 90.0, "critical_pct": 95.0},
        "drift": {"ewma_alpha": 0.3, "threshold_mw": 800.0, "sustained_hours": 3},
    }
    events = detect_anomalies(hourly, forecasts, cfg)
    ids = [e["id"] for e in events]
    assert len(ids) == len(set(ids))


def test_no_events_when_everything_normal():
    events = detect_anomalies(_make_hourly(usage_pct=[80.0] * 24), [], {})
    assert events == []
