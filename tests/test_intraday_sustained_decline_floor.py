"""Keep floor restoration from fighting a corroborated, gradual decline."""
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
import yaml

from python.forecast.baseline import HourlyForecast
from python.forecast.intraday_correction import IntradayResidualCorrector


def _config():
    return yaml.safe_load((Path(__file__).parents[1] / "config.yaml").read_text(encoding="utf-8"))


def _features():
    return pd.DataFrame([
        {"hour": 19, "lag_24h_hourly_delta": -1860.0,
         "recent_same_business_type_delta_mean": -1551.2,
         "recent_same_business_type_mean": 35837.5, "is_non_business_day": 0},
        {"hour": 20, "lag_24h_hourly_delta": -1970.0,
         "recent_same_business_type_delta_mean": -1751.2,
         "recent_same_business_type_mean": 34086.2, "is_non_business_day": 0},
    ])


@pytest.mark.parametrize("actuals,feature_change,expected", [
    ({16: 33250, 17: 32900, 18: 32740}, None, True),
    ({16: 33240, 17: 32900, 18: 32740}, None, True),  # cumulative boundary: -500 MW
    ({16: 33239, 17: 32900, 18: 32740}, None, False),
    ({16: 32490, 17: 32170, 18: 32070}, None, False),  # September 11: only -420 MW
    ({16: 32000, 17: 32900, 18: 32740}, None, False),  # one dip after growth
    ({16: 32740, 17: 32740, 18: 32740}, None, False),
    ({16: 33250, 18: 32740}, None, False),
    ({17: 32900, 18: 32740}, None, False),
    ({16: 33250, 17: 32900, 18: 32740}, (19, "lag_24h_hourly_delta", 300), False),
    ({16: 33250, 17: 32900, 18: 32740}, (19, "recent_same_business_type_delta_mean", None), False),
    ({16: 33250, 17: 32900, 18: 32740}, (19, "lag_24h_hourly_delta", float("nan")), False),
    ({16: 33250, 17: 32900, 18: 32740}, (20, "lag_24h_hourly_delta", float("inf")), False),
    ({16: 33250, 17: 32900, 18: 32740}, (20, "recent_same_business_type_delta_mean", -499), False),
])
def test_sustained_decline_requires_contiguous_actuals_and_entire_future_path(
    actuals, feature_change, expected,
):
    corrector = IntradayResidualCorrector(_config())
    context = corrector._negative_residual_near_term_floor_context(actuals, 18)
    features = _features()
    if feature_change:
        h, key, value = feature_change
        features.loc[features.hour == h, key] = value
    assert corrector._near_term_sustained_decline_supported(context, features, 20, 2) is expected


@pytest.mark.parametrize("enabled,expected_restore", [(True, 175.0), (False, 700.0)])
def test_sustained_decline_full_pipeline_only_reduces_negative_restoration(enabled, expected_restore):
    cfg = _config()
    cfg["intraday_correction"]["negative_residual_near_term_floor"]["decline_support_damping"]["enabled"] = enabled
    values = {16: 35974.2, 17: 35647.8, 18: 34465.2, 19: 32645.6, 20: 31560.3}
    forecasts = [HourlyForecast(f"2026-09-10T{h:02d}:00:00+09:00", v, v-500, v+500, v-800, v+800)
                 for h in range(24) for v in [values.get(h, 30000.0)]]
    actuals = [{"ts": f"2026-09-10T{h:02d}:00:00+09:00", "actualMw": v, "actualSource": "observed"}
               for h, v in ((16, 33250.0), (17, 32900.0), (18, 32740.0))]
    before = deepcopy(forecasts)
    result = IntradayResidualCorrector(cfg).apply(forecasts, actuals, inference_features=_features())

    assert result.base_adjustment_mw == -1200.0
    assert forecasts == before
    assert result.forecasts[:19] == before[:19]
    for h, decay in ((19, 1.0), (20, .92)):
        row = next(r for r in result.residual_adjustments_by_hour if r["hour"] == h)
        assert row["negativeResidualNearTermRestoreMw"] == expected_restore
        assert row["negativeResidualNearTermDeclineEvidenceBasis"] == (
            "two_interval_decline_with_supported_path" if enabled else None
        )
        expected = values[h] - 1200 * decay + expected_restore
        assert result.forecasts[h].forecast_mw == pytest.approx(expected)
        assert result.forecasts[h].p95_upper_mw - result.forecasts[h].forecast_mw == 500.0
        assert result.forecasts[h].p99_lower_mw == pytest.approx(expected - 800.0)
        terminal = next(r for r in result.terminal_adjustments_by_hour if r["hour"] == h)
        assert terminal["preCalibrationMw"] + terminal["totalAdjustmentMw"] == pytest.approx(expected)


@pytest.mark.parametrize("lead,adjustment", [(0, -1200.0), (3, -1200.0), (2, 600.0)])
def test_no_sustained_decline_intervention_on_past_far_future_or_positive_adjustment(lead, adjustment):
    corrector = IntradayResidualCorrector(_config())
    context = corrector._negative_residual_near_term_floor_context({16: 33250, 17: 32900, 18: 32740}, 18)
    assert corrector._negative_residual_near_term_floor_restore(
        context, _features(), 18+lead, lead, adjustment, 31560.3, 31560.3+adjustment,
    ) is None
