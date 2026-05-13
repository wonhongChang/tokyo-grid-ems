"""Tests for python/forecast/adjustment.py."""
from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from python.forecast.adjustment import AnalogousDayAdjuster, PostHolidayTimeBandGuard
from python.forecast.baseline import HourlyForecast

JST = ZoneInfo("Asia/Tokyo")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _config(
    enabled: bool = True,
    min_candidates: int = 1,
    max_candidates: int = 5,
    shift_shrinkage: float = 0.7,
    single_candidate_shrinkage: float = 0.5,
    max_abs_shift_mw: float = 2500.0,
    weekday_type_required: bool = True,
) -> dict:
    return {
        "adjustment": {
            "enabled": enabled,
            "analogous_day": {
                "month_window": 1,
                "temp_anomaly_tol": 4.0,
                "daytime_temp_hours": [10, 11, 12, 13, 14, 15, 16, 17],
                "consec_holiday_tol": 2,
                "min_candidates": min_candidates,
                "max_candidates": max_candidates,
                "same_weekday_required": False,
                "weekday_type_required": weekday_type_required,
                "shift_shrinkage": shift_shrinkage,
                "single_candidate_shrinkage": single_candidate_shrinkage,
                "max_abs_shift_mw": max_abs_shift_mw,
            },
        }
    }


def _make_cache(n_days: int = 500, base: str = "2023-06-01") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    start = pd.Timestamp(base, tz=JST)
    n = n_days * 24
    timestamps = pd.date_range(start, periods=n, freq="h")
    hours = np.arange(n)
    actual_mw = 20_000 + 2_000 * np.sin(np.pi * hours / 12) + rng.normal(0, 50, n)
    temp_c = 18.0 + 8.0 * np.sin(2 * np.pi * (hours / 24 - 90) / 365) + rng.normal(0, 1.0, n)
    return pd.DataFrame({"ts": timestamps, "actual_mw": actual_mw, "temp_c": temp_c})


def _make_raw_forecasts(target_date: date, forecast_mw: float = 20_000.0) -> list[HourlyForecast]:
    result = []
    for hour in range(24):
        ts = pd.Timestamp(
            year=target_date.year, month=target_date.month, day=target_date.day,
            hour=hour, tz=JST,
        )
        result.append(HourlyForecast(
            ts=ts.isoformat(timespec="seconds"),
            forecast_mw=forecast_mw,
            p95_lower_mw=forecast_mw - 1_000.0,
            p95_upper_mw=forecast_mw + 1_000.0,
            p99_lower_mw=forecast_mw - 1_500.0,
            p99_upper_mw=forecast_mw + 1_500.0,
        ))
    return result


def _make_inference_features(
    target_date: date,
    consec_holiday_len: int = 0,
    days_since_holiday_end: int = 3,
    temp_anomaly_7d: float = 5.0,
    is_weekend: int = 0,
    is_holiday: int = 0,
    is_non_business_day: int = 0,
) -> pd.DataFrame:
    """Minimal inference_features DataFrame for testing adjust()."""
    rows = []
    for hour in range(24):
        rows.append({
            "hour": hour,
            "dayofweek": target_date.weekday(),
            "month": target_date.month,
            "is_holiday": is_holiday,
            "is_weekend": is_weekend,
            "is_non_business_day": is_non_business_day,
            "lag_24h": 20_000.0,
            "lag_48h": 20_000.0,
            "lag_168h": 20_000.0,
            "lag_336h": 20_000.0,
            "roll_4w_mean": 20_000.0,
            "roll_4w_std": 100.0,
            "lag_last_biz_hour": 20_000.0,
            "lag_last_nonhol_hour": 20_000.0,
            "consec_holiday_len": consec_holiday_len,
            "days_since_holiday_end": days_since_holiday_end,
            "major_holiday_season": 0,
            "temp_c": 25.0,
            "cooling_degree": 3.0,
            "heating_degree": 0.0,
            "temp_anomaly_7d": temp_anomaly_7d,
            "temp_anomaly_doy": 2.0,
            "holiday_x_heat": consec_holiday_len * max(0.0, temp_anomaly_7d),
            "post_holiday_x_heat": int(1 <= days_since_holiday_end <= 2) * max(0.0, temp_anomaly_7d),
            "business_hour_x_post_holiday_heat": (
                int(9 <= hour <= 18) * int(1 <= days_since_holiday_end <= 2)
                * max(0.0, temp_anomaly_7d)
            ),
        })
    return pd.DataFrame(rows)


