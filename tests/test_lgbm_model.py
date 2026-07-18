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
