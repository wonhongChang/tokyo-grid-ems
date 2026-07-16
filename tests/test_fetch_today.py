"""Tests for python/etl/fetch_today.py."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from python.etl.fetch_today import (
    OBSERVED_ACTUAL_SOURCE,
    TEPCO_FORECAST_FALLBACK_SOURCE,
    parse_hourly,
    write_actual_json,
)

JST = ZoneInfo("Asia/Tokyo")


def _csv_text(rows: list[str]) -> str:
    return "\n".join([
        "header block",
        "DATE,TIME,actual,forecast,usage,supply",
        *rows,
        "",
    ])


def test_parse_hourly_marks_observed_rows():
    date_iso, series = parse_hourly(
        _csv_text(["2026/5/12,22:00,3200,3210,80.0,4000"]),
        now=datetime(2026, 5, 12, 22, 40, tzinfo=JST),
    )

    assert date_iso == "2026-05-12"
    assert series[0]["actualMw"] == 32_000.0
    assert series[0]["actualSource"] == OBSERVED_ACTUAL_SOURCE
    assert series[0]["tepcoForecastMw"] == 32_100.0


def test_parse_hourly_uses_tepco_forecast_for_missing_final_hour_at_2340():
    date_iso, series = parse_hourly(
        _csv_text(["2026/5/12,23:00,0,3000,,3900"]),
        now=datetime(2026, 5, 12, 23, 40, tzinfo=JST),
    )

    assert date_iso == "2026-05-12"
    assert series[0]["actualMw"] == 30_000.0
    assert series[0]["actualSource"] == TEPCO_FORECAST_FALLBACK_SOURCE
    assert series[0]["tepcoForecastMw"] == 30_000.0


def test_parse_hourly_waits_before_using_final_hour_fallback():
    _, series = parse_hourly(
        _csv_text(["2026/5/12,23:00,0,3000,,3900"]),
        now=datetime(2026, 5, 12, 23, 10, tzinfo=JST),
    )

    assert series[0]["actualMw"] is None
    assert series[0]["actualSource"] is None


def test_parse_hourly_keeps_non_final_missing_hour_null():
    _, series = parse_hourly(
        _csv_text(["2026/5/12,21:00,0,3100,,3900"]),
        now=datetime(2026, 5, 12, 21, 40, tzinfo=JST),
    )

    assert series[0]["actualMw"] is None
    assert series[0]["actualSource"] is None
    assert series[0]["tepcoForecastMw"] == 31_000.0


def test_write_actual_json_preserves_existing_observed_rows(tmp_path):
    out_dir = tmp_path
    actual_dir = out_dir / "actual"
    actual_dir.mkdir()
    path = actual_dir / "2026-07-16.json"
    path.write_text(json.dumps({
        "date": "2026-07-16",
        "timezone": "Asia/Tokyo",
        "availability": "ok",
        "series": [
            {
                "ts": "2026-07-16T01:00:00+09:00",
                "actualMw": 29_410.0,
                "actualSource": OBSERVED_ACTUAL_SOURCE,
                "tepcoForecastMw": 29_090.0,
                "usagePct": 75.0,
                "supplyMw": 38_950.0,
            },
            {
                "ts": "2026-07-16T02:00:00+09:00",
                "actualMw": None,
                "actualSource": None,
                "tepcoForecastMw": 28_260.0,
                "usagePct": None,
                "supplyMw": 39_100.0,
            },
        ],
    }), encoding="utf-8")

    write_actual_json("2026-07-16", [
        {
            "ts": "2026-07-16T01:00:00+09:00",
            "actualMw": None,
            "actualSource": None,
            "tepcoForecastMw": 29_200.0,
            "usagePct": None,
            "supplyMw": 39_000.0,
        },
        {
            "ts": "2026-07-16T02:00:00+09:00",
            "actualMw": 28_320.0,
            "actualSource": OBSERVED_ACTUAL_SOURCE,
            "tepcoForecastMw": 28_260.0,
            "usagePct": 72.0,
            "supplyMw": 39_100.0,
        },
    ], out_dir)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["series"][0]["actualMw"] == 29_410.0
    assert data["series"][0]["actualSource"] == OBSERVED_ACTUAL_SOURCE
    assert data["series"][0]["usagePct"] == 75.0
    assert data["series"][0]["supplyMw"] == 38_950.0
    assert data["series"][0]["tepcoForecastMw"] == 29_200.0
    assert data["series"][1]["actualMw"] == 28_320.0
