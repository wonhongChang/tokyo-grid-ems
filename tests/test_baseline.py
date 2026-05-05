"""Tests for python/forecast/baseline.py."""
from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from python.forecast.baseline import (
    HourlyForecast,
    _is_holiday,
    _is_holiday_or_weekend,
    compute_forecast,
    forecast_to_dict,
    peak_of_forecasts,
)

JST = ZoneInfo("Asia/Tokyo")

jpholiday = pytest.importorskip("jpholiday", reason="jpholiday not installed")


def _make_history(start: str, n_days: int, mw: float = 30000.0) -> pd.DataFrame:
    rows = []
    base = pd.Timestamp(start, tz=JST)
    for d in range(n_days):
        for h in range(24):
            rows.append({"ts": base + pd.Timedelta(days=d, hours=h), "actual_mw": mw})
    return pd.DataFrame(rows)


# ── Empty / missing data ─────────────────────────────────────────────────────

def test_returns_empty_for_empty_history():
    result = compute_forecast(pd.DataFrame(columns=["ts", "actual_mw"]), date(2024, 1, 8))
    assert result == []


def test_returns_empty_when_no_actual_mw_column():
    df = pd.DataFrame({"ts": [pd.Timestamp("2024-01-01", tz=JST)]})
    result = compute_forecast(df, date(2024, 1, 8))
    assert result == []


def test_returns_empty_when_insufficient_samples():
    # 3 Mondays of history, min_samples=4
    hist = _make_history("2024-01-01", 21)  # 3 weeks; 3 Mondays
    target = date(2024, 1, 22)  # 4th Monday
    result = compute_forecast(hist, target, n_weeks=12, min_samples=4)
    assert result == []


# ── Correctness ──────────────────────────────────────────────────────────────

def test_excludes_target_date_from_history():
    # Inject inflated values on target date — forecast must not use them.
    hist = _make_history("2024-01-01", 14)
    target_rows = [
        {"ts": pd.Timestamp(f"2024-01-15T{h:02d}:00:00+09:00"), "actual_mw": 999999.0}
        for h in range(24)
    ]
    hist = pd.concat([hist, pd.DataFrame(target_rows)], ignore_index=True)
    target = date(2024, 1, 15)  # Monday
    result = compute_forecast(hist, target, n_weeks=12, min_samples=1)
    for f in result:
        assert f.forecast_mw < 999990.0, "Target date data must be excluded from forecast"


def test_filters_same_weekday_only():
    rows = []
    base = pd.Timestamp("2024-01-01", tz=JST)  # Monday
    for day_offset in range(84):  # 12 weeks
        ts_day = base + pd.Timedelta(days=day_offset)
        mw = 10000.0 if ts_day.day_of_week == 0 else 99999.0
        for h in range(24):
            rows.append({"ts": ts_day + pd.Timedelta(hours=h), "actual_mw": mw})
    df = pd.DataFrame(rows)
    target = date(2024, 3, 25)  # 13th Monday
    result = compute_forecast(df, target, n_weeks=12, min_samples=1)
    assert len(result) == 24
    for f in result:
        assert abs(f.forecast_mw - 10000.0) < 1.0, f"Expected ~10000 MW, got {f.forecast_mw}"


def test_returns_24_hours_when_sufficient_history():
    hist = _make_history("2024-01-01", 56)  # 8 weeks
    target = date(2024, 2, 26)  # Monday
    result = compute_forecast(hist, target, n_weeks=8, min_samples=4)
    assert len(result) == 24


def test_ts_format_ends_with_jst_offset():
    hist = _make_history("2024-01-01", 28)
    target = date(2024, 1, 29)  # Monday
    result = compute_forecast(hist, target, n_weeks=12, min_samples=1)
    assert len(result) == 24
    for f in result:
        assert f.ts.endswith("+09:00"), f"Expected ISO +09:00 offset, got {f.ts}"


def test_constant_history_gives_zero_std():
    # All values identical → std=0 → p95/p99 bounds equal forecast_mw
    hist = _make_history("2024-01-01", 28, mw=30000.0)
    target = date(2024, 1, 29)
    result = compute_forecast(hist, target, n_weeks=4, min_samples=1)
    assert len(result) == 24
    for f in result:
        assert f.forecast_mw == pytest.approx(30000.0, abs=1.0)
        assert f.p95_lower_mw == pytest.approx(30000.0, abs=1.0)
        assert f.p95_upper_mw == pytest.approx(30000.0, abs=1.0)


def test_p95_interval_symmetric_around_mean():
    hist = _make_history("2024-01-01", 28)
    target = date(2024, 1, 29)
    result = compute_forecast(hist, target, n_weeks=4, min_samples=1)
    for f in result:
        upper_dist = f.p95_upper_mw - f.forecast_mw
        lower_dist = f.forecast_mw - f.p95_lower_mw
        assert abs(upper_dist - lower_dist) < 0.2


