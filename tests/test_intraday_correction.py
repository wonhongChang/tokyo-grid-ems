"""Tests for python/forecast/intraday_correction.py."""
from __future__ import annotations

from datetime import date

import pandas as pd
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


def test_intraday_correction_ignores_tepco_forecast_fallback_for_residuals():
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

    assert result.applied is False
    assert result.observed_hours == 2
    assert result.fallback_residuals_ignored == 1
    assert result.last_observed_hour == 9
    assert result.forecasts == forecasts


def test_intraday_correction_carries_last_real_residual_across_midnight():
    target = date(2026, 5, 12)
    previous = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    previous_forecasts = _make_forecasts(previous, 20_000.0)
    previous_actual_series = [
        _actual_point(previous, 21, 19_000.0),
        {
            **_actual_point(previous, 22, 20_000.0),
            "actualSource": "tepco_forecast_fallback",
        },
        {
            **_actual_point(previous, 23, 20_000.0),
            "actualSource": "tepco_forecast_fallback",
        },
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "min_observed_hours": 3,
            "operational_calibration": {
                "day_boundary_carryover": {
                    "enabled": True,
                    "shrinkage": 1.0,
                    "decay_per_hour": 1.0,
                    "max_age_hours": 8,
                    "max_abs_adjustment_mw": 1_200.0,
                },
                "day_level_scale": {"enabled": False},
            },
        }
    })

    result = corrector.apply(
        forecasts,
        [],
        previous_actual_series=previous_actual_series,
        previous_forecasts=previous_forecasts,
    )

    assert result.applied is True
    assert result.carryover_source_hour == 21
    assert result.carryover_adjustment_mw == pytest.approx(-1_000.0)
    assert result.forecasts[0].forecast_mw == pytest.approx(19_000.0)
    assert result.forecasts[23].forecast_mw == pytest.approx(19_000.0)


def test_intraday_correction_applies_day_level_scale_when_lag_is_overheated_and_cooler():
    target = date(2026, 5, 12)
    forecasts = _make_forecasts(target, 24_000.0)
    inference_features = pd.DataFrame([
        {
            "hour": 0,
            "lag_24h": 25_000.0,
            "recent_same_business_type_mean": 22_000.0,
            "temp_delta_24h": -4.0,
            "heating_degree": 2.0,
        },
        {
            "hour": 1,
            "lag_24h": 24_000.0,
            "recent_same_business_type_mean": 23_800.0,
            "temp_delta_24h": -4.0,
            "heating_degree": 2.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "min_observed_hours": 3,
            "operational_calibration": {
                "day_boundary_carryover": {"enabled": False},
                "day_level_scale": {
                    "enabled": True,
                    "lag_overheat_threshold_mw": 600.0,
                    "temp_drop_threshold_c": 1.5,
                    "lag_overheat_weight": 0.25,
                    "max_abs_bias_mw": 700.0,
                    "observed_fade_hours": 3,
                    "max_heating_degree": 7.0,
                },
            },
        }
    })

    result = corrector.apply(forecasts, [], inference_features=inference_features)

    assert result.applied is True
    assert result.applied_day_bias_mw == pytest.approx(-480.0)
    assert result.forecasts[0].forecast_mw == pytest.approx(23_520.0)
    assert result.forecasts[1].forecast_mw == pytest.approx(24_000.0)
    assert "lag24_overheat_with_cooler_day" in result.applied_regime_reason


def test_intraday_correction_applies_non_business_transition_prior_before_observations():
    target = date(2026, 5, 23)  # Saturday after a business day
    forecasts = _make_forecasts(target, 24_000.0)
    inference_features = pd.DataFrame([
        {
            "hour": 0,
            "is_non_business_day": 1,
            "lag_24h_business_type_mismatch": 1,
            "lag_24h": 25_500.0,
            "recent_same_business_type_mean": 22_000.0,
        },
        {
            "hour": 1,
            "is_non_business_day": 1,
            "lag_24h_business_type_mismatch": 1,
            "lag_24h": 25_000.0,
            "recent_same_business_type_mean": 22_000.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "min_observed_hours": 3,
            "operational_calibration": {
                "day_boundary_carryover": {"enabled": False},
                "day_level_scale": {"enabled": False},
                "business_type_transition_prior": {
                    "enabled": True,
                    "force_off_hour": 6,
                    "lag_overheat_threshold_mw": 1_500.0,
                    "base_allowed_excess_mw": 900.0,
                    "shrinkage": 0.25,
                    "max_abs_bias_mw": 500.0,
                },
            },
        }
    })

    result = corrector.apply(forecasts, [], inference_features=inference_features)

    assert result.applied is True
    assert result.business_type_transition_prior_applied is True
    assert result.business_type_transition_prior_bias_mw == pytest.approx(-275.0)
    assert result.business_type_transition_applied is False
    assert result.forecasts[0].forecast_mw == pytest.approx(23_725.0)
    assert result.forecasts[1].forecast_mw == pytest.approx(23_725.0)
    assert result.forecasts[2].forecast_mw == pytest.approx(24_000.0)
    assert "business_type_transition_prior_lag_overheat" in result.applied_regime_reason


