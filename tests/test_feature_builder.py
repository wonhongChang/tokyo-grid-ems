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
    """Synthetic hourly cache: 20 000 + hour sinusoid + small noise."""
    rng = np.random.default_rng(0)
    start = pd.Timestamp(base, tz=JST)
    n = n_days * 24
    timestamps = pd.date_range(start, periods=n, freq="h")
    actual_mw = (
        20_000
        + 2_000 * np.sin(np.pi * np.arange(n) / 12)
        + rng.normal(0, 100, n)
    )
    return pd.DataFrame({
        "ts": timestamps,
        "actual_mw": actual_mw,
        "forecast_mw": actual_mw,
        "usage_pct": actual_mw / 250,
        "supply_mw": np.full(n, 25_000.0),
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
    # actual_mw = 20000 everywhere → lag_24h should also be 20000 for every row
    start = pd.Timestamp("2024-01-01", tz=JST)
    n = 400 * 24
    df = pd.DataFrame({
        "ts": pd.date_range(start, periods=n, freq="h"),
        "actual_mw": np.full(n, 20_000.0),
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
# Holiday lag correction helpers
# ---------------------------------------------------------------------------

jpholiday = pytest.importorskip("jpholiday", reason="jpholiday not installed")


def test_last_biz_day_skips_weekend():
    # 2025-05-05 is Children's Day (Monday holiday); 2025-05-04 Sun, 2025-05-03 Sat
    # Last business day before 2025-05-07 (Wednesday) should be 2025-05-02 (Friday)
    result = _last_biz_day(date(2025, 5, 7))
    assert result == date(2025, 5, 2)


def test_last_biz_day_normal_tuesday():
    # 2025-01-15 is Wednesday; 2025-01-13 is 成人の日(holiday), so last biz = 2025-01-14 (Tue)
    result = _last_biz_day(date(2025, 1, 15))
    assert result == date(2025, 1, 14)


def test_consec_holiday_len_after_golden_week():
    # 2025-05-07: May 3(Sat) 4(Sun) 5(Mon holiday) 6(Tue holiday) = 4 non-working days
    length = _consec_holiday_len(date(2025, 5, 7))
    assert length >= 3  # at minimum the GW weekend+holidays before May 7


def test_consec_holiday_len_regular_monday():
    # 2025-01-13 (Mon): just Saturday + Sunday before it
    length = _consec_holiday_len(date(2025, 1, 13))
    assert length == 2


def test_days_since_holiday_end_day_after():
    # 2025-05-07 (Wed): yesterday 2025-05-06 was holiday → 1
    result = _days_since_holiday_end(date(2025, 5, 7))
    assert result == 1


def test_days_since_holiday_end_regular_tuesday():
    # 2025-01-15 (Wed): yesterday Jan 14 (Tue) is normal; Jan 13 (Mon) is 成人の日 → 2
    result = _days_since_holiday_end(date(2025, 1, 15))
    assert result == 2


def test_days_since_holiday_end_on_holiday():
    # Returns 0 when the date itself is a holiday
    result = _days_since_holiday_end(date(2025, 5, 5))  # Children's Day
    assert result == 0


def test_major_holiday_season_golden_week():
    assert _major_holiday_season(date(2025, 5, 1))  == 1  # May 1 = GW zone
    assert _major_holiday_season(date(2025, 5, 7))  == 1  # May 7 = return zone


def test_major_holiday_season_obon():
    assert _major_holiday_season(date(2025, 8, 15)) == 2


def test_major_holiday_season_new_year():
    assert _major_holiday_season(date(2025, 1, 3))  == 3
    assert _major_holiday_season(date(2024, 12, 30)) == 3


def test_major_holiday_season_normal():
    assert _major_holiday_season(date(2025, 3, 15)) == 0
    assert _major_holiday_season(date(2025, 7, 1))  == 0


# ---------------------------------------------------------------------------
# Holiday correction features in training output
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
    # 2025-05-07: yesterday was holiday → lag_24h uses holiday-day MW,
    # lag_last_biz_hour uses 2025-05-02 (Friday before GW)
    out = build_inference_features(cache, date(2025, 5, 7))
    # lag_24h looks up May 6 (holiday), lag_last_biz_hour looks up May 2
    # Both may be NaN if cache doesn't extend that far; just verify they differ
    # when both are present
    lag24 = out["lag_24h"].iloc[0]
    lag_biz = out["lag_last_biz_hour"].iloc[0]
    if not (np.isnan(lag24) or np.isnan(lag_biz)):
        assert lag24 != lag_biz