def test_p99_wider_than_p95():
    # Need variance; use varying mw across weeks
    rows = []
    base = pd.Timestamp("2024-01-01", tz=JST)
    for week in range(8):
        for h in range(24):
            ts = base + pd.Timedelta(weeks=week, hours=h)
            rows.append({"ts": ts, "actual_mw": 30000.0 + week * 500})
    df = pd.DataFrame(rows)
    target = date(2024, 2, 26)
    result = compute_forecast(df, target, n_weeks=8, min_samples=2)
    for f in result:
        assert f.p99_upper_mw >= f.p95_upper_mw
        assert f.p99_lower_mw <= f.p95_lower_mw


# ── Object-dtype ts guard ────────────────────────────────────────────────────

def test_handles_object_dtype_ts():
    hist = _make_history("2024-01-01", 28)
    hist["ts"] = hist["ts"].astype(str)  # degrade to object, simulating empty concat
    target = date(2024, 1, 29)
    result = compute_forecast(hist, target, n_weeks=12, min_samples=1)
    assert len(result) == 24


# ── Helper functions ─────────────────────────────────────────────────────────

def test_forecast_to_dict_has_all_keys():
    hist = _make_history("2024-01-01", 28)
    result = compute_forecast(hist, date(2024, 1, 29), n_weeks=4, min_samples=1)
    assert result
    d = forecast_to_dict(result[0])
    assert set(d.keys()) == {"ts", "forecastMw", "p95LowerMw", "p95UpperMw", "p99LowerMw", "p99UpperMw"}


def test_peak_of_forecasts_finds_maximum():
    hist = _make_history("2024-01-01", 28)
    result = compute_forecast(hist, date(2024, 1, 29), n_weeks=4, min_samples=1)
    assert result
    peak = peak_of_forecasts(result)
    assert peak is not None
    assert peak["forecastMw"] == max(f.forecast_mw for f in result)


def test_peak_of_forecasts_none_for_empty():
    assert peak_of_forecasts([]) is None


# ── Holiday helpers ───────────────────────────────────────────────────────────

def test_is_holiday_detects_known_japanese_holiday():
    assert _is_holiday(date(2025, 5, 5))   # 子供の日 (Children's Day)
    assert _is_holiday(date(2025, 1, 1))   # 元日 (New Year's Day)
    assert not _is_holiday(date(2025, 1, 6))   # regular Monday


def test_is_holiday_or_weekend_covers_saturday_sunday():
    assert _is_holiday_or_weekend(date(2025, 5, 3))   # Saturday
    assert _is_holiday_or_weekend(date(2025, 5, 4))   # Sunday
    assert not _is_holiday_or_weekend(date(2025, 5, 7))  # regular Wednesday


# ── Holiday-aware forecast ────────────────────────────────────────────────────

def _make_holiday_history() -> pd.DataFrame:
    """
    Build history for testing holiday forecast.

    Target date: 2025-05-05 (Golden Week Children's Day, Monday)

    - Regular Mondays in Jan-Mar 2025 (12-week window): actual_mw = 35000
    - Past holiday days (Golden Week region, 2020-2024): actual_mw = 25000

    If holiday logic works, forecast for 2025-05-05 ~= 25000.
    If it falls back to weekday logic, forecast ~= 35000.
    """
    rows = []

    # 12 regular Mondays before target (Jan-Mar 2025)
    mon = date(2025, 1, 6)  # first Monday of 2025
    while mon < date(2025, 5, 5):
        if not _is_holiday_or_weekend(mon):  # skip if accidentally a holiday
            for h in range(24):
                rows.append({
                    "ts": pd.Timestamp(mon.year, mon.month, mon.day, h, 0, tzinfo=JST),
                    "actual_mw": 35000.0,
                })
        mon += timedelta(weeks=1)

    # Past holiday days in Golden Week ± a few days, 2020-2024
    for year in range(2020, 2025):
        gw_start = date(year, 4, 29)
        for delta in range(10):
            d = gw_start + timedelta(days=delta)
            if _is_holiday_or_weekend(d):
                for h in range(24):
                    rows.append({
                        "ts": pd.Timestamp(d.year, d.month, d.day, h, 0, tzinfo=JST),
                        "actual_mw": 25000.0,
                    })

    return pd.DataFrame(rows)


def test_holiday_target_uses_holiday_training_data():
    hist = _make_holiday_history()
    target = date(2025, 5, 5)  # 子供の日 - Golden Week Monday
    result = compute_forecast(hist, target, n_weeks=12, min_samples=4)
    assert len(result) == 24
    for f in result:
        # Holiday pattern (25000) should dominate; regular Monday (35000) should not
        assert f.forecast_mw < 30000.0, (
            f"Holiday forecast should use holiday data (~25000), got {f.forecast_mw}"
        )