def test_intraday_correction_turns_transition_prior_off_at_morning_cutoff():
    target = date(2026, 5, 23)  # Saturday after a business day
    forecasts = _make_forecasts(target, 24_000.0)
    actual_series = [_actual_point(target, 6, 23_500.0)]
    inference_features = pd.DataFrame([
        {
            "hour": 7,
            "is_non_business_day": 1,
            "lag_24h_business_type_mismatch": 1,
            "lag_24h": 28_000.0,
            "recent_same_business_type_mean": 22_000.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "min_observed_hours": 3,
            "operational_calibration": {
                "day_boundary_carryover": {"enabled": False},
                "day_level_scale": {"enabled": False},
                "business_type_transition_prior": {
                    "enabled": True,
                    "force_off_hour": 6,
                    "lag_overheat_threshold_mw": 1_500.0,
                    "base_allowed_excess_mw": 900.0,
                    "shrinkage": 0.25,
                    "max_abs_bias_mw": 500.0,
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.applied is False
    assert result.business_type_transition_prior_applied is False
    assert result.business_type_transition_prior_bias_mw == pytest.approx(0.0)
    assert result.forecasts == forecasts


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


def test_intraday_correction_deweights_large_business_day_midday_residual():
    target = date(2026, 5, 11)  # Monday
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 10, 20_000.0),
        _actual_point(target, 11, 20_000.0),
        _actual_point(target, 12, 18_000.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "decay_per_hour": 1.0,
            "midday_residual_deweight": {
                "enabled": True,
                "hours": [12],
                "weight": 0.25,
                "min_abs_residual_mw": 600.0,
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.midday_residual_deweighted is True
    assert result.base_adjustment_mw == pytest.approx(-222.2, abs=0.1)
    assert result.forecasts[13].forecast_mw == pytest.approx(19_777.8)


def test_intraday_correction_keeps_weekend_midday_residual_weight():
    target = date(2026, 5, 16)  # Saturday
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 10, 20_000.0),
        _actual_point(target, 11, 20_000.0),
        _actual_point(target, 12, 18_000.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "decay_per_hour": 1.0,
            "midday_residual_deweight": {
                "enabled": True,
                "hours": [12],
                "weight": 0.25,
                "min_abs_residual_mw": 600.0,
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.midday_residual_deweighted is False
    assert result.base_adjustment_mw == pytest.approx(-666.7, abs=0.1)


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


def test_intraday_correction_dampens_non_business_day_lag_overheat_after_observed_evidence():
    target = date(2026, 5, 23)  # Saturday after a business day
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[8] = HourlyForecast(
        ts=f"{target.isoformat()}T08:00:00+09:00",
        forecast_mw=26_000.0,
        p95_lower_mw=25_500.0,
        p95_upper_mw=26_500.0,
        p99_lower_mw=25_200.0,
        p99_upper_mw=26_800.0,
    )
    actual_series = [
        _actual_point(target, 5, 19_000.0),
        _actual_point(target, 6, 19_000.0),
        _actual_point(target, 7, 19_000.0),
    ]
    inference_features = pd.DataFrame([
        {
            "hour": 8,
            "is_non_business_day": 1,
            "lag_24h_business_type_mismatch": 1,
            "lag_24h": 30_000.0,
            "recent_same_business_type_mean": 22_000.0,
            "temp_anomaly_7d": -3.0,
            "cooling_degree": 0.0,
        }
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "operational_calibration": {
                "business_type_transition": {
                    "enabled": True,
                    "min_observed_hour": 6,
                    "max_recent_residual_mw": -300.0,
                    "lag_overheat_threshold_mw": 1_500.0,
                    "base_allowed_excess_mw": 900.0,
                    "shrinkage": 0.5,
                    "max_abs_bias_mw": 1_200.0,
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.business_type_transition_applied is True
    assert result.business_type_transition_bias_mw == pytest.approx(-1_200.0)
    assert result.forecasts[7].forecast_mw == pytest.approx(20_000.0)
    assert result.forecasts[8].forecast_mw == pytest.approx(24_800.0)
    assert "business_type_transition_lag_overheat" in result.applied_regime_reason


def test_intraday_shape_guard_caps_afternoon_drop():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[14] = HourlyForecast(
        ts=f"{target.isoformat()}T14:00:00+09:00",
        forecast_mw=35_000.0,
        p95_lower_mw=34_500.0,
        p95_upper_mw=35_500.0,
        p99_lower_mw=34_200.0,
        p99_upper_mw=35_800.0,
    )
    forecasts[15] = HourlyForecast(
        ts=f"{target.isoformat()}T15:00:00+09:00",
        forecast_mw=33_000.0,
        p95_lower_mw=32_500.0,
        p95_upper_mw=33_500.0,
        p99_lower_mw=32_200.0,
        p99_upper_mw=33_800.0,
    )
    forecasts[16] = HourlyForecast(
        ts=f"{target.isoformat()}T16:00:00+09:00",
        forecast_mw=31_500.0,
        p95_lower_mw=31_000.0,
        p95_upper_mw=32_000.0,
        p99_lower_mw=30_700.0,
        p99_upper_mw=32_300.0,
    )
    actual_series = [
        _actual_point(target, 11, 20_000.0),
        _actual_point(target, 12, 20_000.0),
        _actual_point(target, 13, 20_000.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "shape_guard": {
                "enabled": True,
                "min_reference_hour": 12,
                "hours": [15, 16],
                "max_drop_mw": 1_000.0,
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.shape_guard_applied is True
    assert result.forecasts[14].forecast_mw == pytest.approx(35_000.0)
    assert result.forecasts[15].forecast_mw == pytest.approx(34_000.0)
    assert result.forecasts[16].forecast_mw == pytest.approx(33_000.0)


def test_intraday_shape_guard_waits_for_reference_hour():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[15] = HourlyForecast(
        ts=f"{target.isoformat()}T15:00:00+09:00",
        forecast_mw=17_000.0,
        p95_lower_mw=16_500.0,
        p95_upper_mw=17_500.0,
        p99_lower_mw=16_200.0,
        p99_upper_mw=17_800.0,
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
            "shape_guard": {
                "enabled": True,
                "min_reference_hour": 12,
                "hours": [15],
                "max_drop_mw": 1_000.0,
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.shape_guard_applied is False
    assert result.forecasts[15].forecast_mw == pytest.approx(17_000.0)


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
            "shape_guard": {
                "enabled": True,
                "min_reference_hour": 12,
                "hours": [18, 19, 20],
                "max_drop_mw": 1_000.0,
            },
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


def test_intraday_ramp_guard_relaxes_observed_demand_drop_without_time_gate():
    target = date(2026, 5, 19)
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[18] = HourlyForecast(
        ts=f"{target.isoformat()}T18:00:00+09:00",
        forecast_mw=30_350.0,
        p95_lower_mw=29_850.0,
        p95_upper_mw=30_850.0,
        p99_lower_mw=29_550.0,
        p99_upper_mw=31_150.0,
    )
    forecasts[19] = HourlyForecast(
        ts=f"{target.isoformat()}T19:00:00+09:00",
        forecast_mw=28_567.3,
        p95_lower_mw=28_067.3,
        p95_upper_mw=29_067.3,
        p99_lower_mw=27_767.3,
        p99_upper_mw=29_367.3,
    )
    forecasts[20] = HourlyForecast(
        ts=f"{target.isoformat()}T20:00:00+09:00",
        forecast_mw=27_510.4,
        p95_lower_mw=27_010.4,
        p95_upper_mw=28_010.4,
        p99_lower_mw=26_710.4,
        p99_upper_mw=28_310.4,
    )
    actual_series = [
        _actual_point(target, 15, 33_000.0),
        _actual_point(target, 16, 32_710.0),
        _actual_point(target, 17, 31_980.0),
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
                "max_lead_hours": 3,
                "max_increase_mw_by_lead_hour": [1200, 1500, 2000],
                "max_decrease_mw_by_lead_hour": [1000, 1800, 2400],
                "observed_drop_relaxation": {
                    "enabled": True,
                    "min_recent_drop_mw": 700,
                    "lookback_hours": 2,
                    "skip_shape_guard": True,
                    "max_decrease_mw_by_lead_hour": [2000, 3600, 5000],
                },
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.ramp_guard_applied is False
    assert result.shape_guard_applied is False
    assert result.observed_drop_relaxation_active is True
    assert result.forecasts[18].forecast_mw == pytest.approx(30_350.0)
    assert result.forecasts[19].forecast_mw == pytest.approx(28_567.3)
    assert result.forecasts[20].forecast_mw == pytest.approx(27_510.4)


def test_intraday_ramp_guard_still_caps_extreme_observed_drop():
    target = date(2026, 5, 19)
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[20] = HourlyForecast(
        ts=f"{target.isoformat()}T20:00:00+09:00",
        forecast_mw=25_000.0,
        p95_lower_mw=24_500.0,
        p95_upper_mw=25_500.0,
        p99_lower_mw=24_200.0,
        p99_upper_mw=25_800.0,
    )
    actual_series = [
        _actual_point(target, 15, 33_000.0),
        _actual_point(target, 16, 32_710.0),
        _actual_point(target, 17, 31_980.0),
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
                "max_lead_hours": 3,
                "max_increase_mw_by_lead_hour": [1200, 1500, 2000],
                "max_decrease_mw_by_lead_hour": [1000, 1800, 2400],
                "observed_drop_relaxation": {
                    "enabled": True,
                    "min_recent_drop_mw": 700,
                    "lookback_hours": 2,
                    "skip_shape_guard": True,
                    "max_decrease_mw_by_lead_hour": [2000, 3600, 5000],
                },
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.ramp_guard_applied is True
    assert result.observed_drop_relaxation_active is True
    assert result.forecasts[20].forecast_mw == pytest.approx(26_980.0)


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
