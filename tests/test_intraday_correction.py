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
        _actual_point(target, 9, 20_400.0),
        _actual_point(target, 10, 20_400.0),
    ]

    result = IntradayResidualCorrector({}).apply(forecasts, actual_series)

    assert result.applied is False
    assert result.forecasts == forecasts


def test_intraday_correction_ignores_tepco_forecast_fallback_for_residuals():
    target = date(2026, 5, 11)
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 8, 20_400.0),
        _actual_point(target, 9, 20_400.0),
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


def test_intraday_correction_prefers_early_same_day_residuals_over_stale_midnight_carryover():
    target = date(2026, 6, 18)
    previous = date(2026, 6, 17)
    forecasts = _make_forecasts(target, 20_000.0)
    previous_forecasts = _make_forecasts(previous, 20_000.0)
    previous_actual_series = [
        _actual_point(previous, 21, 19_000.0),
        {
            **_actual_point(previous, 22, 20_000.0),
            "actualSource": "tepco_forecast_fallback",
        },
    ]
    actual_series = [
        _actual_point(target, 0, 21_000.0),
        _actual_point(target, 1, 20_900.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "min_observed_hours": 3,
            "early_observed_residual_carryover": {
                "enabled": True,
                "min_observed_hours": 2,
                "min_abs_mean_residual_mw": 500.0,
                "require_same_sign": True,
                "shrinkage": 0.5,
                "max_abs_adjustment_mw": 700.0,
            },
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
        actual_series,
        previous_actual_series=previous_actual_series,
        previous_forecasts=previous_forecasts,
    )

    assert result.applied is True
    assert result.carryover_adjustment_mw == pytest.approx(0.0)
    assert result.early_observed_residual_carryover_applied is True
    assert result.early_observed_residual_carryover_mw == pytest.approx(475.0)
    assert result.early_observed_residual_count == 2
    assert result.forecasts[0].forecast_mw == pytest.approx(20_000.0)
    assert result.forecasts[1].forecast_mw == pytest.approx(20_000.0)
    assert result.forecasts[2].forecast_mw == pytest.approx(20_475.0)
    assert "early_observed_residual_carryover" in result.applied_regime_reason
    assert "day_boundary_residual_carryover" not in result.applied_regime_reason


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


def test_intraday_correction_keeps_transition_prior_alive_until_handoff_hour():
    target = date(2026, 5, 23)  # Saturday after a business day
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[7] = HourlyForecast(
        ts=f"{target.isoformat()}T07:00:00+09:00",
        forecast_mw=24_000.0,
        p95_lower_mw=23_500.0,
        p95_upper_mw=24_500.0,
        p99_lower_mw=23_200.0,
        p99_upper_mw=24_800.0,
    )
    actual_series = [
        _actual_point(target, hour, 20_100.0)
        for hour in range(5)
    ]
    inference_features = pd.DataFrame([{
        "hour": 7,
        "is_non_business_day": 1,
        "lag_24h_business_type_mismatch": 1,
        "lag_24h": 28_500.0,
        "recent_same_business_type_mean": 22_000.0,
    }])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "decay_per_hour": 1.0,
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
                    "positive_residual_mitigation": {
                        "enabled": True,
                        "hours": [6, 7, 8, 9, 10, 11],
                        "multiplier": 0.0,
                    },
                },
                "business_type_transition": {
                    "enabled": True,
                    "min_observed_hour": 6,
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.last_observed_hour == 4
    assert result.base_adjustment_mw == pytest.approx(100.0)
    assert result.business_type_transition_prior_applied is True
    assert result.business_type_transition_prior_bias_mw == pytest.approx(-275.0)
    assert result.positive_residual_mitigation_applied is True
    assert result.positive_residual_mitigation_max_mw == pytest.approx(100.0)
    assert result.business_type_transition_applied is False
    assert result.forecasts[7].forecast_mw == pytest.approx(23_725.0)
    assert "business_type_transition_prior_lag_overheat" in result.applied_regime_reason
    assert "positive_residual_mitigation" in result.applied_regime_reason


def test_intraday_correction_keeps_positive_residual_when_weekend_anchor_has_room():
    target = date(2026, 5, 23)  # Saturday after a business day
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[7] = HourlyForecast(
        ts=f"{target.isoformat()}T07:00:00+09:00",
        forecast_mw=22_800.0,
        p95_lower_mw=22_300.0,
        p95_upper_mw=23_300.0,
        p99_lower_mw=22_000.0,
        p99_upper_mw=23_600.0,
    )
    actual_series = [
        _actual_point(target, hour, 20_100.0)
        for hour in range(5)
    ]
    inference_features = pd.DataFrame([{
        "hour": 7,
        "is_non_business_day": 1,
        "lag_24h_business_type_mismatch": 1,
        "lag_24h": 28_500.0,
        "recent_same_business_type_mean": 22_000.0,
    }])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "decay_per_hour": 1.0,
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
                    "positive_residual_mitigation": {
                        "enabled": True,
                        "hours": [6, 7, 8, 9, 10, 11],
                        "multiplier": 0.0,
                    },
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.business_type_transition_prior_applied is False
    assert result.positive_residual_mitigation_applied is False
    assert result.forecasts[7].forecast_mw == pytest.approx(22_900.0)


def test_intraday_correction_damps_negative_residual_when_weekend_demand_recovers():
    target = date(2026, 5, 23)  # Saturday after a business day
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[7] = HourlyForecast(
        ts=f"{target.isoformat()}T07:00:00+09:00",
        forecast_mw=23_700.0,
        p95_lower_mw=23_200.0,
        p95_upper_mw=24_200.0,
        p99_lower_mw=22_900.0,
        p99_upper_mw=24_500.0,
    )
    forecasts[8] = HourlyForecast(
        ts=f"{target.isoformat()}T08:00:00+09:00",
        forecast_mw=24_800.0,
        p95_lower_mw=24_300.0,
        p95_upper_mw=25_300.0,
        p99_lower_mw=24_000.0,
        p99_upper_mw=25_600.0,
    )
    forecasts[9] = HourlyForecast(
        ts=f"{target.isoformat()}T09:00:00+09:00",
        forecast_mw=25_400.0,
        p95_lower_mw=24_900.0,
        p95_upper_mw=25_900.0,
        p99_lower_mw=24_600.0,
        p99_upper_mw=26_200.0,
    )
    forecasts[11] = HourlyForecast(
        ts=f"{target.isoformat()}T11:00:00+09:00",
        forecast_mw=25_569.0,
        p95_lower_mw=25_069.0,
        p95_upper_mw=26_069.0,
        p99_lower_mw=24_769.0,
        p99_upper_mw=26_369.0,
    )
    actual_series = [
        _actual_point(target, 7, 21_000.0),
        _actual_point(target, 8, 22_600.0),
        _actual_point(target, 9, 24_200.0),
    ]
    inference_features = pd.DataFrame([{
        "hour": 9,
        "is_non_business_day": 1,
        "lag_24h_business_type_mismatch": 1,
        "lag_24h": 30_000.0,
        "recent_same_business_type_mean": 24_000.0,
    }])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "decay_per_hour": 1.0,
            "operational_calibration": {
                "day_boundary_carryover": {"enabled": False},
                "day_level_scale": {"enabled": False},
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "negative_residual_recovery_damping": {
                "enabled": True,
                "recovery_slope_base_mw": 1_000.0,
                "anchor_proximity_tolerance_mw": 1_200.0,
                "damping_factor_default": 0.4,
                "damping_factor_strong": 0.2,
                "strong_recovery_mean_slope_mw": 500.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.neg_residual_recovery_damping_applied is True
    assert result.neg_residual_recovery_damping_factor == pytest.approx(0.2)
    assert result.metadata()["negResidualRecoveryDampingApplied"] is True
    assert result.metadata()["negResidualRecoveryDampingFactor"] == pytest.approx(0.2)
    assert result.base_adjustment_mw == pytest.approx(-1_200.0)
    assert result.forecasts[11].forecast_mw == pytest.approx(25_329.0, abs=0.1)
    assert (
        "negative_residual_recovery_damping_triggered"
        in result.applied_regime_reason
    )


def test_intraday_correction_keeps_negative_residual_when_recovery_is_false():
    target = date(2026, 5, 23)  # Saturday after a business day
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[7] = HourlyForecast(
        ts=f"{target.isoformat()}T07:00:00+09:00",
        forecast_mw=21_300.0,
        p95_lower_mw=20_800.0,
        p95_upper_mw=21_800.0,
        p99_lower_mw=20_500.0,
        p99_upper_mw=22_100.0,
    )
    forecasts[8] = HourlyForecast(
        ts=f"{target.isoformat()}T08:00:00+09:00",
        forecast_mw=24_000.0,
        p95_lower_mw=23_500.0,
        p95_upper_mw=24_500.0,
        p99_lower_mw=23_200.0,
        p99_upper_mw=24_800.0,
    )
    forecasts[9] = HourlyForecast(
        ts=f"{target.isoformat()}T09:00:00+09:00",
        forecast_mw=26_000.0,
        p95_lower_mw=25_500.0,
        p95_upper_mw=26_500.0,
        p99_lower_mw=25_200.0,
        p99_upper_mw=26_800.0,
    )
    forecasts[11] = HourlyForecast(
        ts=f"{target.isoformat()}T11:00:00+09:00",
        forecast_mw=25_569.0,
        p95_lower_mw=25_069.0,
        p95_upper_mw=26_069.0,
        p99_lower_mw=24_769.0,
        p99_upper_mw=26_369.0,
    )
    actual_series = [
        _actual_point(target, 7, 21_000.0),
        _actual_point(target, 8, 22_600.0),
        _actual_point(target, 9, 24_200.0),
    ]
    inference_features = pd.DataFrame([{
        "hour": 9,
        "is_non_business_day": 1,
        "lag_24h_business_type_mismatch": 1,
        "lag_24h": 30_000.0,
        "recent_same_business_type_mean": 24_000.0,
    }])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "decay_per_hour": 1.0,
            "operational_calibration": {
                "day_boundary_carryover": {"enabled": False},
                "day_level_scale": {"enabled": False},
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "negative_residual_recovery_damping": {
                "enabled": True,
                "recovery_slope_base_mw": 1_000.0,
                "anchor_proximity_tolerance_mw": 1_200.0,
                "damping_factor_default": 0.4,
                "damping_factor_strong": 0.2,
                "strong_recovery_mean_slope_mw": 500.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.neg_residual_recovery_damping_applied is False
    assert result.neg_residual_recovery_damping_factor == pytest.approx(1.0)
    assert result.metadata()["negResidualRecoveryDampingApplied"] is False
    assert result.metadata()["negResidualRecoveryDampingFactor"] == pytest.approx(1.0)
    assert result.base_adjustment_mw == pytest.approx(-1_166.7, abs=0.1)
    assert result.forecasts[11].forecast_mw == pytest.approx(24_402.3, abs=0.1)
    assert (
        "negative_residual_recovery_damping_triggered"
        not in result.applied_regime_reason
    )


def test_intraday_correction_damps_positive_residual_when_actual_slope_decelerates():
    target = date(2026, 5, 25)  # Monday
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        12: 31_280.0,
        13: 31_600.0,
        14: 32_750.0,
        15: 33_300.0,
        16: 33_100.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 12, 32_140.0),
        _actual_point(target, 13, 33_120.0),
        _actual_point(target, 14, 33_350.0),
    ]
    inference_features = pd.DataFrame([{
        "hour": 14,
        "recent_same_business_type_mean": 33_000.0,
    }])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "decay_per_hour": 1.0,
            "operational_calibration": {
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "midday_residual_deweight": {"enabled": False},
            "positive_residual_slope_damping": {
                "enabled": True,
                "min_reference_hour": 12,
                "max_lead_hours": 3,
                "min_base_adjustment_mw": 300.0,
                "min_positive_residual_mw": 300.0,
                "min_residual_improvement_mw": 300.0,
                "min_slope_deceleration_mw": 500.0,
                "latest_slope_max_mw": 400.0,
                "peak_excess_allowance_mw": 300.0,
                "damping_factor": 0.4,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(993.3, abs=0.1)
    assert result.positive_residual_slope_damping_applied is True
    assert result.positive_residual_slope_damping_factor == pytest.approx(0.4)
    assert result.positive_residual_slope_damping_max_mw == pytest.approx(596.0)
    assert result.forecasts[15].forecast_mw == pytest.approx(33_697.3, abs=0.1)
    assert result.forecasts[16].forecast_mw == pytest.approx(33_497.3, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    assert residual_logs[0]["hour"] == 15
    assert residual_logs[0]["positiveResidualSlopeDampingFactor"] == pytest.approx(0.4)
    assert residual_logs[0]["finalAdjustmentMw"] == pytest.approx(397.3, abs=0.1)
    assert (
        "positive_residual_slope_damping_triggered"
        in result.applied_regime_reason
    )


def test_intraday_correction_keeps_positive_residual_when_residual_is_worsening():
    target = date(2026, 5, 25)  # Monday
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        12: 31_500.0,
        13: 32_000.0,
        14: 32_400.0,
        15: 33_300.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 12, 32_000.0),
        _actual_point(target, 13, 33_200.0),
        _actual_point(target, 14, 34_200.0),
    ]
    inference_features = pd.DataFrame([{
        "hour": 14,
        "recent_same_business_type_mean": 33_000.0,
    }])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "decay_per_hour": 1.0,
            "operational_calibration": {
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "positive_residual_slope_damping": {
                "enabled": True,
                "min_reference_hour": 12,
                "damping_factor": 0.4,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.positive_residual_slope_damping_applied is False
    assert result.positive_residual_slope_damping_factor == pytest.approx(1.0)
    assert result.base_adjustment_mw == pytest.approx(1_166.7, abs=0.1)
    assert result.forecasts[15].forecast_mw == pytest.approx(34_466.7, abs=0.1)


def test_intraday_damps_morning_positive_carryover_when_shape_support_is_weak():
    target = date(2026, 6, 5)  # Friday ramp carryover over-extension case
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        6: 22_332.0,
        7: 24_134.9,
        8: 26_410.7,
        9: 29_921.0,
        10: 30_827.4,
        11: 30_918.0,
        12: 30_014.3,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 6, 22_660.0),
        _actual_point(target, 7, 25_190.0),
        _actual_point(target, 8, 28_140.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 8, "is_non_business_day": 0},
        {
            "hour": 9,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 3_050.0,
            "recent_same_business_type_delta_mean": 3_023.8,
        },
        {
            "hour": 10,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 710.0,
            "recent_same_business_type_delta_mean": 848.8,
        },
        {
            "hour": 11,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 80.0,
            "recent_same_business_type_delta_mean": 392.5,
        },
        {
            "hour": 12,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -490.0,
            "recent_same_business_type_delta_mean": -771.2,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 0.92,
            "operational_calibration": {
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "positive_residual_slope_damping": {"enabled": False},
            "midday_residual_deweight": {"enabled": False},
            "morning_positive_residual_carryover_damping": {
                "enabled": True,
                "target_hours": [10, 11, 12],
                "min_reference_hour": 7,
                "max_reference_hour": 10,
                "min_lead_hours": 2,
                "max_lead_hours": 4,
                "min_base_adjustment_mw": 300.0,
                "min_recent_ramp_slope_mw": 1_000.0,
                "weak_support_delta_mw": 1_000.0,
                "damping_factor": 0.4,
                "min_damped_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(622.5, abs=0.1)
    assert result.morning_positive_residual_carryover_damping_applied is True
    assert (
        result.morning_positive_residual_carryover_damping_factor
        == pytest.approx(0.4)
    )
    assert (
        result.morning_positive_residual_carryover_damping_max_mw
        == pytest.approx(343.6, abs=0.1)
    )
    assert result.forecasts[9].forecast_mw == pytest.approx(30_543.5, abs=0.1)
    assert result.forecasts[10].forecast_mw == pytest.approx(31_056.5, abs=0.1)
    assert result.forecasts[11].forecast_mw == pytest.approx(31_128.8, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_10 = next(item for item in residual_logs if item["hour"] == 10)
    assert (
        hour_10["morningPositiveResidualCarryoverDampingFactor"]
        == pytest.approx(0.4)
    )
    assert (
        hour_10["morningPositiveResidualCarryoverDampedMw"]
        == pytest.approx(343.6, abs=0.1)
    )
    assert (
        "morning_positive_residual_carryover_damping"
        in result.applied_regime_reason
    )


def test_intraday_keeps_morning_positive_carryover_when_shape_support_is_strong():
    target = date(2026, 6, 5)
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        6: 22_332.0,
        7: 24_134.9,
        8: 26_410.7,
        10: 30_827.4,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 6, 22_660.0),
        _actual_point(target, 7, 25_190.0),
        _actual_point(target, 8, 28_140.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 8, "is_non_business_day": 0},
        {
            "hour": 10,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 2_500.0,
            "recent_same_business_type_delta_mean": 2_300.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "decay_per_hour": 0.92,
            "operational_calibration": {
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "positive_residual_slope_damping": {"enabled": False},
            "morning_positive_residual_carryover_damping": {
                "enabled": True,
                "target_hours": [10],
                "weak_support_delta_mw": 1_000.0,
                "damping_factor": 0.4,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_positive_residual_carryover_damping_applied is False
    assert result.forecasts[10].forecast_mw == pytest.approx(31_400.1, abs=0.1)


def test_intraday_damps_afternoon_positive_carryover_when_shape_support_is_weak():
    target = date(2026, 6, 16)
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        12: 32_312.2,
        13: 33_648.9,
        14: 33_530.0,
        15: 33_350.0,
        16: 33_439.6,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 12, 32_770.0),
        _actual_point(target, 13, 34_350.0),
        _actual_point(target, 14, 34_190.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 14, "is_non_business_day": 0},
        {
            "hour": 15,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -180.0,
            "recent_same_business_type_delta_mean": -181.2,
        },
        {
            "hour": 16,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 170.0,
            "recent_same_business_type_delta_mean": -153.8,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "operational_calibration": {
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "positive_residual_slope_damping": {"enabled": False},
            "morning_positive_residual_carryover_damping": {"enabled": False},
            "afternoon_positive_residual_carryover_damping": {
                "enabled": True,
                "business_day_only": False,
                "target_hours": [15, 16],
                "min_reference_hour": 12,
                "max_reference_hour": 15,
                "min_lead_hours": 1,
                "max_lead_hours": 3,
                "min_base_adjustment_mw": 250.0,
                "weak_support_delta_mw": 300.0,
                "damping_factor": 0.4,
                "min_damped_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(363.8, abs=0.1)
    assert result.afternoon_positive_residual_carryover_damping_applied is True
    assert (
        result.afternoon_positive_residual_carryover_damping_factor
        == pytest.approx(0.4)
    )
    assert (
        result.afternoon_positive_residual_carryover_damping_max_mw
        == pytest.approx(218.3, abs=0.1)
    )
    assert result.forecasts[15].forecast_mw == pytest.approx(33_495.5, abs=0.1)
    assert result.forecasts[16].forecast_mw == pytest.approx(33_585.1, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_15 = next(item for item in residual_logs if item["hour"] == 15)
    assert (
        hour_15["afternoonPositiveResidualCarryoverDampingFactor"]
        == pytest.approx(0.4)
    )
    assert (
        hour_15["afternoonPositiveResidualCarryoverDampedMw"]
        == pytest.approx(218.3, abs=0.1)
    )
    assert (
        "afternoon_positive_residual_carryover_damping"
        in result.applied_regime_reason
    )


def test_intraday_damps_non_business_evening_positive_carryover_when_shape_is_weak():
    target = date(2026, 6, 13)  # Saturday
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 13, 21_000.0),
        _actual_point(target, 14, 21_000.0),
        _actual_point(target, 15, 21_000.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": hour, "is_non_business_day": 1}
        for hour in range(24)
    ])
    inference_features.loc[18, "lag_24h_hourly_delta"] = -550.0
    inference_features.loc[18, "recent_same_business_type_delta_mean"] = 548.0
    inference_features.loc[19, "lag_24h_hourly_delta"] = -430.0
    inference_features.loc[19, "recent_same_business_type_delta_mean"] = 14.0
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 0.92,
            "operational_calibration": {
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "positive_residual_slope_damping": {"enabled": False},
            "morning_positive_residual_carryover_damping": {"enabled": False},
            "non_business_evening_positive_residual_damping": {
                "enabled": True,
                "target_hours": [18, 19, 20],
                "min_reference_hour": 12,
                "min_lead_hours": 3,
                "max_lead_hours": 6,
                "min_base_adjustment_mw": 500.0,
                "weak_support_delta_mw": 600.0,
                "damping_factor": 0.45,
                "min_damped_mw": 120.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(600.0, abs=0.1)
    assert result.non_business_evening_positive_residual_damping_applied is True
    assert (
        result.non_business_evening_positive_residual_damping_factor
        == pytest.approx(0.45)
    )
    assert (
        result.non_business_evening_positive_residual_damping_max_mw
        == pytest.approx(279.3, abs=0.1)
    )
    assert result.forecasts[16].forecast_mw == pytest.approx(20_600.0, abs=0.1)
    assert result.forecasts[17].forecast_mw == pytest.approx(20_552.0, abs=0.1)
    assert result.forecasts[18].forecast_mw == pytest.approx(20_228.5, abs=0.1)
    assert result.forecasts[19].forecast_mw == pytest.approx(20_210.2, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_18 = next(item for item in residual_logs if item["hour"] == 18)
    assert (
        hour_18["nonBusinessEveningPositiveResidualDampingFactor"]
        == pytest.approx(0.45)
    )
    assert (
        "non_business_evening_positive_residual_damping"
        in result.applied_regime_reason
    )


def test_intraday_damps_non_business_17h_positive_carryover_when_shape_is_weak():
    target = date(2026, 7, 5)  # Sunday
    forecasts = _make_forecasts(target, 20_000.0)
    actual_series = [
        _actual_point(target, 13, 21_000.0),
        _actual_point(target, 14, 21_000.0),
        _actual_point(target, 15, 21_000.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": hour, "is_non_business_day": 1}
        for hour in range(24)
    ])
    inference_features.loc[17, "lag_24h_hourly_delta"] = 150.0
    inference_features.loc[17, "recent_same_business_type_delta_mean"] = 460.0
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 0.92,
            "operational_calibration": {
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "positive_residual_slope_damping": {"enabled": False},
            "morning_positive_residual_carryover_damping": {"enabled": False},
            "non_business_evening_positive_residual_damping": {
                "enabled": True,
                "target_hours": [17, 18, 19, 20],
                "min_reference_hour": 12,
                "min_lead_hours": 2,
                "max_lead_hours": 6,
                "min_base_adjustment_mw": 500.0,
                "weak_support_delta_mw": 600.0,
                "damping_factor": 0.45,
                "min_damped_mw": 120.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(600.0, abs=0.1)
    assert result.non_business_evening_positive_residual_damping_applied is True
    assert result.forecasts[17].forecast_mw == pytest.approx(20_248.4, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_17 = next(item for item in residual_logs if item["hour"] == 17)
    assert (
        hour_17["nonBusinessEveningPositiveResidualDampingFactor"]
        == pytest.approx(0.45)
    )
    assert (
        hour_17["nonBusinessEveningPositiveResidualDampedMw"]
        == pytest.approx(303.6, abs=0.1)
    )


def test_intraday_damps_business_late_evening_positive_carryover_when_shape_is_weak():
    target = date(2026, 6, 29)  # Monday, late positive carryover after afternoon miss
    forecasts = _make_forecasts(target, 29_000.0)
    forecasts[21] = HourlyForecast(
        ts=f"{target.isoformat()}T21:00:00+09:00",
        forecast_mw=29_691.4,
        p95_lower_mw=29_191.4,
        p95_upper_mw=30_191.4,
        p99_lower_mw=28_891.4,
        p99_upper_mw=30_491.4,
    )
    forecasts[22] = HourlyForecast(
        ts=f"{target.isoformat()}T22:00:00+09:00",
        forecast_mw=28_490.6,
        p95_lower_mw=27_990.6,
        p95_upper_mw=28_990.6,
        p99_lower_mw=27_690.6,
        p99_upper_mw=29_290.6,
    )
    actual_series = [
        _actual_point(target, 17, 34_500.0),
        _actual_point(target, 18, 34_500.0),
        _actual_point(target, 19, 34_500.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": hour, "is_non_business_day": 0}
        for hour in range(24)
    ])
    inference_features.loc[21, "lag_24h_hourly_delta"] = -1_380.0
    inference_features.loc[21, "recent_same_business_type_delta_mean"] = -1_635.0
    inference_features.loc[22, "lag_24h_hourly_delta"] = -1_210.0
    inference_features.loc[22, "recent_same_business_type_delta_mean"] = -1_168.8
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 0.92,
            "operational_calibration": {
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "positive_residual_slope_damping": {"enabled": False},
            "morning_positive_residual_carryover_damping": {"enabled": False},
            "afternoon_positive_residual_carryover_damping": {
                "enabled": True,
                "business_day_only": True,
                "target_hours": [21, 22],
                "min_reference_hour": 11,
                "max_reference_hour": 19,
                "min_lead_hours": 1,
                "max_lead_hours": 6,
                "min_base_adjustment_mw": 250.0,
                "weak_support_delta_mw": 900.0,
                "damping_factor": 0.4,
                "min_damped_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(1_200.0)
    assert result.afternoon_positive_residual_carryover_damping_applied is True
    assert result.afternoon_positive_residual_carryover_damping_factor == pytest.approx(0.4)
    assert result.forecasts[21].forecast_mw == pytest.approx(30_133.0, abs=0.1)
    assert result.forecasts[22].forecast_mw == pytest.approx(28_896.9, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_21 = next(item for item in residual_logs if item["hour"] == 21)
    assert (
        hour_21["afternoonPositiveResidualCarryoverDampingFactor"]
        == pytest.approx(0.4)
    )
    assert (
        "afternoon_positive_residual_carryover_damping"
        in result.applied_regime_reason
    )


def test_intraday_damps_business_late_evening_positive_carryover_after_20_observed_hour():
    target = date(2026, 6, 30)  # Tuesday, positive miss should not lift the full late tail
    forecasts = _make_forecasts(target, 29_000.0)
    for hour, value in {
        18: 34_052.8,
        19: 33_265.0,
        20: 32_011.5,
        21: 30_281.4,
        22: 28_640.8,
        23: 27_618.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 18, 35_380.0),
        _actual_point(target, 19, 34_540.0),
        _actual_point(target, 20, 32_980.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": hour, "is_non_business_day": 0}
        for hour in range(24)
    ])
    inference_features.loc[21, "lag_24h_hourly_delta"] = -1_770.0
    inference_features.loc[21, "recent_same_business_type_delta_mean"] = -1_646.2
    inference_features.loc[22, "lag_24h_hourly_delta"] = -1_420.0
    inference_features.loc[22, "recent_same_business_type_delta_mean"] = -1_201.2
    inference_features.loc[23, "lag_24h_hourly_delta"] = -1_470.0
    inference_features.loc[23, "recent_same_business_type_delta_mean"] = -1_406.2
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 0.92,
            "operational_calibration": {
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "positive_residual_slope_damping": {"enabled": False},
            "morning_positive_residual_carryover_damping": {"enabled": False},
            "afternoon_positive_residual_carryover_damping": {
                "enabled": True,
                "business_day_only": True,
                "target_hours": [21, 22, 23],
                "min_reference_hour": 11,
                "max_reference_hour": 20,
                "min_lead_hours": 1,
                "max_lead_hours": 6,
                "min_base_adjustment_mw": 250.0,
                "weak_support_delta_mw": 900.0,
                "damping_factor": 0.4,
                "min_damped_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw > 600.0
    assert result.afternoon_positive_residual_carryover_damping_applied is True
    residual_logs = result.metadata()["residualCarryoverByHour"]
    for hour in [21, 22, 23]:
        item = next(row for row in residual_logs if row["hour"] == hour)
        assert item["afternoonPositiveResidualCarryoverDampingFactor"] == pytest.approx(
            0.4
        )
        assert item["afternoonPositiveResidualCarryoverDampedMw"] >= 100.0
    assert result.forecasts[23].forecast_mw < 28_780.0


def test_intraday_damps_non_business_evening_negative_carryover_when_actual_recovers():
    target = date(2026, 6, 14)  # Sunday
    forecasts = _make_forecasts(target, 28_000.0)
    actual_series = [
        _actual_point(target, 15, 26_480.0),
        _actual_point(target, 16, 26_690.0),
        _actual_point(target, 17, 27_610.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": hour, "is_non_business_day": 1}
        for hour in range(24)
    ])
    inference_features.loc[18, "lag_24h_hourly_delta"] = -90.0
    inference_features.loc[18, "recent_same_business_type_delta_mean"] = 506.2
    inference_features.loc[19, "lag_24h_hourly_delta"] = 60.0
    inference_features.loc[19, "recent_same_business_type_delta_mean"] = 20.0
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "negative_residual_recovery_damping": {"enabled": False},
            "negative_residual_continuity_floor": {"enabled": False},
            "negative_residual_near_term_floor": {"enabled": False},
            "operational_calibration": {
                "business_type_transition_prior": {"enabled": False},
                "business_type_transition": {"enabled": False},
            },
            "non_business_evening_negative_residual_damping": {
                "enabled": True,
                "target_hours": [18, 19],
                "min_reference_hour": 16,
                "min_lead_hours": 1,
                "max_lead_hours": 3,
                "min_abs_base_adjustment_mw": 500.0,
                "min_latest_slope_mw": 600.0,
                "min_mean_slope_mw": 300.0,
                "min_support_delta_mw": 0.0,
                "damping_factor": 0.45,
                "min_damped_mw": 120.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(-644.0, abs=0.1)
    assert result.non_business_evening_negative_residual_damping_applied is True
    assert (
        result.non_business_evening_negative_residual_damping_factor
        == pytest.approx(0.45)
    )
    assert (
        result.non_business_evening_negative_residual_damping_max_mw
        == pytest.approx(354.2, abs=0.1)
    )
    assert result.forecasts[18].forecast_mw == pytest.approx(27_710.2, abs=0.1)
    assert result.forecasts[19].forecast_mw == pytest.approx(27_710.2, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_18 = next(item for item in residual_logs if item["hour"] == 18)
    assert (
        hour_18["nonBusinessEveningNegativeResidualDampingFactor"]
        == pytest.approx(0.45)
    )
    assert (
        "non_business_evening_negative_residual_damping"
        in result.applied_regime_reason
    )


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


def test_intraday_correction_protects_strong_morning_ramp_from_negative_residual():
    target = date(2026, 5, 27)  # Wednesday
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        7: 26_000.0,
        8: 29_000.0,
        9: 32_000.0,
        10: 31_400.0,
        11: 34_400.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 7, 25_000.0),
        _actual_point(target, 8, 28_000.0),
        _actual_point(target, 9, 31_000.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 9, "is_non_business_day": 0},
        {"hour": 10, "is_non_business_day": 0},
        {"hour": 11, "is_non_business_day": 0},
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "decay_per_hour": 1.0,
            "morning_ramp_continuity_guard": {
                "enabled": True,
                "target_hours": [10],
                "min_reference_hour": 7,
                "max_lead_hours": 1,
                "min_recent_slope_mw": 1_000.0,
                "min_mean_slope_mw": 1_000.0,
                "floor_slope_fraction": 0.25,
                "max_floor_delta_mw": 900.0,
                "max_restore_mw": 700.0,
                "min_restore_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(-600.0)
    assert result.morning_ramp_continuity_guard_applied is True
    assert result.morning_ramp_continuity_max_restore_mw == pytest.approx(600.0)
    assert result.forecasts[10].forecast_mw == pytest.approx(31_400.0)
    assert result.forecasts[11].forecast_mw == pytest.approx(33_800.0)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_10 = next(item for item in residual_logs if item["hour"] == 10)
    hour_11 = next(item for item in residual_logs if item["hour"] == 11)
    assert hour_10["morningRampContinuityRestoreMw"] == pytest.approx(600.0)
    assert hour_10["finalAdjustmentMw"] == pytest.approx(0.0)
    assert hour_11["morningRampContinuityRestoreMw"] == pytest.approx(0.0)
    assert "morning_ramp_continuity_guard" in result.applied_regime_reason


def test_intraday_correction_lifts_near_future_when_observed_morning_ramp_is_strong():
    target = date(2026, 6, 12)
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        6: 23_000.0,
        7: 25_300.0,
        8: 28_800.0,
        9: 30_000.0,
        10: 31_000.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 6, 23_000.0),
        _actual_point(target, 7, 25_300.0),
        _actual_point(target, 8, 28_800.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 8, "is_non_business_day": 0},
        {"hour": 9, "is_non_business_day": 0},
        {"hour": 10, "is_non_business_day": 0},
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "decay_per_hour": 1.0,
            "morning_observed_ramp_floor": {
                "enabled": True,
                "business_day_only": True,
                "target_hours": [9, 10],
                "min_reference_hour": 7,
                "max_reference_hour": 10,
                "max_lead_hours": 2,
                "min_recent_slope_mw": 1_000.0,
                "min_mean_slope_mw": 1_000.0,
                "floor_slope_fraction": 0.85,
                "max_floor_delta_mw": 2_200.0,
                "max_lift_mw": 1_200.0,
                "min_lift_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_ramp_floor_applied is True
    assert result.morning_observed_ramp_floor_max_lift_mw == pytest.approx(1_200.0)
    assert result.forecasts[9].forecast_mw == pytest.approx(31_000.0)
    assert result.forecasts[10].forecast_mw == pytest.approx(32_200.0)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_9 = next(item for item in residual_logs if item["hour"] == 9)
    hour_10 = next(item for item in residual_logs if item["hour"] == 10)
    assert hour_9["morningObservedRampFloorLiftMw"] == pytest.approx(1_000.0)
    assert hour_10["morningObservedRampFloorLiftMw"] == pytest.approx(1_200.0)
    assert hour_10["morningObservedRampFloorDeltaMw"] == pytest.approx(2_200.0)
    assert "morning_observed_ramp_floor" in result.applied_regime_reason


def test_intraday_correction_caps_observed_morning_ramp_floor_by_target_shape_support():
    target = date(2026, 6, 16)
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        8: 28_416.7,
        9: 31_749.0,
        10: 32_712.3,
        11: 33_355.1,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 8, 28_190.0),
        _actual_point(target, 9, 31_650.0),
        _actual_point(target, 10, 33_090.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 10, "is_non_business_day": 0},
        {
            "hour": 11,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 510.0,
            "recent_same_business_type_delta_mean": 403.8,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "morning_observed_ramp_floor": {
                "enabled": True,
                "business_day_only": True,
                "target_hours": [11],
                "min_reference_hour": 7,
                "max_reference_hour": 10,
                "max_lead_hours": 2,
                "min_recent_slope_mw": 1_000.0,
                "min_mean_slope_mw": 1_000.0,
                "floor_slope_fraction": 0.85,
                "max_floor_delta_mw": 2_200.0,
                "max_floor_delta_over_support_mw": 300.0,
                "max_lift_mw": 1_200.0,
                "min_lift_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_ramp_floor_applied is True
    assert result.morning_observed_ramp_floor_max_lift_mw == pytest.approx(
        544.9,
        abs=0.1,
    )
    assert result.forecasts[11].forecast_mw == pytest.approx(33_900.0, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_11 = next(item for item in residual_logs if item["hour"] == 11)
    assert hour_11["morningObservedRampFloorDeltaMw"] == pytest.approx(810.0)
    assert hour_11["morningObservedRampFloorSupportDeltaMw"] == pytest.approx(510.0)


def test_intraday_observed_morning_ramp_floor_uses_fractional_support_and_skips_weak_targets():
    target = date(2026, 7, 2)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        7: 28_384.2,
        8: 30_749.5,
        9: 34_080.0,
        10: 34_500.0,
        11: 34_000.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 7, 28_570.0),
        _actual_point(target, 8, 31_880.0),
        _actual_point(target, 9, 34_340.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 9, "is_non_business_day": 0},
        {
            "hour": 10,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 970.0,
            "recent_same_business_type_delta_mean": 847.5,
        },
        {
            "hour": 11,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -550.0,
            "recent_same_business_type_delta_mean": 253.8,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "morning_observed_ramp_floor": {
                "enabled": True,
                "business_day_only": True,
                "target_hours": [10, 11],
                "min_reference_hour": 7,
                "max_reference_hour": 10,
                "max_lead_hours": 2,
                "min_recent_slope_mw": 1_200.0,
                "min_mean_slope_mw": 1_200.0,
                "floor_slope_fraction": 0.85,
                "max_floor_delta_mw": 2_200.0,
                "max_floor_delta_over_support_mw": 0.0,
                "min_support_delta_mw": 700.0,
                "support_delta_fraction": 0.5,
                "max_lift_mw": 1_200.0,
                "min_lift_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_10 = next(item for item in residual_logs if item["hour"] == 10)
    hour_11 = next(item for item in residual_logs if item["hour"] == 11)
    assert result.morning_observed_ramp_floor_applied is True
    assert hour_10["morningObservedRampFloorDeltaMw"] == pytest.approx(485.0)
    assert hour_10["morningObservedRampFloorLiftMw"] == pytest.approx(325.0)
    assert result.forecasts[10].forecast_mw == pytest.approx(34_825.0)
    assert hour_11["morningObservedRampFloorLiftMw"] == pytest.approx(0.0)
    assert result.forecasts[11].forecast_mw == pytest.approx(34_000.0)


def test_intraday_damps_morning_positive_carryover_before_ramp_floor_lift():
    target = date(2026, 6, 18)
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        6: 23_900.0,
        7: 27_000.0,
        8: 29_600.0,
        9: 32_230.2,
        10: 32_901.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 6, 24_900.0),
        _actual_point(target, 7, 27_150.0),
        _actual_point(target, 8, 30_100.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 8, "is_non_business_day": 0},
        {
            "hour": 9,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 2_200.0,
            "recent_same_business_type_delta_mean": 2_100.0,
        },
        {
            "hour": 10,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 1_600.0,
            "recent_same_business_type_delta_mean": 1_300.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "morning_positive_residual_carryover_damping": {
                "enabled": True,
                "target_hours": [10],
                "min_reference_hour": 7,
                "max_reference_hour": 10,
                "min_lead_hours": 2,
                "max_lead_hours": 4,
                "min_base_adjustment_mw": 300.0,
                "min_recent_ramp_slope_mw": 1_000.0,
                "weak_support_delta_mw": 1_800.0,
                "damping_factor": 0.4,
                "min_damped_mw": 100.0,
            },
            "morning_observed_ramp_floor": {
                "enabled": True,
                "business_day_only": True,
                "target_hours": [10],
                "min_reference_hour": 7,
                "max_reference_hour": 10,
                "max_lead_hours": 2,
                "min_recent_slope_mw": 1_200.0,
                "min_mean_slope_mw": 1_200.0,
                "floor_slope_fraction": 0.85,
                "max_floor_delta_mw": 2_200.0,
                "max_floor_delta_over_support_mw": 0.0,
                "max_lift_mw": 1_200.0,
                "min_lift_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_positive_residual_carryover_damping_applied is True
    assert result.morning_observed_ramp_floor_applied is True
    assert result.forecasts[10].forecast_mw == pytest.approx(33_300.0)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_10 = next(item for item in residual_logs if item["hour"] == 10)
    assert (
        hour_10["morningPositiveResidualCarryoverDampingFactor"]
        == pytest.approx(0.4)
    )
    assert hour_10["morningObservedRampFloorDeltaMw"] == pytest.approx(1_600.0)
    assert hour_10["morningObservedRampFloorLiftMw"] == pytest.approx(179.0)


def test_intraday_correction_skips_morning_ramp_floor_when_latest_observed_bucket_is_already_high():
    target = date(2026, 6, 15)
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        6: 23_136.0,
        7: 25_596.0,
        8: 28_780.0,
        9: 30_631.0,
        10: 30_639.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 6, 23_330.0),
        _actual_point(target, 7, 25_170.0),
        _actual_point(target, 8, 27_780.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 8, "is_non_business_day": 0},
        {"hour": 9, "is_non_business_day": 0},
        {"hour": 10, "is_non_business_day": 0},
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "morning_observed_ramp_floor": {
                "enabled": True,
                "business_day_only": True,
                "target_hours": [9, 10],
                "min_reference_hour": 7,
                "max_reference_hour": 10,
                "max_lead_hours": 2,
                "min_recent_slope_mw": 1_000.0,
                "min_mean_slope_mw": 1_000.0,
                "floor_slope_fraction": 0.85,
                "max_floor_delta_mw": 2_200.0,
                "max_lift_mw": 1_200.0,
                "min_lift_mw": 100.0,
                "max_latest_overforecast_mw": 500.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_ramp_floor_applied is False
    assert result.forecasts[10].forecast_mw == pytest.approx(30_639.0)
    assert "morning_observed_ramp_floor" not in result.applied_regime_reason


def test_intraday_correction_does_not_apply_morning_ramp_guard_without_strong_ramp():
    target = date(2026, 5, 27)
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        7: 31_000.0,
        8: 31_300.0,
        9: 31_600.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    forecasts[10] = HourlyForecast(
        ts=f"{target.isoformat()}T10:00:00+09:00",
        forecast_mw=31_400.0,
        p95_lower_mw=30_900.0,
        p95_upper_mw=31_900.0,
        p99_lower_mw=30_600.0,
        p99_upper_mw=32_200.0,
    )
    actual_series = [
        _actual_point(target, 7, 30_000.0),
        _actual_point(target, 8, 30_300.0),
        _actual_point(target, 9, 30_600.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 9, "is_non_business_day": 0},
        {"hour": 10, "is_non_business_day": 0},
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "decay_per_hour": 1.0,
            "morning_ramp_continuity_guard": {
                "enabled": True,
                "target_hours": [10],
                "min_recent_slope_mw": 1_000.0,
                "min_mean_slope_mw": 1_000.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_ramp_continuity_guard_applied is False
    assert result.forecasts[10].forecast_mw == pytest.approx(30_800.0)


def test_intraday_correction_damps_warm_lag_morning_overreaction():
    target = date(2026, 6, 4)  # Thursday warm-lag overreaction case
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        5: 22_531.0,
        6: 24_180.0,
        7: 25_850.0,
        9: 32_900.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 5, 22_360.0),
        _actual_point(target, 6, 22_880.0),
        _actual_point(target, 7, 24_580.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 7, "is_non_business_day": 0},
        {
            "hour": 9,
            "is_non_business_day": 0,
            "temp_delta_24h": 5.5,
            "cooling_delta_24h": 1.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "morning_warm_lag_overreaction_guard": {
                "enabled": True,
                "target_hours": [9],
                "min_reference_hour": 6,
                "max_reference_hour": 10,
                "max_lead_hours": 2,
                "min_base_adjustment_mw": 500.0,
                "min_temp_delta_24h_c": 2.0,
                "min_cooling_delta_24h_c": 0.8,
                "slope_slack_mw": 300.0,
                "min_projected_slope_mw": 400.0,
                "max_projected_slope_mw": 1_800.0,
                "cap_buffer_mw": 0.0,
                "shrinkage": 0.75,
                "max_reduction_mw": 800.0,
                "min_reduction_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(-913.7, abs=0.1)
    assert result.morning_warm_lag_overreaction_guard_applied is True
    assert result.morning_warm_lag_overreaction_max_reduction_mw == pytest.approx(800.0)
    assert result.forecasts[9].forecast_mw == pytest.approx(31_186.3, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_9 = next(item for item in residual_logs if item["hour"] == 9)
    assert hour_9["morningWarmLagOverreactionCapMw"] == pytest.approx(28_180.0)
    assert hour_9["morningWarmLagOverreactionReductionMw"] == pytest.approx(800.0)
    assert hour_9["morningWarmLagOverreactionTempDelta24hC"] == pytest.approx(5.5)
    assert "morning_warm_lag_overreaction_guard" in result.applied_regime_reason


def test_intraday_correction_keeps_morning_negative_residual_without_warm_signal():
    target = date(2026, 6, 4)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        5: 22_531.0,
        6: 24_180.0,
        7: 25_850.0,
        9: 32_900.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 5, 22_360.0),
        _actual_point(target, 6, 22_880.0),
        _actual_point(target, 7, 24_580.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 7, "is_non_business_day": 0},
        {
            "hour": 9,
            "is_non_business_day": 0,
            "temp_delta_24h": 0.5,
            "cooling_delta_24h": 0.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "morning_warm_lag_overreaction_guard": {
                "enabled": True,
                "target_hours": [9],
                "min_temp_delta_24h_c": 2.0,
                "min_cooling_delta_24h_c": 0.8,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_warm_lag_overreaction_guard_applied is False
    assert result.morning_warm_lag_overreaction_max_reduction_mw == pytest.approx(0.0)
    assert result.forecasts[9].forecast_mw == pytest.approx(31_986.3, abs=0.1)


def test_intraday_caps_morning_forecast_above_observed_anchor_path():
    target = date(2026, 6, 9)  # Tuesday late-morning overforecast case
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        7: 25_695.1,
        8: 28_585.5,
        9: 31_019.9,
        10: 32_081.0,
        11: 32_423.2,
        12: 31_281.3,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 7, 25_580.0),
        _actual_point(target, 8, 28_320.0),
        _actual_point(target, 9, 30_690.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 9, "is_non_business_day": 0},
        {
            "hour": 10,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 670.0,
            "recent_same_business_type_delta_mean": 660.0,
        },
        {
            "hour": 11,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 150.0,
            "recent_same_business_type_delta_mean": 245.0,
        },
        {
            "hour": 12,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -1_240.0,
            "recent_same_business_type_delta_mean": -917.5,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "morning_observed_anchor_cap": {
                "enabled": True,
                "target_hours": [10, 11, 12],
                "min_reference_hour": 8,
                "max_reference_hour": 12,
                "max_lead_hours": 4,
                "min_latest_overforecast_mw": 200.0,
                "cap_buffer_mw": 250.0,
                "shrinkage": 0.75,
                "max_reduction_mw": 800.0,
                "min_reduction_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_anchor_cap_applied is True
    assert result.morning_observed_anchor_cap_max_reduction_mw == pytest.approx(426.2)
    assert result.forecasts[10].forecast_mw == pytest.approx(31_727.8)
    assert result.forecasts[11].forecast_mw == pytest.approx(31_997.0)
    assert result.forecasts[12].forecast_mw == pytest.approx(31_023.5)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_11 = next(item for item in residual_logs if item["hour"] == 11)
    assert hour_11["morningObservedAnchorCapMw"] == pytest.approx(31_855.0)
    assert hour_11["morningObservedAnchorCapReductionMw"] == pytest.approx(426.2)
    assert hour_11["morningObservedAnchorCapLatestResidualMw"] == pytest.approx(-329.9)
    assert "morning_observed_anchor_cap" in result.applied_regime_reason


def test_intraday_morning_observed_anchor_cap_waits_for_negative_residual():
    target = date(2026, 6, 9)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        7: 25_695.1,
        8: 28_585.5,
        9: 31_019.9,
        10: 32_081.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 7, 25_580.0),
        _actual_point(target, 8, 28_320.0),
        _actual_point(target, 9, 31_000.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 9, "is_non_business_day": 0},
        {
            "hour": 10,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 670.0,
            "recent_same_business_type_delta_mean": 660.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "morning_observed_anchor_cap": {
                "enabled": True,
                "target_hours": [10],
                "min_latest_overforecast_mw": 200.0,
                "cap_buffer_mw": 250.0,
                "shrinkage": 0.75,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_anchor_cap_applied is False
    assert result.morning_observed_anchor_cap_max_reduction_mw == pytest.approx(0.0)
    assert result.forecasts[10].forecast_mw == pytest.approx(32_081.0)


def test_intraday_morning_observed_anchor_cap_handles_warm_ramp_overhang():
    target = date(2026, 6, 26)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        9: 34_052.3,
        10: 35_157.1,
        11: 34_970.0,
        12: 34_010.0,
        13: 35_530.3,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 7, 27_430.0),
        _actual_point(target, 8, 30_520.0),
        _actual_point(target, 9, 33_190.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 9, "is_non_business_day": 0},
        {
            "hour": 10,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 440.0,
            "recent_same_business_type_delta_mean": 895.0,
        },
        {
            "hour": 11,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -300.0,
            "recent_same_business_type_delta_mean": 630.0,
        },
        {
            "hour": 12,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -960.0,
            "recent_same_business_type_delta_mean": -907.5,
        },
        {
            "hour": 13,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 1_090.0,
            "recent_same_business_type_delta_mean": 968.8,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "morning_observed_anchor_cap": {
                "enabled": True,
                "target_hours": [10, 11, 12, 13],
                "min_reference_hour": 8,
                "max_reference_hour": 12,
                "max_lead_hours": 4,
                "min_latest_overforecast_mw": 400.0,
                "cap_buffer_mw": 0.0,
                "shrinkage": 1.0,
                "max_reduction_mw": 1_000.0,
                "min_reduction_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_anchor_cap_applied is True
    assert result.morning_observed_anchor_cap_max_reduction_mw == pytest.approx(1_000.0)
    assert result.forecasts[10].forecast_mw == pytest.approx(34_157.1)
    assert result.forecasts[11].forecast_mw == pytest.approx(34_715.0)
    assert result.forecasts[12].forecast_mw == pytest.approx(33_807.5)
    assert result.forecasts[13].forecast_mw == pytest.approx(34_897.5)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_10 = next(item for item in residual_logs if item["hour"] == 10)
    hour_13 = next(item for item in residual_logs if item["hour"] == 13)
    assert hour_10["morningObservedAnchorCapReductionMw"] == pytest.approx(1_000.0)
    assert hour_13["morningObservedAnchorCapCumulativeSupportMw"] == pytest.approx(
        1_707.5
    )


def test_intraday_morning_observed_anchor_cap_can_protect_next_09_bucket():
    target = date(2026, 6, 29)
    forecasts = _make_forecasts(target, 30_000.0)
    forecasts[8] = HourlyForecast(
        ts=f"{target.isoformat()}T08:00:00+09:00",
        forecast_mw=29_858.0,
        p95_lower_mw=29_358.0,
        p95_upper_mw=30_358.0,
        p99_lower_mw=29_058.0,
        p99_upper_mw=30_658.0,
    )
    forecasts[9] = HourlyForecast(
        ts=f"{target.isoformat()}T09:00:00+09:00",
        forecast_mw=33_600.0,
        p95_lower_mw=33_100.0,
        p95_upper_mw=34_100.0,
        p99_lower_mw=32_800.0,
        p99_upper_mw=34_400.0,
    )
    actual_series = [
        _actual_point(target, 6, 24_360.0),
        _actual_point(target, 7, 26_010.0),
        _actual_point(target, 8, 29_050.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 8, "is_non_business_day": 0},
        {
            "hour": 9,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 1_860.0,
            "recent_same_business_type_delta_mean": 3_220.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "morning_observed_anchor_cap": {
                "enabled": True,
                "business_day_only": True,
                "target_hours": [9, 10, 11, 12, 13],
                "min_reference_hour": 8,
                "max_reference_hour": 12,
                "max_lead_hours": 4,
                "min_latest_overforecast_mw": 400.0,
                "cap_buffer_mw": 0.0,
                "shrinkage": 1.0,
                "max_reduction_mw": 1_000.0,
                "min_reduction_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_anchor_cap_applied is True
    assert result.morning_observed_anchor_cap_max_reduction_mw == pytest.approx(1_000.0)
    assert result.forecasts[9].forecast_mw == pytest.approx(32_600.0, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_9 = next(item for item in residual_logs if item["hour"] == 9)
    assert hour_9["morningObservedAnchorCapReductionMw"] == pytest.approx(1_000.0)


def test_intraday_morning_anchor_support_overhang_caps_hot_day_09_spike():
    target = date(2026, 7, 14)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        6: 28_553.6,
        7: 33_824.3,
        8: 38_790.2,
        9: 46_075.1,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 6, 28_440.0),
        _actual_point(target, 7, 32_870.0),
        _actual_point(target, 8, 38_890.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 8, "is_non_business_day": 0},
        {
            "hour": 9,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 3_220.0,
            "recent_same_business_type_delta_mean": 3_336.2,
            "temp_delta_24h": 5.2,
            "cooling_delta_24h": 5.2,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "morning_observed_anchor_cap": {
                "enabled": True,
                "business_day_only": True,
                "target_hours": [9],
                "min_reference_hour": 8,
                "max_reference_hour": 12,
                "max_lead_hours": 4,
                "min_latest_overforecast_mw": 400.0,
                "cap_buffer_mw": 0.0,
                "shrinkage": 1.0,
                "max_reduction_mw": 1_000.0,
                "min_reduction_mw": 100.0,
                "support_overhang": {
                    "enabled": True,
                    "min_projected_overhang_mw": 1_200.0,
                    "max_latest_underforecast_mw": 300.0,
                    "min_temp_delta_24h_c": 3.0,
                    "min_cooling_delta_24h_c": 2.0,
                    "cap_buffer_mw": 1_200.0,
                    "shrinkage": 0.5,
                    "max_reduction_mw": 1_000.0,
                    "min_reduction_mw": 150.0,
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_anchor_cap_applied is True
    assert result.morning_observed_anchor_cap_max_reduction_mw == pytest.approx(1_000.0)
    assert result.forecasts[9].forecast_mw == pytest.approx(45_075.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_9 = next(item for item in residual_logs if item["hour"] == 9)
    assert hour_9["morningObservedAnchorCapMode"] == "support_overhang"
    assert hour_9["morningObservedAnchorCapMw"] == pytest.approx(43_426.2)
    assert hour_9["morningObservedAnchorCapLatestResidualMw"] == pytest.approx(99.8)


def test_intraday_morning_observed_anchor_cap_vetoes_confirmed_explosive_ramp():
    target = date(2026, 7, 8)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        8: 32_247.9,
        9: 35_217.9,
        10: 36_672.5,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 6, 24_480.0),
        _actual_point(target, 7, 27_380.0),
        _actual_point(target, 8, 31_810.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 8, "is_non_business_day": 0},
        {
            "hour": 9,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 2_980.0,
            "recent_same_business_type_delta_mean": 2_965.0,
        },
        {
            "hour": 10,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 460.0,
            "recent_same_business_type_delta_mean": 677.5,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "morning_observed_anchor_cap": {
                "enabled": True,
                "business_day_only": True,
                "target_hours": [9, 10],
                "min_reference_hour": 8,
                "max_reference_hour": 12,
                "max_lead_hours": 4,
                "min_latest_overforecast_mw": 400.0,
                "cap_buffer_mw": 0.0,
                "shrinkage": 1.0,
                "max_reduction_mw": 1_000.0,
                "min_reduction_mw": 100.0,
                "ramp_veto": {
                    "enabled": True,
                    "min_latest_slope_mw": 3_000.0,
                    "min_mean_slope_mw": 3_000.0,
                    "min_cumulative_support_mw": 2_500.0,
                    "max_latest_overforecast_mw": 650.0,
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_anchor_cap_applied is False
    assert result.morning_observed_anchor_cap_max_reduction_mw == pytest.approx(0.0)
    assert result.forecasts[9].forecast_mw == pytest.approx(35_217.9)
    assert result.forecasts[10].forecast_mw == pytest.approx(36_672.5)


def test_intraday_afternoon_observed_anchor_cap_damps_supported_plateau_overhang():
    target = date(2026, 6, 9)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        10: 32_223.1,
        11: 32_553.9,
        12: 31_401.6,
        14: 33_404.8,
        15: 33_694.5,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 10, 30_690.0),
        _actual_point(target, 11, 31_300.0),
        _actual_point(target, 12, 30_120.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 12, "is_non_business_day": 0},
        {
            "hour": 13,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 1_150.0,
            "recent_same_business_type_delta_mean": 776.2,
        },
        {
            "hour": 14,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 700.0,
            "recent_same_business_type_delta_mean": 201.2,
        },
        {
            "hour": 15,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 110.0,
            "recent_same_business_type_delta_mean": -421.2,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "afternoon_observed_anchor_cap": {
                "enabled": True,
                "target_hours": [14, 15],
                "min_reference_hour": 12,
                "max_reference_hour": 15,
                "max_lead_hours": 3,
                "lookback_observed_hours": 3,
                "min_latest_overforecast_mw": 500.0,
                "min_mean_overforecast_mw": 500.0,
                "cap_buffer_mw": 350.0,
                "support_fraction": 0.6,
                "shrinkage": 0.75,
                "max_reduction_mw": 1_200.0,
                "min_reduction_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.afternoon_observed_anchor_cap_applied is True
    assert result.afternoon_observed_anchor_cap_max_reduction_mw == pytest.approx(1_200.0)
    assert result.forecasts[14].forecast_mw == pytest.approx(32_204.8)
    assert result.forecasts[15].forecast_mw == pytest.approx(32_494.5)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_14 = next(item for item in residual_logs if item["hour"] == 14)
    hour_15 = next(item for item in residual_logs if item["hour"] == 15)
    assert hour_14["afternoonObservedAnchorCapMw"] == pytest.approx(31_580.0)
    assert hour_14["afternoonObservedAnchorCapReductionMw"] == pytest.approx(1_200.0)
    assert hour_15["afternoonObservedAnchorCapCumulativeSupportMw"] == pytest.approx(1_176.0)
    assert hour_15["afternoonObservedAnchorCapMeanResidualMw"] == pytest.approx(-1_356.2)
    assert "afternoon_observed_anchor_cap" in result.applied_regime_reason


def test_intraday_afternoon_observed_anchor_cap_can_run_on_non_business_days():
    target = date(2026, 6, 14)  # Sunday
    forecasts = _make_forecasts(target, 27_000.0)
    for hour, value in {
        13: 27_266.7,
        14: 27_548.8,
        15: 27_437.4,
        16: 28_214.7,
        17: 28_403.8,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 13, 27_660.0),
        _actual_point(target, 14, 26_610.0),
        _actual_point(target, 15, 26_480.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 15, "is_non_business_day": 1},
        {
            "hour": 16,
            "is_non_business_day": 1,
            "lag_24h_hourly_delta": 80.0,
            "recent_same_business_type_delta_mean": 436.2,
        },
        {
            "hour": 17,
            "is_non_business_day": 1,
            "lag_24h_hourly_delta": -430.0,
            "recent_same_business_type_delta_mean": 356.2,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "afternoon_observed_anchor_cap": {
                "enabled": True,
                "business_day_only": False,
                "target_hours": [16, 17],
                "min_reference_hour": 12,
                "max_reference_hour": 15,
                "max_lead_hours": 3,
                "lookback_observed_hours": 3,
                "min_latest_overforecast_mw": 500.0,
                "min_mean_overforecast_mw": 500.0,
                "cap_buffer_mw": 350.0,
                "support_fraction": 0.6,
                "shrinkage": 0.75,
                "max_reduction_mw": 1_200.0,
                "min_reduction_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.afternoon_observed_anchor_cap_applied is True
    assert result.forecasts[16].forecast_mw == pytest.approx(27_372.5, abs=0.1)
    assert result.forecasts[17].forecast_mw == pytest.approx(27_580.0, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_16 = next(item for item in residual_logs if item["hour"] == 16)
    assert hour_16["afternoonObservedAnchorCapReductionMw"] == pytest.approx(842.2, abs=0.1)


def test_intraday_afternoon_observed_anchor_cap_skips_when_actuals_are_recovering():
    target = date(2026, 6, 18)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        11: 34_000.0,
        12: 32_900.0,
        13: 33_863.7,
        14: 34_565.1,
        15: 34_204.2,
        16: 34_122.7,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 11, 33_340.0),
        _actual_point(target, 12, 32_470.0),
        _actual_point(target, 13, 33_300.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 13, "is_non_business_day": 0},
        {
            "hour": 14,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 830.0,
            "recent_same_business_type_delta_mean": 620.0,
        },
        {
            "hour": 15,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 1_000.0,
            "recent_same_business_type_delta_mean": 450.0,
        },
        {
            "hour": 16,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 10.0,
            "recent_same_business_type_delta_mean": 200.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "afternoon_observed_anchor_cap": {
                "enabled": True,
                "business_day_only": False,
                "target_hours": [14, 15, 16],
                "min_reference_hour": 12,
                "max_reference_hour": 15,
                "max_lead_hours": 3,
                "lookback_observed_hours": 3,
                "min_latest_overforecast_mw": 500.0,
                "min_mean_overforecast_mw": 500.0,
                "max_latest_slope_mw": 500.0,
                "cap_buffer_mw": 350.0,
                "support_fraction": 0.6,
                "shrinkage": 0.75,
                "max_reduction_mw": 1_200.0,
                "min_reduction_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.afternoon_observed_anchor_cap_applied is False
    assert result.afternoon_observed_anchor_cap_max_reduction_mw == pytest.approx(0.0)
    assert result.forecasts[14].forecast_mw == pytest.approx(34_565.1)
    assert result.forecasts[15].forecast_mw == pytest.approx(34_204.2)
    assert "afternoon_observed_anchor_cap" not in result.applied_regime_reason


def test_intraday_afternoon_anchor_severe_mode_allows_cap_after_large_rebound_miss():
    target = date(2026, 7, 14)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        11: 48_538.7,
        12: 47_996.8,
        13: 50_338.9,
        14: 50_092.3,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 11, 48_060.0),
        _actual_point(target, 12, 47_440.0),
        _actual_point(target, 13, 48_690.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 13, "is_non_business_day": 0},
        {
            "hour": 14,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 380.0,
            "recent_same_business_type_delta_mean": 260.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "afternoon_observed_anchor_cap": {
                "enabled": True,
                "business_day_only": False,
                "target_hours": [14],
                "min_reference_hour": 12,
                "max_reference_hour": 15,
                "max_lead_hours": 3,
                "lookback_observed_hours": 3,
                "min_latest_overforecast_mw": 500.0,
                "min_mean_overforecast_mw": 500.0,
                "max_latest_slope_mw": 900.0,
                "cap_buffer_mw": 350.0,
                "support_fraction": 0.6,
                "shrinkage": 0.75,
                "max_reduction_mw": 1_200.0,
                "min_reduction_mw": 100.0,
                "severe_overforecast": {
                    "enabled": True,
                    "min_latest_overforecast_mw": 1_200.0,
                    "min_mean_overforecast_mw": 700.0,
                    "max_latest_slope_mw": 1_500.0,
                    "cap_buffer_mw": 0.0,
                    "support_fraction": 0.35,
                    "shrinkage": 1.0,
                    "max_reduction_mw": 1_500.0,
                    "min_reduction_mw": 150.0,
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.afternoon_observed_anchor_cap_applied is True
    assert result.afternoon_observed_anchor_cap_max_reduction_mw == pytest.approx(
        1_269.3
    )
    assert result.forecasts[14].forecast_mw == pytest.approx(48_823.0)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_14 = next(item for item in residual_logs if item["hour"] == 14)
    assert hour_14["afternoonObservedAnchorCapMode"] == "severe_overforecast"
    assert hour_14["afternoonObservedAnchorCapLatestSlopeMw"] == pytest.approx(1_250.0)


def test_intraday_afternoon_observed_anchor_cap_allows_moderate_recovery_overhang():
    target = date(2026, 6, 26)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        11: 34_970.0,
        12: 34_010.0,
        13: 35_530.3,
        14: 35_652.8,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 11, 33_460.0),
        _actual_point(target, 12, 33_580.0),
        _actual_point(target, 13, 34_220.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 13, "is_non_business_day": 0},
        {
            "hour": 14,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -40.0,
            "recent_same_business_type_delta_mean": -61.2,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "afternoon_observed_anchor_cap": {
                "enabled": True,
                "business_day_only": False,
                "target_hours": [14],
                "min_reference_hour": 12,
                "max_reference_hour": 15,
                "max_lead_hours": 3,
                "lookback_observed_hours": 3,
                "min_latest_overforecast_mw": 500.0,
                "min_mean_overforecast_mw": 500.0,
                "max_latest_slope_mw": 900.0,
                "cap_buffer_mw": 350.0,
                "support_fraction": 0.6,
                "shrinkage": 0.75,
                "max_reduction_mw": 1_200.0,
                "min_reduction_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.afternoon_observed_anchor_cap_applied is True
    assert result.afternoon_observed_anchor_cap_max_reduction_mw == pytest.approx(812.1)
    assert result.forecasts[14].forecast_mw == pytest.approx(34_840.7)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_14 = next(item for item in residual_logs if item["hour"] == 14)
    assert hour_14["afternoonObservedAnchorCapLatestSlopeMw"] == pytest.approx(640.0)
    assert hour_14["afternoonObservedAnchorCapReductionMw"] == pytest.approx(812.1)


def test_intraday_afternoon_observed_anchor_cap_ignores_single_midday_dip():
    target = date(2026, 6, 9)
    forecasts = _make_forecasts(target, 30_000.0)
    forecasts[14] = HourlyForecast(
        ts=f"{target.isoformat()}T14:00:00+09:00",
        forecast_mw=33_000.0,
        p95_lower_mw=32_500.0,
        p95_upper_mw=33_500.0,
        p99_lower_mw=32_200.0,
        p99_upper_mw=33_800.0,
    )
    actual_series = [
        _actual_point(target, 10, 30_050.0),
        _actual_point(target, 11, 30_100.0),
        _actual_point(target, 12, 29_000.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 12, "is_non_business_day": 0},
        {
            "hour": 13,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 1_200.0,
            "recent_same_business_type_delta_mean": 900.0,
        },
        {
            "hour": 14,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 1_100.0,
            "recent_same_business_type_delta_mean": 800.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "afternoon_observed_anchor_cap": {
                "enabled": True,
                "target_hours": [14],
                "min_latest_overforecast_mw": 500.0,
                "min_mean_overforecast_mw": 500.0,
                "cap_buffer_mw": 350.0,
                "support_fraction": 0.6,
                "shrinkage": 0.75,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.afternoon_observed_anchor_cap_applied is False
    assert result.afternoon_observed_anchor_cap_max_reduction_mw == pytest.approx(0.0)
    assert result.forecasts[14].forecast_mw == pytest.approx(33_000.0)


def test_intraday_correction_caps_evening_rebound_after_observed_decline():
    target = date(2026, 5, 27)  # Wednesday
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        15: 34_395.7,
        16: 34_486.2,
        17: 32_901.8,
        18: 34_165.8,
        19: 32_822.2,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 15, 34_400.0),
        _actual_point(target, 16, 34_220.0),
        _actual_point(target, 17, 33_330.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 17, "is_non_business_day": 0},
        {
            "hour": 18,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -30.0,
            "recent_same_business_type_delta_mean": -228.8,
            "temp_delta_1h": 0.3,
            "cooling_delta_1h": 0.3,
            "temp_c": 25.3,
        },
        {
            "hour": 19,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -670.0,
            "recent_same_business_type_delta_mean": -712.5,
            "temp_delta_1h": -2.0,
            "cooling_delta_1h": -2.0,
            "temp_c": 23.3,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "evening_decline_continuity_guard": {
                "enabled": True,
                "target_hours": [18, 19],
                "min_reference_hour": 16,
                "max_lead_hours": 2,
                "latest_slope_max_mw": -500.0,
                "mean_slope_max_mw": -300.0,
                "max_supporting_delta_mw": 200.0,
                "min_forecast_rebound_mw": 800.0,
                "max_rebound_mw": 600.0,
                "actual_reference_slack_mw": 300.0,
                "weather_allowance_mw_per_c": 120.0,
                "max_weather_allowance_mw": 400.0,
                "max_reduction_mw": 900.0,
                "min_reduction_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.evening_decline_continuity_guard_applied is True
    assert result.evening_decline_continuity_max_reduction_mw == pytest.approx(499.8)
    assert result.forecasts[18].forecast_mw == pytest.approx(33_666.0)
    assert result.forecasts[18].p95_upper_mw == pytest.approx(34_166.0)
    assert result.forecasts[19].forecast_mw == pytest.approx(32_822.2)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_18 = next(item for item in residual_logs if item["hour"] == 18)
    assert hour_18["eveningDeclineContinuityCapMw"] == pytest.approx(33_666.0)
    assert hour_18["eveningDeclineContinuityReductionMw"] == pytest.approx(499.8)
    assert hour_18["finalAdjustmentMw"] == pytest.approx(-499.8)
    assert "evening_decline_continuity_guard" in result.applied_regime_reason


def test_intraday_daytime_sustained_underforecast_lifts_hot_business_day_future():
    target = date(2026, 6, 19)  # Friday
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        9: 34_000.0,
        10: 35_000.0,
        11: 36_000.0,
        12: 36_500.0,
        13: 36_000.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 9, 35_500.0),
        _actual_point(target, 10, 37_000.0),
        _actual_point(target, 11, 38_000.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 11, "is_non_business_day": 0},
        {
            "hour": 12,
            "is_non_business_day": 0,
            "temp_delta_24h": 5.0,
            "cooling_delta_24h": 2.0,
        },
        {
            "hour": 13,
            "is_non_business_day": 0,
            "temp_delta_24h": 5.0,
            "cooling_delta_24h": 2.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "daytime_sustained_underforecast_lift": {
                "enabled": True,
                "target_hours": [12, 13],
                "min_reference_hour": 8,
                "max_reference_hour": 14,
                "max_lead_hours": 4,
                "min_base_adjustment_mw": 600.0,
                "min_latest_residual_mw": 600.0,
                "min_mean_residual_mw": 600.0,
                "min_peak_residual_mw": 1_000.0,
                "min_temp_delta_24h_c": 3.0,
                "min_cooling_delta_24h_c": 1.0,
                "floor_slope_fraction": 0.25,
                "floor_slack_mw": 300.0,
                "floor_shrinkage": 0.5,
                "residual_pressure_shrinkage": 0.55,
                "residual_slack_mw": 200.0,
                "max_lift_mw": 900.0,
                "min_lift_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(1200.0)
    assert result.daytime_sustained_underforecast_lift_applied is True
    assert result.daytime_sustained_underforecast_max_lift_mw == pytest.approx(500.0)
    assert result.forecasts[13].forecast_mw == pytest.approx(37_700.0)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_13 = next(item for item in residual_logs if item["hour"] == 13)
    assert hour_13["daytimeSustainedUnderforecastLiftMw"] == pytest.approx(500.0)
    assert "daytime_sustained_underforecast_lift" in result.applied_regime_reason


def test_intraday_daytime_lift_uses_latest_residual_override_for_hot_business_afternoon():
    target = date(2026, 6, 29)  # Monday hot afternoon after a low analog line
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        11: 34_000.0,
        12: 34_360.0,
        13: 33_657.0,
        14: 33_324.8,
        15: 33_831.8,
        16: 34_170.3,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 11, 34_100.0),
        _actual_point(target, 12, 33_660.0),
        _actual_point(target, 13, 34_570.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 13, "is_non_business_day": 0},
        {
            "hour": 14,
            "is_non_business_day": 0,
            "temp_delta_24h": 2.8,
            "cooling_delta_24h": 2.6,
            "lag_24h_hourly_delta": 280.0,
            "recent_same_business_type_delta_mean": -6.2,
        },
        {
            "hour": 15,
            "is_non_business_day": 0,
            "temp_delta_24h": 3.2,
            "cooling_delta_24h": 3.0,
            "lag_24h_hourly_delta": -210.0,
            "recent_same_business_type_delta_mean": -357.5,
        },
        {
            "hour": 16,
            "is_non_business_day": 0,
            "temp_delta_24h": 2.6,
            "cooling_delta_24h": 2.6,
            "lag_24h_hourly_delta": 670.0,
            "recent_same_business_type_delta_mean": -270.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "daytime_sustained_underforecast_lift": {
                "enabled": True,
                "target_hours": [14, 15, 16],
                "min_reference_hour": 8,
                "max_reference_hour": 14,
                "max_lead_hours": 3,
                "lookback_observed_hours": 3,
                "min_positive_residual_count": 2,
                "min_base_adjustment_mw": 600.0,
                "min_latest_residual_mw": 600.0,
                "min_mean_residual_mw": 600.0,
                "min_peak_residual_mw": 1_000.0,
                "latest_residual_override_mw": 900.0,
                "override_min_base_adjustment_mw": 0.0,
                "min_temp_delta_24h_c": 3.0,
                "min_cooling_delta_24h_c": 1.0,
                "floor_slope_fraction": 0.25,
                "floor_slack_mw": 300.0,
                "floor_shrinkage": 0.5,
                "residual_pressure_shrinkage": 0.65,
                "residual_slack_mw": 100.0,
                "max_lift_mw": 900.0,
                "min_lift_mw": 100.0,
                "post_midday_shape_gate": {
                    "enabled": True,
                    "target_hours": [12, 13],
                    "min_lag_delta_mw": 600.0,
                    "min_recent_delta_mw": 600.0,
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(223.5, abs=0.1)
    assert result.daytime_sustained_underforecast_lift_applied is True
    assert result.daytime_sustained_underforecast_max_lift_mw == pytest.approx(
        474.6,
        abs=0.1,
    )
    assert result.forecasts[15].forecast_mw == pytest.approx(34_438.5, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_15 = next(item for item in residual_logs if item["hour"] == 15)
    assert hour_15["daytimeSustainedUnderforecastLiftMw"] == pytest.approx(383.2)
    assert "daytime_sustained_underforecast_lift" in result.applied_regime_reason


def test_intraday_daytime_lift_uses_business_discomfort_plateau_after_hot_afternoon_miss():
    target = date(2026, 6, 30)  # Tuesday hot/humid plateau after ETL lowered q50
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        13: 36_465.1,
        14: 36_271.7,
        15: 36_119.5,
        16: 36_292.4,
        17: 34_412.8,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 13, 36_590.0),
        _actual_point(target, 14, 37_490.0),
        _actual_point(target, 15, 37_790.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 15, "is_non_business_day": 0},
        {
            "hour": 16,
            "is_non_business_day": 0,
            "temp_delta_24h": 0.6,
            "cooling_delta_24h": 0.6,
            "apparent_temp_c": 29.1,
            "humidity_pct": 75.0,
            "discomfort_index": 77.2,
            "lag_24h_hourly_delta": -70.0,
            "recent_same_business_type_delta_mean": -205.0,
        },
        {
            "hour": 17,
            "is_non_business_day": 0,
            "temp_delta_24h": 0.7,
            "cooling_delta_24h": 0.7,
            "apparent_temp_c": 29.4,
            "humidity_pct": 75.0,
            "discomfort_index": 76.6,
            "lag_24h_hourly_delta": -1_050.0,
            "recent_same_business_type_delta_mean": -950.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "daytime_sustained_underforecast_lift": {
                "enabled": True,
                "target_hours": [16, 17],
                "min_reference_hour": 8,
                "max_reference_hour": 15,
                "max_lead_hours": 3,
                "lookback_observed_hours": 3,
                "min_positive_residual_count": 2,
                "min_base_adjustment_mw": 600.0,
                "min_latest_residual_mw": 600.0,
                "min_mean_residual_mw": 600.0,
                "min_peak_residual_mw": 1_000.0,
                "latest_residual_override_mw": 900.0,
                "override_min_base_adjustment_mw": 0.0,
                "min_temp_delta_24h_c": 3.0,
                "min_cooling_delta_24h_c": 1.0,
                "business_min_discomfort_index": 76.5,
                "business_min_apparent_temp_c": 30.0,
                "floor_slope_fraction": 0.25,
                "floor_slack_mw": 300.0,
                "floor_shrinkage": 0.5,
                "residual_pressure_shrinkage": 0.55,
                "residual_slack_mw": 200.0,
                "max_lift_mw": 900.0,
                "min_lift_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.daytime_sustained_underforecast_lift_applied is True
    assert result.forecasts[16].forecast_mw > 36_292.4
    assert result.forecasts[17].forecast_mw > 34_412.8
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_16 = next(item for item in residual_logs if item["hour"] == 16)
    hour_17 = next(item for item in residual_logs if item["hour"] == 17)
    assert hour_16["daytimeSustainedUnderforecastDiscomfortIndex"] == pytest.approx(77.2)
    assert hour_17["daytimeSustainedUnderforecastApparentTempC"] == pytest.approx(29.4)
    assert "daytime_sustained_underforecast_lift" in result.applied_regime_reason


def test_intraday_daytime_underforecast_lift_respects_post_midday_shape_gate():
    target = date(2026, 6, 22)  # Monday, lunch-shape conflict
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        9: 34_000.0,
        10: 34_690.4,
        11: 36_118.4,
        12: 35_794.9,
        13: 37_039.7,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 9, 34_990.0),
        _actual_point(target, 10, 36_290.0),
        _actual_point(target, 11, 37_030.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 11, "is_non_business_day": 0},
        {
            "hour": 12,
            "is_non_business_day": 0,
            "temp_delta_24h": 5.0,
            "cooling_delta_24h": 5.5,
            "lag_24h_hourly_delta": 420.0,
            "recent_same_business_type_delta_mean": -860.0,
        },
        {
            "hour": 13,
            "is_non_business_day": 0,
            "temp_delta_24h": 5.0,
            "cooling_delta_24h": 2.0,
            "lag_24h_hourly_delta": 300.0,
            "recent_same_business_type_delta_mean": 898.8,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "daytime_sustained_underforecast_lift": {
                "enabled": True,
                "target_hours": [12, 13],
                "min_reference_hour": 8,
                "max_reference_hour": 14,
                "max_lead_hours": 3,
                "min_base_adjustment_mw": 600.0,
                "min_latest_residual_mw": 600.0,
                "min_mean_residual_mw": 600.0,
                "min_peak_residual_mw": 1_000.0,
                "min_temp_delta_24h_c": 3.0,
                "min_cooling_delta_24h_c": 1.0,
                "floor_slope_fraction": 0.25,
                "floor_slack_mw": 300.0,
                "floor_shrinkage": 0.5,
                "residual_pressure_shrinkage": 0.55,
                "residual_slack_mw": 200.0,
                "max_lift_mw": 900.0,
                "min_lift_mw": 100.0,
                "post_midday_shape_gate": {
                    "enabled": True,
                    "target_hours": [12, 13],
                    "min_lag_delta_mw": 600.0,
                    "min_recent_delta_mw": 600.0,
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(700.2, abs=0.1)
    assert result.daytime_sustained_underforecast_lift_applied is False
    assert result.forecasts[12].forecast_mw == pytest.approx(36_495.1, abs=0.1)
    assert result.forecasts[13].forecast_mw == pytest.approx(37_739.9, abs=0.1)


def test_intraday_post_lunch_decline_caps_near_term_overhang():
    target = date(2026, 6, 22)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        12: 35_794.9,
        13: 37_039.7,
        14: 36_871.9,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 10, 36_290.0),
        _actual_point(target, 11, 37_030.0),
        _actual_point(target, 12, 35_860.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 12, "is_non_business_day": 0},
        {
            "hour": 13,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 300.0,
            "recent_same_business_type_delta_mean": 898.8,
        },
        {
            "hour": 14,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 580.0,
            "recent_same_business_type_delta_mean": 41.2,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "post_lunch_decline_continuity_guard": {
                "enabled": True,
                "business_day_only": True,
                "target_hours": [13, 14],
                "min_reference_hour": 12,
                "max_reference_hour": 13,
                "max_lead_hours": 2,
                "latest_slope_max_mw": -700.0,
                "max_supporting_delta_mw": 900.0,
                "support_fraction": 0.35,
                "cap_buffer_mw": 500.0,
                "max_reduction_mw": 900.0,
                "min_reduction_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.post_lunch_decline_continuity_guard_applied is True
    assert result.post_lunch_decline_continuity_max_reduction_mw == pytest.approx(365.1)
    assert result.forecasts[13].forecast_mw == pytest.approx(36_674.6, abs=0.1)
    assert result.forecasts[14].forecast_mw == pytest.approx(36_563.0, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_13 = next(item for item in residual_logs if item["hour"] == 13)
    assert hour_13["postLunchDeclineContinuityCapMw"] == pytest.approx(36_674.6)
    assert "post_lunch_decline_continuity_guard" in result.applied_regime_reason


def test_intraday_caps_pre_observation_prior_stack_before_weekend_actuals():
    target = date(2026, 6, 20)  # Saturday after a hotter business day
    forecasts = _make_forecasts(target, 30_000.0)
    inference_features = pd.DataFrame([
        {
            "hour": 9,
            "is_non_business_day": 1,
            "lag_24h_business_type_mismatch": 1,
            "lag_24h": 34_000.0,
            "recent_same_business_type_mean": 30_000.0,
            "temp_delta_24h": -5.0,
            "heating_degree": 0.0,
        }
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "min_observed_hours": 3,
            "operational_calibration": {
                "pre_observation_prior_stack_cap": {
                    "enabled": True,
                    "max_observed_hours": 1,
                    "max_downshift_mw": 900.0,
                },
                "day_level_scale": {
                    "enabled": True,
                    "lag_overheat_threshold_mw": 0.0,
                    "temp_drop_threshold_c": 0.0,
                    "lag_overheat_weight": 1.0,
                    "max_abs_bias_mw": 1_000.0,
                    "observed_fade_hours": 3,
                },
                "business_type_transition_prior": {
                    "enabled": True,
                    "lag_overheat_threshold_mw": 0.0,
                    "base_allowed_excess_mw": 0.0,
                    "shrinkage": 1.0,
                    "max_abs_bias_mw": 500.0,
                },
                "day_boundary_carryover": {"enabled": False},
            },
        }
    })

    result = corrector.apply(
        forecasts,
        [],
        inference_features=inference_features,
    )

    assert result.pre_observation_prior_stack_cap_applied is True
    assert result.forecasts[9].forecast_mw == pytest.approx(29_100.0)
    assert result.pre_observation_prior_stack_cap_max_restore_mw == pytest.approx(100.0)
    assert "pre_observation_prior_stack_cap" in result.applied_regime_reason


def test_intraday_weekend_morning_ramp_floor_lifts_observed_non_business_ramp():
    target = date(2026, 6, 20)
    forecasts = _make_forecasts(target, 20_000.0)
    forecasts[9] = HourlyForecast(
        ts=f"{target.isoformat()}T09:00:00+09:00",
        forecast_mw=27_600.0,
        p95_lower_mw=27_100.0,
        p95_upper_mw=28_100.0,
        p99_lower_mw=26_800.0,
        p99_upper_mw=28_400.0,
    )
    forecasts[10] = HourlyForecast(
        ts=f"{target.isoformat()}T10:00:00+09:00",
        forecast_mw=28_200.0,
        p95_lower_mw=27_700.0,
        p95_upper_mw=28_700.0,
        p99_lower_mw=27_400.0,
        p99_upper_mw=29_000.0,
    )
    forecasts[11] = HourlyForecast(
        ts=f"{target.isoformat()}T11:00:00+09:00",
        forecast_mw=28_400.0,
        p95_lower_mw=27_900.0,
        p95_upper_mw=28_900.0,
        p99_lower_mw=27_600.0,
        p99_upper_mw=29_200.0,
    )
    actual_series = [
        _actual_point(target, 7, 23_800.0),
        _actual_point(target, 8, 26_200.0),
        _actual_point(target, 9, 28_200.0),
    ]
    inference_features = pd.DataFrame([
        {
            "hour": hour,
            "is_non_business_day": 1,
            "lag_24h_hourly_delta": delta,
            "recent_same_business_type_delta_mean": recent_delta,
        }
        for hour, delta, recent_delta in [
            (9, 1_900.0, 1_700.0),
            (10, 1_600.0, 1_100.0),
            (11, 1_100.0, 800.0),
        ]
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "morning_observed_ramp_floor": {
                "enabled": True,
                "business_day_only": False,
                "target_hours": [8, 9, 10, 11],
                "min_reference_hour": 7,
                "max_reference_hour": 10,
                "max_lead_hours": 2,
                "min_recent_slope_mw": 1_200.0,
                "min_mean_slope_mw": 1_200.0,
                "floor_slope_fraction": 0.85,
                "non_business_floor_slope_fraction": 0.35,
                "max_floor_delta_mw": 2_200.0,
                "max_lift_mw": 1_200.0,
                "non_business_max_lift_mw": 700.0,
                "min_lift_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_ramp_floor_applied is True
    assert result.morning_observed_ramp_floor_max_lift_mw == pytest.approx(700.0)
    assert result.forecasts[10].forecast_mw == pytest.approx(28_900.0)
    assert result.forecasts[11].forecast_mw == pytest.approx(29_100.0)


def test_intraday_weekend_morning_ramp_floor_uses_latest_slope_when_ramp_starts_late():
    target = date(2026, 7, 11)
    forecasts = _make_forecasts(target, 24_000.0)
    for hour, value in {
        7: 27_495.7,
        8: 29_198.6,
        9: 30_995.8,
        10: 33_573.1,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 5, 24_380.0),
        _actual_point(target, 6, 24_810.0),
        _actual_point(target, 7, 27_240.0),
    ]
    inference_features = pd.DataFrame([
        {
            "hour": hour,
            "is_non_business_day": 1,
            "lag_24h_hourly_delta": delta,
            "recent_same_business_type_delta_mean": recent_delta,
        }
        for hour, delta, recent_delta in [
            (8, 5_390.0, 1_898.8),
            (9, 4_430.0, 1_925.0),
            (10, 1_900.0, 1_061.0),
        ]
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "morning_observed_ramp_floor": {
                "enabled": True,
                "business_day_only": False,
                "target_hours": [8, 9, 10, 11],
                "min_reference_hour": 7,
                "max_reference_hour": 10,
                "max_lead_hours": 2,
                "min_recent_slope_mw": 1_200.0,
                "min_mean_slope_mw": 1_200.0,
                "floor_slope_fraction": 0.85,
                "non_business_min_latest_slope_mw": 2_000.0,
                "non_business_min_mean_slope_mw": 1_200.0,
                "non_business_floor_basis": "latest",
                "non_business_floor_slope_fraction": 1.0,
                "max_floor_delta_mw": 2_200.0,
                "max_lift_mw": 1_200.0,
                "non_business_max_lift_mw": 700.0,
                "min_lift_mw": 100.0,
                "max_latest_overforecast_mw": 500.0,
                "max_floor_delta_over_support_mw": 0.0,
                "min_support_delta_mw": 700.0,
                "support_delta_fraction": 0.5,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_ramp_floor_applied is True
    assert result.forecasts[8].forecast_mw == pytest.approx(29_440.0)
    assert result.forecasts[9].forecast_mw == pytest.approx(31_640.0)
    assert result.forecasts[10].forecast_mw == pytest.approx(33_573.1)
    ramp_items = [
        item
        for item in result.residual_adjustments_by_hour
        if item.get("morningObservedRampFloorLiftMw", 0.0) > 0.0
    ]
    assert [item["hour"] for item in ramp_items] == [8, 9]
    assert all(item["morningObservedRampFloorBasis"] == "latest" for item in ramp_items)


def test_intraday_weekend_morning_ramp_floor_waits_for_strong_latest_slope():
    target = date(2026, 7, 12)
    forecasts = _make_forecasts(target, 24_000.0)
    for hour, value in {
        7: 26_000.0,
        8: 27_000.0,
        9: 29_000.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 5, 24_120.0),
        _actual_point(target, 6, 24_610.0),
        _actual_point(target, 7, 25_830.0),
    ]
    inference_features = pd.DataFrame([
        {
            "hour": hour,
            "is_non_business_day": 1,
            "lag_24h_hourly_delta": delta,
            "recent_same_business_type_delta_mean": recent_delta,
        }
        for hour, delta, recent_delta in [
            (8, 3_000.0, 2_000.0),
            (9, 3_500.0, 2_100.0),
        ]
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "morning_observed_ramp_floor": {
                "enabled": True,
                "business_day_only": False,
                "target_hours": [8, 9, 10, 11],
                "min_reference_hour": 7,
                "max_reference_hour": 10,
                "max_lead_hours": 2,
                "min_recent_slope_mw": 1_200.0,
                "min_mean_slope_mw": 1_200.0,
                "non_business_min_latest_slope_mw": 2_000.0,
                "non_business_min_mean_slope_mw": 1_200.0,
                "non_business_floor_basis": "latest",
                "non_business_floor_slope_fraction": 1.0,
                "max_floor_delta_mw": 2_200.0,
                "non_business_max_lift_mw": 700.0,
                "min_lift_mw": 100.0,
                "max_latest_overforecast_mw": 500.0,
                "max_floor_delta_over_support_mw": 0.0,
                "min_support_delta_mw": 700.0,
                "support_delta_fraction": 0.5,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.morning_observed_ramp_floor_applied is False
    assert result.forecasts[8].forecast_mw == pytest.approx(27_000.0)
    assert result.forecasts[9].forecast_mw == pytest.approx(29_000.0)


def test_intraday_weekend_humid_daytime_underforecast_lifts_plateau_hours():
    target = date(2026, 6, 20)
    forecasts = _make_forecasts(target, 20_000.0)
    for hour, value in {
        10: 28_200.0,
        11: 28_400.0,
        12: 28_400.0,
        13: 28_500.0,
        14: 27_800.0,
        15: 27_600.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 10, 28_700.0),
        _actual_point(target, 11, 29_100.0),
        _actual_point(target, 12, 28_900.0),
    ]
    inference_features = pd.DataFrame([
        {
            "hour": hour,
            "is_non_business_day": 1,
            "temp_delta_24h": -5.0,
            "cooling_delta_24h": -4.0,
            "apparent_cooling_delta_24h": -3.0,
            "humidity_pct": 95.0,
            "discomfort_index": 75.0,
        }
        for hour in [12, 13, 14, 15]
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "daytime_sustained_underforecast_lift": {
                "enabled": True,
                "business_day_only": False,
                "target_hours": [10, 11, 12, 13, 14],
                "non_business_target_hours": [14, 15],
                "min_reference_hour": 8,
                "max_reference_hour": 14,
                "max_lead_hours": 3,
                "lookback_observed_hours": 3,
                "min_positive_residual_count": 2,
                "non_business_min_positive_residual_count": 2,
                "min_base_adjustment_mw": 600.0,
                "non_business_min_base_adjustment_mw": 250.0,
                "min_latest_residual_mw": 600.0,
                "non_business_min_latest_residual_mw": 350.0,
                "min_mean_residual_mw": 600.0,
                "non_business_min_mean_residual_mw": 450.0,
                "min_peak_residual_mw": 1_000.0,
                "non_business_min_peak_residual_mw": 700.0,
                "min_temp_delta_24h_c": 3.0,
                "min_cooling_delta_24h_c": 1.0,
                "non_business_min_discomfort_index": 74.0,
                "non_business_min_humidity_pct": 90.0,
                "min_latest_slope_mw": -800.0,
                "floor_slope_fraction": 0.25,
                "max_floor_delta_mw": 900.0,
                "floor_slack_mw": 300.0,
                "floor_shrinkage": 0.5,
                "residual_pressure_shrinkage": 0.55,
                "residual_slack_mw": 200.0,
                "max_lift_mw": 900.0,
                "non_business_max_lift_mw": 800.0,
                "min_lift_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.daytime_sustained_underforecast_lift_applied is True
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_14 = next(item for item in residual_logs if item["hour"] == 14)
    hour_15 = next(item for item in residual_logs if item["hour"] == 15)
    assert hour_14["daytimeSustainedUnderforecastLiftMw"] > 0.0
    assert hour_15["daytimeSustainedUnderforecastLiftMw"] > 0.0
    assert hour_14["daytimeSustainedUnderforecastDiscomfortIndex"] == pytest.approx(75.0)
    assert result.forecasts[13].forecast_mw == pytest.approx(28_840.0)


def test_intraday_daytime_sustained_underforecast_lifts_moderate_humid_non_business_day():
    target = date(2026, 6, 28)  # Sunday, humid but not hot by cooling-delta
    forecasts = _make_forecasts(target, 26_000.0)
    for hour, value in {
        9: 25_641.2,
        10: 26_113.1,
        11: 26_613.8,
        12: 26_273.5,
        13: 26_007.4,
        14: 25_693.1,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 9, 26_840.0),
        _actual_point(target, 10, 27_250.0),
        _actual_point(target, 11, 27_630.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 11, "is_non_business_day": 1},
        {
            "hour": 12,
            "is_non_business_day": 1,
            "temp_delta_24h": -0.5,
            "cooling_delta_24h": -0.7,
            "apparent_cooling_delta_24h": -0.5,
            "humidity_pct": 89.0,
            "discomfort_index": 70.4,
        },
        {
            "hour": 13,
            "is_non_business_day": 1,
            "temp_delta_24h": -1.2,
            "cooling_delta_24h": -2.0,
            "apparent_cooling_delta_24h": -1.0,
            "humidity_pct": 87.0,
            "discomfort_index": 70.3,
        },
        {
            "hour": 14,
            "is_non_business_day": 1,
            "temp_delta_24h": -1.5,
            "cooling_delta_24h": -2.5,
            "apparent_cooling_delta_24h": -1.2,
            "humidity_pct": 89.0,
            "discomfort_index": 70.4,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "daytime_sustained_underforecast_lift": {
                "enabled": True,
                "business_day_only": False,
                "target_hours": [10, 11, 12, 13, 14],
                "non_business_target_hours": [12, 13, 14, 15],
                "min_reference_hour": 8,
                "max_reference_hour": 14,
                "max_lead_hours": 3,
                "lookback_observed_hours": 3,
                "min_positive_residual_count": 2,
                "non_business_min_positive_residual_count": 2,
                "min_base_adjustment_mw": 600.0,
                "non_business_min_base_adjustment_mw": 250.0,
                "min_latest_residual_mw": 600.0,
                "non_business_min_latest_residual_mw": 350.0,
                "min_mean_residual_mw": 600.0,
                "non_business_min_mean_residual_mw": 450.0,
                "min_peak_residual_mw": 1_000.0,
                "non_business_min_peak_residual_mw": 700.0,
                "min_temp_delta_24h_c": 3.0,
                "min_cooling_delta_24h_c": 1.0,
                "non_business_min_discomfort_index": 70.0,
                "non_business_min_humidity_pct": 85.0,
                "min_latest_slope_mw": -800.0,
                "floor_slope_fraction": 0.25,
                "max_floor_delta_mw": 900.0,
                "floor_slack_mw": 300.0,
                "floor_shrinkage": 0.5,
                "residual_pressure_shrinkage": 0.55,
                "non_business_residual_pressure_shrinkage": 0.8,
                "residual_slack_mw": 200.0,
                "non_business_residual_slack_mw": 0.0,
                "max_lift_mw": 900.0,
                "non_business_max_lift_mw": 800.0,
                "min_lift_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.daytime_sustained_underforecast_lift_applied is True
    assert result.forecasts[12].forecast_mw == pytest.approx(27_301.4, abs=0.1)
    assert result.forecasts[13].forecast_mw == pytest.approx(27_098.9, abs=0.1)
    assert result.forecasts[14].forecast_mw == pytest.approx(26_989.3, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_12 = next(item for item in residual_logs if item["hour"] == 12)
    hour_14 = next(item for item in residual_logs if item["hour"] == 14)
    assert hour_12["daytimeSustainedUnderforecastLiftMw"] == pytest.approx(357.5)
    assert hour_14["daytimeSustainedUnderforecastHumidityPct"] == pytest.approx(89.0)
    assert "daytime_sustained_underforecast_lift" in result.applied_regime_reason


def test_intraday_weekend_daytime_lift_uses_positive_tail_after_one_earlier_overforecast():
    target = date(2026, 7, 5)  # Sunday
    forecasts = _make_forecasts(target, 27_000.0)
    for hour, value in {
        9: 27_118.3,
        10: 26_786.9,
        11: 27_614.6,
        12: 27_021.1,
        13: 26_737.6,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 9, 26_390.0),
        _actual_point(target, 10, 27_390.0),
        _actual_point(target, 11, 28_240.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 11, "is_non_business_day": 1},
        {
            "hour": 12,
            "is_non_business_day": 1,
            "temp_delta_24h": -2.6,
            "cooling_delta_24h": -2.6,
            "apparent_cooling_delta_24h": -2.3,
            "humidity_pct": 85.0,
            "discomfort_index": 73.6,
        },
        {
            "hour": 13,
            "is_non_business_day": 1,
            "temp_delta_24h": -2.8,
            "cooling_delta_24h": -2.8,
            "apparent_cooling_delta_24h": -2.4,
            "humidity_pct": 85.0,
            "discomfort_index": 73.5,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.6,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "daytime_sustained_underforecast_lift": {
                "enabled": True,
                "business_day_only": False,
                "target_hours": [10, 11, 12, 13, 14],
                "non_business_target_hours": [12, 13],
                "min_reference_hour": 8,
                "max_reference_hour": 14,
                "max_lead_hours": 3,
                "lookback_observed_hours": 3,
                "min_positive_residual_count": 2,
                "non_business_min_positive_residual_count": 2,
                "min_base_adjustment_mw": 600.0,
                "non_business_min_base_adjustment_mw": 250.0,
                "non_business_positive_tail_override": {
                    "enabled": True,
                    "min_base_adjustment_mw": 0.0,
                    "min_peak_residual_mw": 600.0,
                },
                "min_latest_residual_mw": 600.0,
                "non_business_min_latest_residual_mw": 350.0,
                "min_mean_residual_mw": 600.0,
                "non_business_min_mean_residual_mw": 450.0,
                "min_peak_residual_mw": 1_000.0,
                "non_business_min_peak_residual_mw": 700.0,
                "min_temp_delta_24h_c": 3.0,
                "min_cooling_delta_24h_c": 1.0,
                "non_business_min_discomfort_index": 70.0,
                "non_business_min_humidity_pct": 85.0,
                "min_latest_slope_mw": -800.0,
                "floor_slope_fraction": 0.25,
                "max_floor_delta_mw": 900.0,
                "floor_slack_mw": 300.0,
                "floor_shrinkage": 0.5,
                "residual_pressure_shrinkage": 0.55,
                "non_business_residual_pressure_shrinkage": 0.8,
                "residual_slack_mw": 200.0,
                "non_business_residual_slack_mw": 0.0,
                "max_lift_mw": 900.0,
                "non_business_max_lift_mw": 800.0,
                "min_lift_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.daytime_sustained_underforecast_lift_applied is True
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_12 = next(item for item in residual_logs if item["hour"] == 12)
    hour_13 = next(item for item in residual_logs if item["hour"] == 13)
    assert hour_12["daytimeSustainedUnderforecastPositiveTailOverrideActive"] is True
    assert hour_12["daytimeSustainedUnderforecastLiftMw"] > 0.0
    assert hour_13["daytimeSustainedUnderforecastPositiveTailOverrideActive"] is True
    assert result.forecasts[12].forecast_mw > 27_500.0
    assert result.forecasts[13].forecast_mw > 27_300.0


def test_intraday_daytime_sustained_underforecast_requires_heat_context():
    target = date(2026, 6, 19)
    forecasts = _make_forecasts(target, 30_000.0)
    forecasts[13] = HourlyForecast(
        ts=f"{target.isoformat()}T13:00:00+09:00",
        forecast_mw=36_000.0,
        p95_lower_mw=35_500.0,
        p95_upper_mw=36_500.0,
        p99_lower_mw=35_200.0,
        p99_upper_mw=36_800.0,
    )
    actual_series = [
        _actual_point(target, 9, 31_500.0),
        _actual_point(target, 10, 32_000.0),
        _actual_point(target, 11, 32_000.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 11, "is_non_business_day": 0},
        {
            "hour": 13,
            "is_non_business_day": 0,
            "temp_delta_24h": 0.5,
            "cooling_delta_24h": 0.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "daytime_sustained_underforecast_lift": {
                "enabled": True,
                "target_hours": [13],
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.daytime_sustained_underforecast_lift_applied is False
    assert result.forecasts[13].forecast_mw == pytest.approx(37_200.0)


def test_intraday_correction_caps_evening_level_overhang_without_local_rebound():
    target = date(2026, 5, 29)  # Friday hot-day overhang case
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        13: 38_580.0,
        14: 39_070.0,
        15: 38_460.0,
        16: 37_890.0,
        17: 36_479.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 13, 36_420.0),
        _actual_point(target, 14, 36_170.0),
        _actual_point(target, 15, 35_290.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 15, "is_non_business_day": 0},
        {
            "hour": 16,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -330.0,
            "recent_same_business_type_delta_mean": -198.8,
            "recent_same_business_type_mean": 33_367.5,
            "temp_delta_1h": -1.1,
            "cooling_delta_1h": -1.1,
            "temp_c": 28.8,
        },
        {
            "hour": 17,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -860.0,
            "recent_same_business_type_delta_mean": -875.0,
            "recent_same_business_type_mean": 32_492.5,
            "temp_delta_1h": -1.4,
            "cooling_delta_1h": -1.4,
            "temp_c": 27.4,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "evening_decline_continuity_guard": {
                "enabled": True,
                "target_hours": [16, 17],
                "min_reference_hour": 15,
                "max_lead_hours": 2,
                "latest_slope_max_mw": -500.0,
                "mean_slope_max_mw": -300.0,
                "max_supporting_delta_mw": 200.0,
                "min_forecast_rebound_mw": 800.0,
                "max_rebound_mw": 600.0,
                "actual_reference_slack_mw": 300.0,
                "weather_allowance_mw_per_c": 120.0,
                "max_weather_allowance_mw": 400.0,
                "max_reduction_mw": 900.0,
                "min_reduction_mw": 100.0,
                "level_overhang_enabled": True,
                "min_level_overhang_mw": 500.0,
                "level_overhang_shrinkage": 0.75,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(-1_200.0)
    assert result.evening_decline_continuity_guard_applied is True
    assert result.forecasts[16].forecast_mw == pytest.approx(35_865.0)
    assert result.forecasts[17].forecast_mw == pytest.approx(35_279.0)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_16 = next(item for item in residual_logs if item["hour"] == 16)
    assert hour_16["eveningDeclineContinuityMode"] == "level_overhang"
    assert hour_16["eveningDeclineContinuityCapMw"] == pytest.approx(35_590.0)
    assert hour_16["eveningDeclineContinuityReductionMw"] == pytest.approx(825.0)


def test_intraday_correction_restores_non_business_plateau_after_negative_residual():
    target = date(2026, 5, 30)  # Saturday plateau after early overprediction
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        11: 31_424.6,
        12: 29_836.7,
        13: 30_683.2,
        14: 29_551.7,
        15: 30_089.1,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 11, 29_170.0),
        _actual_point(target, 12, 29_220.0),
        _actual_point(target, 13, 29_260.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 14, "is_non_business_day": 1},
        {"hour": 15, "is_non_business_day": 1},
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "negative_residual_continuity_floor": {
                "enabled": True,
                "non_business_day_only": True,
                "target_hours": [14, 15],
                "min_reference_hour": 10,
                "max_lead_hours": 2,
                "latest_slope_min_mw": -300.0,
                "mean_slope_min_mw": -300.0,
                "floor_slack_mw": 500.0,
                "floor_slope_fraction": 0.25,
                "max_floor_slope_mw": 300.0,
                "max_restore_mw": 900.0,
                "min_restore_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(-1_200.0)
    assert result.negative_residual_continuity_floor_applied is True
    assert result.negative_residual_continuity_floor_max_restore_mw == pytest.approx(419.5)
    assert result.forecasts[14].forecast_mw == pytest.approx(28_771.2)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_14 = next(item for item in residual_logs if item["hour"] == 14)
    assert hour_14["negativeResidualContinuityFloorMw"] == pytest.approx(28_771.2)
    assert hour_14["negativeResidualContinuityRestoreMw"] == pytest.approx(419.5)
    assert "negative_residual_continuity_floor" in result.applied_regime_reason


def test_intraday_correction_limits_near_term_negative_residual_overcorrection():
    target = date(2026, 6, 2)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        15: 36_028.0,
        16: 34_191.4,
        17: 33_911.8,
        18: 31_844.6,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 15, 34_300.0),
        _actual_point(target, 16, 33_260.0),
        _actual_point(target, 17, 32_280.0),
    ]
    inference_features = pd.DataFrame([
        {
            "hour": 18,
            "is_non_business_day": 0,
            "recent_same_business_type_mean": 32_413.8,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "negative_residual_near_term_floor": {
                "enabled": True,
                "target_hours": [18],
                "min_reference_hour": 10,
                "max_lead_hours": 2,
                "min_adjustment_mw": 500.0,
                "actual_reference_slack_mw": 500.0,
                "anchor_slack_mw": 1_200.0,
                "drop_slope_allowance_fraction": 0.25,
                "max_drop_slope_allowance_mw": 400.0,
                "max_restore_mw": 700.0,
                "min_restore_mw": 100.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(-1_200.0)
    assert result.negative_residual_near_term_floor_applied is True
    assert result.negative_residual_near_term_floor_max_restore_mw == pytest.approx(700.0)
    assert result.forecasts[18].forecast_mw == pytest.approx(31_344.6)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_18 = next(item for item in residual_logs if item["hour"] == 18)
    assert hour_18["negativeResidualNearTermRestoreMw"] == pytest.approx(700.0)
    assert hour_18["negativeResidualNearTermFloorMw"] == pytest.approx(31_535.0)
    assert "negative_residual_near_term_floor" in result.applied_regime_reason


def test_intraday_near_term_floor_damps_restore_when_evening_shape_points_down():
    target = date(2026, 7, 2)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        17: 33_940.0,
        18: 33_300.0,
        19: 32_750.0,
        20: 31_672.7,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 17, 32_940.0),
        _actual_point(target, 18, 32_850.0),
        _actual_point(target, 19, 32_230.0),
    ]
    inference_features = pd.DataFrame([
        {
            "hour": 20,
            "is_non_business_day": 0,
            "recent_same_business_type_mean": 32_100.0,
            "lag_24h_hourly_delta": -1_540.0,
            "recent_same_business_type_delta_mean": -1_477.5,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "negative_residual_near_term_floor": {
                "enabled": True,
                "target_hours": [20],
                "min_reference_hour": 10,
                "max_lead_hours": 2,
                "min_adjustment_mw": 500.0,
                "actual_reference_slack_mw": 500.0,
                "anchor_slack_mw": 1_200.0,
                "drop_slope_allowance_fraction": 0.25,
                "max_drop_slope_allowance_mw": 400.0,
                "max_restore_mw": 700.0,
                "min_restore_mw": 100.0,
                "decline_support_damping": {
                    "enabled": True,
                    "latest_slope_max_mw": -500.0,
                    "max_support_delta_mw": -500.0,
                    "restore_factor": 0.25,
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_20 = next(item for item in residual_logs if item["hour"] == 20)
    assert result.base_adjustment_mw == pytest.approx(-656.7, abs=0.1)
    assert result.negative_residual_near_term_floor_applied is True
    assert hour_20["negativeResidualNearTermSupportDeltaMw"] == pytest.approx(
        -1_477.5,
    )
    assert hour_20["negativeResidualNearTermDeclineDampingFactor"] == pytest.approx(
        0.25,
    )
    assert hour_20["negativeResidualNearTermRestoreMw"] == pytest.approx(139.8, abs=0.1)
    assert result.forecasts[20].forecast_mw == pytest.approx(31_155.8, abs=0.1)


def test_intraday_near_term_floor_protects_first_future_hour_from_stale_negative_residual():
    target = date(2026, 7, 7)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        13: 35_000.0,
        14: 35_000.0,
        15: 35_000.0,
        16: 34_453.0,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 13, 34_000.0),
        _actual_point(target, 14, 34_000.0),
        _actual_point(target, 15, 34_190.0),
    ]
    inference_features = pd.DataFrame([
        {
            "hour": 16,
            "is_non_business_day": 0,
            "recent_same_business_type_mean": 34_780.0,
            "lag_24h_hourly_delta": -150.0,
            "recent_same_business_type_delta_mean": -175.0,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "negative_residual_near_term_floor": {
                "enabled": True,
                "target_hours": [16],
                "min_reference_hour": 10,
                "max_lead_hours": 2,
                "min_adjustment_mw": 500.0,
                "actual_reference_slack_mw": 150.0,
                "anchor_slack_mw": 1_200.0,
                "drop_slope_allowance_fraction": 0.25,
                "max_drop_slope_allowance_mw": 400.0,
                "max_restore_mw": 700.0,
                "min_restore_mw": 100.0,
            },
            "ramp_guard": {"enabled": False},
            "evening_decline_continuity_guard": {"enabled": False},
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.base_adjustment_mw == pytest.approx(-936.7, abs=0.1)
    assert result.negative_residual_near_term_floor_applied is True
    assert result.forecasts[16].forecast_mw == pytest.approx(34_040.0, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_16 = next(item for item in residual_logs if item["hour"] == 16)
    assert hour_16["negativeResidualNearTermFloorMw"] == pytest.approx(34_040.0)
    assert hour_16["negativeResidualNearTermRestoreMw"] == pytest.approx(523.7, abs=0.1)


def test_intraday_correction_keeps_evening_rebound_when_shape_supports_it():
    target = date(2026, 5, 27)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        15: 34_395.7,
        16: 34_486.2,
        17: 32_901.8,
        18: 34_165.8,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 15, 34_400.0),
        _actual_point(target, 16, 34_220.0),
        _actual_point(target, 17, 33_330.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 17, "is_non_business_day": 0},
        {
            "hour": 18,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": 500.0,
            "recent_same_business_type_delta_mean": 350.0,
            "temp_delta_1h": 0.3,
            "cooling_delta_1h": 0.3,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "evening_decline_continuity_guard": {
                "enabled": True,
                "target_hours": [18],
                "max_supporting_delta_mw": 200.0,
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.evening_decline_continuity_guard_applied is False
    assert result.evening_decline_continuity_max_reduction_mw == pytest.approx(0.0)
    assert result.forecasts[18].forecast_mw == pytest.approx(34_165.8)


def test_intraday_evening_decline_uses_recent_anchor_for_strong_late_drop_overhang():
    target = date(2026, 7, 7)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        17: 33_263.3,
        18: 32_849.5,
        19: 32_709.0,
        20: 31_586.1,
        21: 30_475.7,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 17, 33_590.0),
        _actual_point(target, 18, 33_120.0),
        _actual_point(target, 19, 32_510.0),
    ]
    inference_features = pd.DataFrame([
        {"hour": 19, "is_non_business_day": 0},
        {
            "hour": 21,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -1_580.0,
            "recent_same_business_type_delta_mean": -1_595.0,
            "recent_same_business_type_mean": 29_612.5,
            "temp_delta_1h": 0.0,
            "cooling_delta_1h": 0.0,
            "temp_c": 22.5,
        },
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "evening_decline_continuity_guard": {
                "enabled": True,
                "target_hours": [21],
                "min_reference_hour": 15,
                "max_lead_hours": 2,
                "latest_slope_max_mw": -500.0,
                "mean_slope_max_mw": -300.0,
                "max_supporting_delta_mw": 200.0,
                "min_forecast_rebound_mw": 800.0,
                "max_rebound_mw": 600.0,
                "actual_reference_slack_mw": 300.0,
                "weather_allowance_mw_per_c": 120.0,
                "max_weather_allowance_mw": 400.0,
                "max_reduction_mw": 900.0,
                "min_reduction_mw": 100.0,
                "level_overhang_enabled": True,
                "min_level_overhang_mw": 500.0,
                "level_overhang_shrinkage": 0.75,
                "strong_decline_level_anchor": {
                    "enabled": True,
                    "max_supporting_delta_mw": -800.0,
                    "anchor_buffer_mw": 300.0,
                    "min_overhang_mw": 250.0,
                    "shrinkage": 0.75,
                },
            },
            "ramp_guard": {"enabled": False},
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.evening_decline_continuity_guard_applied is True
    assert result.forecasts[21].forecast_mw == pytest.approx(30_053.3, abs=0.1)
    residual_logs = result.metadata()["residualCarryoverByHour"]
    hour_21 = next(item for item in residual_logs if item["hour"] == 21)
    assert hour_21["eveningDeclineContinuityMode"] == "strong_decline_level_anchor"
    assert hour_21["eveningDeclineContinuityCapMw"] == pytest.approx(29_912.5)
    assert hour_21["eveningDeclineContinuityReductionMw"] == pytest.approx(422.4, abs=0.1)


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


def test_intraday_ramp_guard_limits_evening_negative_carryover_after_sharp_drop():
    target = date(2026, 6, 1)
    forecasts = _make_forecasts(target, 30_000.0)
    for hour, value in {
        16: 40_246.0,
        17: 37_769.3,
        18: 35_640.8,
        19: 33_319.5,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            forecast_mw=value,
            p95_lower_mw=value - 500.0,
            p95_upper_mw=value + 500.0,
            p99_lower_mw=value - 800.0,
            p99_upper_mw=value + 800.0,
        )
    actual_series = [
        _actual_point(target, 16, 37_400.0),
        _actual_point(target, 17, 36_060.0),
        _actual_point(target, 18, 34_930.0),
    ]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 1.0,
            "max_abs_adjustment_mw": 1_200.0,
            "decay_per_hour": 1.0,
            "ramp_guard": {
                "enabled": True,
                "min_reference_hour": 10,
                "max_lead_hours": 3,
                "max_increase_mw_by_lead_hour": [1800, 2400, 3000],
                "max_decrease_mw_by_lead_hour": [1600, 2600, 3600],
                "observed_drop_relaxation": {
                    "enabled": True,
                    "min_recent_drop_mw": 700.0,
                    "lookback_hours": 2,
                    "skip_shape_guard": True,
                    "max_decrease_mw_by_lead_hour": [1600, 2800, 4200],
                },
            },
        }
    })

    result = corrector.apply(forecasts, actual_series)

    assert result.base_adjustment_mw == pytest.approx(-1_200.0)
    assert result.ramp_guard_applied is True
    assert result.forecasts[19].forecast_mw == pytest.approx(33_330.0)
    assert result.forecasts[19].p95_lower_mw == pytest.approx(32_830.0)


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


def test_intraday_ramp_guard_relaxes_drop_cap_when_target_shape_supports_decline():
    target = date(2026, 7, 9)
    forecasts = _make_forecasts(target, 37_350.0)
    forecasts[20] = HourlyForecast(
        ts=f"{target.isoformat()}T20:00:00+09:00",
        forecast_mw=35_000.0,
        p95_lower_mw=34_500.0,
        p95_upper_mw=35_500.0,
        p99_lower_mw=34_200.0,
        p99_upper_mw=35_800.0,
    )
    forecasts[21] = HourlyForecast(
        ts=f"{target.isoformat()}T21:00:00+09:00",
        forecast_mw=31_900.0,
        p95_lower_mw=31_400.0,
        p95_upper_mw=32_400.0,
        p99_lower_mw=31_100.0,
        p99_upper_mw=32_700.0,
    )
    actual_series = [
        _actual_point(target, 17, 39_520.0),
        _actual_point(target, 18, 38_643.0),
        _actual_point(target, 19, 37_350.0),
    ]
    inference_features = pd.DataFrame([
        {
            "hour": hour,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -200.0,
            "recent_same_business_type_delta_mean": -200.0,
        }
        for hour in range(24)
    ])
    inference_features.loc[
        inference_features["hour"] == 21,
        ["lag_24h_hourly_delta", "recent_same_business_type_delta_mean"],
    ] = [-1_940.0, -1_667.5]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "shape_guard": {"enabled": False},
            "ramp_guard": {
                "enabled": True,
                "min_reference_hour": 10,
                "max_lead_hours": 3,
                "max_increase_mw_by_lead_hour": [1800, 2400, 3000],
                "max_decrease_mw_by_lead_hour": [1600, 2600, 3600],
                "observed_drop_relaxation": {
                    "enabled": True,
                    "min_recent_drop_mw": 700,
                    "lookback_hours": 2,
                    "skip_shape_guard": True,
                    "max_decrease_mw_by_lead_hour": [1600, 2800, 4200],
                    "decline_support": {
                        "enabled": True,
                        "business_day_only": True,
                        "min_lead_hours": 2,
                        "max_support_delta_mw": -1000,
                        "max_decrease_mw_by_lead_hour": [1600, 4000, 5600],
                    },
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.observed_drop_relaxation_active is True
    assert result.ramp_guard_applied is True
    assert result.ramp_guard_decline_support_relaxation_applied is True
    assert "ramp_guard_decline_support_relaxation" in result.applied_regime_reason
    assert result.ramp_guard_decline_support_relaxation_max_extra_drop_mw == pytest.approx(1_200.0)
    assert result.forecasts[20].forecast_mw == pytest.approx(35_750.0)
    assert result.forecasts[21].forecast_mw == pytest.approx(33_350.0)
    assert result.metadata()["rampGuardDeclineSupportRelaxationApplied"] is True


def test_intraday_ramp_guard_allows_supported_evening_decline_after_moderate_drop():
    target = date(2026, 7, 15)
    forecasts = _make_forecasts(target, 50_000.0)
    forecasts[16] = HourlyForecast(
        ts=f"{target.isoformat()}T16:00:00+09:00",
        forecast_mw=50_060.0,
        p95_lower_mw=49_560.0,
        p95_upper_mw=50_560.0,
        p99_lower_mw=49_260.0,
        p99_upper_mw=50_860.0,
    )
    forecasts[17] = HourlyForecast(
        ts=f"{target.isoformat()}T17:00:00+09:00",
        forecast_mw=47_167.5,
        p95_lower_mw=46_667.5,
        p95_upper_mw=47_667.5,
        p99_lower_mw=46_367.5,
        p99_upper_mw=47_967.5,
    )
    forecasts[18] = HourlyForecast(
        ts=f"{target.isoformat()}T18:00:00+09:00",
        forecast_mw=45_687.2,
        p95_lower_mw=45_187.2,
        p95_upper_mw=46_187.2,
        p99_lower_mw=44_887.2,
        p99_upper_mw=46_487.2,
    )
    actual_series = [
        _actual_point(target, 14, 50_440.0),
        _actual_point(target, 15, 50_200.0),
        _actual_point(target, 16, 49_680.0),
    ]
    inference_features = pd.DataFrame([
        {
            "hour": hour,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -200.0,
            "recent_same_business_type_delta_mean": -200.0,
        }
        for hour in range(24)
    ])
    inference_features.loc[
        inference_features["hour"] == 17,
        ["lag_24h_hourly_delta", "recent_same_business_type_delta_mean"],
    ] = [-1_780.0, -1_341.2]
    inference_features.loc[
        inference_features["hour"] == 18,
        ["lag_24h_hourly_delta", "recent_same_business_type_delta_mean"],
    ] = [-1_550.0, -976.2]
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "shape_guard": {
                "enabled": True,
                "min_reference_hour": 12,
                "hours": [15, 16, 17, 18, 19],
                "max_drop_mw": 1_000.0,
            },
            "ramp_guard": {
                "enabled": True,
                "min_reference_hour": 10,
                "max_lead_hours": 3,
                "max_increase_mw_by_lead_hour": [1_800.0, 2_400.0, 3_000.0],
                "max_decrease_mw_by_lead_hour": [1_600.0, 2_600.0, 3_600.0],
                "observed_drop_relaxation": {
                    "enabled": True,
                    "min_recent_drop_mw": 500.0,
                    "lookback_hours": 2,
                    "skip_shape_guard": True,
                    "max_decrease_mw_by_lead_hour": [1_600.0, 2_800.0, 4_200.0],
                    "decline_support": {
                        "enabled": True,
                        "business_day_only": True,
                        "min_lead_hours": 1,
                        "max_support_delta_mw": -900.0,
                        "max_decrease_mw_by_lead_hour": [
                            2_600.0,
                            4_800.0,
                            6_500.0,
                        ],
                    },
                },
            },
        },
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.observed_drop_relaxation_active is True
    assert result.shape_guard_applied is False
    assert result.ramp_guard_applied is False
    assert result.ramp_guard_decline_support_relaxation_applied is True
    assert result.forecasts[17].forecast_mw == pytest.approx(47_167.5)
    assert result.forecasts[18].forecast_mw == pytest.approx(45_687.2)
    assert result.metadata()["rampGuardDeclineSupportRelaxationApplied"] is True


def test_intraday_ramp_guard_keeps_drop_cap_without_decline_shape_support():
    target = date(2026, 7, 9)
    forecasts = _make_forecasts(target, 37_350.0)
    forecasts[21] = HourlyForecast(
        ts=f"{target.isoformat()}T21:00:00+09:00",
        forecast_mw=31_900.0,
        p95_lower_mw=31_400.0,
        p95_upper_mw=32_400.0,
        p99_lower_mw=31_100.0,
        p99_upper_mw=32_700.0,
    )
    actual_series = [
        _actual_point(target, 17, 39_520.0),
        _actual_point(target, 18, 38_643.0),
        _actual_point(target, 19, 37_350.0),
    ]
    inference_features = pd.DataFrame([
        {
            "hour": hour,
            "is_non_business_day": 0,
            "lag_24h_hourly_delta": -300.0,
            "recent_same_business_type_delta_mean": -300.0,
        }
        for hour in range(24)
    ])
    corrector = IntradayResidualCorrector({
        "intraday_correction": {
            "lookback_hours": 3,
            "min_observed_hours": 3,
            "shrinkage": 0.0,
            "decay_per_hour": 1.0,
            "shape_guard": {"enabled": False},
            "ramp_guard": {
                "enabled": True,
                "min_reference_hour": 10,
                "max_lead_hours": 3,
                "max_increase_mw_by_lead_hour": [1800, 2400, 3000],
                "max_decrease_mw_by_lead_hour": [1600, 2600, 3600],
                "observed_drop_relaxation": {
                    "enabled": True,
                    "min_recent_drop_mw": 700,
                    "lookback_hours": 2,
                    "skip_shape_guard": True,
                    "max_decrease_mw_by_lead_hour": [1600, 2800, 4200],
                    "decline_support": {
                        "enabled": True,
                        "business_day_only": True,
                        "min_lead_hours": 2,
                        "max_support_delta_mw": -1000,
                        "max_decrease_mw_by_lead_hour": [1600, 4000, 5600],
                    },
                },
            },
        }
    })

    result = corrector.apply(
        forecasts,
        actual_series,
        inference_features=inference_features,
    )

    assert result.observed_drop_relaxation_active is True
    assert result.ramp_guard_decline_support_relaxation_applied is False
    assert result.forecasts[21].forecast_mw == pytest.approx(34_550.0)


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
