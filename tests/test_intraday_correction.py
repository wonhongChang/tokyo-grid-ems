"""Tests for python/forecast/intraday_correction.py."""
from __future__ import annotations

from datetime import date

import pytest

from python.forecast.baseline import HourlyForecast
from python.forecast.intraday_correction import IntradayResidualCorrector


def _make_forecasts(target_date: date, forecast_mw: float = 20_000.0) -> list[HourlyForecast]:
    return [
        HourlyForecast(
            ts=f"{target_date.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=forecast_mw,
            p95_lower_mw=forecast_mw - 500.0,
            p95_upper_mw=forecast_mw + 500.0,
            p99_lower_mw=forecast_mw - 800.0,
            p99_upper_mw=forecast_mw + 800.0,
        )
        for hour in range(24)
    ]


def _actual_point(target_date: date, hour: int, actual_mw: float) -> dict:
    return {
        "ts": f"{target_date.isoformat()}T{hour:02d}:00:00+09:00",
        "actualMw": actual_mw,
        "tepcoForecastMw": actual_mw,
        "usagePct": 80.0,
        "supplyMw": 25_000.0,
    }


def test_intraday_correction_adjusts_future_hours_only():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 8, 21_000.0),
        _actual_point(target, 9, 21_200.0),
        _actual_point(target, 10, 21_400.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.5,
            "decay_per_hour": 1.0,
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.applied is True
    assert result.last_observed_hour == 10
    assert result.base_adjustment_mw == pytest.approx(600.0)
    assert result.forecasts[10].forecast_mw == pytest.approx(20_000.0)
    assert result.forecasts[11].forecast_mw == pytest.approx(20_600.0)
    assert result.forecasts[23].forecast_mw == pytest.approx(20_600.0)


def test_intraday_correction_decays_farther_hours():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 8, 21_000.0),
        _actual_point(target, 9, 21_000.0),
        _actual_point(target, 10, 21_000.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "decay_per_hour": 0.5,
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.forecasts[11].forecast_mw == pytest.approx(21_000.0)
    assert result.forecasts[12].forecast_mw == pytest.approx(20_500.0)
    assert result.forecasts[13].forecast_mw == pytest.approx(20_250.0)


def test_intraday_correction_waits_for_minimum_observed_hours():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 9, 21_000.0),
        _actual_point(target, 10, 21_000.0),
    ]

    result = IntradayResidualCorrector({}).apply(forecasts, actual_series)

    assert result.applied is False
    assert result.forecasts == forecasts


def test_intraday_correction_uses_tepco_forecast_fallback_for_operational_adjustment():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 8, 21_000.0),
        _actual_point(target, 9, 21_000.0),
        {
            **_actual_point(target, 10, 21_000.0),
            "actualSource": "tepco_forecast_fallback",
        },
    ]

    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.5,
            "decay_per_hour": 1.0,
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.applied is True
    assert result.observed_hours == 3
    assert result.last_observed_hour == 10
    assert result.forecasts[11].forecast_mw == pytest.approx(20_500.0)


def test_intraday_correction_clips_large_adjustment():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 8, 30_000.0),
        _actual_point(target, 9, 30_000.0),
        _actual_point(target, 10, 30_000.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.applied is True
    assert result.base_adjustment_mw == pytest.approx(1_200.0)
    assert result.forecasts[11].forecast_mw == pytest.approx(21_200.0)


def test_intraday_correction_does_not_mark_applied_after_final_hour():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 21, 21_000.0),
        _actual_point(target, 22, 21_000.0),
        _actual_point(target, 23, 21_000.0),
    ]

    result = IntradayResidualCorrector({}).apply(forecasts, actual_series)

    assert result.applied is False
    assert result.last_observed_hour == 23
    assert result.forecasts == forecasts
