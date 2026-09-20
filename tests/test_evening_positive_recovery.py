"""Observed recovery may veto damping, never create a new residual lift."""
from copy import deepcopy
from dataclasses import replace

import pandas as pd
import pytest

from python.forecast.baseline import HourlyForecast
from python.forecast.intraday_correction import IntradayResidualCorrector


def _case():
    forecasts = [
        HourlyForecast(f"2026-09-20T{h:02}:00:00+09:00", 28_000.0,
                       27_000.0, 29_000.0, 26_500.0, 29_500.0)
        for h in range(24)
    ]
    actual = [
        {"ts": forecasts[h].ts, "actualMw": value, "actualSource": "observed"}
        for h, value in [(14, 28_500.0), (15, 28_500.0), (16, 29_210.0)]
    ]
    features = pd.DataFrame([
        {"hour": h, "is_non_business_day": 1, "lag_24h_hourly_delta": 260.0,
         "recent_same_business_type_delta_mean": 502.5}
        for h in range(24)
    ])
    config = {"intraday_correction": {
        "shrinkage": 0.6, "decay_per_hour": 0.92,
        "non_business_evening_positive_residual_damping": {
            "enabled": True, "target_hours": [17, 18, 19, 20],
            "min_reference_hour": 12, "min_lead_hours": 2, "max_lead_hours": 6,
            "min_base_adjustment_mw": 350, "weak_support_delta_mw": 600,
            "damping_factor": 0.45, "min_damped_mw": 120,
            "observed_recovery_veto": {"enabled": True, "max_lead_hours": 3,
                "min_latest_slope_mw": 600, "min_mean_slope_mw": 300},
        },
    }}
    return forecasts, actual, features, config


def _run(forecasts, actual, features, config):
    return IntradayResidualCorrector(config).apply(
        forecasts, actual, inference_features=features,
    )


def test_recovery_only_restores_existing_positive_residual_and_preserves_inputs():
    forecasts, actual, features, config = _case()
    saved_forecasts, saved_actual, saved_features = deepcopy(forecasts), deepcopy(actual), features.copy(deep=True)
    result = _run(forecasts, actual, features, config)
    old = deepcopy(config)
    old["intraday_correction"]["non_business_evening_positive_residual_damping"]["observed_recovery_veto"]["enabled"] = False
    baseline = _run(forecasts, actual, features, old)
    undamped = deepcopy(config)
    undamped["intraday_correction"]["non_business_evening_positive_residual_damping"]["enabled"] = False
    reference = _run(forecasts, actual, features, undamped)

    for h in [18, 19]:
        assert result.forecasts[h] == reference.forecasts[h]
        assert result.forecasts[h].forecast_mw > baseline.forecasts[h].forecast_mw
        assert result.forecasts[h].p95_upper_mw - result.forecasts[h].p95_lower_mw == 2000
        assert result.forecasts[h].p99_upper_mw - result.forecasts[h].p99_lower_mw == 3000
    for h in [*range(18), *range(20, 24)]:
        assert result.forecasts[h] == baseline.forecasts[h]
    trace = {r["hour"]: r for r in result.residual_adjustments_by_hour}
    assert trace[18]["nonBusinessEveningPositiveResidualDampingFactor"] == 1.0
    assert trace[18]["nonBusinessEveningPositiveResidualDampedMw"] == 0.0
    assert trace[18]["nonBusinessEveningPositiveResidualSupportDeltaMw"] == 502.5
    assert trace[18]["nonBusinessEveningPositiveResidualObservedRecovery"] == {
        "latestSlopeMw": 710.0, "meanSlopeMw": 355.0, "minResidualMw": 500.0,
    }
    assert trace[20]["nonBusinessEveningPositiveResidualObservedRecovery"] is None
    assert "non_business_evening_positive_residual_observed_recovery" in result.applied_regime_reason
    assert forecasts == saved_forecasts and actual == saved_actual
    pd.testing.assert_frame_equal(features, saved_features)