class _MockForecaster:
    """Returns flat forecasts; actual_mw in cache determines residuals."""
    def __init__(self, q50: float = 20_000.0):
        self._q50 = q50

    def predict(self, target_date: date, cache: pd.DataFrame) -> list[HourlyForecast]:
        return _make_raw_forecasts(target_date, self._q50)


# ---------------------------------------------------------------------------
# Passthrough cases
# ---------------------------------------------------------------------------

def test_disabled_returns_raw():
    adj = AnalogousDayAdjuster(_config(enabled=False))
    raw = _make_raw_forecasts(date(2024, 9, 3))
    result = adj.adjust(_MockForecaster(), raw, _make_cache(), date(2024, 9, 3),
                        _make_inference_features(date(2024, 9, 3)))
    assert result is raw


def test_no_forecaster_returns_raw():
    adj = AnalogousDayAdjuster(_config())
    raw = _make_raw_forecasts(date(2024, 9, 3))
    result = adj.adjust(None, raw, _make_cache(), date(2024, 9, 3),
                        _make_inference_features(date(2024, 9, 3)))
    assert result is raw


def test_empty_raw_returns_raw():
    adj = AnalogousDayAdjuster(_config())
    result = adj.adjust(_MockForecaster(), [], _make_cache(), date(2024, 9, 3),
                        _make_inference_features(date(2024, 9, 3)))
    assert result == []


def test_no_candidates_returns_raw(monkeypatch):
    adj = AnalogousDayAdjuster(_config(min_candidates=3))
    monkeypatch.setattr(adj, "_find_candidates", lambda *a, **kw: [])
    raw = _make_raw_forecasts(date(2024, 9, 3))
    result = adj.adjust(_MockForecaster(), raw, _make_cache(), date(2024, 9, 3),
                        _make_inference_features(date(2024, 9, 3)))
    assert result is raw


# ---------------------------------------------------------------------------
# Shift application
# ---------------------------------------------------------------------------

def test_positive_shift_applied(monkeypatch):
    """actual > q50 for candidate → corrected forecasts higher than raw."""
    cache = _make_cache()
    target_date = date(2024, 10, 8)
    cand_date   = date(2023, 10, 3)

    # Force actual_mw = 22000 for candidate
    cache.loc[cache["ts"].dt.date == cand_date, "actual_mw"] = 22_000.0

    # Mock predicts 20000; residual = 22000 - 20000 = 2000; shrinkage=1.0
    adj = AnalogousDayAdjuster(_config(single_candidate_shrinkage=1.0))
    monkeypatch.setattr(adj, "_find_candidates", lambda *a, **kw: [cand_date])

    raw = _make_raw_forecasts(target_date, 20_000.0)
    inf = _make_inference_features(target_date)
    corrected = adj.adjust(_MockForecaster(q50=20_000.0), raw, cache, target_date, inf)

    assert all(c.forecast_mw > r.forecast_mw for c, r in zip(corrected, raw))


def test_negative_shift_applied(monkeypatch):
    """actual < q50 → corrected forecasts lower than raw."""
    cache = _make_cache()
    target_date = date(2024, 10, 8)
    cand_date   = date(2023, 10, 3)

    cache.loc[cache["ts"].dt.date == cand_date, "actual_mw"] = 18_000.0

    adj = AnalogousDayAdjuster(_config(single_candidate_shrinkage=1.0))
    monkeypatch.setattr(adj, "_find_candidates", lambda *a, **kw: [cand_date])

    raw = _make_raw_forecasts(target_date, 20_000.0)
    inf = _make_inference_features(target_date)
    corrected = adj.adjust(_MockForecaster(q50=20_000.0), raw, cache, target_date, inf)

    assert all(c.forecast_mw < r.forecast_mw for c, r in zip(corrected, raw))


