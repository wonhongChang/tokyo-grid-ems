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


def test_candidate_config_preserves_hourly_contract_and_adds_v14_blocks():
    champion = {
        "forecast": {
            "lag24_residual_ensemble": {"enabled": True, "weight": 0.5},
        },
        "weather_features": {"cooling_base_temp_c": 22.0},
    }
    project = {
        "forecast": {
            "q50_regime_model": {"enabled": True},
            "daily_level_model": {"enabled": True, "weight": 0.25},
            "partial_lag_q50_fallback": {
                "enabled": True,
                "min_observed_lag24_hours": 23,
            },
        }
    }

    result = candidate_config(champion, project)

    assert result["forecast"]["lag24_residual_ensemble"] == {
        "enabled": True,
        "weight": 0.5,
    }
    assert result["forecast"]["q50_regime_model"] == {"enabled": True}
    assert result["forecast"]["daily_level_model"]["weight"] == 0.25
    assert (
        result["forecast"]["partial_lag_q50_fallback"]
        ["min_observed_lag24_hours"]
        == 23
    )
    assert champion["forecast"].keys() == {"lag24_residual_ensemble"}


def test_hourly_estimator_fingerprints_cover_the_preserved_boosters() -> None:
    forecaster = type("Forecaster", (), {})()
    forecaster.model_q025 = _FakeEstimator("q025")
    forecaster.model_q50 = _FakeEstimator("q50")
    forecaster.model_q975 = _FakeEstimator("q975")
    forecaster.model_q50_lag24_residual = _FakeEstimator("residual")

    fingerprints = hourly_estimator_fingerprints(forecaster)

    assert set(fingerprints) == {
        "model_q025",
        "model_q50",
        "model_q975",
        "model_q50_lag24_residual",
    }
    assert len(set(fingerprints.values())) == 4
