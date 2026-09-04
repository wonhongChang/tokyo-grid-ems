"""Tests for leakage-safe rolling forecast-interval calibration."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from python.etl.run_batch import build_forecast_json
from python.forecast.baseline import HourlyForecast
from python.forecast.rolling_interval_calibration import (
    build_rolling_conformal_floor_profile,
    finite_sample_upper_quantile,
)


def _config(
    *,
    min_samples: int = 24,
    max_half_width: float = 3_000.0,
    width_scale: float = 1.0,
    served_target: bool = False,
) -> dict:
    config = {
        "interval_calibration": {
            "min_p95_half_width_mw": 500.0,
            "max_p95_half_width_mw": max_half_width,
            "p95_half_width_scale": width_scale,
            "max_p95_asymmetry_ratio": 2.5,
            "asymmetry_reference_half_width_mw": 900.0,
            "rolling_conformal_floor": {
                "enabled": True,
                "window_days": 28,
                "target_coverage": 0.95,
                "min_samples_per_band": min_samples,
            },
        }
    }
    if served_target:
        config["served_interval_calibration"] = {
            "enabled": True,
            "mode": "rolling_conformal_target_width",
            "recent_all_regime_window_days": 10,
            "recent_min_samples_per_band": 24,
            "safety_scale": 1.05,
            "max_p95_half_width_mw": 3_750.0,
        }
    return config


def _write_operating_day(
    out_dir: Path,
    target: date,
    *,
    morning_error_mw: float,
    fallback_hour: int | None = None,
) -> None:
    actual_dir = out_dir / "actual"
    forecast_dir = out_dir / "forecast"
    actual_dir.mkdir(parents=True, exist_ok=True)
    forecast_dir.mkdir(parents=True, exist_ok=True)

    actual_series = []
    forecast_series = []
    for hour in range(24):
        actual_point = {
            "ts": f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            "actualMw": 30_000.0,
        }
        if hour == fallback_hour:
            actual_point["actualSource"] = "tepco_forecast_fallback"
        actual_series.append(actual_point)
        error_mw = morning_error_mw if 6 <= hour <= 10 else 700.0
        forecast_series.append({
            "ts": f"{target.isoformat()}T{hour:02d}:00:00+09:00",
            "forecastMw": 30_000.0 + error_mw,
        })

    (actual_dir / f"{target.isoformat()}.json").write_text(
        json.dumps({"series": actual_series}),
        encoding="utf-8",
    )
    (forecast_dir / f"{target.isoformat()}.json").write_text(
        json.dumps({"series": forecast_series}),
        encoding="utf-8",
    )


def _write_state(out_dir: Path, finalized_dates: list[date]) -> None:
    (out_dir / ".etl_state.json").write_text(
        json.dumps({"okDates": [day.isoformat() for day in finalized_dates]}),
        encoding="utf-8",
    )


def _history(out_dir: Path, start: date, days: int) -> list[date]:
    finalized_dates: list[date] = []
    for offset in range(days):
        target = start + timedelta(days=offset)
        morning_error = 600.0 if target.weekday() >= 5 else 1_800.0
        _write_operating_day(
            out_dir,
            target,
            morning_error_mw=morning_error,
        )
        finalized_dates.append(target)
    _write_state(out_dir, finalized_dates)
    return finalized_dates


def test_finite_sample_upper_quantile_uses_conservative_rank():
    assert finite_sample_upper_quantile([1.0, 2.0, 3.0, 4.0], 0.8) == 4.0


def test_profile_uses_only_prior_finalized_same_regime_rows(tmp_path):
    finalized_dates = _history(tmp_path, date(2024, 1, 4), 28)
    target = date(2024, 2, 1)  # Thursday

    # A target-day outlier must never enter its own interval calibration, even
    # if a malformed state file already lists that date as finalized.
    _write_operating_day(tmp_path, target, morning_error_mw=20_000.0)
    _write_state(tmp_path, [*finalized_dates, target])
    profile = build_rolling_conformal_floor_profile(tmp_path, target, _config())

    assert profile is not None
    assert profile["availability"] == "ok"
    assert profile["targetRegime"] == "business"
    assert profile["floorsMwByTimeBand"]["morning"] == 1_800.0
    assert profile["contributingDates"] < 28
    assert profile["sampleHoursByTimeBand"]["morning"] == (
        profile["contributingDates"] * 5
    )
    assert profile["historyEnd"] == "2024-01-31"


def test_profile_fails_closed_when_finalized_history_is_incomplete(tmp_path):
    target = date(2024, 2, 1)
    historical_date = target - timedelta(days=1)
    _write_operating_day(
        tmp_path,
        historical_date,
        morning_error_mw=2_000.0,
        fallback_hour=23,
    )
    _write_state(tmp_path, [historical_date])

    profile = build_rolling_conformal_floor_profile(tmp_path, target, _config())

    assert profile is not None
    assert profile["availability"] == "insufficient_history"
    assert profile["floorsMwByTimeBand"] == {}
    assert profile["historyStart"] is None


def test_build_forecast_json_applies_floor_and_records_provenance(tmp_path):
    _history(tmp_path, date(2024, 1, 4), 28)
    target = date(2024, 2, 1)
    forecast = HourlyForecast(
        ts=f"{target.isoformat()}T09:00:00+09:00",
        forecast_mw=31_000.0,
        p95_lower_mw=30_500.0,
        p95_upper_mw=31_500.0,
        p99_lower_mw=30_000.0,
        p99_upper_mw=32_000.0,
    )

    payload = build_forecast_json(
        target,
        [forecast],
        _config(),
        out_dir=tmp_path,
    )
    point = payload["series"][0]

    assert point["p95LowerMw"] == 29_200.0
    assert point["p95UpperMw"] == 32_800.0
    assert payload["intervalCalibration"]["method"] == (
        "rolling_conformal_minimum_floor"
    )
    assert payload["intervalCalibration"]["source"] == (
        "finalized_actual_vs_served_forecast"
    )


def test_served_target_replaces_saturated_width_with_drift_safe_profile(tmp_path):
    finalized_dates = _history(tmp_path, date(2024, 1, 4), 28)
    target = date(2024, 2, 1)  # Thursday

    # The latest weekend does not belong to the target's business regime, but
    # it does belong to the short drift window. Its larger error must protect
    # the target width from a stale same-regime estimate.
    for historical_date in (date(2024, 1, 27), date(2024, 1, 28)):
        _write_operating_day(
            tmp_path,
            historical_date,
            morning_error_mw=2_500.0,
        )
    _write_state(tmp_path, finalized_dates)

    forecast = HourlyForecast(
        ts=f"{target.isoformat()}T09:00:00+09:00",
        forecast_mw=31_000.0,
        p95_lower_mw=28_000.0,
        p95_upper_mw=34_000.0,
        p99_lower_mw=25_000.0,
        p99_upper_mw=37_000.0,
    )
    payload = build_forecast_json(
        target,
        [forecast],
        _config(served_target=True),
        out_dir=tmp_path,
    )

    point = payload["series"][0]
    target_profile = payload["intervalCalibration"]["servedTarget"]
    assert target_profile["availability"] == "ok"
    assert target_profile["recentWidthsMwByTimeBand"]["morning"] == 2_500.0
    assert target_profile["targetWidthsMwByTimeBand"]["morning"] == 2_625.0
    assert point["p95LowerMw"] == 28_375.0
    assert point["p95UpperMw"] == 33_625.0


def test_served_target_fails_closed_to_existing_floor(tmp_path):
    _history(tmp_path, date(2024, 1, 4), 28)
    target = date(2024, 2, 1)
    config = _config(served_target=True)
    config["served_interval_calibration"]["recent_min_samples_per_band"] = 1_000
    forecast = HourlyForecast(
        ts=f"{target.isoformat()}T09:00:00+09:00",
        forecast_mw=31_000.0,
        p95_lower_mw=30_500.0,
        p95_upper_mw=31_500.0,
        p99_lower_mw=30_000.0,
        p99_upper_mw=32_000.0,
    )

    payload = build_forecast_json(target, [forecast], config, out_dir=tmp_path)

    assert payload["intervalCalibration"]["servedTarget"]["availability"] == (
        "insufficient_history"
    )
    assert payload["series"][0]["p95LowerMw"] == 29_200.0
    assert payload["series"][0]["p95UpperMw"] == 32_800.0


def test_rolling_floor_never_exceeds_operational_width_cap(tmp_path):
    finalized_dates = []
    start = date(2024, 1, 4)
    for offset in range(28):
        historical_date = start + timedelta(days=offset)
        _write_operating_day(
            tmp_path,
            historical_date,
            morning_error_mw=8_000.0,
        )
        finalized_dates.append(historical_date)
    _write_state(tmp_path, finalized_dates)

    profile = build_rolling_conformal_floor_profile(
        tmp_path,
        date(2024, 2, 1),
        _config(max_half_width=3_000.0),
    )

    assert profile is not None
    assert profile["floorsMwByTimeBand"]["morning"] == pytest.approx(3_000.0)


def test_profile_reports_pre_scale_and_final_width_caps(tmp_path):
    _history(tmp_path, date(2024, 1, 4), 28)

    profile = build_rolling_conformal_floor_profile(
        tmp_path,
        date(2024, 2, 1),
        _config(max_half_width=3_000.0, width_scale=1.25),
    )

    assert profile is not None
    assert profile["preScaleMaxP95HalfWidthMw"] == 3_000.0
    assert profile["p95HalfWidthScale"] == 1.25
    assert profile["maxP95HalfWidthMw"] == 3_750.0