def test_all_bands_shifted_equally(monkeypatch):
    """p95_lower/upper and p99_lower/upper shift by the same amount as forecast_mw."""
    cache = _make_cache()
    target_date = date(2024, 10, 8)
    cand_date   = date(2023, 10, 3)

    cache.loc[cache["ts"].dt.date == cand_date, "actual_mw"] = 22_000.0

    adj = AnalogousDayAdjuster(_config(single_candidate_shrinkage=1.0))
    monkeypatch.setattr(adj, "_find_candidates", lambda *a, **kw: [cand_date])

    raw = _make_raw_forecasts(target_date, 20_000.0)
    inf = _make_inference_features(target_date)
    corrected = adj.adjust(_MockForecaster(q50=20_000.0), raw, cache, target_date, inf)

    for c, r in zip(corrected, raw):
        delta_fc   = c.forecast_mw    - r.forecast_mw
        delta_lo95 = c.p95_lower_mw   - r.p95_lower_mw
        delta_hi95 = c.p95_upper_mw   - r.p95_upper_mw
        assert abs(delta_lo95 - delta_fc) < 0.01
        assert abs(delta_hi95 - delta_fc) < 0.01


# ---------------------------------------------------------------------------
# Shrinkage
# ---------------------------------------------------------------------------

def test_single_candidate_uses_single_shrinkage(monkeypatch):
    """1 candidate → single_candidate_shrinkage (0.5) applied, not shift_shrinkage."""
    cache = _make_cache()
    target_date = date(2024, 10, 8)
    cand_date   = date(2023, 10, 3)

    # actual_mw = 22000, q50 = 20000, raw residual = 2000
    cache.loc[cache["ts"].dt.date == cand_date, "actual_mw"] = 22_000.0

    adj = AnalogousDayAdjuster(_config(
        single_candidate_shrinkage=0.5,
        shift_shrinkage=0.7,
    ))
    monkeypatch.setattr(adj, "_find_candidates", lambda *a, **kw: [cand_date])

    raw = _make_raw_forecasts(target_date, 20_000.0)
    inf = _make_inference_features(target_date)
    corrected = adj.adjust(_MockForecaster(q50=20_000.0), raw, cache, target_date, inf)

    # Expected shift = 2000 * 0.5 = 1000
    for fc in corrected:
        assert abs(fc.forecast_mw - 21_000.0) < 5.0  # within 5 MW (rounding)


def test_multi_candidate_uses_shift_shrinkage(monkeypatch):
    """2+ candidates → shift_shrinkage (0.7) applied."""
    cache = _make_cache()
    target_date = date(2024, 10, 8)
    cand1 = date(2023, 10, 3)
    cand2 = date(2023, 9, 26)

    cache.loc[cache["ts"].dt.date == cand1, "actual_mw"] = 22_000.0
    cache.loc[cache["ts"].dt.date == cand2, "actual_mw"] = 22_000.0

    adj = AnalogousDayAdjuster(_config(
        single_candidate_shrinkage=0.5,
        shift_shrinkage=0.7,
    ))
    monkeypatch.setattr(adj, "_find_candidates", lambda *a, **kw: [cand1, cand2])

    raw = _make_raw_forecasts(target_date, 20_000.0)
    inf = _make_inference_features(target_date)
    corrected = adj.adjust(_MockForecaster(q50=20_000.0), raw, cache, target_date, inf)

    # Expected shift = 2000 * 0.7 = 1400
    for fc in corrected:
        assert abs(fc.forecast_mw - 21_400.0) < 5.0


# ---------------------------------------------------------------------------
# Clamping
# ---------------------------------------------------------------------------

