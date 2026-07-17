"""Tests for python/forecast/adjustment.py."""
from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from python.forecast.adjustment import (
    AnalogousDayAdjuster,
    LocalizedShapeSpikeGuard,
    MiddayTransitionGuard,
    PostHolidayTimeBandGuard,
)
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
    warm_day: bool = False,
    warm_day_offset: float = 0.0,
    business_return_enabled: bool = True,
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
                    "activate_on_warm_day": warm_day,
                    "warm_day_min_temp_anomaly_doy": 1.0,
                    "warm_day_upward_offset_mw": warm_day_offset,
                    "max_upward_offset_mw": 900.0,
                    "warm_day_decline_damping": {
                        "enabled": True,
                        "hours": [15, 16, 17, 18, 19],
                        "max_same_business_delta_mw": 0.0,
                        "max_lag24_delta_mw": 500.0,
                        "offset_multiplier": 0.0,
                        "allow_negative_analog_shift": True,
                    },
                },
                "business_return_anchor_shortfall": {
                    "enabled": business_return_enabled,
                    "target_hours": [6, 7, 8, 9, 10, 11],
                    "gap_threshold_mw": 6_000.0,
                    "allowance_mw": 1_000.0,
                    "max_clipping_mw": 1_000.0,
                    "min_shape_shortfall_mw": 800.0,
                    "shrinkage_map": {
                        6: 0.25,
                        7: 0.35,
                        8: 0.45,
                        9: 0.50,
                        10: 0.30,
                        11: 0.20,
                    },
                },
                "business_return_anchor_excess_cap": {
                    "enabled": True,
                    "target_hours": [8, 9, 10, 11],
                    "gap_threshold_mw": 1_000.0,
                    "allowance_mw": 500.0,
                    "weather_allowance_mw_per_c": 100.0,
                    "max_weather_allowance_mw": 300.0,
                    "shrinkage": 0.6,
                    "max_clipping_mw": 900.0,
                },
                "business_declining_analog_uplift_cap": {
                    "enabled": True,
                    "target_hours": [13, 14, 15, 16, 17, 18, 19, 20],
                    "min_positive_shift_mw": 300.0,
                    "max_allowed_shift_mw": 100.0,
                    "max_supporting_delta_mw": 200.0,
                    "max_weather_delta_c": 0.0,
                    "require_same_business_type": True,
                },
            }
        }
    }


