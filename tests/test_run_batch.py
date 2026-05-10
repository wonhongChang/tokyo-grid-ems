"""Tests for python/etl/run_batch.py utility functions."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from python.etl.run_batch import (
    build_actual_json,
    build_alerts_json,
    build_forecast_json,
    compute_missing_days,
    discover_csv_files,
    extract_day_summary,
    load_hourly_cache,
    save_hourly_cache,
)
from python.tepc_parser import TepcoDailyParsed

JST = ZoneInfo("Asia/Tokyo")


# ── build_actual_json ────────────────────────────────────────────────────────

def _make_hourly_df(n: int = 24) -> pd.DataFrame:
    base = pd.Timestamp("2024-01-01", tz=JST)
    rows = [
        {
            "ts": base + pd.Timedelta(hours=h),
            "actual_mw": 30000.0 + h * 100,
            "usage_pct": 85.0,
            "supply_mw": 35000.0,
        }
        for h in range(n)
    ]
    return pd.DataFrame(rows)


def test_build_actual_json_structure():
    result = build_actual_json(date(2024, 1, 1), _make_hourly_df())
    assert result["date"] == "2024-01-01"
    assert result["timezone"] == "Asia/Tokyo"
    assert result["availability"] == "ok"
    assert len(result["series"]) == 24


def test_build_actual_json_series_keys():
    result = build_actual_json(date(2024, 1, 1), _make_hourly_df())
    point = result["series"][0]
    assert set(point.keys()) == {"ts", "actualMw", "tepcoForecastMw", "usagePct", "supplyMw"}


def test_build_actual_json_ts_format():
    result = build_actual_json(date(2024, 1, 1), _make_hourly_df())
    ts = result["series"][0]["ts"]
    assert ts.endswith("+09:00")
    assert ts.startswith("2024-01-01T00:00:00")


def test_build_actual_json_mw_values():
    result = build_actual_json(date(2024, 1, 1), _make_hourly_df())
    assert result["series"][0]["actualMw"] == 30000.0
    assert result["series"][0]["supplyMw"] == 35000.0
    assert result["series"][0]["usagePct"] == 85.0


def test_build_actual_json_nan_becomes_none():
    df = _make_hourly_df()
    df.loc[0, "actual_mw"] = float("nan")
    result = build_actual_json(date(2024, 1, 1), df)
    assert result["series"][0]["actualMw"] is None


def test_build_actual_json_sorted_by_ts():
    df = _make_hourly_df().sample(frac=1, random_state=42)  # shuffle
    result = build_actual_json(date(2024, 1, 1), df)
    ts_list = [p["ts"] for p in result["series"]]
    assert ts_list == sorted(ts_list)


def test_build_actual_json_skips_nat_rows():
    df = _make_hourly_df()
    df.loc[0, "ts"] = pd.NaT
    result = build_actual_json(date(2024, 1, 1), df)
    assert len(result["series"]) == 23


# ── hourly cache ─────────────────────────────────────────────────────────────

def test_save_hourly_cache_prefers_actual_rows_over_virtual_rows(tmp_path):
    ts = pd.Timestamp("2024-01-01T00:00:00+09:00")
    cache = pd.DataFrame([
        {
            "ts": ts,
            "actual_mw": float("nan"),
            "forecast_mw": float("nan"),
            "usage_pct": float("nan"),
            "supply_mw": float("nan"),
            "temp_c": 9.0,
        },
        {
            "ts": ts,
            "actual_mw": 20_000.0,
            "forecast_mw": 19_800.0,
            "usage_pct": 80.0,
            "supply_mw": 25_000.0,
            "temp_c": 8.5,
        },
    ])

    save_hourly_cache(tmp_path, cache)
    result = load_hourly_cache(tmp_path)

    assert len(result) == 1
    assert result["actual_mw"].iloc[0] == pytest.approx(20_000.0)
    assert result["forecast_mw"].iloc[0] == pytest.approx(19_800.0)
    assert result["temp_c"].iloc[0] == pytest.approx(8.5)


# ── build_alerts_json ────────────────────────────────────────────────────────

def test_build_alerts_json_empty_events():
    result = build_alerts_json(date(2024, 1, 1), [])
    assert result["date"] == "2024-01-01"
    assert result["summary"] == {"critical": 0, "warning": 0, "info": 0}
    assert result["events"] == []


def test_build_alerts_json_counts_severity():
    events = [
        {"severity": "critical"},
        {"severity": "warning"},
        {"severity": "warning"},
        {"severity": "info"},
    ]
    result = build_alerts_json(date(2024, 1, 1), events)
    assert result["summary"]["critical"] == 1
    assert result["summary"]["warning"] == 2
    assert result["summary"]["info"] == 1


def test_build_alerts_json_preserves_events():
    events = [{"id": "abc", "severity": "warning", "type": "drift"}]
    result = build_alerts_json(date(2024, 1, 1), events)
    assert result["events"] == events


# ── build_forecast_json ───────────────────────────────────────────────────────

def test_build_forecast_json_not_yet_available_when_empty():
    result = build_forecast_json(date(2024, 1, 1), [], {})
    assert result["availability"] == "not_yet_available"
    assert result["series"] == []


def test_build_forecast_json_ok_when_has_data():
    from python.forecast.baseline import HourlyForecast
    fc = HourlyForecast(
        ts="2024-01-01T00:00:00+09:00",
        forecast_mw=30000.0,
        p95_lower_mw=28000.0, p95_upper_mw=32000.0,
        p99_lower_mw=27000.0, p99_upper_mw=33000.0,
    )
    result = build_forecast_json(date(2024, 1, 1), [fc], {})
    assert result["availability"] == "ok"
    assert len(result["series"]) == 1
    assert result["peak"]["forecastMw"] == 30000.0


# ── compute_missing_days ──────────────────────────────────────────────────────

def test_compute_missing_days_empty():
    assert compute_missing_days(set()) == []


def test_compute_missing_days_no_gaps():
    dates = {date(2024, 1, d) for d in range(1, 6)}  # Jan 1-5
    # Missing days only checked up to yesterday. If all provided days are in the past,
    # result should be empty if no gaps.
    result = compute_missing_days(dates)
    # All days 1-5 covered, no missing days
    assert "2024-01-02" not in result
    assert "2024-01-03" not in result


def test_compute_missing_days_detects_gap():
    dates = {date(2024, 1, 1), date(2024, 1, 3)}  # Jan 2 is missing
    result = compute_missing_days(dates)
    assert "2024-01-02" in result


def test_compute_missing_days_returns_iso_strings():
    dates = {date(2024, 1, 1), date(2024, 1, 3)}
    result = compute_missing_days(dates)
    for d in result:
        assert len(d) == 10 and d[4] == "-" and d[7] == "-"


# ── discover_csv_files ────────────────────────────────────────────────────────

def test_discover_csv_files_finds_files(tmp_path):
    (tmp_path / "20240101_power_usage.csv").touch()
    (tmp_path / "20240102_power_usage.csv").touch()
    (tmp_path / "irrelevant.csv").touch()
    result = discover_csv_files(tmp_path)
    assert date(2024, 1, 1) in result
    assert date(2024, 1, 2) in result
    assert len(result) == 2


def test_discover_csv_files_recursive(tmp_path):
    sub = tmp_path / "2024" / "202401"
    sub.mkdir(parents=True)
    (sub / "20240115_power_usage.csv").touch()
    result = discover_csv_files(tmp_path)
    assert date(2024, 1, 15) in result


def test_discover_csv_files_sorted(tmp_path):
    (tmp_path / "20240103_power_usage.csv").touch()
    (tmp_path / "20240101_power_usage.csv").touch()
    (tmp_path / "20240102_power_usage.csv").touch()
    result = discover_csv_files(tmp_path)
    keys = list(result.keys())
    assert keys == sorted(keys)


def test_discover_csv_files_ignores_invalid_names(tmp_path):
    (tmp_path / "badname_power_usage.csv").touch()
    result = discover_csv_files(tmp_path)
    assert len(result) == 0


# ── extract_day_summary ───────────────────────────────────────────────────────

def test_extract_day_summary_structure():
    hourly = _make_hourly_df()
    parsed = TepcoDailyParsed(
        source_path="fake.csv",
        encoding_used="utf-8",
        updated_at=None,
        summary_blocks={},
        hourly=hourly,
        five_min=pd.DataFrame(),
        quality={},
    )
    result = extract_day_summary(date(2024, 1, 1), parsed)
    assert result["date"] == "2024-01-01"
    assert "peakActualMw" in result
    assert "peakActualAt" in result
    assert "peakUsagePct" in result
    assert "peakSupplyMw" in result


def test_extract_day_summary_peak_is_max():
    hourly = _make_hourly_df()
    parsed = TepcoDailyParsed(
        source_path="fake.csv",
        encoding_used="utf-8",
        updated_at=None,
        summary_blocks={},
        hourly=hourly,
        five_min=pd.DataFrame(),
        quality={},
    )
    result = extract_day_summary(date(2024, 1, 1), parsed)
    # _make_hourly_df: actual_mw = 30000 + h*100, max at h=23 → 32300
    assert result["peakActualMw"] == 32300.0