def test_shift_clamped_to_max(monkeypatch):
    """Shift exceeding max_abs_shift_mw is clamped."""
    cache = _make_cache()
    target_date = date(2024, 10, 8)
    cand_date   = date(2023, 10, 3)

    # actual >> q50 to create a massive residual
    cache.loc[cache["ts"].dt.date == cand_date, "actual_mw"] = 40_000.0

    adj = AnalogousDayAdjuster(_config(
        single_candidate_shrinkage=1.0,
        max_abs_shift_mw=2500.0,
    ))
    monkeypatch.setattr(adj, "_find_candidates", lambda *a, **kw: [cand_date])

    raw = _make_raw_forecasts(target_date, 20_000.0)
    inf = _make_inference_features(target_date)
    corrected = adj.adjust(_MockForecaster(q50=20_000.0), raw, cache, target_date, inf)

    for fc in corrected:
        shift = fc.forecast_mw - 20_000.0
        assert shift <= 2500.0 + 0.5  # within rounding


# ---------------------------------------------------------------------------
# _find_candidates smoke tests
# ---------------------------------------------------------------------------

jpholiday = pytest.importorskip("jpholiday", reason="jpholiday not installed")


def test_find_candidates_returns_list():
    cache = _make_cache(500)
    adj = AnalogousDayAdjuster(_config())
    target = date(2024, 9, 10)
    result = adj._find_candidates(
        cache, target,
        target_consecutive_holiday_len=0,
        target_temp_anomaly_7d=2.0,
        target_is_business_day=True,
    )
    assert isinstance(result, list)
    assert all(isinstance(d, date) for d in result)


def test_find_candidates_all_before_target():
    cache = _make_cache(500)
    adj = AnalogousDayAdjuster(_config())
    target = date(2024, 9, 10)
    result = adj._find_candidates(
        cache, target,
        target_consecutive_holiday_len=0,
        target_temp_anomaly_7d=2.0,
        target_is_business_day=True,
    )
    assert all(d < target for d in result)


def test_find_candidates_respects_max():
    cache = _make_cache(500)
    adj = AnalogousDayAdjuster(_config(max_candidates=2))
    target = date(2024, 9, 10)
    result = adj._find_candidates(
        cache, target,
        target_consecutive_holiday_len=0,
        target_temp_anomaly_7d=2.0,
        target_is_business_day=True,
    )
    assert len(result) <= 2


# ===========================================================================
# PostHolidayTimeBandGuard
# ===========================================================================

def _guard_config(
    enabled: bool = True,
    min_consec: int = 3,
    max_dsh: int = 1,
    em_block: bool = True,
    em_offset: float = 0.0,
    dt_block: bool = True,
    dt_offset: float = 0.0,
    dt_min_anomaly: float = 2.0,
) -> dict:
    return {
        "adjustment": {
            "post_holiday_timeband_guard": {
                "enabled": enabled,
                "min_consec_holiday_len": min_consec,
                "max_days_since_holiday_end": max_dsh,
                "early_morning": {
                    "hours": [1, 2, 3, 4, 5, 6],
                    "block_positive_shift": em_block,
                    "downward_offset_mw": em_offset,
                    "max_downward_offset_mw": 600.0,
                },
                "daytime": {
                    "hours": [10, 11, 12, 13, 14, 15, 16, 17, 18],
                    "min_temp_anomaly_7d": dt_min_anomaly,
                    "block_negative_shift": dt_block,
                    "upward_offset_mw": dt_offset,
                    "max_upward_offset_mw": 900.0,
                },
            }
        }
    }