def _make_post_holiday_inf(
    consec: int = 5,
    dsh: int = 1,
    temp_anomaly_morning: float = 0.5,
    temp_anomaly_daytime: float = 5.0,
    is_non_business_day: int = 0,
) -> pd.DataFrame:
    """inference_features where early morning has low anomaly, daytime has high anomaly."""
    rows = []
    for h in range(24):
        anom = temp_anomaly_daytime if 10 <= h <= 18 else temp_anomaly_morning
        rows.append({
            "hour": h, "dayofweek": 0, "month": 5,
            "is_holiday": 0,
            "is_weekend": is_non_business_day,
            "is_non_business_day": is_non_business_day,
            "lag_24h": 20_000.0, "lag_48h": 20_000.0,
            "lag_168h": 20_000.0, "lag_336h": 20_000.0,
            "roll_4w_mean": 20_000.0, "roll_4w_std": 100.0,
            "lag_last_biz_hour": 20_000.0, "lag_last_nonhol_hour": 20_000.0,
            "lag_24h_business_type_mismatch": 0,
            "recent_same_business_type_mean": 20_000.0,
            "lag_24h_hourly_delta": 600.0,
            "recent_same_business_type_delta_mean": 100.0,
            "consec_holiday_len": consec,
            "days_since_holiday_end": dsh,
            "major_holiday_season": 1,
            "temp_c": 25.0, "cooling_degree": 3.0, "heating_degree": 0.0,
            "temp_delta_24h": 0.0, "cooling_delta_24h": 0.0,
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


def test_guard_adds_small_offset_for_ordinary_warm_day():
    """Seasonally warm business day without holiday context gets a smaller upward guard."""
    guard = PostHolidayTimeBandGuard(_guard_config(
        warm_day=True,
        warm_day_offset=250.0,
    ))
    target = date(2026, 5, 14)  # week-ago date is a normal business day
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
    inf = _make_post_holiday_inf(
        consec=0,
        dsh=8,
        temp_anomaly_daytime=0.5,
    )
    inf.loc[inf["hour"].between(10, 18), "temp_c"] = 22.5
    inf.loc[inf["hour"].between(10, 18), "temp_anomaly_doy"] = 1.5

    result = guard.apply(raw, adj, inf)

    for fc_r, fc_res in zip(raw, result):
        h = pd.Timestamp(fc_r.ts).hour
        if 10 <= h <= 18:
            assert fc_res.forecast_mw == pytest.approx(fc_r.forecast_mw + 250.0)


def test_guard_does_not_add_warm_day_offset_on_non_business_day():
    """Weekend/holiday heat remains a model feature; manual warm-day offset is business-day only."""
    config = _guard_config(
        warm_day=True,
        warm_day_offset=250.0,
    )
    config["adjustment"]["post_holiday_timeband_guard"][
        "non_business_analog_downshift_guard"
    ] = {"enabled": False}
    guard = PostHolidayTimeBandGuard(config)
    target = date(2026, 5, 16)  # Saturday
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
    inf = _make_post_holiday_inf(
        consec=0,
        dsh=0,
        temp_anomaly_daytime=5.0,
        is_non_business_day=1,
    )
    inf.loc[inf["hour"].between(10, 18), "temp_c"] = 25.0
    inf.loc[inf["hour"].between(10, 18), "temp_anomaly_doy"] = 2.0

    result = guard.apply(raw, adj, inf)

    for fc_a, fc_res in zip(adj, result):
        h = pd.Timestamp(fc_a.ts).hour
        if 10 <= h <= 18:
            assert fc_res.forecast_mw == pytest.approx(fc_a.forecast_mw)


def test_guard_does_not_add_warm_day_offset_when_adjuster_already_raises():
    """A positive analogous-day shift is trusted without extra warm-day offset."""
    guard = PostHolidayTimeBandGuard(_guard_config(
        warm_day=True,
        warm_day_offset=250.0,
    ))
    target = date(2026, 5, 14)
    raw = _make_raw_forecasts(target, 28_000.0)
    adj = []
    for fc in raw:
        h = pd.Timestamp(fc.ts).hour
        bump = 300.0 if 10 <= h <= 18 else 0.0
        from python.forecast.baseline import HourlyForecast
        adj.append(HourlyForecast(
            ts=fc.ts,
            forecast_mw=fc.forecast_mw + bump,
            p95_lower_mw=fc.p95_lower_mw + bump,
            p95_upper_mw=fc.p95_upper_mw + bump,
            p99_lower_mw=fc.p99_lower_mw + bump,
            p99_upper_mw=fc.p99_upper_mw + bump,
        ))
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"].between(10, 18), "temp_c"] = 22.5
    inf.loc[inf["hour"].between(10, 18), "temp_anomaly_doy"] = 1.5

    result = guard.apply(raw, adj, inf)

    for fc_a, fc_res in zip(adj, result):
        h = pd.Timestamp(fc_a.ts).hour
        if 10 <= h <= 18:
            assert fc_res.forecast_mw == pytest.approx(fc_a.forecast_mw)


def test_guard_damps_warm_day_offset_when_evening_shape_is_declining():
    """Warm-day guard should not erase a declining analog shape in late afternoon."""
    guard = PostHolidayTimeBandGuard(_guard_config(
        warm_day=True,
        warm_day_offset=250.0,
    ))
    target = date(2026, 6, 1)
    raw = _make_raw_forecasts(target, 40_000.0)
    adj = []
    for fc in raw:
        h = pd.Timestamp(fc.ts).hour
        bump = -300.0 if h == 16 else 0.0
        from python.forecast.baseline import HourlyForecast
        adj.append(HourlyForecast(
            ts=fc.ts,
            forecast_mw=fc.forecast_mw + bump,
            p95_lower_mw=fc.p95_lower_mw + bump,
            p95_upper_mw=fc.p95_upper_mw + bump,
            p99_lower_mw=fc.p99_lower_mw + bump,
            p99_upper_mw=fc.p99_upper_mw + bump,
        ))
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"] == 16, "temp_c"] = 31.0
    inf.loc[inf["hour"] == 16, "temp_anomaly_doy"] = 3.0
    inf.loc[inf["hour"] == 16, "lag_24h_hourly_delta"] = 400.0
    inf.loc[inf["hour"] == 16, "recent_same_business_type_delta_mean"] = -380.0

    result = guard.apply(raw, adj, inf)

    assert result[16].forecast_mw == pytest.approx(39_700.0)
    assert result[16].p95_upper_mw == pytest.approx(40_700.0)


def test_guard_caps_warm_day_forecast_too_far_above_lag24():
    """Warm-day guard can prevent hot-day adjustments from drifting far above yesterday."""
    config = _guard_config(warm_day=True)
    daytime_config = config["adjustment"]["post_holiday_timeband_guard"]["daytime"]
    daytime_config["lag24_warm_day_cap_enabled"] = True
    daytime_config["lag24_warm_day_max_increase_mw"] = 2500.0
    guard = PostHolidayTimeBandGuard(config)
    target = date(2026, 5, 14)
    raw = _make_raw_forecasts(target, 38_000.0)
    adj = _make_raw_forecasts(target, 38_200.0)
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"].between(10, 18), "temp_c"] = 28.0
    inf.loc[inf["hour"].between(10, 18), "temp_anomaly_doy"] = 4.0
    inf.loc[inf["hour"].between(10, 18), "lag_24h"] = 34_000.0

    result = guard.apply(raw, adj, inf)

    assert result[11].forecast_mw == pytest.approx(36_500.0)
    assert result[11].p95_upper_mw == pytest.approx(37_500.0)
    assert result[9].forecast_mw == pytest.approx(38_200.0)


def test_guard_relaxes_lag24_cap_when_current_day_is_much_hotter_than_yesterday():
    """Large 24h cooling deltas should not force a warm business-day ramp below shape."""
    config = _guard_config(warm_day=True)
    daytime_config = config["adjustment"]["post_holiday_timeband_guard"]["daytime"]
    daytime_config["lag24_warm_day_cap_enabled"] = True
    daytime_config["lag24_warm_day_max_increase_mw"] = 2_500.0
    daytime_config["lag24_warm_day_weather_allowance_mw_per_c"] = 1_200.0
    daytime_config["lag24_warm_day_max_weather_allowance_mw"] = 5_000.0
    guard = PostHolidayTimeBandGuard(config)
    target = date(2026, 7, 14)
    raw = _make_raw_forecasts(target, 46_549.0)
    adj = _make_raw_forecasts(target, 46_549.0)
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"].between(10, 18), "temp_c"] = 31.0
    inf.loc[inf["hour"].between(10, 18), "temp_anomaly_doy"] = 4.0
    inf.loc[inf["hour"].between(10, 18), "lag_24h"] = 40_340.0
    inf.loc[inf["hour"].between(10, 18), "temp_delta_24h"] = 3.8
    inf.loc[inf["hour"].between(10, 18), "cooling_delta_24h"] = 3.8

    result = guard.apply(raw, adj, inf)

    assert 40_340.0 + 2_500.0 == pytest.approx(42_840.0)
    assert result[10].forecast_mw == pytest.approx(46_549.0)
    assert result[10].p95_upper_mw == pytest.approx(47_549.0)


def test_guard_skips_lag24_cap_when_previous_day_business_type_differs():
    """Do not cap a Monday business-day recovery against Sunday's low lag_24h."""
    config = _guard_config(warm_day=True)
    daytime_config = config["adjustment"]["post_holiday_timeband_guard"]["daytime"]
    guard_config = config["adjustment"]["post_holiday_timeband_guard"]
    daytime_config["lag24_warm_day_cap_enabled"] = True
    daytime_config["lag24_warm_day_max_increase_mw"] = 2500.0
    guard_config["business_return_anchor_excess_cap"]["enabled"] = False
    guard = PostHolidayTimeBandGuard(config)
    target = date(2026, 5, 25)  # Monday after a non-business day
    raw = _make_raw_forecasts(target, 33_000.0)
    adj = _make_raw_forecasts(target, 33_200.0)
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"].between(10, 18), "temp_c"] = 28.0
    inf.loc[inf["hour"].between(10, 18), "temp_anomaly_doy"] = 4.0
    inf.loc[inf["hour"].between(10, 18), "lag_24h"] = 28_000.0
    inf.loc[inf["hour"].between(10, 18), "lag_24h_business_type_mismatch"] = 1
    inf.loc[inf["hour"].between(10, 18), "recent_same_business_type_mean"] = 32_000.0

    result = guard.apply(raw, adj, inf)

    assert result[11].forecast_mw == pytest.approx(33_200.0)
    assert result[11].p95_upper_mw == pytest.approx(34_200.0)


def test_guard_lifts_business_return_anchor_shortfall():
    """Business return guard restores part of a Monday 09:00 anchor shortfall."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 5, 25)
    raw = _make_raw_forecasts(target, 29_570.0)
    adj = _make_raw_forecasts(target, 29_570.0)
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"] == 9, "lag_24h"] = 22_830.0
    inf.loc[inf["hour"] == 9, "recent_same_business_type_mean"] = 31_795.0
    inf.loc[inf["hour"] == 9, "recent_same_business_type_delta_mean"] = 1_500.0
    inf.loc[inf["hour"] == 9, "lag_24h_business_type_mismatch"] = 1

    result = guard.apply(raw, adj, inf)

    assert result[9].forecast_mw == pytest.approx(30_182.5)
    assert result[9].p95_lower_mw == pytest.approx(29_182.5)
    assert result[9].p95_upper_mw == pytest.approx(31_182.5)
    assert result[8].forecast_mw == pytest.approx(29_570.0)


def test_guard_skips_business_return_lift_when_shape_is_already_supported():
    """Business return level anchor should not lift an already healthy morning ramp."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 6, 8)
    raw = _make_raw_forecasts(target, 30_000.0)
    adj = _make_raw_forecasts(target, 30_000.0)
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)

    for h, value in {8: 28_477.3, 9: 30_800.7, 10: 31_143.4}.items():
        raw[h] = HourlyForecast(
            ts=raw[h].ts,
            forecast_mw=value,
            p95_lower_mw=value - 1_000.0,
            p95_upper_mw=value + 1_000.0,
            p99_lower_mw=value - 1_500.0,
            p99_upper_mw=value + 1_500.0,
        )
        adj[h] = HourlyForecast(
            ts=adj[h].ts,
            forecast_mw=value,
            p95_lower_mw=value - 1_000.0,
            p95_upper_mw=value + 1_000.0,
            p99_lower_mw=value - 1_500.0,
            p99_upper_mw=value + 1_500.0,
        )

    inf.loc[inf["hour"] == 9, "lag_24h"] = 22_830.0
    inf.loc[inf["hour"] == 9, "recent_same_business_type_mean"] = 32_000.0
    inf.loc[inf["hour"] == 9, "recent_same_business_type_delta_mean"] = 2_938.8
    inf.loc[inf["hour"] == 9, "lag_24h_business_type_mismatch"] = 1

    result = guard.apply(raw, adj, inf)

    assert result[9].forecast_mw == pytest.approx(30_800.7)
    assert result[9].p95_upper_mw == pytest.approx(31_800.7)


def test_guard_caps_business_return_anchor_excess():
    """Business return guard trims excessive morning overshoot against same-type anchor."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 6, 1)
    raw = _make_raw_forecasts(target, 37_000.0)
    adj = _make_raw_forecasts(target, 37_000.0)
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"] == 9, "lag_24h"] = 33_000.0
    inf.loc[inf["hour"] == 9, "recent_same_business_type_mean"] = 35_000.0
    inf.loc[inf["hour"] == 9, "lag_24h_business_type_mismatch"] = 1
    inf.loc[inf["hour"] == 9, "temp_delta_24h"] = 1.0
    inf.loc[inf["hour"] == 9, "temp_anomaly_doy"] = 0.0

    result = guard.apply(raw, adj, inf)

    # upper bound = 35000 + 500 + 100; excess 1400 * 0.6 = 840
    assert result[9].forecast_mw == pytest.approx(36_160.0)
    assert result[9].p95_lower_mw == pytest.approx(35_160.0)
    assert result[8].forecast_mw == pytest.approx(37_000.0)


def test_guard_caps_business_return_anchor_excess_at_11():
    """The excess cap also covers the late morning handoff hour."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 6, 8)
    raw = _make_raw_forecasts(target, 36_000.0)
    adj = _make_raw_forecasts(target, 36_000.0)
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"] == 11, "lag_24h"] = 30_000.0
    inf.loc[inf["hour"] == 11, "recent_same_business_type_mean"] = 34_000.0
    inf.loc[inf["hour"] == 11, "lag_24h_business_type_mismatch"] = 1
    inf.loc[inf["hour"] == 11, "temp_delta_24h"] = 1.0
    inf.loc[inf["hour"] == 11, "temp_anomaly_doy"] = 0.0

    result = guard.apply(raw, adj, inf)

    # upper bound = 34000 + 500 + 100; excess 1400 * 0.6 = 840
    assert result[11].forecast_mw == pytest.approx(35_160.0)
    assert result[11].p95_lower_mw == pytest.approx(34_160.0)


def test_guard_softens_business_return_excess_cap_when_shape_supports_ramp():
    """A Monday return cap should not erase a supported warm morning ramp."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 6, 22)
    raw = _make_raw_forecasts(target, 35_590.4)
    adj = _make_raw_forecasts(target, 35_590.4)
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"] == 10, "lag_24h"] = 28_000.0
    inf.loc[inf["hour"] == 10, "recent_same_business_type_mean"] = 33_790.4
    inf.loc[inf["hour"] == 10, "lag_24h_business_type_mismatch"] = 1
    inf.loc[inf["hour"] == 10, "temp_delta_24h"] = 1.6
    inf.loc[inf["hour"] == 10, "temp_anomaly_doy"] = 0.0
    inf.loc[inf["hour"] == 10, "lag_24h_hourly_delta"] = 750.0
    inf.loc[inf["hour"] == 10, "recent_same_business_type_delta_mean"] = 777.5

    result = guard.apply(raw, adj, inf)

    # Old cap hit max clipping (900 MW). Shape-supported cap leaves more ramp energy.
    assert result[10].forecast_mw == pytest.approx(35_373.4)
    assert result[10].forecast_mw > 35_000.0


def test_guard_caps_business_afternoon_analog_excess_when_shape_support_is_weak():
    """Analogous-day uplift should not create an unsupported afternoon plateau."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 6, 22)
    raw = _make_raw_forecasts(target, 35_923.9)
    adj = _make_raw_forecasts(target, 37_039.7)
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"] == 13, "is_non_business_day"] = 0
    inf.loc[inf["hour"] == 13, "lag_24h_hourly_delta"] = 300.0
    inf.loc[inf["hour"] == 13, "recent_same_business_type_delta_mean"] = 898.8
    inf.loc[inf["hour"] == 13, "cooling_delta_24h"] = 2.0
    inf.loc[inf["hour"] == 13, "temp_delta_24h"] = 0.0

    result = guard.apply(raw, adj, inf)

    # allowed shift = 300 + min(2.0 * 120, 300) = 540 MW
    assert result[13].forecast_mw == pytest.approx(36_463.9)
    assert result[12].forecast_mw == pytest.approx(37_039.7)


def test_guard_caps_declining_business_analog_uplift():
    """A positive analog shift must not fight a supported business-day decline."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 7, 17)
    raw = _make_raw_forecasts(target, 42_524.9)
    adjusted = _make_raw_forecasts(target, 42_524.9)
    adjusted[19] = HourlyForecast(
        ts=raw[19].ts,
        forecast_mw=43_616.4,
        p95_lower_mw=42_616.4,
        p95_upper_mw=44_616.4,
        p99_lower_mw=42_116.4,
        p99_upper_mw=45_116.4,
    )
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[19, "lag_24h_business_type_mismatch"] = 0
    inf.loc[19, "lag_24h_hourly_delta"] = -1_590.0
    inf.loc[19, "recent_same_business_type_delta_mean"] = -1_233.8
    inf.loc[19, "temp_delta_24h"] = -2.1
    inf.loc[19, "cooling_delta_24h"] = -2.1
    inf.loc[19, "apparent_cooling_delta_24h"] = -1.8

    result = guard.apply(raw, adjusted, inf)

    assert result[19].forecast_mw == pytest.approx(42_624.9)
    assert result[19].p95_lower_mw == pytest.approx(41_624.9)


@pytest.mark.parametrize(
    ("is_non_business_day", "mismatch", "lag_delta", "recent_delta", "weather_delta"),
    [
        (1, 0, -1_500.0, -1_200.0, -2.0),
        (0, 1, -1_500.0, -1_200.0, -2.0),
        (0, 0, 500.0, -1_200.0, -2.0),
        (0, 0, -1_500.0, -1_200.0, 1.0),
    ],
)
def test_guard_keeps_analog_uplift_outside_declining_business_regime(
    is_non_business_day,
    mismatch,
    lag_delta,
    recent_delta,
    weather_delta,
):
    """Weekend, transition, rising-shape, and warmer regimes keep the analog signal."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    raw = _make_raw_forecasts(date(2026, 7, 17), 42_000.0)
    adjusted = _make_raw_forecasts(date(2026, 7, 17), 42_800.0)
    inf = _make_post_holiday_inf(
        consec=0,
        dsh=8,
        temp_anomaly_daytime=0.5,
        is_non_business_day=is_non_business_day,
    )
    inf.loc[19, "lag_24h_business_type_mismatch"] = mismatch
    inf.loc[19, "lag_24h_hourly_delta"] = lag_delta
    inf.loc[19, "recent_same_business_type_delta_mean"] = recent_delta
    inf.loc[19, "temp_delta_24h"] = weather_delta
    inf.loc[19, "cooling_delta_24h"] = weather_delta
    inf.loc[19, "apparent_cooling_delta_24h"] = weather_delta

    result = guard.apply(raw, adjusted, inf)

    assert result[19].forecast_mw == pytest.approx(42_800.0)


def test_guard_caps_business_afternoon_analog_downshift_on_warm_business_day():
    """Warm business afternoons should not inherit an unsupported analog downshift."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 6, 29)
    raw = _make_raw_forecasts(target, 34_131.8)
    adjusted = _make_raw_forecasts(target, 34_131.8)
    adjusted[15] = HourlyForecast(
        ts=raw[15].ts,
        forecast_mw=32_484.8,
        p95_lower_mw=31_484.8,
        p95_upper_mw=33_484.8,
        p99_lower_mw=30_984.8,
        p99_upper_mw=33_984.8,
    )
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[15, "is_non_business_day"] = 0
    inf.loc[15, "lag_24h_hourly_delta"] = -210.0
    inf.loc[15, "recent_same_business_type_delta_mean"] = -357.5
    inf.loc[15, "recent_same_business_type_mean"] = 35_000.0
    inf.loc[15, "cooling_delta_24h"] = 3.0
    inf.loc[15, "temp_delta_24h"] = 2.0
    inf.loc[15, "apparent_cooling_delta_24h"] = 2.5

    result = guard.apply(raw, adjusted, inf)

    assert result[15].forecast_mw == pytest.approx(33_831.8)
    assert result[15].p95_lower_mw == pytest.approx(32_831.8)


def test_guard_keeps_business_afternoon_downshift_when_shape_clearly_declines():
    """A strong decline signal should still be allowed to keep an analog downshift."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 6, 29)
    raw = _make_raw_forecasts(target, 34_000.0)
    adjusted = _make_raw_forecasts(target, 34_000.0)
    adjusted[15] = HourlyForecast(
        ts=raw[15].ts,
        forecast_mw=32_900.0,
        p95_lower_mw=31_900.0,
        p95_upper_mw=33_900.0,
        p99_lower_mw=31_400.0,
        p99_upper_mw=34_400.0,
    )
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[15, "is_non_business_day"] = 0
    inf.loc[15, "lag_24h_hourly_delta"] = -1_200.0
    inf.loc[15, "recent_same_business_type_delta_mean"] = -950.0
    inf.loc[15, "recent_same_business_type_mean"] = 34_500.0
    inf.loc[15, "cooling_delta_24h"] = 3.0

    result = guard.apply(raw, adjusted, inf)

    assert result[15] is adjusted[15]


def test_guard_does_not_lift_business_return_without_mismatch():
    """Business return guard stays isolated on ordinary business-day sequences."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    target = date(2026, 5, 26)
    raw = _make_raw_forecasts(target, 29_570.0)
    adj = _make_raw_forecasts(target, 29_570.0)
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"] == 9, "lag_24h"] = 22_830.0
    inf.loc[inf["hour"] == 9, "recent_same_business_type_mean"] = 31_795.0
    inf.loc[inf["hour"] == 9, "lag_24h_business_type_mismatch"] = 0

    result = guard.apply(raw, adj, inf)

    assert result is adj
    assert result[9].forecast_mw == pytest.approx(29_570.0)


def test_guard_business_return_off_keeps_other_guards_active():
    """Disabling business return shortfall must not disable the warm-day guard."""
    guard = PostHolidayTimeBandGuard(_guard_config(
        warm_day=True,
        warm_day_offset=250.0,
        business_return_enabled=False,
    ))
    target = date(2026, 5, 25)
    raw = _make_raw_forecasts(target, 29_570.0)
    adj = _make_raw_forecasts(target, 29_570.0)
    inf = _make_post_holiday_inf(consec=0, dsh=8, temp_anomaly_daytime=0.5)
    inf.loc[inf["hour"] == 9, "lag_24h"] = 22_830.0
    inf.loc[inf["hour"] == 9, "recent_same_business_type_mean"] = 31_795.0
    inf.loc[inf["hour"] == 9, "lag_24h_business_type_mismatch"] = 1
    inf.loc[inf["hour"] == 10, "temp_c"] = 28.0
    inf.loc[inf["hour"] == 10, "temp_anomaly_doy"] = 4.0

    result = guard.apply(raw, adj, inf)

    assert result[9].forecast_mw == pytest.approx(29_570.0)
    assert result[10].forecast_mw == pytest.approx(29_820.0)


def test_guard_caps_non_business_analog_downshift_when_ramp_is_supported():
    """Weekend analog shifts should not erase a supported same-day ramp."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    raw = _make_raw_forecasts(date(2026, 6, 13), 25_000.0)
    adjusted = _make_raw_forecasts(date(2026, 6, 13), 25_000.0)
    adjusted[9] = HourlyForecast(
        ts=raw[9].ts,
        forecast_mw=23_900.0,
        p95_lower_mw=22_900.0,
        p95_upper_mw=24_900.0,
        p99_lower_mw=22_400.0,
        p99_upper_mw=25_400.0,
    )
    inf = _make_post_holiday_inf(is_non_business_day=1)
    inf.loc[9, "lag_24h_hourly_delta"] = 3_790.0
    inf.loc[9, "recent_same_business_type_delta_mean"] = 1_628.8
    inf.loc[9, "recent_same_business_type_mean"] = 26_000.0

    result = guard.apply(raw, adjusted, inf)

    assert result[9].forecast_mw == pytest.approx(25_000.0)
    assert result[9].p95_lower_mw == pytest.approx(24_000.0)


def test_guard_caps_non_business_afternoon_analog_downshift_when_anchor_supports_plateau():
    """Weekend afternoon analog downshifts should not erase an anchor-supported plateau."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    raw = _make_raw_forecasts(date(2026, 6, 21), 28_135.7)
    adjusted = _make_raw_forecasts(date(2026, 6, 21), 28_135.7)
    adjusted[14] = HourlyForecast(
        ts=raw[14].ts,
        forecast_mw=27_485.1,
        p95_lower_mw=26_485.1,
        p95_upper_mw=28_485.1,
        p99_lower_mw=25_985.1,
        p99_upper_mw=28_985.1,
    )
    inf = _make_post_holiday_inf(
        consec=0,
        dsh=8,
        temp_anomaly_daytime=0.5,
        is_non_business_day=1,
    )
    inf.loc[14, "lag_24h_hourly_delta"] = -10.0
    inf.loc[14, "recent_same_business_type_delta_mean"] = -236.2
    inf.loc[14, "recent_same_business_type_mean"] = 28_800.0

    result = guard.apply(raw, adjusted, inf)

    assert result[14].forecast_mw == pytest.approx(28_135.7)
    assert result[14].p95_lower_mw == pytest.approx(27_135.7)


def test_guard_keeps_non_business_analog_downshift_without_shape_support():
    """Declining weekend afternoon shape can keep the analog downward shift."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    raw = _make_raw_forecasts(date(2026, 6, 13), 25_000.0)
    adjusted = _make_raw_forecasts(date(2026, 6, 13), 25_000.0)
    adjusted[14] = HourlyForecast(
        ts=raw[14].ts,
        forecast_mw=23_900.0,
        p95_lower_mw=22_900.0,
        p95_upper_mw=24_900.0,
        p99_lower_mw=22_400.0,
        p99_upper_mw=25_400.0,
    )
    inf = _make_post_holiday_inf(
        consec=0,
        dsh=8,
        temp_anomaly_daytime=0.5,
        is_non_business_day=1,
    )
    inf.loc[14, "lag_24h_hourly_delta"] = -1_750.0
    inf.loc[14, "recent_same_business_type_delta_mean"] = -110.0
    inf.loc[14, "recent_same_business_type_mean"] = 23_000.0

    result = guard.apply(raw, adjusted, inf)

    assert result[14] is adjusted[14]


def test_guard_lifts_non_business_morning_shape_floor_when_drop_is_unsupported():
    """A weekend 06:00 trough should be softened when lag/recent shape is flat."""
    guard = PostHolidayTimeBandGuard(_guard_config())
    raw = _make_raw_forecasts(date(2026, 6, 21), 22_000.0)
    adjusted = _make_raw_forecasts(date(2026, 6, 21), 22_000.0)
    adjusted[5] = HourlyForecast(
        ts=raw[5].ts,
        forecast_mw=21_640.8,
        p95_lower_mw=20_640.8,
        p95_upper_mw=22_640.8,
        p99_lower_mw=20_140.8,
        p99_upper_mw=23_140.8,
    )
    adjusted[6] = HourlyForecast(
        ts=raw[6].ts,
        forecast_mw=20_492.9,
        p95_lower_mw=19_492.9,
        p95_upper_mw=21_492.9,
        p99_lower_mw=18_992.9,
        p99_upper_mw=21_992.9,
    )
    inf = _make_post_holiday_inf(
        consec=0,
        dsh=8,
        temp_anomaly_morning=0.5,
        temp_anomaly_daytime=0.5,
        is_non_business_day=1,
    )
    inf.loc[6, "lag_24h_hourly_delta"] = -10.0
    inf.loc[6, "recent_same_business_type_delta_mean"] = -263.8

    result = guard.apply(raw, adjusted, inf)

    assert result[6].forecast_mw == pytest.approx(21_158.8)
    assert result[6].p95_lower_mw == pytest.approx(20_158.8)


# ---------------------------------------------------------------------------
# Midday transition guard
# ---------------------------------------------------------------------------

def _midday_guard_config(**overrides) -> dict:
    guard_config = {
        "enabled": True,
        "hours": [12],
        "min_negative_delta_mw": 500.0,
        "min_excess_mw": 300.0,
        "shrinkage": 0.5,
        "max_downward_adjustment_mw": 900.0,
    }
    guard_config.update(overrides)
    return {"adjustment": {"midday_transition_guard": guard_config}}


def _midday_inf(
    is_non_business_day: int = 0,
    lag_delta: float = -900.0,
    recent_delta: float = -800.0,
    recent_delta_q25: float | None = None,
    same_day_latest_hour: float = np.nan,
    same_day_latest_delta: float = np.nan,
    same_day_recent_delta: float = np.nan,
) -> pd.DataFrame:
    if recent_delta_q25 is None:
        recent_delta_q25 = recent_delta
    rows = []
    for hour in range(24):
        rows.append({
            "hour": hour,
            "is_non_business_day": is_non_business_day,
            "lag_24h_hourly_delta": lag_delta if hour == 12 else 0.0,
            "recent_same_business_type_delta_mean": (
                recent_delta if hour == 12 else 0.0
            ),
            "recent_same_business_type_delta_q25": (
                recent_delta_q25 if hour == 12 else 0.0
            ),
            "same_day_latest_actual_hour": (
                same_day_latest_hour if hour == 12 else np.nan
            ),
            "same_day_latest_hourly_delta": (
                same_day_latest_delta if hour == 12 else np.nan
            ),
            "same_day_recent_hourly_delta_mean": (
                same_day_recent_delta if hour == 12 else np.nan
            ),
        })
    return pd.DataFrame(rows)


def test_midday_transition_guard_dampens_unsupported_noon_jump():
    target = date(2026, 5, 20)
    forecasts = _make_raw_forecasts(target, 35_000.0)
    forecasts[11] = HourlyForecast(
        ts=forecasts[11].ts,
        forecast_mw=36_000.0,
        p95_lower_mw=35_000.0,
        p95_upper_mw=37_000.0,
        p99_lower_mw=34_000.0,
        p99_upper_mw=38_000.0,
    )
    forecasts[12] = HourlyForecast(
        ts=forecasts[12].ts,
        forecast_mw=37_400.0,
        p95_lower_mw=36_400.0,
        p95_upper_mw=38_400.0,
        p99_lower_mw=35_900.0,
        p99_upper_mw=38_900.0,
    )

    result = MiddayTransitionGuard(_midday_guard_config()).apply(
        forecasts,
        _midday_inf(),
    )

    assert result[12].forecast_mw == pytest.approx(36_500.0)
    assert result[12].p95_lower_mw == pytest.approx(35_500.0)
    assert result[11].forecast_mw == pytest.approx(36_000.0)


def test_midday_transition_guard_ignores_non_business_day():
    target = date(2026, 5, 23)
    forecasts = _make_raw_forecasts(target, 35_000.0)
    forecasts[12] = HourlyForecast(
        ts=forecasts[12].ts,
        forecast_mw=37_400.0,
        p95_lower_mw=36_400.0,
        p95_upper_mw=38_400.0,
        p99_lower_mw=35_900.0,
        p99_upper_mw=38_900.0,
    )

    result = MiddayTransitionGuard(_midday_guard_config()).apply(
        forecasts,
        _midday_inf(is_non_business_day=1),
    )

    assert result is forecasts


def test_midday_transition_guard_requires_recent_negative_shape():
    target = date(2026, 5, 20)
    forecasts = _make_raw_forecasts(target, 35_000.0)
    forecasts[12] = HourlyForecast(
        ts=forecasts[12].ts,
        forecast_mw=37_400.0,
        p95_lower_mw=36_400.0,
        p95_upper_mw=38_400.0,
        p99_lower_mw=35_900.0,
        p99_upper_mw=38_900.0,
    )

    result = MiddayTransitionGuard(_midday_guard_config()).apply(
        forecasts,
        _midday_inf(lag_delta=-200.0, recent_delta=-100.0),
    )

    assert result is not forecasts
    assert result[12].forecast_mw == pytest.approx(37_400.0)


def test_midday_transition_guard_uses_lower_recent_quantile_when_same_day_softens():
    target = date(2026, 5, 20)
    forecasts = _make_raw_forecasts(target, 35_000.0)
    forecasts[11] = HourlyForecast(
        ts=forecasts[11].ts,
        forecast_mw=36_000.0,
        p95_lower_mw=35_000.0,
        p95_upper_mw=37_000.0,
        p99_lower_mw=34_000.0,
        p99_upper_mw=38_000.0,
    )
    forecasts[12] = HourlyForecast(
        ts=forecasts[12].ts,
        forecast_mw=35_700.0,
        p95_lower_mw=34_700.0,
        p95_upper_mw=36_700.0,
        p99_lower_mw=34_200.0,
        p99_upper_mw=37_200.0,
    )

    result = MiddayTransitionGuard(_midday_guard_config()).apply(
        forecasts,
        _midday_inf(
            lag_delta=-200.0,
            recent_delta=-650.0,
            recent_delta_q25=-1_000.0,
            same_day_latest_hour=11.0,
            same_day_latest_delta=-700.0,
            same_day_recent_delta=-370.0,
        ),
    )

    # Previous hour 36,000 + q25 transition -1,000 = 35,000 target.
    # Triggered shrinkage 0.75 moves 35,700 down by 525 MW.
    assert result[12].forecast_mw == pytest.approx(35_175.0)


def test_midday_transition_guard_does_not_use_quantile_without_same_day_softening():
    target = date(2026, 5, 20)
    forecasts = _make_raw_forecasts(target, 35_000.0)
    forecasts[11] = HourlyForecast(
        ts=forecasts[11].ts,
        forecast_mw=36_000.0,
        p95_lower_mw=35_000.0,
        p95_upper_mw=37_000.0,
        p99_lower_mw=34_000.0,
        p99_upper_mw=38_000.0,
    )
    forecasts[12] = HourlyForecast(
        ts=forecasts[12].ts,
        forecast_mw=35_700.0,
        p95_lower_mw=34_700.0,
        p95_upper_mw=36_700.0,
        p99_lower_mw=34_200.0,
        p99_upper_mw=37_200.0,
    )

    result = MiddayTransitionGuard(_midday_guard_config()).apply(
        forecasts,
        _midday_inf(
            lag_delta=-200.0,
            recent_delta=-650.0,
            recent_delta_q25=-1_000.0,
            same_day_latest_hour=11.0,
            same_day_latest_delta=-100.0,
            same_day_recent_delta=-50.0,
        ),
    )

    # Without same-day softening, the guard keeps using the mean transition.
    assert result[12].forecast_mw == pytest.approx(35_525.0)


# ---------------------------------------------------------------------------
# Localized shape spike guard
# ---------------------------------------------------------------------------

def _localized_spike_config(**overrides) -> dict:
    guard_config = {
        "enabled": True,
        "business_day_only": True,
        "hours": [13, 14, 15, 16, 17],
        "min_neighbor_excess_mw": 600.0,
        "neighbor_buffer_mw": 450.0,
        "max_supporting_delta_mw": 500.0,
        "max_weather_delta_c": 2.0,
        "max_same_day_slope_mw": 900.0,
        "shrinkage": 0.75,
        "max_reduction_mw": 700.0,
        "min_reduction_mw": 100.0,
    }
    guard_config.update(overrides)
    return {"adjustment": {"localized_shape_spike_guard": guard_config}}


def _localized_spike_inf(
    is_non_business_day: int = 0,
    lag_delta: float = 180.0,
    recent_delta: float = -300.0,
    temp_delta: float = 0.8,
    cooling_delta: float = 0.8,
    same_day_slope: float = 670.0,
) -> pd.DataFrame:
    rows = []
    for hour in range(24):
        rows.append({
            "hour": hour,
            "is_non_business_day": is_non_business_day,
            "lag_24h_hourly_delta": lag_delta,
            "recent_same_business_type_delta_mean": recent_delta,
            "temp_delta_24h": temp_delta,
            "cooling_delta_24h": cooling_delta,
            "same_day_latest_hourly_delta": same_day_slope,
        })
    return pd.DataFrame(rows)


def test_localized_shape_spike_guard_dampens_unsupported_single_hour_peak():
    target = date(2026, 6, 10)
    forecasts = _make_raw_forecasts(target, 30_700.0)
    forecasts[14] = HourlyForecast(
        ts=forecasts[14].ts,
        forecast_mw=30_700.0,
        p95_lower_mw=29_700.0,
        p95_upper_mw=31_700.0,
        p99_lower_mw=29_200.0,
        p99_upper_mw=32_200.0,
    )
    forecasts[15] = HourlyForecast(
        ts=forecasts[15].ts,
        forecast_mw=31_759.3,
        p95_lower_mw=30_759.3,
        p95_upper_mw=32_759.3,
        p99_lower_mw=30_259.3,
        p99_upper_mw=33_259.3,
    )
    forecasts[16] = HourlyForecast(
        ts=forecasts[16].ts,
        forecast_mw=30_933.0,
        p95_lower_mw=29_933.0,
        p95_upper_mw=31_933.0,
        p99_lower_mw=29_433.0,
        p99_upper_mw=32_433.0,
    )

    result = LocalizedShapeSpikeGuard(_localized_spike_config()).apply(
        forecasts,
        _localized_spike_inf(),
    )

    assert result[15].forecast_mw == pytest.approx(31_389.7)
    assert result[15].p95_upper_mw == pytest.approx(32_389.7)
    assert result[14].forecast_mw == pytest.approx(30_700.0)
    assert result[16].forecast_mw == pytest.approx(30_933.0)


def test_localized_shape_spike_guard_keeps_weather_supported_peak():
    target = date(2026, 6, 10)
    forecasts = _make_raw_forecasts(target, 30_700.0)
    forecasts[15] = HourlyForecast(
        ts=forecasts[15].ts,
        forecast_mw=31_759.3,
        p95_lower_mw=30_759.3,
        p95_upper_mw=32_759.3,
        p99_lower_mw=30_259.3,
        p99_upper_mw=33_259.3,
    )

    result = LocalizedShapeSpikeGuard(_localized_spike_config()).apply(
        forecasts,
        _localized_spike_inf(temp_delta=3.0, cooling_delta=3.0),
    )

    assert result is forecasts
    assert result[15].forecast_mw == pytest.approx(31_759.3)


def test_localized_shape_spike_guard_dampens_business_morning_pre_observation_spike():
    target = date(2026, 7, 3)
    forecasts = _make_raw_forecasts(target, 30_000.0)
    for hour, value in {
        8: 31_476.7,
        9: 36_047.8,
        10: 34_497.6,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=forecasts[hour].ts,
            forecast_mw=value,
            p95_lower_mw=value - 1_000.0,
            p95_upper_mw=value + 1_000.0,
            p99_lower_mw=value - 1_500.0,
            p99_upper_mw=value + 1_500.0,
        )
    inference_features = _localized_spike_inf(
        lag_delta=2_460.0,
        recent_delta=2_982.5,
        temp_delta=2.7,
        cooling_delta=2.7,
        same_day_slope=0.0,
    )

    result = LocalizedShapeSpikeGuard(_localized_spike_config(
        morning_spike={
            "enabled": True,
            "hours": [8, 9, 10, 11],
            "min_neighbor_excess_mw": 1_000.0,
            "min_forecast_delta_over_support_mw": 1_000.0,
            "min_next_drop_mw": 800.0,
            "neighbor_buffer_mw": 700.0,
            "max_weather_delta_c": 3.5,
            "shrinkage": 0.75,
            "max_reduction_mw": 1_400.0,
            "min_reduction_mw": 150.0,
        },
    )).apply(
        forecasts,
        inference_features,
    )

    assert result[9].forecast_mw == pytest.approx(34_647.8)
    assert result[9].p95_lower_mw == pytest.approx(33_647.8)
    assert result[8].forecast_mw == pytest.approx(31_476.7)
    assert result[10].forecast_mw == pytest.approx(34_497.6)


def test_localized_shape_spike_guard_dampens_warm_morning_slope_overreaction():
    target = date(2026, 7, 16)
    forecasts = _make_raw_forecasts(target, 30_000.0)
    for hour, value in {
        7: 35_094.2,
        8: 42_369.9,
        9: 48_196.1,
        10: 49_695.6,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=forecasts[hour].ts,
            forecast_mw=value,
            p95_lower_mw=value - 1_000.0,
            p95_upper_mw=value + 1_000.0,
            p99_lower_mw=value - 1_500.0,
            p99_upper_mw=value + 1_500.0,
        )
    inference_features = _localized_spike_inf(
        lag_delta=4_760.0,
        recent_delta=3_863.8,
        temp_delta=2.1,
        cooling_delta=2.1,
        same_day_slope=0.0,
    )
    inference_features["discomfort_delta_24h"] = 3.2

    result = LocalizedShapeSpikeGuard(_localized_spike_config(
        morning_spike={
            "enabled": True,
            "hours": [8, 9, 10],
            "min_neighbor_excess_mw": 1_000.0,
            "min_forecast_delta_over_support_mw": 1_000.0,
            "min_next_drop_mw": 800.0,
            "neighbor_buffer_mw": 400.0,
            "max_weather_delta_c": 3.5,
            "shrinkage": 0.75,
            "max_reduction_mw": 1_400.0,
            "min_reduction_mw": 100.0,
            "slope_overreaction": {
                "enabled": True,
                "min_forecast_delta_mw": 4_000.0,
                "min_forecast_delta_over_support_mw": 900.0,
                "min_weather_delta_c": 1.5,
                "min_discomfort_delta": 2.0,
                "max_weather_delta_c": 6.0,
            },
        },
    )).apply(
        forecasts,
        inference_features,
    )

    assert result[8].forecast_mw == pytest.approx(42_126.3)
    assert result[9].forecast_mw == pytest.approx(46_796.1)
    assert result[10].forecast_mw == pytest.approx(49_695.6)


def test_localized_shape_spike_guard_keeps_cooler_well_matched_morning_ramp():
    target = date(2026, 7, 15)
    forecasts = _make_raw_forecasts(target, 30_000.0)
    for hour, value in {
        8: 39_822.2,
        9: 45_884.7,
        10: 47_442.4,
    }.items():
        forecasts[hour] = HourlyForecast(
            ts=forecasts[hour].ts,
            forecast_mw=value,
            p95_lower_mw=value - 1_000.0,
            p95_upper_mw=value + 1_000.0,
            p99_lower_mw=value - 1_500.0,
            p99_upper_mw=value + 1_500.0,
        )
    inference_features = _localized_spike_inf(
        lag_delta=4_780.0,
        recent_delta=3_642.5,
        temp_delta=-2.2,
        cooling_delta=-2.2,
        same_day_slope=0.0,
    )
    inference_features["discomfort_delta_24h"] = -1.8

    result = LocalizedShapeSpikeGuard(_localized_spike_config(
        morning_spike={
            "enabled": True,
            "hours": [8, 9, 10],
            "neighbor_buffer_mw": 400.0,
            "shrinkage": 0.75,
            "slope_overreaction": {
                "enabled": True,
                "min_forecast_delta_mw": 4_000.0,
                "min_forecast_delta_over_support_mw": 900.0,
                "min_weather_delta_c": 1.5,
                "min_discomfort_delta": 2.0,
                "max_weather_delta_c": 6.0,
            },
        },
    )).apply(
        forecasts,
        inference_features,
    )

    assert result is forecasts
    assert result[9].forecast_mw == pytest.approx(45_884.7)
