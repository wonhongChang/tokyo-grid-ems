from __future__ import annotations

from python.eval.build_v14_candidate import (
    candidate_config,
    hourly_estimator_fingerprints,
)


class _FakeBooster:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def model_to_string(self) -> str:
        return self.payload


class _FakeEstimator:
    def __init__(self, payload: str) -> None:
        self.booster_ = _FakeBooster(payload)


def test_candidate_config_uses_complete_v14_r2_project_contract():
    champion = {
        "forecast": {
            "lag24_residual_ensemble": {"enabled": True, "weight": 0.5},
        },
        "weather_features": {"cooling_base_temp_c": 22.0},
    }
    project = {
        "forecast": {
            "lag24_residual_ensemble": {"enabled": True, "weight": 0.5},
            "q50_regime_model": {"enabled": True},
            "q50_feature_view_ensemble": {
                "enabled": True,
                "no_humidity_delta_share": 0.35,
            },
            "same_regime_day_level_calibration": {"enabled": True},
            "daily_level_model": {"enabled": False},
            "partial_lag_q50_fallback": {
                "enabled": True,
                "min_observed_lag24_hours": 23,
            },
        }
    }

    result = candidate_config(champion, project)

    assert result["forecast"]["lag24_residual_ensemble"]["weight"] == 0.5
    assert result["forecast"]["q50_regime_model"] == {"enabled": True}
    assert result["forecast"]["q50_feature_view_ensemble"][
        "no_humidity_delta_share"
    ] == 0.35
    assert result["forecast"]["daily_level_model"]["enabled"] is False
    assert (
        result["forecast"]["partial_lag_q50_fallback"]
        ["min_observed_lag24_hours"]
        == 23
    )
    assert champion["forecast"].keys() == {"lag24_residual_ensemble"}


def test_candidate_config_rejects_uniform_daily_level_shift():
    project = {
        "forecast": {
            "lag24_residual_ensemble": {},
            "q50_regime_model": {},
            "q50_feature_view_ensemble": {"enabled": True},
            "same_regime_day_level_calibration": {"enabled": True},
            "daily_level_model": {"enabled": True},
            "partial_lag_q50_fallback": {},
        }
    }

    import pytest

    with pytest.raises(ValueError, match="daily_level_model.enabled=false"):
        candidate_config({}, project)


def test_hourly_estimator_fingerprints_cover_the_preserved_boosters() -> None:
    forecaster = type("Forecaster", (), {})()
    forecaster.model_q025 = _FakeEstimator("q025")
    forecaster.model_q50 = _FakeEstimator("q50")
    forecaster.model_q975 = _FakeEstimator("q975")
    forecaster.model_q50_lag24_residual = _FakeEstimator("residual")
    forecaster.model_q50_lag_unavailable = _FakeEstimator("lag-unavailable")
    forecaster.model_q50_lag_unavailable_non_business = _FakeEstimator(
        "lag-unavailable-non-business"
    )

    fingerprints = hourly_estimator_fingerprints(forecaster)

    assert set(fingerprints) == {
        "model_q025",
        "model_q50",
        "model_q975",
        "model_q50_lag24_residual",
        "model_q50_lag_unavailable",
        "model_q50_lag_unavailable_non_business",
    }
    assert len(set(fingerprints.values())) == 6