def _make_post_holiday_inf(
    consec: int = 5,
    dsh: int = 1,
    temp_anomaly_morning: float = 0.5,
    temp_anomaly_daytime: float = 5.0,
) -> pd.DataFrame:
    """inference_features where early morning has low anomaly, daytime has high anomaly."""
    rows = []
    for h in range(24):
        anom = temp_anomaly_daytime if 10 <= h <= 18 else temp_anomaly_morning
        rows.append({
            "hour": h, "dayofweek": 0, "month": 5,
            "is_holiday": 0, "is_weekend": 0, "is_non_business_day": 0,
            "lag_24h": 20_000.0, "lag_48h": 20_000.0,
            "lag_168h": 20_000.0, "lag_336h": 20_000.0,
            "roll_4w_mean": 20_000.0, "roll_4w_std": 100.0,
            "lag_last_biz_hour": 20_000.0, "lag_last_nonhol_hour": 20_000.0,
            "consec_holiday_len": consec,
            "days_since_holiday_end": dsh,
            "major_holiday_season": 1,
            "temp_c": 25.0, "cooling_degree": 3.0, "heating_degree": 0.0,
            "temp_anomaly_7d": anom, "temp_anomaly_doy": 2.0,
            "holiday_x_heat": consec * max(0.0, anom),
            "post_holiday_x_heat": int(1 <= dsh <= 2) * max(0.0, anom),
            "business_hour_x_post_holiday_heat": int(10 <= h <= 18) * int(1 <= dsh <= 2) * max(0.0, anom),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Passthrough cases
# ---------------------------------------------------------------------------

def test_guard_disabled_returns_adjusted():
    guard = PostHolidayTimeBandGuard(_guard_config(enabled=False))
    raw = _make_raw_forecasts(date(2026, 5, 7), 21_000.0)
    adj = _make_raw_forecasts(date(2026, 5, 7), 22_000.0)
    inf = _make_post_holiday_inf()
    assert guard.apply(raw, adj, inf) is adj


def test_guard_empty_raw_returns_adjusted():
    guard = PostHolidayTimeBandGuard(_guard_config())
    inf = _make_post_holiday_inf()
    assert guard.apply([], [], inf) == []


def test_guard_short_holiday_no_block():
    """consec=2 < min_consec=3 → guard does not fire, adjusted returned as-is."""
    guard = PostHolidayTimeBandGuard(_guard_config(min_consec=3))
    raw = _make_raw_forecasts(date(2026, 5, 7), 21_000.0)
    adj = _make_raw_forecasts(date(2026, 5, 7), 22_000.0)
    inf = _make_post_holiday_inf(consec=2)
    result = guard.apply(raw, adj, inf)
    assert result is adj


def test_guard_dsh_too_large_no_block():
    """dsh=2 > max_dsh=1 → guard does not fire."""
    guard = PostHolidayTimeBandGuard(_guard_config(max_dsh=1))
    raw = _make_raw_forecasts(date(2026, 5, 7), 21_000.0)
    adj = _make_raw_forecasts(date(2026, 5, 7), 22_000.0)
    inf = _make_post_holiday_inf(dsh=2)
    result = guard.apply(raw, adj, inf)
    assert result is adj


# ---------------------------------------------------------------------------
# Early morning guard
# ---------------------------------------------------------------------------

def test_guard_blocks_positive_early_morning():
    """Positive adjuster shift in early morning hours → reverted to raw (offset=0)."""
    guard = PostHolidayTimeBandGuard(_guard_config(em_offset=0.0))
    target = date(2026, 5, 7)
    raw = _make_raw_forecasts(target, 21_000.0)
    adj = []
    for fc in raw:
        h = pd.Timestamp(fc.ts).hour
        bump = 500.0 if 1 <= h <= 6 else 0.0
        from python.forecast.baseline import HourlyForecast
        adj.append(HourlyForecast(
            ts=fc.ts,
            forecast_mw=fc.forecast_mw + bump,
            p95_lower_mw=fc.p95_lower_mw + bump,
            p95_upper_mw=fc.p95_upper_mw + bump,
            p99_lower_mw=fc.p99_lower_mw + bump,
            p99_upper_mw=fc.p99_upper_mw + bump,
        ))
    inf = _make_post_holiday_inf(consec=5, dsh=1)
    result = guard.apply(raw, adj, inf)

    for fc_r, fc_res in zip(raw, result):
        h = pd.Timestamp(fc_r.ts).hour
        if 1 <= h <= 6:
            assert fc_res.forecast_mw == fc_r.forecast_mw  # reverted to raw


def test_guard_offset_applies_regardless_of_shift_direction():
    """upward_offset applies even when adjuster shift is positive (not blocked)."""
    guard = PostHolidayTimeBandGuard(_guard_config(dt_offset=300.0))
    target = date(2026, 5, 7)
    raw = _make_raw_forecasts(target, 28_000.0)
    # Adjuster went UP by 200 in daytime (positive — no blocking)
    adj = []
    for fc in raw:
        h = pd.Timestamp(fc.ts).hour
        bump = 200.0 if 10 <= h <= 18 else 0.0
        from python.forecast.baseline import HourlyForecast
        adj.append(HourlyForecast(
            ts=fc.ts,
            forecast_mw=fc.forecast_mw + bump,
            p95_lower_mw=fc.p95_lower_mw + bump,
            p95_upper_mw=fc.p95_upper_mw + bump,
            p99_lower_mw=fc.p99_lower_mw + bump,
            p99_upper_mw=fc.p99_upper_mw + bump,
        ))
    inf = _make_post_holiday_inf(consec=5, dsh=1, temp_anomaly_daytime=5.0)
    result = guard.apply(raw, adj, inf)

    for fc_a, fc_res in zip(adj, result):
        h = pd.Timestamp(fc_a.ts).hour
        if 10 <= h <= 18:
            # base = adj (shift positive, not blocked), then +300 offset
            assert abs(fc_res.forecast_mw - (fc_a.forecast_mw + 300.0)) < 0.5


def test_guard_offset_uses_raw_as_base_when_blocked():
    """When shift is blocked, offset is applied from raw base, not adj."""
    guard = PostHolidayTimeBandGuard(_guard_config(dt_offset=300.0))
    target = date(2026, 5, 7)
    raw = _make_raw_forecasts(target, 28_000.0)
    # Adjuster went DOWN by 500 in daytime (negative — gets blocked)
    adj = []
    for fc in raw:
        h = pd.Timestamp(fc.ts).hour
        bump = -500.0 if 10 <= h <= 18 else 0.0
        from python.forecast.baseline import HourlyForecast
        adj.append(HourlyForecast(
            ts=fc.ts,
            forecast_mw=fc.forecast_mw + bump,
            p95_lower_mw=fc.p95_lower_mw + bump,
            p95_upper_mw=fc.p95_upper_mw + bump,
            p99_lower_mw=fc.p99_lower_mw + bump,
            p99_upper_mw=fc.p99_upper_mw + bump,
        ))
    inf = _make_post_holiday_inf(consec=5, dsh=1, temp_anomaly_daytime=5.0)
    result = guard.apply(raw, adj, inf)

    for fc_r, fc_res in zip(raw, result):
        h = pd.Timestamp(fc_r.ts).hour
        if 10 <= h <= 18:
            # base = raw (blocked), then +300 offset → raw + 300
            assert abs(fc_res.forecast_mw - (fc_r.forecast_mw + 300.0)) < 0.5


def test_guard_allows_negative_early_morning():
    """Negative adjuster shift in early morning → kept (correct direction)."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 5, 7)
    raw = _make_raw_forecasts(target, 21_000.0)
    adj = []
    for fc in raw:
        h = pd.Timestamp(fc.ts).hour
        bump = -300.0 if 1 <= h <= 6 else 0.0
        from python.forecast.baseline import HourlyForecast
        adj.append(HourlyForecast(
            ts=fc.ts,
            forecast_mw=fc.forecast_mw + bump,
            p95_lower_mw=fc.p95_lower_mw + bump,
            p95_upper_mw=fc.p95_upper_mw + bump,
            p99_lower_mw=fc.p99_lower_mw + bump,
            p99_upper_mw=fc.p99_upper_mw + bump,
        ))
    inf = _make_post_holiday_inf(consec=5, dsh=1)
    result = guard.apply(raw, adj, inf)

    for fc_a, fc_res in zip(adj, result):
        h = pd.Timestamp(fc_a.ts).hour
        if 1 <= h <= 6:
            assert fc_res.forecast_mw == fc_a.forecast_mw  # kept


# ---------------------------------------------------------------------------
# Daytime guard
# ---------------------------------------------------------------------------

def test_guard_blocks_negative_daytime_hot():
    """Negative adjuster shift in daytime + high anomaly → reverted to raw."""
    guard = PostHolidayTimeBandGuard(_guard_config(dt_min_anomaly=2.0))
    target = date(2026, 5, 7)
    raw = _make_raw_forecasts(target, 28_000.0)
    adj = []
    for fc in raw:
        h = pd.Timestamp(fc.ts).hour
        bump = -500.0 if 10 <= h <= 18 else 0.0
        from python.forecast.baseline import HourlyForecast
        adj.append(HourlyForecast(
            ts=fc.ts,
            forecast_mw=fc.forecast_mw + bump,
            p95_lower_mw=fc.p95_lower_mw + bump,
            p95_upper_mw=fc.p95_upper_mw + bump,
            p99_lower_mw=fc.p99_lower_mw + bump,
            p99_upper_mw=fc.p99_upper_mw + bump,
        ))
    inf = _make_post_holiday_inf(consec=5, dsh=1, temp_anomaly_daytime=5.0)
    result = guard.apply(raw, adj, inf)

    for fc_r, fc_res in zip(raw, result):
        h = pd.Timestamp(fc_r.ts).hour
        if 10 <= h <= 18:
            assert fc_res.forecast_mw == fc_r.forecast_mw  # reverted to raw


def test_guard_allows_positive_daytime():
    """Positive adjuster shift in daytime → kept."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 5, 7)
    raw = _make_raw_forecasts(target, 28_000.0)
    adj = []
    for fc in raw:
        h = pd.Timestamp(fc.ts).hour
        bump = 400.0 if 10 <= h <= 18 else 0.0
        from python.forecast.baseline import HourlyForecast
        adj.append(HourlyForecast(
            ts=fc.ts,
            forecast_mw=fc.forecast_mw + bump,
            p95_lower_mw=fc.p95_lower_mw + bump,
            p95_upper_mw=fc.p95_upper_mw + bump,
            p99_lower_mw=fc.p99_lower_mw + bump,
            p99_upper_mw=fc.p99_upper_mw + bump,
        ))
    inf = _make_post_holiday_inf(consec=5, dsh=1, temp_anomaly_daytime=5.0)
    result = guard.apply(raw, adj, inf)

    for fc_a, fc_res in zip(adj, result):
        h = pd.Timestamp(fc_a.ts).hour
        if 10 <= h <= 18:
            assert fc_res.forecast_mw == fc_a.forecast_mw  # kept


def test_guard_daytime_no_block_when_cool():
    """Negative daytime shift not blocked when temp_anomaly_7d < threshold."""
    guard = PostHolidayTimeBandGuard(_guard_config(dt_min_anomaly=2.0))
    target = date(2026, 5, 7)
    raw = _make_raw_forecasts(target, 28_000.0)
    adj = []
    for fc in raw:
        h = pd.Timestamp(fc.ts).hour
        bump = -400.0 if 10 <= h <= 18 else 0.0
        from python.forecast.baseline import HourlyForecast
        adj.append(HourlyForecast(
            ts=fc.ts,
            forecast_mw=fc.forecast_mw + bump,
            p95_lower_mw=fc.p95_lower_mw + bump,
            p95_upper_mw=fc.p95_upper_mw + bump,
            p99_lower_mw=fc.p99_lower_mw + bump,
            p99_upper_mw=fc.p99_upper_mw + bump,
        ))
    # Cool day: anomaly = 1.0 < 2.0 threshold
    inf = _make_post_holiday_inf(consec=5, dsh=1, temp_anomaly_daytime=1.0)
    result = guard.apply(raw, adj, inf)

    for fc_a, fc_res in zip(adj, result):
        h = pd.Timestamp(fc_a.ts).hour
        if 10 <= h <= 18:
            assert fc_res.forecast_mw == fc_a.forecast_mw  # kept (cool → no block)
