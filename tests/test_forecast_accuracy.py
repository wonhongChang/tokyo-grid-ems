"""Tests for python/eval/forecast_accuracy.py."""
from __future__ import annotations

import json
from pathlib import Path

from python.eval.forecast_accuracy import build_forecast_accuracy_report


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_forecast_accuracy_report_compares_model_and_tepco(tmp_path):
    date_iso = "2026-05-11"
    _write_json(tmp_path / "actual" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T00:00:00+09:00",
                "actualMw": 20_000.0,
                "tepcoForecastMw": 20_100.0,
            },
            {
                "ts": f"{date_iso}T01:00:00+09:00",
                "actualMw": 21_000.0,
                "tepcoForecastMw": 21_500.0,
            },
        ],
    })
    _write_json(tmp_path / "forecast" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T00:00:00+09:00",
                "forecastMw": 20_050.0,
            },
            {
                "ts": f"{date_iso}T01:00:00+09:00",
                "forecastMw": 20_700.0,
            },
        ],
    })

    report = build_forecast_accuracy_report(
        tmp_path,
        generated_at="2026-05-11T18:00:00+09:00",
    )

    assert report["summary"]["dates"] == 1
    assert report["summary"]["hours"] == 2
    assert report["summary"]["modelMaeMw"] == 175.0
    assert report["summary"]["tepcoMaeMw"] == 300.0
    assert report["summary"]["modelWins"] == 2
    assert report["daily"][0]["date"] == date_iso
    assert report["hourly"][0]["hour"] == 0


def test_forecast_accuracy_report_skips_incomplete_points(tmp_path):
    date_iso = "2026-05-11"
    _write_json(tmp_path / "actual" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T00:00:00+09:00",
                "actualMw": 20_000.0,
                "tepcoForecastMw": None,
            }
        ],
    })
    _write_json(tmp_path / "forecast" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T00:00:00+09:00",
                "forecastMw": 20_050.0,
            }
        ],
    })

    report = build_forecast_accuracy_report(tmp_path, generated_at="now")

    assert report["summary"]["dates"] == 0
    assert report["summary"]["hours"] == 0
    assert report["summary"]["modelMaeMw"] is None


def test_forecast_accuracy_report_skips_tepco_forecast_fallback_actuals(tmp_path):
    date_iso = "2026-05-11"
    _write_json(tmp_path / "actual" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T23:00:00+09:00",
                "actualMw": 20_000.0,
                "actualSource": "tepco_forecast_fallback",
                "tepcoForecastMw": 20_000.0,
            }
        ],
    })
    _write_json(tmp_path / "forecast" / f"{date_iso}.json", {
        "date": date_iso,
        "series": [
            {
                "ts": f"{date_iso}T23:00:00+09:00",
                "forecastMw": 19_500.0,
            }
        ],
    })

    report = build_forecast_accuracy_report(tmp_path, generated_at="now")

    assert report["summary"]["dates"] == 0
    assert report["summary"]["hours"] == 0
