"""Tests for python/forecast/feature_builder.py."""
from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from python.forecast.feature_builder import (
    FEATURE_COLS,
    _consec_holiday_len,
    _days_since_holiday_end,
    _ensure_tz,
    _last_biz_day,
    _major_holiday_season,
    build_inference_features,
    build_training_features,
)

JST = ZoneInfo("Asia/Tokyo")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_cache(n_days: int = 200, base: str = "2024-01-01") -> pd.DataFrame:
    """Synthetic hourly cache with realistic temp_c."""
    rng = np.random.default_rng(0)
    start = pd.Timestamp(base, tz=JST)
    n = n_days * 24
    timestamps = pd.date_range(start, periods=n, freq="h")
    hours = np.arange(n)
    actual_mw = (
        20_000
        + 2_000 * np.sin(np.pi * hours / 12)
        + rng.normal(0, 100, n)
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


# ---------------------------------------------------------------------------
# _ensure_tz
# ---------------------------------------------------------------------------

def test_ensure_tz_localizes_naive():
    df = pd.DataFrame({"ts": pd.to_datetime(["2024-01-01", "2024-01-02"])})
    out = _ensure_tz(df)
    assert out["ts"].dt.tz is not None
    assert str(out["ts"].dt.tz) == "Asia/Tokyo"


def test_ensure_tz_leaves_aware_unchanged():
    df = pd.DataFrame({"ts": pd.to_datetime(["2024-01-01", "2024-01-02"]).tz_localize("UTC")})
    out = _ensure_tz(df)
    assert out["ts"].dt.tz is not None


# ---------------------------------------------------------------------------
# build_training_features — shape and completeness
# ---------------------------------------------------------------------------

def test_returns_correct_columns():
    cache = _make_cache(200)
    X, y = build_training_features(cache)
    assert list(X.columns) == FEATURE_COLS


def test_no_nan_in_features():
    cache = _make_cache(200)
    X, y = build_training_features(cache)
    assert not X.isnull().any().any()
    assert not y.isnull().any()


def test_returns_fewer_rows_than_cache():
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    assert len(X) < len(cache)


def test_x_y_same_length():
    cache = _make_cache(200)
    X, y = build_training_features(cache)
    assert len(X) == len(y)


# ---------------------------------------------------------------------------
# build_training_features — lag feature correctness
# ---------------------------------------------------------------------------

def test_lag_24h_matches_actual_yesterday():
    """lag_24h must equal actual_mw exactly 24 h earlier; use constant-value
    cache so every lag equals the constant regardless of which rows survive dropna."""
    start = pd.Timestamp("2024-01-01", tz=JST)
    n = 400 * 24
    df = pd.DataFrame({
        "ts":        pd.date_range(start, periods=n, freq="h"),
        "actual_mw": np.full(n, 20_000.0),
        "temp_c":    np.full(n, 20.0),
    })
    X, y = build_training_features(df)
    assert np.allclose(X["lag_24h"].values,  20_000.0, atol=1e-3)
    assert np.allclose(X["lag_168h"].values, 20_000.0, atol=1e-3)


def test_lag_features_handle_gaps():
    """Gaps in cache must yield NaN for affected rows (not a wrong neighbour)."""
    cache = _make_cache(100)
    gap_mask = (
        (cache["ts"] >= pd.Timestamp("2024-01-05 10:00", tz=JST)) &
        (cache["ts"] <  pd.Timestamp("2024-01-05 12:00", tz=JST))
    )
    X, y = build_training_features(cache[~gap_mask].copy())
    assert not X.isnull().any().any()


# ---------------------------------------------------------------------------
# build_training_features — rolling stats no-leakage
# ---------------------------------------------------------------------------

def test_rolling_stats_no_self_inclusion():
    """roll_4w_mean must not include the current row (shift(1) required)."""
    cache = _make_cache(200)
    spike_day = pd.Timestamp("2024-07-18", tz=JST)
    cache.loc[cache["ts"].dt.date == spike_day.date(), "actual_mw"] = 99999.0

    X, _ = build_training_features(cache)
    assert X["roll_4w_mean"].max() < 50_000


# ---------------------------------------------------------------------------
# build_training_features — temperature features
# ---------------------------------------------------------------------------

def test_training_has_temp_columns():
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    for col in ["temp_c", "cooling_degree", "heating_degree"]:
        assert col in X.columns


def test_cooling_degree_nonnegative():
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    assert (X["cooling_degree"] >= 0).all()


def test_heating_degree_nonnegative():
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    assert (X["heating_degree"] >= 0).all()


def test_cooling_degree_zero_below_threshold():
    """cooling_degree must be 0 when temp_c <= 22."""
    start = pd.Timestamp("2024-01-01", tz=JST)
    n = 400 * 24
    df = pd.DataFrame({
        "ts":        pd.date_range(start, periods=n, freq="h"),
        "actual_mw": np.full(n, 20_000.0),
        "temp_c":    np.full(n, 15.0),
    })
    X, _ = build_training_features(df)
    assert (X["cooling_degree"] == 0.0).all()


def test_cooling_degree_correct_value():
    """cooling_degree = temp_c - 22 when temp_c > 22."""
    start = pd.Timestamp("2024-01-01", tz=JST)
    n = 400 * 24
    df = pd.DataFrame({
        "ts":        pd.date_range(start, periods=n, freq="h"),
        "actual_mw": np.full(n, 20_000.0),
        "temp_c":    np.full(n, 30.0),
    })
    X, _ = build_training_features(df)
    assert np.allclose(X["cooling_degree"].values, 8.0, atol=1e-6)


def test_cooling_degree_uses_configured_base_temperature():
    """cooling_degree should use the configured balance point, not a hard-coded value."""
    start = pd.Timestamp("2024-01-01", tz=JST)
    n = 400 * 24
    df = pd.DataFrame({
        "ts":        pd.date_range(start, periods=n, freq="h"),
        "actual_mw": np.full(n, 20_000.0),
        "temp_c":    np.full(n, 30.0),
    })
    X, _ = build_training_features(df, {
        "weather_features": {"cooling_base_temp_c": 20.0}
    })
    assert np.allclose(X["cooling_degree"].values, 10.0, atol=1e-6)


def test_training_without_temp_c_drops_rows():
    """Rows without temp_c are excluded from training set."""
    cache = _make_cache(200)
    cache_no_temp = cache.drop(columns=["temp_c"])
    X, _ = build_training_features(cache_no_temp)
    assert len(X) == 0


def test_training_has_temp_anomaly_columns():
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    assert "temp_anomaly_7d"  in X.columns
    assert "temp_anomaly_doy" in X.columns
    assert "temp_delta_168h" in X.columns
    assert "cooling_delta_168h" in X.columns


def test_temp_anomaly_7d_sign_on_hot_spike():
    """On a sudden hot period, temp_anomaly_7d should be positive."""
    cache = _make_cache(200)
    # Replace last 3 days with very high temp (after a cool period)
    cache = cache.copy()
    cache.loc[cache.index[-72:], "temp_c"] = 38.0
    X, _ = build_training_features(cache)
    last_rows = X.tail(72)
    assert (last_rows["temp_anomaly_7d"] > 0).all()


def test_temp_anomaly_doy_zero_mean():
    """temp_anomaly_doy should have mean ~0 (it's a demeaned feature)."""
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    assert abs(X["temp_anomaly_doy"].mean()) < 1.0


# ---------------------------------------------------------------------------
# build_inference_features — shape and structure
# ---------------------------------------------------------------------------

def test_inference_returns_24_rows():
    cache = _make_cache(400)
    out = build_inference_features(cache, date(2025, 1, 10))
    assert len(out) == 24


def test_inference_returns_correct_columns():
    cache = _make_cache(400)
    out = build_inference_features(cache, date(2025, 1, 10))
    assert list(out.columns) == FEATURE_COLS


def test_inference_hour_column_0_to_23():
    cache = _make_cache(400)
    out = build_inference_features(cache, date(2025, 1, 10))
    assert list(out["hour"]) == list(range(24))


def test_inference_is_weekend_saturday():
    cache = _make_cache(400)
    out = build_inference_features(cache, date(2025, 1, 11))  # Saturday
    assert all(out["is_weekend"] == 1)


def test_inference_is_weekend_weekday():
    cache = _make_cache(400)
    out = build_inference_features(cache, date(2025, 1, 13))  # Monday
    assert all(out["is_weekend"] == 0)


def test_inference_lag_24h_correct_value():
    cache = _make_cache(400)
    target = date(2025, 1, 15)
    ts_to_mw = dict(zip(cache["ts"], cache["actual_mw"]))
    out = build_inference_features(cache, target)

    for hour in range(24):
        lag_ts = pd.Timestamp(
            year=target.year, month=target.month, day=target.day,
            hour=hour, tz=JST,
        ) - pd.Timedelta(hours=24)
        expected = ts_to_mw.get(lag_ts, float("nan"))
        got = out["lag_24h"].iloc[hour]
        if not np.isnan(expected):
            assert abs(got - expected) < 1e-3


def test_inference_nan_when_lag_missing():
    cache = _make_cache(10)
    out = build_inference_features(cache, date(2024, 6, 1))
    assert out["lag_24h"].isna().all()
    assert out["lag_168h"].isna().all()


# ---------------------------------------------------------------------------
# build_inference_features — temperature features
# ---------------------------------------------------------------------------

def test_inference_temp_c_from_cache():
    """temp_c in inference output should match the value in cache for target_date."""
    cache = _make_cache(400)
    target = date(2025, 1, 15)

    # Plant a known temp for each hour of target_date
    mask = cache["ts"].dt.date == target
    cache.loc[mask, "temp_c"] = 25.0

    out = build_inference_features(cache, target)
    assert np.allclose(out["temp_c"].values, 25.0, atol=1e-6)


def test_inference_temp_nan_when_not_in_cache():
    """If cache has no temp_c for target_date, inference temp features are NaN."""
    cache = _make_cache(400)
    target = date(2025, 1, 15)

    mask = cache["ts"].dt.date == target
    cache.loc[mask, "temp_c"] = float("nan")

    out = build_inference_features(cache, target)
    assert out["temp_c"].isna().all()
    assert out["cooling_degree"].isna().all()
    assert out["heating_degree"].isna().all()


def test_inference_cooling_degree_correct():
    cache = _make_cache(400)
    target = date(2025, 1, 15)
    cache.loc[cache["ts"].dt.date == target, "temp_c"] = 30.0

    out = build_inference_features(cache, target)
    assert np.allclose(out["cooling_degree"].values, 8.0, atol=1e-6)
    assert np.allclose(out["heating_degree"].values, 0.0, atol=1e-6)


def test_inference_cooling_degree_uses_configured_base_temperature():
    cache = _make_cache(400)
    target = date(2025, 1, 15)
    cache.loc[cache["ts"].dt.date == target, "temp_c"] = 30.0

    out = build_inference_features(cache, target, {
        "weather_features": {"cooling_base_temp_c": 20.0}
    })

    assert np.allclose(out["cooling_degree"].values, 10.0, atol=1e-6)


def test_inference_has_temp_anomaly_columns():
    cache = _make_cache(400)
    out = build_inference_features(cache, date(2025, 1, 15))
    assert "temp_anomaly_7d"  in out.columns
    assert "temp_anomaly_doy" in out.columns
    assert "temp_delta_168h" in out.columns
    assert "cooling_delta_168h" in out.columns


def test_inference_temp_anomaly_7d_positive_on_hot_day():
    """If target_date is much hotter than the past week, anomaly_7d should be positive."""
    # Need ≥600 days so 2025-06-01 and its prior 7 days are within the cache window
    cache = _make_cache(600)
    target = date(2025, 6, 1)
    # Past 7 days: cool
    past_mask = (
        (cache["ts"].dt.date >= date(2025, 5, 25)) &
        (cache["ts"].dt.date <  target)
    )
    cache.loc[past_mask, "temp_c"] = 15.0
    # Today: very hot
    cache.loc[cache["ts"].dt.date == target, "temp_c"] = 35.0

    out = build_inference_features(cache, target)
    assert (out["temp_anomaly_7d"] > 0).all()


def test_inference_delta_168h_compares_same_hour_last_week():
    cache = _make_cache(600)
    target = date(2025, 6, 1)
    current_mask = cache["ts"].dt.date == target
    prior_week_mask = cache["ts"].dt.date == date(2025, 5, 25)
    cache.loc[current_mask, "temp_c"] = 25.0
    cache.loc[prior_week_mask, "temp_c"] = 20.0

    out = build_inference_features(cache, target)

    assert np.allclose(out["temp_delta_168h"].values, 5.0, atol=1e-6)
    assert np.allclose(out["cooling_delta_168h"].values, 3.0, atol=1e-6)


# ---------------------------------------------------------------------------
# Holiday lag correction helpers
# ---------------------------------------------------------------------------

jpholiday = pytest.importorskip("jpholiday", reason="jpholiday not installed")


def test_last_biz_day_skips_weekend():
    result = _last_biz_day(date(2025, 5, 7))
    assert result == date(2025, 5, 2)


def test_last_biz_day_normal_tuesday():
    result = _last_biz_day(date(2025, 1, 15))
    assert result == date(2025, 1, 14)


def test_consec_holiday_len_after_golden_week():
    length = _consec_holiday_len(date(2025, 5, 7))
    assert length >= 3


def test_consec_holiday_len_regular_monday():
    length = _consec_holiday_len(date(2025, 1, 13))
    assert length == 2


def test_days_since_holiday_end_day_after():
    result = _days_since_holiday_end(date(2025, 5, 7))
    assert result == 1


def test_days_since_holiday_end_regular_tuesday():
    result = _days_since_holiday_end(date(2025, 1, 15))
    assert result == 2


def test_days_since_holiday_end_on_holiday():
    result = _days_since_holiday_end(date(2025, 5, 5))
    assert result == 0


def test_major_holiday_season_golden_week():
    assert _major_holiday_season(date(2025, 5, 1))  == 1
    assert _major_holiday_season(date(2025, 5, 7))  == 1


def test_major_holiday_season_obon():
    assert _major_holiday_season(date(2025, 8, 15)) == 2


def test_major_holiday_season_new_year():
    assert _major_holiday_season(date(2025, 1, 3))  == 3
    assert _major_holiday_season(date(2024, 12, 30)) == 3


def test_major_holiday_season_normal():
    assert _major_holiday_season(date(2025, 3, 15)) == 0
    assert _major_holiday_season(date(2025, 7, 1))  == 0


# ---------------------------------------------------------------------------
# Holiday correction features in training / inference output
# ---------------------------------------------------------------------------

def test_training_has_holiday_correction_columns():
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    for col in ["lag_last_biz_hour", "lag_last_nonhol_hour",
                "consec_holiday_len", "days_since_holiday_end", "major_holiday_season"]:
        assert col in X.columns


def test_inference_has_holiday_correction_columns():
    cache = _make_cache(400)
    out = build_inference_features(cache, date(2025, 1, 13))
    for col in ["lag_last_biz_hour", "lag_last_nonhol_hour",
                "consec_holiday_len", "days_since_holiday_end", "major_holiday_season"]:
        assert col in out.columns


def test_lag_last_biz_hour_differs_from_lag_24h_post_holiday():
    """After a holiday, lag_last_biz_hour should differ from lag_24h."""
    cache = _make_cache(400)
    out = build_inference_features(cache, date(2025, 5, 7))
    lag24    = out["lag_24h"].iloc[0]
    lag_biz  = out["lag_last_biz_hour"].iloc[0]
    if not (np.isnan(lag24) or np.isnan(lag_biz)):
        assert lag24 != lag_biz


# ---------------------------------------------------------------------------
# Interaction features
# ---------------------------------------------------------------------------

def test_training_has_interaction_columns():
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    for col in ["holiday_x_heat", "post_holiday_x_heat", "business_hour_x_post_holiday_heat"]:
        assert col in X.columns


def test_inference_has_interaction_columns():
    cache = _make_cache(400)
    out = build_inference_features(cache, date(2025, 1, 13))
    for col in ["holiday_x_heat", "post_holiday_x_heat", "business_hour_x_post_holiday_heat"]:
        assert col in out.columns


def test_interaction_feature_cols_count():
    """FEATURE_COLS should include weather-delta features and lag context."""
    from python.forecast.feature_builder import FEATURE_COLS
    assert len(FEATURE_COLS) == 30


def test_holiday_x_heat_nonneg():
    """holiday_x_heat must be non-negative (consec_len ≥ 0, heat7d = max(0,anomaly) ≥ 0)."""
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    assert (X["holiday_x_heat"] >= 0).all()


def test_post_holiday_x_heat_nonneg():
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    assert (X["post_holiday_x_heat"] >= 0).all()


def test_business_hour_x_post_holiday_heat_nonneg():
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    assert (X["business_hour_x_post_holiday_heat"] >= 0).all()


def test_post_holiday_x_heat_zero_far_from_holiday():
    """post_holiday_x_heat must be 0 when days_since_holiday_end > 2."""
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    far_rows = X[X["days_since_holiday_end"] > 2]
    assert (far_rows["post_holiday_x_heat"] == 0).all()


def test_business_hour_x_post_holiday_heat_zero_overnight():
    """business_hour_x_post_holiday_heat must be 0 for hours 0-8."""
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    night = X[X["hour"] < 9]
    assert (night["business_hour_x_post_holiday_heat"] == 0).all()


def test_inference_interaction_zero_when_no_heat():
    """All interaction features are 0 when temp_anomaly_7d ≤ 0."""
    start = pd.Timestamp("2024-01-01", tz=JST)
    n = 600 * 24
    # Constant low temp so trailing mean = current temp → anomaly ≈ 0
    df = pd.DataFrame({
        "ts":        pd.date_range(start, periods=n, freq="h"),
        "actual_mw": np.full(n, 20_000.0),
        "temp_c":    np.full(n, 15.0),
    })
    target = date(2025, 8, 5)
    out = build_inference_features(df, target)
    # anomaly_7d ≈ 0, so heat7d = max(0, 0) = 0 → interaction all 0
    assert (out["holiday_x_heat"] == 0).all()
    assert (out["post_holiday_x_heat"] == 0).all()
    assert (out["business_hour_x_post_holiday_heat"] == 0).all()


# ---------------------------------------------------------------------------
# Lag contamination context features
# ---------------------------------------------------------------------------

def test_training_has_lag_context_columns():
    cache = _make_cache(200)
    X, _ = build_training_features(cache)
    for col in ["lag_24h_dsh", "lag_24h_consec", "lag_168h_dsh"]:
        assert col in X.columns


def test_inference_has_lag_context_columns():
    cache = _make_cache(400)
    out = build_inference_features(cache, date(2025, 1, 13))
    for col in ["lag_24h_dsh", "lag_24h_consec", "lag_168h_dsh"]:
        assert col in out.columns


def test_lag_24h_consec_post_golden_week():
    """lag_24h_consec for 2025-05-08 = consec_holiday_len(2025-05-07) ≥ 3."""
    cache = _make_cache(600)
    out = build_inference_features(cache, date(2025, 5, 8))
    assert (out["lag_24h_consec"] >= 3).all()


def test_lag_24h_dsh_post_golden_week():
    """lag_24h_dsh for 2025-05-08 = days_since_holiday_end(2025-05-07) = 1."""
    cache = _make_cache(600)
    out = build_inference_features(cache, date(2025, 5, 8))
    assert (out["lag_24h_dsh"] == 1).all()


def test_lag_168h_dsh_post_golden_week():
    """lag_168h_dsh for 2025-05-08 = days_since_holiday_end(2025-05-01).
    May 1 is a regular Thursday (not a holiday); the nearest prior non-working day
    is April 29 (Showa Day), so dsh=2."""
    cache = _make_cache(600)
    out = build_inference_features(cache, date(2025, 5, 8))
    assert (out["lag_168h_dsh"] == 2).all()


def test_lag_context_regular_tuesday():
    """For a regular Tuesday (Jan 21), the preceding Monday is a normal business day.
    lag_24h_consec(Tuesday) = _consec_holiday_len(Monday) = 2 (Sat+Sun preceded Monday).
    lag_24h_dsh(Tuesday) = _days_since_holiday_end(Monday) = 1 (1 day after Sunday).
    Compare with post-GW May 8: lag_24h_consec=4 — that's the model's signal."""
    cache = _make_cache(400)
    # 2025-01-21 is Tuesday, 2025-01-20 is a regular Monday
    out = build_inference_features(cache, date(2025, 1, 21))
    assert (out["lag_24h_consec"] == 2).all()
    assert (out["lag_24h_dsh"] == 1).all()