@pytest.mark.parametrize("failure", [
    "falling", "weak_latest", "weak_mean", "zero_residual", "negative_residual",
    "missing", "fallback", "missing_forecast", "nonfinite_forecast",
    "negative_support", "missing_support", "business", "negative_base", "off", "absent",
])
def test_recovery_fails_closed_without_required_evidence(failure):
    forecasts, actual, features, config = _case()
    guard = config["intraday_correction"]["non_business_evening_positive_residual_damping"]
    if failure == "falling":
        actual[-1]["actualMw"] = 28_100
    elif failure == "weak_latest":
        actual[-1]["actualMw"] = 28_900
    elif failure == "weak_mean":
        actual[0]["actualMw"] = 29_000
    elif failure in {"zero_residual", "negative_residual"}:
        forecasts[14] = replace(forecasts[14], forecast_mw=actual[0]["actualMw"] + (1 if failure == "negative_residual" else 0))
    elif failure == "missing":
        actual[0]["ts"] = forecasts[13].ts
    elif failure == "fallback":
        actual[0]["actualSource"] = "tepco_forecast_fallback"
    elif failure == "missing_forecast":
        forecasts = [f for h, f in enumerate(forecasts) if h != 14]
    elif failure == "nonfinite_forecast":
        forecasts[14] = replace(forecasts[14], forecast_mw=float('nan'))
    elif failure in {"negative_support", "missing_support"}:
        value = -1 if failure == "negative_support" else float('nan')
        features[["lag_24h_hourly_delta", "recent_same_business_type_delta_mean"]] = value
    elif failure == "business":
        features["is_non_business_day"] = 0
    elif failure == "negative_base":
        for r in actual:
            r["actualMw"] -= 2000
    elif failure == "off":
        guard["observed_recovery_veto"]["enabled"] = False
    elif failure == "absent":
        guard.pop("observed_recovery_veto")
    result = _run(forecasts, actual, features, config)
    assert all(r["nonBusinessEveningPositiveResidualObservedRecovery"] is None
               for r in result.residual_adjustments_by_hour)
    old = deepcopy(config)
    old["intraday_correction"]["non_business_evening_positive_residual_damping"]["observed_recovery_veto"] = {"enabled": False}
    baseline = _run(forecasts, actual, features, old)
    for f, b in zip(result.forecasts, baseline.forecasts):
        if pd.notna(f.forecast_mw):
            assert f.forecast_mw == b.forecast_mw


def test_recovery_uses_configured_thresholds_and_horizon():
    forecasts, actual, features, config = _case()
    veto = config["intraday_correction"]["non_business_evening_positive_residual_damping"]["observed_recovery_veto"]
    veto["max_lead_hours"] = 2
    result = _run(forecasts, actual, features, config)
    trace = {r["hour"]: r for r in result.residual_adjustments_by_hour}
    assert trace[18]["nonBusinessEveningPositiveResidualObservedRecovery"] is not None
    assert trace[19]["nonBusinessEveningPositiveResidualObservedRecovery"] is None
    veto["min_latest_slope_mw"] = 711
    result = _run(forecasts, actual, features, config)
    assert all(r["nonBusinessEveningPositiveResidualObservedRecovery"] is None for r in result.residual_adjustments_by_hour)


def test_september_20_captured_residual_and_negative_target_support():
    forecasts, actual, features, config = _case()
    for h, value in {14: 26628.7, 15: 26618.4, 16: 27514.4,
                     18: 28393.2, 19: 27982.3}.items():
        forecasts[h] = replace(forecasts[h], forecast_mw=value,
            p95_lower_mw=value-1000, p95_upper_mw=value+1000,
            p99_lower_mw=value-1500, p99_upper_mw=value+1500)
    for row, value in zip(actual, [27310.0, 27310.0, 28020.0]):
        row["actualMw"] = value
    features.loc[19, ["lag_24h_hourly_delta", "recent_same_business_type_delta_mean"]] = [-620, -360]
    result = _run(forecasts, actual, features, config)
    assert result.base_adjustment_mw == 375.7
    assert result.forecasts[18].forecast_mw == 28738.8
    assert result.forecasts[19].forecast_mw == 28125.4
    old = deepcopy(config)
    old["intraday_correction"]["non_business_evening_positive_residual_damping"]["observed_recovery_veto"]["enabled"] = False
    baseline = _run(forecasts, actual, features, old)
    assert baseline.forecasts[18].forecast_mw == 28548.7
    assert result.forecasts[19] == baseline.forecasts[19]