def test_holiday_fallback_when_insufficient_holiday_samples():
    # Only 2 holiday days in history -> falls back to weekday data (35000)
    rows = []

    # Regular Mondays: mw=35000
    mon = date(2025, 1, 6)
    while mon < date(2025, 5, 5):
        if not _is_holiday_or_weekend(mon):
            for h in range(24):
                rows.append({
                    "ts": pd.Timestamp(mon.year, mon.month, mon.day, h, 0, tzinfo=JST),
                    "actual_mw": 35000.0,
                })
        mon += timedelta(weeks=1)

    # Only 2 holiday days (below min_samples=4): mw=25000
    for d in [date(2024, 5, 3), date(2024, 5, 5)]:
        for h in range(24):
            rows.append({
                "ts": pd.Timestamp(d.year, d.month, d.day, h, 0, tzinfo=JST),
                "actual_mw": 25000.0,
            })

    hist = pd.DataFrame(rows)
    target = date(2025, 5, 5)
    result = compute_forecast(hist, target, n_weeks=16, min_samples=4)
    assert len(result) == 24
    for f in result:
        # Should fall back to weekday data (~35000) since only 2 holiday days available
        assert f.forecast_mw > 30000.0, (
            f"Fallback should use weekday data (~35000), got {f.forecast_mw}"
        )


def test_weekday_uses_year_over_year_same_season():
    """
    Weekday forecast should pull in same-season same-weekday data from prior years.

    Target: 2025-03-03 (Monday, not a holiday).
    Recent window (4 weeks): only 2 Mondays  → mw=50000.
    YOY 2024 Mondays in Mar ±4 weeks: 5 Mondays → mw=30000.
    Combined = 7 samples per hour; mean ≈ 35714 (between 30000 and 50000).
    Without YOY the 2 recent samples alone would be below min_samples=4 → empty result.
    """
    rows = []
    # 2 recent Mondays (within 4-week window before 2025-03-03)
    for d in [date(2025, 2, 24), date(2025, 2, 17)]:
        for h in range(24):
            rows.append({"ts": pd.Timestamp(d.year, d.month, d.day, h, 0, tzinfo=JST), "actual_mw": 50000.0})

    # 5 Mondays from Feb-Mar 2024 (same season, previous year; none are holidays)
    for d in [date(2024, 2, 26), date(2024, 3, 4), date(2024, 3, 11), date(2024, 3, 18), date(2024, 3, 25)]:
        for h in range(24):
            rows.append({"ts": pd.Timestamp(d.year, d.month, d.day, h, 0, tzinfo=JST), "actual_mw": 30000.0})

    hist = pd.DataFrame(rows)
    target = date(2025, 3, 3)  # Monday, n_weeks=4 → only 2 recent samples alone
    result = compute_forecast(hist, target, n_weeks=4, min_samples=4)
    assert len(result) == 24, "YOY data should bring sample count above min_samples"
    for f in result:
        assert 30000.0 < f.forecast_mw < 50000.0, (
            f"Expected YOY data to blend with recent (mean ~35714), got {f.forecast_mw}"
        )


def test_regular_weekday_excludes_holiday_mondays():
    # 2024-02-12 is 振替休日 (substitute holiday - Monday after Feb 11 Sunday)
    holiday_monday = date(2024, 2, 12)
    assert _is_holiday(holiday_monday), "2024-02-12 should be a Japanese holiday"

    rows = []
    # Inject regular Mondays with mw=30000
    for weeks_back in range(1, 13):
        d = date(2025, 3, 3) - timedelta(weeks=weeks_back)  # 2025-03-03 is Monday
        if d.weekday() == 0 and not _is_holiday(d):
            for h in range(24):
                rows.append({
                    "ts": pd.Timestamp(d.year, d.month, d.day, h, 0, tzinfo=JST),
                    "actual_mw": 30000.0,
                })

    # Inject holiday_monday with mw=99000 (should be excluded)
    for h in range(24):
        rows.append({
            "ts": pd.Timestamp(holiday_monday.year, holiday_monday.month, holiday_monday.day, h, 0, tzinfo=JST),
            "actual_mw": 99000.0,
        })

    hist = pd.DataFrame(rows)
    target = date(2025, 3, 3)  # regular Monday
    result = compute_forecast(hist, target, n_weeks=52, min_samples=4)
    assert len(result) == 24
    for f in result:
        assert f.forecast_mw < 50000.0, (
            f"Holiday Monday (99000) must be excluded from regular weekday training; got {f.forecast_mw}"
        )
