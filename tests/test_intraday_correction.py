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


def test_intraday_correction_damps_afternoon_negative_residual():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 12, 19_000.0),
        _actual_point(target, 13, 19_000.0),
        _actual_point(target, 14, 19_000.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "decay_per_hour": 1.0,
            "negative_residual_damping": {
                "enabled": True,
                "min_reference_hour": 12,
                "multiplier": 0.5,
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.applied is True
    assert result.negative_adjustment_damped is True
    assert result.base_adjustment_mw == pytest.approx(-500.0)
    assert result.forecasts[15].forecast_mw == pytest.approx(19_500.0)


def test_intraday_correction_keeps_morning_negative_residual():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 7, 19_000.0),
        _actual_point(target, 8, 19_000.0),
        _actual_point(target, 9, 19_000.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "decay_per_hour": 1.0,
            "negative_residual_damping": {
                "enabled": True,
                "min_reference_hour": 12,
                "multiplier": 0.5,
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.applied is True
    assert result.negative_adjustment_damped is False
    assert result.base_adjustment_mw == pytest.approx(-1_000.0)
    assert result.forecasts[10].forecast_mw == pytest.approx(19_000.0)


def test_intraday_ramp_guard_caps_near_term_jump_after_late_morning_actual():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[11] = HourlyForecast(
        ts=f"{target.isoformat()}T11:00:00+09:00",
        forecast_mw=23_500.0,
        p95_lower_mw=23_000.0,
        p95_upper_mw=24_000.0,
        p99_lower_mw=22_700.0,
        p99_upper_mw=24_300.0,
    )
    forecasts[12] = HourlyForecast(
        ts=f"{target.isoformat()}T12:00:00+09:00",
        forecast_mw=24_000.0,
        p95_lower_mw=23_500.0,
        p95_upper_mw=24_500.0,
        p99_lower_mw=23_200.0,
        p99_upper_mw=24_800.0,
    )
    actual_series = [
        _actual_point(target, 8, 20_000.0),
        _actual_point(target, 9, 20_000.0),
        _actual_point(target, 10, 20_000.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "ramp_guard": {
                "enabled": True,
                "min_reference_hour": 10,
                "max_lead_hours": 2,
                "max_increase_mw_by_lead_hour": [1200, 1500],
                "max_decrease_mw_by_lead_hour": [1200, 1500],
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.applied is True
    assert result.ramp_guard_applied is True
    assert result.forecasts[11].forecast_mw == pytest.approx(21_200.0)
    assert result.forecasts[11].p95_upper_mw == pytest.approx(21_700.0)
    assert result.forecasts[12].forecast_mw == pytest.approx(21_500.0)


def test_intraday_ramp_guard_does_not_limit_real_morning_ramp():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[9] = HourlyForecast(
        ts=f"{target.isoformat()}T09:00:00+09:00",
        forecast_mw=23_500.0,
        p95_lower_mw=23_000.0,
        p95_upper_mw=24_000.0,
        p99_lower_mw=22_700.0,
        p99_upper_mw=24_300.0,
    )
    actual_series = [
        _actual_point(target, 6, 20_000.0),
        _actual_point(target, 7, 20_000.0),
        _actual_point(target, 8, 20_000.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "ramp_guard": {
                "enabled": True,
                "min_reference_hour": 10,
                "max_lead_hours": 2,
                "max_increase_mw_by_lead_hour": [1200, 1500],
                "max_decrease_mw_by_lead_hour": [1200, 1500],
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.ramp_guard_applied is False
    assert result.forecasts[9].forecast_mw == pytest.approx(23_500.0)


def test_intraday_ramp_guard_caps_near_term_drop_after_afternoon_actual():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[16] = HourlyForecast(
        ts=f"{target.isoformat()}T16:00:00+09:00",
        forecast_mw=16_000.0,
        p95_lower_mw=15_500.0,
        p95_upper_mw=16_500.0,
        p99_lower_mw=15_200.0,
        p99_upper_mw=16_800.0,
    )
    forecasts[17] = HourlyForecast(
        ts=f"{target.isoformat()}T17:00:00+09:00",
        forecast_mw=15_000.0,
        p95_lower_mw=14_500.0,
        p95_upper_mw=15_500.0,
        p99_lower_mw=14_200.0,
        p99_upper_mw=15_800.0,
    )
    actual_series = [
        _actual_point(target, 13, 20_000.0),
        _actual_point(target, 14, 20_000.0),
        _actual_point(target, 15, 20_000.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "ramp_guard": {
                "enabled": True,
                "min_reference_hour": 10,
                "max_lead_hours": 2,
                "max_increase_mw_by_lead_hour": [1200, 1500],
                "max_decrease_mw_by_lead_hour": [1000, 1800],
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.applied is True
    assert result.ramp_guard_applied is True
    assert result.forecasts[16].forecast_mw == pytest.approx(19_000.0)
    assert result.forecasts[16].p95_lower_mw == pytest.approx(18_500.0)
    assert result.forecasts[17].forecast_mw == pytest.approx(18_200.0)


def test_intraday_ramp_guard_allows_plausible_near_term_drop():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[16] = HourlyForecast(
        ts=f"{target.isoformat()}T16:00:00+09:00",
        forecast_mw=19_200.0,
        p95_lower_mw=18_700.0,
        p95_upper_mw=19_700.0,
        p99_lower_mw=18_400.0,
        p99_upper_mw=20_000.0,
    )
    actual_series = [
        _actual_point(target, 13, 20_000.0),
        _actual_point(target, 14, 20_000.0),
        _actual_point(target, 15, 20_000.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "ramp_guard": {
                "enabled": True,
                "min_reference_hour": 10,
                "max_lead_hours": 1,
                "max_increase_mw_by_lead_hour": [1200],
                "max_decrease_mw_by_lead_hour": [1000],
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.ramp_guard_applied is False
    assert result.forecasts[16].forecast_mw == pytest.approx(19_200.0)


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
