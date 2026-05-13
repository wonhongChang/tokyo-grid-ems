"""Focused tests for holiday-lag daytime heat guard behavior."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from python.forecast.adjustment import PostHolidayTimeBandGuard
from python.forecast.baseline import HourlyForecast


def _guard_config() -> dict:
    return {
        "adjustment": {
            "post_holiday_timeband_guard": {
                "enabled": True,
                "min_consec_holiday_len": 3,
                "max_days_since_holiday_end": 1,
                "daytime": {
                    "hours": [10, 11, 12, 13, 14, 15, 16, 17, 18],
                    "min_temp_anomaly_7d": 2.0,
                    "block_negative_shift": True,
                    "activate_on_holiday_lag": True,
                    "upward_offset_mw": 300.0,
                    "max_upward_offset_mw": 900.0,
                },
            }
        }
    }


def _forecasts(target: date, forecast_mw: float) -> list[HourlyForecast]:
    return [
        HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=forecast_mw,
            p95_lower_mw=forecast_mw - 1000.0,
            p95_upper_mw=forecast_mw + 1000.0,
            p99_lower_mw=forecast_mw - 1500.0,
            p99_upper_mw=forecast_mw + 1500.0,
        )
        for hour in range(24)
    ]


def _features() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "hour": hour,
            "consec_holiday_len": 0,
            "days_since_holiday_end": 3,
            "temp_anomaly_7d": 2.5 if 10 <= hour <= 18 else 0.0,
        }
        for hour in range(24)
    ])


def test_guard_blocks_negative_daytime_when_week_ago_was_holiday():
    target = date(2025, 5, 13)  # 2025-05-06 was a Golden Week public holiday.
    raw = _forecasts(target, 28_000.0)
    adjusted = [
        HourlyForecast(
            ts=point.ts,
            forecast_mw=point.forecast_mw - (500.0 if 10 <= hour <= 18 else 0.0),
            p95_lower_mw=point.p95_lower_mw - (500.0 if 10 <= hour <= 18 else 0.0),
            p95_upper_mw=point.p95_upper_mw - (500.0 if 10 <= hour <= 18 else 0.0),
            p99_lower_mw=point.p99_lower_mw - (500.0 if 10 <= hour <= 18 else 0.0),
            p99_upper_mw=point.p99_upper_mw - (500.0 if 10 <= hour <= 18 else 0.0),
        )
        for hour, point in enumerate(raw)
    ]

    result = PostHolidayTimeBandGuard(_guard_config()).apply(raw, adjusted, _features())

    for hour, point in enumerate(result):
        if 10 <= hour <= 18:
            assert point.forecast_mw == pytest.approx(raw[hour].forecast_mw + 300.0)
