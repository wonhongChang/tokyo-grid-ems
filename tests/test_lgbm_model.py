"""Tests for python/forecast/lgbm_model.py."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

lightgbm = pytest.importorskip("lightgbm", reason="lightgbm not installed")
joblib   = pytest.importorskip("joblib",   reason="joblib not installed")

from python.forecast.lgbm_model import LGBMForecaster

JST = ZoneInfo("Asia/Tokyo")


def _make_cache(n_days: int = 120, base: str = "2023-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    start = pd.Timestamp(base, tz=JST)
    n = n_days * 24
    hours = np.arange(n)
    timestamps = pd.date_range(start, periods=n, freq="h")
    actual_mw = (
        20_000
        + 2_000 * np.sin(np.pi * hours / 12)
        + rng.normal(0, 200, n)
    )
    temp_c = (
        18.0
        + 10.0 * np.sin(2 * np.pi * (hours / 24 - 90) / 365)
        + 3.0  * np.sin(np.pi * hours / 12)
        + rng.normal(0, 1.0, n)
    )
    return pd.DataFrame({
        "ts":         timestamps,
        "actual_mw":  actual_mw,
        "forecast_mw": actual_mw,
        "usage_pct":  actual_mw / 250,
        "supply_mw":  np.full(n, 25_000.0),
        "temp_c":     temp_c,
    })


@pytest.fixture(scope="module")
def fitted_forecaster() -> LGBMForecaster:
    f = LGBMForecaster(n_estimators=50, learning_rate=0.1)
    f.fit(_make_cache(120))
    return f


@pytest.fixture(scope="module")
def big_cache() -> pd.DataFrame:
    return _make_cache(120)


# ---------------------------------------------------------------------------
# Fit guard
# ---------------------------------------------------------------------------

def test_fit_raises_when_too_little_data():
    f = LGBMForecaster(n_estimators=10)
    with pytest.raises(ValueError, match="90 days"):
        f.fit(_make_cache(30))


def test_fit_succeeds_at_minimum_threshold():
    # lag_336h drops ~14 days, so raw cache needs ~105 days to yield >= 90*24 training rows
    f = LGBMForecaster(n_estimators=10, learning_rate=0.1)
    f.fit(_make_cache(105))
    assert f.model_q50 is not None
    assert f.model_q025 is not None
    assert f.model_q975 is not None
    assert f.model_q50_lag24_residual is not None
    assert f.is_compatible()


def test_fit_keeps_source_sensitive_features_out_of_non_business_q50_only():
    excluded_feature = "humidity_delta_24h"
    config = {
        "forecast": {
            "q50_regime_model": {
                "enabled": True,
                "min_non_business_training_rows": 336,
                "weight": 0.5,
                "excluded_features": [excluded_feature],
            }
        }
    }
    f = LGBMForecaster(
        n_estimators=10,
        learning_rate=0.1,
        config=config,
    )

    f.fit(_make_cache(105))

    assert excluded_feature in f.model_q50.feature_name_
    assert excluded_feature in f.model_q50_lag24_residual.feature_name_
    assert excluded_feature not in f.model_q50_non_business.feature_name_
    assert (
        f.q50_non_business_feature_columns
        == f.model_q50_non_business.feature_name_
    )
    assert f.is_compatible()


def test_fit_rejects_unknown_non_business_feature_exclusion():
    f = LGBMForecaster(
        n_estimators=10,
        config={
            "forecast": {
                "q50_regime_model": {
                    "enabled": True,
                    "excluded_features": ["not_a_real_feature"],
                }
            }
        },
    )

    with pytest.raises(ValueError, match="unknown non-business q50 exclusions"):
        f.fit(_make_cache(105))


def test_fit_builds_source_robust_q50_feature_views():
    f = LGBMForecaster(
        n_estimators=10,
        learning_rate=0.1,
        config={
            "forecast": {
                "q50_regime_model": {
                    "enabled": True,
                    "min_non_business_training_rows": 336,
                    "excluded_features": ["humidity_delta_24h"],
                },
                "q50_feature_view_ensemble": {"enabled": True},
            }
        },
    )

    f.fit(_make_cache(105))

    assert set(f.q50_feature_views) == {
        "no_humidity_delta",
        "source_robust",
    }
    assert "humidity_delta_24h" not in (
        f.q50_feature_views["no_humidity_delta"]["feature_columns"]
    )
    assert "temp_delta_1h" not in (
        f.q50_feature_views["source_robust"]["feature_columns"]
    )
    assert f.is_compatible()


def test_fit_builds_lag_unavailable_q50_without_unfinalized_inputs():
    f = LGBMForecaster(
        n_estimators=10,
        learning_rate=0.1,
        config={
            "forecast": {
                "q50_regime_model": {
                    "min_non_business_training_rows": 336,
                },
                "partial_lag_q50_fallback": {
                    "lag_unavailable_models_enabled": True,
                    "lag_unavailable_non_business_weight": 0.5,
                },
            }
        },
    )

    f.fit(_make_cache(105))

    assert f.model_q50_lag_unavailable is not None
    assert f.model_q50_lag_unavailable_non_business is not None
    assert {
        "lag_24h",
        "lag_last_biz_hour",
        "lag_last_nonhol_hour",
        "lag_24h_to_last_biz_gap",
        "lag_24h_to_same_business_type_gap",
        "lag_24h_gap_x_business_hour",
    }.isdisjoint(f.lag_unavailable_feature_columns)
    assert {
        "humidity_pct",
        "discomfort_index",
        "apparent_temp_c",
        "temp_delta_1h",
        "cooling_degree_3h_mean",
    }.isdisjoint(f.lag_unavailable_feature_columns)
    assert f.is_compatible()


def test_lag_unavailable_q50_replaces_only_rows_with_missing_context():
    class FakeModel:
        def __init__(self, values):
            self.values = np.asarray(values, dtype=float)

        def predict(self, _features):
            return self.values

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "partial_lag_q50_fallback": {
                "lag_unavailable_models_enabled": True,
                "lag_unavailable_non_business_weight": 0.5,
            }
        }
    }
    f.model_q50_lag_unavailable = FakeModel([100.0, 200.0, 300.0])
    f.model_q50_lag_unavailable_non_business = FakeModel(
        [110.0, 240.0, 360.0]
    )
    f.lag_unavailable_feature_columns = ["hour", "is_non_business_day"]
    features = pd.DataFrame({
        "hour": [0, 1, 2],
        "is_non_business_day": [0.0, 1.0, 1.0],
        "lag_24h": [30_000.0, np.nan, 31_000.0],
        "lag_last_biz_hour": [30_000.0, 30_000.0, np.nan],
        "lag_last_nonhol_hour": [30_000.0, 30_000.0, 30_000.0],
    })

    unavailable, values = f._lag_unavailable_q50(features)

    assert unavailable.tolist() == [False, True, True]
    assert values == pytest.approx([100.0, 220.0, 330.0])


def test_feature_view_q50_uses_business_and_non_business_weights(monkeypatch):
    f = LGBMForecaster(
        config={
            "forecast": {
                "q50_feature_view_ensemble": {
                    "enabled": True,
                    "no_humidity_delta_share": 0.35,
                    "non_business_full_share": 0.40,
                }
            }
        }
    )
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    first = {"name": "a"}
    second = {"name": "c"}
    f.q50_feature_views = {
        "no_humidity_delta": first,
        "source_robust": second,
    }
    monkeypatch.setattr(
        f,
        "_predict_q50_feature_view",
        lambda view, _features, *, use_lag_residual: np.full(
            2,
            200.0 if view is first else 300.0,
        ),
    )
    features = pd.DataFrame({"is_non_business_day": [0.0, 1.0]})

    result = f._feature_view_q50(
        features,
        np.full(2, 100.0),
        partial_lag_fallback=False,
    )

    assert result == pytest.approx([265.0, 199.0])


def test_feature_view_q50_uses_direct_views_on_partial_lag(monkeypatch):
    f = LGBMForecaster(
        config={
            "forecast": {
                "q50_feature_view_ensemble": {
                    "enabled": True,
                    "no_humidity_delta_share": 0.25,
                    "non_business_full_share": 0.50,
                },
            }
        }
    )
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    first = {"name": "a"}
    second = {"name": "c"}
    f.q50_feature_views = {
        "no_humidity_delta": first,
        "source_robust": second,
    }
    calls = []

    def _predict(view, _features, *, use_lag_residual):
        calls.append(use_lag_residual)
        return np.full(2, 200.0 if view is first else 300.0)

    monkeypatch.setattr(f, "_predict_q50_feature_view", _predict)

    result = f._feature_view_q50(
        pd.DataFrame({"is_non_business_day": [0.0, 1.0]}),
        np.asarray([123.0, 456.0]),
        partial_lag_fallback=True,
    )

    assert result == pytest.approx([275.0, 365.5])
    assert calls == [False, False]


def test_feature_view_q50_caps_divergence_from_legacy_anchor(monkeypatch):
    f = LGBMForecaster(
        config={
            "forecast": {
                "q50_feature_view_ensemble": {
                    "enabled": True,
                    "no_humidity_delta_share": 0.5,
                    "non_business_full_share": 0.5,
                    "max_abs_delta_from_legacy_mw": 50.0,
                }
            }
        }
    )
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.q50_feature_views = {
        "no_humidity_delta": {"name": "a"},
        "source_robust": {"name": "c"},
    }
    monkeypatch.setattr(
        f,
        "_predict_q50_feature_view",
        lambda _view, _features, *, use_lag_residual: np.full(2, 300.0),
    )

    result = f._feature_view_q50(
        pd.DataFrame({"is_non_business_day": [0.0, 1.0]}),
        np.asarray([100.0, 100.0]),
        partial_lag_fallback=False,
    )

    assert result == pytest.approx([150.0, 125.0])


def test_fit_builds_v14_daily_level_model_when_enabled():
    f = LGBMForecaster(
        n_estimators=10,
        learning_rate=0.1,
        config={
            "forecast": {
                "daily_level_model": {
                    "enabled": True,
                    "training_window_days": 90,
                    "n_estimators": 10,
                    "learning_rate": 0.1,
                }
            }
        },
    )

    f.fit(_make_cache(105))

    assert f.model_q50_daily_level is not None
    assert f.q50_daily_level_feature_columns
    assert f.daily_level_training_days == 90
    assert f.is_compatible()


# ---------------------------------------------------------------------------
# predict — structure
# ---------------------------------------------------------------------------

def test_predict_returns_24_hourly_forecasts(fitted_forecaster, big_cache):
    result = fitted_forecaster.predict(date(2023, 5, 1), big_cache)
    assert len(result) == 24


def test_predict_ts_in_jst(fitted_forecaster, big_cache):
    result = fitted_forecaster.predict(date(2023, 5, 1), big_cache)
    for f in result:
        assert f.ts.endswith("+09:00")


def test_predict_ts_spans_all_hours(fitted_forecaster, big_cache):
    result = fitted_forecaster.predict(date(2023, 5, 1), big_cache)
    assert [pd.Timestamp(f.ts).hour for f in result] == list(range(24))


def test_predict_raises_before_fit():
    f = LGBMForecaster.__new__(LGBMForecaster)
    f.model_q025 = f.model_q50 = f.model_q975 = None
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    with pytest.raises(RuntimeError, match="fit\\(\\)"):
        f.predict(date(2023, 5, 1), _make_cache(120))


# ---------------------------------------------------------------------------
# predict — quantile ordering
# ---------------------------------------------------------------------------

def test_q025_lte_q50(fitted_forecaster, big_cache):
    for f in fitted_forecaster.predict(date(2023, 5, 1), big_cache):
        assert f.p95_lower_mw <= f.forecast_mw + 1.0


def test_q50_lte_q975(fitted_forecaster, big_cache):
    for f in fitted_forecaster.predict(date(2023, 5, 1), big_cache):
        assert f.forecast_mw <= f.p95_upper_mw + 1.0


def test_forecast_mw_positive(fitted_forecaster, big_cache):
    for f in fitted_forecaster.predict(date(2023, 5, 1), big_cache):
        assert f.forecast_mw > 0


def test_p99_wider_than_p95(fitted_forecaster, big_cache):
    for f in fitted_forecaster.predict(date(2023, 5, 1), big_cache):
        assert f.p99_lower_mw <= f.p95_lower_mw
        assert f.p99_upper_mw >= f.p95_upper_mw


def test_p99_expansion_doubles_half_width(fitted_forecaster, big_cache):
    for f in fitted_forecaster.predict(date(2023, 5, 1), big_cache):
        half_lo = max(0.0, f.forecast_mw - f.p95_lower_mw)
        half_hi = max(0.0, f.p95_upper_mw - f.forecast_mw)
        assert f.p99_lower_mw == pytest.approx(f.p95_lower_mw - half_lo, abs=0.2)
        assert f.p99_upper_mw == pytest.approx(f.p95_upper_mw + half_hi, abs=0.2)


def test_predict_normalizes_crossed_quantiles(monkeypatch):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _x):
            return np.full(24, self.value)

    import python.forecast.lgbm_model as mod
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({"hour": range(24)}),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = FakeModel(30_000.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(31_000.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    for point in result:
        assert point.p95_lower_mw <= point.forecast_mw <= point.p95_upper_mw
        assert point.p95_lower_mw == 30_000.0
        assert point.forecast_mw == 32_000.0
        assert point.p95_upper_mw == 32_500.0
        assert point.p99_upper_mw == 33_000.0


def test_predict_applies_minimum_interval_half_width(monkeypatch):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _x):
            return np.full(24, self.value)

    import python.forecast.lgbm_model as mod
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({"hour": range(24)}),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {"interval_calibration": {"min_p95_half_width_mw": 500.0}}
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = FakeModel(31_900.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(32_050.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    for point in result:
        assert point.p95_lower_mw == 31_500.0
        assert point.p95_upper_mw == 32_500.0
        assert point.p99_lower_mw == 31_000.0
        assert point.p99_upper_mw == 33_000.0


def test_interval_half_width_scale_applies_after_sanity_calibration():
    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "interval_calibration": {
            "min_p95_half_width_mw": 500.0,
            "max_p95_half_width_mw": 3_000.0,
            "p95_half_width_scale": 1.25,
        }
    }

    assert f._calibrate_interval_half_widths(100.0, 4_000.0) == (
        625.0,
        3_750.0,
    )


def test_predict_does_not_mirror_one_sided_interval_by_default(monkeypatch):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _x):
            return np.full(24, self.value)

    import python.forecast.lgbm_model as mod
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({"hour": range(24)}),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {"interval_calibration": {"min_p95_half_width_mw": 500.0}}
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = FakeModel(31_900.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(36_000.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    for point in result:
        assert point.p95_lower_mw == 31_500.0
        assert point.p95_upper_mw == 36_000.0
        assert point.p99_lower_mw == 31_000.0
        assert point.p99_upper_mw == 40_000.0


def test_predict_caps_extreme_one_sided_interval_when_configured(monkeypatch):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _x):
            return np.full(24, self.value)

    import python.forecast.lgbm_model as mod
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({"hour": range(24)}),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "interval_calibration": {
            "min_p95_half_width_mw": 500.0,
            "max_p95_half_width_mw": 3_000.0,
            "max_p95_asymmetry_ratio": 2.5,
            "asymmetry_reference_half_width_mw": 900.0,
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = FakeModel(30_200.0)
    f.model_q50 = FakeModel(31_000.0)
    f.model_q975 = FakeModel(37_200.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    for point in result:
        assert point.p95_lower_mw == 30_200.0
        assert point.p95_upper_mw == 33_250.0
        assert point.p99_lower_mw == 29_400.0
        assert point.p99_upper_mw == 35_500.0


def test_predict_can_mirror_collapsed_side_when_configured(monkeypatch):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _x):
            return np.full(24, self.value)

    import python.forecast.lgbm_model as mod
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({"hour": range(24)}),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "interval_calibration": {
            "min_p95_half_width_mw": 500.0,
            "mirror_collapsed_side": True,
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = FakeModel(31_900.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(36_000.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    for point in result:
        assert point.p95_lower_mw == 28_000.0
        assert point.p95_upper_mw == 36_000.0
        assert point.p99_lower_mw == 24_000.0
        assert point.p99_upper_mw == 40_000.0


def test_old_q10_q90_pickle_layout_is_incompatible():
    f = LGBMForecaster.__new__(LGBMForecaster)
    f.model_q10 = object()
    f.model_q50 = object()
    f.model_q90 = object()

    assert not f.is_compatible()


def test_old_feature_version_is_incompatible():
    f = LGBMForecaster.__new__(LGBMForecaster)
    f.interval_version = "q025_q50_q975_p95_v1"
    f.model_q025 = object()
    f.model_q50 = object()
    f.model_q975 = object()

    assert not f.is_compatible()


def test_enabled_lag24_residual_ensemble_requires_residual_model():
    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "lag24_residual_ensemble": {"enabled": True},
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = object()
    f.model_q50 = object()
    f.model_q975 = object()
    f.model_q50_lag24_residual = None

    assert not f.is_compatible()


def test_enabled_q50_regime_requires_feature_contract_and_non_business_model():
    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "q50_regime_model": {
                "enabled": True,
                "weight": 1.0,
            },
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = object()
    f.model_q50 = object()
    f.model_q975 = object()
    f.q50_non_business_feature_columns = ["hour"]
    f.model_q50_non_business = None

    assert not f.is_compatible()

    f.model_q50_non_business = object()
    assert f.is_compatible()


def test_v14_daily_level_contract_requires_model_and_feature_columns():
    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "daily_level_model": {"enabled": True},
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = object()
    f.model_q50 = object()
    f.model_q975 = object()
    f.model_q50_daily_level = None
    f.q50_daily_level_feature_columns = ["lag_24h__mean"]

    assert not f.is_compatible()

    f.model_q50_daily_level = object()
    assert f.is_compatible()


def test_legacy_v11_model_remains_compatible_without_regime_artifacts():
    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "q50_regime_model": {"enabled": True},
        }
    }
    f.interval_version = "q025_q50_q975_p95_v11_lag24_residual_ensemble"
    f.model_q025 = object()
    f.model_q50 = object()
    f.model_q975 = object()

    assert f.is_compatible()


def test_legacy_v12_model_keeps_regime_artifact_contract():
    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "q50_regime_model": {"enabled": True},
        }
    }
    f.interval_version = "q025_q50_q975_p95_v12_regime_q50"
    f.model_q025 = object()
    f.model_q50 = object()
    f.model_q975 = object()
    f.q50_non_business_feature_columns = ["hour"]
    f.model_q50_non_business = object()

    assert f.is_compatible()

    f.model_q50_non_business = None
    assert not f.is_compatible()


def test_legacy_v13_model_remains_compatible_without_daily_level_artifact():
    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "q50_regime_model": {"enabled": True},
            "daily_level_model": {"enabled": True},
        }
    }
    f.interval_version = "q025_q50_q975_p95_v13_transition_cooling_blend"
    f.model_q025 = object()
    f.model_q50 = object()
    f.model_q975 = object()
    f.q50_non_business_feature_columns = ["hour"]
    f.model_q50_non_business = object()

    assert f.is_compatible()


@pytest.mark.parametrize(
    ("is_non_business_day", "business_day_only", "weight", "expected_mid"),
    [
        (0, True, 0.5, 30_500.0),
        (1, True, 0.5, 32_000.0),
        (1, False, 0.5, 30_500.0),
        (0, True, 2.0, 29_000.0),
        (0, True, -1.0, 32_000.0),
    ],
)
def test_predict_blends_lag24_residual_q50_and_recenters_interval(
    monkeypatch,
    is_non_business_day,
    business_day_only,
    weight,
    expected_mid,
):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _x):
            return np.full(24, self.value)

    import python.forecast.lgbm_model as mod
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({
            "hour": range(24),
            "lag_24h": np.full(24, 30_000.0),
            "is_non_business_day": np.full(24, is_non_business_day),
        }),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "lag24_residual_ensemble": {
                "enabled": True,
                "business_day_only": business_day_only,
                "weight": weight,
            }
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = FakeModel(31_000.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(33_000.0)
    f.model_q50_lag24_residual = FakeModel(-1_000.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    for point in result:
        assert point.forecast_mw == expected_mid
        assert point.p95_lower_mw == expected_mid - 1_000.0
        assert point.p95_upper_mw == expected_mid + 1_000.0


def test_predict_uses_base_q50_when_lag24_is_missing(monkeypatch):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _x):
            return np.full(24, self.value)

    import python.forecast.lgbm_model as mod
    lag24 = np.full(24, 30_000.0)
    lag24[5] = np.nan
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({
            "hour": range(24),
            "lag_24h": lag24,
            "is_non_business_day": np.zeros(24),
        }),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "lag24_residual_ensemble": {
                "enabled": True,
                "business_day_only": True,
                "weight": 0.5,
            }
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = FakeModel(31_000.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(33_000.0)
    f.model_q50_lag24_residual = FakeModel(-1_000.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    assert result[4].forecast_mw == 30_500.0
    assert result[5].forecast_mw == 32_000.0


def test_predict_blends_dedicated_q50_only_for_non_business_rows(monkeypatch):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _x):
            return np.full(24, self.value)

    import python.forecast.lgbm_model as mod
    non_business = np.zeros(24)
    non_business[12:] = 1
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({
            "hour": range(24),
            "is_non_business_day": non_business,
        }),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "q50_regime_model": {"enabled": True},
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.q50_non_business_feature_columns = ["hour", "is_non_business_day"]
    f.model_q025 = FakeModel(29_000.0)
    f.model_q50 = FakeModel(31_000.0)
    f.model_q975 = FakeModel(34_000.0)
    f.model_q50_non_business = FakeModel(32_000.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    assert result[11].forecast_mw == 31_000.0
    assert result[12].forecast_mw == 31_500.0


def test_predict_skips_lag24_blend_across_business_type_transition(monkeypatch):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _x):
            return np.full(24, self.value)

    import python.forecast.lgbm_model as mod
    mismatch = np.zeros(24)
    mismatch[12:] = 1
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({
            "hour": range(24),
            "lag_24h": np.full(24, 30_000.0),
            "is_non_business_day": np.zeros(24),
            "lag_24h_business_type_mismatch": mismatch,
        }),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "lag24_residual_ensemble": {
                "enabled": True,
                "business_day_only": True,
                "same_business_type_only": True,
                "weight": 0.5,
            }
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = FakeModel(29_000.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(34_000.0)
    f.model_q50_lag24_residual = FakeModel(-1_000.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    assert result[11].forecast_mw == 30_500.0
    assert result[12].forecast_mw == 32_000.0


def test_predict_attenuates_transition_residual_blend_on_cooler_business_day(
    monkeypatch,
):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _x):
            return np.full(24, self.value)

    import python.forecast.lgbm_model as mod
    mismatch = np.ones(24)
    mismatch[4] = 0
    non_business = np.zeros(24)
    non_business[5] = 1
    cooling_delta = np.zeros(24)
    cooling_delta[:6] = [-4.0, -2.0, 0.0, 2.0, -4.0, -4.0]
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({
            "hour": range(24),
            "lag_24h": np.full(24, 30_000.0),
            "is_non_business_day": non_business,
            "lag_24h_business_type_mismatch": mismatch,
            "cooling_delta_24h": cooling_delta,
        }),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "lag24_residual_ensemble": {
                "enabled": True,
                "business_day_only": True,
                "weight": 0.5,
                "transition_cooling_attenuation": {
                    "enabled": True,
                    "zero_weight_delta_c": -4.0,
                    "full_weight_delta_c": 0.0,
                },
            }
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = FakeModel(31_000.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(33_000.0)
    f.model_q50_lag24_residual = FakeModel(-1_000.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    assert result[0].forecast_mw == 32_000.0
    assert result[1].forecast_mw == 31_250.0
    assert result[2].forecast_mw == 30_500.0
    assert result[3].forecast_mw == 30_500.0
    assert result[4].forecast_mw == 30_500.0
    assert result[5].forecast_mw == 32_000.0


def test_legacy_v12_does_not_apply_v13_transition_attenuation(monkeypatch):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _x):
            return np.full(24, self.value)

    import python.forecast.lgbm_model as mod
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({
            "hour": range(24),
            "lag_24h": np.full(24, 30_000.0),
            "is_non_business_day": np.zeros(24),
            "lag_24h_business_type_mismatch": np.ones(24),
            "cooling_delta_24h": np.full(24, -4.0),
        }),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "lag24_residual_ensemble": {
                "enabled": True,
                "business_day_only": True,
                "weight": 0.5,
                "transition_cooling_attenuation": {"enabled": True},
            },
            "q50_regime_model": {"enabled": False},
        }
    }
    f.interval_version = "q025_q50_q975_p95_v12_regime_q50"
    f.model_q025 = FakeModel(31_000.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(33_000.0)
    f.model_q50_lag24_residual = FakeModel(-1_000.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    assert all(point.forecast_mw == 30_500.0 for point in result)


def test_v14_daily_level_model_recenters_q50_with_a_bounded_adjustment(
    monkeypatch,
):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, x):
            return np.full(len(x), self.value)

    import python.forecast.lgbm_model as mod
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({
            "hour": range(24),
        }),
    )
    monkeypatch.setattr(
        mod,
        "build_daily_level_features",
        lambda _features: (pd.DataFrame({"daily": [1.0]}), [0]),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "daily_level_model": {
                "enabled": True,
                "weight": 0.25,
                "max_abs_adjustment_mw": 750,
            },
            "partial_lag_q50_fallback": {"enabled": False},
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = FakeModel(31_000.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(33_000.0)
    f.model_q50_daily_level = FakeModel(40_000.0)
    f.q50_daily_level_feature_columns = ["daily"]

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    assert all(point.forecast_mw == 32_750.0 for point in result)
    assert all(point.p95_lower_mw == 31_750.0 for point in result)
    assert all(point.p95_upper_mw == 33_750.0 for point in result)


@pytest.mark.parametrize(
    ("valid_lag_hours", "expected_forecast"),
    [(12, 32_000.0), (24, 30_750.0)],
)
def test_v14_partial_lag_fallback_uses_v11_q50_until_lag_is_complete(
    monkeypatch,
    valid_lag_hours,
    expected_forecast,
):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, x):
            return np.full(len(x), self.value)

    import python.forecast.lgbm_model as mod
    lag24 = np.full(24, np.nan)
    lag24[:valid_lag_hours] = 30_000.0
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({
            "hour": range(24),
            "lag_24h": lag24,
            "is_non_business_day": np.ones(24),
        }),
    )
    monkeypatch.setattr(
        mod,
        "build_daily_level_features",
        lambda _features: (pd.DataFrame({"daily": [1.0]}), [0]),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "lag24_residual_ensemble": {
                "enabled": True,
                "business_day_only": True,
                "weight": 0.5,
            },
            "q50_regime_model": {"enabled": True, "weight": 0.5},
            "daily_level_model": {
                "enabled": True,
                "weight": 0.25,
                "max_abs_adjustment_mw": 750,
            },
            "partial_lag_q50_fallback": {
                "enabled": True,
                "min_valid_lag24_hours": 24,
            },
        }
    }
    f.interval_version = LGBMForecaster.INTERVAL_VERSION
    f.model_q025 = FakeModel(31_000.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(33_000.0)
    f.model_q50_lag24_residual = FakeModel(0.0)
    f.model_q50_non_business = FakeModel(28_000.0)
    f.q50_non_business_feature_columns = ["hour"]
    f.model_q50_daily_level = FakeModel(40_000.0)
    f.q50_daily_level_feature_columns = ["daily"]

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    assert all(point.forecast_mw == expected_forecast for point in result)


@pytest.mark.parametrize(
    ("observed_hours", "fallback_active"),
    [(22, True), (23, False), (24, False)],
)
def test_v14_partial_lag_fallback_uses_observed_source_coverage(
    observed_hours,
    fallback_active,
):
    target = date(2026, 8, 21)
    timestamps = pd.date_range(
        "2026-08-20 00:00:00+09:00",
        periods=24,
        freq="h",
    )
    sources = np.full(24, "tepco_forecast_fallback", dtype=object)
    sources[:observed_hours] = "observed"
    cache = pd.DataFrame({
        "ts": timestamps,
        "actual_mw": np.full(24, 30_000.0),
        "actual_source": sources,
    })
    features = pd.DataFrame({"lag_24h": np.full(24, 30_000.0)})
    forecaster = LGBMForecaster.__new__(LGBMForecaster)
    forecaster.interval_version = LGBMForecaster.INTERVAL_VERSION
    forecaster.config = {
        "forecast": {
            "partial_lag_q50_fallback": {
                "enabled": True,
                "min_valid_lag24_hours": 24,
                "min_observed_lag24_hours": 23,
            }
        }
    }

    assert forecaster._partial_lag_fallback_active(
        features,
        cache=cache,
        target_date=target,
    ) is fallback_active


def test_v14_partial_lag_fallback_rejects_non_final_missing_actual_hour():
    target = date(2026, 8, 21)
    timestamps = pd.date_range(
        "2026-08-20 00:00:00+09:00",
        periods=24,
        freq="h",
    )
    sources = np.full(24, "observed", dtype=object)
    sources[12] = "tepco_forecast_fallback"
    cache = pd.DataFrame({
        "ts": timestamps,
        "actual_mw": np.full(24, 30_000.0),
        "actual_source": sources,
    })
    features = pd.DataFrame({"lag_24h": np.full(24, 30_000.0)})
    forecaster = LGBMForecaster.__new__(LGBMForecaster)
    forecaster.interval_version = LGBMForecaster.INTERVAL_VERSION
    forecaster.config = {
        "forecast": {
            "partial_lag_q50_fallback": {
                "enabled": True,
                "min_valid_lag24_hours": 24,
                "min_observed_lag24_hours": 23,
            }
        }
    }

    assert forecaster._partial_lag_fallback_active(
        features,
        cache=cache,
        target_date=target,
    ) is True


def test_legacy_v13_does_not_apply_v14_daily_level_adjustment(monkeypatch):
    class FakeModel:
        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, x):
            return np.full(len(x), self.value)

    import python.forecast.lgbm_model as mod
    monkeypatch.setattr(
        mod,
        "build_inference_features",
        lambda _cache, _target_date, _config=None: pd.DataFrame({
            "hour": range(24),
        }),
    )

    f = LGBMForecaster.__new__(LGBMForecaster)
    f.config = {
        "forecast": {
            "daily_level_model": {"enabled": True},
        }
    }
    f.interval_version = "q025_q50_q975_p95_v13_transition_cooling_blend"
    f.model_q025 = FakeModel(31_000.0)
    f.model_q50 = FakeModel(32_000.0)
    f.model_q975 = FakeModel(33_000.0)

    result = f.predict(date(2023, 5, 1), pd.DataFrame())

    assert all(point.forecast_mw == 32_000.0 for point in result)


# ---------------------------------------------------------------------------
# save / load roundtrip
# ---------------------------------------------------------------------------

def test_save_load_roundtrip(fitted_forecaster, big_cache):
    target = date(2023, 5, 1)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "model.pkl"
        fitted_forecaster.save(path)
        loaded = LGBMForecaster.load(path)

    for o, r in zip(
        fitted_forecaster.predict(target, big_cache),
        loaded.predict(target, big_cache),
    ):
        assert o.forecast_mw  == pytest.approx(r.forecast_mw,  abs=0.1)
        assert o.p95_lower_mw == pytest.approx(r.p95_lower_mw, abs=0.1)
        assert o.p95_upper_mw == pytest.approx(r.p95_upper_mw, abs=0.1)


def test_save_creates_parent_dir(fitted_forecaster):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "subdir" / "model.pkl"
        fitted_forecaster.save(path)
        assert path.exists()


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

def test_import_error_without_lightgbm(monkeypatch):
    import python.forecast.lgbm_model as mod
    monkeypatch.setattr(mod, "_HAS_LGBM", False)
    with pytest.raises(ImportError, match="lightgbm"):
        LGBMForecaster()
