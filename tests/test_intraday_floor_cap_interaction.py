"""Exercise floor restoration together with the deployed downstream controls."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml

from python.forecast.baseline import HourlyForecast
from python.forecast.intraday_correction import IntradayResidualCorrector


@pytest.mark.parametrize("previous_actual,lag_delta,recent_delta,expected_restore", [
    (27_690.0, 1_650.0, 292.5, 421.7),
    (27_690.0, 1.0, 1.0, 0.0),
    (27_690.0, -1.0, 292.5, 0.0),
    (27_690.0, 1_650.0, 0.0, 0.0),
    (27_690.0, 1_650.0, None, 0.0),
    (27_690.0, float("nan"), 292.5, 0.0),
    (29_000.0, 1_650.0, 292.5, 0.0),
    (None, 1_650.0, 292.5, 0.0),
])
def test_historical_floor_requires_contiguous_magnitude_supported_ramp(
    previous_actual, lag_delta, recent_delta, expected_restore,
):
    cfg = yaml.safe_load((Path(__file__).parents[1] / "config.yaml").read_text(encoding="utf-8"))
    corrector = IntradayResidualCorrector(cfg)
    actuals = {10: 28_360.0, 11: 29_450.0}
    if previous_actual is not None:
        actuals[9] = previous_actual
    context = corrector._negative_residual_near_term_floor_context(actuals, 11)
    features = pd.DataFrame([{
        "hour": 13, "recent_same_business_type_mean": 33_266.2,
        "lag_24h_hourly_delta": lag_delta,
        "recent_same_business_type_delta_mean": recent_delta,
    }])
    result = corrector._negative_residual_near_term_floor_restore(
        context, features, forecast_hour=13, lead_hours=2,
        decayed_adjustment_mw=-507.9, pre_calibration_mw=30_121.2,
        final_before_floor_mw=29_613.3,
    )
    if expected_restore == 0.0:
        assert result is None
    else:
        assert result["restoreMw"] == pytest.approx(expected_restore)
        assert result["rampAllowanceMw"] == 585.0
        assert result["floorMw"] == 30_035.0
        assert 29_613.3 + result["restoreMw"] == pytest.approx(30_035.0)


def test_positive_sign_alone_does_not_authorize_a_large_ramp_allowance():
    cfg = yaml.safe_load((Path(__file__).parents[1] / "config.yaml").read_text(encoding="utf-8"))
    corrector = IntradayResidualCorrector(cfg)
    context = corrector._negative_residual_near_term_floor_context(
        {9: 27_690.0, 10: 28_360.0, 11: 29_450.0}, 11,
    )
    result = corrector._negative_residual_near_term_floor_restore(
        context, pd.DataFrame([{
            "hour": 13, "recent_same_business_type_mean": 33_266.2,
            "lag_24h_hourly_delta": 1.0, "recent_same_business_type_delta_mean": 1.0,
        }]), forecast_hour=13, lead_hours=2, decayed_adjustment_mw=-1_000.0,
        pre_calibration_mw=30_000.0, final_before_floor_mw=29_000.0,
    )
    assert result["rampAllowanceMw"] == 2.0
    assert result["floorMw"] == 29_452.0
    assert result["restoreMw"] == 452.0


def test_observed_bound_recalculates_downstream_caps_instead_of_subtracting_700():
    cfg = yaml.safe_load((Path(__file__).parents[1] / "config.yaml").read_text(encoding="utf-8"))
    target = date(2026, 9, 10)
    values = {12: 35_000.0, 13: 35_500.0, 14: 35_917.1, 15: 35_672.1, 16: 35_992.9}
    forecasts = [HourlyForecast(
        f"{target}T{h:02d}:00:00+09:00", value, value-500, value+500, value-800, value+800,
    ) for h in range(24) for value in [values.get(h, 35_000.0)]]
    actuals = [{"ts": f"{target}T{h:02d}:00:00+09:00", "actualMw": value,
                "actualSource": "observed"}
               for h, value in ((12, 32_630), (13, 33_320), (14, 33_400))]
    features = pd.DataFrame([{
        "hour": h, "is_non_business_day": 0, "lag_24h_business_type_mismatch": 0,
        "recent_same_business_type_mean": 39_706.2,
        "lag_24h_hourly_delta": -2_340.0, "recent_same_business_type_delta_mean": -558.8,
        "temp_delta_24h": -5.7, "cooling_delta_24h": -5.7,
    } for h in range(24)])
    original = [vars(point).copy() for point in forecasts]

    result = IntradayResidualCorrector(cfg).apply(forecasts, actuals, inference_features=features)

    assert result.base_adjustment_mw == -1_200.0
    assert [vars(point) for point in forecasts] == original
    assert result.forecasts[:15] == forecasts[:15]
    for hour, cap_reduction in ((15, 1_072.1), (16, 1_488.9)):
        log = next(row for row in result.residual_adjustments_by_hour if row["hour"] == hour)
        assert log["negativeResidualNearTermRestoreMw"] == 0.0
        assert log["afternoonObservedAnchorCapReductionMw"] == pytest.approx(cap_reduction)
        assert result.forecasts[hour].forecast_mw == pytest.approx(33_400.0)
        assert result.forecasts[hour].p95_upper_mw - result.forecasts[hour].forecast_mw == 500.0
        terminal = next(row for row in result.terminal_adjustments_by_hour if row["hour"] == hour)
        assert terminal["preCalibrationMw"] + terminal["totalAdjustmentMw"] == pytest.approx(33_400.0)
